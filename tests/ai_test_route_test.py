# -*- coding: utf-8 -*-
"""POST /api/v1/ai/test — gọi thử model chat cho nút «Thử gọi» của Flow (26/9/2026).

Cam kết (mọi lời gọi model giả, không mạng):
  1. Trả lời thật → ok + seconds + reply cắt ngắn.
  2. Brain trả CHUỖI lỗi «[OpenAI Error] …» (không ném) → ok=False, message = chuỗi ấy — đúng ca ag/gemini-3.8-flash 403.
  3. Brain ném → ok=False, message = lỗi; trả lời rỗng → ok=False.
  4. Không có model và máy không có mặc định → ok=False, không gọi brain; provider truyền xuống agent dict.
Run:  python tests/ai_test_route_test.py   (exit 0 = pass)
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.api import ai_routes as R                    # noqa: E402
from tubecli.core.brain import AgentBrain                  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


CALLS = []


def fake(reply):
    def _call(agent, messages, temperature=0.7, max_tokens=None):
        CALLS.append((dict(agent), list(messages), temperature, max_tokens))
        if isinstance(reply, Exception):
            raise reply
        return reply
    return _call


orig = AgentBrain._call_llm
try:
    AgentBrain._call_llm = staticmethod(fake("OK"))
    r = asyncio.run(R.test_model(R.TestRequest(model="ag/gemini-3.8-flash")))
    ok(r["ok"] is True and r["model"] == "ag/gemini-3.8-flash" and r["reply"] == "OK" and isinstance(r["seconds"], float),
       "trả lời thật → ok + reply + seconds", r)
    ok(CALLS and CALLS[-1][0] == {"model": "ag/gemini-3.8-flash"} and CALLS[-1][3] == 8 and CALLS[-1][2] == 0.0
       and "OK" in CALLS[-1][1][0]["content"], "gọi brain với đúng model, câu hỏi 1 từ, max_tokens 8", CALLS[-1:])

    AgentBrain._call_llm = staticmethod(fake("[OpenAI Error] Error code: 503 - {'error': {'message': '[antigravity/gemini-3.8-flash] [403]: HTTP 403 (reset after 19s)'}}"))
    r = asyncio.run(R.test_model(R.TestRequest(model="ag/gemini-3.8-flash")))
    ok(r["ok"] is False and "403" in r["message"] and r["message"].startswith("[OpenAI Error]"), "chuỗi lỗi của brain → hỏng, giữ lý do", r)

    AgentBrain._call_llm = staticmethod(fake(RuntimeError("boom")))
    r = asyncio.run(R.test_model(R.TestRequest(model="x")))
    ok(r["ok"] is False and r["message"] == "boom", "brain ném → hỏng với lý do", r)

    AgentBrain._call_llm = staticmethod(fake("   "))
    r = asyncio.run(R.test_model(R.TestRequest(model="x")))
    ok(r["ok"] is False and "empty" in r["message"], "trả lời rỗng → hỏng", r)

    CALLS.clear()
    AgentBrain._call_llm = staticmethod(fake("OK"))
    r = asyncio.run(R.test_model(R.TestRequest(model="cx/gpt-5", provider="9Router")))
    ok(CALLS[-1][0] == {"model": "cx/gpt-5", "provider": "9router"}, "provider truyền xuống agent dict (chữ thường)", CALLS[-1][0])

    import tubecli.config as C
    old_resolve = C.resolve_browser_ai_model
    C.resolve_browser_ai_model = lambda agent=None: ""
    CALLS.clear()
    try:
        r = asyncio.run(R.test_model(R.TestRequest(model="")))
    finally:
        C.resolve_browser_ai_model = old_resolve
    ok(r["ok"] is False and not CALLS and "pick a model" in r["message"], "không có model → không gọi brain", r)
    ok(R.is_llm_error("[Gemini Error] x") and R.is_llm_error("  [Error] y") and not R.is_llm_error("OK [Error]"),
       "nhận diện chuỗi lỗi ở ĐẦU câu, không phải chỗ khác")
finally:
    AgentBrain._call_llm = orig

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
