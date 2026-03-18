"""
Node Registry — Maps node type strings to node classes.
Used by WorkflowEngine to instantiate nodes from JSON definitions.
"""
from typing import Dict, Type
from tubecli.nodes.base_node import BaseNode
from tubecli.nodes.text_input_node import TextInputNode
from tubecli.nodes.loop_node import LoopNode
from tubecli.nodes.python_code_node import PythonCodeNode
from tubecli.nodes.api_request_node import ApiRequestNode
from tubecli.nodes.run_command_node import RunCommandNode
from tubecli.nodes.ai_node import AiNode
from tubecli.nodes.output_node import OutputNode


NODE_REGISTRY: Dict[str, Type[BaseNode]] = {
    "text_input": TextInputNode,
    "manual_input": TextInputNode,  # Alias
    "loop": LoopNode,
    "python_code": PythonCodeNode,
    "api_request": ApiRequestNode,
    "run_command": RunCommandNode,
    "ai_node": AiNode,
    "ai_summarizer": AiNode,  # Alias
    "output": OutputNode,
}


def create_node_from_dict(node_data: dict) -> BaseNode:
    """Create a node instance from a JSON definition."""
    node_type = node_data.get("type", "")
    node_cls = NODE_REGISTRY.get(node_type)

    if not node_cls:
        raise ValueError(f"Unknown node type: '{node_type}'. Available: {list(NODE_REGISTRY.keys())}")

    node = node_cls.from_dict(node_data)
    return node


def list_available_nodes() -> list:
    """Return list of available node types with descriptions."""
    seen = set()
    result = []
    for key, cls in NODE_REGISTRY.items():
        if cls not in seen:
            seen.add(cls)
            result.append({
                "type": key,
                "name": cls.display_name,
                "description": cls.description,
                "category": cls.category,
            })
    return result
