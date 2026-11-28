"""Dọn ô review của Bảng việc cho task video (28/11/2026 — agent quản lý contabo báo: 92 task nằm review, phần lớn không
có gì để duyệt).

  1. resolve_publish      task ghi «Published» mà link không phải video (support.google.com/… của hộp thoại Studio):
                          tìm lại video trên kênh theo tiêu đề + ngày đăng — qua YouTube API (token của kênh, Video
                          Manager) rồi tới tìm kiếm công khai (yt-dlp, bắt buộc đúng tên / id kênh). Thấy ⇒ ghi
                          youtu.be/<id> vào checkpoint.published + meta.published_url (bulk accept-published nhận được);
                          không thấy ⇒ nhãn PUBLISH_UNVERIFIED. KHÔNG mở trình duyệt (RAM), không tải gì lên.
  2. unproductive_reason  lượt video kết thúc mà không ra sản phẩm (⚠ OFF-NICHE…, ⚠ DUPLICATE TOPIC, ⚠ TOPIC IN
                          COOLDOWN, «Nothing was rendered», bước đăng bị chặn mà không có file video) ⇒ hook on_result
                          của codex đưa task sang FAILED (không vào review); bulk_close_unproductive đóng task CŨ đang
                          nằm review. Task chỉ trả lời chữ mà là từ chối / xin bổ sung cũng được đóng ở đây.
  3. scan_duplicates      task video đang review cùng cụm chủ đề (niche_memory.same_cluster — cùng câu Kinh Thánh / cùng
                          chữ chính) với một task tốt hơn của cùng agent ⇒ nhãn «DUPLICATE_OF #n»; bulk đóng — mặc định
                          CHỈ bản trùng chưa có file video (include_rendered=true mới đóng cả bản đã dựng).

Đóng = huỷ (CANCELLED): không xoá gì, sổ sự kiện / checkpoint / file còn nguyên, Chạy lại vẫn được.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BoardTriage")

KINDS = ("content_video.auto", "content_video.render")
HOLD_HEADS = ("⚠ OFF-NICHE", "⚠ DUPLICATE TOPIC", "⚠ TOPIC IN COOLDOWN")
_NOTHING_RE = re.compile(r"\bNothing was rendered\b", re.I)
_DUP_OF_RE = re.compile(r"already made as task #(\d+)")
_YT_TITLE_RE = re.compile(r"^- \*\*Title on YouTube\*\*:\s*(.+?)\s*$", re.M)
_PUBLISHED_LINE_RE = re.compile(r"^- \*\*Published\*\*", re.M)
_GENERIC_TITLE = ("auto publish:", "auto video:", "auto publish ·", "auto video ·")
DATE_SLACK_DAYS = 3          # ngày đăng ghi trên task và ngày YouTube hiện lệch nhau tối đa chừng này (múi giờ, hẹn giờ)
SEARCH_RESULTS = 15
BULK_RESOLVE_MAX = 50


def _cm():
    from tubecli.extensions.codex.manager import codex_manager

    return codex_manager


def _M():
    from tubecli.extensions.codex import manager as M

    return M


def _err(status: int, code: str, message: str, **extra):
    from .publish_jobs import JobError

    return JobError(status, code, message, **extra)


# ── tiện ích ─────────────────────────────────────────────────────────────────
def _fold(text: Any) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).casefold()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


def _parse_ts(ts: Any) -> Optional[datetime.datetime]:
    if not ts:
        return None
    s = str(ts).strip()
    if re.fullmatch(r"\d{8}", s):                 # upload_date của yt-dlp: 20261107
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def _age_days(task: Dict[str, Any]) -> float:
    d = _parse_ts(task.get("finished_at") or task.get("updated_at") or task.get("created_at"))
    if d is None:
        return 0.0
    return (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds() / 86400.0


def _step(task: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next((s for s in (task.get("steps") or []) if isinstance(s, dict) and s.get("name") == name), {})


def kind_of(task: Dict[str, Any]) -> str:
    meta = task.get("meta") if isinstance(task.get("meta"), dict) else {}
    return str(meta.get("kind") or "") or str(_cm().kind_of(str(task.get("id") or "")) or "")


def video_path(task: Dict[str, Any], ck: Dict[str, Any]) -> str:
    from .publish_jobs import task_video_path

    return task_video_path(task, ck)


def has_video(task: Dict[str, Any], ck: Dict[str, Any]) -> bool:
    """Lượt này CÓ file video thật trên đĩa."""
    path = video_path(task, ck)
    return bool(path) and os.path.isfile(path)


# ── 2. không ra sản phẩm ─────────────────────────────────────────────────────
def unproductive_reason(task: Dict[str, Any], result: Optional[str] = None,
                        ck: Optional[Dict[str, Any]] = None) -> str:
    """Lý do (tiếng Anh, một dòng) khi lượt video KHÔNG ra sản phẩm, hay "". Có video / đã đăng thì không bao giờ."""
    text = str(task.get("result") if result is None else result or "")
    ck = _cm().checkpoint_of(str(task.get("id") or "")) if ck is None else ck
    if _cm().published_video(str(task.get("id") or "")) or has_video(task, ck):
        return ""
    head = text.strip().split("\n", 1)[0].strip().lstrip("#").strip()
    if head.startswith(HOLD_HEADS):
        return head[:300]
    if _NOTHING_RE.search(text):
        return "Nothing was rendered or published"
    pub = _step(task, "publish")
    if pub.get("status") == "error" and not ck.get("published"):
        return f"Publishing was blocked and there is no video file: {str(pub.get('message') or '')[:200]}".rstrip(": ")
    return ""


def duplicate_of(result: str) -> Optional[int]:
    m = _DUP_OF_RE.search(str(result or ""))
    return int(m.group(1)) if m else None


def result_hook(task: Dict[str, Any], result: str) -> Optional[Dict[str, Any]]:
    """codex on_result cho task video tự động: không ra sản phẩm ⇒ FAILED kèm lý do + nhãn (không vào review)."""
    reason = unproductive_reason(task, result)
    if not reason:
        return None
    M = _M()
    labels = [M.LABEL_UNPRODUCTIVE]
    dup = duplicate_of(result)
    if dup:
        labels.append(f"{M.LABEL_DUPLICATE} #{dup}")
        try:
            _cm().set_meta(str(task.get("id") or ""), {"duplicate_of": dup})
        except Exception:       # noqa: BLE001
            pass
    return {"reason": reason, "labels": labels}


def direct_reply_reason(task: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Task chung mà agent chỉ TRẢ LỜI CHỮ (bước «reason» = direct reply, không chạy skill / action) và câu trả lời là
    từ chối / xin bổ sung ⇒ (lý do, nhãn). Không thì ("", [])."""
    steps = [s for s in (task.get("steps") or []) if isinstance(s, dict)]
    names = {s.get("name") for s in steps}
    reason = _step(task, "reason")
    if not reason or "direct reply" not in str(reason.get("message") or "") or names & {"run_skill", "action"}:
        return "", []
    from tubecli.extensions.codex import executor as E

    reply, goal = str(task.get("result") or ""), str(task.get("goal") or "")
    why = E.refusal_reason(reply, goal)
    ask = E.needs_input_reason(reply, goal, refused=bool(why))
    if not why and not ask:
        return "", []
    M = _M()
    if ask:
        return f"The agent needs more from you: {ask}", [M.LABEL_NEEDS_INPUT]
    return f"The agent did not do the task: {why[:240]}", [M.LABEL_UNPRODUCTIVE]


