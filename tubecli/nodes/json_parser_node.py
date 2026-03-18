"""Built-in node: JSON Parser — parse, extract, merge, and transform JSON data."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class JsonParserNode(BaseNode):
    node_type = "json_parser"
    display_name = "📋 JSON Parser"
    description = "Parse, extract, merge, filter, or stringify JSON data."
    icon = "📋"
    category = "Data"

    def _setup_ports(self):
        self.add_input("data", PortType.ANY, "Input data (text or JSON)")
        self.add_input("expression", PortType.TEXT, "Path expression override", required=False)
        self.add_output("result", PortType.ANY, "Processed result")
        self.add_output("keys", PortType.JSON, "Top-level keys (if object)")
        self.add_output("count", PortType.TEXT, "Item count")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        action = self.config.get("action", "parse")
        data = inputs.get("data", "")
        expression = inputs.get("expression") or self.config.get("expression", "")

        try:
            # Parse string to JSON if needed
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    if action == "parse":
                        return {"result": data, "keys": [], "count": "1"}

            if action == "parse":
                keys = list(data.keys()) if isinstance(data, dict) else []
                count = len(data) if isinstance(data, (list, dict)) else 1
                return {"result": data, "keys": keys, "count": str(count)}

            elif action == "stringify":
                result = json.dumps(data, indent=2, ensure_ascii=False)
                return {"result": result, "keys": [], "count": str(len(result))}

            elif action == "extract":
                result = self._extract(data, expression)
                keys = list(result.keys()) if isinstance(result, dict) else []
                count = len(result) if isinstance(result, (list, dict)) else 1
                return {"result": result, "keys": keys, "count": str(count)}

            elif action == "filter":
                if isinstance(data, list) and expression:
                    # Filter list items where expression key exists and is truthy
                    key = expression.strip()
                    result = [item for item in data if isinstance(item, dict) and item.get(key)]
                    return {"result": result, "keys": [], "count": str(len(result))}
                return {"result": data, "keys": [], "count": str(len(data) if isinstance(data, list) else 1)}

            elif action == "merge":
                data2_str = self.config.get("data2", "")
                data2 = json.loads(data2_str) if isinstance(data2_str, str) and data2_str else {}
                if isinstance(data, dict) and isinstance(data2, dict):
                    merged = {**data, **data2}
                elif isinstance(data, list) and isinstance(data2, list):
                    merged = data + data2
                else:
                    merged = [data, data2]
                return {"result": merged, "keys": list(merged.keys()) if isinstance(merged, dict) else [], "count": str(len(merged))}

            elif action == "transform":
                # Apply a simple key mapping
                mapping_str = self.config.get("mapping", "{}")
                mapping = json.loads(mapping_str) if isinstance(mapping_str, str) else mapping_str
                if isinstance(data, dict) and isinstance(mapping, dict):
                    result = {mapping.get(k, k): v for k, v in data.items()}
                    return {"result": result, "keys": list(result.keys()), "count": str(len(result))}
                return {"result": data, "keys": [], "count": "1"}

            else:
                return {"result": data, "keys": [], "count": "0"}

        except Exception as e:
            return {"result": f"Error: {e}", "keys": [], "count": "0"}

    def _extract(self, data: Any, path: str) -> Any:
        """Extract value using dot-notation path (e.g. 'data.items[0].name')."""
        if not path:
            return data
        parts = path.replace("[", ".[").split(".")
        current = data
        for part in parts:
            if not part:
                continue
            if part.startswith("[") and part.endswith("]"):
                idx = int(part[1:-1])
                if isinstance(current, (list, tuple)) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current
