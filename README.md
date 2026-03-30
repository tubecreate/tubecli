# ⚡ TubeCLI — 终极开源 AI Agents 生态协同系统

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

一个集成了本地安装、多代理管理以及可视化编排等全面能力的 **AI Agents** 智能操作系统。该系统底层基于命令行 (CLI) 形态流转，上层则拥有极具科幻感的全栈生态面板。通过我们专为大语言模型打造的三大核心矩阵：**Agents Browser**（智能体浏览器宇宙）、**Agents Workflow**（多智能体工作流引擎）以及 **Agents Studio World**（3D多智能体协同视觉世界），您可以轻松让各类自治 AI Agents 理解并接管您的数字工作区。

---

## 🌟 核心理念与三大矩阵

由 TubeCLI 引领的智能终端架构彻底改变了 AI 行事的维度。我们将其拆分为以下三个极其强大的功能矩阵：

### 🌐 1. Agents Browser (智能体浏览器矩阵)
不再受限于普通 API！通过 **Agents Browser** 环境映射集，我们允许 AI Agents 获取、启动并控制独立沙箱浏览器环境 (Browser Profiles)。具备高度拟真的指纹克隆 (Fingerprints)、原生级多开以及自动绕过反爬机制的强力穿透。无论你是挂载自动多端社媒运营、批量读取本地或网页内容，Agents 从此具备了全自动巡航互联网的能力（内嵌免代理与 TOTP 2FA 登录）。

### ⚡ 2. Agents Workflow (多智能体工作流引擎)
全自动流转业务！**Agents Workflow** 是系统的“超级骨髓”。它是一个极度现代化的 DAG 节点执行器。通过控制面板可视化的接管环境面板，用户可以自由拖拽节点构建连线任务。
- 支持单条 Workflow 逻辑里随意拔插、调用基于 Ollama 跑出的私有模型（或云API如 DeepSeek/GPT）。
- 实时滑动属性表盘 (Sliding property panels)。让复杂的多 AI 智能流互传变量变得犹如呼吸般简单。

### 🏢 3. Agents Studio World (3D 多智能体视觉世界)
不仅仅是代码，现在你的 Agents 有了他们的三维容身之所！**Agents Studio World** 提供了一整套用 Three.js 构建的等距立体化物理生成空间 (Procedural Isometric 3D)。
- 您可利用自然语言 Prompt 指导 AI 建房布置家具（如自动排布U型圆桌、植被盆栽、会议室工作站）。
- **Agents 团队 (Teams Agents) 组织挂载：** 在物理沙盘世界将您的虚拟智能体拉入团队架构并落实至各个座位，进行有机的角色委派和沟通反馈机制！

---

## 🚀 极速启动与安装环境

### 前置要求
- Python 3.9 或以上版本
- Ollama (可选要求，主要运行本地大算力底层模型)
- Git 

### 1. 克隆代码与快速安装
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. 初始化核心系统工作区
只需执行该命令，ZhiYing 内核将会被写入电脑本地进行数据化装载与编译模块，拉取相关的核心内置执行库（如 `webui`, `browser`, `studio3d` 等）：
```bash
tubecli init --lang zh
```
*(一旦执行成功，您可以全天候随时敲入 `tubecli` 弹出中文大盘面)*

### 3. 点火激活终端大屏 (Web Dashboard)
后台启动控制服务器。一旦启动，CLI 变身超级引擎服务：
```bash
tubecli api start --port 5295
```
直接利用任一现代浏览器访问控制台： **http://localhost:5295/dashboard**


---

## 💻 原生 CLI 极客指南

对于资深的 Terminal 终端开发者，系统依然为您保留了极致且纯粹的无头 (Headless) 调配通道：

### 组织你的 Agents (Agent Management)
```bash
tubecli agent create "财务专员" --description "负责整理发票与核算"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### 发号施令 (Skill Execution)
```bash
tubecli skill list
tubecli skill run "一键智能摘要总结" --input "贴入超过10万字的长文本..."
```

### 后台编排与接口调用 (Workflow & APIs)
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <指向_某处_workflow_流文件.json>
```

### 广袤插件海洋 (Extensions & Market)
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo优化"
tubecli market install "seo-analyzer"
```

---

## 🧠 大局架空全景鸟瞰

```text
tubecli/
├── tubecli/           # 整个体系的发动机机核
│   ├── api/           # 高并发 REST API 发信器 (FastAPI驱动)
│   ├── cli/           # Shell 壳指令中枢
│   ├── core/          # 大脑黑盒与业务逻辑闭环
│   ├── extensions/    # 各种插件体系源 (Agents Browser, Market, Studio3D)
│   ├── nodes/         # Workflow 执行器里被执行的最细小颗粒度原子业务逻辑
│   └── skills/        # 植入体内的首发超能力
├── .agents/           # 供 LLM 阅读的自我繁育文档 (SKILL.md)
├── data/              # 安全本地跑出来的活体数据与流配置
└── tests/             # QA 集群
```

## 📖 写给外部 AI 阅读的奇妙物语 (.agents/)
这是一个独特的底层理念。在我们的工程架构里，常常会有一份 `SKILL.md` 的指引存留于各个特定文件夹内。当您将诸如 GPT-4 / Claude / Gemini 引入我们的源码，外部的这些最高智核只需简单一读 `SKILL.md`，就能彻底领会 **Agents Workflow** 等工作流该如何编写执行逻辑规范。这使得整个系统能够进行全自动自我进化！

---

## 📝 授权许可与开源声明
MIT License - Made with 🤖 by TubeCreate Team
