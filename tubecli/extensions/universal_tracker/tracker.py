import asyncio
import json
import os
import uuid
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import shlex

logger = logging.getLogger("UniversalTracker")

try:
    from tubecli.config import DATA_DIR
    from tubecli.extensions.multi_agents.extension import orchestrator
except ImportError:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
    orchestrator = None

DATA_FILE = os.path.join(str(DATA_DIR), "universal_tracker_jobs.json")

class TrackerJob:
    def __init__(self, data: dict):
        self.id: str = data.get("id", str(uuid.uuid4()))
        self.platform: str = data.get("platform", "youtube")
        self.url: str = data.get("url", "")
        self.interval_minutes: int = data.get("interval_minutes", 60)
        self.target_team_id: str = data.get("target_team_id", "")
        self.instruction: str = data.get("instruction", "")
        self.status: str = data.get("status", "active")
        self.last_checked_at: str = data.get("last_checked_at", "")
        self.next_check_at: str = data.get("next_check_at", "")
        self.last_item_id: str = data.get("last_item_id", "")
        
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "url": self.url,
            "interval_minutes": self.interval_minutes,
            "target_team_id": self.target_team_id,
            "instruction": self.instruction,
            "status": self.status,
            "last_checked_at": self.last_checked_at,
            "next_check_at": self.next_check_at,
            "last_item_id": self.last_item_id,
        }

