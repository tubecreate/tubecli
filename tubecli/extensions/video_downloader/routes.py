"""
Video Downloader API Routes — powered by yt-dlp.
Supports YouTube, TikTok, Twitch, Instagram, and 50+ platforms.
"""
import os
import re
import sys
import glob
import shutil
import asyncio
import logging
import subprocess
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("video_downloader.routes")

router = APIRouter(prefix="/api/v1/ytdl", tags=["Video Downloader (yt-dlp)"])

_ext_dir = os.path.dirname(os.path.abspath(__file__))

# ── UI page router (no prefix, gets included into main router) ──
_page_router = APIRouter(tags=["Video Downloader UI"])


@_page_router.get("/video-downloader", include_in_schema=False, response_class=HTMLResponse)
async def video_downloader_page():
    """Serve the Video Downloader HTML page."""
    html_path = os.path.join(_ext_dir, "static", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Video Downloader – HTML not found</h1>", status_code=404)


@_page_router.get("/video-downloader-static/{filepath:path}", include_in_schema=False)
async def video_downloader_static(filepath: str):
    """Serve static files for the Video Downloader UI."""
    file_path = os.path.join(_ext_dir, "static", filepath)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(404, f"Static file not found: {filepath}")



# ── Models ──

class VideoInfoRequest(BaseModel):
    url: str
    proxy: Optional[str] = None


class VideoDownloadRequest(BaseModel):
    url: str
    format: str = "mp4"         # mp4, mp3, webm
    quality: str = "720p"       # 360p, 480p, 720p, 1080p, best
    proxy: Optional[str] = None
    title: Optional[str] = None # custom filename
    save_dir: Optional[str] = None # custom save directory
    filename_template: Optional[str] = None # custom yt-dlp output template


class VideoSearchRequest(BaseModel):
    query: str
    platform: str = "youtube"   # youtube, soundcloud
    limit: int = 10
    proxy: Optional[str] = None


# ── Helpers ──

def _get_download_dir():
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    dl_dir = os.path.join(data_dir, "ytdl_downloads")
    os.makedirs(dl_dir, exist_ok=True)
    return dl_dir


# ── Settings (shared with douyin_downloader) ──

_settings_cache = None

def _get_settings():
    """Get extension settings from shared downloader_settings.json."""
    global _settings_cache
    if _settings_cache is None:
        import json as _json
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        path = os.path.join(data_dir, "downloader_settings.json")
        _settings_cache = {
            "cookie_youtube": "",
            "cookie_douyin": "",
            "cookie_tiktok": "",
            "cookies_from_browser": "",  # e.g. "chrome", "firefox", "edge"
            "proxy": "",
        }
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    _settings_cache.update(_json.load(f))
            except Exception:
                pass
    return _settings_cache


def _save_settings(settings):
    """Save settings to shared downloader_settings.json."""
    import json as _json
    global _settings_cache
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "downloader_settings.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(settings, f, indent=2, ensure_ascii=False)
    _settings_cache = settings


def _parse_cookie_input(value: str) -> str:
    """Auto-detect cookie format (JSON array, JSON object, or plain string) and normalize."""
    import json as _json
    value = value.strip()
    if not value:
        return ""
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
    except Exception:
        pass
    return value


def _get_cookie_file(url: str) -> str:
    """Create a Netscape-format cookie file for yt-dlp from stored cookie strings.
    Returns the file path, or None if no cookies configured."""
    settings = _get_settings()
    
    # Determine which cookie to use based on URL
    cookie_str = ""
    domain = ".youtube.com"
    if "youtube.com" in url or "youtu.be" in url:
        cookie_str = settings.get("cookie_youtube", "")
        domain = ".youtube.com"
    elif "tiktok.com" in url:
        cookie_str = settings.get("cookie_tiktok", "")
        domain = ".tiktok.com"
    elif "douyin.com" in url or "iesdouyin.com" in url:
        cookie_str = settings.get("cookie_douyin", "")
        domain = ".douyin.com"
    else:
        # For other sites, try YouTube cookies as default
        cookie_str = settings.get("cookie_youtube", "")
    
    if not cookie_str:
        return None
    
    # Convert "key=val; key2=val2" to Netscape cookie file format
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    cookie_file = os.path.join(data_dir, "ytdl_cookies.txt")
    
    lines = ["# Netscape HTTP Cookie File", "# Generated by TubeCLI Video Downloader", ""]
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, val = pair.split("=", 1)
        # domain  includeSubdomains  path  secure  expiry  name  value
        lines.append(f"{domain}\tTRUE\t/\tTRUE\t2147483647\t{name.strip()}\t{val.strip()}")
    
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return cookie_file


def _ensure_deps():
    """Install yt-dlp and ffmpeg if not present."""
    deps_to_install = []
    if shutil.which("yt-dlp") is None:
        deps_to_install.append("yt-dlp")
    try:
        import imageio_ffmpeg
    except ImportError:
        deps_to_install.append("imageio-ffmpeg")
        
    if deps_to_install:
        logger.info(f"Installing missing downloader deps: {deps_to_install}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", *deps_to_install],
            capture_output=True, timeout=120,
        )


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()[:120] or "video"


