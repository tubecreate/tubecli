"""18/11/2026 — contabo, «Deep Biblical Echoes»: «Matthew 6:33» làm 6 lần (#196–#206), lượt hẹn giờ bị «all candidate
profiles are in use» 3 ngày liền (16–18/11), Muse trả rỗng thì dùng lại bộ từ khoá cũ, bỏ «Channel not verified» mà tự
đăng không nói gì.

A. Cụm chủ đề (niche_memory): same_cluster / scripture_refs — câu viết khác nhưng cùng đoạn Kinh Thánh là MỘT cụm.
B. mark_cluster_used / cooled_clusters / cluster_cooldown: used + last_used, cooldown_days, task huỷ không chặn, task
   không tự chặn mình, nạp sổ một lần từ bảng việc (seed_from_tasks).
C. Từ khoá ngày (server): cụm đang nghỉ bị bỏ khỏi daily_keywords + có trong prompt; model chính trả rỗng → model DỰ
   PHÒNG của nhà khác thay vì dùng lại bộ cũ; bộ cũ dùng lại cũng bỏ cụm đang nghỉ.
D. Tự đăng: chủ đề thuộc cụm đang nghỉ thì không xếp việc; xếp việc / đăng ghi vào cụm.
E. Bỏ tick «Channel not verified» → mở lại tự đăng đang tạm dừng vì video dài NGAY + status có paused_at / resumed.
F. Khoá hồ sơ trình duyệt: phiên preview đã chết / attach mà trình duyệt đã thoát / mở quá lâu bị dọn; phiên còn giữ
   thì mô tả được (tên phiên, ai mở, bao lâu, pid).

Cách ly: mọi sổ ở thư mục TẠM; agent_manager / codex / key_manager / run_log giả; không mạng, không model thật.
"""
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
TMP = Path(tempfile.mkdtemp(prefix="topic_cluster_"))
os.environ.setdefault("TUBECLI_SKIP_STARTUP", "1")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:400]}")


import tubecli.extensions.content_video.niche_memory as NM  # noqa: E402
import tubecli.extensions.content_video.autopublish as AP  # noqa: E402

NM._store_path = lambda: TMP / "niche_memory.json"
AP._store_path = lambda: TMP / "autopublish.json"

T = "Seek First the Kingdom — What Matthew 6:33 Really Asks"

# ── A ──────────────────────────────────────────────────────────────────────────
SAME = ["what does 'seek first the kingdom' mean Matthew 6",
        'top What does "seek first the kingdom of God" mean in Matthew 6:33? tools',
        "Seek First: What Matthew 6:33 Really Means", "Matthew 6:33 explained", "seek first the kingdom of God meaning"]
for i, q in enumerate(SAME, 1):
    check(f"A{i} cùng cụm với «{T[:30]}…»: {q[:50]}", NM.same_cluster(q, T))
DIFF = ["deep bible study Matthew 6:9-13", "what does 'do not worry about tomorrow' mean Matthew 6",
        "Matthew 6:34 explained", "Psalm 23:4 explained", "top 10 bible verses", "Matthew 7:13 explained narrow gate"]
for i, q in enumerate(DIFF, len(SAME) + 1):
    check(f"A{i} KHÁC cụm: {q[:50]}", not NM.same_cluster(q, T))
check("A12 scripture_refs: khoảng câu + sách có số + bỏ «top 10»",
      NM.scripture_refs("Proverbs 3:5-6 and 1 Corinthians 13:4-7, top 10 tips")
      == [("proverbs", 3, 5, 6), ("1 corinthians", 13, 4, 7)], NM.scripture_refs("Proverbs 3:5-6 and 1 Corinthians 13:4-7, top 10 tips"))
check("A13 khoảng câu chồng nhau là một cụm", NM.same_cluster("Matthew 5:3-12 the Beatitudes", "Matthew 5:3 poor in spirit"))
check("A14 câu rỗng không bao giờ cùng cụm", not NM.same_cluster("", T) and not NM.same_cluster(T, "  "))

