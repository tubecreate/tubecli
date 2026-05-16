"""
Downloader API Routes
"""
import os
import uuid
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("downloader.routes")

router = APIRouter(prefix="/api/v1/douyin_downloader", tags=["Downloader"])

# Lazy-initialized
_downloader = None
_settings = None


def _get_downloader():
    global _downloader
    if _downloader is None:
        from tubecli.extensions.douyin_downloader.file_downloader import FileDownloader
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        dl_dir = os.path.join(data_dir, "downloads")
        _downloader = FileDownloader(dl_dir)
    return _downloader


def _get_settings():
    """Get extension settings."""
    global _settings
    if _settings is None:
        import json
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        path = os.path.join(data_dir, "downloader_settings.json")
        _settings = {
            "cookie_douyin": "",
            "cookie_tiktok": "",
            "proxy": "",
            "download_path": "downloads",
            "max_workers": 3,
            "chunk_size": 1048576,
        }
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _settings.update(json.load(f))
            except Exception:
                pass
    return _settings


# === Models ===

class ParseRequest(BaseModel):
    url: str
    proxy: Optional[str] = None


class DownloadRequest(BaseModel):
    url: str = "https://www.douyin.com/video/7615246740991511846"
    filename: Optional[str] = "aaa.mp4"
    proxy: Optional[str] = None


class SettingsUpdate(BaseModel):
    cookie_douyin: Optional[str] = None
    cookie_tiktok: Optional[str] = None
    proxy: Optional[str] = None


# === Routes ===

@router.post("/parse")
async def parse_link(req: ParseRequest):
    """Parse a TikTok/Douyin link and return video info."""
    try:
        from tubecli.extensions.douyin_downloader.link_parser import LinkParser
        from tubecli.extensions.douyin_downloader.api_client import APIClient
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Thiếu thư viện: {e}. Chạy: pip install gmssl httpx")

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None

    try:
        # Parse link — pass cookies for short URL resolution
        cookie_douyin = settings.get("cookie_douyin", "")
        platform, detail_id = await LinkParser.parse(req.url, proxy, cookie_douyin)
        if not platform or not detail_id:
            raise HTTPException(status_code=400, detail="Không thể phân tích link. Hãy nhập link đầy đủ (https://www.douyin.com/video/xxx) hoặc video ID.")

        # Get video info
        if platform == 'douyin_user':
            cookie = settings.get("cookie_douyin", "")
            user_info = await APIClient.get_user_info(detail_id, cookie, proxy)
            if not user_info:
                raise HTTPException(status_code=404, detail="Không thể lấy thông tin trang cá nhân. Cookie có thể đã hết hạn.")
            return {
                "success": True,
                "data": {"type": "user", **user_info},
            }

        cookie_key = platform
        if platform in ("douyin_live", "douyin_user_live"):
            cookie_key = "douyin"
        cookie = settings.get(f"cookie_{cookie_key}", "")
        info = await APIClient.get_video_info(platform, detail_id, cookie, proxy)
        if not info:
            if platform in ("douyin_live", "douyin_user_live"):
                raise HTTPException(status_code=404, detail="Không thể lấy thông tin live. Phòng live có thể đã kết thúc hoặc không tồn tại.")
            raise HTTPException(status_code=404, detail="Không thể lấy thông tin video. Cookie có thể đã hết hạn.")

        return {
            "success": True,
            "data": info.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"parse error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")


@router.post("/parse-batch")
async def parse_batch(req: ParseRequest):
    """Parse multiple links from text."""
    from tubecli.extensions.douyin_downloader.link_parser import LinkParser
    from tubecli.extensions.douyin_downloader.api_client import APIClient

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None

    parsed = await LinkParser.parse_batch(req.url, proxy)
    results = []
    for item in parsed:
        cookie_key = item["platform"]
        if cookie_key in ("douyin_live", "douyin_user_live"):
            cookie_key = "douyin"
        cookie = settings.get(f"cookie_{cookie_key}", "")
        info = await APIClient.get_video_info(item["platform"], item["detail_id"], cookie, proxy)
        if info:
            results.append(info.to_dict())

    return {"success": True, "data": results}


@router.post("/parse-user")
async def parse_user(req: ParseRequest):
    """Parse a Douyin user profile link and get all their videos."""
    import re
    from tubecli.extensions.douyin_downloader.api_client import APIClient

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None
    cookie = settings.get("cookie_douyin", "")

    url = req.url.strip()

    # Extract sec_user_id from URL like: https://www.douyin.com/user/MS4wLjABAAAA...
    sec_user_id = None
    m = re.search(r"douyin\.com/user/([a-zA-Z0-9_\-]+)", url)
    if m:
        sec_user_id = m.group(1)
    elif url.startswith("MS4") or (len(url) > 30 and not url.startswith("http")):
        # Direct sec_user_id
        sec_user_id = url

    if not sec_user_id:
        raise HTTPException(status_code=400, detail="Không tìm thấy sec_user_id. Hãy nhập link user Douyin (https://www.douyin.com/user/xxx).")

    try:
        # Get user info
        user_info = await APIClient.get_user_info(sec_user_id, cookie, proxy)

        # Get max_pages from request proxy field (hacky, but works)
        max_pages = 10  # default: 10 pages * 18 = ~180 videos

        # Get all user posts
        videos = await APIClient.get_user_posts(sec_user_id, cookie, proxy, max_pages=max_pages)

        return {
            "success": True,
            "user": user_info,
            "videos": [v.to_dict() for v in videos],
            "total": len(videos),
        }
    except Exception as e:
        logger.error(f"parse-user error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi phân tích user: {str(e)}. Kiểm tra thư viện gmssl đã cài chưa (pip install gmssl).")



