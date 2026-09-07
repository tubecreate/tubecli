# -*- coding: utf-8 -*-
"""Kịch bản viết bằng ngôn ngữ của tài liệu, và giọng đọc phải khớp kịch bản.

Run:  python tests/content_video_language_test.py     (exit 0 = pass)

Ca thật (4/9/26): agent lướt toàn trang tiếng Anh, video ra kịch bản TIẾNG VIỆT
đọc bằng GIỌNG TIẾNG ANH. Hai lỗi độc lập:
  - "auto" (mặc định của mọi agent) được ánh xạ cứng thành Vietnamese
  - bước lồng tiếng không nhìn ngôn ngữ kịch bản: CapCut dùng giọng mặc định
    của tài khoản, edge ghi cứng vi-VN

Kiểm, đối chiếu code thật trong extensions/content_video/pipeline.py:
  A. detect_language      — vi/en/zh/ja/ko/ru, rỗng → ""
  B. resolve_language     — tuỳ chọn > agent > tài liệu > dashboard
  C. run_plan             — agent auto + tài liệu tiếng Anh → prompt "Write in English",
                            kế hoạch ghi rõ nguồn quyết định, checkpoint mang ngôn ngữ
  D. giọng edge           — theo ngôn ngữ; chỉ định lệch → cảnh báo, không đổi
  E. giọng CapCut         — speaker đúng ngôn ngữ; không có → edge; ép capcut → lỗi rõ
  F. run_render           — ngôn ngữ từ payload → drama; thiếu thì nhận từ kịch bản
"""
import os
import sys
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("NGÔN NGỮ KỊCH BẢN THEO TÀI LIỆU, GIỌNG THEO KỊCH BẢN")
print("=" * 70)

# ── A. detect_language ──────────────────────────────────────────────────────
EN = ("Cold email templates for YouTube sponsorships: how to pitch a brand, what to put in the "
      "subject line, and why a one-pager helps creators close deals faster. ") * 4
VI = ("Định giá tài trợ không còn là chuyện đoán mò. Người sáng tạo cần một bảng giá rõ ràng, "
      "và những thương hiệu được trả lời nhanh sẽ quay lại. ") * 3
VI_NO_MARKS = "va cua khong nhung duoc cho la co nay voi nguoi trong " * 5
check("A tiếng Anh", P.detect_language(EN) == "en", P.detect_language(EN))
check("A tiếng Việt có dấu", P.detect_language(VI) == "vi", P.detect_language(VI))
# Không dấu vẫn là tiếng Việt: các từ nối không dấu ("cho", "trong") chỉ có trong tiếng Việt.
check("A tiếng Việt không dấu → vẫn nhận nhờ từ nối", P.detect_language(VI_NO_MARKS) == "vi", P.detect_language(VI_NO_MARKS))
check("A chữ Hán", P.detect_language("这是一个关于创作者赞助定价的视频脚本，内容来自代理收集的资料。") == "zh")
check("A tiếng Nhật", P.detect_language("これはクリエイターのスポンサー価格についての動画台本です。") == "ja")
check("A tiếng Hàn", P.detect_language("이것은 크리에이터 스폰서십 가격에 관한 영상 대본입니다.") == "ko")
check("A tiếng Nga", P.detect_language("Это сценарий видео о ценах на спонсорство для авторов.") == "ru")
check("A rỗng / chỉ ký hiệu → ''", P.detect_language("") == "" and P.detect_language("123 ... !!! 456") == "")
print("A nhan dien  : vi có dấu | vi không dấu (từ nối) | en | zh/ja/ko/ru | rỗng → ''")

# ── B. resolve_language ─────────────────────────────────────────────────────


class Ag:
    def __init__(self, language):
        self.language = language


check("B tuỳ chọn thắng tất cả", P.resolve_language({"language": "ja"}, Ag("vi"), EN) == ("ja", "option"))
check("B tuỳ chọn 'auto' bị bỏ qua, agent thắng", P.resolve_language({"language": "auto"}, Ag("vi"), EN) == ("vi", "agent"))
check("B agent auto → theo tài liệu", P.resolve_language({}, Ag("auto"), EN) == ("en", "material"))
check("B agent rỗng → theo tài liệu", P.resolve_language({}, Ag(""), VI) == ("vi", "material"))
with mock.patch("tubecli.config.get_language", lambda: "ko"):
    check("B không có tài liệu → ngôn ngữ dashboard", P.resolve_language({}, Ag("auto"), "") == ("ko", "dashboard"))
check("B language_name biết mã vùng", P.language_name("zh-TW") == "Chinese (Traditional)" and P.language_name("pt-BR") == "Portuguese")
print("B thu tu     : tuỳ chọn > agent > tài liệu > dashboard | 'auto' không phải ngôn ngữ")

# ── C. run_plan: agent auto + corpus tiếng Anh ──────────────────────────────


