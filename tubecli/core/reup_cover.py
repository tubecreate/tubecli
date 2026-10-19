"""Che PHỤ ĐỀ GỐC cháy sẵn trong video — port từ ReupDouyin core/subtitles/region_detect.py
+ pipeline.stage_clean (user 28/9/2026: «cái logic che sub nội suy chưa thấy tích hợp»).

  1. Trích 6 khung rải đều (bỏ 5 % đầu/cuối), gửi từng khung cho Gemini vision (khoá
     trong Cloud API Keys, xoay vòng khi 429) → ô phụ đề [x1,y1,x2,y2] chuẩn hoá 0..1.
  2. Gộp: ngang lấy HỢP (phủ câu dài nhất), dọc lấy TRUNG VỊ, đệm 3 %/1.5 %, dải rộng tối
     thiểu 72 % khung (6 khung mẫu rơi vào câu ngắn thì câu dài vẫn thò hai đầu).
     Thấy chữ ở ≥ 1/3 số khung mới coi là có phụ đề cháy sẵn.
  3. Che: «delogo» = NỘI SUY từ viền (gần như vô hình trên nền phẳng), «blur» mờ
     Gaussian, «pixel» khảm, «fill» tối hẳn — ba kiểu sau NHOÈ MÉP qua mặt nạ gblur.

Khác bản gốc: không encode riêng một lượt che — trả về MẢNH FILTER để reup_dub ghép chung
với bước ghi phụ đề mới vào một lần encode (bớt một lần nén lại video). Phần dò/xoá logo
của bản gốc (tắt mặc định bên đó) không mang sang.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("reup_cover")

COVER_MODES = ("delogo", "blur", "pixel", "fill")
SAMPLE_FRAMES = 6
MIN_BAND_W = 0.72
STRICT_STATIC = 0.7
GEMINI_MODEL = "gemini-2.5-flash"
_KEY_TRIES = 4

# Nguyên văn prompt bên ReupDouyin: một lượt vision trả CẢ phụ đề lẫn logo/watermark.
_DETECT_PROMPT = (
    "You are a video overlay detector. The attached image is ONE frame from a video.\n\n"
    "Find TWO separate kinds of overlay drawn ON TOP of the video:\n\n"
    "1) \"subtitles\" — hardcoded/burned-in CAPTION of spoken dialogue (usually one or "
    "two lines near the bottom). Give a TIGHT box enclosing all lines together.\n\n"
    "2) \"overlays\" — PERMANENT branding in the TOP-LEFT or TOP-RIGHT corner that stays "
    "on screen: channel logo, watermark, username/handle, site name, corner sticker, fixed "
    "label text. Look closely — these are often small and faint. Only report items in "
    "those two top corners. Give a TIGHT box per item and a `kind` among: logo, "
    "watermark, username, text.\n\n"
    "IMPORTANT — do NOT list as \"overlays\": anything that is part of the filmed "
    "scene (signs, shop names, product labels, clothing text, screens in the scene), "
    "moving objects, people, or the dialogue caption itself.\n\n"
    "OUTPUT: ONE JSON object only, no markdown, no explanation. Coordinates are "
    "NORMALIZED floats in [0,1] relative to image width/height, "
    "box = [x1,y1,x2,y2] = [left, top, right, bottom].\n"
    "Example:\n"
    '{"subtitles": [{"text": "字幕内容", "box": [0.12, 0.86, 0.88, 0.95]}], '
    '"overlays": [{"kind": "logo", "text": "bilibili", "box": [0.82, 0.02, 0.98, 0.09]}]}\n'
    'If the frame has neither, return exactly: {"subtitles": [], "overlays": []}'
)


def norm_box(box) -> Optional[List[float]]:
    """[x1,y1,x2,y2] trong 0..1; chịu cả thang 0..1000 (kiểu Gemini hay trả)."""
    try:
        vals = [float(v) for v in list(box)[:4]]
    except (TypeError, ValueError):
        return None
    if len(vals) < 4:
        return None
    if any(v > 1.5 for v in vals):
        vals = [v / 1000.0 for v in vals]
    x1, x2 = sorted((vals[0], vals[2]))
    y1, y2 = sorted((vals[1], vals[3]))
    x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(1.0, x2), min(1.0, y2)
    if x2 - x1 < 0.02 or y2 - y1 < 0.01:
        return None
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def _items(arr) -> List[Dict]:
    out = []
    for it in arr if isinstance(arr, list) else []:
        if isinstance(it, dict):
            b = norm_box(it.get("box") or it.get("bbox") or [])
            if b:
                out.append({"text": str(it.get("text") or "").strip(),
                            "kind": str(it.get("kind") or "").strip().lower(), "box": b})
    return out


def parse_detection(text: str) -> Tuple[List[Dict], List[Dict]]:
    """(phụ đề, logo) từ phản hồi model — chịu cả object {"subtitles","overlays"} lẫn mảng
    trần (coi hết là phụ đề)."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            d = json.loads(m.group())
            if isinstance(d, dict) and ("subtitles" in d or "overlays" in d):
                return _items(d.get("subtitles")), _items(d.get("overlays"))
        except ValueError:
            pass
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if m:
        try:
            return _items(json.loads(m.group())), []
        except ValueError:
            pass
    return [], []


