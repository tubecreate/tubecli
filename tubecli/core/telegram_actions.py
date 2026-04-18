"""
Telegram Actions — Extracted action execution logic from telegram_listener.
Handles: download, upload sequences, extension actions, scheduling, teams, API calls.
"""
import asyncio
import os
import re
import json
import datetime
import httpx
from tubecli.core.bot_i18n import t, get_user_lang
from typing import Dict, Any, Optional, List

from tubecli.config import DATA_DIR

TUBECLI_BASE_URL = "http://localhost:5295"
SETTINGS_FILE = DATA_DIR / "global_settings.json"


# ═══════════════════════════════════════════════════════════════
#  JSON EXTRACTION & CLEANING
# ═══════════════════════════════════════════════════════════════

def extract_json_action(text: str) -> Optional[Dict]:
    """Extract the first valid JSON action block from text."""
    if not text or not isinstance(text, str):
        return None

    # 1. Try code block first: ```json {...} ```
    code_match = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
    if code_match:
        try:
            data = json.loads(code_match.group(1))
            if "action" in data:
                return data
        except Exception:
            pass

    # 2. Try parsing entire text as JSON
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "action" in data:
                return data
        except Exception:
            pass

    # 3. Find JSON by bracket-depth matching
    start_idx = text.find("{")
    while start_idx >= 0:
        depth = 0
        end_idx = start_idx
        for i in range(start_idx, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        if end_idx > start_idx:
            try:
                data = json.loads(text[start_idx:end_idx])
                if isinstance(data, dict) and "action" in data:
                    return data
            except Exception:
                pass
        start_idx = text.find("{", start_idx + 1)

    return None


def clean_reply_text(text: str) -> str:
    """Clean JSON wrappers from reply text to ensure human-readable output."""
    if not text:
        return text

    def _extract_answer(data):
        if not isinstance(data, dict):
            return None
        for key in ("finalAnswer", "final_answer", "answer", "reply"):
            if key in data and data[key]:
                return str(data[key])
        if "message" in data and isinstance(data["message"], str) and len(data["message"]) > 10:
            return data["message"]

        # Action JSON that wasn't handled — execute file_action inline
        if data.get("action") == "file_action":
            try:
                from tubecli.extensions.file_manager.file_service import file_service
                op = data.get("operation", "")
                path = data.get("path", "")
                if op == "create_folder":
                    r = file_service.create_folder(path)
                    return f"✅ Đã tạo thư mục: {r.get('path', path)}"
                elif op == "create_file":
                    r = file_service.create_file(path, data.get("content", ""))
                    return f"✅ Đã tạo file: {r.get('path', path)}"
                elif op == "delete":
                    file_service.delete(path)
                    return f"✅ Đã xóa: {path}"
                elif op == "list":
                    r = file_service.list_dir(path or "~/Desktop")
                    items = r.get("items", [])
                    lines = [f"📂 {r.get('path', path)} ({r.get('count', 0)} mục):"]
                    for item in items[:15]:
                        icon = "📁" if item.get("is_dir") else "📄"
                        lines.append(f"  {icon} {item['name']}")
                    return "\n".join(lines)
                elif op == "read":
                    r = file_service.read_file(path)
                    return f"📄 {path}:\n{r.get('content', '')[:1500]}"
                elif op == "move":
                    file_service.move(path, data.get("destination", ""))
                    return f"✅ Đã di chuyển: {path}"
                elif op == "copy":
                    file_service.copy(path, data.get("destination", ""))
                    return f"✅ Đã sao chép: {path}"
            except Exception as e:
                return f"❌ Lỗi: {str(e)}"

        params = data.get("params", {})
        if isinstance(params, dict):
            for key in ("finalAnswer", "final_answer", "answer", "result"):
                if key in params and params[key]:
                    return str(params[key])
        return None

    stripped = text.strip()

    # 1. Try parsing the entire text as JSON directly
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            answer = _extract_answer(data)
            if answer:
                return answer
        except Exception:
            pass

    # 2. Try extracting from ```json ... ``` code blocks
    try:
        code_match = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
        if code_match:
            data = json.loads(code_match.group(1))
            answer = _extract_answer(data)
            if answer:
                return answer
    except Exception:
        pass

    # 3. Try finding JSON-like block by bracket matching
    start_idx = stripped.find("{")
    if start_idx >= 0:
        depth = 0
        end_idx = start_idx
        for i in range(start_idx, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        if end_idx > start_idx:
            try:
                data = json.loads(stripped[start_idx:end_idx])
                answer = _extract_answer(data)
                if answer:
                    return answer
            except Exception:
                pass

    return text


# ═══════════════════════════════════════════════════════════════
#  DOWNLOAD ACTIONS
# ═══════════════════════════════════════════════════════════════

async def execute_download(url: str, agent_dict: Dict, context: Dict = None) -> dict:
    """Execute video download via Downloader extension API and return file info."""
    chat_id = context.get("chat_id", 0) if context else 0
    lang = get_user_lang(chat_id)
    print(f"[Actions] 📥 Starting download: {url}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            parse_resp = await client.post(
                f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/parse",
                json={"url": url}
            )

            if parse_resp.status_code != 200:
                error_detail = ""
                try:
                    error_detail = parse_resp.json().get("detail", parse_resp.text[:200])
                except Exception:
                    error_detail = parse_resp.text[:200]
                return t("action.download_err", lang, error=error_detail)

            parse_data = parse_resp.json()
            video_info = parse_data.get("data", {})

            if video_info.get("type") == "user":
                user_name = video_info.get("nickname", "Unknown")
                return t("action.download_err", lang, error="Is user profile")

            title = video_info.get("title", "video")[:50]
            author = video_info.get("author", "unknown")
            platform = video_info.get("platform", "")
            duration = video_info.get("duration", 0)

            print(f"[Actions] ✅ Parsed: {author} - {title}")

    except httpx.ConnectError:
        return t("action.download_err", lang, error="Connection Error")
    except Exception as e:
        return t("action.download_err", lang, error=str(e)[:200])

    # Step 2: Download
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            dl_resp = await client.post(
                f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/download",
                json={"url": url}
            )
            if dl_resp.status_code != 200:
                try:
                    err = dl_resp.json().get("detail", dl_resp.text[:200])
                except Exception:
                    err = dl_resp.text[:200]
                return t("action.download_err", lang, error=err)

            dl_data = dl_resp.json()
            task_id = dl_data.get("task_id", "")
            filename = dl_data.get("filename", "video.mp4")

    except Exception as e:
        return t("action.download_err", lang, error=str(e)[:200])

    # Step 3: Wait for download
    print(f"[Actions] ⏳ Waiting for download task: {task_id}")
    file_path = await _wait_for_download(task_id, filename)

    if not file_path or not os.path.exists(file_path):
        return t("action.download_fail", lang)

    # Update filename to match actual file on disk
    actual_filename = os.path.basename(file_path)

    caption = (
        f"✅ *{title}*\n"
        f"👤 {author}{'  |  ⏱️ ' + str(duration) + 's' if duration else ''}\n"
        f"🌐 {platform.upper() if platform else 'Video'}\n"
        f"📁 `{actual_filename}`"
    )

    return {
        "type": "file",
        "file_path": file_path,
        "filename": actual_filename,
        "caption": caption,
        "file_type": "video",
        "duration": duration,
        "original_title": title,
        "original_author": author,
        "download_url": f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/file/{actual_filename}"
    }


async def _wait_for_download(task_id: str, filename: str, max_wait: int = 120) -> str:
    """Poll download status until complete. Returns local file path."""
    data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
    dl_dir = os.path.join(data_dir, "downloads")

    for _ in range(max_wait // 3):
        await asyncio.sleep(3)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/status/{task_id}"
                )
                if resp.status_code == 200:
                    task_data = resp.json().get("data", {})
                    status = task_data.get("status", "")
                    progress = task_data.get("progress", 0)
                    print(f"[Actions] Download progress: {progress:.1f}% ({status})")

                    if status in ("completed", "done"):
                        # Priority 1: save_path from task (absolute)
                        save_path = task_data.get("save_path", "")
                        if save_path and os.path.exists(save_path):
                            return save_path
                        # Priority 2: filename from task status (may differ after sanitize)
                        task_filename = task_data.get("filename", "")
                        if task_filename:
                            resolved = os.path.join(dl_dir, task_filename)
                            if os.path.exists(resolved):
                                return resolved
                        # Priority 3: original filename param
                        local_path = os.path.join(dl_dir, filename)
                        if os.path.exists(local_path):
                            return local_path
                        # Priority 4: glob most recent file in downloads dir
                        import glob
                        candidates = sorted(
                            glob.glob(os.path.join(dl_dir, "*.mp4")),
                            key=os.path.getmtime, reverse=True
                        )
                        if candidates:
                            print(f"[Actions] Fallback: using most recent file {candidates[0]}")
                            return candidates[0]
                        return ""
                    elif status in ("error", "failed"):
                        err_msg = task_data.get("error", "Unknown error")
                        print(f"[Actions] ❌ Download failed: {err_msg}")
                        return ""
        except Exception:
            pass

    local_path = os.path.join(dl_dir, filename)
    return local_path if os.path.exists(local_path) else ""


# ═══════════════════════════════════════════════════════════════
#  UPLOAD SEQUENCE (Download → AI Title → Upload)
# ═══════════════════════════════════════════════════════════════

async def execute_upload_sequence(
    video_url: str,
    user_text: str,
    agent_dict: Dict,
    send_message_fn,
    send_file_fn,
    handle_extension_fn,
    context: Dict,
) -> str:
    """Full Download + AI Title (parallel) → Upload pipeline.
    Uses SubAgentFork for concurrent execution.
    """
    token = context.get("token", "")
    chat_id = context.get("chat_id", 0)

    lang = get_user_lang(chat_id)
    await send_message_fn(token, chat_id, t("action.detect_download", lang))

    # ★ FORK: Download + AI Title chạy song song
    from tubecli.core.fork_agent import fork_download_and_title
    fork_result = await fork_download_and_title(video_url, user_text, agent_dict, context)

    # Get download result
    dl_subtask = fork_result.get("download")
    dl_result = dl_subtask.result if dl_subtask and dl_subtask.status.value == "completed" else None

    if not dl_result or not isinstance(dl_result, dict) or not dl_result.get("file_path"):
        error = dl_result if isinstance(dl_result, str) else "❌ Tải video thất bại."
        if dl_subtask and dl_subtask.error:
            error = f"❌ Lỗi tải: {dl_subtask.error}"
        return error

    # Send downloaded file to chat
    try:
        await send_file_fn(token, chat_id, dl_result)
    except Exception as e:
        print(f"[Actions] Lỗi gửi file: {e}")

    video_path = dl_result["file_path"]
    duration = dl_result.get("duration", 0)
    original_title = dl_result.get("original_title", "Video Mới")
    original_author = dl_result.get("original_author", "Unknown")

    # Get AI title from fork result (ran in parallel with download!)
    title_subtask = fork_result.get("ai_title")
    ai_title = title_subtask.result if title_subtask and title_subtask.status.value == "completed" and title_subtask.result else original_title

    speed_msg = f"⚡ Fork hoàn tất trong {fork_result.total_duration_ms}ms (Download: {dl_subtask.duration_ms}ms | Title: {title_subtask.duration_ms if title_subtask else 0}ms)"
    print(f"[Actions] {speed_msg}")
    await send_message_fn(token, chat_id, f"✨ AI Title: *{ai_title}*\n{speed_msg}")

    # Resolve upload provider from context (default: youtube)
    provider = context.get("upload_provider", "youtube")
    provider_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(provider, "YouTube")

    # ── Smart Channel Resolution (via channel_cache) ──
    target_email = ""
    target_id = ""
    resolved_channel_title = ""
    try:
        from tubecli.core.channel_cache import channel_cache
        text_lower = user_text.lower()
        
        # Try resolving from cache first (supports "kênh 2", name match, last-used)
        resolved = channel_cache.resolve_channel(provider, user_text)
        
        if resolved:
            target_email = resolved.get("email", "")
            target_id = resolved.get("id", "")
            resolved_channel_title = resolved.get("title", "")
            print(f"[Actions] ✅ Channel resolved from cache: {resolved_channel_title} ({target_id})")
        else:
            # Cache empty → try API fallback to populate cache
            print(f"[Actions] Cache empty for {provider}, trying API fallback...")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{TUBECLI_BASE_URL}/api/v1/video_manager/accounts?provider={provider}")
                if resp.status_code == 200:
                    accounts = resp.json().get("accounts", [])
                    all_channels = []
                    for acct in accounts:
                        em = acct.get("email", "")
                        ch_resp = await client.get(f"{TUBECLI_BASE_URL}/api/v1/video_manager/channels?provider={provider}&email={em}")
                        if ch_resp.status_code == 200:
                            for ch in ch_resp.json().get("channels", []):
                                ch_entry = {
                                    "id": ch.get("id", ""),
                                    "title": ch.get("title", ""),
                                    "email": em,
                                    "subscribers": ch.get("subscribers", 0),
                                    "url": ch.get("url", ""),
                                    "provider": provider,
                                }
                                all_channels.append(ch_entry)
                    
                    if all_channels:
                        channel_cache.save_channels(provider, all_channels)
                        # Re-resolve after populating cache
                        resolved = channel_cache.resolve_channel(provider, user_text)
                        if resolved:
                            target_email = resolved.get("email", "")
                            target_id = resolved.get("id", "")
                            resolved_channel_title = resolved.get("title", "")
                        else:
                            # Just use first channel
                            target_email = all_channels[0].get("email", "")
                            target_id = all_channels[0].get("id", "")
                            resolved_channel_title = all_channels[0].get("title", "")
    except Exception as e:
        print(f"[Actions] Channel resolve error: {e}")

    # Notify user which channel was selected
    if resolved_channel_title:
        await send_message_fn(token, chat_id, t("action.upload_target", lang, provider=provider_label, channel=resolved_channel_title))

    # Trigger Upload
    fake_ai_action = {
        "action": "upload_video",
        "file_path": video_path,
        "provider": provider,
        "privacy": "public",
        "title": ai_title
    }
    if target_email:
        fake_ai_action["email"] = target_email
    if target_id:
        fake_ai_action["target_id"] = target_id

    reply_payload = "```json\n" + json.dumps(fake_ai_action) + "\n```"
    upload_result = await handle_extension_fn(reply_payload, agent_dict, context)

    # Mark this channel as last-used on success
    if target_id and "✅" in str(upload_result):
        try:
            from tubecli.core.channel_cache import channel_cache
            channel_cache.set_last_used(provider, target_id)
        except Exception:
            pass

    # Poll upload status
    duration_sec = _parse_duration(duration)
    task_id_match = re.search(r'Task ID:\s*`([^`]+)`', upload_result)

    if task_id_match:
        task_id = task_id_match.group(1)
        if 0 < duration_sec < 60:
            return await _poll_short_video(task_id, upload_result, handle_extension_fn, send_message_fn, agent_dict, context)
        else:
            asyncio.create_task(_poll_long_video_bg(task_id, handle_extension_fn, send_message_fn, agent_dict, context))
            return upload_result + "\n\n" + t("action.bg_schedule", lang)

    return upload_result


def _parse_duration(duration) -> int:
    """Parse duration to seconds."""
    if isinstance(duration, int):
        return duration
    if isinstance(duration, str):
        try:
            parts = duration.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return int(float(parts[0].replace('s', '')))
        except Exception:
            pass
    return 0


async def _poll_short_video(task_id, upload_result, handle_ext_fn, send_msg_fn, agent_dict, context):
    lang = get_user_lang(context.get("chat_id", 0))
    """Block and wait for short video upload result."""
    token = context.get("token", "")
    chat_id = context.get("chat_id", 0)
    await send_msg_fn(token, chat_id, t("action.upload_short", lang))
    
    for _ in range(30):
        await asyncio.sleep(10)
        st_payload = "```json\n" + json.dumps({"action": "video_status", "task_id": task_id}) + "\n```"
        st_result = await handle_ext_fn(st_payload, agent_dict, context)
        if "✅" in st_result and "done" in st_result.lower():
            return t("action.upload_success", lang, provider="YouTube", result=st_result)
        elif "❌" in st_result or "error" in st_result.lower():
            return st_result

    return t("action.upload_timeout", lang, result=upload_result)


async def _poll_long_video_bg(task_id, handle_ext_fn, send_msg_fn, agent_dict, context):
    lang = get_user_lang(context.get("chat_id", 0))
    """Background polling for long video uploads."""
    token = context.get("token", "")
    chat_id = context.get("chat_id", 0)
    await asyncio.sleep(60)
    
    for _ in range(60):
        st_payload = "```json\n" + json.dumps({"action": "video_status", "task_id": task_id}) + "\n```"
        st_result = await handle_ext_fn(st_payload, agent_dict, context)
        if "✅" in st_result and "done" in st_result.lower():
            await send_msg_fn(token, chat_id, t("action.bg_success", lang, result=st_result))
            return
        elif "❌" in st_result or "error" in st_result.lower():
            await send_msg_fn(token, chat_id, t("action.bg_fail", lang, result=st_result))
            return
        await asyncio.sleep(10)


# ═══════════════════════════════════════════════════════════════
#  REUP SEQUENCE (Download → FFmpeg Effects → Upload)
# ═══════════════════════════════════════════════════════════════

async def execute_reup_sequence(
    video_url: str,
    user_text: str,
    agent_dict: Dict,
    send_message_fn,
    send_file_fn,
    handle_extension_fn,
    context: Dict,
) -> str:
    """Full Re-up Pipeline: Download → FFmpeg (mirror/trim/effects) → Upload YouTube.
    Extends execute_upload_sequence with an FFmpeg processing step in between.
    """
    token = context.get("token", "")
    chat_id = context.get("chat_id", 0)

    # ── Step 1: Parse user request for effects ──
    text_lower = user_text.lower()
    effects = []
    if any(k in text_lower for k in ["gương", "mirror", "lật", "flip", "hflip"]):
        effects.append("mirror")
    if any(k in text_lower for k in ["trắng đen", "grayscale", "đen trắng", "bw"]):
        effects.append("grayscale")
    if any(k in text_lower for k in ["tốc độ 2", "speed 2", "nhanh 2", "2x"]):
        effects.append("speed_2x")
    if any(k in text_lower for k in ["xoay 90", "rotate 90"]):
        effects.append("rotate_90")
    if any(k in text_lower for k in ["xoay 180", "rotate 180"]):
        effects.append("rotate_180")
    if any(k in text_lower for k in ["blur", "mờ"]):
        effects.append("blur")
    if any(k in text_lower for k in ["sepia", "vintage", "cổ điển"]):
        effects.append("sepia")
    if any(k in text_lower for k in ["ngược", "reverse", "đảo ngược"]):
        effects.append("reverse")
    
    # Parse crop percentage (e.g., "crop 5%", "crop 10")
    crop_percent = 0
    crop_match = re.search(r'crop\s*(\d+)\s*%?', text_lower)
    if crop_match:
        crop_percent = int(crop_match.group(1))
        if crop_percent > 50:  # Sanity check
            crop_percent = 5
    
    # Parse background removal
    remove_bg = any(k in text_lower for k in ["tách nền", "xóa phông", "remove bg", "remove background", "green screen", "màn xanh"])
    # Parse background replacement color/image
    bg_replace = None
    bg_match = re.search(r'(?:nền|background)\s+(trắng|\u0111en|xanh|\u0111ỏ|#[0-9a-fA-F]{6})', text_lower)
    if bg_match:
        bg_colors = {"trắng": "#FFFFFF", "đen": "#000000", "xanh": "#00FF00", "đỏ": "#FF0000"}
        bg_replace = bg_colors.get(bg_match.group(1), bg_match.group(1))
    
    # Default to mirror if no explicit effect mentioned AND no template
    template_id = context.get("template_id")
    template_name = context.get("template_name", "")
    if not effects and crop_percent == 0 and not remove_bg and not template_id:
        effects.append("mirror")

    # Parse trim times
    trim_start = None
    trim_end = None
    trim_match = re.search(r'cắt\s+(\d+)\s*[s giây]?\s*(?:đầu|cuối)?', text_lower)
    if not trim_match:
        trim_match = re.search(r'trim\s+(\d+)', text_lower)
    
    crop_str = f" + Crop {crop_percent}%" if crop_percent > 0 else ""
    bg_str = " + Tách nền" if remove_bg else ""
    effects_str = ", ".join(effects) + crop_str + bg_str
    trim_str = f" + Cắt {trim_start}-{trim_end}s" if trim_start else ""
    
    # ── Create pipeline tracker task ──
    from tubecli.core.pipeline_tracker import pipeline_tracker
    reup_provider = context.get("upload_provider", "youtube")
    reup_provider_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(reup_provider, "YouTube")
    step_names = [("download", "📥 Tải video")]
    if effects:
        step_names.append(("ffmpeg", f"🎬 FFmpeg ({effects_str})"))
    if template_id:
        step_names.append(("template", f"🎨 Template: {template_name}"))
    step_names.append(("upload", f"📤 Upload {reup_provider_label}"))
    pt_task = pipeline_tracker.create_task(
        pipeline_type="reup_pipeline",
        chat_id=chat_id,
        url=video_url,
        original_message=user_text[:200],
        step_names=step_names,
    )
    pt_id = pt_task.task_id
    
    pipeline_tracker.start_step(pt_id, "download", "Đang tải...")
    lang = get_user_lang(chat_id)
    
    # Build dynamic start message to match what was displayed in the plan
    exec_steps = [t("plan.step_download", lang)]
    if effects:
        exec_steps.append(t("plan.step_ffmpeg", lang, effects=', '.join(effects)))
    if template_id:
        exec_steps.append(t("plan.step_template", lang, name=template_name))
    exec_steps.append(t("plan.step_ai_title", lang))
    exec_steps.append(t("plan.step_upload", lang, provider=reup_provider_label))
    
    title_msg = t("plan.reup_title", lang)  # e.g. "♻️ Plan: Re-up Pipeline"
    title_msg = title_msg.replace("Plan: ", "") # quick fix to say Re-up Pipeline
    start_msg = [f"**{title_msg} Started**\n"]
    for idx, step_txt in enumerate(exec_steps, 1):
        start_msg.append(f"Step {idx}/{len(exec_steps)}: {step_txt}")
        
    await send_message_fn(token, chat_id, "\n".join(start_msg))

    # ── Step 2: Download ──
    from tubecli.core.fork_agent import fork_download_and_title
    fork_result = await fork_download_and_title(video_url, user_text, agent_dict, context)

    dl_subtask = fork_result.get("download")
    dl_result = dl_subtask.result if dl_subtask and dl_subtask.status.value == "completed" else None

    if not dl_result or not isinstance(dl_result, dict) or not dl_result.get("file_path"):
        error = dl_result if isinstance(dl_result, str) else "❌ Tải video thất bại."
        if dl_subtask and dl_subtask.error:
            error = f"❌ Lỗi tải: {dl_subtask.error}"
        pipeline_tracker.fail_step(pt_id, "download", str(error)[:200])
        pipeline_tracker.fail_task(pt_id, "Tải video thất bại")
        return error

    video_path = dl_result["file_path"]
    original_title = dl_result.get("original_title", "Video Mới")
    duration = dl_result.get("duration", 0)

    dl_speed = f"{dl_subtask.duration_ms}ms" if dl_subtask else "?"
    pipeline_tracker.complete_step(pt_id, "download", f"{os.path.basename(video_path)} ({dl_speed})")
    pt_task.video_filename = os.path.basename(video_path)
    
    pipeline_tracker.start_step(pt_id, "ffmpeg", effects_str)
    await send_message_fn(token, chat_id, t("action.reup_dl_done", lang, speed=dl_speed, effects=effects_str))

    # ── Step 3: FFmpeg Processing ──
    import time
    ffmpeg_start = time.time()
    processed_path = video_path
    
    try:
        import importlib.util
        import sys
        
        # Load video_engine using the canonical config path
        from tubecli.config import EXTENSIONS_EXTERNAL_DIR, DATA_DIR
        ve_dir = str(EXTENSIONS_EXTERNAL_DIR / "video_editor")
        engine_path = os.path.join(ve_dir, "video_engine.py")
        
        if os.path.exists(engine_path):
            spec = importlib.util.spec_from_file_location("ve_engine_reup", engine_path)
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)
            
            output_dir = os.path.join(str(DATA_DIR), "video_editor", "exports")
            os.makedirs(output_dir, exist_ok=True)
            
            current_input = video_path
            
            # Apply trim first (if requested)
            if trim_start is not None and trim_end is not None:
                base = os.path.splitext(os.path.basename(current_input))[0]
                trim_output = os.path.join(output_dir, f"{base}_trim.mp4")
                result = await engine.trim(current_input, str(trim_start), str(trim_end), trim_output)
                if result.get("status") == "success":
                    current_input = result.get("output", trim_output)
                    print(f"[Reup] ✅ Trim done: {current_input}")
                else:
                    print(f"[Reup] ⚠️ Trim failed, continuing with original")
            
            # Apply effects sequentially
            for effect in effects:
                base = os.path.splitext(os.path.basename(current_input))[0]
                effect_output = os.path.join(output_dir, f"{base}_{effect}.mp4")
                result = await engine.apply_effect(current_input, effect, effect_output)
                if result.get("status") == "success":
                    current_input = result.get("output", effect_output)
                    print(f"[Reup] ✅ Effect '{effect}' done: {current_input}")
                else:
                    print(f"[Reup] ⚠️ Effect '{effect}' failed, continuing with previous")
            
            # Apply crop (if requested)
            if crop_percent > 0:
                base = os.path.splitext(os.path.basename(current_input))[0]
                crop_output = os.path.join(output_dir, f"{base}_crop{crop_percent}.mp4")
                
                keep_ratio = (100 - 2 * crop_percent) / 100
                keep_res = any(k in text_lower for k in ["giữ độ phân giải", "giữ resolution", "keep res", "same res"])
                
                if keep_res:
                    crop_filter = (
                        f"-vf \"crop=iw*{keep_ratio}:ih*{keep_ratio}:iw*{crop_percent/100}:ih*{crop_percent/100},"
                        f"scale=iw/{keep_ratio}:ih/{keep_ratio}:flags=lanczos\""
                    )
                else:
                    crop_filter = (
                        f"-vf \"crop=iw*{keep_ratio}:ih*{keep_ratio}:iw*{crop_percent/100}:ih*{crop_percent/100}\""
                    )
                
                codec, _ = engine.detect_gpu_encoder()
                ffmpeg_cmd = f'-y -i "{current_input}" {crop_filter} -c:v {codec} -c:a copy "{crop_output}"'
                result = await engine.run_custom_ffmpeg(ffmpeg_cmd)
                
                if result.get("status") == "success" and os.path.exists(crop_output):
                    current_input = crop_output
                    print(f"[Reup] ✅ Crop {crop_percent}% done: {current_input}")
                else:
                    print(f"[Reup] ⚠️ Crop failed: {result.get('stderr', '')[:200]}")
            
            # Apply background removal (AI-powered, runs last)
            if remove_bg:
                await send_message_fn(token, chat_id, t("action.matting_ai", lang))
                try:
                    matting_path = os.path.join(ve_dir, "video_matting.py")
                    matting_spec = importlib.util.spec_from_file_location("ve_matting_reup", matting_path)
                    matting_mod = importlib.util.module_from_spec(matting_spec)
                    matting_spec.loader.exec_module(matting_mod)
                    
                    base = os.path.splitext(os.path.basename(current_input))[0]
                    green_output = os.path.join(output_dir, f"{base}_greenscreen.mp4")
                    
                    # Step A: Remove background (outputs green screen)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, matting_mod.remove_background, current_input, green_output)
                    
                    if os.path.exists(green_output):
                        current_input = green_output
                        print(f"[Reup] ✅ Background removed: {current_input}")
                        
                        # Step B: Composite onto custom background (if specified)
                        if bg_replace:
                            final_output = os.path.join(output_dir, f"{base}_composed.mp4")
                            comp_result = await matting_mod.composite_background(
                                green_output, bg_replace, final_output
                            )
                            if comp_result.get("status") == "success":
                                current_input = final_output
                                print(f"[Reup] ✅ Background replaced with {bg_replace}: {current_input}")
                    else:
                        print(f"[Reup] ⚠️ Background removal produced no output")
                        
                except Exception as e:
                    print(f"[Reup] ⚠️ Background removal failed: {e}")
                    await send_message_fn(token, chat_id, t("action.matting_fail", lang, error=str(e)[:150]))
            
            processed_path = current_input
        else:
            await send_message_fn(token, chat_id, t("action.no_ve_ext", lang))

    except Exception as e:
        print(f"[Reup] ❌ FFmpeg error: {e}")
        await send_message_fn(token, chat_id, t("action.ffmpeg_fail", lang, error=str(e)[:200]))

    ffmpeg_elapsed = int((time.time() - ffmpeg_start) * 1000)
    
    if processed_path != video_path:
        file_size = os.path.getsize(processed_path) if os.path.exists(processed_path) else 0
        size_mb = file_size / (1024 * 1024)
        pipeline_tracker.complete_step(pt_id, "ffmpeg", f"{os.path.basename(processed_path)} ({size_mb:.1f}MB) {ffmpeg_elapsed}ms")
        await send_message_fn(token, chat_id, t("action.ffmpeg_done", lang, speed=ffmpeg_elapsed, effects=effects_str, filename=os.path.basename(processed_path), size=f"{size_mb:.1f}", provider=reup_provider_label))
    elif effects:
        pipeline_tracker.complete_step(pt_id, "ffmpeg", f"No change ({ffmpeg_elapsed}ms)")

    # ── Step 3b: Apply Template (if requested) ──
    template_ok = True
    if template_id:
        import time as _time
        tpl_start = _time.time()
        pipeline_tracker.start_step(pt_id, "template", template_name)
        await send_message_fn(token, chat_id, f"🎨 Đang áp dụng template: {template_name}...")
        
        try:
            async with httpx.AsyncClient(timeout=180) as tpl_client:
                # Call template render API
                render_resp = await tpl_client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/templates/render",
                    json={"template_id": template_id, "input_video": processed_path},
                    timeout=30,
                )
                if render_resp.status_code == 200:
                    render_data = render_resp.json()
                    render_task_id = render_data.get("task_id", "")
                    render_output = render_data.get("output_file", "")
                    
                    # Poll render task until done
                    if render_task_id:
                        for _ in range(60):  # 5 min max
                            await asyncio.sleep(5)
                            try:
                                st_resp = await tpl_client.get(
                                    f"{TUBECLI_BASE_URL}/api/v1/templates/task/{render_task_id}",
                                    timeout=10,
                                )
                                if st_resp.status_code == 200:
                                    task_info = st_resp.json().get("task", {})
                                    if task_info.get("status") == "done":
                                        result_output = task_info.get("result", {}).get("output_file", render_output)
                                        if result_output and os.path.exists(result_output):
                                            processed_path = result_output
                                        elif render_output and os.path.exists(render_output):
                                            processed_path = render_output
                                        break
                                    elif task_info.get("status") == "error":
                                        tpl_err = task_info.get("error", "Unknown error")[:500]
                                        template_ok = False
                                        print(f"[Reup] ❌ Template render failed: {tpl_err}")
                                        pipeline_tracker.fail_step(pt_id, "template", tpl_err[:200])
                                        await send_message_fn(token, chat_id, f"❌ Template render thất bại:\n```\n{tpl_err}\n```")
                                        break
                            except Exception as poll_e:
                                print(f"[Reup] Poll error: {poll_e}")
                else:
                    tpl_err = render_resp.text[:500]
                    template_ok = False
                    print(f"[Reup] ❌ Template render API error ({render_resp.status_code}): {tpl_err}")
                    pipeline_tracker.fail_step(pt_id, "template", tpl_err[:200])
                    await send_message_fn(token, chat_id, f"❌ Template API error ({render_resp.status_code}):\n```\n{tpl_err}\n```")
        except Exception as e:
            template_ok = False
            print(f"[Reup] ❌ Template error: {e}")
            import traceback; traceback.print_exc()
            pipeline_tracker.fail_step(pt_id, "template", str(e)[:200])
            await send_message_fn(token, chat_id, f"❌ Template exception: {str(e)[:300]}")
        
        tpl_elapsed = int((_time.time() - tpl_start) * 1000)
        if template_ok:
            pipeline_tracker.complete_step(pt_id, "template", f"{template_name} ({tpl_elapsed}ms)")
            await send_message_fn(token, chat_id, f"✅ Template '{template_name}' áp dụng thành công ({tpl_elapsed}ms)")

    # ── Step 4: Get AI title ──
    title_subtask = fork_result.get("ai_title")
    ai_title = title_subtask.result if title_subtask and title_subtask.status.value == "completed" and title_subtask.result else original_title

    # ── Step 5: Smart Channel Resolution (via channel_cache) ──
    provider = context.get("upload_provider", "youtube")
    provider_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(provider, "YouTube")
    target_email = ""
    target_id = ""
    resolved_channel_title = ""
    try:
        from tubecli.core.channel_cache import channel_cache
        resolved = channel_cache.resolve_channel(provider, user_text)
        if resolved:
            target_email = resolved.get("email", "")
            target_id = resolved.get("id", "")
            resolved_channel_title = resolved.get("title", "")
            print(f"[Reup] ✅ Channel resolved: {resolved_channel_title} ({target_id})")
        else:
            # Fallback: API query + cache population
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{TUBECLI_BASE_URL}/api/v1/video_manager/accounts?provider={provider}")
                if resp.status_code == 200:
                    accounts = resp.json().get("accounts", [])
                    all_channels = []
                    for acct in accounts:
                        em = acct.get("email", "")
                        ch_resp = await client.get(f"{TUBECLI_BASE_URL}/api/v1/video_manager/channels?provider={provider}&email={em}")
                        if ch_resp.status_code == 200:
                            for ch in ch_resp.json().get("channels", []):
                                all_channels.append({
                                    "id": ch.get("id", ""), "title": ch.get("title", ""),
                                    "email": em, "subscribers": ch.get("subscribers", 0),
                                    "url": ch.get("url", ""), "provider": provider,
                                })
                    if all_channels:
                        channel_cache.save_channels(provider, all_channels)
                        resolved = channel_cache.resolve_channel(provider, user_text)
                        if resolved:
                            target_email = resolved.get("email", "")
                            target_id = resolved.get("id", "")
                            resolved_channel_title = resolved.get("title", "")
                        else:
                            target_email = all_channels[0].get("email", "")
                            target_id = all_channels[0].get("id", "")
                            resolved_channel_title = all_channels[0].get("title", "")
    except Exception as e:
        print(f"[Reup] Channel resolve error: {e}")

    if resolved_channel_title:
        await send_message_fn(token, chat_id, t("action.upload_target", lang, provider=provider_label, channel=resolved_channel_title))

    fake_ai_action = {
        "action": "upload_video",
        "file_path": processed_path,
        "provider": provider,
        "privacy": "public",
        "title": ai_title
    }
    if target_email:
        fake_ai_action["email"] = target_email
    if target_id:
        fake_ai_action["target_id"] = target_id

    pipeline_tracker.start_step(pt_id, "upload", provider_label)
    reply_payload = "```json\n" + json.dumps(fake_ai_action) + "\n```"
    upload_result = await handle_extension_fn(reply_payload, agent_dict, context)

    # Mark channel as last-used on success
    if target_id and "✅" in str(upload_result):
        try:
            from tubecli.core.channel_cache import channel_cache
            channel_cache.set_last_used(provider, target_id)
        except Exception:
            pass

    # Poll upload status
    duration_sec = _parse_duration(duration)
    task_id_match = re.search(r'Task ID:\s*`([^`]+)`', upload_result)

    # File paths for preview
    video_serve_url = f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/file/{os.path.basename(processed_path)}"

    total_msg = (
        f"♻️ **Re-up Pipeline Hoàn tất!**\n"
        f"📥 Download: {dl_speed}\n"
        f"🎬 FFmpeg ({effects_str}): {ffmpeg_elapsed}ms\n"
    )

    if task_id_match:
        task_id = task_id_match.group(1)
        if 0 < duration_sec < 60:
            result = await _poll_short_video(task_id, upload_result, handle_extension_fn, send_message_fn, agent_dict, context)
            # Check if upload succeeded
            if '✅' in result or 'done' in result.lower():
                pipeline_tracker.complete_step(pt_id, "upload", result[:100])
                pipeline_tracker.complete_task(pt_id, total_msg + result, os.path.basename(processed_path))
            else:
                pipeline_tracker.fail_step(pt_id, "upload", result[:200])
                pipeline_tracker.fail_task(pt_id, f"Upload: {result[:200]}")
            return total_msg + result + f"\n\n📁 File: `{processed_path}`\n▶️ Xem: {video_serve_url}"
        else:
            pipeline_tracker.complete_step(pt_id, "upload", f"Queued (long video) Task: {task_id[:12]}")
            pipeline_tracker.complete_task(pt_id, total_msg + "Video dài, đang chờ YouTube xử lý", os.path.basename(processed_path))
            asyncio.create_task(_poll_long_video_bg(task_id, handle_extension_fn, send_message_fn, agent_dict, context))
            return total_msg + upload_result + f"\n\n📁 File: `{processed_path}`\n▶️ Xem: {video_serve_url}\n\n*(Video dài, bot sẽ ping khi YouTube duyệt xong!)*"

    pipeline_tracker.complete_step(pt_id, "upload", upload_result[:100])
    pipeline_tracker.complete_task(pt_id, total_msg + upload_result, os.path.basename(processed_path))
    return total_msg + upload_result + f"\n\n📁 File: `{processed_path}`\n▶️ Xem: {video_serve_url}"


