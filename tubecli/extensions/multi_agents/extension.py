"""
Multi-Agents Extension — Multi-agent orchestration and collaboration.
Enables agent teams, task delegation, and coordinated multi-agent workflows.
"""
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
from tubecli.core.extension_manager import Extension
from tubecli.config import DATA_DIR
import os

logger = logging.getLogger("MultiAgentsExtension")

TEAMS_FILE = os.path.join(DATA_DIR, "agent_teams.json")


class TeamNode:
    """A single node in the team hierarchy tree. Links a role to an agent."""

    def __init__(
        self,
        role_id: str,
        role: str = "",
        emoji: str = "🤖",
        description: str = "",
        system_hint: str = "",
        agent_id: str = "",
        children: List[str] = None,
        parent: str = None,
        layer: int = 0,
    ):
        self.role_id = role_id
        self.role = role
        self.emoji = emoji
        self.description = description
        self.system_hint = system_hint
        self.agent_id = agent_id  # Linked individual agent ID
        self.children = children or []
        self.parent = parent
        self.layer = layer

    def to_dict(self) -> dict:
        return {
            "role_id": self.role_id,
            "role": self.role,
            "emoji": self.emoji,
            "description": self.description,
            "system_hint": self.system_hint,
            "agent_id": self.agent_id,
            "children": self.children,
            "parent": self.parent,
            "layer": self.layer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeamNode":
        return cls(**data)


class AgentTeam:
    """A group of agents working together on tasks with optional hierarchy."""

    def __init__(
        self,
        name: str,
        description: str = "",
        agent_ids: List[str] = None,
        lead_agent_id: str = "",
        strategy: str = "sequential",  # sequential | parallel | lead-delegate | hierarchy
        template: str = "custom",
        nodes: List[dict] = None,
        id: str = None,
        created_at: str = None,
    ):
        self.id = id or f"team_{__import__('uuid').uuid4().hex[:8]}"
        self.name = name
        self.description = description
        self.agent_ids = agent_ids or []
        self.lead_agent_id = lead_agent_id
        self.strategy = strategy
        self.template = template
        self.nodes: Dict[str, TeamNode] = {}
        self.created_at = created_at or datetime.datetime.now().isoformat()

        # Load nodes from dict list
        if nodes:
            for nd in nodes:
                node = TeamNode.from_dict(nd) if isinstance(nd, dict) else nd
                self.nodes[node.role_id] = node

    def get_root_nodes(self) -> List[TeamNode]:
        """Get top-level nodes (no parent)."""
        return [n for n in self.nodes.values() if n.parent is None]

    def get_children(self, role_id: str) -> List[TeamNode]:
        """Get child nodes of a given role."""
        node = self.nodes.get(role_id)
        if not node:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_org_chart(self) -> dict:
        """Build a nested org chart tree for UI rendering."""
        def build_tree(node: TeamNode) -> dict:
            return {
                **node.to_dict(),
                "children_nodes": [build_tree(self.nodes[cid]) for cid in node.children if cid in self.nodes],
            }

        roots = self.get_root_nodes()
        return [build_tree(r) for r in roots]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "agent_ids": self.agent_ids,
            "lead_agent_id": self.lead_agent_id,
            "strategy": self.strategy,
            "template": self.template,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentTeam":
        return cls(**data)


class Orchestrator:
    """Multi-agent task orchestration engine."""

    def __init__(self):
        self._teams: Dict[str, AgentTeam] = {}
        self._task_log: List[dict] = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(TEAMS_FILE):
                with open(TEAMS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    teams = data.get("teams", [])
                    self._teams = {t["id"]: AgentTeam.from_dict(t) for t in teams}
                    self._task_log = data.get("task_log", [])
        except Exception as e:
            logger.error(f"Error loading teams: {e}")
            self._teams = {}

    def _save(self):
        os.makedirs(os.path.dirname(TEAMS_FILE), exist_ok=True)
        with open(TEAMS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "teams": [t.to_dict() for t in self._teams.values()],
                "task_log": self._task_log[-100:],
            }, f, indent=2, ensure_ascii=False)

    # ── Team CRUD ────────────────────────────────────────────

    def create_team(self, name: str, agent_ids: List[str] = None, lead_agent_id: str = "",
                    strategy: str = "sequential", description: str = "",
                    template: str = "custom", nodes: List[dict] = None) -> AgentTeam:
        team = AgentTeam(
            name=name, agent_ids=agent_ids or [], lead_agent_id=lead_agent_id or (agent_ids[0] if agent_ids else ""),
            strategy=strategy, description=description, template=template, nodes=nodes,
        )
        self._teams[team.id] = team
        self._save()
        return team

    def create_from_template(self, template_id: str, name: str = "",
                              agent_assignments: Dict[str, str] = None) -> AgentTeam:
        """Create a team from a preset template, optionally assigning agents to roles."""
        from tubecli.extensions.multi_agents.templates import get_template

        tmpl = get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template '{template_id}' not found")

        team_name = name or tmpl["name"]
        nodes = []
        agent_ids = []
        lead_agent_id = ""

        for node_def in tmpl["nodes"]:
            node_data = dict(node_def)
            # Assign agent if provided
            if agent_assignments and node_data["role_id"] in agent_assignments:
                aid = agent_assignments[node_data["role_id"]]
                node_data["agent_id"] = aid
                if aid not in agent_ids:
                    agent_ids.append(aid)
            nodes.append(node_data)

        # First node with an agent = lead
        if agent_ids:
            lead_agent_id = agent_ids[0]

        return self.create_team(
            name=team_name,
            agent_ids=agent_ids,
            lead_agent_id=lead_agent_id,
            strategy="hierarchy",
            description=tmpl["description"],
            template=template_id,
            nodes=nodes,
        )

    def update_team(self, team_id: str, **updates) -> Optional[AgentTeam]:
        """Update team fields."""
        team = self._teams.get(team_id)
        if not team:
            return None

        for key, value in updates.items():
            if key == "nodes" and isinstance(value, list):
                team.nodes = {}
                for nd in value:
                    node = TeamNode.from_dict(nd) if isinstance(nd, dict) else nd
                    team.nodes[node.role_id] = node
                # Rebuild agent_ids from nodes
                team.agent_ids = list(set(
                    n.agent_id for n in team.nodes.values() if n.agent_id
                ))
            elif hasattr(team, key):
                setattr(team, key, value)

        self._save()
        return team

    def delete_team(self, team_id: str) -> bool:
        if team_id in self._teams:
            del self._teams[team_id]
            self._save()
            return True
        return False

    def get_team(self, team_id: str) -> Optional[AgentTeam]:
        return self._teams.get(team_id)

    def get_all_teams(self) -> List[AgentTeam]:
        return list(self._teams.values())

    def find_team_by_name(self, name: str) -> Optional[AgentTeam]:
        for t in self._teams.values():
            if t.name.lower() == name.lower():
                return t
        return None

    # ── Task Delegation ──────────────────────────────────────

    async def delegate(self, team_id: str, task: str) -> dict:
        """Delegate a task to a team of agents based on team strategy."""
        team = self._teams.get(team_id)
        if not team:
            return {"status": "error", "message": f"Team '{team_id}' not found."}

        # Use hierarchy strategy if team has nodes
        if team.strategy == "hierarchy" and team.nodes:
            return await self._delegate_hierarchy(team, task)

        if not team.agent_ids:
            return {"status": "error", "message": "Team has no agents."}

        from tubecli.core.agent import agent_manager
        from tubecli.core.skill import skill_manager
        from tubecli.core.brain import AgentBrain

        results = []
        context_chain = task

        if team.strategy == "sequential":
            for agent_id in team.agent_ids:
                agent = agent_manager.get(agent_id)
                if not agent:
                    results.append({"agent_id": agent_id, "status": "error", "reply": "Agent not found"})
                    continue
                agent_dict = agent.to_dict()
                skills = [s.to_dict() for s in skill_manager.get_all()]
                brain_result = AgentBrain.chat(message=context_chain, agent=agent_dict, skills=skills)
                results.append({
                    "agent_id": agent_id, "agent_name": agent.name,
                    "reply": brain_result.get("reply", ""), "action": brain_result.get("action"),
                })
                if brain_result.get("reply"):
                    context_chain = f"Previous agent ({agent.name}) said: {brain_result['reply']}\n\nOriginal task: {task}\n\nYour turn to continue."

        elif team.strategy == "parallel":
            for agent_id in team.agent_ids:
                agent = agent_manager.get(agent_id)
                if not agent:
                    results.append({"agent_id": agent_id, "status": "error", "reply": "Agent not found"})
                    continue
                agent_dict = agent.to_dict()
                skills = [s.to_dict() for s in skill_manager.get_all()]
                brain_result = AgentBrain.chat(message=task, agent=agent_dict, skills=skills)
                results.append({
                    "agent_id": agent_id, "agent_name": agent.name,
                    "reply": brain_result.get("reply", ""), "action": brain_result.get("action"),
                })

        elif team.strategy == "lead-delegate":
            lead = agent_manager.get(team.lead_agent_id)
            if not lead:
                return {"status": "error", "message": "Lead agent not found."}
            lead_dict = lead.to_dict()
            member_names = []
            for aid in team.agent_ids:
                a = agent_manager.get(aid)
                if a:
                    member_names.append(f"- {a.name} (ID: {aid}): {a.description}")
            delegation_prompt = f"""You are the team lead. Your task: "{task}"

Your team members:
{chr(10).join(member_names)}

Analyze the task and respond with how to delegate. Reply normally — your response will be shared with team members for execution."""
            brain_result = AgentBrain.chat(
                message=delegation_prompt, agent=lead_dict, skills=[s.to_dict() for s in skill_manager.get_all()],
            )
            results.append({
                "agent_id": lead.id, "agent_name": lead.name,
                "role": "lead", "reply": brain_result.get("reply", ""),
            })

        self._log_task(team_id, team.name, task, team.strategy, len(results))
        return {"status": "completed", "team": team.name, "strategy": team.strategy, "results": results}

    async def _delegate_hierarchy(self, team: AgentTeam, task: str) -> dict:
        """Delegate a task through the team hierarchy tree (top-down)."""
        from tubecli.core.agent import agent_manager
        from tubecli.core.skill import skill_manager
        from tubecli.core.brain import AgentBrain

        results = []

        async def process_node(node: TeamNode, incoming_task: str, depth: int = 0):
            """Process a single node and recursively delegate to children."""
            agent = agent_manager.get(node.agent_id) if node.agent_id else None

            if not agent:
                results.append({
                    "role_id": node.role_id, "role": node.role, "emoji": node.emoji,
                    "status": "skipped", "reply": f"No agent assigned to role '{node.role}'",
                    "depth": depth,
                })
                # Still try to delegate to children with the same task
                for child_id in node.children:
                    child_node = team.nodes.get(child_id)
                    if child_node:
                        await process_node(child_node, incoming_task, depth + 1)
                return

            # Build context-aware prompt
            children_desc = ""
            if node.children:
                child_roles = []
                for cid in node.children:
                    cn = team.nodes.get(cid)
                    if cn:
                        child_roles.append(f"  - {cn.emoji} {cn.role}: {cn.description}")
                children_desc = f"\n\nYour subordinates:\n" + "\n".join(child_roles)

            enhanced_prompt = f"""{node.system_hint}
{children_desc}

Task from {'your superior' if node.parent else 'the user'}:
{incoming_task}

Process this task according to your role. If you have subordinates, indicate what each should handle."""

            agent_dict = agent.to_dict()
            skills = [s.to_dict() for s in skill_manager.get_all()]
            brain_result = AgentBrain.chat(message=enhanced_prompt, agent=agent_dict, skills=skills)
            reply = brain_result.get("reply", "")

            results.append({
                "role_id": node.role_id, "role": node.role, "emoji": node.emoji,
                "agent_id": node.agent_id, "agent_name": agent.name,
                "reply": reply, "action": brain_result.get("action"),
                "depth": depth,
            })

            # Pass output to children
            for child_id in node.children:
                child_node = team.nodes.get(child_id)
                if child_node:
                    child_task = f"Your superior ({node.role}) has processed this task and says:\n{reply}\n\nOriginal task: {task}\n\nHandle your part according to your role."
                    await process_node(child_node, child_task, depth + 1)

        # Start from root nodes
        for root_node in team.get_root_nodes():
            await process_node(root_node, task)

        self._log_task(team.id, team.name, task, "hierarchy", len(results))
        return {"status": "completed", "team": team.name, "strategy": "hierarchy", "results": results}

    def _log_task(self, team_id: str, team_name: str, task: str, strategy: str, agent_count: int):
        self._task_log.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "team_id": team_id, "team_name": team_name,
            "task": task[:200], "strategy": strategy,
            "agent_count": agent_count,
        })
        self._save()

    def get_task_log(self) -> List[dict]:
        return self._task_log


# Global singleton
orchestrator = Orchestrator()


class MultiAgentsExtension(Extension):
    name = "multi_agents"
    version = "0.2.0"
    description = "Multi-agent orchestration — teams, task delegation, and collaborative workflows"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        os.makedirs(os.path.dirname(TEAMS_FILE), exist_ok=True)

    def get_commands(self):
        from tubecli.extensions.multi_agents.commands import multi_agents_group
        return multi_agents_group

    def get_routes(self):
        from tubecli.extensions.multi_agents.routes import router
        return router
