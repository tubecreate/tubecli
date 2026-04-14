# SKILL: Xây Dựng Extension TubeCLI — Hướng Dẫn Chuẩn

> **Mục đích**: Tài liệu kỹ thuật để AI (hoặc dev) xây dựng extension TubeCLI **không lỗi**, bao gồm đầy đủ quy trình: cấu trúc file, manifest, route registration, i18n, sidebar integration.

---

## 1. Cấu Trúc Thư Mục Chuẩn

```
data/extensions_external/<extension_name>/
├── tubecli-extension.json     ← Manifest (BẮT BUỘC)
├── extension.py               ← Entry point Python (BẮT BUỘC)
├── SKILL.md                   ← Hướng dẫn cho AI chatbot
├── requirements.txt           ← Python dependencies (nếu có)
├── <api_routes>.py            ← FastAPI routes (tùy chọn)
├── nodes/                     ← Workflow nodes (tùy chọn)
│   └── <node_name>_node.py
├── static/                    ← UI tĩnh (HTML/CSS/JS)
│   ├── <main_page>.html
│   ├── <main_page>.css
│   ├── <main_page>.js
│   └── i18n/                  ← Đa ngôn ngữ
│       ├── en.json
│       ├── vi.json
│       └── zh.json
└── locales/                   ← Server-side i18n (API)
    ├── en.json
    └── vi.json
```

---

## 2. Manifest: `tubecli-extension.json`

### ⚠️ CRITICAL: Phải có `page_url` nếu extension có UI

```json
{
  "name": "my_extension",
  "version": "1.0.0",
  "description": "Mô tả ngắn gọn",
  "author": "TubeCreate",
  "entry": "extension.py",
  "extension_class": "MyExtension",
  "icon": "🎯",
  "dependencies": ["some-pip-package"],
  "nodes": ["my_node_type"],
  "skill_md": "SKILL.md",
  "ui_static": "static",
  "api_prefix": "/api/v1/my-ext",
  "page_url": "/my-extension",
  "min_tubecli_version": "0.3.0",
  "category": "extension",
  "tags": ["tag1", "tag2"],
  "license": "MIT"
}
```

### Giải thích các trường quan trọng:

| Trường | Bắt buộc | Mô tả |
|--------|----------|-------|
| `name` | ✅ | ID duy nhất, dùng `snake_case` (vd: `template_designer`) |
| `version` | ✅ | Semantic versioning |
| `entry` | ✅ | File Python chính |
| `extension_class` | ✅ | Tên class kế thừa `Extension` |
| `icon` | ⚠️ | Emoji hiển thị trên sidebar |
| `ui_static` | ⚠️ | Thư mục chứa file tĩnh (thường là `"static"`) |
| **`page_url`** | **⚠️ CRITICAL** | **URL để dashboard load UI dạng iframe. Format: `/<name-with-hyphens>`. Không có → KHÔNG HIỆN trên sidebar!** |
| `api_prefix` | ⚠️ | Prefix cho API routes |
| `nodes` | | Danh sách node types cho workflow |
| `skill_md` | | File SKILL.md cho AI agents |

### Quy tắc đặt tên:
- `name`: `snake_case` → `template_designer`
- `page_url`: `kebab-case` → `/template-designer`
- `api_prefix`: → `/api/v1/templates`

---

## 3. Extension Class: `extension.py`

```python
"""
Extension: My Extension
"""
import os
import logging
from typing import Dict, Any

logger = logging.getLogger('MyExtension')

# Khai báo data dir
def _data_dir():
    from tubecli.config import DATA_DIR
    d = os.path.join(DATA_DIR, "my_extension")
    os.makedirs(d, exist_ok=True)
    return d


class MyExtension:
    """Extension class — BaseClass tự inject bởi ExtensionManager."""

    # ── Lifecycle ────────────────────────────────────
    def on_install(self):
        """Gọi 1 lần khi extension được cài đặt."""
        d = _data_dir()
        os.makedirs(os.path.join(d, "data"), exist_ok=True)
        logger.info("MyExtension installed")

    def on_enable(self):
        """Gọi khi extension được bật."""
        logger.info("MyExtension enabled")

    def on_disable(self):
        """Gọi khi extension bị tắt."""
        pass

    def on_uninstall(self):
        """Gọi trước khi extension bị gỡ."""
        pass

    # ── Routes (FastAPI) ─────────────────────────────
    def get_routes(self):
        """Trả về FastAPI router."""
        from my_api import router  # import từ file api cùng thư mục
        return router

    # ── Workflow Nodes ───────────────────────────────
    def get_nodes(self) -> Dict[str, Any]:
        """Trả về dict {node_type: NodeClass}."""
        try:
            from nodes.my_node import MyNode
            return {"my_node_type": MyNode}
        except ImportError:
            return {}

    # ── Telegram Actions ─────────────────────────────
    def get_telegram_actions(self) -> Dict[str, Any]:
        """Actions gọi từ chatbot Telegram."""
        return {
            "my_action": self._action_my_action,
        }

    async def _action_my_action(self, data: dict, context: dict) -> str:
        """Handler cho Telegram action."""
        # data = payload từ chatbot
        # context = {"chat_id": ..., "bot": ...}
        return "✅ Action completed!"
```

