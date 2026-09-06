# Tests for the 0-token content_video path: router → registry handler → chat marker.
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.core import intent_router as R
from tubecli.core import intent_handlers as H

Router = next(v for v in vars(R).values() if isinstance(v, type) and hasattr(v, "classify"))
router = Router()


def cls(msg):
    return router.classify(msg, agent={"id": "a1"}, skills=[])


# 1. positives
r = cls("làm video từ những gì đã đọc hôm nay")
assert r.intent_type == "content_video" and r.skip_llm and r.extracted_data["sources"] == [] and "day" not in r.extracted_data, r
r = cls("Làm video reels từ những gì đã xem hôm qua")
assert r.intent_type == "content_video" and r.extracted_data["day"] == "yesterday" and r.extracted_data["aspect_ratio"] == "9:16", r
r = cls("make a video from what I read today")
assert r.intent_type == "content_video", r
r = cls("tổng hợp tin tức hôm nay thành video")
assert r.intent_type == "content_video", r
r = cls("làm video từ bài này https://vnexpress.net/abc-123.html")
assert r.intent_type == "content_video" and r.extracted_data["sources"] == ["https://vnexpress.net/abc-123.html"], r
print("1 positives  : 5/5 -> content_video (day/aspect/sources extracted)")

# 2. negatives — must keep their own branches
r = cls("tải video https://www.youtube.com/watch?v=abc")
assert r.intent_type != "content_video", r
r = cls("làm video")
assert r.intent_type != "content_video", r
r = cls("làm video từ link")            # source cue but no URL → not ours
assert r.intent_type != "content_video", r
r = cls("xin chào")
assert r.intent_type == "greeting", r
r = cls("tách sub từ video hôm nay")     # subtitle wording stays with subtitles
assert r.intent_type != "content_video", r
print("2 negatives  : download / bare 'làm video' / link-without-url / greeting / subtitle untouched")

# 3. survives the desk (defer_to_model)
cv = cls("làm video từ những gì đã đọc hôm nay")
assert R.defer_to_model(cv) is cv, "content_video must survive defer_to_model"
dl = cls("tải video https://www.youtube.com/watch?v=abc")
assert R.defer_to_model(dl) is not dl, "a guessed intent is still deferred"
print("3 desk       : content_video survives defer_to_model; guessed intents still deferred")

# 4. handler → queued reply with marker, via mocked create_digest_task
from tubecli.extensions.content_video import pipeline as P
calls = []


def fake_create(agent_id, options=None, created_by="user", origin=None, sources=None, **kw):
    calls.append((agent_id, options, created_by, origin, sources))
    return {"id": "0190a1b2-0000-7000-8000-00000000abcd", "seq": 9, "status": "queued"}


P.create_digest_task = fake_create
assert H.has_handler("content_video")
reply = asyncio.run(H.dispatch(cv, {"id": "a1", "name": "MC"}, "vi"))
assert reply and reply.endswith("<!--codex:0190a1b2-0000-7000-8000-00000000abcd:9:queued-->"), reply
assert calls == [("a1", {}, "user", {"agent_id": "a1"}, [])], calls
reply2 = asyncio.run(H.dispatch(cls("làm video reels từ bài này https://x.y/z hôm qua"), {"id": "a1"}, "vi"))
assert calls[-1][1] == {"day": "yesterday", "aspect_ratio": "9:16"} and calls[-1][4] == ["https://x.y/z"], calls[-1]
# "10 phút" phải đi TỚI pipeline: trước đây handler chỉ chuyển day/aspect/preset,
# target_words rơi ở đây và thẻ kết quả ghi "from the template's Video Length".
asyncio.run(H.dispatch(cls("làm video 10 phút từ tất cả những gì đã đọc"), {"id": "a1"}, "vi"))
assert calls[-1][1].get("target_words") == 1500 and calls[-1][1].get("day") == "all", calls[-1]
assert asyncio.run(H.dispatch(cv, {}, "vi")) is None, "no agent → fall back to LLM"
print("4 handler    : queues once, created_by=user, options/sources/target_words passed | no agent -> None")

# 5. chat pipeline lifts the marker into meta
from tubecli.extensions.chat import pipeline as CP
text, task = CP._extract_task_marker(reply)
assert task and task.get("id") == "0190a1b2-0000-7000-8000-00000000abcd" and "<!--" not in text, (text, task)
import inspect
src = inspect.getsource(CP)
assert "handled, _task = _extract_task_marker(handled)" in src
print("5 chat card  : marker lifted -> meta.codex_task, comment removed from text")

# ── Cửa sổ ngày: mặc định chỉ HÔM NAY, phải nói được "tất cả" ────────────────
# Ca thật 5/9/26: task render chạy ngon tối hôm trước, sáng sau ra "The corpus
# has nothing new" — kho đầy nhưng lệnh chỉ nhìn hôm nay, và không có cách nào
# nói "lấy hết" nên người dùng tắc mỗi sáng.
for _msg, _want in [
    ("làm video từ tất cả những gì đã đọc", "all"),
    ("lam video tu tat ca noi dung da thu duoc", "all"),
    ("làm video từ toàn bộ dữ liệu đã thu thập", "all"),
    ("make a video from everything I have read", "all"),
    ("làm video từ những gì đã đọc hôm qua", "yesterday"),
    ("làm video từ những gì đã đọc hôm nay", None),
]:
    _r = cls(_msg)
    assert _r is not None and _r.intent_type == "content_video", (_msg, _r and _r.intent_type)
    assert _r.extracted_data.get("day") == _want, (_msg, _r.extracted_data.get("day"), _want)
# "tất cả" KHÔNG được là cue trần: hai câu này không phải làm video từ kho.
for _msg in ["làm video quảng cáo cho tất cả sản phẩm", "gửi tất cả hoá đơn qua email"]:
    _r = cls(_msg)
    assert not _r or _r.intent_type != "content_video", (_msg, _r and _r.intent_type)
print("6 cua so ngay: 'tất cả' → all | 'hôm qua' → yesterday | mặc định hôm nay | không khớp nhầm")


# ── Độ dài video: nói được "N phút" ─────────────────────────────────────────
# Ca thật: "video làm ngắn quá". Mọi video ra ~90 giây vì target_words ghi cứng
# 260 và chat không có cách nào đổi — kể cả khi mẫu Studio chọn "Long > 10 phút".
for _msg, _want in [
    ("làm video 5 phút từ những gì đã đọc hôm nay", 750),
    ("làm video dài 10 phút từ tất cả những gì đã đọc", 1500),
    ("lam video 3 phut tu nhung gi da doc", 450),
    ("make a 2 minute video from what I read today", 300),
    ("làm video từ những gì đã đọc hôm nay", None),
]:
    _r = cls(_msg)
    assert _r is not None and _r.intent_type == "content_video", (_msg, _r and _r.intent_type)
    assert _r.extracted_data.get("target_words") == _want, (_msg, _r.extracted_data.get("target_words"))
# Số vô lý thì bỏ qua, không để một con số lạ đi thẳng vào prompt.
for _msg in ["làm video 999 phút từ những gì đã đọc", "làm video 0 phút từ những gì đã đọc"]:
    assert cls(_msg).extracted_data.get("target_words") is None, _msg
print("7 do dai     : 'N phút' → số chữ | vi/en, có/không dấu | số vô lý bị bỏ")

print()
print("ALL 7 GROUPS PASSED")