def _get_ffmpeg_path():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg: return ffmpeg
    # tubecli knows extra install locations (and can repair PATH) — ask it
    # before falling back to the pip copy.
    try:
        from tubecli.extensions.video_studio.ffmpeg_utils import find_ffmpeg
        found = find_ffmpeg()
        if found: return found
    except Exception:
        pass
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _ffmpeg_location_for_ytdlp(ff_path):
    """What to hand yt-dlp as `ffmpeg_location`.

    MUST be the executable FILE, not its directory. Given a directory, yt-dlp
    looks inside for a file literally named ffmpeg.exe — and the copy that
    ships with imageio-ffmpeg is called ffmpeg-win-x86_64-v7.1.exe, so the
    lookup failed and yt-dlp aborted with "You have requested merging of
    multiple formats but ffmpeg is not installed" while ffmpeg sat right there.
    Given the file, yt-dlp maps it to the ffmpeg slot whatever it is named.
    """
    return ff_path if ff_path and os.path.isfile(ff_path) else None


def _ytdlp_can_merge(ff_path):
    """Ask yt-dlp itself whether it can merge with this location.

    Requesting bestvideo+bestaudio when the merge is impossible turns a
    working download into a hard failure, so the format choice below is made
    from the real answer rather than from "some ffmpeg path exists".
    """
    try:
        import yt_dlp
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

        opts = {"quiet": True, "no_warnings": True}
        loc = _ffmpeg_location_for_ytdlp(ff_path)
        if loc:
            opts["ffmpeg_location"] = loc
        return bool(FFmpegPostProcessor(yt_dlp.YoutubeDL(opts)).available)
    except Exception as e:
        logger.warning(f"could not probe ffmpeg for yt-dlp: {e}")
        return False


def _get_ytdlp_cmd():
    """Return yt-dlp command, falling back to 'python -m yt_dlp' if not in PATH."""
    # First try direct command
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    # Fallback: run as Python module (works even if not in PATH after pip install)
    try:
        import yt_dlp  # noqa
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass
    # Last resort: Scripts/yt-dlp.exe (Windows)
    scripts_path = os.path.join(os.path.dirname(sys.executable), "Scripts", "yt-dlp.exe")
    if os.path.exists(scripts_path):
        return [scripts_path]
    return None

# ── Routes ──

@router.get("/status")
async def ytdl_status():
    """Check if yt-dlp and ffmpeg are installed and return versions."""
    try:
        ydl_res = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        ff_path = _get_ffmpeg_path()
        return {
            "status": "success",
            "installed": ydl_res.returncode == 0,
            "version": ydl_res.stdout.strip() if ydl_res.returncode == 0 else None,
            "ffmpeg_available": ff_path is not None
        }
    except Exception:
        return {"status": "success", "installed": False, "version": None, "ffmpeg_available": False}


