"""10/11/2026 — contabo: kênh Kinh Thánh không ra video nhiều ngày liền.

A. niche.from_system_prompt / effective: ô Niche trống → lấy khối «NICHE CONFIG» trong system prompt.
B. _step_niche: bỏ nguồn > 30 ngày + nguồn đã bị loại lượt trước TRƯỚC khi chấm; nhớ nguồn bị loại.
C. < 3 nguồn đúng ngách → KHÔNG dừng: chủ đề lấy từ kho từ khoá (daily_keywords), bỏ chủ đề dùng trong 21 ngày,
   meta keyword_source=bank; kho rỗng → vẫn dừng (BANK_LOW).
D. check_and_generate_daily_keywords: model hỏng → ghi lỗi vào run_log.note + dùng lại bộ cũ (không rơi về
   «github trending»); ngày theo múi giờ agent.
E. youtube_video_id: link trợ giúp support.google.com không phải video; bước đăng không id → «warning» UNVERIFIED.
F. Tên kênh không khớp hồ sơ đăng đã chọn → dừng đăng (channel_mismatch).
G. Model ảnh chết (Studio dead_image_models) → một dòng mỗi model.

Mọi sổ (niche_memory, run_log) ghi vào thư mục TẠM; không gọi model thật, không mạng.
"""
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="niche_fb_"))

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


from tubecli.core import niche as N  # noqa: E402
import tubecli.extensions.content_video.niche_memory as NM  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

NM._store_path = lambda: TMP / "niche_memory.json"

PROMPT = """You are a researcher.

NICHE CONFIG
Channel: Deep Biblical Echoes
Language: English
Niche: the meaning and context of Bible passages
Must relate to: Bible, scripture passages, Jesus, prayer
Deny terms (never use, even with a "biblical angle"): stocks, markets, Big Tech, layoffs
Minimum niche score: 8 / 10
Keyword bank: the channel's keyword bank (clusters with score)

1. Niche gate — run on EVERY item
"""


class Agent:
    def __init__(self, **kw):
        self.id = kw.pop("id", "agB")
        self.name = kw.pop("name", "Deep Biblical Echoes Niche Researcher")
        self.niche = kw.pop("niche", {})
        self.system_prompt = kw.pop("system_prompt", PROMPT)
        self.research_prompt = kw.pop("research_prompt", "study the bible niche")
        self.description = ""
        self.routine = kw.pop("routine", {})
        self.model = "muse-spark"
        self.timezone = kw.pop("timezone", None)
        self.language = "en"
        self.allowed_profiles = kw.pop("allowed_profiles", [])
        self.persona = {}
        for k, v in kw.items():
            setattr(self, k, v)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model, "routine": self.routine}


# ── A ──────────────────────────────────────────────────────────────────────────
blk = N.from_system_prompt(PROMPT)
check("A1 đọc khối NICHE CONFIG: phải liên quan + từ cấm + điểm", blk.get("must_relate_to") and blk.get("deny_terms")
      and blk.get("min_niche_score") == "8", blk)
cfg, w = N.effective(Agent())
check("A2 ô Niche trống → dùng khối prompt, cảnh báo FROM_PROMPT (không phải UNCONFIGURED)",
      w == [N.FROM_PROMPT] and cfg["must_relate_to"][:2] == ["Bible", "scripture passages"]
      and "Big Tech" in cfg["deny_terms"] and cfg["min_niche_score"] == 8, (w, cfg))
cfg, w = N.effective(Agent(niche={"must_relate_to": ["Psalms"], "min_niche_score": 6}))
check("A3 ô Niche đã khai giữ nguyên, chỉ điền trường còn trống (từ cấm)", cfg["must_relate_to"] == ["Psalms"]
      and cfg["min_niche_score"] == 6 and "layoffs" in cfg["deny_terms"], cfg)
cfg, w = N.effective(Agent(system_prompt="no block here"))
check("A4 không có khối → UNCONFIGURED như cũ", w == [N.UNCONFIGURED], w)
check("A5 khối kết thúc ở dòng trống — không nuốt mục «1. Niche gate»",
      "niche_description" in blk and "1" not in json.dumps(blk.get("must_relate_to")), blk)

# ── B + C: _step_niche ─────────────────────────────────────────────────────────
META, EVENTS = {}, []
P._task_meta = lambda task_id, **patch: META.update({k: v for k, v in patch.items() if v not in (None, "")})
P._task_event = lambda task_id, message: EVENTS.append(message)


