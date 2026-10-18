# -*- coding: utf-8 -*-
"""Telegram ↔ Codex GPT (user 18/10/2026: «thêm chatbot telegram vào setting để đồng bộ, khi tạo phiên chat qua telegram»).

Chạy:  python tests/codex_gpt_telegram_test.py   (exit 0 = pass). Không gọi mạng thật: Telegram và service là đồ giả.

Luật canh:
  A. helper thuần: token «123456:ABC…», chat id chỉ số (âm = nhóm), cắt ≤ 4000 theo dòng, mô tả câu hỏi duyệt
  B. chat lạ chỉ nhận chat id của mình (1 lần/giờ), không tạo phiên; chat được phép: /start /id /stop /status /new,
     chữ thường → tạo phiên (đặt tên «📱 …»), ánh xạ chat→phiên LƯU vào state, lần sau dùng lại; đang chạy → chèn
  C. sự kiện Codex: gom agentMessage, lượt xong mới gửi (+ số lệnh, xoá «đang làm…»), lỗi/dừng nói rõ, phiên lạ
     im; câu hỏi duyệt → nút Cho phép / Cả phiên / Từ chối (công cụ once → không có «cả phiên»); callback → trả lời
     đúng key/decision, chat lạ không được; approval_done → sửa tin
  D. service thật: update_settings kiểm token, parse chat id, public_settings che token; chưa bật → start() False
  E. nối tĩnh: routes startup + /telegram/test, app.js có ô Telegram và gửi khi lưu, 9 locale, __version__ ≥ .205
"""
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TMP = Path(tempfile.mkdtemp(prefix="codex_gpt_tg_test_"))
os.environ["TUBECLI_CODEX_GPT_DIR"] = str(TMP / "data")

from tubecli.extensions.codex_gpt import telegram as T  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name}  {detail}")


TOKEN = "123456789:AAHfiqksKZ8WmR2zSjiQ7_v4TMAKdiHm9T0"


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = {}

    async def post(self, url, json=None):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, json or {}))
        if method in self.fail:
            return Resp(self.fail[method], {"ok": False, "description": "boom"})
        if method == "sendMessage":
            return Resp(200, {"ok": True, "result": {"message_id": len(self.calls)}})
        if method == "getMe":
            return Resp(200, {"ok": True, "result": {"username": "codex_bot"}})
        if method == "getUpdates":
            return Resp(200, {"ok": True, "result": []})
        return Resp(200, {"ok": True, "result": True})

    async def aclose(self):
        pass

    def of(self, method):
        return [c for m, c in self.calls if m == method]


class FakeService:
    def __init__(self):
        self._st = {"settings": {"telegram_enabled": True, "telegram_token": TOKEN, "telegram_chat_ids": ["111"]}}
        self.sent, self.interrupted, self.approvals, self.names = [], [], [], []
        self.threads = 0
        self.active_turns = {}
        self.subs = set()
        self.send_error = None

    def state(self):
        st = json.loads(json.dumps(self._st))
        st.setdefault("settings", {})
        return st

    def save_state(self, st):
        self._st = json.loads(json.dumps(st))

    async def start_thread(self, cwd="", model=""):
        self.threads += 1
        return {"id": f"thr-{self.threads}", "name": ""}

    async def send(self, tid, text, **kw):
        if self.send_error:
            raise self.send_error
        self.sent.append((tid, text))
        return {"turnId": "t1", "steered": tid in self.active_turns}

    async def interrupt(self, tid):
        self.interrupted.append(tid)
        return tid in self.active_turns

    async def thread_call(self, method, tid, **extra):
        self.names.append((method, tid, extra))

    async def read_thread(self, tid):
        return {"thread": {"id": tid, "name": "📱 hello"}, "running": self.active_turns.get(tid) or ""}

    def accounts_public(self):
        return [{"id": "a1", "label": "plus-main", "active": True}]

    async def answer_approval(self, key, decision):
        self.approvals.append((key, decision))
        return key != "gone"

    def subscribe(self):
        q = asyncio.Queue()
        self.subs.add(q)
        return q

    def unsubscribe(self, q):
        self.subs.discard(q)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── A. helper ─────────────────────────────────────────────────────────────────
print("A. helper")
check("token đúng dạng", T.TG_TOKEN_RE.match(TOKEN) is not None and T.TG_TOKEN_RE.match("abc") is None and T.TG_TOKEN_RE.match("123:short") is None)
check("parse_chat_ids: số, âm, bỏ rác/trùng", T.parse_chat_ids("111, -1001234, abc, 111 ; 222") == ["111", "-1001234", "222"]
      and T.parse_chat_ids(["5", 6, "x"]) == ["5", "6"] and T.parse_chat_ids(None) == [])