@router.get("/check-update")
async def ytdl_check_update():
    """Check if a newer version of yt-dlp is available."""
    import concurrent.futures

    def _check():
        current_version = None
        latest_version = None

        # Get installed version
        try:
            res = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                current_version = res.stdout.strip()
        except Exception:
            pass

        # Method 1: pip index versions (fast, local, no network needed for cached)
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "yt-dlp"],
                capture_output=True, text=True, timeout=15
            )
            if res.returncode == 0 and res.stdout:
                # Output: "yt-dlp (2026.03.25)\n  Available versions: 2026.03.25, ..."
                import re
                m = re.search(r'yt-dlp\s*\(([^)]+)\)', res.stdout)
                if m:
                    latest_version = m.group(1).strip()
        except Exception:
            pass

        # Method 2: GitHub API (if pip index failed)
        if not latest_version:
            try:
                import urllib.request, json as _json
                req = urllib.request.Request(
                    "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                    headers={"User-Agent": "TubeCLI/1.0"}
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read().decode())
                    tag = data.get("tag_name", "")
                    latest_version = tag.strip()
            except Exception as e:
                logger.warning(f"GitHub API check failed: {e}")

        # Method 3: PyPI fallback
        if not latest_version:
            try:
                import urllib.request, json as _json
                req = urllib.request.Request(
                    "https://pypi.org/pypi/yt-dlp/json",
                    headers={"User-Agent": "TubeCLI/1.0"}
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read().decode())
                    latest_version = data.get("info", {}).get("version")
            except Exception as e:
                logger.warning(f"PyPI check failed: {e}")

        has_update = False
        if current_version and latest_version:
            has_update = current_version.strip() != latest_version.strip()

        return {
            "status": "success",
            "current_version": current_version,
            "latest_version": latest_version,
            "has_update": has_update,
        }

    # Run in thread to avoid blocking async loop
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _check)
    return result


