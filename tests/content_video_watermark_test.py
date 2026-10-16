# -*- coding: utf-8 -*-
"""Watermark chữ ký trôi (user 14/10/2026: «chèn thêm watermark dạng chữ ký trôi ngẫu nhiên… chữ màu trắng 'tubecli.app'
ngẫu nhiên hiện trôi ở vài đoạn», «chữ này người dùng có thể tự chỉnh», đặt ở CẢ mẫu lẫn form taskboard).

Cam kết được canh ở đây:
  1. Form Codex: ô cx-v-watermark gửi options.watermark (đã cắt khoảng trắng, ≤ 60 ký tự); trống = không gửi.
  2. Pipeline: options.watermark → metadata.watermark của drama, ĐÈ chữ của mẫu; trống → chữ của mẫu giữ nguyên.
  3. Content Studio: wizWatermark của mẫu → metadata.watermark (preset_drama_fields); engines/watermark: text_of, plan
     (vài lần, né đầu / cuối, cách nhau, tất định theo hạt giống), filter_graph (drawtext trắng, font thường), vị trí ngẫu nhiên rải đều (thay cho bản dò
     chỗ ít nét nhất, nền sáng → viền đậm), apply (sổ phụ chống gắn hai lần, hỏng giữ video).
Không gọi HTTP thật; ffmpeg chỉ chạy ở mục 4 khi máy có (video thử 26 s tự tạo).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label)


class Stop(Exception):
    pass


def drama_meta(options, template_wm="", template_size=""):
    sent = {}

    def fake_post(path, payload, timeout=300):
        if path == "/api/v1/studio/dramas":
            sent.update(payload)
            raise Stop()
        raise AssertionError(f"unexpected POST {path}")
    real_post, real_meta = P._post, P._task_meta
    P._post, P._task_meta = fake_post, (lambda *a, **k: None)
    try:
        meta = {"tts_voice": "vi_female_thuytrang_mb", "tts_engine": "everai"}
        if template_wm:
            meta["watermark"] = template_wm
        if template_size:
            meta["watermark_size"] = template_size
        state = {"agent": SimpleNamespace(id="a1", name="Agent"), "checkpoint": {}, "title": "T", "language": "vi",
                 "preset": {"name": "Ink Wash Film · Kiếm Lai (tiếng Việt)", "fields": {"style": "ink", "metadata": meta}}}
        try:
            P._step_studio(state, dict(P.DEFAULTS, **options))
        except Stop:
            pass
    finally:
        P._post, P._task_meta = real_post, real_meta
    return sent.get("metadata") or {}


print("1. form Codex")
js = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.js").read_text(encoding="utf-8")
html = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.html").read_text(encoding="utf-8")
ok('id="cx-v-watermark"' in html and 'maxlength="60"' in html, "ô cx-v-watermark (≤ 60 ký tự)")
ok("options.watermark = wmText" in js and "if (wmText)" in js, "submitVideo gửi watermark khi có chữ")
for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
    d = json.loads((ROOT / "tubecli" / "extensions" / "codex" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    ok(all(d.get(k) for k in ("codex.field_watermark", "codex.field_watermark_ph", "codex.field_watermark_hint")),
       f"codex locale {lang} đủ 3 khoá")
    # 15/10/2026 «thêm tính năng cho chỉnh size»
    ok(all(d.get(k) for k in ("codex.field_watermark_size", "codex.wm_size_template", "codex.wm_size_small",
                              "codex.wm_size_medium", "codex.wm_size_large", "codex.wm_size_xlarge")),
       f"codex locale {lang} đủ chữ cho ô cỡ chữ")
ok('id="cx-v-watermark-size"' in html and all(f'value="{v}"' in html for v in ("small", "medium", "large", "xlarge")),
   "ô chọn cỡ chữ watermark: theo mẫu / nhỏ / vừa / lớn / rất lớn")
ok("options.watermark_size = wmSize" in js and "if (wmSize)" in js, "submitVideo gửi cỡ chữ khi chọn (trống = theo mẫu)")

print("2. pipeline → drama")
m = drama_meta({"watermark": "  kênh   của tôi  "}, template_wm="tubecli.app")
ok(m.get("watermark") == "kênh của tôi", f"chữ của task đè chữ của mẫu ({m.get('watermark')!r})")
m = drama_meta({}, template_wm="tubecli.app")
ok(m.get("watermark") == "tubecli.app", "trống → chữ của mẫu giữ nguyên")
m = drama_meta({})
ok("watermark" not in m, "mẫu không khai, task không gõ → không có watermark")
ok(P._scene_media_meta({"watermark": "x" * 90}).get("watermark") == "x" * 60, "cắt còn 60 ký tự")
ok(P.DEFAULTS.get("watermark") == "", "mặc định = theo mẫu")
m = drama_meta({"watermark_size": "large"}, template_wm="tubecli.app", template_size="medium")
ok(m.get("watermark_size") == "large" and m.get("watermark") == "tubecli.app", "cỡ của task đè cỡ của mẫu, chữ mẫu giữ")
m = drama_meta({}, template_wm="tubecli.app", template_size="medium")
ok(m.get("watermark_size") == "medium", "không chọn cỡ → cỡ của mẫu")
ok(P._scene_media_meta({"watermark_size": "huge"}) == {} and P.DEFAULTS.get("watermark_size") == "",
   "cỡ lạ bị bỏ (theo mẫu); mặc định = theo mẫu")

print("3. Content Studio")
studio = ROOT / "data" / "extensions_external" / "content_studio"
if not (studio / "engines" / "watermark.py").is_file():
    print("  (bỏ qua — máy này không có Content Studio bản có watermark)")
else:
    sys.path.insert(0, str(studio / "engines"))
    import watermark as W  # noqa: E402
    import numpy as np  # noqa: E402
    ok(os.path.isfile(W.FONT) and os.path.basename(W.FONT) == "BeVietnamPro-Regular.ttf",
       "font TubeCLI có sẵn trong gói, bản Regular nét mảnh (15/10 «font mảnh chữ nhỏ» → «font trên tubecli như bình thường»)")
    # 15/10/2026 «cho watermark font mảnh chữ nhỏ tôi không cần quá to» + «nhỏ thôi mà trôi lâu hơn»
    ok(W.font_size(1920, 1080) <= 26 and W.font_size(1080, 1920) == W.font_size(1920, 1080),
       f"chữ nhỏ (1080p = {W.font_size(1920, 1080)} px, từng 37), video dọc không to hơn video ngang")
    ok(W.SHOW >= 15 and W.GAP > W.SHOW, "mỗi lần trôi ~15 s (từng 7 s), các lần không chồng nhau")
    ok(W.text_of({"watermark": " tubecli.app \n"}) == "tubecli.app" and W.text_of({}) == "" and W.text_of(None) == "",
       "text_of: cắt khoảng trắng; trống = tắt")
    segs = W.plan(382, "767|tubecli.app", 1920, 1080, "tubecli.app")
    ok(2 <= len(segs) <= W.MAX_N, f"video 6:22 → {len(segs)} lần hiện")
    ok(all(W.EDGE <= s["t0"] and s["t1"] <= 382 - W.EDGE for s in segs), "né đầu / cuối video")
    ok(all(b["t0"] - a["t1"] >= W.GAP - W.SHOW - 0.01 for a, b in zip(segs, segs[1:])), "các lần hiện không dồn sát nhau")
    # 15/10/2026: lên 15 s/lần thì bản cũ cho hai chữ CHỒNG nhau (90 s: 27–42 s và 38–53 s) — quét nhiều tập, nhiều độ dài.
    clash = [(d, e) for d in (45, 60, 90, 120, 200, 382, 900) for e in range(40)
             for a, b in zip(W.plan(d, f"{e}|tubecli.app", 1920, 1080, "tubecli.app"),
                             W.plan(d, f"{e}|tubecli.app", 1920, 1080, "tubecli.app")[1:])
             if b["t0"] < a["t1"] + (W.GAP - W.SHOW) - 0.01]
    ok(not clash, f"không bao giờ chồng nhau, lần sau cách lần trước ≥ {W.GAP - W.SHOW:.0f} s (lỗi: {clash[:3]})")
    ok(all(s["t1"] <= d - W.EDGE + 0.01 for d in (45, 90, 382) for s in W.plan(d, "z|tubecli.app")), "lần cuối vẫn né đoạn kết")
    ok(W.plan(382, "767|tubecli.app", 1920, 1080, "tubecli.app") == segs, "tất định theo hạt giống (dựng lại ra y hệt)")
    ok(W.plan(382, "768|tubecli.app", 1920, 1080, "tubecli.app") != segs, "tập khác → chỗ khác")
    ok(W.plan(10, "x") == [] and len(W.plan(25, "x")) == 1, "video quá ngắn → không có / một lần")
    short = W.plan(25, "x")
    ok(short and W.MIN_SHOW <= short[0]["t1"] - short[0]["t0"] < W.SHOW and short[0]["t1"] <= 25 - W.EDGE,
       f"Shorts 25 s: lần hiện rút cho vừa video, vẫn né đầu / cuối {short}")
    g = W.filter_graph("C:/tmp/wm.txt", segs[:2], 1920, 1080)
    ok(g.count("drawtext=") == 2 and "fontcolor=white" in g and "enable='between(t," in g and "textfile='C\\:/tmp/wm.txt'" in g,
       "filter_graph: mỗi lần một drawtext trắng, bật đúng đoạn, đường dẫn thoát dấu «:»")
    # VỊ TRÍ NGẪU NHIÊN (user 14/10/2026 «vì sao ngẫu nhiên nhưng toàn hiện ở trên top?» → «không cần xác định vị trí
    # trống, cứ cho ngẫu nhiên»): rải trên / giữa / dưới, cả quãng trôi nằm trong khung + trên vùng phụ đề
    # + «xuất hiện ngẫu nhiên ở nửa dưới, đừng để ở nửa trên màn hình»: chỉ nửa dưới; có phụ đề thì dừng trên dòng phụ đề
    tw, th = W._text_size("tubecli.app", 1920, 1080)

    def sweep(bottom):
        rows, inside = [], True
        for ep in range(700, 760):
            for s_ in W.plan(382, f"{ep}|tubecli.app", 1920, 1080, "tubecli.app", bottom):
                rows.append(s_["row"])
                xs = (s_["x0"], s_["x0"] + s_["dx"])
                ys = (s_["y0"], s_["y0"] + s_["dy"])
                if (min(xs) < W.LEFT - 1e-6 or max(xs) + tw / 1920 > W.RIGHT + 1e-6 or min(ys) < W.TOP - 1e-6
                        or max(ys) + th * 1.5 / 1080 > bottom + 1e-6):
                    inside = False
        return rows, inside
    rows, inside = sweep(W.BOTTOM)
    share = [rows.count(r) / len(rows) for r in range(3)]
    ok(all(0.2 < x < 0.46 for x in share), f"60 tập: ba dải của nửa dưới gần đều ({[round(x, 2) for x in share]})")
    ok(W.TOP >= 0.5 and inside, "chữ + quãng trôi luôn ở NỬA DƯỚI, trong khung")
    _r, inside_subs = sweep(W.BOTTOM_SUBS)
    ok(inside_subs and W.BOTTOM_SUBS < W.BOTTOM, "video có phụ đề → chữ dừng trên dòng phụ đề")
    src_routes = (studio / "studio_routes.py").read_text(encoding="utf-8")
    ok("bool(subtitle_style)," in src_routes, "xuất video báo cho watermark biết có phụ đề")
    # Cỡ chữ (15/10/2026 «thêm tính năng cho chỉnh size»)
    ok(W.size_of({}) == "small" and W.size_of({"watermark_size": "large"}) == "large"
       and W.size_of({"watermark_size": "huge"}) == "small" and W.size_of({"watermark": {"text": "x", "size": "xlarge"}}) == "xlarge",
       "size_of: không khai / lạ = nhỏ")
    px = [W.font_size(1920, 1080, s) for s in ("small", "medium", "large", "xlarge")]
    ok(px == sorted(px) and len(set(px)) == 4 and px[0] == W.font_size(1920, 1080), f"bốn cỡ tăng dần, nhỏ = mặc định ({px} px)")
    ok(f"fontsize={px[2]}:" in W.filter_graph("t.txt", W.plan(382, "s|x")[:1], 1920, 1080, size="large"),
       "filter_graph vẽ đúng cỡ đã chọn")
    tw_xl, th_xl = W._text_size("tubecli.app", 1920, 1080, size="xlarge")
    big = [s_ for ep in range(30) for s_ in W.plan(382, f"{ep}|tubecli.app", 1920, 1080, "tubecli.app", W.BOTTOM, "xlarge")]
    ok(all(s_["x0"] + max(0, s_["dx"]) + tw_xl / 1920 <= W.RIGHT + 1e-6 and min(s_["x0"], s_["x0"] + s_["dx"]) >= W.LEFT - 1e-6
           for s_ in big), "cỡ rất lớn: chữ + quãng trôi vẫn trong khung")
    ok("_wm.size_of(drama_meta)" in src_routes and 'meta["watermark_size"]' in src_routes
       and 'has("wizWatermarkSize")' in src_routes, "mẫu wizWatermarkSize → metadata.watermark_size → apply(size)")
    s_html = (studio / "static" / "studio.html").read_text(encoding="utf-8")
    s_js = (studio / "static" / "studio2.js").read_text(encoding="utf-8")
    s_tpl = (studio / "static" / "templates.js").read_text(encoding="utf-8")
    ok('id="wizWatermarkSize"' in s_html and "'wizWatermarkSize'" in s_js and "metadata.watermark_size" in s_js
       and "fields: ['wizWatermark', 'wizWatermarkSize']" in s_tpl, "ô cỡ chữ trong wizard + trình sửa mẫu (nhóm Watermark)")
    for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
        d = json.loads((studio / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        ok(d.get("cs.f.watermark_size") and d.get("cs.opt.wm_size_default") and d.get("cs.size.xlarge")
           and "chỗ trống" not in d.get("cs.f.watermark_hint", ""), f"studio locale {lang}: chữ ô cỡ chữ + gợi ý mới")
    one = W.plan(382, "767|tubecli.app", 1920, 1080, "tubecli.app")
    ok(all(a_["row"] != b_["row"] for a_, b_ in zip(one, one[1:])) or len({x["row"] for x in one}) == 3,
       "hai lần liền nhau ít khi cùng dải")
    ok(not hasattr(W, "frame_gray") and not hasattr(W, "place"), "không còn dò chỗ trống trên khung hình")
    g2 = W.filter_graph("t.txt", one[:1], 1920, 1080)
    ok("borderw=1" in g2 and "shadowcolor=black" in g2, "chữ luôn có viền + bóng tối nhẹ, 1 px cho nét mảnh")
    preset = (studio / "studio_routes.py").read_text(encoding="utf-8")
    ok('if has("wizWatermark")' in preset and 'meta["watermark"]' in preset, "preset_drama_fields: wizWatermark → metadata.watermark")
    ok("_wm.apply, export_path" in preset and "_max_sec <= 0" in preset, "xuất video: gắn watermark cho bản thành phẩm")
    s2 = (studio / "static" / "studio2.js").read_text(encoding="utf-8")
    tj = (studio / "static" / "templates.js").read_text(encoding="utf-8")
    sh = (studio / "static" / "studio.html").read_text(encoding="utf-8")
    ok("'wizWatermark'" in s2 and 'id="wizWatermark"' in sh and "fields: ['wizWatermark'" in tj,
       "ô Watermark có trong wizard + trang mẫu + danh sách trường lưu")
    for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
        d = json.loads((studio / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        ok(all(d.get(k) for k in ("cs.f.watermark", "cs.f.watermark_ph", "cs.f.watermark_hint", "cs.ed.g_brand",
                                  "cs.sum.no_watermark")), f"studio locale {lang} đủ 5 khoá")

    print("4. apply trên video thật (26 s)")
    ff = shutil.which("ffmpeg")
    try:
        from ffmpeg_video_engine import _ff  # noqa: E402
        ff = _ff("ffmpeg")
        fp = _ff("ffprobe")
    except Exception:       # noqa: BLE001
        fp = shutil.which("ffprobe")
    tmp = tempfile.mkdtemp(prefix="wm_test_")
    try:
        vid = os.path.join(tmp, "v.mp4")
        r = subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xd8cfb8:s=640x360:r=24:d=26",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=26", "-c:v", "libx264", "-pix_fmt",
                            "yuv420p", "-c:a", "aac", "-shortest", vid], capture_output=True, timeout=120) if ff else None
        if not r or r.returncode:
            print("  (bỏ qua — không có ffmpeg)")
        else:
            res = W.apply(vid, "tubecli.app", "t", ff, fp)
            ok(res.get("ok") and res.get("segments") == 1, f"gắn xong ({res})")
            ok(os.path.isfile(vid + ".wm.json"), "ghi sổ phụ")
            ok(W.apply(vid, "tubecli.app", "t", ff, fp).get("skipped") == "already marked", "gắn lần hai → bỏ qua")
            a = subprocess.run([fp, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                                vid], capture_output=True, text=True).stdout.strip()
            ok(bool(a), "tiếng vẫn còn")
            bad = W.apply(vid + ".nope.mp4", "x", "t", ff, fp)
            ok(not bad.get("ok") and bad.get("skipped") == "no video", "không có video → bỏ qua, không ném")
            ok(W.apply(vid, "", "t", ff, fp).get("skipped") == "no text", "không có chữ → bỏ qua")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
