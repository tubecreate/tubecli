# TubeCLI — Open Source AI Agent CLI System

A headless CLI system for installing, managing, and orchestrating **AI agents**, **skills**, and **workflows**. Designed so that AI agents can understand, install, and operate the entire system autonomously.

## Features

- 🤖 **Agent Manager** — Create and manage AI agents with personas, routines, and skills
- ⚡ **Skill System** — Pre-built workflow templates that agents can execute
- 🔄 **Workflow Engine** — DAG-based workflow executor with typed node connections
- 🌐 **API Server** — FastAPI REST API for programmatic access
- 📖 **AI-Readable Docs** — SKILL.md documentation for AI agents to self-operate

## Quick Start

```bash
# Install
cd tubecli
pip install -e .

# Initialize workspace
tubecli init

# Create an agent
tubecli agent create "My Assistant" --description "General purpose AI agent"

# List skills
tubecli skill list

# Run a skill
tubecli skill run "AI Summarizer" --input "Your text here"

# Start API server
tubecli api start
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `tubecli init` | Initialize workspace and install default skills |
| `tubecli agent create` | Create a new agent |
| `tubecli agent list` | List all agents |
| `tubecli agent show <id>` | Show agent details |
| `tubecli agent delete <id>` | Delete an agent |
| `tubecli skill list` | List available skills |
| `tubecli skill run <name>` | Execute a skill |
| `tubecli workflow run <file>` | Run a workflow JSON file |
| `tubecli api start` | Start the REST API server |
| `tubecli api stop` | Stop the API server |

## Architecture

```
tubecli/
├── tubecli/           # Main package
│   ├── main.py        # CLI entry point (Click)
│   ├── config.py      # Global configuration
│   ├── core/          # Business logic (agents, skills, workflows)
│   ├── api/           # REST API server (FastAPI)
│   ├── cli/           # CLI command modules
│   ├── nodes/         # Workflow node implementations
│   └── skills/        # Built-in skill definitions
├── .agents/           # AI-readable documentation
├── data/              # Runtime data (gitignored)
└── tests/             # Test suite
```

## API Server

When running (`tubecli api start`), the following endpoints are available:

- `GET /api/v1/health` — Health check
- `GET/POST/PUT/DELETE /api/v1/agents` — Agent CRUD
- `GET/POST/DELETE /api/v1/skills` — Skill CRUD
- `POST /api/v1/workflows/run` — Execute workflow
- `GET /api/v1/workflows/status/{id}` — Check execution status

## License

MIT
