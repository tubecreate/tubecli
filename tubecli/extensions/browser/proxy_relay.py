"""Relay proxy cục bộ — Chrome trỏ vào một địa chỉ, upstream đổi bên dưới.

Hai vấn đề tệp này giải, cả hai đều đã được đo trên máy thật:

  1. SOCKS5 CÓ MẬT KHẨU. Đo trên 14 hồ sơ có proxy ở máy này: chỉ 2 chạy được.
     11 cái còn lại là SOCKS5 kèm đăng nhập, thứ Chromium không biết làm và
     Playwright chặn thẳng ("Browser does not support socks5 proxy
     authentication" — browserContext.js:665). routes.proxy_blocker đã ghi rõ
     kết luận: "Không có đường nào qua nếu không dựng một relay cục bộ."
     Relay nói HTTP với Chrome (không đăng nhập, chỉ nghe loopback) và tự đăng
     nhập SOCKS5 với upstream. 11 proxy kia dùng được ngay.

  2. XOAY THEO LỊCH. Playwright nhận proxy lúc launchPersistentContext và không
     đổi được cho context đang chạy, nên "đổi IP mỗi 30 phút" trước đây chỉ có
     cách khởi động lại trình duyệt — mất phiên đăng nhập, tức mất đúng thứ ta
     mở trình duyệt để giữ. Chrome trỏ vào relay MỘT lần; relay đổi upstream.

Giới hạn phải nói thẳng: đổi upstream chỉ áp dụng cho KẾT NỐI MỚI. Một kết nối
đang mở (websocket, tải tệp dài, video đang phát) giữ nguyên IP cũ đến khi đóng.
Không có cách nào khác trừ khi cắt ngang kết nối của người dùng, và cắt thì tệ
hơn là để nó chạy nốt.

Không dùng thư viện ngoài: máy này không có PySocks/python-socks, và bắt tay
SOCKS5 chỉ tốn vài chục dòng. Thêm phụ thuộc cho một giao thức năm 1996 là
không đáng, nhất là với dự án chạy được offline.
"""
import asyncio
import base64
import ipaddress
import logging
import socket
import struct
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Browser.ProxyRelay")

_SOCKS5_ERRORS = {
    0x01: "SOCKS5: máy chủ lỗi",
    0x02: "SOCKS5: bị luật của proxy từ chối",
    0x03: "SOCKS5: mạng không tới được",
    0x04: "SOCKS5: máy đích không tới được",
    0x05: "SOCKS5: máy đích từ chối kết nối",
    0x06: "SOCKS5: hết hạn TTL",
    0x07: "SOCKS5: proxy không hỗ trợ lệnh này",
    0x08: "SOCKS5: proxy không hỗ trợ kiểu địa chỉ",
}


# ── nói chuyện với upstream ─────────────────────────────────────────────────
async def _open_socks5(up: dict, host: str, port: int, timeout: float):
    """Mở đường hầm tới host:port qua một proxy SOCKS5, kèm đăng nhập nếu có."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(up["host"], up["port"]), timeout)
    try:
        methods = b"\x02\x00" if up["user"] else b"\x00"
        writer.write(b"\x05" + bytes([len(methods)]) + methods)
        await writer.drain()
        ver, method = await asyncio.wait_for(reader.readexactly(2), timeout)
        if ver != 5:
            raise OSError("Bên kia không nói SOCKS5")
        if method == 0x02:
            if not up["user"]:
                raise OSError("Proxy đòi đăng nhập nhưng không có tài khoản")
            u = up["user"].encode(); p = up["password"].encode()
            writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            await writer.drain()
            _v, status = await asyncio.wait_for(reader.readexactly(2), timeout)
            if status != 0:
                raise OSError("Sai tài khoản proxy")
        elif method == 0xFF:
            raise OSError("Proxy từ chối mọi cách đăng nhập")

        # Gửi tên miền nguyên văn (ATYP 0x03) chứ KHÔNG tự phân giải DNS: phân
        # giải ở máy này làm rò truy vấn DNS ra ngoài proxy, đúng thứ người dùng
        # cắm proxy để tránh.
        try:
            packed = ipaddress.ip_address(host)
            atyp = b"\x01" if packed.version == 4 else b"\x04"
            addr = packed.packed
        except ValueError:
            raw = host.encode("idna")
            atyp = b"\x03"
            addr = bytes([len(raw)]) + raw
        writer.write(b"\x05\x01\x00" + atyp + addr + struct.pack("!H", port))
        await writer.drain()

        head = await asyncio.wait_for(reader.readexactly(4), timeout)
        if head[1] != 0:
            raise OSError(_SOCKS5_ERRORS.get(head[1], f"SOCKS5: lỗi {head[1]}"))
        # Nuốt nốt địa chỉ ràng buộc, nếu không nó dính vào byte đầu của dữ liệu.
        if head[3] == 0x01:
            await reader.readexactly(4 + 2)
        elif head[3] == 0x04:
            await reader.readexactly(16 + 2)
        elif head[3] == 0x03:
            n = (await reader.readexactly(1))[0]
            await reader.readexactly(n + 2)
        return reader, writer
    except Exception:
        writer.close()
        raise


async def _open_http(up: dict, host: str, port: int, timeout: float):
    """Mở đường hầm qua proxy HTTP bằng CONNECT."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(up["host"], up["port"]), timeout)
    try:
        req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if up["user"]:
            token = base64.b64encode(
                f"{up['user']}:{up['password']}".encode()).decode()
            req += f"Proxy-Authorization: Basic {token}\r\n"
        req += "Proxy-Connection: keep-alive\r\n\r\n"
        writer.write(req.encode())
        await writer.drain()
        status = await asyncio.wait_for(reader.readline(), timeout)
        parts = status.decode("latin-1", "replace").split()
        if len(parts) < 2 or not parts[1].startswith("2"):
            raise OSError("Proxy HTTP trả " + status.decode("latin-1", "replace").strip())
        while True:  # đọc hết phần đầu
            line = await asyncio.wait_for(reader.readline(), timeout)
            if line in (b"\r\n", b"\n", b""):
                break
        return reader, writer
    except Exception:
        writer.close()
        raise


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter, counter: dict, key: str):
    try:
        while True:
            chunk = await src.read(65536)
            if not chunk:
                break
            counter[key] = counter.get(key, 0) + len(chunk)
            dst.write(chunk)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


