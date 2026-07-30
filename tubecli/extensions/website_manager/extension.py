"""
Website Manager Extension — Deploy và quản lý websites Cloudflare Workers.
Logic deploy dựa trên website-manager (wrangler + OpenNext + D1 + R2).
"""
import os
import json
import uuid
import queue
import logging
import threading
import subprocess
import shutil
import tempfile
import time
from datetime import datetime, timezone
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

# Deploy-lock: tên site đang deploy (chặn 2 tiến trình song song cùng site).
_active_deploys: set = set()
_active_deploys_lock = threading.Lock()

# Registry để HỦY deploy: site_name -> Popen đang chạy; + tập site đã bị hủy.
_active_procs: Dict[str, Any] = {}
_cancelled_deploys: set = set()
_procs_lock = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def try_acquire_deploy(site_name: str) -> bool:
    """Đánh dấu site đang deploy. Trả False nếu đã có tiến trình deploy khác."""
    with _active_deploys_lock:
        if site_name in _active_deploys:
            return False
        _active_deploys.add(site_name)
        return True


def release_deploy(site_name: str):
    with _active_deploys_lock:
        _active_deploys.discard(site_name)


def _register_proc(site_name: str, proc):
    with _procs_lock:
        _active_procs[site_name] = proc


def _unregister_proc(site_name: str):
    with _procs_lock:
        _active_procs.pop(site_name, None)


def cancel_deploy(site_name: str) -> bool:
    """Hủy deploy đang chạy: kill cả cây tiến trình (node → git/npm/wrangler).
    Trả True nếu có tiến trình để kill. _run_cmd sẽ thấy đã-hủy và báo phù hợp."""
    with _procs_lock:
        _cancelled_deploys.add(site_name)
        proc = _active_procs.get(site_name)
    if proc is None:
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


def is_deploying(site_name: str) -> bool:
    with _active_deploys_lock:
        return site_name in _active_deploys


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
            # KHÔNG im lặng ghi đè file hỏng bằng list rỗng (sẽ mất sạch record +
            # secret). Đổi tên file hỏng để giữ lại rồi mới bắt đầu list mới.
            logger.error(f"Failed to load websites.json (giữ lại bản hỏng): {e}")
            try:
                corrupt = f"{self.data_file}.corrupt-{int(time.time())}"
                os.replace(self.data_file, corrupt)
                logger.error(f"Đã đổi tên file hỏng thành {corrupt}")
            except Exception:
                pass
            self._data = {"websites": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        # Ghi atomic: dump ra .tmp + fsync rồi os.replace → không để lại JSON cụt
        # nếu tiến trình chết giữa chừng. chmod 0600 vì file chứa secret.
        tmp = f"{self.data_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, self.data_file)

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
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
                **(extra or {}),
            }
            self._data["websites"].append(site)
            self._save()
        return site

    def update_website(self, site_id: str, **kwargs) -> Optional[dict]:
        with self._lock:
            for site in self._data["websites"]:
                if site.get("id") == site_id or site.get("name") == site_id:
                    kwargs["updated_at"] = _utcnow()
                    for k, v in kwargs.items():
                        if v is not None:
                            site[k] = v
                    self._save()
                    return site
        return None

    def delete_website(self, site_id: str) -> bool:
        with self._lock:
            original = len(self._data["websites"])
            removed = [
                s for s in self._data["websites"]
                if s.get("id") == site_id or s.get("name") == site_id
            ]
            self._data["websites"] = [
                s for s in self._data["websites"]
                if s.get("id") != site_id and s.get("name") != site_id
            ]
            if len(self._data["websites"]) < original:
                self._save()
                # Dọn artefact trên đĩa (log + build + config chứa secret)
                for s in removed:
                    _cleanup_site_files(s.get("name", ""))
                return True
        return False

    def upsert_by_name(self, name: str, **kwargs) -> dict:
        """Update existing site by name, or create if not found."""
        with self._lock:
            for site in self._data["websites"]:
                if site.get("name") == name:
                    kwargs["updated_at"] = _utcnow()
                    site.update(kwargs)
                    self._save()
                    return site
        # Not found, create
        return self.add_website(name=name, **kwargs)


# ── Log streaming helpers ────────────────────────────────────────────

def _broadcast_log(site_name: str, clean: str, is_error: bool = False):
    """Đẩy một đoạn log (đã strip ansi) tới mọi SSE listener của site.

    Khi queue đầy: DROP message CŨ NHẤT rồi nhét mới — KHÔNG discard listener
    (queue.Full chỉ nghĩa là consumer chậm hơn producer, không phải đã chết).
    """
    with _log_listeners_lock:
        listeners = _log_listeners.get(site_name, set())
        dead = set()
        for q in list(listeners):
            try:
                q.put_nowait({"message": clean, "is_error": is_error})
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait({"message": clean, "is_error": is_error})
                except Exception:
                    pass
            except Exception:
                dead.add(q)
        for d in dead:
            listeners.discard(d)


