# -*- coding: utf-8 -*-
"""Bảng XEM TRƯỚC của form «Tạo video từ nội dung» (content_video/preview.py, 14/11/2026).

User: «thêm button xem trước … bảng review … template, AI tạo content, AI tạo ảnh, AI tạo voice, thêm load 1 lần check AI
có hoạt động hay không, rồi phương thức tạo, dạng ảnh video, kiểu dùng voice gốc … có tạo thumbnail hay không».
Mọi thứ ngoài (Studio, agent, model, Muse, bộ vẽ ảnh, giọng) đều GIẢ — không gọi dịch vụ thật. Kiểm:
  A. build_preview: đủ dòng, đúng giá trị (mẫu, AI viết, Muse / bộ vẽ, file giọng + mốc .srt, nguyên văn, ảnh tĩnh / clip,
     thumbnail, duyệt, YouTube); mẫu sai tên / agent mất → dòng báo đỏ, ok=False; không ghi file mốc.
  B. run_checks: AI viết gọi thử (ok / lỗi), Muse (tài khoản hỏng / đăng xuất), giọng (lỗi bước giọng), Studio; mục quá hạn
     → «no answer within», không treo.
  C. route /preview + /preview/check có mặt, chặn khách.
Chạy: python tests/content_video_preview_test.py   (exit 0 = pass)
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.config as CFG  # noqa: E402

from pathlib import Path  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cv_preview_test_")
CFG.DATA_DIR = Path(TMP)

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.extensions.content_video import preview as PV  # noqa: E402
from tubecli.extensions.content_video import narration_dub as ND  # noqa: E402

PASS = FAIL = 0


def ok(cond, name, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", name)
    else:
        FAIL += 1
        print("  FAIL", name, "->", str(info)[:300])


# ── đồ giả ───────────────────────────────────────────────────────────────────────────────────────────────────────────
class Agent:
    id = "a1"
    name = "chuyên gia it"
    model = "ag/gemini-3.8-flash"
    content_video_preset = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model, "provider": "9router"}


AGENTS = {"a1": Agent()}
PRESETS = {
    "Cartoon News Recap": {"language": "zh-TW", "metadata": {
        "muse_only": True, "aspect_ratio": "16:9", "video_length": "long_10m", "tts_engine": "edge",
        "tts_voice": "zh-TW-YunJheNeural", "clip_mode": "", "clip_max": 0, "subtitle_style": "capcut_bold",
        "subtitle_size": "medium", "cast": ["shen_boyang"], "cast_library": "auto",
        "content_dna": "talk-show-news-recap-zh-tw"}},
    "Stick Figures": {"language": "vi", "metadata": {
        "aspect_ratio": "9:16", "tts_engine": "capcut", "tts_voice": "BV075_streaming", "clip_mode": "important",
        "clip_max": 4, "hook_video": "muse", "image_models": {"hook": "gpt-image-2"}}},
}


def fake_load_preset(name):
    if name not in PRESETS:
        raise RuntimeError(f"Template {name!r} not found. Saved templates: {', '.join(PRESETS)}")
    return dict(PRESETS[name])


import tubecli.core.agent as _agent_mod  # noqa: E402

_agent_mod.agent_manager.get = lambda aid: AGENTS.get(aid)
P._load_preset = fake_load_preset
P._agent_image_default = lambda state: ("", "")
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
import tubecli.core.image_gen as IG  # noqa: E402

IG.resolve_provider = lambda p=None, m=None, _chain=True: {"ok": True, "provider": "cloudflare", "model": "flux-1-schnell"}

SRT = "\n".join(f"{i}\n00:00:{i * 2:02d},000 --> 00:00:{i * 2 + 1:02d},500\n第{i}句話很重要\n" for i in range(1, 8))
up = os.path.join(TMP, "content_video", "voice_uploads")
os.makedirs(up, exist_ok=True)
voice = os.path.join(up, "abc.mp3")
open(voice, "wb").write(b"ID3")
P.media_seconds = lambda path: 16.0


def rows_of(r):
    return {x["key"]: x for x in r["rows"]}


# ── A. build_preview ────────────────────────────────────────────────────────────────────────────────────────────────
r = PV.build_preview("a1", SRT, {"preset": "Cartoon News Recap", "voice_file": voice, "thumbnail": True,
                                 "thumbnail_engine": "image", "thumbnail_style": "bold red title"},
                     review=True, voice_name="宜蘭選情.mp3")
R = rows_of(r)
ok(r["ok"], "preview ok", r)
ok([x["key"] for x in r["rows"]][:7] == ["template", "content_ai", "image_ai", "voice", "source", "script", "media"],
   "rows in the order the user listed them", [x["key"] for x in r["rows"]])
ok(R["template"]["value"] == "Cartoon News Recap" and "Chinese (Traditional)" in R["template"]["detail"]
   and "16:9" in R["template"]["detail"] and "~10 min" in R["template"]["detail"], "template + language/frame/length",
   R["template"])
ok(R["content_ai"]["value"] == "ag/gemini-3.8-flash" and "chuyên gia it" in R["content_ai"]["detail"]
   and "9router" in R["content_ai"]["detail"], "content AI = the agent's model", R["content_ai"])
ok("describes every scene" in R["content_ai"]["detail"], "word for word → the AI only describes the scenes",
   R["content_ai"]["detail"])
ok(R["image_ai"]["value"] == "Muse" and "shared character library" in R["image_ai"]["detail"],
   "muse_only template → Muse; cast library noted", R["image_ai"])
ok("宜蘭選情.mp3" in R["voice"]["value"] and "00:16" in R["voice"]["value"]
   and "by the times in your subtitles (7 lines)" in R["voice"]["detail"], "voice file cut by the subtitles' times",
   R["voice"])
ok(R["source"]["value"].startswith("Subtitles (.srt / .vtt) · 7 lines"), "source = subtitles", R["source"])
ok(R["script"]["value"] == "Word for word" and "as long as your voice file (00:16)" in R["script"]["detail"],
   "voice file → word for word, length = the file", R["script"])
ok(R["media"]["value"] == "Images + video clips" and "16:9" in R["media"]["detail"], "template clips", R["media"])
ok(R["thumbnail"]["value"] == "Drawn with the image AI" and "bold red title" in R["thumbnail"]["detail"], "thumbnail on")
ok(R["review"]["value"].startswith("Stop at the script"), "review stop")
ok(R["publish"]["value"] == "Off" and R["drive"]["value"] == "Off", "publish / Drive off")
ok(R["cast"]["value"] == "shen_boyang" and R["subtitles"]["value"] == "Capcut Bold", "cast + subtitles from the template")
ok(not os.path.exists(voice + ".cues.json"), "preview writes no subtitle-times file")
ok(r["steps"] and all("will_run" in s for s in r["steps"]), "steps listed", r["steps"][:2])

ND.whisper_installed = lambda: False
r2 = PV.build_preview("a1", "一段普通的文字。很長的內容。", {"preset": "Cartoon News Recap", "voice_file": voice}, True)
ok("installs itself the first time" in rows_of(r2)["voice"]["detail"], "no subtitles, no Whisper → says it installs",
   rows_of(r2)["voice"])
far = "\n".join(f"{i}\n00:0{i}:00,000 --> 00:0{i}:05,000\n第{i}句\n" for i in range(1, 6))
r3 = PV.build_preview("a1", far, {"preset": "Cartoon News Recap", "voice_file": voice}, True)
ok(any("may not belong together" in w for w in r3["warnings"]), "subtitles longer than the file → warning", r3["warnings"])

r4 = PV.build_preview("a1", "Bài viết về kinh tế.", {
    "preset": "Stick Figures", "script_mode": "rewrite", "length_mode": "minutes", "target_words": 1500,
    "scene_media": "", "publish": True, "publish_method": "api", "publish_channel_name": "Kênh A",
    "publish_privacy": "public", "publish_when": "now", "instructions": "Giọng vui"}, review=False)
R4 = rows_of(r4)
ok(R4["image_ai"]["value"] == "cloudflare · flux-1-schnell" and "hook: gpt-image-2" in R4["image_ai"]["detail"],
   "not muse_only → machine image settings + per-role models", R4["image_ai"])
ok(R4["voice"]["value"] == "CapCut · BV075_streaming" and "template's voice" in R4["voice"]["detail"],
   "template voice", R4["voice"])
ok(R4["script"]["value"] == "Rewritten by the AI" and "~10 min" in R4["script"]["detail"]
   and "Giọng vui" in R4["script"]["detail"], "rewrite + minutes + instructions", R4["script"])
ok(R4["media"]["value"].startswith("Moving stills + clips for key scenes") and "at most 4" in R4["media"]["detail"]
   and "opening clip (muse)" in R4["media"]["detail"], "key-scene clips, cap, opening clip", R4["media"])
ok(R4["thumbnail"]["value"] == "Prompt only", "thumbnail off → prompt only")
ok(R4["review"]["value"] == "Runs straight to the video", "no review stop")
ok(R4["publish"]["value"] == "YouTube" and "Kênh A" in R4["publish"]["detail"] and "YouTube API" in R4["publish"]["detail"],
   "YouTube line", R4["publish"])
r5 = PV.build_preview("a1", "x", {"preset": "Cartoon News Recap", "scene_media": "stills"}, True)
ok(rows_of(r5)["media"]["value"] == "Still images only", "stills chosen in the form")

# Lõi < .236 (không có whisper_installed / subtitle_cues): bảng vẫn mở — Whisper tự dò bằng find_spec
_wi = ND.whisper_installed
del ND.whisper_installed
old = PV.build_preview("a1", "一段普通的文字。", {"preset": "Cartoon News Recap", "voice_file": voice}, True)
ok(old["ok"] and "Whisper" in rows_of(old)["voice"]["detail"], "older core without whisper_installed → still works",
   rows_of(old)["voice"])
ND.whisper_installed = _wi
_pv_src = open(PV.__file__, encoding="utf-8").read()
ok('P.subtitle_cues(content) if hasattr(P, "subtitle_cues") else []' in _pv_src,
   "older core without subtitle_cues → subtitles read as plain text")

bad = PV.build_preview("a1", "x", {"preset": "Nope"}, True)
ok(not bad["ok"] and rows_of(bad)["template"]["tone"] == "bad" and "not found" in rows_of(bad)["template"]["detail"],
   "unknown template → red row, ok=False", rows_of(bad)["template"])
gone = PV.build_preview("zz", "x", {"preset": "Cartoon News Recap"}, True)
ok(not gone["ok"] and rows_of(gone)["content_ai"]["tone"] == "bad", "missing agent → red row")

# ── B. run_checks ───────────────────────────────────────────────────────────────────────────────────────────────────
import tubecli.api.ai_routes as AR  # noqa: E402
import tubecli.core.muse as MU  # noqa: E402
import tubecli.extensions.content_video.capabilities as CAP  # noqa: E402

probe_calls = []
AR.run_probe = lambda model, provider="": probe_calls.append((model, provider)) or {"ok": True, "seconds": 1.4,
                                                                                   "reply": "OK"}
MU.status = lambda quick=False: {"configured": True, "remote_seats": 0, "busy": False,
                                 "pool": [{"profile": "m1", "down": False, "signed_out": False},
                                          {"profile": "m2", "down": True, "signed_out": False}]}
CAP.studio_capabilities = lambda timeout=20: {"assembly": {"ok": True}}
P._tts_engine = lambda state, options: "capcut" if not state.update(capcut_email="cap@x.com") else ""

c = PV.run_checks("a1", SRT, {"preset": "Cartoon News Recap", "voice_file": voice})
C = {x["key"]: x for x in c["checks"]}
ok([x["key"] for x in c["checks"]] == ["content_ai", "image_ai", "voice", "studio"], "four checks in order")
ok(C["content_ai"]["status"] == "ok" and "1.4 s" in C["content_ai"]["detail"]
   and probe_calls == [("ag/gemini-3.8-flash", "9router")], "content AI really called once with its provider",
   (C["content_ai"], probe_calls))
ok(C["image_ai"]["status"] == "ok" and "1 account(s)" in C["image_ai"]["detail"] and "not test-drawn" in C["image_ai"]["detail"],
   "Muse: usable accounts counted, nothing drawn", C["image_ai"])
ok(C["voice"]["status"] == "ok" and "CapCut" in C["voice"]["detail"] and "subtitles' times" in C["voice"]["detail"],
   "voice: temporary CapCut + subtitle times", C["voice"])
ok(C["studio"]["status"] == "ok" and c["ok"], "studio ok → all ok", C["studio"])

AR.run_probe = lambda model, provider="": {"ok": False, "seconds": 0.3, "message": "[9Router Error] 403 quota"}
MU.status = lambda quick=False: {"configured": True, "remote_seats": 0,
                                 "pool": [{"profile": "m1", "signed_out": True}]}


def no_voice(state, options):
    raise RuntimeError("tts_engine=capcut but the CapCut TTS extension is not installed/enabled.")


P._tts_engine = no_voice
CAP.studio_capabilities = lambda timeout=20: {"assembly": {"ok": False, "label": "Video assembly", "detail": "no ffmpeg",
                                                           "fix": "install ffmpeg"}}
c2 = PV.run_checks("a1", "文字", {"preset": "Stick Figures"})
C2 = {x["key"]: x for x in c2["checks"]}
ok(not c2["ok"] and C2["content_ai"]["status"] == "fail" and "403 quota" in C2["content_ai"]["detail"],
   "model error is shown as it came", C2["content_ai"])
ok(C2["image_ai"]["status"] == "ok", "not muse_only → the machine's image provider, not Muse", C2["image_ai"])
ok(C2["voice"]["status"] == "fail" and "not installed" in C2["voice"]["detail"], "voice error from the voice step",
   C2["voice"])
ok(C2["studio"]["status"] == "fail" and "ffmpeg" in C2["studio"]["detail"], "assembly not ready", C2["studio"])
c3 = PV.run_checks("a1", "文字", {"preset": "Cartoon News Recap"})
ok({x["key"]: x for x in c3["checks"]}["image_ai"]["status"] == "fail"
   and "signed out" in {x["key"]: x for x in c3["checks"]}["image_ai"]["detail"], "Muse signed out → fail")

AR.run_probe = lambda model, provider="": time.sleep(3) or {"ok": True, "seconds": 3}
t0 = time.time()
c4 = PV.run_checks("a1", "文字", {"preset": "Stick Figures"}, timeout=0.5)
ok(time.time() - t0 < 2.5 and {x["key"]: x for x in c4["checks"]}["content_ai"]["status"] == "warn"
   and "no answer within" in {x["key"]: x for x in c4["checks"]}["content_ai"]["detail"],
   "a slow check does not hold the table", (time.time() - t0, c4["checks"][0]))

# ── C. routes ───────────────────────────────────────────────────────────────────────────────────────────────────────
src = open(os.path.join(ROOT, "tubecli", "extensions", "content_video", "routes.py"), encoding="utf-8").read()
ok('@router.post("/preview")' in src and '@router.post("/preview/check")' in src, "routes exist")
seg = src[src.index('@router.post("/preview")'):src.index("# ── File giọng của người dùng")]
ok(seg.count("_deny_guests(request)") == 2, "guests are refused on both routes")
ok("create_auto_task" not in seg and "create_plan_task" not in seg, "preview never creates a task")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
