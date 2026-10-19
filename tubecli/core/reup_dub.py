"""Lồng tiếng video từ phụ đề — bản gọn port từ ReupDouyin core/dubbing/srt_dubber.py
(user 28/9/2026: «tích hợp logic lồng tiếng của ReupDouyin»).

Giữ nguyên xương sống 4 bước + các hằng số đã trả giá thật bên đó:
  1. TTS từng câu bằng Edge-TTS, SONG SONG 3 luồng (giãn nhịp 0.15 s trong slot chống
     Microsoft rate-limit), retry có backoff, câu hỏng bỏ qua; ép khớp 4 luồng. Ghép theo
     CHỈ SỐ nên câu sau xong trước cũng không đảo thứ tự.
  2. Ép khớp khung phụ đề: giọng dài hơn khung >2% thì atempo (chuỗi khi hệ số >2,
     trần 2.5x — nhanh hơn nữa khó nghe, chấp nhận tràn).
  3. Ghép track: anullsrc + adelay từng câu + amix normalize=0; quá 50 câu mix theo
     lô 30 (một lệnh amix quá nhiều đầu vào là ffmpeg gãy).
  4. Mux: "replace" thay hẳn âm gốc, "mix" giữ nền gốc hạ xuống bg_volume.
Kèm ghi (burn) phụ đề tuỳ chọn — dựng .ass với PlayRes = đúng khổ video (core/subtitles/
burn.py bên đó): SRT + filter subtitles quy chiếu 288px rồi phóng lên nên chữ khổng lồ.
Các chế độ nặng của bản gốc (duck/tách nhạc Demucs,
co giãn video) không mang sang — skill công khai cần gọn và đoán được.

Không ffprobe cũng chạy: imageio-ffmpeg không kèm ffprobe (bài học lõi .129) — đo thời
lượng bằng ffprobe nếu có, không thì bóc "Duration:" từ stderr của ffmpeg."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("reup_dub")

SAMPLE_RATE = 44100
FIT_TOLERANCE = 1.02
MAX_SPEEDUP = 2.5
BATCH_THRESHOLD = 50
BATCH_SIZE = 30
TTS_CONCURRENCY = 3
FIT_CONCURRENCY = 4

EDGE_VOICES = {
    "vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural",
    "en-US-JennyNeural", "en-US-GuyNeural",
    "ja-JP-NanamiNeural", "zh-CN-XiaoxiaoNeural",
}


def find_ffmpeg() -> Optional[str]:
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        from tubecli.extensions.video_downloader.routes import _get_ffmpeg_path

        return _get_ffmpeg_path()
    except Exception:      # noqa: BLE001
        return None


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        # Lỗi mềm kiểu lệnh `timeout` — đừng giết cả job vì một bước quá hạn.
        return subprocess.CompletedProcess(cmd, 124, "", f"timeout sau {timeout}s")


async def _run_ff(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(_run, cmd, timeout)


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


async def media_duration(path: str, ffmpeg: Optional[str] = None) -> float:
    fp = shutil.which("ffprobe")
    if fp:
        r = await _run_ff([fp, "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=noprint_wrappers=1:nokey=1", path], 60)
        try:
            return float((r.stdout or "").strip())
        except (TypeError, ValueError):
            pass
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        return 0.0
    r = await _run_ff([ff, "-i", path], 60)
    m = _DUR_RE.search((r.stderr or "") + (r.stdout or ""))
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _atempo_chain(factor: float) -> str:
    """atempo chỉ nhận 0.5..2 — hệ số lớn hơn phải xâu chuỗi."""
    parts = []
    while factor > 2.0:
        parts.append("atempo=2.0")
        factor /= 2.0
    parts.append(f"atempo={factor:.4f}")
    return ",".join(parts)


async def _edge_tts(text: str, voice: str, out_mp3: Path) -> bool:
    import edge_tts

    # «No audio was received» là lỗi chập chờn quen của Edge-TTS (đo 28/9 buổi trưa:
    # ~50% lượt dính) — 4 lần, giãn 2/4/6 s như edge_engine.py bên ReupDouyin.
    for attempt in range(4):
        if attempt:
            await asyncio.sleep(2 * attempt)
        try:
            await edge_tts.Communicate(text, voice).save(str(out_mp3))
            if out_mp3.exists() and out_mp3.stat().st_size > 200:
                return True
        except Exception as e:      # noqa: BLE001
            logger.debug("edge-tts lỗi (lần %d): %s", attempt + 1, str(e)[:120])
    return False


# ── CapCut TTS (giọng mặc định của agent, user 28/9/2026) ────────────────────
# capcut_tts là extension EXTERNAL → gọi loopback như dây chuyền content_video. Đọc theo
# ĐỢT (/synthesize/batch: nhiều câu một lượt gọi, audio riêng từng câu) — 76 câu từng
# câu một là 76 lượt mượn tài khoản, dễ chạm nhịp nghỉ của bể.
CAPCUT_BATCH_TEXTS = 40         # trần sidecar là 60; chừa chỗ cho câu dài
CAPCUT_BATCH_CHARS = 3000
_CAPCUT_VOICE_RE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")


def _loopback() -> str:
    from tubecli.config import get_api_port

    return f"http://127.0.0.1:{get_api_port()}"


def _capcut_account() -> str:
    """Email một tài khoản đang bật và không nghỉ trong bể của chủ; "" = không có."""
    import time as _t

    import requests

    try:
        r = requests.get(_loopback() + "/api/v1/capcut-tts/accounts", timeout=10)
        if r.status_code >= 400:
            return ""
        now = _t.time()
        for a in (r.json() or {}).get("accounts") or []:
            if a.get("enabled") and float(a.get("rest_until") or 0) <= now:
                return str(a.get("email") or "")
    except Exception:      # noqa: BLE001
        pass
    return ""


def _capcut_groups(texts: List[str]) -> List[List[int]]:
    groups: List[List[int]] = []
    cur: List[int] = []
    chars = 0
    for i, t in enumerate(texts):
        if cur and (len(cur) >= CAPCUT_BATCH_TEXTS or chars + len(t) > CAPCUT_BATCH_CHARS):
            groups.append(cur)
            cur, chars = [], 0
        cur.append(i)
        chars += len(t)
    if cur:
        groups.append(cur)
    return groups


def _capcut_batch_blocking(email: str, texts: List[str], speaker: str) -> List[bytes]:
    """Một đợt → audio từng câu theo đúng thứ tự (b"" = câu đó không có audio).
    Hỏng cả đợt thì ném lỗi để bên gọi cho cả đợt lùi về Edge."""
    import base64

    import requests

    body: Dict = {"email": email, "texts": texts}
    if speaker:
        body["speaker"] = speaker
    timeout = int(min(900, max(180, 60 + sum(len(t) for t in texts) // 10))) + 30
    r = requests.post(_loopback() + "/api/v1/capcut-tts/synthesize/batch", json=body, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"capcut batch HTTP {r.status_code}: {(r.text or '')[:160]}")
    by = {it.get("index"): it for it in ((r.json() or {}).get("items") or []) if isinstance(it, dict)}
    out: List[bytes] = []
    for i in range(len(texts)):
        it = by.get(i) or {}
        audio = b""
        if it.get("ok"):
            try:
                audio = base64.b64decode(it.get("audio_b64") or "")
            except (ValueError, TypeError):
                audio = b""
        out.append(audio if len(audio) >= 1000 else b"")
    return out


async def _capcut_all(subs: List[Dict], speaker: str, tmp: Path,
                      say: Callable[[str, int, int], None]) -> Dict[int, Path]:
    """{chỉ số câu: mp3} cho mọi câu CapCut đọc được; câu vắng mặt sẽ lùi về Edge."""
    email = await asyncio.to_thread(_capcut_account)
    if not email:
        logger.info("capcut: không có tài khoản rảnh — cả bài lùi về Edge")
        return {}
    texts = [str(s["text"]).strip() for s in subs]
    got: Dict[int, Path] = {}
    done = 0
    for group in _capcut_groups(texts):
        try:
            audios = await asyncio.to_thread(_capcut_batch_blocking, email,
                                             [texts[i] for i in group], speaker)
        except Exception as e:      # noqa: BLE001
            logger.warning("capcut: đợt %d câu hỏng, lùi về Edge: %s", len(group), str(e)[:160])
            audios = [b""] * len(group)
        for i, audio in zip(group, audios):
            if audio:
                p = tmp / f"tts_{i:04d}.mp3"
                p.write_bytes(audio)
                got[i] = p
        done += len(group)
        say("tts", done, len(subs))
    return got


async def _fit_segment(ffmpeg: str, mp3: Path, wav: Path, slot: float) -> bool:
    dur = await media_duration(str(mp3), ffmpeg)
    af = None
    if slot > 0 and dur > slot * FIT_TOLERANCE:
        af = _atempo_chain(min(dur / slot, MAX_SPEEDUP))
    cmd = [ffmpeg, "-y", "-i", str(mp3)]
    if af:
        cmd += ["-filter:a", af]
    cmd += ["-ar", str(SAMPLE_RATE), "-ac", "1", "-sample_fmt", "s16", str(wav)]
    r = await _run_ff(cmd, 120)
    if r.returncode != 0 and af:
        r = await _run_ff([ffmpeg, "-y", "-i", str(mp3), "-ar", str(SAMPLE_RATE),
                           "-ac", "1", "-sample_fmt", "s16", str(wav)], 120)
    return r.returncode == 0 and wav.exists()


async def _mix_chunk(ffmpeg: str, entries: List[tuple], total: float, out_wav: Path) -> bool:
    """entries: [(start_sec, wav_path)] — anullsrc nền + adelay + amix một lệnh."""
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-t", f"{total:.3f}",
           "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono"]
    flt = []
    for i, (start, wav) in enumerate(entries):
        cmd += ["-i", str(wav)]
        ms = max(0, int(start * 1000))
        flt.append(f"[{i + 1}:a]adelay={ms}|{ms}[d{i}]")
    inputs = "[0:a]" + "".join(f"[d{i}]" for i in range(len(entries)))
    flt.append(f"{inputs}amix=inputs={len(entries) + 1}:normalize=0:duration=first[out]")
    cmd += ["-filter_complex", ";".join(flt), "-map", "[out]",
            "-ar", str(SAMPLE_RATE), "-ac", "1", str(out_wav)]
    r = await _run_ff(cmd, int(max(300, total * 2)))
    return r.returncode == 0 and out_wav.exists()


def _srt_time(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(subtitles: List[Dict], path: Path) -> None:
    lines = []
    for i, s in enumerate(subtitles, 1):
        lines += [str(i), f"{_srt_time(float(s['start']))} --> {_srt_time(float(s['end']))}",
                  str(s.get("text") or "").strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


_SIZE_RE = re.compile(r"Video:[^\n]*?\b(\d{2,5})x(\d{2,5})\b")


async def video_size(path: str, ffmpeg: str) -> tuple:
    r = await _run_ff([ffmpeg, "-i", path], 60)
    m = _SIZE_RE.search((r.stderr or "") + (r.stdout or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _ass_time(sec: float) -> str:
    cs = max(0, round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(subs: List[Dict], w: int, h: int, box: Optional[List[float]] = None) -> str:
    """Chữ ~5.5% cạnh ngắn (nhất quán dọc/ngang), lề ngang 5% (ngang 12%), cách đáy 6%,
    tối đa 2 dòng: cue dài tự thu cỡ (sàn 14px) — y hệt ReupDouyin khi không dò box.

    `box` = ô phụ đề GỐC vừa che (0..1): chữ mới LẤP đúng ô đó — cỡ 40 % chiều cao ô
    (kẹp giữa cỡ thường và 8.5 % cạnh ngắn), căn giữa ô theo số dòng ước lượng."""
    S = min(w, h)
    font = max(16, int(round(S * 0.055)))
    if box:
        box_h = min(max(0.02, box[3] - box[1]) * h, h * 0.22)     # chặn ô cao bất thường
        font = max(16, int(round(min(max(box_h * 0.40, S * 0.052), S * 0.085))))
    ml = int(round(w * (0.12 if w > h else 0.05)))
    mv = int(round(h * 0.06))
    outline = max(1, round(font * 0.09))
    shadow = max(0, round(font * 0.04))
    head = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{font},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,"
        f"{outline},{shadow},2,{ml},{ml},{mv},1", "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", "",
    ])
    usable = max(1, w - 2 * ml)
    ev = []
    for s in subs:
        raw = str(s.get("text") or "").strip()
        # «{» mở khối lệnh ASS — chữ người dùng không được thành lệnh định dạng.
        text = raw.replace("{", "(").replace("}", ")").replace("\n", r"\N")
        fs = max(14, min(font, int((2 * usable) / (0.6 * max(1, len(raw))))))
        tags = r"\fs%d" % fs if fs != font else ""
        if box:
            # Neo TÂM khối chữ vào TÂM ô (\an5): libass tự canh dù 1 hay 2 dòng. Bản gốc ước
            # số dòng bằng 0.6×cỡ chữ/ký tự — đo 28/9: câu 55 ký tự bị tưởng 2 dòng, thực tế
            # 1 dòng, nên chữ rơi xuống dưới ô vừa che nửa dòng.
            tags = r"\an5\pos(%d,%d)" % (int(round((box[0] + box[2]) / 2 * w)),
                                        int(round((box[1] + box[3]) / 2 * h))) + tags
        pre = "{" + tags + "}" if tags else ""
        ev.append(f"Dialogue: 0,{_ass_time(float(s['start']))},{_ass_time(float(s['end']))},"
                  f"Default,,{ml},{ml},{mv},,{pre}{text}")
    return head + "\n".join(ev) + "\n"


# ── Tách dòng dài (ReupDouyin core/subtitles/segment.py, bước 3.5 của pipeline) ──
# Gemini hay gom cả đoạn 10–15 s vào MỘT dòng → tường chữ, đọc không kịp, lồng tiếng
# dễ lệch. Cắt tại ranh giới câu rồi mệnh đề, gói mảnh ≤ max_chars, chia lại mốc thời
# gian theo tỷ lệ số ký tự; mảnh cuối kết đúng end gốc.
_BREAKS = "。．！？!?…；;，、,:："
_SEG_RE = re.compile(rf"[^{re.escape(_BREAKS)}]+[{re.escape(_BREAKS)}]?")


def _segments(text: str) -> List[str]:
    return [m.group().strip() for m in _SEG_RE.finditer(text) if m.group().strip()]


def _hard_split(seg: str, max_chars: int) -> List[str]:
    """Mệnh đề dài hơn max_chars: cắt CÂN BẰNG theo từ (hoặc theo ký tự với CJK)."""
    if len(seg) <= max_chars:
        return [seg]
    n = max(2, -(-len(seg) // max_chars))
    target = -(-len(seg) // n)
    if " " in seg:
        out, cur = [], ""
        for w in seg.split(" "):
            if cur and len(cur) + 1 + len(w) > target and len(out) < n - 1:
                out.append(cur)
                cur = w
            else:
                cur = w if not cur else cur + " " + w
        if cur:
            out.append(cur)
        return out
    size = -(-len(seg) // n)
    return [seg[i:i + size] for i in range(0, len(seg), size)] or [seg]


def _pack(text: str, max_chars: int) -> List[str]:
    sep = " " if " " in text.strip() else ""
    units: List[str] = []
    for seg in _segments(text):
        units.extend([seg] if len(seg) <= max_chars else _hard_split(seg, max_chars))
    pieces, cur = [], ""
    for u in units:
        if not cur:
            cur = u
        elif len(cur) + len(sep) + len(u) <= max_chars:
            cur = cur + sep + u
        else:
            pieces.append(cur)
            cur = u
    if cur:
        pieces.append(cur)
    pieces = pieces or [text]
    # mảnh cuối quá ngắn (mồ côi) thì gộp vào mảnh trước nếu không vượt quá nhiều
    if len(pieces) >= 2 and len(pieces[-1]) < max_chars * 0.35:
        merged = pieces[-2] + sep + pieces[-1]
        if len(merged) <= int(max_chars * 1.3):
            pieces = pieces[:-2] + [merged]
    return pieces


def split_long_subtitles(subs: List[Dict], max_chars: int = 56, max_cps: float = 18.0,
                         max_dur: float = 7.0, min_piece_dur: float = 0.6) -> List[Dict]:
    out: List[Dict] = []
    for s in subs:
        text = str(s.get("text") or "").strip()
        try:
            start = float(s.get("start", 0))
            end = float(s.get("end", start))
        except (TypeError, ValueError):
            continue
        dur = end - start
        if not text or dur <= 0 or not (len(text) > max_chars or len(text) / dur > max_cps
                                         or dur > max_dur):
            out.append({**s, "start": start, "end": end, "text": text})
            continue
        pieces = _pack(text, max_chars)
        if len(pieces) <= 1:
            out.append({**s, "start": start, "end": end, "text": text})
            continue
        total_chars = sum(len(p) for p in pieces) or 1
        t, n = start, len(pieces)
        for i, p in enumerate(pieces):
            if i == n - 1:
                seg_end = end
            else:
                seg_end = min(end - min_piece_dur * (n - 1 - i),
                              t + max(min_piece_dur, dur * len(p) / total_chars))
                if seg_end <= t:
                    seg_end = t + min_piece_dur
            out.append({**s, "start": round(t, 3), "end": round(seg_end, 3), "text": p})
            t = seg_end
    return out


def _subtitles_filter_path(p: Path) -> str:
    """Đường dẫn cho filter subtitles trên Windows: \\ -> /, thoát dấu hai chấm ổ đĩa."""
    s = str(p).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{s}'"


async def _finish_video(ffmpeg: str, src: Path, dst: Path, subs: List[Dict], burn: bool,
                        cover_box: Optional[List[float]], cover_mode: str,
                        cover_segments: Optional[List[Dict]], logo_boxes: Optional[List[List[float]]],
                        enc_timeout: int, tmp: Path) -> Dict:
    """Bước cuối: che phụ đề gốc / logo + ghi phụ đề mới trong MỘT lần encode (audio của
    `src` chép nguyên). `cover_segments` (reup_cover.scan_subtitle_segments) = che theo ĐOẠN
    có chữ, ô khít riêng; không có thì che dải `cover_box` suốt video như cũ. `cover_box`
    còn dùng để neo chữ mới đúng chỗ phụ đề gốc. Trả {applied, covered, logos}: applied=False
    = không có gì để làm hoặc encode hỏng (đã ghi log) — người gọi giữ bản vào."""
    from tubecli.core.reup_cover import COVER_MODES, cover_graph, delogo_graph, segments_graph

    nothing = {"applied": False, "covered": False, "logos": 0}
    if not (burn or cover_box or cover_segments or logo_boxes):
        return nothing
    w, h = await video_size(str(src), ffmpeg)
    if not w or not h:
        w, h = 720, 1280
    graph, cur = [], "0:v"
    if logo_boxes:
        # logo/watermark: luôn NỘI SUY (bản gốc cũng vậy), trước lớp che phụ đề
        graph.append(delogo_graph(logo_boxes, w, h, cur, "vlogo"))
        cur = "vlogo"
    if cover_mode in COVER_MODES and (cover_segments or cover_box):
        if cover_segments:
            graph.append(segments_graph(cover_segments, w, h, cover_mode, inp=cur, out="vcov"))
        else:
            graph.append(cover_graph(cover_box, w, h, cover_mode, inp=cur, out="vcov"))
        cur = "vcov"
    if burn and subs:
        ass = tmp / "subs.ass"
        # ô gốc đã che → chữ mới lấp đúng ô; không che thì đặt chỗ mặc định
        ass.write_text(build_ass(subs, w, h, cover_box if cur == "vcov" else None), encoding="utf-8")
        graph.append(f"[{cur}]{_subtitles_filter_path(ass)}[vsub]")
        cur = "vsub"
    if not graph:
        return nothing
    r = await _run_ff([ffmpeg, "-y", "-i", str(src),
                       "-filter_complex", ";".join(graph),
                       "-map", f"[{cur}]", "-map", "0:a?",
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                       "-c:a", "copy", str(dst)], enc_timeout)
    if r.returncode == 0 and dst.exists():
        return {"applied": True, "covered": "vcov" in ";".join(graph), "logos": len(logo_boxes or [])}
    logger.warning("che/ghi phụ đề hỏng: %s", (r.stderr or "")[-300:])
    return nothing


async def render_only(video_path: str, subtitles: List[Dict], output_path: str, burn: bool = False,
                      progress: Optional[Callable[[str, int, int], None]] = None,
                      cover_box: Optional[List[float]] = None, cover_mode: str = "delogo",
                      cover_segments: Optional[List[Dict]] = None,
                      logo_boxes: Optional[List[List[float]]] = None) -> Dict:
    """KHÔNG lồng tiếng (user 19/10/2026: «chỉ subtitle, không cần lồng tiếng»): âm gốc giữ
    nguyên, chỉ che phụ đề gốc / logo + ghi phụ đề mới. Không có gì để làm → chép nguyên
    video. Cùng khuôn trả về với dub_video, engine = "none"."""
    say = progress or (lambda phase, done, total: None)
    subs = [s for s in (subtitles or [])
            if isinstance(s, dict) and str(s.get("text") or "").strip()
            and float(s.get("end", 0)) > float(s.get("start", 0))]
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {"status": "error", "message": "no_ffmpeg"}
    video = Path(video_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / f"rendtmp_{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        dur = await media_duration(str(video), ffmpeg)
        enc_timeout = int(max(900, min(4 * 3600, dur * 3)))
        say("burn", 0, 1)
        dst = tmp / "burned.mp4"
        fin = await _finish_video(ffmpeg, video, dst, subs, burn, cover_box, cover_mode,
                                  cover_segments, logo_boxes, enc_timeout, tmp)
        say("burn", 1, 1)
        if fin["applied"]:
            shutil.move(str(dst), str(out))
        else:
            shutil.copyfile(str(video), str(out))
        return {"status": "success", "output": str(out), "segments": len(subs), "skipped": 0,
                "engine": "none", "capcut_lines": 0, "covered": fin["covered"], "logos": fin["logos"]}
    except Exception as e:      # noqa: BLE001
        logger.warning("render_only lỗi: %s", e, exc_info=True)
        return {"status": "error", "message": f"render_failed: {str(e)[:120]}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def dub_video(video_path: str, subtitles: List[Dict], voice: str,
                    output_path: str, mode: str = "replace", bg_volume: float = 0.15,
                    burn: bool = False,
                    progress: Optional[Callable[[str, int, int], None]] = None,
                    engine: str = "edge", fallback_voice: str = "vi-VN-HoaiMyNeural",
                    cover_box: Optional[List[float]] = None, cover_mode: str = "delogo",
                    logo_boxes: Optional[List[List[float]]] = None,
                    cover_segments: Optional[List[Dict]] = None) -> Dict:
    """Trả {"status": "success", "output", "segments", "skipped", "engine"} hay
    {"status": "error", "message"}.

    engine "capcut": `voice` là mã speaker CapCut ("" = giọng mặc định của CapCut); câu
    nào CapCut không đọc được thì đọc bằng Edge `fallback_voice` — video vẫn đủ tiếng."""
    say = progress or (lambda phase, done, total: None)
    if engine == "capcut":
        if voice and not _CAPCUT_VOICE_RE.match(voice):
            return {"status": "error", "message": "voice_not_allowed"}
        if fallback_voice not in EDGE_VOICES:
            return {"status": "error", "message": "voice_not_allowed"}
    elif voice not in EDGE_VOICES:
        return {"status": "error", "message": "voice_not_allowed"}
    subs = [s for s in (subtitles or [])
            if isinstance(s, dict) and str(s.get("text") or "").strip()
            and float(s.get("end", 0)) > float(s.get("start", 0))]
    if not subs:
        return {"status": "error", "message": "no_subtitles"}
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return {"status": "error", "message": "no_ffmpeg"}

    video = Path(video_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / f"dubtmp_{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        video_dur = await media_duration(str(video), ffmpeg)
        total_dur = max(video_dur, max(float(s["end"]) for s in subs) + 0.5)

        # 1+2. TTS từng câu + ép khớp khung — song song, ghép lại theo chỉ số
        tts_sem = asyncio.Semaphore(TTS_CONCURRENCY)
        fit_sem = asyncio.Semaphore(FIT_CONCURRENCY)
        got: Dict[int, tuple] = {}
        done = 0
        capcut: Dict[int, Path] = {}
        if engine == "capcut":
            capcut = await _capcut_all(subs, voice, tmp, say)
        edge_voice = voice if engine != "capcut" else fallback_voice

        async def _one(i: int, s: Dict, count: bool = True) -> None:
            nonlocal done
            mp3 = tmp / f"tts_{i:04d}.mp3"
            wav = tmp / f"seg_{i:04d}.wav"
            ok = i in capcut
            if not ok:
                async with tts_sem:
                    ok = await _edge_tts(str(s["text"]).strip(), edge_voice, mp3)
                    # giãn nhịp TRONG slot: tốc độ gọi tỉ lệ số luồng, không dồn cục
                    await asyncio.sleep(0.15 if ok else 0.2)
            if ok:
                async with fit_sem:
                    if await _fit_segment(ffmpeg, mp3, wav,
                                          float(s["end"]) - float(s["start"])):
                        got[i] = (float(s["start"]), wav)
            # CapCut đã tự báo tiến độ theo đợt; lượt này chỉ còn ép khớp + vá bằng Edge
            if count and engine != "capcut":
                done += 1
                say("tts", done, len(subs))

        await asyncio.gather(*(_one(i, s) for i, s in enumerate(subs)))
        # Lượt vét: Edge chập chờn theo đợt — câu hỏng cả 4 lần thường đọc được khi cả
        # lượt đã qua. Hỏng quá nhiều = dịch vụ đang sập, vét chỉ tốn thêm thời gian.
        miss = [i for i in range(len(subs)) if i not in got]
        if miss and len(miss) <= max(3, len(subs) // 4):
            for i in miss:
                await _one(i, subs[i], count=False)
        entries: List[tuple] = [got[i] for i in sorted(got)]
        skipped = len(subs) - len(entries)
        if not entries:
            return {"status": "error", "message": "tts_failed"}

        # 3. Ghép track giọng — quá BATCH_THRESHOLD câu thì mix theo lô rồi mix các lô
        say("mix", 0, 1)
        voice_wav = tmp / "voice.wav"
        if len(entries) <= BATCH_THRESHOLD:
            ok = await _mix_chunk(ffmpeg, entries, total_dur, voice_wav)
        else:
            parts = []
            for bi in range(0, len(entries), BATCH_SIZE):
                pw = tmp / f"part_{bi}.wav"
                if not await _mix_chunk(ffmpeg, entries[bi:bi + BATCH_SIZE], total_dur, pw):
                    return {"status": "error", "message": "mix_failed"}
                parts.append(pw)
            ok = await _mix_chunk(ffmpeg, [(0.0, p) for p in parts], total_dur, voice_wav)
        if not ok:
            return {"status": "error", "message": "mix_failed"}
        say("mix", 1, 1)

        # 4. Mux vào video (replace / mix nền gốc)
        say("mux", 0, 1)
        enc_timeout = int(max(900, min(4 * 3600, total_dur * 3)))
        dubbed = tmp / "dubbed.mp4"
        if mode == "mix":
            cmd = [ffmpeg, "-y", "-i", str(video), "-i", str(voice_wav),
                   "-filter_complex",
                   f"[0:a]volume={max(0.0, min(1.0, bg_volume)):.2f}[bg];"
                   f"[bg][1:a]amix=inputs=2:normalize=0:duration=first[out]",
                   "-map", "0:v", "-map", "[out]", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k", "-shortest", str(dubbed)]
            r = await _run_ff(cmd, enc_timeout)
            if r.returncode != 0:
                # video không có audio gốc → lùi về replace
                mode = "replace"
        if mode != "mix" or not dubbed.exists():
            r = await _run_ff([ffmpeg, "-y", "-i", str(video), "-i", str(voice_wav),
                               "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                               "-c:a", "aac", "-b:a", "192k", "-shortest", str(dubbed)],
                              enc_timeout)
            if r.returncode != 0 or not dubbed.exists():
                return {"status": "error", "message": "mux_failed"}
        say("mux", 1, 1)

        # 5. Che phụ đề gốc + ghi phụ đề mới — MỘT lần encode (bản gốc encode hai lần)
        final = dubbed
        fin = {"applied": False, "covered": False, "logos": 0}
        if burn or cover_box or cover_segments or logo_boxes:
            say("burn", 0, 1)
            burned = tmp / "burned.mp4"
            fin = await _finish_video(ffmpeg, dubbed, burned, subs, burn, cover_box, cover_mode,
                                      cover_segments, logo_boxes, enc_timeout, tmp)
            if fin["applied"]:
                final = burned
            # hỏng thì vẫn giao bản đã lồng tiếng — đừng mất trắng cả job
            say("burn", 1, 1)

        shutil.move(str(final), str(out))
        return {"status": "success", "output": str(out),
                "segments": len(entries), "skipped": skipped,
                # Giọng THẬT đã đọc: capcut chỉ khi CapCut đọc được ít nhất một câu
                "engine": "capcut" if capcut else "edge", "capcut_lines": len(capcut),
                "covered": fin["covered"], "logos": fin["logos"]}
    except Exception as e:      # noqa: BLE001
        logger.warning("dub_video lỗi: %s", e, exc_info=True)
        return {"status": "error", "message": f"dub_failed: {str(e)[:120]}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
