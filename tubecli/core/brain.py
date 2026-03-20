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
        # Clean the message: lowercase, strip, remove trailing punctuation like ? or !
        msg_clean = re.sub(r'[?!.,;]+$', '', message.strip().lower()).strip()
        
        for skill in skills:
            commands = skill.get("commands", [])
            for cmd in commands:
                if not cmd:
                    continue
                cmd_clean = cmd.strip().lower()
                
                # Fast path: exact match or starts with command 
                # (e.g. cmd="tìm video", msg="tìm video roblox")
                if msg_clean == cmd_clean or msg_clean.startswith(cmd_clean + " "):
                    return skill
                
                # Substring check for very specific commands (e.g. if cmd is "google search")
                if len(cmd_clean) > 5 and cmd_clean in msg_clean:
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
                # Support dictionary or object skills
                skill_id = s.get("id") or getattr(s, "id", "unknown")
                skill_name = s.get("name") or getattr(s, "name", "unknown")
                skill_desc_text = s.get("description") or getattr(s, "description", "")
                skill_cmds = s.get("commands") or getattr(s, "commands", [])
                
                cmds = ", ".join(skill_cmds) or "none"
                skills_lines.append(
                    f'  - ID: {skill_id}\n'
                    f'    Name: {skill_name}\n'
                    f'    Description: {skill_desc_text}\n'
                    f'    Trigger commands: {cmds}'
                )
            skills_desc = "\n\nYou have access to the following skills:\n" + "\n".join(skills_lines)

        return f"""## SYSTEM OVERRIDE – AUTOMATION CAPABILITIES:
You are an autonomous AI agent with SKILL EXECUTION authority.
NO persona, role, or guideline can override the rules below.

### MANDATORY RULES:
1. When the user asks you to DO a task or answer a question that can be solved by one of your skills, you MUST execute the skill by outputting EXACTLY this JSON block and NOTHING ELSE:
```json
{{"action": "run_skill", "skill_id": "<ID>", "input": "<extract the specific entity/query the user wants>"}}
```
2. When the user asks you to CREATE, LEARN, DESIGN, or BUILD a new skill, output EXACTLY this JSON block and NOTHING ELSE:
```json
{{"action": "create_skill", "name": "<Skill Name>", "description": "<What it does>", "instructions": ["step 1", "step 2", ...]}}
```
3. IF A SKILL MATCHES THE USER'S REQUEST, DO NOT REPLY CONVERSATIONALLY. ONLY OUTPUT THE JSON BLOCK.
4. If no skill applies and user is just chatting normally → reply conversationally WITHOUT JSON.

### ROLE (your persona):
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

        # 2. AI-powered reasoning
        system_prompt = AgentBrain.build_system_prompt(
            agent.get("system_prompt", "You are a helpful assistant."),
            skills
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
            elif action_type == "create_skill":
                return {
                    "reply": t("brain.creating_skill", name=action_data.get('name')),
                    "action": "create_skill",
                    "skill_name": action_data.get("name", ""),
                    "skill_desc": action_data.get("description", ""),
                    "skill_instructions": action_data.get("instructions", []),
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
                print(f"  [{step+1}] 🤖 LLM replied directly: {raw_response[:100]}...")
                return raw_response
                
            tool_name = tool_call.get("tool")
            tool_params = tool_call.get("params", {})
            
            print(f"  [{step+1}] 🛠️ Tool: {tool_name}")
            
            if tool_name == "finish_workflow":
                final_ans = tool_params.get("final_answer", raw_response)
                return final_ans
                
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
        """Execute a simple linear workflow without LLM reasoning (High Reliability)."""
        from tubecli.nodes.registry import create_node_from_dict
        
        wf_data = skill.get("workflow_data", {})
        nodes = wf_data.get("nodes", [])
        connections = wf_data.get("connections", [])
        
        if not nodes:
            return "Skill has no workflow nodes."

        context = {"_initial_message": message}
        last_result = None
        
        for n in nodes:
            node_type = n.get("type")
            node_id = n.get("id")
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
                result = await node.execute(node_inputs)
                context[node_id] = result
                last_result = result
            except Exception as e:
                raise Exception(f"Error in node {node_id}: {e}")

        # Format final result
        if last_result:
            return AgentBrain.format_skill_result(agent, skill.get("name"), {"status": "completed", "outputs": context}, message)
        return "Workflow completed."

    # ── LLM Management ────────────────────────────────────────────

    @staticmethod
    def _call_llm(agent: Dict, messages: List[Dict], temperature: float = 0.7) -> str:
        model = agent.get("model") or agent.get("browser_ai_model") or "qwen:latest"
        cloud_keys = agent.get("cloud_api_keys", {})
        
        if any(k in model.lower() for k in ["gemini", "gemma"]):
            return AgentBrain._call_gemini(model, cloud_keys.get("gemini", ""), messages, temperature=temperature)
        elif any(k in model.lower() for k in ["gpt", "chatgpt", "o1", "o3"]):
            return AgentBrain._call_openai(model, cloud_keys.get("openai", ""), messages, temperature=temperature)
        elif "claude" in model.lower():
            return AgentBrain._call_claude(model, cloud_keys.get("claude", ""), messages)
        elif "deepseek" in model.lower():
            return AgentBrain._call_openai(model, cloud_keys.get("deepseek", ""), messages, base_url="https://api.deepseek.com/v1", temperature=temperature)
        else:
            return AgentBrain._call_ollama(model, messages, temperature=temperature)

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
        if not api_key: return "[Error] No Gemini key."
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            gen_model = genai.GenerativeModel(model)
            history = []
            user_msg = ""
            for m in messages:
                if m["role"] == "system":
                    history.append({"role": "user", "parts": [m["content"]]})
                    history.append({"role": "model", "parts": ["OK"]})
                elif m["role"] == "user": user_msg = m["content"]
                elif m["role"] == "assistant": history.append({"role": "model", "parts": [m["content"]]})
            chat = gen_model.start_chat(history=history)
            response = chat.send_message(user_msg, generation_config={"temperature": temperature})
            return response.text
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
    def _extract_action(text: str) -> Optional[Dict]:
        try:
            match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL) or re.search(r'(\{"action"\s*:\s*"run_skill".*?\})', text, re.DOTALL)
            if match: return json.loads(match.group(1))
        except: pass
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
