# -*- coding: utf-8 -*-
"""Công cụ YouTube của MCP — extensions/codex_gpt/youtube_tools.py (user 22/11/2026: «thêm vào công cụ mcp luôn»).

  A. youtube_channels: mọi token có quyền YouTube; KHÔNG lộ email / token; một token hỏng không che kênh khác
  B. youtube_videos: trạng thái scheduled, lọc, lật trang, bản Video Manager cũ → báo cập nhật
  C. youtube_schedule: khoá ĐÚNG token của kênh; chỉ gửi publish_at (không privacy); sai một dòng = không đặt dòng nào;
     bỏ hẹn; lỗi từng video; YouTube lưu giờ khác → FAILED; bản cũ → không báo «đã hẹn»
  D. youtube_update: chỉ trường được đưa; kiểm dữ liệu
  E. trình kết nối: có trong tools/list, chỉ-đọc không hẹn được, không cần duyệt, Codex GPT phải qua thẻ duyệt

Chạy:  python tests/youtube_tools_test.py   (exit 0 = pass). Auth Manager + Video Manager giả, không gọi mạng nào.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
os.environ["TUBECLI_CODEX_GPT_DIR"] = tempfile.mkdtemp(prefix="yt_tools_codex_")

from fastapi import FastAPI, HTTPException, Request                   # noqa: E402

from tubecli.core import claude_connector as CC                       # noqa: E402
from tubecli.extensions.codex_gpt import tools as T                   # noqa: E402
from tubecli.extensions.codex_gpt import youtube_tools as Y           # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


TOKENS = [{"token_id": "tok-A", "authorized_email": "secret.a@example.com", "scopes": ["youtube"], "status": "active"},
          {"token_id": "tok-B", "authorized_email": "secret.b@example.com", "scopes": ["youtube"], "status": "expired"},
          {"token_id": "tok-BAD", "authorized_email": "secret.c@example.com", "scopes": ["youtube"], "status": "active"}]
Y.tokens = lambda: TOKENS
CHANNELS = {"tok-A": [{"id": "UCaaa", "title": "Kho Bài Giảng", "video_count": 804, "subscribers": 10,
                       "extra": {"uploads_playlist": "UUaaa"}}],
            "tok-B": [{"id": "UCbbb", "title": "Other", "video_count": 1, "subscribers": 1, "extra": {}}]}
ST = {"old": False, "installed": True, "wrong": False}
CALLS = []
VIDEOS = [{"id": f"vid{i:05d}", "title": f"V{i}", "status": "private" if i % 2 else "public", "published_at": "2026-11-21",
           "views": i, "extra": {"publish_at": "2026-12-01T12:45:00Z" if i == 3 else ""}} for i in range(120)]

app = FastAPI()


@app.get("/api/v1/video_manager/channels")
async def _channels(token_id: str = "", email: str = ""):
    if not ST["installed"]:
        raise HTTPException(404)
    if token_id not in CHANNELS:
        raise HTTPException(401, "Re-authorize this account in Auth Manager ya29.SECRET-abc")
    return {"success": True, "channels": CHANNELS[token_id]}


@app.get("/api/v1/video_manager/videos")
async def _videos(request: Request, channel_id: str, token_id: str = "", page_token: str = "", max_results: int = 20):
    CALLS.append(("LIST", channel_id, dict(request.query_params)))
    at = int(page_token or 0)
    rows = [dict(v, extra=({} if ST["old"] else v["extra"])) for v in VIDEOS[at:at + max_results]]
    nxt = at + max_results
    return {"success": True, "videos": rows, "next_page_token": str(nxt) if nxt < len(VIDEOS) else "", "total": 120}


@app.put("/api/v1/video_manager/videos/{vid}")
async def _put(vid: str, request: Request):
    body = await request.json()
    CALLS.append(("PUT", vid, dict(request.query_params), body, request.headers.get("x-tubecli-agent")))
    if ST["old"] and set(body) == {"publish_at"}:
        raise HTTPException(400, "No fields to update")
    if vid == "publicvid":
        raise HTTPException(400, "Video 'publicvid' is public now — only a private video can be scheduled")
    if "publish_at" in body:
        return {"success": True, "privacy": "private",
                "publish_at": "2030-01-01T00:00:00Z" if ST["wrong"] and body["publish_at"] else body["publish_at"]}
    return {"success": True, "privacy": body.get("privacy", "private"), "publish_at": ""}


async def yes(*a, **k):
    return True, "", ""


def call(name, args, approve=yes):
    r = asyncio.run(T.call_tool(name, args, app, approve, agent="claude_connector"))
    return r["isError"], r["content"][0]["text"]


def puts():
    return [c for c in CALLS if c[0] == "PUT"]


def reset(**kw):
    CALLS.clear()
    ST.update(old=False, installed=True, wrong=False, **kw)
    Y._cache.update(at=0.0, rows=[])


WHEN = "2099-12-01T19:45:00+07:00"
UTC = "2099-12-01T12:45:00Z"

# ── A ──
reset()
err, txt = call("youtube_channels", {})
check("A1 hai kênh của hai token, kể cả token «expired» làm mới được", not err and "UCaaa" in txt and "UCbbb" in txt, txt)
check("A2 không lộ email / token_id / access token", not any(x in txt for x in ("secret.", "tok-", "ya29")), txt)
check("A3 token hỏng được nói ra, không che kênh khác", "could not be read" in txt and "401" in txt, txt)
reset()
ST["installed"] = False
err, txt = call("youtube_channels", {})
check("A4 chưa cài Video Manager → chỉ cách cài", err and "vid_mn" in txt, txt)
reset()
saved, Y.tokens = Y.tokens, lambda: []
err, txt = call("youtube_channels", {})
check("A5 chưa có tài khoản → nói chủ vào Auth Manager", err and "Auth Manager" in txt, txt)
Y.tokens = saved

# ── B ──
reset()
err, txt = call("youtube_videos", {"channel": "UCaaa"})
check("B1 đọc 50 video mới nhất, có next page_token", not err and "50 newest" in txt and "page_token: 50" in txt, txt[-200:])
q = CALLS[0][2]
check("B2 dùng token + playlist của đúng kênh", q["token_id"] == "tok-A" and q["uploads_playlist_id"] == "UUaaa" and "email" not in q, q)
err, txt = call("youtube_videos", {"channel": "kho bài giảng", "status": "scheduled", "scan": 120})
check("B3 tìm kênh theo tên, lọc scheduled = đúng 1 video kèm giờ", not err and "1 scheduled" in txt and "vid00003" in txt
      and "2026-12-01T12:45:00Z" in txt and "vid00005" not in txt, txt)
err, txt = call("youtube_videos", {"channel": "UCaaa", "status": "private", "scan": 120})
check("B4 private không lẫn video đang hẹn", not err and "vid00003" not in txt and "vid00005" in txt, txt[:300])
err, txt = call("youtube_videos", {"channel": "UCaaa", "scan": 500})
check("B5 nhiều hơn 100 dòng → nói rõ chỉ hiện 100", not err and "Showing 100" in txt and "120 newest" in txt, txt[:300])
ST["old"] = True
err, txt = call("youtube_videos", {"channel": "UCaaa", "status": "scheduled"})
check("B6 Video Manager cũ + lọc scheduled → báo cập nhật, không trả danh sách rỗng", err and Y.MIN_VERSION in txt, txt)
reset()
err, txt = call("youtube_videos", {"channel": "Nope"})
check("B7 kênh lạ → liệt kê kênh có", err and "UCaaa" in txt and "secret." not in txt, txt)

# ── C ──
reset()
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "q5-xLqSZAFI", "publish_at": WHEN},
                                                                  {"video_id": "https://youtu.be/abcdefghijk", "publish_at": WHEN}]})
check("C1 hẹn hai video (id + link) → 2 of 2", not err and "2 of 2" in txt and UTC in txt, txt)
check("C2 đúng token của kênh, CHỈ publish_at (không privacy, không email)", sorted(p[1] for p in puts()) == ["abcdefghijk", "q5-xLqSZAFI"]
      and all(p[2] == {"provider": "youtube", "token_id": "tok-A"} and p[3] == {"publish_at": UTC} for p in puts()), puts())
check("C3 mang X-TubeCLI-Agent của người gọi", all(p[4] == "claude_connector" for p in puts()), puts())
for label, bad, word in (("thiếu múi giờ", "2099-12-01T19:45:00", "no timezone"), ("giờ đã qua", "2020-01-01T00:00:00Z", "past"),
                         ("sai dạng", "tối nay", "ISO 8601"), ("rỗng", "", "ISO 8601")):
    reset()
    err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "goodvideo01", "publish_at": WHEN},
                                                                      {"video_id": "badvideo001", "publish_at": bad}]})
    check(f"C4 một dòng {label} → KHÔNG đặt dòng nào", err and word in txt and "item 2" in txt and not CALLS, (txt, CALLS))
reset()
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "samevideo01", "publish_at": WHEN}] * 2})
check("C5 trùng video → từ chối", err and "twice" in txt and not puts(), txt)
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": f"video{i:06d}", "publish_at": WHEN} for i in range(21)]})
check("C6 quá 20 video → từ chối", err and "20" in txt and not puts(), txt)
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "../../x", "publish_at": WHEN}]})
check("C7 id lạ (../) → từ chối, không gọi gì", err and "not a YouTube video id" in txt and not puts(), txt)
reset()
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "goodvideo01", "publish_at": "cancel"}]})
check("C8 «cancel» → publish_at rỗng, báo đã bỏ hẹn", not err and puts()[0][3] == {"publish_at": ""} and "cancelled" in txt, txt)
reset()
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "publicvid", "publish_at": WHEN},
                                                                  {"video_id": "goodvideo01", "publish_at": WHEN}]})
check("C9 một video hỏng → báo riêng, video kia vẫn đặt, isError", err and "1 of 2" in txt and "only a private video" in txt
      and '"scheduled"' in txt, txt)
reset()
ST["wrong"] = True
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "goodvideo01", "publish_at": WHEN}]})
check("C10 YouTube lưu giờ khác → FAILED, không báo «đã hẹn»", err and "0 of 1" in txt and "instead of" in txt, txt)
reset()
ST["old"] = True
err, txt = call("youtube_schedule", {"channel": "UCaaa", "items": [{"video_id": "goodvideo01", "publish_at": WHEN}]})
check("C11 Video Manager cũ → báo cập nhật, nói rõ chưa đặt gì", err and Y.MIN_VERSION in txt and "Nothing was scheduled" in txt, txt)
check("C12 «…Z» / phút lẻ: so giờ theo thời điểm, không theo chữ", Y._same_time("2099-12-01T12:45:00.000Z", UTC)
      and not Y._same_time("2099-12-01T13:45:00Z", UTC) and Y._same_time("", "") and not Y._same_time(None, UTC))

# ── D ──
reset()
err, txt = call("youtube_update", {"channel": "UCbbb", "video_id": "goodvideo01", "title": "New", "privacy": "public"})
check("D1 sửa tiêu đề + public bằng token kênh B", not err and puts()[0][2]["token_id"] == "tok-B"
      and puts()[0][3] == {"title": "New", "privacy": "public"} and "public" in txt, (txt, puts()))
for args, word in (({}, "Nothing to change"), ({"privacy": "secret"}, "privacy must"), ({"title": "x" * 101}, "1-100"),
                   ({"tags": "a,b"}, "list"), ({"description": "x" * 5001}, "5000")):
    reset()
    err, txt = call("youtube_update", {"channel": "UCaaa", "video_id": "goodvideo01", **args})
    check(f"D2 dữ liệu sai ({word}) → từ chối, không gọi", err and word in txt and not CALLS, txt)

# ── E ──
names = {t["name"] for t in CC.list_tools("write")}
ro = {t["name"] for t in CC.list_tools("read")}
four = {"youtube_channels", "youtube_videos", "youtube_schedule", "youtube_update"}
check("E1 tools/list đủ bốn; chỉ-đọc chỉ thấy hai công cụ đọc", four <= names and four & ro == {"youtube_channels", "youtube_videos"},
      (names & four, ro & four))
reset()
args = {"channel": "UCaaa", "items": [{"video_id": "goodvideo01", "publish_at": WHEN}]}
r = asyncio.run(CC.call("youtube_schedule", args, "read", False, app))
check("E2 kết nối chỉ-đọc không hẹn được", r["result"]["isError"] and "read-only" in r["result"]["content"][0]["text"] and not puts(), r)
r = asyncio.run(CC.call("youtube_schedule", args, "write", False, app))
check("E3 kết nối ghi: chạy luôn, không cần link duyệt", "needs_approval" not in r and not r["result"]["isError"] and len(puts()) == 1, r)
reset()
seen = []


async def no(name, summary, a, **k):
    seen.append(summary)
    return False, "declined", ""


err, txt = call("youtube_schedule", args, approve=no)
check("E4 Codex GPT: chủ từ chối thẻ duyệt → không đặt gì; thẻ ghi video + giờ", err and txt == "declined" and not puts()
      and "goodvideo01" in seen[0] and WHEN in seen[0], (txt, seen))
check("E5 Codex GPT trên máy cũng có bốn công cụ", four <= {t["name"] for t in T.list_tools()})

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
