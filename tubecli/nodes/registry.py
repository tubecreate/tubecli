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
from tubecli.nodes.google_auth_node import GoogleAuthNode
from tubecli.nodes.google_sheets_node import GoogleSheetsNode
from tubecli.nodes.google_calendar_node import GoogleCalendarNode
from tubecli.nodes.browser_node import BrowserNode
from tubecli.nodes.json_parser_node import JsonParserNode
from tubecli.nodes.web_search_node import WebSearchNode
from tubecli.nodes.model_agent_node import ModelAgentNode
from tubecli.nodes.custom_node import CustomNode
from tubecli.nodes.if_node import IfNode
from tubecli.nodes.switch_node import SwitchNode
from tubecli.nodes.merge_node import MergeNode
from tubecli.nodes.file_manager_node import FileManagerNode


NODE_REGISTRY: Dict[str, Type[BaseNode]] = {
    # Original nodes
    "text_input": TextInputNode,
    "manual_input": TextInputNode,  # Alias
    "loop": LoopNode,
    "python_code": PythonCodeNode,
    "api_request": ApiRequestNode,
    "run_command": RunCommandNode,
    "ai_node": AiNode,
    "ai_summarizer": AiNode,  # Alias
    "output": OutputNode,
    # New nodes
    "google_auth": GoogleAuthNode,
    "google_sheets": GoogleSheetsNode,
    "google_calendar": GoogleCalendarNode,
    "browser_action": BrowserNode,
    "json_parser": JsonParserNode,
    "web_search": WebSearchNode,
    "model_agent": ModelAgentNode,
    "custom": CustomNode,
    "if_node": IfNode,
    "switch_node": SwitchNode,
    "merge_node": MergeNode,
    "file_manager": FileManagerNode,
    # LLM-generated aliases
    "browser_search": WebSearchNode,  # LLMs often hallucinate this name
    "search": WebSearchNode,          # Short alias
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
    """Return list of available node types with descriptions.

    Each entry includes full port metadata (name/type/description/required)
    as `input_ports` / `output_ports`, plus the node's `config_schema`, so
    LLM prompt builders can teach the model exactly how to use each node.
    `inputs` / `outputs` remain simple name lists for backward compatibility.
    """
    seen = set()
    result = []
    icons = {
        "text_input": "📝", "loop": "🔄", "python_code": "🐍",
        "api_request": "🌐", "run_command": "💻", "ai_node": "🧠", "output": "📤",
        "google_auth": "🔐", "google_sheets": "📊", "google_calendar": "📅",
        "browser_action": "🌐",
        "json_parser": "📋", "model_agent": "🤖", "custom": "⚙️",
        "if_node": "🔀", "switch_node": "🔃", "merge_node": "🔗",
    }
    for key, cls in NODE_REGISTRY.items():
        if cls not in seen:
            seen.add(cls)
            input_ports, output_ports = [], []
            try:
                inst = cls.__new__(cls)
                inst.__init__()
                input_ports = [
                    {"name": p.name, "type": p.port_type.value,
                     "description": p.description, "required": p.required}
                    for p in inst.inputs
                ]
                output_ports = [
                    {"name": p.name, "type": p.port_type.value, "description": p.description}
                    for p in inst.outputs
                ]
            except Exception:
                pass
            result.append({
                "type": key,
                "name": cls.display_name,
                "icon": icons.get(key, "📦"),
                "description": cls.description,
                "category": cls.category,
                "inputs": [p["name"] for p in input_ports],
                "outputs": [p["name"] for p in output_ports],
                "input_ports": input_ports,
                "output_ports": output_ports,
                "config_schema": getattr(cls, "config_schema", {}) or {},
            })
    return result


def build_port_defs() -> dict:
    """Build {node_type: {inputs: [...], outputs: [...]}} from the live
    registry (covers extension-registered nodes too — no hand-maintained map)."""
    defs = {}
    for key, cls in NODE_REGISTRY.items():
        try:
            inst = cls.__new__(cls)
            inst.__init__()
            defs[key] = {
                "inputs": [p.name for p in inst.inputs],
                "outputs": [p.name for p in inst.outputs],
            }
        except Exception:
            defs[key] = {"inputs": [], "outputs": []}
    return defs


def get_node_tool_schemas() -> list:
    """Return list of available nodes formatted as OpenAI/Anthropic Tool JSON schemas."""
    seen = set()
    tools = []
    
    for key, cls in NODE_REGISTRY.items():
        if cls not in seen:
            seen.add(cls)
            try:
                inst = cls.__new__(cls)
                inst.__init__()
                input_ports = inst.inputs
            except Exception:
                input_ports = []
                
            # Build config property from the node's declared config_schema
            config_schema = getattr(cls, "config_schema", {}) or {}
            config_properties = {}
            config_required = []
            for ckey, cdef in config_schema.items():
                prop = {
                    "type": cdef.get("type", "string"),
                    "description": cdef.get("description", ""),
                }
                if "options" in cdef:
                    prop["enum"] = cdef["options"]
                if "default" in cdef:
                    prop["description"] += f" (default: {cdef['default']})"
                config_properties[ckey] = prop
                if cdef.get("required"):
                    config_required.append(ckey)

            config_prop = {
                "type": "object",
                "description": "Node settings/configurations",
                "additionalProperties": True,
            }
            if config_properties:
                config_prop["properties"] = config_properties
                if config_required:
                    config_prop["required"] = config_required

            properties = {"config": config_prop}

            for port in input_ports:
                properties[port.name] = {
                    "type": "string" if port.port_type.value == "text" else "object",
                    "description": port.description or f"Input for {port.name}"
                }
                
            tools.append({
                "type": "function",
                "function": {
                    "name": key,
                    "description": cls.description or f"Executes the {cls.display_name} node",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": [p.name for p in input_ports if p.required]
                    }
                }
            })
            
    # Add a built-in termination tool
    tools.append({
        "type": "function",
        "function": {
            "name": "finish_workflow",
            "description": "Call this tool when you have completed all tasks and want to return the final answer to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "final_answer": {
                        "type": "string",
                        "description": "The final human-readable response summarizing what was done."
                    }
                },
                "required": ["final_answer"]
            }
        }
    })
    
    return tools


def register_external_nodes(nodes_dict: dict):
    """Register additional nodes from extensions into the global NODE_REGISTRY."""
    for node_type, node_cls in nodes_dict.items():
        if node_type not in NODE_REGISTRY:
            NODE_REGISTRY[node_type] = node_cls


# ── Auto-register extension nodes at import time ────────────────────
try:
    from tubecli.core.extension_manager import extension_manager
    extension_manager.register_extension_nodes(NODE_REGISTRY)
except Exception:
    pass  # Graceful fallback if extensions haven't been discovered yet
