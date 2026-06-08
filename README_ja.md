# ⚡ TubeCLI — オープンソース AI Agent CLI システム

<p align="center">
  <a href="README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <b>日本語</b> | 
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

**AI エージェント**、**スキル**、および**ワークフロー**をインストール、管理、およびオーケストレーションするためのヘッドレス CLI システム。AI エージェントがシステム全体を自律的に理解、インストール、および操作できるように設計されています。

![3D Studio Office Builder](screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](screenshots/studio3d_teams.png)

## 🌟 主な機能

システムは、完全な 10 サブシステム アーキテクチャに進化しました：

- 🤖 **Agent Manager** — ペルソナ、ルーティン、スキルを持つ AI エージェントを作成および管理します。
- ⚡ **Skill System** — マークダウン ビューアとリアルタイム実行モーダルを備えた、タグ（ワークフロー、API、マークダウン）でマークされた実行可能ワークフロー。
- 🔄 **Workflow Engine & Builder** — DAG ベースのワークフロー実行エンジン。WebUI は、コンパクトなノード、コンテキスト スライディング プロパティ パネル、および動的なモデル選択（ローカル Ollama / クラウド API）を備えた最新のノードベース ビルダーを備えています。
- 🎨 **Web Dashboard** — エージェント、ワークフロー、スキル、マーケットプレイス、設定を視覚的に管理し、ブラウザをネイティブに監視するための `localhost:5295/dashboard` にある包括的な SPA（シングル ページ アプリケーション）。
- 👥 **Teams Agents** — 組織図を使用して複数のエージェントを調整します。論理テンプレートまたはドラッグ アンド ドロップを介して役割を割り当てます。タスクの委任は、シーケンシャル、並列、または階層的戦略に基づいて、チームを介して作業をルーティングします。
- 🏢 **3D Studio (Teams 3D)** — Three.js を使用した等角投影法によるプロシージャル 3D ビジュアライゼーション。インテリジェントな内向きアルゴリズム、レイキャスティング グループ操作、および 15 以上の組み込みアセットを備えた複数席の家具（会議用テーブルなど）をサポートします。
- 🎬 **Story Engine & Player** — スクリプト エディタを介してプロンプトからインタラクティブな 3D ストーリーを生成します。エージェントは、アニメーション化されたシーン プレーヤー内で 3D 吹き出しを介して通信します。
- 🔌 **Extension Manager** — `browser`、`webui`、`market`、および `studio3d` をサポートするプラグイン可能アーキテクチャ。CLI コマンドと API ルートのホットリロードを可能にします。
- 🌐 **Browser Automation** — ブラウザ プロファイル、プロキシ、フィンガープリントをオーケストレーションします。TOTP 2FA を使用した Google の自動ログインが組み込まれています。
- 🛒 **Marketplace** — オンライン レジストリを介してコミュニティ スキルを発見、インストール、共有します。

## 🚀 クイック スタート & インストール

### オプション 1: ワンクリック自動インストール (ユーザー向け推奨)
**Windowsの場合:** **PowerShell** (管理者として実行) を開き、次のコマンドを貼り付けます：
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1 | iex"
```

**Linux / MacOSの場合:** ターミナルを開き、次を実行します：
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install.sh | bash
```

Python、Git (ない場合) を自動的にインストールし、リポジトリをクローンして、すべてを自動的にセットアップします。

### オプション 2: 手動インストール (開発者向け)

#### 前提条件
- Python 3.9+
- Ollama (任意、ローカル AI 実行に必要)
- Git

#### 1. クローン & インストール
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. ワークスペースの初期化
初期化コマンドを実行して、`data/` ディレクトリのセットアップ、デフォルト スキルの抽出、コア拡張機能のアクティブ化、およびデフォルト ポートの設定を行います。
```bash
tubecli init --lang ja --port 5295
```

### 3. Web ダッシュボードの起動
初期化後、API サーバーを起動して GUI にアクセスします。
```bash
tubecli api start
```
ブラウザを開き、次のアドレスに移動します：**http://localhost:5295/dashboard**

## 💻 CLI の使用方法

ヘッドレス アプローチを好む場合は、ターミナルから直接システム全体を管理できます：

### エージェント管理
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### スキル実行
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API & ワークフロー
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### 拡張機能 & マーケット
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```

## 🧠 アーキテクチャの概要

```
tubecli/
├── tubecli/           # メイン パッケージ
│   ├── api/           # REST API サーバー (FastAPI)
│   ├── cli/           # CLI コマンド モジュール
│   ├── core/          # コア ビジネス ロジック
│   ├── extensions/    # 拡張機能 (Browser, WebUI, Market, Studio3D)
│   ├── nodes/         # ワークフロー ノードの実装
│   └── skills/        # 組み込みシステム スキル
├── .agents/           # AI 読み取り用ドキュメント (SKILL.md)
├── data/              # ランタイム DB & 状態 (gitignored)
└── tests/             # テスト スイート
```

## 📖 AI 読み取り用ドキュメント
`.agents/` および skills フォルダには、LLM 用に特別に作成されたドキュメント (`SKILL.md`) が含まれています。外部 AI エージェント (Claude や GPT-4 など) は、これらのファイルを読み取って、人間の介入なしに TubeCLI システムの操作方法、プラグインの作成方法、およびワークフローのデバッグ方法を完全に自律的に学習できます。

## 📝 ライセンス
MIT ライセンス - TubeCreate チームが 🤖 と共に作成
