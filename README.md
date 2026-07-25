# ⚡ TubeCLI — Open Source AI Agent CLI System

<p align="center">
  <b>English</b> | 
  <a href="READMEs/README_zh-CN.md">简体中文</a> | 
  <a href="READMEs/README_zh-TW.md">繁體中文</a> | 
  <a href="READMEs/README_ja.md">日本語</a> | 
  <a href="READMEs/README_ko.md">한국어</a> | 
  <a href="READMEs/README_es.md">Español</a> | 
  <a href="READMEs/README_tr.md">Türkçe</a> | 
  <a href="READMEs/README_ru.md">Русский</a> | 
  <a href="READMEs/README_vi.md">Tiếng Việt</a>
</p>

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

The system has evolved into a full-fledged 12-subsystem architecture:

- 💬 **Chat** — A unified conversation interface for the whole system. Multi-session threads with durable history, an agent picker (or automatic routing to the right specialist), and markdown rendering. Every turn runs the full pipeline — zero-token intent classification, skill selection, then the model — so anything the Telegram bot can do, the browser can do too.
- 📋 **Codex** — Mission control for agentic work. You or the AI create a task, delegate it to an agent or a team, approve it, and a background worker runs it while you watch the step timeline. Results come back for review. Tasks are durable and survive a restart, with a full audit trail per task.
- 🤖 **Agent Manager** — Create and manage AI agents with personas, routines, and skills.
- ⚡ **Skill System** — Executable workflows marked with tags (Workflow, API, Markdown) featuring a Markdown Viewer and Real-time Execution Modal.
- 🔄 **Workflow Engine & Builder** — DAG-based workflow executor. The WebUI features a modern node-based builder with compact nodes, contextual sliding property panels, and dynamic model selection (Ollama local / Cloud API).
- 🎨 **Web Dashboard** — Comprehensive SPA (Single Page Application) at `localhost:5295/dashboard` to visually manage agents, workflows, skills, marketplace, settings, and monitor browsers natively.
- 👥 **Teams Agents** — Orchestrate multiple agents using Organizational Charts. Assign roles via logical templates or drag-and-drop. Task Delegation routes work through the team based on sequential, parallel, or hierarchical strategies.
- 🏢 **3D Studio (Teams 3D)** — Isometric procedural 3D visualization using Three.js. Supports multi-seat furniture (meeting tables, conference tables) with intelligent inward-facing algorithms, raycasting group manipulation, and 15+ built-in assets.
- 🎬 **Story Engine & Player** — Generate interactive 3D stories from prompts via our Script Editor. Agents communicate via 3D speech bubbles inside an animated scene player.
- 🔌 **Extension Manager** — Pluggable architecture. Built-ins include `chat`, `codex`, `browser`, `browser_scripts`, `webui`, `market`, `multi_agents`, `studio3d`, `cloud_api`, and more. Each extension contributes CLI commands, API routes, workflow nodes, Telegram actions, and its own UI page.
- 🌐 **Browser Automation** — Orchestrate browser profiles, proxies, fingerprints. Built-in Auto-Login for Google with TOTP 2FA.
- 🛒 **Marketplace** — Discover, install, and share community skills via an online registry.
- 📨 **Telegram Bridge** — Drive the same system from a Telegram bot: intent routing, skill execution, task approval, and proactive notifications when long-running work finishes.

## 🚀 Quick Start & Installation

### Option 1: One-Click Auto Install (Recommended for Users)
**For Windows:** Open **PowerShell** (Run as Administrator) and paste the following command:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1 | iex"
```
*Note: To install with a specific language (e.g. `vi`, `zh-TW`, `ja`), use:*
```powershell
powershell -c "&([ScriptBlock]::Create((irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1))) -Lang vi"
```

**For Linux / MacOS:** Open your terminal and run:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash
```
*Note: To install with a specific language (e.g. `vi`, `zh-TW`, `ja`), use:*
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash -s -- --lang vi
```

It will automatically install Python, Git (if missing), clone the repo, and set up everything for you from A-Z.

### Option 2: Manual Installation (For Developers)

#### Prerequisites
- Python 3.9+
- Ollama (Optional, required for local AI execution)
- Git

#### 1. Clone & Install
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Initialize Workspace
Run the initialization command to setup the `data/` directory, extract default skills, activate core extensions, and configure the default port.
```bash
tubecli init --lang en --port 5295
```

### 3. Start the Web Dashboard
After initialization, start the API server to access the GUI.
```bash
tubecli api start
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

### Task Board (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> Tasks the AI creates always wait for your approval before they run.

### Extensions & Market
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> Extensions bind their API routes when the server imports them, so **restart the server** after enabling or adding one.

## 🧠 Architecture Overview

```
tubecli/
├── tubecli/           # Main package
│   ├── api/           # REST API server (FastAPI)
│   ├── cli/           # CLI command modules
│   ├── core/          # Core Business logic
│   ├── extensions/    # Extensions (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
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