# ── B ──────────────────────────────────────────────────────────────────────────
TASK_STATUS = {}
NM._task_alive = lambda tid: TASK_STATUS.get(str(tid), "review") not in ("cancelled", "failed", "rejected")
NM._SEEDED.update({"agB", "agC", "agK", "agP"})          # sổ tạm: không nạp từ bảng việc thật

cid = NM.mark_cluster_used("agB", [T], "t206", "published")
c = NM.cooled_clusters("agB", 21)
check("B1 ghi cụm: label, uses 1, status published, last_used hôm nay", cid and len(c) == 1 and c[0]["uses"] == 1
      and c[0]["status"] == "published" and c[0]["last_used"] == datetime.date.today().isoformat(), c)
cid2 = NM.mark_cluster_used("agB", ["what does 'seek first the kingdom' mean Matthew 6"], "t207", "open")
c = NM.cooled_clusters("agB", 21)
check("B2 câu viết khác vào CÙNG cụm, uses 2, status không hạ cấp", cid2 == cid and len(c) == 1 and c[0]["uses"] == 2
      and c[0]["status"] == "published" and len(c[0]["aliases"]) == 1, c)
NM.mark_cluster_used("agB", [T], "t206", "published")
check("B3 cùng task ghi lại không tăng uses", NM.cooled_clusters("agB", 21)[0]["uses"] == 2)
check("B4 cluster_cooldown bắt câu khác chữ", (NM.cluster_cooldown("agB", "Matthew 6:33 explained", 21) or {}).get("id") == cid)
check("B5 chủ đề khác không bị chặn", NM.cluster_cooldown("agB", "Psalm 23:4 explained", 21) is None)
check("B6 cooldown 0 ngày = không chặn gì", NM.cooled_clusters("agB", 0) == [])
# cụm cũ quá cooldown
data = json.loads((TMP / "niche_memory.json").read_text(encoding="utf-8"))
old_day = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
data["agB"]["clusters"][cid]["last_used"] = old_day
(TMP / "niche_memory.json").write_text(json.dumps(data), encoding="utf-8")
check("B7 dùng 30 ngày trước, cooldown 21 → hết nghỉ", NM.cluster_cooldown("agB", T, 21) is None)
check("B8 …cooldown 45 → còn nghỉ", NM.cluster_cooldown("agB", T, 45) is not None)
# task MỞ đã bị huỷ → không chặn
NM.mark_cluster_used("agC", ["Guard Your Heart: Proverbs 4:23"], "tX", "open")
TASK_STATUS["tX"] = "cancelled"
check("B9 cụm chỉ có task mở đã HUỶ → không chặn", NM.cluster_cooldown("agC", "guard your heart Proverbs 4:23", 21) is None)
TASK_STATUS["tX"] = "review"
check("B10 …task còn mở → chặn", NM.cluster_cooldown("agC", "guard your heart Proverbs 4:23", 21) is not None)
check("B11 task không tự chặn mình (exclude_task)", NM.cooled_clusters("agC", 21, exclude_task="tX") == [])


class SeedCodex:
    def list_tasks(self, limit=50, **kw):
        now = datetime.datetime.now().astimezone()
        mk = lambda tid, title, st, d, **m: {"id": tid, "title": title, "status": st, "assignee_id": "agS",
                                              "created_at": (now - datetime.timedelta(days=d)).isoformat(), "meta": m}
        return [mk("s206", "Seek First the Kingdom — What Matthew 6:33 Really Asks", "done", 3),
                mk("s204", "Seek First: What Matthew 6:33 Really Means", "review", 4),
                mk("s202", "Seek First: What Matthew 6:33 Really Means", "cancelled", 5),
                mk("s195", "Auto publish: Deep Biblical Echoes", "review", 9, topic_query="the narrow gate Matthew 7:13"),
                mk("s100", "Be Still and Know: Psalm 46:10", "done", 40),
                {"id": "o1", "title": "Other agent", "status": "done", "assignee_id": "agZ", "created_at": now.isoformat()}]

    def published_video(self, tid):
        return {"url": "https://youtu.be/x"} if tid == "s206" else {}

    def get_task(self, tid):
        return None