# ── Logo/watermark: 3 CỬA LỌC trước khi xoá (xoá nhầm cảnh vật là phá video) ──────
def _iou(a: List[float], b: List[float]) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def cluster_overlays(per_frame: List[List[Dict]], total: int, min_ratio: float = 0.6,
                     iou_thr: float = 0.4, need: Optional[int] = None) -> List[Dict]:
    """CỬA 1 — BỀN: cùng chỗ ở ≥ 60 % số khung (logo thật khung nào cũng có).
    `need` ghi đè số khung tối thiểu (1 = lấy mọi cụm, để cửa tĩnh chặt quyết)."""
    clusters: List[Dict] = []
    for fi, items in enumerate(per_frame):
        for it in items:
            b = it["box"]
            for c in clusters:
                if _iou(c["box"], b) >= iou_thr:
                    c["frames"].add(fi)
                    # ô đại diện = BAO TRÙM các lần thấy (logo hơi lệch giữa các khung)
                    c["box"] = [min(c["box"][0], b[0]), min(c["box"][1], b[1]),
                                max(c["box"][2], b[2]), max(c["box"][3], b[3])]
                    c["text"] = c["text"] or it.get("text", "")
                    break
            else:
                clusters.append({"box": list(b), "frames": {fi}, "text": it.get("text", ""),
                                 "kind": it.get("kind") or "logo"})
    if need is None:
        need = max(2, int(round(total * min_ratio)))
    return [{"box": [round(v, 4) for v in c["box"]], "seen": len(c["frames"]), "total": total,
             "text": c["text"], "kind": c["kind"]} for c in clusters if len(c["frames"]) >= need]


TOP_BAND = 0.15      # logo chỉ được nằm trong dải 15 % trên cùng (22 % từng ăn cả tiêu đề chương ngay dưới logo)…
CORNER_X = 0.4       # …và lệch hẳn về một góc: tâm ≤ 40 % (trái) hoặc ≥ 60 % (phải)


def filter_by_size(items: List[Dict], max_area: float = 0.12) -> List[Dict]:
    """CỬA 2 — NHỎ & Ở HAI GÓC TRÊN. User 28/9: «chỉ cần kiểm tra logo ở 2 góc trên trái
    phải thôi» — bản gốc nhận mọi rìa (cả đáy, cạnh bên), ở đây chỉ góc trên-trái và
    trên-phải; ô to hay chỗ khác đều coi là cảnh vật, không xoá."""
    out = []
    for it in items:
        b = it["box"]
        if (b[2] - b[0]) * (b[3] - b[1]) > max_area or b[3] > TOP_BAND:
            continue
        cx = (b[0] + b[2]) / 2
        if CORNER_X < cx < 1 - CORNER_X:
            continue
        out.append(it)
    return out


def verify_static(items: List[Dict], frames: List[bytes], ratio_thr: float = 0.95) -> List[Dict]:
    """CỬA 3 — TĨNH: độ biến thiên theo thời gian của ô ≤ 95 % mặt bằng khung. Ngưỡng
    KHÔNG chặt hơn: logo bán trong suốt để nền xuyên qua nên std vẫn 70–85 % mặt bằng."""
    if not items or len(frames) < 3:
        return items
    try:
        import io

        import numpy as np
        from PIL import Image

        arr = np.stack([np.asarray(Image.open(io.BytesIO(f)).convert("L"), dtype=np.float32)
                        for f in frames])
    except Exception as e:      # noqa: BLE001 — thiếu thư viện/khung lệch cỡ: bỏ cửa này
        logger.info("bỏ qua kiểm tĩnh logo: %s", e)
        return items
    std = arr.std(axis=0)
    h, w = std.shape
    overall = float(std.mean()) or 1.0
    out = []
    for it in items:
        x1, y1, x2, y2 = it["box"]
        sl = std[int(y1 * h):max(int(y2 * h), int(y1 * h) + 1), int(x1 * w):max(int(x2 * w), int(x1 * w) + 1)]
        if sl.size and float(sl.mean()) <= overall * ratio_thr:
            out.append({**it, "static_ratio": round(float(sl.mean()) / overall, 3)})
    return out


def pad_logo(b: List[float]) -> List[float]:
    """Ô logo vision trả thường KHÍT sát nét chữ: nội suy đúng ô đó để lại vệt viền chữ
    (đo 28/9: nhãn góc 20 px còn đọc lờ mờ). Nới CỐ ĐỊNH 1.2 % ngang, 1.5 % dọc — nới theo
    tỷ lệ chiều cao ô (40 %) làm ô logo cao lấn xuống nửa dòng tiêu đề chương ngay dưới."""
    return [round(max(0.0, b[0] - 0.012), 4), round(max(0.0, b[1] - 0.015), 4),
            round(min(1.0, b[2] + 0.012), 4), round(min(1.0, b[3] + 0.015), 4)]


