"""
API Client — Fetch video metadata from Douyin & TikTok APIs.
Uses ABogus signature for Douyin anti-bot verification.
"""
import httpx
import logging
import importlib.util
import sys
import types
import os
from typing import Optional
from urllib.parse import urlencode, quote

logger = logging.getLogger("downloader.api_client")

DOUYIN_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
DOUYIN_USER_API = "https://www.douyin.com/aweme/v1/web/user/profile/other/"
DOUYIN_POST_API = "https://www.douyin.com/aweme/v1/web/aweme/post/"
TIKTOK_API = "https://www.tiktok.com/api/item/detail/"

USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

DOUYIN_HEADERS = {
    "User-Agent": USERAGENT,
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
}

TIKTOK_HEADERS = {
    "User-Agent": USERAGENT,
    "Referer": "https://www.tiktok.com/",
    "Accept": "application/json, text/plain, */*",
}

# Douyin base params (from TikTokDownloader template.py)
DOUYIN_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "platform": "PC",
    "msToken": "",
}

# === ABogus Loader ===

_abogus_instance = None


def _get_abogus():
    """Lazy-load ABogus from the original TikTokDownloader or our copy."""
    global _abogus_instance
    if _abogus_instance is not None:
        return _abogus_instance

    # Try loading from original TikTokDownloader project
    abogus_paths = [
        os.path.join(os.path.dirname(__file__), "encrypt", "aBogus.py"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "TikTokDownloader", "src", "encrypt", "aBogus.py"),
    ]

    for path in abogus_paths:
        path = os.path.abspath(path)
        if os.path.exists(path):
            try:
                # Mock src.custom if needed
                if "src" not in sys.modules:
                    src = types.ModuleType("src")
                    src.custom = types.ModuleType("src.custom")
                    src.custom.USERAGENT = USERAGENT
                    sys.modules["src"] = src
                    sys.modules["src.custom"] = src.custom
                elif not hasattr(sys.modules.get("src", None), "custom"):
                    sys.modules["src"].custom = types.ModuleType("src.custom")
                    sys.modules["src"].custom.USERAGENT = USERAGENT
                    sys.modules["src.custom"] = sys.modules["src"].custom

                spec = importlib.util.spec_from_file_location("abogus_module", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _abogus_instance = mod.ABogus(USERAGENT)
                logger.info(f"ABogus loaded from {path}")
                return _abogus_instance
            except Exception as e:
                logger.warning(f"Failed to load ABogus from {path}: {e}")
                continue

    logger.error("ABogus not available — Douyin API will not work")
    return None


class VideoInfo:
    """Parsed video metadata."""
    def __init__(self):
        self.id = ""
        self.platform = ""
        self.title = ""
        self.author = ""
        self.author_id = ""
        self.duration = ""
        self.cover_url = ""
        self.download_url = ""
        self.download_urls = []
        self.width = 0
        self.height = 0
        self.play_count = 0
        self.like_count = 0
        self.comment_count = 0
        self.share_count = 0
        self.create_time = ""
        self.type = "video"
        self.music_url = ""
        self.music_title = ""
        self.raw_data = None

    def to_dict(self):
        return {
            "id": self.id,
            "platform": self.platform,
            "title": self.title,
            "author": self.author,
            "author_id": self.author_id,
            "duration": self.duration,
            "cover_url": self.cover_url,
            "download_url": self.download_url,
            "width": self.width,
            "height": self.height,
            "play_count": self.play_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "share_count": self.share_count,
            "create_time": self.create_time,
            "type": self.type,
            "music_url": self.music_url,
            "music_title": self.music_title,
        }


class APIClient:
    """Fetch video info from Douyin/TikTok APIs."""

    @staticmethod
    async def get_video_info(
        platform: str,
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
    ) -> Optional[VideoInfo]:
        if platform == "douyin":
            return await APIClient._get_douyin_info(detail_id, cookie, proxy)
        elif platform == "tiktok":
            return await APIClient._get_tiktok_info(detail_id, cookie, proxy)
        return None

    @staticmethod
    def _build_douyin_url(detail_id: str) -> Optional[str]:
        """Build Douyin API URL with ABogus signature."""
        ab = _get_abogus()
        params = {**DOUYIN_BASE_PARAMS, "aweme_id": detail_id}
        encoded = urlencode(params, safe="=", quote_via=quote)

        if ab:
            a_bogus = ab.get_value(encoded, "GET")
            return f"{DOUYIN_API}?{encoded}&a_bogus={a_bogus}"
        else:
            # Fallback without signature (will likely fail)
            return f"{DOUYIN_API}?{encoded}"

    @staticmethod
    async def _get_douyin_info(
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
    ) -> Optional[VideoInfo]:
        headers = {**DOUYIN_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        url = APIClient._build_douyin_url(detail_id)
        if not url:
            logger.error("Cannot build Douyin API URL")
            return None

        try:
            async with httpx.AsyncClient(
                timeout=15,
                proxy=proxy,
                headers=headers,
                verify=False,
            ) as client:
                resp = await client.get(url)
                if not resp.text:
                    logger.warning(f"Empty response for {detail_id} — ABogus may have failed")
                    return None
                data = resp.json()

            detail = data.get("aweme_detail")
            if not detail:
                logger.warning(f"No aweme_detail for {detail_id}: status_code={data.get('status_code')}")
                return None

            info = VideoInfo()
            info.id = detail.get("aweme_id", detail_id)
            info.platform = "douyin"
            info.title = detail.get("desc", "")[:200]
            info.raw_data = detail

            # Author
            author = detail.get("author", {})
            info.author = author.get("nickname", "")
            info.author_id = author.get("uid", "")

            # Statistics
            stats = detail.get("statistics", {})
            info.play_count = stats.get("play_count", 0)
            info.like_count = stats.get("digg_count", 0)
            info.comment_count = stats.get("comment_count", 0)
            info.share_count = stats.get("share_count", 0)

            # Time
            create_time = detail.get("create_time", 0)
            if create_time:
                from datetime import datetime
                info.create_time = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")

            # Check if images or video
            if detail.get("images"):
                info.type = "image"
                images = detail["images"]
                info.download_url = images[0].get("url_list", [""])[0] if images else ""
            else:
                info.type = "video"
                video = detail.get("video", {})
                # Duration
                duration_ms = video.get("duration", 0)
                s = duration_ms // 1000
                info.duration = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

                # Best quality video URL from bit_rate
                bit_rate = video.get("bit_rate", [])
                if bit_rate:
                    sorted_br = sorted(
                        bit_rate,
                        key=lambda x: max(
                            x.get("play_addr", {}).get("height", 0),
                            x.get("play_addr", {}).get("width", 0),
                        ),
                    )
                    best = sorted_br[-1]
                    play_addr = best.get("play_addr", {})
                    urls = play_addr.get("url_list", [])
                    info.download_url = urls[0] if urls else ""
                    info.width = play_addr.get("width", 0)
                    info.height = play_addr.get("height", 0)
                elif video.get("play_addr"):
                    urls = video["play_addr"].get("url_list", [])
                    info.download_url = urls[0] if urls else ""
                    info.width = video["play_addr"].get("width", 0)
                    info.height = video["play_addr"].get("height", 0)

                # Cover
                cover = video.get("cover", {})
                info.cover_url = (cover.get("url_list", [""])[-1]) if cover else ""

            # Music
            music = detail.get("music", {})
            if music:
                info.music_title = music.get("title", "")
                play_url = music.get("play_url", {})
                if isinstance(play_url, dict):
                    urls = play_url.get("url_list", [])
                    info.music_url = urls[0] if urls else ""
                elif isinstance(play_url, str):
                    info.music_url = play_url

            return info

        except Exception as e:
            logger.error(f"Douyin API error: {e}")
            return None

    @staticmethod
    async def _get_tiktok_info(
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
    ) -> Optional[VideoInfo]:
        headers = {**TIKTOK_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        params = {"itemId": detail_id}

        try:
            async with httpx.AsyncClient(
                timeout=15,
                proxy=proxy,
                headers=headers,
            ) as client:
                resp = await client.get(TIKTOK_API, params=params)
                data = resp.json()

            item_info = data.get("itemInfo", {})
            detail = item_info.get("itemStruct")
            if not detail:
                logger.warning(f"No itemStruct for {detail_id}")
                return None

            info = VideoInfo()
            info.id = detail.get("id", detail_id)
            info.platform = "tiktok"
            info.title = detail.get("desc", "")[:200]
            info.raw_data = detail

            # Author
            author = detail.get("author", {})
            info.author = author.get("nickname", "")
            info.author_id = author.get("id", "")

            # Stats
            stats = detail.get("stats", {})
            info.play_count = stats.get("playCount", 0)
            info.like_count = stats.get("diggCount", 0)
            info.comment_count = stats.get("commentCount", 0)
            info.share_count = stats.get("shareCount", 0)

            # Time
            create_time = detail.get("createTime", 0)
            if create_time:
                from datetime import datetime
                try:
                    info.create_time = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, OSError):
                    pass

            # Video
            video = detail.get("video", {})
            if detail.get("imagePost"):
                info.type = "image"
                images = detail["imagePost"].get("images", [])
                if images:
                    url_list = images[0].get("imageURL", {}).get("urlList", [])
                    info.download_url = url_list[0] if url_list else ""
            else:
                info.type = "video"
                duration_s = video.get("duration", 0)
                info.duration = f"{duration_s // 3600:02d}:{duration_s % 3600 // 60:02d}:{duration_s % 60:02d}"

                bitrate_info = video.get("bitrateInfo", [])
                if bitrate_info:
                    sorted_br = sorted(
                        bitrate_info,
                        key=lambda x: max(
                            x.get("PlayAddr", {}).get("Height", 0),
                            x.get("PlayAddr", {}).get("Width", 0),
                        ),
                    )
                    best = sorted_br[-1]
                    play_addr = best.get("PlayAddr", {})
                    urls = play_addr.get("UrlList", [])
                    info.download_url = urls[0] if urls else ""
                    info.width = play_addr.get("Width", 0)
                    info.height = play_addr.get("Height", 0)
                elif video.get("playAddr"):
                    info.download_url = video["playAddr"]

                info.cover_url = video.get("cover", "")

            # Music
            music = detail.get("music", {})
            if music:
                info.music_title = music.get("title", "")
                info.music_url = music.get("playUrl", "")

            return info

        except Exception as e:
            logger.error(f"TikTok API error: {e}")
            return None

    # === User Profile APIs ===

    @staticmethod
    def _build_douyin_signed_url(api_url: str, extra_params: dict) -> Optional[str]:
        """Build any Douyin API URL with ABogus signature."""
        ab = _get_abogus()
        params = {**DOUYIN_BASE_PARAMS, **extra_params}
        encoded = urlencode(params, safe="=", quote_via=quote)
        if ab:
            a_bogus = ab.get_value(encoded, "GET")
            return f"{api_url}?{encoded}&a_bogus={a_bogus}"
        return f"{api_url}?{encoded}"

    @staticmethod
    async def get_user_info(
        sec_user_id: str,
        cookie: str = "",
        proxy: str = None,
    ) -> Optional[dict]:
        """Get Douyin user profile info."""
        headers = {**DOUYIN_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        url = APIClient._build_douyin_signed_url(DOUYIN_USER_API, {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": "2",
            "personal_center_strategy": "1",
            "profile_other_record_enable": "1",
            "land_to": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
        })

        try:
            async with httpx.AsyncClient(
                timeout=15, proxy=proxy, headers=headers, verify=False,
            ) as client:
                resp = await client.get(url)
                if not resp.text:
                    return None
                data = resp.json()

            user = data.get("user")
            if not user:
                logger.warning(f"No user data for {sec_user_id}")
                return None

            return {
                "sec_user_id": user.get("sec_uid", sec_user_id),
                "nickname": user.get("nickname", ""),
                "signature": user.get("signature", ""),
                "avatar": user.get("avatar_300x300", {}).get("url_list", [""])[0] if user.get("avatar_300x300") else "",
                "aweme_count": user.get("aweme_count", 0),
                "follower_count": user.get("follower_count", 0),
                "following_count": user.get("following_count", 0),
                "total_favorited": user.get("total_favorited", 0),
                "uid": user.get("uid", ""),
                "unique_id": user.get("unique_id", ""),
            }
        except Exception as e:
            logger.error(f"User info API error: {e}")
            return None

    @staticmethod
    async def get_user_posts(
        sec_user_id: str,
        cookie: str = "",
        proxy: str = None,
        max_pages: int = 5,
        count: int = 18,
    ) -> list:
        """Get all videos from a Douyin user profile (paginated)."""
        headers = {**DOUYIN_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        all_videos = []
        cursor = 0
        page = 0

        while page < max_pages:
            url = APIClient._build_douyin_signed_url(DOUYIN_POST_API, {
                "sec_user_id": sec_user_id,
                "max_cursor": str(cursor),
                "locate_query": "false",
                "show_live_replay_strategy": "1",
                "need_time_list": "1",
                "time_list_query": "0",
                "whale_cut_token": "",
                "cut_version": "1",
                "count": str(count),
                "publish_video_strategy_type": "2",
            })

            try:
                async with httpx.AsyncClient(
                    timeout=15, proxy=proxy, headers=headers, verify=False,
                ) as client:
                    resp = await client.get(url)
                    if not resp.text:
                        break
                    data = resp.json()

                aweme_list = data.get("aweme_list", [])
                if not aweme_list:
                    break

                for item in aweme_list:
                    video_info = APIClient._parse_douyin_aweme(item)
                    if video_info:
                        all_videos.append(video_info)

                has_more = data.get("has_more", 0)
                cursor = data.get("max_cursor", 0)
                page += 1

                if not has_more:
                    break

            except Exception as e:
                logger.error(f"User posts API error (page {page}): {e}")
                break

        return all_videos

    @staticmethod
    def _parse_douyin_aweme(detail: dict) -> Optional[VideoInfo]:
        """Parse a single aweme item from Douyin API response."""
        try:
            info = VideoInfo()
            info.id = detail.get("aweme_id", "")
            info.platform = "douyin"
            info.title = detail.get("desc", "")[:200]

            # Author
            author = detail.get("author", {})
            info.author = author.get("nickname", "")
            info.author_id = author.get("uid", "")

            # Statistics
            stats = detail.get("statistics", {})
            info.play_count = stats.get("play_count", 0)
            info.like_count = stats.get("digg_count", 0)
            info.comment_count = stats.get("comment_count", 0)
            info.share_count = stats.get("share_count", 0)

            # Time
            create_time = detail.get("create_time", 0)
            if create_time:
                from datetime import datetime
                info.create_time = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")

            # Images or video
            if detail.get("images"):
                info.type = "image"
                images = detail["images"]
                info.download_url = images[0].get("url_list", [""])[0] if images else ""
            else:
                info.type = "video"
                video = detail.get("video", {})
                duration_ms = video.get("duration", 0)
                s = duration_ms // 1000
                info.duration = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

                bit_rate = video.get("bit_rate", [])
                if bit_rate:
                    sorted_br = sorted(
                        bit_rate,
                        key=lambda x: max(
                            x.get("play_addr", {}).get("height", 0),
                            x.get("play_addr", {}).get("width", 0),
                        ),
                    )
                    best = sorted_br[-1]
                    play_addr = best.get("play_addr", {})
                    urls = play_addr.get("url_list", [])
                    info.download_url = urls[0] if urls else ""
                    info.width = play_addr.get("width", 0)
                    info.height = play_addr.get("height", 0)
                elif video.get("play_addr"):
                    urls = video["play_addr"].get("url_list", [])
                    info.download_url = urls[0] if urls else ""

                cover = video.get("cover", {})
                info.cover_url = (cover.get("url_list", [""])[-1]) if cover else ""

            return info
        except Exception as e:
            logger.warning(f"Failed to parse aweme: {e}")
            return None
