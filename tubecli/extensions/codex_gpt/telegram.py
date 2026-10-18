"""Telegram ↔ Codex GPT (user 18/10/2026: «thêm chatbot telegram vào setting để đồng bộ, khi tạo phiên chat qua telegram»).

Một bot Telegram riêng cho Codex GPT (Settings → Telegram chatbot). Mỗi chat Telegram được phép ↔ MỘT phiên chat Codex
(ánh xạ chat_id → threadId lưu trong state.json["telegram"]), nên phiên tạo từ điện thoại hiện ngay trong danh sách
chat của trang /codex-gpt và ngược lại trang thấy gì thì Telegram nhận câu trả lời đó.

  Telegram → Codex: chữ thường = gửi lượt vào phiên của chat (chưa có thì tạo phiên mới ở thư mục mặc định);
                    đang chạy thì «chèn» (steer) như trên trang. Lệnh: /new [việc], /stop, /status, /id, /help.
  Codex → Telegram: nghe kênh sự kiện của service (cùng kênh WebSocket của trang): gom agentMessage của lượt,
                    lượt xong (turn/completed) mới gửi — tối đa 4000 ký tự/tin, cắt theo dòng; lỗi / dừng nói rõ.
  Duyệt:            câu hỏi duyệt (lệnh, sửa file, công cụ TubeCLI) thành tin có nút «Cho phép / Cả phiên / Từ chối»
                    → callback_query → service.answer_approval; hết hạn thì service tự từ chối như trên trang.

An toàn: chỉ chat_id trong danh sách cho phép mới được nói chuyện (Codex ghi được thư mục làm việc) — chat lạ chỉ
nhận lại chat id của mình (1 lần/giờ) để chủ máy dán vào Settings. Token KHÔNG bao giờ trả ra /status (chỉ cờ đã
lưu). Dùng bot RIÊNG: cùng token với bot của một agent thì Telegram trả 409 cho một trong hai bộ poll — bắt 409 và
nói rõ. Best-effort tuyệt đối: vòng poll / vòng sự kiện không bao giờ chết vì một tin hỏng.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except Exception:      # noqa: BLE001 — thiếu httpx thì bridge chỉ báo lỗi, không kéo sập Codex GPT
    httpx = None

TG_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
MAX_TG = 4000                 # Telegram cho 4096; chừa chỗ cho đuôi
POLL_TIMEOUT = 30
NOTIFY_GAP_S = 3600           # chat lạ: nhắc chat id 1 lần/giờ
MAX_CHATS = 20

MSG = {
    "en": {
        "help": ("Codex GPT on TubeCLI.\nJust type what Codex should do — this chat is one Codex chat on the machine.\n"
                 "/new [task] start a new chat · /stop stop the running turn · /status what is running · /id your chat id"),
        "not_allowed": "This chat is not allowed yet. Your chat id: {id}\nPaste it into TubeCLI → Codex GPT → Settings → Telegram chatbot → Allowed chat ids.",
        "id": "Your chat id: {id}",
        "new": "New Codex chat started.",
        "started": "⏳ Codex is working…",
        "steered": "↪ Added to the turn that is already running.",
        "stopped": "⏹ Stop requested.",
        "nothing": "Nothing is running.",
        "status": "Chat: {name}\nRunning: {running}\nAccount: {account}",
        "done_empty": "✅ Done (Codex sent no text).",
        "failed": "❌ The turn failed: {err}",
        "interrupted": "⏹ The turn was stopped.",
        "cmds": "🛠 {n} command(s) ran",
        "ask_cmd": "⚠ Codex wants to run a command",
        "ask_file": "⚠ Codex wants to change files",
        "ask_tool": "🔧 Codex wants to use TubeCLI: {tool}",
        "allow": "✅ Allow", "allow_session": "Allow for this chat", "deny": "❌ Deny",
        "decided": "→ {decision}",
        "expired": "This question has already been answered or expired.",
        "test": "✅ Codex GPT on TubeCLI can reach this chat.",
        "error": "⚠ {err}",
    },
    "vi": {
        "help": ("Codex GPT trên TubeCLI.\nGõ việc cần Codex làm — chat này là một phiên chat Codex trên máy.\n"
                 "/new [việc] mở phiên mới · /stop dừng lượt đang chạy · /status đang chạy gì · /id xem chat id"),
        "not_allowed": "Chat này chưa được phép. Chat id của bạn: {id}\nDán vào TubeCLI → Codex GPT → Settings → Telegram chatbot → Chat id được phép.",
        "id": "Chat id của bạn: {id}",
        "new": "Đã mở phiên Codex mới.",
        "started": "⏳ Codex đang làm…",
        "steered": "↪ Đã chèn vào lượt đang chạy.",
        "stopped": "⏹ Đã yêu cầu dừng.",
        "nothing": "Không có lượt nào đang chạy.",
        "status": "Phiên: {name}\nĐang chạy: {running}\nTài khoản: {account}",
        "done_empty": "✅ Xong (Codex không gửi chữ).",
        "failed": "❌ Lượt lỗi: {err}",
        "interrupted": "⏹ Lượt đã bị dừng.",
        "cmds": "🛠 đã chạy {n} lệnh",
        "ask_cmd": "⚠ Codex muốn chạy lệnh",
        "ask_file": "⚠ Codex muốn sửa file",
        "ask_tool": "🔧 Codex muốn dùng TubeCLI: {tool}",
        "allow": "✅ Cho phép", "allow_session": "Cho cả phiên", "deny": "❌ Từ chối",
        "decided": "→ {decision}",
        "expired": "Câu hỏi này đã được trả lời hoặc hết hạn.",
        "test": "✅ Codex GPT trên TubeCLI nhắn tới chat này được.",
        "error": "⚠ {err}",
    },
}


def _lang() -> str:
    try:
        from tubecli.config import get_global_setting
        lang = str(get_global_setting("language", "en") or "en").lower()
    except Exception:      # noqa: BLE001
        lang = "en"
    return "vi" if lang.startswith("vi") else "en"


def tr(key: str, **kw) -> str:
    s = MSG.get(_lang(), MSG["en"]).get(key) or MSG["en"].get(key) or key
    try:
        return s.format(**kw)
    except (KeyError, IndexError):
        return s


def parse_chat_ids(value: Any) -> List[str]:
    """«123, -100987» / list → danh sách id hợp lệ (số, có thể âm = nhóm), bỏ trùng, tối đa MAX_CHATS."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[,\s;]+", str(value or ""))
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if re.fullmatch(r"-?\d{1,20}", p) and p not in out:
            out.append(p)
    return out[:MAX_CHATS]


