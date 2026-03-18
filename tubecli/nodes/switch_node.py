"""Built-in node: Switch — multi-way routing based on field value."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class SwitchNode(BaseNode):
    node_type = "switch_node"
    display_name = "🔃 Switch"
    description = "Route data to different outputs based on a field value."
    icon = "🔃"
    category = "Logic"

    def _setup_ports(self):
        self.add_input("data", PortType.ANY, "Input data")
        self.add_output("output_0", PortType.ANY, "Route 0 (default/fallback)")
        self.add_output("output_1", PortType.ANY, "Route 1")
        self.add_output("output_2", PortType.ANY, "Route 2")
        self.add_output("output_3", PortType.ANY, "Route 3")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        data = inputs.get("data", "")
        field = self.config.get("field", "")
        rules_str = self.config.get("rules", "[]")

        # Parse rules: [{"value": "...", "output": 0}, ...]
        try:
            rules = json.loads(rules_str) if isinstance(rules_str, str) else rules_str
        except json.JSONDecodeError:
            rules = []

        # Get the value to match
        if field and isinstance(data, dict):
            match_value = str(data.get(field, ""))
        else:
            match_value = str(data)

        # Initialize all outputs as None
        result = {"output_0": None, "output_1": None, "output_2": None, "output_3": None}

        # Find matching rule
        matched = False
        for rule in rules:
            if isinstance(rule, dict):
                if str(rule.get("value", "")) == match_value:
                    out_idx = int(rule.get("output", 0))
                    key = f"output_{out_idx}"
                    if key in result:
                        result[key] = data
                        matched = True
                        break

        # Fallback to output_0 if no match
        if not matched:
            result["output_0"] = data

        return result
