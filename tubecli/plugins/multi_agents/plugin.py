"""
Multi-Agents Plugin — Multi-agent orchestration and collaboration.
Enables agent teams, task delegation, and coordinated multi-agent workflows.
"""
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
from tubecli.core.plugin_manager import Plugin
from tubecli.config import DATA_DIR
import os

logger = logging.getLogger("MultiAgentsPlugin")

TEAMS_FILE = os.path.join(DATA_DIR, "agent_teams.json")


class AgentTeam:
    """A group of agents working together on tasks."""

    def __init__(
        self,
        name: str,
        description: str = "",
        agent_ids: List[str] = None,
        lead_agent_id: str = "",
        strategy: str = "sequential",  # sequential | parallel | lead-delegate
        id: str = None,
        created_at: str = None,
    ):
        self.id = id or f"team_{__import__('uuid').uuid4().hex[:8]}"
        self.name = name
        self.description = description
        self.agent_ids = agent_ids or []
        self.lead_agent_id = lead_agent_id
        self.strategy = strategy
        self.created_at = created_at or datetime.datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "agent_ids": self.agent_ids, "lead_agent_id": self.lead_agent_id,
            "strategy": self.strategy, "created_at": self.created_at,
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

    def create_team(self, name: str, agent_ids: List[str], lead_agent_id: str = "",
                    strategy: str = "sequential", description: str = "") -> AgentTeam:
        team = AgentTeam(
            name=name, agent_ids=agent_ids, lead_agent_id=lead_agent_id or (agent_ids[0] if agent_ids else ""),
            strategy=strategy, description=description,
        )
        self._teams[team.id] = team
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
        """Delegate a task to a team of agents based on team strategy.

        Returns execution results from each agent step.
        """
        team = self._teams.get(team_id)
        if not team:
            return {"status": "error", "message": f"Team '{team_id}' not found."}

        if not team.agent_ids:
            return {"status": "error", "message": "Team has no agents."}

        from tubecli.core.agent import agent_manager
        from tubecli.core.skill import skill_manager
        from tubecli.core.brain import AgentBrain

        results = []
        context_chain = task  # Output from previous agent feeds into next

        if team.strategy == "sequential":
            # Each agent processes in order, passing context forward
            for agent_id in team.agent_ids:
                agent = agent_manager.get(agent_id)
                if not agent:
                    results.append({"agent_id": agent_id, "status": "error", "reply": f"Agent not found"})
                    continue

                agent_dict = agent.to_dict()
                all_skills = skill_manager.get_all()
                skills = [s.to_dict() for s in all_skills]

                brain_result = AgentBrain.chat(
                    message=context_chain, agent=agent_dict, skills=skills,
                )

                results.append({
                    "agent_id": agent_id, "agent_name": agent.name,
                    "reply": brain_result.get("reply", ""),
                    "action": brain_result.get("action"),
                })

                # Chain output to next agent
                if brain_result.get("reply"):
                    context_chain = f"Previous agent ({agent.name}) said: {brain_result['reply']}\n\nOriginal task: {task}\n\nYour turn to continue."

        elif team.strategy == "parallel":
            # All agents process independently (simulated sequentially for now)
            for agent_id in team.agent_ids:
                agent = agent_manager.get(agent_id)
                if not agent:
                    results.append({"agent_id": agent_id, "status": "error", "reply": "Agent not found"})
                    continue

                agent_dict = agent.to_dict()
                all_skills = skill_manager.get_all()
                skills = [s.to_dict() for s in all_skills]

                brain_result = AgentBrain.chat(
                    message=task, agent=agent_dict, skills=skills,
                )

                results.append({
                    "agent_id": agent_id, "agent_name": agent.name,
                    "reply": brain_result.get("reply", ""),
                    "action": brain_result.get("action"),
                })

        elif team.strategy == "lead-delegate":
            # Lead agent decides how to split work, then delegates
            lead = agent_manager.get(team.lead_agent_id)
            if not lead:
                return {"status": "error", "message": f"Lead agent not found."}

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

        # Log the delegation
        self._task_log.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "team_id": team_id, "team_name": team.name,
            "task": task[:200], "strategy": team.strategy,
            "agent_count": len(results),
        })
        self._save()

        return {
            "status": "completed",
            "team": team.name,
            "strategy": team.strategy,
            "results": results,
        }

    def get_task_log(self) -> List[dict]:
        return self._task_log


# Global singleton
orchestrator = Orchestrator()


class MultiAgentsPlugin(Plugin):
    name = "multi_agents"
    version = "0.1.0"
    description = "Multi-agent orchestration — teams, task delegation, and collaborative workflows"
    author = "TubeCreate"
    plugin_type = "system"

    def on_enable(self):
        os.makedirs(os.path.dirname(TEAMS_FILE), exist_ok=True)

    def get_commands(self):
        from tubecli.plugins.multi_agents.commands import multi_agents_group
        return multi_agents_group

    def get_routes(self):
        from tubecli.plugins.multi_agents.routes import router
        return router
