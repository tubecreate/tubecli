"""
Telegram Listener — Refactored with 2-Tier Intent Routing.
Tier 1: IntentRouter (zero-token keyword/regex classification)
Tier 2: Smart dispatch with SkillSelector (minimal token LLM calls)

Architecture inspired by claw-code-main/src/runtime.py PortRuntime pattern.
"""
import asyncio
import httpx
import traceback
from tubecli.core.bot_i18n import t, get_user_lang
import datetime
import os
import json
import re
from typing import Dict, Any, Optional

from tubecli.core.agent import agent_manager
from tubecli.core.brain import AgentBrain
from tubecli.core.intent_router import intent_router, IntentResult
from tubecli.core.skill_selector import skill_selector
from tubecli.core import intent_handlers
from tubecli.core.telegram_actions import (
    execute_download, execute_upload_sequence, execute_reup_sequence,
    handle_extension_action, clean_reply_text,
    exec_schedule_event, exec_create_team, exec_run_api,
)
from tubecli.config import DATA_DIR, get_api_port

SETTINGS_FILE = DATA_DIR / "global_settings.json"
TUBECLI_BASE_URL = f"http://localhost:{get_api_port()}"


# ── Confirmation Keywords ──
# EXACT match only (see _matches_keyword) — ambiguous single words like
# "đi"/"được" were removed: with prefix-matching they made messages like
# "đi ngủ đây" silently confirm an upload plan.
CONFIRM_KEYWORDS = ["ok", "oke", "okê", "okay", "yes", "go", "confirm", "xác nhận", "đồng ý", "chạy", "chạy đi", "làm đi", "thực hiện", "bắt đầu", "ok đi"]
CANCEL_KEYWORDS = ["không", "hủy", "huỷ", "thôi", "cancel", "no", "bỏ", "dừng", "stop"]


def _matches_keyword(text_lower: str, keywords: list) -> bool:
    """Exact keyword match, tolerant of trailing punctuation ('ok!', 'hủy.')."""
    cleaned = re.sub(r'[!.…,~]+$', '', text_lower).strip()
    return cleaned in keywords
MODIFY_CHANNEL_PATTERN = r'(?:đổi|chuyển|chọn|switch)\s*(?:sang\s*)?(?:kênh|channel|page|trang)\s*(?:thứ\s*)?(\d+)'


