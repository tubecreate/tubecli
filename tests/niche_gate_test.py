"""Bộ lọc ngách + dự phòng AI cho content_video (đợt 1, 4/11/2026).

Chạy:  python tests/niche_gate_test.py      (mã thoát 0 = đạt)

Sự cố thật: task #149 «Big Tech's Selloff» của agent «Deep Biblical Echoes Niche Researcher» (kênh Kinh Thánh) viết 38
cảnh về cổ phiếu Amazon/Intel từ 5 bài báo tài chính trong kho; nhiều task hỏng hẳn vì «[Codex Error] usage_limit»,
«402 Insufficient Balance», 5xx, trả rỗng. Canh:
  A. cấu hình ngách: coerce không ném, agent cũ có mặc định, agent chưa khai → cảnh báo NICHE_UNCONFIGURED
  B. niche_gate: từ cấm (hoa thường, có dấu/không dấu, theo TỪ), điểm model ≥ ngưỡng, cache, model lỗi → cổng ĐÓNG
  C. phân loại lỗi + thời gian nghỉ theo nhà cung cấp
  D. TÁI HIỆN #149: kho 5 bài tài chính → bị loại hết (GATE_REJECT) → dừng ở review «⚠ OFF-NICHE SOURCES», không viết
  E. kịch bản lạc ngách → «⚠ OFF-NICHE (score X/10)», dừng trước storyboard; lượt dựng sau khi NGƯỜI Accept thì bỏ qua
  F. _ask_model: model của agent hết lượt → model nhà khác; hết lựa chọn → AIUnavailable; tiền tố «Auto-Failover» bị bỏ
  G. board: TaskDeferred → về backlog, không hỏng; hàng đợi chỉ thả khi tới retry_at; Retry tay xoá giờ hẹn
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="niche_gate_"))
from tubecli.core import llm_errors as LE  # noqa: E402
from tubecli.core import niche as N  # noqa: E402

LE.reset()

checks = fails = 0


def check(name, ok, detail=""):
    global checks, fails
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        fails += 1


BIBLE = {"language": "en", "niche_description": "the meaning and context of Bible passages, biblical people and "
                                                "Christian life",
         "must_relate_to": ["Bible", "scripture", "Jesus", "God", "prayer", "faith"],
         "deny_terms": ["stocks", "markets", "earnings", "selloff", "Amazon", "Intel", "Big Tech", "crypto", "Chứng khoán"],
         "min_niche_score": 7}


def agent(niche=None, research=""):
    a = SimpleNamespace(id="ag1", name="Deep Biblical Echoes Niche Researcher", model="codex/gpt-6.1-sol",
                        research_prompt=research, description="", niche=niche)
    a.to_dict = lambda: {"id": a.id, "name": a.name, "model": a.model}
    return a


ASKED = []


def fake_ask(ag, model, prompt):
    """Model chấm giả: bài có chữ Kinh Thánh → 9, còn lại → 1. 'BROKEN' → lỗi nhà cung cấp."""
    ASKED.append(model)
    body = prompt.split("<<<", 1)[-1]
    if "BROKEN" in body:
        return "[Codex Error] usage_limit: You've hit your usage limit"
    if any(w in body for w in ("Matthew", "Jesus", "Psalm", "scripture")):
        return '⚠️ *[Auto-Failover: codex → gemini]*\n\n{"score": 9, "reason": "explains a Bible passage"}'
    return '{"score": 1, "reason": "about markets, not the Bible"}'


N._ask = fake_ask
N.gate_model = lambda cfg: cfg.get("gate_model") or "gemini-2.5-flash"

# ── A. cấu hình ───────────────────────────────────────────────────────────────
c = N.coerce({"deny_terms": "stocks, Big Tech\nIntel", "min_niche_score": "99", "explore_ratio": "x", "enabled": "false"})
check("A1 coerce: chuỗi → danh sách, kẹp ngưỡng 0-10, rác → mặc định, enabled 'false' → tắt",
      c["deny_terms"] == ["stocks", "Big Tech", "Intel"] and c["min_niche_score"] == 10 and c["explore_ratio"] == 0.2
      and c["enabled"] is False, c)
check("A2 coerce(None) = mặc định an toàn (bật, ngưỡng 7)", N.coerce(None)["enabled"] is True and N.coerce(None)["min_niche_score"] == 7)
cfg, warns = N.effective(agent(None, research="Study English YouTube niche for Deep Biblical Echoes"))
check("A3 agent chưa khai ngách → dùng research_prompt + NICHE_UNCONFIGURED", warns == [N.UNCONFIGURED]
      and "Deep Biblical Echoes" in cfg["niche_description"], (warns, cfg["niche_description"]))
cfg, warns = N.effective(agent(BIBLE))
check("A4 agent đã khai → không cảnh báo", warns == [] and cfg["min_niche_score"] == 7)

# ── B. niche_gate ─────────────────────────────────────────────────────────────
A = agent(BIBLE)
r = N.niche_gate(A, "Big Tech's Selloff: what the headlines really mean")
check("B1 từ cấm («selloff» / «Big Tech») → loại ngay, không gọi model", not r["pass"] and r["deny"] in ("selloff", "Big Tech") and not ASKED, (r, ASKED))
check("B2 từ cấm không phân biệt hoa thường", N.deny_hit(N.coerce(BIBLE), "AMAZON shares fall") == "Amazon")
check("B3 từ cấm có dấu khớp chữ không dấu", N.deny_hit(N.coerce(BIBLE), "thi truong chung khoan hom nay") == "Chứng khoán")
check("B4 so theo TỪ: «Intelligence» không dính «Intel»", N.deny_hit(N.coerce(BIBLE), "Artificial Intelligence and faith") == "")
r = N.niche_gate(A, "What Matthew 5:13 'salt of the earth' means")
check("B5 nội dung đúng ngách → model chấm 9 ≥ 7 → đạt; tiền tố Auto-Failover được bỏ", r["pass"] and r["score"] == 9, r)
n_before = len(ASKED)
r2 = N.niche_gate(A, "What Matthew 5:13 'salt of the earth' means")
check("B6 cache theo nội dung: lần hai không gọi model", r2["pass"] and r2["cached"] and len(ASKED) == n_before)
r = N.niche_gate(A, "Why the Fed may cut interest rates next month")
check("B7 lạc ngách (không dính từ cấm) → model chấm 1 → loại", not r["pass"] and r["score"] == 1, r)
r = N.niche_gate(A, "BROKEN request about prayer")
check("B8 model lỗi → cổng ĐÓNG (không đạt), không ghi cache", not r["pass"] and r.get("unavailable")
      and r["score"] is None, r)
N.gate_model_orig = N.gate_model
N.gate_model = lambda cfg: ""
r = N.niche_gate(A, "Psalm 23 explained")
check("B9 không có model nào → cổng ĐÓNG kèm lý do", not r["pass"] and "no AI model" in r["reason"], r)
N.gate_model = N.gate_model_orig
off = N.niche_gate(agent(dict(BIBLE, enabled=False)), "Big Tech selloff")
check("B10 agent tắt bộ lọc → luôn đạt", off["pass"] and off["score"] is None)
check("B11 parse_score: JSON, «score: 8», rác", N.parse_score('{"score": 8.4, "reason": "ok"}') == (8, "ok")
      and N.parse_score("Score: 6") == (6, "") and N.parse_score("no idea")[0] == -1)
check("B12 prompt nằm trong file mẫu tubecli/prompts/niche_gate.txt",
      (ROOT / "tubecli" / "prompts" / "niche_gate.txt").is_file())

# ── C. phân loại lỗi ──────────────────────────────────────────────────────────
cases = {
    "[Codex Error] usage_limit: Codex usage limit reached on every account": LE.QUOTA,
    "[OpenAI Error] 402 Insufficient Balance": LE.BALANCE,
    "AI server error (HTTP 502/503)": LE.HTTP_5XX,
    "[OpenAI Error] The model returned an empty response": LE.EMPTY,
    "": LE.EMPTY,
    "429 Too Many Requests": LE.QUOTA,
    "Profile muse-vinh-20 is signed out": LE.SIGNED_OUT,
    "net::ERR_CONNECTION_RESET at https://youtube.com": LE.PAGE_LOAD,
    "SyntaxError in scene 3": LE.OTHER,
}
bad = {k: LE.classify(k) for k, v in cases.items() if LE.classify(k) != v}
check("C1 phân loại 9 loại lỗi thật", not bad, bad)
check("C2 lỗi tạm thời vs không", LE.retryable("402 Insufficient Balance") and not LE.retryable("SyntaxError"))
check("C3 provider_of theo tên model", LE.provider_of("codex/gpt-6.1-sol") == "codex" and LE.provider_of("deepseek-chat") == "deepseek"
      and LE.provider_of("ag/gemini-3.8-flash") == "9router" and LE.provider_of("x", "gemini") == "gemini")
now = time.time()
until = LE.cool_down("codex", LE.QUOTA, "usage limit", now=now)
check("C4 hết lượt → nhà đó nghỉ 60 phút", abs(until - now - 3600) < 1 and LE.cooling_until("codex", now=now + 10) == until)
check("C5 hết giờ nghỉ → dùng lại được", LE.cooling_until("codex", now=until + 1) == 0)
check("C6 lỗi không tạm thời thì không nghỉ", LE.cool_down("gemini", LE.OTHER) == 0 and LE.cooling_until("gemini") == 0)

# ── D–F. pipeline ─────────────────────────────────────────────────────────────
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

META, EVENTS, CK = {}, [], {}
P._task_meta = lambda task_id, **patch: META.update({k: v for k, v in patch.items() if v not in (None, "")})
P._task_event = lambda task_id, message: EVENTS.append(message)
P._checkpoint_merge = lambda state, extra: CK.update(extra)
SKIPPED = []
import tubecli.extensions.content_video.autopublish as AP  # noqa: E402
AP.skip_window = lambda aid, hw="": SKIPPED.append((aid, hw)) or True


def state_with(corpus, ag=None, **kw):
    st = {"agent": ag or agent(BIBLE), "task_id": "t149", "corpus": corpus, "videos": [], "warnings": [],
          "checkpoint": {}, "_say": lambda *a, **k: None, "_cancelled": lambda: False, "high_water": "2026-10-31T02:55"}
    st.update(kw)
    return st


FINANCE = [{"title": t, "url": f"https://news.example/{i}", "content": body, "source": "read", "scraped_at": ""}
           for i, (t, body) in enumerate([
               ("Amazon shares slide after earnings", "Amazon stock fell as cloud growth slowed..."),
               ("Intel under pressure in Asian trading", "Intel shares weakened as Nasdaq futures fell..."),
               ("Investors rotate into bonds", "Treasury yields moved as investors questioned AI spending..."),
               ("Layoffs: why companies cut jobs", "Restructuring and automation explain several job cuts..."),
               ("Tech showcase: new robots", "Developers demonstrated machines that sort parcels..."),
           ])]
st = state_with([dict(c) for c in FINANCE])
try:
    P._step_niche(st, {"autopublish": True})
    held = None
except P.NicheHold as h:
    held = h
check("D1 #149: 5 bài tài chính → dừng (NicheHold), không viết", held is not None and "OFF-NICHE SOURCES" in held.headline
      and "only 0 of 5" in held.headline, held and held.headline)
check("D2 cả 5 bài bị loại + ghi GATE_REJECT vào sự kiện và meta", len([e for e in EVENTS if e.startswith("GATE_REJECT:")]) == 5
      and len(META.get("gate_rejects") or []) == 5 and META.get("niche_sources") == 0, (EVENTS, META))
check("D3 nguồn lạc bị bỏ khỏi kho đưa cho bước viết", not [c for c in st["corpus"] if c.get("content")])
P._skip_window_after_hold(st, {"autopublish": True}, held)
check("D4 lượt tự động: cửa sổ kho lạc ngách được bỏ qua (không châm ngòi lại)", SKIPPED == [("ag1", "2026-10-31T02:55")], SKIPPED)
res = P._held_result(st, held)
check("D5 kết quả dừng ở review mở đầu «⚠ OFF-NICHE», nói rõ không dựng / không đăng",
      res.startswith("⚠ OFF-NICHE") and "Nothing was rendered or published" in res and "GATE_REJECT" in res, res[:400])
BIBLE_SRC = [{"title": f"Matthew 5:{n} explained", "url": f"https://b.example/{n}", "content": "Jesus taught ...",
              "source": "read", "scraped_at": ""} for n in (13, 14, 16)]
st = state_with([dict(c) for c in FINANCE] + [dict(c) for c in BIBLE_SRC])
EVENTS.clear()
P._step_niche(st, {})
check("D6 trộn: 3 bài Kinh Thánh đạt + 5 bài tài chính bị loại → đi tiếp với 3 bài đúng ngách",
      [c["title"] for c in st["corpus"] if c.get("content")] == [c["title"] for c in BIBLE_SRC]
      and len(EVENTS) == 5, [c["title"] for c in st["corpus"]])
st = state_with([{"title": "", "url": "", "content": "BROKEN everything", "source": "read", "scraped_at": ""}] * 3)
SKIPPED.clear()
try:
    P._step_niche(st, {"autopublish": True})
    h2 = None
except P.NicheHold as h:
    h2 = h
check("D7 model chấm lỗi → dừng «CHECK UNAVAILABLE», GIỮ cửa sổ kho (chấm lại được lần sau)",
      h2 is not None and h2.unavailable and "UNAVAILABLE" in h2.headline and not SKIPPED, (h2 and h2.headline, SKIPPED))
st = state_with([{"title": "", "url": "", "content": "Big Tech", "source": "pasted", "scraped_at": ""}])
P._step_niche(st, {})
check("D8 nội dung người dùng DÁN: không lọc nguồn (kịch bản được kiểm sau)", st["corpus"][0]["source"] == "pasted")

# E. kiểm kịch bản
st = state_with([], script="[SHOW: a trader] Amazon and Intel fell after earnings...", title="Big Tech’s Selloff: What the Headlines Really Mean")
try:
    P._step_fit(st, {})
    h3 = None
except P.NicheHold as h:
    h3 = h
check("E1 kịch bản #149 → «⚠ OFF-NICHE (score 0/10)» (từ cấm trong tiêu đề)", h3 is not None
      and h3.headline.startswith("⚠ OFF-NICHE (score 0/10)"), h3 and h3.headline)
st = state_with([], script="[SHOW: a calm lake] Interest rates and the economy this quarter...", title="What the Fed means")
try:
    P._step_fit(st, {})
    h4 = None
except P.NicheHold as h:
    h4 = h
check("E2 kịch bản lạc ngách không từ cấm → model chấm 1 → dừng", h4 is not None and "score 1/10" in h4.headline
      and META.get("niche_score") == 1 and CK.get("niche_check", {}).get("pass") is False, (h4 and h4.headline, META))
st = state_with([], script="[SHOW: a hillside] Jesus told the crowd: you are the salt of the earth (Matthew 5:13)...",
                title="What “Salt of the Earth” Really Means")
P._step_fit(st, {})
check("E3 kịch bản đúng ngách → đi tiếp, ghi điểm", META.get("niche_score") == 9 and CK["niche_check"]["pass"] is True)
st = state_with([], script="Amazon stock...", title="Big Tech", stage="render",
                checkpoint={"niche_check": {"score": 0, "pass": False}})
P._step_fit(st, {})
check("E4 lượt DỰNG sau khi người duyệt Accept bản đã kiểm → không chặn lại", True)
st = state_with([], script="Amazon stock...", title="Big Tech", stage="render")
try:
    P._step_fit(st, {})
    h5 = None
except P.NicheHold as h:
    h5 = h
check("E5 kịch bản tới THẲNG lượt dựng (Claude dán sẵn) chưa kiểm → vẫn bị chặn", h5 is not None)
PASTE = [{"title": "", "url": "", "content": "Taiwan election rally ...", "source": "pasted", "scraped_at": ""}]
st = state_with([dict(c) for c in PASTE], script="[SHOW: a rally] Amazon and Intel fell...", title="Big Tech rally")
try:
    P._step_fit(st, {})
    h6 = None
except P.NicheHold as h:
    h6 = h
check("E9 bài người dùng DÁN lạc ngách → không chặn, chỉ cảnh báo", h6 is None
      and any("you gave this content yourself" in w for w in st["warnings"]), (h6 and h6.headline, st["warnings"]))
st = state_with([], script="[SHOW: a rally] Amazon and Intel fell...", title="Big Tech rally")
try:
    P._step_fit(st, {"voice_file": "C:/x/voice.mp3"})
    h7 = None
except P.NicheHold as h:
    h7 = h
check("E10 có file giọng của người dùng → không chặn", h7 is None, h7 and h7.headline)
st = state_with([dict(c) for c in PASTE], script="[SHOW: a rally] Amazon and Intel fell...", title="Big Tech rally")
try:
    P._step_fit(st, {"autopublish": True})
    h8 = None
except P.NicheHold as h:
    h8 = h
check("E11 lượt TỰ ĐĂNG vẫn chặn dù nguồn là bài dán", h8 is not None)
ids = [s[0] for s in P.PLAN_STEPS]
check("E6 thứ tự bước kế hoạch: crawl → niche → script → fit", ids[ids.index("crawl") + 1:ids.index("fit") + 1]
      == ["niche", "script", "fit"], ids)
auto = [s[0] for s in P.AUTO_STEPS]
check("E7 lượt tự động: fit trước studio, chỉ một lần", auto.count("fit") == 1 and auto.index("fit") < auto.index("studio"), auto)
check("E8 lượt dựng: fit ngay sau capabilities; lượt clone không có fit",
      [s[0] for s in P.RENDER_STEPS][:2] == ["capabilities", "fit"] and "fit" not in [s[0] for s in P.CLONE_STEPS])

# F. dự phòng model
CALLS = []


def fake_once(ag, sp, up, words):
    d = ag.to_dict()
    CALLS.append(d.get("model"))
    if str(d.get("model")).startswith("codex/"):
        raise RuntimeError("[Codex Error] usage_limit: You've hit your usage limit")
    if d.get("provider") == "deepseek":
        raise RuntimeError("[OpenAI Error] 402 Insufficient Balance")
    return "TITLE: ok\n[SHOW: x] narration"


P._ask_once = fake_once
P._text_model_choices = lambda: [{"provider": "deepseek", "models": ["deepseek-chat"]},
                                 {"provider": "gemini", "models": ["gemini-2.5-flash"]}]
LE.reset()
P._FALLBACK_LOG.rows = rows = []
real = agent(BIBLE)
real.to_dict = lambda: {"id": "ag1", "name": "x", "model": "codex/gpt-6.1-sol"}
out = P._ask_model(real, "sys", "user", 800)
check("F1 codex hết lượt → deepseek hết tiền → gemini viết được", out.startswith("TITLE: ok")
      and CALLS == ["codex/gpt-6.1-sol", "deepseek-chat", "gemini-2.5-flash"], CALLS)
check("F2 ghi sổ dự phòng", rows and rows[-1]["to"] == "gemini|gemini-2.5-flash" and "quota" in rows[-1]["why"], rows)
check("F3 codex + deepseek đang nghỉ (không bị gọi lại mỗi phút)", LE.cooling_until("codex") > 0 and LE.cooling_until("deepseek") > 0)
CALLS.clear()
P._ask_model(real, "sys", "user", 800)
check("F4 lượt sau: bỏ qua nhà đang nghỉ, đi thẳng gemini", CALLS == ["gemini-2.5-flash"], CALLS)
P._text_model_choices = lambda: [{"provider": "deepseek", "models": ["deepseek-chat"]}]
try:
    P._ask_model(real, "sys", "user", 800)
    au = None
except P.AIUnavailable as e:
    au = e
check("F5 hết lựa chọn → AIUnavailable (không phải lỗi thường)", au is not None, au)


def raise_other(ag, sp, up, words):
    raise RuntimeError("the reasoning model stalled")


LE.reset()
P._ask_once = raise_other
try:
    P._ask_model(real, "sys", "user", 800)
    oth = None
except P.AIUnavailable:
    oth = "wrong"
except RuntimeError as e:
    oth = str(e)
check("F6 lỗi không tạm thời (reasoning stall) ném nguyên như cũ", oth == "the reasoning model stalled", oth)

def reasoning_empty(ag, sp, up, words):
    raise RuntimeError("[OpenAI Error] deepseek-v4-flash returned an empty response (finish_reason=length, the model "
                       "spent its whole budget on reasoning)")


LE.reset()
P._ask_once = reasoning_empty
try:
    P._ask_model(real, "sys", "user", 800)
    rz = None
except P.AIUnavailable:
    rz = "wrong"
except RuntimeError as e:
    rz = str(e)
check("F6b model suy luận hết ngân sách: KHÔNG nghỉ / đổi model — ném nguyên để viết theo đợt",
      rz and "reasoning" in rz and not LE.cooling(), (rz, LE.cooling()))
check("F7 câu «Tất cả AI Cloud đều hết quota» là LỖI, không phải kịch bản",
      LE.classify("[Error] quota: every cloud AI is out of quota") == LE.QUOTA
      and bool(P._ALL_AI_DOWN_RE.match("⚠️ **Tất cả AI Cloud đều hết quota!**")))
check("F8 tiền tố Auto-Failover bị gỡ", P._FAILOVER_PREFIX_RE.sub("", "⚠️ *[Auto-Failover: codex → gemini]*\n\nTITLE: x").strip()
      == "TITLE: x")

# ── H. tích hợp qua bộ chạy bước thật (_run_steps + PLAN_STEPS) ─────────────────
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": []}
P.scan_window = lambda **kw: [{"title": c["title"], "url": c["url"], "content": c["content"], "has_content": True,
                               "domain": "news.example", "scraped_at": f"2026-10-31T02:5{i}"} for i, c in enumerate(FINANCE)]
WROTE = []
_orig_script = P._HANDLERS["script"]
P._HANDLERS["script"] = lambda state, options: WROTE.append("script")
STEPS_SEEN = []
st = state_with([], profiles=[], feedback=[])
st["_say"] = lambda sid, status, msg="", *a: STEPS_SEEN.append((sid, status))
try:
    P._run_steps(P.PLAN_STEPS, st, dict(P.DEFAULTS, capabilities=False), st["_say"], lambda: False, [], [])
    hi = None
except P.NicheHold as h:
    hi = h
P._HANDLERS["script"] = _orig_script
check("H1 #149 qua bộ chạy thật: gather → … → niche dừng; bước script KHÔNG chạy", hi is not None and not WROTE
      and ("niche", "error") in STEPS_SEEN and not any(s == "script" for s, _ in STEPS_SEEN), (hi, WROTE, STEPS_SEEN))

# ── G. board ──────────────────────────────────────────────────────────────────
from tubecli.extensions.codex import manager as M  # noqa: E402

mgr = M.CodexManager()
mgr._loaded = True
mgr._save = lambda: None
mgr.append_event = lambda *a, **k: None
mgr.notify = lambda *a, **k: None
mgr.post_to_chat = lambda *a, **k: None
t = M.CodexTask(goal="video", title="Auto video").to_dict() if hasattr(M.CodexTask, "to_dict") else None
base = {"id": "t1", "seq": 1, "goal": "g", "title": "Auto video", "status": "running", "lane": "video", "priority": 0,
        "created_at": "2026-11-04T01:00:00", "updated_at": "", "steps": [], "meta": {}, "retry_count": 0, "max_retries": 3}
mgr._tasks = {"t1": dict(base)}
mgr._tasks["t1"]["meta"] = {"retry_at": time.time() + 3600, "ai_defers": 1}
up = mgr.report_failure("t1", M.TASK_DEFERRED_PREFIX + "the AI is unavailable at «Write the script» (quota)")
check("G1 TaskDeferred → backlog, KHÔNG failed", up.get("status") == M.BACKLOG and mgr._tasks["t1"]["status"] == M.BACKLOG, up.get("status"))
with mgr._lock:
    rel = mgr._release_backlog()
check("G2 chưa tới retry_at → hàng đợi không thả", not rel and mgr._tasks["t1"]["status"] == M.BACKLOG)
mgr._tasks["t1"]["meta"]["retry_at"] = time.time() - 5
with mgr._lock:
    rel = mgr._release_backlog()
check("G3 tới giờ → thả vào queued", [r["id"] for r in rel] == ["t1"] and mgr._tasks["t1"]["status"] == M.QUEUED)
mgr._tasks["t1"].update(status="failed", meta={"retry_at": time.time() + 3600, "ai_defers": 2, "language": "en"})
mgr.retry("t1")
check("G4 Retry tay: xoá retry_at / ai_defers, giữ meta khác", "retry_at" not in mgr._tasks["t1"]["meta"]
      and "ai_defers" not in mgr._tasks["t1"]["meta"] and mgr._tasks["t1"]["meta"].get("language") == "en", mgr._tasks["t1"]["meta"])
mgr._tasks["t2"] = dict(base, id="t2", seq=2, meta={})
up = mgr.report_failure("t2", "RuntimeError: SyntaxError in scene 3")
check("G5 lỗi thường vẫn FAILED như cũ", up.get("status") == M.FAILED)
check("G6 META_KEYS nhận các trường mới", all(k in M.META_KEYS for k in ("niche_score", "gate_rejects", "keyword_source",
                                                                        "fallback_used", "retry_at", "ai_defers")))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{checks - fails}/{checks} PASS")
sys.exit(1 if fails else 0)
