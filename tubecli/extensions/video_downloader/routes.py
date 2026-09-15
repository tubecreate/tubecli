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
            # YouTube đòi đăng nhập → lấy cookie từ hồ sơ browser TubeCLI ĐANG MỞ (core/youtube_cookies.py).
            "cookie_auto_browser": True,
            "cookie_profile": "",        # "" = tự chọn hồ sơ đang mở đã đăng nhập YouTube
            "ytdlp_auto_update": True,   # trước khi tải phụ đề/video: yt-dlp cũ thì tự cập nhật (core/ytdlp_manager.py)
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
    """yt-dlp: thiếu thì cài, cũ thì tự cập nhật (core/ytdlp_manager.py) — kiểm bằng THƯ VIỆN Python của máy chủ.

    Bản cũ dò `which yt-dlp`: dịch vụ systemd không có .venv/bin trong PATH, nên máy chủ CÓ yt-dlp vẫn báo
    "not installed" và pip chạy lại (tới 120 s) mỗi lần bấm Info/Tải (15/9/2026). Đang có lượt tải chạy thì chỉ
    cài khi thiếu — nâng cấp giữa chừng làm lượt tải đang nạp extractor hỏng."""
    from tubecli.core import ytdlp_manager as ym

    busy = any((t or {}).get("status") == "downloading" for t in DOWNLOAD_TASKS.values())
    res = ym.ensure(update=False if busy else None)
    if not _get_ffmpeg_path():
        ym.pip_install(["imageio-ffmpeg"])
    return res


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
    """Lệnh yt-dlp CỦA máy chủ: `python -m yt_dlp` (khớp thư viện đang dùng, không khoá yt-dlp.exe khi pip nâng
    cấp), rồi mới tới yt-dlp trên PATH. None = chưa cài."""
    from tubecli.core import ytdlp_manager as ym

    return ym.cli_command()


def _reload_ytdlp(old):
    """Module yt_dlp sau khi cập nhật (ytdlp_manager đã xoá bản cũ khỏi sys.modules)."""
    import importlib

    try:
        return importlib.import_module("yt_dlp")
    except Exception:      # noqa: BLE001
        return old

# ── Routes ──

@router.get("/status")
async def ytdl_status():
    """yt-dlp của máy chủ (thư viện Python, không phải lệnh trên PATH), FFmpeg, tuỳ chọn tự cập nhật."""
    from tubecli.core import ytdlp_manager as ym

    s = await asyncio.to_thread(ym.status)
    ff_path = await asyncio.to_thread(_get_ffmpeg_path)
    return {
        "status": "success",
        "installed": bool(s.get("installed")),
        "version": s.get("version") or None,
        "ffmpeg_available": ff_path is not None,
        "auto_update": bool(s.get("auto_update")),
        "latest_version": s.get("latest") or None,
        "last_error": s.get("last_error") or None,
    }


@router.post("/install")
async def ytdl_install():
    """Nút «Install yt-dlp» / «Install FFmpeg»: cài thứ còn thiếu vào Python của máy chủ — dùng được ngay, không restart."""
    from tubecli.core import ytdlp_manager as ym

    res = await asyncio.to_thread(ym.ensure, False)
    ff_note = ""
    if not await asyncio.to_thread(_get_ffmpeg_path):
        ok, tail = await asyncio.to_thread(ym.pip_install, ["imageio-ffmpeg"])
        ff_note = "" if ok else f"FFmpeg: {tail}"
    ff_path = await asyncio.to_thread(_get_ffmpeg_path)
    ready = bool(res.get("ok")) and ff_path is not None
    problems = [m for m in ((res.get("message") if not res.get("ok") else ""), ff_note) if m]
    if ff_path is None and not ff_note:
        problems.append("FFmpeg is still not available")
    return {
        "status": "success" if ready else "error",
        "installed": bool(res.get("ok")),
        "version": res.get("version") or None,
        "ffmpeg_available": ff_path is not None,
        "message": "; ".join(problems) if problems else (res.get("message") or "yt-dlp is ready"),
    }


@router.get("/check-update")
async def ytdl_check_update():
    """Bản yt-dlp mới nhất trên PyPI so với bản của máy chủ."""
    from tubecli.core import ytdlp_manager as ym

    cur = await asyncio.to_thread(ym.installed_version)
    latest = await asyncio.to_thread(ym.latest_version)
    return {
        "status": "success",
        "current_version": cur or None,
        "latest_version": latest or None,
        "has_update": bool(cur and latest and ym.is_newer(latest, cur)),
    }


@router.post("/update")
async def ytdl_update():
    """Nút «Update»: dò bản mới NGAY và nâng cấp (cài nếu thiếu) — dùng được ngay, không restart."""
    from tubecli.core import ytdlp_manager as ym

    before = await asyncio.to_thread(ym.installed_version)
    res = await asyncio.to_thread(ym.ensure, None, True)
    if not res.get("ok") or res.get("action") in ("update_failed", "install_failed"):
        return {"status": "error", "message": res.get("message") or "update failed",
                "new_version": res.get("version") or None}
    return {
        "status": "success",
        "message": res.get("message") or f"yt-dlp {res.get('version')} is the latest",
        "new_version": res.get("version") or None,
        "previous_version": before or None,
    }


