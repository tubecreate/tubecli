"""Codex (ChatGPT) làm MODEL cho agent / model mặc định của TubeCLI — 30/10/2026.

User: «thêm provider lựa chọn codex chatgpt». Trước đây Codex GPT chỉ là một app chat riêng; chọn «gpt-5» làm model
mặc định thì brain gửi sang OpenAI API và đòi API key — không dùng được gói ChatGPT đã đăng nhập trong Codex.

Cách làm (cùng khuôn Muse): model tên `codex/<id>` (`codex/default` = model mặc định của tài khoản). Mỗi lời gọi
mở MỘT luồng tạm trên app-server SẴN CÓ của extension (chung tài khoản đang chọn — hai tiến trình cùng một tài
khoản ChatGPT sẽ giành nhau refresh token), chạy một lượt, lấy câu trả lời cuối, rồi bỏ luồng:

  • ephemeral=True     — không ghi lịch sử, không hiện trong danh sách chat của trang Codex GPT;
  • baseInstructions   — thay toàn bộ lời dặn hệ thống của Codex bằng system prompt của người gọi;
  • sandbox read-only + approvalPolicy never;
  • config ghi đè theo luồng: tắt MỌI máy chủ MCP khai trong config.toml (gồm «tubecli» — công cụ TubeCLI),
    tắt shell / apply_patch / tìm web. Đã thử thật trên Codex 0.160 (scratchpad codex_probe*.py): ghi đè
    mcp_servers.<tên>.enabled=false làm luồng đó không khởi động MCP; features.shell_tool,
    features.apply_patch_freeform, web_search được nhận (khoá lạ chỉ bị cảnh báo, sai kiểu thì thread/start hỏng).

Hết hạn mức: đổi sang tài khoản khác (A.best) MỘT lần rồi chạy lại trên luồng mới — không gửi «tiếp tục» như
chat. Sự kiện của luồng tạm đi thẳng vào hàng đợi của lời gọi (service.llm_sinks), không phát lên trang.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

PREFIX = "codex/"
DEFAULT_ID = "default"
DEFAULT_MODEL = PREFIX + DEFAULT_ID
CALL_TIMEOUT_S = 300
MAX_PARALLEL = 3
PROMPT_LIMIT = 200000

BASE_RULES = (
    "You are a text model called by an application through an API. Answer the request directly with the final "
    "text only. You have no tools: do not run commands, read or write files, browse, or describe what you would do."
)

_sem: Optional[asyncio.Semaphore] = None


class CodexLLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_codex_model(model: Any) -> bool:
    return str(model or "").strip().lower().startswith(PREFIX)


def bare_model(model: Any) -> str:
    """'codex/gpt-5.1-codex' → 'gpt-5.1-codex'; 'codex/default' / 'codex/' → '' (model mặc định của tài khoản)."""
    s = str(model or "").strip()
    if s.lower().startswith(PREFIX):
        s = s[len(PREFIX):]
    s = s.strip()
    return "" if s.lower() in ("", DEFAULT_ID) else s


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):          # dạng phần của OpenAI: [{"type":"text","text":...}, {"type":"image_url"...}]
        out = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("text", "input_text"):
                out.append(str(p.get("text") or ""))
            elif isinstance(p, str):
                out.append(p)
        return "\n".join(x for x in out if x)
    return str(content or "")


def flatten(messages: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(lời dặn hệ thống, lời nhắn cho lượt). Một tin user duy nhất → gửi nguyên văn; nhiều lượt → bản ghi hội thoại."""
    system, convo = [], []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "user").lower()
        text = _text_of(m.get("content")).strip()
        if not text:
            continue
        if role in ("system", "developer"):
            system.append(text)
        else:
            convo.append((role, text))
    instructions = BASE_RULES + ("\n\n" + "\n\n".join(system) if system else "")
    if len(convo) == 1 and convo[0][0] == "user":
        prompt = convo[0][1]
    else:
        names = {"user": "User", "assistant": "Assistant", "tool": "Tool"}
        prompt = "\n\n".join(f"{names.get(r, r.title())}: {t}" for r, t in convo)
        if convo:
            prompt += "\n\nAssistant:"
    return instructions, prompt[:PROMPT_LIMIT]


def mcp_server_names(config_toml: str) -> List[str]:
    """Tên mọi [mcp_servers.<tên>] trong config.toml (cả bảng con như [mcp_servers.tubecli.env])."""
    names = []
    for m in re.finditer(r"^\s*\[\s*mcp_servers\.([A-Za-z0-9_-]+|\"[^\"]+\")", config_toml or "", re.M):
        n = m.group(1).strip('"')
        if n not in names:
            names.append(n)
    return names


def thread_config(config_toml: str) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {"features": {"shell_tool": False, "apply_patch_freeform": False}, "web_search": "disabled"}
    names = mcp_server_names(config_toml)
    if names:
        cfg["mcp_servers"] = {n: {"enabled": False} for n in names}
    return cfg


def _sem_get() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(MAX_PARALLEL)
    return _sem


def _scratch_dir(service) -> str:
    d = service.root / "llm-cwd"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


