# -*- coding: utf-8 -*-
"""«Tạo video từ nội dung» dùng MODEL CỦA AGENT — không phải model riêng của Content Studio.

Bệnh (máy PC của user, 11/9/2026): agent chọn Gemini qua 9Router mà task chết
ngay bước kiểm năng lực, vì Content Studio tự cấu hình "deepseek-chat"; storyboard
cũng gọi model của Studio. Cam kết được canh ở đây:
  1. AgentBrain.openai_compat_params định tuyến y như _call_llm: provider nói rõ
     thắng, 9Router nhận theo tên, vendor/model hỏi danh mục 9Router; thiếu khoá → None.
  2. Pipeline gửi agent_id khi gọi storyboard.
  3. Bước kế hoạch không đòi AI của Studio; bước dựng chỉ bỏ qua nó khi Studio có cờ
     agent_model (Studio cũ vẫn vẽ storyboard bằng model riêng → vẫn phải chặn).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import requests  # noqa: E402

from tubecli.core import brain as B  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
import tubecli.extensions.cloud_api.extension as CA  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


KEYS = {}
CA.key_manager.get_active_key = lambda name: KEYS.get(name, "")
B.list_9router_models = lambda ttl=60.0: ["ag/gemini-3.8-flash", "openai/gpt-oss-120b"]
R = B.AgentBrain.openai_compat_params
R9 = B._9R_BASE

print("── quy model của agent ra (địa chỉ, khoá, tên) ────────────────")
ok(R({"model": "ag/gemini-3.8-flash"}) == (R9, "9router", "ag/gemini-3.8-flash"),
   "model 9Router (ag/) → localhost:20128, khoá giữ chỗ khi không có khoá", R({"model": "ag/gemini-3.8-flash"}))
KEYS["9router"] = "k9"
ok(R({"model": "kr/claude-sonnet-4-6"}) == (R9, "k9", "kr/claude-sonnet-4-6"), "khoá 9Router thật được dùng khi có")
ok((R({"model": "openai/gpt-oss-120b"}) or ("",))[0] == R9, "vendor/model mà 9Router CÓ phục vụ → 9Router, không sang OpenRouter")
ok(R({"model": "google/gemini-2.5-flash"}) is None, "vendor/model 9Router không có + thiếu khoá OpenRouter → None")
KEYS["openrouter"] = "or"
ok(R({"model": "google/gemini-2.5-flash"}) == ("https://openrouter.ai/api/v1", "or", "google/gemini-2.5-flash"),
   "…có khoá OpenRouter thì sang OpenRouter")
ok(R({"model": "gemini-2.5-flash"}) is None, "Gemini thiếu khoá → None (người gọi lui về cấu hình riêng)")
KEYS["gemini"] = "g"
ok(R({"model": "gemini-2.5-flash"}) == ("https://generativelanguage.googleapis.com/v1beta/openai", "g", "gemini-2.5-flash"),
   "Gemini → lớp tương thích OpenAI của Google")
ok((R({"model": "gemini-2.5-flash", "cloud_api_keys": {"gemini": "own"}}) or ("", ""))[1] == "own",
   "khoá riêng của agent thắng kho chung")
ok((R({"model": "deepseek-chat", "provider": "9router"}) or ("",))[0] == R9, "provider nói rõ thắng đoán theo tên")
KEYS["deepseek"] = "d"
ok(R({"model": "deepseek-v4-flash", "provider": "deepseek"}) == ("https://api.deepseek.com/v1", "d", "deepseek-v4-flash"),
   "DeepSeek")
ok(R({"model": "qwen2.5:latest"}) == ("http://localhost:11434/v1", "ollama", "qwen2.5:latest"), "Ollama (tên có dấu hai chấm)")
ok(R({"model": "@cf/meta/llama-3.3-70b"}) is None and R({"model": "x", "provider": "cloudflare"}) is None,
   "Cloudflare không gọi được theo lối chuẩn OpenAI → None")
ok(R({"model": "gpt-4o"}) is None, "OpenAI thiếu khoá → None")
ok(R({"model": "gpt-4o", "provider": "chatgpt", "cloud_api_keys": {"openai": "o"}}) == ("https://api.openai.com/v1", "o", "gpt-4o"),
   "provider 'chatgpt' = openai")

print("── storyboard gửi agent_id ────────────────────────────────────")
sent = {}


class _Resp:
    status_code = 200
    text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        yield 'data: {"event": "status", "message": "AI: ag/gemini-3.8-flash (agent)"}'
        yield "data: [DONE]"


def _post(url, json=None, **k):
    sent.update(url=url, json=json)
    return _Resp()


requests.post = _post


class Agent:
    id, name, model = "a7", "MC", "ag/gemini-3.8-flash"


said = []
P._stream_storyboard(12, {"agent": Agent(), "_cancelled": lambda: False, "_say": lambda *a: said.append(a)})
ok(sent.get("json") == {"append": False, "agent_id": "a7"}, "POST storyboard mang agent_id", sent.get("json"))
ok(any("(agent)" in str(a) for a in said), "dòng 'AI: … (agent)' của Studio hiện lên thẻ bước", said)

print("── bước kiểm năng lực ─────────────────────────────────────────")


def caps(text_ok, agent_flag):
    t = {"ok": text_ok, "label": "Văn bản", "detail": "deepseek-chat · http://localhost:20128/v1",
         "fix": "Bật lại dịch vụ ở http://localhost:20128/v1"}
    if agent_flag:
        t["agent_model"] = True
    return {"text": t, "image": {"ok": True, "detail": "API · cloudflare"},
            "assembly": {"ok": True, "detail": "ffmpeg"}}


def cap_run(needs, c):
    said.clear()
    P.studio_capabilities = lambda: c
    st = {"agent": Agent(), "_needs": needs, "warnings": [], "_say": lambda *a: said.append(a)}
    try:
        P._step_capabilities(st, {})
        return "ok"
    except RuntimeError as e:
        return str(e)


ok(cap_run((), caps(False, False)) == "ok", "kế hoạch: AI của Studio hỏng mà KHÔNG chặn (kịch bản do agent viết)")
ok(said and "ag/gemini-3.8-flash (agent)" in str(said[-1]), "…thẻ bước nói đúng model sẽ viết: của agent", said)
ok(cap_run(("text", "image", "assembly"), caps(False, True)) == "ok",
   "dựng + Studio có cờ agent_model: AI của Studio hỏng không chặn")
ok(said and "(agent)" in str(said[-1]), "…và thẻ bước nói model của agent", said)
r = cap_run(("text", "image", "assembly"), caps(False, False))
ok("not ready (text)" in r, "dựng + Studio CŨ (không cờ): vẫn chặn — storyboard của nó còn dùng model riêng", r)
cap_run(("text", "image", "assembly"), caps(True, False))
ok(said and "deepseek-chat" in str(said[-1]), "Studio cũ chạy được: thẻ bước nói model của Studio (vì nó vẽ storyboard)", said)
src = open(P.__file__, encoding="utf-8").read()
ok(src.count("needs=())") == 1, "run_plan không đòi AI của Studio (needs=())")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
