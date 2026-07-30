# ⚡ TubeCLI — 開源 AI Agent CLI 系統

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <b>繁體中文</b> | 
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

一個無頭（headless）的 CLI 系統，用於安裝、管理和協調 **AI Agent**、**技能（skills）**和**工作流（workflows）**。專為 AI Agent 設計，使其能夠自主理解、安裝和運行整個系統。

![3D Studio Office Builder](../screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](../screenshots/studio3d_teams.png)

## 🌟 主要功能

該系統已演變為一個完整的 12 子系統架構：

- 💬 **Chat** — 整個系統的統一對話介面。支持多會話對話串與持久化歷史記錄、Agent 選擇器（或自動路由至合適的專職 Agent），以及 Markdown 渲染。每一輪對話都會執行完整流程 — 零 token 意圖分類、技能選擇，然後才交給模型 — 因此 Telegram 機器人能做的事，瀏覽器同樣能做。
- 📋 **Codex** — Agent 化工作的任務中控台。您或 AI 創建一個任務，將其委派給某個 Agent 或團隊，核准之後由後台工作程序執行，同時您可以觀看步驟時間軸。結果會回傳供您審核。任務具備持久性，重啟後依然存在，且每個任務都有完整的稽核紀錄。
- 🤖 **Agent Manager** — 創建和管理具有角色設定（persona）、日常例程（routine）和技能（skill）的 AI Agent。
- ⚡ **Skill System** — 帶標籤的可執行工作流（Workflow, API, Markdown），配備 Markdown 查看器和即時執行模態框。
- 🔄 **Workflow Engine & Builder** — 基於 DAG 的工作流執行器。WebUI 提供了現代化的節點生成器，包含緊湊的節點、上下文滑動屬性面板以及動態模型選擇（本地 Ollama / 雲端 API）。
- 🎨 **Web Dashboard** — 位於 `localhost:5295/dashboard` 的全面 SPA（單頁應用），用於視覺化管理 Agent、工作流、技能、市場和設置，並原生監控瀏覽器。
- 👥 **Teams Agents** — 使用組織結構圖協調多個 Agent。通過邏輯模板或拖放來分配角色。任務分配通過團隊依據順序、並行或層級策略路由工作。
- 🏢 **3D Studio (Teams 3D)** — 使用 Three.js 的等距 3D 視覺化。支持多座家具（會議桌、談判桌）以及智能內向算法、射線檢測（raycasting）組操作和 15+ 內置資產。
- 🎬 **Story Engine & Player** — 通過劇本編輯器根據提示生成交互式 3D 故事。Agent 在動畫場景播放器內通過 3D 氣泡進行交流。
- 🔌 **Extension Manager** — 可插拔架構。內置擴充包括 `chat`、`codex`、`browser`、`browser_scripts`、`webui`、`market`、`multi_agents`、`studio3d`、`cloud_api` 等。每個擴充都能提供 CLI 命令、API 路由、工作流節點、Telegram 動作以及自己的 UI 頁面。
- 🌐 **Browser Automation** — 協調瀏覽器配置、代理、指紋。內置帶有 TOTP 雙因素認證（2FA）的谷歌自動登入。
- 🛒 **Marketplace** — 通過線上註冊表發現、安裝和分享社區技能。
- 📨 **Telegram Bridge** — 通過 Telegram 機器人操作同一套系統：意圖路由、技能執行、任務核准，以及長時間任務完成時的主動通知。

## 🚀 快速開始與安裝

### 選項 1: 一鍵自動安裝（推薦使用者使用）
**Windows系統：** 打開 **PowerShell** (以系統管理員身分執行) 並貼上以下命令：
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_zh-TW.ps1 | iex"
```
 
**Linux / MacOS系統：** 打開終端機並執行：
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_zh-TW.sh | bash
```

它會自動安裝 Python, Git（若缺失），克隆倉庫並為您從 A-Z 設置好一切。

### 選項 2: 手動安裝（推薦開發者使用）

#### 前提條件
- Python 3.9+
- Ollama (可選，本地 AI 執行所需)
- Git

#### 1. 克隆與安裝
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. 初始化工作空間
執行初始化命令以設置 `data/` 目錄、提取預設技能、激活核心擴充並配置預設埠。
```bash
tubecli init --lang zh --port 5295
```

### 3. 啟動 Web 控制面板
初始化後，啟動 API 伺服器以訪問 GUI。
```bash
tubecli api start
```
打開瀏覽器並訪問：**http://localhost:5295/dashboard**

## 💻 命令行用法

如果您更喜歡無頭方式，可以直接從終端機管理整個系統：

### Agent 管理
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### 技能執行
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

### 任務看板 (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> AI 創建的任務在執行前一律會等待您的核准。

### 擴充與市場
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> 擴充的 API 路由是在伺服器導入它們時綁定的，因此啟用或新增擴充後請**重啟伺服器**。

## 🧠 架構概述

```
tubecli/
├── tubecli/           # 主包
│   ├── api/           # REST API 伺服器 (FastAPI)
│   ├── cli/           # CLI 命令模組
│   ├── core/          # 核心業務邏輯
│   ├── extensions/    # 擴充 (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # 工作流節點實現
│   └── skills/        # 內置系統技能
├── .agents/           # AI 可讀文檔 (SKILL.md)
├── data/              # 運行時的資料庫與狀態 (已 gitignored)
└── tests/             # 測試套件
```

## 📖 AI 可讀文檔
`.agents/` 和 skills 資料夾包含專門為 LLM 打造的文檔 (`SKILL.md`)。外部 AI Agent（如 Claude 或 GPT-4）可以讀取這些文件，以完全自主地學習如何運行 TubeCLI 系統、編寫插件和調試工作流，無需人工干預。

## 📝 許可證
MIT 許可證 - 由 TubeCreate 團隊用 🤖 傾情打造