def _review_tasks() -> List[Dict[str, Any]]:
    rows = _cm().list_tasks(status="review", limit=0)          # limit=0 = tất cả
    return sorted([dict(t) for t in rows or []], key=lambda t: int(t.get("seq") or 0))


def bulk_close_unproductive(older_than_days: float = 0, actor: str = "user", dry_run: bool = False) -> Dict[str, Any]:
    """Đóng mọi task đang REVIEW không ra sản phẩm (video lạc ngách / trùng / chưa dựng gì, hay agent chỉ từ chối bằng
    chữ) đã nằm đó hơn `older_than_days` ngày. dry_run ⇒ chỉ liệt kê."""
    try:
        days = float(older_than_days or 0)
    except (TypeError, ValueError):
        raise _err(400, "bad_days", "older_than_days must be a number")
    if not (0 <= days <= 3650):
        raise _err(400, "bad_days", "older_than_days must be between 0 and 3650")
    cm = _cm()
    hits: List[Dict[str, Any]] = []
    for t in _review_tasks():
        if _age_days(t) < days:
            continue
        tid = str(t.get("id") or "")
        kind = kind_of(t)
        labels: List[str] = []
        if kind in KINDS:
            reason = unproductive_reason(t)
            dup = duplicate_of(str(t.get("result") or "")) if reason else None
            labels = [_M().LABEL_UNPRODUCTIVE] + ([f"{_M().LABEL_DUPLICATE} #{dup}"] if dup else [])
        elif kind:
            continue                           # task kế hoạch / Drive… của pipeline: người duyệt quyết
        else:
            reason, labels = direct_reply_reason(t)
        if reason:
            hits.append({"id": tid, "seq": t.get("seq"), "title": t.get("title", ""), "reason": reason,
                         "labels": labels})
    done = hits if dry_run else cm.close_tasks(hits, actor, "Closed (no product)")
    return {"dry_run": bool(dry_run), "older_than_days": days, "matched": len(hits),
            "closed": 0 if dry_run else len(done), "tasks": done}


