"""
Website Manager Extension — Deploy và quản lý websites Cloudflare Workers.
Logic deploy dựa trên website-manager (wrangler + OpenNext + D1 + R2).
"""
import os
import json
import uuid
import logging
import threading
import subprocess
import shutil
import tempfile
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from tubecli.core.extension_manager import Extension
from tubecli.config import EXTENSIONS_DATA_DIR

logger = logging.getLogger("WebsiteManagerExtension")

WEBSITE_MANAGER_DATA_DIR = os.path.join(EXTENSIONS_DATA_DIR, "website_manager")
WEBSITES_FILE = os.path.join(WEBSITE_MANAGER_DATA_DIR, "websites.json")
LOGS_DIR = os.path.join(WEBSITE_MANAGER_DATA_DIR, "logs")
BUILD_DIR = os.path.join(WEBSITE_MANAGER_DATA_DIR, "build")

TEMPLATES_API_URL = "https://autoweb.tubecreate.com/api/templates"

# SSE log listeners: site_name -> set of queues
_log_listeners: Dict[str, set] = {}
_log_listeners_lock = threading.Lock()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|\x1B\[[\x20-\x3f]*[\x40-\x7e]|\x1B[PX^_].*?\x1B\\)')
    return ansi_escape.sub('', text)


class WebsiteManager:
    """Manages website records stored in JSON."""

    def __init__(self, data_file: str = WEBSITES_FILE):
        self.data_file = data_file
        self._data: Dict[str, Any] = {"websites": []}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if not os.path.exists(self.data_file):
            self._save()
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            if "websites" not in self._data:
                self._data["websites"] = []
        except Exception as e:
            logger.error(f"Failed to load websites.json: {e}")
            self._data = {"websites": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def list_websites(self) -> List[dict]:
        with self._lock:
            return list(self._data.get("websites", []))

    def get_website(self, site_id: str) -> Optional[dict]:
        with self._lock:
            for site in self._data.get("websites", []):
                if site.get("id") == site_id or site.get("name") == site_id:
                    return site
        return None

    def add_website(
        self,
        name: str,
        user_token: str = "",
        wp_token: str = "",
        thumbnail: str = "",
        deploy_url: str = "",
        template: str = "",
        status: str = "active",
        cf_account_id: str = "",
        cf_api_token: str = "",
        admin_password: str = "",
        extra: dict = None,
    ) -> dict:
        with self._lock:
            # Check duplicate name
            for site in self._data["websites"]:
                if site.get("name") == name:
                    raise ValueError(f"Website '{name}' đã tồn tại.")
            site_id = str(uuid.uuid4())
            site = {
                "id": site_id,
                "name": name,
                "user_token": user_token,
                "wp_token": wp_token,
                "thumbnail": thumbnail,
                "deploy_url": deploy_url,
                "template": template,
                "status": status,
                "cf_account_id": cf_account_id,
                "cf_api_token": cf_api_token,
                "admin_password": admin_password,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "updated_at": datetime.utcnow().isoformat() + "Z",
                **(extra or {}),
            }
            self._data["websites"].append(site)
            self._save()
        return site

    def update_website(self, site_id: str, **kwargs) -> Optional[dict]:
        with self._lock:
            for site in self._data["websites"]:
                if site.get("id") == site_id or site.get("name") == site_id:
                    kwargs["updated_at"] = datetime.utcnow().isoformat() + "Z"
                    for k, v in kwargs.items():
                        if v is not None:
                            site[k] = v
                    self._save()
                    return site
        return None

    def delete_website(self, site_id: str) -> bool:
        with self._lock:
            original = len(self._data["websites"])
            self._data["websites"] = [
                s for s in self._data["websites"]
                if s.get("id") != site_id and s.get("name") != site_id
            ]
            if len(self._data["websites"]) < original:
                self._save()
                return True
        return False

    def upsert_by_name(self, name: str, **kwargs) -> dict:
        """Update existing site by name, or create if not found."""
        with self._lock:
            for site in self._data["websites"]:
                if site.get("name") == name:
                    kwargs["updated_at"] = datetime.utcnow().isoformat() + "Z"
                    site.update(kwargs)
                    self._save()
                    return site
        # Not found, create
        return self.add_website(name=name, **kwargs)


# ── Log streaming helpers ────────────────────────────────────────────

def _write_log(site_name: str, text: str, is_error: bool = False):
    """Append log to file and broadcast to SSE listeners."""
    clean = _strip_ansi(text)
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"{site_name}.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {clean}")
    except Exception:
        pass

    # Broadcast to SSE queues
    with _log_listeners_lock:
        listeners = _log_listeners.get(site_name, set())
        dead = set()
        for q in listeners:
            try:
                q.put_nowait({"message": clean, "is_error": is_error})
            except Exception:
                dead.add(q)
        for d in dead:
            listeners.discard(d)


