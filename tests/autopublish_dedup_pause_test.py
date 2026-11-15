"""14/11/2026 — contabo: 78 video dựng xong không đăng, 5 bản «Seek First: What Matthew 6:33 Really Means».

A. similar_topic / duplicate_task: câu tìm kiếm ≈ tiêu đề đã có; số chương-câu khác nhau thì KHÔNG trùng.
B. skip_window (hàm pipeline gọi từ 4/11 mà chưa từng tồn tại) chỉ tiến, không lùi.
C. Vòng «tự dừng vì video dài»: lần dừng ghi theo mức giới hạn chữ CŨ không còn giữ; fit_unverified cắt cảnh cho vừa.
D. set_publish / status / pause_agent / resume_agent + route PATCH /codex/autopublish, POST /agents/{id}/pause|resume.
E. parse_keyword_reply đọc được JSON hỏng vì nháy kép trong câu; xoay vòng từ khoá qua ngày.
F. Lưới chống trùng tiêu đề trong pipeline (dừng ở review trước khi dựng).

Cách ly: sổ autopublish ở thư mục tạm; agent_manager / codex / run_log đều giả; không mạng, không model.
"""
import asyncio
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
TMP = Path(tempfile.mkdtemp(prefix="ap_dedup_"))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


import tubecli.extensions.content_video.autopublish as AP  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

AP._store_path = lambda: TMP / "autopublish.json"
Q = 'latest What does "seek first the kingdom of God" mean in Matthew 6:33? news'
T = "Seek First: What Matthew 6:33 Really Means"

# ── A ──────────────────────────────────────────────────────────────────────────
check("A1 câu tìm kiếm ≈ tiêu đề video đã dựng (ca thật trên contabo)", AP.similar_topic(Q, T))
check("A2 hai tiêu đề gần trùng", AP.similar_topic("Seek First the Kingdom: Matthew 6:33 Explained", T))
check("A3 Matthew 6:33 và Matthew 6:34 là hai bài khác", not AP.similar_topic(
    'What does "do not worry about tomorrow" mean in Matthew 6:34?', T))
check("A4 chủ đề khác hẳn", not AP.similar_topic('What does "the narrow gate" mean in Matthew 7:13-14?', T))
check("A5 câu rỗng / toàn chữ vỏ không bao giờ trùng", not AP.similar_topic("latest news", T) and not AP.similar_topic("", T))
check("A6 tiếng Tây Ban Nha: cùng chủ đề", AP.similar_topic(
    "mejores prácticas de enseñanzas de Jesús sobre el dominio propio y la mente",
    "Enseñanzas de Jesús sobre el dominio propio y la mente"))

NOW = datetime.datetime.now().astimezone()
TASKS = [
    {"id": "t1", "seq": 198, "title": T, "status": "review", "assignee_id": "agB",
     "created_at": (NOW - datetime.timedelta(days=2)).isoformat(), "meta": {}},
    {"id": "t2", "seq": 150, "title": "Auto publish: Deep Biblical Echoes", "status": "review", "assignee_id": "agB",
     "created_at": (NOW - datetime.timedelta(days=1)).isoformat(), "meta": {"topic_query": "the narrow gate Matthew 7:13"}},
    {"id": "t3", "seq": 120, "title": "Guard Your Heart: Proverbs 4:23", "status": "cancelled", "assignee_id": "agB",
     "created_at": (NOW - datetime.timedelta(days=1)).isoformat(), "meta": {}},
    {"id": "t4", "seq": 90, "title": "My Grace Is Sufficient: 2 Corinthians 12:9", "status": "done", "assignee_id": "agB",
     "created_at": (NOW - datetime.timedelta(days=40)).isoformat(), "meta": {}},
    {"id": "t5", "seq": 80, "title": T, "status": "done", "assignee_id": "agOTHER",
     "created_at": (NOW - datetime.timedelta(days=1)).isoformat(), "meta": {}},
]


