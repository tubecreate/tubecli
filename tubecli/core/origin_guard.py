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


_local_ip_cache = None


def _local_ip_addresses() -> set:
    """Every IP address this machine answers on.

    An Origin whose host is one of OUR OWN addresses is same-origin by
    definition — the browser is talking to this server at the address it really
    has. Refusing those is what made the dashboard unusable on a VPS: the page
    loads over http://43.155.135.49:5295 (navigation sends no Origin), then
    every write from that page carries Origin: http://43.155.135.49:5295 and was
    refused as "cross-origin" against itself.

    This does NOT reopen DNS rebinding, which is why the allowlist was strict.
    Rebinding needs an attacker-controlled NAME that resolves to us; the victim's
    browser then sends Origin: http://evil.com. A bare IP literal cannot be
    rebound — if the Origin says 43.155.135.49, the browser really is pointed at
    43.155.135.49. Only literal addresses of this host are added here; hostnames
    still require TUBECLI_ALLOWED_ORIGIN_HOSTS.

    Cached: the addresses do not change while the process runs, and this is on
    the path of every request.
    """
    global _local_ip_cache
    if _local_ip_cache is not None:
        return _local_ip_cache

    found = set()
    try:
        import socket

        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            addr = sockaddr[0]
            if addr:
                found.add(str(addr).lower())
    except Exception:
        pass
    # The address used to reach the internet, which on a cloud VM is often the
    # only one gethostbyname misses. No packet is sent — connect() on a UDP
    # socket just picks the route.
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            found.add(s.getsockname()[0].lower())
        finally:
            s.close()
    except Exception:
        pass

    _local_ip_cache = found
    return found


# Hosts learned by someone proving they hold the dashboard password. See
# remember_host().
_learned_hosts: set = set()


def remember_host(origin: str, host_header: str) -> None:
    """Trust this address from now on, because someone just authenticated on it.

    The NAT problem this solves: a cloud VM's own interface holds a private
    address, so _local_ip_addresses() never contains the public IP the user
    actually browses to. On Tencent/AWS/GCP the machine has no way to know that
    address — but the browser does, and it tells us in the Host header.

    Only recorded when the login SUCCEEDED and the Origin and Host agree, i.e.
    a browser sitting on that address proved it holds the password. Host alone
    is caller-controlled and is never enough: a curl with a forged Host and the
    right password would otherwise be able to allowlist anything. Requiring
    Origin == Host means a real browser really was there — and anyone who has
    the password has already won by every other measure.

    Not persisted. It is re-learned on the next login after a restart, which
    keeps a stale entry from outliving a change of address.
    """
    o, h = _host_of(origin), _host_of(host_header)
    if o and h and o == h and o not in _LOOPBACK_HOSTS:
        _learned_hosts.add(o)


def _allowed_hosts() -> set:
    extra = os.environ.get("TUBECLI_ALLOWED_ORIGIN_HOSTS", "")
    hosts = set(_LOOPBACK_HOSTS)
    hosts |= _local_ip_addresses()
    hosts |= _learned_hosts
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


def is_origin_allowed(origin: str, host: str = "") -> bool:
    """Bản trả bool, không raise — dùng cho middleware bọc toàn bộ API surface.

    `host` hiện chưa dùng để quyết định (xem chú thích về DNS rebinding ở trên:
    Host header do kẻ tấn công điều khiển nên KHÔNG được tin). Giữ tham số để
    caller truyền vào mà không phải sửa lại chữ ký sau này.
    """
    if not origin:
        return True   # không phải trình duyệt → không có nguy cơ cross-site
    return _host_of(origin) in _allowed_hosts()


def guard_origin(request: Request):
    """Dependency cho từng router. Middleware toàn cục trong api/server.py đã
    bọc mọi route; giữ hàm này cho các router muốn nêu rõ yêu cầu tại chỗ."""
    if is_origin_allowed(request.headers.get("origin"),
                         request.headers.get("host", "")):
        return
    raise HTTPException(403, "Cross-origin request bị từ chối.")
