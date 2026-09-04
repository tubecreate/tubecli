# -*- coding: utf-8 -*-
"""Video của agent theo MẪU (preset) đã lưu trong wizard Content Studio.

Run:  python tests/content_video_preset_test.py     (exit 0 = pass)

Người dùng bấm Preset → Save trong wizard rồi muốn agent làm video ĐÚNG mẫu đó
(vibe, ngôn ngữ, khung hình, độ dài) — không có hệ mẫu thứ hai. Pipeline hỏi
Content Studio GET /api/v1/studio/presets/<tên>/drama-fields và đặt nguyên kết
quả lên drama, đúng như wizard tự tạo (style string + metadata).

Kiểm, đối chiếu code thật:
  A. Agent.content_video_preset — mặc định "", có trong to_dict, from_dict nhận,
                                  AgentManager.update ghi được, AgentUpdateRequest có trường
  B. intent_router              — "theo mẫu X" / "with the template X" → data["preset"];
                                  không nhắc → không có khoá; tải/tách sub vẫn không phải
                                  content_video; handler + verb chuyển "preset" vào options
  C. _load_preset               — có / không có → liệt kê tên đã lưu / Studio cũ → None /
                                  lỗi khác → ném nguyên
  D. run_plan                   — ngôn ngữ theo mẫu (nguồn "preset"), tuỳ chọn vẫn thắng mẫu,
                                  kế hoạch có dòng Template, checkpoint mang preset, mẫu sai → lỗi rõ
  E. run_render                 — drama mang style / total_episodes / metadata của mẫu (+ khoá
                                  của pipeline + tên mẫu); khung hình theo mẫu, 9:16 rõ ràng
                                  thắng, gen-images khớp; preset đi checkpoint → payload render
  F. Studio cũ                  — cảnh báo + vibe mặc định, không dòng Template
"""
import ast
import asyncio
import copy
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.core.agent import Agent as RealAgent, AgentManager  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("VIDEO CỦA AGENT THEO MẪU (PRESET) CỦA WIZARD CONTENT STUDIO")
print("=" * 70)

