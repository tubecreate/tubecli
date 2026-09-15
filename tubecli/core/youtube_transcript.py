"""Phụ đề YouTube làm nguyên liệu cho kịch bản (15/9/2026).

User: "trong Codex tôi không nhập nội dung gốc, tôi muốn tham khảo subtitle của kênh YouTube" — dán
link vào ô "Video content" từng bị coi là 43 ký tự nội dung (1 chữ → kịch bản 120 chữ bịa từ cái
link). Mô-đun này:

  * youtube_ids(text) / link_only(text)  nhận ra nội dung CHỈ là link YouTube (vài chữ kèm theo được),
                                          còn bài viết có lẫn link thì không đụng tới
  * fetch_transcript(link)               lấy phụ đề bằng yt-dlp: phụ đề tải lên theo ngôn ngữ gốc trước,
                                          rồi phụ đề tự động gốc ("<lang>-orig"), json3 rồi vtt
  * public_info(result)                  bản không có văn bản cho route thăm dò của form Codex

Kết quả nhớ trong tiến trình 1 giờ theo id video: form thăm dò xong, lượt chạy dùng lại.
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("tubecli.youtube_transcript")

WORDS_PER_MINUTE = 150            # PHẢI khớp content_video/pipeline.py WORDS_PER_MINUTE
LINK_EXTRA_WORDS = 12             # "link + vài chữ ghi chú" vẫn là link; dài hơn là bài viết có lẫn link
_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s#]*?&)?v=|shorts/|live/|embed/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_RE = re.compile(r"https?://\S+")
_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_RE = re.compile(r"\[(?:[^\]\s]{1,20}(?:\s[^\]\s]{1,20}){0,2})\]")    # [Música], [Aplausos], [Music]
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_THAI_RE = re.compile(r"[฀-๿]")
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 3600
_LOCK = threading.Lock()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"


# ── nhận diện link ────────────────────────────────────────────────────────────

def youtube_ids(text: str) -> List[str]:
    """Id video (11 ký tự) theo thứ tự xuất hiện, không trùng."""
    out: List[str] = []
    for m in _ID_RE.finditer(str(text or "")):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def link_only(text: str, max_extra_words: int = LINK_EXTRA_WORDS) -> List[str]:
    """Id video nếu nội dung CHỈ là link YouTube (cho phép vài chữ kèm theo); [] nếu là bài viết.

    Bài dán tay có trích một link YouTube ở giữa vẫn là bài dán tay — lối cũ giữ nguyên.
    """
    ids = youtube_ids(text)
    if not ids:
        return []
    rest = _URL_RE.sub(" ", str(text or ""))
    words = [w for w in rest.split() if any(ch.isalnum() for ch in w)]
    return ids if len(words) <= max_extra_words else []


def count_words(text: str) -> int:
    """Số chữ đọc thành tiếng — y hệt content_words() của pipeline (Hán/kana ~2 ký tự, Thái ~5)."""
    text = str(text or "")
    cjk = len(_CJK_RE.findall(text))
    thai = len(_THAI_RE.findall(text))
    rest = _THAI_RE.sub(" ", _CJK_RE.sub(" ", text))
    return sum(1 for w in rest.split() if any(ch.isalnum() for ch in w)) + (cjk + 1) // 2 + (thai + 2) // 5


# ── chọn và đọc track phụ đề ──────────────────────────────────────────────────

_FORMATS = ("json3", "vtt")


def _base(code: str) -> str:
    return str(code or "").split("-")[0].lower()


def _playable(entries) -> Optional[Dict[str, Any]]:
    by_ext = {e.get("ext"): e for e in (entries or []) if isinstance(e, dict) and e.get("url")}
    for ext in _FORMATS:
        if ext in by_ext:
            return by_ext[ext]
    return None


def pick_track(info: Dict[str, Any], prefer_lang: str = "") -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """(mã ngôn ngữ, "manual"|"auto", mục có url+ext) — track đáng tin nhất, hay None.

    Thứ tự: phụ đề TẢI LÊN theo ngôn ngữ gốc của video → tải lên theo ngôn ngữ muốn → phụ đề tự
    động GỐC ("<lang>-orig", do chính giọng nói nhận ra) → tự động theo ngôn ngữ gốc → tải lên bất kỳ.
    Phụ đề tự động dịch sang ngôn ngữ khác đứng cuối: đó là máy dịch của máy dịch.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    orig = _base(info.get("language") or "")
    want = _base(prefer_lang)

    def find(pool, pred):
        for code, entries in pool.items():
            if code == "live_chat" or not pred(code):
                continue
            e = _playable(entries)
            if e:
                return code, e
        return None

    steps = [
        (manual, "manual", lambda c: orig and _base(c) == orig),
        (manual, "manual", lambda c: want and _base(c) == want),
        (auto, "auto", lambda c: c.endswith("-orig")),
        (auto, "auto", lambda c: orig and c == orig),
        (manual, "manual", lambda c: True),
        (auto, "auto", lambda c: orig and _base(c) == orig),
        (auto, "auto", lambda c: want and _base(c) == want),
    ]
    for pool, kind, pred in steps:
        got = find(pool, pred)
        if got:
            return got[0], kind, got[1]
    return None


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_json3(data: Dict[str, Any]) -> str:
    """Văn bản từ phụ đề json3. Đoạn "\\n" giữa hai dòng là CHỖ NGẮT CHỮ — ghép thẳng thì
    "casi\\nsin" thành "casisin" (đo thật 15/9/2026)."""
    parts: List[str] = []
    for ev in (data or {}).get("events") or []:
        for seg in ev.get("segs") or []:
            t = seg.get("utf8", "")
            parts.append(" " if t == "\n" else t)
        parts.append(" ")
    return _clean("".join(parts))


