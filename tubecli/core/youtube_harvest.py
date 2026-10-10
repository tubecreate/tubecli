"""Phụ đề YouTube vào KHO THU THẬP sau mỗi lượt chạy của agent (user 10/10/2026).

«Agent hằng ngày đi thu thập dữ liệu từ web, YouTube (tự lấy sub) theo từ khoá tự sinh … khi thu thập đủ dữ liệu thì
tự động tạo video». Trước đây lượt chạy bằng kịch bản (mặc định) bỏ qua hẳn youtube.com (open.js harvestIfContentPage,
extract_content.js SKIP_DOMAINS): agent «xem video» mà kho không có gì; phụ đề chỉ được lấy lúc LÀM video, qua extension
web_crawler không cài sẵn, tối đa 5 cái và không lưu lại. Nay, khi lượt chạy khép sổ (process_manager._record_run_end,
TRƯỚC khi hỏi chuyện tự tạo video để phụ đề được tính vào ngưỡng «đủ bài mới»):

  1. video agent THẬT SỰ đã mở trong lượt — open.js ghi lượt ghé trang /watch, /shorts vào history.json (có agentId);
  2. thiếu thì tìm đúng câu tìm kiếm của lượt đó trên YouTube (yt-dlp «ytsearch») lấy vài video đầu, bỏ video quá ngắn;
  3. lấy phụ đề (core/youtube_transcript.fetch_transcript, ưu tiên ngôn ngữ của agent) rồi ghi articles.json +
     history.json của hồ sơ Y NHƯ extract_content.js (history có agentId; articles nối qua url) ⇒ scraped_store thấy
     nó là một «bài có nội dung» của agent.

Số video mỗi lượt = agent.youtube_subs_per_run (0 = tắt). Best-effort tuyệt đối: chạy trong luồng theo dõi tiến trình,
không có ai bắt lỗi hộ, nên KHÔNG BAO GIỜ ném — trả một câu tóm tắt để ghi log.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("YouTubeHarvest")

# Lượt kiểm / trả lời email không có câu tìm kiếm chủ đề nào — không đi tìm video cho chúng.
SKIP_BEHAVIORS = {"checkEmails", "replyEmail", "sendReport"}
OK_OUTCOMES = {"completed", "partial", "timeout_killed"}
MIN_WORDS = 80                 # ít hơn: phụ đề rác (nhạc, «[Music]») — không đáng là một bài
MIN_SECONDS, MAX_SECONDS = 90, 3 * 3600
ARTICLES_CAP, HISTORY_CAP = 100, 500          # y như extract_content.js / session_manager.js
SOURCE = "youtube_transcript"
_LOCK = threading.Lock()


def _aware(stamp: Any) -> Optional[datetime]:
    """ISO → datetime có múi giờ. run_log ghi giờ ĐỊA PHƯƠNG không múi; history.json ghi UTC «Z»."""
    s = str(stamp or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def _launch(run_id: str, agent_id: str) -> Dict[str, Any]:
    """Bản ghi lượt chạy trong run_log: {ts, launch:{profile, behavior, query, …}}; {} khi không tra được."""
    try:
        from tubecli.core import run_log

        for run in run_log.list_for_agent(agent_id, days=2, limit=500):
            if run.get("run_id") == run_id:
                return run
    except Exception as e:      # noqa: BLE001
        logger.debug(f"run_log lookup failed: {e}")
    return {}


def _vid(url: str) -> str:
    from tubecli.core.youtube_transcript import youtube_ids

    ids = youtube_ids(str(url or ""))
    return ids[0] if ids else ""


def search_videos(query: str, n: int, timeout: int = 45) -> List[Dict[str, Any]]:
    """Vài video đầu khi tìm `query` trên YouTube (yt-dlp, không tải gì): [{id, url, title, duration}]. [] khi hỏng."""
    query = " ".join(str(query or "").split())[:200]
    if not query or n <= 0:
        return []
    try:
        from tubecli.core import youtube_transcript as YT

        if not YT._ensure_ytdlp().get("ok"):
            return []
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
                "socket_timeout": timeout, "noplaylist": True}
        opts.update(YT._ytdlp().js_runtime_opts())       # cùng runtime JS như lượt lấy phụ đề (thử thách của YouTube)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max(3, n * 3)}:{query}", download=False) or {}
    except Exception as e:      # noqa: BLE001
        logger.info(f"YouTube search failed for {query!r}: {e}")
        return []
    out = []
    for e in info.get("entries") or []:
        vid = str((e or {}).get("id") or "")
        dur = (e or {}).get("duration")
        if not vid or (dur and not (MIN_SECONDS <= float(dur) <= MAX_SECONDS)):
            continue          # bỏ shorts / livestream dài: phụ đề ngắn ngủn hoặc khổng lồ
        out.append({"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": str(e.get("title") or ""),
                    "duration": dur})
    return out


def _paths(profile: str):
    from tubecli.core import scraped_store

    base = scraped_store.data_root() / profile
    return base / "articles.json", base / "history.json"


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except Exception:       # noqa: BLE001 — chưa có / hỏng: bắt đầu từ rỗng như bản JS
        return default


def _write(path, data) -> None:
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def save_transcript(profile: str, agent, res: Dict[str, Any], url: str) -> bool:
    """Ghi MỘT phụ đề vào kho của hồ sơ (articles + history). `url` = đúng url của lượt ghé (nếu có) để hai file nối
    được với nhau qua url như scraped_store làm. False khi video đã có bài."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    limit = max(2000, int(getattr(agent, "scraper_text_limit", 10000) or 10000))
    text = str(res.get("text") or "")[:limit]
    channel = str(res.get("channel") or "")
    art_p, hist_p = _paths(profile)
    vid = str(res.get("id") or _vid(url))
    with _LOCK:
        arts = _read(art_p, [])
        if any(_vid(a.get("url")) == vid for a in arts if isinstance(a, dict)):
            return False
        arts.append({"title": str(res.get("title") or ""), "url": url,
                     "description": f"YouTube subtitles ({res.get('language') or '?'}, {res.get('kind') or 'auto'}) · "
                                    f"{channel}".strip(" ·"),
                     "author": channel, "publishedDate": "", "content": text, "images": [], "imageCount": 0,
                     "scrapedAt": now, "source": SOURCE})
        _write(art_p, arts[-ARTICLES_CAP:])
        hist = _read(hist_p, {})
        rows = hist.get("scrapedArticles") if isinstance(hist.get("scrapedArticles"), list) else []
        row = next((r for r in rows if isinstance(r, dict) and r.get("url") == url), None)
        if row is None:
            row = {"title": str(res.get("title") or ""), "url": url, "ip": "", "imageCount": 0}
            rows.append(row)
        row.update({"author": channel, "contentLength": len(text), "scrapedAt": now, "isScraped": True,
                    "agentId": str(agent.id), "agentName": str(getattr(agent, "name", "") or ""), "source": SOURCE})
        hist["scrapedArticles"] = rows[-HISTORY_CAP:]
        _write(hist_p, hist)
    return True


