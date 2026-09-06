# Tests for "asked 10 minutes, got 2": the length must survive chat → pipeline →
# model → TTS → render, and every place it can silently shrink must say so.
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubecli.core import brain as B  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
_REAL_POLL = P._poll_studio

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
P._step_script(state, {"target_words": 1000})
assert budgets == [4096], budgets
assert state["target_words"] == 1000 and state["words_from"] == "asked for"
assert any("stopped early" in w for w in state.get("warnings", [])), state.get("warnings")
print("3 step       : ≤1000 words → one call under its budget; 3-word reply → 'stopped early' warning")

# 3b. A provider error string must not become the script (it used to land as "scene 2")
B.AgentBrain._call_llm = staticmethod(lambda *a, **k: "[OpenAI Error] deepseek-v4-flash returned an empty response (finish_reason=length, the model spent its whole budget on reasoning).")
state = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
         "_say": lambda *a: None, "_cancelled": lambda: False}
try:
    P._step_script(state, {"target_words": 3000})
    raise SystemExit("error string must raise")
except RuntimeError as e:
    assert "could not write the script" in str(e) and "reasoning model" in str(e) and "shorter video" in str(e), e
assert P.is_llm_error("[Gemini Error] HTTP 429") and P.is_llm_error("  [Claude Error] x") and not P.is_llm_error("TITLE: Errors of 1999")
print("3b error     : '[… Error]' reply → RuntimeError with the reasoning-model hint, never a one-line plan")

# 3c. OpenAI-compatible retry after finish=length asks for MORE than the first budget
import types
asks = []


class _Msg:
    def __init__(self, content):
        self.content = content
        self.reasoning_content = "thinking…"


class _Choice:
    def __init__(self, content, finish):
        self.message = _Msg(content)
        self.finish_reason = finish


class _Completions:
    def create(self, **kw):
        asks.append(kw.get("max_tokens"))
        if len(asks) == 1:
            return types.SimpleNamespace(choices=[_Choice("", "length")])
        return types.SimpleNamespace(choices=[_Choice("TITLE: ok", "stop")])


class _OpenAI:
    def __init__(self, *a, **k):
        self.chat = types.SimpleNamespace(completions=_Completions())


sys.modules["openai"] = types.SimpleNamespace(OpenAI=_OpenAI)
with B.AgentBrain.output_budget(9600):
    out = B.AgentBrain._call_openai("deepseek-v4-flash", "k", [{"role": "user", "content": "x"}])
assert out == "TITLE: ok" and asks == [9600, 19200], asks
asks.clear()
out = B.AgentBrain._call_openai("gpt-x", "k", [{"role": "user", "content": "x"}])
assert asks == [None, 8192], asks
del sys.modules["openai"]
print("3c retry     : finish=length → second ask doubles the budget (9600→19200); no budget → 8192 as before")

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
# 8. Storyboard that condenses the script: narration restored in place, nothing regenerated
def mk_script(n, per=100):
    return "\n".join(f"[SHOW: scene {i} about topic{i}]\nTopic{i} sentence one is here. "
                      + " ".join([f"topic{i}word"] * (per - 12)) + f". Topic{i} sentence three ends it."
                      for i in range(n))


script = mk_script(20)                                   # ~2000 words, 20 scenes
full = [{"id": i, "storyboard_number": i + 1, "narration_text": f"topic{i} " + " ".join([f"topic{i}word"] * 95)} for i in range(20)]
# What the Studio did: 32 shots (some scenes split in two), each narration a short paraphrase
condensed = []
num = 1
for i in range(20):
    parts = 2 if i % 3 == 0 else 1
    for k in range(parts):
        condensed.append({"id": 100 + num, "storyboard_number": num, "title": f"Scene {i} (Part {k + 1})",
                          "narration_text": f"Topic{i} short summary {k}.", "image_prompt": f"img {i}"})
        num += 1
assert len(condensed) == 27
assert P.storyboard_coverage(full, script) > 0.9 and P.storyboard_coverage(condensed, script) < 0.1
assert P.storyboard_coverage([], "") == 1.0, "no script → nothing to lose"

