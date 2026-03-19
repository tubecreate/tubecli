# Multi-Agent Orchestration — AI Skill Guide

## Extension: multi_agents
Enables multi-agent collaboration through teams, task delegation, and coordinated workflows.

## Strategies
- **sequential**: Agents process in order, passing context forward (chain-of-thought)
- **parallel**: All agents process independently on the same task
- **lead-delegate**: Lead agent analyzes task and delegates to team members

## Available Commands

### List Teams
```
tubecli multi-agent teams
```

### Create Team
```
tubecli multi-agent create-team "Research Team" -a agent_id1,agent_id2,agent_id3 -s sequential
```

### Delete Team
```
tubecli multi-agent delete-team team_abc123
```

### Delegate Task
```
tubecli multi-agent delegate team_abc123 "Summarize the latest news about AI"
```

### View Log
```
tubecli multi-agent log
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/multi-agents/teams` | List teams |
| POST | `/api/v1/multi-agents/teams` | Create team |
| GET | `/api/v1/multi-agents/teams/{id}` | Get team |
| DELETE | `/api/v1/multi-agents/teams/{id}` | Delete team |
| POST | `/api/v1/multi-agents/teams/{id}/delegate` | Delegate task |
| GET | `/api/v1/multi-agents/log` | Delegation log |

## AI Usage
1. Create a team with agents that have complementary skills
2. Choose strategy based on task type:
   - Use **sequential** for tasks that build on each other
   - Use **parallel** for independent sub-tasks
   - Use **lead-delegate** when one agent should coordinate
3. Delegate the task and collect combined results