def get_log_file(site_name: str) -> str:
    return os.path.join(LOGS_DIR, f"{site_name}.log")


def register_log_listener(site_name: str, queue):
    with _log_listeners_lock:
        if site_name not in _log_listeners:
            _log_listeners[site_name] = set()
        _log_listeners[site_name].add(queue)


def unregister_log_listener(site_name: str, queue):
    with _log_listeners_lock:
        if site_name in _log_listeners:
            _log_listeners[site_name].discard(queue)


# ── Cloudflare environment helper ────────────────────────────────────

def _get_cf_env(cf_api_token: str, cf_account_id: str) -> dict:
    env = dict(os.environ)
    token_str = (cf_api_token or "").strip()
    if token_str.startswith("cfut_"):
        env["CLOUDFLARE_API_TOKEN"] = token_str
        env.pop("CLOUDFLARE_API_KEY", None)
        env.pop("CLOUDFLARE_EMAIL", None)
    elif token_str:
        env["CLOUDFLARE_API_KEY"] = token_str
        env["CLOUDFLARE_EMAIL"] = os.environ.get("CLOUDFLARE_EMAIL", "zhenfai@gmail.com")
        env.pop("CLOUDFLARE_API_TOKEN", None)
    if cf_account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = cf_account_id.strip()
    return env


# ── Background deploy orchestrator ──────────────────────────────────

def _run_cmd(site_name: str, cmd: list, cwd: str, env: dict = None, timeout: int = 600) -> str:
    """Run subprocess, stream output to log. Returns combined output."""
    _write_log(site_name, f"$ {' '.join(cmd)}\n")
    exec_cmd = list(cmd)
    use_shell = False
    if os.name == "nt":
        if exec_cmd[0] == "npm":
            exec_cmd[0] = "npm.cmd"
        elif exec_cmd[0] == "npx":
            exec_cmd[0] = "npx.cmd"
        elif exec_cmd[0] == "git":
            exec_cmd[0] = "git.exe"
        elif exec_cmd[0] in ["node", "node.exe"]:
            resolved = shutil.which("node")
            if resolved:
                exec_cmd[0] = resolved
            else:
                exec_cmd[0] = "node"
                use_shell = True
        else:
            use_shell = True

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    proc = subprocess.Popen(
        exec_cmd,
        cwd=cwd,
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=use_shell,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = []
    while True:
        chunk = proc.stdout.read(256)
        if not chunk and proc.poll() is not None:
            break
        if chunk:
            output.append(chunk)
            _write_log(site_name, chunk)
    proc.wait(timeout=timeout)
    combined = "".join(output)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(cmd)}\n{combined[-2000:]}")
    return combined


def _analyze_error(msg: str) -> str:
    """Return a human-readable Vietnamese error description."""
    lo = msg.lower()
    if "maximum number of d1" in lo or ("reached the maximum" in lo and "d1" in lo):
        return "❌ Đã đạt giới hạn D1 databases (free plan tối đa 10 DB). Xóa bớt database trên Cloudflare Dashboard → D1."
    if "please enable r2" in lo or "10042" in lo:
        return "⚠️ R2 Storage chưa được bật. Vào Cloudflare Dashboard → R2 để kích hoạt."
    if "authentication" in lo or "unauthorized" in lo or "10000" in lo or "invalid api token" in lo:
        return "❌ Lỗi xác thực Cloudflare. Kiểm tra lại CF API Token và Account ID."
    if "already exists" in lo and ("pages" in lo or "project" in lo):
        return "⚠️ Tên website đã tồn tại trên Cloudflare Pages. Chọn tên khác hoặc xóa project cũ."
    if "already exists" in lo and "worker" in lo:
        return "⚠️ Tên Worker đã tồn tại. Chọn tên khác hoặc xóa Worker cũ trên CF Dashboard."
    if "git" in lo and ("clone" in lo or "repository" in lo) and ("failed" in lo or "error" in lo):
        return "❌ Không thể clone template từ GitHub. Kiểm tra kết nối internet."
    return msg[:500]


