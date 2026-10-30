"""Route Codex GPT: trang /codex-gpt, file tĩnh, REST /api/v1/codex-gpt/*, WebSocket /api/v1/codex-gpt/ws.

Gắn thẳng vào server (api/server.py) như Terminal — Codex chạy lệnh trên máy nên /api/v1/codex-gpt
nằm trong danh sách «nhạy cảm»: người được chia sẻ nhóm KHÔNG gọi được. WS qua reject_unless_allowed
(cookie phiên + Origin), REST qua cổng HTTP chung.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.requests import HTTPConnection

from . import cli
from .rpc import RpcError
from .service import GptError, service


def _note_port(conn: HTTPConnection) -> None:
    """Cổng TubeCLI THẬT (scope server) — ống MCP của Codex gọi về đúng cổng này, kể cả khi chạy --port khác."""
    srv = conn.scope.get("server") or ()
    if len(srv) >= 2:
        service.note_port(srv[1])


router = APIRouter(dependencies=[Depends(_note_port)])
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
API = "/api/v1/codex-gpt"


def _asset_version() -> str:
    """Đổi khi app.js/app.css đổi: HTML mới chạy với JS cũ trong bộ nhớ đệm là trang chết."""
    try:
        return str(int(max(os.path.getmtime(os.path.join(STATIC_DIR, n)) for n in ("app.js", "app.css"))))
    except OSError:
        return "0"


@router.get("/codex-gpt", include_in_schema=False, response_class=HTMLResponse)
def page():
    p = os.path.join(STATIC_DIR, "index.html")
    try:
        with open(p, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return HTMLResponse("<h1>Codex GPT</h1><p>static/index.html is missing.</p>", status_code=500)
    return HTMLResponse(html.replace("__ASSET_VER__", _asset_version()),
                        headers={"Cache-Control": "no-store, must-revalidate"})


@router.get("/codex-gpt-static/{filepath:path}", include_in_schema=False)
def static(filepath: str, v: str = Query("")):
    root = os.path.abspath(STATIC_DIR)
    full = os.path.abspath(os.path.join(root, filepath))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, "no such file")
    return FileResponse(full, headers={"Cache-Control": "public, max-age=31536000, immutable" if v else "no-store"})


def _fail(e: Exception) -> JSONResponse:
    if isinstance(e, GptError):
        return JSONResponse({"ok": False, "code": e.code, "error": str(e)}, status_code=e.status)
    if isinstance(e, RpcError):
        return JSONResponse({"ok": False, "code": "codex_error", "error": str(e)}, status_code=502)
    raise e


async def _body(request: Request) -> Dict[str, Any]:
    try:
        b = await request.json()
    except Exception:      # noqa: BLE001
        b = {}
    return b if isinstance(b, dict) else {}


def _ok(**kw) -> Dict[str, Any]:
    return {"ok": True, **kw}


# ── cài đặt + trạng thái ─────────────────────────────────────────────────────
@router.get(API + "/status")
async def status():
    return _ok(**(await service.status()))


@router.post(API + "/install")
async def install():
    return _ok(install=cli.start_install())


@router.on_event("startup")
async def _telegram_start() -> None:
    """Bot Telegram của Codex GPT chạy từ lúc server lên (nếu đã bật trong Settings) — không đợi ai mở trang."""
    # Vòng sự kiện của server cho llm.complete_sync (brain gọi Codex-làm-model từ luồng phụ).
    service.loop = asyncio.get_running_loop()
    try:
        service.telegram.start()
    except Exception as e:      # noqa: BLE001
        print(f"[CodexTG] start failed: {e}")


@router.post(API + "/telegram/test")
async def telegram_test():
    """Gửi một tin thử tới mọi chat được phép — nút «Gửi tin thử» trong Settings."""
    tg = service.telegram
    if not tg.configured():
        return _fail(GptError("telegram_off", "Turn the Telegram chatbot on and save a bot token first", 400))
    if not tg.running:
        tg.start()
    n = await tg.send_test()
    if n == 0:
        return _fail(GptError("telegram_send", tg.error or "No allowed chat received the message", 400))
    return _ok(sent=n, telegram=tg.public_status())


@router.put(API + "/settings")
async def settings(request: Request):
    try:
        return _ok(**(await service.apply_settings(await _body(request))))
    except GptError as e:
        return _fail(e)


@router.get(API + "/windows-sandbox")
async def windows_sandbox():
    try:
        return _ok(**(await service.win_sandbox_status()))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/windows-sandbox/setup")
async def windows_sandbox_setup(request: Request):
    b = await _body(request)
    try:
        return _ok(**(await service.win_sandbox_setup(str(b.get("mode") or "unelevated"))))
    except (GptError, RpcError) as e:
        return _fail(e)


# ── công cụ TubeCLI cho Codex (MCP) ──────────────────────────────────────────
@router.post(API + "/mcp", include_in_schema=False)
async def mcp(request: Request):
    """Chỉ ống mcp_relay.py trên CHÍNH máy này gọi: loopback, không qua proxy/tunnel, đúng khoá trong config.toml.
    Duyệt lệnh thay đổi nằm trong tools.call_tool → service.tool_approval — biết khoá cũng không bỏ qua được."""
    from tubecli.core.auth import behind_proxy, is_loopback

    from . import tools
    host = request.client.host if request.client else ""
    key = request.headers.get("x-codex-gpt-key") or ""
    if not is_loopback(host) or behind_proxy(request.headers) or not secrets.compare_digest(key, service.mcp_key()):
        return JSONResponse({"error": {"code": -32001, "message": "forbidden"}}, status_code=403)
    return await tools.handle_rpc(await _body(request), request.app, service.tool_approval)


@router.get(API + "/models")
async def models():
    try:
        return _ok(models=await service.models())
    except (GptError, RpcError) as e:
        return _fail(e)


# ── tài khoản ────────────────────────────────────────────────────────────────
@router.get(API + "/accounts")
async def accounts_list():
    return _ok(accounts=service.accounts_public(), active=service.active_id())


@router.post(API + "/accounts/login")
async def login_start(request: Request):
    b = await _body(request)
    try:
        return _ok(login=await service.start_login(str(b.get("kind") or ""), b.get("label") or "",
                                                   api_key=str(b.get("api_key") or ""), auth_json=str(b.get("auth_json") or "")))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.get(API + "/accounts/login/{lid}")
async def login_status(lid: str):
    try:
        return _ok(login=service.login_public(lid))
    except GptError as e:
        return _fail(e)


@router.post(API + "/accounts/login/{lid}/cancel")
async def login_cancel(lid: str):
    return _ok(cancelled=await service.cancel_login(lid))


@router.post(API + "/accounts/refresh-limits")
async def refresh_limits():
    return _ok(accounts=await service.refresh_limits())


@router.post(API + "/accounts/{acc_id}/activate")
async def activate(acc_id: str, request: Request):
    b = await _body(request)
    try:
        r = await service.switch(acc_id, reason="manual", force=bool(b.get("force")))
        return _ok(**r, accounts=service.accounts_public())
    except GptError as e:
        return _fail(e)


@router.patch(API + "/accounts/{acc_id}")
async def account_patch(acc_id: str, request: Request):
    from . import accounts as A
    b = await _body(request)
    if A.get(acc_id) is None:
        return _fail(GptError("not_found", "No such account", 404))
    fields: Dict[str, Any] = {}
    if "label" in b:
        fields["label"] = " ".join(str(b["label"] or "").split())[:60] or "Codex"
    if "disabled" in b:
        fields["disabled"] = bool(b["disabled"])
    if b.get("clear_limit"):
        fields["limited_until"] = 0
    A.update(acc_id, **fields)
    return _ok(accounts=service.accounts_public())


@router.delete(API + "/accounts/{acc_id}")
async def account_delete(acc_id: str):
    try:
        await service.remove_account(acc_id)
        return _ok(accounts=service.accounts_public(), active=service.active_id())
    except GptError as e:
        return _fail(e)


# ── phiên ────────────────────────────────────────────────────────────────────
@router.get(API + "/threads")
async def threads(archived: bool = False, q: str = "", cursor: str = ""):
    try:
        return _ok(**(await service.list_threads(archived=archived, search=q, cursor=cursor)))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/threads")
async def thread_new(request: Request):
    b = await _body(request)
    try:
        t = await service.start_thread(cwd=str(b.get("cwd") or ""), model=str(b.get("model") or ""))
        if b.get("text"):
            await service.send(t["id"], str(b["text"]), model=str(b.get("model") or ""), effort=str(b.get("effort") or ""))
        return _ok(thread=t)
    except (GptError, RpcError) as e:
        return _fail(e)


@router.get(API + "/threads/{tid}")
async def thread_read(tid: str):
    try:
        return _ok(**(await service.read_thread(tid)))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.patch(API + "/threads/{tid}")
async def thread_rename(tid: str, request: Request):
    b = await _body(request)
    name = " ".join(str(b.get("name") or "").split())[:120]
    try:
        await service.thread_call("thread/name/set", tid, name=name)
        return _ok(name=name)
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/threads/{tid}/archive")
async def thread_archive(tid: str):
    try:
        await service.thread_call("thread/archive", tid)
        return _ok()
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/threads/{tid}/unarchive")
async def thread_unarchive(tid: str):
    try:
        await service.thread_call("thread/unarchive", tid)
        return _ok()
    except (GptError, RpcError) as e:
        return _fail(e)


@router.delete(API + "/threads/{tid}")
async def thread_delete(tid: str):
    try:
        await service.thread_call("thread/delete", tid)
        return _ok()
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/threads/{tid}/turns")
async def thread_send(tid: str, request: Request):
    b = await _body(request)
    try:
        return _ok(**(await service.send(tid, str(b.get("text") or ""), model=str(b.get("model") or ""),
                                         effort=str(b.get("effort") or ""))))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/threads/{tid}/interrupt")
async def thread_interrupt(tid: str):
    try:
        return _ok(stopped=await service.interrupt(tid))
    except (GptError, RpcError) as e:
        return _fail(e)


@router.post(API + "/approvals/{key}")
async def approval(key: str, request: Request):
    b = await _body(request)
    try:
        return _ok(answered=await service.answer_approval(key, str(b.get("decision") or "decline")))
    except RpcError as e:
        return _fail(e)


# ── luồng sự kiện ────────────────────────────────────────────────────────────
@router.websocket(API + "/ws")
async def ws(websocket: WebSocket):
    """Đẩy mọi sự kiện của Codex (chữ chạy, item, lượt, đổi tài khoản, câu hỏi duyệt) ra trang."""
    from tubecli.core.ws_auth import reject_unless_allowed
    if not await reject_unless_allowed(websocket):
        return
    await websocket.accept()
    q = service.subscribe()
    try:
        await websocket.send_json({"type": "hello", "approvals": service.pending_approvals(),
                                   "running": dict(service.active_turns)})

        async def pump():
            while True:
                msg = await q.get()
                await websocket.send_json(msg)

        async def drain():
            while True:
                m = await websocket.receive_json()          # trang gửi «ping» để giữ kết nối qua tunnel
                if isinstance(m, dict) and m.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

        done, pending = await asyncio.wait({asyncio.ensure_future(pump()), asyncio.ensure_future(drain())},
                                           return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:      # noqa: BLE001 — ổ cắm đóng giữa chừng
        pass
    finally:
        service.unsubscribe(q)


# ── Codex (ChatGPT) làm MODEL: cổng chuẩn OpenAI cho chính máy này (30/10/2026) ────────────────────────
# Cho chỗ chỉ biết gọi kiểu OpenAI qua HTTP (Content Studio đọc PROVIDERS["codex"]["base_url"]). brain.py gọi thẳng
# llm.complete_sync, không qua đây. CHỈ loopback, không qua tunnel/proxy: đây là gói ChatGPT của chủ máy — người được
# chia sẻ workspace hay khách qua tunnel không được dùng nó làm API miễn phí.
def _loopback_only(request: Request) -> bool:
    from tubecli.core.auth import behind_proxy, is_loopback
    host = request.client.host if request.client else ""
    return is_loopback(host) and not behind_proxy(request.headers)


@router.get(API + "/v1/models")
async def oai_models(request: Request):
    from . import llm
    if not _loopback_only(request):
        return JSONResponse({"error": {"message": "local only", "code": "forbidden"}}, status_code=403)
    try:
        await service.models()
    except Exception:   # noqa: BLE001 — chưa có tài khoản / chưa cài: vẫn trả bản lưu
        pass
    return {"object": "list", "data": [{"id": m, "object": "model", "created": 0, "owned_by": "codex"}
                                       for m in llm.cached_models(service)]}


@router.post(API + "/v1/chat/completions")
async def oai_chat(request: Request):
    import json as _json
    import time as _time

    from fastapi.responses import StreamingResponse

    from . import llm
    if not _loopback_only(request):
        return JSONResponse({"error": {"message": "local only", "code": "forbidden"}}, status_code=403)
    body = await _body(request)
    model = str(body.get("model") or llm.DEFAULT_MODEL)
    try:
        r = await llm.complete(body.get("messages") or [], model)
    except llm.CodexLLMError as e:
        status = {"usage_limit": 429, "timeout": 504, "empty": 400, "not_installed": 503,
                  "no_account": 503}.get(e.code, 502)
        return JSONResponse({"error": {"message": e.message, "code": e.code, "type": "codex_error"}}, status_code=status)
    cid = "chatcmpl-codex-" + secrets.token_hex(8)
    now = int(_time.time())
    if body.get("stream"):
        def gen():
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": r["model"],
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": r["text"]}, "finish_reason": None}]}
            yield "data: " + _json.dumps(chunk, ensure_ascii=False) + "\n\n"
            end = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": r["model"],
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield "data: " + _json.dumps(end) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"id": cid, "object": "chat.completion", "created": now, "model": r["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": r["text"]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