---

## 4. API Routes: `<name>_api.py`

```python
"""
API routes for My Extension.
"""
import os
import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse

router = APIRouter(prefix="/api/v1/my-ext", tags=["my_extension"])


def _data_dir():
    from tubecli.config import DATA_DIR
    d = os.path.join(DATA_DIR, "my_extension")
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/items")
async def list_items():
    """List all items."""
    return {"items": [], "count": 0}


@router.post("/items")
async def create_item(request):
    """Create a new item."""
    body = await request.json()
    # ... save logic
    return {"status": "success", "item": body}
```

---

## 5. ⚠️ CRITICAL: Route Registration trong `webui/routes.py`

### Vì sao cần?
TubeCLI **KHÔNG tự động mount static files** cho extension. Phải đăng ký thủ công 3 thứ:

1. **`_find_<name>_dir()`** — Hàm tìm thư mục extension
2. **`GET /<page-url>`** — Route serve trang HTML chính
3. **`GET /<name>-static/{filename}`** — Route serve file tĩnh (CSS/JS)

### Template code (copy vào cuối `tubecli/extensions/webui/routes.py`):

```python
def _find_my_extension_dir():
    """Find the My Extension directory."""
    from tubecli.core.extension_manager import extension_manager
    ext = extension_manager.get("my_extension")  # ← dùng name từ manifest
    if ext and ext.extension_dir:
        return ext.extension_dir
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "my_extension")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("my_extension__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None


@router.get("/my-extension")        # ← page_url từ manifest
@router.get("/my_extension")        # ← fallback với underscore
async def my_extension_page():
    """Serve the My Extension page."""
    ext_dir = _find_my_extension_dir()
    if ext_dir:
        html_file = os.path.join(ext_dir, "static", "main.html")
        if os.path.exists(html_file):
            return FileResponse(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>My Extension — Not Installed</title>
    <style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a12;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}.card{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:16px;padding:48px;max-width:480px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.4)}.icon{font-size:64px;margin-bottom:16px}h1{font-size:24px;margin-bottom:12px;color:#fff}p{color:#aaa;line-height:1.6;margin-bottom:24px}.btn{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;border-radius:8px;text-decoration:none;font-weight:700}</style>
    </head>
    <body><div class="card"><div class="icon">🎯</div><h1>My Extension</h1><p>Extension not installed.</p><a href="/dashboard" class="btn">← Dashboard</a></div></body>
    </html>
    """, status_code=200)


@router.get("/my-extension-static/{filename:path}")
@router.get("/my_extension-static/{filename:path}")    # ← fallback
async def serve_my_extension_static(filename: str):
    """Serve My Extension static files (JS, CSS)."""
    ext_dir = _find_my_extension_dir()
    if ext_dir:
        filepath = os.path.join(ext_dir, "static", filename)
        if os.path.exists(filepath):
            return FileResponse(filepath)
    return {"error": f"File {filename} not found"}
```

### Quy tắc đặt tên route:

| Manifest `name` | `page_url` | Static route | HTML references |
|-----------------|-----------|--------------|-----------------|
| `my_extension` | `/my-extension` | `/my-extension-static/{filename}` | `href="/my-extension-static/main.css"` |
| `template_designer` | `/template-designer` | `/template-designer-static/{filename}` | `href="/template-designer-static/designer.css"` |
| `video_editor` | `/video-editor` | `/video-editor-static/{filename}` | `href="/video-editor-static/editor.css"` |

---

## 6. Dashboard Sidebar — Cách Extension Hiển Thị

