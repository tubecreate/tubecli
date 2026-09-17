"""Máy này thuộc tài khoản TubeCLI Cloud nào, là server số mấy — cloud báo sau mỗi lần đăng nhập hộ
(PUT /api/v1/instance/cloud-identity, lib/tubecli.js của cloud).

Dùng đặt thư mục cha khi task video lưu lên Google Drive: «<username>-vps-<server_id>/<tên project>» —
nhiều máy đăng chung một Drive vẫn biết ai đăng, từ máy nào (user 17/9/2026: "sử dụng đường dẫn tạo folder
username-vps-9/tenproject để biết được user nào đăng lên và ở server nào nếu tất cả đăng chung 1 drive").

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


def _path() -> str:
    from tubecli.config import DATA_DIR

    return os.path.join(str(DATA_DIR), "cloud_identity.json")


def _valid(username: Any, server_id: Any) -> bool:
    return bool(_USERNAME.match(str(username or ""))) and type(server_id) is int and server_id > 0


def load() -> Dict[str, Any]:
    """{"username", "server_id", "seen"} hay {} khi chưa biết / file hỏng."""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not _valid(data.get("username"), data.get("server_id")):
        return {}
    return {"username": data["username"], "server_id": data["server_id"], "seen": data.get("seen")}


def save(username: Any, server_id: Any) -> Dict[str, Any]:
    """Ghi danh tính cloud báo; sai dạng → ValueError. Không đổi gì thì không ghi lại file."""
    u = str(username or "").strip()
    if not _USERNAME.match(u):
        raise ValueError("username must be 1-64 characters of A-Z a-z 0-9 . _ -")
    if isinstance(server_id, bool):
        raise ValueError("server_id must be a positive integer")
    try:
        sid = int(server_id)
    except (TypeError, ValueError):
        raise ValueError("server_id must be a positive integer")
    if sid <= 0:
        raise ValueError("server_id must be a positive integer")
    old = load()
    if old.get("username") == u and old.get("server_id") == sid:
        return old
    data = {"username": u, "server_id": sid, "seen": time.time()}
    path = _path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return data


def drive_root_name() -> str:
    """Tên thư mục cha trên Google Drive: «tuan89tk-vps-9»; máy chưa nối cloud: «tubecli-<tên máy>»."""
    ident = load()
    if ident:
        return f"{ident['username']}-vps-{ident['server_id']}"
    host = re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname() or "").strip("-.")[:40]
    return f"tubecli-{host}" if host else "tubecli"
