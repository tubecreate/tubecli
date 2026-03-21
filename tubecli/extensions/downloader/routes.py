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

router = APIRouter(prefix="/api/v1/downloader", tags=["Downloader"])

# Lazy-initialized
_downloader = None
_settings = None


def _get_downloader():
    global _downloader
    if _downloader is None:
        from tubecli.extensions.downloader.file_downloader import FileDownloader
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
    url: str
    filename: Optional[str] = None
    proxy: Optional[str] = None


class SettingsUpdate(BaseModel):
    cookie_douyin: Optional[str] = None
    cookie_tiktok: Optional[str] = None
    proxy: Optional[str] = None


# === Routes ===

@router.post("/parse")
async def parse_link(req: ParseRequest):
    """Parse a TikTok/Douyin link and return video info."""
    from tubecli.extensions.downloader.link_parser import LinkParser
    from tubecli.extensions.downloader.api_client import APIClient

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None

    # Parse link — pass cookies for short URL resolution
    cookie_douyin = settings.get("cookie_douyin", "")
    platform, detail_id = await LinkParser.parse(req.url, proxy, cookie_douyin)
    if not platform or not detail_id:
        raise HTTPException(status_code=400, detail="Không thể phân tích link. Hãy nhập link đầy đủ (https://www.douyin.com/video/xxx) hoặc video ID.")

    # Get video info
    cookie = settings.get(f"cookie_{platform}", "")
    info = await APIClient.get_video_info(platform, detail_id, cookie, proxy)
    if not info:
        raise HTTPException(status_code=404, detail="Không thể lấy thông tin video. Cookie có thể đã hết hạn.")

    return {
        "success": True,
        "data": info.to_dict(),
    }


@router.post("/parse-batch")
async def parse_batch(req: ParseRequest):
    """Parse multiple links from text."""
    from tubecli.extensions.downloader.link_parser import LinkParser
    from tubecli.extensions.downloader.api_client import APIClient

    settings = _get_settings()
    proxy = req.proxy or settings.get("proxy") or None

    parsed = await LinkParser.parse_batch(req.url, proxy)
    results = []
    for item in parsed:
        cookie = settings.get(f"cookie_{item['platform']}", "")
        info = await APIClient.get_video_info(item["platform"], item["detail_id"], cookie, proxy)
        if info:
            results.append(info.to_dict())

    return {"success": True, "data": results}


@router.post("/parse-user")
async def parse_user(req: ParseRequest):
    """Parse a Douyin user profile link and get all their videos."""
    import re
    from tubecli.extensions.downloader.api_client import APIClient

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



@router.post("/download")
async def start_download(req: DownloadRequest):
    """Start downloading a video."""
    from tubecli.extensions.downloader.link_parser import LinkParser
    from tubecli.extensions.downloader.api_client import APIClient

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
            cookie = settings.get(f"cookie_{platform}", "")
            info = await APIClient.get_video_info(platform, detail_id, cookie, proxy)
            if info and info.download_url:
                download_url = info.download_url
                from tubecli.extensions.downloader.file_downloader import sanitize_filename
                filename = sanitize_filename(f"{info.author}_{info.title}") + ".mp4"

    task_id = str(uuid.uuid4())[:8]
    task = await dl.download(download_url, filename, task_id, proxy)

    return {
        "success": True,
        "task_id": task_id,
        "filename": task.filename,
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