def _write_log(site_name: str, text: str, is_error: bool = False):
    """Ghi một message rời (banner start/lỗi) vào file + broadcast.

    Luồng stream chính đi qua `_run_cmd` (mở file một lần, gom theo dòng). Hàm này
    chỉ dùng cho vài message lẻ nên open/close mỗi lần là chấp nhận được.
    """
    clean = _strip_ansi(text)
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"{site_name}.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(clean)
    except Exception:
        pass
    _broadcast_log(site_name, clean, is_error)


def get_log_file(site_name: str) -> str:
    # Defense-in-depth: chặn traversal nếu site_name lọt qua tầng route.
    path = os.path.realpath(os.path.join(LOGS_DIR, f"{site_name}.log"))
    root = os.path.realpath(LOGS_DIR)
    try:
        if os.path.commonpath([root, path]) != root:
            return os.path.join(LOGS_DIR, "_invalid.log")
    except ValueError:
        return os.path.join(LOGS_DIR, "_invalid.log")
    return path


def _cleanup_site_files(site_name: str):
    """Xóa log + thư mục build + file config (chứa secret) của một site."""
    if not site_name:
        return
    targets = [
        os.path.join(LOGS_DIR, f"{site_name}.log"),
        os.path.join(BUILD_DIR, f"config_{site_name}.json"),
    ]
    for t in targets:
        try:
            if os.path.isfile(t):
                os.remove(t)
        except Exception:
            pass
    try:
        shutil.rmtree(os.path.join(BUILD_DIR, site_name), ignore_errors=True)
    except Exception:
        pass


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