class FakeCodex:
    metas = {}

    def list_tasks(self, limit=50, **kw):
        return [dict(t) for t in TASKS]

    def set_meta(self, task_id, patch):
        self.metas[task_id] = patch

    def get_task(self, task_id):
        return next((t for t in TASKS if t["id"] == task_id), None)


AP._codex = lambda: FakeCodex()
check("A7 duplicate_task: câu tìm kiếm trùng tiêu đề task review", (AP.duplicate_task("agB", [Q]) or {}).get("id") == "t1")
check("A8 …so cả meta.topic_query của task chưa có tiêu đề thật", (AP.duplicate_task("agB", ["narrow gate in Matthew 7:13"]) or {}).get("id") == "t2")
check("A9 task đã HUỶ không tính", AP.duplicate_task("agB", ["guard your heart Proverbs 4:23"]) is None)
check("A10 task quá 21 ngày không tính", AP.duplicate_task("agB", ["my grace is sufficient 2 Corinthians 12:9"]) is None)
check("A11 task của agent KHÁC không tính", AP.duplicate_task("agX", [Q]) is None)
check("A12 exclude: không tự trùng với chính mình", AP.duplicate_task("agB", [T], exclude="t1") is None)

# ── B ──────────────────────────────────────────────────────────────────────────
check("B1 skip_window dời mốc tới", AP.skip_window("agB", "2026-11-14T02:00:00+00:00") and AP.get_mark("agB")["high_water"] == "2026-11-14T02:00:00+00:00")
check("B2 …không lùi về mốc cũ hơn, không nhận mốc rỗng", not AP.skip_window("agB", "2026-11-10T00:00:00+00:00")
      and not AP.skip_window("agB", "") and AP.get_mark("agB")["high_water"] == "2026-11-14T02:00:00+00:00")

# ── C ──────────────────────────────────────────────────────────────────────────
class Agent:
    def __init__(self, **kw):
        self.id, self.name = kw.pop("id", "agB"), "Deep Biblical Echoes"
        self.auto_publish, self.auto_video = True, True
        self.publish_max_per_day, self.publish_method = 2, "script"
        self.publish_profile, self.publish_channel_name = "gmail_pk0789743", "Pawan Kumar"
        self.publish_unverified, self.content_video_preset = True, "Ink"
        self.schedule_enabled = True
        for k, v in kw.items():
            setattr(self, k, v)


AP._preset_sig = lambda name: "sig1"
old = {"reason": AP.PAUSE_LONG_UNVERIFIED, "seconds": 1100, "preset": "Ink", "capped": True, "preset_sig": "sig1"}
check("C1 lần tự dừng ghi theo mức giới hạn CŨ (không có cap_words) không còn giữ", not AP._pause_holds(Agent(), dict(old)))
check("C2 …ghi theo mức 2000 chữ cũng không giữ", not AP._pause_holds(Agent(), dict(old, cap_words=2000)))
check("C3 đã viết theo mức MỚI mà vẫn dài → giữ", AP._pause_holds(Agent(), dict(old, cap_words=P.UNVERIFIED_SAFE_WORDS)))
AP.pause_for_length("agC", 1100, preset="Ink", capped=True)
check("C4 pause_for_length ghi mức giới hạn hiện tại", AP.get_mark("agC")["paused"].get("cap_words") == P.UNVERIFIED_SAFE_WORDS)
check("C5 mức xin mới đủ thấp để lố 20% vẫn dưới trần cứng", P.UNVERIFIED_SAFE_WORDS * 1.2 <= P.UNVERIFIED_HARD_WORDS + 80
      and P.UNVERIFIED_HARD_WORDS / 132 < 15, (P.UNVERIFIED_SAFE_WORDS, P.UNVERIFIED_HARD_WORDS))

scene = lambda i, n: f"[SHOW: scene {i}]\n" + " ".join(["word"] * n)
script = "TITLE: X\n\n" + "\n\n".join(scene(i, 100) for i in range(24))        # 2400 chữ
st = {"warnings": []}
out = P.fit_unverified(st, script)
check("C6 kịch bản 2400 chữ → cắt còn ≤ trần cứng", P.narration_words(out) <= P.UNVERIFIED_HARD_WORDS, P.narration_words(out))
check("C7 …giữ TITLE, cảnh mở đầu và cảnh KẾT", out.startswith("TITLE: X") and "[SHOW: scene 0]" in out and "[SHOW: scene 23]" in out
      and "[SHOW: scene 22]" not in out)
