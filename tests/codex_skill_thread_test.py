# -*- coding: utf-8 -*-
"""Task Board #4 (7/11/2026): «[Codex Error] wrong_thread: Codex model was called from the server event loop» — skill
SOP gọi model ĐỒNG BỘ ngay trên vòng sự kiện; câu lỗi về như kết quả ⇒ bước run_skill báo success, task sang review.

  A. autonomous_run (skill SOP + vòng ReAct) gọi _call_llm ở LUỒNG PHỤ, không trên vòng sự kiện
  B. codex_gpt.llm.complete_sync: trên vòng sự kiện của server → wrong_thread; từ luồng phụ → chạy được
  C. executor: skill trả «[Codex Error] …» / «❌ …» → bước run_skill = error, task ném lỗi (failed), kèm nguyên nhân
  D. việc TẠO video: không có file video → lỗi; có file video thật → success kèm đường dẫn
  E. skill thường trả chữ thật → success như cũ

Run:  python tests/codex_skill_thread_test.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.core.brain import AgentBrain  # noqa: E402
from tubecli.extensions.codex import executor as E  # noqa: E402
from tubecli.extensions.codex_gpt import llm as L  # noqa: E402

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  → {detail}"))


AGENT = {"id": "a500k", "name": "500k", "model": "codex/gpt-5"}
WRONG = "[Codex Error] wrong_thread: Codex model was called from the server event loop; use a worker thread."

# ── A ─────────────────────────────────────────────────────────────────────────────────────────────────────────
_orig_call = AgentBrain._call_llm
seen = []


def fake_call(agent, messages, temperature=0.7, *a, **k):
    try:
        asyncio.get_running_loop()
        on_loop = True
    except RuntimeError:
        on_loop = False
    seen.append((threading.get_ident(), on_loop))
    return "Done: followed the SOP."


AgentBrain._call_llm = staticmethod(fake_call)


async def run_sop():
    main = threading.get_ident()
    out = await AgentBrain.autonomous_run("make it", AGENT, {"name": "SOP", "skill_format": "markdown",
                                                            "workflow_data": {"sop": "1. do it"}})
    return main, out


seen.clear()
main, out = asyncio.run(run_sop())
check("A1 skill SOP: _call_llm chạy ở luồng phụ (không có vòng sự kiện đang chạy)",
      seen and seen[0][0] != main and seen[0][1] is False, seen)
check("A2 skill SOP: vẫn trả câu trả lời của model", out == "Done: followed the SOP.", out)


async def run_react():
    main = threading.get_ident()
    out = await AgentBrain.autonomous_run("make it", AGENT, {"name": "Flow", "skill_format": "workflow",
                                                            "workflow_data": {"nodes": [{"id": "n1", "type": "x"}]}})
    return main, out


async def _linear_fails(*a, **k):
    raise RuntimeError("linear failed")   # → rơi xuống vòng ReAct


_orig_linear = AgentBrain.run_workflow_linear
AgentBrain.run_workflow_linear = staticmethod(_linear_fails)
seen.clear()
try:
    main, out = asyncio.run(run_react())
    check("A3 vòng ReAct: _call_llm ở luồng phụ", seen and all(t != main and not lp for t, lp in seen), seen)
except Exception as e:  # noqa: BLE001
    check("A3 vòng ReAct: _call_llm ở luồng phụ", False, repr(e))
AgentBrain.run_workflow_linear = _orig_linear

AgentBrain._call_llm = staticmethod(lambda agent, messages, temperature=0.7, *a, **k: WRONG)
_, out = asyncio.run(run_sop())
check("A4 câu lỗi của model trả NGUYÊN (bên gọi nhận ra lỗi)", out == WRONG, out)
AgentBrain._call_llm = _orig_call

# ── B ─────────────────────────────────────────────────────────────────────────────────────────────────────────
from tubecli.extensions.codex_gpt.service import service as SVC  # noqa: E402

_orig_complete, _orig_loop = L.complete, getattr(SVC, "loop", None)


async def fake_complete(messages, model="", timeout=0):
    return {"content": "ok from codex"}


L.complete = fake_complete


async def server():
    SVC.loop = asyncio.get_running_loop()
    try:
        L.complete_sync([{"role": "user", "content": "hi"}])
        on_loop = None
    except L.CodexLLMError as e:
        on_loop = str(e)
    off = await asyncio.to_thread(L.complete_sync, [{"role": "user", "content": "hi"}])
    return on_loop, off


on_loop, off = asyncio.run(server())
check("B1 gọi trên vòng sự kiện của server → wrong_thread (tái hiện lỗi #4)", on_loop and "wrong_thread" in on_loop
      or "event loop" in str(on_loop), on_loop)
check("B2 gọi từ luồng phụ (asyncio.to_thread) → chạy được", (off or {}).get("content") == "ok from codex", off)
L.complete, SVC.loop = _orig_complete, _orig_loop

# ── C–E ───────────────────────────────────────────────────────────────────────────────────────────────────────


class _Agent:
    name = "500k"

    def to_dict(self):
        return dict(AGENT)


def run_task(task, skill_out, skill=None):
    steps = []
    skill = skill or {"id": "s1", "name": "Content Video SOP"}
    E._resolve_agent = lambda t: _Agent()
    E._select_skills = lambda goal, ag: [skill]
    E._get_skill = lambda sid: skill
    AgentBrain.chat_targeted = staticmethod(lambda *a, **k: {"reply": "ok", "action": "run_skill",
                                                            "skill_id": "s1", "skill_input": "go"})

    async def fake_run(message, agent, sk):
        return skill_out

    AgentBrain.autonomous_run = staticmethod(fake_run)
    report = lambda step, status, msg="", **k: steps.append((step, status, msg))  # noqa: E731
    try:
        out = asyncio.run(E._execute_agent(task, report, lambda: False))
        err = None
    except Exception as e:  # noqa: BLE001
        out, err = None, str(e)
    return out, err, steps


_orig_brain = (AgentBrain.chat_targeted, AgentBrain.autonomous_run)
PLAIN = {"id": "t4", "goal": "Summarise the agent's corpus", "title": "Summary"}
out, err, steps = run_task(PLAIN, WRONG)
run = [s for s in steps if s[0] == "run_skill"]
check("C1 «[Codex Error] wrong_thread» → task ném lỗi (failed) kèm nguyên nhân", err and "wrong_thread" in err, err)
check("C2 bước run_skill = error, KHÔNG có success", run and run[-1][1] == "error"
      and not any(s[1] == "success" for s in run), run)
out, err, steps = run_task(PLAIN, "❌ Extension action failed (HTTP 500): boom")
check("C3 «❌ …» cũng là lỗi", err and "HTTP 500" in err, err)
out, err, steps = run_task(PLAIN, "⚠️ *[Auto-Failover: codex → 9router]*\n[OpenAI Error] 402 quota")
check("C4 lỗi có tiền tố Auto-Failover cũng là lỗi", err and "402" in err, err)

VIDEO = {"id": "t4", "goal": "Create a video from 3_done.srt and 3_done.wav with template Cartoon News Recap",
         "title": "Video #4"}
out, err, steps = run_task(VIDEO, "The video has been created successfully! You can find it in your library.")
check("D1 việc tạo video, skill chỉ nói «đã xong» mà không có file → lỗi", err and "no video file" in err, err)
check("D2 ... bước run_skill = error", [s for s in steps if s[0] == "run_skill"][-1][1] == "error", steps)
check("D3 làn video cũng là việc tạo video", E.wants_video({"lane": "video", "goal": "x"}))
check("D4 «tóm tắt video» KHÔNG phải tạo video", not E.wants_video({"goal": "Tóm tắt video này giúp tôi"}))

tmp = tempfile.mkdtemp(prefix="skill_video_")
mp4 = os.path.join(tmp, "out video.mp4")
ff = shutil.which("ffmpeg")
if ff:
    import subprocess
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", mp4], capture_output=True, timeout=60)
if not os.path.isfile(mp4) or os.path.getsize(mp4) < 10_000:
    with open(mp4, "wb") as f:
        f.write(b"\0" * 20_000)
    _which = shutil.which
    shutil.which = lambda name, *a, **k: None if name == "ffprobe" else _which(name, *a, **k)
out, err, steps = run_task(VIDEO, f"Rendered: {mp4} (1 s)")
check("D5 có file video thật → success, ghi đường dẫn", err is None and steps[-1][1] == "success"
      and mp4 in steps[-1][2], (err, steps[-1:]))
check("D6 find_video: khớp bắt đầu sớm («and/or C:…») vẫn tìm ra file", E.find_video(f"and/or {mp4}") == mp4)
bad = os.path.join(tmp, "empty.mp4")
open(bad, "wb").close()
check("D7 file rỗng không phải video hợp lệ", E.find_video(f"Rendered: {bad}") == "")
shutil.rmtree(tmp, ignore_errors=True)

out, err, steps = run_task(PLAIN, "Here is the summary: three articles about rain.")
check("E1 skill thường → success như cũ", err is None and steps[-1] == ("run_skill", "success", "Skill finished")
      and out.startswith("Here is"), (err, steps[-1:]))
AgentBrain.chat_targeted, AgentBrain.autonomous_run = _orig_brain

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
