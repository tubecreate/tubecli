"""
content_video: bộ đếm tiến độ, luồng SSE, và các lỗi phải nói rõ bệnh.

Run:  python tests/content_video_test.py     (exit 0 = pass)

Không server, không mạng. Hợp đồng HAI GIAI ĐOẠN (lập kế hoạch cho người dùng
duyệt, rồi mới dựng) do content_video_two_stage_test.py giữ; file này giữ những
mảnh KHÔNG nằm trong luồng đó — bộ đếm tiến độ của Content Studio, luồng SSE
dựng storyboard, và thông báo lỗi.

Vì sao tách: bản đầu của file này kiểm run_digest như một lượt chạy liền mạch.
Khi pipeline tách đôi, run_digest thành bí danh của run_plan, nên các khẳng định
về mp4 và về drama/episode thành sai — mà file lại nằm ngoài repo nên không ai
chạy, không ai biết. Nay ở trong repo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.content_video import pipeline as P

# 1. plan/describe_plan on the REAL check_job (extension manager)
# 9 = 5 bước kế hoạch + 4 bước dựng (RENDER_STEPS[0] trùng 'capabilities').
rows = P.plan({})
assert len(rows) == len(P.PLAN_STEPS) + len(P.RENDER_STEPS) - 1 == 9, rows
print("1 plan       : 9 steps |", P.describe_plan({}).splitlines()[2][:70])

# 2. poller: progress, completion, 'error: ...', cancel
P.POLL_SEC = 0
seq = [{"status": "starting", "done": 0, "total": 4},
       {"status": "running", "done": 2, "total": 4},
       {"status": "completed", "done": 4, "total": 4}]
P._get = lambda path, timeout=60: seq.pop(0)
calls = []
st = {"_cancelled": lambda: False, "_say": lambda *a: calls.append(a)}
d = P._poll_studio("/x", 10, st, "images", done_statuses=("completed",))
assert d["status"] == "completed" and any(len(a) > 3 and a[3] == 50 for a in calls), calls
seq[:] = [{"status": "error: RATE_LIMIT_REACHED", "done": 1, "total": 4}]
try:
    P._poll_studio("/x", 10, st, "images")
    raise SystemExit("poller must raise")
except RuntimeError as e:
    assert "RATE_LIMIT" in str(e), e
try:
    P._poll_studio("/x", 10, {"_cancelled": lambda: True, "_say": lambda *a: None}, "images")
    raise SystemExit("must cancel")
except Exception as e:
    assert P._is_cancel(e), e
print("2 poller     : progress 50% | 'error:' -> RuntimeError | cancel -> TaskCancelled")

# 3. SSE storyboard
import requests


class FakeResp:
    status_code = 200
    text = ""

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


msgs = []
requests.post = lambda *a, **k: FakeResp([
    'data: {"event":"status","message":"chunk 1/2"}', "",
    'data: {"event":"complete","saved_count":3}', "data: [DONE]"])
P._stream_storyboard(7, {"_cancelled": lambda: False, "_say": lambda s, st_, m, *r: msgs.append(m)})
assert msgs == ["chunk 1/2"], msgs
requests.post = lambda *a, **k: FakeResp([
    'data: {"event":"error","message":"No AI API key configured."}', "data: [DONE]"])
try:
    P._stream_storyboard(7, {"_cancelled": lambda: False, "_say": lambda *a: None})
    raise SystemExit("sse error must raise")
except RuntimeError as e:
    assert "No AI API key" in str(e)
print("3 SSE        : status -> progress | error -> RuntimeError | stops at [DONE]")


# ---- do gia dung chung cho nhom 4 --------------------------------
class Agent:
    id = "a1"
    name = "Median Content Creator"
    language = "vi"
    allowed_profiles = ["tuan5"]

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": "x"}


import tubecli.core.agent as AG
AG.agent_manager.get = lambda aid: Agent() if aid == "a1" else None
import tubecli.core.scraped_store as SS
SS.query = lambda **kw: {"items": [
    {"title": "Bai 1", "url": "https://vnexpress.net/1", "domain": "vnexpress.net", "has_content": True,
     "content": "noi dung bai mot " * 60, "scraped_at": "2026-09-04T01:00:00Z"},
    {"title": "Bai 2", "url": "https://vnexpress.net/2", "domain": "vnexpress.net", "has_content": True,
     "content": "noi dung bai hai " * 60, "scraped_at": "2026-09-04T02:00:00Z"},
    {"title": "Video da xem", "url": "https://www.youtube.com/watch?v=abc", "domain": "youtube.com",
     "has_content": False, "scraped_at": "2026-09-04T03:00:00Z"},
]}
P._agent_scope = lambda agent: list(agent.allowed_profiles)
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P.studio_capabilities = lambda: {"text": {"ok": True, "detail": "gemini-2.5-flash"},
                                 "image": {"ok": True, "detail": "API - cloudflare - flux"},
                                 "assembly": {"ok": True}, "voice": {"ok": True}}
import tubecli.core.brain as B
B.AgentBrain._call_llm = staticmethod(lambda agent, messages, temperature=0.7: (
    "TITLE: Ba tin nong hom nay\n\n[SHOW: city skyline at dawn]\nMo dau hap dan.\n"
    "[SHOW: a phone screen]\nKet thuc."))
posts, ck, sb_calls = [], [], {"n": 0}


def fake_post(path, payload, timeout=300):
    posts.append((path, payload))
    if path == "/api/v1/web_crawler/scrape":
        return {"data": [{"url": payload["url"], "title": "Trang nguon", "content": "van ban cao duoc " * 40}]}
    if path == "/api/v1/studio/dramas":
        return {"id": 12}
    if path == "/api/v1/studio/dramas/12/episodes":
        return {"id": 34}
    if path.endswith("/gen-images"):
        return {"task_id": "img1", "total": 3}
    if path.endswith("/batch-tts"):
        return {"task_id": "tts1"}
    if path.endswith("/export-ffmpeg"):
        return {"task_id": "exp1"}
    raise AssertionError("unexpected POST " + path)


def fake_get(path, timeout=60):
    if path == "/api/v1/studio/episodes/34/storyboards":
        sb_calls["n"] += 1
        return [] if sb_calls["n"] == 1 else [{"id": 1}, {"id": 2}, {"id": 3}]
    if path == "/api/v1/studio/gen-images/status/img1":
        return {"status": "completed", "done": 3, "total": 3, "errors": []}
    if path == "/api/v1/studio/batch-tts/tts1":
        return {"status": "done", "done": 3, "total": 3, "success": 3, "failed": 0}
    if path == "/api/v1/studio/export-ffmpeg/status/exp1":
        return {"status": "completed", "done": 100, "total": 100}
    if path == "/api/v1/studio/episodes/34":
        return {"id": 34, "video_url": r"C:\tubecli\data\content_studio\outputs\exports\episode_34_pipeline_export.mp4"}
    raise AssertionError("unexpected GET " + path)



# ---- 4. loi phai noi ro benh --------------------------------------
try:
    P.run_plan({"agent_id": "nope"}, None, None)
    raise SystemExit("must fail: agent")
except RuntimeError as e:
    assert "not found" in str(e)
SS.query = lambda **kw: {"items": []}
P._read_checkpoint = lambda tid: {}
try:
    P.run_plan({"agent_id": "a1", "task_id": "t2"}, None, None)
    raise SystemExit("must fail: empty corpus")
except RuntimeError as e:
    assert "nothing new" in str(e)
print("4 clear errs : missing agent -> 'not found' | empty corpus -> 'nothing new'")

print()
print("ALL 4 GROUPS PASSED")
