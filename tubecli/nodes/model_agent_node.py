"""Built-in node: Model Agent — multi-provider AI inference (Ollama, Gemini, ChatGPT, Claude, Grok)."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
from tubecli.config import OLLAMA_BASE_URL, DEFAULT_AI_MODEL
import requests
import json


class ModelAgentNode(BaseNode):
    node_type = "model_agent"
    display_name = "🤖 Model Agent"
    description = "AI inference with multiple providers: Ollama, Gemini, ChatGPT, Claude, Grok. Can use existing Agent config."
    icon = "🤖"
    category = "AI"

    def _setup_ports(self):
        self.add_input("prompt", PortType.TEXT, "User prompt")
        self.add_input("context", PortType.TEXT, "Additional context", required=False)
        self.add_input("history", PortType.JSON, "Chat history (messages array)", required=False)
        self.add_output("response", PortType.TEXT, "AI response text")
        self.add_output("usage", PortType.JSON, "Token usage info")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        prompt = inputs.get("prompt", "")
        context = inputs.get("context", "")
        history = inputs.get("history", [])

        # Try loading config from an existing Agent
        agent_name = self.config.get("agent_name", "")
        provider = self.config.get("provider", "ollama")
        api_key = self.config.get("api_key", "")
        model = self.config.get("model", DEFAULT_AI_MODEL)
        system_prompt = self.config.get("system_prompt", "You are a helpful assistant.")
        temperature = float(self.config.get("temperature", 0.7))
        max_tokens = int(self.config.get("max_tokens", 2048))

        # If agent_name is set, load its config
        if agent_name:
            agent_cfg = self._load_agent_config(agent_name)
            if agent_cfg:
                model = agent_cfg.get("model", model)
                system_prompt = agent_cfg.get("system_prompt", system_prompt)

        if not prompt:
            return {"response": "No prompt provided", "usage": {}}

        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if isinstance(history, list):
            messages.extend(history)
        messages.append({"role": "user", "content": full_prompt})

        try:
            if provider == "ollama":
                return self._call_ollama(messages, model)
            elif provider == "gemini":
                return self._call_gemini(messages, api_key, model, temperature, max_tokens)
            elif provider == "chatgpt":
                return self._call_openai(messages, api_key, model, temperature, max_tokens)
            elif provider == "claude":
                return self._call_claude(messages, api_key, model, temperature, max_tokens)
            elif provider == "grok":
                return self._call_grok(messages, api_key, model, temperature, max_tokens)
            else:
                return {"response": f"Unknown provider: {provider}", "usage": {}}
        except Exception as e:
            return {"response": f"Error: {e}", "usage": {}}

    def _load_agent_config(self, name: str) -> dict:
        try:
            from tubecli.core.agent import agent_manager
            agent = agent_manager.find_by_name(name)
            if agent:
                return agent.to_dict()
        except Exception:
            pass
        return {}

    def _call_ollama(self, messages, model):
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            usage = data.get("eval_count", {})
            return {"response": content, "usage": {"provider": "ollama", "model": model}}
        return {"response": f"Ollama error ({resp.status_code}): {resp.text[:200]}", "usage": {}}

    def _call_openai(self, messages, api_key, model, temperature, max_tokens):
        if not api_key:
            return {"response": "Error: No api_key for ChatGPT", "usage": {}}
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {"response": content, "usage": {**usage, "provider": "chatgpt", "model": model}}
        return {"response": f"OpenAI error ({resp.status_code}): {resp.text[:200]}", "usage": {}}

    def _call_gemini(self, messages, api_key, model, temperature, max_tokens):
        if not api_key:
            return {"response": "Error: No api_key for Gemini", "usage": {}}
        model_name = model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        resp = requests.post(url, json={"contents": contents}, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return {"response": content, "usage": {"provider": "gemini", "model": model_name}}
        return {"response": f"Gemini error ({resp.status_code}): {resp.text[:200]}", "usage": {}}

    def _call_claude(self, messages, api_key, model, temperature, max_tokens):
        if not api_key:
            return {"response": "Error: No api_key for Claude", "usage": {}}
        # Extract system message
        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                chat_messages.append(msg)
        payload = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "messages": chat_messages,
        }
        if system_text:
            payload["system"] = system_text
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
            json=payload,
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", [{}])[0].get("text", "")
            usage = data.get("usage", {})
            return {"response": content, "usage": {**usage, "provider": "claude", "model": model}}
        return {"response": f"Claude error ({resp.status_code}): {resp.text[:200]}", "usage": {}}

    def _call_grok(self, messages, api_key, model, temperature, max_tokens):
        if not api_key:
            return {"response": "Error: No api_key for Grok", "usage": {}}
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "grok-3", "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {"response": content, "usage": {**usage, "provider": "grok", "model": model}}
        return {"response": f"Grok error ({resp.status_code}): {resp.text[:200]}", "usage": {}}
