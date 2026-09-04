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
P._post_bytes = lambda path, payload, timeout=180: posts.append(payload) or (b"ID3" + b"\x00" * 2000)
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
reports = []
state = {"episode_id": 34, "capcut_email": "a@x.com", "_cancelled": lambda: False, "_say": lambda *a: reports.append(a)}
P._tts_capcut(state, {"capcut_speaker": "vi_female_01"})
assert posts == [{"email": "a@x.com", "text": "Xin chào các bạn hôm nay", "speed": 10, "volume": 10, "speaker": "vi_female_01"}], posts
assert len(puts) == 1 and puts[0][0] == "/api/v1/studio/storyboards/1"
path = puts[0][1]["tts_audio_url"]
import os
assert os.path.isabs(path) and os.path.isfile(path) and path.endswith("shot001.mp3"), path
assert state["tts_summary"] == "1 voiced (CapCut), 1 silent", state["tts_summary"]
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
print()
print("ALL 4 GROUPS PASSED")
