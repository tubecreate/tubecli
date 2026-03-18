"""Built-in node: Custom — user-defined node with dynamic ports and custom code."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class CustomNode(BaseNode):
    node_type = "custom"
    display_name = "⚙️ Custom Node"
    description = "User-defined node with custom code and dynamic input/output ports."
    icon = "⚙️"
    category = "Custom"

    def _setup_ports(self):
        # Default ports — will be overridden by config
        self.add_input("input", PortType.ANY, "Default input")
        self.add_output("output", PortType.ANY, "Default output")

    def _apply_dynamic_ports(self):
        """Reconfigure ports based on config values."""
        input_ports = self.config.get("input_ports", "")
        output_ports = self.config.get("output_ports", "")

        if input_ports:
            try:
                ports = json.loads(input_ports) if isinstance(input_ports, str) else input_ports
                if isinstance(ports, list) and len(ports) > 0:
                    self.inputs.clear()
                    for p in ports:
                        name = p if isinstance(p, str) else p.get("name", "input")
                        self.add_input(name, PortType.ANY, name)
            except Exception:
                pass

        if output_ports:
            try:
                ports = json.loads(output_ports) if isinstance(output_ports, str) else output_ports
                if isinstance(ports, list) and len(ports) > 0:
                    self.outputs.clear()
                    for p in ports:
                        name = p if isinstance(p, str) else p.get("name", "output")
                        self.add_output(name, PortType.ANY, name)
            except Exception:
                pass

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        self._apply_dynamic_ports()
        code = self.config.get("code", "output = input")

        namespace = {**inputs, "result": None, "output": None}

        try:
            exec(code, {"__builtins__": __builtins__, "json": json}, namespace)

            # Collect outputs
            outputs = {}
            for port in self.outputs:
                outputs[port.name] = namespace.get(port.name, namespace.get("result", ""))

            # Fallback: if no named output found, use 'output' or 'result'
            if not any(v for v in outputs.values()):
                outputs = {self.outputs[0].name: namespace.get("output", namespace.get("result", ""))} if self.outputs else {"output": ""}

            return outputs
        except Exception as e:
            return {port.name: f"Error: {e}" for port in self.outputs}