def _deploy_site_background(
    website_manager: "WebsiteManager",
    site_name: str,
    template_id: str,
    github_url: str,
    cf_api_token: str,
    cf_account_id: str,
    admin_password: str,
    site_title: str = "",
):
    """Delegate full deploy pipeline to Node.js runner script for maximum speed and non-blocking execution."""
    log_path = get_log_file(site_name)
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("")

    _write_log(site_name, f"=== DEPLOY BẮT ĐẦU (NODE ENGINE): {site_name} ===\n\n")

    site_path = os.path.join(BUILD_DIR, site_name)
    config_data = {
        "siteName": site_name,
        "githubUrl": github_url,
        "cfApiToken": cf_api_token,
        "cfAccountId": cf_account_id,
        "adminPassword": admin_password,
        "siteTitle": site_title,
        "logsDir": LOGS_DIR,
        "buildDir": BUILD_DIR,
    }
    config_file = os.path.join(BUILD_DIR, f"config_{site_name}.json")
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

    runner_script = os.path.join(os.path.dirname(__file__), "deploy_runner.js")
    node_bin = shutil.which("node") or "node"

    try:
        _run_cmd(site_name, [node_bin, runner_script, config_file], os.path.dirname(__file__), _get_cf_env(cf_api_token, cf_account_id))
        
        deploy_url = f"https://{site_name}.workers.dev"
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
                import re
                url_match = re.search(r'https://[a-zA-Z0-9.\-]+\.workers\.dev', content)
                if url_match:
                    deploy_url = url_match.group(0)
        except Exception:
            pass

        website_manager.update_website(
            site_name,
            status="active",
            deploy_url=deploy_url,
        )

        try:
            if os.path.exists(config_file):
                os.remove(config_file)
            shutil.rmtree(site_path, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        err_msg = str(e)
        _write_log(site_name, f"\n❌ DEPLOY THẤT BẠI: {err_msg}\n", True)
        website_manager.update_website(site_name, status="failed")
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
            shutil.rmtree(site_path, ignore_errors=True)
        except Exception:
            pass


def _generate_wp_token(deploy_url: str, admin_password: str) -> str:
    """Generate application token by logging in as admin and requesting a token."""
    import urllib.request
    import urllib.parse

    # Try /api/admin/generate-token first (custom endpoint)
    try:
        payload = json.dumps({"username": "admin", "password": admin_password}).encode()
        req = urllib.request.Request(
            f"{deploy_url}/api/admin/generate-token",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token") or data.get("access_token") or data.get("wp_token")
            if token:
                return token
    except Exception:
        pass

    # Fallback: try standard login endpoint
    try:
        payload = json.dumps({"username": "admin", "password": admin_password}).encode()
        req = urllib.request.Request(
            f"{deploy_url}/api/admin/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token") or data.get("access_token") or data.get("jwt")
            if token:
                return token
    except Exception:
        pass

    return ""


# ── Extension Class ──────────────────────────────────────────────────

class WebsiteManagerExtension(Extension):
    name = "website_manager"
    version = "1.0.0"
    description = "Quản lý và deploy websites Cloudflare Workers với giao diện card list trực quan."
    author = "TubeCLI"
    extension_type = "system"

    def __init__(self):
        super().__init__()
        self.extension_dir = os.path.dirname(__file__)
        self._manager: Optional[WebsiteManager] = None

    def on_enable(self):
        self._manager = WebsiteManager()
        logger.info("Website Manager extension enabled.")

    def get_manager(self) -> WebsiteManager:
        if self._manager is None:
            self._manager = WebsiteManager()
        return self._manager

    def get_routes(self):
        from tubecli.extensions.website_manager.routes import router, ui_router
        return [ui_router, router]

    def get_ui_static_dir(self) -> Optional[str]:
        static_dir = os.path.join(self.extension_dir, "static")
        if os.path.isdir(static_dir):
            return static_dir
        return None

    def get_skill_md(self) -> Optional[str]:
        skill_path = os.path.join(self.extension_dir, "SKILL.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                return f.read()
        return None


# Singleton
website_manager_extension = WebsiteManagerExtension()
website_manager = website_manager_extension.get_manager()
