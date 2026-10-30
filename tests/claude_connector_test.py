# -*- coding: utf-8 -*-
"""Trình kết nối claude.ai — phía máy (core/claude_connector.py + POST /api/v1/public/mcp).

User 23/10/2026: «thêm trình kết nối vào claude để tự động điều chỉnh»; chọn: lệnh nguy hiểm duyệt qua link trên cloud,
lệnh ghi thường làm luôn, chỉ chủ máy nối được.

  A. route: chữ ký miền «mcp» (sai miền / sai khoá / phát lại / quá cỡ / máy chưa có khoá), công tắc chủ tắt → 403
  B. tools/list: chỉ-đọc bỏ công cụ chỉ-ghi; đủ quyền = 23 công cụ; destructiveHint
  C. tools/call: chỉ-đọc chặn lệnh ghi (không chạy); nguy hiểm → needs_approval (không chạy); approved → chạy;
     ghi thường chạy luôn kèm X-TubeCLI-Agent: claude_connector; khoá cứng vẫn giữ
  D. lỗ /api/v1/files (tên cũ của File Manager) đã chặn — cho cả Codex
  E. việc Claude tạo ghi created_by «claude_connector»; Codex vẫn «codex_gpt»

Chạy:  python tests/claude_connector_test.py   (exit 0 = pass). Không gọi mạng thật, không đụng data/ thật.
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


TMP = Path(tempfile.mkdtemp(prefix="claude_connector_test_"))

from tubecli import config  # noqa: E402

config.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"    # KHÔNG đụng data/global_settings.json thật

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tubecli.api import public_routes  # noqa: E402
from tubecli.core import claude_connector as cc  # noqa: E402
from tubecli.core import public_agents as pa  # noqa: E402
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402

KEY = "b" * 48
pa._identity = lambda: {"code": "abc234", "key": KEY}


def set_switch(value):
    config.GLOBAL_SETTINGS_FILE.write_text(json.dumps({"claude_connector": value, "theme": "dark"}), encoding="utf-8")


# Máy giả: vài route thật để công cụ gọi qua ASGI — ghi lại ai gọi.
calls = []
app = FastAPI()
app.include_router(public_routes.router)


@app.post("/api/v1/codex/tasks/{tid}/retry")
async def _retry(tid: str, request: Request):
    calls.append(("retry", tid, request.headers.get("x-tubecli-agent")))
    return {"status": "queued"}


@app.post("/api/v1/codex/tasks/{tid}/cancel")
async def _cancel(tid: str, request: Request):
    calls.append(("cancel", tid, request.headers.get("x-tubecli-agent")))
    return {"status": "cancelled"}


@app.delete("/api/v1/codex/tasks/{tid}")
async def _delete(tid: str, request: Request):
    calls.append(("delete", tid, request.headers.get("x-tubecli-agent")))
    return {"deleted": True}


@app.get("/api/v1/files/read")
async def _files_read(path: str = ""):
    calls.append(("files_read", path, ""))
    return {"content": "SECRET"}


client = TestClient(app)
_n = [0]


def nonce():
    _n[0] += 1
    return f"{_n[0]:024x}"


def post_mcp(payload, domain="mcp", key=KEY, ts=None, raw=None, n=None):
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()) if ts is None else ts)
    n = n or nonce()
    sig = pa.sign(key, domain, ts, body, n)
    r = client.post("/api/v1/public/mcp", content=body,
                    headers={"x-town-ts": ts, "x-town-nonce": n, "x-town-sig": sig, "content-type": "application/json"})
    return r, (ts, n, sig, body)


def rpc_call(name, arguments, level="write", approved=False):
    return {"rpc": {"method": "tools/call", "params": {"name": name, "arguments": arguments}},
            "level": level, "approved": approved}


def text_of(out):
    try:
        return out["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return json.dumps(out)


# ── A. route + chữ ký + công tắc ─────────────────────────────────────────────
set_switch(True)
LIST_W = {"rpc": {"method": "tools/list"}, "level": "write"}
r, _ = post_mcp(LIST_W)
check("A1 chữ ký «mcp» đúng + công tắc bật → 200", r.status_code == 200 and r.json().get("ok") is True, r.text[:200])
r, _ = post_mcp(LIST_W, domain="invoke")
check("A2 chữ ký miền «invoke» không dùng được cho /mcp → 401", r.status_code == 401
      and r.json().get("code") == "bad_signature", r.text[:200])
r, _ = post_mcp(LIST_W, key="c" * 48)
check("A3 sai khoá → 401", r.status_code == 401, r.text[:200])
r, (ts, n, sig, body) = post_mcp(LIST_W)
r2 = client.post("/api/v1/public/mcp", content=body, headers={"x-town-ts": ts, "x-town-nonce": n, "x-town-sig": sig})
check("A4 phát lại đúng request đó → 401 replayed", r2.status_code == 401 and r2.json().get("code") == "replayed",
      r2.text[:200])
r = client.post("/api/v1/public/mcp", content=json.dumps(LIST_W))
check("A5 không có chữ ký → 401", r.status_code == 401, r.text[:200])
r, _ = post_mcp(LIST_W, ts=int(time.time()) - 400)
check("A6 mốc giờ quá 5 phút → 401", r.status_code == 401, r.text[:200])
r, _ = post_mcp(None, raw=b"x" * (cc.MAX_BODY + 1))
check("A7 thân quá cỡ → 413", r.status_code == 413, r.status_code)
saved = pa._identity
pa._identity = lambda: None
r, _ = post_mcp(LIST_W)
pa._identity = saved
check("A8 máy chưa có town_key → 503 not_configured", r.status_code == 503
      and r.json().get("code") == "not_configured", r.text[:200])
for val, label in ((False, "False"), ("true", "chuỗi «true»"), (None, "không có khoá")):
    if val is None:
        config.GLOBAL_SETTINGS_FILE.write_text("{}", encoding="utf-8")
    else:
        set_switch(val)
    r, _ = post_mcp(LIST_W)
    check(f"A9 công tắc chủ {label} → 403 connector_off", r.status_code == 403
          and r.json().get("code") == "connector_off", r.text[:200])
set_switch(True)
r, _ = post_mcp(None, raw=b"{not json")
check("A10 thân không phải JSON → 400", r.status_code == 400, r.text[:200])
r, _ = post_mcp({"rpc": {"method": "tools/list"}, "level": "admin"})
check("A11 mức quyền lạ → 400 bad_level", r.status_code == 400 and r.json().get("code") == "bad_level", r.text[:200])
r, _ = post_mcp({"rpc": {"method": "resources/list"}, "level": "read"})
check("A12 phương thức lạ → 400 bad_method", r.status_code == 400 and r.json().get("code") == "bad_method", r.text[:200])
# Đọc hằng số bằng ast — import api/server.py là dựng cả máy chủ (nạp extension, dời file trong data/ thật).
import ast  # noqa: E402

_tree = ast.parse((ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8"))
_exempt = next(ast.literal_eval(n.value) for n in _tree.body if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_AUTH_EXEMPT_EXACT" for t in n.targets))
check("A13 /api/v1/public/mcp miễn phiên đăng nhập (chìa khoá là chữ ký)", "/api/v1/public/mcp" in _exempt
      and "/api/v1/public/mcpx" not in _exempt)

# ── B. tools/list ────────────────────────────────────────────────────────────
r, _ = post_mcp(LIST_W)
tw = {t["name"]: t for t in r.json()["result"]["tools"]}
check("B1 đủ quyền: 23 công cụ (cùng bộ với Codex; +4 clone_* 30/10/2026)", len(tw) == len(T.TOOLS) == 23, sorted(tw))
check("B2 destructiveHint cho browser_close / market_install / town_agent_offer, không cho board_create",
      all(tw[n]["annotations"]["destructiveHint"] for n in ("browser_close", "market_install", "town_agent_offer"))
      and tw["board_create"]["annotations"]["destructiveHint"] is False, tw["board_create"]["annotations"])
check("B3 kèm version của lõi", bool(r.json().get("version")))
r, _ = post_mcp({"rpc": {"method": "tools/list"}, "level": "read"})
tr = {t["name"] for t in r.json()["result"]["tools"]}
check("B4 chỉ-đọc: bỏ board_create / browser_click / market_install / town_agent_offer",
      not tr & {"board_create", "browser_click", "browser_open", "browser_close", "market_install", "town_agent_offer"}, tr)
check("B5 chỉ-đọc: còn board_list / board_task / browser_screenshot / tubecli_api (GET)",
      {"board_list", "board_task", "browser_screenshot", "tubecli_api", "tubecli_overview"} <= tr, tr)

# ── C. tools/call ────────────────────────────────────────────────────────────
calls.clear()
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "POST", "path": "/api/v1/codex/tasks/t1/retry"}, level="read"))
out = r.json()
check("C1 chỉ-đọc + POST → lỗi read-only, KHÔNG chạy", out["result"]["isError"] and "read-only" in text_of(out)
      and not calls, (out, calls))
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "POST", "path": "/api/v1/codex/tasks/t1/retry"}))
out = r.json()
check("C2 ghi thường (Retry) chạy luôn", not out["result"]["isError"] and calls == [("retry", "t1", "claude_connector")],
      (out, calls))
calls.clear()
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "POST", "path": "/api/v1/codex/tasks/t1/cancel"}))
out = r.json()
check("C3 huỷ task → needs_approval, KHÔNG chạy", out.get("needs_approval", {}).get("tool") == "tubecli_api"
      and "POST /api/v1/codex/tasks/t1/cancel" in out["needs_approval"]["summary"] and not calls, (out, calls))
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "DELETE", "path": "/api/v1/codex/tasks/t1"}))
out = r.json()
check("C4 DELETE → needs_approval, KHÔNG chạy", "needs_approval" in out and not calls, (out, calls))
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "DELETE", "path": "/api/v1/codex/tasks/t1"}, approved=True))
out = r.json()
check("C5 DELETE đã duyệt → chạy, kèm X-TubeCLI-Agent", not out["result"]["isError"]
      and calls == [("delete", "t1", "claude_connector")], (out, calls))
calls.clear()
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "DELETE", "path": "/api/v1/codex/tasks/t1"}, level="read",
                         approved=True))
check("C6 approved KHÔNG vượt được kết nối chỉ-đọc", r.json()["result"]["isError"] and not calls, (r.json(), calls))
r, _ = post_mcp(rpc_call("browser_close", {"profile": "gmail_x"}))
out = r.json()
check("C7 đóng trình duyệt → needs_approval kèm tên hồ sơ", out.get("needs_approval", {}).get("tool") == "browser_close"
      and "gmail_x" in out["needs_approval"]["summary"], out)
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "GET", "path": "/api/v1/auth/status"}))
out = r.json()
check("C8 khoá cứng vẫn giữ (auth) — báo lỗi, không đòi duyệt", out["result"]["isError"] and "needs_approval" not in out,
      out)
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "DELETE", "path": "/api/v1/settings/x"}))
out = r.json()
check("C9 lệnh nguy hiểm nhưng bị khoá cứng → lỗi ngay, không tạo link duyệt", out["result"]["isError"]
      and "needs_approval" not in out, out)
r, _ = post_mcp(rpc_call("nope", {}))
check("C10 công cụ lạ → isError", r.json()["result"]["isError"], r.json())
r, _ = post_mcp(rpc_call("browser_click", {"profile": "p"}))
check("C11 thiếu tham số → lỗi trước khi chạy", r.json()["result"]["isError"] and "x and y" in text_of(r.json()), r.json())


def danger(method, path):
    return cc.is_dangerous(T.TOOLS["tubecli_api"], {"method": method, "path": path})


check("C12 phân loại nguy hiểm: stop / purge / uninstall / extensions/install / DELETE",
      danger("POST", "/api/v1/browser/stop") and danger("POST", "/api/v1/codex/tasks/x/purge")
      and danger("POST", "/api/v1/extensions/foo/uninstall") and danger("POST", "/api/v1/extensions/install")
      and danger("DELETE", "/api/v1/agents/x") and danger("POST", "/api/v1/x/force-stop"))
check("C13 không nguy hiểm: retry / run-now / sửa agent / tạo việc",
      not danger("POST", "/api/v1/codex/tasks/x/retry") and not danger("POST", "/api/v1/codex/tasks/x/run-now")
      and not danger("PUT", "/api/v1/agents/x") and not danger("POST", "/api/v1/content-video/tasks/x/retry"))

# ── D. lỗ /api/v1/files ──────────────────────────────────────────────────────
calls.clear()
for path in ("/api/v1/files/read", "/api/v1/files", "/api/v1/FILES/read", "/api/v1/%66iles/read"):
    try:
        T.check_api_path("GET", path)
        ok = False
    except T.ToolError:
        ok = True
    check(f"D1 GET {path} bị chặn (Codex lẫn Claude)", ok)
r, _ = post_mcp(rpc_call("tubecli_api", {"method": "GET", "path": "/api/v1/files/read",
                                         "query": {"path": "/x/cloud_api_keys.json"}}))
check("D2 qua /mcp: đọc /api/v1/files → lỗi, route không chạy", r.json()["result"]["isError"] and not calls,
      (r.json(), calls))
check("D3 /api/v1/files-extra không bị chặn nhầm (khớp theo đoạn)", not T.api_blocked("GET", "/api/v1/filesx/list"))

# ── E. created_by ────────────────────────────────────────────────────────────
made = []


class _Board:
    def create_task(self, **kw):
        made.append(kw)
        return {"seq": 7, "id": "t7", "status": "queued"}


T.board = lambda: _Board()
r, _ = post_mcp(rpc_call("board_create", {"goal": "Check the queue", "title": "Check"}))
check("E1 việc Claude tạo: created_by + origin.source = claude_connector", made and made[-1]["created_by"] ==
      "claude_connector" and made[-1]["origin"]["source"] == "claude_connector", made)


async def _codex_create():
    async def approve(*_a, **_k):
        return True, "", "th1"
    return await T.call_tool("board_create", {"goal": "x"}, app, approve)

asyncio.run(_codex_create())
check("E2 Codex vẫn ghi created_by codex_gpt + thread", made[-1]["created_by"] == "codex_gpt"
      and made[-1]["origin"] == {"source": "codex_gpt", "thread": "th1"}, made[-1])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
