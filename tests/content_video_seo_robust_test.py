"""SEO lúc đăng bền hơn + lời giải thích lỗi model ảnh Codex qua 9Router (14/11/2026, contabo t3rwap).

Chạy:  python tests/content_video_seo_robust_test.py      (mã thoát 0 = đạt)

(b) «Model SEO không trả lời → video đăng không có tags / mô tả tốt»: agent chạy muse-spark (model qua phiên trình
    duyệt) trả gần-JSON hỏng — cùng kiểu lỗi «Expecting ',' delimiter» thấy ở bước sinh từ khoá của chính agent đó. Nay:
    đọc khoan dung, thử model của nhà khác, và khi không model nào trả lời thì dựng mô tả + tag từ kịch bản.
(a) «The 'gpt-5.6-sol' model is not supported when using Codex with a ChatGPT account»: model lái do 9Router chọn —
    cảnh báo nói rõ điều đó và chỗ sửa.

Mọi lượt gọi model là GIẢ; không mạng.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.core.brain import AgentBrain  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:400]}")


class Agent:
    name = "Deep Biblical Echoes Niche Researcher"
    model = "muse-spark"

    def to_dict(self):
        return {"model": self.model, "name": self.name}


SCRIPT = ("[SHOW: a kitchen]\nYou have probably heard seek first the kingdom of God so often that the words sound like a "
          "slogan. Yet behind them sits one precise question about what comes first when money and worry ask for your "
          "attention. In Matthew chapter six, Jesus is speaking in the Sermon on the Mount about prayer and trust. "
          "The kingdom is the rule of God over every decision. Righteousness is living rightly under that kingdom. "
          "Worry shrinks when the kingdom comes first, and the kingdom reaches the home and the workplace. " * 3)
CHANNEL = {"id": "", "name": "Deep Biblical Echoes", "about": "Bible passages explained"}


def state():
    return {"agent": Agent(), "language": "en", "title": "Seek First: What Matthew 6:33 Really Means", "script": SCRIPT,
            "seo_sources": [{"title": "What Matthew 6:33 means", "url": "https://bibleproject.com/articles/x/"}],
            "warnings": []}


CALLS = []
REPLIES = {}


def fake_llm(agent_dict, messages, temperature=0.7):
    key = (str(agent_dict.get("provider") or ""), str(agent_dict.get("model") or ""))
    CALLS.append(key)
    r = REPLIES.get(key, REPLIES.get("*", ""))
    if isinstance(r, Exception):
        raise r
    return r


AgentBrain._call_llm = staticmethod(fake_llm)
P._seo_timeline = lambda st: []
P._text_model_choices = lambda: [{"provider": "deepseek", "label": "DeepSeek", "models": ["deepseek-chat"]},
                                 {"provider": "gemini", "label": "Gemini", "models": ["gemini-2.5-flash"]}]
from tubecli.core import llm_errors as LE  # noqa: E402
LE.cooling_until = lambda provider, now=None: 0

GOOD = {"keyword": "seek first the kingdom", "title": "Seek First the Kingdom: What Matthew 6:33 Really Means",
        "description": "Seek first the kingdom of God — what it means.\nA study of Matthew 6:33 in its context.\n\n"
                       "We read the verse inside the Sermon on the Mount.\n\n#bible #matthew633 #jesus",
        "tags": ["seek first the kingdom", "matthew 6:33", "sermon on the mount", "bible study", "jesus teachings"],
        "chapters": []}

# ── A. đọc khoan dung ─────────────────────────────────────────────────────────
BROKEN = ('{"keyword": "seek first the kingdom", "title": "Seek First: What "Matthew 6:33" Really Means", '
          '"description": "Jesus said "seek first" the kingdom.\nIt sits inside the Sermon on the Mount.\n\n#bible #jesus", '
          '"tags": ["seek first the kingdom", "matthew 6:33", "bible study"], "chapters": []}')
try:
    json.loads(BROKEN)
    is_json = True
except ValueError:
    is_json = False
got = P._seo_lenient(BROKEN)
check("A1 gần-JSON có nháy / xuống dòng không thoát (kiểu Muse) KHÔNG phải JSON hợp lệ…", not is_json)
check("A2 …nhưng vẫn đọc ra đủ tiêu đề, mô tả, tag, từ khoá", got and got["title"].startswith("Seek First: What \"Matthew 6:33\"")
      and "Sermon on the Mount" in got["description"] and got["tags"][:2] == ["seek first the kingdom", "matthew 6:33"]
      and got["keyword"] == "seek first the kingdom", got)
LABELLED = ("Here is the metadata:\n**Title:** Seek First the Kingdom Explained\nKeyword: seek first the kingdom\n"
            "Description: What Matthew 6:33 means.\nSecond line of the description.\nTags: bible, matthew 6:33, jesus\n")
got = P._seo_lenient(LABELLED)
check("A3 văn bản có nhãn Title / Description / Tags cũng đọc được", got and got["title"] == "Seek First the Kingdom Explained"
      and "Second line" in got["description"] and got["tags"] == ["bible", " matthew 6:33", " jesus"], got)
check("A4 lời từ chối / rác → None (không bịa)", P._seo_lenient("Sorry, I can't help with that.") is None
      and P._seo_lenient("") is None and P._seo_lenient('{"tags": ["a"]}') is None)

# ── B. _seo_for: model agent hỏng JSON → vẫn có SEO, không gọi model khác ─────
CALLS.clear()
REPLIES.clear()
REPLIES[("", "muse-spark")] = BROKEN
st = state()
seo = P._seo_for(st, {}, CHANNEL)
check("B1 model của agent trả gần-JSON → dùng luôn, không cảnh báo, không gọi model khác",
      st["warnings"] == [] and CALLS == [("", "muse-spark")] and "matthew 6:33" in [t.lower() for t in seo["tags"]],
      (st["warnings"], CALLS, seo["tags"]))

# model agent im lặng → model nhà khác
CALLS.clear()
REPLIES.clear()
REPLIES[("", "muse-spark")] = ""
REPLIES[("deepseek", "deepseek-chat")] = json.dumps(GOOD)
st = state()
seo = P._seo_for(st, {}, CHANNEL)
check("B2 model của agent im lặng → thử model nhà khác và dùng được", CALLS == [("", "muse-spark"), ("deepseek", "deepseek-chat")]
      and st["warnings"] == [] and len(seo["tags"]) >= 5 and "#bible" in seo["description"], (CALLS, st["warnings"], seo["tags"]))

CALLS.clear()
REPLIES.clear()
REPLIES[("", "muse-spark")] = RuntimeError("browser signed out")
REPLIES[("deepseek", "deepseek-chat")] = "[OpenAI Error] 402 Insufficient Balance"
REPLIES[("gemini", "gemini-2.5-flash")] = json.dumps(GOOD)
st = state()
seo = P._seo_for(st, {}, CHANNEL)
check("B3 hai model đầu lỗi → model thứ ba; tối đa 1 + 2 lượt gọi", len(CALLS) == 3 and st["warnings"] == []
      and seo["title"].startswith("Seek First the Kingdom"), (CALLS, st["warnings"]))

# ── C. không model nào trả lời → dựng không cần AI ────────────────────────────
CALLS.clear()
REPLIES.clear()
REPLIES["*"] = "Sorry, I can't help with that."
st = state()
seo = P._seo_for(st, {}, CHANNEL)
check("C1 không model nào trả lời → tiêu đề là tiêu đề video", seo["title"] == "Seek First: What Matthew 6:33 Really Means", seo["title"])
check("C2 …có tag dựng từ tiêu đề / tên kênh / từ lặp trong kịch bản (trước: 0 tag)", len(seo["tags"]) >= 5
      and "Deep Biblical Echoes" in seo["tags"] and "kingdom" in seo["tags"] and "Seek First" in seo["tags"], seo["tags"])
check("C3 …mô tả ≥ 250 ký tự, cắt ở cuối câu, có link nguồn và hashtag", len(seo["description"]) >= 250
      and "https://bibleproject.com/articles/x/" in seo["description"] and "#" in seo["description"].splitlines()[-1]
      and "[SHOW" not in seo["description"], seo["description"][-200:])
check("C4 …tag trong ngân sách 500 ký tự của YouTube, không có «#»", sum(len(t) + 1 for t in seo["tags"]) <= 500
      and all("#" not in t for t in seo["tags"]))
check("C5 …MỘT cảnh báo nói rõ đã thử model nào và metadata dựng không cần AI", len(st["warnings"]) == 1
      and "SEO model did not answer" in st["warnings"][0] and "muse-spark" in st["warnings"][0]
      and "without AI" in st["warnings"][0], st["warnings"])
check("C6 từ dừng không thành tag", not ({"really", "means", "about", "their"} & {t.lower() for t in seo["tags"]}), seo["tags"])
st = state()
seo = P._seo_for(st, {"seo_tags": ["my tag"], "seo_title": "My Own Title"}, CHANNEL)
check("C7 phần người gọi tự viết (seo_title / seo_tags) vẫn thắng bản dự phòng", seo["title"] == "My Own Title"
      and seo["tags"] == ["my tag"], seo)

# ── D. lỗi model lái của Codex qua 9Router ────────────────────────────────────
REASON = ("HTTP 400: {\"error\":{\"message\":\"[codex/gpt-image-2] [400]: The 'gpt-5.6-sol' model is not supported when "
          "using Codex with a ChatGPT account. (reset after 29m 20s")
hint = P.codex_image_driver_hint(REASON)
check("D1 nhận ra lỗi model lái, nêu đúng tên model và rằng chờ không khỏi", "«gpt-5.6-sol»" in hint and "9Router" in hint
      and "waiting does not help" in hint, hint)
check("D2 lỗi khác → không gắn lời giải thích này", P.codex_image_driver_hint("HTTP 429 quota exceeded") == ""
      and P.codex_image_driver_hint("") == "")
lines = P._fallback_image_warnings({"dead_image_models": [{"model": "9router/cx/gpt-image-2", "reason": REASON, "shots": 62}]})
check("D3 dòng cảnh báo của task: một dòng, nói sửa ở 9Router / đổi model ảnh của mẫu, không còn JSON cụt",
      len(lines) == 1 and "9router/cx/gpt-image-2" in lines[0] and "sign in a ChatGPT account" in lines[0]
      and "62 shot(s)" in lines[0] and "Content Studio" in lines[0] and '{"error"' not in lines[0], lines)
lines = P._fallback_image_warnings({"dead_image_models": [{"model": "cloudflare/x", "reason": "HTTP 400: unknown model", "shots": 3}]})
check("D4 model chết vì lý do khác giữ câu cũ", "unknown model" in lines[0] and "Settings → AI image" in lines[0], lines)
from tubecli.core import image_gen as IG  # noqa: E402
check("D5 lõi coi lỗi này là CẤU HÌNH (không thử lại mỗi shot)", IG._permanent(IG.ProviderError("error", "9Router: " + REASON)))

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
