# Voice step: edge (tts_vibevoice) or CapCut (capcut_tts), chosen by what is installed.
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.content_video import capabilities as C
from tubecli.extensions.content_video import pipeline as P

# 1. any_of in check_job / guidance
C.installed_extensions = lambda: {"content_studio": True, "capcut_tts": True}
r = C.check_job("tts")
assert r["ready"] and r["missing"] == [] and r["any_of"] == ["tts_vibevoice", "capcut_tts"], r
C.installed_extensions = lambda: {"content_studio": True}
r = C.check_job("tts")
assert not r["ready"] and r["missing"] == ["tts_vibevoice", "capcut_tts"], r
g = C.guidance_for(["tts"])
assert "Install ONE of these" in g and "CapCut TTS" in g and "TTS VibeVoice" in g, g
C.installed_extensions = lambda: {"content_studio": True, "tts_vibevoice": False, "capcut_tts": True}
assert C.check_job("tts")["ready"], "one enabled member is enough"
print("1 any_of     : ready with either extension | both missing → 'Install ONE of these'")

# 2. engine selection
P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
P._get = lambda path, timeout=60: {"accounts": [{"email": "a@x.com", "enabled": True}]}
st = {}
assert P._tts_engine(st, {"tts_engine": "auto"}) == "capcut" and st["capcut_email"] == "a@x.com"
P._get = lambda path, timeout=60: {"accounts": [{"email": "a@x.com", "enabled": False}]}
assert P._tts_engine({}, {"tts_engine": "auto"}) == "edge", "no enabled CapCut account → edge"
P.installed_extensions = lambda: {"tts_vibevoice": False, "capcut_tts": False}
assert P._tts_engine({}, {"tts_engine": "auto"}) == ""
P.installed_extensions = lambda: {"tts_vibevoice": True}
assert P._tts_engine({}, {"tts_engine": "edge"}) == "edge"
try:
    P._tts_engine({}, {"tts_engine": "capcut"})
    raise SystemExit("capcut requested but absent must raise")
except RuntimeError as e:
    assert "CapCut" in str(e)
print("2 engine     : auto→capcut with account, →edge without | explicit choices validated")

# 3. CapCut per-shot path: synthesize → save mp3 → PUT tts_audio_url (absolute path)
import tubecli.config as CFG
tmp = tempfile.mkdtemp(prefix="cv-audio-")
CFG.DATA_DIR = tmp
puts, posts = [], []
shots = [{"id": 1, "storyboard_number": 1, "narration_text": "[nhạc nền] Xin chào các bạn hôm nay"},
         {"id": 2, "storyboard_number": 2, "narration_text": "Cảnh hai", "tts_audio_url": "/already.mp3"},
         {"id": 3, "storyboard_number": 3, "narration_text": "[]"}]
P._storyboards = lambda ep_id: shots
P._post_audio_marks = lambda path, payload, timeout=180: (posts.append(payload) or (b"ID3" + b"\x00" * 2000),
                                                          [{"word": "Xin", "start": 0.0, "end": 0.4}] if payload["text"].startswith("Xin") else [])
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
reports = []
state = {"episode_id": 34, "capcut_email": "a@x.com", "_cancelled": lambda: False, "_say": lambda *a: reports.append(a)}
P._tts_capcut(state, {"capcut_speaker": "vi_female_01"})
assert posts == [{"email": "a@x.com", "text": "Xin chào các bạn hôm nay", "speed": 10, "volume": 10, "speaker": "vi_female_01", "timestamps": True}], posts
assert len(puts) == 1 and puts[0][0] == "/api/v1/studio/storyboards/1"
path = puts[0][1]["tts_audio_url"]
import os
assert os.path.isabs(path) and os.path.isfile(path) and path.endswith("shot001.mp3"), path
assert state["tts_summary"] == "1 voiced (CapCut), 1 silent", state["tts_summary"]
import json as _json
side = _json.load(open(path + ".words.json", encoding="utf-8"))
assert side["engine"] == "capcut" and side["words"][0]["word"] == "Xin", side
print("3 capcut     : cue stripped, voiced shot saved + PUT absolute path, existing audio kept, empty skipped")