scenes = [sc for sc in P.scenes_of(script) if sc[1]]
owner = P.align_shots_to_scenes(condensed, scenes)
assert owner == sorted(owner) and owner[0] == 0 and owner[-1] == 19, owner
assert owner[:3] == [0, 0, 1], "scene 0 has two shots; both stay on scene 0"
fixed = P.restore_narration(condensed, script)
assert [sid for sid, _ in fixed] == [sh["id"] for sh in condensed], "every shot, in order"
joined = " ".join(t for _, t in fixed)
for i in range(20):
    assert f"Topic{i} sentence one is here." in joined and f"Topic{i} sentence three ends it." in joined, i
assert fixed[0][1].startswith("Topic0 sentence one is here.") and fixed[1][1].endswith("Topic0 sentence three ends it."), \
    "a split scene hands its sentences to its two shots in order"
assert not P.storyboard_stopped_early(condensed, scenes)

# dropped scenes: 3 shots for 20 scenes, only the first three covered → stopped early;
# after Studio's append the rest is still missing → text of the uncovered scenes folds into neighbours
three = condensed[:3]
assert P.storyboard_stopped_early(three, scenes)
fixed3 = P.restore_narration(three, script)
assert "Topic19 sentence three ends it." in fixed3[-1][1], "tail scenes fold into the last shot"

# _step_studio: restore via PUT, no regeneration, coverage re-measured
streams, puts = [], []
P._stream_storyboard = lambda ep_id, st, append=False: streams.append((ep_id, append))
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
store = {"shots": [dict(sh) for sh in condensed]}


def fake_storyboards(ep_id):
    for sh in store["shots"]:
        for path, payload in puts:
            if path.endswith(f"/{sh['id']}"):
                sh["narration_text"] = payload["narration_text"]
    return [dict(sh) for sh in store["shots"]]


P._storyboards = fake_storyboards
st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": script,
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_studio(st, {})
assert streams == [], "condensed (not truncated) storyboard → no Studio call at all"
assert len(puts) == 27 and all(p[1]["tts_audio_url"] == "" for p in puts), "every shot rewritten, stale audio dropped"
assert st["shot_count"] == 27 and st["storyboard_coverage"] > 0.9 and st["storyboard_restored"] == 27, st
out = P._render_result(st, {}, [], [], 1.0)
assert "- **Storyboard**: 27 shots · covers" in out and "narration restored from the script" in out, out

# truncated storyboard → append first, then restore
puts.clear()
store["shots"] = [dict(sh) for sh in condensed[:3]]
st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": script,
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_studio(st, {})
assert streams == [(9, True)], "stopped early → continue with append=True, never a fresh regenerate"
assert st["storyboard_coverage"] > 0.9

# good storyboard → untouched; short scripts never judged
puts.clear(); streams.clear()
store["shots"] = [dict(sh) for sh in full]
st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": script,
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_studio(st, {})
assert puts == [] and streams == [] and st["shot_count"] == 20 and "storyboard_restored" not in st
store["shots"] = [dict(sh) for sh in condensed[:3]]
st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": "[SHOW: a]\n" + " ".join(["w"] * 150),
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_studio(st, {})
assert puts == [] and st.get("storyboard_coverage") is None
print("8 storyboard : condensed narration restored in place (27 PUTs, 0 regenerations); truncated → append; good → untouched")

# 9. Plan warns when a long script has almost no [SHOW] scenes
B.AgentBrain._call_llm = staticmethod(lambda *a, **k: "TITLE: T\n\n[SHOW: one]\n" + " ".join(["w"] * 3000))
st = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._publish_plan = lambda task_id, agent_name, title, script: len(P.scenes_of(script))
P._step_script(st, {"target_words": 3000})
assert st["scene_count"] == 1 and any("only 1 [SHOW] scene" in w for w in st["warnings"]), st.get("warnings")
print("9 plan       : 3000 words in one [SHOW] → warning on the plan")
# 10. Long scripts are written in batches: outline call + one call per 6 scenes
calls = []