# ── 4. trùng chủ đề ──────────────────────────────────────────────────────────
def _topic_texts(t: Dict[str, Any], ck: Optional[Dict[str, Any]] = None) -> List[str]:
    out = []
    title = str(t.get("title") or "").strip()
    if title and not title.casefold().startswith(_GENERIC_TITLE):
        out.append(title)
    pub = (ck or {}).get("published") if isinstance((ck or {}).get("published"), dict) else {}
    if pub.get("title"):
        out.append(str(pub["title"]))
    return out


def _rank(info: Dict[str, Any]) -> int:
    """Càng lớn càng nên GIỮ: đã đăng > đã có video > còn lại."""
    return 2 if info["published"] else (1 if info["video"] else 0)


def scan_duplicates(within_days: float = 60) -> List[Dict[str, Any]]:
    """[{id, seq, title, duplicate_of, original_title, has_video, reason}] — task video đang REVIEW trùng chủ đề với một
    task khác (review / done) của CÙNG agent mà nên giữ hơn (đã đăng > có video > làm trước). Bản đã đăng không bao giờ
    bị coi là bản thừa."""
    from . import niche_memory as NM

    cm = _cm()
    pool = [dict(t) for t in (cm.list_tasks(status="review", limit=0) or [])
            + (cm.list_tasks(status="done", limit=0) or [])
            if kind_of(t) in KINDS and _age_days(t) <= max(1.0, float(within_days or 60))]
    info: Dict[str, Dict[str, Any]] = {}
    for t in pool:
        tid = str(t.get("id") or "")
        ck = cm.checkpoint_of(tid)
        info[tid] = {"task": t, "texts": _topic_texts(t, ck), "published": bool(cm.published_video(tid)),
                     "video": has_video(t, ck), "agent": str(t.get("assignee_id") or "")}
    out: List[Dict[str, Any]] = []
    for tid, me in info.items():
        t = me["task"]
        if t.get("status") != "review" or me["published"] or not me["texts"]:
            continue
        best = None
        for oid, other in info.items():
            if oid == tid or other["agent"] != me["agent"] or not other["texts"]:
                continue
            if not any(NM.same_cluster(a, b) for a in me["texts"] for b in other["texts"]):
                continue
            better = (_rank(other), -int(other["task"].get("seq") or 0)) > (_rank(me), -int(t.get("seq") or 0))
            if better and (best is None or (_rank(other), -int(other["task"].get("seq") or 0))
                           > (_rank(best), -int(best["task"].get("seq") or 0))):
                best = other
        if best is None:
            continue
        o = best["task"]
        out.append({"id": tid, "seq": t.get("seq"), "title": t.get("title", ""), "duplicate_of": o.get("seq"),
                    "original_title": o.get("title", ""), "original_status": "published" if best["published"]
                    else o.get("status"), "has_video": me["video"],
                    "reason": f"same topic as task #{o.get('seq')} «{str(o.get('title') or '')[:80]}»"})
    return sorted(out, key=lambda h: int(h.get("seq") or 0))


def bulk_close_duplicates(actor: str = "user", dry_run: bool = False, include_rendered: bool = False,
                          label_only: bool = False, within_days: float = 60) -> Dict[str, Any]:
    """Gắn nhãn «DUPLICATE_OF #n» cho mọi bản trùng đang review rồi đóng chúng. Mặc định KHÔNG đóng bản trùng đã có
    file video (chỉ gắn nhãn) — include_rendered=true mới đóng cả chúng. dry_run ⇒ chỉ liệt kê, không gắn nhãn."""
    cm, M = _cm(), _M()
    hits = scan_duplicates(within_days)
    if dry_run:
        return {"dry_run": True, "matched": len(hits), "closed": 0, "labelled": 0, "tasks": hits}
    for h in hits:
        cm.set_labels(h["id"], add=[f"{M.LABEL_DUPLICATE} #{h['duplicate_of']}"], remove_prefix=M.LABEL_DUPLICATE)
        cm.set_meta(h["id"], {"duplicate_of": h["duplicate_of"]})
    closable = [] if label_only else [h for h in hits if include_rendered or not h["has_video"]]
    closed = cm.close_tasks(closable, actor, "Closed as a duplicate")
    kept = [h for h in hits if h not in closed]
    return {"dry_run": False, "matched": len(hits), "labelled": len(hits), "closed": len(closed),
            "tasks": closed, "kept_open": kept}


