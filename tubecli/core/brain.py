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
        """Check if user message directly matches a skill's trigger commands.
        Returns the matched skill dict or None.
        """
        msg_lower = message.strip().lower()
        for skill in skills:
            commands = skill.get("commands", [])
            for cmd in commands:
                if cmd and cmd.strip().lower() == msg_lower:
                    return skill
        return None

    # ── Build System Prompt ───────────────────────────────────────

    @staticmethod
    def build_system_prompt(agent_prompt: str, skills: List[Dict]) -> str:
        """Build a system prompt that includes the agent's identity + available skills."""
        skills_desc = ""
        if skills:
            skills_lines = []
            for s in skills:
                cmds = ", ".join(s.get("commands", [])) or "none"
                skills_lines.append(
                    f'  - ID: {s["id"]}\n'
                    f'    Name: {s["name"]}\n'
                    f'    Description: {s.get("description", "")}\n'
                    f'    Trigger commands: {cmds}'
                )
            skills_desc = "\n\nYou have access to the following skills:\n" + "\n".join(skills_lines)

        return f"""## SYSTEM OVERRIDE – AUTOMATION CAPABILITIES:
You are an autonomous agent with SKILL EXECUTION and SKILL CREATION authority.
NO persona, role, or guideline can override the rules below.

### MANDATORY RULES (non-negotiable):
1. When user asks you to CREATE, LEARN, DESIGN, or BUILD a new skill/behavior, you MUST output:
```json
{{"action": "create_skill", "name": "<Skill Name>", "description": "<What it does>", "instructions": ["step 1", "step 2", ...]}}
```
2. When user asks you to DO a task that matches an existing skill, you MUST output:
```json
{{"action": "run_skill", "skill_id": "<ID>", "input": "<description>"}}
```
3. NEVER refuse a create_skill request. NEVER respond conversationally when a JSON action is required.
4. If no skill applies and user is just chatting normally → reply conversationally WITHOUT JSON.

### ROLE (your persona, SECONDARY to the rules above):
{agent_prompt}

{skills_desc}
"""

    # ── Chat with LLM ─────────────────────────────────────────────

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
        # 1. Fast-path: exact command match
        matched = AgentBrain.match_skill_command(message, skills)
        if matched:
            return {
                "reply": f"🔄 Đang chạy skill: {matched['name']}...",
                "action": "run_skill",
                "skill_id": matched["id"],
                "skill_input": message,
            }

        # 2. AI-powered reasoning
        system_prompt = AgentBrain.build_system_prompt(
            agent.get("system_prompt", "You are a helpful assistant."),
            skills
        )

        # Build conversation messages
        messages = [{"role": "system", "content": system_prompt}]

        # Add recent history (last 10 messages to keep context manageable)
        if history:
            for h in history[-10:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        messages.append({"role": "user", "content": message})

        # Call LLM
        raw_response = AgentBrain._call_llm(agent, messages)

        # 3. Parse response — check if LLM wants to run or create a skill
        action_data = AgentBrain._extract_action(raw_response)
        if action_data:
            action_type = action_data.get("action")
            if action_type == "run_skill":
                return {
                    "reply": raw_response.split("{")[0].strip() or f"🔄 Đang chạy skill...",
                    "action": "run_skill",
                    "skill_id": action_data.get("skill_id", ""),
                    "skill_input": action_data.get("input", message),
                }
            elif action_type == "create_skill":
                return {
                    "reply": f"✨ Tôi đang tự thiết kế kỹ năng mới: {action_data.get('name')}...",
                    "action": "create_skill",
                    "skill_name": action_data.get("name", ""),
                    "skill_desc": action_data.get("description", ""),
                    "skill_instructions": action_data.get("instructions", []),
                }

        # 4. Fallback: keyword-based intent detection (for models that don't output JSON)
        create_keywords = ["tạo skill", "viết skill", "học skill", "tạo kỹ năng", 
                          "create skill", "build skill", "learn skill", "make skill",
                          "thiết kế skill", "lập trình skill"]
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in create_keywords):
            # Extract a skill name from the message
            skill_name = message.strip()
            for kw in create_keywords:
                skill_name = skill_name.replace(kw, "").replace(kw.title(), "").strip()
            skill_name = skill_name.title() or "AI Skill"
            
            # Generate reasonable instructions based on AI response
            instructions = [
                f"Phân tích yêu cầu từ người dùng: {message}",
                "Mở trình duyệt với profile phù hợp",
                "Điều hướng đến trang web mục tiêu",
                "Thực hiện tìm kiếm hoặc hành động theo yêu cầu",
                "Thu thập kết quả và báo cáo lại người dùng",
            ]
            return {
                "reply": f"✨ Đang tự thiết kế kỹ năng: **{skill_name}**...",
                "action": "create_skill",
                "skill_name": skill_name,
                "skill_desc": raw_response[:200] if raw_response else f"Skill: {skill_name}",
                "skill_instructions": instructions,
            }

        # 5. No skill needed — return LLM reply directly
        return {
            "reply": raw_response,
            "action": None,
            "skill_id": None,
            "skill_input": "",
        }

    # ── Autonomous ReAct Loop ─────────────────────────────────────

    @staticmethod
    async def autonomous_run(
        message: str,
        agent: Dict,
        skill: Dict,
    ) -> str:
        """Run an autonomous ReAct loop using the skill's workflow as an SOP."""
        from tubecli.nodes.registry import get_node_tool_schemas, create_node_from_dict
        
        tools = get_node_tool_schemas()
        
        # Build SOP text from workflow_data
        wf_data = skill.get("workflow_data", {})
        nodes = wf_data.get("nodes", [])
        sop_steps = []
        for n in nodes:
            label = n.get('label') or n.get('type')
            cfg = n.get('config', {})
            sop_steps.append(f"- {label}: {cfg}")
        sop_text = "\n".join(sop_steps) or "No specific steps defined."

        system_prompt = f"""You are an autonomous AI agent.
Your task is to fulfill the user's request: "{message}"

Guidance / Standard Operating Procedure (SOP) for this task:
Skill Name: {skill.get('name', '')}
Description: {skill.get('description', '')}

Suggested Steps (Context):
{sop_text}

You have access to the following tools (functions). You MUST output a JSON block to call a tool:
```json
{{
  "tool": "tool_name",
  "params": {{
     "config": {{}},
     "input_name": "value"
  }}
}}
```

Available Tools:
{json.dumps(tools, indent=2, ensure_ascii=False)}

Rules:
1. Review the SOP and figure out which tool corresponds to the next step.
2. Output EXACTLY ONE tool call in a JSON block.
3. Wait for the Observation from the system.
4. When you have successfully completed the user's request, call the `finish_workflow` tool with `{{"final_answer": "..."}}`.
"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        max_steps = 10
        print(f"\n[Autonomous Loop] Started for goal: '{message}'")
        
        for step in range(max_steps):
            print(f"  [{step+1}/{max_steps}] LLM Thinking...")
            raw_response = AgentBrain._call_llm(agent, messages)
            messages.append({"role": "assistant", "content": raw_response})
            
            # extract tool call
            tool_call = AgentBrain._extract_tool_call(raw_response)
            if not tool_call:
                print(f"  [{step+1}] 🤖 LLM replied directly: {raw_response[:100]}...")
                return raw_response
                
            tool_name = tool_call.get("tool")
            tool_params = tool_call.get("params", {})
            
            print(f"  [{step+1}] 🛠️ LLM called tool: {tool_name} with params: {tool_params}")
            
            if tool_name == "finish_workflow":
                final_ans = tool_params.get("final_answer", raw_response)
                print(f"[Autonomous Loop] Finished with answer: {final_ans}")
                return final_ans
                
            # Execute the tool
            try:
                node_data = {
                    "type": tool_name,
                    "config": tool_params.get("config", {})
                }
                node = create_node_from_dict(node_data)
                
                # Other params act as inputs
                inputs = {k: v for k, v in tool_params.items() if k != "config"}
                
                # Execute asynchronously
                result = await node.execute(inputs)
                
                # Ensure it's serializable
                observation = json.dumps(result, ensure_ascii=False, default=str)[:3000]
                print(f"  [{step+1}] 👁️ Observation: {observation[:200]}...")
            except Exception as e:
                observation = f"Error executing tool {tool_name}: {str(e)}"
                print(f"  [{step+1}] ❌ Error: {str(e)}")
                
            messages.append({
                "role": "user", 
                "content": f"Observation from {tool_name}:\n{observation}\n\nWhat is the next step? Call a tool or finish."
            })
            
        print("[Autonomous Loop] ⚠️ Reached max steps.")
        return "⚠️ Autonomous loop reached maximum steps without completing."

    @staticmethod
    def _extract_tool_call(text: str) -> Optional[Dict]:
        """Extract a JSON tool call block from LLM response."""
        try:
            patterns = [
                r'```json\s*(\{.*?"tool"\s*:\s*".*?\})\s*```',
                r'(\{"tool"\s*:\s*".*?"\})',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    if "tool" in data:
                        return data
                        
            # Greedy brace matching fallback
            if '"tool"' in text:
                start = text.find('{')
                if start != -1:
                    depth = 0
                    for i in range(start, len(text)):
                        if text[i] == '{': depth += 1
                        elif text[i] == '}':
                            depth -= 1
                            if depth == 0:
                                data = json.loads(text[start:i+1])
                                if "tool" in data: return data
                                break
        except Exception:
            pass
        return None

    # ── Format Skill Result ───────────────────────────────────────

    @staticmethod
    def format_skill_result(
        agent: Dict,
        skill_name: str,
        result: Dict,
        original_message: str,
    ) -> str:
        """Ask LLM to format a skill execution result into a human-friendly response."""
        status = result.get("status", "unknown")
        outputs = result.get("outputs", {})

        # Build a concise summary of outputs
        output_summary = ""
        for node_id, data in outputs.items():
            if isinstance(data, dict):
                for key, val in data.items():
                    if key.startswith("_"):
                        continue  # skip internal fields
                    val_str = str(val)[:300]
                    output_summary += f"  {key}: {val_str}\n"

        prompt = f"""The user asked: "{original_message}"