def chunk_llm(agent, messages, temperature=0.7):
    prompt = messages[-1]["content"]
    calls.append((prompt, B._output_budget(4096)))
    if "Plan a news video" in prompt:
        return "TITLE: Twenty Minutes\n" + "\n".join(f"{i}. [SHOW: frame {i}] — gist {i}" for i in range(1, 27))
    import re as _re
    m = _re.search(r"scenes (\d+)-(\d+) ONLY", prompt)
    a, b = int(m.group(1)), int(m.group(2))
    return "\n\n".join(f"[SHOW: frame {i}]\n" + " ".join([f"s{i}w"] * 110) + "." for i in range(a, b + 1))


B.AgentBrain._call_llm = staticmethod(chunk_llm)
st = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
      "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_script(st, {"target_words": 3000})
assert len(calls) == 1 + 5, [c[0][:40] for c in calls]                      # 26 scenes → 5 batches of ≤6
assert calls[0][1] == 4096 and all(c[1] == 4096 for c in calls[1:]), "each call small enough for a 4096 budget"
assert st["title"] == "Twenty Minutes" and st["scene_count"] == 26, (st["title"], st["scene_count"])
assert "scenes 1-6 ONLY" in calls[1][0] and "start with a hook" in calls[1][0]
assert "scenes 25-26 ONLY" in calls[5][0] and "Close the video" in calls[5][0] and "previous scene ended with" in calls[5][0]
assert "planned as these 26 scenes" in calls[3][0], "every batch sees the whole outline"
assert not st.get("warnings"), st.get("warnings")
assert 26 * 110 <= len(st["script"].split()) <= 26 * 115, len(st["script"].split())

# revision of a long script also goes batch by batch, keeping the title
calls.clear()
B.AgentBrain._call_llm = staticmethod(lambda agent, messages, temperature=0.7: calls.append(messages[-1]["content"]) or
                                      "\n\n".join(f"[SHOW: fixed {k}]\n" + " ".join(["r"] * 100) for k in range(6)))
st2 = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
       "feedback": ["make scene 3 funnier"], "checkpoint": {"script": st["script"], "title": "Twenty Minutes"},
       "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_script(st2, {"target_words": 3000})
assert len(calls) == 5 and all("make scene 3 funnier" in c for c in calls) and "scenes 7-12 of 26" in calls[1]
assert st2["title"] == "Twenty Minutes" and st2["scene_count"] == 30

# outline that does not parse → single call, as before
calls.clear()
B.AgentBrain._call_llm = staticmethod(lambda agent, messages, temperature=0.7: calls.append(messages[-1]["content"]) or
                                      "TITLE: T\n\n[SHOW: one]\n" + " ".join(["w"] * 3000))
st3 = {"task_id": "t", "agent": A(), "corpus": [{"title": "x", "url": "u", "content": "c" * 50}],
       "_say": lambda *a: None, "_cancelled": lambda: False}
P._step_script(st3, {"target_words": 3000})
assert len(calls) == 2 and st3["scene_count"] == 1, "outline unusable → one full write"
print("10 chunked   : 3000 words = outline + 5 batches of ≤6 scenes, each under 4096 tokens; revision batched; bad outline → single call")
# 11. Slow box: wait on PROGRESS, not on the clock; Retry re-attaches to the running export
import time as _time
P.POLL_SEC = 0
P._poll_studio = _REAL_POLL          # groups 5/6 mocked it
# (a) status keeps changing → a 1800s-style stall budget never fires; the absolute cap does
import itertools as _it
ticks = _it.count()
P._get = lambda path, timeout=60: {"status": "running", "done": next(ticks), "total": 10_000, "current_shot": "Shot"}
st = {"_cancelled": lambda: False, "_say": lambda *a: None}
t0 = _time.time()
try:
    P._poll_studio("/x", 0.5, st, "render", done_statuses=("completed",), max_wait=0.15)
    raise SystemExit("must hit the absolute cap")
except RuntimeError as e:
    assert str(e).startswith("Gave up after 0.15s") and "running" in str(e), e
assert _time.time() - t0 < 0.5, "progress kept it alive right up to the cap, not the stall budget"
# (b) frozen status → stall budget fires, message shows what it last saw
P._get = lambda path, timeout=60: {"status": "running", "done": 3, "total": 32, "current_shot": "Shot 4/32: Dawn"}
try:
    P._poll_studio("/x", 0.1, st, "render", done_statuses=("completed",))
    raise SystemExit("must stall")