def harvest_after_run(agent_id: str, run_id: str, profile: str = "", outcome: str = "") -> str:
    """Lấy phụ đề YouTube của lượt chạy vừa xong vào kho. Trả câu tóm tắt; không bao giờ ném."""
    try:
        return _harvest(agent_id, run_id, profile, outcome)
    except Exception as e:      # noqa: BLE001
        logger.warning(f"YouTube harvest failed for {agent_id}/{run_id}: {e}")
        return f"error: {e}"


def _harvest(agent_id: str, run_id: str, profile: str, outcome: str) -> str:
    if outcome and outcome not in OK_OUTCOMES:
        return f"skip: outcome {outcome}"
    from tubecli.core.agent import agent_manager
    from tubecli.core.youtube_transcript import fetch_transcript

    agent = agent_manager.get(str(agent_id or ""))
    if agent is None:
        return "skip: no agent"
    if not getattr(agent, "enable_scraping", False):
        return "skip: data collection off"
    n = int(getattr(agent, "youtube_subs_per_run", 2) or 0)
    if n <= 0:
        return "skip: youtube_subs_per_run = 0"
    run = _launch(run_id, str(agent.id))
    launch = run.get("launch") or {}
    behavior = str(launch.get("behavior") or "")
    if behavior in SKIP_BEHAVIORS:
        return f"skip: behaviour {behavior}"
    profile = str(profile or launch.get("profile") or "")
    if not profile:
        return "skip: no profile"
    since = _aware(run.get("ts") or launch.get("ts"))
    art_p, hist_p = _paths(profile)
    have = {_vid(a.get("url")) for a in _read(art_p, []) if isinstance(a, dict)}
    picks: List[tuple] = []           # (video id, url ghi kho, nguồn)
    # 1) video agent đã mở trong lượt này
    for r in _read(hist_p, {}).get("scrapedArticles") or []:
        if not isinstance(r, dict) or str(r.get("agentId") or "") != str(agent.id):
            continue
        vid = _vid(r.get("url"))
        at = _aware(r.get("scrapedAt"))
        if vid and vid not in have and (since is None or (at and at >= since)) and all(p[0] != vid for p in picks):
            picks.append((vid, str(r.get("url")), "watched"))
    # 2) thiếu thì tìm theo câu tìm kiếm của lượt
    query = str(launch.get("query") or "")
    if len(picks) < n and query:
        for v in search_videos(query, n - len(picks)):
            if v["id"] not in have and all(p[0] != v["id"] for p in picks):
                picks.append((v["id"], v["url"], "search"))
    if not picks:
        return "nothing to fetch" + (f" (query {query!r})" if query else " (no query recorded)")
    saved, tried, notes = [], 0, []
    for vid, url, src in picks:
        if len(saved) >= n or tried >= n * 3:
            break
        tried += 1
        # Phụ đề theo NGÔN NGỮ GỐC của video (user 10/10/2026: «không cần, cứ lấy ngôn ngữ gốc video gom nội dung lại
        # rồi AI content viết lại») — kịch bản viết bằng ngôn ngữ của agent/mẫu ở bước làm video, không phải ở đây.
        res = fetch_transcript(url, prefer_lang="", timeout=60)
        if not res.get("ok"):
            notes.append(f"{vid}: {str(res.get('message') or '')[:60]}")
            continue
        if int(res.get("words") or len(str(res.get("text") or "").split())) < MIN_WORDS:
            notes.append(f"{vid}: too short")
            continue
        if save_transcript(profile, agent, res, url):
            saved.append(f"{src}:{vid}")
    msg = f"saved {len(saved)}/{n} transcript(s) to {profile}"
    if saved:
        msg += " — " + ", ".join(saved)
    if notes:
        msg += " · skipped " + "; ".join(notes[:3])
    return msg