def delogo_graph(boxes: List[List[float]], w: int, h: int, inp: str, out: str,
                 enable: str = "") -> str:
    """Nội suy NHIỀU ô trong một chuỗi filter. `enable` = biểu thức timeline ffmpeg (chỉ
    nội suy lúc có chữ); trống = suốt video."""
    parts = []
    for b in boxes:
        px = to_pixels(b, w, h)
        dx, dy = max(1, min(px["x"], w - 3)), max(1, min(px["y"], h - 3))
        dw, dh = max(1, min(px["w"], w - dx - 1)), max(1, min(px["h"], h - dy - 1))
        parts.append(f"delogo=x={dx}:y={dy}:w={dw}:h={dh}" + (f":enable='{enable}'" if enable else ""))
    return f"[{inp}]{','.join(parts)}[{out}]"


def aggregate(boxes: List[List[float]], pad_x: float = 0.03, pad_y: float = 0.015,
              min_w: float = MIN_BAND_W) -> Optional[List[float]]:
    if not boxes:
        return None
    x1 = max(0.0, min(b[0] for b in boxes) - pad_x)
    x2 = min(1.0, max(b[2] for b in boxes) + pad_x)
    y1 = max(0.0, median(b[1] for b in boxes) - pad_y)
    y2 = min(1.0, median(b[3] for b in boxes) + pad_y)
    if x2 - x1 < min_w:
        # chữ căn giữa → nới ĐỐI XỨNG quanh tâm; lệch tâm thì đẩy vào trong khung
        half = min_w / 2.0
        cx = min(max((x1 + x2) / 2.0, half), 1.0 - half)
        x1, x2 = max(0.0, cx - half), min(1.0, cx + half)
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def to_pixels(box: List[float], w: int, h: int) -> Dict[str, int]:
    """Ô 0..1 → pixel CHẴN {x,y,w,h} (ffmpeg cần số chẵn)."""
    x = int(box[0] * w) & ~1
    y = int(box[1] * h) & ~1
    bw = (int((box[2] - box[0]) * w) + 1) & ~1
    bh = (int((box[3] - box[1]) * h) + 1) & ~1
    return {"x": x, "y": y, "w": max(2, min(bw, w - x)), "h": max(2, min(bh, h - y))}


