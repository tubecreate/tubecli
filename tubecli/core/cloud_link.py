"""Liên kết máy ↔ TubeCLI Cloud: máy này có nối cloud không, và báo cloud mật khẩu dashboard mới.

Vì sao có module này (user 29/10/2026): «bên tubecli setting … không có chỗ để đồng bộ pass với cloud».
Cloud giữ bản mã hoá mật khẩu dashboard để đăng nhập hộ (Flow Builder, live view, nút Dashboard ↗).
Đổi mật khẩu trên máy mà cloud không biết là cloud mất quyền vào máy — Flow báo «TubeCLI login failed».
Trước đây chỉ app TubeCLI Connect báo được (client/tubecli_connect.pyw `sync_cloud_password`); bảng điều
khiển TubeCLI không có chỗ nào, còn VPS thì không có Connect.

Cách chứng minh «đây đúng là máy X»: TUNNEL TOKEN của cloudflared — thứ chỉ máy này và cloud biết. Route
cloud `/api/servers/pair/password` (có từ 16/9/2026) so token với Cloudflare, rồi tự đăng nhập vào máy
qua tunnel bằng mật khẩu ấy trước khi lưu — mật khẩu sai không bao giờ được ghi.

Token nằm ở:
  • máy local ghép nối bằng TubeCLI Connect: `connect.json` (khoá `tunnel_token`) trong thư mục cấu hình
    của Connect — %APPDATA%\\TubeCLI (Windows), ~/Library/Application Support/TubeCLI (macOS),
    $XDG_CONFIG_HOME/tubecli hoặc ~/.config/tubecli (Linux);
  • VPS do cloud cài: /etc/cloudflared/token (provisioner ghi, chmod 600);
  • biến môi trường TUNNEL_TOKEN / TUBECLI_TUNNEL_TOKEN.
Token KHÔNG bao giờ ra khỏi module này (link_status chỉ nói có hay không, và lấy ở đâu).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Tuple

PAIR_PASSWORD_PATH = "/api/servers/pair/password"


def cloud_url() -> str:
    return os.environ.get("TUBECLI_CLOUD_URL", "https://cloud.tubecreate.com").rstrip("/")


def connect_homes() -> List[str]:
    """Mọi thư mục cấu hình TubeCLI Connect có thể có (không lọc theo hệ: rẻ, và chạy WSL / chép tay vẫn thấy)."""
    override = os.environ.get("TUBECLI_CONNECT_HOME")
    if override:
        return [override]
    home = os.path.expanduser("~")
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(os.path.join(appdata, "TubeCLI"))
    out.append(os.path.join(home, "Library", "Application Support", "TubeCLI"))
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        out.append(os.path.join(xdg, "tubecli"))
    out.append(os.path.join(home, ".config", "tubecli"))
    return out


def token_files() -> List[str]:
    override = os.environ.get("TUBECLI_TUNNEL_TOKEN_FILE")
    return [override] if override else ["/etc/cloudflared/token"]


def find_tunnel_token() -> Tuple[str, str]:
    """(token, nguồn). Không có: ("", "none"); có tệp mà không đọc được (quyền): ("", "unreadable")."""
    for k in ("TUBECLI_TUNNEL_TOKEN", "TUNNEL_TOKEN"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v, "env"
    for d in connect_homes():
        p = os.path.join(d, "connect.json")
        try:
            with open(p, encoding="utf-8") as f:
                tok = str((json.load(f) or {}).get("tunnel_token") or "").strip()
            if tok:
                return tok, "connect"
        except (OSError, ValueError, AttributeError):
            continue
    unreadable = False
    for p in token_files():
        try:
            with open(p, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok, "vps"
        except PermissionError:
            unreadable = True
        except OSError:
            continue
    return "", ("unreadable" if unreadable else "none")


def link_status() -> Dict:
    """Cho bảng điều khiển: máy có nối cloud không. KHÔNG trả token."""
    tok, src = find_tunnel_token()
    return {"linked": bool(tok), "source": src, "cloud_url": cloud_url()}


def _version() -> str:
    try:
        from tubecli import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001
        return "?"


def sync_password(password: str, timeout: float = 60.0) -> Dict:
    """Báo cloud mật khẩu dashboard mới. {"ok": bool, "code": str, "error": str?, "server_id": int?}.

    Mã: synced · not_linked · token_unreadable · not_recognised (cloud không nhận ra máy) ·
    cloud_login_failed (cloud thử đăng nhập vào máy bằng mật khẩu này mà không được) ·
    cloud_unreachable · cloud_error. Đồng bộ: gọi trong asyncio.to_thread — cloud sẽ gọi NGƯỢC vào máy
    này qua tunnel để thử đăng nhập trong lúc chờ, nên event loop phải rảnh.
    """
    tok, src = find_tunnel_token()
    if not tok:
        if src == "unreadable":
            return {"ok": False, "code": "token_unreadable",
                    "error": "The tunnel token file exists but TubeCLI cannot read it (permissions)."}
        return {"ok": False, "code": "not_linked", "error": "This machine is not linked to TubeCLI Cloud."}
    body = json.dumps({"tunnel_token": tok, "tubecli_password": password}).encode()
    req = urllib.request.Request(
        cloud_url() + PAIR_PASSWORD_PATH, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": f"TubeCLI/{_version()} (cloud-link)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
        return {"ok": True, "code": "synced", "server_id": data.get("server_id"), "source": src}
    except urllib.error.HTTPError as e:
        try:
            detail = str((json.loads(e.read().decode("utf-8", "replace") or "{}") or {}).get("error") or "")
        except Exception:  # noqa: BLE001
            detail = ""
        code = {401: "not_recognised", 409: "cloud_login_failed"}.get(e.code, "cloud_error")
        return {"ok": False, "code": code, "status": e.code, "error": detail or f"HTTP {e.code}", "source": src}
    except Exception as e:  # noqa: BLE001 — mạng / DNS / timeout
        return {"ok": False, "code": "cloud_unreachable", "error": str(e)[:200], "source": src}
