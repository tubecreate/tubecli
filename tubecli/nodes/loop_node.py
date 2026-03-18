"""Built-in node: Loop — iterates over items."""
from typing import Dict, Any, List
from tubecli.nodes.base_node import BaseNode, PortType


class LoopNode(BaseNode):
    node_type = "loop"
    display_name = "🔄 Loop"
    description = "Iterate over a list of items."
    category = "Control"

    def _setup_ports(self):
        self.add_input("items", PortType.ANY, "Items to iterate over")
        self.add_output("current_item", PortType.TEXT, "Current item")
        self.add_output("index", PortType.TEXT, "Current index")
        self.add_output("total", PortType.TEXT, "Total items")

    def get_all_items(self, inputs: Dict[str, Any]) -> List:
        """Extract items from inputs, supporting string splitting."""
        items = inputs.get("items", [])
        if isinstance(items, str):
            # Split by newline for multi-line text
            items = [l.strip() for l in items.strip().split("\n") if l.strip()]
        return items if isinstance(items, list) else [items]

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        # Loop logic is handled by WorkflowEngine
        items = self.get_all_items(inputs)
        return {"current_item": "", "index": "0", "total": str(len(items))}
