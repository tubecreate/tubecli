"""Built-in node: Python Code — executes arbitrary Python code."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json as _json
import re as _re
import os as _os


class PythonCodeNode(BaseNode):
    node_type = "python_code"
    display_name = "🐍 Python Code"
    description = "Execute Python code. Access inputs via variables."
    category = "Logic"
    config_schema = {
        "code": {"type": "string", "required": True, "description": "Python code to run. Read `input_data` (auto), `text_input`, `json_input`. Pre-imported: json, re, os. Assign the final value to `result`."},
    }

    def _setup_ports(self):
        self.add_input("text_input", PortType.TEXT, "Text input", required=False)
        self.add_input("json_input", PortType.JSON, "JSON input", required=False)
        self.add_output("result", PortType.ANY, "Execution result")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        code = self.config.get("code", "result = 'No code provided'")

        text_in = inputs.get("text_input", "")
        json_in = inputs.get("json_input", "")

        # input_data = convenience alias (text_input or json_input, whichever is provided)
        input_data = text_in if text_in else json_in

        # Build execution namespace with common modules pre-imported
        namespace = {
            "text_input": text_in,
            "json_input": json_in,
            "input_data": input_data,
            "result": None,
            # Common modules
            "json": _json,
            "re": _re,
            "os": _os,
        }

        try:
            exec(code, {"__builtins__": __builtins__}, namespace)
            result = namespace.get("result", "")
            return {"result": result}
        except Exception as e:
            return {"result": f"Error: {e}"}

