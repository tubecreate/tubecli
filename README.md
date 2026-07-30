# TubeCLI — Self-Hosted AI Agent Team That Deploys Websites, Automates Browsers, and Translates Video

**Coding agents write code. This one runs the operations — on your machine, with your keys, for your clients.**

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
  <a href="https://github.com/tubecreate/tubecli/stargazers"><img src="https://img.shields.io/github/stars/tubecreate/tubecli?style=for-the-badge&color=2a2a2a&labelColor=1a1a1a" alt="GitHub stars for TubeCLI" /></a>
  <a href="https://github.com/tubecreate/tubecli/blob/main/LICENSE"><img src="https://img.shields.io/badge/LICENSE-MIT-00897b?style=for-the-badge&labelColor=333333" alt="MIT License — free to resell and white-label" /></a>
  <img src="https://img.shields.io/badge/SELF--HOSTED-YES-4c1?style=for-the-badge&labelColor=333333" alt="Self-hosted AI agents, no cloud required" />
  <img src="https://img.shields.io/badge/LOCAL_LLM-OLLAMA-ff6b35?style=for-the-badge&labelColor=333333" alt="Runs on local LLM via Ollama" />
  <img src="https://img.shields.io/badge/PYTHON-3.9+-0078d4?style=for-the-badge&logo=python&logoColor=white&labelColor=333333" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/API-FASTAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=333333" alt="FastAPI backend" />
</p>

**TubeCLI is a self-hosted, open-source AI agent team that executes real operational work end to end.** It is not a chat wrapper, and it is not a framework you have to code your agents into. You describe the job in plain language — from the CLI, a web dashboard, or Telegram — and an agent team carries it out with real tools against your own infrastructure.

What that means in practice, measured on 2026-07-30:

