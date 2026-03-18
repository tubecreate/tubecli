"""Built-in node: Merge — combine data from multiple inputs."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType
import json


class MergeNode(BaseNode):
    node_type = "merge_node"
    display_name = "🔗 Merge"
    description = "Combine data from two inputs using append, combine, or join modes."
    icon = "🔗"
    category = "Logic"

    def _setup_ports(self):
        self.add_input("input_1", PortType.ANY, "First input")
        self.add_input("input_2", PortType.ANY, "Second input")
        self.add_output("merged", PortType.ANY, "Merged result")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        input_1 = inputs.get("input_1", "")
        input_2 = inputs.get("input_2", "")
        mode = self.config.get("mode", "append")
        join_key = self.config.get("join_key", "")

        # Parse strings to JSON if needed
        if isinstance(input_1, str):
            try:
                input_1 = json.loads(input_1)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(input_2, str):
            try:
                input_2 = json.loads(input_2)
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            if mode == "append":
                # Concatenate lists or merge dicts
                if isinstance(input_1, list) and isinstance(input_2, list):
                    merged = input_1 + input_2
                elif isinstance(input_1, dict) and isinstance(input_2, dict):
                    merged = {**input_1, **input_2}
                else:
                    merged = [input_1, input_2]

            elif mode == "combine":
                # Zip items together
                if isinstance(input_1, list) and isinstance(input_2, list):
                    merged = [{**(a if isinstance(a, dict) else {"item1": a}),
                               **(b if isinstance(b, dict) else {"item2": b})}
                              for a, b in zip(input_1, input_2)]
                else:
                    merged = {"input_1": input_1, "input_2": input_2}

            elif mode == "join":
                # SQL-style join on a key
                if isinstance(input_1, list) and isinstance(input_2, list) and join_key:
                    lookup = {}
                    for item in input_2:
                        if isinstance(item, dict) and join_key in item:
                            lookup[str(item[join_key])] = item
                    merged = []
                    for item in input_1:
                        if isinstance(item, dict) and join_key in item:
                            key_val = str(item[join_key])
                            if key_val in lookup:
                                merged.append({**item, **lookup[key_val]})
                            else:
                                merged.append(item)
                        else:
                            merged.append(item)
                else:
                    merged = [input_1, input_2]

            else:
                merged = [input_1, input_2]

            return {"merged": merged}

        except Exception as e:
            return {"merged": f"Error: {e}"}