def fake_gate(agent, text, kind="item", cfg=None):
    t = str(text).lower()
    if any(x in t for x in ("matthew", "psalm", "jesus", "what does")):
        return {"pass": True, "score": 9, "reason": "on niche", "deny": ""}
    return {"pass": False, "score": 2, "reason": "off the niche", "deny": ""}


N.niche_gate = fake_gate
P._open_bank_topics = lambda agent_id, exclude="": set()
OLD = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=45)).isoformat()
NEW = datetime.datetime.now(datetime.timezone.utc).isoformat()
TECH = [{"title": f"GitHub trending repo {i}", "url": f"https://tech.example/{i}", "content": "a repo", "source": "read",
         "scraped_at": NEW} for i in range(4)]
BIBLE = [{"title": "Matthew 5 explained", "url": "https://b.example/1", "content": "Jesus taught", "source": "read",
          "scraped_at": NEW}]
ROUTINE = {"daily_keywords": {"date": "2026-11-03",
                              "morning": ["What does \"seek first the kingdom\" mean in Matthew 6:33?",
                                          "What does \"the narrow gate\" mean in Matthew 7:13?"],
                              "afternoon": ["stocks to buy this week"]}}


def st_for(corpus, agent=None):
    return {"agent": agent or Agent(routine=ROUTINE), "task_id": "t1", "corpus": corpus, "videos": [], "warnings": [],
            "checkpoint": {}, "_say": lambda *a, **k: None, "_cancelled": lambda: False}


st = st_for([dict(c) for c in TECH] + [dict(c) for c in BIBLE])
P._step_niche(st, {"autopublish": True})
check("C1 1/5 nguồn đúng ngách → KHÔNG dừng, chủ đề lấy từ kho từ khoá",
      st.get("bank_topic", "").startswith("What does \"seek first"), st.get("bank_topic"))
check("C2 meta: source=bank, keyword_source=bank, bank_topic", META.get("keyword_source") == "bank"
      and META.get("source") == "bank" and "seek first" in META.get("bank_topic", ""), META)
first = st["corpus"][0]
check("C3 mục đầu của corpus là lời dặn chủ đề (source bank) + nguồn đúng ngách giữ lại, nguồn lạc bị bỏ",
      first.get("source") == "bank" and "seek first" in first["content"]
      and [c["title"] for c in st["corpus"][1:] if c.get("content")] == ["Matthew 5 explained"], st["corpus"])
check("C4 BANK_LOW khi kho còn < 10 chủ đề", META.get("bank_low") and any("BANK_LOW" in w for w in st["warnings"]),
      (META, st["warnings"]))
check("B1 nguồn bị loại được nhớ", set(NM.rejected_urls("agB")) == {f"https://tech.example/{i}" for i in range(4)},
      NM.rejected_urls("agB"))
check("C5 chủ đề vừa dùng được ghi sổ", NM.topic_key(st["bank_topic"]) in NM.used_topics("agB", 21))
check("C6 từ khoá chứa từ cấm («stocks») không bao giờ được chọn",
      all("stocks" not in q for q in [st["bank_topic"]]))

EVENTS.clear()
META.clear()
st = st_for([dict(c) for c in TECH] + [dict(c, scraped_at=OLD, url="https://b.example/old") for c in BIBLE])
P._step_niche(st, {"autopublish": True})
check("B2 lượt sau: nguồn đã loại + nguồn > 30 ngày không bị chấm lại (0 GATE_REJECT)",
      not [e for e in EVENTS if e.startswith("GATE_REJECT:")], EVENTS)
check("C7 chủ đề đã dùng trong 21 ngày bị bỏ → lấy chủ đề kế tiếp",
      "narrow gate" in st.get("bank_topic", ""), st.get("bank_topic"))

st = st_for([dict(c, url=f"https://tech2.example/{i}") for i, c in enumerate(TECH)], agent=Agent(id="agEmpty"))
try:
    P._step_niche(st, {"autopublish": True})
    held = None
except P.NicheHold as h:
    held = h
check("C8 kho từ khoá rỗng → vẫn dừng, nói rõ BANK_LOW", held is not None and "keyword bank" in held.headline
      and "BANK_LOW" in held.reason, held and (held.headline, held.reason))

