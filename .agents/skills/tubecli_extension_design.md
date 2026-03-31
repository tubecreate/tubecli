---
name: tubecli_extension_design
description: Pattern thiết kế extension cho TubeCLI — cấu trúc file, vị trí, cách load routes/nodes, lifecycle hooks, UI, market packaging
---

# TubeCLI Extension Design Pattern

## Vị trí Extension

**KHÔNG bao giờ** đặt extension mới vào `tubecli/extensions/` hoặc thêm vào `BUILTIN_EXTENSIONS`.

Extension phân phối qua Market phải nằm tại:
```
data/extensions_external/<extension_name>/
```

Khi user install từ Market, Market routes ghi file vào:
```
data/extensions_external/<extension_name>__<public_id>/
```

`discover_external_extensions()` tự scan thư mục này khi khởi động — không cần đăng ký thủ công.

---

## Cấu trúc file chuẩn (theo video_editor pattern)

```
data/extensions_external/<name>/
├── tubecli-extension.json   ← Bắt buộc, manifest cho Market & ExtensionManager
├── SKILL.md                 ← AI guidance context
├── requirements.txt         ← Python dependencies
├── extension.py             ← Extension class (entry point)
├── <name>_api.py            ← FastAPI router + business logic
├── skills.py                ← Default skills đăng ký khi install
├── nodes/
│   ├── __init__.py          ← ALL_NODES = {"node_type": NodeClass, ...}
│   └── <node_name>_node.py
└── static/
    ├── <name>.html
    ├── <name>.js
    └── <name>.css
```

**Không có:** `__init__.py` ở root extension, `commands.py` (optional), `locales/` (optional, embed trong JS)

---

## `tubecli-extension.json` — Manifest

```json
{
  "name": "extension_name",
  "version": "1.0.0",
  "description": "Mô tả extension",
  "author": "TubeCreate",
  "icon": "📦",
  "entry": "extension.py",
  "extension_class": "ExtensionNameExtension",
  "category": "extension",
  "tags": ["tag1", "tag2"],
  "dependencies": ["package>=version"],
  "nodes": ["node_type_1", "node_type_2"],
  "skill_md": "SKILL.md",
  "ui_static": "static",
  "api_prefix": "/api/v1/extension-name",
  "min_tubecli_version": "0.1.0",
  "license": "MIT"
}
```

---

## `extension.py` — Pattern chuẩn (dùng importlib, KHÔNG dùng relative import)

```python
import os
import logging
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("ExtensionNameExtension")

class ExtensionNameExtension(Extension):
    name = "extension_name"
    version = "1.0.0"
    description = "Mô tả"
    author = "TubeCreate"

    def on_install(self):
        """Chạy khi install từ Market — tạo dirs, đăng ký skills."""
        self._register_skills()

    def on_enable(self):
        """Chạy khi enable — idempotent."""
        self._register_skills()

    def _register_skills(self):
        """Load và chạy skills.py bằng importlib (không dùng relative import)."""
        try:
            import importlib.util
            skills_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills.py")
            spec = importlib.util.spec_from_file_location("ext_skills", skills_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.register_skills()
        except Exception as e:
            logger.warning(f"Could not register skills: {e}")

    def get_routes(self):
        """Load FastAPI router từ <name>_api.py bằng importlib."""
        try:
            import importlib.util
            api_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "<name>_api.py")
            spec = importlib.util.spec_from_file_location("ext_routes", api_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            router = getattr(mod, "router", None)
            print(f"[ExtName] Loaded {len(router.routes) if router else 0} routes")
            return router
        except Exception as e:
            print(f"FAILED to import router: {e}")
            return None

    def get_nodes(self):
        """Load nodes từ nodes/__init__.py → ALL_NODES dict."""
        try:
            import importlib.util
            nodes_init = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes", "__init__.py")
            spec = importlib.util.spec_from_file_location("ext_nodes", nodes_init)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "ALL_NODES", {})
        except Exception as e:
            print(f"FAILED to import nodes: {e}")
            return {}

    def get_ui_static_dir(self):
        """Serve UI từ static/ trong extension directory."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
```

---

## `skills.py` — Pattern đăng ký Skills (idempotent)