class Agent:
    id = "a1"
    name = "Median Content Creator"
    language = "auto"
    allowed_profiles = ["tuan5"]

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
    {"title": "Rate card basics", "url": "https://x.com/2", "domain": "x.com", "has_content": True,
     "content": EN, "scraped_at": "2026-09-04T02:00:00Z"},
]}
P._agent_scope = lambda agent: list(agent.allowed_profiles)
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P.studio_capabilities = lambda: {"text": {"ok": True, "detail": "gemini"}, "image": {"ok": True, "detail": "cf"},
                                 "assembly": {"ok": True}, "voice": {"ok": True}}
prompts = []


def fake_llm(agent, messages, temperature=0.7):
    prompts.append((messages[0]["content"], messages[-1]["content"]))
    return "TITLE: Sponsorship pricing is not guesswork\n\n[SHOW: a rate card]\nOpen with the number.\n[SHOW: inbox]\nClose."


B.AgentBrain._call_llm = staticmethod(fake_llm)
ck = []
P._read_checkpoint = lambda tid: {}
P._write_checkpoint = lambda tid, d: ck.append(d)
CM.codex_manager.set_plan = lambda tid, items, actor="pipeline": None
CM.codex_manager.get_task = lambda tid: {"id": tid, "goal": "Content video"}
P._bulletin = lambda *a, **k: None
out = P.run_plan({"kind": P.KIND_PLAN, "task_id": "t1", "agent_id": "a1", "options": {"transcripts": False, "crawl": False}},
                 None, lambda: False)
sys_prompt = prompts[-1][0]
check("C prompt bảo viết tiếng Anh", "Write in English." in sys_prompt, sys_prompt)
check("C   và nói rõ đó là ngôn ngữ của tài liệu, đừng dịch", "language of the material" in sys_prompt, sys_prompt)
check("C   KHÔNG còn 'Write in Vietnamese' cho agent auto", "Vietnamese" not in sys_prompt, sys_prompt)
check("C kế hoạch ghi ngôn ngữ + nguồn quyết định",
      "**Language**: English — matched to the material; set the agent's language to override" in out, out)
check("C checkpoint mang ngôn ngữ", ck and ck[-1].get("language") == "en", ck)
# agent đặt rõ tiếng Việt → tài liệu tiếng Anh vẫn ra tiếng Việt, và kế hoạch nói đó là do cài đặt agent
Agent.language = "vi"
prompts.clear()
out_vi = P.run_plan({"kind": P.KIND_PLAN, "task_id": "t1", "agent_id": "a1", "options": {"transcripts": False, "crawl": False}},
                    None, lambda: False)
check("C agent đặt vi → 'Write in Vietnamese.' không kèm câu 'của tài liệu'",
      "Write in Vietnamese." in prompts[-1][0] and "language of the material" not in prompts[-1][0], prompts[-1][0])
check("C   kế hoạch nói rõ là cài đặt agent", "**Language**: Vietnamese — the agent's language setting" in out_vi, out_vi)
Agent.language = "auto"
print("C run_plan   : auto + tài liệu Anh → viết tiếng Anh, không dịch | kế hoạch nói nguồn | checkpoint có language")

# ── D. giọng edge theo ngôn ngữ ─────────────────────────────────────────────
check("D bảng giọng: mỗi ngôn ngữ một giọng đúng vùng",
      all(P._voice_matches(v, k) for k, v in P._EDGE_VOICES.items()), P._EDGE_VOICES)