def chunks(text: str, n: int = MAX_TG) -> List[str]:
    """Cắt theo dòng cho vừa trần Telegram; dòng quá dài thì cắt cứng."""
    text = (text or "").strip()
    if not text:
        return []
    out: List[str] = []
    while len(text) > n:
        cut = text.rfind("\n", 0, n)
        if cut < n // 2:
            cut = n
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    if text:
        out.append(text)
    return out


def _cmd_text(command: Any) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(c) for c in command)
    return str(command or "")


def describe_approval(method: str, params: Dict[str, Any]) -> str:
    p = params or {}
    if method == "tubecli/tool":
        head = tr("ask_tool", tool=str(p.get("tool") or "?"))
        detail = str(p.get("detail") or "").strip()
        return head + ("\n" + detail[:1500] if detail else "")
    is_file = bool(re.search(r"fileChange|applyPatch", str(method)))
    lines = [tr("ask_file") if is_file else tr("ask_cmd")]
    if p.get("command"):
        lines.append(_cmd_text(p["command"])[:1500])
    if p.get("cwd"):
        lines.append("📁 " + str(p["cwd"]))
    if p.get("reason"):
        lines.append(str(p["reason"])[:500])
    return "\n".join(lines)


class TgError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class TelegramBridge:
    def __init__(self, service, client_factory=None):
        self.svc = service
        self._client_factory = client_factory
        self.client = None
        self.tasks: List[asyncio.Task] = []
        self.running = False
        self.bot = ""
        self.error = ""
        self.queue: Optional[asyncio.Queue] = None
        self.buffers: Dict[str, List[str]] = {}             # tid → chữ Codex trong lượt đang chạy
        self.cmds: Dict[str, int] = {}                       # tid → số lệnh đã chạy trong lượt
        self.placeholders: Dict[str, Tuple[str, int]] = {}   # tid → (chat, message_id «đang làm…»)
        self.approval_msgs: Dict[str, Tuple[str, int, str]] = {}   # key → (chat, message_id, text)
        self.notified: Dict[str, float] = {}                 # chat lạ → lúc đã nhắc chat id

    # ── thiết lập ─────────────────────────────────────────────────────────────
    def settings(self) -> Dict[str, Any]:
        return self.svc.state()["settings"]

    def token(self) -> str:
        return str(self.settings().get("telegram_token") or "")

    def configured(self) -> bool:
        s = self.settings()
        return bool(s.get("telegram_enabled")) and bool(s.get("telegram_token"))

    def allowed_ids(self) -> List[str]:
        return parse_chat_ids(self.settings().get("telegram_chat_ids"))

    def allowed(self, chat_id: Any) -> bool:
        return str(chat_id) in set(self.allowed_ids())

    def public_status(self) -> Dict[str, Any]:
        s = self.settings()
        st = self.svc.state().get("telegram") or {}
        return {"enabled": bool(s.get("telegram_enabled")), "token_set": bool(s.get("telegram_token")),
                "running": self.running, "bot": self.bot, "error": self.error,
                "chats": len(self.allowed_ids()), "threads": len(st.get("threads") or {})}

    # ── ánh xạ chat ↔ phiên (state.json["telegram"]) ──────────────────────────
    def thread_for(self, chat_id: Any) -> Optional[str]:
        return ((self.svc.state().get("telegram") or {}).get("threads") or {}).get(str(chat_id))

    def chat_for(self, tid: str) -> Optional[str]:
        for c, t in (((self.svc.state().get("telegram") or {}).get("threads") or {})).items():
            if t == tid:
                return c
        return None

    def bind(self, chat_id: Any, tid: str) -> None:
        st = self.svc.state()
        tg = st.setdefault("telegram", {})
        threads = tg.setdefault("threads", {})
        threads[str(chat_id)] = tid
        self.svc.save_state(st)

    # ── vòng đời ──────────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Bật nếu đã cấu hình. Gọi từ startup của router và sau khi lưu Settings. Trả True nếu đang chạy."""
        if self.running:
            return True
        if not self.configured():
            return False
        if httpx is None:
            self.error = "httpx is not installed"
            return False
        self.error = ""
        self.running = True
        loop = asyncio.get_event_loop()
        self.tasks = [loop.create_task(self._poll_loop()), loop.create_task(self._events_loop())]
        return True

    async def stop(self) -> None:
        self.running = False
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):      # noqa: BLE001
                pass
        self.tasks = []
        if self.queue is not None:
            try:
                self.svc.unsubscribe(self.queue)
            except Exception:      # noqa: BLE001
                pass
            self.queue = None
        if self.client is not None:
            try:
                await self.client.aclose()
            except Exception:      # noqa: BLE001
                pass
            self.client = None

    async def reconfigure(self) -> bool:
        await self.stop()
        return self.start()

    # ── Telegram API ──────────────────────────────────────────────────────────
    def _client(self):
        if self.client is None:
            if self._client_factory is not None:
                self.client = self._client_factory()
            else:
                self.client = httpx.AsyncClient(timeout=httpx.Timeout(POLL_TIMEOUT + 15, connect=15.0))
        return self.client

    async def _api(self, method: str, **payload) -> Any:
        r = await self._client().post(f"https://api.telegram.org/bot{self.token()}/{method}", json=payload)
        try:
            data = r.json()
        except Exception:      # noqa: BLE001
            data = {}
        if r.status_code != 200 or not data.get("ok"):
            raise TgError(str(data.get("description") or f"HTTP {r.status_code}"), r.status_code)
        return data.get("result")

    async def send(self, chat_id: Any, text: str, markup: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Gửi chữ thường (không parse_mode — markdown của Codex không đoán được), cắt ≤ 4000. Trả message_id cuối."""
        mid = None
        parts = chunks(text) or [""]
        for i, part in enumerate(parts):
            payload: Dict[str, Any] = {"chat_id": chat_id, "text": part or "…", "disable_web_page_preview": True}
            if markup and i == len(parts) - 1:
                payload["reply_markup"] = markup
            try:
                res = await self._api("sendMessage", **payload)
                mid = (res or {}).get("message_id")
            except TgError as e:
                self.error = str(e)
                print(f"[CodexTG] sendMessage: {e}")
                break
        return mid

    async def edit(self, chat_id: Any, message_id: int, text: str, markup: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": chunks(text)[0] if text else "…",
                                   "disable_web_page_preview": True}
        payload["reply_markup"] = markup if markup else {"inline_keyboard": []}
        try:
            await self._api("editMessageText", **payload)
        except TgError as e:
            print(f"[CodexTG] editMessageText: {e}")

    async def delete(self, chat_id: Any, message_id: int) -> None:
        try:
            await self._api("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TgError:
            pass

    async def send_test(self) -> int:
        n = 0
        for c in self.allowed_ids():
            if await self.send(c, tr("test")) is not None:
                n += 1
        return n

    # ── vòng poll Telegram ────────────────────────────────────────────────────
    async def _poll_loop(self) -> None:
        try:
            await self._api("deleteWebhook", drop_pending_updates=False)
        except Exception as e:      # noqa: BLE001
            print(f"[CodexTG] deleteWebhook: {e}")
        try:
            me = await self._api("getMe")
            self.bot = str((me or {}).get("username") or "")
            print(f"[CodexTG] polling as @{self.bot}")
        except Exception as e:      # noqa: BLE001
            self.error = str(e)
            print(f"[CodexTG] getMe: {e}")
            if isinstance(e, TgError) and e.status == 401:
                self.running = False
                return
        offset = int((self.svc.state().get("telegram") or {}).get("offset") or 0)
        while self.running:
            try:
                updates = await self._api("getUpdates", offset=offset, timeout=POLL_TIMEOUT,
                                          allowed_updates=["message", "callback_query"])
                for u in updates or []:
                    offset = max(offset, int(u.get("update_id", 0)) + 1)
                    try:
                        await self.handle_update(u)
                    except Exception as e:      # noqa: BLE001
                        print(f"[CodexTG] update error: {e}")
                if updates:
                    st = self.svc.state()
                    st.setdefault("telegram", {})["offset"] = offset
                    self.svc.save_state(st)
            except asyncio.CancelledError:
                raise
            except TgError as e:
                self.error = str(e)
                if e.status == 401:
                    print("[CodexTG] token invalid — stopping")
                    self.running = False
                    return
                if e.status == 409:
                    self.error = "Another bot poller uses this token (an agent's Telegram bot?) — use a separate bot for Codex"
                    print(f"[CodexTG] 409 conflict — stopping: {self.error}")
                    self.running = False
                    return
                await asyncio.sleep(5)
            except Exception as e:      # noqa: BLE001
                self.error = str(e)
                await asyncio.sleep(5)

    async def handle_update(self, update: Dict[str, Any]) -> None:
        cq = update.get("callback_query")
        if cq:
            await self._on_callback(cq)
            return
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        if not chat_id:
            return
        await self._on_message(chat_id, str(msg.get("text") or ""))

    async def _on_message(self, chat_id: str, text: str) -> None:
        text = text.strip()
        if not self.allowed(chat_id):
            last = self.notified.get(chat_id, 0)
            if time.time() - last > NOTIFY_GAP_S:
                self.notified[chat_id] = time.time()
                await self.send(chat_id, tr("not_allowed", id=chat_id))
            return
        low = text.lower()
        if low in ("/start", "/help") or low.startswith("/help "):
            await self.send(chat_id, tr("help"))
            return
        if low == "/id":
            await self.send(chat_id, tr("id", id=chat_id))
            return
        if low == "/stop":
            tid = self.thread_for(chat_id)
            ok = await self.svc.interrupt(tid) if tid else False
            await self.send(chat_id, tr("stopped") if ok else tr("nothing"))
            return
        if low == "/status":
            await self._send_status(chat_id)
            return
        if low == "/new" or low.startswith("/new "):
            rest = text[4:].strip()
            tid = await self._new_thread(chat_id, rest)
            if not rest:
                await self.send(chat_id, tr("new"))
                return
            await self._send_turn(chat_id, tid, rest)
            return
        if text.startswith("/"):
            await self.send(chat_id, tr("help"))
            return
        tid = self.thread_for(chat_id) or await self._new_thread(chat_id, text)
        await self._send_turn(chat_id, tid, text)

    async def _new_thread(self, chat_id: str, first_text: str = "") -> str:
        t = await self.svc.start_thread()
        tid = str(t.get("id") or "")
        self.bind(chat_id, tid)
        name = ("📱 " + " ".join(first_text.split())[:50]) if first_text else "📱 Telegram"
        try:
            await self.svc.thread_call("thread/name/set", tid, name=name)
        except Exception:      # noqa: BLE001 — tên chỉ để nhìn, không có cũng được
            pass
        return tid

    async def _send_turn(self, chat_id: str, tid: str, text: str) -> None:
        try:
            r = await self.svc.send(tid, text)
        except Exception as e:      # noqa: BLE001
            msg = getattr(e, "message", None) or str(e)
            if getattr(e, "code", "") in ("thread_missing", "not_found") or "not found" in msg.lower():
                # Phiên đã bị xoá trên trang → mở phiên mới cho chat này rồi gửi lại
                tid = await self._new_thread(chat_id, text)
                try:
                    r = await self.svc.send(tid, text)
                except Exception as e2:      # noqa: BLE001
                    await self.send(chat_id, tr("error", err=getattr(e2, "message", None) or str(e2)))
                    return
            else:
                await self.send(chat_id, tr("error", err=msg))
                return
        if r.get("steered"):
            await self.send(chat_id, tr("steered"))
            return
        mid = await self.send(chat_id, tr("started"))
        if mid is not None:
            self.placeholders[tid] = (chat_id, mid)

    async def _send_status(self, chat_id: str) -> None:
        tid = self.thread_for(chat_id)
        name = "—"
        running = "no"
        if tid:
            name = tid[:8]
            try:
                r = await self.svc.read_thread(tid)
                th = r.get("thread") or {}
                name = th.get("name") or th.get("preview") or tid[:8]
                running = "yes" if r.get("running") else "no"
            except Exception:      # noqa: BLE001
                pass
        account = "—"
        try:
            for a in self.svc.accounts_public():
                if a.get("active"):
                    account = str(a.get("label") or a.get("email") or a.get("id") or "—")
                    break
        except Exception:      # noqa: BLE001
            pass
        await self.send(chat_id, tr("status", name=name, running=running, account=account))

    async def _on_callback(self, cq: Dict[str, Any]) -> None:
        cq_id = cq.get("id")
        data = str(cq.get("data") or "")
        chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id") or "")
        m = re.fullmatch(r"cg\|([^|]+)\|(accept|acceptForSession|decline)", data)
        answer = ""
        if not m or not self.allowed(chat_id):
            answer = tr("expired")
        else:
            key, decision = m.group(1), m.group(2)
            ok = await self.svc.answer_approval(key, decision)
            answer = tr("decided", decision=decision) if ok else tr("expired")
        if cq_id:
            try:
                await self._api("answerCallbackQuery", callback_query_id=cq_id, text=answer[:200])
            except TgError:
                pass

    # ── vòng sự kiện Codex ────────────────────────────────────────────────────
    async def _events_loop(self) -> None:
        self.queue = self.svc.subscribe()
        while self.running:
            try:
                msg = await self.queue.get()
            except asyncio.CancelledError:
                raise
            except Exception:      # noqa: BLE001
                await asyncio.sleep(1)
                continue
            try:
                await self.handle_event(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:      # noqa: BLE001
                print(f"[CodexTG] event error: {e}")

    def _keyboard(self, key: str, params: Dict[str, Any]) -> Dict[str, Any]:
        rows = [[{"text": tr("allow"), "callback_data": f"cg|{key}|accept"}]]
        if params.get("threadId") and not params.get("once"):
            rows[0].append({"text": tr("allow_session"), "callback_data": f"cg|{key}|acceptForSession"})
        rows.append([{"text": tr("deny"), "callback_data": f"cg|{key}|decline"}])
        return {"inline_keyboard": rows}

    async def handle_event(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "event":
            method = str(msg.get("method") or "")
            p = msg.get("params") or {}
            tid = str(p.get("threadId") or "")
            if not tid or self.chat_for(tid) is None:
                return
            if method == "item/completed":
                it = p.get("item") or {}
                if it.get("type") == "agentMessage" and str(it.get("text") or "").strip():
                    self.buffers.setdefault(tid, []).append(str(it["text"]).strip())
                elif it.get("type") == "commandExecution":
                    self.cmds[tid] = self.cmds.get(tid, 0) + 1
            elif method == "turn/completed":
                await self._turn_done(tid, p.get("turn") or {})
            return
        if kind == "approval":
            p = msg.get("params") or {}
            tid = str(p.get("threadId") or "")
            chat = self.chat_for(tid) if tid else None
            if not chat:
                return
            key = str(msg.get("key") or "")
            text = describe_approval(str(msg.get("method") or ""), p)
            mid = await self.send(chat, text, markup=self._keyboard(key, p))
            if mid is not None:
                self.approval_msgs[key] = (chat, mid, text)
            return
        if kind == "approval_done":
            rec = self.approval_msgs.pop(str(msg.get("key") or ""), None)
            if rec:
                chat, mid, text = rec
                await self.edit(chat, mid, text + "\n" + tr("decided", decision=str(msg.get("decision") or "")))
            return

    async def _turn_done(self, tid: str, turn: Dict[str, Any]) -> None:
        chat = self.chat_for(tid)
        texts = self.buffers.pop(tid, [])
        n = self.cmds.pop(tid, 0)
        ph = self.placeholders.pop(tid, None)
        if not chat:
            return
        status = str(turn.get("status") or "")
        err = str(((turn.get("error") or {}).get("message")) or "")
        if status == "failed":
            body = tr("failed", err=err or "?")
            if texts:
                body = "\n\n".join(texts) + "\n\n" + body
        elif status == "interrupted":
            body = ("\n\n".join(texts) + "\n\n" if texts else "") + tr("interrupted")
        else:
            body = "\n\n".join(texts) if texts else tr("done_empty")
        if n:
            body += "\n\n" + tr("cmds", n=n)
        if ph:
            await self.delete(ph[0], ph[1])
        await self.send(chat, body)
