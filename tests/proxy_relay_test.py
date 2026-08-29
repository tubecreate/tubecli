"""Relay proxy phải thật sự chuyển được gói tin, và xoay được upstream giữa chừng.

Chạy:  python tests/proxy_relay_test.py      (mã thoát 0 = đạt)

Vì sao tệp này tồn tại. Đo trên 14 hồ sơ có proxy ở máy phát triển: chỉ 2 chạy
được. 11 cái là SOCKS5 kèm đăng nhập — Chromium không biết đăng nhập SOCKS5 và
Playwright chặn thẳng, nên chúng mở trình duyệt xong mọi trang đều chết. Relay
là đường duy nhất đi qua (routes.proxy_blocker đã kết luận đúng như vậy), và
"đường duy nhất" thì phải được chứng minh chứ không phải được tin.

Bài kiểm không giả lập relay. Nó dựng:

  * một máy chủ gốc thật, trả về tên của chính nó;
  * HAI máy chủ SOCKS5 thật, mỗi cái đòi đúng tài khoản của nó và gắn nhãn
    lưu lượng đi qua — nhãn đó là cách duy nhất để biết gói tin ĐÃ đi qua
    upstream nào, thay vì tin vào biến trong bộ nhớ;

rồi cho một client HTTP nói chuyện với relay y như Chrome: CONNECT cho https,
dạng tuyệt đối cho http trần.
"""
import asyncio
import struct
import sys
from pathlib import Path

# Console Windows mặc định là cp1252 và không in nổi tiếng Việt: nếu không đặt
# dòng này, tệp chạy tốt khi ĐẠT nhưng SẬP đúng lúc in câu báo hỏng — nghĩa là
# người gặp lỗi thật không bao giờ đọc được lỗi đó.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.browser.proxy_relay import ProxyRelay, RelayManager, _mask  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


# ── máy chủ gốc ─────────────────────────────────────────────────────────────
async def start_origin(body: str):
    async def handle(reader, writer):
        try:
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            payload = body.encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: "
                         + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n"
                         + payload)
            await writer.drain()
        finally:
            writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


# ── máy chủ SOCKS5 thật, có đăng nhập ───────────────────────────────────────
async def start_socks5(user: str, password: str, tag: str, log: list):
    """Một SOCKS5 tối giản nhưng ĐÚNG giao thức: chào hỏi, đăng nhập, CONNECT.

    `tag` được ghi vào `log` mỗi lần có kết nối đi qua, nên bài kiểm biết chính
    xác gói tin đi lối nào — điều mà đọc biến upstream trong bộ nhớ không chứng
    minh được."""
    async def handle(reader, writer):
        up_writer = None
        try:
            ver, n = await reader.readexactly(2)
            methods = await reader.readexactly(n)
            if ver != 5:
                return
            need_auth = bool(user)
            if need_auth and 0x02 not in methods:
                writer.write(b"\x05\xff"); await writer.drain(); return
            writer.write(b"\x05" + (b"\x02" if need_auth else b"\x00"))
            await writer.drain()

            if need_auth:
                v = (await reader.readexactly(1))[0]
                ulen = (await reader.readexactly(1))[0]
                u = (await reader.readexactly(ulen)).decode()
                plen = (await reader.readexactly(1))[0]
                p = (await reader.readexactly(plen)).decode()
                ok = (v == 1 and u == user and p == password)
                writer.write(b"\x01" + (b"\x00" if ok else b"\x01"))
                await writer.drain()
                if not ok:
                    log.append(f"{tag}:bad-auth")
                    return

            head = await reader.readexactly(4)
            atyp = head[3]
            if atyp == 0x01:
                host = ".".join(str(b) for b in await reader.readexactly(4))
            elif atyp == 0x03:
                ln = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(ln)).decode()
            else:
                await reader.readexactly(16)
                host = "::1"
            port = struct.unpack("!H", await reader.readexactly(2))[0]

            up_reader, up_writer = await asyncio.open_connection(host, port)
            writer.write(b"\x05\x00\x00\x01" + bytes(4) + struct.pack("!H", 0))
            await writer.drain()
            log.append(f"{tag}:{host}:{port}")

            async def pipe(r, w):
                try:
                    while True:
                        chunk = await r.read(65536)
                        if not chunk:
                            break
                        w.write(chunk)
                        await w.drain()
                except Exception:
                    pass
                finally:
                    try:
                        w.close()
                    except Exception:
                        pass

            await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
        except Exception:
            pass
        finally:
            for w in (up_writer, writer):
                try:
                    if w:
                        w.close()
                except Exception:
                    pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


