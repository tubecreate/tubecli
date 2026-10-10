# -*- coding: utf-8 -*-
"""Phụ đề YouTube vào kho thu thập sau mỗi lượt chạy (core/youtube_harvest.py, 10/10/2026).

Kiểm (KHÔNG mạng — run_log, agent, yt-dlp, phụ đề đều giả; kho ở thư mục tạm):
  1. video agent đã mở trong lượt (history có agentId, sau giờ bắt đầu) được ưu tiên, giữ ĐÚNG url lượt ghé
  2. thiếu thì lấy từ tìm kiếm theo câu tìm kiếm của lượt
  3. ghi articles.json + history.json như extract_content.js ⇒ scraped_store thấy là bài CÓ nội dung của agent
  4. không lấy lại video đã có; bỏ phụ đề quá ngắn
  5. tắt thu thập / youtube_subs_per_run = 0 / lượt email / lượt hỏng ⇒ không làm gì
  6. pick_track: video lồng tiếng nhiều thứ tiếng ⇒ lấy «-orig» của NGÔN NGỮ GỐC, không phải cái đầu tiên

Run:  python tests/youtube_harvest_test.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tubecli.core import agent as AG            # noqa: E402
from tubecli.core import run_log                # noqa: E402
from tubecli.core import scraped_store as S     # noqa: E402
from tubecli.core import youtube_harvest as H   # noqa: E402
from tubecli.core import youtube_transcript as YT  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


TMP = Path(tempfile.mkdtemp(prefix="yt_harvest_"))
S.data_root = lambda: TMP


class FakeAgent:
    def __init__(self, **kw):
        self.id, self.name = "agent-1", "Researcher"
        self.enable_scraping, self.youtube_subs_per_run, self.language, self.scraper_text_limit = True, 2, "es", 10000
        self.__dict__.update(kw)


AGENT = {"a": FakeAgent()}
AG.agent_manager.get = lambda aid: AGENT["a"] if aid == "agent-1" else None
START = datetime.now() - timedelta(minutes=10)            # run_log: giờ địa phương không múi
LAUNCH = {"profile": "p1", "behavior": "watchVideos", "query": "video diffusion models explained"}
run_log.list_for_agent = lambda aid, days=2, limit=500: [
    {"run_id": "r1", "ts": START.isoformat(), "launch": dict(LAUNCH)}]
SEARCH = [{"id": "BBBBBBBBBBB", "url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "title": "found", "duration": 600},
          {"id": "CCCCCCCCCCC", "url": "https://www.youtube.com/watch?v=CCCCCCCCCCC", "title": "found2", "duration": 700}]
searched = []
H.search_videos = lambda q, n, timeout=45: searched.append((q, n)) or [dict(v) for v in SEARCH]
WORDS = {"n": 200}
fetched = []


def fake_fetch(url, prefer_lang="", timeout=60, **k):
    fetched.append((url, prefer_lang))
    vid = H._vid(url)
    return {"ok": True, "id": vid, "url": url, "title": f"Video {vid}", "channel": "Chan", "language": "en",
            "kind": "auto", "text": " ".join(["word"] * WORDS["n"]), "words": WORDS["n"]}


YT.fetch_transcript = fake_fetch
utc = lambda dt: dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")   # noqa: E731
WATCHED = "https://www.youtube.com/watch?v=AAAAAAAAAAA&pp=ygUQ"
(TMP / "p1").mkdir()
(TMP / "p1" / "history.json").write_text(json.dumps({"scrapedArticles": [
    {"title": "old", "url": "https://www.youtube.com/watch?v=OOOOOOOOOOO", "scrapedAt": utc(START - timedelta(hours=3)),
     "isScraped": False, "agentId": "agent-1"},
    {"title": "other agent", "url": "https://www.youtube.com/watch?v=XXXXXXXXXXX", "scrapedAt": utc(datetime.now()),
     "isScraped": False, "agentId": "agent-2"},
    {"title": "watched (1) - YouTube", "url": WATCHED, "scrapedAt": utc(datetime.now()), "isScraped": False,
     "agentId": "agent-1"}]}), encoding="utf-8")

print("── 1–3. video đã xem + tìm kiếm → kho ─────────────────────────")
msg = H.harvest_after_run("agent-1", "r1", "p1", "completed")
arts = json.loads((TMP / "p1" / "articles.json").read_text(encoding="utf-8"))
ok([a["url"] for a in arts] == [WATCHED, SEARCH[0]["url"]], "video ĐÃ XEM trước (giữ đúng url lượt ghé), rồi 1 video tìm được",
   [a["url"] for a in arts])
ok(searched == [("video diffusion models explained", 1)], "tìm kiếm đúng câu của lượt, chỉ phần còn thiếu", searched)
ok(all(p == "" for _, p in fetched), "phụ đề theo ngôn ngữ GỐC của video (AI viết lại ở bước làm video)", fetched)
ok(all(a["content"] and a.get("source") == H.SOURCE and a["author"] == "Chan" for a in arts), "bài có nội dung + nguồn")
hist = json.loads((TMP / "p1" / "history.json").read_text(encoding="utf-8"))["scrapedArticles"]
row = next(r for r in hist if r["url"] == WATCHED)
ok(row["isScraped"] and row["agentId"] == "agent-1" and row["contentLength"] > 0, "dòng lượt ghé thành «đã thu», có agentId", row)
ok(not any(H._vid(r["url"]) == "OOOOOOOOOOO" and r.get("isScraped") for r in hist), "video xem TRƯỚC lượt này không bị lấy")
got = S.query(agent_id="agent-1", allowed_profiles=["p1"], only_with_content=True, limit=50)
items = got.get("items") if isinstance(got, dict) else got
ok(len(items or []) == 2, "scraped_store thấy 2 bài CÓ nội dung của agent (tính vào ngưỡng tự tạo video)",
   [i.get("url") for i in items or []])
ok("saved 2/2" in msg, "câu tóm tắt", msg)

print("── 4. không lấy lại · phụ đề ngắn ─────────────────────────────")
fetched.clear()
msg2 = H.harvest_after_run("agent-1", "r1", "p1", "completed")
ok(len(json.loads((TMP / "p1" / "articles.json").read_text(encoding="utf-8"))) == 3 and
   all(H._vid(u) not in ("AAAAAAAAAAA", "BBBBBBBBBBB") for u, _ in fetched), "video đã có thì bỏ, lấy cái tìm được kế tiếp", fetched)
WORDS["n"] = 20
(TMP / "p2").mkdir()
LAUNCH["profile"] = "p2"
msg3 = H.harvest_after_run("agent-1", "r1", "", "completed")
ok("saved 0/2" in msg3 and "too short" in msg3 and not (TMP / "p2" / "articles.json").exists(), "phụ đề quá ngắn ⇒ bỏ", msg3)
WORDS["n"] = 200

print("── 5. các trường hợp không làm gì ─────────────────────────────")
fetched.clear()
AGENT["a"] = FakeAgent(enable_scraping=False)
ok(H.harvest_after_run("agent-1", "r1", "p1", "completed").startswith("skip: data collection off"), "tắt thu thập")
AGENT["a"] = FakeAgent(youtube_subs_per_run=0)
ok(H.harvest_after_run("agent-1", "r1", "p1", "completed").startswith("skip: youtube_subs_per_run"), "số video = 0")
AGENT["a"] = FakeAgent()
LAUNCH["behavior"] = "checkEmails"
ok(H.harvest_after_run("agent-1", "r1", "p1", "completed").startswith("skip: behaviour"), "lượt kiểm email")
LAUNCH["behavior"] = "watchVideos"
ok(H.harvest_after_run("agent-1", "r1", "p1", "error").startswith("skip: outcome"), "lượt hỏng")
ok(not fetched, "không gọi lấy phụ đề lần nào", fetched)
H._harvest = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
ok(H.harvest_after_run("agent-1", "r1", "p1", "completed").startswith("error:"), "lỗi bất ngờ ⇒ trả câu, KHÔNG ném")

print("── 6. pick_track với video lồng tiếng ─────────────────────────")
e = [{"ext": "json3", "url": "u"}]
info = {"language": "en-US", "subtitles": {},
        "automatic_captions": {"ar-orig": e, "ar": e, "en": e, "es": e, "en-orig": e, "fr-FR-orig": e}}
ok(YT.pick_track(info, "es")[0] == "en-orig", "lấy en-orig (ngôn ngữ gốc), không phải ar-orig", YT.pick_track(info, "es"))
ok(YT.pick_track({"language": "", "automatic_captions": {"de-orig": e, "de": e}}, "")[0] == "de-orig",
   "không biết ngôn ngữ gốc ⇒ «-orig» bất kỳ")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
