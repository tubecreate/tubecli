# Máy chỉ có ffmpeg đóng gói (imageio-ffmpeg) thì KHÔNG có ffprobe. Trước 20/9/2026 mọi phép đo thời lượng
# trên những máy ấy trả 0, và bên gọi hiểu nhầm là «file không có giọng»: máy 28 dựng 59 shot đã thu tiếng
# thành 59 ảnh tĩnh 5 giây (video 5 phút thay cho 25 phút), «Subtitles: 0 shot(s)», tiêu đề kết quả không có
# dòng thời lượng. Bộ đo phải đứng được khi CHỈ có ffmpeg.
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data", "extensions_external",
                                "content_studio", "engines"))

from tubecli.extensions.video_studio import ffmpeg_utils as FU  # noqa: E402

FFMPEG = FU.find_ffmpeg()
if not FFMPEG:
    print("SKIP: máy này không có ffmpeg")
    sys.exit(0)

TMP = tempfile.mkdtemp(prefix="ffdur_")
WANT = 3.5
MP3 = os.path.join(TMP, "a.mp3")
MP4 = os.path.join(TMP, "a.mp4")
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", f"sine=frequency=440:duration={WANT}", MP3], check=True)
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", f"color=c=black:s=320x240:d={WANT}", "-pix_fmt", "yuv420p", MP4], check=True)

fails = []
checks = []


def ok(cond, what, got=None):
    print(("  ok   " if cond else "  FAIL ") + what + ("" if cond else f"  → {got!r}"))
    checks.append(what)
    if not cond:
        fails.append(what)


def near(got, want=WANT, tol=0.25):
    return abs(float(got) - want) <= tol


print("── A. lõi: ffmpeg_utils.media_duration ─────────────────────────")
ok(near(FU.media_duration(MP3)), "đo mp3 khi máy có ffprobe", FU.media_duration(MP3))

_real = FU.find_ffprobe
FU.find_ffprobe = lambda: None                      # ── giả lập máy THIẾU ffprobe ──
try:
    ok(near(FU.media_duration(MP3)), "đo mp3 khi máy KHÔNG có ffprobe", FU.media_duration(MP3))
    ok(near(FU.media_duration(MP4)), "đo mp4 khi máy KHÔNG có ffprobe", FU.media_duration(MP4))
    ok(FU.media_duration(os.path.join(TMP, "khong-co.mp3")) == 0.0, "file không có thật → 0.0")
    _realff = FU.find_ffmpeg
    FU.find_ffmpeg = lambda: None                   # không có cả hai → chịu, nhưng không được ném lỗi
    try:
        ok(FU.media_duration(MP3) == 0.0, "không ffprobe lẫn ffmpeg → 0.0, không ném lỗi")
    finally:
        FU.find_ffmpeg = _realff

    print("── B. pipeline content_video ───────────────────────────────────")
    from tubecli.extensions.content_video import pipeline as P
    ok(near(P.media_seconds(MP3)), "media_seconds đo được khi không có ffprobe", P.media_seconds(MP3))
    ok(P.media_seconds("") == 0.0 and P.media_seconds(os.path.join(TMP, "x.mp3")) == 0.0,
       "media_seconds: đường dẫn rỗng / file không có → 0.0")

    print("── C. Content Studio ───────────────────────────────────────────")
    import subtitles as SB
    SB._cache["bin:ffprobe"] = "ffprobe-khong-co-tren-may-nay"
    try:
        ok(near(SB.media_seconds(MP3)), "subtitles.media_seconds đo được khi không có ffprobe",
           SB.media_seconds(MP3))
    finally:
        SB._cache.pop("bin:ffprobe", None)

    import canvas_video_engine as CE
    ok(near(CE.probe_seconds(MP3)), "canvas: probe_seconds không gọi \"ffprobe\" trần nữa",
       CE.probe_seconds(MP3))

    print("── D. đo không ra thì phải KÊU, không im ───────────────────────")
    line = P.subtitles_line({"style": "capcut_bold", "name": "CapCut Bold", "shots": 0,
                             "audio_unreadable": 59})
    ok("59" in line and "unmeasurable" in line, "dòng Subtitles nói ra 59 shot đo không được", line)
    ok("audio_unreadable" not in P.subtitles_line({"style": "x", "name": "X", "shots": 12, "tts": 12}),
       "lượt bình thường thì dòng Subtitles không mọc thêm chữ lạ")
finally:
    FU.find_ffprobe = _real

print()
print(("ALL %d CHECKS PASSED" % len(checks)) if not fails else ("%d FAILED: %s" % (len(fails), fails)))
sys.exit(1 if fails else 0)