@router.post("/update")
async def ytdl_update():
    """Update yt-dlp to the latest version via pip."""
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True, text=True, timeout=120
        )
        if res.returncode == 0:
            # Get new version after upgrade
            ver_res = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
            new_version = ver_res.stdout.strip() if ver_res.returncode == 0 else "unknown"
            return {
                "status": "success",
                "message": f"yt-dlp updated to {new_version}",
                "new_version": new_version,
                "pip_output": res.stdout.strip()[-500:] if res.stdout else ""
            }
        else:
            return {
                "status": "error",
                "message": f"pip upgrade failed (exit code {res.returncode})",
                "pip_output": (res.stderr or res.stdout or "")[:500]
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/info")
async def get_video_info(req: VideoInfoRequest):
    """Get video metadata without downloading."""
    await asyncio.to_thread(_ensure_deps)

    cmd = ["yt-dlp", "--dump-json", "--no-download"]
    if req.proxy:
        cmd.extend(["--proxy", req.proxy])
    cmd.append(req.url)

    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"yt-dlp error: {result.stderr[:500]}")

        import json
        info = json.loads(result.stdout.split("\n")[0])  # first JSON object

        return {
            "status": "success",
            "data": {
                "id": info.get("id"),
                "title": info.get("title"),
                "description": (info.get("description") or "")[:500],
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "thumbnail": info.get("thumbnail"),
                "webpage_url": info.get("webpage_url"),
                "platform": info.get("extractor_key", "Unknown"),
                "formats_count": len(info.get("formats", [])),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


DOWNLOAD_TASKS = {}


@router.post("/download")
async def download_video(req: VideoDownloadRequest, bg_tasks: BackgroundTasks):
    """Alias for download_async."""
    return await download_video_async(req, bg_tasks)

@router.post("/download_async")
async def download_video_async(req: VideoDownloadRequest, bg_tasks: BackgroundTasks):
    """Start an async download with yt-dlp and return a task_id."""
    await asyncio.to_thread(_ensure_deps)
    
    ytdlp_cmd = _get_ytdlp_cmd()
    if ytdlp_cmd is None:
        raise HTTPException(status_code=500, detail="yt-dlp not installed. Run: pip install yt-dlp")
        
    import uuid
    task_id = str(uuid.uuid4())[:8]
    DOWNLOAD_TASKS[task_id] = {
        "status": "downloading", 
        "progress": 0, 
        "speed": 0,
        "downloaded": 0,
        "total_size": 0,
        "filename": None, 
        "error": None
    }
    
    def run_download():
        dl_dir = _get_download_dir()
        if req.save_dir and req.save_dir.strip():
            custom_dir = req.save_dir.strip()
            if not os.path.exists(custom_dir):
                try: os.makedirs(custom_dir, exist_ok=True)
                except: pass
            if os.path.exists(custom_dir):
                dl_dir = custom_dir
                
        temp_dir = os.path.join(dl_dir, f".tmp_{task_id}")
        os.makedirs(temp_dir, exist_ok=True)
        try:
            import yt_dlp
            
            if req.filename_template and req.filename_template.strip():
                output_template = os.path.join(temp_dir, req.filename_template.strip())
            elif req.title and req.title.strip():
                title = _sanitize_filename(req.title)
                output_template = os.path.join(temp_dir, f"{title}.%(ext)s")
            else:
                output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")
                
            ydl_opts = {
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }
            
            ff_path = _get_ffmpeg_path()
            ff_loc = _ffmpeg_location_for_ytdlp(ff_path)
            if ff_loc:
                # The FILE, not its directory — see _ffmpeg_location_for_ytdlp.
                ydl_opts['ffmpeg_location'] = ff_loc
            # Trust yt-dlp's own verdict, not the mere existence of a path.
            can_merge = _ytdlp_can_merge(ff_path)
            if ff_path and not can_merge:
                logger.warning(
                    f"ffmpeg at {ff_path!r} is not usable by yt-dlp; "
                    f"falling back to a pre-merged format"
                )

            if req.format == "mp3":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                height = req.quality.replace("p", "")
                if can_merge:
                    # FFmpeg available: download separate streams and merge
                    if height == "best":
                        ydl_opts['format'] = 'bestvideo+bestaudio/best'
                    else:
                        ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
                    ydl_opts['merge_output_format'] = 'mp4'
                else:
                    # No usable FFmpeg: download a pre-merged format instead of
                    # asking for a merge that will abort the whole download.
                    if height == "best":
                        ydl_opts['format'] = 'best[ext=mp4]/best'
                    else:
                        ydl_opts['format'] = f'best[height<={height}][ext=mp4]/best[height<={height}]/best'
                
            if req.proxy:
                ydl_opts['proxy'] = req.proxy
            
            # Apply cookies
            settings = _get_settings()
            browser = settings.get("cookies_from_browser", "").strip()
            if browser:
                ydl_opts['cookiesfrombrowser'] = (browser,)
            else:
                cookie_file = _get_cookie_file(req.url)
                if cookie_file:
                    ydl_opts['cookiefile'] = cookie_file
                
            def progress_hook(d):
                if d['status'] == 'downloading':
                    try:
                        down_bytes = d.get('downloaded_bytes')
                        DOWNLOAD_TASKS[task_id]['downloaded'] = down_bytes if down_bytes is not None else 0
                        
                        tot_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                        DOWNLOAD_TASKS[task_id]['total_size'] = tot_bytes if tot_bytes is not None else 0
                        
                        speed = d.get('speed')
                        DOWNLOAD_TASKS[task_id]['speed'] = speed if speed is not None else 0
                        
                        percent_str = str(d.get('_percent_str', '0%')).strip()
                        import re
                        percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str).replace('%', '').strip()
                        if percent_str and percent_str != 'Unknown':
                            DOWNLOAD_TASKS[task_id]['progress'] = float(percent_str)
                    except Exception as ex:
                        pass
                elif d['status'] == 'finished':
                    DOWNLOAD_TASKS[task_id]['progress'] = 100
                    
            ydl_opts['progress_hooks'] = [progress_hook]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([req.url])
                
            # Find output file in temp dir
            downloaded_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
            if not downloaded_files:
                raise Exception("Download completed but output file not found.")
                
            final_filename = downloaded_files[0]
            temp_path = os.path.join(temp_dir, final_filename)
            final_path = os.path.join(dl_dir, final_filename)
            
            if os.path.exists(final_path):
                try: os.remove(final_path)
                except: pass
                    
            shutil.move(temp_path, final_path)
            
            DOWNLOAD_TASKS[task_id].update({
                "status": "done",
                "filename": final_filename,
                "progress": 100,
                "total_size": os.path.getsize(final_path)
            })
        except Exception as e:
            # yt-dlp colourises its errors; those escape codes used to travel
            # all the way into the chat bubble as literal "[0;31mERROR:[0m".
            msg = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', str(e)).strip()
            DOWNLOAD_TASKS[task_id]["status"] = "error"
            DOWNLOAD_TASKS[task_id]["error"] = msg
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    bg_tasks.add_task(run_download)
    return {"status": "success", "success": True, "task_id": task_id}


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in DOWNLOAD_TASKS:
        return {"success": False, "detail": "Task not found"}
    return {"success": True, "data": DOWNLOAD_TASKS[task_id]}



@router.post("/search")
async def search_videos(req: VideoSearchRequest):
    """Search for videos on YouTube or SoundCloud."""
    await asyncio.to_thread(_ensure_deps)

    try:
        import yt_dlp

        search_prefix = {
            "youtube": "ytsearch",
            "soundcloud": "scsearch",
        }.get(req.platform, "ytsearch")

        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "no_warnings": True,
        }
        if req.proxy:
            ydl_opts["proxy"] = req.proxy

        def do_search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(
                    f"{search_prefix}{req.limit}:{req.query}",
                    download=False,
                )
                return data.get("entries", []) if data else []

        entries = await asyncio.to_thread(do_search)

        results = []
        for entry in entries[:req.limit]:
            url = entry.get("url") or entry.get("webpage_url") or ""
            if not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={entry.get('id', '')}"
            results.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "url": url,
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader") or entry.get("channel"),
                "view_count": entry.get("view_count"),
                "thumbnail": entry.get("thumbnails", [{}])[0].get("url") if entry.get("thumbnails") else None,
            })

        return {"status": "success", "results": results, "count": len(results)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads")
async def list_downloads():
    """List all downloaded files."""
    dl_dir = _get_download_dir()
    files = []
    for f in os.listdir(dl_dir):
        fpath = os.path.join(dl_dir, f)
        if os.path.isfile(fpath):
            files.append({
                "filename": f,
                "size": os.path.getsize(fpath),
                "modified": os.path.getmtime(fpath),
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"status": "success", "files": files}


@router.get("/downloads/{filename}")
async def serve_download(filename: str):
    """Serve a downloaded file."""
    dl_dir = _get_download_dir()
    fpath = os.path.join(dl_dir, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fpath, filename=filename)


@router.delete("/downloads/{filename}")
async def delete_download(filename: str):
    """Delete a downloaded file."""
    dl_dir = _get_download_dir()
    fpath = os.path.join(dl_dir, filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        return {"status": "success", "message": f"Deleted {filename}"}
    raise HTTPException(status_code=404, detail="File not found")


# ── Settings API ──

@router.get("/settings")
async def ytdl_get_settings():
    """Get video downloader settings (cookies masked)."""
    s = _get_settings()
    def mask(v):
        if not v: return ""
        return "***" + v[-20:] if len(v) > 20 else "***"
    return {
        "status": "success",
        "data": {
            "cookie_youtube": mask(s.get("cookie_youtube", "")),
            "cookie_youtube_set": bool(s.get("cookie_youtube", "")),
            "cookie_douyin": mask(s.get("cookie_douyin", "")),
            "cookie_douyin_set": bool(s.get("cookie_douyin", "")),
            "cookie_tiktok": mask(s.get("cookie_tiktok", "")),
            "cookie_tiktok_set": bool(s.get("cookie_tiktok", "")),
            "cookies_from_browser": s.get("cookies_from_browser", ""),
            "proxy": s.get("proxy", ""),
        }
    }


class YtdlSettingsUpdate(BaseModel):
    cookie_youtube: Optional[str] = None
    cookie_douyin: Optional[str] = None
    cookie_tiktok: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    proxy: Optional[str] = None


@router.put("/settings")
async def ytdl_update_settings(req: YtdlSettingsUpdate):
    """Update video downloader settings."""
    settings = _get_settings()
    updates = req.model_dump(exclude_none=True)
    # Auto-convert cookie formats
    for key in ("cookie_youtube", "cookie_douyin", "cookie_tiktok"):
        if key in updates and updates[key]:
            updates[key] = _parse_cookie_input(updates[key])
    settings.update(updates)
    _save_settings(settings)
    return {"status": "success", "message": "Settings saved"}