check("C8 …và nói rõ đã bỏ mấy cảnh", st["warnings"] and "dropped to fit" in st["warnings"][0], st["warnings"])
short = "TITLE: X\n\n" + "\n\n".join(scene(i, 100) for i in range(15))
check("C9 kịch bản vừa khung → để nguyên, không cảnh báo", P.fit_unverified({"warnings": []}, short) == short)

# ── D ──────────────────────────────────────────────────────────────────────────
AGENTS = {"agB": Agent(), "agOff": Agent(id="agOff", auto_publish=False, schedule_enabled=False)}


class FakeManager:
    def get(self, aid):
        return AGENTS.get(aid)

    def update(self, aid, **kw):
        for k, v in kw.items():
            setattr(AGENTS[aid], k, v)
        return AGENTS[aid]


import tubecli.core.agent as _agmod  # noqa: E402
_agmod.agent_manager = FakeManager()
AP.save_mark("agOff", paused=dict(old, cap_words=P.UNVERIFIED_SAFE_WORDS))
s0 = AP.status(AGENTS["agOff"])
check("D1 status: publish tắt, đang tự dừng vì video dài, có lý do đọc được", s0["publish"] is False and s0["paused_for_length"]
      and "15 min" in s0["paused_detail"], s0)
s1 = AP.set_publish("agOff", True, 3)
check("D2 bật publish + trần 3/ngày → agent đổi, gỡ luôn lần tự dừng", s1["publish"] is True and s1["daily_limit"] == 3
      and not s1["paused_for_length"] and AGENTS["agOff"].auto_publish is True, s1)
for bad in (0, 21, "nhiều"):
    try:
        AP.set_publish("agOff", True, bad)
        ok = False
    except ValueError:
        ok = True
    check(f"D3 trần sai ({bad!r}) bị từ chối", ok)
check("D4 trần sai không làm đổi trần đang có", AGENTS["agOff"].publish_max_per_day == 3)
r = AP.pause_agent("agB", by="connector")
check("D5 pause: tắt lịch, ghi cờ", r["paused"] and AGENTS["agB"].schedule_enabled is False and AP.get_mark("agB")["agent_paused"])
AP.pause_agent("agB")
check("D6 pause hai lần vẫn nhớ lịch TRƯỚC khi dừng là bật", AP.get_mark("agB")["agent_paused"].get("schedule_was") is True)
r = AP.resume_agent("agB")
check("D7 resume: bật lại lịch, gỡ cờ", r["schedule_enabled"] is True and AGENTS["agB"].schedule_enabled is True
      and not AP.get_mark("agB")["agent_paused"])
AP.pause_agent("agOff")
r = AP.resume_agent("agOff")
check("D8 agent vốn tắt lịch: resume không tự bật lịch", r["schedule_enabled"] is False)

AP.pause_agent("agB")
check("D9 agent đang tạm dừng → lượt thu thập không châm ngòi", "paused" in AP._maybe_publish("agB", "run-x", "completed", "schedule"))
AP.resume_agent("agB")

from tubecli.extensions.codex import routes as CR  # noqa: E402
from fastapi import HTTPException  # noqa: E402
got = asyncio.run(CR.get_autopublish("agB"))
check("D10 GET /codex/autopublish/{id}", got["agent_id"] == "agB" and got["publish"] is True and got["channel"] == "Pawan Kumar", got)
got = asyncio.run(CR.patch_autopublish("agB", CR.AutopublishPatch(publish=False)))
check("D11 PATCH publish=false", got["status"] == "updated" and got["publish"] is False and AGENTS["agB"].auto_publish is False)
got = asyncio.run(CR.patch_autopublish("agB", CR.AutopublishPatch(daily_limit=1)))
check("D12 PATCH chỉ daily_limit: giữ nguyên công tắc", got["daily_limit"] == 1 and got["publish"] is False)
for req, code in ((CR.AutopublishPatch(), 400), (CR.AutopublishPatch(daily_limit=99), 400)):
    try:
        asyncio.run(CR.patch_autopublish("agB", req))
        c = 200
    except HTTPException as e:
        c = e.status_code
    check(f"D13 PATCH sai → {code}", c == code, c)
