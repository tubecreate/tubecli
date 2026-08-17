"""Cài & chạy các "app" phụ trợ (9Router, Ollama...) như systemd service.

Dùng cho node App trong Flow Builder của cloud: nhập mật khẩu → cài → tạo service
tự chạy nền → cloud mở tunnel tới cổng của app → nhúng iframe dashboard.

Whitelist cứng — chỉ cài đúng vài app định sẵn bằng script cố định, KHÔNG chạy
lệnh do client gửi. Mật khẩu chỉ được ghi vào Environment= của unit systemd (do
Python ghi, không nội suy vào shell) nên không có nguy cơ injection. Chạy nền
trong thread, tiến trình theo dõi qua /status. Chỉ Linux + có systemd + sudo.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import threading
import time
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/apps", tags=["apps"])

# name -> cách cài. npm_global: gói npm cài -g. port: cổng lắng nghe.
# exec: lệnh chạy (dùng {bin} = đường dẫn binary tuyệt đối, {port}). pw_env: tên
# biến môi trường nhận mật khẩu (None nếu app không cần).
APP_REGISTRY = {
    "9router": {
        "label": "9Router",
        "npm_global": "9router",
        "bin": "9router",
        "port": 20128,
        "exec": "{bin} --no-browser --host 127.0.0.1 --port {port}",
        "pw_env": "INITIAL_PASSWORD",
        # 9Router đòi TTY (in spinner "Checking for updates…") — dưới systemd không
        # có tty nên nó tự thoát ngay. Bọc trong `script` để cấp pty giả.
        "needs_tty": True,
    },
    "ollama": {
        "label": "Ollama",
        "install_sh": "curl -fsSL https://ollama.com/install.sh | sh",
        "bin": "ollama",
        "port": 11434,
        "exec": "{bin} serve",
        "pw_env": None,
        "env": {"OLLAMA_HOST": "127.0.0.1:11434"},
    },
}

# name -> {status: installing|running|error, log: str, ts}
_STATUS: dict = {}
_LOCK = threading.Lock()


def _sudo(args, timeout=600):
    """sudo không tương tác (-n). Trả (rc, output)."""
    try:
        p = subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _port_alive(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True  # có phản hồi HTTP (kể cả 401/403) = app đang sống
    except Exception:
        return False


def _set(name, status, line=""):
    with _LOCK:
        cur = _STATUS.setdefault(name, {"status": status, "log": "", "ts": 0})
        cur["status"] = status
        cur["ts"] = int(time.time())
        if line:
            cur["log"] = (cur["log"] + line + "\n")[-4000:]


def _install_worker(name: str, spec: dict, password: str):
    try:
        _set(name, "installing", f"[{spec['label']}] bắt đầu cài…")

        # 1) Cài binary (npm global hoặc script chính thức)
        if spec.get("npm_global"):
            _set(name, "installing", f"npm install -g {spec['npm_global']} …")
            rc, out = _sudo(["npm", "install", "-g", spec["npm_global"]], timeout=600)
            if rc != 0:
                _set(name, "error", "Cài npm lỗi:\n" + out[-1500:])
                return
        elif spec.get("install_sh"):
            _set(name, "installing", "Chạy script cài chính thức…")
            rc, out = _sudo(["bash", "-lc", spec["install_sh"]], timeout=900)
            if rc != 0:
                _set(name, "error", "Script cài lỗi:\n" + out[-1500:])
                return

        # 2) Đường dẫn binary tuyệt đối
        binpath = shutil.which(spec["bin"]) or f"/usr/bin/{spec['bin']}"
        if not os.path.exists(binpath):
            _set(name, "error", f"Không tìm thấy binary {spec['bin']} sau khi cài.")
            return

        port = spec["port"]
        exec_line = spec["exec"].format(bin=binpath, port=port)
        # App đòi TTY → chạy trong pty giả bằng `script` (exec_line không chứa dấu
        # nháy đơn nên nhét vào script -c '...' an toàn).
        if spec.get("needs_tty"):
            sc = shutil.which("script") or "/usr/bin/script"
            exec_line = f"{sc} -qfc '{exec_line}' /dev/null"

        # 3) Ghi unit systemd (mật khẩu + env qua Environment=, Python ghi — không injection)
        env_lines = []
        if spec.get("pw_env") and password:
            env_lines.append(f'Environment="{spec["pw_env"]}={password}"')
        for k, v in (spec.get("env") or {}).items():
            env_lines.append(f'Environment="{k}={v}"')
        user = os.environ.get("USER") or "ubuntu"
        home = os.path.expanduser("~")
        unit = (
            "[Unit]\n"
            f"Description=TubeCLI app: {spec['label']}\n"
            "After=network.target\n\n"
            "[Service]\n"
            f"User={user}\n"
            f"WorkingDirectory={home}\n"
            + ("\n".join(env_lines) + ("\n" if env_lines else "")) +
            f"ExecStart={exec_line}\n"
            "Restart=always\nRestartSec=3\n\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )
        tmp = f"/tmp/tc_app_{name}.service"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(unit)
        rc, out = _sudo(["cp", tmp, f"/etc/systemd/system/{name}.service"])
        if rc != 0:
            _set(name, "error", "Ghi unit lỗi:\n" + out[-800:])
            return

        # 4) Dừng tiến trình cũ (nếu chạy foreground chiếm cổng) rồi bật service
        _sudo(["pkill", "-f", spec["bin"]], timeout=15)
        time.sleep(1)
        _sudo(["systemctl", "daemon-reload"])
        rc, out = _sudo(["systemctl", "enable", "--now", f"{name}.service"], timeout=120)
        if rc != 0:
            _set(name, "error", "Bật service lỗi:\n" + out[-1200:])
            return

        # 5) Chờ cổng sống (tối đa 60s)
        _set(name, "installing", f"Chờ {spec['label']} lên cổng {port}…")
        for _ in range(30):
            if _port_alive(port):
                _set(name, "running", f"✓ {spec['label']} đang chạy ở cổng {port}.")
                return
            time.sleep(2)
        _set(name, "error", f"Đã cài nhưng cổng {port} chưa phản hồi. Kiểm tra: systemctl status {name}")
    except Exception as e:  # noqa: BLE001
        _set(name, "error", f"Lỗi không rõ: {e}")


class InstallReq(BaseModel):
    password: str | None = None


@router.get("/catalog")
async def catalog():
    """Danh sách app cài được + cổng."""
    return {"apps": [
        {"name": n, "label": s["label"], "port": s["port"], "needs_password": bool(s.get("pw_env"))}
        for n, s in APP_REGISTRY.items()
    ]}


@router.post("/{name}/install")
async def install_app(name: str, req: InstallReq):
    spec = APP_REGISTRY.get(name)
    if not spec:
        raise HTTPException(404, f"App '{name}' không được hỗ trợ")
    if shutil.which("systemctl") is None:
        raise HTTPException(400, "Server không có systemd — không cài dạng service được.")
    with _LOCK:
        cur = _STATUS.get(name)
        if cur and cur["status"] == "installing":
            return {"status": "installing", "message": "Đang cài, chờ chút…"}
    _set(name, "installing", "")
    threading.Thread(target=_install_worker, args=(name, spec, req.password or ""), daemon=True).start()
    return {"status": "installing", "port": spec["port"]}


@router.get("/{name}/status")
async def app_status(name: str):
    spec = APP_REGISTRY.get(name)
    if not spec:
        raise HTTPException(404, f"App '{name}' không được hỗ trợ")
    with _LOCK:
        cur = dict(_STATUS.get(name) or {"status": "unknown", "log": ""})
    # Đồng bộ với thực tế: nếu chưa từng cài trong phiên này nhưng cổng đang sống → running
    if cur.get("status") in (None, "unknown") and _port_alive(spec["port"]):
        cur["status"] = "running"
    cur["port"] = spec["port"]
    cur["installed"] = shutil.which(spec["bin"]) is not None
    return cur
