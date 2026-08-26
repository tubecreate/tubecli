"""
Node Registry — Maps node type strings to node classes.
Used by WorkflowEngine to instantiate nodes from JSON definitions.
"""
import logging
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Type
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

logger = logging.getLogger("NodeRegistry")


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


# ── Who is allowed to build which node ───────────────────────────────
#
# A node is not a drawing. run_command shells out, python_code/custom call
# exec() on a string, api_request reaches this server's OWN loopback API (which
# skips auth for 127.0.0.1), output writes to any path it is handed, if_node
# eval()s an expression. create_node_from_dict used to take a bare dict from
# whoever happened to hold one - including a workflow the model wrote a second
# earlier, or a tool name the model invented mid-ReAct-loop - so every one of
# those was a single JSON field away from the model.
#
# Callers therefore have to say WHOSE dict this is. `policy` is keyword-only
# and has NO default on purpose: the eighth call site, added next year, fails
# loudly at the call instead of silently inheriting the owner's rights.

# The only node types a model-authored workflow may instantiate. An allowlist,
# not a blocklist, because extensions register node types at runtime (the
# video_editor extension alone adds ffmpeg_command, which runs arbitrary ffmpeg
# arguments) - anything not named here, in today's registry or next month's, is
# refused.
#
# What is deliberately absent, and why:
#   python_code, custom       exec() of source the model wrote
#   run_command               subprocess
#   ffmpeg_command & other    extension nodes that shell out
#   if_node                   eval(condition); `{"__builtins__": {}}` is not a
#                             sandbox, and the condition comes from the model
#   api_request               arbitrary HTTP including loopback - the same door
#                             run_api is (core/telegram_actions.exec_run_api),
#                             and loopback is exempt from auth
#   output, file_manager      write/delete any path as the server user, which
#                             is enough to rewrite data/global_settings.json,
#                             where the technician_mode switch lives
#   browser_action            drives the owner's logged-in browser profiles
#   google_auth/_sheets/      the owner's Google credentials, and outside the
#   google_calendar           group permission gate the gsheet_* actions go
#                             through (core/group_context.py)
#
# What is left is text in, text out: prompting, parsing, routing, searching.
MODEL_SAFE_NODE_TYPES: FrozenSet[str] = frozenset({
    "text_input", "manual_input",
    "ai_node", "ai_summarizer", "model_agent",
    "json_parser",
    "web_search", "browser_search", "search",
    "loop", "switch_node", "merge_node",
})


class NodePolicyError(ValueError):
    """A node type the caller is not allowed to build.

    Subclasses ValueError so the `except Exception -> HTTP 400` already wrapped
    around every call site reports it as a bad request, not a 500.
    """


@dataclass(frozen=True)
class NodePolicy:
    """allow=None means every registered node; otherwise only these types.

    `where` names the call site and only ever reaches the log line - it is what
    turns "a node was refused" into "the ReAct loop asked for run_command".
    """
    allow: Optional[FrozenSet[str]]
    source: str            # "user" (a person acted) | "model" (an LLM did)
    where: str = ""

    @classmethod
    def user(cls, where: str = "") -> "NodePolicy":
        """A person clicked or typed this: the CLI, or an owner session."""
        return cls(None, "user", where)

    @classmethod
    def model(cls, where: str = "") -> "NodePolicy":
        """An LLM produced this workflow, or picked this node."""
        return cls(MODEL_SAFE_NODE_TYPES, "model", where)

    def permits(self, node_type: str) -> bool:
        return self.allow is None or str(node_type or "") in self.allow

    def enforce(self, node_type: str) -> None:
        """Raise NodePolicyError unless this policy allows `node_type`.

        Refusals are logged and raised, never swallowed: a node quietly dropped
        from a generated workflow is how "the AI made me a flow that does
        nothing" happens, and a refusal nobody can see is one nobody can audit.
        """
        if self.permits(node_type):
            return
        logger.warning("Node policy refused '%s' (source=%s, where=%s)",
                       node_type, self.source, self.where or "?")
        raise NodePolicyError(
            f"Node type '{node_type}' is not available to AI-generated workflows. "
            f"Allowed here: {', '.join(sorted(self.allow or ()))}. "
            "Nodes that run commands, code or arbitrary HTTP can only be placed "
            "by a person, on the canvas."
        )


