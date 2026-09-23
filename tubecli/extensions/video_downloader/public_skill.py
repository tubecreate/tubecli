"""Skill «phụ đề YouTube» cho NGƯỜI LẠ gọi qua Agent Town (core/public_agents.py).

Vì sao chỉ có bấy nhiêu đây (chốt 23/9/2026, sau khi soi extension Web Crawler):
Douyin an toàn được nhờ HAI CÁI NEO — đầu vào ép về đúng tên miền, đầu ra lọc theo đúng
tên miền đó. Một web crawler đúng nghĩa phải gỡ bỏ cả hai cái neo ấy, nên không mở. Phụ
đề YouTube giữ nguyên được cả hai, chặt hơn cả Douyin:

  • ĐẦU VÀO: chỉ móc ra MÃ VIDEO 11 ký tự trong tin nhắn. URL gọi đi do lõi tự ghép
    (`https://www.youtube.com/watch?v=<id>`), KHÔNG lấy một mẩu nào từ chữ người lạ gõ —
    nên không có đường nào trỏ máy sang localhost, sang mạng nội bộ hay sang site khác.
  • ĐẦU RA: chỉ có CHỮ. Không link lạ, không file, không ảnh — cloud không phải tin một
    tên miền nào ngoài chính youtube.com.
  • KHÔNG COOKIE: chạy như một người khách vãng lai. Cookie/tài khoản Google của chủ máy
    không bao giờ dính vào lượt gọi của người lạ, và video riêng tư của chủ cũng không lọt
    ra qua bộ nhớ đệm (lõi nhớ riêng hai chế độ).
  • KHÔNG GHI GÌ: không lưu file, không vào lịch sử tải, không vào kho nội dung.
"""
from __future__ import annotations

import asyncio
import re
from functools import partial
from typing import Any, Dict

from tubecli.core.public_agents import PublicSkillError

_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

MAX_CHARS = 20000          # đủ cho một video ~2 giờ; dài hơn thì cắt và nói rõ là đã cắt
FETCH_TIMEOUT_SEC = 25     # cloud chờ 50 s, lõi cắt ở 40 s — chừa chỗ cho đường về

# Video công khai hoặc «không công khai nhưng ai có link đều xem được». Còn riêng tư /
# chỉ hội viên / trả tiền thì không đụng tới, kể cả khi yt-dlp lấy được.
_OPEN = ("", "public", "unlisted", "unlisted_from_search")


def pick_link(text: str) -> str:
    """Mã video YouTube đầu tiên trong tin nhắn, hay '' nếu không có. Không đoán.

    Dùng đúng bộ dò của lõi (core/youtube_transcript.youtube_ids): nó chỉ nhận
    youtube.com / youtu.be / shorts / embed và mã trần 11 ký tự."""
    from tubecli.core.youtube_transcript import youtube_ids

    t = str(text or "").strip()
    ids = youtube_ids(t)
    if ids:
        return ids[0]
    return t if _BARE_ID_RE.match(t) else ""


def _hms(seconds: int) -> str:
    s = max(0, int(seconds or 0))
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _code_for(message: str) -> str:
    low = (message or "").lower()
    if "sign in" in low or "not a bot" in low:
        return "yt_signin"
    if "no subtitles" in low or "almost empty" in low:
        return "no_subtitles"
    if "private" in low or "unavailable" in low or "removed" in low or "age-restricted" in low:
        return "video_unavailable"
    if "yt-dlp" in low:
        return "skill_unavailable"
    return "skill_failed"


async def resolve(text: str) -> Dict[str, Any]:
    vid = pick_link(text)
    if not vid:
        raise PublicSkillError("need_youtube_link")

    from tubecli.core.youtube_transcript import fetch_transcript

    # fetch_transcript là hàm chặn (yt-dlp + tải file phụ đề) — chạy ở luồng khác để vòng
    # lặp async của máy vẫn phục vụ chủ trong lúc chờ.
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(partial(fetch_transcript, vid, timeout=20, use_cookies=False)),
            timeout=FETCH_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        raise PublicSkillError("timeout", status=504)
    except ImportError:
        raise PublicSkillError("skill_unavailable", status=503)

    if not res.get("ok"):
        code = _code_for(str(res.get("message") or ""))
        raise PublicSkillError(code, status=404 if code == "video_unavailable" else 422)
    if str(res.get("availability") or "") not in _OPEN:
        raise PublicSkillError("video_unavailable", status=404)

    body = str(res.get("text") or "")
    cut = len(body) > MAX_CHARS
    return {
        "kind": "text",
        "title": str(res.get("title") or "")[:300],
        "author": str(res.get("channel") or "")[:80],
        "duration": _hms(res.get("duration") or 0),
        "language": str(res.get("language") or "")[:16],
        "auto": res.get("kind") == "auto",
        "words": int(res.get("words") or 0),
        "text": body[:MAX_CHARS],
        "truncated": cut,
        "source": f"https://www.youtube.com/watch?v={res.get('id') or vid}",
    }
