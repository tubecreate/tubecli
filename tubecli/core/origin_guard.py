"""Origin-guard dùng chung — chặn request cross-origin từ TRÌNH DUYỆT tới các
endpoint chứa/thao tác secret (CF token, AI key, deploy...).

Bối cảnh: server bật CORS `allow_origins=["*"]` toàn cục và không có auth. Bất kỳ
trang web nào người dùng mở trong trình duyệt đều có thể `fetch(...)` tới
`http://127.0.0.1:PORT/api/...` và đọc secret / kích side-effect (CSRF). Guard này
chặn ngay tại tầng route:

- Không có header `Origin`  → client server-side (curl, Telegram, tiến trình nội
  bộ) → CHO QUA (không có nguy cơ cross-site).
- Origin host thuộc allowlist (mặc định loopback: localhost/127.0.0.1/::1) → QUA.
- Còn lại (evil.com...) → 403.

QUAN TRỌNG — vì sao KHÔNG dùng "same-origin theo Host header": một phiên bản trước
cho qua khi `Origin host == Host header host`. Điều đó bị DNS rebinding phá: nạn
nhân mở evil.com, kẻ tấn công rebind evil.com → 127.0.0.1, trình duyệt gửi request
tới `http://evil.com:PORT/...` với Origin=Host=evil.com → guard cho qua. Host header
do kẻ tấn công điều khiển nên KHÔNG được tin. Allowlist tường minh (mặc định
loopback) chặn được cả rebinding lẫn cross-origin đơn giản.

Phục vụ trên host khác loopback (`--host 0.0.0.0` / LAN / tunnel): người dùng CHỦ
ĐỘNG thêm host vào env `TUBECLI_ALLOWED_ORIGIN_HOSTS` (phẩy ngăn cách). Đây là lựa
chọn opt-in có ý thức, không phải mặc định mở.

EventSource (SSE) cũng gửi Origin nên được bảo vệ mà không cần custom header.
"""
import os
from urllib.parse import urlparse
from fastapi import Request, HTTPException

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _allowed_hosts() -> set:
    extra = os.environ.get("TUBECLI_ALLOWED_ORIGIN_HOSTS", "")
    hosts = set(_LOOPBACK_HOSTS)
    for h in extra.split(","):
        h = h.strip().lower()
        if h:
            hosts.add(h)
    return hosts


def _host_of(value: str) -> str:
    if not value:
        return ""
    v = value.strip()
    try:
        if "://" not in v:
            v = "//" + v
        return (urlparse(v).hostname or "").lower()
    except Exception:
        return ""


def guard_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin:
        return  # không phải trình duyệt → bỏ qua
    if _host_of(origin) in _allowed_hosts():
        return
    raise HTTPException(403, "Cross-origin request bị từ chối.")
