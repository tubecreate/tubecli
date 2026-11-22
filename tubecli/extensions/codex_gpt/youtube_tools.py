"""Công cụ YouTube cho MCP (Codex GPT + trình kết nối claude.ai) — user 22/11/2026: «thêm vào công cụ mcp luôn giúp tôi».

Đi qua extension Chợ Video Manager (vid_mn) bằng asgi_call, như tubecli_api. Khác tubecli_api ở ba chỗ:

  * Chọn theo KÊNH rồi khoá ĐÚNG token của kênh đó (token_id). Video Manager chỉ nhận `email` thì khi token của email ấy
    hỏng nó lùi sang token tài khoản KHÁC — sửa nhầm kênh. Email / token_id không bao giờ trả ra cho AI
    (/video_manager/accounts vẫn bị khoá SECRET_SEGMENTS).
  * Hẹn giờ cả lô: kiểm HẾT giờ trước, sai một dòng là không đặt dòng nào; chạy thì báo từng video.
  * Đối chiếu giờ YouTube trả về. Bản Video Manager cũ bỏ qua publish_at — báo cập nhật, không báo «đã hẹn».
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

API = "/api/v1/video_manager"
MIN_VERSION = "2026.11.22.170536"          # bản đầu: publish_at + từ chối hẹn video đang công khai
MAX_ITEMS = 20                             # mỗi video 2 lượt gọi YouTube; cloud chờ một công cụ tối đa 55 s
PARALLEL = 4
MAX_SCAN = 500
MAX_ROWS = 100
CACHE_S = 600
STATUSES = ("all", "scheduled", "private", "unlisted", "public")
PRIVACIES = ("private", "unlisted", "public")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")

_cache: Dict[str, Any] = {"at": 0.0, "rows": []}


def _T():
    from . import tools as T
    return T


def tokens() -> List[Dict[str, Any]]:
    """Token Google có quyền YouTube trong Auth Manager (tách ra để test thay bằng đồ giả)."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    return [t for t in auth_manager.list_tokens(provider="google")
            if t.get("token_id") and t.get("status") in ("active", "expired")
            and any("youtube" in str(s) for s in (t.get("scopes") or []))]


async def _api(ctx, method: str, path: str, query: Dict[str, Any], body: Any = None) -> Tuple[int, Dict[str, Any]]:
    T = _T()
    try:
        status, _ctype, data = await T.asgi_call(ctx["app"], method, API + path, query, body,
                                                 agent=ctx.get("agent") or T.AGENT_HEADER)
    except asyncio.TimeoutError:
        return 504, {"detail": "YouTube did not answer in time"}
    try:
        out = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        out = {}
    return status, out if isinstance(out, dict) else {}


def _error(status: int, out: Dict[str, Any]) -> str:
    detail = out.get("detail")
    detail = detail if isinstance(detail, str) else json.dumps(detail or out, ensure_ascii=False)
    return f"HTTP {status}: {re.sub(r'ya29[.][A-Za-z0-9._-]+', '***', detail)[:400]}"


def _need_extension() -> str:
    return ("Video Manager is not installed or enabled on this server. Install it with market_install (item 'vid_mn') — "
            "the owner approves it.")


def _need_update() -> str:
    return (f"The Video Manager on this server is too old to schedule videos (needs {MIN_VERSION} or newer). Update it "
            "with market_install (item 'vid_mn', update true) — the owner approves it. Nothing was scheduled.")


async def channels(ctx, fresh: bool = False) -> List[Dict[str, Any]]:
    """[{id, title, videos, subscribers, token_id, uploads}] mọi kênh của mọi token. Nhớ 10 phút (mỗi token 1 quota)."""
    if not fresh and _cache["rows"] and time.time() - _cache["at"] < CACHE_S:
        return _cache["rows"]
    T = _T()
    toks = await asyncio.to_thread(tokens)
    if not toks:
        raise T.ToolError("No YouTube account is authorized on this server. The owner adds one in Auth Manager › Google › "
                          "YouTube.")
    sem = asyncio.Semaphore(PARALLEL)

    async def one(t):
        async with sem:
            return t, await _api(ctx, "GET", "/channels", {"provider": "youtube", "token_id": t["token_id"]})

    rows, errors, seen = [], [], set()
    for t, (status, out) in await asyncio.gather(*[one(t) for t in toks]):
        if status == 404:
            raise T.ToolError(_need_extension())
        if status != 200:
            errors.append(_error(status, out))
            continue
        for c in out.get("channels") or []:
            if c.get("id") and c["id"] not in seen:
                seen.add(c["id"])
                rows.append({"id": c["id"], "title": c.get("title") or "", "videos": c.get("video_count"),
                             "subscribers": c.get("subscribers"), "token_id": t["token_id"],
                             "uploads": (c.get("extra") or {}).get("uploads_playlist") or ""})
    if not rows:
        raise T.ToolError("No YouTube channel could be read. " + ("; ".join(errors[:3]) or "The accounts have no channel."))
    _cache.update(at=time.time(), rows=rows)
    ctx["yt_errors"] = errors
    return rows


