"""
Base Node — Foundation for all workflow nodes.
Ported from python-video-studio without UI fields.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import uuid


class PortType(Enum):
    TEXT = "text"
    JSON = "json"
    FILE = "file"
    ANY = "any"


@dataclass
class Port:
    """Input or output port on a node."""
    name: str
    port_type: PortType
    is_input: bool
    description: str = ""
    required: bool = True
    connected_to: Optional[str] = None

    def __post_init__(self):
        self.id = f"port_{uuid.uuid4().hex[:8]}"


@dataclass
class NodeConfig:
    """Configuration values for a node."""
    values: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if not isinstance(self.values, dict):
            return default
        return self.values.get(key, default)

    def set(self, key: str, value: Any):
        self.values[key] = value


class BaseNode:
    """Base class for all workflow nodes."""

    node_type: str = "base"
    display_name: str = "Base Node"
    description: str = ""
    icon: str = "⚙️"
    category: str = "General"

    def __init__(self):
        self.id = f"node_{uuid.uuid4().hex[:8]}"
        self.label = ""
        self.inputs: List[Port] = []
        self.outputs: List[Port] = []
        self.config = NodeConfig()
        self._setup_ports()

    def _setup_ports(self):
        """Override to add input/output ports."""
        pass

    def add_input(self, name: str, port_type: PortType, description: str = "", required: bool = True) -> Port:
        port = Port(name=name, port_type=port_type, is_input=True, description=description, required=required)
        self.inputs.append(port)
        return port

    def add_output(self, name: str, port_type: PortType, description: str = "") -> Port:
        port = Port(name=name, port_type=port_type, is_input=False, description=description)
        self.outputs.append(port)
        return port

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        raise NotImplementedError(f"execute() not implemented for {self.node_type}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.node_type,
            "label": self.label,
            "config": self.config.values,
            "inputs": [{"id": p.id, "name": p.name} for p in self.inputs],
            "outputs": [{"id": p.id, "name": p.name} for p in self.outputs],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseNode":
        node = cls()
        node.id = data.get("id", node.id)
        node.label = data.get("label", "")
        node.config.values = data.get("config", {})

        # Restore port IDs
        for saved in data.get("inputs", []):
            for port in node.inputs:
                if port.name == saved.get("name"):
                    port.id = saved.get("id", port.id)
                    break

        for saved in data.get("outputs", []):
            for port in node.outputs:
                if port.name == saved.get("name"):
                    port.id = saved.get("id", port.id)
                    break

        return node