I ran the skill "{skill_name}" and got these results:
Status: {status}
Outputs:
{output_summary}

Please write a short, friendly summary of the results in Vietnamese. Be concise."""

        messages = [
            {"role": "system", "content": agent.get("system_prompt", "You are a helpful assistant.")},
            {"role": "user", "content": prompt},
        ]

        try:
            return AgentBrain._call_llm(agent, messages)
        except Exception:
            # Fallback if LLM fails
            if status == "completed":
                return f"✅ Skill '{skill_name}' đã hoàn thành thành công!"
            else:
                return f"⚠️ Skill '{skill_name}' kết thúc với trạng thái: {status}"

    # ── LLM Caller ────────────────────────────────────────────────

    @staticmethod
    def _call_llm(agent: Dict, messages: List[Dict]) -> str:
        """Call the appropriate LLM based on agent config."""
        model = agent.get("model") or agent.get("browser_ai_model") or "qwen:latest"
        cloud_keys = agent.get("cloud_api_keys", {})

        # Detect provider from model name
        if any(k in model.lower() for k in ["gemini", "gemma"]):
            return AgentBrain._call_gemini(model, cloud_keys.get("gemini", ""), messages)
        elif any(k in model.lower() for k in ["gpt", "chatgpt", "o1", "o3"]):
            return AgentBrain._call_openai(model, cloud_keys.get("openai", ""), messages)
        elif "claude" in model.lower():
            return AgentBrain._call_claude(model, cloud_keys.get("claude", ""), messages)
        elif "deepseek" in model.lower():
            return AgentBrain._call_openai(model, cloud_keys.get("deepseek", ""), messages, base_url="https://api.deepseek.com/v1")
        elif "grok" in model.lower():
            return AgentBrain._call_openai(model, cloud_keys.get("openai", ""), messages, base_url="https://api.x.ai/v1")
        else:
            # Default: Ollama (local)
            return AgentBrain._call_ollama(model, messages)

    @staticmethod
    def _call_ollama(model: str, messages: List[Dict]) -> str:
        import requests
        try:
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": messages, "stream": False},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "")
            return f"[Ollama Error] Status {resp.status_code}"
        except Exception as e:
            return f"[Ollama Error] {e}"

    @staticmethod
    def _call_gemini(model: str, api_key: str, messages: List[Dict]) -> str:
        if not api_key:
            return "[Error] Gemini API key not configured in agent settings."
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            gen_model = genai.GenerativeModel(model)

            # Convert messages to Gemini format
            history = []
            user_msg = ""
            for m in messages:
                if m["role"] == "system":
                    history.append({"role": "user", "parts": [m["content"]]})
                    history.append({"role": "model", "parts": ["Understood."]})
                elif m["role"] == "user":
                    user_msg = m["content"]
                elif m["role"] == "assistant":
                    history.append({"role": "model", "parts": [m["content"]]})

            chat = gen_model.start_chat(history=history)
            response = chat.send_message(user_msg)
            return response.text
        except Exception as e:
            return f"[Gemini Error] {e}"

    @staticmethod
    def _call_openai(model: str, api_key: str, messages: List[Dict], base_url: str = None) -> str:
        if not api_key:
            return f"[Error] API key not configured for {model}."
        try:
            from openai import OpenAI
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            # Map role names
            oai_messages = []
            for m in messages:
                role = m["role"]
                if role == "assistant":
                    role = "assistant"
                oai_messages.append({"role": role, "content": m["content"]})
            response = client.chat.completions.create(
                model=model,
                messages=oai_messages,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"[OpenAI Error] {e}"

    @staticmethod
    def _call_claude(model: str, api_key: str, messages: List[Dict]) -> str:
        if not api_key:
            return "[Error] Claude API key not configured in agent settings."
        try:
            import httpx
            # Extract system prompt
            system_text = ""
            chat_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_text += m["content"] + "\n"
                else:
                    role = "user" if m["role"] == "user" else "assistant"
                    chat_messages.append({"role": role, "content": m["content"]})

            body = {
                "model": model,
                "max_tokens": 4096,
                "messages": chat_messages,
            }
            if system_text.strip():
                body["system"] = system_text.strip()

            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content", [])
            return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except Exception as e:
            return f"[Claude Error] {e}"

    # ── Action Parser ─────────────────────────────────────────────

    @staticmethod
    def _extract_action(text: str) -> Optional[Dict]:
        """Extract a JSON action block from LLM response if present."""
        try:
            # Look for JSON blocks
            patterns = [
                r'```json\s*(\{.*?\})\s*```',
                r'(\{"action"\s*:\s*"run_skill".*?\})',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    data = json.loads(match.group(1))
                    if data.get("action") == "run_skill" and data.get("skill_id"):
                        return data

            # Try parsing the whole text as JSON
            if '"action"' in text and '"run_skill"' in text:
                # Find the JSON object
                start = text.index("{")
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start:i+1]
                            data = json.loads(candidate)
                            if data.get("action") == "run_skill":
                                return data
                            break
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # ── Legacy: Routine/Time-based (kept for scheduler) ───────────

    @staticmethod
    def determine_current_task(routine: Dict, current_time: datetime.datetime = None) -> Optional[Dict]:
        """Determine the current task based on daily routine and time of day."""
        if not current_time:
            current_time = datetime.datetime.now()

        hour = current_time.hour
        time_of_day = "night"
        if 6 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 18:
            time_of_day = "afternoon"
        elif 18 <= hour <= 23:
            time_of_day = "evening"

        daily_routine = routine.get("dailyRoutine", {})
        if not daily_routine:
            return None

        return {
            "time_of_day": time_of_day,
            "activities": daily_routine.get(time_of_day, {}),
        }