async def pick_channel(args, ctx) -> Dict[str, Any]:
    T = _T()
    want = T._str(args, "channel", True, 200)
    for fresh in (False, True):                 # không thấy trong sổ nhớ → hỏi lại một lần
        rows = await channels(ctx, fresh=fresh)
        hit = [r for r in rows if r["id"] == want] or [r for r in rows if r["title"].strip().lower() == want.lower()]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:
            raise T.ToolError(f"{len(hit)} channels are named '{want}' — pass the channel id: " + ", ".join(r["id"] for r in hit))
    raise T.ToolError(f"No channel '{want}' on this server. Channels: " + "; ".join(f"{r['title']} ({r['id']})" for r in rows))


def _video_id(v: Any) -> str:
    T = _T()
    v = str(v or "").strip()
    m = re.search(r"(?:youtu\.be/|/shorts/|[?&]v=)([A-Za-z0-9_-]{6,20})", v)
    v = m.group(1) if m else v
    if not VIDEO_ID_RE.match(v):
        raise T.ToolError(f"'{v[:60]}' is not a YouTube video id or link")
    return v


def parse_when(value: Any, now: datetime = None) -> str:
    """ISO 8601 CÓ múi giờ, ở tương lai → UTC «…Z». «cancel» → "" (bỏ hẹn)."""
    T = _T()
    text = str(value if value is not None else "").strip()
    if text.lower() == "cancel":
        return ""
    raw = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise T.ToolError(f"'{text[:60]}' is not an ISO 8601 time — use e.g. 2026-11-22T19:45:00+07:00") from None
    if dt.tzinfo is None:
        raise T.ToolError(f"'{text[:60]}' has no timezone — add one (e.g. +07:00, or Z for UTC). Ask the user if unsure.")
    if dt <= (now or datetime.now(timezone.utc)) + timedelta(minutes=1):
        raise T.ToolError(f"'{text[:60]}' is in the past or less than a minute away")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _items(args) -> List[Tuple[str, str, str]]:
    """[(video_id, giờ UTC | "" = bỏ hẹn, chữ người dùng gửi)] — sai MỘT dòng là từ chối cả lô, trước khi đổi gì."""
    T = _T()
    raw = args.get("items")
    if not isinstance(raw, list) or not raw:
        raise T.ToolError("'items' is required: [{\"video_id\": …, \"publish_at\": …}]")
    if len(raw) > MAX_ITEMS:
        raise T.ToolError(f"At most {MAX_ITEMS} videos per call — split the list")
    out, bad, seen = [], [], set()
    for n, it in enumerate(raw, 1):
        try:
            if not isinstance(it, dict):
                raise T.ToolError("must be an object with video_id and publish_at")
            vid = _video_id(it.get("video_id"))
            if vid in seen:
                raise T.ToolError(f"video {vid} appears twice")
            seen.add(vid)
            out.append((vid, parse_when(it.get("publish_at")), str(it.get("publish_at"))))
        except T.ToolError as e:
            bad.append(f"item {n}: {e}")
    if bad:
        raise T.ToolError("Nothing was scheduled. " + "; ".join(bad))
    return out


def schedule_prepare(args):
    _T()._str(args, "channel", True, 200)
    _items(args)


def schedule_summary(args) -> str:
    lines = [f"{v} → " + (f"public at {raw}" if when else "cancel the schedule (stays private)") for v, when, raw in _items(args)]
    return f"Schedule YouTube videos on {args.get('channel')}:\n" + "\n".join(lines)


async def t_channels(args, ctx):
    T = _T()
    rows = await channels(ctx, fresh=True)
    out = [{"channel_id": r["id"], "title": r["title"], "videos": r["videos"], "subscribers": r["subscribers"]} for r in rows]
    note = "".join(f"\nOne account could not be read: {e}" for e in ctx.get("yt_errors") or [])
    return T.text_result(f"{len(out)} YouTube channel(s). Pass the id or exact title as `channel`.\n" + T._dump(out) + note)