### Flow:
```
1. Server khởi động → ExtensionManager.discover_extensions()
2. Dashboard load → GET /api/v1/extensions → danh sách extensions
3. loadDynamicExtensionsToSidebar() chạy:
   a. Extension KHÔNG có trong EXT_REGISTRY (app.js) → tự động thêm sidebar
   b. Fetch GET /api/v1/extensions/{name}/info → lấy manifest.page_url
   c. Nếu có page_url → tạo <iframe data-src="{page_url}"> trong tab panel
   d. Click sidebar → iframe load page_url
```

### ⚠️ Không cần sửa `app.js` nếu:
- Extension là external (type: `"external"`)
- Manifest có `"page_url"`
- Route tương ứng đã đăng ký trong `webui/routes.py`

### Chỉ cần sửa `app.js` khi:
- Muốn extension xuất hiện trong `EXT_REGISTRY` (card grid)
- Muốn hardcode hash route cho sidebar (vd: `'ext-video-editor'`)
- Extension là system/built-in

---

## 7. i18n — Đa Ngôn Ngữ

### 7.1. Client-side i18n (Trong Static HTML/JS)

**Cấu trúc file i18n:**
```
static/i18n/
├── en.json
├── vi.json
└── zh.json
```

**Nội dung `en.json`:**
```json
{
    "title": "My Extension",
    "subtitle": "Description here",
    "btn_save": "Save",
    "btn_cancel": "Cancel",
    "status_loading": "Loading...",
    "status_ready": "Ready",
    "status_error": "Error occurred",
    "label_name": "Name",
    "label_description": "Description",
    "msg_success": "Operation completed successfully",
    "msg_confirm_delete": "Are you sure you want to delete this?"
}
```

**Nội dung `vi.json`:**
```json
{
    "title": "Extension Của Tôi",
    "subtitle": "Mô tả ở đây",
    "btn_save": "Lưu",
    "btn_cancel": "Hủy",
    "status_loading": "Đang tải...",
    "status_ready": "Sẵn sàng",
    "status_error": "Đã xảy ra lỗi",
    "label_name": "Tên",
    "label_description": "Mô tả",
    "msg_success": "Thao tác hoàn tất",
    "msg_confirm_delete": "Bạn có chắc muốn xóa?"
}
```

**JavaScript i18n loader (đặt trong file JS chính):**
```javascript
// ── i18n System ─────────────────────────────────────────
const I18N = {
    _strings: {},
    _lang: 'en',
    _fallback: {},

    async init() {
        // 1. Detect language from parent dashboard or settings
        this._lang = this._detectLang();

        // 2. Load fallback (English) first
        try {
            const enRes = await fetch('/my-extension-static/i18n/en.json');
            if (enRes.ok) this._fallback = await enRes.json();
        } catch (e) { console.warn('i18n: fallback load failed'); }

        // 3. Load target language
        if (this._lang !== 'en') {
            try {
                const res = await fetch(`/my-extension-static/i18n/${this._lang}.json`);
                if (res.ok) this._strings = await res.json();
            } catch (e) { console.warn(`i18n: ${this._lang} load failed, using fallback`); }
        }

        if (Object.keys(this._strings).length === 0) {
            this._strings = this._fallback;
        }

        // 4. Apply translations to DOM
        this._applyDOM();

        // 5. Setup language selector if exists
        const langSelect = document.getElementById('langSelect');
        if (langSelect) {
            langSelect.value = this._lang;
            langSelect.addEventListener('change', (e) => {
                localStorage.setItem('ext_lang', e.target.value);
                location.reload();
            });
        }
    },

    _detectLang() {
        // Priority: localStorage > parent dashboard settings > navigator
        const stored = localStorage.getItem('ext_lang');
        if (stored) return stored;

        // Try to read from parent window (dashboard)
        try {
            const parentLang = window.parent?.document?.documentElement?.lang;
            if (parentLang) return parentLang.split('-')[0];
        } catch (e) {}

        // Try to read from global settings API
        try {
            const settings = JSON.parse(localStorage.getItem('tubecli_settings') || '{}');
            if (settings.language) return settings.language;
        } catch (e) {}

        // Fallback to browser language
        return navigator.language?.split('-')[0] || 'en';
    },

    _applyDOM() {
        // Auto-translate elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const text = this.t(key);
            if (text) {
                if (el.tagName === 'INPUT' && el.type !== 'submit') {
                    el.placeholder = text;
                } else {
                    el.textContent = text;
                }
            }
        });

        // Also handle data-i18n-title
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.title = this.t(key) || el.title;
        });
    },

    t(key, fallback) {
        return this._strings[key] || this._fallback[key] || fallback || key;
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => I18N.init());
```

