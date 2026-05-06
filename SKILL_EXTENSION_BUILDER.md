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
│   └── <main_page>.js
└── locales/                   ← Đa ngôn ngữ (core i18n API)
    ├── en.json
    ├── vi.json
    └── zh.json
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

## 4.5. 💾 Data Storage — Ưu Tiên JSON (Tối Ưu Đa Luồng)

> **Quy tắc**: Extension **PHẢI ưu tiên dùng JSON file** làm storage thay vì SQLite. JSON file-per-entity giúp tránh hoàn toàn `database is locked` khi chạy đa luồng/đa tiến trình.

### Tại sao KHÔNG dùng SQLite?

| Vấn đề SQLite | JSON giải quyết |
|---------------|-----------------|
| 1 connection cho tất cả threads → `SQLITE_BUSY` | Mỗi entity = file riêng, không conflict |
| `check_same_thread=False` gây race condition | `threading.Lock` per file, atomic write |
| WAL mode vẫn serialize writes | Chỉ lock khi write cùng 1 file |
| Cần migration tool (Alembic) khi thay đổi schema | Thêm field = thêm key vào JSON, không cần migrate |

### Architecture Pattern: File-Per-Entity

```
data/<extension_name>/
├── _meta.json              ← ID counters (next_item_id, etc.)
├── items.json              ← Shared collection (nếu ít data)
├── categories.json         ← Shared collection
└── projects/               ← Project-level isolation
    ├── 1/
    │   ├── project.json    ← Project metadata
    │   ├── items.json      ← Items thuộc project 1
    │   └── sub_items/
    │       └── item_1.json
    └── 2/
        └── ...             ← Project 2 hoàn toàn độc lập
```

### Template Code: JsonStore Class

```python
"""
JSON file-based storage with thread safety and atomic writes.
Copy pattern này cho mỗi extension cần lưu trữ dữ liệu.
"""
import os
import json
import threading
from typing import Optional, List, Dict
from datetime import datetime, timezone

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonStore:
    _instance = None

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._file_locks: Dict[str, threading.Lock] = {}
        os.makedirs(data_dir, exist_ok=True)
        self._init_meta()

    @classmethod
    def get_instance(cls, data_dir: str = ""):
        if cls._instance is None:
            cls._instance = cls(data_dir)
        return cls._instance

    def _get_lock(self, filepath: str) -> threading.Lock:
        """Thread-safe file-level lock."""
        if filepath not in self._file_locks:
            self._file_locks[filepath] = threading.Lock()
        return self._file_locks[filepath]

    def _read(self, filepath: str, default=None):
        """Read JSON file, trả về default nếu chưa tồn tại."""
        if not os.path.exists(filepath):
            return default if default is not None else None
        lock = self._get_lock(filepath)
        with lock:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, filepath: str, data):
        """Atomic write: ghi vào .tmp → os.replace() (an toàn trên NTFS)."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        lock = self._get_lock(filepath)
        with lock:
            tmp = filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, filepath)

    def _init_meta(self):
        """Khởi tạo file ID counters."""
        meta = os.path.join(self.data_dir, "_meta.json")
        if not os.path.exists(meta):
            self._write(meta, {"next_item_id": 1})

    def _next_id(self, key: str = "next_item_id") -> int:
        """Cấp ID tự tăng, thread-safe."""
        meta_path = os.path.join(self.data_dir, "_meta.json")
        lock = self._get_lock(meta_path)
        with lock:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            nid = meta.get(key, 1)
            meta[key] = nid + 1
            tmp = meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, meta_path)
        return nid

    # ── CRUD Methods ──────────────────────────────────
    def _items_path(self) -> str:
        return os.path.join(self.data_dir, "items.json")

    def create_item(self, data: dict) -> dict:
        items = self._read(self._items_path(), [])
        item = {"id": self._next_id(), **data, "created_at": _now()}
        items.append(item)
        self._write(self._items_path(), items)
        return item

    def list_items(self) -> list:
        return self._read(self._items_path(), [])

    def get_item(self, item_id: int) -> Optional[dict]:
        for i in self._read(self._items_path(), []):
            if i["id"] == item_id:
                return i
        return None

    def update_item(self, item_id: int, data: dict) -> Optional[dict]:
        items = self._read(self._items_path(), [])
        for i in items:
            if i["id"] == item_id:
                i.update(data)
                i["updated_at"] = _now()
                self._write(self._items_path(), items)
                return i
        return None

    def delete_item(self, item_id: int) -> bool:
        items = self._read(self._items_path(), [])
        items = [i for i in items if i["id"] != item_id]
        self._write(self._items_path(), items)
        return True
```

### Quy tắc quan trọng:

1. **Atomic write**: Luôn dùng pattern `write .tmp → os.replace()`. KHÔNG BAO GIỜ ghi trực tiếp vào file chính (sẽ corrupt data nếu crash giữa chừng).
2. **File-level lock**: Mỗi file có `threading.Lock` riêng → 2 project khác nhau không bao giờ block lẫn nhau.
3. **Soft delete**: Dùng `deleted_at` field thay vì xóa thật, để có thể recover.
4. **ID centralized**: Dùng `_meta.json` lưu counters, tránh trùng ID.
5. **Project isolation**: Nếu extension có khái niệm "project/workspace", tách data theo thư mục `projects/<id>/` để tối ưu concurrent access.