# ═══════════════════════════════════════════════════════════════
#  LIVESTREAM PIPELINE (Source → Create Broadcast → SEO Title → FFmpeg)
# ═══════════════════════════════════════════════════════════════

async def execute_livestream_pipeline(
    source_url: str,
    user_text: str,
    agent_dict: Dict,
    send_message_fn,
    context: Dict,
) -> str:
    """Full Auto-Livestream Pipeline:
    1. Resolve YouTube credential (token_id)
    2. AI SEO Title generation (parallel)
    3. Call /api/v1/livestream/auto-live (create broadcast + start FFmpeg)
    4. Notify user with result
    """
    import time
    token = context.get("token", "")
    chat_id = context.get("chat_id", 0)
    lang = get_user_lang(chat_id)
    pipeline_start = time.time()

    await send_message_fn(token, chat_id,
        "🔴 **Auto-Livestream Pipeline**\n\n"
        "Step 1/3: 🔑 Resolving YouTube credentials...\n"
        "Step 2/3: ✨ AI SEO Title...\n"
        "Step 3/3: 🎬 Create Broadcast + FFmpeg..."
    )

    # ── Step 0: Pre-validate source URL ──
    resolved_url = source_url
    source_title = ""
    is_live_link = any(k in source_url.lower() for k in ["douyin.com", "tiktok.com", "iesdouyin.com"])

    if is_live_link:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/parse",
                    json={"url": source_url},
                )
                if resp.status_code == 200:
                    parse_data = resp.json().get("data", {})
                    content_type = parse_data.get("type", "")
                    source_title = parse_data.get("title", "") or parse_data.get("author", "")

                    if content_type == "live":
                        # It's a live stream — get the HLS/FLV URL
                        hls_url = parse_data.get("download_url", "")
                        if hls_url:
                            resolved_url = hls_url
                            await send_message_fn(token, chat_id,
                                f"✅ Step 0/3: Phòng live **đang hoạt động** ✨\n"
                                f"👤 {parse_data.get('author', 'Unknown')}\n"
                                f"📺 {source_title}"
                            )
                        else:
                            return (
                                "🔴 **Livestream Pipeline**\n\n"
                                "❌ **Phòng live đã offline** hoặc không thể lấy luồng stream.\n"
                                f"👤 {parse_data.get('author', 'Unknown')}\n"
                                f"🔗 {source_url}\n\n"
                                "_Vui lòng kiểm tra lại link hoặc chờ phòng live mở lại._"
                            )
                    elif content_type == "video":
                        # It's a regular video — can still stream it
                        video_url = parse_data.get("download_url", "")
                        if video_url:
                            resolved_url = video_url
                            await send_message_fn(token, chat_id,
                                f"✅ Step 0/3: Đây là **video** (không phải live)\n"
                                f"📺 {source_title}\n"
                                f"_Sẽ dùng preset file_loop để stream._"
                            )
                        else:
                            return (
                                "🔴 **Livestream Pipeline**\n\n"
                                "❌ **Không thể lấy link download** từ video.\n"
                                f"🔗 {source_url}\n\n"
                                "_Cookie Douyin có thể đã hết hạn. Kiểm tra Settings._"
                            )
                    else:
                        await send_message_fn(token, chat_id,
                            f"⚠️ Step 0/3: Loại nội dung: **{content_type}**\n"
                            f"_Sẽ thử stream trực tiếp._"
                        )
                elif resp.status_code == 404:
                    try:
                        err_detail = resp.json().get("detail", "")
                    except Exception:
                        err_detail = resp.text[:300]
                    return (
                        "🔴 **Livestream Pipeline**\n\n"
                        f"❌ **Link không hợp lệ hoặc đã hết hạn**\n"
                        f"🔗 {source_url}\n"
                        f"📝 {err_detail}\n\n"
                        "_Kiểm tra lại link hoặc thử link khác._"
                    )
                elif resp.status_code == 400:
                    try:
                        err_detail = resp.json().get("detail", "")
                    except Exception:
                        err_detail = resp.text[:300]
                    return (
                        "🔴 **Livestream Pipeline**\n\n"
                        f"❌ **Không phân tích được link**\n"
                        f"🔗 {source_url}\n"
                        f"📝 {err_detail}\n\n"
                        "_Vui lòng nhập link đầy đủ (https://www.douyin.com/video/xxx)._"
                    )
        except httpx.ConnectError:
            # Downloader service not available — skip validation, try anyway
            await send_message_fn(token, chat_id,
                "⚠️ Step 0/3: Không kết nối được Downloader API, sẽ thử stream trực tiếp."
            )
        except Exception as e:
            print(f"[Livestream] Pre-validate error: {e}")
            await send_message_fn(token, chat_id,
                f"⚠️ Step 0/3: Lỗi kiểm tra link: {str(e)[:100]}\n_Sẽ thử stream trực tiếp._"
            )

    # ── Step 1: Resolve token_id ──
    token_id = ""
    email_display = "default"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{TUBECLI_BASE_URL}/api/v1/livestream/credentials")
            if resp.status_code == 200:
                creds = resp.json().get("credentials", [])
                if creds:
                    text_lower = user_text.lower()

                    # Priority 1: Match email from user text (e.g. "2@5.com")
                    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_text)
                    if email_match:
                        target_email = email_match.group(0)
                        for c in creds:
                            if c.get("authorized_email", "").lower() == target_email.lower():
                                token_id = c["token_id"]
                                break

                    # Priority 2: Match "kênh N" via channel_cache
                    if not token_id:
                        try:
                            from tubecli.core.channel_cache import channel_cache
                            ch = channel_cache.resolve_channel("youtube", user_text)
                            if ch:
                                ch_email = ch.get("email", "").lower()
                                if ch_email:
                                    for c in creds:
                                        if c.get("authorized_email", "").lower() == ch_email:
                                            token_id = c["token_id"]
                                            break
                        except Exception as e:
                            print(f"[Livestream] Channel cache resolve error: {e}")

                    # Fallback: use first available credential
                    if not token_id:
                        token_id = creds[0].get("token_id", "")
                    
                    email_display = next(
                        (c.get("authorized_email", "") for c in creds if c.get("token_id") == token_id),
                        "default"
                    )
                    await send_message_fn(token, chat_id,
                        f"✅ Step 1/3: YouTube account: **{email_display}**"
                    )
                else:
                    return "❌ Không tìm thấy YouTube credentials. Vui lòng authorize trong Auth Manager."
    except Exception as e:
        print(f"[Livestream] Credential resolve error: {e}")
        # token_id = "" will let backend use default

    # ── Step 2: AI SEO Title ──
    ai_title = source_title or "Live Restream"
    try:
        from tubecli.core.brain import AgentBrain
        title_prompt = (
            f"Generate a short, catchy YouTube livestream title (max 60 chars) for this stream.\n"
            f"Source: {source_url}\n"
            f"Source title: {source_title}\n"
            f"User request: {user_text}\n"
            f"Rules: Vietnamese or English based on user's language. No quotes. SEO optimized. Return ONLY the title."
        )
        title_result = AgentBrain.quick_reply(
            message=title_prompt,
            agent=agent_dict,
            history=[],
        )
        if title_result and isinstance(title_result, str) and len(title_result.strip()) > 5:
            # Clean AI response — take first line, remove quotes
            first_line = title_result.strip().split('\n')[0]
            ai_title = first_line.strip().strip('"').strip("'")[:80]
        await send_message_fn(token, chat_id,
            f"✅ Step 2/3: AI Title: **{ai_title}**"
        )
    except Exception as e:
        print(f"[Livestream] AI title error: {e}")
        await send_message_fn(token, chat_id,
            f"⚠️ Step 2/3: AI Title fallback → **{ai_title}**"
        )

    # ── Step 3: Call auto-live API ──
    try:
        payload = {
            "token_id": token_id,
            "title": ai_title,
            "description": f"Auto-livestream via TubeCLI chatbot | Source: {source_url}",
            "privacy": "public",
            "input_source": resolved_url,   # Use pre-resolved URL (HLS/FLV)
            "preset": "file",
            "resolution": "1080p",
            "frame_rate": "30fps",
        }

        # Detect preset based on content type
        if is_live_link or any(k in resolved_url.lower() for k in [".m3u8", ".flv", "rtmp://", "live"]):
            payload["preset"] = "file"  # Real-time restream
        elif resolved_url.endswith((".mp4", ".mkv", ".avi", ".mov")):
            payload["preset"] = "file_loop"  # Loop video file

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{TUBECLI_BASE_URL}/api/v1/livestream/auto-live",
                json=payload,
            )

            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "")
                broadcast = data.get("broadcast", {})
                ffmpeg_sid = data.get("ffmpeg_session_id", "")
                elapsed = int((time.time() - pipeline_start) * 1000)

                if status == "success":
                    broadcast_id = broadcast.get("broadcast_id", "")
                    stream_key = broadcast.get("stream_key", "???")
                    yt_url = f"https://www.youtube.com/watch?v={broadcast_id}"

                    result_msg = (
                        f"🔴 **LIVE! Pipeline hoàn tất** ({elapsed}ms)\n\n"
                        f"📺 **{ai_title}**\n"
                        f"🔗 YouTube: {yt_url}\n"
                        f"🔑 Stream Key: `{stream_key[:12]}...`\n"
                        f"🎬 FFmpeg Session: `{ffmpeg_sid}`\n"
                        f"📡 Source: `{source_url[:60]}...`\n\n"
                        f"_Dùng lệnh 'stop live' để dừng stream._"
                    )
                    return result_msg

                elif status == "partial":
                    broadcast_id = broadcast.get("broadcast_id", "")
                    ffmpeg_err = data.get("ffmpeg_error", "Unknown")
                    return (
                        f"⚠️ **Broadcast đã tạo nhưng FFmpeg lỗi**\n\n"
                        f"📺 Broadcast ID: `{broadcast_id}`\n"
                        f"🔑 Stream Key: `{broadcast.get('stream_key', '???')}`\n"
                        f"❌ FFmpeg: {ffmpeg_err}\n\n"
                        f"_Thử lại bằng cách gửi link khác hoặc kiểm tra FFmpeg._"
                    )
                else:
                    return f"❌ Livestream lỗi: {data.get('message', 'Không rõ lỗi')}"
            else:
                try:
                    err_detail = resp.json().get("detail", resp.text[:300])
                except Exception:
                    err_detail = resp.text[:300]
                err_str = str(err_detail).lower()

                # ── User-friendly error messages ──
                if "not enabled for live streaming" in err_str:
                    return (
                        f"🔴 **Kênh chưa bật Live Streaming**\n\n"
                        f"📧 Account: **{email_display if token_id else 'default'}**\n"
                        f"❌ YouTube yêu cầu bật tính năng Live trước khi phát.\n\n"
                        f"📋 **Cách bật:**\n"
                        f"1. Vào [YouTube Studio](https://studio.youtube.com)\n"
                        f"2. Chọn **Settings** → **Channel** → **Feature eligibility**\n"
                        f"3. Bật **Live streaming**\n"
                        f"4. Chờ 24h để YouTube kích hoạt\n\n"
                        f"_Sau khi bật xong, thử lại lệnh này._"
                    )
                elif "quota" in err_str:
                    return (
                        f"🔴 **YouTube API quota đã hết**\n\n"
                        f"❌ Đã vượt giới hạn API YouTube trong ngày.\n"
                        f"_Thử lại sau 24h hoặc dùng account khác._"
                    )
                elif "forbidden" in err_str or "403" in err_str:
                    return (
                        f"🔴 **Không có quyền truy cập**\n\n"
                        f"❌ Account không có quyền tạo broadcast.\n"
                        f"_Kiểm tra lại quyền OAuth hoặc authorize lại._"
                    )
                else:
                    return f"❌ API lỗi ({resp.status_code}): {err_detail}"

    except httpx.ConnectError:
        return "❌ Không kết nối được TubeCLI server. Kiểm tra service đang chạy."
    except Exception as e:
        return f"❌ Livestream pipeline lỗi: {str(e)[:300]}"