try:
    asyncio.run(CR.get_autopublish("khong-co"))
    c = 200
except HTTPException as e:
    c = e.status_code
check("D14 agent không có → 404", c == 404)

# ── E ──────────────────────────────────────────────────────────────────────────
from tubecli.api import server as S  # noqa: E402

BROKEN = '''Here you go:
{
  "morning": ["What does "seek first the kingdom of God" mean in Matthew 6:33?", "What does "the narrow gate" mean in Matthew 7:13-14?"],
  "afternoon": ["Psalm 23 explained"],
  "evening": ["What does "guard your heart" mean in Proverbs 4:23?"],
  "night": ["Romans 8:28 explained", "John 1:14 explained"]
}'''
try:
    json.loads(BROKEN[BROKEN.index("{"):])
    really_broken = False
except ValueError:
    really_broken = True
got = S.parse_keyword_reply(BROKEN)
check("E1 mẫu thử đúng là JSON hỏng (nháy kép trong câu)", really_broken)
check("E2 parse_keyword_reply vẫn đọc đủ 4 buổi", set(got) == set(S.KEYWORD_PERIODS), got)
check("E3 …giữ nguyên câu có nháy kép bên trong", got.get("morning") == [
    'What does "seek first the kingdom of God" mean in Matthew 6:33?', 'What does "the narrow gate" mean in Matthew 7:13-14?'], got.get("morning"))
check("E4 JSON chuẩn vẫn đi đường json.loads", S.parse_keyword_reply('{"morning": ["a"], "afternoon": ["b"], "evening": ["c"], "night": ["d"]}')
      == {"morning": ["a"], "afternoon": ["b"], "evening": ["c"], "night": ["d"]})
check("E5 câu trả lời không có gì → {}", S.parse_keyword_reply("Sorry, I can't help with that.") == {})

today = "2026-11-14"
routine = {}
S.remember_keyword(routine, 'What does "seek first the kingdom of God" mean in Matthew 6:33?', "2026-11-13")
S.remember_keyword(routine, "old one", "2026-10-01")
hist = S.keyword_history(routine, today)
check("E6 lịch sử: câu hôm qua có, câu quá 21 ngày không", S._kw_key("what does seek first the kingdom of god mean in matthew 6 33") in hist
      and S._kw_key("old one") not in hist, hist)
S.remember_keyword(routine, "today one", today)
check("E7 câu của HÔM NAY không nằm trong lịch sử (đã có sổ «đã dùng hôm nay»)", S._kw_key("today one") not in S.keyword_history(routine, today))
src = Path(S.__file__).read_text(encoding="utf-8")
pick = src[src.index("available = [kw for kw in today_keywords if kw not in period_used]"):]
check("E8 bước chọn câu loại câu đã tìm trong những ngày trước, và ghi lại câu vừa dùng",
      "_fresh_kw = [kw for kw in available if _kw_key(kw) not in _kw_hist]" in pick[:2500]
      and "remember_keyword(routine_data, base_topic, today_date)" in pick[:6000])

# ── F ──────────────────────────────────────────────────────────────────────────
state = {"agent": Agent(), "task_id": "new", "title": "Seek First the Kingdom — Matthew 6:33 Explained"}
try:
    P._refuse_duplicate_title(state, {"autopublish": True})
    held = None
except P.NicheHold as h:
    held = h
check("F1 lượt tự động viết ra tiêu đề trùng → dừng ở review, nói rõ task nào", held is not None
      and "DUPLICATE TOPIC" in held.headline and "#198" in held.headline, held and held.headline)
try:
    P._refuse_duplicate_title(dict(state), {})
    manual_ok = True
except P.NicheHold:
    manual_ok = False