def parse_vtt(text: str) -> str:
    """Văn bản từ WebVTT. Phụ đề tự động "cuộn" — mỗi khối lặp lại dòng trước — nên bỏ dòng trùng liền kề."""
    out: List[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if (not line or line == "WEBVTT" or "-->" in line or line.isdigit()
                or line.startswith(("Kind:", "Language:", "NOTE", "STYLE"))):
            continue
        line = _TAG_RE.sub("", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return _clean(" ".join(out))


# ── lấy phụ đề ────────────────────────────────────────────────────────────────

def _cookie_file() -> Optional[str]:
    """Cookie YouTube đã lưu ở Video Downloader (nếu có) — máy chủ IP trung tâm dữ liệu hay bị đòi đăng nhập."""
    try:
        from tubecli.extensions.video_downloader.routes import _get_cookie_file
        return _get_cookie_file("https://www.youtube.com/") or None
    except Exception:      # noqa: BLE001
        return None


class _YdlLogger:
    """yt-dlp in lỗi thẳng ra stderr kể cả khi quiet=True — gom về logger của TubeCLI (người gọi đã ghi cảnh báo)."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        logger.debug("yt-dlp: %s", msg)

    def error(self, msg):
        logger.debug("yt-dlp: %s", msg)


def _ydl_extract(url: str, timeout: int, cookiefile: Optional[str] = None, proxy: Optional[str] = None,
                 browser: str = "") -> Dict[str, Any]:
    import yt_dlp  # noqa: F401 — ImportError được người gọi đổi thành câu chỉ đường
    opts = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True,
            "socket_timeout": max(5, min(int(timeout), 30)), "logger": _YdlLogger()}
    # Cookie tài khoản → YouTube đòi giải thử thách JS: thiếu runtime là "The page needs to be reloaded" (đo 15/9/2026).
    opts.update(_ytdlp().js_runtime_opts())
    # Cookie chỉ gắn khi người gọi đưa — tức là lượt thử SAU khi YouTube đòi đăng nhập (_extract_with_cookies).
    if cookiefile:
        opts["cookiefile"] = cookiefile
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    if proxy:
        opts["proxy"] = proxy
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _http_get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _explain(msg: str) -> str:
    low = (msg or "").lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return ("YouTube asked this server to sign in (it treats the server's IP as a bot). Add YouTube cookies "
                "in Video Downloader → Settings, or paste the subtitles as text.")
    if "private video" in low:
        return "The video is private."
    if "unavailable" in low or "removed" in low or "does not exist" in low:
        return "The video is unavailable or was removed."
    if "age" in low and ("restrict" in low or "confirm your age" in low):
        return "The video is age-restricted; add YouTube cookies in Video Downloader → Settings."
    first = (msg or "").strip().splitlines()[0] if (msg or "").strip() else "unknown error"
    return re.sub(r"^ERROR:\s*", "", first)[:240]


def _ytdlp():
    from tubecli.core import ytdlp_manager
    return ytdlp_manager


def _ensure_ytdlp(progress=None, force: bool = False) -> Dict[str, Any]:
    """Thiếu yt-dlp thì cài, cũ thì cập nhật (core/ytdlp_manager.py). Lỗi bất ngờ của bước này không chặn lượt tải."""
    try:
        return _ytdlp().ensure(force_check=force, progress=progress)
    except Exception as e:      # noqa: BLE001
        logger.warning("yt-dlp check failed: %s", e)
        return {"ok": True, "action": "none", "message": str(e)}


def _short(err) -> str:
    first = str(err or "").strip().splitlines()[0] if str(err or "").strip() else "unknown error"
    return re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?([A-Za-z0-9_-]{11}:\s*)?", "", first)[:160]


def _challenge_hint(log: List[str]) -> str:
    """Có cookie mà YouTube trả "The page needs to be reloaded" / "challenge" = yt-dlp không giải được thử thách JS
    (đo 15/9/2026: thiếu yt-dlp-ejs + JS runtime thì cookie nào cũng hỏng kiểu này)."""
    text = " ".join(log).lower()
    if "needs to be reloaded" not in text and "challenge" not in text:
        return ""
    missing: List[str] = []
    try:
        ym = _ytdlp()
        if not ym.ejs_available():
            missing.append("the YouTube challenge solver (yt-dlp-ejs)")
        if not ym.js_runtimes():
            notes = ym.js_runtime_notes()
            missing.append("a JavaScript runtime yt-dlp accepts"
                           + (f" ({'; '.join(notes)})" if notes else " (deno 2.3+, node 22+ or bun 1.2.11+)"))
    except Exception:      # noqa: BLE001
        pass
    if missing:
        return (f"yt-dlp could not solve YouTube's JavaScript challenge: this server is missing {' and '.join(missing)} "
                "— open Video Downloader and press «Install deno» or «Check Update» (it installs what is missing).")
    return "yt-dlp could not solve YouTube's JavaScript challenge — update yt-dlp in Video Downloader."


def _extract_with_cookies(url: str, vid: str, timeout: int,
                          progress=None) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """(info, lỗi, nguồn cookie). KHÔNG cookie trước; chỉ khi YouTube đòi đăng nhập mới thử cookie, lần lượt:
    cookie dán tay ở Video Downloader → hồ sơ browser TubeCLI ĐANG MỞ (CDP) → cookie ĐÃ LƯU của hồ sơ đang tắt
    (1–2 s, không mở browser) → mở ẨN hồ sơ đó cho Google làm mới cookie → trình duyệt cài trên máy.

    Mỗi lượt thử kèm lỗi THẬT của yt-dlp đi lên Activity và vào câu báo lỗi — user 15/9/2026: "thử tải chưa mà báo
    yêu cầu cookies?" (câu cũ chỉ nói chung chung, lỗi thật nằm trong log máy chủ)."""
    from tubecli.core import youtube_cookies as yc

    say = progress or (lambda msg: None)
    try:
        return _ydl_extract(url, timeout), "", ""
    except ImportError:
        raise
    except Exception as e:      # noqa: BLE001
        first = str(e)
    logger.warning("youtube extract %s: %s", vid, _short(first))
    if _ytdlp().looks_outdated(first):
        # YouTube đổi trang → yt-dlp cũ "Unable to extract … latest version": cập nhật NGAY rồi thử lại một lần.
        ens = _ensure_ytdlp(progress, force=True)
        if ens.get("action") == "updated":
            try:
                return _ydl_extract(url, timeout), "", ""
            except ImportError:
                raise
            except Exception as e:      # noqa: BLE001
                first = str(e)
                logger.warning("youtube extract after updating yt-dlp %s: %s", vid, _short(first))
    if not yc.is_blocked(first):
        return None, _explain(first), ""
    say(f"YouTube refused the request without cookies: {_short(first)}")
    st = yc.settings()
    log: List[str] = [f"without cookies: {_short(first)}"]
    pl, tried, opened = None, [], []

    def attempt(label: str, **kw):
        try:
            return _ydl_extract(url, timeout, **kw)
        except ImportError:
            raise
        except Exception as e:      # noqa: BLE001
            log.append(f"{label}: {_short(e)}")
            say(f"{label} did not work: {_short(e)}")
            return None

    def with_file(label: str, name: str, att: Dict[str, Any]):
        if name not in tried:
            tried.append(name)
        try:
            return attempt(label, cookiefile=att["cookiefile"], proxy=att.get("proxy"))
        finally:
            yc.remove_file(att["cookiefile"])

    pasted = _cookie_file()
    if pasted:
        info = attempt("pasted cookies", cookiefile=pasted)
        if info is not None:
            return info, "", "pasted"
    if st.get("auto"):
        pl = yc.plan(st.get("profile") or "")
        for name in pl["live"][:yc.MAX_PROFILES]:
            att, why = yc.export_attempt(name)
            if not att:
                log.append(f"open profile {name}: {why}")
                continue
            info = with_file(f"cookies of the open profile {name}", name, att)
            if info is not None:
                return info, "", f"profile:{name}"
        for name in pl["closed"][:yc.MAX_PROFILES]:
            say(f"trying the saved YouTube cookies of {name}")
            att, why = yc.stored_attempt(name)
            if not att:
                log.append(f"saved cookies of {name}: {why}")
                continue
            info = with_file(f"saved cookies of {name}", name, att)
            if info is not None:
                return info, "", f"saved:{name}"
        # Cookie đã lưu không qua được → mở ẨN hồ sơ đầu tiên cho Google làm mới cookie (một hồ sơ: RAM).
        for name in pl["closed"][:1]:
            att, why = yc.refresh_attempt(name, progress=progress)
            if not att:
                opened.append(f"{name} ({why})")
                log.append(f"opening {name} in the background: {why}")
                continue
            info = with_file(f"refreshed cookies of {name}", name, att)
            if info is not None:
                return info, "", f"profile:{name}"
    if st.get("browser"):
        info = attempt(f"{st['browser']} cookies", browser=st["browser"])
        if info is not None:
            return info, "", f"browser:{st['browser']}"
    logger.info("youtube cookie attempts %s: %s", vid, " | ".join(log))
    low = first.lower()
    base = ("The video is age-restricted." if "age" in low and ("restrict" in low or "confirm your age" in low)
            else "YouTube asked this server to sign in (it treats the server's IP as a bot).")
    msg = f"{base} {yc.blocked_hint(st, pl, tried, opened)}"
    challenge = _challenge_hint(log)
    if challenge:
        msg += " " + challenge
    return None, f"{msg} Attempts: {'; '.join(log)}. You can also paste the video's text instead.", ""


def fetch_transcript(ref: str, prefer_lang: str = "", timeout: int = 60, use_cache: bool = True,
                     progress=None) -> Dict[str, Any]:
    """Phụ đề của MỘT video: {"ok", "id", "url", "title", "channel", "duration", "language", "kind",
    "text", "words", "minutes", "message"}. Không bao giờ ném — ok=False kèm câu người đọc được."""
    ref = str(ref or "").strip()
    ids = youtube_ids(ref) or ([ref] if _BARE_ID_RE.match(ref) else [])
    if not ids:
        return {"ok": False, "message": "Not a YouTube link."}
    vid = ids[0]
    url = f"https://www.youtube.com/watch?v={vid}"
    now = time.time()
    if use_cache:
        with _LOCK:
            hit = _CACHE.get(vid)
        if hit and now - hit[0] < _CACHE_TTL:
            return dict(hit[1])

    def fail(message: str) -> Dict[str, Any]:
        return {"ok": False, "id": vid, "url": url, "message": message}

    ens = _ensure_ytdlp(progress)
    if not ens.get("ok"):
        return fail(str(ens.get("message") or "yt-dlp is not installed on this server"))
    try:
        info, err, cookie_source = _extract_with_cookies(url, vid, timeout, progress)
    except ImportError:
        return fail("yt-dlp is not installed on this server — update TubeCLI (it installs yt-dlp) "
                    "or run: pip install yt-dlp")
    if info is None:
        return fail(err)
    track = pick_track(info, prefer_lang)
    if not track:
        return fail("This video has no subtitles (neither uploaded nor automatic) — paste its text instead.")
    lang, kind, entry = track
    try:
        raw = _http_get(entry["url"], timeout)
        text = (parse_json3(json.loads(raw.decode("utf-8", "replace"))) if entry.get("ext") == "json3"
                else parse_vtt(raw.decode("utf-8", "replace")))
    except Exception as e:      # noqa: BLE001
        logger.warning("youtube subtitle download %s: %s", vid, e)
        return fail(f"Could not download the subtitles: {str(e)[:200]}")
    words = count_words(text)
    if words < 30:
        return fail("The subtitles are almost empty — paste the video's text instead.")
    result = {"ok": True, "id": vid, "url": url, "title": str(info.get("title") or ""),
              "channel": str(info.get("channel") or info.get("uploader") or ""),
              "duration": int(info.get("duration") or 0), "language": lang, "kind": kind,
              "text": text, "words": words, "minutes": round(words / WORDS_PER_MINUTE, 1), "message": "",
              "cookie_source": cookie_source}
    with _LOCK:
        _CACHE[vid] = (now, result)
    return dict(result)


def public_info(result: Dict[str, Any]) -> Dict[str, Any]:
    """Kết quả không kèm văn bản (cho form)."""
    return {k: v for k, v in (result or {}).items() if k != "text"}
