# ⚡ TubeCLI — Hệ thống CLI Agent AI mã nguồn mở

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <a href="README_ko.md">한국어</a> | 
  <a href="README_es.md">Español</a> | 
  <a href="README_tr.md">Türkçe</a> | 
  <a href="README_ru.md">Русский</a> | 
  <b>Tiếng Việt</b>
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

Hệ thống CLI không giao diện (headless) để cài đặt, quản lý và điều phối các **agent AI**, **skill (kỹ năng)** và **workflow (luồng công việc)**. Được thiết kế để các agent AI có thể tự hiểu, cài đặt và vận hành toàn bộ hệ thống một cách tự động.

![3D Studio Office Builder](../screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](../screenshots/studio3d_teams.png)

## 🌟 Tính năng chính

Hệ thống đã phát triển thành một kiến trúc hoàn chỉnh gồm 12 phân hệ chính:

- 💬 **Chat** — Giao diện hội thoại hợp nhất cho toàn bộ hệ thống. Hỗ trợ nhiều phiên trò chuyện với lịch sử được lưu bền, bộ chọn agent (hoặc tự động định tuyến tới đúng chuyên gia) và hiển thị markdown. Mỗi lượt trò chuyện đều chạy qua toàn bộ pipeline — phân loại ý định không tốn token, chọn skill, rồi mới tới model — nên bất cứ điều gì bot Telegram làm được thì trình duyệt cũng làm được.
- 📋 **Codex** — Trung tâm điều hành cho các tác vụ agent. Bạn hoặc AI tạo một tác vụ, ủy thác cho một agent hoặc một nhóm, phê duyệt nó, và một worker chạy nền sẽ thực thi trong khi bạn theo dõi dòng thời gian từng bước. Kết quả được trả về để bạn xem xét. Các tác vụ được lưu bền và vẫn còn nguyên sau khi khởi động lại, kèm nhật ký kiểm toán đầy đủ cho từng tác vụ.
- 🤖 **Agent Manager** — Tạo và quản lý các agent AI với tính cách (persona), thói quen (routine) và kỹ năng (skill).
- ⚡ **Skill System** — Các quy trình công việc có thể thực thi được gắn thẻ (Workflow, API, Markdown) với Trình xem Markdown và Giao diện thực thi thời gian thực.
- 🔄 **Workflow Engine & Builder** — Trình thực thi workflow dựa trên đồ thị DAG. Giao diện WebUI có trình tạo dạng node hiện đại với các nút nhỏ gọn, bảng thuộc tính trượt theo ngữ cảnh và chọn model động (Ollama cục bộ / API Cloud).
- 🎨 **Web Dashboard** — Ứng dụng SPA (Single Page Application) toàn diện tại `localhost:5295/dashboard` để quản lý trực quan các agent, workflow, skill, chợ ứng dụng (marketplace), cài đặt và giám sát trình duyệt gốc.
- 👥 **Teams Agents** — Điều phối nhiều agent bằng Sơ đồ tổ chức. Phân vai qua các mẫu logic hoặc kéo thả. Ủy thác công việc định tuyến qua nhóm theo các chiến lược tuần tự, song song hoặc phân cấp.
- 🏢 **3D Studio (Teams 3D)** — Trực quan hóa 3D thủ tục trực diện (isometric) sử dụng Three.js. Hỗ trợ nội thất nhiều chỗ ngồi (bàn họp, bàn hội nghị) với thuật toán xoay hướng thông minh, thao tác nhóm bằng raycasting và hơn 15 tài nguyên có sẵn.
- 🎬 **Story Engine & Player** — Tạo cốt truyện 3D tương tác từ prompt qua Trình soạn thảo kịch bản. Các agent giao tiếp qua bong bóng thoại 3D bên trong trình phát cảnh hoạt họa.
- 🔌 **Extension Manager** — Kiến trúc cắm (pluggable). Các extension tích hợp sẵn gồm `chat`, `codex`, `browser`, `browser_scripts`, `webui`, `market`, `multi_agents`, `studio3d`, `cloud_api` và nhiều hơn nữa. Mỗi extension đóng góp các lệnh CLI, tuyến API, node workflow, hành động Telegram và trang giao diện riêng.
- 🌐 **Browser Automation** — Điều phối cấu hình trình duyệt, proxy, dấu vân tay (fingerprint). Tích hợp tự động đăng nhập Google với TOTP 2FA.
- 🛒 **Marketplace** — Khám phá, cài đặt và chia sẻ kỹ năng cộng đồng qua sổ đăng ký trực tuyến.
- 📨 **Telegram Bridge** — Điều khiển chính hệ thống này từ một bot Telegram: định tuyến ý định, thực thi skill, phê duyệt tác vụ và thông báo chủ động khi các công việc chạy dài hoàn tất.

