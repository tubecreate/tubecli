# Two-stage content video: plan (script → board, review) → accept → render.
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── A. codex manager: set_plan + on_accept on a throwaway store ────────
import tubecli.extensions.codex.manager as CMod

tmp = tempfile.mkdtemp(prefix="codex-test-")
CMod.CODEX_DATA_DIR = tmp
CMod.TASKS_FILE = os.path.join(tmp, "tasks.json")
CMod.EVENTS_DIR = os.path.join(tmp, "events")
cm = CMod.CodexManager()
cm.notifications_enabled = False
t = cm.create_task(goal="plan test", title="plan test", created_by="user", approval_required=False)
cm.append_event(t["id"], "log", "queued", actor="content_video", data={"kind": "content_video.plan", "task_id": t["id"]})
assert cm.kind_of(t["id"]) == "content_video.plan"
snap = cm.set_plan(t["id"], [{"step": 1, "description": "TITLE — x"}, {"step": 2, "description": "SHOW: a — b"}])
assert snap and len(snap["plan"]) == 2 and cm.get_task(t["id"])["plan"][1]["description"] == "SHOW: a — b"
fired = []
cm.on_accept("content_video.plan", lambda task, actor: fired.append((task["id"], actor)))
cm.claim_next()                                   # queued → running
cm.report_result(t["id"], "## script ready")      # running → review
assert cm.get_task(t["id"])["status"] == "review"
done = cm.complete_review(t["id"], True, actor="owner")
assert done["status"] == "done" and fired == [(t["id"], "owner")], fired
# a broken hook never breaks the click
t2 = cm.create_task(goal="p2", title="p2", created_by="user", approval_required=False)
cm.append_event(t2["id"], "log", "q", actor="x", data={"kind": "content_video.plan"})
cm.on_accept("content_video.plan", lambda task, actor: 1 / 0)
cm.claim_next(); cm.report_result(t2["id"], "r")
assert cm.complete_review(t2["id"], True)["status"] == "done"
assert any("Next stage could not be queued" in (e.get("message") or "") for e in cm.get_events(t2["id"], limit=1000))
print("A manager    : set_plan writes task.plan | on_accept fires (task, actor) | broken hook logged, accept stands")

# ── B. pipeline: scenes parser ─────────────────────────────────────────
from tubecli.extensions.content_video import pipeline as P

sc = P.scenes_of("[SHOW: city at dawn]\nHook line. Second.\n[SHOW: phone]\nClose.")
assert sc == [("city at dawn", "Hook line. Second."), ("phone", "Close.")], sc
assert P.scenes_of("plain narration only") == [("", "plain narration only")]
print("B scenes     : [SHOW] tags → (show, narration) pairs; untagged → one scene")


# ── C. run_plan: script goes to the board, NOT into the result ────────
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
    {"title": "Video da xem", "url": "https://www.youtube.com/watch?v=abc", "domain": "youtube.com",
     "has_content": False, "scraped_at": "2026-09-04T03:00:00Z"},
]}
P._agent_scope = lambda agent: list(agent.allowed_profiles)
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P.studio_capabilities = lambda: {"text": {"ok": True, "detail": "gemini"},
                                 "image": {"ok": False, "detail": "no provider", "fix": "add a Cloudflare key"},
                                 "assembly": {"ok": True}, "voice": {"ok": True}}
import tubecli.core.brain as B
prompts = []


def fake_llm(agent, messages, temperature=0.7):
    prompts.append(messages[-1]["content"])
    return "TITLE: Ba tin nong\n\n[SHOW: city at dawn]\nMo dau.\n[SHOW: phone]\nKet."


B.AgentBrain._call_llm = staticmethod(fake_llm)
P._post = lambda path, payload, timeout=300: {"data": [{"url": payload.get("url"), "title": "yt", "content": "transcript " * 30}]}
ck, plans = [], []
P._read_checkpoint = lambda tid: {}
P._write_checkpoint = lambda tid, d: ck.append(d)
CMod.codex_manager.set_plan = lambda tid, items, actor="pipeline": plans.append((tid, items))
CMod.codex_manager.get_task = lambda tid: {"id": tid, "goal": "Content video for agent MC"}
P._bulletin = lambda *a, **k: None
reports = []
out = P.run_plan({"kind": P.KIND_PLAN, "task_id": "t1", "agent_id": "a1", "options": {}},
                 lambda *a: reports.append(a), lambda: False)
assert out.startswith("## 📝 Script ready for review — Ba tin nong"), out[:80]
assert "[SHOW:" not in out and "Mo dau" not in out, "script must not be in the chat-visible result"
assert "Not ready for rendering" in out and "Cloudflare" in out, "image warning must be surfaced before accept"
assert plans and plans[0][0] == "t1" and plans[0][1][0]["description"] == "TITLE — Ba tin nong"
assert plans[0][1][1]["description"].startswith("SHOW: city at dawn — Mo dau"), plans[0][1]
assert ck and ck[-1]["script"].startswith("[SHOW: city at dawn]") and ck[-1]["title"] == "Ba tin nong"
assert [r[0] for r in reports if r[1] == "success"] == ["capabilities", "gather", "transcripts", "crawl", "script"]
assert "reviewer asked" not in prompts[-1]
print("C run_plan   : result short (no script) + image warning | plan on board | script checkpointed | 5/5 steps")