import tubecli.extensions.codex.manager as _cmod  # noqa: E402
_real_cm = _cmod.codex_manager
_cmod.codex_manager = SeedCodex()
n = NM.seed_from_tasks("agS", 21)
cs = NM.cooled_clusters("agS", 21)
labels = " | ".join(c["label"] for c in cs)
check("B12 nạp sổ từ bảng việc: Matthew 6:33 (2 task sống) + narrow gate; bỏ task huỷ, task > 21 ngày, agent khác",
      n == 3 and len(cs) == 2 and "Matthew 6:33" in labels and "narrow gate" in labels and "Psalm 46" not in labels, (n, cs))
m633 = next(c for c in cs if "6:33" in c["label"])
check("B13 …status published (task done có link), last_used = ngày của task mới nhất (3 ngày trước)",
      m633["status"] == "published" and m633["last_used"] == (datetime.date.today() - datetime.timedelta(days=3)).isoformat(),
      m633)
check("B14 nạp MỘT lần (lần gọi sau không nạp lại)", NM.seed_from_tasks("agS", 21) == 0)
_cmod.codex_manager = _real_cm

# ── C: từ khoá ngày ────────────────────────────────────────────────────────────
from tubecli.api import server as S  # noqa: E402
from tubecli.core import run_log  # noqa: E402
from tubecli.core.brain import AgentBrain  # noqa: E402
import tubecli.core.agent as _agmod  # noqa: E402
import tubecli.core.scraped_store as _ss  # noqa: E402
from tubecli.core import llm_errors as LE  # noqa: E402

run_log._dir = lambda: TMP / "runs"
(TMP / "runs").mkdir(exist_ok=True)
_ss.resolve_profiles = lambda profiles: []
_ss.agent_profiles = lambda profiles, aid: []


class Agent:
    def __init__(self, **kw):
        self.id = kw.pop("id", "agK")
        self.name = "Deep Biblical Echoes Niche Researcher"
        self.niche = {"must_relate_to": ["Bible"], "cooldown_days": 21}
        self.system_prompt, self.research_prompt, self.description = "", "bible niche", ""
        self.routine = kw.pop("routine", {})
        self.model = "muse-spark"
        self.timezone, self.language = "Asia/Ho_Chi_Minh", "en"
        self.allowed_profiles, self.persona = [], {}
        self.publish_unverified = kw.pop("publish_unverified", False)
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model, "routine": self.routine}


class FakeManager:
    def __init__(self, ag):
        self.ag = ag

    def get(self, aid):
        return self.ag

    def update(self, aid, **kw):
        for k, v in kw.items():
            setattr(self.ag, k, v)
        return self.ag


class FakeKeys:
    def list_providers(self):
        return [{"id": "muse", "has_key": True, "capabilities": ["chat"], "models": ["muse-spark"]},
                {"id": "deepseek", "has_key": True, "capabilities": ["chat"], "models": ["deepseek-chat"]},
                {"id": "gemini", "has_key": False, "capabilities": ["chat"], "models": ["gemini-2.5-flash"]},
                {"id": "flux", "has_key": True, "capabilities": ["image"], "models": ["flux-1"]}]


import tubecli.extensions.cloud_api.extension as _cae  # noqa: E402
_cae.key_manager = FakeKeys()
import tubecli.config as _cfg  # noqa: E402
_cfg.read_global_settings = lambda: {_cfg.GLOBAL_DEFAULT_MODEL_SETTING: "muse-spark"}

OLD_KW = {"date": "2026-11-16", "morning": ["what does 'seek first the kingdom' mean Matthew 6", "Psalm 23:4 explained"],
          "afternoon": ["Matthew 6:33 explained"], "evening": ["Romans 8:28 explained"], "night": ["Isaiah 53 explained"]}
ag = Agent(routine={"daily_keywords": json.loads(json.dumps(OLD_KW))})
_agmod.agent_manager = FakeManager(ag)
NM.mark_cluster_used("agK", [T], "t206", "published")

