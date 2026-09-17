"""Máy này thuộc tài khoản TubeCLI Cloud nào, mã công khai của server là gì — cloud báo sau mỗi lần đăng nhập hộ
(PUT /api/v1/instance/cloud-identity, lib/tubecli.js của cloud).

Dùng đặt thư mục cha khi task video lưu lên Google Drive: «<username>-vps-<mã server>/<tên project>» — nhiều máy
đăng chung một Drive vẫn biết ai đăng, từ máy nào (user 17/9/2026: "sử dụng đường dẫn tạo folder
username-vps-9/tenproject để biết được user nào đăng lên và ở server nào nếu tất cả đăng chung 1 drive").

Mã server là chuỗi NGẪU NHIÊN cloud cấp (lib/serverCode.js), KHÔNG phải số thứ tự servers.id: "vps-41" cho người
nhận link Sheet biết hệ thống đã có ít nhất 41 máy (user: "người dùng họ xài họ sẽ biết có bao nhiêu server và dò
được"). File của lõi .116 chỉ có server_id → coi như chưa biết, chờ cloud báo mã.

Máy chưa từng được cloud đăng nhập hộ (chạy tự quản) thì dùng tên máy: «tubecli-<hostname>».
"""
import json
import os
import re
import socket
import time
from typing import Any, Dict

# Username của cloud: a-z 0-9 _ . - (8–32 khi đăng ký; tài khoản cũ như "admin" ngắn hơn) — nhận rộng hơn
# một chút nhưng KHÔNG nhận "/" hay khoảng trắng: nó thành tên thư mục trên Drive.
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Mã server cloud cấp: 6 ký tự a-z 2-9 (chừa rộng 4–16 cho sau này).
_CODE = re.compile(r"^[a-z0-9]{4,16}$")


def _path() -> str:
    from tubecli.config import DATA_DIR

    return os.path.join(str(DATA_DIR), "cloud_identity.json")


def load() -> Dict[str, Any]:
    """{"username", "server_code", "seen"} hay {} khi chưa biết / file hỏng / file cũ chỉ có số thứ tự."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    u, code = data.get("username"), data.get("server_code")
    if not (isinstance(u, str) and _USERNAME.match(u) and isinstance(code, str) and _CODE.match(code)):
        return {}
    return {"username": u, "server_code": code, "seen": data.get("seen")}


def save(username: Any, server_code: Any) -> Dict[str, Any]:
    """Ghi danh tính cloud báo; sai dạng → ValueError. Không đổi gì thì không ghi lại file."""
    u = str(username or "").strip()
    if not _USERNAME.match(u):
        raise ValueError("username must be 1-64 characters of A-Z a-z 0-9 . _ -")
    if not isinstance(server_code, str) or not _CODE.match(server_code.strip().lower()):
        raise ValueError("server_code must be 4-16 characters of a-z 0-9")
    code = server_code.strip().lower()
    old = load()
    if old.get("username") == u and old.get("server_code") == code:
        return old
    data = {"username": u, "server_code": code, "seen": time.time()}
    path = _path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return data


def drive_root_name() -> str:
    """Tên thư mục cha trên Google Drive: «tuan89tk-vps-k7m2qx»; máy chưa nối cloud: «tubecli-<tên máy>»."""
    ident = load()
    if ident:
        return f"{ident['username']}-vps-{ident['server_code']}"
    host = re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname() or "").strip("-.")[:40]
    return f"tubecli-{host}" if host else "tubecli"