def _get_cf_env(cf_api_token: str, cf_account_id: str, cf_email: str = "") -> dict:
    """Dựng env cho wrangler.

    MẶC ĐỊNH coi mọi token là API Token (CLOUDFLARE_API_TOKEN) — token tạo từ CF
    dashboard là chuỗi 40 ký tự KHÔNG có tiền tố, trước đây bị định tuyến nhầm sang
    Global API Key kèm email hardcode của người khác. Chỉ dùng nhánh Global API Key
    khi người dùng nhập RÕ RÀNG email (không còn fallback 'zhenfai@gmail.com').
    """
    env = dict(os.environ)
    token_str = (cf_api_token or "").strip()
    email_str = (cf_email or "").strip()
    if token_str and email_str:
        # Có email → Global API Key
        env["CLOUDFLARE_API_KEY"] = token_str
        env["CLOUDFLARE_EMAIL"] = email_str
        env.pop("CLOUDFLARE_API_TOKEN", None)
    elif token_str:
        # Mặc định: API Token
        env["CLOUDFLARE_API_TOKEN"] = token_str
        env.pop("CLOUDFLARE_API_KEY", None)
        env.pop("CLOUDFLARE_EMAIL", None)
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
        prog = exec_cmd[0]
        base = os.path.basename(prog).lower()
        if base in ("node", "node.exe"):
            # QUAN TRỌNG: resolve full-path node và chạy KHÔNG shell. Trước đây
            # node_bin là full-path → rơi vào nhánh else shell=True → watchdog chỉ
            # giết cmd.exe chứ không giết cây node/npm/wrangler → timeout vô dụng.
            exec_cmd[0] = shutil.which(prog) or shutil.which("node") or prog
        elif base in ("npm", "npm.cmd", "npx", "npx.cmd", "git", "git.exe"):
            resolved = shutil.which(prog.split(".")[0])
            if resolved and resolved.lower().endswith(".exe"):
                exec_cmd[0] = resolved
            else:
                exec_cmd[0] = resolved or prog
                use_shell = True  # .cmd cần shell
        elif os.path.isabs(prog) and prog.lower().endswith(".exe") and os.path.isfile(prog):
            pass  # full-path exe → chạy trực tiếp, shell=False
        else:
            use_shell = True

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    creationflags = 0
    if os.name == "nt" and not use_shell:
        # process-group riêng để taskkill /T dọn sạch cả cây con.
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

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
        bufsize=1,  # line-buffered
        creationflags=creationflags,
    )

    # Watchdog: enforce timeout THẬT. Vòng đọc dưới đây block trên readline nên
    # proc.wait(timeout) sau vòng lặp là code chết — nếu npm install treo thì
    # readline treo theo. Timer này kill CẢ CÂY tiến trình khi vượt deadline.
    timed_out = {"v": False}

    def _kill_on_timeout():
        timed_out["v"] = True
        try:
            if os.name == "nt":
                # taskkill /T giết luôn tiến trình con (node → npm → wrangler...)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    watchdog = threading.Timer(timeout, _kill_on_timeout)
    watchdog.daemon = True
    watchdog.start()

    # Đăng ký proc để có thể HỦY từ endpoint /cancel (kill cả cây).
    _register_proc(site_name, proc)

    # Ghi/broadcast NGAY mỗi dòng (real-time), file mở MỘT lần cho cả lệnh.
    # (Bản trước gom lô theo thời gian nhưng flush chỉ chạy KHI có dòng mới tới →
    # dòng đầu bị kẹt trong buffer tới khi có dòng kế; readline block khi git clone
    # chậm → client đứng ở banner. Ghi từng dòng vào handle-mở-sẵn vẫn rẻ: 1 lần
    # open cho cả lệnh, mỗi dòng chỉ 1 write; KHÔNG còn open/close mỗi 256 byte.)
    output = []
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"{site_name}.log")
    logf = None
    try:
        logf = open(log_path, "a", encoding="utf-8")
    except Exception:
        logf = None
    try:
        # iter(readline, '') — KHÔNG `for line in proc.stdout` (đọc-trước giữ output).
        for line in iter(proc.stdout.readline, ''):
            output.append(line)  # giữ TẤT CẢ để caller parse (kể cả marker)
            # KHÔNG ghi log / broadcast dòng marker DEPLOY_RESULT: nó chứa wpToken
            # (JWT admin thật). Marker chỉ nằm trong `combined` trả về cho Python.
            if line.lstrip().startswith("DEPLOY_RESULT "):
                continue
            clean = _strip_ansi(line)
            if logf is not None:
                try:
                    logf.write(clean)
                    logf.flush()
                except Exception:
                    pass
            _broadcast_log(site_name, clean)
    finally:
        watchdog.cancel()
        try:
            if logf is not None:
                logf.close()
        except Exception:
            pass
        try:
            proc.stdout.close()
        except Exception:
            pass
        _unregister_proc(site_name)

    proc.wait()
    combined = "".join(output)
    # Đã bị HỦY theo yêu cầu người dùng? Báo bằng marker riêng để caller phân biệt.
    with _procs_lock:
        was_cancelled = site_name in _cancelled_deploys
    if was_cancelled:
        raise RuntimeError("__CANCELLED__")
    # Watchdog race: chỉ báo timeout khi tiến trình KHÔNG thoát sạch. Nếu process
    # kết thúc đúng vào mốc timeout (returncode==0) thì đó là thành công, không
    # phải treo → tránh báo timeout sai.
    if timed_out["v"] and proc.returncode not in (0, None):
        raise RuntimeError(f"Command timed out sau {timeout}s: {' '.join(cmd)}")
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
    cf_email: str = "",
):
    """Delegate full deploy pipeline to Node.js runner script for maximum speed and non-blocking execution."""
    site_path = os.path.join(BUILD_DIR, site_name)
    config_file = os.path.join(BUILD_DIR, f"config_{site_name}.json")
    # Toàn bộ body trong try/finally: preamble (ghi config) cũng có thể ném
    # (os.replace PermissionError...) — finally PHẢI luôn nhả deploy-lock, nếu
    # không site kẹt 409 vĩnh viễn.
    try:
        log_path = get_log_file(site_name)
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")
        # File log chứa output deploy (có thể lẫn dữ liệu nhạy cảm) → chmod 0600.
        try:
            os.chmod(log_path, 0o600)
        except Exception:
            pass

        _write_log(site_name, f"=== DEPLOY BẮT ĐẦU (NODE ENGINE): {site_name} ===\n\n")

        # Config file KHÔNG chứa secret — chỉ dữ liệu không nhạy cảm. cfApiToken /
        # adminPassword / account-id truyền cho runner qua BIẾN MÔI TRƯỜNG.
        config_data = {
            "siteName": site_name,
            "githubUrl": github_url,
            "siteTitle": site_title,
            "logsDir": LOGS_DIR,
            "buildDir": BUILD_DIR,
        }
        os.makedirs(BUILD_DIR, exist_ok=True)
        fd, tmp_cfg = tempfile.mkstemp(dir=BUILD_DIR, prefix=f"config_{site_name}_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config_data, f)
            try:
                os.chmod(tmp_cfg, 0o600)
            except Exception:
                pass
            os.replace(tmp_cfg, config_file)
        except Exception:
            try:
                os.remove(tmp_cfg)
            except Exception:
                pass
            # KHÔNG nuốt lỗi rồi chạy runner với config thiếu → báo lỗi rõ ràng.
            raise RuntimeError("Không ghi được file config cho deploy runner.")

        runner_script = os.path.join(os.path.dirname(__file__), "deploy_runner.js")
        node_bin = shutil.which("node") or "node"

        # Env cho runner: CF creds + admin password (bước 8 seed admin).
        # Có cf_email → _get_cf_env set CLOUDFLARE_API_KEY + CLOUDFLARE_EMAIL
        # (Global API Key); không thì CLOUDFLARE_API_TOKEN.
        deploy_env = _get_cf_env(cf_api_token, cf_account_id, cf_email)
        deploy_env["SITE_ADMIN_PASSWORD"] = admin_password or ""

        # timeout 1800s (30') — npm install + OpenNext build + wrangler deploy có
        # thể lâu trên máy nguội; cộng thêm ~100s retry seed admin ở bước 8/9. Để
        # 600s có nguy cơ watchdog kill nhầm một deploy đã sống.
        combined = _run_cmd(
            site_name,
            [node_bin, runner_script, config_file],
            os.path.dirname(__file__),
            deploy_env,
            timeout=1800,
        )

        # Đọc marker máy-đọc-được. Lấy DEPLOY_RESULT CUỐI CÙNG (findall[-1]): runner
        # in nó ngay trước __DEPLOY_DONE__, còn output build của repo (người dùng tự
        # chọn) có thể in chuỗi giả 'DEPLOY_RESULT ...' sớm hơn → lấy first sẽ bị
        # spoof. Marker cũng bị strip khỏi log nên không hiện cho người dùng.
        deploy_url = f"https://{site_name}.workers.dev"
        wp_token = ""
        admin_seeded = None
        import re as _re
        markers = _re.findall(r'DEPLOY_RESULT\s+(\{.*\})', combined)
        if markers:
            try:
                result = json.loads(markers[-1])
                deploy_url = result.get("url") or deploy_url
                wp_token = result.get("wpToken") or ""
                admin_seeded = result.get("adminSeeded")
            except Exception:
                pass
        else:
            # fallback: khớp CUỐI CÙNG của workers.dev (URL bước 7 vẫn còn trong log)
            urls = _re.findall(r'https://[a-zA-Z0-9.\-]+\.workers\.dev', combined)
            if urls:
                deploy_url = urls[-1]

        update = {"status": "active", "deploy_url": deploy_url}
        if wp_token:
            update["wp_token"] = wp_token
        # Seed admin thất bại dù có nhập mật khẩu → site đang dùng mật khẩu MẶC ĐỊNH
        # (công khai trong schema.sql của repo). Gắn cờ cảnh báo, không im lặng.
        if admin_password and admin_seeded is False:
            update["deploy_warning"] = "admin_default_password"
        elif admin_password and admin_seeded is True:
            update["deploy_warning"] = ""
        try:
            website_manager.update_website(site_name, **update)
        except Exception:
            logger.exception("update_website (active) thất bại")

    except Exception as e:
        err_msg = str(e)
        if "__CANCELLED__" in err_msg:
            _write_log(site_name, "\n🛑 Đã HỦY deploy theo yêu cầu người dùng.\n", True)
        else:
            _write_log(site_name, f"\n❌ DEPLOY THẤT BẠI: {_analyze_error(err_msg)}\n", True)
        try:
            website_manager.update_website(site_name, status="failed")
        except Exception:
            logger.exception("update_website (failed) thất bại")
    finally:
        # Dọn artefact + nhả deploy-lock DÙ THÀNH/BẠI/HỦY.
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
            shutil.rmtree(site_path, ignore_errors=True)
        except Exception:
            pass
        release_deploy(site_name)
        with _procs_lock:
            _cancelled_deploys.discard(site_name)  # reset cờ hủy cho lần sau


# (Đã bỏ _generate_wp_token — trước đây là dead code không ai gọi và POST sai
#  endpoint. Việc seed admin + sinh token giờ do deploy_runner.js làm ở bước 8/9,
#  trả về qua marker DEPLOY_RESULT để _deploy_site_background đọc.)


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
        # Đăng ký skill (Quản lý + Tạo Website) + gắn vào Web Agent để agent gọi
        # được qua chat/telegram (trước đây extension này không có skill runtime nào).
        try:
            from tubecli.extensions.website_manager.skills import register_skills
            stats = register_skills()
            logger.info(f"Website Manager skills: {stats}")
        except Exception as e:
            logger.warning(f"Website Manager skill registration failed: {e}")

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