def _status_of(v: Dict[str, Any]) -> str:
    ex = v.get("extra") or {}
    return "scheduled" if ex.get("publish_at") else str(v.get("status") or "")


async def t_videos(args, ctx):
    T = _T()
    want = T._str(args, "status", False, 20) or "all"
    if want not in STATUSES:
        raise T.ToolError("status must be one of: " + ", ".join(STATUSES))
    scan = T._int(args, "scan", 50, 1, MAX_SCAN)
    ch = await pick_channel(args, ctx)
    page, read, rows, knows = T._str(args, "page_token", False, 200), 0, [], False
    while read < scan:
        status, out = await _api(ctx, "GET", "/videos", {
            "provider": "youtube", "channel_id": ch["id"], "token_id": ch["token_id"], "page_token": page or None,
            "max_results": min(50, scan - read), "uploads_playlist_id": ch["uploads"] or None})
        if status == 404:
            raise T.ToolError(_need_extension())
        if status != 200:
            raise T.ToolError(_error(status, out))
        vids = out.get("videos") or []
        read += len(vids)
        for v in vids:
            knows = knows or "publish_at" in (v.get("extra") or {})
            st = _status_of(v)
            if want in ("all", st):
                rows.append({"video_id": v.get("id"), "title": str(v.get("title") or "")[:120], "status": st,
                             **({"publish_at": v["extra"]["publish_at"]} if st == "scheduled" else {}),
                             "uploaded_at": v.get("published_at"), "views": v.get("views")})
        page = out.get("next_page_token") or ""
        if not page or not vids:
            break
    if want in ("scheduled", "private") and read and not knows:      # bản cũ: private và scheduled lẫn vào nhau
        raise T.ToolError(_need_update().replace(" Nothing was scheduled.", ""))
    extra = f" Showing {MAX_ROWS}; narrow with status." if len(rows) > MAX_ROWS else ""
    more = f"\nOlder videos remain — next page_token: {page}" if page else ""
    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows[:MAX_ROWS])
    return T.text_result(f"{ch['title']} ({ch['id']}): {len(rows)}{'' if want == 'all' else ' ' + want} video(s) among the "
                         f"{read} newest read. Times are UTC.{extra}\n{lines}{more}")


async def t_schedule(args, ctx):
    T = _T()
    items = _items(args)
    ch = await pick_channel(args, ctx)
    sem = asyncio.Semaphore(PARALLEL)

    async def one(vid, when):
        async with sem:
            # CHỈ publish_at, không kèm privacy: bản cũ bỏ qua publish_at mà thấy privacy=public là đăng NGAY.
            return await _api(ctx, "PUT", f"/videos/{vid}", {"provider": "youtube", "token_id": ch["token_id"]},
                              {"publish_at": when})

    res = await asyncio.gather(*[one(v, w) for v, w, _ in items])
    rows, ok, old = [], 0, 0
    for (vid, when, raw), (status, out) in zip(items, res):
        got = out.get("publish_at")
        detail = str(out.get("detail") or "")
        if status == 404 and detail == "Not Found":
            raise T.ToolError(_need_extension())
        if "No fields to update" in detail or (status == 200 and got is None):
            old += 1
            rows.append({"video_id": vid, "result": "NOT scheduled", "error": "Video Manager is too old"})
        elif status != 200:
            rows.append({"video_id": vid, "result": "FAILED", "error": _error(status, out)})
        elif _same_time(got, when):
            ok += 1
            rows.append({"video_id": vid, "result": "scheduled", "publish_at_utc": got, "asked": raw} if when
                        else {"video_id": vid, "result": "schedule cancelled", "privacy": out.get("privacy")})
        else:
            rows.append({"video_id": vid, "result": "FAILED", "error": f"YouTube saved '{got}' instead of '{when}' — check YouTube Studio"})
    if old == len(items):
        raise T.ToolError(_need_update())
    head = (f"{ok} of {len(items)} done on {ch['title']}. YouTube publishes scheduled videos by itself at that time — "
            "this server does not have to be online.")
    return T.text_result(head + "\n" + T._dump(rows), error=ok < len(items))


def _same_time(a: Any, b: str) -> bool:
    if not a or not b:
        return not a and not b
    try:
        pa, pb = (datetime.fromisoformat(str(x).replace("Z", "+00:00")) for x in (a, b))
        return abs((pa - pb).total_seconds()) < 60
    except (ValueError, TypeError):
        return False


FIELDS = ("title", "description", "category_id", "privacy")


