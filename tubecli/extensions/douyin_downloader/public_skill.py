"""Skill Douyin cho NGƯỜI LẠ gọi qua Agent Town (core/public_agents.py).

Khác /parse của trang Downloader ở ba chỗ, đều có chủ ý:
  • chỉ nhận link Douyin — máy không bị dùng để mở URL bất kỳ người lạ đưa vào;
  • chỉ gửi cookie `ttwid`, KHÔNG BAO GIỜ gửi cookie đăng nhập của chủ: gửi nguyên cookie
    thì Douyin trả trang thử thách JS, và tài khoản của chủ dính vào request của người lạ;
  • không tải file, không ghi lịch sử, không lưu gì — trả đúng link gốc trên CDN Douyin
    (đã thử 22/9/2026: link play/ và ảnh bìa mở thẳng được, không cần Referer/cookie).
Không nhận trang cá nhân hay phòng live: trang cá nhân kéo cả trăm video, live không có
file để trả.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Dict, List

from tubecli.core.public_agents import PublicSkillError

# Link Douyin người ta hay dán: bản đầy đủ, link rút gọn trong app, trang chia sẻ.
_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|v\.)?(?:douyin\.com|iesdouyin\.com)/[^\s<>\"'，。]+",
    re.IGNORECASE,
)
_ID_RE = re.compile(r"^\d{15,20}$")
_MAX_MEDIA = 40


def pick_link(text: str) -> str:
    """Link Douyin đầu tiên trong tin nhắn (app Douyin chép kèm cả đoạn chữ quảng cáo),
    hay một id video trần. Không có thì '' — không đoán."""
    m = _URL_RE.search(text or "")
    if m:
        return m.group(0).rstrip(".,;:!?)）】")
    t = (text or "").strip()
    return t if _ID_RE.match(t) else ""


def _ttwid_only(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        part = part.strip()
        if part.startswith("ttwid="):
            return part
    return ""


def _is_video_url(u: str) -> bool:
    return "douyinvod.com" in u or "/aweme/v1/play" in u or ".mp4" in u.split("?")[0]


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


async def _direct_video(url: str, proxy) -> str:
    """Link play/ của Douyin (aweme.snssdk.com) → link file thật trên douyinvod.com.

    Trình duyệt người xem tải/nén ZIP thẳng từ CDN Douyin (không qua server nào của
    mình — user chốt 22/9/2026), mà muốn đọc file thì CDN phải trả CORS. douyinvod.com
    trả `Access-Control-Allow-Origin: *`, còn cú 302 của aweme.snssdk.com thì KHÔNG — nên
    trình duyệt không tự đi qua được. Máy đi hộ đúng MỘT bước: chỉ đọc header Location,
    không tải thân file. Hỏng thì trả '' và trang rơi về mở link play/ ở tab mới."""
    if "/aweme/v1/play" not in url:
        return url if "douyinvod.com" in url else ""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8, proxy=proxy, follow_redirects=False,
                                     headers={"User-Agent": _UA}) as client:
            r = await client.head(url)
            if not (300 <= r.status_code < 400):
                r = await client.get(url, headers={"Range": "bytes=0-0"})
            loc = r.headers.get("location") or ""
    except Exception:
        return ""
    host = loc.split("/")[2] if loc.startswith("https://") and loc.count("/") >= 3 else ""
    return loc if host.endswith(".douyinvod.com") or host == "douyinvod.com" else ""


async def resolve(text: str) -> Dict[str, Any]:
    link = pick_link(text)
    if not link:
        raise PublicSkillError("need_douyin_link")

    try:
        from tubecli.extensions.douyin_downloader.api_client import APIClient
        from tubecli.extensions.douyin_downloader.link_parser import LinkParser
        from tubecli.extensions.douyin_downloader.routes import _get_settings
    except ImportError:
        raise PublicSkillError("skill_unavailable", status=503)

    settings = _get_settings() or {}
    proxy = settings.get("proxy") or None
    cookie = _ttwid_only(settings.get("cookie_douyin", ""))

    platform, detail_id = await LinkParser.parse(link, proxy, cookie)
    if platform != "douyin" or not detail_id:
        # douyin_user / douyin_live / tiktok / không nhận ra
        raise PublicSkillError("unsupported_link")

    kwargs = {}
    if "reasons" in inspect.signature(APIClient.get_video_info).parameters:
        kwargs["reasons"] = []
    info = await APIClient.get_video_info(platform, detail_id, cookie, proxy, **kwargs)
    if not info:
        raise PublicSkillError("not_found", status=404)

    d = info.to_dict()
    urls: List[str] = []
    for u in [d.get("download_url")] + list(d.get("download_urls") or []):
        if isinstance(u, str) and u.startswith("http") and u not in urls:
            urls.append(u)

    if d.get("type") == "image":
        media = [{"type": "video" if _is_video_url(u) else "image", "url": u} for u in urls[:_MAX_MEDIA]]
        kind = "images"
    else:
        # Cùng một video, nhiều đường CDN: đường đầu là chính, giữ thêm hai đường dự phòng.
        # `direct` = link douyinvod.com để trình duyệt tải thẳng (xem _direct_video).
        media = []
        for u in urls[:3]:
            m = {"type": "video", "url": u}
            direct = await _direct_video(u, proxy)
            if direct:
                m["direct"] = direct
            media.append(m)
        kind = "video"
    if not media:
        raise PublicSkillError("not_found", status=404)

    return {
        "kind": kind,
        "title": str(d.get("title") or "")[:300],
        "author": str(d.get("author") or "")[:80],
        "duration": str(d.get("duration") or "")[:12],
        "cover": d.get("cover_url") or "",
        "media": media,
        "music": d.get("music_url") or "",
        "source": f"https://www.douyin.com/video/{detail_id}",
    }