check("F2 task do NGƯỜI tạo (không autopublish) không bị chặn vì trùng", manual_ok)
try:
    P._refuse_duplicate_title(dict(state, title="The Narrow Road Home"), {"autopublish": True})
    fresh_ok = True
except P.NicheHold:
    fresh_ok = False
check("F3 tiêu đề mới → đi tiếp", fresh_ok)
from tubecli.extensions.codex import manager as CM  # noqa: E402
check("F4 META_KEYS nhận topic_query + bank_topic (trước bị bỏ lặng lẽ)", {"topic_query", "bank_topic"} <= set(CM.META_KEYS))

# ── G. trạng thái nói RÕ có đăng không + sửa «kênh chưa xác minh» / when / slots qua API (15/11/2026) ─────────────
AGENTS["agG"] = Agent(id="agG", publish_when="slots", publish_slots="12:00, 19:00")
AP.save_mark("agG", paused=dict(old, cap_words=P.UNVERIFIED_SAFE_WORDS))
g = AP.status(AGENTS["agG"])
check("G1 auto_publish BẬT mà đang tự dừng → will_publish False + lý do + cách gỡ", g["publish"] is True and g["will_publish"] is False
      and "not verified" in g["why_not"] and "channel_unverified" in g["why_not"], g)
check("G2 status trả when / when_choices / slots", g["when"] == "slots" and g["when_choices"] == ["now", "slots"] and g["slots"] == "12:00, 19:00", g)
g = AP.set_publish("agG", True, None, channel_unverified=False)
check("G3 channel_unverified=false → gỡ cờ của agent + gỡ lần tự dừng → sẽ đăng", AGENTS["agG"].publish_unverified is False
      and g["channel_unverified"] is False and not g["paused_for_length"] and g["will_publish"] is True and g["why_not"] == "", g)
for bad in ("later", "slot", ""):
    try:
        AP.set_publish("agG", True, None, when=bad)
        ok = False
    except ValueError as e:
        ok = "now, slots" in str(e)
    check(f"G4 when sai ({bad!r}) bị từ chối, kể tên giá trị hợp lệ", ok)
g = AP.set_publish("agG", True, None, when="now")
check("G5 when=now nhận", g["when"] == "now" and AGENTS["agG"].publish_when == "now")
g = AP.set_publish("agG", True, None, when="slots", slots="19h, 7am")
check("G6 when=slots + slots được chuẩn hoá", g["when"] == "slots" and g["slots"] == "07:00, 19:00", g)
AGENTS["agG2"] = Agent(id="agG2", publish_when="now", publish_slots="")
try:
    AP.set_publish("agG2", True, None, when="slots")
    ok = False
except ValueError as e:
    ok = "needs at least one time" in str(e)
check("G7 when=slots mà không có khung giờ nào → từ chối (không lặng lẽ đăng ngay)", ok and AGENTS["agG2"].publish_when == "now")
try:
    AP.set_publish("agG", True, None, slots="sáng mai")
    ok = False
except ValueError:
    ok = True
check("G8 slots không đọc được → từ chối", ok and AGENTS["agG"].publish_slots == "07:00, 19:00")
AGENTS["agG3"] = Agent(id="agG3", auto_publish=False)
g = AP.status(AGENTS["agG3"])
check("G9 auto_publish tắt → will_publish False, lý do «off»", g["will_publish"] is False and "off" in g["why_not"], g)
trig = (ROOT / "tubecli" / "extensions" / "content_video" / "autopublish.py").read_text(encoding="utf-8")
check("G10 ghi chú lượt chạy «render only» kèm LÝ DO", 'render only, waiting for review%s' in trig and "why_render_only" in trig
      and "publishing paused itself" in trig)
croutes = (ROOT / "tubecli" / "extensions" / "codex" / "routes.py").read_text(encoding="utf-8")
check("G11 PATCH /codex/autopublish nhận channel_unverified / when / slots", "channel_unverified: Optional[bool] = None" in croutes
      and "req.channel_unverified, req.when, req.slots" in croutes)

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
