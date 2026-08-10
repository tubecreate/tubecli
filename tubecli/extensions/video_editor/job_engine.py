import os
import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from tubecli.config import DATA_DIR
import traceback

logger = logging.getLogger("video_editor.job_engine")

JOBS_FILE = os.path.join(DATA_DIR, "video_editor", "processing_jobs.json")

class ProcessingJob:
    def __init__(self, data: dict):
        self.id: str = data.get("id", str(uuid.uuid4()))
        self.status: str = data.get("status", "queued")
        self.progress: int = data.get("progress", 0)
        self.source_url: str = data.get("source_url", "")
        self.source_file: str = data.get("source_file", "")
        self.background: dict = data.get("background", {"type": "color", "value": "#000000"})
        self.output_file: str = data.get("output_file", "")
        self.person_segments: List[List[float]] = data.get("person_segments", [])
        self.settings: dict = data.get("settings", {"trim_no_person": True})
        self.created_at: str = data.get("created_at", datetime.now().isoformat())
        self.completed_at: str = data.get("completed_at", "")
        self.error: Optional[str] = data.get("error", None)

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "background": self.background,
            "output_file": self.output_file,
            "person_segments": self.person_segments,
            "settings": self.settings,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }

class JobEngine:
    def __init__(self):
        self._jobs: Dict[str, ProcessingJob] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._workspace = os.path.join(DATA_DIR, "video_editor", "processing")
        os.makedirs(self._workspace, exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    arr = json.load(f)
                    for item in arr:
                        job = ProcessingJob(item)
                        # Reset stuck jobs
                        if job.status not in ["done", "failed"]:
                            job.status = "queued"
                        self._jobs[job.id] = job
            except Exception as e:
                logger.error(f"Error loading jobs: {e}")

    def _save(self):
        os.makedirs(os.path.dirname(JOBS_FILE), exist_ok=True)
        try:
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in self._jobs.values()], f, indent=2)
        except Exception as e:
            logger.error(f"Error saving jobs: {e}")

    def create_job(self, source_url: str, background: dict = None, settings: dict = None) -> ProcessingJob:
        if background is None:
            background = {"type": "color", "value": "#00FF00"}
        if settings is None:
            settings = {"trim_no_person": True}
            
        job = ProcessingJob({
            "source_url": source_url,
            "background": background,
            "settings": settings
        })
        self._jobs[job.id] = job
        self._save()
        return job
        
    def get_job(self, job_id: str) -> Optional[ProcessingJob]:
        # Exact match first
        if job_id in self._jobs:
            return self._jobs[job_id]
        # Prefix match (e.g. first 8 chars)
        for full_id, job in self._jobs.items():
            if full_id.startswith(job_id):
                return job
        return None

    def list_jobs(self) -> List[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def delete_job(self, job_id: str) -> bool:
        # Exact match first
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        # Prefix match
        for full_id in list(self._jobs.keys()):
            if full_id.startswith(job_id):
                del self._jobs[full_id]
                self._save()
                return True
        return False

    def start(self):
        if self._running: return
        self._running = True
        self._task = asyncio.create_task(self._process_queue())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _process_queue(self):
        while self._running:
            for job in list(self._jobs.values()):
                if job.status == "queued":
                    await self._process_job(job)
            await asyncio.sleep(5)

    async def _download_video(self, url: str, output_path: str) -> str:
        """Download video using TubeCLI douyin_downloader API first, fallback to yt-dlp."""
        import httpx
        import shutil

        # Check if URL is youtube
        is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()

        # --- Try douyin_downloader API first (handles cookies properly for tiktok/douyin) ---
        if not is_youtube:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    # Step 1: Start download
                    dl_resp = await client.post(
                        "http://localhost:5295/api/v1/douyin_downloader/download",
                        json={"url": url}
                    )
                    if dl_resp.status_code == 200:
                        dl_data = dl_resp.json()
                        task_id = dl_data.get("task_id", "")
                        save_path = dl_data.get("save_path", "")

                        # Step 2: Poll until done
                        for _ in range(60):  # max 2 minutes
                            await asyncio.sleep(2)
                            st_resp = await client.get(
                                f"http://localhost:5295/api/v1/douyin_downloader/status/{task_id}"
                            )
                            if st_resp.status_code == 200:
                                st_data = st_resp.json()
                                # Response: {"success": true, "data": {"status": "done", "filename": "...", ...}}
                                task_info = st_data.get("data", st_data)
                                status = task_info.get("status", "")
                                if status == "done":
                                    # Construct file path
                                    final_path = save_path
                                    if not final_path or not os.path.exists(final_path):
                                        # Try from data dir + filename
                                        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
                                        fname = task_info.get("filename", "")
                                        if fname:
                                            final_path = os.path.join(data_dir, "downloads", fname)
                                    
                                    if final_path and os.path.exists(final_path):
                                        shutil.copy2(final_path, output_path)
                                        logger.info(f"Downloaded via API: {final_path} -> {output_path}")
                                        return output_path
                                    else:
                                        raise RuntimeError(f"Download done but file not found: {final_path}")
                                elif status == "error":
                                    raise RuntimeError(f"API download error: {task_info.get('error', '')[:300]}")
                        else:
                            raise RuntimeError("API download timeout (2 min)")
            except Exception as e:
                logger.warning(f"douyin_downloader API failed, falling back to yt-dlp: {e}")

        # --- Fallback: yt-dlp ---
        logger.info(f"Downloading with yt-dlp: {url}")
        cmd = ["yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4", "-o", output_path, url]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"Download failed: {stderr.decode('utf-8')[:500]}")
        
        # yt-dlp might download format pieces and merge them. The final file should match output_path.
        if not os.path.exists(output_path):
            raise RuntimeError(f"yt-dlp completed but output file not found at {output_path}")
            
        return output_path

    @staticmethod
    def _local(module_name: str, filename: str):
        """Import a sibling module by path.

        Bare imports (`from video_matting import ...`) resolve against sys.path,
        which every other installed extension also contributes to — the same
        collision that made one extension load another's `nodes` package. Here it
        matters twice over: background removal needs RobustVideoMatting, which is
        GPL-3.0 and therefore NOT bundled with this MIT project, so this import
        is also the point where that absence must be reported clearly rather than
        as a bare ModuleNotFoundError.
        """
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    async def _process_job(self, job: ProcessingJob):
        try:
            try:
                _vm = self._local("video_editor_matting", "video_matting.py")
                detect_person_segments = _vm.detect_person_segments
                remove_background = _vm.remove_background
                composite_background = _vm.composite_background
            except Exception as _e:
                raise RuntimeError(
                    "Background removal needs the full Video Editor extension "
                    "(torch + RobustVideoMatting, ~29 MB, GPL-3.0 and so not "
                    "bundled with TubeCLI). Install 'Video Editor' from the "
                    f"Marketplace to enable it. Underlying error: {_e}"
                )
            _ve = self._local("video_editor_engine", "video_engine.py")
            trim = _ve.trim
            
            # --- 1. Download or use local file ---
            job.status = "downloading"
            job.progress = 5
            self._save()
            
            raw_video = os.path.join(self._workspace, f"{job.id}_raw.mp4")
            
            # Check if source_url is actually a local file path
            if os.path.exists(job.source_url):
                import shutil
                shutil.copy2(job.source_url, raw_video)
                logger.info(f"Using local file: {job.source_url}")
            else:
                await self._download_video(job.source_url, raw_video)
            
            job.source_file = raw_video
            
            # --- 2. Person Detection ---
            job.status = "detecting"
            job.progress = 20
            self._save()
            
            segments = []
            if job.settings.get("trim_no_person", True):
                segments = await asyncio.to_thread(detect_person_segments, raw_video, 1.0)
                job.person_segments = segments
                
            input_for_matting = raw_video
            
            # --- 3. Trimming ---
            if job.settings.get("trim_no_person", True) and segments:
                job.status = "trimming"
                job.progress = 30
                self._save()
                
                # Get the largest continuous segment for simplicity in this version
                # Alternatively, merge all segments (needs video_engine.merge)
                # Let's take the first long segment as example if multiple exist.
                longest_seg = max(segments, key=lambda x: x[1] - x[0])
                trimmed_video = os.path.join(self._workspace, f"{job.id}_trimmed.mp4")
                
                await trim(raw_video, str(longest_seg[0]), str(longest_seg[1]), trimmed_video)
                input_for_matting = trimmed_video
                
            # --- 4. Matting (Remove Background) ---
            job.status = "matting"
            job.progress = 40
            self._save()
            
            greenscreen_video = os.path.join(self._workspace, f"{job.id}_gs.mp4")
            await asyncio.to_thread(remove_background, input_for_matting, greenscreen_video)
            
            # --- 5. Compositing ---
            job.status = "compositing"
            job.progress = 80
            self._save()
            
            bg_path = job.background.get("path")
            if not bg_path:
                raise ValueError("No background path provided")
                
            output_dir = os.path.join(DATA_DIR, "video_editor", "exports")
            os.makedirs(output_dir, exist_ok=True)
            final_video = os.path.join(output_dir, f"{job.id}_final.mp4")
            
            # If the user just wants a green screen (default) and we already have it from matting
            if bg_path.upper() == "#00FF00":
                import shutil
                shutil.copy2(greenscreen_video, final_video)
                logger.info("Background is green screen, skip compositing.")
            elif bg_path.startswith("#"):
                # Use a solid color generator instead of treating bg_path as file
                # e.g., bg_path = "#ff0000" -> color=red
                _run_ffmpeg_async = self._local(
                    "video_editor_matting", "video_matting.py")._run_ffmpeg_async
                color_hex = bg_path.lstrip("#")
                
                # Use ffmpeg color source overlay
                # Simple ffmpeg: generate color, scale to foreground, overlay
                filter_complex = (
                    f"color=c=0x{color_hex}:s=1280x720[bg];"
                    f"[0:v]chromakey=0x78FF9B:0.12:0.05,despill=green[fg];"
                    f"[bg][fg]overlay=shortest=1,format=yuv420p[outv]"
                )
                args = [
                    "-y", "-i", greenscreen_video,
                    "-f", "lavfi", "-i", "color=c=black:r=30", # dummy input
                    "-filter_complex", filter_complex,
                    "-map", "[outv]", "-map", "0:a?",
                    "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", final_video
                ]
                await _run_ffmpeg_async(args, timeout=1200)
            else:
                await composite_background(greenscreen_video, bg_path, final_video)
                
            job.output_file = final_video
            
            # Cleanup intermediate files
            for f in [raw_video, trimmed_video if 'trimmed_video' in locals() else None, greenscreen_video]:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception as e:
                        logger.warning(f"Could not remove intermediate file {f}: {e}")
            
            job.status = "done"
            job.progress = 100
            job.completed_at = datetime.now().isoformat()
            self._save()
            
            # Notify Telegram
            self._notify_telegram(job)
            
        except Exception as e:
            job.status = "failed"
            job.error = str(e) + "\n" + traceback.format_exc()
            self._save()
            logger.error(f"Job {job.id} failed: {e}")
            
    def _notify_telegram(self, job: ProcessingJob):
        try:
            from tubecli.core.telegram_listener import GlobalBot
            import asyncio
            
            async def send():
                # Assuming you set up admin id or standard channel somewhere
                admin_id = os.environ.get("ADMIN_TELEGRAM_ID")
                if admin_id and GlobalBot and GlobalBot.application:
                    await GlobalBot.application.bot.send_message(
                        chat_id=admin_id,
                        text=f"✅ Video processing completed!\nID: {job.id}\nOriginal: {job.source_url}\nSaved to: {job.output_file}"
                    )
            
            asyncio.create_task(send())
        except Exception as e:
            logger.warning(f"Failed to notify Telegram: {e}")

global_job_engine = JobEngine()
