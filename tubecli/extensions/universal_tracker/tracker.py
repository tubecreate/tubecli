import asyncio
import json
import os
import uuid
import logging
import time
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger("UniversalTracker")

try:
    from tubecli.config import DATA_DIR, get_api_port, EXTENSIONS_DATA_DIR
    TUBECLI_BASE_URL = f"http://localhost:{get_api_port()}"
except ImportError:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data")
    EXTENSIONS_DATA_DIR = os.path.join(DATA_DIR, "extensions_data")
    TUBECLI_BASE_URL = "http://localhost:5295"

DATA_FILE = os.path.join(str(EXTENSIONS_DATA_DIR), "universal_tracker", "universal_tracker_jobs.json")

# Default TTS voices per language
DEFAULT_TTS_VOICES = {
    "vi": "vi-VN-HoaiMyNeural",
    "en": "en-US-JennyNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
}

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
        
        # ── Pipeline Config ──
        self.pipeline_config: dict = data.get("pipeline_config", {})
        # pipeline_config structure:
        # {
        #   "effects": ["mirror"],           # FFmpeg effects
        #   "crop_percent": 0,               # Crop percentage 0-20
        #   "subtitle": false,               # Extract subtitle?
        #   "translate_to": "",              # "vi", "en", etc.
        #   "tts": false,                    # TTS dubbing?
        #   "tts_voice": "vi-VN-HoaiMyNeural",
        #   "burn_sub": false,               # Burn subtitle into video?
        #   "upload_targets": [
        #     {"platform": "youtube", "email": "", "channel_id": "", "privacy": "public"}
        #   ]
        # }
        
        # ── Stats ──
        self.processed_count: int = data.get("processed_count", 0)
        self.last_error: str = data.get("last_error", "")
        
        # ── Telegram notification ──
        self.notify_chat_id: int = data.get("notify_chat_id", 0)
        self.notify_token: str = data.get("notify_token", "")
        
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
            "pipeline_config": self.pipeline_config,
            "processed_count": self.processed_count,
            "last_error": self.last_error,
            "notify_chat_id": self.notify_chat_id,
            "notify_token": self.notify_token,
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

    def add_tracker(self, platform: str, url: str, interval_minutes: int = 60,
                    target_team_id: str = "", instruction: str = "",
                    pipeline_config: dict = None, notify_chat_id: int = 0,
                    notify_token: str = "") -> TrackerJob:
        job = TrackerJob({
            "platform": platform,
            "url": url,
            "interval_minutes": interval_minutes,
            "target_team_id": target_team_id,
            "instruction": instruction,
            "pipeline_config": pipeline_config or {},
            "notify_chat_id": notify_chat_id,
            "notify_token": notify_token,
            "next_check_at": (datetime.now() + timedelta(seconds=10)).isoformat()
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
                    
                    # Execute pipeline
                    await self._dispatch_event(job, video_info)
        except Exception as e:
            job.last_error = str(e)[:300]
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

                # Run pipeline in background
                asyncio.create_task(self._dispatch_event(job, video_info))
                return {
                    "success": True,
                    "message": f"Đã phát hiện video '{video_info.get('title')}' và bắt đầu pipeline!"
                }
            return {"success": False, "message": "Không tìm thấy video nào."}
        except Exception as e:
            return {"success": False, "message": f"Lỗi khi lấy video: {str(e)}"}

    async def _fetch_latest_video(self, platform: str, url: str) -> dict:
        """Fetches the latest item using native API if possible, fallback to yt-dlp."""
        if platform == "sheets_bg_replace":
            try:
                import aiohttp
                import csv
                import io
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            reader = csv.reader(io.StringIO(text))
                            rows = list(reader)
                            if len(rows) > 1:
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
                lines = stdout.decode("utf-8").strip().split('\n')
                return json.loads(lines[0])
            except json.JSONDecodeError:
                return {}
        return {}

    # ═══════════════════════════════════════════════════════════════
    #  PIPELINE DISPATCH — Direct execution + Telegram notification
    # ═══════════════════════════════════════════════════════════════

    async def _dispatch_event(self, job: TrackerJob, video_info: dict):
        """Execute pipeline based on job.pipeline_config and notify via Telegram."""
        config = job.pipeline_config or {}
        video_url = video_info.get("original_url") or video_info.get("url")
        title = video_info.get("title", "Unknown")
        
        if not video_url:
            logger.error(f"No video URL found in video_info: {video_info}")
            return
        
        # Notify start via Telegram
        await self._notify(job, f"🚀 *Video mới phát hiện!*\n\n📡 Nguồn: {job.platform.upper()}\n📹 `{title}`\n🔗 {video_url}\n\n⏳ Đang bắt đầu pipeline...")
        
        # Track in pipeline_tracker
        from tubecli.core.pipeline_tracker import pipeline_tracker
        
        # Determine pipeline type and steps based on config
        has_effects = bool(config.get("effects")) or config.get("crop_percent", 0) > 0
        has_subtitle = config.get("subtitle", False)
        has_tts = config.get("tts", False)
        has_burn = config.get("burn_sub", False)
        upload_targets = config.get("upload_targets", [])
        
        # Build step list
        step_names = [("download", "📥 Tải video")]
        if has_effects:
            step_names.append(("ffmpeg", f"🎬 FFmpeg ({', '.join(config.get('effects', []))})"))
        if has_subtitle:
            step_names.append(("extract", "📝 Tách phụ đề"))
        if has_tts:
            step_names.append(("tts", "🎙️ Lồng tiếng"))
        if has_burn:
            step_names.append(("burn", "🔥 Burn sub"))
        for i, tgt in enumerate(upload_targets):
            step_names.append((f"upload_{i}", f"📤 Upload {tgt.get('platform', 'youtube').upper()}"))
        
        if not upload_targets:
            step_names.append(("upload_0", "📤 Upload YouTube"))
        
        pt_task = pipeline_tracker.create_task(
            pipeline_type="auto_tracker",
            chat_id=job.notify_chat_id,
            url=video_url,
            original_message=f"[Tracker] {title}",
            step_names=step_names,
        )
        pt_id = pt_task.task_id
        
        try:
            # ── Step 1: Download ──
            pipeline_tracker.start_step(pt_id, "download", "Đang tải...")
            dl_result = await self._download_video(video_url)
            
            if not dl_result or not dl_result.get("file_path"):
                err = dl_result.get("error", "Download failed") if isinstance(dl_result, dict) else "Download failed"
                pipeline_tracker.fail_step(pt_id, "download", str(err)[:200])
                pipeline_tracker.fail_task(pt_id, f"Download failed: {err}")
                job.last_error = str(err)[:300]
                await self._notify(job, f"❌ Tải video thất bại:\n`{title}`\n\nLỗi: {str(err)[:200]}")
                self._save()
                return
            
            file_path = dl_result["file_path"]
            file_name = os.path.basename(file_path)
            pipeline_tracker.complete_step(pt_id, "download", file_name)
            pt_task.video_filename = file_name
            
            output_video = file_path
            srt_path = None
            
            # ── Step 2: FFmpeg Effects ──
            if has_effects:
                pipeline_tracker.start_step(pt_id, "ffmpeg", ", ".join(config.get("effects", [])))
                ffmpeg_result = await self._apply_effects(file_path, config)
                if ffmpeg_result and ffmpeg_result != file_path:
                    output_video = ffmpeg_result
                    pipeline_tracker.complete_step(pt_id, "ffmpeg", os.path.basename(output_video))
                else:
                    pipeline_tracker.complete_step(pt_id, "ffmpeg", "No change")
            
            # ── Step 3: Subtitle Extract ──
            if has_subtitle:
                pipeline_tracker.start_step(pt_id, "extract", "Whisper...")
                sub_result = await self._extract_subtitle(file_path, config.get("translate_to", ""))
                if sub_result and sub_result.get("srt_path"):
                    srt_path = sub_result["srt_path"]
                    srt_content = sub_result.get("srt_content", "")
                    sub_count = sub_result.get("count", 0)
                    pipeline_tracker.complete_step(pt_id, "extract", f"{sub_count} dòng")
                    
                    # ── Step 4: TTS ──
                    if has_tts and srt_content:
                        tts_voice = config.get("tts_voice", "vi-VN-HoaiMyNeural")
                        pipeline_tracker.start_step(pt_id, "tts", f"Voice: {tts_voice}")
                        tts_result = await self._synthesize_tts(srt_content, tts_voice, output_video)
                        if tts_result:
                            output_video = tts_result
                            pipeline_tracker.complete_step(pt_id, "tts", os.path.basename(output_video))
                        else:
                            pipeline_tracker.fail_step(pt_id, "tts", "TTS failed, continuing...")
                    
                    # ── Step 5: Burn Sub ──
                    if has_burn and srt_path:
                        pipeline_tracker.start_step(pt_id, "burn", "FFmpeg...")
                        burn_result = await self._burn_subtitle(output_video, srt_path)
                        if burn_result:
                            output_video = burn_result
                            pipeline_tracker.complete_step(pt_id, "burn", os.path.basename(output_video))
                        else:
                            pipeline_tracker.fail_step(pt_id, "burn", "Burn failed")
                else:
                    pipeline_tracker.fail_step(pt_id, "extract", "No subtitles found")
            
            # ── Step N: Upload ──
            targets = upload_targets if upload_targets else [{"platform": "youtube", "privacy": "public"}]
            
            upload_results = []
            for i, target in enumerate(targets):
                step_key = f"upload_{i}"
                platform = target.get("platform", "youtube")
                pipeline_tracker.start_step(pt_id, step_key, f"{platform.upper()}")
                
                if platform == "youtube":
                    upload_ok, upload_msg = await self._upload_youtube(
                        output_video, title, target
                    )
                    if upload_ok:
                        pipeline_tracker.complete_step(pt_id, step_key, upload_msg[:100])
                        upload_results.append(f"✅ YouTube: {upload_msg[:100]}")
                    else:
                        pipeline_tracker.fail_step(pt_id, step_key, upload_msg[:200])
                        upload_results.append(f"❌ YouTube: {upload_msg[:100]}")
                else:
                    pipeline_tracker.complete_step(pt_id, step_key, f"{platform} chưa hỗ trợ")
                    upload_results.append(f"⏭️ {platform}: chưa hỗ trợ")
            
            # ── Complete ──
            job.processed_count += 1
            job.last_error = ""
            self._save()
            
            effects_str = ", ".join(config.get("effects", [])) if has_effects else "không"
            summary = (
                f"✅ *Pipeline hoàn tất!*\n\n"
                f"📡 Tracker: {job.platform.upper()}\n"
                f"📹 Video: `{title}`\n"
                f"🎬 Effects: {effects_str}\n"
                f"📝 Subtitle: {'✅' if has_subtitle else '⏭️'}\n"
                f"🎙️ TTS: {'✅' if has_tts else '⏭️'}\n"
                f"📤 Upload:\n" + "\n".join(f"  {r}" for r in upload_results) + "\n\n"
                f"📊 Tổng đã xử lý: {job.processed_count} video"
            )
            
            all_uploads_ok = all("✅" in r for r in upload_results)
            if all_uploads_ok:
                pipeline_tracker.complete_task(pt_id, summary, file_name)
            else:
                pipeline_tracker.fail_task(pt_id, "Một số upload thất bại")
            
            await self._notify(job, summary)
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            pipeline_tracker.fail_task(pt_id, str(e)[:400])
            job.last_error = str(e)[:300]
            self._save()
            await self._notify(job, f"❌ Pipeline lỗi:\n`{title}`\n\n{str(e)[:300]}")

    # ═══════════════════════════════════════════════════════════════
    #  PIPELINE HELPER METHODS
    # ═══════════════════════════════════════════════════════════════

    async def _download_video(self, video_url: str) -> dict:
        """Download video via Douyin downloader API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Parse URL first
                parse_resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/parse",
                    json={"url": video_url}
                )
                if parse_resp.status_code != 200:
                    return {"error": f"Parse failed: HTTP {parse_resp.status_code}"}
                
                parse_data = parse_resp.json()
                download_url = parse_data.get("download_url") or parse_data.get("video_url")
                if not download_url:
                    return {"error": "No download URL found"}
                
                # Download
                dl_resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/download",
                    json={"url": video_url, "download_url": download_url}
                )
                if dl_resp.status_code != 200:
                    return {"error": f"Download failed: HTTP {dl_resp.status_code}"}
                
                dl_data = dl_resp.json()
                task_id = dl_data.get("task_id")
                save_path = dl_data.get("save_path", "")
                
                # Poll for download completion
                if task_id:
                    for _ in range(60):
                        await asyncio.sleep(2)
                        sr = await client.get(f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/status/{task_id}")
                        if sr.status_code == 200:
                            sd = sr.json()
                            if sd.get("status") == "completed":
                                fp = sd.get("file_path") or save_path
                                if fp and os.path.exists(fp):
                                    return {"file_path": fp, "original_title": parse_data.get("title", "")}
                            elif sd.get("status") == "error":
                                return {"error": sd.get("error", "Download error")}
                
                # Fallback: check save_path
                if save_path and os.path.exists(save_path):
                    return {"file_path": save_path, "original_title": parse_data.get("title", "")}
                    
                return {"error": "Download timeout"}
        except Exception as e:
            return {"error": str(e)}

    async def _apply_effects(self, file_path: str, config: dict) -> str:
        """Apply FFmpeg effects using video_editor engine."""
        try:
            import importlib.util
            from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR
            
            ve_dir = str(EXTENSIONS_EXTERNAL_DIR / "video_editor")
            engine_path = os.path.join(ve_dir, "video_engine.py")
            
            if not os.path.exists(engine_path):
                return file_path
            
            spec = importlib.util.spec_from_file_location("ve_engine_tracker", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)
            
            output_dir = os.path.join(str(DATA_DIR), "video_editor", "exports")
            os.makedirs(output_dir, exist_ok=True)
            
            current_input = file_path
            effects = config.get("effects", [])
            crop_percent = config.get("crop_percent", 0)
            
            # Apply effects
            for effect in effects:
                base = os.path.splitext(os.path.basename(current_input))[0]
                effect_output = os.path.join(output_dir, f"{base}_{effect}.mp4")
                result = await engine.apply_effect(current_input, effect, effect_output)
                if result.get("status") == "success":
                    current_input = result.get("output", effect_output)
            
            # Apply crop
            if crop_percent > 0:
                base = os.path.splitext(os.path.basename(current_input))[0]
                crop_output = os.path.join(output_dir, f"{base}_crop{crop_percent}.mp4")
                keep_ratio = (100 - 2 * crop_percent) / 100
                crop_filter = f'-vf "crop=iw*{keep_ratio}:ih*{keep_ratio}:iw*{crop_percent/100}:ih*{crop_percent/100}"'
                codec, _ = engine.detect_gpu_encoder()
                ffmpeg_cmd = f'-y -i "{current_input}" {crop_filter} -c:v {codec} -c:a copy "{crop_output}"'
                result = await engine.run_custom_ffmpeg(ffmpeg_cmd)
                if result.get("status") == "success" and os.path.exists(crop_output):
                    current_input = crop_output
            
            return current_input
        except Exception as e:
            logger.error(f"Effects failed: {e}")
            return file_path

    async def _extract_subtitle(self, file_path: str, translate_to: str = "") -> dict:
        """Extract subtitle via Whisper API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                body = {"file_path": file_path, "engine": "whisper", "language": None, "translate_to": translate_to or None}
                resp = await client.post(f"{TUBECLI_BASE_URL}/api/v1/subtitle/extract", json=body)
                if resp.status_code != 200:
                    return {}
                
                task_id = resp.json().get("task_id")
                if not task_id:
                    return {}
                
                # Poll
                for _ in range(120):
                    await asyncio.sleep(2)
                    sr = await client.get(f"{TUBECLI_BASE_URL}/api/v1/subtitle/status/{task_id}", timeout=10)
                    if sr.status_code != 200:
                        continue
                    sd = sr.json()
                    if sd.get("status") == "success" and sd.get("result"):
                        subs = sd["result"].get("subtitles", [])
                        if not subs:
                            return {}
                        
                        # Build SRT
                        srt_path = file_path.rsplit(".", 1)[0] + ".srt"
                        srt_lines = []
                        for i, s in enumerate(subs, 1):
                            start = self._fmt_srt_time(s.get("start", 0))
                            end = self._fmt_srt_time(s.get("end", 0))
                            srt_lines.append(f"{i}\n{start} --> {end}\n{s.get('text', '')}\n")
                        srt_content = "\n".join(srt_lines)
                        with open(srt_path, "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        
                        return {"srt_path": srt_path, "srt_content": srt_content, "count": len(subs)}
                    elif sd.get("status") == "error":
                        return {}
                return {}
        except Exception as e:
            logger.error(f"Subtitle extract failed: {e}")
            return {}

    def _fmt_srt_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    async def _synthesize_tts(self, srt_content: str, voice: str, video_path: str) -> str:
        """TTS synthesis + merge into video."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                tts_resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/tts/synthesize-srt",
                    json={"srt_content": srt_content, "voice": voice, "engine": "edge", "speed_adjust": True}
                )
                if tts_resp.status_code != 200:
                    return ""
                
                tts_task_id = tts_resp.json().get("task_id")
                if not tts_task_id:
                    return ""
                
                tts_audio_path = ""
                for _ in range(90):
                    await asyncio.sleep(2)
                    tr = await client.get(f"{TUBECLI_BASE_URL}/api/v1/tts/status/{tts_task_id}", timeout=10)
                    if tr.status_code != 200:
                        continue
                    td = tr.json()
                    if td.get("status") == "success" and td.get("result"):
                        tts_audio_path = td["result"].get("output", "")
                        break
                    elif td.get("status") == "error":
                        return ""
                
                if not tts_audio_path or not os.path.exists(tts_audio_path):
                    return ""
                
                # Merge audio into video
                merged_path = video_path.rsplit(".", 1)[0] + "_dubbed.mp4"
                merge_cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-i", tts_audio_path,
                    "-filter_complex",
                    "[0:a]volume=0.15[orig];[1:a]volume=1.0[tts];[orig][tts]amix=inputs=2:duration=first[aout]",
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    merged_path,
                ]
                proc = await asyncio.create_subprocess_exec(
                    *merge_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                
                if proc.returncode == 0 and os.path.exists(merged_path):
                    return merged_path
                return ""
        except Exception as e:
            logger.error(f"TTS failed: {e}")
            return ""

    async def _burn_subtitle(self, video_path: str, srt_path: str) -> str:
        """Burn subtitle into video via API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/subtitle/burn",
                    json={"video_path": video_path, "srt_path": srt_path}
                )
                if resp.status_code != 200:
                    return ""
                
                task_id = resp.json().get("task_id")
                if not task_id:
                    return ""
                
                for _ in range(60):
                    await asyncio.sleep(3)
                    sr = await client.get(f"{TUBECLI_BASE_URL}/api/v1/subtitle/status/{task_id}", timeout=10)
                    if sr.status_code != 200:
                        continue
                    sd = sr.json()
                    if sd.get("status") == "success":
                        return sd.get("result", {}).get("output", "")
                    elif sd.get("status") == "error":
                        return ""
                return ""
        except Exception as e:
            logger.error(f"Burn sub failed: {e}")
            return ""

    async def _upload_youtube(self, file_path: str, title: str, target: dict) -> tuple:
        """Upload to YouTube and poll for completion. Returns (success, message)."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                payload = {
                    "provider": "youtube",
                    "file_path": file_path,
                    "title": title,
                    "privacy": target.get("privacy", "public"),
                    "email": target.get("email", ""),
                }
                
                resp = await client.post(f"{TUBECLI_BASE_URL}/api/v1/video_manager/upload", json=payload)
                if resp.status_code != 200:
                    return (False, f"HTTP {resp.status_code}")
                
                data = resp.json()
                if not data.get("success"):
                    return (False, data.get("message", "Upload failed"))
                
                task_id = data.get("task_id", "")
                if not task_id:
                    return (False, "No task_id returned")
                
                # Poll for completion (max 5 min)
                for _ in range(60):
                    await asyncio.sleep(5)
                    sr = await client.get(f"{TUBECLI_BASE_URL}/api/v1/video_manager/upload/tasks/{task_id}")
                    if sr.status_code == 200:
                        task_info = sr.json().get("task", {})
                        status = task_info.get("status", "")
                        if status == "done":
                            video_url = task_info.get("video_url", "")
                            video_id = task_info.get("video_id", "")
                            return (True, f"{video_url or video_id}")
                        elif status in ("error", "cancelled"):
                            return (False, task_info.get("error_message", "Upload error"))
                
                return (False, "Upload timeout (5min)")
        except Exception as e:
            return (False, str(e))

    async def _notify(self, job: TrackerJob, message: str):
        """Send Telegram notification if configured."""
        if not job.notify_token or not job.notify_chat_id:
            logger.info(f"[Tracker] No Telegram notify config: {message[:100]}")
            return
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                send_url = f"https://api.telegram.org/bot{job.notify_token}/sendMessage"
                resp = await client.post(send_url, json={
                    "chat_id": job.notify_chat_id,
                    "text": message[:4000],
                    "parse_mode": "Markdown"
                })
                if resp.status_code != 200 or not resp.json().get("ok"):
                    # Retry without markdown
                    await client.post(send_url, json={"chat_id": job.notify_chat_id, "text": message[:4000]})
        except Exception as e:
            logger.error(f"Telegram notify failed: {e}")

universal_tracker_engine = UniversalTracker()