async def _collect(q: asyncio.Queue, deadline: float) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Đọc sự kiện của MỘT luồng tới turn/completed. (câu trả lời cuối, lỗi lượt | None)."""
    answer = ""
    while True:
        left = deadline - time.time()
        if left <= 0:
            raise asyncio.TimeoutError()
        method, params = await asyncio.wait_for(q.get(), left)
        if method == "item/completed":
            it = params.get("item") or {}
            if it.get("type") == "agentMessage" and str(it.get("text") or "").strip():
                answer = str(it.get("text"))
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            if turn.get("status") == "completed":
                return answer, None
            err = turn.get("error") or {"message": f"turn {turn.get('status') or 'failed'}"}
            return answer, err


async def complete(messages: List[Dict[str, Any]], model: str = "", timeout: float = CALL_TIMEOUT_S) -> Dict[str, Any]:
    """Một lượt hỏi-đáp không công cụ. {"text", "model"}; hỏng → CodexLLMError(code, message)."""
    from . import cli
    from .rpc import RpcError
    from .service import GptError, _is_auth_error, _is_usage_limit, service

    if not cli.command():
        raise CodexLLMError("not_installed", "Codex CLI is not installed on this machine (Codex GPT → Install).")
    instructions, prompt = flatten(messages)
    if not prompt.strip():
        raise CodexLLMError("empty", "No message to send to Codex.")
    m = bare_model(model)
    deadline = time.time() + max(10.0, float(timeout))
    async with _sem_get():
        for attempt in range(2):
            try:
                b = await service.ensure_bridge()
            except GptError as e:
                raise CodexLLMError(e.code, str(e))
            try:
                cfg_text = (service.home / "config.toml").read_text(encoding="utf-8")
            except OSError:
                cfg_text = ""
            params: Dict[str, Any] = {
                "cwd": _scratch_dir(service), "ephemeral": True, "sandbox": "read-only",
                "approvalPolicy": "never", "baseInstructions": instructions, "serviceName": "tubecli-llm",
                "config": thread_config(cfg_text),
            }
            if m:
                params["model"] = m
            try:
                r = await b.request("thread/start", params, timeout=90)
            except RpcError as e:
                raise CodexLLMError("thread_failed", f"Codex could not open a session: {e}")
            tid = ((r or {}).get("thread") or {}).get("id")
            if not tid:
                raise CodexLLMError("thread_failed", "Codex did not return a session id.")
            q: asyncio.Queue = asyncio.Queue()
            service.llm_sinks[tid] = q
            service.llm_threads.add(tid)
            try:
                turn: Dict[str, Any] = {"threadId": tid, "approvalPolicy": "never",
                                        "input": [{"type": "text", "text": prompt}]}
                if m:
                    turn["model"] = m
                try:
                    await b.request("turn/start", turn, timeout=60)
                except RpcError as e:
                    raise CodexLLMError("turn_failed", f"Codex refused the request: {e}")
                try:
                    text, err = await _collect(q, deadline)
                except asyncio.TimeoutError:
                    try:
                        turn_id = service.active_turns.get(tid)
                        if turn_id:
                            await b.request("turn/interrupt", {"threadId": tid, "turnId": turn_id}, timeout=10)
                    except Exception:  # noqa: BLE001
                        pass
                    raise CodexLLMError("timeout", f"Codex did not answer within {int(timeout)} s.")
            finally:
                service.llm_sinks.pop(tid, None)
                service.active_turns.pop(tid, None)
                service.loaded.discard(tid)
            if err is None:
                if not text.strip():
                    raise CodexLLMError("empty_answer", "Codex finished without an answer.")
                service.last_activity = time.time()
                return {"text": text, "model": PREFIX + (m or DEFAULT_ID)}
            msg = str(err.get("message") or err)
            if _is_auth_error(err):
                # Token tài khoản bị thu hồi / hết hạn (30/10/2026, task #491): đánh dấu + đổi tài khoản MỘT lần.
                if attempt == 0 and await service.llm_limit_switch("auth", msg):
                    continue
                raise CodexLLMError("auth_error", "The Codex account needs to sign in again (Codex GPT → Accounts → "
                                    f"Sign in again): {msg}")
            if _is_usage_limit(err):
                if attempt == 0 and await service.llm_limit_switch():
                    continue
                raise CodexLLMError("usage_limit", f"Codex usage limit reached on every account: {msg}")
            raise CodexLLMError("turn_failed", msg[:500])
    raise CodexLLMError("turn_failed", "Codex did not answer.")


def complete_sync(messages: List[Dict[str, Any]], model: str = "", timeout: float = CALL_TIMEOUT_S) -> Dict[str, Any]:
    """Cho code đồng bộ (brain._call_llm chạy trong luồng phụ): đẩy complete() sang vòng sự kiện của server.

    Gọi NGAY trên vòng sự kiện ấy thì không chờ được (treo cả server) → báo lỗi để brain lui sang provider khác."""
    from .service import service

    loop = getattr(service, "loop", None)
    if loop is None or not loop.is_running():
        raise CodexLLMError("not_ready", "Codex GPT is not running on this TubeCLI server yet.")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        raise CodexLLMError("wrong_thread", "Codex model was called from the server event loop; use a worker thread.")
    fut = asyncio.run_coroutine_threadsafe(complete(messages, model, timeout), loop)
    try:
        return fut.result(timeout + 60)
    except TimeoutError:
        fut.cancel()
        raise CodexLLMError("timeout", f"Codex did not answer within {int(timeout)} s.")


def cached_models(service=None) -> List[str]:
    """Tên model kiểu `codex/<id>` cho bảng chọn — đọc bản lưu lần hỏi model/list gần nhất (không mở Codex)."""
    if service is None:
        from .service import service as _svc
        service = _svc
    ids: List[str] = []
    try:
        ids = [str(x) for x in (service.state().get("llm_models") or []) if x]
    except Exception:  # noqa: BLE001
        ids = []
    return [DEFAULT_MODEL] + [PREFIX + i for i in ids if i and i != DEFAULT_ID]


def available() -> Dict[str, Any]:
    """Có dùng được Codex làm model không: đã cài CLI + có ít nhất một tài khoản bật."""
    from . import accounts as A
    from . import cli
    accs = [a for a in A.all_accounts() if not a.get("disabled")]
    return {"installed": bool(cli.command()), "accounts": len(accs)}