## 🚀 Hướng dẫn nhanh & Cài đặt

### Tùy chọn 1: Cài đặt tự động bằng một cú nhấp chuột (Khuyên dùng cho Người dùng)
**Dành cho Windows:** Mở **PowerShell** (Chạy với quyền Administrator) và dán lệnh sau:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_vi.ps1 | iex"
```

**Dành cho Linux / MacOS:** Mở terminal và chạy:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_vi.sh | bash
```

Hệ thống sẽ tự động cài đặt Python, Git (nếu thiếu), clone repo và thiết lập mọi thứ cho bạn từ A-Z.

### Tùy chọn 2: Cài đặt thủ công (Dành cho Lập trình viên)

#### Điều kiện tiên quyết
- Python 3.9+
- Ollama (Tùy chọn, cần cho chạy AI cục bộ)
- Git

#### 1. Clone & Cài đặt
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Khởi tạo không gian làm việc (Workspace)
Chạy lệnh khởi tạo để thiết lập thư mục `data/`, giải nén các skill mặc định, kích hoạt các extension cốt lõi và định cấu hình cổng mặc định.
```bash
tubecli init --lang vi --port 5295
```

### 3. Khởi động Web Dashboard
Sau khi khởi tạo, khởi động máy chủ API để truy cập GUI.
```bash
tubecli api start
```
Mở trình duyệt của bạn và truy cập: **http://localhost:5295/dashboard**

## 💻 Hướng dẫn sử dụng CLI

Quản lý toàn bộ hệ thống trực tiếp từ terminal nếu bạn thích phương pháp headless:

### Quản lý Agent
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### Thực thi Kỹ năng (Skill)
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

### Bảng tác vụ (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> Các tác vụ do AI tạo ra luôn chờ bạn phê duyệt trước khi chạy.

### Extensions & Chợ ứng dụng (Market)
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> Các extension chỉ gắn tuyến API của chúng khi máy chủ nạp (import) chúng, vì vậy hãy **khởi động lại máy chủ** sau khi bật hoặc thêm một extension.

## 🧠 Tổng quan kiến trúc

```
tubecli/
├── tubecli/           # Gói chính
│   ├── api/           # REST API server (FastAPI)
│   ├── cli/           # Các mô-đun lệnh CLI
│   ├── core/          # Logic nghiệp vụ cốt lõi
│   ├── extensions/    # Tiện ích mở rộng (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # Triển khai nút Workflow
│   └── skills/        # Kỹ năng hệ thống tích hợp sẵn
├── .agents/           # Tài liệu đọc cho AI (SKILL.md)
├── data/              # DB thời gian chạy & Trạng thái (được gitignore)
└── tests/             # Bộ kiểm thử
```

## 📖 Tài liệu đọc cho AI
Thư mục `.agents/` và `skills` chứa tài liệu được thiết kế riêng cho LLM (`SKILL.md`). Các agent AI bên ngoài (như Claude hoặc GPT-4) có thể đọc các file này để học cách vận hành hệ thống TubeCLI, viết plugin và gỡ lỗi workflow hoàn toàn tự động mà không cần sự can thiệp của con người.

## 📝 Giấy phép
Giấy phép MIT - Được thực hiện với 🤖 bởi Đội ngũ TubeCreate