# ── 1. tìm lại link video đã đăng ────────────────────────────────────────────
def _api_videos(channel_id: str, channel_name: str, token_id: str) -> Optional[List[Dict[str, Any]]]:
    """Video mới nhất của kênh qua YouTube API (token của chính kênh đó), hay None khi kênh không có token ở máy này."""
    from . import pipeline as P

    found = P._find_channel(name=channel_name, channel_id=channel_id, prefer_token=token_id) \
        if (channel_name or channel_id) else {}
    cid = str(found.get("id") or channel_id or "")
    tid = str(found.get("token_id") or token_id or "")
    token = P._vm_token(tid) if tid else ""
    if not cid or not token:
        return None
    vm = P._vm_module("providers/youtube/video_manager.py", "tubecli_vm_youtube_videos")
    if vm is None or not hasattr(vm, "list_videos"):
        return None
    res = vm.list_videos(cid, token, max_results=50)
    vids = (res.get("videos") if isinstance(res, dict) else res) or []
    rows = []
    for v in vids:
        d = v.to_dict() if hasattr(v, "to_dict") else (v if isinstance(v, dict) else {})
        vid = str(d.get("id") or d.get("video_id") or "")
        if vid:
            rows.append({"id": vid, "title": str(d.get("title") or ""), "published_at": d.get("published_at"),
                         "channel_id": cid, "channel": str(found.get("name") or channel_name or "")})
    return rows


def _public_search(query: str, n: int = SEARCH_RESULTS) -> List[Dict[str, Any]]:
    """Tìm công khai trên YouTube (yt-dlp, không tải gì): [{id, title, channel, channel_id, published_at}]."""
    query = " ".join(str(query or "").split())[:200]
    if not query:
        return []
    try:
        from tubecli.core import youtube_transcript as YT

        if not YT._ensure_ytdlp().get("ok"):
            return []
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
                "socket_timeout": 30, "noplaylist": True}
        opts.update(YT._ytdlp().js_runtime_opts())
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{n}:{query}", download=False) or {}
    except Exception as e:      # noqa: BLE001
        logger.info("[BoardTriage] YouTube search failed for %r: %s", query, e)
        return []
    out = []
    for e in info.get("entries") or []:
        e = e or {}
        if e.get("id"):
            out.append({"id": str(e["id"]), "title": str(e.get("title") or ""),
                        "channel": str(e.get("channel") or e.get("uploader") or ""),
                        "channel_id": str(e.get("channel_id") or ""),
                        "published_at": e.get("upload_date") or e.get("timestamp")})
    return out


# Test thay hai đường tra này bằng đồ giả (không gọi mạng).
API_VIDEOS = _api_videos
SEARCH = _public_search


def _same_title(a: str, b: str) -> bool:
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    short, long_ = sorted((fa, fb), key=len)
    return len(short) >= 20 and short in long_ and len(short) / len(long_) >= 0.6


def _when(row: Dict[str, Any]) -> Optional[datetime.datetime]:
    v = row.get("published_at")
    if isinstance(v, (int, float)):
        return datetime.datetime.fromtimestamp(float(v), datetime.timezone.utc)
    return _parse_ts(v)


