"""
API Client — Fetch video metadata from Douyin & TikTok APIs.

Douyin có hai đường lấy dữ liệu, thử theo thứ tự:

1. Trang chia sẻ iesdouyin.com/share/video/<id>/ — trả HTML kèm khối
   `_ROUTER_DATA` chứa nguyên dữ liệu tác phẩm. KHÔNG cần chữ ký, chỉ cần
   cookie `ttwid` (chính trang đó phát cookie này ở lượt gọi đầu).
2. API ký a_bogus (aweme/v1/web/aweme/detail/) — dữ liệu đầy đủ hơn nhưng từ
   2026 bị ArgusSecurityPlugin chặn 403 nếu chữ ký không do trình duyệt thật
   sinh ra. Giữ lại làm dự phòng phòng khi Douyin nới lại.
"""
import httpx
import json
import logging
import importlib.util
import re
import sys
import types
import os
from typing import Optional
from urllib.parse import urlencode, quote

logger = logging.getLogger("downloader.api_client")

DOUYIN_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
DOUYIN_USER_API = "https://www.douyin.com/aweme/v1/web/user/profile/other/"
DOUYIN_POST_API = "https://www.douyin.com/aweme/v1/web/aweme/post/"
DOUYIN_SHARE_VIDEO = "https://www.iesdouyin.com/share/video/{}/"
# Bài ảnh và ghi chú có đường chia sẻ riêng; thử thêm khi đường /video/ không ra gì.
DOUYIN_SHARE_ALT = (
    "https://www.iesdouyin.com/share/note/{}/",
    "https://www.iesdouyin.com/share/slides/{}/",
)
DOUYIN_SHARE_USER = "https://www.iesdouyin.com/share/user/{}"
TIKTOK_API = "https://www.tiktok.com/api/item/detail/"

USERAGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# Trang chia sẻ chỉ dựng sẵn dữ liệu cho UA di động; UA máy tính bị đá về www.douyin.com.
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")

DOUYIN_HEADERS = {
    "User-Agent": USERAGENT,
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
}

SHARE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TIKTOK_HEADERS = {
    "User-Agent": USERAGENT,
    "Referer": "https://www.tiktok.com/",
    "Accept": "application/json, text/plain, */*",
}

_ROUTER_DATA_RE = re.compile(r"_ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)

# Douyin base params (from TikTokDownloader template.py).
# Thiếu `uifid` là bị chặn ngay từ cổng đầu: "Blocked by ArgusSecurityPlugin Uifid Not Found".
DOUYIN_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "update_version_code": "170400",
    "pc_client_type": "1",
    "pc_libra_divert": "Windows",
    "support_h265": "1",
    "support_dash": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "screen_width": "1536",
    "screen_height": "864",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "131.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "131.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "cpu_core_num": "16",
    "device_memory": "8",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "200",
    "uifid": "",
    "msToken": "",
}


def cookie_value(cookie: str, name: str) -> str:
    """Đọc một giá trị trong chuỗi cookie "k=v; k2=v2"."""
    for part in (cookie or "").split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return ""


def no_watermark(url: str) -> str:
    """Đổi link playwm (có logo) sang link play sạch, và nâng lên 1080p.

    Chỉ chạm tới link aweme/v1/playwm của trang chia sẻ; link lấy từ API ký
    vốn đã trỏ thẳng douyinvod nên hàm này không đụng vào.
    """
    if not url or "/aweme/v1/playwm/" not in url:
        return url
    url = url.replace("/aweme/v1/playwm/", "/aweme/v1/play/")
    return re.sub(r"ratio=\d+p", "ratio=1080p", url)

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
            "download_urls": self.download_urls,
        }


