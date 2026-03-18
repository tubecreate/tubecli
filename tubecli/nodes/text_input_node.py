"""Built-in node: Text Input — provides static text."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class TextInputNode(BaseNode):
    node_type = "text_input"
    display_name = "📝 Text Input"
    description = "Provides static text content."
    category = "Input"

    def _setup_ports(self):
        self.add_output("content", PortType.TEXT, "Text content")
        self.add_output("lines", PortType.TEXT, "Text as line list")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        text = self.config.get("text", "")
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        return {"content": text, "lines": lines}