# ═══════════════════════════════════════════════════════════════
#  EXTENSION ACTION HANDLER
# ═══════════════════════════════════════════════════════════════

async def handle_extension_action(reply: str, agent_dict: Dict, context: Dict = None) -> Any:
    """Parse AI reply for JSON action blocks and execute extension logic."""
    if not isinstance(reply, str):
        return reply

    action_data = extract_json_action(reply)
    if not action_data:
        return reply

    action_type = action_data.get("action", "")

    # ── Core built-in actions ──
    if action_type == "download_video":
        url = action_data.get("url", "")
        if not url:
            return "❌ Thiếu URL video."
        return await execute_download(url, agent_dict)

    elif action_type == "create_team":
        return await exec_create_team(action_data)

    elif action_type == "run_api":
        return await exec_run_api(action_data)

    elif action_type == "schedule_event":
        return await exec_schedule_event(action_data)

    elif action_type == "create_livestream":
        return await exec_create_livestream(action_data, context)


    # ── Dynamic extension actions ──
    try:
        from tubecli.core.extension_manager import extension_manager
        ext_actions = extension_manager.get_all_telegram_actions()

        if action_type in ext_actions:
            handler_info = ext_actions[action_type]
            handler_fn = handler_info["handler"]
            from tubecli.core.bot_i18n import get_user_lang
            ext_context = {"agent": agent_dict}
            if context:
                ext_context["token"] = context.get("token", "")
                chat_id = context.get("chat_id")
                ext_context["chat_id"] = chat_id
                ext_context["lang"] = get_user_lang(chat_id)
            else:
                ext_context["lang"] = get_user_lang()
            result = await handler_fn(action_data, ext_context)
            return result
    except Exception as e:
        print(f"[Actions] Extension action error: {e}")
        import traceback
        traceback.print_exc()

    return reply


