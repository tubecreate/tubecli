"""Runs the bundled CapCut-TTS Node server as a background subprocess.

The CapCut login flow is 9,700 lines of TypeScript that tracks CapCut Web's
current auth (region, cookies, bundle extraction, websocket TTS). Reimplementing
that in Python would be fragile and would break every time CapCut shifts, so the
wrapper runs the real server (MIT-licensed, bundled under server/) and talks to
it over loopback HTTP.

Key facts this manager encodes (from the CapCut env schema):
  - The server REFUSES to boot without one valid CAPCUT_EMAIL + CAPCUT_PASSWORD,
    so it is only started once the user has added an account; the first enabled
    account seeds it.
  - Per-user requests then override that account with x-capcut-email /
    x-capcut-password headers (CAPCUT_ALLOW_REQUEST_CREDENTIALS=true).
  - Session / preview / bundle files are written relative to cwd unless the
    paths are ABSOLUTE, so all three are pointed at ext_data_path.
  - It binds 127.0.0.1 only — never exposed; the Python routes proxy it.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from tubecli.config import ext_data_path

logger = logging.getLogger("CapCutTTS.node")

_EXT = "capcut_tts"
_HOST = "127.0.0.1"

# CapCut returns voice display names in CAPCUT_LOCALE. Default ja-JP shows every
# name in Japanese katakana even for Spanish/Vietnamese voices, which is why the
# list read as Japanese. Map TubeCLI's global UI language onto a CapCut locale so
# names follow the dashboard language instead.
_LOCALE_MAP = {
    "vi": ("vi-VN", "VN"), "en": ("en-US", "US"), "zh": ("zh-CN", "CN"),
    "zh-TW": ("zh-TW", "TW"), "ja": ("ja-JP", "JP"), "ko": ("ko-KR", "KR"),
    "es": ("es-ES", "ES"), "tr": ("tr-TR", "TR"), "ru": ("ru-RU", "RU"),
}


def _capcut_locale() -> tuple:
    """(CAPCUT_LOCALE, CAPCUT_REGION) derived from the dashboard's language."""
    try:
        from tubecli.config import get_language
        lang = (get_language() or "en").strip()
    except Exception:
        lang = "en"
    return _LOCALE_MAP.get(lang, _LOCALE_MAP["en"])

SERVER_DIR = Path(__file__).resolve().parent / "server"
DIST_ENTRY = SERVER_DIR / "dist" / "index.js"
NODE_MODULES = SERVER_DIR / "node_modules"