def pick_video(rows: List[Dict[str, Any]], titles: List[str], published_at: Any = None, channel_name: str = "",
               channel_id: str = "", require_channel: bool = False) -> Optional[Dict[str, Any]]:
    """Video khớp tiêu đề (và đúng kênh khi require_channel, và ngày đăng ±DATE_SLACK_DAYS khi biết), hay None.
    Nhiều video khớp ⇒ lấy cái gần ngày đăng nhất; không biết ngày mà vẫn nhiều ⇒ None (không đoán)."""
    want_ch = _fold(channel_name)
    when = _parse_ts(published_at)
    hits = []
    for r in rows or []:
        if not any(_same_title(r.get("title"), t) for t in titles if t):
            continue
        if require_channel:
            ok_id = channel_id and r.get("channel_id") == channel_id
            ok_name = want_ch and _fold(r.get("channel")) == want_ch
            if not (ok_id or ok_name):
                continue
        rw = _when(r)
        if when and rw and abs((rw - when).total_seconds()) > DATE_SLACK_DAYS * 86400:
            continue
        hits.append((abs((rw - when).total_seconds()) if (when and rw) else None, r))
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0][1]
    dated = sorted((h for h in hits if h[0] is not None), key=lambda h: h[0])
    return dated[0][1] if dated else None


def _publish_facts(task: Dict[str, Any], ck: Dict[str, Any]) -> Dict[str, Any]:
    """Những gì task ghi về lần đăng: tiêu đề, kênh, token, thời điểm."""
    pub = ck.get("published") if isinstance(ck.get("published"), dict) else {}
    result = str(task.get("result") or "")
    titles = []
    for t in (pub.get("title"), *(m.group(1) for m in _YT_TITLE_RE.finditer(result)), task.get("title")):
        t = str(t or "").strip()
        if t and not t.casefold().startswith(_GENERIC_TITLE) and t not in titles:
            titles.append(t)
    agent = None
    try:
        from tubecli.core.agent import agent_manager

        agent = agent_manager.get_agent(str(task.get("assignee_id") or ""))
    except Exception:       # noqa: BLE001
        agent = None
    step = _step(task, "publish")
    return {
        "titles": titles,
        "channel_name": str(pub.get("channel_name") or getattr(agent, "publish_channel_name", "") or ""),
        "channel_id": str(pub.get("channel_id") or getattr(agent, "publish_channel_id", "") or ""),
        "token_id": str(getattr(agent, "publish_token_id", "") or ""),
        "published_at": pub.get("at") or step.get("ended_at") or task.get("finished_at"),
        "claimed": bool(pub) or bool(_PUBLISHED_LINE_RE.search(result)),
    }


def needs_resolve(task: Dict[str, Any]) -> bool:
    """Task video ghi đã đăng mà chưa có id video thật."""
    if kind_of(task) not in KINDS:
        return False
    tid = str(task.get("id") or "")
    cm = _cm()
    if cm.published_video(tid):
        return False
    return _publish_facts(task, cm.checkpoint_of(tid))["claimed"]


