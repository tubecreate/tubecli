# Phụ đề của Content Studio: preset → drama metadata → .ass theo từng shot → filter ffmpeg.
# In "SKIP" và exit 0 khi máy không có extension content_studio.
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

EXT = ROOT / "data" / "extensions_external" / "content_studio"
if not (EXT / "engines" / "subtitles.py").exists():
    print(f"SKIP: không có extension content_studio tại {EXT}")
    sys.exit(0)

sys.path.insert(0, str(EXT))
sys.path.insert(0, str(EXT / "engines"))
TMP = tempfile.mkdtemp(prefix="cs_subs_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
from studio_db.json_store import JsonStore  # noqa: E402
JsonStore.get_instance(os.path.join(TMP, "content_studio"))

import subtitles as S  # noqa: E402
import ffmpeg_video_engine as E  # noqa: E402
import studio_routes as R  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


# A. preset file + lookup
presets = S.list_presets()
check("A 16 mẫu", len(presets) == 16, len(presets))
check("A capcut_bold", S.get_preset("capcut_bold")["font"]["size"] == 58)
check("A id lạ → dự phòng", S.get_preset("no_such")["id"] == "capcut_bold")
check("A rỗng → None", S.get_preset("") is None and S.get_preset(None) is None)
ui = S.styles_for_ui()
check("A UI 6 nổi bật + tóm tắt", ui["featured"] == 6 and len(ui["styles"]) == 16
      and ui["styles"][0]["color"]["active"] == "#facc15" and "layout" in ui["styles"][0], ui["styles"][0])
check("A font đóng gói", (S.FONTS_DIR / "BeVietnamPro-Bold.ttf").exists())

# B. ASS helpers
check("B màu BGR", S.ass_color("#facc15") == "&H0015CCFA", S.ass_color("#facc15"))
check("B màu rgba", S.ass_color("rgba(0,0,0,0.28)") == "&H00000000")
check("B thời gian", S.ass_time(3661.256) == "1:01:01.26", S.ass_time(3661.256))
check("B escape", S._escape("a{b}\nc") == "a\\{b\\} c")
check("B đường dẫn Windows một gạch", S.ff_escape_path(r"C:\tmp\a's.ass") == r"C\:/tmp/a\'s.ass", S.ff_escape_path(r"C:\tmp\a's.ass"))
check("B filter có fontsdir", S.subtitles_filter("/x/y.ass").startswith("subtitles='/x/y.ass':fontsdir='"))

# C. hình học: 16:9 và 9:16 cùng cỡ chữ; khổ dọc ít ký tự hơn
p = S.get_preset("capcut_bold")
check("C tỉ lệ cạnh ngắn", S.frame_scale(1920, 1080) == 1.0 and S.frame_scale(1080, 1920) == 1.0 and abs(S.frame_scale(1280, 720) - 0.6667) < 1e-3)
check("C ký tự/dòng", S.chars_per_line(p, 1920, 1080) == 26 and S.chars_per_line(p, 1080, 1920) == 20 and S.chars_per_line(p, 1080, 1080) == 15,
      (S.chars_per_line(p, 1920, 1080), S.chars_per_line(p, 1080, 1920), S.chars_per_line(p, 1080, 1080)))
check("C neo", S.anchor_pos("bottom", 1920) == (5, 960) and S.anchor_pos("left", 1000) == (5, 240))
check("C font theo ngôn ngữ", S.font_of(p, "ja") == "Noto Sans CJK JP" and S.font_of(p, "vi") == "Be Vietnam Pro"
      and S.font_of(S.get_preset("typewriter"), "") in ("Consolas", "DejaVu Sans Mono"))

# D. ước lượng mốc: phủ kín thời lượng, nghỉ ở dấu câu, CJK tách 2 ký tự
w = S.estimate_words("Hôm nay chúng ta nói về ba điều. Điều thứ nhất, rất quan trọng!", 6.0)
check("D số từ", len(w) == 14, len(w))
check("D đầu cuối", w[0]["start"] >= 0.1 and w[-1]["end"] <= 6.0 and w[-1]["end"] > 5.5, (w[0], w[-1]))
gap_after_dot = w[8]["start"] - w[7]["end"]           # sau "điều."
gap_plain = w[2]["start"] - w[1]["end"]
check("D nghỉ sau dấu chấm", gap_after_dot > gap_plain + 0.1, (gap_after_dot, gap_plain))
check("D đơn điệu", all(w[i]["end"] <= w[i + 1]["start"] + 1e-9 for i in range(len(w) - 1)))
check("D rỗng", S.estimate_words("", 3) == [] and S.estimate_words("a b", 0) == [])
check("D CJK", S.split_words("今天我们谈三件事", "zh") == ["今天", "我们", "谈三", "件事"])
check("D bỏ cue", S.split_words("[nhạc nền] Xin chào", "vi") == ["Xin", "chào"])

# E. sidecar: đủ phủ thì dùng mốc thật, thiếu thì ước lượng
mp3 = Path(TMP) / "shot001.mp3"
mp3.write_bytes(b"x")
text = "một hai ba bốn năm sáu bảy tám chín mười"
S.sidecar_path(mp3).write_text(json.dumps({"words": [{"word": t, "start": i * 0.5, "end": i * 0.5 + 0.4}
                                                     for i, t in enumerate(text.split())]}), encoding="utf-8")
words, src = S.words_for_shot(text, mp3, 5.0)
check("E sidecar đủ → tts", src == "tts" and len(words) == 10, (src, len(words)))
S.sidecar_path(mp3).write_text(json.dumps([{"word": "một", "start": 0, "end": 0.4}]), encoding="utf-8")
words, src = S.words_for_shot(text, mp3, 5.0)
check("E sidecar thiếu → ước lượng", src == "estimated" and len(words) == 10, (src, len(words)))
words, src = S.words_for_shot(text, Path(TMP) / "none.mp3", 5.0)
check("E không sidecar → ước lượng", src == "estimated")

# F. build_ass: mỗi từ một Dialogue chứa trọn cụm, chỉ từ đang đọc tô màu; ước lượng thì không tô
w = S.estimate_words("Hôm nay chúng ta nói về ba điều quan trọng", 4.0)
ass = S.build_ass(w, p, 1920, 1080, language="vi", highlight=True)
lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
check("F một Dialogue mỗi từ", len(lines) == 10, len(lines))
check("F tô đúng một từ", lines[2].count("\\c&H0015CCFA}") == 1 and "chúng" in lines[2] and "quan trọng" in lines[2], lines[2])
check("F liền mạch", all(lines[i].split(",")[2] == lines[i + 1].split(",")[1] for i in range(len(lines) - 1)))
check("F style", "Style: Main,Be Vietnam Pro,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6.0,1,5,20,20,20,1" in ass, ass.splitlines()[8])
check("F PlayRes + pos", "PlayResX: 1920" in ass and "\\pos(960,885)" in ass)
ass_est = S.build_ass(w, p, 1080, 1920, highlight=False)
check("F ước lượng không tô", "\\c&H0015CCFA}" not in ass_est and "Style: Main,Be Vietnam Pro,58," in ass_est)
ass_box = S.build_ass(w, S.get_preset("boxed_dark"), 1920, 1080)
check("F hộp nền BorderStyle 3", ",3,0.0,1,5," in ass_box and "&H47000000" in ass_box, [l for l in ass_box.splitlines() if l.startswith("Style")])
ass_up = S.build_ass(w, S.get_preset("big_impact"), 1920, 1080)
check("F IN HOA", "HÔM NAY" in ass_up and ",68," in ass_up)
out = S.write_ass(Path(TMP) / "a.ass", w, p, 1920, 1080)
check("F BOM", out.read_bytes()[:3] == b"\xef\xbb\xbf")

# G. exporter: ảnh → video mang filter subtitles trước fade; không có ass thì như cũ
cmds = []


class _P:
    returncode = 0

    async def communicate(self):
        return b"", b""


async def fake_exec(*cmd, **kw):
    cmds.append(list(cmd))
    return _P()


E.asyncio.create_subprocess_exec = fake_exec
asyncio.run(E._dynamic_image_to_video("img.jpg", 3.0, os.path.join(TMP, "o.mp4"), ass_path=str(out)))
vf = cmds[-1][cmds[-1].index("-vf") + 1]
check("G filter thứ tự", "scale=1920:1080:flags=bicubic,subtitles='" in vf and ",fade=t=out" in vf.split("subtitles=")[1], vf)
check("G fontsdir", ":fontsdir='" in vf)
asyncio.run(E._dynamic_image_to_video("img.jpg", 3.0, os.path.join(TMP, "o.mp4")))
check("G không ass", "subtitles=" not in cmds[-1][cmds[-1].index("-vf") + 1])
rep = {}
shot = {"narration_text": "Xin chào các bạn hôm nay", "id": 1}
got = E.prepare_shot_subtitles(shot, str(mp3), 2.0, p, 1920, 1080, "vi", os.path.join(TMP, "s.ass"), rep)
check("G prepare ước lượng", got and os.path.exists(got) and rep == {"estimated": 1}, rep)
check("G shot không lời", E.prepare_shot_subtitles({"narration_text": "  "}, None, 2.0, p, 1920, 1080, "", os.path.join(TMP, "n.ass"), rep) is None)

# H. build_ffmpeg_video: libass thiếu → bỏ qua và ghi lý do, không hỏng
E._subs.has_libass = lambda ffmpeg="ffmpeg": False
rep = {}
try:
    asyncio.run(E.build_ffmpeg_video({"id": 1}, [], "16:9", None, subtitle_style="capcut_bold", report=rep))
except ValueError as e:
    check("H thiếu libass → bỏ phụ đề", rep.get("skipped") == "ffmpeg has no libass" and "No shots" in str(e), (rep, e))
E._subs.has_libass = lambda ffmpeg="ffmpeg": True

# I. preset → drama metadata, route styles
f = R.preset_drama_fields({"wizStyle": "Anime", "wizSubtitleStyle": "neon_glow"})
check("I preset mang subtitle_style", f["metadata"]["subtitle_style"] == "neon_glow", f["metadata"])
f = R.preset_drama_fields({"wizStyle": "Anime"})
check("I preset cũ không có khoá", "subtitle_style" not in f["metadata"])
f = R.preset_drama_fields({"wizSubtitleStyle": ""})
check("I chọn None → rỗng", f["metadata"]["subtitle_style"] == "")
res = asyncio.run(R.list_subtitle_styles())
check("I route styles", res["success"] and len(res["styles"]) == 16 and res["featured"] == 6)

# J. wizard JS/HTML carry the field
js = (EXT / "static" / "studio2.js").read_text(encoding="utf-8")
html = (EXT / "static" / "studio.html").read_text(encoding="utf-8")
check("J WIZ_FIELD_IDS", "'wizSubtitleStyle'" in js.split("const WIZ_CHECKBOX_IDS")[0])
check("J metadata.subtitle_style", "metadata.subtitle_style = document.getElementById('wizSubtitleStyle')" in js)
check("J select + preview", 'id="wizSubtitleStyle"' in html and 'id="wizSubtitlePreview"' in html)
check("J cache-bust", "studio2.js?v=20260906_subtitles2" in html)
check("J apiFetch parse sẵn", "const data = await apiFetch('/subtitle-styles')" in js and "await r.json()" not in js.split("async function loadSubtitleStyles")[1].split("function renderSubtitlePreview")[0])
check("J manifest", json.loads((EXT / "tubecli-extension.json").read_text(encoding="utf-8"))["version"] >= "2026.09.06")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