long = "\n".join("dòng %d %s" % (i, "x" * 90) for i in range(80))
parts = T.chunks(long)
check("chunks ≤ 4000, cắt theo dòng, ghép lại đủ", all(len(p) <= 4000 for p in parts) and len(parts) >= 2
      and all(not p.startswith("x") for p in parts) and "\n".join(parts).replace("\n", "") == long.replace("\n", ""))
check("chunks rỗng → []; dòng quá dài cắt cứng", T.chunks("  ") == [] and len(T.chunks("y" * 9000)) == 3)
d = T.describe_approval("item/commandExecution/requestApproval", {"command": ["rm", "-rf", "build"], "cwd": "/x", "reason": "clean"})
check("mô tả duyệt lệnh: lệnh + cwd + lý do", "rm -rf build" in d and "📁 /x" in d and "clean" in d and d.startswith("⚠"))
d2 = T.describe_approval("tubecli/tool", {"tool": "browser_open", "detail": "open youtube"})
check("mô tả duyệt công cụ TubeCLI", "browser_open" in d2 and "open youtube" in d2 and d2.startswith("🔧"))

# ── B. tin nhắn ───────────────────────────────────────────────────────────────
print("B. tin nhắn Telegram → Codex")
svc, cli = FakeService(), FakeClient()
br = T.TelegramBridge(svc, client_factory=lambda: cli)
check("configured khi bật + có token", br.configured() and br.allowed("111") and not br.allowed("999"))

async def b_flow():
    await br._on_message("999", "hello")
    s1 = cli.of("sendMessage")
    check("chat lạ: nhận chat id, không tạo phiên", len(s1) == 1 and s1[0]["chat_id"] == "999" and "999" in s1[0]["text"] and svc.threads == 0)
    await br._on_message("999", "hello again")
    check("chat lạ: không nhắc lại trong 1 giờ", len(cli.of("sendMessage")) == 1)
    await br._on_message("111", "/start")
    check("/start → hướng dẫn", "/new" in cli.of("sendMessage")[-1]["text"])
    await br._on_message("111", "/id")
    check("/id → chat id", "111" in cli.of("sendMessage")[-1]["text"])
    await br._on_message("111", "/stop")
    check("/stop khi không chạy → «không có lượt»", svc.interrupted == [] and "/new" not in cli.of("sendMessage")[-1]["text"])
    await br._on_message("111", "viết script đổi tên file")
    check("chữ thường: tạo phiên + gửi lượt + «đang làm…»", svc.threads == 1 and svc.sent == [("thr-1", "viết script đổi tên file")]
          and cli.of("sendMessage")[-1]["text"].startswith("⏳"))
    check("đặt tên phiên «📱 …» từ câu đầu", svc.names and svc.names[0][0] == "thread/name/set" and svc.names[0][2]["name"].startswith("📱 viết script"))
    check("ánh xạ chat→phiên LƯU vào state", (svc.state().get("telegram") or {}).get("threads", {}).get("111") == "thr-1" and br.chat_for("thr-1") == "111")
    check("placeholder nhớ theo phiên", "thr-1" in br.placeholders)
    await br._on_message("111", "tiếp tục")
    check("lần sau dùng lại phiên cũ", svc.threads == 1 and svc.sent[-1] == ("thr-1", "tiếp tục"))
    svc.active_turns["thr-1"] = "t1"
    await br._on_message("111", "thêm cả thư mục con")
    check("đang chạy → chèn (steer), báo «↪»", cli.of("sendMessage")[-1]["text"].startswith("↪"))
    await br._on_message("111", "/stop")
    check("/stop khi đang chạy → interrupt phiên của chat", svc.interrupted == ["thr-1"] and cli.of("sendMessage")[-1]["text"].startswith("⏹"))
    svc.active_turns.clear()
    await br._on_message("111", "/new dọn repo")
    check("/new <việc>: phiên mới, ánh xạ đổi, gửi việc", svc.threads == 2 and br.thread_for("111") == "thr-2" and svc.sent[-1] == ("thr-2", "dọn repo"))
    await br._on_message("111", "/status")
    t = cli.of("sendMessage")[-1]["text"]
    check("/status: tên phiên + tài khoản", "📱 hello" in t and "plus-main" in t)
    await br._on_message("111", "/whatever")
    check("lệnh lạ → hướng dẫn", "/new" in cli.of("sendMessage")[-1]["text"])
    svc.send_error = T.GptError if hasattr(T, "GptError") else RuntimeError("Thread not found")
    svc.send_error = RuntimeError("Thread not found")
    await br._on_message("111", "sau khi phiên bị xoá")
    check("phiên đã xoá trên trang → báo lỗi, không nổ", cli.of("sendMessage")[-1]["text"].startswith("⚠") or svc.threads == 3)
    svc.send_error = None