# ── client nói chuyện với relay đúng như Chrome ──────────────────────────────
async def through_relay_absolute(relay_port: int, origin_port: int) -> str:
    """http trần: Chrome gửi `GET http://host:port/ HTTP/1.1` tới proxy."""
    r, w = await asyncio.open_connection("127.0.0.1", relay_port)
    try:
        w.write(f"GET http://127.0.0.1:{origin_port}/ HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{origin_port}\r\nConnection: close\r\n\r\n".encode())
        await w.drain()
        data = await asyncio.wait_for(r.read(-1), 10)
        return data.decode("latin-1", "replace")
    finally:
        w.close()


async def through_relay_connect(relay_port: int, origin_port: int) -> str:
    """https: Chrome gửi CONNECT rồi nói thẳng với máy đích qua đường hầm."""
    r, w = await asyncio.open_connection("127.0.0.1", relay_port)
    try:
        w.write(f"CONNECT 127.0.0.1:{origin_port} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{origin_port}\r\n\r\n".encode())
        await w.drain()
        status = await asyncio.wait_for(r.readline(), 10)
        if b"200" not in status:
            return "CONNECT-FAILED " + status.decode("latin-1", "replace")
        while True:
            line = await asyncio.wait_for(r.readline(), 10)
            if line in (b"\r\n", b"\n", b""):
                break
        w.write(b"GET / HTTP/1.1\r\nHost: origin\r\nConnection: close\r\n\r\n")
        await w.drain()
        data = await asyncio.wait_for(r.read(-1), 10)
        return data.decode("latin-1", "replace")
    finally:
        w.close()


