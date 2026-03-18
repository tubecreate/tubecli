"""Built-in node: AI Node — calls AI for inference (Ollama or Cloud)."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
from tubecli.config import OLLAMA_BASE_URL, DEFAULT_AI_MODEL
import requests
import json


class AiNode(BaseNode):
    node_type = "ai_node"
    display_name = "🧠 AI Inference"
    description = "Send prompt to AI model (Ollama or Cloud API)."
    category = "AI"

    def _setup_ports(self):
        self.add_input("prompt", PortType.TEXT, "Input prompt")
        self.add_input("context", PortType.TEXT, "Additional context", required=False)
        self.add_output("response", PortType.TEXT, "AI response")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        prompt = inputs.get("prompt", "")
        context_text = inputs.get("context", "")
        model = self.config.get("model", DEFAULT_AI_MODEL)
        system_prompt = self.config.get("system_prompt", "You are a helpful assistant.")

        if not prompt:
            return {"response": "No prompt provided"}

        full_prompt = f"{context_text}\n\n{prompt}" if context_text else prompt

        try:
            url = f"{OLLAMA_BASE_URL}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt},
                ],
                "stream": False,
            }

            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return {"response": content}
            else:
                return {"response": f"AI Error ({resp.status_code}): {resp.text[:200]}"}

        except requests.exceptions.ConnectionError:
            return {"response": "Error: Cannot connect to Ollama. Is it running? (ollama serve)"}
        except Exception as e:
            return {"response": f"Error: {e}"}