**HTML sử dụng data-i18n attribute:**
```html
<h1 data-i18n="title">My Extension</h1>
<p data-i18n="subtitle">Description</p>
<button data-i18n="btn_save">Save</button>
<input type="text" data-i18n="label_name" placeholder="Name">
```

### 7.2. Server-side i18n (API cung cấp sẵn)

TubeCLI đã có API locale tự động cho mỗi extension:
```
GET /api/v1/extensions/{name}/locale/{lang}
```

Nếu cần server-side translations, đặt file JSON trong:
```
locales/
├── en.json
└── vi.json
```

API sẽ tự tìm và trả về JSON phù hợp.

---

## 8. HTML Page Template Chuẩn

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎯 My Extension — TubeCreate</title>
    <meta name="description" content="Description of extension">
    <link rel="stylesheet" href="/my-extension-static/main.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <div class="app-container">
        <!-- Header -->
        <header class="app-header">
            <div class="header-left">
                <span class="header-icon">🎯</span>
                <div>
                    <h1 data-i18n="title">My Extension</h1>
                    <p class="header-subtitle" data-i18n="subtitle">Description</p>
                </div>
            </div>
            <div class="header-right">
                <select id="langSelect" class="lang-select" title="Language">
                    <option value="en">EN</option>
                    <option value="vi">VI</option>
                    <option value="zh">ZH</option>
                </select>
            </div>
        </header>

        <!-- Main Content -->
        <main class="main-content">
            <!-- Your UI here -->
        </main>
    </div>

    <script src="/my-extension-static/main.js"></script>
</body>
</html>
```

### ⚠️ Path rules cho HTML:
- CSS: `href="/my-extension-static/main.css"` (qua route `/my-extension-static/{filename}`)
- JS: `src="/my-extension-static/main.js"`
- API calls: `fetch('/api/v1/my-ext/items')`
- **KHÔNG dùng** đường dẫn tương đối (`./main.css`) — sẽ KHÔNG hoạt động vì trang load qua route khác

---

## 9. CSS Theme Chuẩn (Dark Theme)

```css
/* ── Root Variables (match dashboard) ──────────────────── */
:root {
    --bg: #0a0a12;
    --bg2: #111827;
    --bg3: #1f2937;
    --text: #e5e7eb;
    --text-muted: #9ca3af;
    --border: rgba(255, 255, 255, 0.08);
    --cyan: #22d3ee;
    --green: #34d399;
    --red: #f87171;
    --purple: #a78bfa;
    --accent: #7c3aed;
    --accent-glow: rgba(124, 58, 237, 0.3);
    --font: 'Inter', system-ui, -apple-system, sans-serif;
    --radius: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

/* ── Buttons ──────────────────────────────────────────── */
.btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg3);
    color: var(--text);
    font-family: var(--font);
    font-size: 0.85rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
}

.btn:hover {
    background: var(--bg2);
    border-color: var(--accent);
}

.btn-primary {
    background: linear-gradient(135deg, var(--accent), #6d28d9);
    border-color: transparent;
    color: #fff;
}

.btn-primary:hover {
    filter: brightness(1.1);
    transform: translateY(-1px);
}

/* ── Cards ────────────────────────────────────────────── */
.card {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    transition: all 0.2s;
}

.card:hover {
    border-color: var(--accent);
    box-shadow: 0 4px 20px var(--accent-glow);
}

/* ── Inputs ───────────────────────────────────────────── */
input, select, textarea {
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 0.9rem;
    transition: border-color 0.2s;
}

input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-glow);
}

