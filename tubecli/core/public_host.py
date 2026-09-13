"""Địa chỉ CÔNG KHAI của máy chủ này (tên miền tunnel, IP VPS) — để link trong kết quả
mở được từ Telegram/điện thoại, thay vì http://127.0.0.1:5295/… chỉ máy này hiểu.

Máy chủ không tự biết địa chỉ công khai của mình (VPS sau NAT, tunnel Cloudflare do
cloud dựng hộ); trình duyệt thì biết. Mỗi lần đăng nhập THÀNH CÔNG qua một địa chỉ
(origin_guard.remember_host — đã đòi mật khẩu đúng và Origin cùng site với Host),
ghi scheme + host vào data/public_host.json. Máy chạy không giao diện thì đặt env
TUBECLI_PUBLIC_URL, biến ấy thắng file.
"""
import json
import os
import time
from typing import Optional
from urllib.parse import urlparse

_LOCAL = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}


def _path() -> str:
    from tubecli.config import DATA_DIR

    return os.path.join(str(DATA_DIR), "public_host.json")


def _is_private(host: str) -> bool:
    """IP riêng (10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7) — không ai ngoài
    mạng nội bộ mở được, không phải địa chỉ công khai."""
    h = host.strip("[]")
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254) or a == 127
    low = h.lower()
    return low.startswith(("fc", "fd", "fe80"))


def remember(origin: str, host_header: str = "") -> Optional[str]:
    """Ghi địa chỉ công khai từ một lần đăng nhập thành công; trả về base đã ghi hay None.

    Host lấy từ Host header (địa chỉ NGƯỜI DÙNG gõ để tới máy này — cloud đăng nhập hộ
    thì Origin là cloud.tubecreate.com, Host mới là máy này); scheme lấy từ Origin (qua
    tunnel là https). Bỏ qua loopback, IP riêng, tên không có dấu chấm."""
    o = urlparse(origin.strip() if "://" in str(origin) else "https://" + str(origin).strip())
    raw_host = str(host_header or "").strip() or (o.netloc or "")
    hp = urlparse("//" + raw_host)
    host = (hp.hostname or "").lower()
    if not host or host in _LOCAL or "." not in host or _is_private(host):
        return None
    scheme = (o.scheme or "https").lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    port = hp.port
    base = f"{scheme}://{host}" + (f":{port}" if port and port not in (80, 443) else "")
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump({"base": base, "seen": time.time()}, f)
    except OSError:
        return None
    return base


def public_base_url() -> str:
    """"https://xxx.tubecreate.com" (không dấu / cuối) hay "" khi chưa biết."""
    env = os.environ.get("TUBECLI_PUBLIC_URL", "").strip().rstrip("/")
    if env:
        return env
    try:
        with open(_path(), encoding="utf-8") as f:
            return str((json.load(f) or {}).get("base") or "").rstrip("/")
    except (OSError, ValueError):
        return ""


def absolute(path: str) -> str:
    """"/s/abc" → "https://xxx.tubecreate.com/s/abc" khi biết địa chỉ; không thì giữ nguyên."""
    base = public_base_url()
    return base + path if base and str(path).startswith("/") else str(path)