def cover_graph(box: List[float], w: int, h: int, mode: str, inp: str = "0:v",
                out: str = "vc", strength: int = 24, enable: str = "") -> str:
    """Mảnh filter_complex che ô `box` trên luồng [inp] → [out]. `enable` (timeline) chỉ
    che vào những lúc có chữ — gắn vào delogo, hoặc vào overlay với ba kiểu còn lại."""
    px = to_pixels(box, w, h)
    x, y, bw, bh = px["x"], px["y"], px["w"], px["h"]
    if mode == "delogo":
        # delogo đòi ô nằm GỌN trong khung, chừa ≥1px mỗi phía
        return delogo_graph([box], w, h, inp, out, enable=enable)
    en = f":enable='{enable}'" if enable else ""
    # Nới vùng cắt F px mỗi phía cho biên tan; mặt nạ = ô trắng đúng box, gblur → mép nhoè
    F = max(12, min(int(round(bh * 0.5)), 64)) & ~1
    cx, cy = max(0, x - F) & ~1, max(0, y - F) & ~1
    cw, ch = max(2, min(w - cx, bw + 2 * F) & ~1), max(2, min(h - cy, bh + 2 * F) & ~1)
    ox, oy = x - cx, y - cy
    if mode == "blur":
        eff = f"gblur=sigma={max(6, strength)}"
    elif mode == "fill":
        eff = f"gblur=sigma=26,drawbox=0:0:{cw}:{ch}:color=black@0.72:t=fill"
    else:     # pixel (khảm)
        div = max(2, strength // 2)
        eff = f"scale={max(2, cw // div)}:{max(2, ch // div)}:flags=neighbor,scale={cw}:{ch}:flags=neighbor"
    return (
        f"[{inp}]split[cvbase][cvsrc];"
        f"[cvsrc]crop={cw}:{ch}:{cx}:{cy},split[cvreg][cvregm];"
        f"[cvreg]{eff}[cvfg0];"
        f"[cvregm]drawbox=0:0:{cw}:{ch}:color=black:t=fill,"
        f"drawbox={ox}:{oy}:{bw}:{bh}:color=white:t=fill,format=gray,gblur=sigma={max(4, F // 2)}[cvmask];"
        f"[cvfg0][cvmask]alphamerge[cvfg];"
        f"[cvbase][cvfg]overlay={cx}:{cy}{en}[{out}]"
    )


# ── Dò theo PIXEL: ô chữ THẬT của từng khung → các đoạn thời gian có chữ ──────────
# User 19/10/2026: «xoá subtitle không đúng vị trí (thường nằm ở giữa dưới); cập nhật thuật
# toán xoá nội suy chính xác, không cần xoá những chỗ khác». Gemini chỉ nhìn 6 khung nên ô
# gộp thành MỘT DẢI cố định suốt video: rộng ≥72 % khung, lệch sang trái khi vision gộp cả
# nhãn nhỏ ở góc, và nội suy cả lúc KHÔNG có chữ. Ở đây đọc từng khung (4–8 khung/giây)
# trong dải đáy: phụ đề cháy = nét SÁNG kề nét TỐI (chữ trắng/vàng viền đen, hoặc ngược
# lại), xếp thành dòng ngang CĂN GIỮA ở nửa dưới khung. Mỗi đoạn thời gian có chữ nhận
# một ô KHÍT riêng; delogo bật đúng lúc đó (timeline `enable`). Gemini chỉ còn làm MỒI
# chọn dải đáy cần quét (và lùi về cách cũ nếu quét pixel không thấy gì).
SUB_Y_MIN = 0.5          # phụ đề chỉ ở nửa dưới khung
SUB_CENTER_TOL = 0.14    # tâm ngang cách tâm khung ≤ 14 %
SUB_MAX_H = 0.22         # ô cao hơn 22 % khung = không phải phụ đề
PIX_W = 960              # dải đáy co về bề ngang này rồi mới đọc (nét viền còn ≥ 1 px)
PIX_FPS_SHORT, PIX_FPS_LONG, PIX_MAX_FRAMES = 8, 4, 2400
PAD_X, PAD_Y = 0.006, 0.008      # nới ô khít thêm viền/bóng chữ (tỷ lệ khung)
DEFAULT_BAND = (0.70, 0.98)      # không có mồi Gemini: quét 30 % đáy khung


def subtitle_prior(items: List[Dict]) -> List[Dict]:
    """Ô Gemini gọi là «phụ đề» nhưng ở nửa trên, lệch hẳn một bên hay cao bất thường (tiêu
    đề, chữ trong cảnh, nhãn góc) → bỏ. Dung sai ngang rộng hơn cửa pixel: ô vision hay
    gộp thêm nhãn góc nên tâm lệch chút — đây chỉ là mồi chọn dải quét."""
    out = []
    for it in items:
        x1, y1, x2, y2 = it["box"]
        if (y1 + y2) / 2 < SUB_Y_MIN or y2 - y1 > SUB_MAX_H:
            continue
        if abs((x1 + x2) / 2 - 0.5) > SUB_CENTER_TOL + 0.08:
            continue
        out.append(it)
    return out


def _runs(flags) -> List[Tuple[int, int]]:
    """Các đoạn True liên tiếp của mảng bool → [(đầu, cuối+1)]."""
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    return out


def _near(m, k: int, axis: int, sign: int):
    """Có điểm True của `m` trong vòng k bước về MỘT phía (axis 1: sign>0 = bên trái,
    <0 = bên phải; axis 0: sign>0 = phía trên, <0 = phía dưới). Không cuộn vòng qua mép."""
    import numpy as np

    out = np.zeros_like(m)
    for st in range(1, k + 1):
        if axis == 1:
            if sign > 0:
                out[:, st:] |= m[:, :-st]
            else:
                out[:, :-st] |= m[:, st:]
        elif sign > 0:
            out[st:, :] |= m[:-st, :]
        else:
            out[:-st, :] |= m[st:, :]
    return out


STROKE_REACH = 6     # nét chữ dày tối đa ~6 px ở bề ngang PIX_W (CJK 1080p ≈ 2 px, Latin đậm ≈ 3 px)


def text_mask(rgb):
    """Pixel NÉT CHỮ cháy: điểm sáng (kênh lớn nhất ≥165 — bắt cả chữ vàng) mà trong vòng
    STROKE_REACH px có nét tối (≤95) ở CẢ HAI phía (trái–phải hoặc trên–dưới) = nét mảnh
    viền đen; hoặc ngược lại (chữ tối viền sáng ≥185). Mép cảnh vật (chân trời, đá, tóc)
    chỉ tối MỘT phía nên không vào mặt nạ — bản đầu lấy «sáng kề tối» bắt cả mép cảnh,
    dính cụm với chữ làm tâm lệch / mật độ vượt ngưỡng (video mẫu 19/10)."""
    import numpy as np

    v = rgb.max(axis=2)
    bright, dark, vivid = v >= 165, v <= 95, v >= 185
    k = STROKE_REACH
    thin_bright = bright & ((_near(dark, k, 1, 1) & _near(dark, k, 1, -1))
                            | (_near(dark, k, 0, 1) & _near(dark, k, 0, -1)))
    thin_dark = (v <= 75) & ((_near(vivid, k, 1, 1) & _near(vivid, k, 1, -1))
                             | (_near(vivid, k, 0, 1) & _near(vivid, k, 0, -1)))
    return thin_bright | thin_dark


def _mass_span(counts, lo: float = 0.02, hi: float = 0.98) -> Tuple[int, int]:
    """[đầu, cuối+1) chứa phần khối lượng lo..hi của một hồ sơ đếm — vệt lẻ ở rìa không kéo ô."""
    import numpy as np

    cs = np.cumsum(counts)
    tot = float(cs[-1]) if cs.size else 0.0
    if tot <= 0:
        return 0, 0
    a = int(np.searchsorted(cs, lo * tot, side="left"))
    b = int(np.searchsorted(cs, hi * tot, side="right"))
    return a, max(a + 1, min(len(counts), b + 1))


def frame_text_candidates(mask, min_line: int = 6, center_tol: float = SUB_CENTER_TOL) -> List[Dict]:
    """Mọi ứng viên dòng chữ trong mặt nạ một khung dải đáy: [{box, count, density, why}];
    why = "" là qua hết cửa. Hàng-trước-cột: hàng có nét (≥ max(3, 0.5 % bề ngang)) dày
    ≥ min_line px, hai dòng sát gộp một; trong khối hàng gộp cột cách ≤3 % bề ngang; mỗi
    cụm cắt theo khối lượng 2–98 % cả hai chiều rồi qua cửa: cao ≤ 60 % dải, rộng ≥ 0.8
    cao, mật độ nét 3.5–60 %, tâm ngang cách giữa ≤ center_tol."""
    import numpy as np

    H, W = mask.shape
    out: List[Dict] = []
    rows = mask.sum(axis=1)
    rr = [r for r in _runs(rows >= max(3, int(W * 0.005))) if r[1] - r[0] >= min_line]
    bands = []
    for a, b in rr:
        if bands and a - bands[-1][1] <= max(4, int(0.8 * (bands[-1][1] - bands[-1][0]))):
            bands[-1][1] = b
        else:
            bands.append([a, b])
    gap = max(4, int(W * 0.03))
    for y1, y2 in bands:
        sub = mask[y1:y2]
        cols = sub.sum(axis=0)
        # Xương cụm = cột MẠNH (≥3 điểm nét): nét chữ cắt nhiều hàng, còn vạch ngang mảnh của
        # cảnh (lưỡi kiếm, chân trời — cao 1–2 px, dài hàng trăm px, cùng hàng với chữ) chỉ
        # 1–2 điểm/cột nên không nối được vào chữ (video mẫu 19/10 t=3.8 s).
        strong = np.where(cols >= 3, cols, 0)
        idx = np.flatnonzero(strong > 0)
        if idx.size == 0:
            continue
        wide = np.zeros(W, dtype=bool)
        for i in idx:
            wide[max(0, i - gap):i + gap + 1] = True
        for c1, c2 in _runs(wide):
            if int(strong[c1:c2].sum()) < 20:
                continue
            lo, hi = _mass_span(strong[c1:c2])
            x1, x2 = c1 + lo, c1 + hi
            lo2, hi2 = _mass_span(mask[y1:y2, x1:x2].sum(axis=1))
            by1, by2 = y1 + lo2, y1 + hi2
            # nới sang cột YẾU kề bên tối đa 1.2× chiều cao chữ mỗi phía: chữ chỉ có một nét
            # ngang (一) ở đầu/cuối câu không bị cắt, mà vạch cảnh dài không kéo ô đi xa
            ext = max(2, int(1.2 * max(1, by2 - by1)))
            while x1 > 0 and cols[x1 - 1] > 0 and (c1 + lo) - x1 < ext:
                x1 -= 1
            while x2 < W and cols[x2] > 0 and x2 - (c1 + hi) < ext:
                x2 += 1
            bw, bh = x2 - x1, by2 - by1
            cnt = int(mask[by1:by2, x1:x2].sum())
            dens = cnt / float(max(1, bw * bh))
            why = []
            if bh < min_line:
                why.append("thấp")
            if bh > H * 0.6:
                why.append("cao")
            if bw < 0.8 * bh:
                why.append("hẹp")
            if dens < 0.035 or dens > 0.6:
                why.append(f"mật độ {dens:.2f}")
            if abs((x1 + x2) / 2.0 / W - 0.5) > center_tol:
                why.append(f"lệch tâm {abs((x1 + x2) / 2.0 / W - 0.5):.2f}")
            out.append({"box": (int(x1), int(by1), int(x2), int(by2)), "count": cnt,
                        "density": round(dens, 3), "why": ", ".join(why)})
    return out


def frame_text_box(mask, min_line: int = 6, center_tol: float = SUB_CENTER_TOL) -> Optional[Tuple[int, int, int, int]]:
    """Ô khít (x1, y1, x2, y2) pixel của DÒNG PHỤ ĐỀ trong mặt nạ một khung dải đáy, hoặc
    None: ứng viên nhiều nét nhất qua hết cửa (frame_text_candidates), nối thêm cụm cùng
    hàng cách ≤ 8 % bề ngang, cao tương đương (khe giữa các từ)."""
    cands = [c for c in frame_text_candidates(mask, min_line, center_tol) if not c["why"]]
    if not cands:
        return None
    best = max(cands, key=lambda c: c["count"])
    x1, y1, x2, y2 = best["box"]
    W = mask.shape[1]
    for c in frame_text_candidates(mask, min_line, center_tol=1.0):
        bx1, by1, bx2, by2 = c["box"]
        if c["why"] and "lệch tâm" not in c["why"]:
            continue
        if bx2 <= x1 - int(W * 0.08) or bx1 >= x2 + int(W * 0.08) or (bx1 >= x1 and bx2 <= x2):
            continue
        if min(by2, y2) - max(by1, y1) >= 0.5 * (y2 - y1) and 0.5 <= (by2 - by1) / float(y2 - y1) <= 2.0:
            x1, x2 = min(x1, bx1), max(x2, bx2)
            y1, y2 = min(y1, by1), max(y2, by2)
    return (x1, y1, x2, y2)


def build_segments(frames: List[Optional[List[float]]], fps: float, dur: float,
                   min_frames: int = 2, fill_gap: int = 2) -> List[Dict]:
    """Ô (0..1) từng khung (None = không chữ) → [{start, end, box}]. Lấp khe ≤ fill_gap khung
    không thấy giữa hai khung thấy ô chồng nhau (một khung lẫn cảnh sáng vẫn mất nét); bỏ
    vệt ngắn hơn min_frames; ô đoạn = bách phân vị 10/90 của các ô trong đoạn (một khung
    lệch không kéo ô to ra) + nới PAD; mốc nới ±(½ khung + 0.1 s); hai đoạn cách ≤0.25 s
    và chồng ô → gộp."""
    import numpy as np

    boxes = list(frames)
    i = 0
    while i < len(boxes):
        if boxes[i] is None and i > 0 and boxes[i - 1] is not None:
            j = i
            while j < len(boxes) and boxes[j] is None and j - i < fill_gap:
                j += 1
            if j < len(boxes) and boxes[j] is not None and _iou(boxes[i - 1], boxes[j]) >= 0.3:
                a, b = boxes[i - 1], boxes[j]
                fill = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                for k in range(i, j):
                    boxes[k] = fill
            i = max(j, i + 1)
        else:
            i += 1
    segs: List[Dict] = []
    for i0, i1 in _runs([b is not None for b in boxes]):
        if i1 - i0 < min_frames:
            continue
        arr = np.array(boxes[i0:i1], dtype=float)
        x1, y1 = float(np.percentile(arr[:, 0], 10)), float(np.percentile(arr[:, 1], 10))
        x2, y2 = float(np.percentile(arr[:, 2], 90)), float(np.percentile(arr[:, 3], 90))
        box = [round(max(0.0, x1 - PAD_X), 4), round(max(0.0, y1 - PAD_Y), 4),
               round(min(1.0, x2 + PAD_X), 4), round(min(1.0, y2 + PAD_Y), 4)]
        pad_t = 0.5 / fps + 0.1
        end = i1 / fps + pad_t
        seg = {"start": round(max(0.0, i0 / fps - pad_t), 2),
               "end": round(min(dur, end) if dur > 0 else end, 2), "box": box}
        # Gộp CHỈ khi ô gần trùng (IoU ≥ 0.6): câu ngắn kề câu dài mà gộp thì câu ngắn bị che
        # bằng ô của câu dài — mỗi câu một ô khít là mục đích của cả bước này.
        if segs and seg["start"] - segs[-1]["end"] <= 0.25 and _iou(segs[-1]["box"], box) >= 0.6:
            prev = segs[-1]
            prev["end"] = seg["end"]
            prev["box"] = [min(prev["box"][0], box[0]), min(prev["box"][1], box[1]),
                           max(prev["box"][2], box[2]), max(prev["box"][3], box[3])]
        else:
            segs.append(seg)
    return segs


def _enable_expr(times: List[Tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in times)


def place_box(segments: List[Dict]) -> Optional[List[float]]:
    """Ô ĐẠI DIỆN để neo chữ mới (trung vị từng cạnh): tâm đúng chỗ phụ đề gốc hay đứng."""
    if not segments:
        return None
    return [round(median(s["box"][i] for s in segments), 4) for i in range(4)]


def segments_graph(segments: List[Dict], w: int, h: int, mode: str, inp: str = "0:v",
                   out: str = "vc") -> str:
    """Che theo ĐOẠN: delogo gộp các đoạn có ô gần nhau (IoU ≥ 0.8) thành một filter với
    enable = tổng các khoảng; ba kiểu còn lại che ô HỢP của mọi đoạn, bật đúng các khoảng."""
    clusters: List[Dict] = []
    for s in segments:
        for c in clusters:
            if _iou(c["box"], s["box"]) >= 0.8:
                c["box"] = [min(c["box"][0], s["box"][0]), min(c["box"][1], s["box"][1]),
                            max(c["box"][2], s["box"][2]), max(c["box"][3], s["box"][3])]
                c["times"].append((s["start"], s["end"]))
                break
        else:
            clusters.append({"box": list(s["box"]), "times": [(s["start"], s["end"])]})
    if mode == "delogo":
        parts = []
        for c in clusters:
            px = to_pixels(c["box"], w, h)
            dx, dy = max(1, min(px["x"], w - 3)), max(1, min(px["y"], h - 3))
            dw, dh = max(1, min(px["w"], w - dx - 1)), max(1, min(px["h"], h - dy - 1))
            parts.append(f"delogo=x={dx}:y={dy}:w={dw}:h={dh}:enable='{_enable_expr(c['times'])}'")
        return f"[{inp}]{','.join(parts)}[{out}]"
    union = [min(c["box"][0] for c in clusters), min(c["box"][1] for c in clusters),
             max(c["box"][2] for c in clusters), max(c["box"][3] for c in clusters)]
    times = sorted(t for c in clusters for t in c["times"])
    return cover_graph(union, w, h, mode, inp=inp, out=out, enable=_enable_expr(times))


def _scan_band_blocking(ffmpeg: str, video: str, vw: int, vh: int, band: Tuple[float, float],
                        fps: float) -> List[Optional[List[float]]]:
    """Đọc dải đáy [band] của MỌI khung ở `fps` qua pipe rawvideo (không ghi file, không giữ
    khung trong RAM) → ô (0..1 theo khung đầy đủ) từng khung hoặc None."""
    import subprocess

    import numpy as np

    y1, y2 = band
    cy, ch = int(y1 * vh) & ~1, max(16, int((y2 - y1) * vh) & ~1)
    ch = min(ch, vh - cy)
    H = max(16, int(round(ch * PIX_W / float(vw))) & ~1)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", video,
           "-vf", f"fps={fps},crop={vw}:{ch}:0:{cy},scale={PIX_W}:{H}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    n = PIX_W * H * 3
    out: List[Optional[List[float]]] = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            rgb = np.frombuffer(buf, dtype=np.uint8).reshape(H, PIX_W, 3)
            b = frame_text_box(text_mask(rgb))
            if b is None:
                out.append(None)
            else:
                bx1, by1, bx2, by2 = b
                out.append([bx1 / PIX_W, y1 + by1 / H * (y2 - y1), bx2 / PIX_W, y1 + by2 / H * (y2 - y1)])
            if len(out) >= PIX_MAX_FRAMES:
                break
    finally:
        try:
            p.stdout.close()
            p.kill()
        except OSError:
            pass
        p.wait()
    return out


async def scan_subtitle_segments(video: str, ffmpeg: str, vw: int, vh: int, dur: float,
                                 seed: Optional[List[float]] = None) -> Dict:
    """Quét pixel dải đáy → {segments, scanned, hits, band, fps}. Có mồi Gemini thì dải =
    quanh ô mồi (trên 1 ô, dưới 0.6 ô, không lên quá nửa khung); không thì DEFAULT_BAND."""
    if seed:
        sh = max(0.02, seed[3] - seed[1])
        band = (max(SUB_Y_MIN, seed[1] - sh), min(1.0, seed[3] + 0.6 * sh))
    else:
        band = DEFAULT_BAND
    fps = float(PIX_FPS_SHORT if dur <= 120 else PIX_FPS_LONG)
    if dur > 0:
        fps = max(1.0, min(fps, PIX_MAX_FRAMES / dur))
    frames = await asyncio.to_thread(_scan_band_blocking, ffmpeg, video, vw, vh, band, fps)
    segs = build_segments(frames, fps, dur)
    hits = sum(1 for f in frames if f is not None)
    if not seed and segs:
        # Không có mồi: một ô bền suốt video (≥95 % thời lượng) là sticker/nhãn chứ không
        # phải phụ đề (phụ đề đổi câu, có khoảng nghỉ) — bỏ, giữ cách cũ quyết.
        total = sum(s["end"] - s["start"] for s in segs)
        if len(segs) == 1 and dur > 0 and total >= 0.95 * dur:
            segs = []
    return {"segments": segs, "scanned": len(frames), "hits": hits, "band": band, "fps": fps}


def _gemini_keys() -> List[str]:
    try:
        from tubecli.extensions.cloud_api.extension import key_manager

        return [e["key"] for e in (key_manager._keys.get("gemini", {}) or {}).values()
                if isinstance(e, dict) and e.get("active") and e.get("key")]
    except Exception:      # noqa: BLE001
        return []


def _detect_frame_blocking(img: bytes, keys: List[str], start: int) -> Optional[Tuple[List[Dict], List[Dict]]]:
    """Một khung → (phụ đề, logo); None = mọi khoá thử đều hỏng (khác ([], []) = không có gì)."""
    import requests

    b64 = base64.b64encode(img).decode()
    payload = {"contents": [{"parts": [{"text": _DETECT_PROMPT},
                                       {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}],
               "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048}}
    for k in range(min(_KEY_TRIES, len(keys))):
        key = keys[(start + k) % len(keys)]
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/"
                              f"{GEMINI_MODEL}:generateContent?key={key}", json=payload, timeout=90)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue      # 429/403 → khoá sau
        cands = (r.json() or {}).get("candidates") or []
        if not cands:
            return [], []
        text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts") or [])
        return parse_detection(text)
    return None


async def _sample_frames(ffmpeg: str, video: str, dur: float, tmp: Path) -> List[bytes]:
    from tubecli.core.reup_dub import _run_ff

    lo, hi = dur * 0.05, dur * 0.95
    step = (hi - lo) / SAMPLE_FRAMES
    frames: List[bytes] = []
    for i in range(SAMPLE_FRAMES):
        out = tmp / f"f{i:02d}.jpg"
        t = max(0.0, lo + step * (i + 0.5))
        r = await _run_ff([ffmpeg, "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                           "-vf", "scale=720:-2", "-q:v", "3", str(out)], 60)
        if r.returncode == 0 and out.exists():
            frames.append(out.read_bytes())
    return frames


async def detect_subtitle_box(video: str, ffmpeg: str, workdir: Path) -> Dict:
    """{found, box, segments, method, overlays, frames_with_text, total, reason}.

    `segments` = [{start, end, box}] các ĐOẠN có chữ với ô khít riêng (quét pixel — xem
    scan_subtitle_segments); `box` = ô đại diện để neo chữ mới. method 'pixel' = che theo
    đoạn; 'static' = quét pixel không thấy gì nhưng Gemini thấy → một dải cố định như cũ.
    `overlays` = logo/watermark cố định ĐÃ qua 3 cửa lọc ([{box, kind, text, seen, total}]).
    Không bao giờ ném lỗi — dò hỏng thì found=False, overlays=[] và video giữ nguyên, như
    stage_clean bên ReupDouyin."""
    from tubecli.core.reup_dub import media_duration, video_size

    keys = _gemini_keys()
    tmp = workdir / f"cover_{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        dur = await media_duration(video, ffmpeg) or 1.0
        vw, vh = await video_size(video, ffmpeg)
        seed, static_found, overlays, reason = None, False, [], ""
        n_boxes, n_frames = 0, 0
        if keys:
            frames = await _sample_frames(ffmpeg, video, dur, tmp)
            n_frames = len(frames)
            if frames:
                # 6 khung song song, mỗi khung bắt đầu ở một khoá khác → không dồn một khoá
                res = await asyncio.gather(*(asyncio.to_thread(_detect_frame_blocking, f, keys, i)
                                             for i, f in enumerate(frames)))
                answered = [r for r in res if r is not None]
                if not answered:
                    reason = "vision_failed"
                boxes = []
                for subs, _ in answered:
                    # Chỉ ô ĐÚNG CHỖ phụ đề (nửa dưới, gần giữa) mới làm mồi — tiêu đề / nhãn
                    # góc / chữ trong cảnh từng kéo dải che lệch sang trái (video mẫu 19/10).
                    cands = subtitle_prior(subs)
                    best = max(cands, key=lambda d: (d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]),
                               default=None)
                    if best:
                        boxes.append(best["box"])
                n_boxes = len(boxes)
                seed = aggregate(boxes)
                static_found = seed is not None and len(boxes) >= max(1, len(frames) // 3)
                try:
                    ok_frames = [f for f, r in zip(frames, res) if r is not None]
                    n = len(answered)
                    every = filter_by_size(cluster_overlays([o for _, o in answered], n, need=1))
                    strong_need = max(2, int(round(n * 0.6)))
                    # Logo NHỎ thì vision hay sót: đo 28/9 (video 1024×576, chữ góc cao ~20 px) Gemini
                    # chỉ thấy ở 1/6 khung, cửa bền của bản gốc loại sạch. Bằng chứng thay thế = pixel:
                    # ô thấy ít khung phải TĨNH hẳn (≤ 0.7 mặt bằng) — logo đo được 0.20–0.62, cảnh vật
                    # ở góc/rìa 0.96–1.34. Ô thấy đủ khung giữ ngưỡng 0.95 như bản gốc.
                    overlays = (verify_static([o for o in every if o["seen"] >= strong_need], ok_frames)
                                + verify_static([o for o in every if o["seen"] < strong_need], ok_frames,
                                                ratio_thr=STRICT_STATIC))
                    if seed:     # không trùng vùng phụ đề
                        overlays = [o for o in overlays if _iou(o["box"], seed) < 0.3]
                    overlays = [{**o, "box": pad_logo(o["box"])} for o in overlays]
                except Exception as e:      # noqa: BLE001
                    logger.warning("lọc logo lỗi (bỏ qua): %s", e)
                    overlays = []
            else:
                reason = "no_frames"
        else:
            reason = "no_vision_key"

        # Quét pixel: chạy được cả khi không có khoá vision (dải đáy mặc định)
        scan: Dict = {"segments": []}
        if vw and vh:
            try:
                scan = await scan_subtitle_segments(video, ffmpeg, vw, vh, dur,
                                                    seed=seed if static_found else None)
            except Exception as e:      # noqa: BLE001
                logger.warning("quét pixel phụ đề lỗi (bỏ qua): %s", e)
        segs = scan.get("segments") or []
        if segs:
            return {"found": True, "box": place_box(segs), "segments": segs, "method": "pixel",
                    "overlays": overlays, "frames_with_text": n_boxes, "total": n_frames,
                    "scanned": scan.get("scanned"), "hits": scan.get("hits")}
        if static_found:
            return {"found": True, "box": seed, "segments": [], "method": "static",
                    "overlays": overlays, "frames_with_text": n_boxes, "total": n_frames}
        return {"found": False, "box": None, "segments": [], "overlays": overlays,
                "frames_with_text": n_boxes, "total": n_frames, "reason": reason or "no_text"}
    except Exception as e:      # noqa: BLE001
        logger.warning("dò phụ đề gốc lỗi (bỏ qua): %s", e)
        return {"found": False, "overlays": [], "segments": [], "reason": "error"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
