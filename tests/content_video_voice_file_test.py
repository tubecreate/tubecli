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


split_kw = []


def fake_split(src, paragraphs, out_dir, ffmpeg="", language="", names=None, transcribe=None, duration=None, **kw):
    splits.append((src, list(paragraphs), language, list(names or [])))
    split_kw.append(kw)
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
          "_say": lambda step, status, msg="", *a: says.append(msg), "_cancelled": lambda: False}

    def merge(state, patch):
        state["checkpoint"].update(patch)
    P._checkpoint_merge = merge
    return st


import shutil  # noqa: E402
import subprocess  # noqa: E402

FF = shutil.which("ffmpeg") or "ffmpeg"


def tone(path, seconds):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-ac", "1", path],
                   check=True)
    return path


# giọng TẠM (CapCut / Edge) của từng cảnh — bước dub đọc thời lượng của nó làm chỗ cắt dự đoán
SHOTS[0]["tts_audio_url"] = tone(os.path.join(TMP, "temp1.mp3"), 2.5)
SHOTS[2]["tts_audio_url"] = tone(os.path.join(TMP, "temp3.mp3"), 4.0)
ND.split_by_paragraph = fake_split
st = new_state()
P._step_dub(st, o)
ok(len(splits) == 1 and splits[0][0] == os.path.abspath(wav), "the user's file is cut (not Muse)", splits)
g = (split_kw[-1] if split_kw else {}).get("guides") or []
ok(len(g) == 2 and abs(g[0] - 2.5) < 0.15 and abs(g[1] - 4.0) < 0.15, "the temporary voice's durations go to the cutter", g)
prog = (split_kw[-1] if split_kw else {}).get("progress")
if callable(prog):
    prog(65.0, 785.0)
ok(any("1:05 / 13:05 heard" in m for m in says), "progress line: «m:ss / M:SS heard»", says[-3:])
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

# ── B2b. dàn nhân vật của task (form «Characters») ─────────────────────────────────────────────────────────────────
ok(P.task_cast({}) is None and P.task_cast({"cast": "maren"}) is None, "no list → follow the template's cast")
ok(P.task_cast({"cast": ["maren", " maren ", "", "kael"]}) == ["maren", "kael"], "cast cleaned, de-duplicated")
ok(P.task_cast({"cast": []}) == [], "empty list = no fixed characters (overrides the template)")
_src = open(P.__file__, encoding="utf-8").read()
ok('agent_meta["cast"] = cast' in _src and 'label = VOICE_FILE_LABEL' in _src,
   "studio step writes the task cast; the dub step is labelled as a voice-file swap")
ok(P.VOICE_FILE_LABEL == "Swap in your voice file", "label text")

# ── B3. narration_dub: Whisper nhanh + báo tiến độ; không Whisper → cắt theo giọng tạm ──────────────────────────────
import importlib.util as _ilu  # noqa: E402
import types  # noqa: E402

_spec = _ilu.spec_from_file_location("nd_fresh", os.path.join(ROOT, "tubecli", "extensions", "content_video", "narration_dub.py"))
NDF = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(NDF)
ok(NDF.WHISPER_MODEL == "base" and NDF.WHISPER_BEAM == 1, "cutting uses Whisper base / beam 1 (≈7× faster than small/5)")

seen_model = {}


class _W:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class _Seg:
    def __init__(self, end, words):
        self.end, self.words = end, words


class FakeModel:
    def __init__(self, size, **kw):
        seen_model["size"] = size

    def transcribe(self, path, **kw):
        seen_model.update(kw)
        return iter([_Seg(3.0, [_W("第一", 0.5, 1.5)]), _Seg(7.5, [_W("段", 4.0, 5.0)])]), None


sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=FakeModel)
heard_at = []
got = NDF.whisper_chars("x.wav", "zh-TW", progress=heard_at.append)
ok(got and got[0] == "第一段" and heard_at == [3.0, 7.5], "progress after each Whisper segment", (got, heard_at))
ok(seen_model.get("size") == "base" and seen_model.get("beam_size") == 1 and seen_model.get("language") == "zh",
   "model base, beam 1, language zh", seen_model)
def _broken_progress(t):
    raise RuntimeError("board offline")


NDF.whisper_chars("x.wav", "zh", progress=_broken_progress)
ok(True, "a broken progress callback does not stop the listening")
del sys.modules["faster_whisper"]

# không Whisper + giọng tạm: file tổng hợp 5 đoạn (tiếng bíp, nghỉ 0,25 s giữa câu, 0,7 s giữa đoạn)
LENS = [[1.2, 1.6], [2.0], [0.9, 1.1, 1.3], [2.4], [1.5, 1.0]]
parts, t, truth_cuts = [], 0.0, []
for pi, sents in enumerate(LENS):
    for si, L in enumerate(sents):
        parts.append(("sine", L)); t += L
        if si < len(sents) - 1:
            parts.append(("sil", 0.25)); t += 0.25
    if pi < len(LENS) - 1:
        parts.append(("sil", 0.7)); truth_cuts.append(t + 0.35); t += 0.7
inputs, filt = [], []
for k, (kind, L) in enumerate(parts):
    inputs += ["-f", "lavfi", "-t", f"{L}", "-i", ("sine=frequency=330:sample_rate=24000" if kind == "sine"
                                                     else "anullsrc=r=24000:cl=mono")]
    filt.append(f"[{k}:a]")
user_wav = os.path.join(TMP, "user_voice.wav")
subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", "".join(filt) + f"concat=n={len(parts)}:v=0:a=1[a]",
                "-map", "[a]", "-ac", "1", user_wav], check=True)
# giọng tạm đọc chậm hơn 12 % và lệch từng đoạn (0,8–1,2×) — như CapCut so với người thật
spoken = [sum(s) + 0.25 * (len(s) - 1) for s in LENS]
guides = [d * f * 1.12 for d, f in zip(spoken, (1.2, 0.85, 1.1, 0.8, 1.0))]
paras = ["一二。三四。", "五六七。", "八。九。十。", "十一十二。", "十三。十四。"]
info = NDF.split_by_paragraph(user_wav, paras, os.path.join(TMP, "guide_out"), ffmpeg=FF, language="zh",
                              transcribe=lambda p, l: None, guides=guides)
cuts = [f["start"] for f in info["files"][1:]]
err = [abs(a - b) for a, b in zip(cuts, truth_cuts)]
ok(info["engine"] == "guide" and max(err) < 0.3, "no Whisper → cut by the temporary voice + pauses", (info["engine"], cuts,
                                                                                                         truth_cuts))
ok(all(os.path.isfile(f["path"]) for f in info["files"]), "one file per scene")
info2 = NDF.split_by_paragraph(user_wav, paras, os.path.join(TMP, "guide_out2"), ffmpeg=FF, language="zh",
                               transcribe=lambda p, l: None)
ok(info2["engine"] == "silence", "no Whisper and no temporary voice → the old pause-only cut")

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