META.clear()
st = st_for([dict(c, url=f"https://bb.example/{i}", title=f"Psalm {i} explained") for i, c in enumerate(BIBLE * 3)])
P._step_niche(st, {})
check("C9 đủ 3 nguồn đúng ngách → viết từ kho thu thập (keyword_source=ai), không lấy chủ đề kho",
      "bank_topic" not in st and META.get("keyword_source") == "ai", (st.get("bank_topic"), META))
check("B3 clear_rejected gỡ dấu loại", NM.clear_rejected("agB") == 4 and not NM.rejected_urls("agB"))

# ── D: từ khoá hằng ngày ──────────────────────────────────────────────────────
os.environ.setdefault("TUBECLI_SKIP_STARTUP", "1")
from tubecli.api import server as S  # noqa: E402
from tubecli.core import run_log  # noqa: E402
from tubecli.core.brain import AgentBrain  # noqa: E402

run_log._dir = lambda: TMP / "runs"
(TMP / "runs").mkdir(exist_ok=True)
saved = {}


class FakeManager:
    def __init__(self, ag):
        self.ag = ag

    def get(self, aid):
        return self.ag

    def update(self, aid, **kw):
        if "routine" in kw:
            self.ag.routine = kw["routine"]
            saved.update(kw["routine"])
        return self.ag


import tubecli.core.agent as _agmod  # noqa: E402

ag = Agent(id="agK", routine=json.loads(json.dumps(ROUTINE)), timezone="Asia/Ho_Chi_Minh")
_agmod.agent_manager = FakeManager(ag)
import tubecli.core.scraped_store as _ss  # noqa: E402
_ss.resolve_profiles = lambda profiles: []
calls = []


def broken_llm(agent_dict, messages, temperature=0.7):
    calls.append(agent_dict.get("model"))
    return "Sorry, I can't help with that."


AgentBrain._call_llm = staticmethod(broken_llm)
run_log.start("run-k1", "agK", "x")
out = S.check_and_generate_daily_keywords(ag, S._agent_now(ag), run_id="run-k1")
check("D1 model trả lời lạc → dùng lại bộ từ khoá cũ (không rỗng)", out.get("stale") and out.get("morning"), out)
check("D2 bộ cũ cũng bị lọc từ cấm («stocks» bị bỏ)", "afternoon" not in out, out)
runs = run_log.list_for_agent("agK", days=2)
notes = [n for r in runs for n in (r.get("notes") or [])]
check("D3 lỗi sinh từ khoá ghi vào lượt chạy (run_log.note)", notes and notes[0]["kind"] == "keywords_error"
      and "could not be generated" in notes[0]["text"], runs)
check("D4 lỗi lưu cả vào routine.daily_keywords_error", "daily_keywords_error" in saved, saved.keys())
check("D5 thử model của agent rồi model mặc định của máy (≤ 2 lượt)", 1 <= len(calls) <= 2 and calls[0] == "muse-spark",
      calls)

GOOD = {"morning": ["What does grace mean in Ephesians 2?"], "afternoon": ["Psalm 23 explained"],
        "evening": ["stocks and the Bible"], "night": ["Romans 8:28 explained", "Big Tech layoffs"]}
AgentBrain._call_llm = staticmethod(lambda a, m, temperature=0.7: json.dumps(GOOD))
out = S.check_and_generate_daily_keywords(ag, S._agent_now(ag), run_id="run-k1")
today = S._agent_now(ag).strftime("%Y-%m-%d")
check("D6 sinh được → lưu với ngày theo múi giờ agent; câu dính từ cấm bị bỏ",
      out.get("date") == today and "evening" not in out and out.get("night") == ["Romans 8:28 explained"], out)
check("D7 sinh lại thành công thì xoá lỗi cũ", "daily_keywords_error" not in ag.routine, ag.routine.keys())
check("D8 _agent_now theo múi giờ agent", S._agent_now(ag).utcoffset() == datetime.timedelta(hours=7))

# ── E: link video ─────────────────────────────────────────────────────────────
check("E1 link trợ giúp KHÔNG phải video", P.youtube_video_id("https://support.google.com/youtube?p=upload_videos") == "")
check("E2 youtu.be / watch / shorts đúng id", P.youtube_video_id("https://youtu.be/swfEtvVCJ-g") == "swfEtvVCJ-g"
      and P.youtube_video_id("https://www.youtube.com/watch?v=swfEtvVCJ-g&t=3") == "swfEtvVCJ-g"
      and P.youtube_video_id("https://youtube.com/shorts/swfEtvVCJ-g") == "swfEtvVCJ-g")