@router.post("/download")
async def start_download(req: DownloadRequest):
    """Start downloading a video."""
    from tubecli.extensions.douyin_downloader.link_parser import LinkParser
    from tubecli.extensions.douyin_downloader.api_client import APIClient

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None
    dl = _get_downloader()

    # If URL is a direct download URL (starts with http and has video/media in it)
    download_url = req.url
    filename = req.filename or "video.mp4"

    # If it's a TikTok/Douyin link, parse it first
    if "douyin.com" in req.url or "tiktok.com" in req.url or "iesdouyin.com" in req.url:
        platform, detail_id = await LinkParser.parse(req.url, proxy)
        if platform and detail_id:
            cookie_key = platform
            if platform in ("douyin_live", "douyin_user_live"):
                cookie_key = "douyin"
            cookie = settings.get(f"cookie_{cookie_key}", "")
            info = await APIClient.get_video_info(platform, detail_id, cookie, proxy)
            if info and info.download_url:
                download_url = info.download_url
                from tubecli.extensions.douyin_downloader.file_downloader import sanitize_filename
                filename = sanitize_filename(f"{info.author}_{info.title}") + ".mp4"

    task_id = str(uuid.uuid4())[:8]
    
    # Add Referer header for Douyin/TikTok CDNs to avoid 404/403 errors
    headers = {}
    dl_lower = download_url.lower()
    req_lower = req.url.lower()
    if "douyin.com" in req_lower or "iesdouyin.com" in req_lower or any(d in dl_lower for d in ["zjcdn.com", "bytecdn.cn", "douyinvod.com", "douyincdn.com", "amemv.com", "huoshan.com"]):
        headers["Referer"] = "https://www.douyin.com/"
    elif "tiktok.com" in req_lower or any(d in dl_lower for d in ["tiktokcdn.com", "tiktokv.com"]):
        headers["Referer"] = "https://www.tiktok.com/"

    task = await dl.download(download_url, filename, task_id, proxy, headers=headers)

    return {
        "success": True,
        "task_id": task_id,
        "filename": task.filename,
        "save_path": task.save_path,
        "original_url": req.url,
    }


@router.get("/status/{task_id}")
async def get_status(task_id: str):
    """Get download progress."""
    dl = _get_downloader()
    task = dl.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": task.to_dict()}


@router.get("/history")
async def get_history():
    """List downloaded files."""
    dl = _get_downloader()
    return {"success": True, "data": dl.get_history()}


@router.delete("/history/{filename}")
async def delete_download(filename: str):
    """Delete a downloaded file."""
    dl = _get_downloader()
    if dl.delete_file(filename):
        return {"success": True, "message": "Đã xóa"}
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/file/{filename}")
async def serve_file(filename: str):
    """Serve a downloaded file."""
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    path = os.path.join(data_dir, "downloads", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)



@router.get("/settings")
async def get_settings():
    """Get downloader settings."""
    s = _get_settings()
    # Mask cookies for display
    return {
        "success": True,
        "data": {
            "cookie_douyin": ("***" + s.get("cookie_douyin", "")[-20:]) if s.get("cookie_douyin") else "",
            "cookie_tiktok": ("***" + s.get("cookie_tiktok", "")[-20:]) if s.get("cookie_tiktok") else "",
            "proxy": s.get("proxy", ""),
        },
    }


def _parse_cookie_input(value: str) -> str:
    """Auto-detect cookie format and convert to string.
    Supports:
      - JSON array: [{"name":"key","value":"val"}, ...]  (browser extension export)
      - JSON object: {"url":"...","cookies":[...]}       (full export with url)
      - Plain string: key=val; key2=val2                 (direct cookie string)
    """
    import json as _json
    value = value.strip()
    if not value:
        return ""
    # Try JSON parse
    try:
        parsed = _json.loads(value)
        cookies_list = None
        if isinstance(parsed, list):
            cookies_list = parsed
        elif isinstance(parsed, dict) and "cookies" in parsed:
            cookies_list = parsed["cookies"]
        if cookies_list and isinstance(cookies_list, list):
            parts = []
            for c in cookies_list:
                name = c.get("name", "").strip()
                val = c.get("value", "")
                if name:
                    parts.append(f"{name}={val}")
            return "; ".join(parts)
    except (_json.JSONDecodeError, TypeError, AttributeError):
        pass
    # Already a plain cookie string
    return value


@router.put("/settings")
async def update_settings(req: SettingsUpdate):
    """Update downloader settings."""
    import json
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    path = os.path.join(data_dir, "downloader_settings.json")
    settings = _get_settings()
    updates = req.model_dump(exclude_none=True)
    # Auto-convert cookie formats
    for key in ("cookie_douyin", "cookie_tiktok"):
        if key in updates and updates[key]:
            updates[key] = _parse_cookie_input(updates[key])
    settings.update(updates)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    global _settings
    _settings = settings
    return {"success": True, "message": "Đã lưu cài đặt"}

