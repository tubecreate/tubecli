"""
Workflow Engine — DAG-based workflow executor.
Handles topological sort, node execution, data passing, and loop iteration.
Ported from python-video-studio/ui/workflow/workflow_engine.py
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExecutionLog:
    """Log entry for workflow execution."""
    timestamp: str
    node_id: str
    node_name: str
    status: str  # "started", "completed", "error", "skipped"
    message: str
    data: Optional[Dict] = None


class WorkflowEngine:
    """
    Engine for executing workflow graphs.

    Features:
    - Topological sort for execution order (Kahn's algorithm)
    - Loop node handling for batch processing
    - Data passing between connected nodes via ports
    - Progress callbacks
    - Execution logs
    """

    def __init__(
        self,
        nodes: list,
        connections: List[Dict],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_log: Optional[Callable[[ExecutionLog], None]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.nodes = {n.id: n for n in nodes}
        self.connections = connections
        self.on_progress = on_progress
        self.on_log = on_log
        self.context = context or {}

        self._running = False
        self._cancelled = False
        self.logs: List[ExecutionLog] = []
        self.node_outputs: Dict[str, Dict] = {}

    def _log(self, node_id: str, node_name: str, status: str, message: str, data: Optional[Dict] = None):
        log = ExecutionLog(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            node_id=node_id,
            node_name=node_name,
            status=status,
            message=message,
            data=data,
        )
        self.logs.append(log)
        if self.on_log:
            self.on_log(log)

    def _get_execution_order(self) -> List[str]:
        """Topological sort using Kahn's algorithm."""
        in_degree = {nid: 0 for nid in self.nodes}
        graph = {nid: [] for nid in self.nodes}

        for conn in self.connections:
            from_node = conn.get("from_node_id")
            to_node = conn.get("to_node_id")
            if from_node in graph and to_node in in_degree:
                graph[from_node].append(to_node)
                in_degree[to_node] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for neighbor in graph.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def _get_node_inputs(self, node_id: str) -> Dict[str, Any]:
        """Get input values for a node from connected outputs."""
        inputs = {}
        node = self.nodes.get(node_id)
        if not node:
            return inputs

        for port in node.inputs:
            for conn in self.connections:
                if conn.get("to_port_id") == port.id or conn.get("to_port_id") == port.name:
                    from_node_id = conn.get("from_node_id")
                    from_port_id = conn.get("from_port_id")

                    if from_node_id in self.node_outputs:
                        from_node = self.nodes.get(from_node_id)
                        if from_node:
                            for out_port in from_node.outputs:
                                if out_port.id == from_port_id or out_port.name == from_port_id:
                                    output_data = self.node_outputs[from_node_id]
                                    inputs[port.name] = output_data.get(out_port.name)
                                    break
                    break

        return inputs

    def _is_loop_node(self, node_id: str) -> bool:
        node = self.nodes.get(node_id)
        return node and node.node_type == "loop"

    # Sentinels nodes return when they were never configured. These are the
    # commonest outcome of an AI-generated flow — the model produced the right
    # boxes and left the fields empty — and they used to be logged as "completed"
    # because they do not start with "Error:". A run of empty boxes then reported
    # success, which is indistinguishable to a beginner from a run that worked.
    _UNCONFIGURED_MARKERS = (
        "no code provided", "no command provided", "no url provided",
        "no prompt provided", "no query provided", "no file provided",
        "no search query provided", "no input provided", "no data provided",
        "no results", "not configured", "unknown action", "unknown provider",
    )

    @staticmethod
    def _name(node) -> str:
        """What to call a node in the log.

        display_name is the CLASS name, so four Python Code boxes all logged as
        "🐍 Python Code" and there was no way to tell which one failed. The label
        the user typed on the canvas is what they are looking at.
        """
        return (getattr(node, "label", "") or "").strip() or node.display_name

    @staticmethod
    def _detect_output_error(result: Any) -> Optional[str]:
        """Most nodes swallow exceptions and return 'Error: ...' strings in
        their outputs instead of raising. Detect that pattern so failures show
        up in logs/errors instead of the run looking fully successful."""
        if not isinstance(result, dict):
            return None
        for key, value in result.items():
            # A nested {"error": ...} is the other shape nodes use.
            if isinstance(value, dict) and value.get("error"):
                return f"{key}: {str(value['error'])[:300]}"
            if isinstance(value, str):
                v = value.strip()
                if v.startswith("Error:") or v.startswith("❌"):
                    return f"{key}: {v[:300]}"
                low = v.lstrip("⚠️ ").lower()
                if any(low.startswith(m) for m in WorkflowEngine._UNCONFIGURED_MARKERS):
                    return f"{key}: {v[:300]}"
        return None

    def _get_downstream_nodes(self, node_id: str) -> List[str]:
        """Get all nodes downstream of a given node, in topological order."""
        downstream_set = set()

        def collect(nid):
            for conn in self.connections:
                if conn.get("from_node_id") == nid:
                    to_node = conn.get("to_node_id")
                    if to_node and to_node not in downstream_set:
                        downstream_set.add(to_node)
                        collect(to_node)

        collect(node_id)
        full_order = self._get_execution_order()
        return [nid for nid in full_order if nid in downstream_set]

    async def run(self) -> Dict[str, Any]:
        """Execute the workflow."""
        self._running = True
        self._cancelled = False
        self.logs.clear()
        self.node_outputs.clear()

        execution_order = self._get_execution_order()
        total = len(execution_order)
        step = 0

        self._log("engine", "Workflow Engine", "started", f"Starting workflow with {total} nodes")

        # Nodes trapped in a cycle never appear in the topological order and
        # would be skipped silently — surface that clearly instead.
        if total < len(self.nodes):
            missing = [nid for nid in self.nodes if nid not in execution_order]
            self._log(
                "engine", "Workflow Engine", "error",
                f"Cycle detected: nodes {missing} form a loop in connections and will NOT run. "
                "Workflows must be a DAG — use the 'loop' node for iteration instead of circular connections.",
            )

        try:
            i = 0
            while i < len(execution_order):
                if self._cancelled:
                    self._log("engine", "Workflow Engine", "cancelled", "Cancelled by user")
                    break

                node_id = execution_order[i]
                node = self.nodes.get(node_id)
                if not node:
                    i += 1
                    continue

                step += 1
                if self.on_progress:
                    self.on_progress(step, total, f"Executing: {self._name(node)}")

                inputs = self._get_node_inputs(node_id)

                # Handle Loop node
                if self._is_loop_node(node_id):
                    items = inputs.get("items", [])
                    if isinstance(items, str):
                        items = items.strip().split("\n")

                    if isinstance(items, list) and len(items) > 0:
                        downstream = self._get_downstream_nodes(node_id)
                        self._log(node_id, self._name(node), "started", f"Looping {len(items)} items")

                        for idx, item in enumerate(items):
                            if self._cancelled:
                                break

                            import json as _json
                            current_str = _json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                            self.node_outputs[node_id] = {
                                "current_item": current_str,
                                "index": str(idx),
                                "total": str(len(items)),
                            }

                            for ds_id in downstream:
                                if self._cancelled:
                                    break
                                ds_node = self.nodes.get(ds_id)
                                if ds_node:
                                    ds_inputs = self._get_node_inputs(ds_id)
                                    # Auto-inject loop context into downstream inputs
                                    # so nodes always get current_item even if connections are imperfect
                                    if "current_item" not in ds_inputs:
                                        ds_inputs["current_item"] = current_str
                                    # Also inject as common port names for broad compatibility
                                    for key in ("input_file", "input", "text_input", "data", "trigger"):
                                        if key not in ds_inputs:
                                            ds_inputs[key] = current_str
                                    ds_inputs["_loop_index"] = str(idx)
                                    ds_inputs["_loop_total"] = str(len(items))
                                    try:
                                        result = await ds_node.execute(ds_inputs, context=self.context)
                                        self.node_outputs[ds_id] = result
                                        err = self._detect_output_error(result)
                                        if err:
                                            self._log(ds_id, self._name(ds_node), "error", err)
                                        else:
                                            self._log(ds_id, self._name(ds_node), "completed", str(result)[:500])
                                    except Exception as ex:
                                        self._log(ds_id, self._name(ds_node), "error", str(ex))

                            delay_ms = node.config.get("delay_ms", 500)
                            await asyncio.sleep(delay_ms / 1000)

                        self._log(node_id, self._name(node), "completed", f"Loop done: {len(items)} items")
                        i += 1
                        while i < len(execution_order) and execution_order[i] in downstream:
                            i += 1
                        continue
                    else:
                        self._log(node_id, self._name(node), "skipped", "No items to loop")
                else:
                    # Regular node
                    self._log(node_id, self._name(node), "started", "Executing")
                    try:
                        result = await node.execute(inputs, context=self.context)
                        self.node_outputs[node_id] = result
                        err = self._detect_output_error(result)
                        if err:
                            self._log(node_id, self._name(node), "error", err)
                        else:
                            self._log(node_id, self._name(node), "completed", str(result)[:500])
                    except Exception as ex:
                        self._log(node_id, self._name(node), "error", str(ex))

                i += 1

            self._log("engine", "Workflow Engine", "completed", "Workflow finished")

        except Exception as ex:
            self._log("engine", "Workflow Engine", "error", f"Workflow failed: {ex}")

        finally:
            self._running = False

        # Summarize node errors so callers (and AI agents) see failures at a
        # glance instead of digging through logs of a "completed" run.
        node_errors = [
            {"node_id": l.node_id, "node_name": l.node_name, "message": l.message}
            for l in self.logs if l.status == "error"
        ]

        return {
            "status": "completed" if not self._cancelled else "cancelled",
            "has_errors": bool(node_errors),
            "errors": node_errors,
            "logs": [{"timestamp": l.timestamp, "node_id": l.node_id, "node_name": l.node_name,
                       "status": l.status, "message": l.message} for l in self.logs],
            "outputs": {k: v for k, v in self.node_outputs.items()},
        }

    def cancel(self):
        self._cancelled = True

    @property
    def is_running(self) -> bool:
        return self._running
