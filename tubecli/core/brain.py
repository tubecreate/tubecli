"""
Agent Brain — AI-powered decision-making for smart agents.
Handles chat → skill dispatch using LLM reasoning + command matching.
"""
import json
import re
import datetime
from typing import Dict, List, Optional, Any


class AgentBrain:
    """The 'brain' of a smart agent: understands user messages and dispatches skills."""

    # ── Fast-path: Command Matching ───────────────────────────────

    @staticmethod
    def match_skill_command(message: str, skills: List[Dict]) -> Optional[Dict]:
        """Check if user message directly matches a skill's explicit trigger commands.
        Only matches exact commands or 'command + arguments' patterns.
        For natural language intent → let the LLM Brain analyze it.
        """
        msg_clean = re.sub(r'[?!.,;]+$', '', message.strip().lower()).strip()
        
        for skill in skills:
            commands = skill.get("commands", [])
            for cmd in commands:
                if not cmd:
                    continue
                cmd_clean = cmd.strip().lower()
                if len(cmd_clean) < 3:
                    continue  # Skip too-short commands to avoid false matches
                
                # Exact match or starts with command (e.g. cmd="tải video", msg="tải video tiktok")
                if msg_clean == cmd_clean or msg_clean.startswith(cmd_clean + " "):
                    return skill
        return None

    @staticmethod
    def build_system_prompt(agent_prompt: str, skills: List[Dict], memory_context: str = "",
                            message: str = "") -> str:
        """Build a system prompt with full skill descriptions for intent-based routing.

        Strategy:
        - Fast-path command match happens BEFORE this (no LLM call = 0 tokens)
        - If LLM is needed: show TOP-8 relevant skills WITH descriptions
        - LLM analyzes user INTENT and picks the right skill
        """
        skills_desc = ""
        if skills:
            msg_lower = (message or "").lower()
            scored = []
            for s in skills:
                skill_id = s.get("id") or getattr(s, "id", "unknown")
                skill_name = s.get("name") or getattr(s, "name", "")
                skill_cmds = s.get("commands") or getattr(s, "commands", [])
                skill_desc_text = s.get("description") or getattr(s, "description", "")

                # Score by semantic relevance
                score = 0
                if msg_lower:
                    for cmd in skill_cmds:
                        if cmd.lower() in msg_lower:
                            score += 3
                            break
                    name_lower = skill_name.lower()
                    if any(w in msg_lower for w in name_lower.split() if len(w) > 2):
                        score += 2
                    desc_words = [w for w in skill_desc_text.lower().split() if len(w) > 3]
                    matching_desc = sum(1 for w in desc_words if w in msg_lower)
                    score += min(matching_desc, 3)  # cap at 3

                scored.append((score, skill_id, skill_name, skill_desc_text, skill_cmds))

            # Show top 8 skills, sorted by relevance
            top = sorted(scored, key=lambda x: -x[0])[:8]

            lines = []
            for score, sid, sname, sdesc, scmds in top:
                # Include description so LLM understands what each skill DOES
                desc_short = sdesc[:120] if sdesc else "No description"
                lines.append(f"  - ID: {sid}\n    Name: {sname}\n    Does: {desc_short}")

            total = len(skills)
            shown = len(lines)
            skills_desc = (
                f"\n\n### AVAILABLE SKILLS ({shown}/{total}) — Analyze user INTENT to pick the right one:\n"
                + "\n".join(lines)
                + "\nIMPORTANT: If user asks about weather, news, searching info, looking up anything → use the Google Search skill."
                + "\nIf user sends a DIRECT video link (douyin.com/video/xxx, tiktok.com/@.../video/xxx) → use download_video action."
                + "\nIf user sends a SHORT link (v.douyin.com/xxx) with intent like 'mới nhất', 'theo dõi', 'post lên kênh' → this is a USER PROFILE link, use the appropriate skill (add_tracker, trigger_tracker) instead of download_video."
                + "\nIf no skill matches the intent → reply conversationally.\n"
            )

        # Memory context injection
        memory_section = ""
        if memory_context:
            memory_section = f"\n\n### MEMORY:\n{memory_context}\n"

        # IMPORTANT: Use string CONCATENATION, NOT .format() or f-string on the full block.
        # agent_prompt may contain {"action": "..."} JSON which breaks str.format().
        static_prompt = (
            "## SYSTEM - AUTONOMOUS EXECUTION MODE:\n"
            "You are an autonomous AI agent. Analyze user INTENT and ACT directly.\n\n"
            "### ACTION FORMAT (output JSON to trigger system):\n"
            '- Run a skill → {"action": "run_skill", "skill_id": "<ID>", "input": "<user query>"}\n'
            '- Video URL → {"action": "download_video", "url": "<URL>"}\n'
            '- File ops → {"action": "file_action", "operation": "create_folder|create_file|delete|move|copy|list|read", "path": "~/Desktop/...", "content": "", "destination": ""}\n'
            '- Create team → {"action": "create_team", "template": "dev_team", "name": "<name>"}\n'
            '- API call → {"action": "run_api", "method": "POST", "endpoint": "/api/v1/..."}\n'
            '- Create skill → {"action": "create_skill", "name": "<n>", "description": "<d>", "instructions": ["..."]}\n\n'
            "### INTENT ANALYSIS RULES:\n"
            "1. Read the user message carefully to understand their INTENT.\n"
            "2. If the intent matches a skill → output run_skill JSON with the skill ID and user's query.\n"
            "3. If user wants info/search/weather/news/lookup → use the search/browser skill.\n"
            "4. DIRECT Video URLs (douyin.com/video/xxx, tiktok.com/@.../video/xxx) → download_video. But SHORT links (v.douyin.com/xxx) with keywords like 'mới nhất', 'lên kênh', 'theo dõi' → these are USER PROFILE links, route to the correct skill instead.\n"
            "5. File/folder create/delete/move/list → ALWAYS use file_action directly.\n"
            "6. NEVER say 'go to Dashboard'. Always try to ACT.\n"
            "7. **CRITICAL**: For greetings (hi, hello, xin chào, etc.), casual chat, or questions WITHOUT a clear actionable intent → reply conversationally in plain text. Do NOT output any JSON action block. Only output JSON when the user EXPLICITLY requests an action.\n\n"
            "### YOUR PERSONA:\n"
        )
        return static_prompt + agent_prompt + "\n" + skills_desc + memory_section + "\n"

    # ── Quick Reply (Minimal Token) ───────────────────────────────

    @staticmethod
    def quick_reply(
        message: str,
        agent: Dict,
        history: List[Dict] = None,
    ) -> str:
        """Lightweight chat for greetings/casual conversation.
        NO skill injection, NO extension docs = ~500 tokens instead of ~15000.
        Uses cloud AI for fast response.
        """
        from tubecli.core.memory import AgentMemory
        agent_id = agent.get("id", "")
        
        # Minimal memory: only facts, no full session history
        memory_section = ""
        try:
            facts = AgentMemory.get_facts(agent_id) if agent_id else []
            if facts:
                fact_lines = [f"- {f.get('fact', '')}" for f in facts[:5]]
                memory_section = "\n### KNOWLEDGE:\n" + "\n".join(fact_lines)
        except Exception:
            pass
        
        persona = agent.get("system_prompt", "You are a friendly assistant.")
        system_prompt = (
            f"### YOUR PERSONA:\n{persona}\n"
            f"{memory_section}\n\n"
            "Respond naturally and conversationally. Keep it brief and friendly. "
            "Use Vietnamese if the user writes in Vietnamese."
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Only last 5 messages for quick context
        if history:
            for h in history[-5:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        
        messages.append({"role": "user", "content": message})
        
        return AgentBrain._call_llm(agent, messages, temperature=0.7)

    # ── Chat with Targeted Skills (Intent-Aware) ──────────────────

    @staticmethod
    def chat_targeted(
        message: str,
        agent: Dict,
        skills: List[Dict],
        history: List[Dict] = None,
        intent_hint: str = "",
    ) -> Dict[str, Any]:
        """Process a chat message with PRE-FILTERED skills only.
        Called by the IntentRouter after selecting relevant skills.
        Uses intent_hint to further reduce system prompt size.
        
        Returns same format as chat().
        """
        from tubecli.i18n import t
        from tubecli.core.memory import AgentMemory

        agent_id = agent.get("id", "")
        memory_context = AgentMemory.build_memory_context(agent_id) if agent_id else ""
        
        # Build optimized system prompt based on intent
        system_prompt = AgentBrain.build_system_prompt(
            agent.get("system_prompt", "You are a helpful assistant."),
            skills,  # Already filtered to 2-3 skills max
            memory_context=memory_context,
            message=message,
        )

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for h in history[-10:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        raw_response = AgentBrain._call_llm(agent, messages)
        
        action_data = AgentBrain._extract_action(raw_response)
        if action_data:
            action_type = action_data.get("action")
            if action_type == "run_skill":
                skill_id = action_data.get("skill_id", "")
                skill_name = "Skill"
                for s in skills:
                    if s["id"] == skill_id:
                        skill_name = s["name"]
                        break
                return {
                    "reply": t("brain.running_skill", name=skill_name),
                    "action": "run_skill",
                    "skill_id": skill_id,
                    "skill_input": action_data.get("input", message),
                }
            elif action_type == "file_action":
                try:
                    from tubecli.extensions.file_manager.file_service import file_service
                    op = action_data.get("operation", "")
                    path = action_data.get("path", "")
                    content = action_data.get("content", "")
                    destination = action_data.get("destination", "")

                    if op == "create_folder":
                        r = file_service.create_folder(path)
                        reply = f"✅ Đã tạo thư mục: {r.get('path', path)}"
                    elif op == "create_file":
                        r = file_service.create_file(path, content)
                        reply = f"✅ Đã tạo file: {r.get('path', path)}"
                    elif op == "delete":
                        file_service.delete(path)
                        reply = f"✅ Đã xóa: {path}"
                    elif op == "list":
                        r = file_service.list_dir(path or "~/Desktop")
                        items = r.get("items", [])
                        lines = [f"📂 {r.get('path', path)} ({r.get('count', 0)} mục):"]
                        for item in items[:20]:
                            icon = "📁" if item.get("is_dir") else "📄"
                            lines.append(f"  {icon} {item['name']}")
                        reply = "\n".join(lines)
                    elif op == "read":
                        r = file_service.read_file(path)
                        reply = f"📄 {path}:\n{r.get('content', '')[:2000]}"
                    elif op == "move":
                        file_service.move(path, destination)
                        reply = f"✅ Đã di chuyển: {path} → {destination}"
                    elif op == "copy":
                        file_service.copy(path, destination)
                        reply = f"✅ Đã sao chép: {path} → {destination}"
                    else:
                        reply = f"❌ Operation không hợp lệ: {op}"

                    return {"reply": reply, "action": "file_action", "action_data": action_data}
                except Exception as e:
                    return {"reply": f"❌ Lỗi file: {str(e)}", "action": "file_action"}
            else:
                import json as _json
                return {
                    "reply": "```json\n" + _json.dumps(action_data, ensure_ascii=False) + "\n```",
                    "action": action_type,
                    "action_data": action_data,
                }

        return {"reply": raw_response, "action": None, "skill_id": None, "skill_input": ""}

    # ── Chat with LLM (Legacy, full skill list) ───────────────────

    @staticmethod
    def chat(
        message: str,
        agent: Dict,
        skills: List[Dict],
        history: List[Dict] = None,
    ) -> Dict[str, Any]:
        """Process a chat message through the agent brain.

        Returns:
            {
                "reply": str,           # Text response to user
                "action": str|None,     # "run_skill" or None
                "skill_id": str|None,   # Which skill to run
                "skill_input": str,     # Input to pass to skill
            }
        """
        from tubecli.i18n import t

        # 1. Fast-path: exact command match
        matched = AgentBrain.match_skill_command(message, skills)
        if matched:
            return {
                "reply": t("brain.running_skill", name=matched['name']),
                "action": "run_skill",
                "skill_id": matched["id"],
                "skill_input": message,
            }

        # 2. AI-powered reasoning (with memory context)
        from tubecli.core.memory import AgentMemory
        agent_id = agent.get("id", "")
        memory_context = AgentMemory.build_memory_context(agent_id) if agent_id else ""
        system_prompt = AgentBrain.build_system_prompt(
            agent.get("system_prompt", "You are a helpful assistant."),
            skills,
            memory_context=memory_context,
            message=message,
        )

        # Build conversation messages
        messages = [{"role": "system", "content": system_prompt}]

        # Add recent history (last 10 messages)
        if history:
            for h in history[-10:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        messages.append({"role": "user", "content": message})

        # Call LLM
        raw_response = AgentBrain._call_llm(agent, messages)

        # 3. Parse response
        action_data = AgentBrain._extract_action(raw_response)
        if action_data:
            action_type = action_data.get("action")
            if action_type == "run_skill":
                skill_id = action_data.get("skill_id", "")
                skill_name = "Skill"
                for s in skills:
                    if s["id"] == skill_id:
                        skill_name = s["name"]
                        break

                return {
                    "reply": t("brain.running_skill", name=skill_name),
                    "action": "run_skill",
                    "skill_id": skill_id,
                    "skill_input": action_data.get("input", message),
                }

            elif action_type == "file_action":
                # Execute file operation directly and return text result
                try:
                    from tubecli.extensions.file_manager.file_service import file_service
                    op = action_data.get("operation", "")
                    path = action_data.get("path", "")
                    content = action_data.get("content", "")
                    destination = action_data.get("destination", "")

                    if op == "create_folder":
                        r = file_service.create_folder(path)
                        reply = f"✅ Đã tạo thư mục: {r.get('path', path)}"
                    elif op == "create_file":
                        r = file_service.create_file(path, content)
                        reply = f"✅ Đã tạo file: {r.get('path', path)}"
                    elif op == "delete":
                        r = file_service.delete(path)
                        reply = f"✅ Đã xóa: {path}"
                    elif op == "move":
                        r = file_service.move(path, destination)
                        reply = f"✅ Đã di chuyển: {path} → {destination}"
                    elif op == "copy":
                        r = file_service.copy(path, destination)
                        reply = f"✅ Đã sao chép: {path} → {destination}"
                    elif op == "list":
                        r = file_service.list_dir(path or "~/Desktop")
                        items = r.get("items", [])
                        lines = [f"📂 {r.get('path', path)} ({r.get('count', 0)} mục):"]
                        for item in items[:20]:
                            icon = "📁" if item.get("is_dir") else "📄"
                            size = f" ({item.get('size_human', '')})" if not item.get("is_dir") else ""
                            lines.append(f"  {icon} {item['name']}{size}")
                        if len(items) > 20:
                            lines.append(f"  ... và {len(items) - 20} mục khác")
                        reply = "\n".join(lines)
                    elif op == "read":
                        r = file_service.read_file(path)
                        file_content = r.get("content", "")
                        reply = f"📄 Nội dung file {path}:\n\n{file_content[:2000]}"
                    else:
                        reply = f"❌ Operation không hợp lệ: {op}"

                    return {
                        "reply": reply,
                        "action": "file_action",
                        "action_data": action_data,
                    }
                except Exception as e:
                    return {
                        "reply": f"❌ Lỗi file: {str(e)}",
                        "action": "file_action",
                    }

            elif action_type in ("download_video", "create_team", "run_api", "schedule_event"):
                # Pass extension actions through as raw reply for telegram_listener to handle
                import json as _json
                return {
                    "reply": "```json\n" + _json.dumps(action_data, ensure_ascii=False) + "\n```",
                    "action": action_type,
                    "action_data": action_data,
                }

            elif action_type == "create_skill":
                return {
                    "reply": t("brain.creating_skill", name=action_data.get('name')),
                    "action": "create_skill",
                    "_raw_action": action_data,          # full JSON for server.py workflow builder
                    "skill_name": action_data.get("name", ""),
                    "skill_desc": action_data.get("description", ""),
                    "skill_instructions": action_data.get("instructions", []),
                }

            else:
                # Unknown action type — pass through for extension handler (e.g. trigger_tracker, add_tracker)
                import json as _json
                return {
                    "reply": "```json\n" + _json.dumps(action_data, ensure_ascii=False) + "\n```",
                    "action": action_type,
                    "action_data": action_data,
                }

        # Fallback keyword matching for creation
        if any(kw in message.lower() for kw in ["tạo skill", "viết skill", "create skill"]):
             return {
                "reply": t("brain.creating_skill_generic"),
                "action": "create_skill",
                "skill_name": "New AI Skill",
                "skill_instructions": ["Analysing request", "Opening browser", "Collecting data"]
            }

        # 5. No skill needed
        return {
            "reply": raw_response,
            "action": None,
            "skill_id": None,
            "skill_input": "",
        }

    # ── Post-Chat Memory Update ───────────────────────────────────

    @staticmethod
    def post_chat_memory_update(agent_id: str, agent: Dict, history: List[Dict]):
        """Check if memory update is needed after a chat exchange.
        Called asynchronously after each chat response.
        """
        if not agent_id or not history:
            return

        from tubecli.core.memory import AgentMemory

        if AgentMemory.should_summarize(agent_id, history):
            # Create a lightweight LLM caller bound to this agent
            def llm_caller(messages):
                return AgentBrain._call_llm(agent, messages, temperature=0.3)

            # Summarize session (Layer 2)
            AgentMemory.summarize_and_archive(agent_id, history, llm_caller)

            # Extract facts (Layer 3)
            AgentMemory.extract_facts(agent_id, history, llm_caller)

            # Mark messages as summarized
            AgentMemory.mark_history_summarized(history)

    # ── Autonomous Execution (ReAct or Linear) ────────────────────

    @staticmethod
    async def autonomous_run(
        message: str,
        agent: Dict,
        skill: Dict,
    ) -> str:
        """Run an autonomous ReAct loop or linear workflow execution."""
        
        # 🟢 If it's a standard Skill with a workflow, run it linearly for 100% reliability
        if skill.get("skill_type") == "Skill":
            try:
                print(f"[Brain] Running skill '{skill.get('name')}' via linear workflow...")
                # Force headless on browser nodes
                if "workflow_data" in skill:
                    for n in skill["workflow_data"].get("nodes", []):
                        if n.get("type") in ("browser_action", "browser_control", "puppeteer"):
                            n.setdefault("config", {})["headless"] = True
                return await AgentBrain.run_workflow_linear(message, agent, skill)
            except Exception as e:
                print(f"[Brain] Linear execution failed, falling back to ReAct: {e}")

        from tubecli.nodes.registry import get_node_tool_schemas, create_node_from_dict
        
        tools = get_node_tool_schemas()
        
        # SOP from workflow_data
        wf_data = skill.get("workflow_data", {})
        nodes = wf_data.get("nodes", [])
        sop_steps = []
        for n in nodes:
            label = n.get('label') or n.get('type')
            sop_steps.append(f"- {label}")
        sop_text = "\n".join(sop_steps) or "No specific steps defined."

        system_prompt = f"""You are an autonomous AI agent.
Task: "{message}"
Skill: {skill.get('name', '')}
SOP:
{sop_text}

You MUST output a JSON block to call a tool:
```json
{{ "tool": "tool_name", "params": {{ "config": {{}}, "input_name": "value" }} }}
```

Available Tools:
{json.dumps(tools, indent=1, ensure_ascii=False)}

Rules:
1. Output ONLY the JSON block.
2. Call `finish_workflow` when done.
"""
        
        messages = [{"role": "system", "content": system_prompt}]
        max_steps = 10
        print(f"\n[Autonomous Loop] Started for goal: '{message}'")
        
        for step in range(max_steps):
            print(f"  [{step+1}/{max_steps}] LLM Thinking...")
            raw_response = AgentBrain._call_llm(agent, messages, temperature=0.1)
            messages.append({"role": "assistant", "content": raw_response})
            
            tool_call = AgentBrain._extract_tool_call(raw_response)
            if not tool_call:
                # Clean any leftover JSON from direct reply
                clean_reply = AgentBrain._clean_json_from_text(raw_response)
                print(f"  [{step+1}] 🤖 LLM replied directly: {clean_reply[:100]}...")
                return clean_reply
                
            tool_name = tool_call.get("tool", "")
            tool_params = tool_call.get("params", {})
            
            print(f"  [{step+1}] 🛠️ Tool: {tool_name}")
            
            # Handle finish — LLMs may use camelCase or snake_case
            tool_name_normalized = tool_name.lower().replace("_", "")
            if tool_name_normalized in ("finishworkflow", "finish", "done"):
                final_ans = (
                    tool_params.get("final_answer")
                    or tool_params.get("finalAnswer")
                    or tool_params.get("answer")
                    or tool_params.get("result")
                    or raw_response
                )
                return AgentBrain._clean_json_from_text(str(final_ans))
                
            try:
                node = create_node_from_dict({"type": tool_name, "config": tool_params.get("config", {})})
                inputs = {k: v for k, v in tool_params.items() if k != "config"}
                result = await node.execute(inputs)
                observation = json.dumps(result, ensure_ascii=False, default=str)[:3000]
                print(f"  [{step+1}] 👁️ Obs: {observation[:100]}...")
            except Exception as e:
                observation = f"Error: {str(e)}"
                print(f"  [{step+1}] ❌ Error: {str(e)}")
                
            messages.append({"role": "user", "content": f"Observation:\n{observation}\n\nNext step?"})
            
        from tubecli.i18n import t as _t
        return _t("brain.max_steps")

    @staticmethod
    async def run_workflow_linear(message: str, agent: Dict, skill: Dict) -> str:
        """Execute a simple linear workflow without LLM reasoning (High Reliability).
        Optimized: skips redundant LLM summarization when workflow already has AI output."""
        import asyncio
        import time
        from tubecli.nodes.registry import create_node_from_dict
        
        wf_data = skill.get("workflow_data", {})
        nodes = wf_data.get("nodes", [])
        connections = wf_data.get("connections", [])
        
        if not nodes:
            return "Skill has no workflow nodes."

        context = {"_initial_message": message}
        last_result = None
        has_ai_node = any(n.get("type") in ("model_agent", "ai_node") for n in nodes)
        ai_response_text = ""
        
        for n in nodes:
            node_type = n.get("type")
            node_id = n.get("id")
            start_t = time.time()
            print(f"  [Linear] Node: {node_id} ({node_type})")
            
            # Resolve inputs from context
            node_inputs = {}
            node_has_explicit_input = False
            for conn in connections:
                if conn.get("to_node_id") == node_id:
                    from_id = conn.get("from_node_id")
                    from_port = conn.get("from_port_id")
                    to_port = conn.get("to_port_id")
                    if from_id in context:
                        val = context[from_id]
                        if isinstance(val, dict) and from_port in val:
                            node_inputs[to_port] = val[from_port]
                        else:
                            node_inputs[to_port] = val
                        node_has_explicit_input = True
            
            # Fallback for first node or search
            if not node_has_explicit_input:
                if node_type == "text_input": node_inputs["text"] = message
                elif node_type == "browser_action": node_inputs["prompt"] = message
                elif node_type == "api_request": node_inputs["url"] = message
            
            try:
                node = create_node_from_dict(n)
                # Per-node timeout: 30s for AI nodes, 15s for search, 10s for others
                if node_type in ("model_agent", "ai_node"):
                    node_timeout = 45
                elif node_type == "web_search":
                    node_timeout = 20
                else:
                    node_timeout = 10
                
                result = await asyncio.wait_for(
                    node.execute(node_inputs),
                    timeout=node_timeout
                )
                context[node_id] = result
                last_result = result
                elapsed = time.time() - start_t
                print(f"  [Linear] ✅ {node_id} done in {elapsed:.1f}s")
                
                # Capture AI response for direct return
                if node_type in ("model_agent", "ai_node") and isinstance(result, dict):
                    ai_text = result.get("response", "")
                    if ai_text and len(ai_text) > 20:
                        ai_response_text = ai_text
                        
            except asyncio.TimeoutError:
                elapsed = time.time() - start_t
                print(f"  [Linear] ⏰ {node_id} timed out after {elapsed:.1f}s")
                # For search nodes, continue with empty results
                if node_type == "web_search":
                    context[node_id] = {"results": f"Tìm kiếm quá lâu cho: {message}", "status": "timeout"}
                    continue
                raise Exception(f"Node {node_id} timed out after {node_timeout}s")
            except Exception as e:
                raise Exception(f"Error in node {node_id}: {e}")

        # Return AI response directly if workflow already processed through AI
        # This avoids a redundant LLM summarization call (saves 5-30s)
        if ai_response_text:
            return ai_response_text

        # Format final result (only for non-AI workflows)
        if last_result:
            return AgentBrain.format_skill_result(agent, skill.get("name"), {"status": "completed", "outputs": context}, message)
        return "Workflow completed."

    # ── LLM Management ────────────────────────────────────────────

    @staticmethod
    def _call_llm(agent: Dict, messages: List[Dict], temperature: float = 0.7) -> str:
        model = agent.get("model") or agent.get("browser_ai_model") or "qwen:latest"
        cloud_keys = agent.get("cloud_api_keys", {})
        
        # Ollama models use colon notation (e.g. gemma3:1b, qwen:latest)
        # Cloud models DON'T (e.g. gemini-2.0-flash, gpt-4o)
        is_ollama_format = ":" in model  # gemma3:1b, qwen:latest, etc.
        
        if not is_ollama_format and any(k in model.lower() for k in ["gemini", "gemma"]):
            result = AgentBrain._call_gemini(model, cloud_keys.get("gemini", ""), messages, temperature=temperature)
        elif any(k in model.lower() for k in ["gpt", "chatgpt", "o1", "o3"]):
            result = AgentBrain._call_openai(model, cloud_keys.get("openai", ""), messages, temperature=temperature)
        elif "claude" in model.lower():
            result = AgentBrain._call_claude(model, cloud_keys.get("claude", ""), messages)
        elif "deepseek" in model.lower():
            result = AgentBrain._call_openai(model, cloud_keys.get("deepseek", ""), messages, base_url="https://api.deepseek.com/v1", temperature=temperature)
        else:
            return AgentBrain._call_ollama(model, messages, temperature=temperature)
        
        # ── Auto-Failover on Quota/Rate Limit Errors ──
        if any(err_tag in result for err_tag in ["429", "quota", "rate limit", "Too Many Requests", "exceeded"]):
            print(f"[Brain] ⚠️ Provider quota error detected: {result[:100]}")
            result = AgentBrain._failover_llm(model, cloud_keys, messages, temperature, result)
        
        return result

    @staticmethod
    def _failover_llm(failed_model: str, cloud_keys: Dict, messages: List[Dict], temperature: float, original_error: str) -> str:
        """Auto-failover: try other keys/providers, then local Ollama."""
        
        # Step 1: Report the failed key to KeyManager
        try:
            from tubecli.extensions.cloud_api.extension import key_manager, PROVIDERS
            
            # Detect which provider failed
            failed_provider = None
            if any(k in failed_model.lower() for k in ["gemini", "gemma"]):
                failed_provider = "gemini"
            elif any(k in failed_model.lower() for k in ["gpt", "chatgpt", "o1", "o3"]):
                failed_provider = "openai"
            elif "claude" in failed_model.lower():
                failed_provider = "claude"
            elif "deepseek" in failed_model.lower():
                failed_provider = "deepseek"
            
            if failed_provider and cloud_keys.get(failed_provider):
                key_manager.report_key_error(failed_provider, cloud_keys[failed_provider], "Auto-disabled: Quota exceeded")
                print(f"[Brain] 🔄 Disabled key for {failed_provider}, searching for alternatives...")
            
            # Step 2: Try another key from the SAME provider
            if failed_provider:
                new_key = key_manager.get_active_key(failed_provider)
                if new_key and new_key != cloud_keys.get(failed_provider):
                    print(f"[Brain] 🔑 Trying backup key for {failed_provider}...")
                    if failed_provider == "gemini":
                        result = AgentBrain._call_gemini(failed_model, new_key, messages, temperature=temperature)
                    elif failed_provider == "openai":
                        result = AgentBrain._call_openai(failed_model, new_key, messages, temperature=temperature)
                    elif failed_provider == "claude":
                        result = AgentBrain._call_claude(failed_model, new_key, messages)
                    elif failed_provider == "deepseek":
                        result = AgentBrain._call_openai(failed_model, new_key, messages, base_url="https://api.deepseek.com/v1", temperature=temperature)
                    else:
                        result = None
                    if result and not any(e in result for e in ["429", "quota", "rate limit", "exceeded"]):
                        print(f"[Brain] ✅ Backup key for {failed_provider} works!")
                        return result
            
            # Step 3: Try a DIFFERENT cloud provider
            fallback_order = ["gemini", "deepseek", "openai", "claude"]
            for provider in fallback_order:
                if provider == failed_provider:
                    continue
                alt_key = key_manager.get_active_key(provider)
                if alt_key:
                    prov_models = PROVIDERS.get(provider, {}).get("models", [])
                    alt_model = prov_models[0] if prov_models else None
                    if not alt_model:
                        continue
                    
                    print(f"[Brain] 🔄 Failover: trying {provider}/{alt_model}...")
                    if provider == "gemini":
                        result = AgentBrain._call_gemini(alt_model, alt_key, messages, temperature=temperature)
                    elif provider == "openai":
                        result = AgentBrain._call_openai(alt_model, alt_key, messages, temperature=temperature)
                    elif provider == "claude":
                        result = AgentBrain._call_claude(alt_model, alt_key, messages)
                    elif provider == "deepseek":
                        result = AgentBrain._call_openai(alt_model, alt_key, messages, base_url="https://api.deepseek.com/v1", temperature=temperature)
                    else:
                        continue
                    
                    if result and not any(e in result for e in ["429", "quota", "rate limit", "exceeded", "[Error]"]):
                        print(f"[Brain] ✅ Failover to {provider}/{alt_model} succeeded!")
                        return f"⚠️ *[Auto-Failover: {failed_provider} → {provider}]*\n\n{result}"
        
        except Exception as e:
            print(f"[Brain] Failover error: {e}")
        
        # Step 4: Final fallback — local Ollama
        print("[Brain] 🏠 All cloud providers failed. Falling back to local Ollama...")
        ollama_result = AgentBrain._call_ollama("qwen:latest", messages, temperature=temperature)
        
        if "[Ollama Error]" in ollama_result:
            # No local model available either
            return (
                f"⚠️ **Tất cả AI Cloud đều hết quota!**\n"
                f"- {failed_model}: {original_error[:150]}\n"
                f"- Ollama local: {ollama_result}\n\n"
                f"💡 Giải pháp:\n"
                f"1. Thêm key mới: `tubecli cloud add <provider> <key>`\n"
                f"2. Cài Ollama: `ollama pull qwen:latest`\n"
                f"3. Chờ quota reset (thường ~1 phút)"
            )
        
        return f"⚠️ *[Auto-Failover: Cloud → Ollama local]*\n\n{ollama_result}"

    @staticmethod
    def _call_ollama(model: str, messages: List[Dict], temperature: float = 0.7) -> str:
        import requests
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "")
            return f"[Ollama Error] {resp.status_code}"
        except Exception as e:
            return f"[Ollama Error] {e}"

    @staticmethod
    def _call_gemini(model: str, api_key: str, messages: List[Dict], temperature: float = 0.7) -> str:
        """Call Gemini via REST API (no SDK required)."""
        if not api_key: return "[Error] No Gemini key."
        import requests
        try:
            # Convert messages to Gemini contents format
            contents = []
            for m in messages:
                if m["role"] == "system":
                    contents.append({"role": "user", "parts": [{"text": m["content"]}]})
                    contents.append({"role": "model", "parts": [{"text": "OK, I understand."}]})
                elif m["role"] == "user":
                    contents.append({"role": "user", "parts": [{"text": m["content"]}]})
                elif m["role"] == "assistant":
                    contents.append({"role": "model", "parts": [{"text": m["content"]}]})

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": contents,
                "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
            }
            r = requests.post(url, json=payload, timeout=120)
            if r.status_code != 200:
                return f"[Gemini Error] HTTP {r.status_code}: {r.text[:200]}"
            data = r.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
            return "[Gemini Error] No candidates in response"
        except Exception as e: return f"[Gemini Error] {e}"

    @staticmethod
    def _call_openai(model: str, api_key: str, messages: List[Dict], base_url: str = None, temperature: float = 0.7) -> str:
        if not api_key: return "[Error] No API key."
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            oai_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
            response = client.chat.completions.create(model=model, messages=oai_messages, temperature=temperature)
            return response.choices[0].message.content
        except Exception as e: return f"[OpenAI Error] {e}"

    @staticmethod
    def _call_claude(model: str, api_key: str, messages: List[Dict]) -> str:
        if not api_key: return "[Error] No Claude key."
        try:
            import httpx
            system_text = "\n".join([m["content"] for m in messages if m["role"] == "system"])
            chat_messages = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]} for m in messages if m["role"] != "system"]
            resp = httpx.post("https://api.anthropic.com/v1/messages", 
                             headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                             json={"model": model, "max_tokens": 4096, "messages": chat_messages, "system": system_text}, timeout=120)
            data = resp.json()
            return "\n".join(b["text"] for b in data.get("content", []) if b["type"] == "text")
        except Exception as e: return f"[Claude Error] {e}"

    @staticmethod
    def _clean_json_from_text(text: str) -> str:
        """Extract clean text from LLM responses that may contain JSON wrappers.
        E.g., extracts the finalAnswer/final_answer from finish_workflow JSON."""
        if not text:
            return text
        
        def _extract_answer(data):
            if not isinstance(data, dict):
                return None
            for key in ("finalAnswer", "final_answer", "answer"):
                if key in data and data[key]:
                    return str(data[key])
            params = data.get("params", {})
            if isinstance(params, dict):
                for key in ("finalAnswer", "final_answer", "answer", "result"):
                    if key in params and params[key]:
                        return str(params[key])
            return None
        
        stripped = text.strip()
        
        # 1. Try parsing entire text as JSON
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                answer = _extract_answer(data)
                if answer:
                    return answer
            except Exception:
                pass
        
        # 2. Try code blocks (greedy for nested {})
        try:
            code_block = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
            if code_block:
                data = json.loads(code_block.group(1))
                answer = _extract_answer(data)
                if answer:
                    return answer
        except Exception:
            pass
        
        # 3. Bracket-matching for nested JSON
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

    @staticmethod
    def _extract_action(text: str) -> Optional[Dict]:
        """Extract any JSON action block from LLM response."""
        # Known action types (built-in)
        known_action_types = ["run_skill", "create_skill", "download_video", "create_team", "run_api", "schedule_event"]
        try:
            # Code block: ```json {...} ```
            code_block = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if code_block:
                data = json.loads(code_block.group(1))
                if data.get("action"):
                    return data
            # Inline JSON for any known action
            for action_type in known_action_types:
                inline = re.search(
                    r'(\{[^{}]*"action"\s*:\s*"' + action_type + r'"[^{}]*\})',
                    text, re.DOTALL
                )
                if inline:
                    try:
                        return json.loads(inline.group(1))
                    except Exception:
                        pass
            # Fallback: try to find ANY inline JSON with an "action" key (extension actions)
            inline_any = re.search(
                r'(\{[^{}]*"action"\s*:\s*"[a-z_]+"[^{}]*\})',
                text, re.DOTALL
            )
            if inline_any:
                try:
                    data = json.loads(inline_any.group(1))
                    if data.get("action"):
                        return data
                except Exception:
                    pass
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_tool_call(text: str) -> Optional[Dict]:
        try:
            match = re.search(r'```json\s*(\{.*?"tool"\s*:\s*".*?\})\s*```', text, re.DOTALL) or re.search(r'(\{"tool"\s*:\s*".*?"\})', text, re.DOTALL)
            if match: return json.loads(match.group(1))
        except: pass
        return None

    @staticmethod
    def format_skill_result(agent: Dict, skill_name: str, result: Dict, original_message: str) -> str:
        from tubecli.i18n import t
        status = result.get("status", "unknown")
        outputs = result.get("outputs", {})
        output_summary = ""
        for node_id, data in outputs.items():
            if isinstance(data, dict):
                for k, v in data.items():
                    if not k.startswith("_"): output_summary += f"  {k}: {str(v)[:300]}\n"
        
        # If output is short enough and already readable, return directly (skip LLM call)
        if output_summary and len(output_summary) < 2000:
            # Check if the output looks like plain human text (not raw JSON/code)
            text_lines = [l.strip() for l in output_summary.split("\n") if l.strip()]
            looks_like_text = all(
                not l.startswith("{") and not l.startswith("[") and not l.startswith("file_path:")
                for l in text_lines[:3]
            )
            if looks_like_text and text_lines:
                # Return the readable output directly
                clean_parts = []
                for line in text_lines:
                    # Remove port prefixes like "response:" "results:" etc.
                    for prefix in ["response: ", "results: ", "content: ", "data: "]:
                        if line.startswith(prefix):
                            line = line[len(prefix):]
                            break
                    if line and line not in ("provider: ollama", "provider: gemini", "provider: chatgpt"):
                        clean_parts.append(line)
                if clean_parts:
                    return "\n".join(clean_parts)

        summarize_instruction = t("brain.summarize_prompt")
        prompt = f"User asked: {original_message}. Skill {skill_name} result: {status}. Outputs: {output_summary}. {summarize_instruction}"
        messages = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}]
        try: return AgentBrain._call_llm(agent, messages)
        except: return t("brain.skill_completed", name=skill_name)

    @staticmethod
    def determine_current_task(routine: Dict, current_time: datetime.datetime = None) -> Optional[Dict]:
        if not current_time: current_time = datetime.datetime.now()
        hour = current_time.hour
        tod = "night"
        if 6 <= hour < 12: tod = "morning"
        elif 12 <= hour < 18: tod = "afternoon"
        elif 18 <= hour <= 23: tod = "evening"
        return {"time_of_day": tod, "activities": routine.get("dailyRoutine", {}).get(tod, {})}
