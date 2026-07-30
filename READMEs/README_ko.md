# ⚡ TubeCLI — 오픈 소스 AI 에이전트 CLI 시스템

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <b>한국어</b> | 
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

**AI 에이전트**, **기술(skills)**, 및 **워크플로(workflows)**를 설치, 관리 및 오케스트레이션하기 위한 헤드리스 CLI 시스템. AI 에이전트가 시스템 전체를 자율적으로 이해하고 설치 및 운영할 수 있도록 설계되었습니다.

![3D Studio Office Builder](../screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](../screenshots/studio3d_teams.png)

## 🌟 주요 기능

시스템은 12개의 핵심 하위 시스템 아키텍처로 발전했습니다:

- 💬 **Chat** — 시스템 전체를 아우르는 통합 대화 인터페이스입니다. 영구적으로 보존되는 기록을 갖춘 다중 세션 스레드, 에이전트 선택기(또는 적합한 전문 에이전트로의 자동 라우팅), 마크다운 렌더링을 제공합니다. 모든 대화 턴은 전체 파이프라인(토큰을 소모하지 않는 의도 분류, 기술 선택, 그다음 모델 호출)을 거치므로, 텔레그램 봇으로 할 수 있는 모든 작업을 브라우저에서도 할 수 있습니다.
- 📋 **Codex** — 에이전트 작업을 위한 미션 컨트롤입니다. 사용자 또는 AI가 작업을 생성하고, 에이전트나 팀에 위임하고, 승인하면 백그라운드 워커가 이를 실행하는 동안 단계별 타임라인을 확인할 수 있습니다. 결과는 검토를 위해 다시 전달됩니다. 작업은 영구적으로 저장되어 재시작 후에도 유지되며, 작업마다 전체 감사 기록이 남습니다.
- 🤖 **Agent Manager** — 페르소나, 루틴, 기술을 가진 AI 에이전트를 생성하고 관리합니다.
- ⚡ **Skill System** — 마크다운 뷰어 및 실시간 실행 모달을 지원하며 태그(워크플로, API, 마크다운)로 표시된 실행 가능한 워크플로입니다.
- 🔄 **Workflow Engine & Builder** — DAG 기반 워크플로 실행기. WebUI는 컴팩트한 노드, 컨텍스트 슬라이딩 속성 패널, 동적 모델 선택(로컬 Ollama / 클라우드 API) 기능을 갖춘 최신 노드 기반 빌더를 제공합니다.
- 🎨 **Web Dashboard** — 에이전트, 워크플로, 기술, 마켓플레이스, 설정을 시각적으로 관리하고 브라우저를 네이티브로 모니터링할 수 있는 `localhost:5295/dashboard`에 위치한 종합 SPA(싱글 페이지 애플리케이션)입니다.
- 👥 **Teams Agents** — 조직도를 사용하여 여러 에이전트를 조정합니다. 논리 템플릿 또는 드래그 앤 드롭을 통해 역할을 할당합니다. 작업 위임은 순차적, 병렬적 또는 계층적 전략에 따라 팀을 통해 작업을 라우팅합니다.
- 🏢 **3D Studio (Teams 3D)** — Three.js를 사용한 등각 투영 절차적 3D 시각화. 지능형 안쪽 방향 정렬 알고리즘, 레이캐스팅 그룹 조작, 15개 이상의 내장 에셋이 포함된 다인승 가구(회의 테이블 등)를 지원합니다.
- 🎬 **Story Engine & Player** — 스크립트 에디터를 사용하여 프롬프트에서 인터랙티브 3D 스토리를 생성합니다. 에이전트는 애니메이션 장면 플레이어 내에서 3D 말풍선으로 통신합니다.
- 🔌 **Extension Manager** — 플러그인 가능 아키텍처. 내장 확장에는 `chat`, `codex`, `browser`, `browser_scripts`, `webui`, `market`, `multi_agents`, `studio3d`, `cloud_api` 등이 포함됩니다. 각 확장은 CLI 명령, API 라우트, 워크플로 노드, 텔레그램 액션 및 자체 UI 페이지를 제공합니다.
- 🌐 **Browser Automation** — 브라우저 프로필, 프록시, 지문을 오케스트레이션합니다. TOTP 2FA가 통합된 Google 자동 로그인이 포함되어 있습니다.
- 🛒 **Marketplace** — 온라인 레지스트리를 통해 커뮤니티 기술을 탐색, 설치 및 공유합니다.
- 📨 **Telegram Bridge** — 텔레그램 봇에서 동일한 시스템을 제어합니다: 의도 라우팅, 기술 실행, 작업 승인, 그리고 장시간 실행되는 작업이 완료되었을 때의 능동적 알림을 지원합니다.