def _update_body(args) -> Dict[str, Any]:
    T = _T()
    body = {k: str(args[k]) for k in FIELDS if args.get(k) is not None}
    if args.get("tags") is not None:
        if not isinstance(args["tags"], list):
            raise T.ToolError("tags must be a list of strings")
        body["tags"] = [str(t)[:100] for t in args["tags"]][:60]
    if not body:
        raise T.ToolError("Nothing to change — pass title, description, tags, category_id or privacy")
    if "title" in body and not 1 <= len(body["title"].strip()) <= 100:
        raise T.ToolError("title must be 1-100 characters")
    if "description" in body and len(body["description"]) > 5000:
        raise T.ToolError("description must be at most 5000 characters")
    if "privacy" in body and body["privacy"] not in PRIVACIES:
        raise T.ToolError("privacy must be private, unlisted or public")
    return body


def update_prepare(args):
    _T()._str(args, "channel", True, 200)
    _video_id(args.get("video_id"))
    _update_body(args)


def update_summary(args) -> str:
    return (f"Change YouTube video {args.get('video_id')} on {args.get('channel')}:\n"
            + json.dumps(_update_body(args), ensure_ascii=False, indent=1)[:1500])


async def t_update(args, ctx):
    T = _T()
    vid, body = _video_id(args.get("video_id")), _update_body(args)
    ch = await pick_channel(args, ctx)
    status, out = await _api(ctx, "PUT", f"/videos/{vid}", {"provider": "youtube", "token_id": ch["token_id"]}, body)
    if status == 404 and out.get("detail") == "Not Found":
        raise T.ToolError(_need_extension())
    if status != 200:
        raise T.ToolError(_error(status, out))
    return T.text_result(f"Video {vid} on {ch['title']} updated: {', '.join(body)}."
                         + (f" Privacy now: {out['privacy']}." if out.get("privacy") else ""))


def build(Tool) -> list:
    S = {"type": "string"}
    CH = {**S, "description": "channel id or exact title from youtube_channels"}
    VID = {**S, "description": "YouTube video id or link"}
    return [
        Tool("youtube_channels", "YouTube channels this server can manage through its authorized Google accounts (Auth "
             "Manager + Video Manager): channel id, title, number of videos. Call it first; the other youtube_* tools "
             "take the channel.", {}, [], t_channels),
        Tool("youtube_videos", "Videos of one channel, newest first: id, title, status (scheduled, private, unlisted, "
             "public…), scheduled time (UTC), upload time, views.",
             {"channel": CH, "status": {"type": "string", "enum": list(STATUSES), "description": "default all; scheduled = "
                                        "private with a publish time set"},
              "scan": {"type": "integer", "description": f"how many of the newest videos to read, 1-{MAX_SCAN}, default 50"},
              "page_token": {**S, "description": "continue from a previous call"}}, ["channel"], t_videos),
        Tool("youtube_schedule", "Schedule PRIVATE videos to go public at a set time, or cancel a schedule. YouTube does "
             f"the publishing itself, so this server may be offline then. Up to {MAX_ITEMS} videos per call; every time "
             "is checked first and one wrong item refuses the whole call. A public or unlisted video is refused "
             "(scheduling would take it offline). To publish right now use youtube_update with privacy public.",
             {"channel": CH,
              "items": {"type": "array", "description": f"1-{MAX_ITEMS} videos", "items": {
                  "type": "object", "required": ["video_id", "publish_at"], "additionalProperties": False, "properties": {
                      "video_id": VID,
                      "publish_at": {**S, "description": "ISO 8601 time WITH a timezone, e.g. 2026-11-22T19:45:00+07:00 "
                                                         "(never guess the timezone — ask), or 'cancel'"}}}}},
             ["channel", "items"], t_schedule, write=True, summary=schedule_summary, prepare=schedule_prepare),
        Tool("youtube_update", "Change a video's title, description, tags, category or privacy (public = publish now). "
             "Only the fields you pass change. For a publish time use youtube_schedule.",
             {"channel": CH, "video_id": VID, "title": {**S, "description": "1-100 characters"},
              "description": {**S, "description": "up to 5000 characters"},
              "tags": {"type": "array", "items": S, "description": "replaces all tags"},
              "category_id": {**S, "description": "YouTube category id, e.g. 27 = Education"},
              "privacy": {"type": "string", "enum": list(PRIVACIES)}},
             ["channel", "video_id"], t_update, write=True, summary=update_summary, prepare=update_prepare),
    ]
