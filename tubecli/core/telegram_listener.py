import asyncio
import httpx
import traceback
import datetime
import os
import json
import re
from typing import Dict, Any, Optional

from tubecli.core.agent import agent_manager
from tubecli.core.brain import AgentBrain

# Try to find global settings file
from tubecli.config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "global_settings.json"
TUBECLI_BASE_URL = "http://localhost:5295"


class TelegramListener:
    def __init__(self):
        self.running = False
        self.polling_tasks: Dict[str, asyncio.Task] = {}
        self.offsets: Dict[str, int] = {}
        self._sync_task = None
        self.client = httpx.AsyncClient(timeout=40)

    def get_configured_tokens(self) -> Dict[str, Dict[str, Any]]:
        """Finds all configured tokens and associated context (agent or global)"""
        tokens = {}

        # 1. Global Token
        global_token = None
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    global_token = data.get("telegram_bot_token")
            except Exception:
                pass

        if global_token:
            global_token = global_token.strip()
            tokens[global_token] = {"type": "global"}

        # 2. Agent-specific Tokens
        agents = agent_manager.get_all()
        for a in agents:
            if a.telegram_token:
                tok = a.telegram_token.strip()
                if tok:
                    tokens[tok] = {"type": "agent", "agent_id": a.id, "agent_name": a.name}

        return tokens

    async def _poll_for_token(self, token: str, context: Dict[str, Any]):
        """Long-polling loop for a specific telegram bot token"""
        bot_name = context.get('agent_name', 'Global')
        print(f"[TelegramListener] Starting polling for {bot_name} Bot...")

        # Delete any existing webhook first
        try:
            del_resp = await self.client.get(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                params={"drop_pending_updates": "false"},
                timeout=10
            )
            del_data = del_resp.json()
            if del_data.get("ok"):
                print(f"[TelegramListener] Webhook cleared for {bot_name} Bot")
        except Exception as e:
            print(f"[TelegramListener] Webhook clear error: {e}")

        url = f"https://api.telegram.org/bot{token}/getUpdates"

        while self.running:
            try:
                offset = self.offsets.get(token, 0)
                resp = await self.client.get(url, params={"offset": offset, "timeout": 30})

                if resp.status_code != 200:
                    if resp.status_code == 401:
                        print(f"[TelegramListener] Invalid token for {bot_name} Bot")
                        break
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                if not data.get("ok"):
                    await asyncio.sleep(5)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    update_id = update["update_id"]
                    self.offsets[token] = update_id + 1

                    message = update.get("message")
                    if not message or "text" not in message:
                        continue

                    chat_id = message["chat"]["id"]
                    text = message["text"]

                    print(f"💬 [Telegram -> {bot_name}] {chat_id}: {text}")

                    # Process with Brain
                    asyncio.create_task(
                        self._process_and_reply(token, chat_id, text, context)
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TelegramListener] Polling error for {bot_name}: {e}")
                await asyncio.sleep(5)

    async def _process_and_reply(self, token: str, chat_id: int, text: str, context: Dict[str, Any]):
        """Process message and send reply (handles file sending too)."""
        typing_task = None
        try:
            # Start typing indicator loop — keeps showing "typing..." while AI processes
            typing_task = asyncio.create_task(
                self._typing_loop(token, chat_id)
            )

            result = await self._process_message(text, context)

            # Cancel typing indicator
            typing_task.cancel()

            if isinstance(result, dict) and result.get("type") == "file":
                await self._send_file(token, chat_id, result)
            else:
                reply_text = result if isinstance(result, str) else str(result)
                if reply_text:
                    await self._send_message(token, chat_id, reply_text)

        except Exception as e:
            if typing_task:
                typing_task.cancel()
            # Log full traceback to server console
            import traceback
            full_error = traceback.format_exc()
            print(f"[TelegramListener] ❌ Reply error: {e}\n{full_error}")
            # Send user-friendly error with enough detail
            error_type = type(e).__name__
            error_msg = str(e)
            await self._send_message(
                token, chat_id,
                f"⚠️ Lỗi xử lý: `{error_type}: {error_msg[:300]}`"
            )

    async def _typing_loop(self, token: str, chat_id: int):
        """Keep sending 'typing' action every 4s while AI is processing."""
        typing_url = f"https://api.telegram.org/bot{token}/sendChatAction"
        try:
            while True:
                try:
                    await self.client.post(typing_url, json={
                        "chat_id": chat_id,
                        "action": "typing"
                    })
                except Exception:
                    pass
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass


    async def _send_message(self, token: str, chat_id: int, text: str):
        """Send text message via Telegram."""
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            await self.client.post(send_url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
        except Exception:
            # Retry without markdown if fails
            try:
                await self.client.post(send_url, json={
                    "chat_id": chat_id,
                    "text": text
                })
            except Exception as e2:
                print(f"[TelegramListener] Send message error: {e2}")

    async def _send_file(self, token: str, chat_id: int, file_info: Dict):
        """Send a file via Telegram sendDocument or sendVideo."""
        file_path = file_info.get("file_path", "")
        caption = file_info.get("caption", "")
        file_type = file_info.get("file_type", "document")

        if not file_path or not os.path.exists(file_path):
            # File not local — try sending as URL or fallback
            download_url = file_info.get("download_url", "")
            await self._send_message(token, chat_id,
                f"✅ {caption}\n\n📥 Download: {download_url}" if download_url else f"✅ {caption}"
            )
            return

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"[TelegramListener] Sending file: {file_path} ({file_size_mb:.1f} MB)")

        # Telegram limit: 50MB for bots
        if file_size_mb > 50:
            await self._send_message(token, chat_id,
                f"⚠️ File quá lớn để gửi qua Telegram ({file_size_mb:.1f} MB > 50 MB).\n"
                f"📁 Đã lưu tại: `{file_path}`\n"
                f"🌐 Xem tại Dashboard: {TUBECLI_BASE_URL}"
            )
            return

        # Choose endpoint based on file type
        api_method = "sendVideo" if file_type == "video" else "sendDocument"
        send_url = f"https://api.telegram.org/bot{token}/{api_method}"

        async with httpx.AsyncClient(timeout=120) as upload_client:
            try:
                with open(file_path, "rb") as f:
                    field_name = "video" if file_type == "video" else "document"
                    response = await upload_client.post(
                        send_url,
                        data={"chat_id": str(chat_id), "caption": caption},
                        files={field_name: (os.path.basename(file_path), f, "video/mp4")}
                    )

                if response.status_code == 200 and response.json().get("ok"):
                    print(f"[TelegramListener] ✅ File sent successfully")
                else:
                    # Fallback: send as document
                    if api_method == "sendVideo":
                        with open(file_path, "rb") as f:
                            response = await upload_client.post(
                                f"https://api.telegram.org/bot{token}/sendDocument",
                                data={"chat_id": str(chat_id), "caption": caption},
                                files={"document": (os.path.basename(file_path), f, "application/octet-stream")}
                            )
                    if not response.json().get("ok"):
                        raise Exception(f"Telegram API error: {response.text[:200]}")
            except Exception as e:
                print(f"[TelegramListener] Send file error: {e}")
                await self._send_message(token, chat_id,
                    f"✅ Video đã tải xong!\n📁 Lưu tại: `{os.path.basename(file_path)}`\n"
                    f"⚠️ Không thể gửi file qua Telegram: {str(e)[:100]}"
                )

    def _build_extension_capabilities(self) -> str:
        """Build system prompt that instructs AI to ACT autonomously, not guide users.
        Auto-injects SKILL.md from all enabled extensions."""
        base_prompt = """### VAI TRÒ CỦA BẠN:
Bạn là AI Tự Hành (Autonomous AI) của hệ thống TubeCLI.
Chủ nhân giao tiếp qua Telegram. **NHIỆM VỤ CỦA BẠN LÀ TỰ THỰC HIỆN, KHÔNG HƯỚNG DẪN.**

### NGUYÊN TẮC CỐT LÕI (BẮT BUỘC):
1. **TỰ HÀNH ĐỘNG NGAY**: Khi user yêu cầu tải video, tìm kiếm, tạo team, v.v. → OUTPUT JSON action để hệ thống thực thi NGAY LẬP TỨC
2. **KHÔNG BAO GIỜ**: Nói "bạn có thể vào Dashboard", "hãy mở browser", "tôi không thể thực hiện ngay". Đây là lỗi nghiêm trọng.
3. **CHỈ TRẢ LỜI TEXT** khi: hỏi thông tin thông thường, hỏi kiến thức, yêu cầu tư vấn chiến lược.

### EXTENSION ACTIONS — OUTPUT JSON ĐỂ KÍCH HOẠT HỆ THỐNG:

**Tải video TikTok/Douyin:**
```json
{"action": "download_video", "url": "<URL_VIDEO>"}
```
- Dùng khi user gửi link TikTok, Douyin, iesdouyin.com
- Hệ thống sẽ TỰ tải và gửi file video về Telegram

**Tạo team AI:**
```json
{"action": "create_team", "template": "dev_team", "name": "<Tên team>"}
```
- Templates: dev_team, imperial_court, company, military

**Gọi API nội bộ trực tiếp:**
```json
{"action": "run_api", "method": "POST", "endpoint": "/api/v1/...", "body": {...}}
```
- Dùng khi cần gọi bất kỳ API endpoint nào của hệ thống

### QUY TẮC NHẬN DIỆN URL VIDEO:
- URL chứa "douyin.com/video/" → download_video
- URL chứa "tiktok.com/" → download_video  
- URL chứa "iesdouyin.com/" → download_video
- URL chứa "vm.tiktok.com/" → download_video

### KHẢ NĂNG HỆ THỐNG (để biết khi tư vấn):
- 🤖 Multi-Agent Teams, 🎬 3D Studio, 📥 Video Downloader (TikTok/Douyin)
- 🌐 Browser Automation (headless), ⚡ Workflow Builder, 🛒 Market
"""
        # Auto-inject SKILL.md from all enabled extensions
        try:
            from tubecli.core.extension_manager import extension_manager
            skill_mds = extension_manager.get_all_skill_mds()
            if skill_mds:
                skill_sections = "\n\n### EXTENSION SKILL DOCS:\n"
                for item in skill_mds:
                    skill_sections += f"\n---\n**Extension: {item['extension']}**\n{item['skill_md']}\n"
                return base_prompt + skill_sections
        except Exception:
            pass
        return base_prompt


    def _get_cloud_model_config(self) -> Dict[str, Any]:
        """Read cloud API model from global settings."""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                model = data.get("default_model", "")
                if model and model != "qwen:latest":
                    return {"model": model}
        except Exception:
            pass
        return {}

    async def _process_message(self, text: str, context: Dict[str, Any]):
        """Route message to Brain and return reply (str or file dict)."""
        from tubecli.core.skill import skill_manager

        agent_id = context.get("agent_id")

        if not agent_id:
            agents = agent_manager.get_all()
            if not agents:
                return "Tôi chưa được cấu hình Agent nào trong hệ thống."
            main_agent = next(
                (a for a in agents if "tổng" in a.name.lower() or "orchestra" in a.name.lower()),
                agents[0]
            )
            agent_id = main_agent.id

        agent = agent_manager.get(agent_id)
        if not agent:
            return "Lỗi: Không tìm thấy Agent cấu hình."

        agent_dict = agent.to_dict()

        # Override model with global settings if agent uses default/None
        cloud_cfg = self._get_cloud_model_config()
        if cloud_cfg.get("model") and (not agent_dict.get("model") or agent_dict["model"] == "qwen:latest"):
            agent_dict["model"] = cloud_cfg["model"]

        # Read cloud API keys
        try:
            from tubecli.extensions.cloud_api.extension import key_manager
            cloud_keys = {}
            for provider in ["gemini", "openai", "claude", "deepseek"]:
                key = key_manager.get_active_key(provider)
                if key:
                    cloud_keys[provider] = key
            if cloud_keys:
                agent_dict["cloud_api_keys"] = {**agent_dict.get("cloud_api_keys", {}), **cloud_keys}
        except Exception:
            pass

        # === Fast-path: detect video URL directly in message ===
        video_url = self._extract_video_url(text)
        if video_url:
            print(f"[TelegramListener] 🎯 Fast-path: detected video URL: {video_url}")
            return await self._execute_download(video_url, agent_dict)

        # Inject autonomous system prompt
        ext_capabilities = self._build_extension_capabilities()
        original_prompt = agent_dict.get("system_prompt", "You are a helpful assistant.")
        agent_dict["system_prompt"] = f"{original_prompt}\n\n{ext_capabilities}"

        # Get allowed skills
        all_skills = skill_manager.get_all()
        if agent.allowed_skills:
            skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
        else:
            skills = [s.to_dict() for s in all_skills]

        history = agent.history_log or []

        # Run Brain chat
        brain_result = AgentBrain.chat(
            message=text,
            agent=agent_dict,
            skills=skills,
            history=history,
        )

        reply = brain_result.get("reply", "...")
        action = brain_result.get("action")
        skill_used = None

        # If skill needed — run it
        if action == "run_skill" and brain_result.get("skill_id"):
            skill_id = brain_result["skill_id"]
            skill = skill_manager.get(skill_id)
            if skill:
                skill_used = skill.name
                skill_input = brain_result.get("skill_input", text)

                # Check if skill requires browser
                wf_data = (skill.to_dict() or {}).get("workflow_data", {})
                nodes = wf_data.get("nodes", [])
                has_browser = any(
                    n.get("type", "") in ("browser", "browser_control", "puppeteer", "browser_action")
                    for n in nodes
                )

                if has_browser:
                    # 2.A: Run browser in headless mode — patch skill to force headless
                    try:
                        skill_dict = skill.to_dict()
                        # Force headless on all browser nodes
                        for n in skill_dict.get("workflow_data", {}).get("nodes", []):
                            if n.get("type") in ("browser_action", "browser_control", "puppeteer"):
                                n.setdefault("config", {})["headless"] = True
                        
                        reply = await asyncio.wait_for(
                            AgentBrain.autonomous_run(
                                message=skill_input,
                                agent=agent_dict,
                                skill=skill_dict
                            ),
                            timeout=90
                        )
                        skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())
                    except asyncio.TimeoutError:
                        reply = f"⏰ Skill '{skill.name}' chạy quá lâu (>90s). Hệ thống đang tiếp tục xử lý."
                    except Exception as e:
                        reply = f"⚠️ Skill '{skill.name}' gặp lỗi: {str(e)[:200]}"
                else:
                    try:
                        reply = await asyncio.wait_for(
                            AgentBrain.autonomous_run(
                                message=skill_input,
                                agent=agent_dict,
                                skill=skill.to_dict()
                            ),
                            timeout=60
                        )
                        skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())
                    except asyncio.TimeoutError:
                        reply = f"⏰ Skill '{skill.name}' chạy quá 60s."
                    except Exception as e:
                        reply = f"⚠️ Skill '{skill.name}' gặp lỗi: {str(e)[:200]}"

        elif action == "create_skill":
            name = brain_result.get("skill_name", "New Skill")
            desc = brain_result.get("skill_desc", "")
            instructions = brain_result.get("skill_instructions", [])
            sop_text = "\n".join([f"{i+1}. {instr}" for i, instr in enumerate(instructions)])
            try:
                skill_manager.create(
                    name=name, description=desc, skill_type="AI Self-Created",
                    workflow_data={"sop": sop_text, "nodes": [{"type": "text", "data": {"text": sop_text}}]},
                    commands=[name.lower()]
                )
                skill_used = f"Created: {name}"
            except Exception as e:
                reply = f"[Create Skill Error] {e}"

        elif action == "download_video":
            # Brain detected and routed a download_video action
            action_data = brain_result.get("action_data", {})
            url = action_data.get("url", "")
            if url:
                return await self._execute_download(url, agent_dict)
            reply = "❌ AI muốn tải video nhưng không tìm thấy URL."

        elif action == "create_team":
            action_data = brain_result.get("action_data", {})
            reply = await self._exec_create_team(action_data)

        elif action == "run_api":
            action_data = brain_result.get("action_data", {})
            reply = await self._exec_run_api(action_data)

        # Handle Extension Actions from AI response text (fallback for inline JSON)
        result = await self._handle_extension_action(reply, agent_dict)


        # Save History
        reply_for_history = result if isinstance(result, str) else f"[File sent: {result.get('caption', '')}]"
        history.append({"role": "user", "content": text, "timestamp": datetime.datetime.now().isoformat()})
        history.append({
            "role": "assistant",
            "content": reply_for_history,
            "timestamp": datetime.datetime.now().isoformat(),
            "skill_used": skill_used
        })
        if len(history) > 50:
            history = history[-50:]

        # Non-blocking memory update
        async def _bg_mem():
            try:
                AgentBrain.post_chat_memory_update(agent_id, agent_dict, history)
                agent_manager.update(agent_id, history_log=history)
            except Exception as e:
                print(f"[TelegramListener] Memory err: {e}")
        asyncio.create_task(_bg_mem())

        agent_manager.update(agent_id, history_log=history)
        return result

    def _extract_video_url(self, text: str) -> Optional[str]:
        """Fast-path: extract video URL directly from message text."""
        video_patterns = [
            r'https?://(?:www\.)?douyin\.com/video/\S+',
            r'https?://(?:www\.)?tiktok\.com/\S+',
            r'https?://vm\.tiktok\.com/\S+',
            r'https?://(?:www\.)?iesdouyin\.com/\S+',
            r'https?://v\.douyin\.com/\S+',
        ]
        for pattern in video_patterns:
            m = re.search(pattern, text)
            if m:
                url = m.group(0).rstrip('.,;?!')
                return url
        return None

    async def _handle_extension_action(self, reply: str, agent_dict: Dict):
        """Parse AI reply for JSON action blocks and execute extension logic.
        Returns str or dict (for file sending).
        """
        if not isinstance(reply, str):
            return reply

        # Try to extract JSON action from the reply
        action_data = self._extract_json_action(reply)
        if not action_data:
            return reply

        action_type = action_data.get("action", "")
        print(f"🔧 [TelegramListener] Extension action detected: {action_type}")

        if action_type == "download_video":
            url = action_data.get("url", "")
            if not url:
                return "❌ Thiếu URL video."
            return await self._execute_download(url, agent_dict)

        elif action_type == "create_team":
            return await self._exec_create_team(action_data)

        elif action_type == "run_api":
            return await self._exec_run_api(action_data)

        else:
            # Unknown action — return original reply
            return reply

    def _extract_json_action(self, text: str) -> Optional[Dict]:
        """Extract the first valid JSON action block from text."""
        # Try code block first: ```json {...} ```
        patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'(\{"action"\s*:\s*"[^"]+"\s*.*?\})',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for raw in matches:
                try:
                    data = json.loads(raw)
                    if "action" in data:
                        return data
                except Exception:
                    continue
        return None

    async def _execute_download(self, url: str, agent_dict: Dict) -> dict:
        """Execute video download via Downloader extension API and return file info."""
        print(f"[TelegramListener] 📥 Starting download: {url}")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Step 1: Parse video info
                parse_resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/downloader/parse",
                    json={"url": url}
                )

                if parse_resp.status_code != 200:
                    error_detail = ""
                    try:
                        error_detail = parse_resp.json().get("detail", parse_resp.text[:200])
                    except Exception:
                        error_detail = parse_resp.text[:200]
                    return f"❌ Không thể phân tích video: {error_detail}"

                parse_data = parse_resp.json()
                video_info = parse_data.get("data", {})
                title = video_info.get("title", "video")[:50]
                author = video_info.get("author", "unknown")
                platform = video_info.get("platform", "")
                duration = video_info.get("duration", 0)
                
                print(f"[TelegramListener] ✅ Parsed: {author} - {title}")

        except httpx.ConnectError:
            return (
                "❌ Không thể kết nối tới TubeCLI server. "
                "Hãy đảm bảo server đang chạy tại localhost:5295."
            )
        except Exception as e:
            return f"❌ Lỗi khi phân tích video: {str(e)[:200]}"

        # Step 2: Download the video
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                dl_resp = await client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/downloader/download",
                    json={"url": url}
                )

                if dl_resp.status_code != 200:
                    try:
                        err = dl_resp.json().get("detail", dl_resp.text[:200])
                    except Exception:
                        err = dl_resp.text[:200]
                    return f"❌ Lỗi tải video: {err}"

                dl_data = dl_resp.json()
                task_id = dl_data.get("task_id", "")
                filename = dl_data.get("filename", "video.mp4")
                save_path = dl_data.get("save_path", "")

        except Exception as e:
            return f"❌ Lỗi khi bắt đầu tải: {str(e)[:200]}"

        # Step 3: Wait for download to complete
        print(f"[TelegramListener] ⏳ Waiting for download task: {task_id}")
        file_path = await self._wait_for_download(task_id, filename)

        caption = (
            f"✅ *{title}*\n"
            f"👤 {author}{'  |  ⏱️ ' + str(duration) + 's' if duration else ''}\n"
            f"🌐 {platform.upper() if platform else 'Video'}\n"
            f"📁 `{filename}`"
        )

        return {
            "type": "file",
            "file_path": file_path,
            "filename": filename,
            "caption": caption,
            "file_type": "video",
            "download_url": f"{TUBECLI_BASE_URL}/api/v1/downloader/file/{filename}"
        }

    async def _wait_for_download(self, task_id: str, filename: str, max_wait: int = 120) -> str:
        """Poll download status until complete. Returns local file path."""
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        
        for _ in range(max_wait // 3):
            await asyncio.sleep(3)
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{TUBECLI_BASE_URL}/api/v1/downloader/status/{task_id}"
                    )
                    if resp.status_code == 200:
                        task_data = resp.json().get("data", {})
                        status = task_data.get("status", "")
                        progress = task_data.get("progress", 0)
                        print(f"[TelegramListener] Download progress: {progress:.1f}% ({status})")

                        if status in ("completed", "done"):
                            save_path = task_data.get("save_path", "")
                            if save_path and os.path.exists(save_path):
                                return save_path
                            # Try local path
                            local_path = os.path.join(data_dir, "downloads", filename)
                            if os.path.exists(local_path):
                                return local_path
                            return ""
                        elif status in ("error", "failed"):
                            return ""
            except Exception:
                pass

        # Timeout: try to find file anyway
        local_path = os.path.join(data_dir, "downloads", filename)
        return local_path if os.path.exists(local_path) else ""

    async def _exec_create_team(self, action_data: Dict) -> str:
        """Execute create_team action via the multi-agents extension."""
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
                        f"🆔 Team ID: `{team.get('id', 'N/A')}`\n\n"
                        f"Mở Dashboard → Teams để xem và tùy chỉnh."
                    )
                else:
                    return f"❌ Tạo team thất bại: {resp.text[:200]}"
        except Exception as e:
            return f"❌ Lỗi tạo team: {e}"

    async def _exec_run_api(self, action_data: Dict) -> str:
        """Execute a direct internal API call."""
        method = action_data.get("method", "GET").upper()
        endpoint = action_data.get("endpoint", "")
        body = action_data.get("body", {})

        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        url = f"{TUBECLI_BASE_URL}{endpoint}"
        print(f"[TelegramListener] run_api: {method} {url}")

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
                    # Format response nicely
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

    async def _sync_loop(self):
        """Periodically syncs polling tasks with configured tokens."""
        while self.running:
            configured_tokens = self.get_configured_tokens()

            # Start new ones
            for token, ctx in configured_tokens.items():
                if token not in self.polling_tasks:
                    self.polling_tasks[token] = asyncio.create_task(
                        self._poll_for_token(token, ctx)
                    )

            # Stop removed ones
            to_stop = [t for t in self.polling_tasks if t not in configured_tokens]
            for token in to_stop:
                self.polling_tasks[token].cancel()
                del self.polling_tasks[token]
                print(f"[TelegramListener] Stopped polling for removed token")

            await asyncio.sleep(10)

    def start(self):
        if self.running:
            return
        self.running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        print("🤖 [TelegramListener] Background service started (Autonomous Mode)")

    async def stop(self):
        self.running = False
        if self._sync_task:
            self._sync_task.cancel()
        for tk, task in self.polling_tasks.items():
            task.cancel()
        self.polling_tasks.clear()
        await self.client.aclose()
        print("🤖 [TelegramListener] Background service stopped")


telegram_listener = TelegramListener()
