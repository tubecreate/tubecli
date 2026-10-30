"""Cầu nối Codex GPT: một `codex app-server` dùng chung, nhiều tài khoản, phiên dùng chung.

MỘT CODEX_HOME (`<root>/home`) giữ lịch sử phiên (sessions/*.jsonl + các SQLite chỉ mục) — dùng chung
cho MỌI tài khoản, nên phiên tạo bằng tài khoản A làm tiếp được bằng tài khoản B. Chỉ auth.json đổi
theo tài khoản đang dùng (bản gốc nằm trong két accounts/<id>/auth.json; Codex tự làm mới token vào
home/auth.json → chép ngược về két sau mỗi lượt và trước mỗi lần đổi).

Hết hạn mức (turn thất bại codexErrorInfo = usageLimitExceeded) và đang bật «tự chuyển»: đánh dấu tài
khoản hết tới giờ đặt lại, chuyển sang tài khoản còn hạn mức dùng ít nhất, mở lại phiên và gửi lời
«làm tiếp». Mỗi lượt người dùng gửi được chuyển tối đa (số tài khoản − 1) lần — hết thì báo.

Đăng nhập / thử hạn mức tài khoản KHÔNG đang dùng chạy app-server TẠM với CODEX_HOME riêng
(<root>/tmp/…) — không đụng phiên đang chạy.

Công cụ TubeCLI (tools.py): khối tự quản trong home/config.toml đăng ký MCP «tubecli» (mcp_relay.py) + vùng ghi
của sandbox = vùng cho phép của TubeCLI (File Manager). Lệnh THAY ĐỔI qua công cụ hỏi chủ máy bằng thẻ duyệt
(kind "tool") trừ khi bật «Không cần hỏi» (settings.tools_auto).
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import accounts as A
from . import cli
from .rpc import AppServer, RpcError

logger = logging.getLogger("tubecli.codex_gpt")

APPROVALS = {"item/commandExecution/requestApproval", "item/fileChange/requestApproval",
             "execCommandApproval", "applyPatchApproval"}
# Thông báo không cần đẩy ra trang (ồn, không vẽ gì).
_QUIET = {"remoteControl/status/changed", "skills/changed", "mcpServer/startupStatus/updated",
          "app/list/updated", "fs/changed", "configWarning", "deprecationNotice"}
APPROVAL_TTL_S = 1800
LOGIN_TTL_S = 900
IDLE_STOP_S = 1200
# Lời nhắn gửi Codex sau khi tự đổi tài khoản (lời cho AI viết tiếng Anh — quy ước của dự án).
CONTINUE_TEXT = ("The previous attempt stopped because the subscription hit its usage limit; the session now "
                 "runs on another account. Continue exactly where you left off — do not repeat finished work.")
SETTINGS_DEFAULT = {"model": "", "effort": "", "approval": "never", "sandbox": "workspace-write", "cwd": "",
                    "tools": True, "tools_auto": False,
                    # Telegram chatbot (telegram.py): bot riêng, chat được phép ↔ phiên Codex (18/10/2026)
                    "telegram_enabled": False, "telegram_token": "", "telegram_chat_ids": []}
APPROVAL_POLICIES = ("never", "on-request", "untrusted")
SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
TOOL_TIMEOUT_S = 1800            # Codex chờ một lời gọi công cụ tối đa chừng này (gồm cả lúc chờ chủ duyệt)
TOOL_APPROVAL_WAIT_S = 1700      # thẻ duyệt tự từ chối trước khi Codex bỏ cuộc
CFG_BEGIN = "# >>> TubeCLI Codex GPT (managed: edits inside this block are overwritten) >>>"
CFG_END = "# <<< TubeCLI Codex GPT <<<"
RELAY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_relay.py")
TOOL_DECLINED = ("The owner declined this TubeCLI action. Do not retry it; ask the owner what to do instead.")
TOOL_NO_VIEWER = ("Nobody has the Codex GPT panel open to approve this TubeCLI action. Ask the owner to open Codex "
                  "GPT in TubeCLI, or to turn on «Don't ask» for TubeCLI tools in its settings.")


class GptError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> int:
    return int(time.time())


def _is_usage_limit(err: Dict[str, Any]) -> bool:
    info = err.get("codexErrorInfo")
    if info == "usageLimitExceeded" or (isinstance(info, dict) and "usageLimitExceeded" in info):
        return True
    return bool(re.search(r"usage limit|hit your (usage )?limit", str(err.get("message") or ""), re.I))


def _limit_reset(limits: Dict[str, Any], now: int) -> int:
    """Lúc tài khoản dùng lại được: giờ đặt lại của cửa sổ đã chạm 100 %, không biết thì +1 giờ."""
    resets = []
    for w in (limits.get("primary"), limits.get("secondary")):
        if isinstance(w, dict) and int(w.get("used") or 0) >= 100 and w.get("resets_at"):
            resets.append(int(w["resets_at"]))
    return max(resets) if resets else now + 3600


def thread_summary(t: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": t.get("id"), "name": t.get("name") or "", "preview": str(t.get("preview") or "")[:160],
            "cwd": t.get("cwd") or "", "model": t.get("model") or "", "createdAt": t.get("createdAt"),
            "updatedAt": t.get("updatedAt") or t.get("recencyAt") or t.get("createdAt"),
            "provider": t.get("modelProvider") or ""}


from .telegram import TG_TOKEN_RE, TelegramBridge, parse_chat_ids


class CodexGptService:
    def __init__(self):
        self.telegram = TelegramBridge(self)
        self.bridge: Optional[AppServer] = None
        self.bridge_error = ""
        self._lock: Optional[asyncio.Lock] = None
        self.subscribers: Set[asyncio.Queue] = set()
        self.active_turns: Dict[str, str] = {}
        self.loaded: Set[str] = set()
        self.approvals: Dict[str, Dict[str, Any]] = {}
        self.logins: Dict[str, Dict[str, Any]] = {}
        self.retry_budget: Dict[str, int] = {}
        self.last_activity = time.time()
        self._limits_written = 0.0
        self._gen = 0
        self._models: Dict[str, Any] = {"acc": None, "at": 0.0, "data": []}
        self._reaper: Optional[asyncio.Task] = None
        self.api_port: Optional[int] = None                 # cổng TubeCLI thật — lấy từ request (routes.note_port)
        self.tool_items: Dict[str, Dict[str, Any]] = {}     # lời gọi công cụ tubecli đang chạy → phiên nào
        self.tool_session_ok: Set[str] = set()              # phiên đã «Cho phép trong phiên này»
        self.win_sandbox: Dict[str, Any] = {}               # {"status", "setup": running|failed|done, "error"}
        # Phiên chat đã bấm «Cho phép, không hỏi lại»: mọi yêu cầu duyệt sau đó tự nhận.
        # CHỈ trong RAM và chết theo app-server — mở lại máy là hỏi lại từ đầu, vì đây là lòng
        # tin cho MỘT lượt làm việc, không phải một cài đặt.
        self.no_ask: set = set()
        # Codex làm MODEL cho agent (llm.py, 30/10/2026): luồng tạm của lời gọi → hàng đợi sự kiện riêng;
        # các luồng ấy không phát lên trang, không nhận «tiếp tục» khi hết hạn mức, không được dùng công cụ.
        self.llm_sinks: Dict[str, asyncio.Queue] = {}
        self.llm_threads: Set[str] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None   # vòng sự kiện của server (llm.complete_sync)

    # ── đường dẫn + trạng thái ───────────────────────────────────────────────
    @property
    def root(self) -> Path:
        return cli.data_root()

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def state(self) -> Dict[str, Any]:
        try:
            with open(self.root / "state.json", encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        st.setdefault("active", None)
        st.setdefault("auto_switch", True)
        st["settings"] = {**SETTINGS_DEFAULT, **(st.get("settings") or {})}
        st.setdefault("recent_cwds", [])
        return st

    def save_state(self, st: Dict[str, Any]) -> None:
        A._atomic_write(self.root / "state.json", json.dumps(st, ensure_ascii=False, indent=1).encode("utf-8"))

    def active_id(self) -> Optional[str]:
        return self.state().get("active")

    # ── phát tới các trang đang mở ───────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=4000)
        self.subscribers.add(q)
        self._start_reaper()
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    async def broadcast(self, msg: Dict[str, Any]) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                self.subscribers.discard(q)        # trang đọc không kịp: cắt, nó tự nối lại

    # ── auth.json trong home ↔ két ───────────────────────────────────────────
    def _marker(self) -> Path:
        return self.home / ".tubecli_account"

    def _sync_back(self) -> None:
        """Codex làm mới token vào home/auth.json — chép ngược về két của tài khoản đang ở trong home."""
        try:
            cur = self._marker().read_text(encoding="utf-8").strip()
        except OSError:
            return
        src = self.home / "auth.json"
        if not cur or not src.is_file() or A.get(cur) is None:
            return
        data = src.read_bytes()
        try:
            if data and data != A.read_auth(cur):
                A.write_auth(cur, data)
        except OSError:
            pass

    def _install_auth(self, acc_id: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            cur = self._marker().read_text(encoding="utf-8").strip()
        except OSError:
            cur = ""
        dst = self.home / "auth.json"
        if cur == acc_id and dst.is_file():
            return
        if cur and cur != acc_id:
            self._sync_back()
        A._atomic_write(dst, A.read_auth(acc_id), private=True)
        self._marker().write_text(acc_id, encoding="utf-8")

    # ── công cụ TubeCLI: cổng, khoá, vùng ghi, config.toml ───────────────────
    def note_port(self, port: Any) -> None:
        try:
            p = int(port)
        except (TypeError, ValueError):
            return
        if 0 < p < 65536:
            self.api_port = p

    def port(self) -> int:
        if self.api_port:
            return self.api_port
        try:
            from tubecli.config import get_api_port
            return int(get_api_port())
        except Exception:
            return 5295

    def mcp_key(self) -> str:
        st = self.state()
        if not st.get("mcp_key"):
            st["mcp_key"] = secrets.token_urlsafe(24)
            self.save_state(st)
        return st["mcp_key"]

    def _data_dirs(self) -> List[str]:
        out = {os.path.normcase(os.path.abspath(os.environ.get("TUBECLI_DATA_DIR", "data")))}
        try:
            from tubecli.config import DATA_DIR
            out.add(os.path.normcase(os.path.abspath(str(DATA_DIR))))
        except Exception:
            pass
        return list(out)

    def writable_roots(self) -> List[str]:
        """Vùng Codex được GHI = vùng cho phép của AI TubeCLI (File Manager: Desktop/Documents/Downloads + thêm),
        TRỪ thư mục data (két, nhóm, khoá API nằm trong đó — sandbox Codex không trừ được thư mục con), CỘNG
        thư mục làm việc riêng của Codex GPT."""
        try:
            from tubecli.extensions.file_manager.file_service import file_service
            roots = list(file_service.allowed_roots)
        except Exception:
            roots = [os.path.expanduser(p) for p in ("~/Desktop", "~/Documents", "~/Downloads")]
        data = self._data_dirs()
        out: List[str] = []
        for r in roots:
            r = os.path.normpath(os.path.abspath(r))
            rc = os.path.normcase(r)
            if any(rc == d or rc.startswith(d + os.sep) for d in data) or not os.path.isdir(r):
                continue
            if r not in out:
                out.append(r)
        out.append(str(self.workspace))
        # Gốc TubeCLI: thư mục làm việc mặc định, nên Codex ghi được ở đây. Liệt kê tường minh
        # để mục «Codex được ghi vào» nói ĐÚNG những gì nó ghi được — sandwich cwd của Codex
        # vốn đã cho ghi trọn cwd, ẩn đi thì giao diện báo thiếu.
        d = self.default_cwd()
        if d not in out:
            out.append(d)
        return out

    def default_cwd(self) -> str:
        """Thư mục làm việc MẶC ĐỊNH = GỐC TubeCLI (user 5/10/2026: «để mặc định workspace làm
        việc với tubecli khi cài extension này»).

        Trước đây mặc định là workspace riêng (data/codex_gpt/workspace) — một thư mục trống,
        nên vừa cài xong Codex chẳng có gì để làm và chủ máy phải tự gõ đường dẫn.

        Đánh đổi phải biết: sandbox «workspace-write» của Codex cho GHI TRỌN cwd («The sandbox
        permits reading files, and editing files in `cwd` and `writable_roots`» — chuỗi trong
        chính binary codex), mà schema config.toml KHÔNG có khoá loại trừ đường dẫn, nên
        data/ (két Keychain, khoá API) nằm trong vùng Codex SỬA được. Phần ĐỌC thì vốn đã mở:
        workspace-write cho đọc mọi nơi bất kể cwd. Câu chữ ở giao diện nói đúng điều này.
        """
        try:
            from tubecli.config import BASE_DIR
            p = str(BASE_DIR)
            return p if os.path.isdir(p) else str(self.workspace)
        except Exception:      # noqa: BLE001 — không lấy được gốc thì về workspace như cũ
            return str(self.workspace)

    def _cwd_allowed(self, cwd: str, sandbox: str) -> bool:
        if sandbox == "danger-full-access":
            return True
        c = os.path.normcase(os.path.abspath(cwd))
        return any(c == os.path.normcase(r) or c.startswith(os.path.normcase(r) + os.sep) for r in self.writable_roots())

    def _write_codex_config(self) -> None:
        """Khối tự quản trong home/config.toml: MCP «tubecli» + writable_roots. Phần người dùng tự viết giữ nguyên;
        bảng họ đã tự khai thì KHÔNG khai lại (TOML trùng bảng = Codex không khởi động được)."""
        self.home.mkdir(parents=True, exist_ok=True)
        p = self.home / "config.toml"
        try:
            cur = p.read_text(encoding="utf-8")
        except OSError:
            cur = ""
        user = re.sub(re.escape(CFG_BEGIN) + r".*?" + re.escape(CFG_END) + r"\n?", "", cur, flags=re.S).rstrip()
        q = json.dumps
        lines: List[str] = []
        if self.state()["settings"].get("tools") and not re.search(r"^\s*\[mcp_servers\.tubecli[\].]", user, re.M):
            url = f"http://127.0.0.1:{self.port()}/api/v1/codex-gpt/mcp"
            # default_tools_approval_mode = "approve": Codex KHÔNG tự đòi duyệt công cụ «không chỉ-đọc» (với
            # approval=never nó từ chối thẳng — thử thật 3/10/2026); duyệt do TubeCLI làm (tools.call_tool → thẻ).
            lines += ["[mcp_servers.tubecli]", f"command = {q(sys.executable)}", f"args = [{q(RELAY)}]",
                      "startup_timeout_sec = 30", f"tool_timeout_sec = {TOOL_TIMEOUT_S}",
                      'default_tools_approval_mode = "approve"', "",
                      "[mcp_servers.tubecli.env]", f"TUBECLI_CG_URL = {q(url)}", f"TUBECLI_CG_KEY = {q(self.mcp_key())}",
                      f"TUBECLI_CG_TIMEOUT = {q(str(TOOL_TIMEOUT_S))}", f"PYTHONIOENCODING = {q('utf-8')}", ""]
        if not re.search(r"^\s*\[sandbox_workspace_write\]", user, re.M):
            lines += ["[sandbox_workspace_write]",
                      "writable_roots = [" + ", ".join(q(r) for r in self.writable_roots()) + "]"]
        block = CFG_BEGIN + "\n" + "\n".join(lines).strip() + "\n" + CFG_END + "\n"
        new = (user + "\n\n" if user else "") + block
        if new != cur:
            A._atomic_write(p, new.encode("utf-8"))

    def _session_opts(self) -> Dict[str, Any]:
        """Tham số mở phiên (thread/start, thread/resume): chế độ duyệt/sandbox + lời dặn về công cụ TubeCLI."""
        opts = self._thread_opts()
        if self.state()["settings"].get("tools"):
            from .tools import INSTRUCTIONS
            opts["developerInstructions"] = INSTRUCTIONS
        return opts

    def _thread_for_tool(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Lời gọi MCP không mang id phiên → so với item mcpToolCall Codex vừa báo (cùng tên, cùng tham số)."""
        best = None
        for it in sorted(self.tool_items.values(), key=lambda x: x["at"], reverse=True):
            if it["tool"] != tool:
                continue
            if it["args"] == args:
                return it["thread"]
            best = best or it["thread"]
        return best

    async def tool_approval(self, tool: str, detail: str, args: Dict[str, Any],
                            force: bool = False) -> Tuple[bool, str, Optional[str]]:
        """(được, lý do cho Codex, phiên). Hỏi bằng thẻ duyệt trong khung chat của phiên gọi.

        force = công cụ LUÔN hỏi (town_agent_offer — đưa agent ra cho người lạ, đặt giá): bỏ qua cả «Không cần hỏi»
        lẫn «Cho phép trong phiên này»; thẻ mang once=True (không có nút cho cả phiên)."""
        tid = self._thread_for_tool(tool, args)
        if tid and tid in self.llm_threads:
            return False, "TubeCLI tools are not available to model calls.", tid
        if not force and (self.state()["settings"].get("tools_auto") or (tid and tid in self.tool_session_ok)):
            return True, "", tid
        if not self.subscribers:
            return False, TOOL_NO_VIEWER, tid
        key = f"t{self._gen}-{secrets.token_hex(4)}"
        fut = asyncio.get_running_loop().create_future()
        params = {"threadId": tid, "tool": tool, "detail": detail[:2000], **({"once": True} if force else {})}
        self.approvals[key] = {"kind": "tool", "method": "tubecli/tool", "params": params, "future": fut, "at": _now()}
        await self.broadcast({"type": "approval", "key": key, "method": "tubecli/tool", "params": params})
        decision = "decline"
        try:
            decision = await asyncio.wait_for(asyncio.shield(fut), TOOL_APPROVAL_WAIT_S)
        except asyncio.TimeoutError:
            pass
        finally:
            if self.approvals.pop(key, None) is not None:        # hết giờ / Codex bỏ lời gọi → gỡ thẻ
                await self.broadcast({"type": "approval_done", "key": key, "decision": "decline"})
        if decision in ("accept", "acceptForSession"):
            return True, "", tid
        return False, TOOL_DECLINED, tid

    async def _decline_tools(self, tid: Optional[str]) -> None:
        for k, a in list(self.approvals.items()):
            if a.get("kind") == "tool" and (tid is None or a["params"].get("threadId") == tid):
                await self.answer_approval(k, "decline")

    # ── sandbox Codex trên Windows ───────────────────────────────────────────
    async def win_sandbox_status(self) -> Dict[str, Any]:
        if os.name != "nt" and not os.environ.get("TUBECLI_CODEX_FAKE_WINDOWS"):
            return {"status": "unsupported"}
        b = await self.ensure_bridge()
        r = await b.request("windowsSandbox/readiness", None, timeout=30)
        self.win_sandbox["status"] = (r or {}).get("status") or "unknown"
        return dict(self.win_sandbox)

    async def win_sandbox_setup(self, mode: str = "unelevated") -> Dict[str, Any]:
        if mode not in ("unelevated", "elevated"):
            raise GptError("bad_setting", "Unknown sandbox setup mode", 400)
        b = await self.ensure_bridge()
        self.win_sandbox.update(setup="running", error="")
        try:
            r = await b.request("windowsSandbox/setupStart", {"mode": mode, "cwd": str(self.workspace)}, timeout=60)
        except RpcError as e:
            self.win_sandbox.update(setup="failed", error=str(e))
            raise
        if not (r or {}).get("started"):
            self.win_sandbox.update(setup="failed", error="setup did not start")
        return dict(self.win_sandbox)

    # ── app-server chính ─────────────────────────────────────────────────────
    async def ensure_bridge(self) -> AppServer:
        self.loop = asyncio.get_running_loop()
        async with self.lock:
            if self.bridge is not None and self.bridge.alive:
                return self.bridge
            cmd = cli.command()
            if not cmd:
                raise GptError("not_installed", "Codex CLI is not installed on this machine", 409)
            st = self.state()
            acc_id = st.get("active")
            if not acc_id or A.get(acc_id) is None:
                b = A.best()
                if b is None:
                    raise GptError("no_account", "Add a Codex account first", 409)
                acc_id = b["id"]
                st["active"] = acc_id
                self.save_state(st)
            self._install_auth(acc_id)
            try:
                self._write_codex_config()
            except OSError as e:
                logger.warning(f"[codex-gpt] cannot write config.toml: {e}")
            self.loaded.clear()
            self.active_turns.clear()
            self.tool_items.clear()
            self._gen += 1
            srv = AppServer(cmd, str(self.home), str(self.workspace), name="main",
                            on_notify=self._on_notify, on_request=self._on_request)
            srv.on_exit = functools.partial(self._on_exit, srv)
            try:
                await srv.start()
            except (RpcError, OSError) as e:
                await srv.stop()
                self.bridge_error = str(e)
                raise GptError("start_failed", f"Codex did not start: {e}", 502)
            self.bridge, self.bridge_error = srv, ""
            A.update(acc_id, last_used_at=_now())
            self.last_activity = time.time()
            self._start_reaper()
            return srv

    async def _on_exit(self, srv: AppServer, code: int) -> None:
        if srv is not self.bridge:
            return                                  # mình chủ động tắt (đổi tài khoản / nghỉ)
        self.bridge = None
        self.bridge_error = srv.exit_reason(code)
        stopped = list(self.active_turns)
        self.active_turns.clear()
        self.loaded.clear()
        self._sync_back()
        await self.broadcast({"type": "bridge", "state": "exited", "error": self.bridge_error, "interrupted": stopped})

    async def _stop_bridge(self) -> None:
        b, self.bridge = self.bridge, None
        if b is not None:
            await b.stop()
        self._sync_back()
        self.loaded.clear()
        self.active_turns.clear()

    def _start_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            try:
                self._reaper = asyncio.get_running_loop().create_task(self._reap_idle())
            except RuntimeError:
                pass

    async def _reap_idle(self) -> None:
        """Không ai mở trang, không lượt nào chạy quá 20 phút → tắt app-server cho nhẹ máy."""
        while True:
            await asyncio.sleep(60)
            if self.bridge is None:
                if not self.subscribers:
                    return
                continue
            if self.subscribers or self.active_turns:
                self.last_activity = time.time()
                continue
            if time.time() - self.last_activity > IDLE_STOP_S:
                async with self.lock:
                    await self._stop_bridge()

    # ── thông báo + câu hỏi từ Codex ─────────────────────────────────────────
    async def _on_notify(self, method: str, params: Dict[str, Any]) -> None:
        self.last_activity = time.time()
        tid = params.get("threadId")
        if method == "turn/started" and tid:
            self.active_turns[tid] = (params.get("turn") or {}).get("id") or ""
        elif method == "turn/completed" and tid:
            self.active_turns.pop(tid, None)
            self._sync_back()
            self.tool_items = {k: v for k, v in self.tool_items.items() if v["thread"] != tid}
            await self._decline_tools(tid)
            turn = params.get("turn") or {}
            err = turn.get("error") or {}
            if turn.get("status") == "failed" and err and _is_usage_limit(err):
                asyncio.ensure_future(self._handle_limit(tid))
        elif method == "thread/started":
            t = (params.get("thread") or {}).get("id")
            if t:
                self.loaded.add(t)
        elif method == "account/rateLimits/updated":
            self._store_limits(params.get("rateLimits"))
        elif method in ("item/started", "item/completed"):
            it = params.get("item") or {}
            if it.get("type") == "mcpToolCall" and it.get("server") == "tubecli" and it.get("id"):
                if method == "item/started":
                    args = it.get("arguments") if isinstance(it.get("arguments"), dict) else {}
                    self.tool_items[it["id"]] = {"thread": tid, "tool": it.get("tool"), "at": time.time(), "args": args}
                else:
                    self.tool_items.pop(it["id"], None)
        elif method == "windowsSandbox/setupCompleted":
            ok = bool(params.get("success"))
            self.win_sandbox.update(setup="done" if ok else "failed", error=str(params.get("error") or ""))
            if ok:
                self.win_sandbox["status"] = "ready"
        if tid and (tid in self.llm_sinks or tid in self.llm_threads):
            # Luồng tạm của Codex-làm-model: sự kiện thuộc về lời gọi, không phải khung chat.
            sink = self.llm_sinks.get(tid)
            if sink is not None:
                sink.put_nowait((method, params))
            return
        if method in _QUIET:
            return
        await self.broadcast({"type": "event", "method": method, "params": params})

    def _store_limits(self, snapshot: Optional[Dict[str, Any]]) -> None:
        acc_id = self.active_id()
        if not acc_id or not isinstance(snapshot, dict):
            return
        if not (snapshot.get("primary") or snapshot.get("secondary") or snapshot.get("rateLimitReachedType")):
            return                                  # provider không báo hạn mức (API key, 9Router…)
        lim = A.limits_from(snapshot)
        acc = A.get(acc_id) or {}
        old = acc.get("limits") or {}
        changed = any((old.get(k) or {}).get("used") != (lim.get(k) or {}).get("used") for k in ("primary", "secondary"))
        fields: Dict[str, Any] = {}
        if changed or time.time() - self._limits_written > 120:
            fields["limits"] = lim
        if lim.get("plan") and lim["plan"] != acc.get("plan"):
            fields["plan"] = lim["plan"]
        if lim.get("reached"):
            fields["limited_until"] = _limit_reset(lim, _now())
        if fields:
            A.update(acc_id, **fields)
            self._limits_written = time.time()

    async def _on_request(self, msg: Dict[str, Any]) -> None:
        method, rid = msg.get("method"), msg.get("id")
        b = self.bridge
        if method not in APPROVALS or b is None:
            if b is not None:
                await b.respond(rid, error={"code": -32601, "message": f"{method} is not supported by TubeCLI"})
            return
        key = f"{self._gen}-{rid}"
        params = msg.get("params") or {}
        # Phiên đã bấm «không hỏi lại»: nhận ngay, và vẫn báo cho giao diện biết đã tự nhận
        # cái gì — tự duyệt mà im lặng thì chủ máy không còn thấy Codex đang làm gì.
        tid = str(params.get("threadId") or "")
        if tid and tid in self.no_ask:
            ok = "approved" if method in ("execCommandApproval", "applyPatchApproval") else "accept"
            await b.respond(rid, {"decision": ok})
            await self.broadcast({"type": "approval_auto", "method": method, "params": params})
            return
        self.approvals[key] = {"rid": rid, "method": method, "params": params, "bridge": b, "at": _now()}
        await self.broadcast({"type": "approval", "key": key, "method": method, "params": params})
        asyncio.get_running_loop().call_later(
            APPROVAL_TTL_S, lambda: asyncio.ensure_future(self.answer_approval(key, "decline")))

    async def answer_approval(self, key: str, decision: str) -> bool:
        a = self.approvals.pop(key, None)
        if a is None:
            return False
        if a.get("kind") == "tool":
            if decision not in ("accept", "acceptForSession"):
                decision = "decline"
            if decision == "acceptForSession" and a["params"].get("once"):
                decision = "accept"                 # công cụ luôn hỏi: «cho cả phiên» chỉ tính là đồng ý LẦN NÀY
            if decision == "acceptForSession" and a["params"].get("threadId"):
                self.tool_session_ok.add(a["params"]["threadId"])
            if not a["future"].done():
                a["future"].set_result(decision)
            await self.broadcast({"type": "approval_done", "key": key, "decision": decision})
            return True
        b = a["bridge"]
        if b is not self.bridge or not b.alive:
            return False
        if decision == "acceptAlways":
            # Ghi sổ TRƯỚC khi trả lời: Codex gửi yêu cầu kế tiếp ngay sau khi nhận được câu
            # trả lời này, ghi sau thì cái đó vẫn kịp hiện thẻ hỏi.
            tid = str((a.get("params") or {}).get("threadId") or "")
            if tid:
                self.no_ask.add(tid)
            decision = "accept"
        if a["method"] in ("execCommandApproval", "applyPatchApproval"):      # giao thức cũ (v1)
            decision = {"accept": "approved", "acceptForSession": "approved_for_session",
                        "decline": "denied", "cancel": "abort"}.get(decision, "denied")
        elif decision not in ("accept", "acceptForSession", "decline", "cancel"):
            decision = "decline"
        await b.respond(a["rid"], {"decision": decision})
        await self.broadcast({"type": "approval_done", "key": key, "decision": decision})
        return True

    def pending_approvals(self) -> List[Dict[str, Any]]:
        return [{"key": k, "method": v["method"], "params": v["params"]} for k, v in self.approvals.items()
                if v.get("kind") == "tool" or v.get("bridge") is self.bridge]

    # ── tự chuyển tài khoản khi hết hạn mức ──────────────────────────────────
    async def _handle_limit(self, tid: str) -> None:
        if tid in self.llm_threads:
            return                                  # llm.complete tự đổi tài khoản + chạy lại trên luồng mới
        st = self.state()
        cur = st.get("active")
        acc = A.get(cur) if cur else None
        if acc is not None:
            A.update(cur, limited_until=max(int(acc.get("limited_until") or 0), _limit_reset(acc.get("limits") or {}, _now())))
        # Lượt bắt đầu trước khi server khởi động lại (không có trong sổ) vẫn được đổi tài khoản.
        budget = self.retry_budget.get(tid, max(0, len(A.all_accounts()) - 1))
        nxt = A.best(exclude={cur}) if st.get("auto_switch") else None
        if nxt is None or budget <= 0:
            await self.broadcast({"type": "limit", "threadId": tid, "account": cur, "switched": False,
                                  "auto": bool(st.get("auto_switch"))})
            return
        self.retry_budget[tid] = budget - 1
        try:
            await self.switch(nxt["id"], reason="limit", force=True)
            await self.broadcast({"type": "switched", "threadId": tid, "from": cur, "to": nxt["id"],
                                  "label": nxt.get("label") or nxt.get("email") or ""})
            await self.send(tid, CONTINUE_TEXT, user=False)
        except (GptError, RpcError) as e:
            await self.broadcast({"type": "limit", "threadId": tid, "account": cur, "switched": False, "error": str(e)})

    async def llm_limit_switch(self) -> bool:
        """Codex-làm-model chạm hạn mức: đánh dấu tài khoản đang dùng, đổi sang tài khoản tốt nhất còn lại.
        True = đã đổi (người gọi chạy lại MỘT lần trên luồng mới). Tôn trọng «tự đổi tài khoản» của trang."""
        st = self.state()
        cur = st.get("active")
        acc = A.get(cur) if cur else None
        if acc is not None:
            A.update(cur, limited_until=max(int(acc.get("limited_until") or 0), _limit_reset(acc.get("limits") or {}, _now())))
        nxt = A.best(exclude={cur}) if st.get("auto_switch") else None
        if nxt is None:
            return False
        try:
            await self.switch(nxt["id"], reason="limit", force=True)
        except (GptError, RpcError):
            return False
        await self.broadcast({"type": "switched", "threadId": None, "from": cur, "to": nxt["id"],
                              "label": nxt.get("label") or nxt.get("email") or ""})
        return True

    async def switch(self, acc_id: str, reason: str = "manual", force: bool = False) -> Dict[str, Any]:
        acc = A.get(acc_id)
        if acc is None:
            raise GptError("not_found", "No such account", 404)
        if acc.get("disabled"):
            raise GptError("disabled", "This account is turned off", 409)
        async with self.lock:
            st = self.state()
            old = st.get("active")
            if old == acc_id and self.bridge is not None and self.bridge.alive:
                return {"active": acc_id, "changed": False}
            if self.active_turns and not force:
                raise GptError("busy", "A reply is still running — stop it or wait before switching account", 409)
            interrupted = list(self.active_turns)
            await self._stop_bridge()
            st["active"] = acc_id
            self.save_state(st)
            self._install_auth(acc_id)
            self._models["acc"] = None
        await self.broadcast({"type": "account", "active": acc_id, "from": old, "reason": reason,
                              "interrupted": [t for t in interrupted]})
        return {"active": acc_id, "changed": True}

    # ── phiên ────────────────────────────────────────────────────────────────
    def _thread_opts(self) -> Dict[str, Any]:
        s = self.state()["settings"]
        return {"approvalPolicy": s["approval"] if s["approval"] in APPROVAL_POLICIES else "never",
                "sandbox": s["sandbox"] if s["sandbox"] in SANDBOXES else "workspace-write"}

    async def list_threads(self, archived: bool = False, search: str = "", cursor: str = "", limit: int = 40):
        b = await self.ensure_bridge()
        params: Dict[str, Any] = {"limit": max(1, min(100, int(limit))), "archived": bool(archived), "sortKey": "updated_at"}
        if search:
            params["searchTerm"] = search[:120]
        if cursor:
            params["cursor"] = cursor
        r = await b.request("thread/list", params)
        return {"threads": [thread_summary(t) for t in (r or {}).get("data") or []], "next": (r or {}).get("nextCursor"),
                "running": dict(self.active_turns)}

    async def read_thread(self, tid: str) -> Dict[str, Any]:
        b = await self.ensure_bridge()
        r = await b.request("thread/read", {"threadId": tid, "includeTurns": True}, timeout=90)
        t = (r or {}).get("thread") or {}
        return {"thread": t, "running": self.active_turns.get(tid) or "",
                "approvals": [a for a in self.pending_approvals() if a["params"].get("threadId") == tid]}

    def _check_cwd(self, cwd: str) -> str:
        if not cwd:
            self.workspace.mkdir(parents=True, exist_ok=True)
            return self.default_cwd()
        p = Path(os.path.expanduser(cwd))
        if not p.is_absolute():
            raise GptError("bad_cwd", "The working folder must be an absolute path", 400)
        if not p.is_dir():
            raise GptError("cwd_missing", f"Folder not found: {p}", 400)
        return str(p)

    async def start_thread(self, cwd: str = "", model: str = "") -> Dict[str, Any]:
        """Mức suy luận (effort) đặt theo từng lượt ở send() — thread/start không nhận nó."""
        st = self.state()
        cwd = self._check_cwd(cwd or st["settings"].get("cwd") or "")
        if not self._cwd_allowed(cwd, st["settings"]["sandbox"]):
            raise GptError("outside_roots", "This folder is outside the areas TubeCLI lets AI write to", 400)
        b = await self.ensure_bridge()
        params: Dict[str, Any] = {"cwd": cwd, "serviceName": "tubecli", **self._session_opts()}
        m = model or st["settings"].get("model")
        if m:
            params["model"] = m
        r = await b.request("thread/start", params)
        t = (r or {}).get("thread") or {}
        if t.get("id"):
            self.loaded.add(t["id"])
        recent = [c for c in st["recent_cwds"] if c != cwd]
        st["recent_cwds"] = [cwd] + recent[:7]
        self.save_state(st)
        return thread_summary(t)

    async def _ensure_loaded(self, b: AppServer, tid: str) -> None:
        if tid in self.loaded:
            return
        await b.request("thread/resume", {"threadId": tid, "excludeTurns": True, **self._session_opts()}, timeout=90)
        self.loaded.add(tid)

    async def send(self, tid: str, text: str, user: bool = True, model: str = "", effort: str = "") -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise GptError("empty", "Type a message first", 400)
        b = await self.ensure_bridge()
        await self._ensure_loaded(b, tid)
        inp = [{"type": "text", "text": text[:200000]}]
        running = self.active_turns.get(tid)
        if running:
            # Đang trả lời: chèn thêm lời nhắn vào lượt đang chạy (Codex gọi là «steer»).
            await b.request("turn/steer", {"threadId": tid, "expectedTurnId": running, "input": inp})
            return {"turnId": running, "steered": True}
        s = self.state()["settings"]
        params: Dict[str, Any] = {"threadId": tid, "input": inp, "approvalPolicy": self._thread_opts()["approvalPolicy"]}
        if model or s.get("model"):
            params["model"] = model or s["model"]
        if effort or s.get("effort"):
            params["effort"] = effort or s["effort"]
        r = await b.request("turn/start", params)
        turn_id = ((r or {}).get("turn") or {}).get("id") or ""
        if turn_id:
            self.active_turns[tid] = turn_id
        if user:
            self.retry_budget[tid] = max(0, len(A.all_accounts()) - 1)
        self.last_activity = time.time()
        return {"turnId": turn_id, "steered": False}

    async def interrupt(self, tid: str) -> bool:
        turn = self.active_turns.get(tid)
        if not turn or self.bridge is None:
            return False
        await self.bridge.request("turn/interrupt", {"threadId": tid, "turnId": turn})
        return True

    async def thread_call(self, method: str, tid: str, **extra) -> Any:
        b = await self.ensure_bridge()
        r = await b.request(method, {"threadId": tid, **extra})
        if method == "thread/delete":
            self.loaded.discard(tid)
        return r

    async def models(self) -> List[Dict[str, Any]]:
        acc = self.active_id()
        if self._models["acc"] == acc and time.time() - self._models["at"] < 600 and self._models["data"]:
            return self._models["data"]
        b = await self.ensure_bridge()
        r = await b.request("model/list", {"limit": 100})
        data = []
        for m in (r or {}).get("data") or []:
            if m.get("hidden"):
                continue
            efforts = m.get("supportedReasoningEfforts") or []
            data.append({"id": m.get("id"), "name": m.get("displayName") or m.get("id"),
                         "defaultEffort": m.get("defaultReasoningEffort") or "",
                         "efforts": [e.get("reasoningEffort") if isinstance(e, dict) else e for e in efforts],
                         "isDefault": bool(m.get("isDefault"))})
        self._models.update(acc=acc, at=time.time(), data=data)
        # Bảng chọn model (Cloud API Keys → «Codex (ChatGPT)») đọc bản lưu này, không phải mở Codex.
        ids = [d["id"] for d in data if d.get("id")]
        st = self.state()
        if ids and st.get("llm_models") != ids:
            st["llm_models"] = ids
            self.save_state(st)
        return data

    # ── tài khoản ────────────────────────────────────────────────────────────
    def _tmp_home(self, tag: str) -> Path:
        p = self.root / "tmp" / f"{tag}-{secrets.token_hex(4)}"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def _temp_server(self, home: Path, name: str, on_notify=None) -> AppServer:
        cmd = cli.command()
        if not cmd:
            raise GptError("not_installed", "Codex CLI is not installed on this machine", 409)
        self.workspace.mkdir(parents=True, exist_ok=True)
        srv = AppServer(cmd, str(home), str(self.workspace), name=name, on_notify=on_notify)
        try:
            await srv.start()
        except (RpcError, OSError) as e:
            await srv.stop()
            shutil.rmtree(home, ignore_errors=True)
            raise GptError("start_failed", f"Codex did not start: {e}", 502)
        return srv

    async def start_login(self, kind: str, label: str = "", api_key: str = "", auth_json: str = "") -> Dict[str, Any]:
        if kind not in ("chatgpt", "apiKey", "import"):
            raise GptError("bad_kind", "Unknown login type", 400)
        label = " ".join(str(label or "").split())[:60]
        if kind == "apiKey":
            api_key = (api_key or "").strip()
            if not re.match(r"^sk-[\w-]{20,}$", api_key):
                raise GptError("bad_key", "That does not look like an OpenAI API key (sk-…)", 400)
            label = label or f"API key …{api_key[-4:]}"
        doc = None
        if kind == "import":
            try:
                doc = json.loads(auth_json or "")
            except ValueError:
                raise GptError("bad_auth", "auth.json is not valid JSON", 400)
            if not isinstance(doc, dict) or not (doc.get("tokens") or doc.get("OPENAI_API_KEY")):
                raise GptError("bad_auth", "This file has no Codex login (tokens or OPENAI_API_KEY)", 400)
        lid = secrets.token_hex(6)
        home = self._tmp_home("login")
        if doc is not None:
            A._atomic_write(home / "auth.json", json.dumps(doc).encode("utf-8"), private=True)
        job: Dict[str, Any] = {"id": lid, "kind": kind, "label": label, "state": "pending", "url": "", "code": "",
                               "error": "", "account": None, "created_at": _now(), "home": home, "srv": None,
                               "login_id": ""}
        self.logins[lid] = job
        try:
            srv = await self._temp_server(home, f"login-{lid}", on_notify=functools.partial(self._login_notify, lid))
        except GptError as e:
            job.update(state="error", error=str(e))
            raise
        job["srv"] = srv
        try:
            if kind == "chatgpt":
                r = await srv.request("account/login/start", {"type": "chatgptDeviceCode"})
                job.update(url=r.get("verificationUrl") or "", code=r.get("userCode") or "", login_id=r.get("loginId") or "")
                asyncio.get_running_loop().call_later(
                    LOGIN_TTL_S, lambda: asyncio.ensure_future(self._finish_login(lid, False, "expired")))
            elif kind == "apiKey":
                await srv.request("account/login/start", {"type": "apiKey", "apiKey": api_key})
                await self._finish_login(lid, True)
            else:
                await self._finish_login(lid, True)
        except RpcError as e:
            await self._finish_login(lid, False, str(e))
        return self.login_public(lid)

    async def _login_notify(self, lid: str, method: str, params: Dict[str, Any]) -> None:
        if method == "account/login/completed":
            await self._finish_login(lid, bool(params.get("success")), params.get("error") or "")

    async def _finish_login(self, lid: str, success: bool, error: str = "") -> None:
        job = self.logins.get(lid)
        if job is None or job["state"] != "pending":
            return
        job["state"] = "finishing"
        srv, home = job["srv"], job["home"]
        try:
            if success and srv is not None:
                info = ((await srv.request("account/read", {"refreshToken": False})) or {}).get("account")
                if not info:
                    raise GptError("login_failed", "Codex did not accept this login", 400)
                limits = None
                try:
                    rl = await srv.request("account/rateLimits/read", timeout=40)
                    limits = A.limits_from((rl or {}).get("rateLimits"))
                except RpcError:
                    pass
                auth = (Path(home) / "auth.json").read_bytes()
                kind = "chatgpt" if info.get("type") == "chatgpt" else "apiKey"
                saved = A.add_or_update({"label": job["label"] or info.get("email") or "Codex", "kind": kind,
                                         "email": info.get("email"), "plan": info.get("planType"),
                                         "limits": limits}, auth)
                st = self.state()
                if not st.get("active") or A.get(st["active"]) is None:
                    st["active"] = saved["id"]
                    self.save_state(st)
                job.update(state="done", account=A.public(saved, self.active_id()))
            else:
                job.update(state="error", error=error or "Login failed")
        except (GptError, RpcError, OSError) as e:
            job.update(state="error", error=str(e))
        finally:
            if srv is not None:
                await srv.stop()
            shutil.rmtree(home, ignore_errors=True)
            job["srv"] = None
        await self.broadcast({"type": "login", "id": lid, "state": job["state"]})

    async def cancel_login(self, lid: str) -> bool:
        job = self.logins.get(lid)
        if job is None or job["state"] != "pending":
            return False
        srv = job.get("srv")
        if srv is not None and job.get("login_id"):
            try:
                await srv.request("account/login/cancel", {"loginId": job["login_id"]}, timeout=15)
            except RpcError:
                pass
        await self._finish_login(lid, False, "cancelled")
        job["state"] = "cancelled"
        return True

    def login_public(self, lid: str) -> Dict[str, Any]:
        job = self.logins.get(lid)
        if job is None:
            raise GptError("not_found", "No such login", 404)
        return {k: job[k] for k in ("id", "kind", "state", "url", "code", "error", "account")}

    async def refresh_limits(self) -> List[Dict[str, Any]]:
        """Hỏi hạn mức của MỌI tài khoản: tài khoản đang dùng qua app-server chính, còn lại qua app-server tạm."""
        act = self.active_id()
        for acc in A.all_accounts():
            if acc.get("disabled"):
                continue
            if acc["id"] == act and self.bridge is not None and self.bridge.alive:
                try:
                    rl = await self.bridge.request("account/rateLimits/read", timeout=40)
                    self._store_limits((rl or {}).get("rateLimits"))
                    A.update(acc["id"], limits=A.limits_from((rl or {}).get("rateLimits")))
                except RpcError:
                    pass
                continue
            home = self._tmp_home("probe")
            srv = None
            try:
                A._atomic_write(home / "auth.json", A.read_auth(acc["id"]), private=True)
                srv = await self._temp_server(home, f"probe-{acc['id']}")
                rl = await srv.request("account/rateLimits/read", timeout=40)
                info = ((await srv.request("account/read", {"refreshToken": False})) or {}).get("account") or {}
                lim = A.limits_from((rl or {}).get("rateLimits"))
                fields: Dict[str, Any] = {"limits": lim}
                if info.get("planType"):
                    fields["plan"] = info["planType"]
                if lim.get("reached"):
                    fields["limited_until"] = _limit_reset(lim, _now())
                elif int(acc.get("limited_until") or 0) > _now():
                    fields["limited_until"] = 0          # đã đặt lại sớm hơn dự tính
                A.update(acc["id"], **fields)
                data = (home / "auth.json").read_bytes()
                if data and data != A.read_auth(acc["id"]):
                    A.write_auth(acc["id"], data)
            except (GptError, RpcError, OSError) as e:
                A.update(acc["id"], probe_error=str(e)[:200])
            finally:
                if srv is not None:
                    await srv.stop()
                shutil.rmtree(home, ignore_errors=True)
        return self.accounts_public()

    def accounts_public(self) -> List[Dict[str, Any]]:
        act = self.active_id()
        return [A.public(a, act) for a in A.all_accounts()]

    async def remove_account(self, acc_id: str) -> None:
        if A.get(acc_id) is None:
            raise GptError("not_found", "No such account", 404)
        if acc_id == self.active_id():
            nxt = A.best(exclude={acc_id})
            if nxt is not None:
                await self.switch(nxt["id"], reason="removed", force=True)
            else:
                async with self.lock:
                    await self._stop_bridge()
                    st = self.state()
                    st["active"] = None
                    self.save_state(st)
                    for f in ("auth.json", ".tubecli_account"):
                        try:
                            (self.home / f).unlink()
                        except OSError:
                            pass
        A.remove(acc_id)

    # ── cài đặt + trạng thái ─────────────────────────────────────────────────
    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        st = self.state()
        s = st["settings"]
        if "auto_switch" in patch:
            st["auto_switch"] = bool(patch["auto_switch"])
        for k in ("model", "effort"):
            if k in patch:
                s[k] = re.sub(r"[^\w.:/-]", "", str(patch[k] or ""))[:80]
        if "approval" in patch:
            if patch["approval"] not in APPROVAL_POLICIES:
                raise GptError("bad_setting", "Unknown approval mode", 400)
            s["approval"] = patch["approval"]
        if "sandbox" in patch:
            if patch["sandbox"] not in SANDBOXES:
                raise GptError("bad_setting", "Unknown sandbox mode", 400)
            s["sandbox"] = patch["sandbox"]
        if "cwd" in patch:
            s["cwd"] = self._check_cwd(str(patch["cwd"] or "")) if patch["cwd"] else ""
        if s["cwd"] and not self._cwd_allowed(s["cwd"], s["sandbox"]):
            raise GptError("outside_roots", "This folder is outside the areas TubeCLI lets AI write to", 400)
        for k in ("tools", "tools_auto"):
            if k in patch:
                s[k] = bool(patch[k])
        # Telegram chatbot: token kiểm dạng «123456:ABC…» (rỗng = gỡ), chat id chỉ nhận số, cờ bật/tắt.
        if "telegram_token" in patch:
            tok = str(patch["telegram_token"] or "").strip()
            if tok and not TG_TOKEN_RE.match(tok):
                raise GptError("bad_setting", "Telegram bot token looks wrong (expected 123456789:ABC…)", 400)
            s["telegram_token"] = tok
        if "telegram_chat_ids" in patch:
            s["telegram_chat_ids"] = parse_chat_ids(patch["telegram_chat_ids"])
        if "telegram_enabled" in patch:
            s["telegram_enabled"] = bool(patch["telegram_enabled"])
        self.save_state(st)
        if "approval" in patch or "sandbox" in patch or "tools" in patch:
            self.loaded.clear()                 # lượt sau mở lại phiên với chế độ mới
            # Đổi chế độ duyệt/sandbox là đổi luật chơi ⇒ bỏ mọi «không hỏi lại» đã cho trước
            # đó, kẻo chủ máy siết lại mà phiên cũ vẫn tự duyệt.
            self.no_ask.clear()
        return {"auto_switch": st["auto_switch"], "settings": st["settings"]}

    async def apply_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Bật/tắt công cụ TubeCLI = đổi config.toml → app-server phải khởi động lại mới nạp (MCP mở lúc khởi động).
        Đang có lượt chạy thì để lần khởi động sau."""
        before = self.state()["settings"].get("tools")
        out = self.update_settings(patch)
        if "tools" in patch and bool(patch["tools"]) != bool(before) and not self.active_turns:
            async with self.lock:
                await self._stop_bridge()
        if any(k in patch for k in ("telegram_token", "telegram_chat_ids", "telegram_enabled")):
            await self.telegram.reconfigure()        # đổi bot / chat / bật-tắt → vòng poll chạy lại ngay
        out["telegram"] = self.telegram.public_status()
        return out

    @staticmethod
    def public_settings(st: Dict[str, Any]) -> Dict[str, Any]:
        """Settings cho trang: token Telegram KHÔNG bao giờ ra ngoài — chỉ cờ đã lưu."""
        pub = dict(st["settings"])
        pub["telegram_token_set"] = bool(pub.get("telegram_token"))
        pub["telegram_token"] = ""
        return pub

    async def status(self) -> Dict[str, Any]:
        ver = await asyncio.to_thread(cli.version)
        st = self.state()
        return {"installed": bool(cli.command()), "version": ver, "source": cli.source(),
                "install": cli.install_state(), "node": bool(shutil.which("node")),
                "accounts": self.accounts_public(), "active": st.get("active"), "auto_switch": st["auto_switch"],
                "settings": self.public_settings(st), "telegram": self.telegram.public_status(),
                "recent_cwds": st["recent_cwds"], "workspace": str(self.workspace),
                "default_cwd": self.default_cwd(),
                "home": str(self.home), "continue_text": CONTINUE_TEXT,
                "bridge": {"running": bool(self.bridge and self.bridge.alive), "error": self.bridge_error},
                "running": dict(self.active_turns), "platform": "windows" if os.name == "nt" else "posix",
                "writable_roots": self.writable_roots(), "win_sandbox": dict(self.win_sandbox)}


service = CodexGptService()