@router.post("/info")
async def get_video_info(req: VideoInfoRequest):
    """Get video metadata without downloading."""
    await asyncio.to_thread(_ensure_deps)

    from tubecli.core import ytdlp_manager as _ym

    cmd = (_get_ytdlp_cmd() or ["yt-dlp"]) + _ym.cli_js_args() + ["--dump-json", "--no-download"]
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


def _download_with_browser_cookies(yt_dlp, ydl_opts, url, task=None):
    """Tải bằng yt-dlp, gỡ hai kiểu hỏng hay gặp của YouTube (15/9/2026):
      * yt-dlp cũ ("Unable to extract … latest version") → cập nhật NGAY rồi tải lại một lần;
      * YouTube đòi đăng nhập → cookie của hồ sơ browser TubeCLI ĐANG MỞ, không có thì mở ẨN một hồ sơ đang tắt cho
        Google làm mới cookie (tuỳ chọn «tự động lấy cookie từ browser» ở Settings).
    Lỗi khác, link không phải YouTube hay tuỳ chọn tắt → ném nguyên lỗi như trước. File cookie tạm xoá sau mỗi lượt."""
    def run(mod, opts):
        with mod.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        run(yt_dlp, ydl_opts)
        return
    except Exception as e:      # noqa: BLE001
        first = e
    from tubecli.core import youtube_cookies as yc
    from tubecli.core import ytdlp_manager as ym

    if ym.looks_outdated(str(first)):
        ens = ym.ensure(force_check=True)
        if ens.get("action") == "updated":
            yt_dlp = _reload_ytdlp(yt_dlp)
            if task is not None:
                task["ytdlp_updated"] = ens.get("version")
            try:
                run(yt_dlp, ydl_opts)
                return
            except Exception as e:      # noqa: BLE001
                first = e
    if not yc.is_blocked(str(first)) or not re.search(r"(youtube\.com|youtu\.be)/", str(url or "")):
        raise first
    st = yc.settings()
    if not st.get("auto"):
        raise first
    pl = yc.plan(st.get("profile") or "")
    tried, opened, log = [], [], []

    def with_cookies(name, att, source=""):
        opts = {k: v for k, v in ydl_opts.items() if k != "cookiesfrombrowser"}
        opts["cookiefile"] = att["cookiefile"]
        if att.get("proxy") and not opts.get("proxy"):
            opts["proxy"] = att["proxy"]
        if name not in tried:
            tried.append(name)
        try:
            run(yt_dlp, opts)
            if task is not None:
                task["cookie_source"] = source or f"profile:{name}"
            return True
        except Exception as e:      # noqa: BLE001
            first_line = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', str(e)).strip().splitlines()[0][:160] if str(e).strip() else "error"
            log.append(f"{source or 'profile:' + name}: {first_line}")
            logger.info(f"[ytdl] YouTube refused the cookies of {name}: {first_line}")
            return False
        finally:
            yc.remove_file(att["cookiefile"])

    for name in pl["live"][:yc.MAX_PROFILES]:
        att, why = yc.export_attempt(name)
        if not att:
            logger.info(f"[ytdl] cookie profile {name}: {why}")
            continue
        if with_cookies(name, att):
            return
    # Cookie ĐÃ LƯU của hồ sơ đang tắt (1–2 s, không mở browser) trước; YouTube vẫn từ chối mới mở ẩn để làm mới.
    for name in pl["closed"][:yc.MAX_PROFILES]:
        att, why = yc.stored_attempt(name)
        if not att:
            log.append(f"saved:{name}: {why}")
            continue
        if with_cookies(name, att, source=f"saved:{name}"):
            return
    for name in pl["closed"][:1]:
        att, why = yc.refresh_attempt(name)
        if not att:
            opened.append(f"{name} ({why})")
            continue
        if with_cookies(name, att):
            return
    details = f" Attempts: {'; '.join(log)}." if log else ""
    raise RuntimeError(f"{first} — {yc.blocked_hint(st, pl, tried, opened)}{details}")


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
            # yt-dlp cần JS runtime để giải thử thách YouTube, nhất là khi có cookie tài khoản (15/9/2026).
            from tubecli.core import ytdlp_manager as _ym
            ydl_opts.update(_ym.js_runtime_opts())

            _download_with_browser_cookies(yt_dlp, ydl_opts, req.url, DOWNLOAD_TASKS[task_id])
                
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
        from tubecli.core import ytdlp_manager as _ym
        ydl_opts.update(_ym.js_runtime_opts())

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

@router.get("/cookie-profiles")
async def ytdl_cookie_profiles():
    """Hồ sơ browser TubeCLI đã đăng nhập YouTube cho ô chọn ở Settings — chỉ tên + đang mở/proxy, KHÔNG có cookie."""
    from tubecli.core import youtube_cookies as yc

    items = await asyncio.to_thread(yc.candidates)
    return {"status": "success", "data": [{k: c.get(k) for k in ("name", "live", "youtube_session", "proxy")}
                                          for c in items]}


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
            "cookie_auto_browser": s.get("cookie_auto_browser", True) is not False,
            "cookie_profile": s.get("cookie_profile", ""),
            "ytdlp_auto_update": s.get("ytdlp_auto_update", True) is not False,
            "proxy": s.get("proxy", ""),
        }
    }


class YtdlSettingsUpdate(BaseModel):
    cookie_youtube: Optional[str] = None
    cookie_douyin: Optional[str] = None
    cookie_tiktok: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    cookie_auto_browser: Optional[bool] = None
    cookie_profile: Optional[str] = None
    ytdlp_auto_update: Optional[bool] = None
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