- **Browser automation** — 556 logged script executions, 375 of them successful. Profiles, proxies, fingerprints, and TOTP 2FA.
- **Subtitles** — a 559-cue Vietnamese SRT with a matching 559-cue English translation on disk, produced by three interchangeable engines (local Whisper, Gemini, YouTube CC) exporting SRT/JSON/VTT/ASS.
- **Cloudflare Workers deploys** — a [435-line deploy runner](tubecli/extensions/website_manager/deploy_runner.js) you can read line by line, executing the real chain: `git clone --depth=1` → `npm install` → `wrangler d1 create` + `r2 bucket create` → remote schema apply → [OpenNext](https://opennext.js.org/cloudflare) build → `wrangler deploy`. **Honest caveat:** real, but not one-click — 1 of the 4 most recent attempts finished clean, and admin-password seeding can fall back to the template default. It fails loudly, with the reason in the log.
- **Also shipping** — WordPress publishing over the WP REST API, web crawling and change watching, video download and dubbing, Google Sheets and Calendar, POD/graphic/content studios, livestream restreaming.

Every LLM call runs on local [Ollama](https://ollama.com) — no API key, no per-token cost — or on Gemini, OpenAI, Claude, DeepSeek, Grok and OpenRouter with your own keys. Critical paths use zero-token fast paths that never call a model at all.

**What you get on `git clone`:** the agent runtime plus **17 built-in extensions** (`website_manager`, `browser`, `browser_scripts`, `codex`, `video_studio`, `multi_agents`, `cloud_api`, `market`, `ollama_manager`, `webui`, `auth_manager`, `calendar_manager`, `chat`, `douyin_downloader`, `file_manager`, `studio3d`, `universal_tracker`). A further **19 studios** — web crawler, video downloader, subtitle extractor, TTS, content/POD/graphic studio, livestream, sheets and more — install in one click from the in-dashboard marketplace.

*v2026.07.30.1 · 394 commits · Python 3.9+ / FastAPI / Vue / Three.js · MIT · all numbers measured 2026-07-30*

---

## Why people pick it

- **"It generated a scaffold, not a website."** The deploy runner executes nine real steps against *your* Cloudflare account and does not stop until a URL answers. You can read every step in the repo. See the caveat above — it is real, not magic.
- **"The framework is free, but I'm not allowed to resell it."** TubeCLI is MIT: multi-tenant deployment, white-labelling and reselling are all permitted. For contrast, n8n's Sustainable Use License forbids reselling it as a hosted service, and Dify's modified Apache license forbids operating a multi-tenant environment and forbids removing their logo. *(CrewAI, LangGraph and OpenHands are MIT too — this argument does not apply to them.)*
- **"My agent burned tokens deciding what to do."** Common flows are routed by zero-token fast paths — deterministic intent matching that never calls a model. The LLM is used where judgement is actually needed.
- **"I don't want my clients' credentials in someone else's cloud."** Everything runs on your hardware. Your keys stay in your own `data/` directory, and with local Ollama the system needs no external API at all.
- **"An agent did something irreversible."** The Codex queue gates it: AI-created tasks land in `pending_approval` and wait for a human before anything irreversible runs. Of 39 recorded tasks, 6 were rejected at that gate. Every task carries an append-only JSONL audit trail with step timings and retry counters.

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

## How TubeCLI compares

Measured 2026-07-30. Rows where TubeCLI loses are marked plainly — if you need those, use one of the others.

| | **TubeCLI** | n8n | Dify | CrewAI | LangGraph | OpenHands |
|---|---|---|---|---|---|---|
| GitHub stars | **166** | 198k | 150k | 56k | 38k | 82k |
| What it sells | Work already finished | Workflow platform | Agentic workflow builder | Agent framework | Low-level orchestration | Coding-agent control center |
| License | **MIT** | Sustainable Use | Modified Apache | MIT | MIT | MIT |
| Resell as a hosted service | **Yes** | **No** | **No** | Yes | Yes | Yes |
| Multi-tenant / white-label | **Yes** | **No** | **No** (logo must stay) | Yes | Yes | Yes |
| Self-host | Yes | Yes | Yes | Yes | Yes | Yes |
| Local LLM first-class (Ollama) | **Yes** | Partial | Partial | Via config | Via config | Partial |
| Zero-token fast paths | **Yes** | n/a | No | No | No | No |
| Deploys a site to Cloudflare Workers end-to-end | **Yes** (see caveat) | No | No | No | No | No |
| Crawl → draft with an LLM → publish to WordPress | **Yes** | Build it yourself | Build it yourself | Build it yourself | Build it yourself | No |
| Subtitle extract + translate (3 engines, SRT/VTT/ASS) | **Yes** | No | No | No | No | No |
| Browser automation with TOTP 2FA | Yes (2FA flaky) | Via nodes | No | No | No | No |
| Human approval gate on irreversible steps | **Yes, enforced** | Manual | No | No | Build it yourself | Partial |
| Telegram as a control plane | **Yes** | Via nodes | No | No | No | No |
| No-code visual builder | **No** | **Yes** | **Yes** | No | No | Partial |
| MCP support | **No** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |
| Prebuilt integrations | ~36 extensions | **400+** | Large | Large | Large | Large |
| Managed cloud option | **No** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |
| Enterprise support / SSO / audit | **No** | **Yes** | **Yes** | **Yes** | **Yes** | Partial |
| Battle-tested at scale | **No — early** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

**Caveat on Cloudflare deploys:** real but not one-click — 1 of the 4 most recent attempts finished clean, and admin-password seeding can fall back to the template default.

**Where TubeCLI honestly loses:** no MCP server, no no-code builder, no managed cloud, no enterprise SSO/audit trail, ~36 extensions against n8n's 400+ integrations, and 166 stars against 198k. It is early software.

**Where the license comparison does *not* apply:** CrewAI, LangGraph and OpenHands are MIT too — the resale argument only beats n8n, Dify and AutoGPT's platform. Against CrewAI and LangGraph the difference is that they hand you building blocks, while TubeCLI hands you a `wrangler deploy` that already ran.

## FAQ

### What is TubeCLI?
TubeCLI is a self-hosted, open-source AI agent team that executes operational work end to end — deploying websites to Cloudflare Workers, crawling the web and publishing to WordPress, extracting and translating video subtitles, and automating browsers. It ships 17 built-in extensions plus 19 marketplace studios, and runs from the CLI, a web dashboard, or Telegram.

### Is TubeCLI free?
Yes. MIT licensed, no paid tier, no seat limits, no credit meter. You may run it for paying clients, multi-tenant and white-labelled, without asking permission. Your only costs are your own infrastructure and whatever LLM you point it at — which can be $0 if you use local Ollama.

### Does TubeCLI need an API key?
No. Point it at local [Ollama](https://ollama.com) and it runs with no API key and no per-token cost. If you prefer cloud models it supports Gemini, OpenAI, Claude, DeepSeek, Grok and OpenRouter with your own keys. Note that the shipped default is a cloud model, so switch the default to Ollama if you want fully local operation.

### Can TubeCLI actually deploy a website?
Yes, genuinely — not a scaffold. Its deploy runner performs `git clone` → `npm install` → `wrangler d1 create` + `r2 bucket create` → remote schema apply → OpenNext build → `wrangler deploy` against your own Cloudflare account, and you can read all 435 lines of it in this repo. It is not one-click: 1 of the 4 most recent attempts finished clean, and admin seeding can leave the template default password. It fails loudly rather than silently.

### How is TubeCLI different from LangChain, CrewAI, or AutoGPT?
Those give you building blocks to construct an agent; you still write the supervisor, the deploy step, and the publishing step yourself. TubeCLI ships the finished tools — a 435-line Cloudflare deploy runner, a WordPress publisher that speaks WP REST with app-password auth, a three-engine subtitle pipeline. You operate it rather than program it.

### Is TubeCLI a self-hosted Manus alternative?
For operational tasks, yes — both aim at an agent that uses real tools rather than returning code. The differences that matter: TubeCLI runs on your hardware, has no credit meter, is MIT so you can resell it, and can run entirely on a local model. It is far less polished and far less battle-tested than a funded hosted product.

### Can I run TubeCLI for my clients and charge for it?
Yes, and this is a deliberate differentiator. MIT permits multi-tenant deployment, white-labelling, and reselling. For contrast: n8n's Sustainable Use License forbids reselling it as a hosted service, and Dify's modified Apache license forbids operating a multi-tenant environment and forbids removing their logo.

### What LLM providers does TubeCLI support?
Local Ollama, plus six cloud providers: Gemini, OpenAI, Claude, DeepSeek, Grok and OpenRouter. Keys are managed per provider in the dashboard, models are switchable per agent, and critical flows use zero-token fast paths that never call a model at all.

### Does TubeCLI support MCP?
No. There is no MCP server or MCP client in the repo today, and any list claiming otherwise is wrong. If MCP is a requirement, use n8n, Dify, CrewAI or LangGraph instead. Wrapping the existing extensions in an MCP server is on the roadmap.

### Can TubeCLI translate and burn subtitles?
Extraction and translation are proven: three interchangeable engines (local Whisper, Gemini, YouTube CC) exporting SRT/JSON/VTT/ASS, with a 559-cue Vietnamese SRT and matching 559-cue English translation on disk. Burn-in and hardsub removal (ffmpeg delogo/blur/pixel/fill with OpenCV region detection) are implemented and reviewable but have no completed end-to-end run yet — treat them as experimental.

### How do I stop an agent from doing something irreversible?
The Codex queue gates it. AI-created tasks land in `pending_approval` and wait for a human to accept or reject before anything irreversible runs — deploying, publishing, deleting. Every task carries an append-only JSONL audit trail with step timings and retry counters. Of 39 recorded tasks, 6 were rejected at the gate.

### Is TubeCLI production-ready?
Parts of it are. Browser automation and subtitle extraction/translation have the most logged runs. WordPress publishing works over the WP REST API. Cloudflare deploys work but need supervision. The full video reup chain and multi-agent org-chart delegation are not proven yet. Treat it as capable early software with an honest changelog, not as enterprise infrastructure.

## 🧠 Architecture Overview

```
tubecli/
├── tubecli/           # Main package
│   ├── api/           # REST API server (FastAPI)
│   ├── cli/           # CLI command modules
│   ├── core/          # Core business logic
│   ├── extensions/    # 17 built-in extensions (each with its own SKILL.md)
│   ├── nodes/         # Workflow node implementations
│   └── skills/        # Built-in system skills
├── READMEs/           # Translated documentation (9 languages)
├── docs/              # Project website
├── data/              # Runtime DB & state (gitignored)
└── tests/             # Test suite
```

## 📖 AI-Readable Documentation

TubeCLI is designed so that an AI agent can understand and operate it without a human walkthrough:

- **`llms.txt`** at the repository root — a compact, machine-readable map of what the system is, what it can do, and what it explicitly cannot do.
- **`SKILL.md` inside every extension** (`tubecli/extensions/*/SKILL.md`) — endpoints, parameters, trigger commands and worked examples, written for LLMs rather than humans.

External agents (Claude, GPT, Gemini) can read these files to learn how to drive the system, write extensions, and debug workflows autonomously.

## 📝 License

[MIT](LICENSE) — you may use, modify, self-host, white-label and resell this software, including for paying clients. Made with 🤖 by the TubeCreate Team.