class ProxyRelay:
    """Một relay cho một phiên trình duyệt.

    Nghe trên 127.0.0.1 ở cổng do hệ điều hành cấp. Chrome nhận
    `http://127.0.0.1:<port>` và không bao giờ biết upstream là gì, đổi lúc nào.
    """

    def __init__(self, name: str, upstream: Optional[str] = None,
                 connect_timeout: float = 20.0):
        self.name = name
        self.port: Optional[int] = None
        self._server: Optional[asyncio.AbstractServer] = None
        self._upstream: Optional[dict] = None
        self._upstream_str: Optional[str] = None
        self._timeout = connect_timeout
        self.stats: Dict[str, int] = {"connections": 0, "failures": 0, "rotations": 0}
        self.history: list = []
        if upstream:
            self.set_upstream(upstream)

    # ── upstream ────────────────────────────────────────────────────────────
    def set_upstream(self, proxy_str: Optional[str]) -> bool:
        """Đổi upstream. Chỉ ảnh hưởng KẾT NỐI MỚI — xem ghi chú đầu tệp."""
        if not proxy_str:
            self._upstream, self._upstream_str = None, None
            return True
        from .proxy_pool import normalise
        canon = normalise(proxy_str)
        if not canon:
            logger.warning("[%s] Chuỗi upstream không đọc được: %s", self.name, proxy_str)
            return False
        from .routes import parse_proxy
        info = parse_proxy(canon)
        changed = canon != self._upstream_str
        self._upstream = {
            "scheme": info["scheme"], "host": info["host"], "port": info["port"],
            "user": info["user"], "password": info["password"],
        }
        self._upstream_str = canon
        if changed:
            self.stats["rotations"] += 1
            self.history.append({"at": time.time(), "upstream": _mask(canon)})
            del self.history[:-20]
            logger.info("[%s] Upstream -> %s", self.name, _mask(canon))
        return True

    @property
    def upstream(self) -> Optional[str]:
        return self._upstream_str

    # ── vòng đời ────────────────────────────────────────────────────────────
    async def start(self) -> int:
        # Cổng 0: để hệ điều hành cấp. Tự chọn một số cố định sẽ đụng nhau ngay
        # khi mở hồ sơ thứ hai, và lỗi đó hiện ra dưới dạng "trình duyệt không
        # mở được" chứ không nói gì về cổng.
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        logger.info("[%s] Relay nghe ở 127.0.0.1:%s", self.name, self.port)
        return self.port

    async def stop(self):
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

    def local_url(self) -> Optional[str]:
        return f"http://127.0.0.1:{self.port}" if self.port else None

    # ── xử lý một kết nối từ Chrome ─────────────────────────────────────────
    async def _connect_upstream(self, host: str, port: int):
        up = self._upstream
        if not up:
            # Không có upstream nghĩa là ĐI THẲNG. Nói rõ trong log, vì im lặng
            # đi thẳng chính là "tưởng có proxy mà lộ IP thật".
            logger.warning("[%s] Chưa có upstream — đi thẳng tới %s:%s", self.name, host, port)
            return await asyncio.wait_for(asyncio.open_connection(host, port), self._timeout)
        if up["scheme"].startswith("socks"):
            return await _open_socks5(up, host, port, self._timeout)
        return await _open_http(up, host, port, self._timeout)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.stats["connections"] += 1
        up_writer = None
        try:
            request_line = await asyncio.wait_for(reader.readline(), 30)
            if not request_line:
                return
            parts = request_line.decode("latin-1", "replace").split()
            if len(parts) < 3:
                return
            method, target, version = parts[0], parts[1], parts[2]

            headers = []
            while True:
                line = await asyncio.wait_for(reader.readline(), 30)
                if line in (b"\r\n", b"\n", b""):
                    break
                headers.append(line)

            if method.upper() == "CONNECT":
                host, _, port_s = target.rpartition(":")
                port = int(port_s or 443)
            else:
                # Dạng tuyệt đối: GET http://host/path HTTP/1.1 — Chrome dùng cho
                # http trần. Phải dựng lại yêu cầu ở dạng gốc cho máy chủ đích.
                if "://" not in target:
                    writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                    await writer.drain()
                    return
                scheme, _, rest = target.partition("://")
                authority, _, path = rest.partition("/")
                host, _, port_s = authority.rpartition(":")
                if not host:
                    host, port = authority, 80 if scheme == "http" else 443
                else:
                    port = int(port_s)
                request_line = f"{method} /{path} {version}\r\n".encode("latin-1")

            up_reader, up_writer = await self._connect_upstream(host, port)

            if method.upper() == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                up_writer.write(request_line)
                for h in headers:
                    # Proxy-Connection chỉ có nghĩa giữa Chrome và relay.
                    if not h.lower().startswith(b"proxy-connection"):
                        up_writer.write(h)
                up_writer.write(b"\r\n")
                await up_writer.drain()

            await asyncio.gather(
                _pipe(reader, up_writer, self.stats, "up_bytes"),
                _pipe(up_reader, writer, self.stats, "down_bytes"),
            )
        except Exception as e:
            self.stats["failures"] += 1
            logger.debug("[%s] %s", self.name, e)
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            for w in (up_writer, writer):
                try:
                    if w:
                        w.close()
                except Exception:
                    pass


