# -*- coding: utf-8 -*-
"""File giọng + bài dán dạng PHỤ ĐỀ (.srt/.vtt) và tự cài Whisper (14/11/2026).

Task #155 (máy khác, lõi .231): bài dán là .srt của chính file giọng 33′, máy KHÔNG có faster_whisper → bước dub đoán chỗ cắt
theo giọng tạm CapCut (lệch thật 10–65 s) → «no clear pause…» → video giữ giọng CapCut 44′. User: «nếu người dùng nhập dạng
srt thì ko cần phải dò lại», «bạn update bản tự động cài đi». Kiểm:
  A. subtitle_cues / save_voice_cues / load_voice_cues: mốc phụ đề ghi cạnh file giọng (<file>.cues.json).
  B. cue_chars: mốc từng chữ từ phụ đề; câu kéo dài qua đoạn không lời → lời dồn về cuối; phụ đề không thuộc file → None.
  C. split_by_paragraph(cues=…): cắt theo mốc phụ đề, KHÔNG gọi Whisper / không cài gì; mốc chữ cho phụ đề video.
  D. phụ đề không khớp file → sang Whisper (tự cài); cài hỏng → lý do nằm trong lỗi.
  E. ensure_whisper: cài một lần, hỏng thì 6 giờ sau mới thử lại.
  F. _step_dub: đọc mốc cạnh file giọng, truyền cues + install_whisper; dòng báo nói cắt theo phụ đề.
Cần ffmpeg trong PATH (dựng file tiếng thử). Chạy: python tests/voice_file_subtitle_cues_test.py   (exit 0 = pass)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.config as CFG  # noqa: E402

TMP = tempfile.mkdtemp(prefix="voice_cues_test_")
CFG.DATA_DIR = TMP

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
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


FF = shutil.which("ffmpeg") or "ffmpeg"


def speech(path, spans, total):
    """Tiếng «nói» (sin 440 Hz) trong các khoảng spans, lặng ở giữa."""
    expr = "+".join(f"between(t,{a},{b})" for a, b in spans)
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='if({expr},0.5*sin(2*PI*440*t),0)':s=16000:d={total}", "-ac", "1", path], check=True)
    return path


SRT = """1
00:00:00,000 --> 00:00:02,000
第一句話

2
00:00:03,000 --> 00:00:06,000
第二句話很長

