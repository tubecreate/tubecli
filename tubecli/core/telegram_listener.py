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
        """Process message and send reply (handles file sending too).
        Shows 'thinking...' message while processing, then replaces with actual result."""
        typing_task = None
        thinking_msg_id = None
        try:
            # Start typing indicator loop
            typing_task = asyncio.create_task(
                self._typing_loop(token, chat_id)
            )

            # Send "thinking..." message
            thinking_msg_id = await self._send_thinking_message(token, chat_id)

            # Enrich context with telegram info for extension handlers
            context["token"] = token
            context["chat_id"] = chat_id

            result = await self._process_message(text, context)

            # Cancel typing indicator
            typing_task.cancel()

            # Delete "thinking..." message
            if thinking_msg_id:
                await self._delete_message(token, chat_id, thinking_msg_id)

            if isinstance(result, dict) and result.get("type") == "file":
                await self._send_file(token, chat_id, result)
            else:
                reply_text = result if isinstance(result, str) else str(result)
                # Clean any JSON wrapper from the reply
                reply_text = self._clean_reply_text(reply_text)
                if reply_text:
                    await self._send_message(token, chat_id, reply_text)
                else:
                    print(f"[TelegramListener] ⚠️ Empty reply after clean! Original result type={type(result).__name__}, len={len(str(result))}")
                    # Send fallback if result was not empty but got cleaned to nothing
                    if result and str(result).strip():
                        await self._send_message(token, chat_id, str(result)[:4000])
        except Exception as e:
            if typing_task:
                typing_task.cancel()
            # Delete "thinking..." message on error too
            if thinking_msg_id:
                await self._delete_message(token, chat_id, thinking_msg_id)
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

    async def _send_thinking_message(self, token: str, chat_id: int) -> Optional[int]:
        """Send a 'thinking...' message and return its message_id for later deletion."""
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            resp = await self.client.post(send_url, json={
                "chat_id": chat_id,
                "text": "🤔 Đang suy nghĩ..."
            })
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data["result"]["message_id"]
        except Exception:
            pass
        return None

    async def _delete_message(self, token: str, chat_id: int, message_id: int):
        """Delete a message by its ID."""
        delete_url = f"https://api.telegram.org/bot{token}/deleteMessage"
        try:
            await self.client.post(delete_url, json={
                "chat_id": chat_id,
                "message_id": message_id
            })
        except Exception:
            pass

    def _clean_reply_text(self, text: str) -> str:
        """Clean JSON wrappers from reply text to ensure human-readable output."""
        if not text:
            return text
        
        import json as _json
        
        # Helper: extract answer from a parsed JSON dict
        def _extract_answer(data):
            if not isinstance(data, dict):
                return None
            # Direct answer keys
            for key in ("finalAnswer", "final_answer", "answer", "reply"):
                if key in data and data[key]:
                    return str(data[key])
            # Message field
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
                        r = file_service.delete(path)
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
                        r = file_service.move(path, data.get("destination", ""))
                        return f"✅ Đã di chuyển: {path}"
                    elif op == "copy":
                        r = file_service.copy(path, data.get("destination", ""))
                        return f"✅ Đã sao chép: {path}"
                except Exception as e:
                    return f"❌ Lỗi: {str(e)}"
            # Nested in params
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
                data = _json.loads(stripped)
                answer = _extract_answer(data)
                if answer:
                    return answer
            except Exception:
                pass
        
        # 2. Try extracting from ```json ... ``` code blocks (greedy match for nested {})
        try:
            code_match = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
            if code_match:
                data = _json.loads(code_match.group(1))
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
                    data = _json.loads(stripped[start_idx:end_idx])
                    answer = _extract_answer(data)
                    if answer:
                        return answer
                except Exception:
                    pass
        
        return text

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
        
        # Truncate if too long for Telegram (4096 char limit)
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (đã cắt bớt)"
        
        try:
            resp = await self.client.post(send_url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            })
            if resp.status_code == 200 and resp.json().get("ok"):
                return
            print(f"[TelegramListener] Markdown send failed: {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            print(f"[TelegramListener] Markdown send exception: {e}")
        
        # Retry without markdown if fails
        try:
            resp2 = await self.client.post(send_url, json={
                "chat_id": chat_id,
                "text": text
            })
            if resp2.status_code != 200 or not resp2.json().get("ok"):
                print(f"[TelegramListener] Plain send also failed: {resp2.status_code} - {resp2.text[:200]}")
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

**Lập lịch / Tạo sự kiện Google Calendar:**
```json
{"action": "schedule_event", "summary": "<Tên sự kiện>", "start": "<ISO datetime>", "end": "<ISO datetime>", "description": "<Mô tả>", "recurrence": "RRULE:FREQ=DAILY"}
```
- Dùng khi user muốn lập lịch, tạo lịch hẹn, đặt lịch livestream
- recurrence là tùy chọn: RRULE:FREQ=DAILY (hằng ngày), RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR (hằng tuần), RRULE:FREQ=MONTHLY (hằng tháng)
- Nếu user nói "hằng ngày" / "mỗi ngày" → thêm recurrence RRULE:FREQ=DAILY
- Nếu user không nói giờ cụ thể, dùng giờ hợp lý (VD: livestream 20:00, meeting 09:00)
- Timezone mặc định: Asia/Ho_Chi_Minh (+07:00)

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

### QUY TẮC NHẬN DIỆN LẬP LỊCH:
- User nói "lập lịch", "đặt lịch", "schedule", "tạo sự kiện", "nhắc nhở", "lên lịch livestream" → schedule_event
- User nói "hằng ngày", "mỗi ngày", "daily" → thêm recurrence RRULE:FREQ=DAILY
- User nói "hằng tuần", "mỗi tuần", "weekly" → thêm recurrence RRULE:FREQ=WEEKLY

### KHẢ NĂNG HỆ THỐNG (để biết khi tư vấn):
- 🤖 Multi-Agent Teams, 🎬 3D Studio, 📥 Video Downloader (TikTok/Douyin)
- 🌐 Browser Automation (headless), ⚡ Workflow Builder, 🛒 Market
- 📅 Google Calendar (lập lịch, recurring events, nhắc nhở Telegram)
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
        from tubecli.core.brain import AgentBrain
        import re

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
            text_lower = text.lower()
            upload_keywords = ["upload", "đăng", "lên kênh", "đăng mmo"]
            has_upload = any(k in text_lower for k in upload_keywords)
            
            if has_upload:
                print(f"[TelegramListener] 🎯 Fast-path: Sequenced Match (Download -> Upload)")
                await self._send_message(context.get("token", ""), context.get("chat_id", 0), "⏳ Đã nhận diện yêu cầu Tải + Upload. Đang tiến hành...")
                
                # 1. Tải Video
                dl_result = await self._execute_download(video_url, agent_dict)
                
                if isinstance(dl_result, dict) and dl_result.get("file_path"):
                    # Gửi file cho user xem trước nếu được
                    try:
                        await self._send_file(context.get("token", ""), context.get("chat_id", 0), dl_result)
                    except Exception as e:
                         print(f"Lỗi gửi file (FastPath): {e}")

                    video_path = dl_result["file_path"]
                    duration = dl_result.get("duration", 0)
                    original_title = dl_result.get("original_title", "Video Mới")
                    original_author = dl_result.get("original_author", "Unknown")
                    import json as _json
                    
                    # 2. Tối ưu tiêu đề bằng AI trước khi Upload
                    await self._send_message(context.get("token", ""), context.get("chat_id", 0), "✨ Đang nhờ AI để tối ưu Tiêu đề & Hashtag chuẩn SEO...")
                    prompt = f"""Bạn là chuyên gia viết tiêu đề YouTube Shorts viral.
Video gốc: "{original_title}" (Tác giả: {original_author}).
Yêu cầu của người dùng: "{text}"

Nhiệm vụ:
1. Nếu trong yêu cầu của người dùng CÓ RÕ RÀNG chỉ định tiêu đề (VD: 'với tiêu đề là XYZ'), BẮT BUỘC dùng nội dung XYZ đó.
2. Nếu không, hãy sáng tạo một tiêu đề siêu thu hút dựa trên video gốc, thêm vài Emoji, và nối thêm 3-5 Hashtag thịnh hành (ưu tiên #Shorts nếu < 60s).
3. TRẢ VỀ DUY NHẤT VÀ TRỰC TIẾP DÒNG TIÊU ĐỀ KÈM HASHTAG ĐÓ. Không giải thích, không ngoặc kép, không có chữ 'Tiêu đề:'.
"""                 
                    ai_title = original_title
                    try:
                        from tubecli.core.brain import AgentBrain
                        ai_resp = AgentBrain._call_llm(agent_dict, [{"role": "user", "content": prompt}], temperature=0.7)
                        if ai_resp and "[Error]" not in ai_resp:
                            ai_title = ai_resp.strip().strip('"').strip("'")
                    except Exception as e:
                        print(f"[TelegramListener] Lỗi LLM tạo Title: {e}")

                    # 3. Tự động mồi lệnh Upload cho Extension (Không cần qua AI phân tích hành động nữa)
                    print(f"[TelegramListener] 🎯 Fast-path: Proceeding to Upload {video_path} (Duration: {duration}) - Title: {ai_title}")
                    fake_ai_action = {
                        "action": "upload_video",
                        "file_path": video_path,
                        "provider": "youtube",
                        "privacy": "public",  # Mặc định public như yêu cầu
                        "title": ai_title
                    }
                    reply_payload = "```json\n" + _json.dumps(fake_ai_action) + "\n```"
                    
                    upload_result = await self._handle_extension_action(reply_payload, agent_dict, context)
                    
                    # Logic kiểm tra trạng thái Upload dựa theo độ dài Video
                    
                    duration_sec = 0
                    if isinstance(duration, int):
                        duration_sec = duration
                    elif isinstance(duration, str):
                        try:
                            parts = duration.split(":")
                            if len(parts) == 3:
                                duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            elif len(parts) == 2:
                                duration_sec = int(parts[0]) * 60 + int(parts[1])
                            else:
                                duration_sec = float(parts[0].replace('s', ''))
                        except Exception:
                            duration_sec = 0
                            
                    import re
                    task_id_match = re.search(r'Task ID:\s*`([^`]+)`', upload_result)
                    
                    if task_id_match:
                        task_id = task_id_match.group(1)
                        if duration_sec > 0 and duration_sec < 60:
                            # Video ngắn: block và chờ kết quả để báo cáo liền
                            await self._send_message(context.get("token", ""), context.get("chat_id", 0), "⏳ Video ngắn (<60s). Đang chờ YouTube xử lý để lấy link...")
                            final_link = None
                            for _ in range(30): # Chờ tối đa 5 phút
                                await asyncio.sleep(10)
                                st_payload = "```json\n" + _json.dumps({"action": "video_status", "task_id": task_id}) + "\n```"
                                st_result = await self._handle_extension_action(st_payload, agent_dict, context)
                                if "✅" in st_result and "done" in st_result.lower():
                                     final_link = st_result
                                     break
                                elif "❌" in st_result or "error" in st_result.lower() or "lỗi" in st_result.lower():
                                     final_link = st_result
                                     break
                            
                            if final_link:
                                return f"🎉 **Đăng YouTube thành công!**\n\n{final_link}"
                            else:
                                return upload_result + "\n\n⚠️ Đợi quá lâu, hệ thống sẽ chạy ngầm tiếp."
                        else:
                            # Video dài (>60s): Không block, setup background task để báo cáo sau
                            async def _background_poll():
                                await asyncio.sleep(60) # Khởi động sau 1 phút
                                for _ in range(60): # Kiểm tra tối đa 10 phút (mỗi 10s)
                                    st_payload = "```json\n" + _json.dumps({"action": "video_status", "task_id": task_id}) + "\n```"
                                    st_result = await self._handle_extension_action(st_payload, agent_dict, context)
                                    if "✅" in st_result and "done" in st_result.lower():
                                        await self._send_message(context.get("token", ""), context.get("chat_id", 0), f"🎉 **Thông báo Background**: Video dài của bạn đã được duyệt lên YouTube!\n\n{st_result}")
                                        break
                                    elif "❌" in st_result or "error" in st_result.lower() or "lỗi" in st_result.lower():
                                        await self._send_message(context.get("token", ""), context.get("chat_id", 0), f"⚠️ **Thông báo Background**: Lỗi upload YouTube!\n\n{st_result}")
                                        break
                                    await asyncio.sleep(10)
                            
                            asyncio.create_task(_background_poll())
                            return upload_result + "\n\n*(Video dài, đã lên lịch theo dõi. Bot sẽ ping bạn khi YouTube duyệt xong!)*"

                    return upload_result
                else:
                    return dl_result # Trả về lỗi tải
            else:
                print(f"[TelegramListener] 🎯 Fast-path: detected video URL: {video_url}")
                dl_result = await self._execute_download(video_url, agent_dict)
                
                # Check if the user's message has additional instructions beyond the URL
                # Strip URL and common share text noise to see if there's real intent
                stripped = text
                stripped = re.sub(r'https?://\S+', '', stripped)
                # Remove common Douyin/TikTok share noise
                stripped = re.sub(r'\d+\.\d+\s*复制打开抖音.*?(?=\s*$|\s*tải|\s*download|\s*giúp)', '', stripped, flags=re.IGNORECASE|re.DOTALL)
                stripped = re.sub(r'[#@]\S+', '', stripped)  # Remove hashtags/mentions
                stripped = re.sub(r'pdn:/\s*\S+', '', stripped)  # Remove pdn:/ tokens
                stripped = stripped.strip()
                
                has_extra_intent = len(stripped) > 5  # More than just noise
                
                if has_extra_intent and isinstance(dl_result, dict) and dl_result.get("file_path"):
                    # User has additional instructions → download first, then let AI handle
                    print(f"[TelegramListener] 🧠 Extra intent detected: '{stripped}' → delegating to AI Brain")
                    try:
                        await self._send_file(context.get("token", ""), context.get("chat_id", 0), dl_result)
                    except Exception as e:
                        print(f"Lỗi gửi file: {e}")
                    
                    # Enrich the message with download context for the AI
                    file_path = dl_result["file_path"]
                    enriched_text = (
                        f"{text}\n\n"
                        f"[Hệ thống đã tải video thành công. File path: {file_path}]\n"
                        f"Hãy phân tích yêu cầu còn lại của người dùng và thực hiện hành động phù hợp. "
                        f"Nếu không rõ ý định, hãy HỎI LẠI người dùng để làm rõ."
                    )
                    # Fall through to AI Brain processing below (don't return)
                    text = enriched_text
                else:
                    # Bare URL or download failed → just return the download result
                    return dl_result

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
                            timeout=90
                        )
                        skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())
                    except asyncio.TimeoutError:
                        reply = f"⏰ Skill '{skill.name}' chạy quá lâu (>90s). Hệ thống đang tiếp tục xử lý."
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

        elif action == "schedule_event":
            action_data = brain_result.get("action_data", {})
            reply = await self._exec_schedule_event(action_data)

        # Handle Extension Actions from AI response text (fallback for inline JSON)
        result = await self._handle_extension_action(reply, agent_dict, context)

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
            r'https?://(?:www\.)?tiktok\.com/@[^/]+/video/\S+',
            r'https?://vm\.tiktok\.com/\S+',
            r'https?://(?:www\.)?iesdouyin\.com/share/video/\S+',
            r'https?://(?:www\.)?iesdouyin\.com/share/note/\S+',
            r'https?://(?:www\.)?iesdouyin\.com/share/slides/\S+',
            r'https?://v\.douyin\.com/\S+',
        ]
        for pattern in video_patterns:
            m = re.search(pattern, text)
            if m:
                url = m.group(0).rstrip('.,;?!')
                # Do not intercept user profile URLs as single video fast-path
                if "/user/" in url:
                    continue
                return url
        return None

    async def _handle_extension_action(self, reply: str, agent_dict: Dict, context: Dict = None):
        """Parse AI reply for JSON action blocks and execute extension logic.
        Dynamically discovers handlers from installed extensions.
        Returns str or dict (for file sending).
        """
        if not isinstance(reply, str):
            return reply

        # Try to extract JSON action from the reply
        action_data = self._extract_json_action(reply)
        if not action_data:
            return reply

        action_type = action_data.get("action", "")
        # ── Core built-in actions (always available) ──
        if action_type == "download_video":
            url = action_data.get("url", "")
            if not url:
                return "❌ Thiếu URL video."
            return await self._execute_download(url, agent_dict)

        elif action_type == "create_team":
            return await self._exec_create_team(action_data)

        elif action_type == "run_api":
            return await self._exec_run_api(action_data)

        elif action_type == "schedule_event":
            return await self._exec_schedule_event(action_data)

        # ── Dynamic extension actions (from installed extensions) ──
        try:
            from tubecli.core.extension_manager import extension_manager
            ext_actions = extension_manager.get_all_telegram_actions()
            
            if action_type in ext_actions:
                handler_info = ext_actions[action_type]
                handler_fn = handler_info["handler"]
                ext_name = handler_info["extension"]
                # Pass telegram context (token, chat_id) to extension handlers
                ext_context = {"agent": agent_dict}
                if context:
                    ext_context["token"] = context.get("token", "")
                    ext_context["chat_id"] = context.get("chat_id")
                result = await handler_fn(action_data, ext_context)
                return result
        except Exception as e:
            print(f"[TelegramListener] Extension action error: {e}")
            import traceback
            traceback.print_exc()

        # Unknown action — return original reply
        return reply

    def _extract_json_action(self, text: str) -> Optional[Dict]:
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
            # Try next occurrence
            start_idx = text.find("{", start_idx + 1)

        return None

    async def _exec_schedule_event(self, action_data: Dict) -> str:
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

        print(f"[TelegramListener] 📅 Creating calendar event: {summary}")

        try:
            from tubecli.extensions.calendar_manager.extension import calendar_manager

            # Read default calendar email from global settings
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
                email=email,
                summary=summary,
                start=start,
                end=end,
                description=description,
                location=location,
                recurrence=recurrence,
            )

            if result.get("status") == "success":
                msg = f"✅ **Đã lập lịch thành công!**\n\n"
                msg += f"📅 **{result.get('summary', summary)}**\n"
                msg += f"🕐 {result.get('start', start)}\n"
                if result.get("recurrence"):
                    recurrence_display = result["recurrence"][0] if result["recurrence"] else ""
                    if "DAILY" in recurrence_display:
                        msg += "🔄 Lặp lại: Hằng ngày\n"
                    elif "WEEKLY" in recurrence_display:
                        msg += "🔄 Lặp lại: Hằng tuần\n"
                    elif "MONTHLY" in recurrence_display:
                        msg += "🔄 Lặp lại: Hằng tháng\n"
                    else:
                        msg += f"🔄 Lặp lại: {recurrence_display}\n"
                if result.get("html_link"):
                    msg += f"🔗 [Mở trong Calendar]({result['html_link']})"
                return msg
            else:
                return f"❌ Lỗi tạo sự kiện: {result.get('message', 'Unknown error')}"

        except ImportError:
            return "❌ Calendar Manager extension chưa được cài đặt hoặc chưa bật."
        except Exception as e:
            return f"❌ Lỗi lập lịch: {str(e)[:300]}"

    async def _execute_download(self, url: str, agent_dict: Dict) -> dict:
        """Execute video download via Downloader extension API and return file info."""
        print(f"[TelegramListener] 📥 Starting download: {url}")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Step 1: Parse video info
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
                    f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/download",
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
            "duration": duration,
            "original_title": title,
            "original_author": author,
            "download_url": f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/file/{filename}"
        }

    async def _wait_for_download(self, task_id: str, filename: str, max_wait: int = 120) -> str:
        """Poll download status until complete. Returns local file path."""
        data_dir = os.environ.get("TUBECLI_DATA_DIR", "data")
        
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