_EXT_NODES_LOADED = False


def ensure_extension_nodes() -> int:
    """Pull extension-contributed nodes into the registry. Idempotent.

    This used to happen once, at the bottom of this module, at import time — and
    whether it worked depended on whether the extension manager had discovered
    anything yet, which depends on which module Python imported first. The
    failure was swallowed by a bare `except Exception: pass`, so nobody ever saw
    it. Measured on this machine: 23 node types at registry import, 30 after
    calling the same registration again once extensions were loaded.

    The seven that went missing were the useful ones — video_download,
    video_processing, subtitle_extract, ffmpeg_command, video_trim, video_effect,
    apply_template — and the damage went further than an incomplete palette:
    build_system_prompt tells the model "For ANY video processing task, ALWAYS
    use the video_processing node" (ai_workflow_builder.py:254). The model obeys,
    the type is not in the registry, and generate_workflow silently rewrites it
    to an empty python_code box (:540). That is the exact "AI made a flow I can't
    use" the owner reported.

    Calling this from the lookup paths instead of at import time removes the
    ordering dependency entirely: by the time anything asks for a node, the
    extensions have had their chance to register.
    """
    global _EXT_NODES_LOADED
    if _EXT_NODES_LOADED:
        return 0
    before = len(NODE_REGISTRY)
    try:
        from tubecli.core.extension_manager import extension_manager
        # get_enabled() reads a dict that discover_extensions() fills; with an
        # empty dict this returns [] and registration is a silent no-op. That was
        # the real failure — not the registration call, the missing discovery.
        if not extension_manager.get_enabled():
            extension_manager.discover_extensions()
        extension_manager.register_extension_nodes(NODE_REGISTRY)
        _EXT_NODES_LOADED = True
    except Exception as e:
        # Still not ready (very early import) — leave the flag down so the next
        # caller retries, but say so rather than failing mute.
        logger.debug("extension nodes not available yet: %s", e)
        return 0
    added = len(NODE_REGISTRY) - before
    if added:
        logger.info("Registered %d node type(s) from extensions", added)
    return added


def create_node_from_dict(node_data: dict, *, policy: NodePolicy) -> BaseNode:
    """Create a node instance from a JSON definition.

    `policy` is keyword-only and mandatory - see NodePolicy above. Pass
    NodePolicy.user(...) only where a PERSON chose the node.
    """
    node_type = node_data.get("type", "")
    # Checked before the registry lookup, so a refused type never reaches
    # from_dict() and an unknown type cannot be told apart from a denied one.
    policy.enforce(node_type)
    node_cls = NODE_REGISTRY.get(node_type)
    if not node_cls:
        ensure_extension_nodes()
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
    ensure_extension_nodes()
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
    ensure_extension_nodes()
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


def get_node_tool_schemas(policy: NodePolicy) -> list:
    """Available nodes as OpenAI/Anthropic Tool JSON schemas, filtered by policy.

    Same policy object as create_node_from_dict, and for the same reason:
    teaching a model about a tool it is not allowed to call is an invitation
    to try it. The refusal at build time is the wall; this keeps the model
    from walking into it, and from burning a ReAct step on it.
    """
    ensure_extension_nodes()
    seen = set()
    tools = []
    
    for key, cls in NODE_REGISTRY.items():
        # Filtered BEFORE the dedup-by-class below: `seen` keeps the first key
        # that maps to a class, so filtering afterwards could drop an allowed
        # alias just because a refused one came earlier in the dict.
        if not policy.permits(key):
            continue
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


# ── Try once at import, then let the lookup paths retry ─────────────
#
# Kept as an optimisation, no longer the only chance. When extensions are not
# discovered yet this quietly does nothing and _EXT_NODES_LOADED stays False, so
# the next call to create_node_from_dict / list_available_nodes / build_port_defs
# / get_node_tool_schemas tries again. Previously this was the ONLY attempt, and
# losing the race meant the extension nodes were absent for the whole process
# life — with no log line saying so.
ensure_extension_nodes()