3
00:00:07,000 --> 00:00:09,000
第三句
"""

# ── A. mốc phụ đề cạnh file giọng ───────────────────────────────────────────────────────────────────────────────────
cues = P.subtitle_cues(SRT)
ok(cues == [(0.0, 2.0, "第一句話"), (3.0, 6.0, "第二句話很長"), (7.0, 9.0, "第三句")], "subtitle_cues reads every line", cues)
ok(P.subtitle_cues("一段普通的文字。\n第二行。") == [], "plain text has no cues")
ok(P.subtitle_to_text(SRT) == "第一句話。\n\n第二句話很長。\n\n第三句。", "subtitle_to_text unchanged",
   P.subtitle_to_text(SRT))

up = os.path.join(TMP, "content_video", "voice_uploads")
os.makedirs(up, exist_ok=True)
voice = speech(os.path.join(up, "v1.wav"), [(0.05, 2.0), (3.0, 6.0), (7.0, 8.95)], 9)
opts = {**P.DEFAULTS, "voice_file": voice, "source_text": P.subtitle_to_text(SRT)}
P.apply_voice_file(opts)
n = P.save_voice_cues(opts, SRT)
side = P.voice_cues_path(opts["voice_file"])
ok(n == 3 and os.path.isfile(side) and side.endswith("v1.wav.cues.json"), "save_voice_cues writes <file>.cues.json", side)
ok(P.load_voice_cues(opts["voice_file"]) == [[0.0, 2.0, "第一句話"], [3.0, 6.0, "第二句話很長"], [7.0, 9.0, "第三句"]],
   "load_voice_cues reads them back")
ok(P.save_voice_cues(opts, "普通文字") == 0, "plain text → nothing saved")
ok(P.save_voice_cues({**P.DEFAULTS}, SRT) == 0, "no voice file → nothing saved")
routes_src = open(os.path.join(ROOT, "tubecli", "extensions", "content_video", "routes.py"), encoding="utf-8").read()
ok("save_voice_cues(options, content)" in routes_src, "/run keeps the pasted subtitles' times next to the voice file")
pipe_src = open(P.__file__, encoding="utf-8").read()
ok("save_voice_cues(options, raw_source)" in pipe_src, "_prepare keeps them too (skill / MCP callers)")

# ── B. cue_chars ─────────────────────────────────────────────────────────────────────────────────────────────────────
cc = ND.cue_chars([[0.0, 2.0, "第一句話"], [3.0, 6.0, "第二句"]], total=9)
ok(cc and cc[0] == "第一句話第二句" and abs(cc[1][0] - 0.25) < 1e-6 and abs(cc[1][4] - 3.5) < 1e-6,
   "one time per character, spread over its line (slow speech, 1 s a character, kept)", cc)
slow = ND.cue_chars([[0.0, 71.0, "有人繼續來解掛"]], total=75)
ok(slow and slow[1][0] > 69.0, "a line stretched over a film clip → its words sit at the end", slow and slow[1][:2])
ok(ND.cue_chars([[0.0, 2.0, "一"], [50.0, 60.0, "二"]], total=20) is None, "times past the file's end → not this file's")
ok(ND.cue_chars([[0.0, 2.0, "一二"]], total=100) is None, "subtitles covering under half the file → not this file's")
ok(ND.cue_chars([], total=9) is None and ND.cue_chars([["x", 1, "a"]], total=9) is None, "nothing usable → None")

# ── C. cắt theo phụ đề, không Whisper ────────────────────────────────────────────────────────────────────────────────
calls = {"whisper": 0, "ensure": 0}


def no_whisper(*a, **k):
    calls["whisper"] += 1
    raise AssertionError("Whisper must not listen when the subtitles give the times")


def no_install(*a, **k):
    calls["ensure"] += 1
    return False, "should not be asked"


ND.whisper_chars = no_whisper
ND.ensure_whisper = no_install
paras = ["第一句話。", "第二句話很長。", "第三句。"]
out = os.path.join(TMP, "cut1")
notes = []
info = ND.split_by_paragraph(voice, paras, out, ffmpeg=FF, language="zh-TW", cues=P.load_voice_cues(voice),
                             install_whisper=True, notice=notes.append)
f = info["files"]
ok(info["engine"] == "subtitles" and info["match"] >= 0.99, "engine = subtitles, script fully matched", info)
ok(calls == {"whisper": 0, "ensure": 0}, "no Whisper, nothing installed", calls)
ok(len(f) == 3 and 2.0 <= f[0]["end"] <= 3.0 and 6.0 <= f[1]["end"] <= 7.0 and abs(f[2]["end"] - 9.0) < 0.1,
   "cuts land in the pauses between the lines", [(x["start"], x["end"]) for x in f])
w = json.load(open(f[1]["path"] + ".words.json", encoding="utf-8"))
ok([m["word"] for m in w["words"]] == list("第二句話很長") and w["words"][0]["start"] < 0.6,
   "word times for the video subtitles come from the subtitles", w["words"][:2])

# ── D. phụ đề không khớp → Whisper (tự cài); cài hỏng → lý do vào lỗi ───────────────────────────────────────────────
ND.ensure_whisper = lambda notice=None, installer=None: (calls.__setitem__("ensure", calls["ensure"] + 1)
                                                         or (False, "Whisper (faster-whisper) could not be installed on "
                                                                    "this machine: boom"))
notes.clear()
info = ND.split_by_paragraph(voice, paras, os.path.join(TMP, "cut2"), ffmpeg=FF, language="zh-TW",
                             cues=[[0, 2, "第一句話"], [40, 60, "第二句話很長"]], install_whisper=True,
                             notice=notes.append, guides=[2.0, 3.0, 2.0])
ok(any("do not fit this voice file" in m for m in notes), "subtitles of another file → said on the board", notes)
ok(calls["ensure"] == 1 and calls["whisper"] == 0, "Whisper install asked; not run when it could not be installed", calls)
ok(info["engine"] == "guide" and "boom" in info["whisper_problem"], "falls back to the temporary-voice timing", info)
flat = speech(os.path.join(up, "flat.wav"), [(0.0, 9.0)], 9)       # không có chỗ lặng nào
try:
    ND.split_by_paragraph(flat, paras, os.path.join(TMP, "cut3"), ffmpeg=FF, language="zh-TW", install_whisper=True,
                          guides=[2.0, 3.0, 2.0])
    ok(False, "no pause and no Whisper must fail")
except ValueError as e:
    ok("no clear pause" in str(e) and "could not be installed" in str(e) and "boom" in str(e),
       "the error says why Whisper was not there", e)
notes.clear()
calls["ensure"] = 0
ND.split_by_paragraph(voice, ["完全不同的內容。", "另一段。", "第三段。"], os.path.join(TMP, "cut4"), ffmpeg=FF,
                      cues=P.load_voice_cues(voice), install_whisper=True, notice=notes.append, guides=[2.0, 3.0, 2.0])
ok(any("match only" in m for m in notes) and calls["ensure"] == 1, "subtitles not matching the script → Whisper asked",
   notes)

# ── E. ensure_whisper ────────────────────────────────────────────────────────────────────────────────────────────────
import importlib.util as _ilu  # noqa: E402

spec = _ilu.spec_from_file_location("nd_e", os.path.join(ROOT, "tubecli", "extensions", "content_video", "narration_dub.py"))
NE = _ilu.module_from_spec(spec)
spec.loader.exec_module(NE)
state = {"have": False}
NE.whisper_installed = lambda: state["have"]
inst = []


def good_installer(pkgs, timeout=0):
    inst.append((list(pkgs), timeout))
    state["have"] = True
    return True, ""


said = []
ok(NE.ensure_whisper(said.append, installer=good_installer) == (True, ""), "missing → installed")
ok(inst == [(["faster-whisper"], NE.WHISPER_PIP_TIMEOUT)], "pip installs faster-whisper", inst)
ok(any("installing Whisper" in m for m in said) and "Whisper installed" in said, "install is reported on the board", said)
inst.clear()
ok(NE.ensure_whisper(installer=good_installer) == (True, "") and not inst, "already there → no pip")

state["have"] = False
bad = []


def bad_installer(pkgs, timeout=0):
    bad.append(1)
    return False, "No matching distribution found for ctranslate2"


r1 = NE.ensure_whisper(installer=bad_installer)
r2 = NE.ensure_whisper(installer=bad_installer)
ok(not r1[0] and "ctranslate2" in r1[1] and r2 == r1 and len(bad) == 1, "a failed install is not retried at once",
   (r1, r2, bad))
NE._WHISPER_FAIL["at"] -= NE.WHISPER_RETRY_S + 1
NE.ensure_whisper(installer=bad_installer)
ok(len(bad) == 2, "retried after 6 hours", bad)
NE._WHISPER_FAIL["at"] = 0.0
ok(NE.ensure_whisper(installer=lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))[1].endswith("disk full"),
   "an installer crash becomes the reason")
yt = open(os.path.join(ROOT, "tubecli", "core", "ytdlp_manager.py"), encoding="utf-8").read()
ok("sys.executable, \"-m\", \"pip\"" in yt, "pip runs in the Python that runs TubeCLI")

# ── F. _step_dub đọc mốc cạnh file giọng ─────────────────────────────────────────────────────────────────────────────
SHOTS = [{"id": 21, "storyboard_number": 1, "narration_text": "第一句話。", "tts_audio_url": ""},
         {"id": 22, "storyboard_number": 2, "narration_text": "第二句話很長。第三句。", "tts_audio_url": ""}]
seen, says = [], []


def fake_split(src, paragraphs, out_dir, ffmpeg="", language="", names=None, transcribe=None, duration=None, **kw):
    seen.append(kw)
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for nm in names:
        p = os.path.join(out_dir, nm + ".mp3")
        open(p, "wb").write(b"ID3")
        files.append({"path": p, "start": 0.0, "end": 1.0, "seconds": 1.0})
    return {"files": files, "engine": "subtitles", "match": 1.0, "anchors": 2}


P._storyboards = lambda ep: [dict(s) for s in SHOTS]
P._put = lambda path, payload, timeout=60: {}
P._task_meta = lambda tid, **patch: None
P._audio_check = lambda st: None
ND.split_by_paragraph = fake_split
ck = {}
st = {"episode_id": 155, "language": "zh-TW", "task_id": "t155", "checkpoint": ck,
      "_say": lambda step, status, msg="", *a: says.append(msg), "_cancelled": lambda: False}
P._checkpoint_merge = lambda state, patch: state["checkpoint"].update(patch)
P._step_dub(st, opts)
kw = seen[-1] if seen else {}
ok(len(kw.get("cues") or []) == 3 and kw.get("install_whisper") is True and callable(kw.get("notice")),
   "the dub step passes the subtitles' times and allows the Whisper install", kw)
ok(any("by the times in your subtitles (3 lines)" in m for m in says), "board: cutting by the subtitles", says)
ok(any("cut by the times in your subtitles" in m for m in says), "board: result names the subtitles", says[-1:])
kw["notice"]("installing Whisper …")
ok(says[-1] == "installing Whisper …", "install notices reach the board")
os.remove(side)
seen.clear()
st2 = {**st, "checkpoint": {}}
P._step_dub(st2, opts)
ok(seen and not seen[-1].get("cues") and seen[-1].get("install_whisper") is True,
   "plain text (no subtitle times) → Whisper, installed if missing", seen[-1:])

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