class APIClient:
    """Fetch video info from Douyin/TikTok APIs."""

    @staticmethod
    async def get_video_info(
        platform: str,
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
    ) -> Optional[VideoInfo]:
        """Lấy dữ liệu tác phẩm. `reasons` (nếu truyền) nhận các lý do thất bại
        để nơi gọi nói cho người dùng biết hỏng ở đâu, thay vì đoán mò."""
        if platform == "douyin":
            return await APIClient._get_douyin_info(detail_id, cookie, proxy, reasons)
        elif platform == "douyin_live":
            return await APIClient._get_douyin_live_info(detail_id, cookie, proxy, reasons)
        elif platform == "douyin_user_live":
            user_info = await APIClient.get_user_info(detail_id, cookie, proxy, reasons)
            if user_info:
                # Use web_rid if available (required for web API), fallback to room_id
                rid = user_info.get("web_rid") or user_info.get("room_id")
                if rid:
                    return await APIClient._get_douyin_live_info(str(rid), cookie, proxy, reasons)
            return None
        elif platform == "tiktok":
            return await APIClient._get_tiktok_info(detail_id, cookie, proxy, reasons)
        return None

    # === Đường 1: trang chia sẻ (không cần chữ ký) ===

    @staticmethod
    def _item_from_router_data(html: str) -> tuple:
        """Bóc (item, lý do bị chặn) từ khối _ROUTER_DATA của trang chia sẻ."""
        m = _ROUTER_DATA_RE.search(html or "")
        if not m:
            return None, ""
        try:
            data = json.loads(m.group(1))
        except Exception as e:
            logger.warning(f"_ROUTER_DATA không đọc được: {e}")
            return None, ""
        for value in (data.get("loaderData") or {}).values():
            if not isinstance(value, dict):
                continue
            res = value.get("videoInfoRes")
            if not isinstance(res, dict):
                continue
            items = res.get("item_list") or []
            if items:
                return items[0], ""
            # Douyin nói rõ vì sao không trả tác phẩm (đã xoá, riêng tư, cần đăng nhập…)
            notice = (res.get("filter_list") or [{}])[0]
            return None, str(notice.get("detail_msg") or notice.get("notice") or "")
        return None, ""

    @staticmethod
    def _share_cookies(cookie: str) -> list:
        """Các cookie đáng thử cho trang chia sẻ, theo thứ tự.

        Trang này chỉ cần `ttwid`. Ném nguyên cookie đăng nhập vào đây thì kiểm
        soát rủi ro của Douyin trả về trang thử thách JS (~2,5 KB, không có
        _ROUTER_DATA) — nghĩa là CÀNG nhiều cookie càng dễ hỏng. Chuỗi rỗng ở
        cuối để tự xin ttwid mới khi ttwid đã lưu bị đánh dấu.
        """
        ttwid = cookie_value(cookie, "ttwid")
        return [f"ttwid={ttwid}", ""] if ttwid else [""]

    @staticmethod
    async def _read_share_page(url: str, cookie: str, proxy: str, pick) -> tuple:
        """Gọi trang chia sẻ, thử lần lượt từng bộ cookie. Trả (kết quả, lời từ chối)."""
        notice = ""
        for header_cookie in APIClient._share_cookies(cookie):
            headers = {**SHARE_HEADERS}
            if header_cookie:
                headers["Cookie"] = header_cookie
            try:
                async with httpx.AsyncClient(
                    timeout=20,
                    proxy=proxy,
                    headers=headers,
                    verify=False,
                    follow_redirects=True,
                ) as client:
                    # Lượt đầu có thể chỉ để trang phát cookie ttwid; giữ jar rồi gọi lại.
                    for _ in (1, 2):
                        resp = await client.get(url)
                        found, notice = pick(resp.text)
                        if found:
                            return found, ""
                        if notice or not client.cookies.get("ttwid"):
                            break
            except Exception as e:
                logger.error(f"Share page error: {e}")
                notice = f"trang chia sẻ lỗi: {e}"
            if notice:
                break
        return None, notice

    @staticmethod
    async def _fetch_share_item(
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
    ) -> Optional[dict]:
        notice = ""
        for template in (DOUYIN_SHARE_VIDEO,) + DOUYIN_SHARE_ALT:
            item, notice = await APIClient._read_share_page(
                template.format(detail_id), cookie, proxy,
                APIClient._item_from_router_data,
            )
            if item:
                return item
            if notice:
                # Douyin đã nói rõ lý do — thử đường khác cũng vậy thôi.
                break
        if notice:
            logger.warning(f"Trang chia sẻ từ chối {detail_id}: {notice}")
            if reasons is not None:
                reasons.append(notice)
        else:
            logger.warning(f"Trang chia sẻ không có dữ liệu cho {detail_id}")
            if reasons is not None:
                reasons.append("trang chia sẻ không có tác phẩm này (có thể đã bị gỡ hoặc để riêng tư)")
        return None

    # === Đường 2: API ký a_bogus ===

    @staticmethod
    def _build_douyin_url(detail_id: str, cookie: str = "") -> Optional[str]:
        """Build Douyin API URL with ABogus signature."""
        return APIClient._build_douyin_signed_url(
            DOUYIN_API, {"aweme_id": detail_id}, cookie,
        )

    @staticmethod
    async def _get_douyin_info(
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
    ) -> Optional[VideoInfo]:
        # 1) Trang chia sẻ trước: nhẹ, không cần chữ ký, chạy cả khi chưa có cookie.
        item = await APIClient._fetch_share_item(detail_id, cookie, proxy, reasons)
        if item:
            info = APIClient._parse_douyin_aweme(item)
            if info:
                info.id = info.id or detail_id
                return info

        # 2) API ký — từ 2026 thường bị ArgusSecurityPlugin chặn, giữ làm dự phòng.
        headers = {**DOUYIN_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        url = APIClient._build_douyin_url(detail_id, cookie)
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
            data = APIClient._read_douyin_json(resp, detail_id, reasons)
            if data is None:
                return None
            detail = data.get("aweme_detail")
            if not detail:
                logger.warning(f"No aweme_detail for {detail_id}: status_code={data.get('status_code')}")
                if reasons is not None:
                    reasons.append(f"API không trả tác phẩm (status_code={data.get('status_code')})")
                return None

            info = APIClient._parse_douyin_aweme(detail)
            if info:
                info.id = info.id or detail_id
            return info

        except Exception as e:
            logger.error(f"Douyin API error: {e}")
            if reasons is not None:
                reasons.append(f"API lỗi: {e}")
            return None

    @staticmethod
    def _read_douyin_json(resp, detail_id: str, reasons: list = None) -> Optional[dict]:
        """Đọc JSON và nói thẳng khi Douyin trả 403/HTML thay vì nuốt lỗi.

        Trước đây resp.json() ném ngoại lệ trên thân 403 "text/plain", rơi vào
        except ngoài cùng và người dùng chỉ thấy "cookie có thể đã hết hạn".
        """
        body = (resp.text or "").strip()
        if resp.status_code != 200 or not body:
            snippet = body[:120] or f"HTTP {resp.status_code}, thân rỗng"
            logger.warning(f"Douyin API {resp.status_code} cho {detail_id}: {snippet}")
            if reasons is not None:
                if "ArgusSecurityPlugin" in body:
                    reasons.append(f"Douyin chặn chữ ký (HTTP {resp.status_code}: {snippet})")
                else:
                    reasons.append(f"Douyin trả HTTP {resp.status_code}: {snippet}")
            return None
        try:
            return resp.json()
        except Exception:
            logger.warning(f"Douyin API trả dữ liệu không phải JSON cho {detail_id}: {body[:120]}")
            if reasons is not None:
                reasons.append(f"API trả dữ liệu không phải JSON: {body[:120]}")
            return None

    @staticmethod
    async def _get_douyin_live_info(
        room_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
    ) -> Optional[VideoInfo]:
        headers = {**DOUYIN_HEADERS}
        if cookie:
            headers["Cookie"] = cookie
        headers["Referer"] = "https://live.douyin.com/"

        # Webcast enter API
        url = "https://live.douyin.com/webcast/room/web/enter/"

        signed_url = APIClient._build_douyin_signed_url(url, {
            "web_rid": room_id,
            "aid": "6383",
            "device_platform": "web"
        }, cookie)
        if not signed_url:
            return None

        try:
            async with httpx.AsyncClient(
                timeout=15,
                proxy=proxy,
                headers=headers,
                verify=False,
            ) as client:
                resp = await client.get(signed_url)
            data = APIClient._read_douyin_json(resp, room_id, reasons)
            if data is None:
                return None

            if "data" not in data or "data" not in data.get("data", {}) or not data["data"]["data"]:
                logger.warning(f"No live room data for {room_id}")
                if reasons is not None:
                    reasons.append("phòng live không có dữ liệu")
                return None

            room = data["data"]["data"][0]
            owner = room.get("owner", {})
            
            info = VideoInfo()
            info.id = str(room.get("id_str", room_id))
            info.platform = "douyin_live"
            info.title = room.get("title", "")[:200]
            info.author = owner.get("nickname", "")
            info.author_id = owner.get("sec_uid", "")
            info.type = "live"
            info.raw_data = room
            
            # Avatar
            avatar = owner.get("avatar_large", {})
            if avatar and avatar.get("url_list"):
                info.cover_url = avatar["url_list"][0]

            # Stream URLs
            stream_url = room.get("stream_url", {})
            hls = stream_url.get("hls_pull_url", "")
            flv = stream_url.get("flv_pull_url", "")
            
            info.download_url = hls if hls else flv
            
            if not info.download_url:
                hls_map = stream_url.get("hls_pull_url_map", {})
                flv_map = stream_url.get("flv_pull_url_map", {})
                for k, v in hls_map.items():
                    info.download_url = v
                    break
                if not info.download_url:
                    for k, v in flv_map.items():
                        info.download_url = v
                        break

            # Viewer count
            info.play_count = room.get("user_count", 0)
            
            return info
        except Exception as e:
            logger.error(f"Live API error: {e}")
            if reasons is not None:
                reasons.append(f"API live lỗi: {e}")
            return None

    @staticmethod
    async def _get_tiktok_info(
        detail_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
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
                if reasons is not None:
                    reasons.append("TikTok không trả dữ liệu tác phẩm")
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
            if reasons is not None:
                reasons.append(f"TikTok API lỗi: {e}")
            return None

    # === User Profile APIs ===

    @staticmethod
    def _build_douyin_signed_url(api_url: str, extra_params: dict, cookie: str = "") -> Optional[str]:
        """Build any Douyin API URL with ABogus signature.

        `uifid` và `msToken` phải lấy từ chính cookie đang dùng — thiếu uifid là
        bị chặn trước cả khi Douyin nhìn tới chữ ký.
        """
        ab = _get_abogus()
        params = {**DOUYIN_BASE_PARAMS, **extra_params}
        if cookie:
            params.setdefault("uifid", "")
            params["uifid"] = params.get("uifid") or cookie_value(cookie, "UIFID")
            params["msToken"] = params.get("msToken") or cookie_value(cookie, "msToken")
        encoded = urlencode(params, safe="=", quote_via=quote)
        if ab:
            a_bogus = quote(ab.get_value(encoded, "GET"), safe="")
            return f"{api_url}?{encoded}&a_bogus={a_bogus}"
        return f"{api_url}?{encoded}"

    @staticmethod
    async def get_user_info(
        sec_user_id: str,
        cookie: str = "",
        proxy: str = None,
        reasons: list = None,
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
        }, cookie)

        try:
            async with httpx.AsyncClient(
                timeout=15, proxy=proxy, headers=headers, verify=False,
            ) as client:
                resp = await client.get(url)
            data = APIClient._read_douyin_json(resp, sec_user_id, reasons) or {}

            user = data.get("user")
            if not user:
                # API ký hay bị chặn — trang chia sẻ vẫn dựng sẵn hồ sơ.
                user = await APIClient._fetch_share_user(sec_user_id, cookie, proxy)
            if not user:
                logger.warning(f"No user data for {sec_user_id}")
                if reasons is not None:
                    reasons.append("không lấy được hồ sơ người dùng")
                return None
            web_rid = ""
            room_data_str = user.get("room_data")
            if room_data_str:
                try:
                    import json
                    room_data = json.loads(room_data_str)
                    web_rid = room_data.get("owner", {}).get("web_rid", "")
                except Exception:
                    pass

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
                "room_id": user.get("room_id", 0),
                "web_rid": web_rid,
            }
        except Exception as e:
            logger.error(f"User info API error: {e}")
            if reasons is not None:
                reasons.append(f"API hồ sơ lỗi: {e}")
            return None

    @staticmethod
    async def _fetch_share_user(
        sec_user_id: str,
        cookie: str = "",
        proxy: str = None,
    ) -> Optional[dict]:
        """Hồ sơ người dùng từ trang chia sẻ (không cần chữ ký).

        Trang này chỉ dựng sẵn phần hồ sơ; danh sách tác phẩm vẫn do JS tải sau
        nên không lấy được ở đây.
        """
        def pick(html: str) -> tuple:
            m = _ROUTER_DATA_RE.search(html or "")
            if not m:
                return None, ""
            try:
                data = json.loads(m.group(1))
            except Exception:
                return None, ""
            for value in (data.get("loaderData") or {}).values():
                if not isinstance(value, dict):
                    continue
                res = value.get("userInfoRes")
                if isinstance(res, dict) and res.get("user_info"):
                    return res["user_info"], ""
            return None, ""

        user, _notice = await APIClient._read_share_page(
            DOUYIN_SHARE_USER.format(sec_user_id), cookie, proxy, pick,
        )
        return user

    @staticmethod
    async def get_user_posts(
        sec_user_id: str,
        cookie: str = "",
        proxy: str = None,
        max_pages: int = 5,
        count: int = 18,
        reasons: list = None,
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
            }, cookie)

            try:
                async with httpx.AsyncClient(
                    timeout=15, proxy=proxy, headers=headers, verify=False,
                ) as client:
                    resp = await client.get(url)
                data = APIClient._read_douyin_json(resp, sec_user_id, reasons)
                if data is None:
                    break

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
                if reasons is not None:
                    reasons.append(f"API danh sách tác phẩm lỗi: {e}")
                break

        return all_videos

    @staticmethod
    def _parse_douyin_aweme(detail: dict) -> Optional[VideoInfo]:
        """Parse a single aweme item (API ký hoặc trang chia sẻ — cùng khuôn)."""
        try:
            info = VideoInfo()
            info.id = detail.get("aweme_id", "")
            info.platform = "douyin"
            info.title = detail.get("desc", "")[:200]
            info.raw_data = detail

            # Author
            author = detail.get("author", {})
            info.author = author.get("nickname", "")
            info.author_id = author.get("uid") or author.get("sec_uid", "")

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
                # Không dùng download_url_list: đó là bản Douyin đóng logo chìm
                # (tplv-dy-water-v2); url_list mới là ảnh sạch.
                first_img = detail["images"][0] or {}
                info.width = first_img.get("width", 0)
                info.height = first_img.get("height", 0)
                for img in detail["images"]:
                    img = img or {}
                    # Ảnh động (实况/live photo): Douyin trả kèm một mp4 ngắn, lấy mp4.
                    live = (img.get("video") or {}).get("play_addr") or {}
                    live_urls = live.get("url_list") or []
                    urls = img.get("url_list") or []
                    if live_urls:
                        info.download_urls.append(live_urls[-1])
                    elif urls:
                        info.download_urls.append(urls[-1])
                info.download_url = info.download_urls[0] if info.download_urls else ""
                first = (detail["images"][0] or {}).get("url_list") or []
                info.cover_url = first[-1] if first else info.download_url
            else:
                info.type = "video"
                video = detail.get("video", {})
                duration_ms = video.get("duration", 0)
                s = duration_ms // 1000
                info.duration = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

                bit_rate = video.get("bit_rate", [])
                play_addr = {}
                if bit_rate:
                    sorted_br = sorted(
                        bit_rate,
                        key=lambda x: max(
                            x.get("play_addr", {}).get("height", 0),
                            x.get("play_addr", {}).get("width", 0),
                        ),
                    )
                    play_addr = sorted_br[-1].get("play_addr", {})
                elif video.get("play_addr"):
                    play_addr = video["play_addr"]

                urls = play_addr.get("url_list") or []
                raw_url = urls[0] if urls else ""
                info.download_url = no_watermark(raw_url)
                # Giữ luôn bản gốc (có logo) làm phương án hai nếu link sạch hỏng.
                info.download_urls = [u for u in (info.download_url, raw_url) if u]
                # Trang chia sẻ không gắn kích thước vào play_addr, lấy ở cấp video.
                info.width = play_addr.get("width") or video.get("width", 0)
                info.height = play_addr.get("height") or video.get("height", 0)

                cover = video.get("cover") or {}
                cover_urls = cover.get("url_list") or []
                info.cover_url = cover_urls[-1] if cover_urls else ""

            # Music
            music = detail.get("music") or {}
            if music:
                info.music_title = music.get("title", "")
                play_url = music.get("play_url")
                if isinstance(play_url, dict):
                    murls = play_url.get("url_list") or []
                    info.music_url = murls[0] if murls else ""
                elif isinstance(play_url, str):
                    info.music_url = play_url

            return info
        except Exception as e:
            logger.warning(f"Failed to parse aweme: {e}")
            return None