chain = S._keyword_model_chain(ag)
check("C1 chuỗi model: agent → (mặc định trùng thì bỏ) → nhà khác có khoá, biết chat; bỏ nhà cùng tên / không khoá / ảnh",
      [m for m, _a in chain] == ["muse-spark", "deepseek|deepseek-chat"], [m for m, _a in chain])
LE.cool_down("deepseek", LE.QUOTA, "test")
check("C2 nhà đang nghỉ (hết lượt) không vào chuỗi", [m for m, _a in S._keyword_model_chain(ag)] == ["muse-spark"])
with LE._LOCK:
    LE._COOLING.pop("deepseek", None)

calls, prompts = [], []
GOOD = {"morning": ["Matthew 6:33 explained", "Psalm 23:4 explained"],
        "afternoon": ["what does 'seek first the kingdom' mean Matthew 6"],
        "evening": ["Romans 8:28 explained"], "night": ["Isaiah 53 explained", "deep bible study Matthew 6:9-13"]}


def llm(agent_dict, messages, temperature=0.7):
    calls.append(f"{agent_dict.get('provider') or ''}|{agent_dict.get('model')}")
    prompts.append(messages[-1]["content"])
    if agent_dict.get("model") == "muse-spark":
        return "[Muse Error] Muse returned an empty reply."
    return json.dumps(GOOD)


AgentBrain._call_llm = staticmethod(llm)
run_log.start("run-c1", "agK", "x")
out = S.check_and_generate_daily_keywords(ag, S._agent_now(ag), run_id="run-c1")
today = S._agent_now(ag).strftime("%Y-%m-%d")
check("C3 Muse trả rỗng → model dự phòng deepseek viết bộ MỚI (không dùng lại bộ cũ)",
      calls == ["|muse-spark", "deepseek|deepseek-chat"] and out.get("date") == today and not out.get("stale"), (calls, out))
check("C4 prompt nói rõ chủ đề đã làm (ALREADY COVERED + tên cụm)", "ALREADY COVERED" in prompts[0] and "Matthew 6:33" in prompts[0])
check("C5 câu thuộc cụm đang nghỉ bị bỏ (cả câu viết khác); câu khác giữ",
      out.get("morning") == ["Psalm 23:4 explained"] and "afternoon" not in out
      and out.get("night") == ["Isaiah 53 explained", "deep bible study Matthew 6:9-13"], out)
notes = [n for r in run_log.list_for_agent("agK", days=2) for n in (r.get("notes") or [])]
check("C6 nhật ký lượt chạy: số câu bị bỏ vì đã làm + model dự phòng đã viết",
      any("already covered" in n["text"] for n in notes) and any("backup model" in n["text"] for n in notes), notes)

# Mọi model đều hỏng → dùng lại bộ cũ NHƯNG bỏ cụm đang nghỉ
ag.routine = {"daily_keywords": json.loads(json.dumps(OLD_KW))}
AgentBrain._call_llm = staticmethod(lambda a, m, temperature=0.7: "[Muse Error] Muse returned an empty reply.")
out = S.check_and_generate_daily_keywords(ag, S._agent_now(ag), run_id="run-c1")
check("C7 hỏng hết → bộ cũ, nhưng không còn câu «seek first» / «Matthew 6:33»", out.get("stale")
      and out.get("morning") == ["Psalm 23:4 explained"] and "afternoon" not in out, out)
# model trả toàn câu đã làm → coi như hỏng, sang model kế
calls.clear()
ALL_COOLED = {p: ["Matthew 6:33 explained"] for p in S.KEYWORD_PERIODS}


def llm2(agent_dict, messages, temperature=0.7):
    calls.append(agent_dict.get("model"))
    return json.dumps(ALL_COOLED) if agent_dict.get("model") == "muse-spark" else json.dumps(GOOD)


AgentBrain._call_llm = staticmethod(llm2)
ag.routine = {"daily_keywords": json.loads(json.dumps(OLD_KW))}
out = S.check_and_generate_daily_keywords(ag, S._agent_now(ag), run_id="run-c1")
check("C8 model trả toàn chủ đề đã làm → thử model kế", calls == ["muse-spark", "deepseek-chat"]
      and out.get("morning") == ["Psalm 23:4 explained"], (calls, out))