run(b_flow())

# ── C. sự kiện Codex → Telegram ──────────────────────────────────────────────
print("C. sự kiện Codex → Telegram")

async def c_flow():
    cli.calls.clear()
    tid = br.thread_for("111")      # cuối phần B: phiên bị «xoá» → chat đã được mở phiên mới
    check("sau lỗi «Thread not found» chat có phiên mới", tid == "thr-3" and svc.threads == 3, tid)
    br.placeholders[tid] = ("111", 42)
    await br.handle_event({"type": "event", "method": "item/completed", "params": {"threadId": tid, "item": {"type": "agentMessage", "text": "Đã xong phần 1"}}})
    await br.handle_event({"type": "event", "method": "item/completed", "params": {"threadId": tid, "item": {"type": "commandExecution", "command": "ls"}}})
    await br.handle_event({"type": "event", "method": "item/completed", "params": {"threadId": tid, "item": {"type": "agentMessage", "text": "Tổng kết: ok"}}})
    check("gom chữ, chưa gửi khi lượt chưa xong", cli.of("sendMessage") == [] and br.buffers.get(tid) == ["Đã xong phần 1", "Tổng kết: ok"])
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": tid, "turn": {"status": "completed"}}})
    s = cli.of("sendMessage")
    check("lượt xong → một tin gộp + số lệnh, xoá «đang làm…»", len(s) == 1 and "Đã xong phần 1" in s[0]["text"] and "Tổng kết: ok" in s[0]["text"]
          and "🛠" in s[0]["text"] and cli.of("deleteMessage") == [{"chat_id": "111", "message_id": 42}] and tid not in br.buffers)
    cli.calls.clear()
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": tid, "turn": {"status": "failed", "error": {"message": "usage limit"}}}})
    check("lượt lỗi → ❌ + lý do", cli.of("sendMessage")[-1]["text"].startswith("❌") and "usage limit" in cli.of("sendMessage")[-1]["text"])
    cli.calls.clear()
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": tid, "turn": {"status": "interrupted"}}})
    check("lượt bị dừng → ⏹", "⏹" in cli.of("sendMessage")[-1]["text"])
    cli.calls.clear()
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": tid, "turn": {"status": "completed"}}})
    check("xong mà không có chữ → nói rõ", cli.of("sendMessage")[-1]["text"].startswith("✅"))
    cli.calls.clear()
    await br.handle_event({"type": "event", "method": "item/completed", "params": {"threadId": "thr-x", "item": {"type": "agentMessage", "text": "lạ"}}})
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": "thr-x", "turn": {"status": "completed"}}})
    check("phiên không gắn chat → im lặng", cli.of("sendMessage") == [])
    await br.handle_event({"type": "event", "method": "item/completed", "params": {"threadId": tid, "item": {"type": "agentMessage", "text": "z" * 9000}}})
    await br.handle_event({"type": "event", "method": "turn/completed", "params": {"threadId": tid, "turn": {"status": "completed"}}})
    check("chữ dài → nhiều tin ≤ 4000", len(cli.of("sendMessage")) == 3 and all(len(c["text"]) <= 4000 for c in cli.of("sendMessage")))
    cli.calls.clear()
    await br.handle_event({"type": "approval", "key": "k1", "method": "item/commandExecution/requestApproval",
                           "params": {"threadId": tid, "command": ["git", "push"], "cwd": "/repo"}})
    a = cli.of("sendMessage")[-1]
    kb = a["reply_markup"]["inline_keyboard"]
    flat = [b["callback_data"] for row in kb for b in row]
    check("duyệt lệnh → tin có 3 nút đúng key", "git push" in a["text"] and flat == ["cg|k1|accept", "cg|k1|acceptForSession", "cg|k1|decline"])
    await br.handle_event({"type": "approval", "key": "k2", "method": "tubecli/tool", "params": {"threadId": tid, "tool": "town_agent_offer", "detail": "x", "once": True}})
    flat2 = [b["callback_data"] for row in cli.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"] for b in row]
    check("công cụ once → không có «cả phiên»", flat2 == ["cg|k2|accept", "cg|k2|decline"])
    await br.handle_event({"type": "approval", "key": "k9", "method": "execCommandApproval", "params": {"threadId": "thr-x", "command": "ls"}})
    check("duyệt của phiên lạ → không gửi", len(cli.of("sendMessage")) == 2)
    await br._on_callback({"id": "cq1", "data": "cg|k1|accept", "message": {"chat": {"id": 111}}})
    check("callback → answer_approval(k1, accept) + answerCallbackQuery", svc.approvals == [("k1", "accept")] and cli.of("answerCallbackQuery")[-1]["callback_query_id"] == "cq1")
    await br._on_callback({"id": "cq2", "data": "cg|k1|decline", "message": {"chat": {"id": 999}}})
    check("callback từ chat lạ → không trả lời duyệt", svc.approvals == [("k1", "accept")])
    await br._on_callback({"id": "cq3", "data": "cg|gone|accept", "message": {"chat": {"id": 111}}})
    check("key hết hạn → báo đã hết hạn", svc.approvals[-1] == ("gone", "accept") and cli.of("answerCallbackQuery")[-1]["text"])
    await br.handle_event({"type": "approval_done", "key": "k1", "decision": "accept"})
    e = cli.of("editMessageText")[-1]
    check("approval_done → sửa tin, bỏ nút", "→ accept" in e["text"] and e["reply_markup"] == {"inline_keyboard": []})
    cli.fail["sendMessage"] = 400
    await br.send("111", "x")
    check("Telegram từ chối → ghi error, không nổ", "boom" in br.error)
    cli.fail.clear()

run(c_flow())

# ── D. service thật ───────────────────────────────────────────────────────────
print("D. service thật: settings")
from tubecli.extensions.codex_gpt.service import CodexGptService, GptError  # noqa: E402
real = CodexGptService()
try:
    real.update_settings({"telegram_token": "not-a-token"})
    check("token sai dạng → bad_setting", False)
except GptError as e:
    check("token sai dạng → bad_setting", e.code == "bad_setting")
out = real.update_settings({"telegram_token": TOKEN, "telegram_chat_ids": "111, abc, -5", "telegram_enabled": False})
s = out["settings"]
check("lưu token + chat id đã lọc + cờ", s["telegram_token"] == TOKEN and s["telegram_chat_ids"] == ["111", "-5"] and s["telegram_enabled"] is False)
pub = CodexGptService.public_settings(real.state())
check("public_settings che token, có cờ đã lưu", pub["telegram_token"] == "" and pub["telegram_token_set"] is True and pub["telegram_chat_ids"] == ["111", "-5"])
check("chưa bật → start() False, không chạy", real.telegram.start() is False and real.telegram.running is False)
check("public_status", real.telegram.public_status() == {"enabled": False, "token_set": True, "running": False, "bot": "", "error": "", "chats": 2, "threads": 0})
real.update_settings({"telegram_token": ""})
check("token rỗng = gỡ", real.state()["settings"]["telegram_token"] == "" and real.telegram.configured() is False)
check("mặc định có 3 khoá telegram", all(k in real.state()["settings"] for k in ("telegram_enabled", "telegram_token", "telegram_chat_ids")))

# ── E. nối tĩnh ───────────────────────────────────────────────────────────────
print("E. nối tĩnh")
CG = ROOT / "tubecli" / "extensions" / "codex_gpt"
routes = (CG / "routes.py").read_text(encoding="utf-8")
check("routes: bật bot lúc startup + /telegram/test", '@router.on_event("startup")' in routes and "service.telegram.start()" in routes and 'API + "/telegram/test"' in routes)
svc_src = (CG / "service.py").read_text(encoding="utf-8")
check("service: reconfigure khi lưu telegram_*, status che token", "await self.telegram.reconfigure()" in svc_src and '"settings": self.public_settings(st), "telegram": self.telegram.public_status()' in svc_src)
app = (CG / "static" / "app.js").read_text(encoding="utf-8")
check("app.js: ô bật / token / chat id + gửi khi lưu (token chỉ khi có chữ)", all(x in app for x in ('id="sTgOn"', 'id="sTgTok"', 'id="sTgChats"', "telegram_enabled: $('sTgOn').checked", "...(tok ? { telegram_token: tok } : {})", "api('/telegram/test'")))
for lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
    d = json.loads((CG / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    miss = [k for k in ("tg_title", "tg_on", "tg_hint", "tg_token", "tg_token_set", "tg_chats", "tg_test", "tg_clear", "tg_sent", "tg_status_off", "tg_status_on", "tg_status_stopped", "tg_status_err") if not d.get("cg." + k)]
    check(f"locale {lang} đủ 13 khoá cg.tg_*", not miss, ",".join(miss))
mv = re.search(r'^__version__ = "2026\.08\.09\.(\d+)"', (ROOT / "tubecli" / "__init__.py").read_text(encoding="utf-8"), re.M)
check("__version__ >= .205", mv is not None and int(mv.group(1)) >= 205)

print(f"\n{ok}/{ok + fail} PASS")
sys.exit(1 if fail else 0)