def _mask(proxy_str: str) -> str:
    """Che mật khẩu trước khi ghi log. Log proxy hay bị dán vào issue."""
    if "@" not in proxy_str:
        return proxy_str
    scheme, _, rest = proxy_str.partition("://")
    creds, _, hostport = rest.rpartition("@")
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{hostport}"


# ── quản lý nhiều relay + lịch xoay ─────────────────────────────────────────
class RelayManager:
    """Giữ relay theo tên hồ sơ và xoay upstream theo lịch."""

    def __init__(self):
        self._relays: Dict[str, ProxyRelay] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    async def acquire(self, profile: str, kho: Optional[str],
                      rotate_minutes: int = 0,
                      initial: Optional[str] = None) -> Optional[str]:
        """Dựng (hoặc dùng lại) relay cho hồ sơ, trả về URL cục bộ cho Chrome.

        rotate_minutes = 0 nghĩa là không xoay: relay vẫn có ích vì nó là thứ
        duy nhất cho phép SOCKS5 có mật khẩu chạy được."""
        from . import proxy_pool as pool
        upstream = initial or pool.pick(kho)
        if not upstream:
            return None

        relay = self._relays.get(profile)
        if relay is None:
            relay = ProxyRelay(profile, upstream)
            await relay.start()
            self._relays[profile] = relay
        else:
            relay.set_upstream(upstream)

        self._cancel_rotation(profile)
        if rotate_minutes and rotate_minutes > 0:
            self._tasks[profile] = asyncio.create_task(
                self._rotate_loop(profile, kho, rotate_minutes))
        return relay.local_url()

    async def _rotate_loop(self, profile: str, kho: Optional[str], minutes: int):
        from . import proxy_pool as pool
        try:
            while True:
                await asyncio.sleep(minutes * 60)
                relay = self._relays.get(profile)
                if relay is None:
                    return
                nxt = pool.next_after(kho, relay.upstream)
                if not nxt:
                    logger.warning("[%s] Kho rỗng — giữ nguyên upstream", profile)
                    continue
                relay.set_upstream(nxt)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[%s] Vòng xoay proxy dừng: %s", profile, e)

    def _cancel_rotation(self, profile: str):
        task = self._tasks.pop(profile, None)
        if task and not task.done():
            task.cancel()

    async def release(self, profile: str):
        self._cancel_rotation(profile)
        relay = self._relays.pop(profile, None)
        if relay:
            await relay.stop()

    def status(self) -> Dict:
        return {name: {"port": r.port, "upstream": _mask(r.upstream or ""),
                       "rotating": name in self._tasks and not self._tasks[name].done(),
                       **r.stats}
                for name, r in self._relays.items()}


manager = RelayManager()