d_cool, n_cool = S._drop_cooled_keywords(ag, {"morning": ["Matthew 6:33 explained", "Psalm 121 explained"]})
check("C9 _drop_cooled_keywords", d_cool == {"morning": ["Psalm 121 explained"]} and n_cool == 1, (d_cool, n_cool))

# ── D: tự đăng ─────────────────────────────────────────────────────────────────
agD = Agent(id="agK")
check("D1 _cooled_topic: câu tìm kiếm của lượt thu thập thuộc cụm đang nghỉ",
      (AP._cooled_topic(agD, "top What does 'seek first the kingdom' mean in Matthew 6:33? tools") or {}).get("label") == T)
check("D2 …chủ đề mới thì không", AP._cooled_topic(agD, "Psalm 121 explained") is None)
src = (ROOT / "tubecli" / "extensions" / "content_video" / "autopublish.py").read_text(encoding="utf-8")
check("D3 cò tự đăng: chặn «topic in cooldown» và ghi cụm khi xếp việc",
      "skip: topic in cooldown" in src and 'note_cluster(agent_id, task_id, "open", [topic_query])' in src)
check("D4 đăng (commit_published / count_published) ghi cụm «published»", src.count('note_cluster(aid, task_id, "published")') == 2)


class NoteCodex:
    def get_task(self, tid):
        return {"id": tid, "title": "Auto publish: Deep Biblical Echoes", "meta": {"topic_query": "Psalm 46:10 be still"}}


AP._codex = lambda: NoteCodex()
NM._SEEDED.add("agN")
AP.note_cluster("agN", "tN", "open")
check("D5 note_cluster: tiêu đề chung chung bị bỏ, câu tìm kiếm trong meta được ghi",
      [c["label"] for c in NM.cooled_clusters("agN", 21)] == ["Psalm 46:10 be still"], NM.cooled_clusters("agN", 21))
AP.commit_published("agN", "", "https://youtu.be/x", "tN")
check("D6 commit_published → cụm thành «published»", NM.cooled_clusters("agN", 21)[0]["status"] == "published")
psrc = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
check("D7 pipeline: tiêu đề thuộc cụm đang nghỉ → dừng ở review trước khi dựng; dựng xong ghi «rendered»",
      "⚠ TOPIC IN COOLDOWN" in psrc and '"rendered",' in psrc and "cluster_cooldown(\"\", q, 0, cooled=cooled)" in psrc)

# ── E: bỏ tick «Channel not verified» ──────────────────────────────────────────
AP._preset_sig = lambda name: "sig1"
agE = Agent(id="agE", publish_unverified=True, content_video_preset="Ink", auto_publish=True, auto_video=True,
            publish_max_per_day=2, publish_method="script", publish_profile="p", publish_channel_name="c")
_agmod.agent_manager = FakeManager(agE)
AP.pause_for_length("agE", 1082, preset="Ink", capped=True)
st = AP.status(agE)
check("E1 đang tạm dừng: status có paused_for_length + paused_at", st["paused_for_length"] and st["paused_at"], st)
check("E2 on_agent_saved: không đổi cờ → không làm gì", not AP.on_agent_saved("agE", True, True)
      and AP.get_mark("agE")["paused"])
agE.publish_unverified = False
check("E3 bỏ tick → mở lại NGAY (gỡ paused, ghi resumed)", AP.on_agent_saved("agE", True, False)
      and not AP.get_mark("agE")["paused"] and AP.get_mark("agE")["resumed"].get("reason", "").startswith("channel verified"))
st = AP.status(agE)
check("E4 status: hết paused_for_length, có resumed {at, reason, seconds}", not st["paused_for_length"]
      and st["resumed"].get("at") and st["resumed"].get("seconds") == 1082 and "Channel not verified" in st["resumed"]["reason"], st)
check("E5 không có lần dừng nào thì bỏ tick không ghi gì", not AP.on_agent_saved("agE", True, False))
agE.publish_unverified = True
AP.pause_for_length("agE", 1082, preset="Ink", capped=True)
AP.set_publish("agE", True, channel_unverified=False)
check("E6 PATCH /codex/autopublish channel_unverified:false cũng ghi resumed", not AP.get_mark("agE")["paused"]
      and "channel verified" in AP.get_mark("agE")["resumed"].get("reason", ""))
