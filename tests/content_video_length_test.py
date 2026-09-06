# Tests for "asked 10 minutes, got 2": the length must survive chat → pipeline →
# model → TTS → render, and every place it can silently shrink must say so.
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubecli.core import brain as B  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

# 1. Output budget reaches every provider through the contextvar, and only inside the block
assert B._output_budget(4096) == 4096
with B.AgentBrain.output_budget(9000):
    assert B._output_budget(4096) == 9000
    with B.AgentBrain.output_budget(None):
        assert B._output_budget(4096) == 4096, "None inside resets to the default"
assert B._output_budget(4096) == 4096, "budget must not leak out of the block"

seen = []
real = B.AgentBrain._call_gemini
B.AgentBrain._call_gemini = staticmethod(lambda *a, **k: seen.append(B._output_budget(4096)) or "TITLE: x\n\nbody")
try:
    agent = {"model": "gemini-2.0-flash", "provider": "gemini", "cloud_api_keys": {"gemini": "k"}}
    B.AgentBrain._call_llm(agent, [{"role": "user", "content": "hi"}], max_tokens=12000)
    B.AgentBrain._call_llm(agent, [{"role": "user", "content": "hi"}])
finally:
    B.AgentBrain._call_gemini = staticmethod(real)
assert seen == [12000, 4096], seen
print("1 budget     : contextvar scoped to the block; max_tokens kwarg on _call_llm sets it; default untouched")

# 2. Script budget scales with words; a 20-minute script no longer fits 4096
assert P.script_token_budget(260) == 4096, "short scripts keep the old ceiling"
assert P.script_token_budget(1500) == 5100
assert P.script_token_budget(3000) == 9600
assert P.script_token_budget(100000) == 16384, "capped"
assert P.short_script_warning(1030, 800) == ""
assert P.short_script_warning(300, 1500).startswith("The script came out at ~300 words")
assert P.short_script_warning(300, 0) == "", "no target → no complaint"
print("2 script     : token budget ≈ 3/word within [4096, 16384]; short-script warning below 60%")

# 3. _step_script runs the model under that budget and flags a truncated script
budgets = []


def fake_llm(agent, messages, temperature=0.7):
    budgets.append(B._output_budget(4096))
    return "TITLE: T\n\n[SHOW: a]\nOne. Two. Three."


B.AgentBrain._call_llm = staticmethod(fake_llm)
P._write_checkpoint = lambda *a, **k: None
P._publish_plan = lambda *a, **k: 1
P.resolve_language = lambda *a, **k: ("en", "dashboard")


class A:
    name = "MC"
    language = ""

    def to_dict(self):
        return {"model": "gemini-2.0-flash"}


state = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
         "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_script(state, {"target_words": 3000})
assert budgets == [9600], budgets
assert state["target_words"] == 3000 and state["words_from"] == "asked for"
assert any("stopped early" in w for w in state.get("warnings", [])), state.get("warnings")
print("3 step       : model called under the 20-minute budget; 3-word reply → 'stopped early' warning")

# 4. CapCut: a shot that fails once is retried, one that fails twice becomes a warning
import tubecli.config as CFG

CFG.DATA_DIR = tempfile.mkdtemp(prefix="cv-len-")
P.TTS_RETRY_DELAY = 0
attempts = {}


def flaky(path, payload, timeout=180):
    n = attempts[payload["text"]] = attempts.get(payload["text"], 0) + 1
    if payload["text"] == "flaky once" and n == 1:
        raise RuntimeError("429")
    if payload["text"] == "always dead":
        raise RuntimeError("500")
    return b"ID3" + b"\x00" * 2000


shots = [{"id": 1, "storyboard_number": 1, "narration_text": "fine"},
         {"id": 2, "storyboard_number": 2, "narration_text": "flaky once"},
         {"id": 3, "storyboard_number": 3, "narration_text": "always dead"}]
P._storyboards = lambda ep_id: shots
P._post_bytes = flaky
P._put = lambda path, payload, timeout=60: {}
st = {"episode_id": 1, "capcut_email": "a@x", "_cancelled": lambda: False, "_say": lambda *a: None}
P._tts_capcut(st, {})
assert attempts == {"fine": 1, "flaky once": 2, "always dead": 2}, attempts
assert st["tts_summary"] == "2 voiced (CapCut), 1 failed", st["tts_summary"]
assert st["warnings"] and "1 shot(s) got no voice after a retry" in st["warnings"][0], st["warnings"]
print("4 capcut     : failed shots retried once; still-failed → warning naming the 5-second stills")

# 5. edge: a second batch-tts only when something failed; summary from the second pass
posts = []
polls = iter([{"status": "done", "success": 10, "failed": 3}, {"status": "done", "success": 13, "failed": 0}])
P._post = lambda path, payload, timeout=300: posts.append(path) or {"task_id": "t"}
P._poll_studio = lambda *a, **k: next(polls)
st = {"episode_id": 1, "language": "en", "_cancelled": lambda: False, "_say": lambda *a: None}
P._tts_edge(st, {})
assert len(posts) == 2 and st["tts_summary"] == "13 voiced (edge)", (posts, st["tts_summary"])
assert not st.get("warnings")
posts.clear()
polls = iter([{"status": "done", "success": 13, "failed": 0}])
st = {"episode_id": 1, "language": "en", "_cancelled": lambda: False, "_say": lambda *a: None}
P._tts_edge(st, {})
assert len(posts) == 1, "no failures → no second batch"
print("5 edge       : batch-tts re-run only for failures; clean run stays single")

# 6. Render measures the real video and complains when it is far shorter than the script
P._post = lambda path, payload, timeout=300: {"task_id": "t"}
P._poll_studio = lambda *a, **k: {"status": "completed"}
P._get = lambda path, timeout=60: {"video_url": "/tmp/ep.mp4"}
P.media_seconds = lambda path: 150.0
st = {"episode_id": 1, "script": " ".join(["w"] * 1030), "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_render(st, {})
assert st["video_seconds"] == 150.0
assert st["warnings"] and st["warnings"][0].startswith("The video is 02:30 long but the script was planned for ~06:52"), st["warnings"]
P.media_seconds = lambda path: 400.0
st = {"episode_id": 1, "script": " ".join(["w"] * 1030), "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_render(st, {})
assert not st.get("warnings"), "6:40 for a 6:52 plan is fine"
P.media_seconds = lambda path: 0.0
st = {"episode_id": 1, "script": "a b", "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_render(st, {})
assert not st.get("warnings"), "no ffprobe → no false alarm"
assert P.media_seconds("/definitely/not/here.mp4") == 0.0
print("6 render     : ffprobe length on the state; <60% of plan → warning; unmeasurable → silent")

# 7. Result card leads with the video length, and the warning makes the icon ⚠️
st = {"video_seconds": 150.0, "shot_count": 13, "title": "T", "warnings": ["The video is 02:30 long but …"]}
out = P._render_result(st, {}, [], [], 4000.0)
assert out.startswith("## ⚠️ Content video rendered — completed with warning — 13 shots · video 02:30"), out.splitlines()[0]
st = {"shot_count": 13, "title": "T"}
out = P._render_result(st, {}, [], [], 125.0)
assert "13 shots · took 02:05" in out.splitlines()[0], out.splitlines()[0]
print("7 card       : header says 'video MM:SS' when measured, 'took MM:SS' otherwise")
print()
print("ALL 7 GROUPS PASSED")