def resolve_publish(task_id: str, actor: str = "user", dry_run: bool = False) -> Dict[str, Any]:
    """Tìm lại video THẬT của task (xem đầu file). Trả {task, status: found|not_found|already, url?, how?, tried}."""
    from .publish_jobs import result_with_link, task_of_video

    cm, M = _cm(), _M()
    task = cm.get_task(str(task_id))
    if not task:
        raise _err(404, "task_not_found", f"Task not found: {task_id}")
    tid = str(task["id"])
    if kind_of(task) not in KINDS:
        raise _err(400, "not_a_rendered_video", "Only an Auto video / render task has a YouTube upload to look up.")
    have = cm.published_video(tid)
    if have:
        return {"task": task.get("seq"), "status": "already", "url": have["url"], "video_id": have["video_id"]}
    ck = cm.checkpoint_of(tid)
    facts = _publish_facts(task, ck)
    if not facts["claimed"]:
        raise _err(409, "not_published", "This task never reported a YouTube upload — nothing to look up.")
    if not facts["titles"]:
        raise _err(409, "no_title", "The task has no title to look the video up by.")
    tried, hit, how = [], None, ""
    try:
        rows = API_VIDEOS(facts["channel_id"], facts["channel_name"], facts["token_id"])
    except Exception as e:      # noqa: BLE001
        rows = None
        tried.append(f"api: {str(e)[:120]}")
    if rows is not None:
        tried.append(f"api: {len(rows)} newest video(s) of the channel")
        hit = pick_video(rows, facts["titles"], facts["published_at"])
        how = "YouTube API" if hit else ""
    if hit is None and (facts["channel_name"] or facts["channel_id"]):
        for title in facts["titles"][:2]:
            rows = SEARCH(title) or []
            tried.append(f"search «{title[:60]}»: {len(rows)} result(s)")
            hit = pick_video(rows, facts["titles"], facts["published_at"], facts["channel_name"],
                             facts["channel_id"], require_channel=True)
            if hit:
                how = "YouTube search"
                break
    elif hit is None:
        tried.append("search skipped: the task names no channel, so a match could be someone else's video")
    if hit is not None:
        other = task_of_video(hit["id"])
        if other and str(other.get("id")) != tid:
            tried.append(f"video {hit['id']} is already recorded on task #{other.get('seq')}")
            hit = None
    out = {"task": task.get("seq"), "titles": facts["titles"], "channel": facts["channel_name"] or facts["channel_id"],
           "tried": tried, "dry_run": bool(dry_run)}
    if hit is None:
        out["status"] = "not_found"
        if not dry_run:
            cm.set_labels(tid, add=[M.LABEL_PUBLISH_UNVERIFIED])
            cm.append_event(tid, "log", "⚠ Could not find the uploaded video on the channel (" + "; ".join(tried)[:600]
                            + ") — labelled PUBLISH_UNVERIFIED. Check YouTube Studio, then record the link with "
                            "PUT /api/v1/codex/tasks/{id}/published.", actor=str(actor or "user"))
        return out
    vid = hit["id"]
    url = f"https://youtu.be/{vid}"
    out.update(status="found", video_id=vid, url=url, how=how, found_title=hit.get("title"))
    if dry_run:
        return out
    pub = dict(ck.get("published") or {}) if isinstance(ck.get("published"), dict) else {}
    pub.update(video_id=vid, url=url, resolved_by=how, resolved_at=datetime.datetime.now().astimezone().isoformat())
    pub.setdefault("title", hit.get("title") or facts["titles"][0])
    if facts["channel_name"]:
        pub.setdefault("channel_name", facts["channel_name"])
    cm.append_event(tid, "log", "checkpoint", actor=str(actor or "user"), data={"checkpoint": {"published": pub}})
    cm.set_meta(tid, {"published_url": url})
    cm.set_labels(tid, remove=[M.LABEL_PUBLISH_UNVERIFIED])
    line = f"- **Published**: {url} (found on the channel by title via {how})"
    cm.set_result(tid, result_with_link(str(task.get("result") or ""), line), actor=str(actor or "user"),
                  note=f"Found the uploaded video: {url} ({how})")
    return out


# Dò hàng loạt chạy NỀN: mỗi task có thể mất vài giây (API / tìm kiếm), cloud chỉ chờ một lời gọi ~55 s.
_BULK: Dict[str, Any] = {"running": False}
_BULK_LOCK = threading.Lock()


def bulk_candidates() -> List[Dict[str, Any]]:
    return [t for t in _review_tasks() if needs_resolve(t)]


def bulk_resolve_status() -> Dict[str, Any]:
    with _BULK_LOCK:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _BULK.items()}


def start_bulk_resolve(actor: str = "user", dry_run: bool = False, limit: int = BULK_RESOLVE_MAX,
                       background: bool = True) -> Dict[str, Any]:
    """Dò mọi task đang review cần tìm lại link. background=False chạy luôn (test). Đang chạy thì trả tiến độ."""
    try:
        limit = max(1, min(BULK_RESOLVE_MAX, int(limit or BULK_RESOLVE_MAX)))
    except (TypeError, ValueError):
        limit = BULK_RESOLVE_MAX
    with _BULK_LOCK:
        if _BULK.get("running"):
            return {**{k: v for k, v in _BULK.items()}, "note": "already running"}
        todo = bulk_candidates()
        _BULK.clear()
        _BULK.update(running=True, dry_run=bool(dry_run), started_at=time.time(), total=min(len(todo), limit),
                     remaining_after=max(0, len(todo) - limit), found=[], not_found=[], errors=[])
        todo = todo[:limit]

    def run():
        try:
            for t in todo:
                try:
                    r = resolve_publish(str(t["id"]), actor=actor, dry_run=dry_run)
                except Exception as e:      # noqa: BLE001
                    with _BULK_LOCK:
                        _BULK["errors"].append({"task": t.get("seq"), "error": str(getattr(e, "message", e))[:200]})
                    continue
                row = {"task": r.get("task"), "title": t.get("title", ""), **({"url": r["url"], "how": r.get("how")}
                                                                              if r.get("url") else {})}
                with _BULK_LOCK:
                    _BULK["found" if r.get("status") in ("found", "already") else "not_found"].append(row)
        finally:
            with _BULK_LOCK:
                _BULK.update(running=False, finished_at=time.time())

    if background:
        threading.Thread(target=run, name="board-resolve-publish", daemon=True).start()
    else:
        run()
    return bulk_resolve_status()