class TelegramListener:
    def __init__(self):
        self.running = False
        self.polling_tasks: Dict[str, asyncio.Task] = {}
        self.offsets: Dict[str, int] = {}
        self._sync_task = None
        self.client = httpx.AsyncClient(timeout=40)
        # Pending action plans awaiting user confirmation (keyed by chat_id)
        self.pending_actions: Dict[int, Dict[str, Any]] = {}
        # Auto-execute timer tasks (keyed by chat_id)
        self._auto_execute_tasks: Dict[int, asyncio.Task] = {}
        # Per-chat conversation histories (keyed by "agent_id:chat_id") so
        # different Telegram users never share/mix conversation context
        self._chat_histories: Dict[str, list] = {}

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
                t("sys.error", error=f"{type(e).__name__}: {str(e)[:300]}")
            )

    async def _process_message(self, text: str, context: Dict[str, Any]):
        """
        ★ CORE: 2-Tier Intent Routing ★
        
        Tier 1 (IntentRouter): Classify intent with 0 tokens
        Tier 2 (Smart Dispatch): Call LLM with only relevant skills
        """
        from tubecli.core.skill import skill_manager
        
        chat_id = context.get("chat_id", 0)
        token = context.get("token", "")
        text_lower_check = text.strip().lower()

        # ── Resolve Agent ──
        agent_id = context.get("agent_id")
        if not agent_id:
            agents = agent_manager.get_all()
            if not agents:
                return t("sys.no_agents", get_user_lang(chat_id))
            main_agent = next(
                (a for a in agents if "tổng" in a.name.lower() or "orchestra" in a.name.lower()),
                agents[0]
            )
            agent_id = main_agent.id

        agent = agent_manager.get(agent_id)
        if not agent:
            return t("sys.no_agents", get_user_lang(chat_id))

        agent_dict = agent.to_dict()
        self._enrich_agent_config(agent_dict)

        # Nhóm Flow Builder: Telegram không biết node nào gửi tin, nên lấy HỢP
        # mọi nhóm chứa agent — khối GROUP WORKSPACE vào prompt, group_ids vào
        # context để handler gsheet_*/xlsx_* resolve alias + kiểm quyền.
        groups = self._inject_group_context(agent_dict, agent_id)
        context["group_ids"] = [g.get("group_id", "") for g in groups if g.get("group_id")]
        context["group_id"] = ""

        # ── Get all skills ──
        all_skills = skill_manager.get_all()
        if agent.allowed_skills:
            available_skills = [s.to_dict() for s in all_skills if s.id in agent.allowed_skills]
        else:
            available_skills = [s.to_dict() for s in all_skills]

        # Per-chat history: each Telegram chat gets its own conversation
        # context instead of all chats sharing agent.history_log
        history = self._get_chat_history(agent_id, chat_id)

        # ═══════════════════════════════════════════════════════════
        #  CHECK PENDING ACTION CONFIRMATION
        # ═══════════════════════════════════════════════════════════
        chat_id = context.get("chat_id", 0)
        token = context.get("token", "")
        pending = self.pending_actions.get(chat_id)
        
        if pending:
            text_lower_check = text.strip().lower()
            
            # Cancel any auto-execute timer since user responded
            self._cancel_auto_execute(chat_id)
            
            # ── User confirms → execute the pending plan ──
            if _matches_keyword(text_lower_check, CONFIRM_KEYWORDS):
                plan = self.pending_actions.pop(chat_id)
                result = await self._execute_plan(plan, agent_dict, context)
                self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                return result
            
            # ── User cancels ──
            if _matches_keyword(text_lower_check, CANCEL_KEYWORDS):
                self.pending_actions.pop(chat_id)
                return "🚫 Đã hủy kế hoạch. Bạn có thể gửi yêu cầu mới."
            
            # ── User modifies: "đổi kênh 3", "chọn trang 1", "đổi trang 2" ──
            modify_match = re.search(MODIFY_CHANNEL_PATTERN, text_lower_check)
            if modify_match:
                new_idx = int(modify_match.group(1))
                try:
                    from tubecli.core.channel_cache import channel_cache
                    
                    # Detect if user is switching provider via keyword
                    if re.search(r'(?:trang|page)', text_lower_check):
                        target_provider = "facebook"
                    elif re.search(r'(?:kênh|channel)', text_lower_check):
                        target_provider = pending.get("provider", "youtube")
                    else:
                        target_provider = pending.get("provider", "youtube")
                    
                    new_ch = channel_cache.get_by_index(target_provider, new_idx)
                    if new_ch:
                        pending["channel"] = new_ch
                        # Switch provider if needed
                        if target_provider != pending.get("provider"):
                            pending["provider"] = target_provider
                            new_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(target_provider, "YouTube")
                            old_label = pending.get("provider_label", "YouTube")
                            pending["provider_label"] = new_label
                            pending["steps"] = [
                                s.replace(old_label, new_label) if "Upload" in s else s
                                for s in pending.get("steps", [])
                            ]
                        plan_msg = self._format_plan(pending, chat_id)
                        return plan_msg
                    else:
                        channels = channel_cache.get_channels(target_provider)
                        entity = "trang" if target_provider == "facebook" else "kênh"
                        return f"❌ {entity.capitalize()} số {new_idx} không tồn tại. Chỉ có {len(channels)} {entity}. Gõ 'danh sách {entity}' để xem."
                except Exception as e:
                    entity = "trang" if pending.get('provider') == 'facebook' else "kênh"
                    return f"❌ Lỗi đổi {entity}: {str(e)[:200]}"
            
            # ── User sends "kênh 3" or "trang 2" directly (without "đổi") ──
            kenh_match = re.search(r'^(?:kênh|channel|trang|page)\s*(?:thứ\s*)?(\d+)$', text_lower_check)
            if kenh_match:
                new_idx = int(kenh_match.group(1))
                try:
                    from tubecli.core.channel_cache import channel_cache
                    
                    # "trang N" → Facebook, "kênh N" → keep current provider
                    if re.search(r'^(?:trang|page)', text_lower_check):
                        target_provider = "facebook"
                    else:
                        target_provider = pending.get("provider", "youtube")
                    
                    new_ch = channel_cache.get_by_index(target_provider, new_idx)
                    if new_ch:
                        pending["channel"] = new_ch
                        # Switch provider if needed
                        if target_provider != pending.get("provider"):
                            pending["provider"] = target_provider
                            new_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(target_provider, "YouTube")
                            old_label = pending.get("provider_label", "YouTube")
                            pending["provider_label"] = new_label
                            pending["steps"] = [
                                s.replace(old_label, new_label) if "Upload" in s else s
                                for s in pending.get("steps", [])
                            ]
                        plan_msg = self._format_plan(pending, chat_id)
                        return plan_msg
                    else:
                        channels = channel_cache.get_channels(target_provider)
                        entity = "trang" if target_provider == "facebook" else "kênh"
                        return f"❌ {entity.capitalize()} số {new_idx} không tồn tại. Chỉ có {len(channels)} {entity}."
                except Exception as e:
                    entity = "trang" if pending.get('provider') == 'facebook' else "kênh"
                    return f"❌ Lỗi chọn {entity}: {str(e)[:200]}"
            
            # ── Any other message while pending → cancel old plan & process new message ──
            # (User might be sending a completely different request)
            self.pending_actions.pop(chat_id)
        
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
            self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
            return result

        # ── Fast-path: video request without a link (0 tokens) ──
        if intent.intent_type == "video_request_no_url":
            from tubecli.core.bot_i18n import t as _bt

            result = _bt("vs.ask_url")
            self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
            return result

        # ── Plan & Confirm: Video Upload Sequence ──
        if intent.intent_type == "video_upload":
            provider = intent.extracted_data.get("provider", "youtube")
            provider_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(provider, "YouTube")
            url = intent.extracted_data.get("url", "")
            
            # Resolve channel for plan display
            resolved_channel = None
            try:
                from tubecli.core.channel_cache import channel_cache
                resolved_channel = channel_cache.resolve_channel(provider, text)
            except Exception:
                pass
            
            # Save pending plan
            user_lang = get_user_lang(chat_id)
            plan = {
                "type": "video_upload",
                "url": url,
                "provider": provider,
                "provider_label": provider_label,
                "channel": resolved_channel,
                "original_text": text,
                "badge": f"🎬 Video Agent đang upload lên {provider_label}...",
                "steps": [
                    t("plan.step_download", user_lang),
                    t("plan.step_ai_title", user_lang),
                    t("plan.step_upload", user_lang, provider=provider_label),
                ],
            }
            self.pending_actions[chat_id] = plan
            # Schedule auto-execute after 10 seconds
            self._schedule_auto_execute(chat_id, plan, agent_dict, context, agent_id, history)
            return self._format_plan(plan, chat_id)

        # ── Plan & Confirm: Re-up Pipeline ──
        if intent.intent_type == "reup_action":
            url = intent.extracted_data.get("url", "")
            provider = context.get("upload_provider", "youtube")
            provider_label = {"facebook": "Facebook", "tiktok": "TikTok"}.get(provider, "YouTube")
            
            # Parse effects from text for plan display
            text_lower = text.lower()
            effects = []
            if any(k in text_lower for k in ["gương", "mirror", "lật", "flip"]): effects.append("Lật gương")
            if any(k in text_lower for k in ["trắng đen", "grayscale"]): effects.append("Trắng đen")
            if any(k in text_lower for k in ["tốc độ 2", "speed 2", "2x"]): effects.append("Tốc độ 2x")
            if any(k in text_lower for k in ["blur", "mờ"]): effects.append("Blur")
            if any(k in text_lower for k in ["xóa phông", "tách nền"]): effects.append("Tách nền AI")
            # Only default to mirror if there are actual mirror keywords and no template-only request
            template_index = intent.extracted_data.get("template_index")
            if not effects and not template_index:
                effects.append("Lật gương (mặc định)")
            
            resolved_channel = None
            try:
                from tubecli.core.channel_cache import channel_cache
                resolved_channel = channel_cache.resolve_channel(provider, text)
            except Exception:
                pass
            
            # ── Resolve template by index ──
            template_id = None
            template_name = None
            if template_index:
                try:
                    resp = await self.client.get(f"{TUBECLI_BASE_URL}/api/v1/templates", timeout=5)
                    if resp.status_code == 200:
                        templates = resp.json().get("templates", [])
                        if 1 <= template_index <= len(templates):
                            tpl = templates[template_index - 1]
                            template_id = tpl.get("id")
                            template_name = tpl.get("name", f"Template {template_index}")
                except Exception as e:
                    print(f"[Reup] Template resolve error: {e}")
            
            user_lang = get_user_lang(chat_id)
            
            # Build steps list
            steps = [t("plan.step_download", user_lang)]
            if effects:
                steps.append(t("plan.step_ffmpeg", user_lang, effects=', '.join(effects)))
            if template_id:
                steps.append(t("plan.step_template", user_lang, name=template_name))
            steps.append(t("plan.step_ai_title", user_lang))
            steps.append(t("plan.step_upload", user_lang, provider=provider_label))
            
            plan = {
                "type": "reup_action",
                "url": url,
                "provider": provider,
                "provider_label": provider_label,
                "channel": resolved_channel,
                "original_text": text,
                "badge": "♻️ Re-up Agent đang xử lý pipeline...",
                "effects": effects,
                "template_id": template_id,
                "template_name": template_name,
                "steps": steps,
            }
            self.pending_actions[chat_id] = plan
            # Schedule auto-execute after 20 seconds
            self._schedule_auto_execute(chat_id, plan, agent_dict, context, agent_id, history)
            return self._format_plan(plan, chat_id)

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
                        self._save_history(agent_id, agent_dict, text, result, history, skill_used=skill_data.get("name"), chat_id=chat_id)
                        return result
                    except asyncio.TimeoutError:
                        return f"⏰ Skill '{skill_data.get('name')}' chạy quá lâu (>90s)."
                    except Exception as e:
                        return f"⚠️ Skill lỗi: {str(e)[:200]}"

        # ── Shared skip_llm handlers (registry chung 2 kênh) ──────────
        # read_page, channel_analyze... định nghĩa MỘT lần trong
        # core/intent_handlers.py; đây là nơi DUY NHẤT đọc skip_llm.
        if getattr(intent, "skip_llm", False) and intent_handlers.has_handler(intent.intent_type):
            hmeta = intent_handlers.meta_for(intent.intent_type)
            if hmeta.get("badge"):
                context["_agent_badge"] = hmeta["badge"]
            self._enrich_agent_config(agent_dict)
            handled = await intent_handlers.dispatch(intent, agent_dict, get_user_lang(chat_id))
            if handled is not None:
                result = await handle_extension_action(handled, agent_dict, context)
                self._save_history(agent_id, agent_dict, text, result, history,
                                   skill_used=hmeta.get("skill_used") or None, chat_id=chat_id)
                return result
            # handler tự bỏ → rơi xuống xử lý mặc định

        # ── Tracker / Live / List Action Bypass ──
        if intent.intent_type in ("tracker_action", "live_action", "list_channels_action", "list_templates_action"):
            if intent.intent_type == "tracker_action":
                action_type = "trigger_tracker"
                payload = {"action": action_type}
                fake_json = "```json\n" + json.dumps(payload) + "\n```"
                result = await handle_extension_action(fake_json, agent_dict, context)
                self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                return result

            elif intent.intent_type == "live_action":
                # ── Plan & Confirm: Livestream Pipeline ──
                context["_agent_badge"] = "🔴 Livestream Pipeline"
                source_url = intent.extracted_data.get("url", "")
                if not source_url:
                    import re as _re
                    url_match = _re.search(r'(https?://\S+|rtmp://\S+)', text)
                    source_url = url_match.group(0).rstrip('.,;?!') if url_match else ""

                if not source_url:
                    result = (
                        "🔴 **Livestream Pipeline**\n\n"
                        "❌ Thiếu link nguồn (source URL).\n"
                        "Vui lòng gửi kèm:\n"
                        "• Link Douyin live: `https://live.douyin.com/xxx`\n"
                        "• Link video: `https://v.douyin.com/xxx`\n"
                        "• Link m3u8/RTMP\n\n"
                        "Ví dụ: `tạo live stream https://v.douyin.com/xxx lên kênh 3`"
                    )
                    self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                    return result

                # ── Pre-validate source URL (inline) ──
                source_info = ""
                source_title = ""
                resolved_url = source_url
                is_live_ok = False

                is_live_link = any(k in source_url.lower() for k in ["douyin.com", "tiktok.com", "iesdouyin.com"])
                if is_live_link:
                    try:
                        resp = await self.client.post(
                            f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/parse",
                            json={"url": source_url}, timeout=20,
                        )
                        if resp.status_code == 200:
                            parse_data = resp.json().get("data", {})
                            content_type = parse_data.get("type", "")
                            source_title = parse_data.get("title", "") or parse_data.get("author", "")
                            author = parse_data.get("author", "Unknown")

                            if content_type == "live":
                                hls_url = parse_data.get("download_url", "")
                                if hls_url:
                                    resolved_url = hls_url
                                    is_live_ok = True
                                    source_info = f"✅ Phòng live đang hoạt động\n👤 {author}\n📺 {source_title}"
                                else:
                                    result = (
                                        "🔴 **Livestream Pipeline**\n\n"
                                        f"❌ **Phòng live đã offline**\n"
                                        f"👤 {author}\n🔗 {source_url}\n\n"
                                        "_Vui lòng kiểm tra lại link hoặc chờ phòng live mở lại._"
                                    )
                                    self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                                    return result
                            elif content_type == "video":
                                video_url = parse_data.get("download_url", "")
                                if video_url:
                                    resolved_url = video_url
                                    is_live_ok = True
                                    source_info = f"✅ Video (sẽ dùng file_loop)\n👤 {author}\n📺 {source_title}"
                                else:
                                    result = (
                                        "🔴 **Livestream Pipeline**\n\n"
                                        f"❌ **Không thể lấy link download**\n"
                                        f"🔗 {source_url}\n\n"
                                        "_Cookie Douyin có thể đã hết hạn._"
                                    )
                                    self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                                    return result
                            else:
                                is_live_ok = True
                                source_info = f"⚠️ Loại: {content_type} — sẽ thử stream"
                        elif resp.status_code in (400, 404):
                            try:
                                err = resp.json().get("detail", "")
                            except Exception:
                                err = resp.text[:200]
                            result = (
                                "🔴 **Livestream Pipeline**\n\n"
                                f"❌ **Link không hợp lệ**\n🔗 {source_url}\n📝 {err}"
                            )
                            self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                            return result
                    except Exception as e:
                        is_live_ok = True  # Skip validation, try anyway
                        source_info = f"⚠️ Không kiểm tra được link: {str(e)[:80]}"
                else:
                    is_live_ok = True
                    source_info = f"🔗 URL trực tiếp"

                # ── Resolve target channel ──
                resolved_channel = None
                try:
                    from tubecli.core.channel_cache import channel_cache
                    resolved_channel = channel_cache.resolve_channel("youtube", text)
                except Exception:
                    pass

                user_lang = get_user_lang(chat_id)
                plan = {
                    "type": "livestream_action",
                    "url": source_url,
                    "resolved_url": resolved_url,
                    "source_title": source_title,
                    "source_info": source_info,
                    "provider": "youtube",
                    "provider_label": "YouTube",
                    "channel": resolved_channel,
                    "original_text": text,
                    "badge": "🔴 Livestream Pipeline đang phát...",
                    "steps": [
                        "🔑 Resolve YouTube credentials",
                        "✨ AI SEO Title",
                        "🎬 Create Broadcast + Start FFmpeg",
                    ],
                }
                self.pending_actions[chat_id] = plan
                self._schedule_auto_execute(chat_id, plan, agent_dict, context, agent_id, history)
                return self._format_livestream_plan(plan, chat_id)

            elif intent.intent_type == "list_channels_action":
                payload = intent.extracted_data.get("action_data", {"action": "list_channels"})
                fake_json = "```json\n" + json.dumps(payload) + "\n```"
                result = await handle_extension_action(fake_json, agent_dict, context)
                self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                return result

            elif intent.intent_type == "list_templates_action":
                payload = intent.extracted_data.get("action_data", {"action": "list_templates"})
                fake_json = "```json\n" + json.dumps(payload) + "\n```"
                result = await handle_extension_action(fake_json, agent_dict, context)
                self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                return result

        # ── Team Create ──
        if intent.intent_type == "team_create":
            # Let LLM parse team name & template from message
            pass  # Falls through to Tier 2

        # ── Fast-path: Browser Management (0 tokens) ──
        if intent.intent_type == "browser_action":
            context["_agent_badge"] = "🌐 Browser Manager"
            result = await self._handle_browser_action(intent.extracted_data, text)
            self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
            return result

        # (read_page + channel_analyze giờ do registry chung ở trên xử lý)

        # ── Fast-path: Subtitle Pipeline (URL + subtitle + optional upload) ──
        if intent.intent_type == "subtitle_pipeline":
            context["_agent_badge"] = "📝 Subtitle Pipeline"
            result = await self._handle_subtitle_pipeline(intent.extracted_data, text, agent_dict, context)
            self._save_history(agent_id, agent_dict, text, result, history, skill_used="Subtitle Extractor", chat_id=chat_id)
            return result

        # ── Fast-path: Subtitle Extraction ──
        if intent.intent_type == "subtitle_action":
            context["_agent_badge"] = "📝 Subtitle Extractor"
            result = await self._handle_subtitle_action(text, agent_dict, context)
            self._save_history(agent_id, agent_dict, text, result, history, skill_used="Subtitle Extractor", chat_id=chat_id)
            return result

        # ═══════════════════════════════════════════════════════════
        #  TIER 2: Smart Dispatch (minimal tokens)
        # ═══════════════════════════════════════════════════════════

        # ── Greeting / General Chat → quick_reply (~500 tokens) ──
        if intent.intent_type == "greeting":
            context["_agent_badge"] = "🤖 Orchestrator"
            # to_thread: LLM call is sync (requests) — never block the event loop
            reply = await asyncio.to_thread(AgentBrain.quick_reply, text, agent_dict, history)
            self._save_history(agent_id, agent_dict, text, reply, history, chat_id=chat_id)
            return reply

        if intent.intent_type == "general_chat" and intent.confidence >= 0.5:
            context["_agent_badge"] = "🤖 Orchestrator"
            reply = await asyncio.to_thread(AgentBrain.quick_reply, text, agent_dict, history)
            self._save_history(agent_id, agent_dict, text, reply, history, chat_id=chat_id)
            return reply

        # ── Team Delegation (Phase 2) ──
        if intent.intent_type == "team_delegate" and intent.target_agent_id:
            target_agent = agent_manager.get(intent.target_agent_id)
            if target_agent:
                context["_agent_badge"] = f"{target_agent.name} đang xử lý..."
                print(f"[Router] 🎯 Delegating to specialist: {target_agent.name}")
                target_dict = target_agent.to_dict()
                self._enrich_agent_config(target_dict)
                self._inject_group_context(target_dict, agent_id)   # acts for the home agent
                
                # Select skills for this specialist
                selected_skills = skill_selector.select_for_team(
                    text, target_agent.allowed_skills, available_skills, limit=3
                )
                
                brain_result = await asyncio.to_thread(
                    AgentBrain.chat_targeted,
                    message=text, agent=target_dict, skills=selected_skills,
                    history=target_agent.history_log or [], intent_hint=intent.intent_type,
                )
                
                # Prefix reply with agent badge
                result = await self._handle_brain_actions(brain_result, text, target_dict, selected_skills, context)
                if isinstance(result, str):
                    result = f"*[{target_agent.name}]*\n{result}"
                self._save_history(agent_id, agent_dict, text, result, history, chat_id=chat_id)
                return result

        # ── Calendar / Search / File / Complex → targeted skills (~3000 tokens) ──
        # Try to find matching specialist for this intent and ACTUALLY hand the
        # turn to it (model + system prompt + skills), instead of only showing
        # its name as a badge while the original agent does the work.
        from tubecli.core.specialists import get_specialist_for_intent
        specialist = get_specialist_for_intent(intent.intent_type)
        # Keep the original agent for history/memory (that's who the user talks
        # to); the specialist only handles this one turn.
        home_agent_dict = agent_dict
        if specialist and specialist.id != agent_dict.get("id"):
            agent_dict = specialist.to_dict()
            self._enrich_agent_config(agent_dict)
            # to_dict() là prompt gốc → khối nhóm của HOME agent phải nhét lại.
            self._inject_group_context(agent_dict, agent_id)
            # Restrict skill choice to the specialist's own allowed set. Dựng
            # lại từ CATALOG ĐẦY ĐỦ (all_skills), không phải available_skills đã
            # bị lọc theo home agent — nếu không sẽ thành HOME ∩ specialist và
            # mất skill của specialist khi home agent bị thu hẹp. Guard: rỗng
            # thì giữ tập đầy (thà thừa còn hơn không có skill nào).
            if specialist.allowed_skills:
                restricted = [
                    s.to_dict() for s in all_skills if s.id in specialist.allowed_skills
                ]
                if restricted:
                    available_skills = restricted
        active_agent_name = agent_dict.get("name", "AI")
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

        # Inject user language preference
        user_lang = get_user_lang(chat_id)
        current_prompt = agent_dict.get("system_prompt", "You are a helpful assistant.")
        if user_lang == "vi":
            lang_instruction = t("sys.only_vi", "vi")
        elif user_lang == "zh":
            lang_instruction = t("sys.only_vi", "zh")
        else:
            lang_instruction = t("sys.only_vi", "en")
            
        agent_dict["system_prompt"] = f"{current_prompt}\n\nIMPORTANT: {lang_instruction}"
        
        brain_result = await asyncio.to_thread(
            AgentBrain.chat_targeted,
            message=text, agent=agent_dict, skills=selected_skills,
            history=history, intent_hint=intent.intent_type,
        )

        result = await self._handle_brain_actions(brain_result, text, agent_dict, selected_skills, context)
        # Worklog nhóm: chỉ khi action/skill THẬT SỰ chạy (dispatcher đổi text,
        # hoặc model chọn run_skill) — cùng tiêu chí với web chat.
        self._record_group_worklog(groups, home_agent_dict, text, brain_result, result)
        self._save_history(agent_id, home_agent_dict, text, result, history, chat_id=chat_id)
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
    #  PLAN FORMATTING
    # ═══════════════════════════════════════════════════════════════

    def _format_plan(self, plan: Dict, chat_id: int) -> str:
        """Format a pending action plan for user review."""
        lang = get_user_lang(chat_id)
        plan_type = plan.get("type", "unknown")
        provider = plan.get("provider", "youtube")
        provider_label = plan.get("provider_label", "YouTube")
        url = plan.get("url", "")
        channel = plan.get("channel")
        steps = plan.get("steps", [])
        effects = plan.get("effects", [])
        
        # Facebook = "Trang", YouTube = "Kênh"
        entity = "Trang" if provider == "facebook" else "Kênh"
        entity_lower = entity.lower()
        
        # Shorten URL for display
        url_short = url[:60] + "..." if len(url) > 60 else url
        
        # Channel/Page info
        if channel:
            ch_title = channel.get("title", "Không rõ")
            ch_email = channel.get("email", "")
            channel_line = t("plan.channel_target", lang, entity=entity, title=ch_title)
            if ch_email:
                channel_line += f" ({ch_email})"
        else:
            channel_line = t("plan.channel_unknown", lang, entity=entity)
        
        # Build plan message
        type_emoji = "📤" if plan_type == "video_upload" else "♻️"
        type_label = t("plan.upload_title", lang) if plan_type == "video_upload" else t("plan.reup_title", lang)
        
        lines = [
            f"{type_emoji} **{t('plan.header', lang)}: {type_label}**\n",
            f"🔗 URL: `{url_short}`",
            f"🌐 **{t('plan.platform', lang)}:** {provider_label}",
            channel_line,
        ]
        
        if effects:
            lines.append(t("plan.effects", lang, effects=', '.join(effects)))
        
        lines.append(t("plan.steps", lang))
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
        
        auto_secs = self._get_auto_execute_seconds()
        if auto_secs > 0:
            lines.append(f"⏱️ _Tự động thực hiện sau {auto_secs} giây..._")
        lines.append(t("plan.reply_ok", lang))
        lines.append(t("plan.reply_change", lang, entity=entity_lower))
        lines.append(t("plan.reply_cancel", lang))

        return "\n".join(lines)

    def _format_livestream_plan(self, plan: Dict, chat_id: int) -> str:
        """Format a livestream pending plan for user review."""
        url = plan.get("url", "")
        source_info = plan.get("source_info", "")
        channel = plan.get("channel")
        steps = plan.get("steps", [])

        url_short = url[:60] + "..." if len(url) > 60 else url

        if channel:
            ch_title = channel.get("title", "Không rõ")
            ch_email = channel.get("email", "")
            channel_line = f"📺 **Kênh:** {ch_title}"
            if ch_email:
                channel_line += f" ({ch_email})"
        else:
            channel_line = "📺 **Kênh:** ⭐ kênh mặc định"

        lines = [
            "🔴 **Kế hoạch: Livestream Restream**\n",
            f"🔗 Source: `{url_short}`",
            source_info,
            "",
            channel_line,
            "",
            "📋 **Các bước:**",
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")

        lines.append("")
        auto_secs = self._get_auto_execute_seconds()
        if auto_secs > 0:
            lines.append(f"⏱️ _Tự động thực hiện sau {auto_secs} giây..._")
        lines.append("✅ Trả lời **ok** để bắt đầu ngay")
        lines.append("🔄 Trả lời **đổi kênh N** để đổi kênh")
        lines.append("🚫 Trả lời **hủy** để hủy")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    #  AUTO-EXECUTE TIMER
    # ═══════════════════════════════════════════════════════════════

    def _get_auto_execute_seconds(self) -> int:
        """Auto-execute delay for pending plans. 0 = DISABLED (default) —
        publishing actions (upload/reup/livestream) then require an explicit
        'ok'. Enable by setting 'telegram_auto_execute_seconds' in
        global_settings.json (e.g. 20)."""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return max(0, int(data.get("telegram_auto_execute_seconds", 0) or 0))
        except Exception:
            pass
        return 0

    def _schedule_auto_execute(self, chat_id: int, plan: Dict, agent_dict: Dict, context: Dict, agent_id: str, history: list):
        """Schedule auto-execution of a pending plan (only if enabled in settings)."""
        self._cancel_auto_execute(chat_id)

        delay = self._get_auto_execute_seconds()
        if delay <= 0:
            return  # Auto-execute disabled — wait for explicit user confirmation

        task = asyncio.create_task(
            self._auto_execute_plan(chat_id, plan, agent_dict, context.copy(), agent_id, history, delay)
        )
        self._auto_execute_tasks[chat_id] = task

    def _cancel_auto_execute(self, chat_id: int):
        """Cancel auto-execute timer for a chat."""
        task = self._auto_execute_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            print(f"[AutoExec] Cancelled timer for chat {chat_id}")

    async def _auto_execute_plan(self, chat_id: int, plan: Dict, agent_dict: Dict, context: Dict, agent_id: str, history: list, delay: int = 20):
        """Wait `delay` seconds then auto-execute the pending plan if still present."""
        try:
            await asyncio.sleep(delay)

            # Check if the plan is still pending (user didn't respond)
            if chat_id not in self.pending_actions:
                return  # Already confirmed/cancelled/replaced

            # Pop the plan and execute
            plan = self.pending_actions.pop(chat_id)
            self._auto_execute_tasks.pop(chat_id, None)

            token = context.get("token", "")

            await self._send_message(token, chat_id,
                f"⏱️ {delay}s đã qua — tự động thực hiện kế hoạch..."
            )

            result = await self._execute_plan(plan, agent_dict, context)

            self._save_history(agent_id, agent_dict, "[auto-execute]", result, history, chat_id=chat_id)

            # Send result back to user
            if isinstance(result, str) and result.strip():
                await self._send_message(token, chat_id, result)

            print(f"[AutoExec] Auto-executed plan for chat {chat_id}")

        except asyncio.CancelledError:
            pass  # Timer was cancelled by user response
        except Exception as e:
            print(f"[AutoExec] Error: {e}")
            import traceback
            traceback.print_exc()

    async def _execute_plan(self, plan: Dict, agent_dict: Dict, context: Dict):
        """Execute a confirmed/auto-executed pending plan (single source of
        truth — used by both the user-confirm branch and the auto-exec timer)."""
        context["_agent_badge"] = plan.get("badge", "🎬 Đang thực hiện...")
        context["upload_provider"] = plan.get("provider", "youtube")
        # Pass template info to executor
        if plan.get("template_id"):
            context["template_id"] = plan["template_id"]
            context["template_name"] = plan.get("template_name", "")

        if plan["type"] == "video_upload":
            return await execute_upload_sequence(
                plan["url"], plan["original_text"], agent_dict,
                self._send_message, self._send_file,
                lambda reply, ad, ctx: handle_extension_action(reply, ad, ctx),
                context,
            )
        elif plan["type"] == "reup_action":
            return await execute_reup_sequence(
                plan["url"], plan["original_text"], agent_dict,
                self._send_message, self._send_file,
                lambda reply, ad, ctx: handle_extension_action(reply, ad, ctx),
                context,
            )
        elif plan["type"] == "livestream_action":
            from tubecli.core.telegram_actions import execute_livestream_pipeline
            return await execute_livestream_pipeline(
                source_url=plan.get("resolved_url", plan["url"]),
                user_text=plan["original_text"],
                agent_dict=agent_dict,
                send_message_fn=self._send_message,
                context=context,
            )
        return "❌ Loại kế hoạch không hợp lệ."

    # ═══════════════════════════════════════════════════════════════
    #  HELPER METHODS
    # ═══════════════════════════════════════════════════════════════

    def _inject_group_context(self, agent_dict: Dict, agent_id: str) -> list:
        """Nối khối GROUP WORKSPACE (hợp mọi nhóm chứa agent) vào system_prompt.

        Trả về danh sách nhóm để caller gửi group_ids theo action context.
        Không bao giờ raise: manifest hỏng trên đĩa không được làm bot câm.
        """
        try:
            from tubecli.core import group_context
            groups = group_context.effective_groups(agent_id or agent_dict.get("id", ""))
            block = group_context.prompt_block(groups) if groups else ""
            if block:
                base = agent_dict.get("system_prompt", "You are a helpful assistant.")
                agent_dict["system_prompt"] = f"{base}\n\n{block}"
            return groups
        except Exception as e:
            print(f"[TelegramListener] Group context skipped: {e}")
            return []

    def _record_group_worklog(self, groups, agent_dict: Dict, text: str, brain_result, result):
        """Ghi 1 dòng vào sheet worklog của nhóm khi có việc thật sự chạy (nền, không raise)."""
        if not groups:
            return
        try:
            from tubecli.core import group_context
            brain = brain_result if isinstance(brain_result, dict) else {}
            ran = brain.get("action") == "run_skill"
            if isinstance(result, dict):
                result_text = f"[File sent: {result.get('caption', '')}]"
                ran = True
            else:
                result_text = result if isinstance(result, str) else str(result or "")
                # handle_extension_action trả NGUYÊN reply khi không có action.
                ran = ran or (result_text != (brain.get("reply") or ""))
            if not ran:
                return
            status = "error" if result_text.lstrip().startswith(("❌", "⚠️", "⏰", "⏱")) else "done"
            group_context.record_worklog(groups, agent_dict, task=text, result=result_text,
                                         artifacts=[], status=status)
        except Exception as e:
            print(f"[TelegramListener] Worklog skipped: {e}")

    def _enrich_agent_config(self, agent_dict: Dict):
        """Override model with global settings + inject cloud API keys."""
        cloud_cfg = self._get_cloud_model_config()
        if cloud_cfg.get("model") and (not agent_dict.get("model") or agent_dict["model"] == "qwen:latest"):
            agent_dict["model"] = cloud_cfg["model"]

        try:
            from tubecli.extensions.cloud_api.extension import key_manager
            cloud_keys = {}
            for provider in ["gemini", "openai", "claude", "deepseek", "grok", "openrouter", "9router"]:
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

    def _chat_history_path(self, agent_id: str, chat_id):
        """File path for a per-chat Telegram history."""
        from tubecli.config import AGENT_MEMORY_DIR
        d = AGENT_MEMORY_DIR / agent_id / "telegram_chats"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{chat_id}.json"

    def _get_chat_history(self, agent_id: str, chat_id) -> list:
        """Load (and cache) the conversation history for one agent+chat pair."""
        key = f"{agent_id}:{chat_id}"
        if key in self._chat_histories:
            return self._chat_histories[key]
        hist = []
        try:
            p = self._chat_history_path(agent_id, chat_id)
            if p.exists():
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    hist = loaded
        except Exception:
            hist = []
        self._chat_histories[key] = hist
        return hist

    def _save_chat_history(self, agent_id: str, chat_id, history: list):
        """Persist a per-chat history to disk and refresh the cache."""
        self._chat_histories[f"{agent_id}:{chat_id}"] = history
        try:
            p = self._chat_history_path(agent_id, chat_id)
            p.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"[TelegramListener] Chat history save err: {e}")

    def _save_history(self, agent_id, agent_dict, text, result, history, skill_used=None, chat_id=None):
        """Non-blocking save of conversation history + memory update."""
        reply_for_history = result if isinstance(result, str) else f"[File sent: {result.get('caption', '') if isinstance(result, dict) else ''}]"
        history.append({"role": "user", "content": text, "timestamp": datetime.datetime.now().isoformat()})
        history.append({
            "role": "assistant", "content": reply_for_history,
            "timestamp": datetime.datetime.now().isoformat(), "skill_used": skill_used
        })
        if len(history) > 50:
            history = history[-50:]

        # Persist per-chat history (LLM context source) + mirror the latest
        # exchange into agent.history_log so the dashboard History tab still works
        if chat_id is not None:
            self._save_chat_history(agent_id, chat_id, history)
        agent_manager.update(agent_id, history_log=history)

        async def _bg_mem():
            try:
                from tubecli.core.memory import AgentMemory
                if not AgentMemory.should_summarize(agent_id, history):
                    return
                # to_thread: summarize/extract are sync LLM calls — keep the
                # event loop responsive for other chats while they run.
                await asyncio.to_thread(AgentBrain.post_chat_memory_update, agent_id, agent_dict, history)
                # Re-save only now: persists the _summarized markers
                if chat_id is not None:
                    self._save_chat_history(agent_id, chat_id, history)
                agent_manager.update(agent_id, history_log=history)
            except Exception as e:
                print(f"[TelegramListener] Memory err: {e}")
        asyncio.create_task(_bg_mem())

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

    async def _handle_subtitle_pipeline(self, data: dict, text: str, agent_dict: dict, context: dict) -> str:
        """Full pipeline: Download → Extract Subtitle → [TTS] → [Burn] → [Upload].
        
        Steps:
        1. Download video from URL (Douyin/TikTok/etc)
        2. Extract subtitle using Whisper (+ translate)
        3. Optionally generate voice-over from SRT (TTS)
        4. Optionally merge TTS audio into video
        5. Optionally burn subtitle into video
        6. Optionally upload to YouTube channel
        """
        import re, asyncio, os
        
        url = data.get("url", "")
        needs_burn = data.get("needs_burn", False)
        needs_tts = data.get("needs_tts", False)
        needs_upload = data.get("needs_upload", False)
        original_msg = data.get("original_message", text)
        
        token = context.get("token", "")
        chat_id = context.get("chat_id", 0)
        
        # ── Load Session Preferences ──
        from tubecli.config import DATA_DIR
        import json
        prefs_file = DATA_DIR / "telegram_prefs.json"
        
        user_prefs = {}
        if prefs_file.exists():
            try:
                with open(prefs_file, "r", encoding="utf-8") as f:
                    user_prefs = json.load(f)
            except Exception:
                pass
                
        chat_prefs = user_prefs.get(str(chat_id), {
            "default_privacy": "public",
            "upload_delay": 180,
            "default_translate": None,
            "default_tts_voice": "vi-VN-HoaiMyNeural",
        })

        # Update prefs from current message
        if "mặc định là public" in text.lower() or "public" in text.lower():
            chat_prefs["default_privacy"] = "public"
        elif "mặc định là private" in text.lower() or "private" in text.lower():
            chat_prefs["default_privacy"] = "private"
            
        if "3 phút" in text.lower() or "180s" in text.lower():
            chat_prefs["upload_delay"] = 180

        # Detect TTS voice
        tts_voice = chat_prefs.get("default_tts_voice", "vi-VN-HoaiMyNeural")
        voice_match = re.search(r'giọng\s+(\w+)', text.lower())
        if voice_match:
            voice_name = voice_match.group(1)
            voice_map = {
                "nam": "vi-VN-NamMinhNeural", "nữ": "vi-VN-HoaiMyNeural",
                "male": "vi-VN-NamMinhNeural", "female": "vi-VN-HoaiMyNeural",
            }
            tts_voice = voice_map.get(voice_name, tts_voice)

        # Detect translation
        translate_to = chat_prefs.get("default_translate")
        trans_match = re.search(r'(?:dịch|translate)\s+(?:sang\s+)?(?:tiếng\s+)?(\w+)', text.lower())
        if trans_match:
            lang_map = {
                'anh': 'English', 'english': 'English',
                'việt': 'Vietnamese', 'vietnamese': 'Vietnamese',
                'trung': 'Chinese', 'nhật': 'Japanese', 'hàn': 'Korean',
            }
            translate_to = lang_map.get(trans_match.group(1).lower(), trans_match.group(1))
            if "mặc định" in text.lower():
                chat_prefs["default_translate"] = translate_to
                
        # Save updated prefs
        user_prefs[str(chat_id)] = chat_prefs
        try:
            with open(prefs_file, "w", encoding="utf-8") as f:
                json.dump(user_prefs, f, ensure_ascii=False)
        except Exception:
            pass
        
        # Detect target channel (using channel_cache for smart resolution)
        channel_id = None
        channel_title = ""
        try:
            from tubecli.core.channel_cache import channel_cache
            resolved = channel_cache.resolve_channel("youtube", text)
            if resolved:
                channel_id = resolved.get("id")
                channel_title = resolved.get("title", "")
        except Exception:
            # Fallback to basic regex
            channel_match = re.search(r'kênh\s*(\d+|[a-zA-Z]\w*)', text.lower())
            channel_id = channel_match.group(1) if channel_match else None
        
        # ── Build dynamic step list ──
        step_defs = [("download", "📥 Tải video"), ("extract", "📝 Tách phụ đề")]
        steps = ["📥 Tải video", "📝 Tách phụ đề"]
        if needs_tts:
            step_defs.append(("tts", "🎙️ Lồng tiếng (TTS)"))
            steps.append("🎙️ Lồng tiếng (TTS)")
        if needs_burn:
            step_defs.append(("burn", "🔥 Ghi sub vào video"))
            steps.append("🔥 Ghi sub vào video")
        if needs_upload:
            step_defs.append(("upload", "📤 Upload lên YouTube"))
            steps.append("📤 Upload lên YouTube")
        
        total_steps = len(steps)
        cur_step = 0
        
        # ── Create pipeline tracker task ──
        from tubecli.core.pipeline_tracker import pipeline_tracker
        pt_task = pipeline_tracker.create_task(
            pipeline_type="subtitle_pipeline",
            chat_id=chat_id,
            url=url,
            original_message=original_msg[:200],
            step_names=step_defs,
        )
        pt_id = pt_task.task_id
        
        await self._send_message(token, chat_id,
            f"🚀 **Subtitle Pipeline** ({total_steps} bước)\n" +
            "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)) +
            f"\n\n⏳ Bước 1/{total_steps}: Đang tải video..."
        )
        
        try:
            # ── Step 1: Download ──
            cur_step = 1
            pipeline_tracker.start_step(pt_id, "download", "Đang tải...")
            dl_result = await execute_download(url, agent_dict)
            
            if not isinstance(dl_result, dict) or not dl_result.get("file_path"):
                pipeline_tracker.fail_step(pt_id, "download", str(dl_result)[:200])
                pipeline_tracker.fail_task(pt_id, "Tải video thất bại")
                return f"❌ Tải video thất bại.\n{str(dl_result)[:300]}"
            
            file_path = dl_result["file_path"]
            file_name = os.path.basename(file_path)
            pipeline_tracker.complete_step(pt_id, "download", file_name)
            pt_task.video_filename = file_name
            
            cur_step = 2
            pipeline_tracker.start_step(pt_id, "extract", "Whisper đang xử lý...")
            await self._send_message(token, chat_id,
                f"✅ Bước 1: Đã tải `{file_name}`\n⏳ Bước {cur_step}/{total_steps}: Đang tách phụ đề (Whisper)..."
            )
            
            # ── Step 2: Extract subtitle ──
            body = {"file_path": file_path, "engine": "whisper", "language": None, "translate_to": translate_to}
            resp = await self.client.post(
                f"{TUBECLI_BASE_URL}/api/v1/subtitle/extract",
                json=body, timeout=30,
            )
            if resp.status_code != 200:
                return f"❌ Lỗi API tách sub: HTTP {resp.status_code}"
            
            task_data = resp.json()
            task_id = task_data.get("task_id")
            if not task_id:
                return "❌ Không nhận được task_id."
            
            # Poll for extraction result
            subs = []
            for poll_i in range(120):  # max 4 minutes
                await asyncio.sleep(2)
                sr = await self.client.get(f"{TUBECLI_BASE_URL}/api/v1/subtitle/status/{task_id}", timeout=10)
                if sr.status_code != 200:
                    continue
                sd = sr.json()
                if sd.get("status") == "success" and sd.get("result"):
                    subs = sd["result"].get("subtitles", [])
                    break
                elif sd.get("status") == "error":
                    pipeline_tracker.fail_step(pt_id, "extract", sd.get('result', {}).get('message', 'Unknown'))
                    pipeline_tracker.fail_task(pt_id, "Tách sub thất bại")
                    return f"❌ Tách sub thất bại: {sd.get('result', {}).get('message', 'Unknown')}"
            
            if not subs:
                pipeline_tracker.fail_step(pt_id, "extract", "Timeout")
                pipeline_tracker.fail_task(pt_id, "Tách subtitle timeout")
                return "❌ Timeout: Tách subtitle mất quá lâu."
            
            # Save SRT file
            srt_path = file_path.rsplit(".", 1)[0] + ".srt"
            srt_lines = []
            for i, s in enumerate(subs, 1):
                start = self._fmt_srt_time(s.get("start", 0))
                end = self._fmt_srt_time(s.get("end", 0))
                srt_lines.append(f"{i}\n{start} --> {end}\n{s.get('text', '')}\n")
            srt_content = "\n".join(srt_lines)
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            
            translated_note = f" (dịch → {translate_to})" if translate_to else ""
            pipeline_tracker.complete_step(pt_id, "extract", f"{len(subs)} dòng{translated_note}")
            
            # ── Step 3 (optional): TTS — generate voice track from SRT ──
            output_video = file_path
            tts_audio_path = None
            
            if needs_tts:
                cur_step += 1
                pipeline_tracker.start_step(pt_id, "tts", f"Voice: {tts_voice}")
                await self._send_message(token, chat_id,
                    f"✅ Bước {cur_step-1}: Tách được {len(subs)} dòng{translated_note}\n"
                    f"⏳ Bước {cur_step}/{total_steps}: Đang lồng tiếng ({tts_voice})..."
                )
                
                # Call SRT synthesis API
                tts_resp = await self.client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/tts/synthesize-srt",
                    json={
                        "srt_content": srt_content,
                        "voice": tts_voice,
                        "engine": "edge",
                        "speed_adjust": True,
                    },
                    timeout=30,
                )
                
                if tts_resp.status_code == 200:
                    tts_data = tts_resp.json()
                    tts_task_id = tts_data.get("task_id")
                    
                    if tts_task_id:
                        # Poll for TTS result
                        for _ in range(90):  # max 3 minutes
                            await asyncio.sleep(2)
                            tr = await self.client.get(
                                f"{TUBECLI_BASE_URL}/api/v1/tts/status/{tts_task_id}", timeout=10
                            )
                            if tr.status_code != 200:
                                continue
                            td = tr.json()
                            if td.get("status") == "success" and td.get("result"):
                                tts_audio_path = td["result"].get("output", "")
                                break
                            elif td.get("status") == "error":
                                await self._send_message(token, chat_id,
                                    f"⚠️ TTS thất bại: {td.get('result', {}).get('message', '')[:200]}\nTiếp tục pipeline..."
                                )
                                break
                    
                    # Merge TTS audio into video
                    if tts_audio_path and os.path.exists(tts_audio_path):
                        merged_path = file_path.rsplit(".", 1)[0] + "_dubbed.mp4"
                        merge_cmd = [
                            "ffmpeg", "-y",
                            "-i", file_path,
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
                            output_video = merged_path
                            pipeline_tracker.complete_step(pt_id, "tts", f"Merged: {os.path.basename(merged_path)}")
                            await self._send_message(token, chat_id,
                                f"✅ Bước {cur_step}: Đã lồng tiếng thành công!"
                            )
                        else:
                            err_msg = stderr.decode()[-200:] if stderr else "Unknown"
                            pipeline_tracker.fail_step(pt_id, "tts", f"Merge failed: {err_msg[:100]}")
                            await self._send_message(token, chat_id,
                                f"⚠️ Merge audio thất bại, tiếp tục với video gốc.\n{err_msg[:100]}"
                            )
                else:
                    await self._send_message(token, chat_id,
                        f"⚠️ TTS API lỗi HTTP {tts_resp.status_code}, bỏ qua lồng tiếng."
                    )
            else:
                await self._send_message(token, chat_id,
                    f"✅ Bước {cur_step}: Tách được {len(subs)} dòng phụ đề{translated_note}"
                )
            
            # ── Step N: Burn subtitle (optional) ──
            if needs_burn:
                cur_step += 1
                pipeline_tracker.start_step(pt_id, "burn", "FFmpeg processing...")
                await self._send_message(token, chat_id,
                    f"⏳ Bước {cur_step}/{total_steps}: Đang ghi sub vào video..."
                )
                burn_resp = await self.client.post(
                    f"{TUBECLI_BASE_URL}/api/v1/subtitle/burn",
                    json={"video_path": output_video, "srt_path": srt_path},
                    timeout=30,
                )
                if burn_resp.status_code == 200:
                    burn_data = burn_resp.json()
                    burn_task = burn_data.get("task_id")
                    if burn_task:
                        for _ in range(60):
                            await asyncio.sleep(3)
                            br = await self.client.get(f"{TUBECLI_BASE_URL}/api/v1/subtitle/status/{burn_task}", timeout=10)
                            if br.status_code != 200:
                                continue
                            bd = br.json()
                            if bd.get("status") == "success":
                                output_video = bd.get("result", {}).get("output", output_video)
                                break
                            elif bd.get("status") == "error":
                                await self._send_message(token, chat_id, f"⚠️ Burn thất bại, tiếp tục với video hiện tại.")
                                break
                
                pipeline_tracker.complete_step(pt_id, "burn", os.path.basename(output_video))
                await self._send_message(token, chat_id,
                    f"✅ Bước {cur_step}: Đã ghi phụ đề vào video"
                )
            
            # ── Step N: Upload (optional) ──
            if needs_upload:
                cur_step += 1
                pipeline_tracker.start_step(pt_id, "upload", f"Channel: {channel_id}")
                await self._send_message(token, chat_id,
                    f"⏳ Bước {cur_step}/{total_steps}: Đang upload lên YouTube kênh {channel_id}..."
                )
                # Trigger upload with preferences
                upload_json = {
                    "action": "upload_video",
                    "file_path": output_video,
                    "privacy": chat_prefs.get("default_privacy", "public"),
                    "delay": chat_prefs.get("upload_delay", 180)
                }
                if channel_id:
                    upload_json["channel_index"] = channel_id
                
                fake_reply = "```json\n" + json.dumps(upload_json, ensure_ascii=False) + "\n```"
                upload_result = await handle_extension_action(fake_reply, agent_dict, context)
                
                # Extract task_id from upload result and poll for actual completion
                upload_task_id = ""
                upload_status = "queued"
                upload_video_url = ""
                upload_video_id = ""
                
                import re as _re
                tid_match = _re.search(r'Task ID[:\s]*`?([a-f0-9\-]+)`?', str(upload_result))
                if tid_match:
                    upload_task_id = tid_match.group(1)
                    
                    await self._send_message(token, chat_id,
                        f"📤 Video đang upload... Task ID: `{upload_task_id[:12]}`"
                    )
                    
                    # Poll upload status (max 5 minutes)
                    for poll_i in range(60):
                        await asyncio.sleep(5)
                        try:
                            sr = await self.client.get(
                                f"{TUBECLI_BASE_URL}/api/v1/video_manager/upload/tasks/{upload_task_id}",
                                timeout=10
                            )
                            if sr.status_code == 200:
                                sdata = sr.json()
                                task_info = sdata.get("task", {})
                                upload_status = task_info.get("status", "unknown")
                                pct = task_info.get("progress_pct", 0)
                                
                                pipeline_tracker.update_step_message(pt_id, "upload", f"{upload_status} ({pct}%)")
                                
                                if upload_status == "done":
                                    upload_video_id = task_info.get("video_id", "")
                                    upload_video_url = task_info.get("video_url", "")
                                    pipeline_tracker.complete_step(pt_id, "upload", f"✅ {upload_video_url or upload_video_id}")
                                    await self._send_message(token, chat_id,
                                        f"✅ Upload thành công!\n🎬 Video ID: `{upload_video_id}`\n🔗 {upload_video_url}"
                                    )
                                    break
                                elif upload_status in ("error", "cancelled"):
                                    err = task_info.get("error_message", "Unknown error")
                                    pipeline_tracker.fail_step(pt_id, "upload", err[:200])
                                    await self._send_message(token, chat_id, f"❌ Upload thất bại: {err[:200]}")
                                    break
                        except Exception:
                            pass
                    else:
                        # Timeout after 5 minutes
                        pipeline_tracker.update_step_message(pt_id, "upload", f"Timeout - status: {upload_status}")
                
                # Build final result
                upload_ok = upload_status == "done"
                upload_msg = f"✅ {upload_video_url}" if upload_ok else f"⏳ {upload_status} (Task: {upload_task_id[:12]})"
                
                # File paths for preview
                video_serve_url = f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/file/{os.path.basename(output_video)}"
                
                summary = (
                    f"{'✅' if upload_ok else '⚠️'} **Pipeline {'hoàn tất' if upload_ok else 'hoàn tất (upload chưa xong)'}!**\n\n"
                    f"📥 Video: `{file_name}`\n"
                    f"📝 Subtitle: {len(subs)} dòng{translated_note}\n"
                    f"🎙️ TTS: {'✅ ' + tts_voice if needs_tts and tts_audio_path else '⏭️ Bỏ qua'}\n"
                    f"🔥 Burn: {'✅' if needs_burn else '⏭️ Bỏ qua'}\n"
                    f"📤 Upload: {upload_msg}\n\n"
                    f"📁 File: `{output_video}`\n"
                    f"▶️ Xem: {video_serve_url}"
                )
                
                if upload_ok:
                    pipeline_tracker.complete_task(pt_id, summary, file_name)
                else:
                    pipeline_tracker.fail_task(pt_id, f"Upload status: {upload_status}")
                return summary
            
            # No upload — return subtitle result
            video_serve_url = f"{TUBECLI_BASE_URL}/api/v1/douyin_downloader/file/{os.path.basename(output_video)}"
            summary = (
                f"✅ **Pipeline hoàn tất!**\n\n"
                f"📥 Video: `{file_name}`\n"
                f"📝 Subtitle: {len(subs)} dòng{translated_note}\n"
                f"🎙️ TTS: {'✅ ' + tts_voice if needs_tts and tts_audio_path else '⏭️ Bỏ qua'}\n"
                f"📁 SRT: `{os.path.basename(srt_path)}`\n"
                f"🔥 Burn: {'✅ ' + os.path.basename(output_video) if needs_burn else '⏭️ Bỏ qua'}\n\n"
                f"📁 File: `{output_video}`\n"
                f"▶️ Xem: {video_serve_url}\n\n"
                f"📝 Preview:\n"
                + "\n".join(f"  {s['start']:.1f}s → {s['end']:.1f}s: {s['text'][:60]}" for s in subs[:5])
                + (f"\n  ... +{len(subs) - 5} dòng nữa" if len(subs) > 5 else "")
            )
            pipeline_tracker.complete_task(pt_id, summary, file_name)
            return summary
        
        except Exception as e:
            pipeline_tracker.fail_task(pt_id, str(e)[:400])
            return f"❌ Pipeline lỗi: {str(e)[:400]}"


    async def _handle_subtitle_action(self, text: str, agent_dict: dict, context: dict) -> str:
        """Handle subtitle extraction requests via chatbot.
        
        Supports:
        - 'tách sub file /path/to/video.mp4'
        - 'tách sub https://youtube.com/watch?v=xxx'
        - 'tách sub video.mp4 dịch sang tiếng Anh'
        - Pipeline: 'tải video <url> tách sub upload lên kênh'
        """
        import re
        text_lower = text.lower()
        
        # Extract YouTube URL
        yt_match = re.search(r'(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+)', text)
        # Extract video URL (Douyin/TikTok)
        video_match = re.search(r'(https?://\S+)', text)
        # Extract file path
        path_match = re.search(r'([A-Za-z]:\\[^\s]+\.\w+|/\S+\.\w+)', text)
        
        # Detect translation target
        translate_to = None
        trans_match = re.search(r'dịch\s+(?:sang\s+)?(?:tiếng\s+)?(\w+)', text_lower)
        if trans_match:
            lang_map = {
                'anh': 'English', 'english': 'English', 'en': 'English',
                'việt': 'Vietnamese', 'vietnamese': 'Vietnamese', 'vi': 'Vietnamese',
                'trung': 'Chinese', 'chinese': 'Chinese', 'zh': 'Chinese',
                'nhật': 'Japanese', 'japanese': 'Japanese', 'ja': 'Japanese',
                'hàn': 'Korean', 'korean': 'Korean', 'ko': 'Korean',
                'pháp': 'French', 'french': 'French', 'fr': 'French',
                'tây ban nha': 'Spanish', 'spanish': 'Spanish',
            }
            translate_to = lang_map.get(trans_match.group(1).lower(), trans_match.group(1))
        
        # Detect engine preference
        engine = "whisper"
        if "gemini" in text_lower:
            engine = "gemini"
        elif "youtube" in text_lower and "cc" in text_lower:
            engine = "youtube"
        
        try:
            # ── Case 1: YouTube URL → use youtube engine or whisper ──
            if yt_match:
                url = yt_match.group(1)
                if engine == "whisper":
                    engine = "youtube"  # Default to CC for YouTube URLs
                
                if engine == "youtube":
                    resp = await self.client.post(
                        f"{TUBECLI_BASE_URL}/api/v1/subtitle/extract/youtube",
                        json={"url": url, "languages": None},
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            subs = data.get("subtitles", [])
                            return self._format_subtitle_result(subs, engine, url=url, translate_to=translate_to)
                        return f"❌ Không lấy được sub: {data.get('message', 'Unknown')}"
                    return f"❌ Lỗi API: HTTP {resp.status_code}"
            
            # ── Case 2: Video URL (Douyin/TikTok) → download first, then extract ──
            if video_match and not path_match:
                url = video_match.group(1)
                # Check if this is a downloadable video URL
                if any(d in url for d in ['douyin', 'tiktok', 'iesdouyin']):
                    from tubecli.core.telegram_actions import execute_download
                    dl_result = await execute_download(url, agent_dict)
                    if isinstance(dl_result, dict) and dl_result.get("file_path"):
                        file_path = dl_result["file_path"]
                    elif isinstance(dl_result, str) and "file_path" in str(dl_result):
                        fp_match = re.search(r'file_path["\s:]+([^\s"]+)', str(dl_result))
                        file_path = fp_match.group(1) if fp_match else None
                    else:
                        return f"⚠️ Đã tải video nhưng không lấy được đường dẫn file.\n{str(dl_result)[:300]}"
                    
                    if file_path:
                        return await self._extract_and_format(file_path, engine, translate_to=translate_to)
            
            # ── Case 3: Local file path ──
            if path_match:
                file_path = path_match.group(1)
                return await self._extract_and_format(file_path, engine, translate_to=translate_to)
            
            # ── Case 4: No URL/path found → guide user ──
            return (
                "📝 **Subtitle Extractor**\n\n"
                "Sử dụng:\n"
                "• `tách sub https://youtube.com/watch?v=xxx`\n"
                "• `tách sub C:\\video.mp4`\n"
                "• `tách sub video.mp4 dịch sang tiếng Anh`\n"
                "• Hoặc mở **Dashboard → Subtitle Extractor** để dùng giao diện UI"
            )
            
        except Exception as e:
            return f"❌ Lỗi tách subtitle: {str(e)[:300]}"

    async def _extract_and_format(self, file_path: str, engine: str, translate_to: str = None) -> str:
        """Call subtitle extraction API and poll for result."""
        import asyncio
        
        body = {"file_path": file_path, "engine": engine, "language": None, "translate_to": translate_to}
        resp = await self.client.post(
            f"{TUBECLI_BASE_URL}/api/v1/subtitle/extract",
            json=body,
            timeout=30,
        )
        if resp.status_code != 200:
            return f"❌ Lỗi API extract: HTTP {resp.status_code}"
        
        data = resp.json()
        task_id = data.get("task_id")
        if not task_id:
            return "❌ Không nhận được task_id từ API."
        
        # Poll for result
        for _ in range(90):  # max 3 minutes
            await asyncio.sleep(2)
            status_resp = await self.client.get(
                f"{TUBECLI_BASE_URL}/api/v1/subtitle/status/{task_id}",
                timeout=10,
            )
            if status_resp.status_code != 200:
                continue
            status_data = status_resp.json()
            
            if status_data.get("status") == "success" and status_data.get("result"):
                result = status_data["result"]
                subs = result.get("subtitles", [])
                lang = result.get("language", "?")
                
                # Save SRT
                srt_path = file_path.rsplit(".", 1)[0] + ".srt"
                srt_lines = []
                for i, s in enumerate(subs, 1):
                    start = self._fmt_srt_time(s.get("start", 0))
                    end = self._fmt_srt_time(s.get("end", 0))
                    srt_lines.append(f"{i}\n{start} --> {end}\n{s.get('text', '')}\n")
                
                import os
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(srt_lines))
                
                translated_note = f"\n🌐 Dịch sang: {result.get('translated_to', translate_to)}" if translate_to else ""
                return (
                    f"✅ **Tách phụ đề thành công!**\n\n"
                    f"🎯 Engine: {engine.upper()}\n"
                    f"🌐 Ngôn ngữ gốc: {lang}{translated_note}\n"
                    f"📊 {len(subs)} dòng phụ đề\n"
                    f"📁 File: `{os.path.basename(srt_path)}`\n\n"
                    f"📝 Preview:\n"
                    + "\n".join(f"  {s['start']:.1f}s → {s['end']:.1f}s: {s['text'][:60]}" for s in subs[:5])
                    + (f"\n  ... +{len(subs) - 5} dòng nữa" if len(subs) > 5 else "")
                )
            
            elif status_data.get("status") == "error":
                msg = status_data.get("result", {}).get("message", "Unknown error")
                return f"❌ Tách subtitle thất bại: {msg}"
        
        return "⏰ Timeout: Quá trình tách subtitle mất quá lâu (>3 phút)."

    @staticmethod
    def _fmt_srt_time(seconds: float) -> str:
        if seconds < 0: seconds = 0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _format_subtitle_result(subs: list, engine: str, url: str = "", translate_to: str = None) -> str:
        count = len(subs)
        if count == 0:
            return "⚠️ Không tìm thấy phụ đề nào."
        return (
            f"✅ **Tách phụ đề thành công!**\n\n"
            f"🎯 Engine: {engine.upper()}\n"
            f"📊 {count} dòng phụ đề\n"
            + (f"🔗 URL: {url}\n" if url else "")
            + f"\n📝 Preview:\n"
            + "\n".join(f"  {s.get('start', 0):.1f}s → {s.get('end', 0):.1f}s: {s.get('text', '')[:60]}" for s in subs[:5])
            + (f"\n  ... +{count - 5} dòng nữa" if count > 5 else "")
        )

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
                json={"chat_id": chat_id, "text": t("sys.thinking")}
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
        try:
            print("[TelegramListener] Background service started (2-Tier Intent Routing)")
        except UnicodeEncodeError:
            print("[TelegramListener] Background service started")

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