# ── D. revision: feedback in goal + checkpointed script → revise prompt ──
CMod.codex_manager.get_task = lambda tid: {"id": tid, "goal": "Content video…\n\n[Feedback from owner]: ngắn hơn, bỏ cảnh 2"}
P._read_checkpoint = lambda tid: {"script": "[SHOW: old]\nold narration", "title": "Old"}
out2 = P.run_plan({"kind": P.KIND_PLAN, "task_id": "t1", "agent_id": "a1", "options": {}}, None, None)
assert "reviewer asked for these changes" in prompts[-1] and "ngắn hơn, bỏ cảnh 2" in prompts[-1] and "old narration" in prompts[-1]
assert "Revision 1" in out2 and "ngắn hơn" in out2
print("D revision   : feedback from goal + previous script → revise prompt; result notes the revision")

# ── E. create_render_task from an accepted plan ────────────────────────
events, created = [], []
CMod.codex_manager.get_events = lambda tid, limit=200: [
    {"data": {"kind": "content_video.plan", "task_id": tid, "agent_id": "a1", "options": {"aspect_ratio": "9:16"}}},
    {"data": {"checkpoint": {"script": "[SHOW: x]\ny", "title": "T"}}},
]
P._read_checkpoint = lambda tid: {"script": "[SHOW: x]\ny", "title": "T"}
CMod.codex_manager.create_task = lambda **kw: created.append(kw) or {"id": "r1", "seq": 12, "status": "queued", **kw}
CMod.codex_manager.append_event = lambda *a, **k: events.append((a, k))
r = P.create_render_task({"id": "p1", "seq": 11, "assignee_id": "a1", "assignee_name": "MC", "origin": {"chat_id": "9"}}, "owner")
assert r and created[0]["approval_required"] is False and created[0]["origin"] == {"chat_id": "9"} and created[0]["created_by"] == "owner"
kind_ev = next(k["data"] for a, k in events if k.get("data", {}).get("kind") == "content_video.render")
assert kind_ev["script"] == "[SHOW: x]\ny" and kind_ev["plan_task_id"] == "p1" and kind_ev["options"] == {"aspect_ratio": "9:16"}
assert any(a[0] == "p1" and "render queued as #12" in a[2] for a, k in events)
print("E accept     : render task queued, no approval, origin carried, script + options in payload, plan task noted")

# ── F. run_render: accepted script → mp4 (HTTP mocked) ────────────────
posts, sb = [], {"n": 0}


def fake_post(path, payload, timeout=300):
    posts.append((path, payload))
    if path == "/api/v1/studio/dramas":
        return {"id": 12}
    if path == "/api/v1/studio/dramas/12/episodes":
        return {"id": 34}
    if path.endswith("/gen-images"):
        return {"task_id": "img1", "total": 2}
    if path.endswith("/batch-tts"):
        return {"task_id": "tts1"}
    if path.endswith("/export-ffmpeg"):
        return {"task_id": "exp1"}
    raise AssertionError(path)


def fake_get(path, timeout=60):
    if path == "/api/v1/studio/episodes/34/storyboards":
        sb["n"] += 1
        return [] if sb["n"] == 1 else [{"id": 1}, {"id": 2}]
    if "gen-images/status" in path:
        return {"status": "completed", "done": 2, "total": 2, "errors": []}
    if "batch-tts/" in path:
        return {"status": "done", "done": 2, "total": 2, "success": 2, "failed": 0}
    if "export-ffmpeg/status" in path:
        return {"status": "completed", "done": 100, "total": 100}
    if path == "/api/v1/studio/episodes/34":
        return {"id": 34, "video_url": r"C:\x\episode_34_pipeline_export.mp4"}
    raise AssertionError(path)


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


requests.post = lambda *a, **k: FakeResp(['data: {"event":"complete","saved_count":2}', "data: [DONE]"])
P._post, P._get = fake_post, fake_get
P.POLL_SEC = 0
P.installed_extensions = lambda: {"tts_vibevoice": True}      # voice engine: edge via the Studio
P.studio_capabilities = lambda: {"text": {"ok": True}, "image": {"ok": True, "detail": "cf"}, "assembly": {"ok": True}, "voice": {"ok": True}}
P._read_checkpoint = lambda tid: {}
reports.clear()
out3 = P.run_render({"kind": P.KIND_RENDER, "task_id": "r1", "agent_id": "a1", "script": "[SHOW: x]\ny", "title": "T",
                     "options": {"aspect_ratio": "9:16"}}, lambda *a: reports.append(a), lambda: False)
assert out3.startswith("## ✅") and "episode_34_pipeline_export.mp4" in out3 and "Accept" in out3
assert [r[0] for r in reports if r[1] == "success"] == ["capabilities", "studio", "images", "tts", "render"]
ep_payload = next(p for path, p in posts if path.endswith("/episodes"))
assert ep_payload["script_content"] == "[SHOW: x]\ny" and ep_payload["title"] == "T"
try:
    P.run_render({"agent_id": "a1", "task_id": "r2"}, None, None)
    raise SystemExit("render without script must fail")
except RuntimeError as e:
    assert "No script" in str(e)
print("F run_render : 5/5 steps → mp4 | script/title from payload | no script → clear error")

# ── G. run_kind dispatch + legacy names ────────────────────────────────
assert P.run_kind.__name__ == "run_kind" and P.create_digest_task is P.create_plan_task and P.run_digest is P.run_plan
try:
    P.run_kind("content_video.nope", {}, None, None)
    raise SystemExit("unknown kind must raise")
except RuntimeError:
    pass
print("G dispatch   : run_kind routes plan/render; legacy names alias; unknown kind raises")
print()
print("ALL 7 GROUPS PASSED")
