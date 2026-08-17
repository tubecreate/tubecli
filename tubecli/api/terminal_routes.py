"""Web terminal — shell SSH của server ngay trong trình duyệt.

Một pty bash chạy dưới user của service TubeCLI, nối với trình duyệt qua WebSocket
(xterm.js). Dùng cho Flow Builder của cloud: khung Terminal nhúng iframe /terminal.

Bảo mật: đây là shell tuỳ ý = toàn quyền như user chạy service. Người dùng vốn đã
có SSH vào máy này, nên terminal không mở thêm quyền — nhưng WS PHẢI qua auth
(reject_unless_allowed đọc cookie tubecli_session, giống browser preview), còn
trang /terminal đi qua HTTP gate như mọi trang khác. Chỉ Linux/macOS (pty).
"""
from __future__ import annotations
import asyncio
import json
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

router = APIRouter()

_TERMINAL_HTML = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Terminal</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css">
<style>
  html,body{margin:0;height:100%;background:#0b0b0e;overflow:hidden}
  #term{position:absolute;inset:0;padding:8px}
  #bar{position:absolute;top:0;left:0;right:0;height:0}
  .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
       color:#a1a1aa;font:13px ui-monospace,monospace;flex-direction:column;gap:8px}
</style></head>
<body>
<div id="term"></div>
<div class="msg" id="msg">Đang kết nối terminal…</div>
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
<script>
(function(){
  var msg = document.getElementById('msg');
  if (!window.Terminal) { msg.textContent = 'Không tải được xterm (cần internet trên máy).'; return; }
  var term = new Terminal({
    cursorBlink: true, fontSize: 13, fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
    theme: { background: '#0b0b0e', foreground: '#e4e4e7', cursor: '#a78bfa',
             selectionBackground: 'rgba(124,58,237,0.35)' }
  });
  var fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById('term'));
  fit.fit();

  var proto = location.protocol === 'https:' ? 'wss' : 'ws';
  var ws = new WebSocket(proto + '://' + location.host + '/api/v1/terminal/ws');
  ws.binaryType = 'arraybuffer';

  function sendResize() {
    if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  }
  ws.onopen = function(){ msg.style.display = 'none'; term.focus(); sendResize(); };
  ws.onmessage = function(e){
    if (typeof e.data === 'string') term.write(e.data);
    else term.write(new Uint8Array(e.data));
  };
  ws.onclose = function(e){
    term.write('\\r\\n\\x1b[31m[phiên đã đóng' + (e.reason ? ': ' + e.reason : '') + ']\\x1b[0m\\r\\n');
    msg.style.display = 'flex'; msg.textContent = 'Phiên terminal đã đóng. Tải lại khung để mở lại.';
  };
  ws.onerror = function(){ msg.style.display = 'flex'; msg.textContent = 'Lỗi kết nối terminal.'; };

  term.onData(function(d){ if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'input', data: d })); });
  var rt; window.addEventListener('resize', function(){ clearTimeout(rt); rt = setTimeout(function(){ fit.fit(); sendResize(); }, 80); });
})();
</script>
</body></html>"""


@router.get("/terminal", response_class=HTMLResponse)
async def terminal_page():
    """Trang terminal (xterm.js). Auth qua HTTP gate như mọi trang dashboard."""
    return HTMLResponse(_TERMINAL_HTML)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


@router.websocket("/api/v1/terminal/ws")
async def terminal_ws(websocket: WebSocket):
    """pty bash ↔ WebSocket. Auth trước khi accept (bỏ qua HTTP middleware)."""
    from tubecli.core.ws_auth import reject_unless_allowed
    if not await reject_unless_allowed(websocket):
        return

    # pty chỉ có trên Unix — Windows không hỗ trợ, báo rõ thay vì 500 khó hiểu
    try:
        import pty
    except ImportError:
        await websocket.accept()
        await websocket.send_text("Terminal chỉ hỗ trợ trên server Linux/macOS.\r\n")
        await websocket.close()
        return

    await websocket.accept()

    shell = os.environ.get("SHELL") or "/bin/bash"
    if not os.path.exists(shell):
        shell = "/bin/sh"
    home = os.path.expanduser("~")

    pid, master_fd = pty.fork()
    if pid == 0:  # tiến trình con → thành shell
        try:
            if os.path.isdir(home):
                os.chdir(home)
            env = dict(os.environ)
            env["TERM"] = "xterm-256color"
            os.execvpe(shell, [shell, "-i"], env)
        except Exception:
            os._exit(1)

    loop = asyncio.get_event_loop()
    os.set_blocking(master_fd, False)
    closed = asyncio.Event()

    def _on_readable():
        try:
            data = os.read(master_fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            loop.call_soon_threadsafe(closed.set)
            return
        if not data:
            loop.call_soon_threadsafe(closed.set)
            return
        asyncio.ensure_future(_safe_send(data))

    async def _safe_send(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            closed.set()

    try:
        loop.add_reader(master_fd, _on_readable)
    except Exception:
        # Một số event loop (Windows Proactor) không add_reader được — đã chặn ở trên
        closed.set()

    async def _pump_input():
        try:
            while not closed.is_set():
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = msg.get("type")
                if t == "input":
                    os.write(master_fd, msg.get("data", "").encode("utf-8", "replace"))
                elif t == "resize":
                    _set_winsize(master_fd, int(msg.get("rows", 24)), int(msg.get("cols", 80)))
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            closed.set()

    input_task = asyncio.ensure_future(_pump_input())
    try:
        await closed.wait()
    finally:
        try: loop.remove_reader(master_fd)
        except Exception: pass
        input_task.cancel()
        try: os.close(master_fd)
        except Exception: pass
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except Exception: pass
        try: await websocket.close()
        except Exception: pass