```python
from typing import List, Dict

SKILLS: List[Dict] = [
    {
        "name": "📊 Skill Name",
        "description": "Mô tả. Dùng: tubecli skill run 'Skill Name'",
        "skill_type": "Skill",
        "commands": ["command alias", "lệnh tắt"],
        "workflow_data": {
            "name": "Skill Name",
            "nodes": [...],
            "connections": [...]
        }
    }
]

def register_skills():
    """Idempotent — gọi nhiều lần không tạo duplicate."""
    try:
        from tubecli.core.skill import skill_manager
        existing = {s.name for s in skill_manager.get_all()}
        added = 0
        for skill_def in SKILLS:
            if skill_def["name"] not in existing:
                skill_manager.create(
                    name=skill_def["name"],
                    workflow_data=skill_def["workflow_data"],
                    skill_type=skill_def.get("skill_type", "Skill"),
                    description=skill_def.get("description", ""),
                    commands=skill_def.get("commands", []),
                )
                added += 1
                print(f"  ✅ Added skill: {skill_def['name']}")
        if added:
            print(f"  📦 Registered {added} skills")
    except Exception as e:
        print(f"  ❌ Error registering skills: {e}")
```

---

## `nodes/__init__.py` — Export ALL_NODES

```python
from .node_a import NodeAClass
from .node_b import NodeBClass

ALL_NODES = {
    "node_type_a": NodeAClass,
    "node_type_b": NodeBClass,
}
```

---

## WebUI Integration — Thêm vào `webui/routes.py`

```python
def _find_<name>_dir():
    """Tìm extension dir — hỗ trợ cả 'ext_name' và 'ext_name__xxx' folder."""
    from tubecli.config import DATA_DIR
    ext_base = os.path.join(DATA_DIR, "extensions_external")
    if not os.path.isdir(ext_base):
        return None
    exact = os.path.join(ext_base, "<name>")
    if os.path.isdir(exact):
        return exact
    for entry in os.listdir(ext_base):
        if entry.startswith("<name>__") and os.path.isdir(os.path.join(ext_base, entry)):
            return os.path.join(ext_base, entry)
    return None

@router.get("/<url-slug>")
async def <name>_page():
    """Serve the <Name> page."""
    ext_dir = _find_<name>_dir()
    if ext_dir:
        html_file = os.path.join(ext_dir, "static", "<name>.html")
        if os.path.exists(html_file):
            return FileResponse(html_file)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="<h1>Extension not installed</h1>")

@router.get("/<url-slug>-static/{filename:path}")
async def serve_<name>_static(filename: str):
    """Serve static files cho extension."""
    ext_dir = _find_<name>_dir()
    if ext_dir:
        filepath = os.path.join(ext_dir, "static", filename)
        if os.path.exists(filepath):
            return FileResponse(filepath)
    return {"error": f"File {filename} not found"}
```

---

## WebUI Nav — Thêm vào `webui/static/index.html`

Tìm section `<!-- Extensions -->` trong sidebar, thêm:
```html
<button class="nav-item" onclick="navigateTo('/url-slug')" id="nav-ext-name">
    <span class="nav-icon">📦</span>
    <span class="nav-text" data-i18n="nav.ext_name">Extension Name</span>
</button>
```

---

## Auth Manager Integration (khi cần OAuth)

```python
# Lấy token từ auth_manager (trong _api.py)
from tubecli.extensions.auth_manager.extension import auth_manager

def get_valid_cred(provider="google", required_scopes=None):
    """Tự tìm credential có token active."""
    creds = auth_manager.list_credentials(provider=provider)
    for cred in creds:
        if cred.get("has_token") and cred.get("token_status") == "active":
            token = auth_manager.get_active_token(cred["id"])
            if token:
                return cred["id"], token
    return None, None
```

---

## Nguyên tắc

1. **KHÔNG** dùng relative import (`from .module import`) trong extension external — dùng `importlib.util`
2. **KHÔNG** thêm vào `BUILTIN_EXTENSIONS` hay thay đổi `extension_manager.py`
3. **BẮT BUỘC** thêm vào `data/extensions.json` với `"enabled": true` — nếu không extension bị discover nhưng không hiện và không bật:
   ```json
   "sheets_manager": { "enabled": true }
   ```
4. `on_install()` + `on_enable()` **phải idempotent** — gọi nhiều lần không tạo duplicate
5. `nodes/__init__.py` **phải export `ALL_NODES`** dict
6. `tubecli-extension.json` **bắt buộc** có đủ required fields: `name, version, description, entry, extension_class`
7. Static files phục vụ qua route trong `webui/routes.py` — thêm `_find_<name>_dir()` + 2 routes
8. `skills.py` track existing skills bằng **set tên** để tránh duplicate