# ═══════════════════════════════════════════════════════════════
#  SPECIFIC ACTION EXECUTORS
# ═══════════════════════════════════════════════════════════════

async def exec_schedule_event(action_data: Dict) -> str:
    """Execute schedule_event action — create Google Calendar event."""
    summary = action_data.get("summary", "")
    start = action_data.get("start", "")
    end = action_data.get("end", "")
    description = action_data.get("description", "")
    location = action_data.get("location", "")
    recurrence_str = action_data.get("recurrence", "")

    if not summary:
        return "❌ Thiếu tên sự kiện (summary)."
    if not start:
        return "❌ Thiếu thời gian bắt đầu (start)."

    print(f"[Actions] 📅 Creating calendar event: {summary}")

    try:
        from tubecli.extensions.calendar_manager.extension import calendar_manager

        email = ""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    email = data.get("default_calendar_email", "")
        except Exception:
            pass

        recurrence = [recurrence_str] if recurrence_str else []

        result = calendar_manager.create_event(
            email=email, summary=summary, start=start, end=end,
            description=description, location=location, recurrence=recurrence,
        )

        if result.get("status") == "success":
            msg = f"✅ **Đã lập lịch thành công!**\n\n"
            msg += f"📅 **{result.get('summary', summary)}**\n"
            msg += f"🕐 {result.get('start', start)}\n"
            if result.get("recurrence"):
                r = result["recurrence"][0] if result["recurrence"] else ""
                if "DAILY" in r: msg += "🔄 Lặp lại: Hằng ngày\n"
                elif "WEEKLY" in r: msg += "🔄 Lặp lại: Hằng tuần\n"
                elif "MONTHLY" in r: msg += "🔄 Lặp lại: Hằng tháng\n"
                else: msg += f"🔄 Lặp lại: {r}\n"
            if result.get("html_link"):
                msg += f"🔗 [Mở trong Calendar]({result['html_link']})"
            return msg
        else:
            return f"❌ Lỗi tạo sự kiện: {result.get('message', 'Unknown error')}"

    except ImportError:
        return "❌ Calendar Manager extension chưa được cài đặt."
    except Exception as e:
        return f"❌ Lỗi lập lịch: {str(e)[:300]}"


