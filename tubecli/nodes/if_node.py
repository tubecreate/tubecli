"""Built-in node: IF — conditional branching based on a condition."""
from typing import Dict, Any
from tubecli.nodes.base_node import BaseNode, PortType


class IfNode(BaseNode):
    node_type = "if_node"
    display_name = "🔀 IF Condition"
    description = "Route data based on a condition. True → output 1, False → output 2."
    icon = "🔀"
    category = "Logic"

    def _setup_ports(self):
        self.add_input("data", PortType.ANY, "Input data to evaluate")
        self.add_output("true_output", PortType.ANY, "Output when condition is true")
        self.add_output("false_output", PortType.ANY, "Output when condition is false")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        data = inputs.get("data", "")
        condition_expr = self.config.get("condition", "")
        value1 = self.config.get("value1", "")
        operator = self.config.get("operator", "equals")
        value2 = self.config.get("value2", "")

        try:
            if condition_expr:
                # Evaluate Python expression
                result = bool(eval(condition_expr, {"__builtins__": {}}, {"data": data, "str": str, "int": int, "float": float, "len": len, "bool": bool}))
            else:
                # Use value1 / operator / value2
                v1 = str(value1 or data)
                v2 = str(value2)
                result = self._evaluate(v1, operator, v2)

            if result:
                return {"true_output": data, "false_output": None}
            else:
                return {"true_output": None, "false_output": data}

        except Exception as e:
            return {"true_output": None, "false_output": f"Error: {e}"}

    def _evaluate(self, v1: str, op: str, v2: str) -> bool:
        if op == "equals":
            return v1 == v2
        elif op == "not_equals":
            return v1 != v2
        elif op == "contains":
            return v2 in v1
        elif op == "not_contains":
            return v2 not in v1
        elif op == "starts_with":
            return v1.startswith(v2)
        elif op == "ends_with":
            return v1.endswith(v2)
        elif op == "greater_than":
            try:
                return float(v1) > float(v2)
            except ValueError:
                return v1 > v2
        elif op == "less_than":
            try:
                return float(v1) < float(v2)
            except ValueError:
                return v1 < v2
        elif op == "is_empty":
            return not v1 or v1.strip() == ""
        elif op == "is_not_empty":
            return bool(v1 and v1.strip())
        elif op == "regex":
            import re
            return bool(re.search(v2, v1))
        else:
            return v1 == v2