class UniversalTracker:
    def __init__(self):
        self._jobs: Dict[str, TrackerJob] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._load()

    def _load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    arr = json.load(f)
                    for item in arr:
                        job = TrackerJob(item)
                        self._jobs[job.id] = job
            except Exception as e:
                logger.error(f"Error loading tracker jobs: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                data = [j.to_dict() for j in self._jobs.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracker jobs: {e}")

    def add_tracker(self, platform: str, url: str, interval_minutes: int = 60, target_team_id: str = "", instruction: str = "") -> TrackerJob:
        job = TrackerJob({
            "platform": platform,
            "url": url,
            "interval_minutes": interval_minutes,
            "target_team_id": target_team_id,
            "instruction": instruction,
            "next_check_at": (datetime.now() + timedelta(seconds=10)).isoformat() # Check shortly after adding
        })
        self._jobs[job.id] = job
        self._save()
        return job

    def remove_tracker(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False
        
    def list_trackers(self) -> List[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def start(self):
        if self._running: return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while self._running:
            now = datetime.now()
            for job in list(self._jobs.values()):
                if job.status != "active": continue
                
                try:
                    next_tk = datetime.fromisoformat(job.next_check_at) if job.next_check_at else now
                    if now >= next_tk:
                        await self._check_job(job)
                except Exception as e:
                    logger.error(f"Error checking tracker {job.id}: {e}")
            await asyncio.sleep(60)

    async def _check_job(self, job: TrackerJob):
        logger.info(f"[UniversalTracker] Polling {job.platform} : {job.url}")
        job.last_checked_at = datetime.now().isoformat()
        
        try:
            video_info = await self._fetch_latest_video(job.platform, job.url)
            if video_info and "id" in video_info:
                vid_id = video_info["id"]
                
                if not job.last_item_id:
                    # First run snapshot
                    job.last_item_id = vid_id
                    logger.info(f"Initialized snapshot for {job.url} with ID {vid_id}")
                elif job.last_item_id != vid_id:
                    # New video!
                    logger.info(f"🚀 NEW VIDEO DETECTED for {job.url}: {vid_id} - {video_info.get('title')}")
                    job.last_item_id = vid_id
                    
                    # Dispatch to Multi-Agent team
                    await self._dispatch_event(job, video_info)
        except Exception as e:
            logger.error(f"Scrape failed {job.url}: {e}")
            
        job.next_check_at = (datetime.now() + timedelta(minutes=job.interval_minutes)).isoformat()
        self._save()

    async def force_check_job(self, job_id: str) -> dict:
        """Force fetch and dispatch the latest video ignoring snapshot rules."""
        if job_id not in self._jobs:
            return {"success": False, "message": "Tracker ID không tồn tại."}

        job = self._jobs[job_id]
        logger.info(f"[UniversalTracker] Force polling {job.platform} : {job.url}")

        try:
            video_info = await self._fetch_latest_video(job.platform, job.url)
            if video_info and "id" in video_info:
                vid_id = video_info["id"]
                job.last_item_id = vid_id
                self._save()

                await self._dispatch_event(job, video_info)
                return {
                    "success": True,
                    "message": f"Đã phát hiện video '{video_info.get('title')}' và giao cho team xử lý!"
                }
            return {"success": False, "message": "Không tìm thấy video nào."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi khi lấy video: {str(e)}"}

    async def _fetch_latest_video(self, platform: str, url: str) -> dict:
        """Fetches the latest item using native API if possible, fallback to yt-dlp."""
        if platform == "sheets_bg_replace":
            try:
                # Expecting a public Google Sheets CSV URL, e.g.
                # https://docs.google.com/spreadsheets/d/1_abc.../export?format=csv
                # We fetch the CSV, read the last row that contains a youtube link
                import aiohttp
                import csv
                import io
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            reader = csv.reader(io.StringIO(text))
                            rows = list(reader)
                            # Assuming row format: YoutubeURL, BackgroundPath
                            if len(rows) > 1: # Ignore header maybe
                                last_row = rows[-1]
                                out_url = last_row[0]
                                bg_path = last_row[1] if len(last_row) > 1 else ""
                                return {
                                    "id": str(uuid.uuid4())[:8],
                                    "title": "Sheet Video",
                                    "url": out_url,
                                    "original_url": out_url,
                                    "background": bg_path
                                }
            except Exception as e:
                logger.error(f"Google Sheets fetch failed: {e}")
            return {}

        if platform == "douyin" or "douyin" in url:
            try:
                from tubecli.extensions.douyin_downloader.api_client import APIClient
                import re
                sec_user_id = None
                m = re.search(r"user/([a-zA-Z0-9_\-]+)", url)
                if m:
                    sec_user_id = m.group(1)
                else: 
                    # fallback raw parse
                    sec_user_id = url.split("?")[0].split("/")[-1].replace("MS4wLjABAAAA", "MS4wLjABAAAA")
                
                if sec_user_id:
                    posts = await APIClient.get_user_posts(sec_user_id, count=1)
                    if posts:
                        p = posts[0]
                        return {
                            "id": p.id,
                            "title": p.title,
                            "url": p.download_url,
                            "original_url": f"https://www.douyin.com/video/{p.id}"
                        }
            except Exception as e:
                logger.error(f"Native Douyin API failed: {e}")
        
        # Fallback to yt-dlp
        cmd = ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-items", "1", url]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0 and stdout:
            try:
                # Need to read the first non-empty JSON line
                lines = stdout.decode("utf-8").strip().split('\n')
                return json.loads(lines[0])
            except json.JSONDecodeError:
                return {}
        return {}

    async def _dispatch_event(self, job: TrackerJob, video_info: dict):
        if job.platform == "sheets_bg_replace":
            try:
                import sys
                ve_dir = "c:/tubecreate-vue/tubecli/data/extensions_external/video_editor"
                if ve_dir not in sys.path:
                    sys.path.insert(0, ve_dir)
                try:
                    from job_engine import global_job_engine
                    bg_path = video_info.get("background")
                    if not bg_path: bg_path = "c:/tubecreate-vue/tubecli/data/extensions_external/video_editor/data/backgrounds/church_bg.jpg"
                    new_job = global_job_engine.create_job(
                        source_url=video_info["url"],
                        background={"type": "image", "path": bg_path},
                        settings={"trim_no_person": True}
                    )
                    logger.info(f"Created Video Background Replace Job: {new_job.id}")
                except Exception as e:
                    logger.error(f"Failed to create job in job_engine: {e}")
            except Exception as e:
                logger.error(f"Failed to trigger sheets bg replace: {e}")
            return
            
        if not job.target_team_id:
            logger.info("No target_team_id provided, skipping dispatch.")
            return

        if not orchestrator:
            logger.error("Multi-Agents orchestrator not loaded!")
            return

        vid_url = video_info.get("original_url") or video_info.get("url")
        if not vid_url:
            vid_url = f"https://www.youtube.com/watch?v={video_info['id']}" if job.platform == "youtube" else ""
            
        task_msg = f"""🚨 NEW CONTENT EVENT DETECTED 🚨
Platform: {job.platform.upper()}
Source URL: {job.url}
Title: '{video_info.get('title', 'Unknown')}'
Video URL: {vid_url}
Instruction from user: {job.instruction}

Please execute your workflow on this new content immediately."""

        # Delegate the task asynchronously
        try:
            logger.info(f"Dispatched task to Team {job.target_team_id}")
            # orchestrator.delegate might trigger long blocking processes,
            # run it in background to avoid blocking the tracker loop
            asyncio.create_task(orchestrator.delegate(job.target_team_id, task_msg))
        except Exception as e:
            logger.error(f"Failed to delegate to team {job.target_team_id}: {e}")

universal_tracker_engine = UniversalTracker()