except RuntimeError as e:
    assert str(e).startswith("No progress for 0.1s") and "3/32" in str(e) and "Dawn" in str(e), e
# (c) Studio restarted: 404 → says so instead of spinning
def _404(path, timeout=60):
    raise RuntimeError(f"{path} → HTTP 404: Task not found")
P._get = _404
try:
    P._poll_studio("/x", 5, st, "render")
    raise SystemExit("404 must raise")
except RuntimeError as e:
    assert "no longer knows this task" in str(e), e
# (d) a transient connection error is not a failure
seq = [OSError("connection refused"), {"status": "completed", "done": 100, "total": 100}]
def _flaky(path, timeout=60):
    x = seq.pop(0)
    if isinstance(x, Exception):
        raise x
    return x
P._get = _flaky
assert P._poll_studio("/x", 5, st, "render", done_statuses=("completed",))["status"] == "completed"
# (e) render: an export the last attempt started is re-used, no second ffmpeg
posts, cks = [], []
P._post = lambda path, payload, timeout=300: posts.append(path) or {"task_id": "new1"}
P._read_checkpoint = lambda task_id: {"drama_id": 9, "episode_id": 9, "export_task_id": "old7"}
P._write_checkpoint = lambda task_id, data: cks.append(dict(data))
P.media_seconds = lambda path: 1200.0
gets = []
def _get_render(path, timeout=60):
    gets.append(path)
    if path.endswith("/status/old7"):
        return {"status": "running", "done": 90, "total": 100} if len(gets) < 3 else {"status": "completed", "done": 100, "total": 100}
    return {"video_url": "/tmp/ep9.mp4"}
P._get = _get_render
st = {"task_id": "t", "episode_id": 9, "script": " ".join(["w"] * 3000),
      "checkpoint": {"drama_id": 9, "episode_id": 9, "export_task_id": "old7"},
      "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_render(st, {})
assert posts == [] and st["video_seconds"] == 1200.0, (posts, st.get("video_seconds"))
assert P.render_max_wait(st) == 3000 * 60 / 150 * 20 == 24000, P.render_max_wait(st)
# (f) old export unknown (Studio restarted) → start a new one and checkpoint its id WITHOUT losing the rest
gets.clear()
def _get_render2(path, timeout=60):
    gets.append(path)
    if path.endswith("/status/old7"):
        raise RuntimeError(path + " → HTTP 404: Task not found")
    if path.endswith("/status/new1"):
        return {"status": "completed", "done": 100, "total": 100}
    return {"video_url": "/tmp/ep9.mp4"}
P._get = _get_render2
st = {"task_id": "t", "episode_id": 9, "script": " ".join(["w"] * 300),
      "checkpoint": {"drama_id": 9, "episode_id": 9, "export_task_id": "old7"},
      "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_render(st, {})
assert posts == ["/api/v1/studio/episodes/9/export-ffmpeg"], posts
assert cks[-1] == {"drama_id": 9, "episode_id": 9, "export_task_id": "new1"}, cks[-1]
assert P.render_max_wait(st) == 4 * 3600, "short video → 4h floor"
# (g) a stall in render carries the re-attach hint
P._get = lambda path, timeout=60: ({"status": "running", "done": 1, "total": 100} if "/status/" in path else {})
P._running_export = lambda tid: ""
P.TIMEOUTS["render"] = 0.1
st = {"task_id": "t", "episode_id": 9, "script": "a b", "checkpoint": {},
      "_cancelled": lambda: False, "_say": lambda *a: None}
try:
    P._step_render(st, {})
    raise SystemExit("must stall")
except RuntimeError as e:
    assert "No progress for 0.1s" in str(e) and "Retry re-attaches" in str(e), e
P.TIMEOUTS["render"] = 1800
print("11 slow box  : stall budget resets on progress; 404 → restarted; transient error tolerated; Retry re-attaches to the running export; cap scales with length")
print()
print("ALL 11 GROUPS PASSED")