# 4. _step_tts dispatch: edge path still goes through the Studio's batch-tts
P.installed_extensions = lambda: {"tts_vibevoice": True}
calls = []
P._post = lambda path, payload, timeout=300: calls.append((path, payload)) or {"task_id": "t"}
P._poll_studio = lambda *a, **k: {"status": "done", "success": 3, "failed": 0}
st = {"episode_id": 34, "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto", "tts_voice": "vi-VN-HoaiMyNeural"})
assert st["tts_engine"] == "edge" and calls[0][0].endswith("/batch-tts") and calls[0][1]["engine"] == "edge"
assert st["tts_summary"] == "3 voiced (edge)"
print("4 dispatch   : edge → Studio batch-tts; summary names the engine")
# 5. Giọng lưu trong preset: preset thắng "auto", chat thắng preset; CapCut mang speaker + email
P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
P._capcut_account = lambda preferred="": preferred or "first@x"
pre = lambda meta: {"preset": {"name": "T", "fields": {"metadata": meta}}}
st = {**pre({"tts_engine": "capcut", "tts_voice": "vi_female_01", "tts_email": "a@x.com"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {}) == "capcut" and st["capcut_email"] == "a@x.com" and st["capcut_speaker"] == "vi_female_01", st
st = {**pre({"tts_engine": "vibevoice", "tts_voice": "Alice"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {}) == "edge" and st["tts_batch_engine"] == "vibevoice" and st["tts_voice_pref"] == "Alice", st
st = {**pre({"tts_engine": "vibevoice", "tts_voice": "Alice"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {"tts_engine": "edge", "tts_voice": "vi-VN-NamMinhNeural"}) == "edge" and st["tts_voice_pref"] == "vi-VN-NamMinhNeural", "chat wins over preset"
assert P._preset_voice({}, {}) == ("auto", "", "")
# batch-tts nhận engine của preset và giọng VibeVoice không bị so ngôn ngữ
calls.clear()
P._post = lambda path, payload, timeout=300: calls.append((path, payload)) or {"task_id": "t"}
P._poll_studio = lambda *a, **k: {"status": "done", "success": 2, "failed": 0}
st = {"episode_id": 1, "language": "vi", "tts_batch_engine": "vibevoice", "tts_voice_pref": "Alice", "_cancelled": lambda: False, "_say": lambda *a: None}
P._tts_edge(st, {})
assert calls[-1][1] == {"voice_id": "Alice", "engine": "vibevoice"} and not st.get("warnings") and st["tts_summary"] == "2 voiced (vibevoice)", (calls[-1], st)
# _step_studio: preset có giọng → agent_meta không ghi đè; không có → mặc định edge theo ngôn ngữ; "auto" từ chat không lọt vào drama
bodies = []
P._post = lambda path, payload, timeout=300: bodies.append((path, payload)) or {"id": 7}
P._write_checkpoint = lambda *a, **k: None
P._storyboards = lambda ep_id: [{"id": 1, "narration_text": "x"}]
P._stream_storyboard = lambda *a, **k: None


class _A:
    id = "a1"
    name = "MC"


for meta, opts, want_engine, want_voice in [
    ({"tts_engine": "capcut", "tts_voice": "spk", "tts_email": "a@x.com"}, {}, "capcut", "spk"),
    ({}, {}, "edge", "vi-VN-HoaiMyNeural"),
    ({}, {"tts_engine": "auto"}, "edge", "vi-VN-HoaiMyNeural"),
    ({"tts_engine": "vibevoice", "tts_voice": "Alice"}, {"tts_voice": "vi-VN-NamMinhNeural"}, "vibevoice", "vi-VN-NamMinhNeural"),
]:
    bodies.clear()
    st = {"agent": _A(), "language": "vi", "script": "[SHOW: a]\nx", "title": "T", "task_id": "",
          "preset": {"name": "T", "fields": {"metadata": meta}} if meta else None, "preset_name": "T" if meta else "",
          "_cancelled": lambda: False, "_say": lambda *a: None}
    P._step_studio(st, opts)
    dm = bodies[0][1]["metadata"]
    assert dm.get("tts_engine") == want_engine and dm.get("tts_voice") == want_voice, (meta, opts, dm)
    if meta.get("tts_email"):
        assert dm.get("tts_email") == "a@x.com", dm
print("5 preset voice: preset thắng auto, chat thắng preset, CapCut mang speaker+email, VibeVoice không bị so ngôn ngữ, 'auto' không lọt vào drama")
# 6. Bước tuỳ chọn ĐÃ CHẠY mà hỏng → lượt hỏng (có Retry); chỉ publish được nuốt lỗi; thiếu năng lực vẫn bỏ qua
P.check_job = lambda job: {"ready": job != "missing_cap", "missing": ["x"] if job == "missing_cap" else [], "disabled": []}
def boom(state, options): raise RuntimeError("CapCut TTS failed for every shot (15)")
P._HANDLERS["tts"] = boom
P._HANDLERS["publish"] = boom
notes, skipped = [], []
try:
    P._run_steps([("tts", "Voice the narration", "tts", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
    raise SystemExit("tts failure must fail the run")
except RuntimeError as e:
    assert "every shot" in str(e)
notes.clear()
P._run_steps([("publish", "Publish to YouTube", "publish", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
assert notes and "Publish to YouTube** failed" in notes[0], notes
notes.clear()
P._run_steps([("tts", "Voice the narration", "missing_cap", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
assert notes and "skipped" in notes[0] and skipped == ["missing_cap"], (notes, skipped)
print("6 fail policy : tts chạy mà hỏng → RuntimeError (Retry); publish hỏng → ghi chú; thiếu năng lực → bỏ qua")
print()
print("ALL 6 GROUPS PASSED")