check("D _edge_voice en", P._edge_voice("en") == "en-US-AriaNeural")
check("D _edge_voice zh-TW rồi zh", P._edge_voice("zh-TW") == "zh-TW-HsiaoChenNeural" and P._edge_voice("zh-HK") == "zh-CN-XiaoxiaoNeural")
check("D _edge_voice lạ → en", P._edge_voice("xx") == "en-US-AriaNeural")
check("D chỉ định thì giữ", P._edge_voice("en", "vi-VN-NamMinhNeural") == "vi-VN-NamMinhNeural")
P.installed_extensions = lambda: {"tts_vibevoice": True}
calls = []
P._post = lambda path, payload, timeout=300: calls.append((path, payload)) or {"task_id": "t"}
orig_poll = P._poll_studio
P._poll_studio = lambda *a, **k: {"status": "done", "success": 3, "failed": 0}
st = {"episode_id": 34, "language": "en", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto", "tts_voice": ""})
check("D edge: kịch bản en → giọng en", calls[-1][1]["voice_id"] == "en-US-AriaNeural", calls[-1])
check("D   ghi giọng đã dùng + ngôn ngữ", st.get("tts_voice_used") == "en-US-AriaNeural · English", st.get("tts_voice_used"))
check("D   không cảnh báo", st["warnings"] == [], st["warnings"])
st = {"episode_id": 34, "language": "en", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto", "tts_voice": "vi-VN-HoaiMyNeural"})
check("D chỉ định giọng lệch ngôn ngữ → vẫn dùng, nhưng cảnh báo",
      calls[-1][1]["voice_id"] == "vi-VN-HoaiMyNeural" and len(st["warnings"]) == 1
      and "does not match the script language (English)" in st["warnings"][0], st["warnings"])
print("D giong edge : theo ngôn ngữ | ghi giọng đã dùng | chỉ định lệch → cảnh báo, không lặng lẽ đổi")

# ── E. giọng CapCut theo ngôn ngữ ───────────────────────────────────────────
gets = []


def fake_get(path, timeout=60):
    gets.append(path)
    if path.startswith("/api/v1/capcut-tts/accounts"):
        return {"accounts": [{"email": "a@x.com", "enabled": True}]}
    if path.startswith("/api/v1/capcut-tts/speakers"):
        if "language=en" in path:
            return [{"id": "en_holiday", "name": "Holiday Twist", "language": "en"}]
        return []
    raise AssertionError(path)


P._get = fake_get
P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
posts = []
P._storyboards = lambda ep_id: [{"id": 1, "storyboard_number": 1, "narration_text": "Open with the number."}]
P._post_audio_marks = lambda path, payload, timeout=180: (posts.append(payload) or (b"ID3" + b"\x00" * 2000), [])
P._put = lambda path, payload, timeout=60: {}
import tubecli.config as CFG  # noqa: E402
import tempfile  # noqa: E402

CFG.DATA_DIR = tempfile.mkdtemp(prefix="cv-lang-")
st = {"episode_id": 34, "language": "en", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto"})
check("E hỏi speaker đúng tài khoản + ngôn ngữ", any("email=a%40x.com" in g and "language=en" in g for g in gets), gets)
check("E chọn speaker tiếng Anh", st.get("capcut_speaker") == "en_holiday", st.get("capcut_speaker"))
check("E   gửi speaker đó lên CapCut", posts and posts[-1].get("speaker") == "en_holiday", posts)
check("E   ghi giọng đã dùng", st.get("tts_voice_used") == "CapCut · Holiday Twist · English", st.get("tts_voice_used"))
# kịch bản tiếng Việt, tài khoản không có giọng Việt, auto → rơi về edge với giọng Việt
calls.clear()
st = {"episode_id": 34, "language": "vi", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto"})
check("E không có giọng cho ngôn ngữ → rơi về edge", st["tts_engine"] == "edge" and calls[-1][1]["voice_id"] == "vi-VN-HoaiMyNeural", (st.get("tts_engine"), calls[-1:]))
check("E   và nói ra vì sao", st["warnings"] and "no Vietnamese voice" in st["warnings"][0], st["warnings"])
# ép capcut mà không có giọng → lỗi rõ, không đọc sai
st = {"episode_id": 34, "language": "vi", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
try:
    P._step_tts(st, {"tts_engine": "capcut"})
    check("E ép capcut, không giọng → lỗi rõ", False, "không ném")
except RuntimeError as e:
    check("E ép capcut, không giọng → lỗi rõ", "no voice for Vietnamese" in str(e), str(e))
# chỉ định speaker → không hỏi, dùng luôn
gets.clear()
st = {"episode_id": 34, "language": "vi", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "capcut", "capcut_speaker": "vi_custom"})
check("E chỉ định speaker → không hỏi danh sách, dùng luôn",
      not any("speakers" in g for g in gets) and posts[-1].get("speaker") == "vi_custom", (gets, posts[-1:]))
print("E giong capcut: speaker theo ngôn ngữ | không có → edge + lý do | ép capcut → lỗi rõ | chỉ định → dùng luôn")

# ── F. run_render: ngôn ngữ đi vào drama ────────────────────────────────────
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
P._read_checkpoint = lambda tid: {}
P._poll_studio = orig_poll               # trả lại bản thật (đã mock ở D)
out_r = P.run_render({"kind": P.KIND_RENDER, "task_id": "r1", "agent_id": "a1", "script": "[SHOW: x]\nOpen with the number.",
                      "title": "T", "language": "en", "options": {}}, None, lambda: False)
drama = next(p for path, p in sent if path == "/api/v1/studio/dramas")
check("F ngôn ngữ payload → drama.language", drama["language"] == "en", drama)
check("F   giọng edge mặc định theo ngôn ngữ vào metadata", drama["metadata"]["tts_voice"] == "en-US-AriaNeural", drama["metadata"])
check("F   kết quả ghi ngôn ngữ + giọng", "**Language**: English" in out_r and "en-US-AriaNeural · English" in out_r, out_r)
sent.clear()
P.run_render({"kind": P.KIND_RENDER, "task_id": "r2", "agent_id": "a1", "script": VI, "title": "T", "options": {}}, None, lambda: False)
drama = next(p for path, p in sent if path == "/api/v1/studio/dramas")
check("F thiếu ngôn ngữ → nhận từ chính kịch bản (vi)", drama["language"] == "vi" and drama["metadata"]["tts_voice"] == "vi-VN-HoaiMyNeural", drama)
print("F run_render : ngôn ngữ vào drama + giọng mặc định đúng | thiếu thì nhận từ kịch bản")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
