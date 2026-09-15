"""yt-dlp của máy chủ: thiếu thì cài, cũ thì tự cập nhật (15/9/2026).

User: "không có chỗ nào bấm để install yt-dlp?" + "khi có yêu cầu tải subtitle từ youtube hay download thì kiểm tra
thư viện và tự động update". Đo trên máy dev trước khi làm:
  * Video Downloader dò `which yt-dlp` — dịch vụ systemd (và .venv trên Windows) không có thư mục Scripts/bin của
    Python trong PATH, nên máy chủ CÓ yt-dlp (thư viện) vẫn báo "yt-dlp not installed", nút Info lỗi 500
    "[WinError 2]", và pip chạy lại (tới 120 s) mỗi lần bấm.
  * YouTube đổi trang thường xuyên; yt-dlp cũ hỏng kiểu "Unable to extract … Confirm you are on the latest version".

Ở đây:
  status()            thư viện Python CỦA máy chủ (importlib.metadata), không phải lệnh trên PATH
  cli_command()       [python, -m, yt_dlp] — luôn khớp thư viện đang dùng, không khoá yt-dlp.exe khi pip nâng cấp
  ensure()            thiếu → pip install; bật tự cập nhật → dò PyPI tối đa CHECK_EVERY một lần, có bản mới → pip
                      install --upgrade rồi xoá yt_dlp khỏi sys.modules (lần import sau nạp mã mới, không restart).
                      Một khoá cho mọi lượt pip; cập nhật hỏng thì nhớ, không cài lại tới hết cửa sổ.
  looks_outdated(msg) lỗi yt-dlp kiểu "hãy dùng bản mới nhất" → người gọi ensure(force_check=True) rồi thử lại một lần
Trạng thái (lần dò, bản mới nhất, lỗi gần nhất) ở data/ytdlp_update.json.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("tubecli.ytdlp_manager")

PACKAGE = "yt-dlp"
MODULE = "yt_dlp"
# yt-dlp[default] kéo theo yt-dlp-ejs — bộ giải thử thách JavaScript của YouTube, khoá đúng phiên bản với yt-dlp.
# Chạy thật 15/9/2026: cookie tài khoản (hồ sơ vừa mở ẩn) mà thiếu bộ giải + JS runtime → "The page needs to be
# reloaded"; cùng cookie, có yt-dlp-ejs + node → lấy được phụ đề.
PACKAGE_SPEC = "yt-dlp[default]"
EJS_MODULE = "yt_dlp_ejs"
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
CHECK_EVERY = 6 * 3600          # dò PyPI tối đa 6 giờ một lần
PIP_TIMEOUT = 300
STATE_FILE: Optional[str] = None  # test trỏ sang thư mục tạm
_LOCK = threading.Lock()
_OUTDATED_MARKERS = ("confirm you are on the latest version", "please report this issue", "unable to extract",
                     "nsig extraction failed", "signature extraction failed", "failed to extract any player response",
                     "unable to download api page")


# ── phiên bản ───────────────────────────────────────────────────────────────

def module_available() -> bool:
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec(MODULE) is not None
    except (ImportError, ValueError):
        return False


def installed_version() -> str:
    """Bản yt-dlp mà Python CỦA máy chủ đang có ("" = chưa cài). Đọc dist-info trên đĩa nên đúng ngay sau pip."""
    importlib.invalidate_caches()
    try:
        from importlib import metadata
        return str(metadata.version(PACKAGE) or "")
    except Exception:      # noqa: BLE001
        return ""


def _vtuple(v) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def is_newer(candidate: str, current: str) -> bool:
    """2026.09.01 > 2026.08.19; bản nightly 2026.08.19.232150 > 2026.08.19; bằng nhau / rỗng → False."""
    a = _vtuple(candidate)
    return bool(a) and a > _vtuple(current)


def latest_version(timeout: int = 8) -> str:
    """Bản mới nhất trên PyPI ("" khi không hỏi được — mất mạng không được chặn lượt tải)."""
    try:
        req = urllib.request.Request(PYPI_URL, headers={"User-Agent": "TubeCLI"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str((json.loads(resp.read().decode("utf-8")).get("info") or {}).get("version") or "")
    except Exception as e:      # noqa: BLE001
        logger.info("yt-dlp latest version check failed: %s", e)
        return ""


def looks_outdated(message: str) -> bool:
    low = str(message or "").lower()
    return any(m in low for m in _OUTDATED_MARKERS)


def cli_command() -> Optional[List[str]]:
    """Lệnh yt-dlp của máy chủ: `python -m yt_dlp` trước, rồi mới tới yt-dlp trên PATH."""
    if module_available():
        return [sys.executable, "-m", MODULE]
    exe = shutil.which("yt-dlp")
    return [exe] if exe else None


def ejs_available() -> bool:
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec(EJS_MODULE) is not None
    except (ImportError, ValueError):
        return False


def js_runtimes() -> Dict[str, Dict[str, str]]:
    """JS runtime cho yt-dlp giải thử thách YouTube: deno (mặc định của yt-dlp) nếu có, node (TubeCLI luôn cần node
    cho browser), bun. Rỗng = để yt-dlp tự lo."""
    out: Dict[str, Dict[str, str]] = {}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            out[name] = {"path": path}
    return out


def js_runtime_opts() -> Dict[str, Any]:
    """Tuỳ chọn YoutubeDL; yt-dlp mặc định chỉ bật deno — máy chủ TubeCLI thường chỉ có node."""
    rt = js_runtimes()
    return {"js_runtimes": rt} if rt else {}


def cli_js_args() -> List[str]:
    return [arg for name in js_runtimes() for arg in ("--js-runtimes", name)]


def auto_update_enabled() -> bool:
    """Tuỳ chọn «Tự cập nhật yt-dlp» ở Video Downloader → Settings (mặc định bật)."""
    try:
        from tubecli.extensions.video_downloader.routes import _get_settings
        v = (_get_settings() or {}).get("ytdlp_auto_update", True)
    except Exception:      # noqa: BLE001
        v = True
    if v is None or v == "":
        return True
    return v is not False and str(v).strip().lower() not in ("0", "false", "no", "off")


# ── trạng thái ──────────────────────────────────────────────────────────────

def _state_path() -> str:
    if STATE_FILE:
        return STATE_FILE
    try:
        from tubecli.config import DATA_DIR
        return os.path.join(str(DATA_DIR), "ytdlp_update.json")
    except Exception:      # noqa: BLE001
        return os.path.join("data", "ytdlp_update.json")


def _load_state() -> Dict[str, Any]:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:      # noqa: BLE001
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:      # noqa: BLE001
        logger.warning("could not save yt-dlp update state: %s", e)


def status() -> Dict[str, Any]:
    st = _load_state()
    ver = installed_version() if module_available() else ""
    return {"installed": bool(ver), "version": ver, "cli": cli_command(), "auto_update": auto_update_enabled(),
            "challenge_solver": ejs_available(), "js_runtimes": sorted(js_runtimes()),
            "latest": str(st.get("latest") or ""), "checked_at": float(st.get("checked_at") or 0),
            "last_error": str(st.get("last_error") or "")}


# ── pip ─────────────────────────────────────────────────────────────────────

def _pip(args: List[str], timeout: int = PIP_TIMEOUT) -> Tuple[bool, str]:
    """(thành công, vài dòng cuối của pip khi hỏng)."""
    kw: Dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check"],
                           capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return False, f"pip timed out after {timeout} s"
    except Exception as e:      # noqa: BLE001
        return False, str(e)[:300]
    finally:
        importlib.invalidate_caches()
    if r.returncode == 0:
        return True, ""
    tail = " | ".join((r.stderr or r.stdout or "").strip().splitlines()[-3:])[:400] or f"pip exited with {r.returncode}"
    if "no module named pip" in tail.lower():
        tail += " — the server's Python has no pip; run: python -m ensurepip --upgrade"
    return False, tail


def pip_install(packages: List[str], upgrade: bool = False, timeout: int = PIP_TIMEOUT) -> Tuple[bool, str]:
    return _pip(["install", *(["--upgrade"] if upgrade else []), *packages], timeout)


def _reload_module() -> None:
    """Xoá yt_dlp khỏi sys.modules: lượt import sau nạp mã vừa cài. Lượt tải đang chạy giữ module cũ của nó."""
    for name in [k for k in list(sys.modules) if k == MODULE or k.startswith(MODULE + ".")]:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


# ── đảm bảo có yt-dlp dùng được ─────────────────────────────────────────────

def ensure(update: Optional[bool] = None, force_check: bool = False,
           progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """{"ok", "version", "action", "message", "latest"}; action: none | installed | install_failed | updated |
    update_failed. ok=False CHỈ khi không có yt-dlp dùng được. update=None → theo tuỳ chọn tự cập nhật;
    force_check=True (nút Update / lỗi kiểu bản cũ) → dò PyPI ngay và thử cả bản từng cập nhật hỏng."""
    say = progress or (lambda msg: None)
    with _LOCK:
        cur = installed_version() if module_available() else ""
        if not cur:
            say("yt-dlp is not installed on this server — installing it")
            ok, tail = pip_install([PACKAGE_SPEC], upgrade=True)
            _reload_module()
            cur = installed_version() if module_available() else ""
            st = _load_state()
            if not cur:
                msg = f"Could not install yt-dlp: {tail or 'pip reported success but the module is still missing'}"
                st.update(last_error=msg, failed_at=time.time())
                _save_state(st)
                return {"ok": False, "version": "", "action": "install_failed", "message": msg, "latest": ""}
            st.update(last_error="", installed_at=time.time(), latest=cur, checked_at=time.time())
            _save_state(st)
            return {"ok": True, "version": cur, "action": "installed", "message": f"Installed yt-dlp {cur}",
                    "latest": cur}
        if not ejs_available():
            # Bản cài cũ chỉ có "yt-dlp", thiếu bộ giải thử thách JS: cài kèm, GIỮ đúng bản yt-dlp đang có.
            st = _load_state()
            now = time.time()
            if force_check or now - float(st.get("ejs_failed_at") or 0) >= CHECK_EVERY:
                say("installing yt-dlp-ejs (YouTube JavaScript challenge solver)")
                ok, tail = pip_install([f"{PACKAGE_SPEC}=={cur}"])
                _reload_module()
                st = _load_state()
                if ejs_available():
                    st.update(ejs_failed_at=0)
                else:
                    st.update(ejs_failed_at=now,
                              last_error=f"Could not install yt-dlp-ejs: {tail or 'the module is still missing'}")
                _save_state(st)
        if update is None:
            update = auto_update_enabled()
        none = {"ok": True, "version": cur, "action": "none", "message": "", "latest": ""}
        if not update and not force_check:
            return none
        st = _load_state()
        now = time.time()
        latest = str(st.get("latest") or "")
        if force_check or now - float(st.get("checked_at") or 0) >= CHECK_EVERY:
            latest = latest_version() or latest
            st.update(checked_at=now, latest=latest)
            _save_state(st)
        none["latest"] = latest
        if not latest or not is_newer(latest, cur):
            return none
        if (not force_check and st.get("failed_version") == latest
                and now - float(st.get("failed_at") or 0) < CHECK_EVERY):
            return {**none, "message": str(st.get("last_error") or "")}
        say(f"updating yt-dlp {cur} → {latest}")
        ok, tail = pip_install([PACKAGE_SPEC], upgrade=True)
        _reload_module()
        new = (installed_version() if module_available() else "") or cur
        if is_newer(latest, new):
            msg = f"Could not update yt-dlp {cur} → {latest}: {tail or 'the version did not change'}"
            st.update(failed_version=latest, failed_at=now, last_error=msg)
            _save_state(st)
            logger.warning(msg)
            return {"ok": True, "version": new, "action": "update_failed", "message": msg, "latest": latest}
        st.update(failed_version="", last_error="", updated_at=now)
        _save_state(st)
        logger.info("yt-dlp updated %s → %s", cur, new)
        return {"ok": True, "version": new, "action": "updated", "message": f"yt-dlp updated {cur} → {new}",
                "latest": latest}
