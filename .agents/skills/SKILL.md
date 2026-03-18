---
name: TubeCLI System Guide
description: Complete guide for AI agents to understand, install, and operate TubeCLI
---

# TubeCLI — AI Agent Operating Guide

## 1. System Overview

TubeCLI is a headless CLI system for managing AI agents, skills (workflow templates), and workflows.
AI agents can use this system via CLI commands or REST API.

### Architecture
```
tubecli (Click CLI)
├── agent  — Manage AI agents (create, list, delete)
├── skill  — Manage & run skills (workflow templates)
├── workflow — Run workflow JSON files
├── api    — Start REST API server
└── init   — Initialize workspace
```

### Key Concepts
- **Agent**: An AI entity with name, description, system prompt, persona, and assigned skills
- **Skill**: A reusable workflow template (DAG of connected nodes)
- **Workflow**: A directed acyclic graph (DAG) of nodes connected by ports
- **Node**: An execution unit with typed input/output ports (text, json, file, any)

## 2. Installation

```bash
cd tubecli
pip install -e .
tubecli init
```

## 3. CLI Commands

### Initialize
```bash
tubecli init  # Creates data dirs, installs default skills, creates default agent
```

### Agents
```bash
tubecli agent create "Agent Name" --description "desc" --model "qwen:latest"
tubecli agent list
tubecli agent show <agent_id_or_name>
tubecli agent delete <agent_id>
```

### Skills
```bash
tubecli skill list
tubecli skill show "AI Summarizer"
tubecli skill run "AI Summarizer" --input "Text to summarize"
tubecli skill run "Batch Command Runner"
```

### Workflows
```bash
tubecli workflow list
tubecli workflow run workflow.json --input "input text"
```

### API Server
```bash
tubecli api start --port 5295
tubecli api status
```

## 4. REST API Reference

Base URL: `http://localhost:5295`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/health | Health check |
| GET | /api/v1/agents | List agents |
| POST | /api/v1/agents | Create agent |
| GET | /api/v1/agents/{id} | Get agent |
| PUT | /api/v1/agents/{id} | Update agent |
| DELETE | /api/v1/agents/{id} | Delete agent |
| GET | /api/v1/skills | List skills |
| POST | /api/v1/skills | Create skill |
| DELETE | /api/v1/skills/{id} | Delete skill |
| POST | /api/v1/workflows/run | Execute workflow |
| GET | /api/v1/nodes | List node types |

## 5. Workflow JSON Format

```json
{
  "name": "My Workflow",
  "nodes": [
    {"id": "input1", "type": "text_input", "config": {"text": "Hello"}},
    {"id": "ai1", "type": "ai_node", "config": {"model": "qwen:latest"}},
    {"id": "out1", "type": "output", "config": {"print": true}}
  ],
  "connections": [
    {"from_node_id": "input1", "from_port_id": "content", "to_node_id": "ai1", "to_port_id": "prompt"},
    {"from_node_id": "ai1", "from_port_id": "response", "to_node_id": "out1", "to_port_id": "data"}
  ]
}
```

## 6. Available Node Types

| Type | Name | Inputs | Outputs | Description |
|------|------|--------|---------|-------------|
| text_input | 📝 Text Input | — | content, lines | Static text |
| loop | 🔄 Loop | items | current_item, index, total | Iterate list |
| python_code | 🐍 Python Code | text_input, json_input | result | Execute Python |
| api_request | 🌐 API Request | url, body | response, status_code | HTTP request |
| run_command | 💻 Run Command | command | stdout, exit_code | Shell command |
| ai_node | 🧠 AI Inference | prompt, context | response | AI model call |
| output | 📤 Output | data | file_path | Display/save results |

## 7. Agent JSON Schema

```json
{
  "id": "uuid",
  "name": "Agent Name",
  "description": "What this agent does",
  "system_prompt": "You are...",
  "allowed_skills": ["skill_id_1", "skill_id_2"],
  "model": "qwen:latest",
  "persona": {},
  "routine": {},
  "cloud_api_keys": {"gemini": "", "openai": "", "claude": "", "deepseek": ""}
}
```

## 8. Creating Custom Skills

To create a custom skill, POST to `/api/v1/skills` or use the skill manager:

```json
{
  "name": "My Custom Skill",
  "description": "What it does",
  "skill_type": "Skill",
  "workflow_data": {
    "nodes": [...],
    "connections": [...]
  }
}
```

## 9. Common Workflow Patterns

### Pattern: Input → AI → Output
```json
{
  "nodes": [
    {"id": "in", "type": "text_input", "config": {"text": "..."}},
    {"id": "ai", "type": "ai_node", "config": {}},
    {"id": "out", "type": "output", "config": {}}
  ],
  "connections": [
    {"from_node_id": "in", "from_port_id": "content", "to_node_id": "ai", "to_port_id": "prompt"},
    {"from_node_id": "ai", "from_port_id": "response", "to_node_id": "out", "to_port_id": "data"}
  ]
}
```

### Pattern: Loop → Command → Output
```json
{
  "nodes": [
    {"id": "list", "type": "text_input", "config": {"text": "cmd1\ncmd2"}},
    {"id": "loop", "type": "loop", "config": {}},
    {"id": "exec", "type": "run_command", "config": {}},
    {"id": "out", "type": "output", "config": {}}
  ],
  "connections": [
    {"from_node_id": "list", "from_port_id": "lines", "to_node_id": "loop", "to_port_id": "items"},
    {"from_node_id": "loop", "from_port_id": "current_item", "to_node_id": "exec", "to_port_id": "command"},
    {"from_node_id": "exec", "from_port_id": "stdout", "to_node_id": "out", "to_port_id": "data"}
  ]
}
```