def _data_dir() -> Path:
    d = ext_data_path(_EXT)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _free_port() -> int:
    """Ask the OS for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return s.getsockname()[1]


def _resolve_node() -> Optional[str]:
    # shutil.which so we pass an absolute path to Popen (shell=False). A bare
    # "node" with shell=True is the cross-platform trap browser/process_manager
    # documents: POSIX turns the arg list into `sh -c node …` and runs a bare
    # REPL. Absolute path + shell=False avoids it.
    return shutil.which("node")


def _resolve_npm() -> Optional[str]:
    # On Windows npm is npm.cmd; shutil.which finds the right one.
    return shutil.which("npm")


class CapCutNodeManager:
    """One background Node process, lazily built and started on first need."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._lock = threading.Lock()
        self._build_error: str = ""

    # ── build ──────────────────────────────────────────────────────────────
    def is_built(self) -> bool:
        return DIST_ENTRY.exists() and NODE_MODULES.exists()

    def build(self, timeout: int = 900) -> dict:
        """Make the server runnable, doing the LEAST work the situation needs.

        The extension ships dist/ pre-built (compiled once on a dev machine and
        committed), so a low-RAM VPS never runs tsc — the concern that a 2 GB box
        cannot compile 88 TypeScript files. Three cases:
          - dist present + node_modules present  → nothing to do.
          - dist present, node_modules missing   → `npm install --omit=dev`
            (7 runtime deps only, no TypeScript toolchain, no compile).
          - dist missing (dev checkout)          → full install + `npm run build`.
        Done lazily on first start, not on enable, so enabling stays instant.
        """
        npm = _resolve_npm()
        if not npm:
            return {"status": "error", "message": "Không tìm thấy npm. Hãy cài Node.js (https://nodejs.org)."}
        dist_present = DIST_ENTRY.exists()
        log = _data_dir() / "build.log"
        try:
            with open(log, "w", encoding="utf-8") as lf:
                if not NODE_MODULES.exists():
                    # --omit=dev when dist is shipped: skip typescript/tsc-alias/eslint,
                    # install only express/cors/hono/ws/zod/tslog/dotenv.
                    args = ["install", "--no-audit", "--no-fund"]
                    if dist_present:
                        args.insert(1, "--omit=dev")
                    logger.info("[CapCut] npm %s …", " ".join(args))
                    lf.write(f"=== npm {' '.join(args)} ===\n"); lf.flush()
                    r = subprocess.run([npm, *args], cwd=str(SERVER_DIR),
                                       stdout=lf, stderr=lf, timeout=timeout)
                    if r.returncode != 0:
                        return {"status": "error", "message": f"npm install lỗi (mã {r.returncode}). Xem {log}."}
                if not dist_present:
                    logger.info("[CapCut] npm run build … (dev, biên dịch TypeScript)")
                    lf.write("\n=== npm run build ===\n"); lf.flush()
                    r = subprocess.run([npm, "run", "build"], cwd=str(SERVER_DIR),
                                       stdout=lf, stderr=lf, timeout=timeout)
                    if r.returncode != 0:
                        return {"status": "error", "message": f"Build lỗi (mã {r.returncode}). Xem {log}."}
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": f"Cài đặt quá lâu (>{timeout}s). Xem {log}."}
        except Exception as e:
            return {"status": "error", "message": f"Cài đặt lỗi: {e}"}
        if not DIST_ENTRY.exists():
            return {"status": "error", "message": f"Thiếu {DIST_ENTRY.name} sau khi cài. Xem {log}."}
        return {"status": "success"}

    # ── lifecycle ──────────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _health_ok(self) -> bool:
        if not self._port:
            return False
        try:
            r = requests.get(f"http://{_HOST}:{self._port}/v2/languages", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def start(self, bootstrap: dict, timeout: int = 40) -> dict:
        """Start (or reuse) the Node server. `bootstrap` = {email, password} of
        the account that seeds it — required, because the server will not boot
        without one."""
        with self._lock:
            if self.is_running() and self._health_ok():
                return {"status": "success", "port": self._port, "reused": True}
            # A dead handle from a crashed run — clear it.
            if self._proc is not None and self._proc.poll() is not None:
                self._proc = None

            if not bootstrap or not bootstrap.get("email") or not bootstrap.get("password"):
                return {"status": "error", "message": "Chưa có tài khoản CapCut nào để khởi động server. Hãy thêm một tài khoản trước."}

            if not self.is_built():
                b = self.build()
                if b["status"] != "error" and not self.is_built():
                    b = {"status": "error", "message": "Build không tạo được dist."}
                if b.get("status") == "error":
                    self._build_error = b["message"]
                    return b

            node = _resolve_node()
            if not node:
                return {"status": "error", "message": "Không tìm thấy node trên PATH."}

            port = _free_port()
            data = _data_dir()
            locale, region = _capcut_locale()
            env = dict(os.environ)
            env.update({
                "HOST": _HOST,
                "PORT": str(port),
                "CAPCUT_EMAIL": bootstrap["email"],
                "CAPCUT_PASSWORD": bootstrap["password"],
                "CAPCUT_ALLOW_REQUEST_CREDENTIALS": "true",
                # Voice names + region follow the dashboard language.
                "CAPCUT_LOCALE": locale,
                "CAPCUT_REGION": region,
                # Absolute paths so session/preview/bundle land in the extension's
                # data dir, not the server's cwd.
                "CAPCUT_SESSION_STORE_PATH": str(data / "capcut-session.json"),
                "CAPCUT_SPEAKER_PREVIEW_TEMP_DIR": str(data / "speaker-preview"),
                "CAPCUT_BUNDLE_CONFIG_PATH": str(data / "capcut-bundle-config.json"),
                # Node block-buffers stdout to a pipe; keep the log readable.
                "NODE_NO_WARNINGS": "1",
            })
            log_path = data / "server.log"
            try:
                log = open(log_path, "w", encoding="utf-8")
                self._proc = subprocess.Popen(
                    [node, str(DIST_ENTRY)],
                    cwd=str(SERVER_DIR),
                    env=env,
                    stdout=log,
                    stderr=log,
                )
            except Exception as e:
                return {"status": "error", "message": f"Không khởi động được node: {e}"}
            self._port = port

            # Wait for readiness — the server logs in on boot, so give it room.
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    tail = ""
                    try:
                        tail = log_path.read_text(encoding="utf-8")[-800:]
                    except OSError:
                        pass
                    return {"status": "error",
                            "message": f"Server thoát ngay (mã {self._proc.returncode}). Log: …{tail}"}
                if self._health_ok():
                    logger.info(f"[CapCut] Node server ready on :{port} (pid {self._proc.pid})")
                    return {"status": "success", "port": port, "reused": False}
                time.sleep(1)
            return {"status": "error", "message": f"Server không sẵn sàng trong {timeout}s. Xem {log_path}."}

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                except Exception:
                    pass
                self._proc = None
                self._port = None

    def ensure_running(self, bootstrap: dict) -> dict:
        """Idempotent start — the routes call this before proxying."""
        if self.is_running() and self._health_ok():
            return {"status": "success", "port": self._port}
        return self.start(bootstrap)

    @property
    def port(self) -> Optional[int]:
        return self._port

    def base_url(self) -> Optional[str]:
        return f"http://{_HOST}:{self._port}" if self._port else None


node_manager = CapCutNodeManager()