# ── A. Agent field ──────────────────────────────────────────────────────────
check("A mặc định ''", RealAgent(name="x").content_video_preset == "")
check("A to_dict có khoá", RealAgent(name="x", content_video_preset="Tin nhanh").to_dict()["content_video_preset"] == "Tin nhanh")
check("A from_dict nhận", RealAgent.from_dict({"name": "x", "content_video_preset": "Daily"}).content_video_preset == "Daily")
check("A agent cũ (không có khoá) → ''", RealAgent.from_dict({"name": "x"}).content_video_preset == "")
check("A None → ''", RealAgent(name="x", content_video_preset=None).content_video_preset == "")
# AgentManager.update chỉ setattr khi hasattr → thuộc tính có sẵn là PUT ghi được
mgr = AgentManager(agents_file=Path(tempfile.mkdtemp(prefix="cv-preset-")) / "agents.json")
ag = mgr.create(name="x")
mgr.update(ag.id, content_video_preset="Tin nhanh")
check("A AgentManager.update ghi được", mgr.get(ag.id).content_video_preset == "Tin nhanh")
# server.py nặng (FastAPI app) → đọc nguồn thay vì import
tree = ast.parse((ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8"))


def _fields(cls_name):
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    return {s.target.id: ast.unparse(s.annotation) for s in node.body if isinstance(s, ast.AnnAssign)}


check("A AgentUpdateRequest.content_video_preset: Optional[str]",
      _fields("AgentUpdateRequest").get("content_video_preset") == "Optional[str]", _fields("AgentUpdateRequest"))
check("A AgentCreateRequest cũng có", _fields("AgentCreateRequest").get("content_video_preset") == "Optional[str]")
print("A agent      : content_video_preset mặc định '' | to_dict/from_dict | update ghi được | request model có trường")

# ── B. intent: tên mẫu, 0 token ─────────────────────────────────────────────
from tubecli.core import intent_router as R  # noqa: E402
from tubecli.core import intent_handlers as H  # noqa: E402

Router = next(v for v in vars(R).values() if isinstance(v, type) and hasattr(v, "classify"))
router = Router()


def cls_(msg):
    return router.classify(msg, agent={"id": "a1"}, skills=[])


r = cls_('làm video từ những gì đã đọc hôm nay theo mẫu "Tin nhanh"')
check("B vi có ngoặc kép", r.intent_type == "content_video" and r.extracted_data.get("preset") == "Tin nhanh", r)
r = cls_("làm video reels từ những gì đã xem hôm qua dùng mẫu Bản tin tối, nhanh nhé")
check("B vi không ngoặc: dừng ở dấu phẩy, giữ hoa/thường, không mất day/aspect",
      r.extracted_data.get("preset") == "Bản tin tối" and r.extracted_data.get("aspect_ratio") == "9:16"
      and r.extracted_data.get("day") == "yesterday", r)
r = cls_("Tổng hợp tin tức hôm nay thành video theo template Daily Digest.")
check("B vi 'theo template', bỏ dấu chấm cuối", r.extracted_data.get("preset") == "Daily Digest", r)
r = cls_("Làm video từ những gì đã đọc hôm nay với preset “Bản tin, ngắn”")
check("B ngoặc kép cong: dấu phẩy BÊN TRONG ngoặc vẫn thuộc tên", r.extracted_data.get("preset") == "Bản tin, ngắn", r)
r = cls_("make a video from what I read today with the template 'News Flash'")
check("B en with the template + nháy đơn", r.intent_type == "content_video" and r.extracted_data.get("preset") == "News Flash", r)
r = cls_("make a video from what I read today using preset Morning Brief")
check("B en using preset", r.extracted_data.get("preset") == "Morning Brief", r)
r = cls_("Make a video from what I read today in the preset Sports Recap, vertical")
check("B en in the preset, dừng ở dấu phẩy", r.extracted_data.get("preset") == "Sports Recap" and r.extracted_data.get("aspect_ratio") == "9:16", r)
r = cls_("làm video từ những gì đã đọc hôm nay")
check("B không nhắc mẫu → không có khoá", r.intent_type == "content_video" and "preset" not in r.extracted_data, r)
r = cls_("làm video từ những gì đã đọc hôm nay theo phong cách vui")
check("B 'theo' mà không có mẫu/template → không có khoá", "preset" not in r.extracted_data, r)
for msg in ("tải video https://www.youtube.com/watch?v=abc theo mẫu Tin nhanh",
            "làm video từ những gì đã đọc hôm nay rồi tải về theo mẫu Tin nhanh",
            "tách sub từ video hôm nay theo mẫu Tin nhanh",
            "làm video phụ đề từ những gì đã đọc hôm nay theo mẫu Tin nhanh"):
    check(f"B tải/tách sub vẫn KHÔNG phải content_video: {msg[:40]}",
          router._content_video_intent(msg, msg.lower()) is None and cls_(msg).intent_type != "content_video", cls_(msg))
check("B _content_video_preset rỗng khi không có", Router._content_video_preset("làm video hôm nay") == ""
      and Router._content_video_preset("") == "" and Router._content_video_preset("theo mẫu ") == "")
# handler → options["preset"] → create_digest_task; verb passthrough cũng biết "preset"
calls = []
P.create_digest_task = lambda agent_id, options=None, created_by="user", origin=None, sources=None, **kw: \
    calls.append((agent_id, options, sources)) or {"id": "0190a1b2-0000-7000-8000-00000000abcd", "seq": 9, "status": "queued"}
asyncio.run(H.dispatch(cls_('làm video từ những gì đã đọc hôm nay theo mẫu "Tin nhanh"'), {"id": "a1", "name": "MC"}, "vi"))
check("B handler chuyển preset vào options", calls and calls[-1][1] == {"preset": "Tin nhanh"}, calls)
from tubecli.extensions.content_video import extension as X  # noqa: E402
check("B verb _PASSTHROUGH có 'preset'", "preset" in X._PASSTHROUGH, X._PASSTHROUGH)
check("B DEFAULTS['preset'] = ''", P.DEFAULTS.get("preset") == "")
print("B intent     : vi/en, ngoặc tuỳ ý, dừng ở phẩy/chấm, giữ hoa/thường | không nhắc → không khoá | tải/sub không đụng | handler+verb chuyển đi")

# ── C. _load_preset ─────────────────────────────────────────────────────────
FIELDS = {
    "style": "Visual Style: Anime | Character Style: Default", "language": "vi", "total_episodes": 3,
    "metadata": {"pipeline": ["raw", "rewrite", "extract", "storyboard", "videos", "audio", "video", "publish"],
                 "pipeline_template": "drama_scene", "aspect_ratio": "9:16", "content_format": "drama",
                 "video_length": "short_60s", "narration_source": "ai", "text_in_video": "notext",
                 "camera_angle": "Default", "ethnicity": "Default", "prompt_focus": "Default",
                 "gallery_category_id": 2},
}
VUONG = copy.deepcopy(FIELDS)
VUONG["language"] = "en"
VUONG["total_episodes"] = 0
VUONG["metadata"]["aspect_ratio"] = "1:1"
VUONG["metadata"]["source"] = "wizard"          # mẫu cố ghi đè khoá của pipeline
STUDIO = {"presets": {"Tin nhanh": FIELDS, "Vuông": VUONG}, "old": False}
gets = []


def studio_get(path, timeout=60):
    gets.append(path)
    if path.startswith("/api/v1/studio/presets"):
        if STUDIO["old"]:                                   # pack cũ: FastAPI 404 cho mọi đường
            raise RuntimeError(f"{path} → HTTP 404: Not Found")
        if path == "/api/v1/studio/presets":
            return {"success": True, "presets": {k: {"wizLanguage": v["language"]} for k, v in STUDIO["presets"].items()}}
        name = unquote(path[len("/api/v1/studio/presets/"):-len("/drama-fields")])
        if name in STUDIO["presets"]:
            return {"success": True, "name": name, "fields": STUDIO["presets"][name]}
        raise RuntimeError(f"{path} → HTTP 404: Preset not found")
    raise AssertionError(path)


P._get = studio_get
check("C tìm thấy → fields", P._load_preset("Tin nhanh") == FIELDS)
check("C   tên có khoảng trắng được mã hoá trong URL", "/api/v1/studio/presets/Tin%20nhanh/drama-fields" in gets, gets)
try:
    P._load_preset("Nope")
    check("C không có → lỗi liệt kê tên", False, "không ném")
except RuntimeError as e:
    check("C không có → lỗi liệt kê tên đã lưu + chỉ chỗ lưu",
          "Template 'Nope' not found" in str(e) and "Saved templates: Tin nhanh, Vuông" in str(e)
          and "Preset → Save" in str(e), str(e))
STUDIO["old"] = True
check("C Studio cũ (không có route) → None", P._load_preset("Tin nhanh") is None)
STUDIO["old"] = False


def boom(path, timeout=60):
    raise RuntimeError(f"{path} → HTTP 500: boom")


P._get = boom
try:
    P._load_preset("Tin nhanh")
    check("C lỗi 500 → ném nguyên", False, "không ném")
except RuntimeError as e:
    check("C lỗi 500 → ném nguyên, không nhầm là 'không có'", "HTTP 500" in str(e) and "not found" not in str(e), str(e))
check("C _http_status", P._http_status(RuntimeError("/x → HTTP 404: nf")) == 404 and P._http_status(ValueError("nope")) == 0)
print("C load       : có → fields | không có → liệt kê tên + chỉ chỗ lưu | Studio cũ → None | 500 → ném nguyên")

# ── D. run_plan ─────────────────────────────────────────────────────────────
EN = ("Cold email templates for YouTube sponsorships: how to pitch a brand, what to put in the "
      "subject line, and why a one-pager helps creators close deals faster. ") * 4
VI = ("Định giá tài trợ không còn là chuyện đoán mò. Người sáng tạo cần một bảng giá rõ ràng, "
      "và những thương hiệu được trả lời nhanh sẽ quay lại. ") * 3


class Agent:
    id = "a1"
    name = "Median Content Creator"
    language = "auto"
    allowed_profiles = ["tuan5"]
    content_video_preset = "Tin nhanh"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": "x"}


import tubecli.core.agent as AG  # noqa: E402
import tubecli.core.scraped_store as SS  # noqa: E402
import tubecli.core.brain as B  # noqa: E402
import tubecli.extensions.codex.manager as CM  # noqa: E402

AG.agent_manager.get = lambda aid: Agent() if aid == "a1" else None
SS.query = lambda **kw: {"items": [
    {"title": "Cold email template", "url": "https://x.com/1", "domain": "x.com", "has_content": True,
     "content": EN, "scraped_at": "2026-09-04T01:00:00Z"},
]}
P._agent_scope = lambda agent: list(agent.allowed_profiles)
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P.studio_capabilities = lambda: {"text": {"ok": True, "detail": "gemini"}, "image": {"ok": True, "detail": "cf"},
                                 "assembly": {"ok": True}, "voice": {"ok": True}}
prompts = []


def fake_llm(agent, messages, temperature=0.7):
    prompts.append((messages[0]["content"], messages[-1]["content"]))
    return "TITLE: Giá tài trợ không phải đoán mò\n\n[SHOW: a rate card]\nMở đầu bằng con số.\n[SHOW: inbox]\nKết."


B.AgentBrain._call_llm = staticmethod(fake_llm)
ck = []
P._read_checkpoint = lambda tid: {}
P._write_checkpoint = lambda tid, d: ck.append(d)
CM.codex_manager.set_plan = lambda tid, items, actor="pipeline": None
CM.codex_manager.get_task = lambda tid: {"id": tid, "goal": "Content video"}
P._bulletin = lambda *a, **k: None
P._get = studio_get
PLAN = {"kind": P.KIND_PLAN, "task_id": "t1", "agent_id": "a1", "options": {"transcripts": False, "crawl": False}}


def template_after_language(out):
    lines = out.splitlines()
    i = next((k for k, ln in enumerate(lines) if ln.startswith("- **Language**")), -1)
    return i >= 0 and i + 1 < len(lines) and lines[i + 1].startswith("- **Template**: ")


out = P.run_plan(PLAN, None, lambda: False)
check("D agent auto + tài liệu Anh + mẫu vi → 'Write in Vietnamese.' không kèm câu 'của tài liệu'",
      "Write in Vietnamese." in prompts[-1][0] and "language of the material" not in prompts[-1][0], prompts[-1][0])
check("D kế hoạch: Language — from the template", "**Language**: Vietnamese — from the template" in out, out)
check("D kế hoạch: dòng Template ngay sau Language", template_after_language(out) and "- **Template**: Tin nhanh" in out, out)
check("D checkpoint mang preset + ngôn ngữ", ck and ck[-1].get("preset") == "Tin nhanh" and ck[-1].get("language") == "vi", ck)
# tuỳ chọn của lượt chạy vẫn đứng trên mẫu
prompts.clear()
out2 = P.run_plan({**PLAN, "options": {**PLAN["options"], "language": "en"}}, None, lambda: False)
check("D tuỳ chọn language thắng mẫu", "Write in English." in prompts[-1][0]
      and "**Language**: English — requested for this run" in out2, out2)
check("D resolve_language: mẫu > agent", P.resolve_language({}, Agent(), EN, "ja") == ("ja", "preset")
      and P.resolve_language({"language": "ko"}, Agent(), EN, "ja") == ("ko", "option")
      and P.resolve_language({}, Agent(), EN, "auto") == ("en", "material"))
# agent không có mẫu, lượt chạy không nhắc → không hỏi Studio, không dòng Template
Agent.content_video_preset = ""
gets.clear()
out3 = P.run_plan(PLAN, None, lambda: False)
check("D không mẫu → không gọi presets, không dòng Template, theo tài liệu",
      not any("presets" in g for g in gets) and "**Template**" not in out3
      and "**Language**: English — matched to the material" in out3, (gets, out3))
# mẫu nói trong chat (options) khi agent không cài
out4 = P.run_plan({**PLAN, "options": {**PLAN["options"], "preset": "Tin nhanh"}}, None, lambda: False)
check("D mẫu qua options → Template + ngôn ngữ mẫu", "- **Template**: Tin nhanh" in out4 and "from the template" in out4, out4)
# checkpoint (lượt sửa lại) nhớ mẫu dù options đã mất
P._read_checkpoint = lambda tid: {"script": "[SHOW: old]\ncũ", "title": "Old", "preset": "Tin nhanh"}
out5 = P.run_plan(PLAN, None, lambda: False)
check("D mẫu từ checkpoint khi options mất", "- **Template**: Tin nhanh" in out5, out5)
P._read_checkpoint = lambda tid: {}
# mẫu sai tên → dừng ngay với lỗi rõ, chưa tốn bước nào
try:
    P.run_plan({**PLAN, "options": {**PLAN["options"], "preset": "Nope"}}, None, lambda: False)
    check("D mẫu sai tên → lỗi rõ", False, "không ném")
except RuntimeError as e:
    check("D mẫu sai tên → lỗi rõ liệt kê tên", "Template 'Nope' not found" in str(e) and "Tin nhanh" in str(e), str(e))
print("D run_plan   : ngôn ngữ theo mẫu (nguồn 'preset') | tuỳ chọn > mẫu | dòng Template | checkpoint có preset | sai tên → lỗi rõ")

# ── E. run_render ───────────────────────────────────────────────────────────
sent = []


def fake_post2(path, payload, timeout=300):
    sent.append((path, payload))
    if path == "/api/v1/studio/dramas":
        return {"id": 12}
    if path == "/api/v1/studio/dramas/12/episodes":
        return {"id": 34}
    if path.endswith("/gen-images"):
        return {"task_id": "img1", "total": 0}
    if path.endswith("/batch-tts"):
        return {"task_id": "tts1"}
    if path.endswith("/export-ffmpeg"):
        return {"task_id": "exp1"}
    raise AssertionError(path)


def fake_get2(path, timeout=60):
    if path.startswith("/api/v1/studio/presets"):
        return studio_get(path, timeout)
    if path == "/api/v1/studio/episodes/34/storyboards":
        return [{"id": 1}]
    if "batch-tts/" in path:
        return {"status": "done", "success": 1, "failed": 0}
    if "export-ffmpeg/status" in path:
        return {"status": "completed"}
    if path == "/api/v1/studio/episodes/34":
        return {"id": 34, "video_url": "/x/ep.mp4"}
    raise AssertionError(path)


P._post, P._get = fake_post2, fake_get2
P.POLL_SEC = 0
P.installed_extensions = lambda: {"tts_vibevoice": True}
Agent.content_video_preset = "Tin nhanh"
RENDER = {"kind": P.KIND_RENDER, "task_id": "r1", "agent_id": "a1", "script": "[SHOW: x]\nMở đầu bằng con số.",
          "title": "T", "language": "vi", "options": {}}


def drama_and_images():
    return (next(p for path, p in sent if path == "/api/v1/studio/dramas"),
            next(p for path, p in sent if path.endswith("/gen-images")))


ck.clear()
out_r = P.run_render(RENDER, None, lambda: False)
drama, gi = drama_and_images()
md = drama["metadata"]
check("E style của mẫu lên drama", drama["style"] == FIELDS["style"], drama)
check("E total_episodes của mẫu (> 0)", drama["total_episodes"] == 3, drama)
check("E metadata của mẫu trải lên drama",
      md["content_format"] == "drama" and md["video_length"] == "short_60s" and md["text_in_video"] == "notext"
      and md["pipeline"] == FIELDS["metadata"]["pipeline"] and md["pipeline_template"] == "drama_scene"
      and md["gallery_category_id"] == 2, md)
check("E   + khoá của pipeline vẫn còn", md["source"] == "content_video" and md["agent_id"] == "a1"
      and md["tts_voice"] == "vi-VN-HoaiMyNeural" and md["tts_engine"] == "edge", md)
check("E   + tên mẫu", md["preset"] == "Tin nhanh", md)
check("E khung hình theo mẫu (9:16) khi lượt chạy không đòi", md["aspect_ratio"] == "9:16", md)
check("E gen-images cùng khung hình với drama", gi["aspect_ratio"] == "9:16", gi)
check("E kết quả: dòng Template ngay sau Language", template_after_language(out_r) and "- **Template**: Tin nhanh" in out_r, out_r)
check("E   không cảnh báo", "⚠️" not in out_r, out_r)
check("E checkpoint bước studio mang preset", ck and ck[-1].get("preset") == "Tin nhanh" and ck[-1].get("episode_id") == 34, ck)
# lượt chạy đòi 9:16 rõ ràng (cue reels) → thắng mẫu 1:1; khoá pipeline thắng khoá mẫu trùng tên
sent.clear()
P.run_render({**RENDER, "options": {"aspect_ratio": "9:16", "preset": "Vuông"}}, None, lambda: False)
drama, gi = drama_and_images()
check("E 9:16 rõ ràng thắng mẫu 1:1, drama = gen-images", drama["metadata"]["aspect_ratio"] == "9:16" and gi["aspect_ratio"] == "9:16", (drama, gi))
check("E options.preset thắng agent.content_video_preset", drama["metadata"]["preset"] == "Vuông", drama)
check("E mẫu không ghi đè được khoá của pipeline (source)", drama["metadata"]["source"] == "content_video", drama)
check("E total_episodes = 0 → không gửi", "total_episodes" not in drama, drama)
# options mang đúng mặc định (16:9) = không đòi → mẫu thắng
sent.clear()
P.run_render({**RENDER, "options": {"aspect_ratio": "16:9", "preset": "Vuông"}}, None, lambda: False)
drama, gi = drama_and_images()
check("E options = mặc định 16:9 → mẫu 1:1 thắng", drama["metadata"]["aspect_ratio"] == "1:1" and gi["aspect_ratio"] == "1:1", (drama, gi))
sent.clear()
P.run_render({**RENDER, "options": {"aspect_ratio": "16:9", "aspect_ratio_explicit": True, "preset": "Vuông"}}, None, lambda: False)
drama, gi = drama_and_images()
check("E aspect_ratio_explicit ép 16:9 thắng mẫu", drama["metadata"]["aspect_ratio"] == "16:9" and gi["aspect_ratio"] == "16:9", (drama, gi))
# thiếu ngôn ngữ payload/checkpoint → ngôn ngữ mẫu đứng trước đoán từ kịch bản
sent.clear()
P.run_render({**RENDER, "language": "", "script": VI, "options": {"preset": "Vuông"}}, None, lambda: False)
drama, _ = drama_and_images()
check("E không có ngôn ngữ payload → mẫu (en) trước đoán kịch bản (vi)",
      drama["language"] == "en" and drama["metadata"]["tts_voice"] == "en-US-AriaNeural", drama)
check("E   payload.language vẫn đứng trên mẫu", next(p for path, p in sent if path == "/api/v1/studio/dramas")["language"] == "en"
      and (sent.clear() or P.run_render({**RENDER, "options": {"preset": "Vuông"}}, None, lambda: False))
      and drama_and_images()[0]["language"] == "vi")
# preset đi theo payload render (create_render_task chép từ checkpoint) khi agent không cài
Agent.content_video_preset = ""
sent.clear()
P.run_render({**RENDER, "preset": "Tin nhanh"}, None, lambda: False)
drama, _ = drama_and_images()
check("E preset từ payload render", drama["metadata"].get("preset") == "Tin nhanh" and drama["style"] == FIELDS["style"], drama)
sent.clear()
P.run_render(RENDER, None, lambda: False)
drama, gi = drama_and_images()
check("E không mẫu → vibe mặc định, không khoá preset", drama["style"] == "news" and "preset" not in drama["metadata"]
      and "total_episodes" not in drama and drama["metadata"]["aspect_ratio"] == "16:9" and gi["aspect_ratio"] == "16:9", drama)
events, created = [], []
CM.codex_manager.get_events = lambda tid, limit=200: [
    {"data": {"kind": "content_video.plan", "task_id": tid, "agent_id": "a1", "options": {}}}]
P._read_checkpoint = lambda tid: {"script": "[SHOW: x]\ny", "title": "T", "language": "vi", "preset": "Tin nhanh"}
CM.codex_manager.create_task = lambda **kw: created.append(kw) or {"id": "r9", "seq": 12, "status": "queued", **kw}
CM.codex_manager.append_event = lambda *a, **k: events.append((a, k))
P.create_render_task({"id": "p1", "seq": 11, "assignee_id": "a1", "assignee_name": "MC", "origin": {}}, "owner")
kind_ev = next(k["data"] for a, k in events if k.get("data", {}).get("kind") == P.KIND_RENDER)
check("E create_render_task chép preset từ checkpoint vào payload render", kind_ev["preset"] == "Tin nhanh" and kind_ev["language"] == "vi", kind_ev)
P._read_checkpoint = lambda tid: {}
print("E run_render : style/total_episodes/metadata của mẫu + khoá pipeline + tên mẫu | khung hình: mẫu > mặc định, đòi rõ > mẫu, gen-images khớp | preset theo payload/checkpoint")

# ── F. Studio cũ ────────────────────────────────────────────────────────────
P.installed_extensions = lambda: {"content_studio": True, "tts_vibevoice": True}
STUDIO["old"] = True
Agent.content_video_preset = "Tin nhanh"
sent.clear()
out_f = P.run_render(RENDER, None, lambda: False)
drama, gi = drama_and_images()
check("F render: vibe mặc định", drama["style"] == "news" and "preset" not in drama["metadata"]
      and drama["metadata"]["aspect_ratio"] == "16:9" and gi["aspect_ratio"] == "16:9", drama)
check("F   cảnh báo nêu tên mẫu + bảo cập nhật, không dòng Template",
      "⚠️ Template 'Tin nhanh' ignored: Content Studio is too old for templates — update it from the Market" in out_f
      and "**Template**" not in out_f, out_f)
P._get = studio_get
out_fp = P.run_plan(PLAN, None, lambda: False)
check("F plan: cảnh báo hiện trong kế hoạch, ngôn ngữ rơi về tài liệu",
      "Content Studio is too old for templates — update it from the Market" in out_fp
      and "**Language**: English — matched to the material" in out_fp and "**Template**" not in out_fp, out_fp)
STUDIO["old"] = False
print("F Studio cũ  : cảnh báo (render + plan), vibe mặc định, không dòng Template")


# ── G. sau phản biện: tên gõ trần, tra khoan dung, mẫu bị xoá, Studio chưa cài ──
P._post, P._get = fake_post2, fake_get2
P.installed_extensions = lambda: {"content_studio": True, "tts_vibevoice": True}
STUDIO["old"] = False
for msg, want in [
    ('làm video từ những gì đã đọc hôm nay theo mẫu Tin nhanh nhé', "Tin nhanh"),
    ('làm video từ những gì đã đọc hôm nay theo mẫu Tin nhanh!', "Tin nhanh"),
    ('làm video từ những gì đã đọc hôm nay với mẫu tin dọc?', "tin dọc"),
    ('làm video từ những gì đã đọc hôm nay theo mẫu Tin nhanh giúp tôi nhé', "Tin nhanh"),
    ('make a video from what I read today with the template News Flash please', "News Flash"),
    ('lam video tu nhung gi da doc hom nay theo mau Tin nhanh', "Tin nhanh"),
    ('make a video from what I read today using preset "Ben\'s picks"', "Ben's picks"),
]:
    r = cls_(msg)
    check(f"G intent: {want!r} từ {msg[-38:]!r}",
          r is not None and r.intent_type == "content_video" and r.extracted_data.get("preset") == want,
          (r and r.extracted_data.get("preset")))
cn = P._canonical_preset_name
check("G canonical: khác hoa/thường", cn("tin nhanh", ["Tin nhanh", "Vuông"]) == "Tin nhanh")
check("G canonical: câu dính chữ sau tên", cn("Tin nhanh hôm nay", ["Tin nhanh", "Vuông"]) == "Tin nhanh")
check("G canonical: hai tên cùng khớp → None (mập mờ)", cn("tin", ["Tin", "tin"]) is None)
check("G canonical: tiền tố dài nhất và duy nhất", cn("Tin nhanh hôm nay", ["Tin nhanh", "Tin nhanh hôm"]) == "Tin nhanh hôm")
check("G canonical: không có gì → None", cn("x", []) is None and cn("", ["x"]) is None)
f = P._load_preset("tin nhanh hôm nay")
check("G _load_preset tra khoan dung → fields + _name chuẩn", isinstance(f, dict) and f.get("_name") == "Tin nhanh", f)
check("G describe_plan ghi mẫu lúc xếp hàng", "- Template: Tin nhanh" in P.describe_plan({"preset": "Tin nhanh"})
      and "Template:" not in P.describe_plan({}))
# mẫu chỉ đến từ checkpoint và đã bị xoá → cảnh báo, vẫn dựng
Agent.content_video_preset = ""
P._read_checkpoint = lambda tid: {"preset": "Đã xoá"}
sent.clear()
out_g = P.run_render({"kind": P.KIND_RENDER, "task_id": "rg", "agent_id": "a1", "script": "[SHOW: x]\nOpen.",
                      "title": "T", "options": {}}, None, lambda: False)
drama, gi = drama_and_images()
check("G mẫu bị xoá sau khi duyệt → vẫn dựng với mặc định + nói ra",
      "Template 'Đã xoá' no longer exists — rendered with Studio defaults" in out_g
      and drama["style"] == "news" and "**Template**" not in out_g, out_g)
P._read_checkpoint = lambda tid: {}
# mẫu do CHÍNH lượt này yêu cầu mà không có → vẫn dừng
try:
    P.run_render({"kind": P.KIND_RENDER, "task_id": "rh", "agent_id": "a1", "script": "[SHOW: x]\nOpen.",
                  "title": "T", "options": {"preset": "Không có"}}, None, lambda: False)
    check("G tên do lượt này yêu cầu mà không có → lỗi rõ", False, "không ném")
except RuntimeError as e:
    check("G tên do lượt này yêu cầu mà không có → lỗi rõ", "not found" in str(e) and "Tin nhanh" in str(e), str(e))
# Studio chưa cài / tắt: câu cảnh báo phải khác câu "quá cũ"
P.installed_extensions = lambda: {"tts_vibevoice": True}
STUDIO["old"] = True
Agent.content_video_preset = "Tin nhanh"
P._get = studio_get
out_gp = P.run_plan(PLAN, None, lambda: False)
check("G Studio chưa cài → nói 'not installed or is disabled', không bảo cập nhật",
      "Template 'Tin nhanh' ignored: Content Studio is not installed or is disabled" in out_gp
      and "too old" not in out_gp, out_gp)
STUDIO["old"] = False
Agent.content_video_preset = ""
P.installed_extensions = lambda: {"content_studio": True, "tts_vibevoice": True}
print("G phan bien  : chữ đuôi/không dấu/nháy đúng cặp | tra khoan dung | mẫu bị xoá → cảnh báo | Studio chưa cài nói đúng")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
