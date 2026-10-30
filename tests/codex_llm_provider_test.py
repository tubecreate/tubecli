"""Codex (ChatGPT) làm MODEL — provider «codex» (user 30/10/2026: «thêm provider lựa chọn codex chatgpt»).

Chạy:  python tests/codex_llm_provider_test.py      (mã thoát 0 = đạt)

Khoá: luồng tạm ephemeral + baseInstructions + read-only + never + config tắt MỌI MCP trong config.toml, shell,
apply_patch, web; câu trả lời = agentMessage cuối; sự kiện không phát lên trang; hết hạn mức → đổi tài khoản MỘT lần
rồi chạy lại (không gửi «tiếp tục»); quá giờ → interrupt; công cụ TubeCLI bị từ chối cho luồng tạm; brain định tuyến
`codex/…` + provider «codex», agent công khai trên Town bị từ chối, Codex lỗi → dự phòng bằng tên trung tính;
cổng chuẩn OpenAI chỉ loopback; Cloud API liệt kê «Codex (ChatGPT)» không khoá, không vào hộp thêm khoá.

App-server là bản GIẢ (không tốn hạn mức tài khoản thật). Dữ liệu Codex GPT trỏ thư mục tạm (TUBECLI_CODEX_GPT_DIR).
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="tubecli_codex_llm_")
os.environ["TUBECLI_CODEX_GPT_DIR"] = TMP

from tubecli.extensions.codex_gpt import llm  # noqa: E402
from tubecli.extensions.codex_gpt import service as svc_mod  # noqa: E402
from tubecli.extensions.codex_gpt.service import service  # noqa: E402

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failures += 1


check("dữ liệu Codex GPT ở thư mục tạm", str(service.root).startswith(TMP), service.root)

# ── 1. hàm thuần ─────────────────────────────────────────────────────────────
check("is_codex_model / bare_model", llm.is_codex_model("codex/gpt-5.1") and not llm.is_codex_model("gpt-5")
      and llm.bare_model("codex/gpt-5.1") == "gpt-5.1" and llm.bare_model("codex/default") == "" and llm.bare_model("codex/") == "")
ins, pr = llm.flatten([{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}])
check("flatten 1 lượt: system vào lời dặn (sau luật nền), user gửi nguyên văn",
      ins.startswith(llm.BASE_RULES) and ins.endswith("Be brief.") and pr == "Hi", (ins[-40:], pr))
ins, pr = llm.flatten([{"role": "user", "content": [{"type": "text", "text": "A"}, {"type": "image_url", "image_url": {}}]},
                       {"role": "assistant", "content": "B"}, {"role": "user", "content": "C"}])
check("flatten nhiều lượt → bản ghi hội thoại, bỏ phần ảnh", pr == "User: A\n\nAssistant: B\n\nUser: C\n\nAssistant:", pr)
TOML = '[mcp_servers.tubecli]\ncommand = "py"\n[mcp_servers.tubecli.env]\nX = "1"\n[mcp_servers."my-db"]\ncommand = "x"\n[features]\n'
check("mcp_server_names đọc mọi máy chủ MCP (kể cả tên có ngoặc, không lặp bảng con)",
      llm.mcp_server_names(TOML) == ["tubecli", "my-db"], llm.mcp_server_names(TOML))
cfg = llm.thread_config(TOML)
check("thread_config tắt MCP + shell + apply_patch + web",
      cfg == {"features": {"shell_tool": False, "apply_patch_freeform": False}, "web_search": "disabled",
              "mcp_servers": {"tubecli": {"enabled": False}, "my-db": {"enabled": False}}}, cfg)
check("không có MCP nào → không ghi đè mcp_servers (bảng rỗng có thể làm hỏng thread/start)",
      "mcp_servers" not in llm.thread_config("[features]\n"))

# ── 2. app-server GIẢ ────────────────────────────────────────────────────────
service.home.mkdir(parents=True, exist_ok=True)
(service.home / "config.toml").write_text(TOML, encoding="utf-8")


class FakeBridge:
    def __init__(self, script):
        self.calls = []
        self.script = script          # list: mỗi lượt = ("ok", text) | ("limit",) | ("hang",) | ("fail", msg)
        self.n = 0
        self.alive = True

    async def request(self, method, params=None, timeout=120.0):
        self.calls.append((method, params))
        if method == "thread/start":
            self.n += 1
            return {"thread": {"id": f"t{self.n}", "ephemeral": True}}
        if method == "turn/start":
            tid = params["threadId"]
            kind = self.script.pop(0)
            loop = asyncio.get_running_loop()

            async def play():
                await service._on_notify("turn/started", {"threadId": tid, "turn": {"id": "u" + tid}})
                if kind[0] == "hang":
                    return
                if kind[0] == "ok":
                    await service._on_notify("item/completed", {"threadId": tid, "item": {"type": "agentMessage", "text": "draft"}})
                    await service._on_notify("item/completed", {"threadId": tid, "item": {"type": "reasoning", "text": "x"}})
                    await service._on_notify("item/completed", {"threadId": tid, "item": {"type": "agentMessage", "text": kind[1]}})
                    await service._on_notify("turn/completed", {"threadId": tid, "turn": {"id": "u" + tid, "status": "completed"}})
                elif kind[0] == "limit":
                    await service._on_notify("turn/completed", {"threadId": tid, "turn": {"id": "u" + tid, "status": "failed",
                        "error": {"message": "You've hit your usage limit", "codexErrorInfo": "usageLimitExceeded"}}})
                else:
                    await service._on_notify("turn/completed", {"threadId": tid, "turn": {"id": "u" + tid, "status": "failed",
                        "error": {"message": kind[1]}}})
            loop.call_later(0.05, lambda: asyncio.ensure_future(play()))
            return {"turn": {"id": "u" + tid}}
        if method == "turn/interrupt":
            return {}
        return {}


def run(coro):
    return asyncio.run(coro)


svc_mod.cli.command = lambda: ["codex-fake"]          # «đã cài»
SENT = []


async def fake_send(*a, **k):
    SENT.append((a, k))
    return {}

service.send = fake_send
UI = asyncio.Queue  # placeholder


async def case_ok():
    fb = FakeBridge([("ok", "Final answer")])

    async def eb():
        return fb
    service.ensure_bridge = eb
    ui_q = service.subscribe()
    r = await llm.complete([{"role": "system", "content": "Sys"}, {"role": "user", "content": "Q"}], "codex/gpt-test")
    leaked = []
    while not ui_q.empty():
        leaked.append(ui_q.get_nowait())
    service.unsubscribe(ui_q)
    return fb, r, leaked


fb, r, leaked = run(case_ok())
ts = dict(fb.calls[0][1])
check("trả agentMessage CUỐI + tên model codex/…", r == {"text": "Final answer", "model": "codex/gpt-test"}, r)
check("thread/start: ephemeral, read-only, never, baseInstructions = luật nền + system, serviceName tubecli-llm",
      ts.get("ephemeral") is True and ts.get("sandbox") == "read-only" and ts.get("approvalPolicy") == "never"
      and ts.get("baseInstructions", "").endswith("Sys") and ts.get("serviceName") == "tubecli-llm", ts)
check("thread/start: config tắt MCP «tubecli» + «my-db», shell, apply_patch, web; model không tiền tố",
      ts.get("config") == llm.thread_config(TOML) and ts.get("model") == "gpt-test", ts.get("config"))
check("cwd = thư mục trống riêng (llm-cwd) trong dữ liệu Codex GPT", str(ts.get("cwd", "")).startswith(TMP) and ts["cwd"].endswith("llm-cwd"))
tu = dict(fb.calls[1][1])
check("turn/start: never + nguyên văn câu hỏi", tu.get("approvalPolicy") == "never" and tu["input"] == [{"type": "text", "text": "Q"}])
check("sự kiện luồng tạm KHÔNG phát lên trang Codex GPT", leaked == [], leaked[:2])
check("dọn hàng đợi + lượt đang chạy sau khi xong", not service.llm_sinks and "t1" not in service.active_turns)

# model mặc định của tài khoản
fb2 = FakeBridge([("ok", "ok2")])


async def eb2():
    return fb2
service.ensure_bridge = eb2
r = run(llm.complete([{"role": "user", "content": "x"}], "codex/default"))
check("codex/default → không gửi model (dùng model mặc định của tài khoản)",
      "model" not in fb2.calls[0][1] and "model" not in fb2.calls[1][1] and r["model"] == "codex/default", fb2.calls[:2])

# hết hạn mức → đổi tài khoản 1 lần, chạy lại luồng mới, KHÔNG gửi «tiếp tục»
SWITCHES = []


async def sw_ok():
    SWITCHES.append(1)
    return True
service.llm_limit_switch = sw_ok
fb3 = FakeBridge([("limit",), ("ok", "after switch")])


async def eb3():
    return fb3
service.ensure_bridge = eb3
SENT.clear()


async def limit_case():
    r = await llm.complete([{"role": "user", "content": "x"}], "codex/default")
    await asyncio.sleep(0.2)            # cho _handle_limit (ensure_future) kịp chạy nếu có
    return r
r = run(limit_case())
check("hết hạn mức → đổi tài khoản MỘT lần, chạy lại trên luồng MỚI, trả kết quả",
      r["text"] == "after switch" and SWITCHES == [1] and [c[1]["threadId"] for c in fb3.calls if c[0] == "turn/start"] == ["t1", "t2"], fb3.calls)
check("luồng tạm KHÔNG nhận «tiếp tục» của chat (service.send không được gọi)", SENT == [], SENT)


async def sw_no():
    return False
service.llm_limit_switch = sw_no
fb4 = FakeBridge([("limit",)])


async def eb4():
    return fb4
service.ensure_bridge = eb4
try:
    run(llm.complete([{"role": "user", "content": "x"}]))
    check("mọi tài khoản hết hạn mức → CodexLLMError usage_limit", False, "không ném")
except llm.CodexLLMError as e:
    check("mọi tài khoản hết hạn mức → CodexLLMError usage_limit", e.code == "usage_limit", e.code)

fb5 = FakeBridge([("hang",)])


async def eb5():
    return fb5
service.ensure_bridge = eb5
try:
    run(llm.complete([{"role": "user", "content": "x"}], timeout=1))
    check("quá giờ → timeout + turn/interrupt", False, "không ném")
except llm.CodexLLMError as e:
    check("quá giờ → timeout + turn/interrupt", e.code == "timeout" and any(c[0] == "turn/interrupt" for c in fb5.calls), (e.code, fb5.calls))

fb6 = FakeBridge([("fail", "model not supported with ChatGPT account")])


async def eb6():
    return fb6
service.ensure_bridge = eb6
try:
    run(llm.complete([{"role": "user", "content": "x"}], "codex/gpt-6.1-sol"))
    check("lượt hỏng → CodexLLMError kèm lý do của Codex", False, "không ném")
except llm.CodexLLMError as e:
    check("lượt hỏng → CodexLLMError kèm lý do của Codex", e.code == "turn_failed" and "not supported" in e.message, e.message)

try:
    run(llm.complete([{"role": "system", "content": "only system"}]))
    check("không có câu hỏi → empty, không mở luồng", False, "không ném")
except llm.CodexLLMError as e:
    check("không có câu hỏi → empty, không mở luồng", e.code == "empty")

# công cụ TubeCLI bị từ chối cho luồng tạm
service.llm_threads.add("tool-thread")
service.tool_items["it1"] = {"thread": "tool-thread", "tool": "files_write", "at": 9e9, "args": {"a": 1}}
ok, why, tid = run(service.tool_approval("files_write", "d", {"a": 1}))
check("tool_approval từ chối công cụ cho luồng của Codex-làm-model", ok is False and tid == "tool-thread" and "not available" in why, (ok, why))
service.tool_items.clear()

# ── 3. complete_sync: luồng phụ ↔ vòng sự kiện ───────────────────────────────
loop = asyncio.new_event_loop()
th = threading.Thread(target=loop.run_forever, daemon=True)
th.start()
service.loop = loop
fb7 = FakeBridge([("ok", "from worker")])


async def eb7():
    return fb7
service.ensure_bridge = eb7
r = llm.complete_sync([{"role": "user", "content": "x"}], "codex/default", timeout=20)
check("complete_sync từ luồng phụ chạy trên vòng sự kiện của server", r["text"] == "from worker", r)
fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop)
fut.result(5)


async def on_loop():
    try:
        llm.complete_sync([{"role": "user", "content": "x"}])
        return "no error"
    except llm.CodexLLMError as e:
        return e.code
code = asyncio.run_coroutine_threadsafe(on_loop(), loop).result(10)
check("gọi complete_sync NGAY trên vòng sự kiện → wrong_thread (không treo server)", code == "wrong_thread", code)
service.loop = None
try:
    llm.complete_sync([{"role": "user", "content": "x"}])
    check("chưa có vòng sự kiện → not_ready", False, "không ném")
except llm.CodexLLMError as e:
    check("chưa có vòng sự kiện → not_ready", e.code == "not_ready")
service.loop = loop

# ── 4. brain ─────────────────────────────────────────────────────────────────
from tubecli.core import brain as B  # noqa: E402
CALLS = []


def fake_sync(messages, model="", timeout=300):
    CALLS.append(model)
    return {"text": f"codex says ({model})", "model": model}
llm.complete_sync = fake_sync
out = B.AgentBrain._call_llm({"id": "a-private", "model": "codex/gpt-test"}, [{"role": "user", "content": "hi"}])
check("brain: tên codex/… → Codex", out == "codex says (codex/gpt-test)" and CALLS == ["codex/gpt-test"], out)
CALLS.clear()
out = B.AgentBrain._call_llm({"id": "a2", "model": "codex/default", "provider": "codex"}, [{"role": "user", "content": "hi"}])
check("brain: provider «codex» → Codex", CALLS == ["codex/default"], out)
check("_call_provider('codex') → Codex", B.AgentBrain._call_provider("codex", "codex/x", {}, [{"role": "user", "content": "q"}]).startswith("codex says"))
p = B.AgentBrain.openai_compat_params({"model": "codex/gpt-test"})
check("openai_compat_params → cổng OpenAI của chính máy (/api/v1/codex-gpt/v1)",
      p and p[0].startswith("http://127.0.0.1:") and p[0].endswith("/api/v1/codex-gpt/v1") and p[1:] == ("codex", "codex/gpt-test"), p)

from tubecli.core import public_agents  # noqa: E402
_orig_gs = public_agents.get_settings
public_agents.get_settings = lambda aid: {"enabled": True, "visibility": "public"} if aid == "a-public" else (
    {"enabled": True, "visibility": "private"} if aid == "a-mine" else {})
FAILOVER = []
_orig_fo = B.AgentBrain._failover_llm
B.AgentBrain._failover_llm = staticmethod(lambda fm, ck, msgs, t, err: FAILOVER.append((fm, err)) or "from gemini")
CALLS.clear()
out = B.AgentBrain._call_llm({"id": "a-public", "model": "codex/default"}, [{"role": "user", "content": "hi"}])
check("agent CÔNG KHAI trên Town → không gọi Codex, lui sang provider khác",
      CALLS == [] and out == "from gemini" and FAILOVER and FAILOVER[0][0] == "codex" and "Agent Town" in FAILOVER[0][1], (CALLS, out, FAILOVER))
CALLS.clear()
out = B.AgentBrain._call_llm({"id": "a-mine", "model": "codex/default"}, [{"role": "user", "content": "hi"}])
check("agent «chỉ mình tôi» (private) vẫn dùng Codex", CALLS == ["codex/default"], (CALLS, out))


def boom(messages, model="", timeout=300):
    raise llm.CodexLLMError("usage_limit", "all accounts limited")
llm.complete_sync = boom
FAILOVER.clear()
out = B.AgentBrain._call_llm({"id": "a-mine", "model": "codex/gpt-x"}, [{"role": "user", "content": "hi"}])
check("Codex lỗi → dự phòng với tên trung tính «codex» (không bị đoán là OpenRouter/OpenAI)",
      out == "from gemini" and FAILOVER and FAILOVER[0][0] == "codex" and "usage_limit" in FAILOVER[0][1], (out, FAILOVER))
B.AgentBrain._failover_llm = staticmethod(lambda fm, ck, msgs, t, err: "[Gemini Error] no key")
out = B.AgentBrain._call_llm({"id": "a-mine", "model": "codex/gpt-x"}, [{"role": "user", "content": "hi"}])
check("không provider nào cứu được → trả nguyên lỗi Codex", out.startswith("[Codex Error] usage_limit"), out)
B.AgentBrain._failover_llm = _orig_fo
public_agents.get_settings = _orig_gs

# ── 5. cổng chuẩn OpenAI: chỉ loopback ───────────────────────────────────────
from starlette.requests import Request  # noqa: E402
from tubecli.extensions.codex_gpt import routes as R  # noqa: E402


def req(host, body, headers=None):
    raw = json.dumps(body).encode()
    hdrs = [(b"content-type", b"application/json")] + [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": hdrs, "client": (host, 5555), "query_string": b""}
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request(scope, receive)


async def real_complete_stub(messages, model="", timeout=300):
    return {"text": "OAI answer", "model": model or "codex/default"}
llm.complete = real_complete_stub
resp = run(R.oai_chat(req("8.8.8.8", {"model": "codex/default", "messages": [{"role": "user", "content": "x"}]})))
check("chat/completions từ ngoài máy → 403", getattr(resp, "status_code", 0) == 403)
resp = run(R.oai_chat(req("127.0.0.1", {"messages": []}, {"x-forwarded-for": "1.2.3.4", "cf-connecting-ip": "1.2.3.4"})))
check("chat/completions qua tunnel/proxy (có header chuyển tiếp) → 403", getattr(resp, "status_code", 0) == 403, getattr(resp, "status_code", resp))
resp = run(R.oai_chat(req("127.0.0.1", {"model": "codex/gpt-test", "messages": [{"role": "user", "content": "x"}]})))
check("chat/completions loopback → dạng OpenAI", isinstance(resp, dict) and resp["choices"][0]["message"]["content"] == "OAI answer"
      and resp["model"] == "codex/gpt-test" and resp["object"] == "chat.completion", resp)


async def lim(messages, model="", timeout=300):
    raise llm.CodexLLMError("usage_limit", "limited")
llm.complete = lim
resp = run(R.oai_chat(req("127.0.0.1", {"messages": [{"role": "user", "content": "x"}]})))
check("hết hạn mức → HTTP 429 + mã codex", getattr(resp, "status_code", 0) == 429 and json.loads(resp.body)["error"]["code"] == "usage_limit")

# ── 6. Cloud API + dashboard ─────────────────────────────────────────────────
from tubecli.extensions.cloud_api import extension as CA  # noqa: E402
st = service.state()
st["llm_models"] = ["gpt-5.1-codex", "gpt-5.1"]
service.save_state(st)
llm.available = lambda: {"installed": True, "accounts": 2}
prov = [p for p in CA.key_manager.list_providers() if p["id"] == "codex"]
check("Cloud API liệt kê «Codex (ChatGPT)»: có sẵn khi đã cài + có tài khoản, model từ bản lưu, không «local»",
      prov and prov[0]["has_key"] and prov[0]["models"] == ["codex/default", "codex/gpt-5.1-codex", "codex/gpt-5.1"]
      and prov[0]["codex_session"] and prov[0]["accounts"] == 2 and not prov[0]["local"]
      and prov[0]["capability"] == "chat" and prov[0]["base_url"].endswith("/api/v1/codex-gpt/v1"), prov)
llm.available = lambda: {"installed": True, "accounts": 0}
prov = [p for p in CA.key_manager.list_providers() if p["id"] == "codex"][0]
check("chưa có tài khoản → has_key=False (Flow không liệt kê)", prov["has_key"] is False)

APP = io.open(ROOT / "tubecli/extensions/webui/static/app.js", encoding="utf-8").read().replace("\r\n", "\n")
check("thẻ Cloud API: nút «Mở Codex GPT» thay «Thêm khoá» + nhãn số tài khoản",
      "const addBtn = p.codex_session" in APP and 'href="/codex-gpt"' in APP and "cloud_api.codex_accounts_tag" in APP)
check("hộp thêm khoá bỏ Codex (không có khoá để thêm)", "filter(p => !p.browser_session && !p.codex_session)" in APP)
check("bảng model mặc định đặt nhãn «Codex (ChatGPT)»", "codex: '🧠 Codex (ChatGPT)'" in APP)
for lang in ["en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]:
    d = json.load(io.open(ROOT / f"tubecli/extensions/cloud_api/locales/{lang}.json", encoding="utf-8"))
    miss = [k for k in ("codex_open", "codex_accounts_tag", "codex_no_account", "codex_not_installed") if f"cloud_api.{k}" not in d]
    check(f"locale cloud_api {lang}: đủ 4 khoá Codex, {{n}} trong nhãn", not miss and "{n}" in d.get("cloud_api.codex_accounts_tag", ""), miss)

loop.call_soon_threadsafe(loop.stop)
print(f"\n{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
