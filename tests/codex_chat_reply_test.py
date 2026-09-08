# Ra lệnh trong chat thì phải NHẬN LẠI KẾT QUẢ ở đó.
#
# Người dùng gõ "làm video … đăng lên kênh mai le", chat trả "Content video queued as
# Codex #44" rồi im. Task chạy xong hay hỏng chỉ bắn Telegram và nằm trên bảng Codex,
# nên trong chat họ chỉ thấy lệnh được nhận chứ không bao giờ thấy kết quả — phải tự
# đi mở bảng mới biết. Ở đây kiểm: phiên chat đi theo task, và lúc task kết thúc thì
# đúng phiên ấy nhận một tin nhắn có kết quả (hoặc lỗi) kèm thẻ task.
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.core import intent_handlers as H  # noqa: E402
from tubecli.core import intent_router as R  # noqa: E402
from tubecli.extensions.codex.manager import CodexManager  # noqa: E402

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    if ok:
        print(f"  ok  {name}")
        return
    failures += 1
    print(f"  FAIL {name} — {detail}")


# ── 1. Phiên chat đi theo lượt dispatch, và vào origin của task ─────────────
router = R.IntentRouter()
seen = []
H.chat_session and None                       # hàm phải tồn tại
check("ngoài lượt dispatch thì không có phiên", H.chat_session() == "")
check("không có phiên → origin chỉ có agent", H.task_origin("a1") == {"agent_id": "a1"})

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

P.create_auto_task = lambda agent_id, options=None, created_by="", origin=None, job_label="", hp=None, hw=None, sources=None: (
    seen.append(("auto", origin)) or {"id": "0190a1b2-0000-7000-8000-00000000abcd", "seq": 44, "status": "queued"})
P.create_digest_task = lambda agent_id, options=None, created_by="", origin=None, sources=None, **k: (
    seen.append(("digest", origin)) or {"id": "0190a1b2-0000-7000-8000-0000000dddd1", "seq": 45, "status": "queued"})

intent = router.classify("làm video từ những gì đã đọc, thumbnail mẫu noal, đăng lên kênh mai le")
asyncio.run(H.dispatch(intent, {"id": "a1", "name": "CB"}, "vi", session_id="sess_9"))
check("task auto mang theo phiên chat", seen and seen[-1] == ("auto", {"agent_id": "a1", "chat_session": "sess_9"}), seen[-1:])

seen.clear()
asyncio.run(H.dispatch(router.classify("làm video từ những gì đã đọc hôm nay"), {"id": "a1"}, "vi", session_id="sess_9"))
check("task duyệt cũng mang theo phiên", seen and seen[-1] == ("digest", {"agent_id": "a1", "chat_session": "sess_9"}), seen[-1:])

seen.clear()
asyncio.run(H.dispatch(intent, {"id": "a1"}, "vi"))            # Telegram / lịch: không có phiên
check("không truyền phiên → origin không có chat_session", seen and "chat_session" not in (seen[-1][1] or {}), seen[-1:])
check("phiên được trả lại sau mỗi lượt", H.chat_session() == "")

# ── 2. Task kết thúc → tin nhắn vào ĐÚNG phiên ấy ──────────────────────────
posts = []
fake_store = types.SimpleNamespace(
    get_session=lambda sid: {"id": sid} if sid != "đã xoá" else None,
    append_message=lambda sid, role, content, meta=None: posts.append((sid, role, content, meta)))
import tubecli.extensions.chat.store as CS  # noqa: E402
CS.conversation_store = fake_store

m = CodexManager()
task = {"id": "t1", "seq": 44, "title": "Content video: CB", "status": "review",
        "origin": {"agent_id": "a1", "chat_session": "sess_9"}}
m.post_to_chat(task, "✅", "- **Published**: https://youtu.be/P7NZiLYEysQ (public)")
check("có một tin nhắn vào đúng phiên", len(posts) == 1 and posts[0][0] == "sess_9", posts)
sid, role, text, meta = posts[0]
check("là lời của agent", role == "assistant")
check("dòng đầu: icon + số task + tiêu đề", text.splitlines()[0] == "✅ Codex #44 · Content video: CB", text[:60])
check("thân tin nhắn là kết quả thật", "https://youtu.be/P7NZiLYEysQ" in text)
check("kèm thẻ task cho giao diện vẽ", meta.get("codex_task") == "t1" and meta.get("kind") == "codex_result"
      and meta.get("seq") == 44, meta)

posts.clear()
m.post_to_chat({"id": "t2", "seq": 45, "title": "X", "origin": {"agent_id": "a1"}}, "✅", "xong")
check("lệnh từ Telegram/lịch (không phiên) → không đăng gì", posts == [], posts)
m.post_to_chat({"id": "t3", "seq": 46, "title": "X", "origin": {"chat_session": "đã xoá"}}, "✅", "xong")
check("phiên đã bị xoá → không đẻ file mồ côi", posts == [], posts)

posts.clear()
long_body = "x" * (m.CHAT_PREVIEW + 500)
m.post_to_chat(task, "❌", long_body)
check("kết quả dài bị cắt, có dấu …", len(posts[0][2]) < m.CHAT_PREVIEW + 200 and posts[0][2].endswith("…"),
      len(posts[0][2]))

# Kho chat hỏng thì KHÔNG được làm hỏng lượt chạy đã xong.
def _boom(*a, **k):
    raise RuntimeError("chat store down")


CS.conversation_store = types.SimpleNamespace(get_session=_boom, append_message=_boom)
m.post_to_chat(task, "✅", "xong")
check("kho chat hỏng cũng không ném ra ngoài", True)

# ── 3. report_result / report_failure đều gọi đường này ────────────────────
src = (ROOT / "tubecli" / "extensions" / "codex" / "manager.py").read_text(encoding="utf-8")
after_result = src[src.index("def report_result"):src.index("def report_failure")]
after_fail = src[src.index("def report_failure"):src.index("def is_cancel_requested")]
check("xong việc thì trả kết quả về chat", 'self.post_to_chat(updated, "✅", result or "")' in after_result)
check("hỏng việc cũng báo về chat", 'self.post_to_chat(updated, "❌", error or "")' in after_fail)

print("=" * 62)
print(f"{failures} FAIL / {checks}" if failures else f"{checks}/{checks} PASS")
sys.exit(1 if failures else 0)