### Khi nào CÓ THỂ dùng SQLite?

Chỉ khi extension thỏa **TẤT CẢ** điều kiện sau:
- Chỉ chạy single-thread (không có background tasks)
- Cần query phức tạp (JOIN, aggregate, full-text search)
- Data rất lớn (>100MB) cần index
- Không cần multi-user concurrent access

### Tham khảo Implementation:
- **Full example**: `content_studio/db/json_store.py` — 1000+ lines, đầy đủ CRUD cho Drama/Episode/Character/Scene/Storyboard/Gallery/Pipeline
- **Migration từ SQLite**: `content_studio/db/migrate_db_to_json.py`

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

> **Chỉ dùng `locales/`** — TubeCLI core đã cung cấp hệ thống i18n tập trung. Extension **KHÔNG** cần viết JS loader riêng.

### Cấu trúc file:
```
locales/
├── en.json     ← Bắt buộc (fallback)
├── vi.json
└── zh.json
```

### Cách hoạt động:
```
1. Server khởi động → GET /api/v1/i18n/{lang}
2. API tự scan ALL extensions: locales/{lang}.json
3. Merge tất cả vào 1 dict chung → trả về frontend
4. i18n.js (core) gọi applyI18n() → dịch data-i18n attributes
```

### Nội dung `locales/en.json`:
```json
{
    "myext.title": "My Extension",
    "myext.subtitle": "Description here",
    "myext.btn_save": "Save",
    "myext.btn_cancel": "Cancel",
    "myext.status_loading": "Loading...",
    "myext.msg_success": "Operation completed"
}
```

### Nội dung `locales/vi.json`:
```json
{
    "myext.title": "Extension Của Tôi",
    "myext.subtitle": "Mô tả ở đây",
    "myext.btn_save": "Lưu",
    "myext.btn_cancel": "Hủy",
    "myext.status_loading": "Đang tải...",
    "myext.msg_success": "Thao tác hoàn tất"
}
```

> **⚠️ Quan trọng:** Dùng prefix `myext.` (tên extension) cho tất cả key để tránh xung đột khi merge với extension khác.

### HTML sử dụng `data-i18n`:
```html
<h1 data-i18n="myext.title">My Extension</h1>
<p data-i18n="myext.subtitle">Description</p>
<button data-i18n="myext.btn_save">Save</button>
```

### JS sử dụng hàm `T()` (từ core `i18n.js`):
```javascript
// Trong HTML, include i18n.js từ core:
// <script src="/static/i18n.js"></script>

// Sau đó dùng trực tiếp:
showToast(T('myext.msg_success'));

// Với biến thay thế:
log(T('myext.status_pulling', {name: 'model1'}));
// locales/en.json: "myext.status_pulling": "Pulling {name}..."
```

### Chuyển ngôn ngữ:
Extension **KHÔNG cần** làm gì — dashboard core đã xử lý:
- User chọn ngôn ngữ → `changeLanguage(lang)` → reload page
- `loadI18nFromApi()` tự fetch `/api/v1/i18n/{lang}` → merge tất cả locales
- `applyI18n()` tự dịch tất cả `data-i18n` elements

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
    <!-- Core i18n — PHẢI include trước JS của extension -->
    <script src="/static/i18n.js"></script>
</head>
<body>
    <div class="app-container">
        <!-- Header -->
        <header class="app-header">
            <div class="header-left">
                <span class="header-icon">🎯</span>
                <div>
                    <h1 data-i18n="myext.title">My Extension</h1>
                    <p class="header-subtitle" data-i18n="myext.subtitle">Description</p>
                </div>
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
  □ Google Fonts (Inter) loaded

□ locales/ (đa ngôn ngữ)
  □ en.json (bắt buộc, fallback)
  □ vi.json
  □ Key dùng prefix tên extension (vd: myext.title)

□ API routes
  □ router = APIRouter(prefix=api_prefix)
  □ Error handling (HTTPException)
  □ Background tasks (nếu cần)

□ Data Storage (ưu tiên JSON)
  □ JsonStore class (Singleton, thread-safe)
  □ Atomic write (_write → .tmp → os.replace)
  □ _meta.json cho ID counters
  □ Project isolation (nếu multi-project)
  □ KHÔNG dùng SQLite (trừ khi single-thread + query phức tạp)

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
| i18n không hoạt động | Thiếu `locales/` folder hoặc key sai | Kiểm tra `locales/en.json` có tồn tại, key có prefix đúng (vd: `myext.title`) |
| `database is locked` / `SQLITE_BUSY` | Dùng SQLite với đa luồng | Chuyển sang JSON storage (xem Section 4.5). KHÔNG dùng SQLite cho extension có background tasks |
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