check("E3 trang studio / kênh không phải video",
      P.youtube_video_id("https://studio.youtube.com/channel/UC123/videos") == ""
      and P.youtube_video_id("https://www.youtube.com/@deepbiblicalechoes") == "")
check("E4 bước xác minh trong trình duyệt không còn lấy link đầu tiên có chữ «youtu»",
      'a[href*="youtu"]' not in P.VERIFY_PUBLISH_CODE and "youtu\\.be" in P.VERIFY_PUBLISH_CODE)

said = []
st_x = {}
P._step_final(st_x, "publish", "warning", "UNVERIFIED — x")
check("E4b _step_final ghi trạng thái cuối", st_x["_step_final"]["publish"][0] == "warning")


def _cap(job):
    return {"ready": True, "missing": [], "disabled": []}


_orig_cj = P.check_job
P.check_job = _cap
st_e = {"_step_final": {"publish": ("warning", "UNVERIFIED — no link")}}
P._HANDLERS_BACKUP = P._HANDLERS.get("publish")
P._HANDLERS["publish"] = lambda state, options: None
P._run_steps([("publish", "Publish", "x", True)], st_e, {"publish": True}, lambda *a, **k: said.append(a),
             lambda: False, [], [])
P._HANDLERS["publish"] = P._HANDLERS_BACKUP
P.check_job = _orig_cj
check("E5 bước tự đặt trạng thái cuối «warning» → không bị ghi đè thành success",
      said and said[-1][:2] == ("publish", "warning") and "UNVERIFIED" in said[-1][2], said)
from tubecli.extensions.codex import manager as CM  # noqa: E402
check("E6 Codex có trạng thái bước warning", getattr(CM, "STEP_WARNING", "") == "warning")

# ── F: kênh không khớp ────────────────────────────────────────────────────────
P._profile_identities = lambda agent: [("gmail_pk0789743", ["gmail_pk0789743", "pk0789743@gmail.com", "pk0789743"])]
P._find_channel = lambda **kw: {}
st_f = {"agent": Agent(), "_say": lambda *a, **k: None}
P._resolve_channel(st_f, {"publish_channel_name": "Pawan Kumar", "publish_profile": "gmail_pk0789743"})
check("F1 hồ sơ đăng đã chọn không mang tên kênh → channel_mismatch (dừng đăng)",
      "Publishing stopped" in st_f.get("channel_mismatch", "") and "Pawan Kumar" in st_f["channel_mismatch"], st_f)
P._profile_identities = lambda agent: [("gmail_pk0789743", ["gmail_pk0789743", "Pawan Kumar"])]
st_f = {"agent": Agent(), "_say": lambda *a, **k: None}
P._resolve_channel(st_f, {"publish_channel_name": "Pawan Kumar", "publish_profile": "gmail_pk0789743"})
check("F2 hồ sơ mang bí danh / tên kênh → đăng bình thường", not st_f.get("channel_mismatch")
      and st_f.get("channel_profile") == "gmail_pk0789743", st_f)
st_f = {"agent": Agent(), "_say": lambda *a, **k: None}
P._resolve_channel(st_f, {"publish_channel_name": "Shivani Sahu", "publish_channel_id": "UCQGpEsXiK2rxzufJBhaY89A"})
check("F3 có id kênh → không coi là lệch (Studio mở đúng kênh theo id)", not st_f.get("channel_mismatch"), st_f)

# ── G: model ảnh chết ─────────────────────────────────────────────────────────
lines = P._fallback_image_warnings({"dead_image_models": [{"model": "9router/ag/bad-image",
                                                            "reason": "HTTP 400: model not supported", "shots": 70}],
                                    "fallback_images": {"count": 70, "total": 79, "drew": {"muse": 70}}})
check("G1 một dòng cho mỗi model chết, thay cho câu chung", len(lines) == 1 and "9router/ag/bad-image" in lines[0]
      and "not retried for 6 hours" in lines[0] and "70 shot" in lines[0], lines)
check("G2 Studio cũ (không có dead_image_models) → câu fallback như trước",
      "FALLBACK" in P._fallback_image_warnings({"fallback_images": {"count": 2, "total": 9}})[0])

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
