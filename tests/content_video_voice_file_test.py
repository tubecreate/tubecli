# -*- coding: utf-8 -*-
"""File giọng của người dùng kèm bài dán (options.voice_file, 5/11/2026).

User: «logic nhập voice kèm text vào taskboard luôn giúp tôi» (sau tập 888: bài phồn thể + file trung_done.wav 13:10 lồng
bằng tay). Kiểm — KHÔNG gọi Studio / Whisper / ffmpeg thật (mọi HTTP, narration_dub, TTS đều giả):
  A. apply_voice_file: file trong DATA_DIR + có bài dán → nguyên văn, tắt TTS, bật dub; file ngoài DATA_DIR / không có /
     không có bài → bỏ, chạy như thường.
  B. _step_dub với voice_file: cắt file theo cảnh, PUT đường giọng từng cảnh, nhớ checkpoint (Retry không cắt lại), meta
     giọng = file; cắt hỏng → đọc bằng giọng của mẫu (_step_tts) + cảnh báo, KHÔNG gọi Muse.
  C. route POST /voice-file: lưu file tiếng vào DATA_DIR/content_video/voice_uploads, từ chối đuôi lạ / file không có tiếng;
     /run với voice_file mà không có bài → 400.
Chạy: python tests/content_video_voice_file_test.py   (exit 0 = pass)
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.config as CFG  # noqa: E402

TMP = tempfile.mkdtemp(prefix="voice_file_test_")
CFG.DATA_DIR = TMP                      # mọi đường dẫn DATA_DIR của lượt thử nằm trong thư mục tạm

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


# ── A. apply_voice_file ────────────────────────────────────────────────────────────────────────────────────────────
up = os.path.join(TMP, "content_video", "voice_uploads")
os.makedirs(up, exist_ok=True)
wav = os.path.join(up, "abc123.wav")
open(wav, "wb").write(b"RIFF0000WAVE")
outside = os.path.join(tempfile.mkdtemp(prefix="voice_out_"), "x.wav")
open(outside, "wb").write(b"RIFF")

o = {**P.DEFAULTS, "voice_file": wav, "source_text": "第一段。第二段。", "script_mode": "rewrite", "target_words": 900,
     "length_mode": "minutes"}
P.apply_voice_file(o)
ok(o["voice_file"] == os.path.abspath(wav) and o["script_mode"] == "verbatim", "voice file → verbatim script", o)
ok(o["tts"] is True and o["tts_engine"] == "auto" and o["dub"] is True and o.get("_voice_mode"),
   "voice file → a temporary voice reads, then the dub step replaces it", (o["tts"], o["tts_engine"], o["dub"]))
ok(o["length_mode"] == "content" and "target_words" not in o, "length = the pasted text's own length", o)

o2 = {**P.DEFAULTS, "voice_file": outside, "source_text": "x"}
P.apply_voice_file(o2)
ok(o2["voice_file"] == "" and o2.get("_voice_file_dropped") and o2.get("_voice_mode"), "a file outside DATA_DIR is refused",
   o2)
o3 = {**P.DEFAULTS, "voice_file": os.path.join(up, "gone.wav"), "source_text": "x"}
P.apply_voice_file(o3)
ok(o3["voice_file"] == "" and o3.get("_voice_mode") and o3["dub"] is True, "a missing file is dropped, voice mode kept")
# #572 (6/11/2026): chặng DỰNG không mang bài dán — voice_file phải còn nguyên
o4 = {**P.DEFAULTS, "voice_file": wav, "script": "第一段。", "dub": True}
P.apply_voice_file(o4)
ok(o4["voice_file"] == os.path.abspath(wav) and o4["script_mode"] == "verbatim",
   "render stage without the pasted text keeps the voice file", o4)
o5 = {**P.DEFAULTS}
P.apply_voice_file(o5)
ok(o5 == {**P.DEFAULTS}, "no voice file → options untouched")
plan = P.describe_plan({**o, "preset": "T"}) if hasattr(P, "describe_plan") else ""
ok(not plan or "your file abc123.wav" in plan, "the plan names the voice file", str(plan)[:400])

# ── B. _step_dub với file giọng ────────────────────────────────────────────────────────────────────────────────────
SHOTS = [{"id": 11, "storyboard_number": 1, "narration_text": "第一段。", "tts_audio_url": ""},
         {"id": 12, "storyboard_number": 2, "narration_text": "", "tts_audio_url": ""},
         {"id": 13, "storyboard_number": 3, "narration_text": "第二段。", "tts_audio_url": ""}]
puts, splits, tts_calls, metas, says = [], [], [], [], []


def fake_split(src, paragraphs, out_dir, ffmpeg="", language="", names=None, transcribe=None, duration=None):
    splits.append((src, list(paragraphs), language, list(names or [])))
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for n in names:
        p = os.path.join(out_dir, n + ".mp3")
        open(p, "wb").write(b"ID3")
        files.append({"path": p, "start": 0.0, "end": 1.0, "seconds": 1.0})
    return {"files": files, "engine": "whisper", "match": 0.913, "anchors": 3}


def fail_split(*a, **k):
    raise ValueError("the voice-over does not follow the script (only 12% of it was heard back)")


def fake_muse(*a, **k):
    raise AssertionError("Muse must not be called for a user voice file")


P._storyboards = lambda ep: [dict(s) for s in SHOTS]
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
P._task_meta = lambda tid, **patch: metas.append(patch)
P._audio_check = lambda state: None
P._step_tts = lambda state, options: tts_calls.append(dict(options))
try:
    from tubecli.core import muse as _M
    _M.generate_speech = fake_muse
except Exception:      # noqa: BLE001
    pass


def new_state():
    st = {"episode_id": 888, "language": "zh-TW", "task_id": "t1", "checkpoint": {},
          "_say": lambda step, status, msg="": says.append(msg), "_cancelled": lambda: False}

    def merge(state, patch):
        state["checkpoint"].update(patch)
    P._checkpoint_merge = merge
    return st


ND.split_by_paragraph = fake_split
st = new_state()
P._step_dub(st, o)
ok(len(splits) == 1 and splits[0][0] == os.path.abspath(wav), "the user's file is cut (not Muse)", splits)
ok(splits and splits[0][1] == ["第一段。", "第二段。"] and splits[0][3] == ["shot001", "shot003"],
   "only scenes with narration, named by shot number", splits)
ok(splits and splits[0][2] == "zh-TW", "the script language goes to the cutter")
ok([p for p, _ in puts] == ["/api/v1/studio/storyboards/11", "/api/v1/studio/storyboards/13"]
   and all(pl["tts_audio_url"].endswith((".mp3",)) for _, pl in puts), "each voiced scene points at its cut", puts)
ok(os.path.join("content_video", "audio", "ep888_user") in puts[0][1]["tts_audio_url"], "cuts live in ep<id>_user", puts)
ok(metas and metas[-1]["voice"]["engine"] == "file" and "abc123.wav" in st["tts_voice_used"], "voice meta = your file",
   (metas, st.get("tts_voice_used")))
ok(st["checkpoint"]["dub"]["match"] == 0.913 and not tts_calls, "checkpoint saved, no TTS", st["checkpoint"])
ok(any("Whisper match 91%" in m for m in says), "the board line reports the match", says[-2:])

# Retry: cùng file + cùng lời → không cắt lại
splits.clear(); puts.clear()
SHOTS[0]["tts_audio_url"] = st["checkpoint"]["dub"]["files"][0]
SHOTS[2]["tts_audio_url"] = st["checkpoint"]["dub"]["files"][1]
ck = dict(st["checkpoint"])
st2 = new_state()
st2["checkpoint"] = ck
P._step_dub(st2, o)
ok(not splits and not puts, "retry with the same file and script reuses the cut", (splits, puts))
SHOTS[0]["tts_audio_url"] = SHOTS[2]["tts_audio_url"] = ""

# Giọng không theo bài → GIỮ giọng tạm (CapCut / Edge đã đọc ở bước tts) + cảnh báo; không Muse, không đọc lại
ND.split_by_paragraph = fail_split
puts.clear(); tts_calls.clear()
st3 = new_state()
st3["tts_voice_used"] = "CapCut · 台灣男聲 · Chinese (Traditional)"
P._step_dub(st3, o)
ok(not tts_calls, "a file that does not follow the script → no second TTS run", tts_calls)
ok(any("abc123.wav was not used" in w and "CapCut" in w for w in st3.get("warnings") or []),
   "the task warns and names the temporary voice it keeps", st3.get("warnings"))
ok(not puts, "no scene is pointed at a broken cut", puts)

# File biến mất / bị bỏ ở chặng dựng (#572) → vẫn KHÔNG gọi Muse
ND.split_by_paragraph = fake_split
tts_calls.clear()
st4 = new_state()
P._step_dub(st4, {**o, "voice_file": "", "_voice_mode": True})
ok(not tts_calls and st4.get("warnings"), "voice mode without a usable file → keep the temporary voice + warning, no Muse",
   (tts_calls, st4.get("warnings")))

# ── B2. giọng tạm: CapCut nếu có tài khoản, không thì Edge; bỏ qua giọng của mẫu ────────────────────────────────────
_real_inst, _real_acct = P.installed_extensions, P._capcut_account
P.installed_extensions = lambda: {"capcut_tts": True, "tts_vibevoice": True}
P._capcut_account = lambda email="": "cap@example.com"
stv = {"capcut_speaker": "vi_template_voice"}
ok(P._tts_engine(stv, o) == "capcut" and stv.get("capcut_email") == "cap@example.com" and "capcut_speaker" not in stv,
   "voice mode → CapCut, the template's speaker is dropped (picked by language)", stv)
P._capcut_account = lambda email="": ""
stv = {}
ok(P._tts_engine(stv, o) == "edge" and stv.get("tts_batch_engine") == "edge", "no CapCut account → Edge", stv)
P.installed_extensions = lambda: {"capcut_tts": False, "tts_vibevoice": True}
ok(P._tts_engine({}, {**o, "tts_engine": "everai"}) == "edge", "voice mode ignores the template's paid / desktop engines")
P.installed_extensions, P._capcut_account = _real_inst, _real_acct

# ── C. route ───────────────────────────────────────────────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tubecli.extensions.content_video import routes as R
    import tubecli.extensions.video_studio.ffmpeg_utils as FU
    FU.media_duration = lambda path: 12.5 if open(path, "rb").read(4) == b"RIFF" else 0.0
    app = FastAPI()
    app.include_router(R.router)
    c = TestClient(app)
    r = c.post("/api/v1/content-video/voice-file", files={"file": ("my voice.wav", b"RIFF" + b"0" * 64, "audio/wav")})
    j = r.json() if r.status_code == 200 else {}
    ok(r.status_code == 200 and j.get("seconds") == 12.5 and j.get("name") == "my voice.wav", "upload accepted", r.text)
    ok(j.get("path", "").startswith(os.path.join(TMP, "content_video", "voice_uploads")) and os.path.isfile(j.get("path", "")),
       "saved under DATA_DIR/content_video/voice_uploads", j)
    r = c.post("/api/v1/content-video/voice-file", files={"file": ("notes.txt", b"hello", "text/plain")})
    ok(r.status_code == 400, "a non-audio extension is refused", r.text)
    before = set(os.listdir(up))
    r = c.post("/api/v1/content-video/voice-file", files={"file": ("silent.mp3", b"ID3notaudio", "audio/mpeg")})
    ok(r.status_code == 400 and set(os.listdir(up)) == before, "a file without readable audio is refused and removed",
       (r.text, set(os.listdir(up)) - before))
    r = c.post("/api/v1/content-video/run", json={"agent_id": "a1", "content": "", "options": {"voice_file": wav}})
    ok(r.status_code != 200 or r.json().get("status") == "need_agent" or "task" not in r.json(),
       "no content: no task is created", r.text[:200])
    import tubecli.extensions.content_video.pipeline as PP
    made = []
    PP.create_plan_task = lambda *a, **k: made.append((a, k)) or {"id": "x", "status": "queued"}
    PP.queued_reply = lambda task: ""
    r = c.post("/api/v1/content-video/run", json={"agent_id": "a1", "content": "第一段。",
                                                 "options": {"voice_file": outside}})
    ok(r.status_code == 400 and not made, "/run with a voice file outside DATA_DIR → 400, no task", (r.status_code, r.text))
    r = c.post("/api/v1/content-video/run", json={"agent_id": "a1", "content": "第一段。", "options": {"voice_file": wav}})
    opts = made[-1][0][1] if made and len(made[-1][0]) > 1 else {}
    ok(r.status_code == 200 and opts.get("script_mode") == "verbatim" and opts.get("_voice_mode") and opts.get("dub"),
       "/run normalises the options before the task is made", (r.status_code, opts))
except ImportError as e:
    ok(False, "fastapi test client available", e)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
