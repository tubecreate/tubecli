"""
Link Parser — Extract video IDs from TikTok & Douyin URLs.
Ported from TikTokDownloader/src/link/extractor.py
"""
import re
import httpx
from typing import Optional, Tuple

__all__ = ["LinkParser"]

# Douyin patterns
DOUYIN_VIDEO = re.compile(r"https://www\.douyin\.com/(?:video|note|slides)/(\d{19})")
DOUYIN_SHARE = re.compile(r"https://www\.iesdouyin\.com/share/(?:video|note|slides)/(\d{19})")
DOUYIN_SEARCH = re.compile(r"https://www\.douyin\.com/search/\S+?modal_id=(\d{19})")
DOUYIN_SHORT = re.compile(r"https://v\.douyin\.com/\S+")
DOUYIN_DISCOVER = re.compile(r"https://www\.douyin\.com/discover\S*?modal_id=(\d{19})")

# TikTok patterns
TIKTOK_VIDEO = re.compile(r"https://(?:www\.)?tiktok\.com/@[^/]+/(?:video|photo)/(\d{19})")
TIKTOK_SHORT = re.compile(r"https://(?:vm|vt)\.tiktok\.com/\S+")

# Generic ID (19 digits)
DETAIL_ID = re.compile(r"(\d{19})")

# Pattern to find video IDs in response body/URL
BODY_VIDEO_ID = re.compile(r"(?:video|note|slides|modal_id|aweme_id|item_id)[/=](\d{19})")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


class LinkParser:
    """Parse TikTok/Douyin URLs and extract video IDs."""

    @staticmethod
    async def parse(url: str, proxy: str = None, cookie: str = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Returns (platform, detail_id) or (None, None) if invalid.
        platform: 'douyin' | 'tiktok'
        """
        url = url.strip()

        # Accept raw 19-digit video ID
        if re.match(r'^\d{19}$', url):
            return 'douyin', url

        # Check if it's already a full URL with ID
        platform, detail_id = LinkParser._extract_from_url(url)
        if platform and detail_id:
            return platform, detail_id

        # Resolve short URLs
        if DOUYIN_SHORT.match(url):
            return await LinkParser._resolve_douyin_short(url, proxy, cookie)
        elif TIKTOK_SHORT.match(url):
            return await LinkParser._resolve_tiktok_short(url, proxy)

        # Last resort: find any 19-digit number
        m = DETAIL_ID.search(url)
        if m:
            if 'douyin' in url or 'iesdouyin' in url:
                return 'douyin', m.group(1)
            elif 'tiktok' in url:
                return 'tiktok', m.group(1)

        return None, None

    @staticmethod
    def _extract_from_url(url: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract platform and ID from a full URL."""
        # Douyin
        for pattern in [DOUYIN_VIDEO, DOUYIN_SHARE, DOUYIN_SEARCH, DOUYIN_DISCOVER]:
            m = pattern.search(url)
            if m:
                return "douyin", m.group(1)

        # TikTok
        m = TIKTOK_VIDEO.search(url)
        if m:
            return "tiktok", m.group(1)

        # Try body-style patterns
        m = BODY_VIDEO_ID.search(url)
        if m:
            if "douyin" in url or "iesdouyin" in url:
                return "douyin", m.group(1)
            elif "tiktok" in url:
                return "tiktok", m.group(1)

        return None, None

    @staticmethod
    async def _resolve_douyin_short(url: str, proxy: str = None, cookie: str = None) -> Tuple[Optional[str], Optional[str]]:
        """Resolve Douyin short URL (v.douyin.com) → extract video ID.
        Strategy:
        1. GET with SSR rendering headers → scan body for video/aweme ID
        2. Try iesdouyin.com/share endpoint
        3. Follow redirect chain and scan all URLs
        """
        headers = {**HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        try:
            # Strategy 1: GET the short URL page — look for video ID in HTML/JS
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15,
                proxy=proxy,
                headers=headers,
                verify=False,
            ) as client:
                resp = await client.get(url)

                # Check final URL and history for video IDs
                all_urls = [str(resp.url)] + [r.headers.get('location', '') for r in resp.history]
                combined_text = ' '.join(all_urls)

                for pattern in [DOUYIN_VIDEO, DOUYIN_SHARE, BODY_VIDEO_ID]:
                    m = pattern.search(combined_text)
                    if m:
                        return 'douyin', m.group(1)

                # Scan response body for aweme_id, video_id etc
                body = resp.text[:20000]
                m = BODY_VIDEO_ID.search(body)
                if m:
                    return 'douyin', m.group(1)

                # Search for aweme_id in JSON data embedded in page
                aweme_match = re.search(r'aweme_id["\':=]+\s*["\']?(\d{19})', body)
                if aweme_match:
                    return 'douyin', aweme_match.group(1)

                # Search for 19-digit IDs near keywords
                id_context = re.search(r'(?:aweme|video|item|detail|note)\S{0,30}(\d{19})', body)
                if id_context:
                    return 'douyin', id_context.group(1)

        except Exception:
            pass

        return None, None

    @staticmethod
    async def _resolve_tiktok_short(url: str, proxy: str = None) -> Tuple[Optional[str], Optional[str]]:
        """Resolve TikTok short URL (vm.tiktok.com / vt.tiktok.com)."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10,
                proxy=proxy,
                headers=HEADERS,
            ) as client:
                resp = await client.get(url)
                final_url = str(resp.url)
                platform, detail_id = LinkParser._extract_from_url(final_url)
                if platform and detail_id:
                    return platform, detail_id

                # Check history
                for r in resp.history:
                    loc = r.headers.get("location", "")
                    if loc:
                        p, d = LinkParser._extract_from_url(loc)
                        if p and d:
                            return p, d
        except Exception:
            pass

        return None, None

    @staticmethod
    async def parse_batch(text: str, proxy: str = None) -> list:
        """Parse multiple URLs from text (one per line or space-separated)."""
        import asyncio
        urls = re.findall(r"https?://\S+", text)
        results = await asyncio.gather(
            *[LinkParser.parse(u, proxy) for u in urls],
            return_exceptions=True,
        )
        parsed = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                continue
            platform, detail_id = result
            if platform and detail_id:
                parsed.append({
                    "url": url,
                    "platform": platform,
                    "detail_id": detail_id,
                })
        return parsed
