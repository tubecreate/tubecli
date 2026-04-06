"""
Telegram Listener — Refactored with 2-Tier Intent Routing.
Tier 1: IntentRouter (zero-token keyword/regex classification)
Tier 2: Smart dispatch with SkillSelector (minimal token LLM calls)

Architecture inspired by claw-code-main/src/runtime.py PortRuntime pattern.
"""
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
from tubecli.core.intent_router import intent_router, IntentResult
from tubecli.core.skill_selector import skill_selector
from tubecli.core.telegram_actions import (
    execute_download, execute_upload_sequence,
    handle_extension_action, clean_reply_text,
    exec_schedule_event, exec_create_team, exec_run_api,
)
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

    # ═══════════════════════════════════════════════════════════════
    #  TOKEN MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

    def get_configured_tokens(self) -> Dict[str, Dict[str, Any]]:
        """Finds all configured tokens and associated context."""
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

    # ═══════════════════════════════════════════════════════════════
    #  POLLING
    # ═══════════════════════════════════════════════════════════════

    async def _poll_for_token(self, token: str, context: Dict[str, Any]):
        """Long-polling loop for a specific telegram bot token."""
        bot_name = context.get('agent_name', 'Global')
        print(f"[TelegramListener] Starting polling for {bot_name} Bot...")

        try:
            del_resp = await self.client.get(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                params={"drop_pending_updates": "false"}, timeout=10
            )
            if del_resp.json().get("ok"):
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

                    asyncio.create_task(
                        self._process_and_reply(token, chat_id, text, context)
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TelegramListener] Polling error for {bot_name}: {e}")
                await asyncio.sleep(5)

    # ═══════════════════════════════════════════════════════════════
    #  MESSAGE PROCESSING (2-Tier Routing)
    # ═══════════════════════════════════════════════════════════════

    async def _process_and_reply(self, token: str, chat_id: int, text: str, context: Dict[str, Any]):
        """Process message and send reply with typing indicator."""
        typing_task = None
        thinking_msg_id = None
        try:
            typing_task = asyncio.create_task(self._typing_loop(token, chat_id))
            thinking_msg_id = await self._send_thinking_message(token, chat_id)

            context["token"] = token
            context["chat_id"] = chat_id

            result = await self._process_message(text, context)

            typing_task.cancel()

            # Update thinking message → show which agent handled it
            agent_badge = context.get("_agent_badge", "")
            if thinking_msg_id and agent_badge:
                await self._edit_message(token, chat_id, thinking_msg_id, agent_badge)
                await asyncio.sleep(0.8)  # Brief pause so user sees the badge
                await self._delete_message(token, chat_id, thinking_msg_id)
            elif thinking_msg_id:
                await self._delete_message(token, chat_id, thinking_msg_id)

            if isinstance(result, dict) and result.get("type") == "file":
                await self._send_file(token, chat_id, result)
            else:
                reply_text = result if isinstance(result, str) else str(result)
                reply_text = clean_reply_text(reply_text)
                if reply_text:
                    await self._send_message(token, chat_id, reply_text)
                elif result and str(result).strip():
                    await self._send_message(token, chat_id, str(result)[:4000])
        except Exception as e:
            if typing_task:
                typing_task.cancel()
            if thinking_msg_id:
                await self._delete_message(token, chat_id, thinking_msg_id)
            full_error = traceback.format_exc()
            print(f"[TelegramListener] ❌ Reply error: {e}\n{full_error}")
            await self._send_message(
                token, chat_id,
                f"⚠️ Lỗi xử lý: `{type(e).__name__}: {str(e)[:300]}`"
            )

    async def _process_message(self, text: str, context: Dict[str, Any]):
        """
        ★ CORE: 2-Tier Intent Routing ★
        
        Tier 1 (IntentRouter): Classify intent with 0 tokens
        Tier 2 (Smart Dispatch): Call LLM with only relevant skills
        """
        from tubecli.core.skill import skill_manager

        # ── Resolve Agent ──
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
        self._enrich_agent_config(agent_dict)

        # ── Get all skills ──
        all_skills = skill_manager.get_all()
        if agent.allowed_skills:
            available_skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
        else:
            available_skills = [s.to_dict() for s in all_skills]

        history = agent.history_log or []

        # ═══════════════════════════════════════════════════════════
        #  TIER 1: Intent Classification (0 tokens)
        # ═══════════════════════════════════════════════════════════
        intent = intent_router.classify(text, agent_dict, available_skills)
        print(f"[Router] Intent: {intent.intent_type} (confidence: {intent.confidence:.2f})")

        # ── Fast-path: Video Download (0 tokens) ──
        if intent.intent_type == "video_download":
            context["_agent_badge"] = "🎬 Video Agent đang tải video..."
            url = intent.extracted_data.get("url", "")
            result = await execute_download(url, agent_dict)
            self._save_history(agent_id, agent_dict, text, result, history)
            return result

        # ── Fast-path: Video Upload Sequence ──
        if intent.intent_type == "video_upload":
            context["_agent_badge"] = "🎬 Video Agent đang xử lý upload..."
            url = intent.extracted_data.get("url", "")
            result = await execute_upload_sequence(
                url, text, agent_dict,
                self._send_message, self._send_file,
                lambda reply, ad, ctx: handle_extension_action(reply, ad, ctx),
                context,
            )
            self._save_history(agent_id, agent_dict, text, result, history)
            return result

        # ── Fast-path: Skill Command Match (0 tokens) ──
        if intent.intent_type == "skill_command":
            skill_data = intent.extracted_data.get("skill")
            if skill_data:
                skill_obj = skill_manager.get(skill_data["id"])
                if skill_obj:
                    try:
                        reply = await asyncio.wait_for(
                            AgentBrain.autonomous_run(message=text, agent=agent_dict, skill=skill_obj.to_dict()),
                            timeout=90
                        )
                        skill_manager.update(skill_data["id"], last_run=datetime.datetime.now().isoformat())
                        result = await handle_extension_action(reply, agent_dict, context)
                        self._save_history(agent_id, agent_dict, text, result, history, skill_used=skill_data.get("name"))
                        return result
                    except asyncio.TimeoutError:
                        return f"⏰ Skill '{skill_data.get('name')}' chạy quá lâu (>90s)."
                    except Exception as e:
                        return f"⚠️ Skill lỗi: {str(e)[:200]}"

        # ── Tracker / Live Action ──
        if intent.intent_type in ("tracker_action", "live_action"):
            action_type = "trigger_tracker" if intent.intent_type == "tracker_action" else "create_livestream"
            fake_json = "```json\n" + json.dumps({"action": action_type}) + "\n```"
            result = await handle_extension_action(fake_json, agent_dict, context)
            self._save_history(agent_id, agent_dict, text, result, history)
            return result

        # ── Team Create ──
        if intent.intent_type == "team_create":
            # Let LLM parse team name & template from message
            pass  # Falls through to Tier 2

        # ── Fast-path: Browser Management (0 tokens) ──
        if intent.intent_type == "browser_action":
            context["_agent_badge"] = "🌐 Browser Manager"
            result = await self._handle_browser_action(intent.extracted_data, text)
            self._save_history(agent_id, agent_dict, text, result, history)
            return result

        # ═══════════════════════════════════════════════════════════
        #  TIER 2: Smart Dispatch (minimal tokens)
        # ═══════════════════════════════════════════════════════════

        # ── Greeting / General Chat → quick_reply (~500 tokens) ──
        if intent.intent_type == "greeting":
            context["_agent_badge"] = "🤖 Orchestrator"
            reply = AgentBrain.quick_reply(text, agent_dict, history)
            self._save_history(agent_id, agent_dict, text, reply, history)
            return reply

        if intent.intent_type == "general_chat" and intent.confidence >= 0.5:
            context["_agent_badge"] = "🤖 Orchestrator"
            reply = AgentBrain.quick_reply(text, agent_dict, history)
            self._save_history(agent_id, agent_dict, text, reply, history)
            return reply

        # ── Team Delegation (Phase 2) ──
        if intent.intent_type == "team_delegate" and intent.target_agent_id:
            target_agent = agent_manager.get(intent.target_agent_id)
            if target_agent:
                context["_agent_badge"] = f"{target_agent.name} đang xử lý..."
                print(f"[Router] 🎯 Delegating to specialist: {target_agent.name}")
                target_dict = target_agent.to_dict()
                self._enrich_agent_config(target_dict)
                
                # Select skills for this specialist
                selected_skills = skill_selector.select_for_team(
                    text, target_agent.allowed_skills, available_skills, limit=3
                )
                
                brain_result = AgentBrain.chat_targeted(
                    message=text, agent=target_dict, skills=selected_skills,
                    history=target_agent.history_log or [], intent_hint=intent.intent_type,
                )
                
                # Prefix reply with agent badge
                result = await self._handle_brain_actions(brain_result, text, target_dict, selected_skills, context)
                if isinstance(result, str):
                    result = f"*[{target_agent.name}]*\n{result}"
                self._save_history(agent_id, agent_dict, text, result, history)
                return result

        # ── Calendar / Search / File / Complex → targeted skills (~3000 tokens) ──
        # Try to find matching specialist for this intent
        from tubecli.core.specialists import get_specialist_for_intent
        specialist = get_specialist_for_intent(intent.intent_type)
        active_agent_name = specialist.name if specialist else agent_dict.get("name", "AI")
        context["_agent_badge"] = f"{active_agent_name} đang xử lý..."

        selected_skills = skill_selector.select(
            text, intent.intent_type, available_skills,
            matched_skill_ids=intent.matched_skills, limit=3,
        )

        print(f"[Router] [{active_agent_name}] Selected {len(selected_skills)} skills: {[s.get('name', '?') for s in selected_skills]}")

        # Inject extension capabilities (only for complex actions)
        if intent.intent_type == "complex_action":
            ext_capabilities = self._build_extension_capabilities()
            original_prompt = agent_dict.get("system_prompt", "You are a helpful assistant.")
            agent_dict["system_prompt"] = f"{original_prompt}\n\n{ext_capabilities}"

        brain_result = AgentBrain.chat_targeted(
            message=text, agent=agent_dict, skills=selected_skills,
            history=history, intent_hint=intent.intent_type,
        )

        result = await self._handle_brain_actions(brain_result, text, agent_dict, selected_skills, context)
        self._save_history(agent_id, agent_dict, text, result, history)
        return result

    # ═══════════════════════════════════════════════════════════════
    #  BRAIN ACTION HANDLING
    # ═══════════════════════════════════════════════════════════════

    async def _handle_brain_actions(self, brain_result, text, agent_dict, skills, context):
        """Handle actions returned by AgentBrain (run_skill, download, etc.)."""
        from tubecli.core.skill import skill_manager

        reply = brain_result.get("reply", "...")
        action = brain_result.get("action")

        if action == "run_skill" and brain_result.get("skill_id"):
            skill_id = brain_result["skill_id"]
            skill = skill_manager.get(skill_id)
            if skill:
                skill_input = brain_result.get("skill_input", text)
                try:
                    skill_dict = skill.to_dict()
                    # Force headless on browser nodes
                    for n in skill_dict.get("workflow_data", {}).get("nodes", []):
                        if n.get("type") in ("browser_action", "browser_control", "puppeteer"):
                            n.setdefault("config", {})["headless"] = True
                    
                    reply = await asyncio.wait_for(
                        AgentBrain.autonomous_run(message=skill_input, agent=agent_dict, skill=skill_dict),
                        timeout=90
                    )
                    skill_manager.update(skill_id, last_run=datetime.datetime.now().isoformat())
                except asyncio.TimeoutError:
                    reply = f"⏰ Skill '{skill.name}' chạy quá lâu (>90s)."
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
            except Exception as e:
                reply = f"[Create Skill Error] {e}"

        elif action == "download_video":
            url = brain_result.get("action_data", {}).get("url", "")
            if url:
                return await execute_download(url, agent_dict)
            reply = "❌ AI muốn tải video nhưng không tìm thấy URL."

        elif action == "create_team":
            return await exec_create_team(brain_result.get("action_data", {}))

        elif action == "run_api":
            return await exec_run_api(brain_result.get("action_data", {}))

        elif action == "schedule_event":
            return await exec_schedule_event(brain_result.get("action_data", {}))

        # Handle extension actions from AI response text
        result = await handle_extension_action(reply, agent_dict, context)
        return result

    # ═══════════════════════════════════════════════════════════════
    #  HELPER METHODS
    # ═══════════════════════════════════════════════════════════════

    def _enrich_agent_config(self, agent_dict: Dict):
        """Override model with global settings + inject cloud API keys."""
        cloud_cfg = self._get_cloud_model_config()
        if cloud_cfg.get("model") and (not agent_dict.get("model") or agent_dict["model"] == "qwen:latest"):
            agent_dict["model"] = cloud_cfg["model"]

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

    def _save_history(self, agent_id, agent_dict, text, result, history, skill_used=None):
        """Non-blocking save of conversation history + memory update."""
        reply_for_history = result if isinstance(result, str) else f"[File sent: {result.get('caption', '') if isinstance(result, dict) else ''}]"
        history.append({"role": "user", "content": text, "timestamp": datetime.datetime.now().isoformat()})
        history.append({
            "role": "assistant", "content": reply_for_history,
            "timestamp": datetime.datetime.now().isoformat(), "skill_used": skill_used
        })
        if len(history) > 50:
            history = history[-50:]

        async def _bg_mem():
            try:
                AgentBrain.post_chat_memory_update(agent_id, agent_dict, history)
                agent_manager.update(agent_id, history_log=history)
            except Exception as e:
                print(f"[TelegramListener] Memory err: {e}")
        asyncio.create_task(_bg_mem())
        agent_manager.update(agent_id, history_log=history)

    async def _handle_browser_action(self, data: dict, original_text: str) -> str:
        """Handle browser management actions (0 tokens — pure API call)."""
        sub_action = data.get("sub_action", "list")
        profile_name = data.get("profile_name")

        try:
            # If profile_name is purely digits, resolve from current list
            if profile_name and profile_name.isdigit() and sub_action in ["launch", "stop", "delete"]:
                idx = int(profile_name)
                resp = await self.client.get(f"{TUBECLI_BASE_URL}/api/v1/browser/profiles", timeout=10)
                if resp.status_code == 200:
                    profiles = resp.json().get("profiles", [])
                    if 1 <= idx <= len(profiles):
                        profile_name = profiles[idx-1]["name"]
                    else:
                        return f"❌ Số thứ tự {idx} không hợp lệ (chỉ có từ 1 đến {len(profiles)})."

            if sub_action == "list":
                resp = await self.client.get(f"{TUBECLI_BASE_URL}/api/v1/browser/profiles", timeout=10)
                if resp.status_code == 200:
                    profiles = resp.json().get("profiles", [])
                    if not profiles:
                        return "📂 Chưa có browser profile nào. Dùng lệnh 'tạo browser profile <tên>' để tạo mới."
                    lines = ["🌐 Danh sách Browser Profiles:\n"]
                    for i, p in enumerate(profiles, 1):
                        status = "🔒" if p.get("has_cookies") else "📂"
                        proxy = f" | Proxy: {p['proxy']}" if p.get("proxy") else ""
                        lines.append(f"{i}. {status} {p['name']}{proxy}")
                    lines.append(f"\n📊 Tổng: {len(profiles)} profiles")
                    lines.append("💡 Dùng: 'mở browser <tên>' để khởi chạy")
                    return "\n".join(lines)
                return f"❌ Lỗi lấy danh sách profiles: HTTP {resp.status_code}"

            elif sub_action == "create":
                if not profile_name:
                    return "❌ Thiếu tên profile. VD: 'tạo browser profile myprofile'"
                resp = await self.client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/browser/profiles",
                    json={"name": profile_name},
                    timeout=15,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    return f"✅ Đã tạo browser profile: {result.get('profile', {}).get('name', profile_name)}\n💡 Dùng: 'mở browser {profile_name}' để khởi chạy"
                elif resp.status_code == 409:
                    return f"⚠️ Profile '{profile_name}' đã tồn tại."
                return f"❌ Lỗi tạo profile: {resp.text[:200]}"

            elif sub_action == "launch":
                if not profile_name:
                    return "❌ Thiếu tên profile cần mở. VD: 'mở browser testlive'"
                resp = await self.client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/browser/launch",
                    json={"profile": profile_name, "manual": True},
                    timeout=15,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("status") == "error":
                        return f"❌ Không mở được: {result.get('error', 'Unknown error')[:300]}"
                    return f"🚀 Đã mở browser profile {profile_name}\n🔑 Instance: {result.get('instance_id', 'N/A')}\n⚙️ PID: {result.get('pid', 'N/A')}"
                return f"❌ Lỗi mở browser: HTTP {resp.status_code}"

            elif sub_action == "stop":
                if not profile_name:
                    return "❌ Thiếu tên profile cần đóng. VD: 'đóng browser testlive'"
                resp = await self.client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/browser/stop",
                    json={"profile": profile_name},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return f"⏹ Đã đóng browser: {profile_name}"
                elif resp.status_code == 404:
                    return f"⚠️ Không tìm thấy browser đang chạy cho profile '{profile_name}'."
                return f"❌ Lỗi đóng browser: HTTP {resp.status_code}"

            elif sub_action == "delete":
                if not profile_name:
                    return "❌ Thiếu tên profile cần xóa. VD: 'xóa browser profile testlive'"
                resp = await self.client.delete(
                    f"{TUBECLI_BASE_URL}/api/v1/browser/profiles/{profile_name}",
                    timeout=10,
                )
                if resp.status_code == 200:
                    return f"🗑 Đã xóa browser profile: {profile_name}"
                elif resp.status_code == 404:
                    return f"⚠️ Profile '{profile_name}' không tồn tại."
                return f"❌ Lỗi xóa profile: HTTP {resp.status_code}"

            return f"❌ Hành động '{sub_action}' chưa được hỗ trợ."

        except Exception as e:
            return f"❌ Lỗi xử lý browser: {str(e)[:200]}"

    def _build_extension_capabilities(self) -> str:
        """Build system prompt for extension actions (only for complex intents)."""
        base_prompt = """### EXTENSION ACTIONS — OUTPUT JSON ĐỂ KÍCH HOẠT HỆ THỐNG:

**Tải video TikTok/Douyin:**
```json
{"action": "download_video", "url": "<URL_VIDEO>"}
```

**Tạo team AI:**
```json
{"action": "create_team", "template": "dev_team", "name": "<Tên team>"}
```

**Lập lịch Google Calendar:**
```json
{"action": "schedule_event", "summary": "<Tên>", "start": "<ISO datetime>", "end": "<ISO datetime>", "recurrence": "RRULE:FREQ=DAILY"}
```

**Gọi API nội bộ:**
```json
{"action": "run_api", "method": "POST", "endpoint": "/api/v1/...", "body": {...}}
```
"""
        # Auto-inject SKILL.md from enabled extensions (only for complex actions)
        try:
            from tubecli.core.extension_manager import extension_manager
            skill_mds = extension_manager.get_all_skill_mds()
            if skill_mds:
                skill_sections = "\n\n### EXTENSION SKILL DOCS:\n"
                for item in skill_mds:
                    skill_sections += f"\n---\n**{item['extension']}**\n{item['skill_md']}\n"
                return base_prompt + skill_sections
        except Exception:
            pass
        return base_prompt

    # ═══════════════════════════════════════════════════════════════
    #  TELEGRAM API METHODS
    # ═══════════════════════════════════════════════════════════════

    async def _send_thinking_message(self, token: str, chat_id: int) -> Optional[int]:
        """Send 'thinking...' message and return its message_id."""
        try:
            resp = await self.client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "🤔 Đang suy nghĩ..."}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data["result"]["message_id"]
        except Exception:
            pass
        return None

    async def _edit_message(self, token: str, chat_id: int, message_id: int, text: str):
        """Edit an existing message text."""
        try:
            await self.client.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": text}
            )
        except Exception:
            pass

    async def _delete_message(self, token: str, chat_id: int, message_id: int):
        """Delete a message by its ID."""
        try:
            await self.client.post(
                f"https://api.telegram.org/bot{token}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id}
            )
        except Exception:
            pass

    async def _typing_loop(self, token: str, chat_id: int):
        """Keep sending 'typing' action every 4s."""
        typing_url = f"https://api.telegram.org/bot{token}/sendChatAction"
        try:
            while True:
                try:
                    await self.client.post(typing_url, json={"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def _send_message(self, token: str, chat_id: int, text: str):
        """Send text message via Telegram."""
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (đã cắt bớt)"

        try:
            resp = await self.client.post(send_url, json={
                "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
            })
            if resp.status_code == 200 and resp.json().get("ok"):
                return
        except Exception:
            pass

        # Retry without markdown
        try:
            await self.client.post(send_url, json={"chat_id": chat_id, "text": text})
        except Exception as e:
            print(f"[TelegramListener] Send message error: {e}")

    async def _send_file(self, token: str, chat_id: int, file_info: Dict):
        """Send a file via Telegram."""
        file_path = file_info.get("file_path", "")
        caption = file_info.get("caption", "")
        file_type = file_info.get("file_type", "document")

        if not file_path or not os.path.exists(file_path):
            download_url = file_info.get("download_url", "")
            await self._send_message(token, chat_id,
                f"✅ {caption}\n\n📥 Download: {download_url}" if download_url else f"✅ {caption}"
            )
            return

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 50:
            await self._send_message(token, chat_id,
                f"⚠️ File quá lớn ({file_size_mb:.1f} MB > 50 MB).\n📁 Đã lưu tại: `{file_path}`"
            )
            return

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
                    f"✅ Video đã tải xong!\n📁 `{os.path.basename(file_path)}`\n⚠️ Không thể gửi file: {str(e)[:100]}"
                )

    # ═══════════════════════════════════════════════════════════════
    #  LIFECYCLE
    # ═══════════════════════════════════════════════════════════════

    async def _sync_loop(self):
        """Periodically syncs polling tasks with configured tokens."""
        while self.running:
            configured_tokens = self.get_configured_tokens()
            for token, ctx in configured_tokens.items():
                if token not in self.polling_tasks:
                    self.polling_tasks[token] = asyncio.create_task(
                        self._poll_for_token(token, ctx)
                    )
            to_stop = [t for t in self.polling_tasks if t not in configured_tokens]
            for token in to_stop:
                self.polling_tasks[token].cancel()
                del self.polling_tasks[token]
            await asyncio.sleep(10)

    def start(self):
        if self.running:
            return
        self.running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        print("🤖 [TelegramListener] Background service started (2-Tier Intent Routing)")

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
