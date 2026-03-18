"""Built-in node: Output — saves or displays final results."""
import json
import os
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
from tubecli.config import DATA_DIR


class OutputNode(BaseNode):
    node_type = "output"
    display_name = "📤 Output"
    description = "Save or display workflow results."
    category = "Output"

    def _setup_ports(self):
        self.add_input("data", PortType.ANY, "Data to output")
        self.add_output("file_path", PortType.FILE, "Saved file path")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        data = inputs.get("data", "")
        output_file = self.config.get("output_file", "")
        print_output = self.config.get("print", True)

        # Convert to string
        if isinstance(data, (dict, list)):
            text = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            text = str(data)

        if print_output:
            print(f"\n{'='*50}")
            print(f"📤 OUTPUT:")
            print(f"{'='*50}")
            print(text)
            print(f"{'='*50}\n")

        # Save to file if configured
        file_path = ""
        if output_file:
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)
            file_path = output_file
            print(f"💾 Saved to: {file_path}")

        return {"file_path": file_path}
