# ⚡ TubeCLI — Open Source AI Agent CLI System

<p align="center">
    <a href="https://github.com/tubecreate/tubecli">
        <img src="https://img.shields.io/github/stars/tubecreate/tubecli?style=for-the-badge&color=2a2a2a&labelColor=1a1a1a" alt="Stars" />
    </a>
    <a href="https://github.com/tubecreate/tubecli">
        <img src="https://img.shields.io/github/forks/tubecreate/tubecli?style=for-the-badge&color=1e7b85&labelColor=236f78" alt="Forks" />
    </a>
    <a href="https://github.com/tubecreate/tubecli/blob/main/LICENSE">
        <img src="https://img.shields.io/badge/LICENSE-MIT-00897b?style=for-the-badge&labelColor=333333" alt="License" />
    </a>
</p>

<p align="center">
    <img src="https://img.shields.io/badge/PYTHON-3.9+-0078d4?style=for-the-badge&logo=python&logoColor=white&labelColor=333333" alt="Python" />
    <img src="https://img.shields.io/badge/API-FASTAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=333333" alt="FastAPI" />
    <img src="https://img.shields.io/badge/UI-VUE.JS-4FC08D?style=for-the-badge&logo=vue.js&logoColor=white&labelColor=333333" alt="Vue.js" />
    <img src="https://img.shields.io/badge/3D-THREE.JS-000000?style=for-the-badge&logo=three.js&logoColor=white&labelColor=333333" alt="Three.js" />
</p>

<p align="center">
    <img src="https://img.shields.io/badge/AGENTS-BROWSER-ffd700?style=for-the-badge&labelColor=1a1a1a" alt="Agents Browser" />
    <img src="https://img.shields.io/badge/AGENTS-WORKFLOW-ff0055?style=for-the-badge&labelColor=1a1a1a" alt="Agents Workflow" />
    <img src="https://img.shields.io/badge/AGENTS-STUDIO_WORLD-00ffcc?style=for-the-badge&labelColor=1a1a1a" alt="Agents Studio World" />
</p>

A headless CLI system for installing, managing, and orchestrating **AI agents**, **skills**, and **workflows**. Designed so that AI agents can understand, install, and operate the entire system autonomously.

![3D Studio Office Builder](screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](screenshots/studio3d_teams.png)

## 🌟 Key Features

The system has evolved into a full-fledged 10-subsystem architecture:

- 🤖 **Agent Manager** — Create and manage AI agents with personas, routines, and skills.
- ⚡ **Skill System** — Executable workflows marked with tags (Workflow, API, Markdown) featuring a Markdown Viewer and Real-time Execution Modal.
- 🔄 **Workflow Engine & Builder** — DAG-based workflow executor. The WebUI features a modern node-based builder with compact nodes, contextual sliding property panels, and dynamic model selection (Ollama local / Cloud API).
- 🎨 **Web Dashboard** — Comprehensive SPA (Single Page Application) at `localhost:5295/dashboard` to visually manage agents, workflows, skills, marketplace, settings, and monitor browsers natively.
- 👥 **Teams Agents** — Orchestrate multiple agents using Organizational Charts. Assign roles via logical templates or drag-and-drop. Task Delegation routes work through the team based on sequential, parallel, or hierarchical strategies.
- 🏢 **3D Studio (Teams 3D)** — Isometric procedural 3D visualization using Three.js. Supports multi-seat furniture (meeting tables, conference tables) with intelligent inward-facing algorithms, raycasting group manipulation, and 15+ built-in assets.
- 🎬 **Story Engine & Player** — Generate interactive 3D stories from prompts via our Script Editor. Agents communicate via 3D speech bubbles inside an animated scene player.
- 🔌 **Extension Manager** — Pluggable architecture supporting `browser`, `webui`, `market`, and `studio3d`. Enables hot-reloading CLI commands and API routes.
- 🌐 **Browser Automation** — Orchestrate browser profiles, proxies, fingerprints. Built-in Auto-Login for Google with TOTP 2FA.
- 🛒 **Marketplace** — Discover, install, and share community skills via an online registry.

## 🚀 Quick Start & Installation

### Prerequisites
- Python 3.9+
- Ollama (Optional, required for local AI execution)
- Git

### 1. Clone & Install
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Initialize Workspace
Run the initialization command to setup the `data/` directory, extract default skills, and activate core extensions.
```bash
tubecli init --lang vi
```

### 3. Start the Web Dashboard
After initialization, start the API server to access the GUI.
```bash
tubecli api start --port 5295
```
Open your browser and navigate to: **http://localhost:5295/dashboard**

## 💻 CLI Usage

Manage the entire system directly from the terminal if you prefer a headless approach:

### Agent Management
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### Skill Execution
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API & Workflows
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### Extensions & Market
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```

## 🧠 Architecture Overview

```
tubecli/
├── tubecli/           # Main package
│   ├── api/           # REST API server (FastAPI)
│   ├── cli/           # CLI command modules
│   ├── core/          # Core Business logic
│   ├── extensions/    # Extensions (Browser, WebUI, Market, Studio3D)
│   ├── nodes/         # Workflow Node implementations
│   └── skills/        # Built-in system skills
├── .agents/           # AI-readable documentation (SKILL.md)
├── data/              # Runtime DB & State (gitignored)
└── tests/             # Test suite
```

## 📖 AI-Readable Documentation
The `.agents/` and skills folders contain documentation crafted explicitly for LLMs (`SKILL.md`). External AI agents (like Claude or GPT-4) can read these files to learn how to operate the TubeCLI system, write plugins, and debug workflows completely autonomously without human intervention.

## 📝 License
MIT License - Made with 🤖 by TubeCreate Team
