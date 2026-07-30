# ⚡ TubeCLI — 开源 AI Agent CLI 系统

<p align="center">
  <a href="../README.md">English</a> | 
  <b>简体中文</b> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <a href="README_ko.md">한국어</a> | 
  <a href="README_es.md">Español</a> | 
  <a href="README_tr.md">Türkçe</a> | 
  <a href="README_ru.md">Русский</a> | 
  <a href="README_vi.md">Tiếng Việt</a>
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

一个无头（headless）的 CLI 系统，用于安装、管理和编排 **AI Agent**、**技能（skills）**和**工作流（workflows）**。专为 AI Agent 设计，使其能够自主理解、安装和运行整个系统。

![3D Studio Office Builder](../screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](../screenshots/studio3d_teams.png)

## 🌟 主要功能

该系统已演变为一个完整的 12 子系统架构：

- 💬 **Chat** — 面向整个系统的统一对话界面。支持多会话线程与持久化历史记录、Agent 选择器（或自动路由到合适的专职 Agent）以及 Markdown 渲染。每一轮对话都会执行完整流水线——零 token 意图分类、技能选择，然后调用模型——因此 Telegram 机器人能做的一切，在浏览器中同样可以完成。
- 📋 **Codex** — Agent 化工作的任务中枢。您或 AI 创建任务，将其分派给某个 Agent 或团队，批准后由后台工作进程执行，同时您可以观看步骤时间线。结果会返回供您审阅。任务是持久化的，重启后依然存在，并且每个任务都有完整的审计记录。
- 🤖 **Agent Manager** — 创建和管理具有角色设定（persona）、日常例程（routine）和技能（skill）的 AI Agent。
- ⚡ **Skill System** — 带标签的可执行工作流（Workflow, API, Markdown），配备 Markdown 查看器和实时执行模态框。
- 🔄 **Workflow Engine & Builder** — 基于 DAG 的工作流执行器。WebUI 提供了现代化的节点生成器，包含紧凑的节点、上下文滑动属性面板以及动态模型选择（本地 Ollama / 云端 API）。
- 🎨 **Web Dashboard** — 位于 `localhost:5295/dashboard` 的全面 SPA（单页应用），用于可视化管理 Agent、工作流、技能、市场和设置，并原生监控浏览器。
- 👥 **Teams Agents** — 使用组织结构图编排多个 Agent。通过逻辑模板或拖放来分配角色。任务分配通过团队依据顺序、并行或层级策略路由工作。
- 🏢 **3D Studio (Teams 3D)** — 使用 Three.js 的等距 3D 可视化。支持多座家具（会议桌、谈判桌）以及智能内向算法、射线检测（raycasting）组操作和 15+ 内置资产。
- 🎬 **Story Engine & Player** — 通过剧本编辑器根据提示生成交互式 3D 故事。Agent 在动画场景播放器内通过 3D 气泡进行交流。
- 🔌 **Extension Manager** — 可插拔架构。内置扩展包括 `chat`、`codex`、`browser`、`browser_scripts`、`webui`、`market`、`multi_agents`、`studio3d`、`cloud_api` 等。每个扩展都可以提供 CLI 命令、API 路由、工作流节点、Telegram 动作以及自己的 UI 页面。
- 🌐 **Browser Automation** — 编排浏览器配置、代理、指纹。内置带有 TOTP 双因素认证（2FA）的谷歌自动登录。
- 🛒 **Marketplace** — 通过在线注册表发现、安装和分享社区技能。
- 📨 **Telegram Bridge** — 通过 Telegram 机器人驱动同一套系统：意图路由、技能执行、任务审批，以及长时间任务完成时的主动通知。

## 🚀 快速开始与安装

### 选项 1: 一键自动安装（推荐用户使用）
**Windows系统：** 打开 **PowerShell** (以管理员身份运行) 并粘贴以下命令：
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_zh.ps1 | iex"
```

**Linux / MacOS系统：** 打开终端并运行：
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_zh.sh | bash
```

它会自动安装 Python, Git（若缺失），克隆仓库并为您从 A-Z 设置好一切。

### 选项 2: 手动安装（推荐开发者使用）

#### 前提条件
- Python 3.9+
- Ollama (可选，本地 AI 执行所需)
- Git

#### 1. 克隆与安装
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. 初始化工作空间
运行初始化命令以设置 `data/` 目录、提取默认技能、激活核心扩展并配置默认端口。
```bash
tubecli init --lang zh --port 5295
```

### 3. 启动 Web 控制面板
初始化后，启动 API 服务器以访问 GUI。
```bash
tubecli api start
```
打开浏览器并访问：**http://localhost:5295/dashboard**

## 💻 命令行用法

如果您更喜欢无头方式，可以直接从终端管理整个系统：

### Agent 管理
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### 技能执行
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API 和工作流
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### 任务看板 (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> AI 创建的任务在运行前始终会等待您的批准。

### 扩展与市场
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> 扩展的 API 路由是在服务器导入它们时绑定的，因此启用或添加扩展后请**重启服务器**。

## 🧠 架构概述

```
tubecli/
├── tubecli/           # 主包
│   ├── api/           # REST API 服务器 (FastAPI)
│   ├── cli/           # CLI 命令模块
│   ├── core/          # 核心业务逻辑
│   ├── extensions/    # 扩展 (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # 工作流节点实现
│   └── skills/        # 内置系统技能
├── .agents/           # AI 可读文档 (SKILL.md)
├── data/              # 运行时的数据库与状态 (已 gitignored)
└── tests/             # 测试套件
```

## 📖 AI 可读文档
`.agents/` 和 skills 文件夹包含专门为 LLM 打造的文档 (`SKILL.md`)。外部 AI Agent（如 Claude 或 GPT-4）可以读取这些文件，以完全自主地学习如何运行 TubeCLI 系统、编写插件和调试工作流，无需人工干预。

## 📝 许可证
MIT 许可证 - 由 TubeCreate 团队用 🤖 倾情打造