/* ── Scrollbar ────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.25); }
```

---

## 10. Workflow Node Template

```python
"""
Workflow Node: My Custom Node
"""

class MyNode:
    """Custom workflow node for My Extension."""
    node_type = "my_node_type"       # Phải khớp với manifest.nodes[]
    display_name = "My Node"
    description = "Does something useful"
    category = "my_extension"

    # Inputs/outputs definition
    inputs = [
        {"name": "input_text", "type": "string", "label": "Input Text"},
    ]
    outputs = [
        {"name": "result", "type": "string", "label": "Result"},
    ]

    def __init__(self):
        self.id = None
        self.config = {}

    async def execute(self, input_data: dict, config: dict) -> dict:
        """Execute the node logic."""
        text = input_data.get("input_text", "")
        # ... processing logic
        return {"result": f"Processed: {text}"}
```

---

## 11. SKILL.md cho AI Chatbot

```markdown
# Extension: My Extension

## Capabilities
- Feature 1: Description
- Feature 2: Description

## Telegram Actions

### action: my_action
- Description: What this action does
- Parameters:
  - `param1` (string, required): Description
  - `param2` (number, optional): Description
- Example: `{"action": "my_action", "param1": "value"}`
- Returns: Text result

## API Endpoints

### GET /api/v1/my-ext/items
Returns list of items.

### POST /api/v1/my-ext/items
Creates a new item.
Body: `{"name": "...", "data": {...}}`

## Workflow Nodes
- `my_node_type`: Does X with input Y
```

---

## 12. Checklist — Extension Hoàn Chỉnh

```
□ tubecli-extension.json
  □ name (snake_case)
  □ entry + extension_class
  □ icon (emoji)
  □ page_url (kebab-case, nếu có UI)
  □ api_prefix (nếu có API)
  □ nodes (nếu có workflow nodes)

□ extension.py
  □ on_install() — tạo thư mục data
  □ get_routes() — trả về FastAPI router
  □ get_nodes() — trả về dict node classes
  □ get_telegram_actions() — trả về dict handlers

□ webui/routes.py (trong tubecli core)
  □ _find_<name>_dir() function
  □ GET /<page-url> route (serve HTML)
  □ GET /<name>-static/{filename} route (serve CSS/JS)
  □ Fallback HTML (Not Installed page)

□ static/ UI
  □ HTML — đúng path (<name>-static/...)
  □ CSS — dark theme, match dashboard
  □ JS — API calls, event handlers
  □ i18n/ — en.json + vi.json (tối thiểu)
  □ Google Fonts (Inter) loaded

□ API routes
  □ router = APIRouter(prefix=api_prefix)
  □ Error handling (HTTPException)
  □ Background tasks (nếu cần)

□ SKILL.md
  □ Capabilities
  □ Telegram actions
  □ API endpoints
  □ Workflow nodes

□ Kiểm tra
  □ python -m py_compile extension.py
  □ python -m py_compile <api_file>.py
  □ JSON valid (tubecli-extension.json)
  □ Server restart → extension hiện trên sidebar
  □ Click sidebar → UI load đúng
  □ i18n chuyển ngôn ngữ hoạt động
```

---

## 13. Lỗi Thường Gặp & Cách Sửa

| Lỗi | Nguyên nhân | Cách sửa |
|-----|-------------|----------|
| `{"detail":"Not Found"}` khi truy cập trang | Thiếu route trong `webui/routes.py` | Thêm `_find_xxx_dir()` + page route + static route |
| Sidebar không hiện extension | Thiếu `page_url` trong manifest | Thêm `"page_url": "/my-extension"` |
| CSS/JS không load | Path sai trong HTML | Dùng `/my-extension-static/file.css`, KHÔNG dùng `./file.css` |
| Extension không enable | Lỗi import trong extension.py | Check `python -m py_compile extension.py` |
| API trả lỗi 500 | Lỗi trong route handler | Check server log, thêm try/except |
| i18n không hoạt động | File JSON path sai | Kiểm tra `/my-extension-static/i18n/en.json` accessible |
| Node không hiện trong workflow | `nodes` trong manifest không khớp `get_nodes()` | Đảm bảo key trong dict khớp manifest |

---

## 14. Extension Samples (Tham Khảo)

| Extension | Đặc điểm | File tham khảo |
|-----------|----------|----------------|
| `video_editor` | Full-featured, hardcoded sidebar, FFmpeg | `video_editor/extension.py` |
| `tts_vibevoice` | Dynamic sidebar, has `page_url`, i18n | `tts_vibevoice/tubecli-extension.json` |
| `sheets_manager` | Google API integration, credentials | `sheets_manager/extension.py` |
| `subtitle_extractor` | AI engines, background tasks | `subtitle_extractor/extension.py` |
| `template_designer` | Canvas UI (Fabric.js), animations | `template_designer/extension.py` |