## 🚀 빠른 시작 & 설치

### 옵션 1: 원클릭 자동 설치 (사용자 권장)
**Windows:** **PowerShell** (관리자 권한으로 실행)을 열고 다음 명령을 붙여넣습니다:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_ko.ps1 | iex"
```

**Linux / MacOS:** 터미널을 열고 다음을 실행합니다:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_ko.sh | bash
```

Python, Git (없는 경우)을 자동으로 설치하고 리포지토리를 클론하여 모든 설정을 완료합니다.

### 옵션 2: 수동 설치 (개발자용)

#### 요구 사항
- Python 3.9+
- Ollama (선택 사항, 로컬 AI 실행 시 필요)
- Git

#### 1. 클론 & 설치
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. 작업 공간 초기화
초기화 명령을 실행하여 `data/` 디렉터리를 설정하고, 기본 기술을 추출하고, 핵심 확장을 활성화하고, 기본 포트를 구성합니다.
```bash
tubecli init --lang ko --port 5295
```

### 3. 웹 대시보드 시작
초기화 후, API 서버를 시작하여 GUI에 접속합니다.
```bash
tubecli api start
```
브라우저를 열고 다음 주소로 이동합니다: **http://localhost:5295/dashboard**

## 💻 CLI 사용법

헤드리스 방식을 선호하는 경우 터미널에서 직접 전체 시스템을 관리할 수 있습니다:

### 에이전트 관리
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### 기술 실행
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API & 워크플로
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### 작업 보드 (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> AI가 생성한 작업은 실행되기 전에 항상 사용자의 승인을 기다립니다.

### 확장 기능 & 마켓
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> 확장 기능은 서버가 이를 임포트할 때 API 라우트를 바인딩하므로, 확장을 활성화하거나 추가한 후에는 **서버를 재시작**하세요.

## 🧠 아키텍처 개요

```
tubecli/
├── tubecli/           # 메인 패키지
│   ├── api/           # REST API 서버 (FastAPI)
│   ├── cli/           # CLI 명령 모듈
│   ├── core/          # 코어 비즈니스 로직
│   ├── extensions/    # 확장 기능 (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # 워크플로 노드 구현체
│   └── skills/        # 내장 시스템 기술
├── .agents/           # AI가 읽을 수 있는 문서 (SKILL.md)
├── data/              # 런타임 DB & 상태 (gitignored)
└── tests/             # 테스트 스위트
```

## 📖 AI가 읽을 수 있는 문서
`.agents/` 및 skills 폴더에는 LLM용으로 특별히 제작된 문서(`SKILL.md`)가 포함되어 있습니다. 외부 AI 에이전트(Claude 또는 GPT-4 등)는 사람이 개입하지 않고도 이 파일들을 읽어 TubeCLI 시스템을 작동하고, 플러그인을 작성하며, 워크플로를 디버깅하는 방법을 완전히 자율적으로 학습할 수 있습니다.

## 📝 라이선스
MIT 라이선스 - TubeCreate 팀이 🤖와 함께 제작
