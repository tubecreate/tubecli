# The agent must SEE the content-video ability as a skill chip, and the skill
# must reach the endpoint carrying the agent that asked.
import asyncio
import inspect
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 1. the skill spec is an extension_action with a real endpoint (= runnable)
from tubecli.extensions.content_video import skills as CVS
spec = CVS.SKILLS[0]
assert spec["endpoint"] == "/api/v1/content-video/run" and spec["input_key"] == "input"
assert spec["with_agent"] is True and spec["name"] == "🎬 Content Video"
print("1 spec       : extension_action, endpoint thật, with_agent=True →", spec["name"])

# 2. registering is idempotent and lands in the store as runnable
from tubecli.core.skill import Skill
created = {}


class FakeSkill:
    def __init__(self, sid, name):
        self.id, self.name = sid, name


class FakeMgr:
    def __init__(self):
        self.store = {}

    def find_by_name(self, name):
        return self.store.get(name)

    def create(self, name=None, **kw):
        created[name] = kw
        self.store[name] = FakeSkill("s1", name)
        return self.store[name]

    def update(self, sid, **kw):
        created["updated"] = kw
        return None


import tubecli.core.skill as SK
real = SK.skill_manager
SK.skill_manager = FakeMgr()
try:
    st = CVS.register_skills()
    assert st == {"created": 1, "updated": 0}, st
    st2 = CVS.register_skills()
    assert st2 == {"created": 0, "updated": 1}, st2
finally:
    payload = created[spec["name"]]
    SK.skill_manager = real
assert payload["skill_format"] == "extension_action"
wf = payload["workflow_data"]
assert wf["endpoint"] == "/api/v1/content-video/run" and wf["with_agent"] is True
real_skill = Skill(name=spec["name"], **payload)
assert real_skill.is_runnable, "skill phải RUNNABLE, không thì giao diện/brain ẩn nó"
print("2 dang ky    : tạo 1 lần rồi cập nhật tại chỗ | Skill.is_runnable = True")

# 3. registering does NOT attach itself to any agent (owner's choice)
src = inspect.getsource(CVS)
assert "agent_manager" not in src and "allowed_skills" not in src
print("3 khong ep   : không tự gắn vào agent nào — chủ tự tick trong tab Kỹ năng")

# 4. on_enable registers the skill
from tubecli.extensions.content_video import extension as CVE
assert "register_skills" in inspect.getsource(CVE.ContentVideoExtension.on_enable)
print("4 on_enable  : gọi register_skills()")

# 5. brain forwards the agent when the skill asks for it
import tubecli.core.brain as B
bsrc = inspect.getsource(B)
i = bsrc.index('payload.setdefault(input_key, user_input)')
window = bsrc[i:i + 500]
assert 'wf_data.get("with_agent")' in window and 'payload.setdefault("agent_id"' in window, window[:300]
print("5 brain      : with_agent → payload kèm agent_id/agent_name")

# 6. the route takes the skill's shape and answers in words
from tubecli.extensions.content_video import routes as CVR
fields = CVR.RunRequest.model_fields if hasattr(CVR.RunRequest, "model_fields") else CVR.RunRequest.__fields__
for f in ("agent_id", "input", "agent_name", "sources", "options", "created_by"):
    assert f in fields, f
req = CVR.RunRequest(input="làm video hôm nay")


class Req:
    class state:
        guest_scope = None


out = asyncio.run(CVR.run_route(req, Req()))
assert out["status"] == "need_agent" and len(out["report"]) >= 40 and "agent" in out["report"].lower()
print("6 route      : thiếu agent → câu người đọc được (≥40 ký tự để brain chuyển nguyên văn)")

# 7. URLs in the sentence become crawl sources; skill path is created_by=brain
seen = {}


def fake_create(agent_id, options=None, created_by="user", origin=None, sources=None, **kw):
    seen.update(agent_id=agent_id, created_by=created_by, sources=sources, origin=origin)
    return {"id": "t1", "seq": 3, "status": "pending_approval"}


from tubecli.extensions.content_video import pipeline as P
P.create_digest_task = fake_create
req = CVR.RunRequest(agent_id="a1", agent_name="MC",
                     input="làm video hôm nay, thêm https://vnexpress.net/a.html nữa nhé")
out = asyncio.run(CVR.run_route(req, Req()))
assert seen["agent_id"] == "a1" and seen["created_by"] == "brain", seen
assert seen["sources"] == ["https://vnexpress.net/a.html"], seen["sources"]
assert seen["origin"]["agent_id"] == "a1"
assert out["report"].endswith("<!--codex:t1:3:pending_approval-->"), out["report"]
print("7 skill path : rút link ra làm nguồn | created_by=brain (chịu luật duyệt) | trả thẻ codex")

# 8. canvas path keeps an explicit created_by
seen.clear()
asyncio.run(CVR.run_route(CVR.RunRequest(agent_id="a1", created_by="user", sources=["https://x.y/z"]), Req()))
assert seen["created_by"] == "user" and seen["sources"] == ["https://x.y/z"]
print("8 canvas path: created_by tường minh được giữ nguyên")

# 9. the market install always runs the setup hook and reports its failure
msrc = io.open(os.path.join(ROOT, "tubecli", "extensions", "market", "routes.py"),
               encoding="utf-8").read()
assert "setup_error = None" in msrc and "Re-ran setup for already-enabled" in msrc
assert '"setup_error": setup_error' in msrc
i = msrc.index("setup_error = None")
assert "ext_obj.on_enable()" in msrc[i:i + 1200], "phải gọi lại on_enable cho extension đã bật"
print("9 cai dat    : luôn chạy lại on_enable; hỏng thì trả setup_error thay vì báo 'đã cài' suông")
print()
print("ALL 9 GROUPS PASSED")
