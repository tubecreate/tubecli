# -*- coding: utf-8 -*-
"""Video từ NỘI DUNG DÁN TAY (cửa sổ "Nhiệm vụ mới" của Codex).

Cam kết được canh ở đây:
  1. Dán nội dung thì KHÔNG đụng tới kho của agent.
  2. Nội dung dán vào đi NGUYÊN VẸN tới model — luật chia ngân sách của kho (mỗi
     bài ≤ 4000 ký tự) mà áp lên một bài dán vào là cắt lặng lẽ nửa sau.
  3. Mẫu tiếng Tây Ban Nha + bài tiếng Việt → đề bài nói thẳng là phải DỊCH.
  4. Đường kho cũ không đổi một ký tự.
  5. Lượt dựng không mang theo nội dung gốc; câu mô tả task auto nói đúng lượt ấy.
  6. Route: có nội dung → task "Video from content", không cổng duyệt-trước-khi-chạy;
     review=False → task chạy thẳng; quá dài / thiếu agent → 400 nói rõ.
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

from fastapi import HTTPException  # noqa: E402

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label)


class Agent:
    def __init__(self, name="chuyen gia it", language="auto"):
        self.name, self.language, self.id = name, language, "a1"


def noop(*a, **k):
    return None


# Bài tiếng Việt DÀI HƠN 4000 ký tự, câu cuối là dấu để kiểm có bị cắt không.
VI_BODY = ("Điện toán đám mây đang thay đổi cách các doanh nghiệp vận hành hằng ngày. "
           "Những máy chủ ảo giúp lưu trữ dữ liệu và xử lý hàng triệu yêu cầu mỗi giây. ") * 40
TAIL = "Câu cuối cùng này phải còn nguyên trong đề bài gửi cho model."
VI_TEXT = VI_BODY + TAIL
assert len(VI_TEXT) > 4000

# ── 1. gather: nội dung dán tay không đụng kho ────────────────────────────
print("── gather ─────────────────────────────────────────────────────")


def _no_scan(**k):
    raise AssertionError("scan_window must not run when content is pasted")


P.scan_window = _no_scan
st = {"agent": Agent(), "profiles": [], "_say": noop, "warnings": []}
P._step_gather(st, {"source_text": "  " + VI_TEXT + "  ", "title": "Mây"})
ok(len(st["corpus"]) == 1 and st["corpus"][0]["source"] == "pasted", "một mục 'pasted' duy nhất")
ok(st["corpus"][0]["content"] == VI_TEXT, "nội dung đi nguyên văn (chỉ bỏ khoảng trắng hai đầu)")
ok(st["high_water"] == "", "mốc lịch tự đăng không nhúc nhích")
ok(not st["warnings"], "không cảnh báo khi dưới trần")

st = {"agent": Agent(), "profiles": [], "_say": noop, "warnings": []}
P._step_gather(st, {"source_text": "x" * (P.SOURCE_TEXT_MAX + 50)})
ok(len(st["corpus"][0]["content"]) == P.SOURCE_TEXT_MAX, "quá trần → cắt ở SOURCE_TEXT_MAX")
ok(any("only the first" in w for w in st["warnings"]), "…và NÓI RA là đã cắt")

# ── 2. script: không cắt, đề bài 'viết lại', nói rõ phải dịch ─────────────
print("── script (dán tay) ───────────────────────────────────────────")
seen = {}


def fake_ask(agent, system_prompt, user_prompt, words):
    seen["system"], seen["user"] = system_prompt, user_prompt
    return "TITLE: La nube\n\n[SHOW: Un servidor]\nUno dos tres cuatro."


P._ask_model = fake_ask
P._publish_plan = lambda *a, **k: 1
P._write_checkpoint = noop
P._checkpoint_sources = lambda state: []
P.resolve_words = lambda options, preset: (300, "option")   # ở dưới CHUNK_WORDS: viết một lượt

st = {"agent": Agent(), "corpus": [{"title": "", "url": "", "content": VI_TEXT, "source": "pasted"}],
      "preset": {"name": "nguoi que", "fields": {"language": "es"}}, "task_id": "t1",
      "checkpoint": {}, "_say": noop, "warnings": [], "feedback": []}
P._step_script(st, {})
ok(TAIL in seen["user"], "câu CUỐI của bài >4000 ký tự vẫn có trong đề bài")
ok("Rewrite this content" in seen["user"], "đề bài là 'viết lại nội dung này'")
ok("Content to turn into this video" in seen["user"], "giới thiệu nguyên liệu là nội dung dán vào")
ok("Material the agent collected" not in seen["user"], "không gọi nó là 'kho agent thu thập'")
ok(st["language"] == "es" and st["language_from"] == "preset", "ngôn ngữ lấy từ MẪU (es)")
ok("Spanish" in seen["system"] and "Vietnamese" in seen["system"] and "translate" in seen["system"],
   "system prompt nói rõ: bài tiếng Việt → DỊCH sang Spanish")
ok("the content you are given" in seen["system"], "system prompt không nói 'agent đã đọc và xem'")

# Cùng ngôn ngữ thì KHÔNG bảo dịch.
st["preset"] = {"name": "vi tpl", "fields": {"language": "vi"}}
st["checkpoint"] = {}
P._step_script(st, {})
ok("translate" not in seen["system"], "mẫu tiếng Việt + bài tiếng Việt → không có lệnh dịch")

# ── 3. đường kho cũ không đổi ─────────────────────────────────────────────
print("── script (kho, như cũ) ───────────────────────────────────────")
long_item = "Cloud computing moves storage to remote servers. " * 130 + "CORPUS-TAIL-MARKER"
assert len(long_item) > 4000
st = {"agent": Agent(language="en"),
      "corpus": [{"title": "A", "url": "http://a", "content": long_item, "source": "read"},
                 {"title": "B", "url": "http://b", "content": long_item, "source": "read"}],
      "preset": None, "task_id": "t2", "checkpoint": {}, "_say": noop, "warnings": [], "feedback": []}
P._step_script(st, {})
ok("Material the agent collected" in seen["user"], "kho vẫn được gọi là 'Material the agent collected'")
ok("CORPUS-TAIL-MARKER" not in seen["user"], "kho vẫn cắt mỗi bài ở ngân sách cũ (không đổi hành vi)")
ok("what the channel's agent read and watched" in seen["system"], "system prompt của kho giữ nguyên")

# ── 4. kết quả kế hoạch ───────────────────────────────────────────────────
print("── kết quả kế hoạch ───────────────────────────────────────────")
st = {"corpus": [{"content": "một hai ba bốn năm", "source": "pasted"}], "script": "x y",
      "title": "T", "scene_count": 1, "language": "es", "language_from": "preset", "warnings": []}
res = P._plan_result(st, {}, [], [])
ok("pasted content · ~5 words" in res, "'Based on' nói là nội dung dán vào, đếm đúng 5 chữ")
ok("articles read" not in res, "không nói 'articles read' cho lượt dán tay")

# ── 5. lượt dựng + câu mô tả task auto ────────────────────────────────────
print("── task ───────────────────────────────────────────────────────")
from tubecli.core.agent import agent_manager  # noqa: E402
from tubecli.extensions.codex.manager import codex_manager  # noqa: E402

made = {}


def fake_create_task(**k):
    made["task"] = k
    return {"id": "r1", "seq": 2}


def fake_append(task_id, kind, text, actor=None, data=None):
    made.setdefault("events", []).append(data or {})


codex_manager.create_task = fake_create_task
codex_manager.append_event = fake_append
codex_manager.get_events = lambda task_id, limit=1000: [
    {"data": {"kind": P.KIND_PLAN, "agent_id": "a1",
              "options": {"preset": "nguoi que", "source_text": VI_TEXT, "job_label": "Video from content"}}}]
P._read_checkpoint = lambda task_id: {"script": "kịch bản", "title": "La nube", "language": "es"}
P.create_render_task({"id": "p1", "seq": 1, "assignee_name": "A"})
render_opts = [e for e in made["events"] if e.get("kind") == P.KIND_RENDER][0]["options"]
ok("source_text" not in render_opts, "lượt dựng KHÔNG mang theo nội dung gốc")
ok(render_opts.get("preset") == "nguoi que", "…nhưng vẫn giữ mẫu")

agent_manager.get = lambda aid: Agent()
P.describe_plan = lambda options: "PLAN"
made.clear()
P.create_auto_task("a1", {"source_text": "abc"}, created_by="user", job_label="Video from content")
goal = made["task"]["goal"]
ok("Nội dung dán vào" in goal and "YouTube" not in goal and "video đã dựng xong" in goal,
   "auto dán tay không đăng: câu mô tả không nói 'thu thập' hay 'YouTube'")
made.clear()
P.create_auto_task("a1", {"publish": True}, created_by="autopublish")
goal = made["task"]["goal"]
ok("Thu thập xong" in goal and "đăng thẳng lên YouTube" in goal and "video đã lên rồi" in goal,
   "lịch tự đăng (publish=True): câu mô tả giữ nguyên như cũ")

# ── 6. route ──────────────────────────────────────────────────────────────
print("── route /content-video/run ───────────────────────────────────")
from tubecli.extensions.content_video import routes as RT  # noqa: E402

calls = {}


def fake_plan(agent_id, options=None, created_by="user", origin=None, sources=None, **k):
    calls["plan"] = {"agent_id": agent_id, "options": options, "created_by": created_by, **k}
    return {"id": "x", "seq": 5}


def fake_auto(agent_id, options=None, created_by="", origin=None, **k):
    calls["auto"] = {"agent_id": agent_id, "options": options, "created_by": created_by, **k}
    return {"id": "y", "seq": 6}


def fake_digest(agent_id, options=None, created_by="user", origin=None, sources=None, **k):
    calls["digest"] = {"agent_id": agent_id, "options": options, "created_by": created_by,
                       "origin": origin, "sources": sources, **k}
    return {"id": "z", "seq": 7}


# Chặn CẢ BA tên. Chỉ chặn tên mới là để lọt đường cũ ra codex_manager thật —
# chính cái bẫy suýt tạo task thật trên bảng Codex khi đổi route.
P.create_plan_task = fake_plan
P.create_auto_task = fake_auto
P.create_digest_task = fake_digest
P.queued_reply = lambda task: "queued"


class Req:
    class state:
        guest_scope = None


def run(**body):
    calls.clear()
    return asyncio.run(RT.run_route(RT.RunRequest(**body), Req()))


r = run(agent_id="a1", content="Nội dung cần làm video", options={"preset": "nguoi que"}, created_by="user")
pl = calls.get("plan") or {}
ok(r["status"] == "queued" and "auto" not in calls, "có nội dung + review → task hai chặng")
ok(pl.get("options", {}).get("source_text") == "Nội dung cần làm video", "nội dung vào options.source_text")
ok(pl.get("options", {}).get("preset") == "nguoi que", "mẫu đi cùng")
ok(pl.get("job_label") == "Video from content", "nhãn task 'Video from content'")
ok(pl.get("approval_required") is False, "người bấm Tạo = lời duyệt: không cổng trước khi chạy")

run(agent_id="a1", content="Nội dung", review=False, options={"preset": "nguoi que"}, created_by="user")
ok("auto" in calls and "plan" not in calls, "review=False → một task chạy thẳng tới mp4")
ok(calls["auto"]["options"].get("source_text") == "Nội dung", "…mang theo nội dung")

run(agent_id="a1", content="Nội dung", options={}, created_by="brain")
ok(calls["plan"].get("approval_required") is None, "lời gọi từ brain vẫn theo luật duyệt của codex")

run(agent_id="a1", input="làm video", options={"preset": "x"})
d = calls.get("digest") or {}
ok("plan" not in calls and "auto" not in calls, "không có nội dung → KHÔNG đi đường mới")
ok(d.get("options") == {"preset": "x"} and set(d) == {"agent_id", "options", "created_by", "origin", "sources"},
   "…mà gọi create_digest_task y như cũ: cùng tên, đúng năm đối số cũ")

try:
    run(agent_id="a1", content="x" * (P.SOURCE_TEXT_MAX + 1))
    ok(False, "quá dài phải bị từ chối")
except HTTPException as e:
    ok(e.status_code == 400 and "limit" in str(e.detail), "quá dài → 400 nói rõ giới hạn")
ok(not calls, "…và KHÔNG xếp việc nào")

try:
    run(content="Nội dung mà không có agent")
    ok(False, "thiếu agent phải bị từ chối")
except HTTPException as e:
    ok(e.status_code == 400 and "agent" in str(e.detail).lower(), "có nội dung mà thiếu agent → 400")

r = run(input="làm video")
ok(r.get("status") == "need_agent", "không nội dung, không agent → câu cũ 'need_agent'")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