async def exec_create_team(action_data: Dict) -> str:
    """Execute create_team action."""
    try:
        template = action_data.get("template", "dev_team")
        name = action_data.get("name", "New Team")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{TUBECLI_BASE_URL}/api/v1/multi-agents/teams/from-template",
                json={"template_id": template, "name": name}
            )
            if resp.status_code == 200:
                data = resp.json()
                team = data.get("team", {})
                node_count = len(team.get("nodes", []))
                return (
                    f"✅ Đã tạo team *{team.get('name', name)}* thành công!\n"
                    f"📋 Template: `{template}`\n"
                    f"👥 Số roles: {node_count}\n"
                    f"🆔 Team ID: `{team.get('id', 'N/A')}`"
                )
            else:
                return f"❌ Tạo team thất bại: {resp.text[:200]}"
    except Exception as e:
        return f"❌ Lỗi tạo team: {e}"


async def exec_run_api(action_data: Dict) -> str:
    """Execute a direct internal API call."""
    method = action_data.get("method", "GET").upper()
    endpoint = action_data.get("endpoint", "")
    body = action_data.get("body", {})

    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint

    url = f"{TUBECLI_BASE_URL}{endpoint}"
    print(f"[Actions] run_api: {method} {url}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url)
            elif method == "POST":
                resp = await client.post(url, json=body)
            elif method == "PUT":
                resp = await client.put(url, json=body)
            elif method == "DELETE":
                resp = await client.delete(url)
            else:
                return f"❌ Method không hỗ trợ: {method}"

            try:
                data = resp.json()
                if isinstance(data, dict):
                    if data.get("success"):
                        msg_data = data.get("data") or data.get("message") or data
                        return f"✅ Thành công:\n```\n{json.dumps(msg_data, ensure_ascii=False, indent=2)[:500]}\n```"
                    else:
                        return f"❌ Lỗi API: {data.get('detail', str(data)[:200])}"
                return f"✅ Response: `{str(data)[:500]}`"
            except Exception:
                return f"✅ Response ({resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return f"❌ Lỗi gọi API {endpoint}: {str(e)[:200]}"


async def exec_create_livestream(action_data: Dict, context: Dict = None) -> str:
    """Execute create_livestream action — fallback handler for extension-dispatched livestream requests."""
    source_url = action_data.get("input_source", "") or action_data.get("url", "")
    title = action_data.get("title", "Live Restream")
    token_id = action_data.get("token_id", "")
    preset = action_data.get("preset", "file")
    privacy = action_data.get("privacy", "public")

    if not source_url:
        return "❌ Thiếu link nguồn (input_source). Vui lòng cung cấp URL để restream."

    payload = {
        "token_id": token_id,
        "title": title,
        "description": f"Auto-livestream via TubeCLI",
        "privacy": privacy,
        "input_source": source_url,
        "preset": preset,
        "resolution": "1080p",
        "frame_rate": "30fps",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{TUBECLI_BASE_URL}/api/v1/livestream/auto-live",
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                broadcast = data.get("broadcast", {})
                status = data.get("status", "")
                if status == "success":
                    broadcast_id = broadcast.get("broadcast_id", "")
                    return (
                        f"🔴 **LIVE!**\n"
                        f"📺 {broadcast.get('title', title)}\n"
                        f"🔗 https://www.youtube.com/watch?v={broadcast_id}\n"
                        f"🔑 Stream Key: `{broadcast.get('stream_key', '???')[:12]}...`\n"
                        f"🎬 FFmpeg: `{data.get('ffmpeg_session_id', '')}`"
                    )
                else:
                    return f"❌ {data.get('message', 'Livestream failed')}"
            else:
                try:
                    err = resp.json().get("detail", resp.text[:300])
                except Exception:
                    err = resp.text[:300]
                return f"❌ Livestream API error ({resp.status_code}): {err}"
    except Exception as e:
        return f"❌ Livestream error: {str(e)[:300]}"
