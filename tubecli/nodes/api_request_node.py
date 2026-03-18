"""Built-in node: API Request — makes HTTP requests."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import requests
import json


class ApiRequestNode(BaseNode):
    node_type = "api_request"
    display_name = "🌐 API Request"
    description = "Make HTTP requests to external APIs."
    category = "Network"

    def _setup_ports(self):
        self.add_input("url", PortType.TEXT, "Request URL", required=False)
        self.add_input("body", PortType.JSON, "Request body (JSON)", required=False)
        self.add_output("response", PortType.JSON, "Response data")
        self.add_output("status_code", PortType.TEXT, "HTTP status code")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        url = inputs.get("url") or self.config.get("url", "")
        method = self.config.get("method", "GET").upper()
        headers = self.config.get("headers", {})
        body = inputs.get("body") or self.config.get("body")
        timeout = self.config.get("timeout", 30)

        if not url:
            return {"response": {"error": "No URL provided"}, "status_code": "0"}

        try:
            if isinstance(body, str):
                body = json.loads(body)

            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=timeout)
            elif method == "POST":
                resp = requests.post(url, json=body, headers=headers, timeout=timeout)
            elif method == "PUT":
                resp = requests.put(url, json=body, headers=headers, timeout=timeout)
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers, timeout=timeout)
            else:
                return {"response": {"error": f"Unsupported method: {method}"}, "status_code": "0"}

            try:
                data = resp.json()
            except Exception:
                data = {"text": resp.text}

            return {"response": data, "status_code": str(resp.status_code)}

        except Exception as e:
            return {"response": {"error": str(e)}, "status_code": "0"}