ssrc = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
check("E7 PUT /agents/{id}: so cờ cũ / mới rồi gọi on_agent_saved", "_AP.on_agent_saved(agent_id, was_unverified" in ssrc)

# ── F: khoá hồ sơ trình duyệt ──────────────────────────────────────────────────
import tubecli.extensions.browser.routes as BR  # noqa: E402


class Proc:
    def __init__(self, alive=True, pid=4321):
        self.alive, self.pid = alive, pid

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.alive = False


import time as _time  # noqa: E402
now = _time.time()
BR._cdp_alive = lambda port, timeout=1.5: int(port) == 9222
BR._preview_processes.clear()
BR._preview_processes.update({
    "dead": {"proc": Proc(False), "profile": "gmail_pk", "started_at": now - 60},
    "attach_gone": {"proc": Proc(), "profile": "gmail_pk", "attach": True, "cdp_port": 9333, "started_at": now - 120,
                    "opened_by": "canvas", "port": 41000},
    "stale": {"proc": Proc(), "profile": "gmail_pk", "started_at": now - 3 * 86400, "opened_by": "content_video",
              "port": 43479},
})
h = BR.preview_holder("gmail_pk", reap=True, now=now)
reaped = BR.pop_reaped_previews("gmail_pk")
check("F1 phiên chết / attach mà trình duyệt đã thoát / mở 3 ngày → dọn hết, hồ sơ rảnh", h is None
      and not BR._preview_processes, (h, list(BR._preview_processes)))
check("F2 …mỗi phiên bị dọn kể lại lý do (2 phiên còn sống bị đóng)", len(reaped) == 2
      and any("exited" in r["reason"] for r in reaped) and any("open for 3 d" in r["reason"] for r in reaped), reaped)
check("F3 pop_reaped_previews chỉ trả một lần", BR.pop_reaped_previews("gmail_pk") == [])
live = Proc(pid=999)
BR._preview_processes["preview_1"] = {"proc": live, "profile": "gmail_pk", "started_at": now - 600,
                                       "opened_by": "canvas", "port": 45000}
BR._preview_processes["attach_ok"] = {"proc": Proc(pid=998), "profile": "other", "attach": True, "cdp_port": 9222,
                                      "started_at": now - 60}
h = BR.preview_holder("gmail_pk", reap=True, now=now)
check("F4 live view thật (10 phút) vẫn giữ — KHÔNG giết", h and h["session_id"] == "preview_1" and live.alive, h)
d = BR.describe_holder(h)
check("F5 mô tả kẻ giữ: tên phiên, ai mở, bao lâu, pid, cổng",
      "preview_1" in d and "opened by canvas" in d and "10 min ago" in d and "pid 999" in d and "port 45000" in d, d)
check("F6 attach còn sống (CDP trả lời) không bị dọn", BR.preview_holder("other", reap=True, now=now)
      and "attach_ok" in BR._preview_processes)
check("F7 preview_holds_profile vẫn dùng được (bọc preview_holder)", BR.preview_holds_profile("gmail_pk"))
BR._preview_processes["nostamp"] = {"proc": Proc(), "profile": "p2"}
BR.preview_holder("p2", reap=True, now=now)
check("F8 phiên sổ cũ không có giờ mở → tính từ lần đầu thấy (không bị dọn oan)",
      "nostamp" in BR._preview_processes and BR._preview_processes["nostamp"]["started_at"] == now)
BR._preview_processes.clear()
check("F9 vòng lịch: ghi kẻ giữ vào lý do bỏ qua + ghi khoá hỏng đã dọn vào nhật ký lượt",
      "busy_holders.append(f\"'{_prof}' is held by {describe_holder(_holder)}\")" in ssrc
      and 'kind="profile_lock"' in ssrc and '" — " + "; ".join(busy_holders)' in ssrc)

print(f"\n{'=' * 62}\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
