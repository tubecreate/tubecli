"""Built-in node: Python Code — executes arbitrary Python code."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class PythonCodeNode(BaseNode):
    node_type = "python_code"
    display_name = "🐍 Python Code"
    description = "Execute Python code. Access inputs via variables."
    category = "Logic"

    def _setup_ports(self):
        self.add_input("text_input", PortType.TEXT, "Text input", required=False)
        self.add_input("json_input", PortType.JSON, "JSON input", required=False)
        self.add_output("result", PortType.ANY, "Execution result")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        code = self.config.get("code", "result = 'No code provided'")

        # Build execution namespace
        namespace = {
            "text_input": inputs.get("text_input", ""),
            "json_input": inputs.get("json_input", ""),
            "result": None,
        }

        try:
            exec(code, {"__builtins__": __builtins__}, namespace)
            result = namespace.get("result", "")
            return {"result": result}
        except Exception as e:
            return {"result": f"Error: {e}"}