async def main():
    log = []
    origin, origin_port = await start_origin("XIN-CHAO-GOC")
    socks_a, port_a = await start_socks5("ua", "pa", "A", log)
    socks_b, port_b = await start_socks5("ub", "pb", "B", log)

    up_a = f"socks5://ua:pa@127.0.0.1:{port_a}"
    up_b = f"socks5://ub:pb@127.0.0.1:{port_b}"

    relay = ProxyRelay("test", up_a)
    port = await relay.start()
    check("relay chiếm được một cổng loopback", isinstance(port, int) and port > 0, port)
    check("URL đưa cho Chrome là loopback, không đăng nhập",
          relay.local_url() == f"http://127.0.0.1:{port}", relay.local_url())

    # 1. http trần, qua SOCKS5 CÓ MẬT KHẨU — đúng ca Chromium không làm được.
    body = await through_relay_absolute(port, origin_port)
    check("dạng tuyệt đối đi tới máy chủ gốc", "XIN-CHAO-GOC" in body, body[:120])
    check("và nó đi qua upstream A", any(x.startswith("A:") for x in log), log)

    # 2. CONNECT (https)
    log.clear()
    body = await through_relay_connect(port, origin_port)
    check("CONNECT dựng được đường hầm", "XIN-CHAO-GOC" in body, body[:120])
    check("đường hầm cũng đi qua upstream A", any(x.startswith("A:") for x in log), log)

    # 3. Xoay upstream: kết nối MỚI phải sang B.
    log.clear()
    ok = relay.set_upstream(up_b)
    check("đổi upstream được chấp nhận", ok)
    body = await through_relay_absolute(port, origin_port)
    check("sau khi xoay, gói tin vẫn tới đích", "XIN-CHAO-GOC" in body, body[:120])
    check("và bây giờ đi qua upstream B, không phải A",
          any(x.startswith("B:") for x in log) and not any(x.startswith("A:") for x in log), log)
    check("số lần xoay được đếm", relay.stats["rotations"] >= 2, relay.stats)

    # 4. Sai mật khẩu phải HỎNG, không được âm thầm đi thẳng — đây là ca tệ nhất:
    #    người dùng tưởng có proxy trong khi IP thật đang lộ.
    log.clear()
    relay.set_upstream(f"socks5://ua:SAI@127.0.0.1:{port_a}")
    body = await through_relay_absolute(port, origin_port)
    check("sai mật khẩu thì trả 502, KHÔNG đi thẳng ra ngoài",
          "502" in body and "XIN-CHAO-GOC" not in body, body[:120])
    check("máy chủ SOCKS5 ghi nhận là hỏng đăng nhập",
          any(x == "A:bad-auth" for x in log), log)

    # 5. Không nhận chuỗi upstream vô nghĩa.
    check("chuỗi upstream hỏng bị từ chối", relay.set_upstream("không-phải-proxy") is False)
    check("upstream cũ được giữ nguyên khi từ chối",
          relay.upstream is not None and "127.0.0.1" in relay.upstream, relay.upstream)

    # 6. Log không được để lộ mật khẩu.
    check("mật khẩu bị che trong log", _mask(up_a) == f"socks5://ua:***@127.0.0.1:{port_a}", _mask(up_a))
    check("lịch sử xoay cũng che mật khẩu",
          all("pa" not in h["upstream"] and "pb" not in h["upstream"] for h in relay.history),
          relay.history)

    await relay.stop()

    # 7. RelayManager: một relay cho mỗi hồ sơ, dọn sạch khi thả.
    mgr = RelayManager()
    url = await mgr.acquire("ho-so-1", kho=None, rotate_minutes=0, initial=up_a)
    check("manager dựng relay và trả URL cục bộ", url and url.startswith("http://127.0.0.1:"), url)
    again = await mgr.acquire("ho-so-1", kho=None, rotate_minutes=0, initial=up_b)
    check("gọi lại cùng hồ sơ thì DÙNG LẠI cổng cũ, không mở cổng thứ hai",
          again == url, (url, again))
    st = mgr.status()
    check("trạng thái báo đúng upstream đang dùng", "ub" in st["ho-so-1"]["upstream"], st)
    check("trạng thái không lộ mật khẩu", "pb" not in st["ho-so-1"]["upstream"], st)
    await mgr.release("ho-so-1")
    check("thả xong thì không còn relay nào", mgr.status() == {}, mgr.status())

    # 8. Vòng xoay theo lịch chạy thật (rút ngắn còn vài giây bằng cách chỉnh
    #    trực tiếp vòng lặp — lịch 30 phút không kiểm được trong một bài test).
    from tubecli.extensions.browser import proxy_pool as pool
    real_next = pool.next_after
    pool.next_after = lambda kho, cur: up_b if (cur or "").find(f":{port_a}") > 0 else up_a
    try:
        mgr2 = RelayManager()
        await mgr2.acquire("ho-so-2", kho=None, rotate_minutes=0, initial=up_a)
        relay2 = mgr2._relays["ho-so-2"]
        task = asyncio.create_task(mgr2._rotate_loop("ho-so-2", None, 0.02))  # 1.2 giây
        await asyncio.sleep(1.6)
        task.cancel()
        check("vòng xoay theo lịch có đổi upstream", relay2.upstream == up_b, relay2.upstream)
        await mgr2.release("ho-so-2")
    finally:
        pool.next_after = real_next

    for s in (origin, socks_a, socks_b):
        s.close()

    print()
    for f in failures:
        print("  FAIL", f)
    print(f"{checks - len(failures)}/{checks} PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    print("=" * 70)
    print("PROXY RELAY")
    print("=" * 70)
    sys.exit(asyncio.run(main()))
