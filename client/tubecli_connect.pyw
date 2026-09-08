"""TubeCLI Connect — cầu nối giữa MÁY CỦA BẠN và cloud.tubecreate.com.

Một tiến trình nhỏ chạy nền, làm đúng ba việc:
  1. Có TubeCLI chưa? Chưa thì cài (chạy install.ps1 chính thức).
  2. Bật TubeCLI ở cổng 5295 và giữ nó sống.
  3. Dựng tunnel Cloudflare bằng token cloud cấp, để canvas trên cloud nhìn thấy máy.

VÌ SAO PHẢI CÓ TUNNEL, KHÔNG NỐI THẲNG localhost:5295 ĐƯỢC:
  * lệnh điều khiển của canvas đi qua Worker của cloud (chạy trên edge Cloudflare) —
    từ đó "localhost" là localhost của edge, không phải máy bạn;
  * cookie phiên của TubeCLI là SameSite=Lax, nên chỉ đi được khi tên miền CÙNG SITE
    với cloud — đó là lý do tunnel phải là <tên>.tubecreate.com chứ không phải một
    domain trycloudflare ngẫu nhiên;
  * trang https không gọi được http://localhost kèm cookie: node trả
    Access-Control-Allow-Origin: * và trình duyệt chặn đúng tổ hợp ấy.

Chạy:  pythonw client/tubecli_connect.pyw          (lần đầu sẽ hỏi mã ghép nối)
       python  client/tubecli_connect.pyw --status  (in trạng thái rồi thoát)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

APP = "TubeCLI Connect"
# Cloudflare chặn thẳng User-Agent mặc định của urllib ("Python-urllib/3.12") bằng
# lỗi 1010 — request chết ở edge, không tới Worker, nên mã đúng hay sai cũng ra 403.
# Đo trên máy người dùng 8/9/26: urllib → 403 "error code: 1010", cùng URL với UA
# thường → 410 (câu trả lời thật). Mọi cuộc gọi ra ngoài phải tự xưng tên.
UA = f"TubeCLI-Connect/1.0 (Windows; Python {sys.version_info.major}.{sys.version_info.minor})"
CLOUD = os.environ.get("TUBECLI_CLOUD", "https://cloud.tubecreate.com")
PORT = int(os.environ.get("TUBECLI_PORT", "5295"))
HOME = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TubeCLI")
CONF = os.path.join(HOME, "connect.json")
LOG = os.path.join(HOME, "connect.log")
CLOUDFLARED = os.path.join(HOME, "cloudflared.exe")
CF_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
INSTALL_PS1 = "https://raw.githubusercontent.com/tubecreate/tubecli/main/install.ps1"
HEALTH = f"http://127.0.0.1:{PORT}/api/v1/health"
DASH = f"http://127.0.0.1:{PORT}/dashboard"

def _install_ua_opener() -> None:
    """Gắn UA cho cả những chỗ gọi urlopen(chuỗi) — như lúc tải cloudflared."""
    op = urllib.request.build_opener()
    op.addheaders = [("User-Agent", UA)]
    urllib.request.install_opener(op)


_install_ua_opener()

# Nơi install.ps1 đặt TubeCLI. Người dùng có thể đổi, nên còn dò thêm ở dưới.
DEFAULT_DIRS = [
    os.path.join(os.path.expanduser("~"), "TubeCLI"),
    r"C:\TubeCLI",
]


def log(msg: str) -> None:
    """Ghi một dòng vào log, và KHÔNG BAO GIỜ được ném ra ngoài.

    print() dưới pythonw là một quả mìn: không có console thì sys.stdout là None và
    print ném AttributeError — giết cả tiến trình ở đúng chỗ ta chỉ định ghi một dòng
    nhật ký. Client này chạy bằng pythonw là chính, nên đây là đường chết thật, không
    phải phòng xa.
    """
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # KHÔNG bắt hẹp: đường dẫn hỏng ném ValueError chứ không phải OSError, và một
        # hàm ghi nhật ký mà giết được tiến trình thì tệ hơn hẳn việc không có nhật ký.
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def conf_read() -> dict:
    try:
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def conf_write(data: dict) -> None:
    os.makedirs(HOME, exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONF)
    # Token tunnel nằm trong file này: mở đúng cho chủ máy, không cho người khác.
    try:
        subprocess.run(["icacls", CONF, "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME')}:F"],
                       capture_output=True, timeout=10)
    except Exception as e:
        log(f"không siết được quyền {CONF}: {e}")


# ── Máy chủ TubeCLI ─────────────────────────────────────────────────────────

def tubecli_up(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def is_tubecli_dir(d: str) -> bool:
    """Thư mục này có phải một bản TubeCLI dùng được không.

    Hai bố cục đều tính: bản cài bằng install.ps1 (có TubeCLI.bat) và bản lấy thẳng
    từ git (có tubecli/main.py) — máy của người phát triển là bản thứ hai, và client
    này nằm ngay trong đó.
    """
    return bool(d) and (os.path.isfile(os.path.join(d, "TubeCLI.bat"))
                        or os.path.isfile(os.path.join(d, "tubecli", "main.py")))


def find_install() -> str:
    """Thư mục TubeCLI đã cài, hay "". Dò lối tắt trước — đó là nơi install.ps1
    ghi lại lựa chọn thật của người dùng, kể cả khi họ đổi ổ đĩa."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if is_tubecli_dir(here):          # client nằm trong chính bản TubeCLI
        return here
    for d in DEFAULT_DIRS:
        if is_tubecli_dir(d):
            return d
    lnk = os.path.join(os.path.expanduser("~"), "Desktop", "TubeCLI.lnk")
    if os.path.isfile(lnk):
        try:
            raw = open(lnk, "rb").read().decode("latin-1")
            for part in raw.split("\x00"):
                if part.lower().endswith("tubecli.bat") and os.path.isfile(part):
                    return os.path.dirname(part)
        except OSError:
            pass
    return ""


def server_cmd() -> tuple:
    """(lệnh bật máy chủ, thư mục chạy) — hay ([], "") nếu máy chưa có TubeCLI.

    Hai kiểu cài đều nhận: một thư mục (install.ps1 hoặc bản git) và lệnh `tubecli`
    trên PATH (cài bằng pip). Thiếu nhánh PATH thì máy cài bằng pip bị coi là chưa
    cài, và client sẽ cài chồng lên.
    """
    d = find_install()
    if d:
        py = os.path.join(d, "venv", "Scripts", "pythonw.exe")
        exe = py if os.path.isfile(py) else "pythonw"
        return [exe, "-m", "tubecli.main", "serve", "--port", str(PORT)], d
    exe = shutil.which("tubecli")
    if exe:
        return [exe, "serve", "--port", str(PORT)], os.path.dirname(exe)
    return [], ""


def have_tubecli() -> bool:
    """Máy này đã có TubeCLI chưa. ĐANG CHẠY là câu trả lời mạnh nhất và phải hỏi
    TRƯỚC: máy người dùng có thể cài ở một thư mục lạ, nhưng cổng 5295 đang trả lời
    thì chuyện "chưa cài" là sai, và cài chồng lên chỉ tổ mở ra một trình hướng dẫn
    đứng đợi người gõ."""
    return tubecli_up() or bool(server_cmd()[0])


def install_tubecli(lang: str = "vi") -> bool:
    """Chạy đúng trình cài chính thức (install.ps1). Không tự dựng bản cài riêng:
    một bản thứ hai là một bộ bug thứ hai."""
    log("Chưa có TubeCLI — bắt đầu cài (cửa sổ PowerShell sẽ hiện ra)…")
    cmd = ("$ErrorActionPreference='Stop'; "
           f"$s = irm {INSTALL_PS1}; "
           f"& ([scriptblock]::Create($s)) -Lang {lang}")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                           creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        ok = p.returncode == 0
    except Exception as e:
        log(f"cài thất bại: {e}")
        return False
    log("cài xong" if ok else f"trình cài trả mã {p.returncode}")
    return ok


def start_tubecli() -> bool:
    """Bật máy chủ TubeCLI, không kèm cửa sổ đen. Trả True khi /health trả lời."""
    if tubecli_up():
        return True
    cmd, d = server_cmd()
    if not cmd:
        return False
    log(f"bật TubeCLI từ {d}")
    try:
        subprocess.Popen(cmd, cwd=d or None,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"không bật được TubeCLI: {e}")
        return False
    for _ in range(60):
        if tubecli_up():
            log("TubeCLI đã sẵn sàng")
            return True
        time.sleep(1)
    log("TubeCLI không trả lời sau 60 giây")
    return False


def node_login(password: str) -> bool:
    """Mật khẩu này có mở được dashboard không — hỏi thẳng node, đừng đoán."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/v1/auth/login", method="POST",
            data=json.dumps({"password": password}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


# ── Tunnel ──────────────────────────────────────────────────────────────────

def ensure_cloudflared() -> bool:
    if os.path.isfile(CLOUDFLARED):
        return True
    log("tải cloudflared…")
    os.makedirs(HOME, exist_ok=True)
    try:
        cf_req = urllib.request.Request(CF_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(cf_req, timeout=180) as r, open(CLOUDFLARED + ".part", "wb") as f:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(CLOUDFLARED + ".part", CLOUDFLARED)
        log("đã tải cloudflared")
        return True
    except Exception as e:
        log(f"không tải được cloudflared: {e}")
        return False


def start_tunnel(token: str):
    """cloudflared chạy nền với token của cloud. Trả tiến trình, hay None."""
    if not ensure_cloudflared():
        return None
    try:
        return subprocess.Popen(
            [CLOUDFLARED, "tunnel", "--no-autoupdate", "run", "--token", token],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"không chạy được cloudflared: {e}")
        return None


# ── Ghép nối với cloud ──────────────────────────────────────────────────────

def claim(code: str, password: str) -> dict:
    """Đổi mã ghép nối lấy token tunnel. Ném RuntimeError với câu người đọc được."""
    req = urllib.request.Request(
        f"{CLOUD}/api/servers/pair/claim", method="POST",
        data=json.dumps({"code": code, "tubecli_password": password}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            detail = json.loads(raw).get("error") or ""
        except Exception:
            detail = ""
        if not detail:
            # Cloudflare chặn ở edge thì thân trả về là text/HTML, không phải JSON —
            # nuốt nó đi là bỏ mất manh mối duy nhất ("error code: 1010").
            detail = f"HTTP {e.code}"
            snippet = " ".join(raw.split())[:120]
            if snippet:
                detail += f" — {snippet}"
        raise RuntimeError(detail) from e
    except Exception as e:
        raise RuntimeError(f"Không gọi được cloud: {e}") from e


# ── Khởi động cùng Windows ──────────────────────────────────────────────────

def startup_path() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup", "TubeCLI Connect.cmd")


def autostart_on() -> bool:
    return os.path.isfile(startup_path())


def set_autostart(on: bool) -> None:
    p = startup_path()
    if not on:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = exe if os.path.isfile(exe) else sys.executable
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'@echo off\r\nstart "" "{exe}" "{os.path.abspath(__file__)}"\r\n')
    except OSError as e:
        log(f"không đặt được khởi động cùng Windows: {e}")


def prepare_node(say, lang: str = "vi") -> tuple:
    """Đưa máy về trạng thái CHẠY ĐƯỢC, kể lại từng bước qua say(). Trả (ok, mật khẩu
    gợi ý). Ba ngả, theo đúng thứ tự người dùng mong đợi:
        * cổng 5295 đang trả lời → xong, không đụng gì;
        * đã cài mà chưa chạy   → tự bật;
        * chưa cài              → chạy trình cài rồi bật (mật khẩu khi ấy là mặc định).
    """
    if tubecli_up():
        say("TubeCLI đang chạy ✓")
        return True, ""
    cmd, d = server_cmd()
    if cmd:
        say(f"Đã cài sẵn — đang bật TubeCLI… ({d})")
        if start_tubecli():
            say("TubeCLI đang chạy ✓")
            return True, ""
        say("Không bật được TubeCLI — xem log.")
        return False, ""
    say("Máy chưa có TubeCLI — đang cài. Cửa sổ cài đặt sẽ HỎI vài câu.")
    if not install_tubecli(lang=lang):
        say("Trình cài không hoàn tất — xem log.")
        return False, ""
    say("Cài xong — đang bật TubeCLI…")
    if not start_tubecli():
        say("Cài xong nhưng chưa bật được — mở TubeCLI rồi chạy lại client.")
        return False, ""
    say("TubeCLI đang chạy ✓")
    # Bản vừa cài dùng mật khẩu mặc định; điền sẵn để người dùng khỏi đoán.
    return True, "123456"


# ── Hỏi mã ghép nối (tkinter — có sẵn trong Python, không cài thêm) ─────────

def ask_pairing(default_code: str = "", lang: str = "vi") -> tuple:
    import tkinter as tk
    from tkinter import ttk

    out = {"code": "", "password": "", "info": None}
    root = tk.Tk()
    root.title(APP)
    root.resizable(False, False)
    # Cửa sổ mở sau lưng trình duyệt thì cũng như không mở — người dùng đang nhìn
    # trang cloud, không ai đi lục thanh tác vụ.
    root.attributes("-topmost", True)
    root.after(1200, lambda: root.attributes("-topmost", False))
    root.lift()
    try:
        root.focus_force()
    except Exception:
        pass
    frm = ttk.Frame(root, padding=16)
    frm.grid()
    ttk.Label(frm, text="Mã ghép nối (lấy trên cloud → Kết nối máy của tôi)").grid(column=0, row=0, sticky="w")
    e_code = ttk.Entry(frm, width=24, font=("Consolas", 14))
    e_code.grid(column=0, row=1, sticky="we", pady=(2, 10))
    e_code.insert(0, default_code)
    ttk.Label(frm, text="Mật khẩu dashboard TubeCLI").grid(column=0, row=2, sticky="w")
    e_pw = ttk.Entry(frm, width=24, show="•")
    e_pw.grid(column=0, row=3, sticky="we", pady=(2, 4))
    ttk.Label(frm, text="Máy chưa cài TubeCLI thì để 123456 — cài xong dùng mật khẩu đó.",
              foreground="#888").grid(column=0, row=4, sticky="w", pady=(0, 10))
    msg = ttk.Label(frm, text="", foreground="#c33")
    msg.grid(column=0, row=6, sticky="w", pady=(8, 0))
    state = ttk.Label(frm, text="Đang kiểm tra máy…", foreground="#888")
    state.grid(column=0, row=7, sticky="w", pady=(6, 0))

    btn = ttk.Button(frm, text="Kết nối")
    btn.grid(column=0, row=5, sticky="e")
    btn.state(["disabled"])                 # chỉ mở khi máy chủ đã trả lời

    def fail(text: str):
        """Hỏng thì Ở LẠI cửa sổ. Mã sống 15 phút; bắt tải lại client rồi gõ lại từ
        đầu là ép người dùng chạy đua với đồng hồ vì một lỗi đánh máy."""
        log(f"ghép nối hỏng: {text}")

        def show():
            msg.config(text=text)
            state.config(text="Sửa rồi bấm Kết nối lại.", foreground="#c33")
            btn.state(["!disabled"])
            e_code.focus()
        root.after(0, show)

    def connect(code: str, pw: str):
        """Đăng nhập node rồi đổi mã — chạy ở luồng nền để cửa sổ không đơ."""
        if not tubecli_up():
            fail("TubeCLI không còn trả lời ở cổng 5295. Mở TubeCLI rồi thử lại.")
            return
        if not node_login(pw):
            fail("Mật khẩu dashboard TubeCLI không đúng — cloud sẽ không mở được máy này.")
            return
        try:
            info = claim(code, pw)
        except RuntimeError as e:
            fail(f"Cloud không nhận mã: {e}")
            return
        out["code"], out["password"], out["info"] = code, pw, info
        log(f"ghép nối xong: {info.get('url')}")
        root.after(0, root.destroy)

    def ok():
        code = e_code.get().strip().upper()
        pw = e_pw.get()
        if len(code) < 4 or not pw:
            msg.config(text="Nhập đủ mã và mật khẩu.")
            return
        msg.config(text="")
        btn.state(["disabled"])
        state.config(text="Đang ghép nối với cloud…", foreground="#888")
        threading.Thread(target=connect, args=(code, pw), daemon=True).start()

    btn.config(command=ok)
    root.bind("<Return>", lambda _e: ok() if "disabled" not in btn.state() else None)

    # Dò / bật / cài chạy ở LUỒNG NỀN: trình cài có thể mất vài phút, mà cửa sổ đứng
    # đơ mấy phút thì Windows dán nhãn "Not responding" và người dùng tắt nó đi.
    def prepare():
        ok_node, suggest = prepare_node(lambda m: root.after(0, lambda: state.config(text=m)), lang)

        def done():
            if ok_node:
                state.config(text=state.cget("text"), foreground="#2a7")
                btn.state(["!disabled"])
                if suggest and not e_pw.get():
                    e_pw.insert(0, suggest)
                (e_code if not e_code.get() else e_pw).focus()
            else:
                state.config(foreground="#c33")
        root.after(0, done)

    threading.Thread(target=prepare, daemon=True).start()
    e_code.focus()
    root.mainloop()
    return out["code"], out["password"], out["info"]


def notify(title: str, body: str, wait: bool = False) -> None:
    """Báo một câu cho người dùng.

    LUÔN ghi log trước khi vẽ: hộp thoại có thể không hiện được (thiếu màn hình,
    tkinter hỏng), còn log thì đọc lại được lúc đi tìm nguyên nhân.

    wait=True khi đây là lời cuối trước lúc thoát. Thread daemon + sys.exit ngay
    sau đó = hộp thoại không bao giờ kịp vẽ, và người dùng chỉ thấy client bốc hơi.
    """
    log(f"{title}: {body}")

    def run():
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            messagebox.showinfo(title, body, parent=r)
            r.destroy()
        except Exception as e:
            log(f"không vẽ được hộp thoại: {e}")
    if wait:
        run()
        return
    threading.Thread(target=run, daemon=True).start()


# ── Vòng đời ────────────────────────────────────────────────────────────────

class Bridge:
    """Giữ TubeCLI và cloudflared cùng sống. Cả hai đều có thể chết bất cứ lúc nào
    (Windows update, người dùng tắt nhầm) — vòng canh dựng lại, vì máy để ở nhà thì
    không ai ngồi đó mà bật lại."""

    def __init__(self, conf: dict):
        self.conf = conf
        self.tunnel = None
        self.stop = threading.Event()

    def status(self) -> str:
        node = "đang chạy" if tubecli_up() else "TẮT"
        tun = "đang chạy" if (self.tunnel and self.tunnel.poll() is None) else "TẮT"
        return f"TubeCLI: {node} · Tunnel: {tun} · {self.conf.get('url', '')}"

    def watch(self) -> None:
        while not self.stop.is_set():
            try:
                if not tubecli_up():
                    start_tubecli()
                if self.conf.get("tunnel_token") and (self.tunnel is None or self.tunnel.poll() is not None):
                    if self.tunnel is not None:
                        log("cloudflared đã dừng — chạy lại")
                    self.tunnel = start_tunnel(self.conf["tunnel_token"])
            except Exception as e:
                log(f"vòng canh: {e}")
            self.stop.wait(20)

    def shutdown(self) -> None:
        self.stop.set()
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()


def tray(bridge: Bridge) -> None:
    """Icon khay hệ thống. Không có pystray thì vẫn chạy nền, chỉ là không có icon —
    cầu nối mới là việc chính, cái icon chỉ để bấm."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        # KHÔNG được ngủ im trong nền: pythonw không có cửa sổ, không có icon thì
        # người dùng không có cách nào biết client còn sống hay đã chết.
        log("thiếu pystray/Pillow — mở cửa sổ trạng thái thay cho icon khay")
        status_window(bridge)
        return

    img = Image.new("RGB", (64, 64), "#111827")
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill="#5276EB")

    def toggle_autostart(icon, item):
        set_autostart(not autostart_on())

    menu = pystray.Menu(
        pystray.MenuItem(lambda _i: bridge.status(), None, enabled=False),
        pystray.MenuItem("Mở dashboard", lambda: os.startfile(DASH)),
        pystray.MenuItem("Mở cloud", lambda: os.startfile(CLOUD + "/dash")),
        pystray.MenuItem("Xem log", lambda: os.startfile(LOG) if os.path.isfile(LOG) else None),
        pystray.MenuItem("Khởi động cùng Windows", toggle_autostart,
                         checked=lambda _i: autostart_on()),
        pystray.MenuItem("Thoát", lambda icon: (bridge.shutdown(), icon.stop())),
    )
    pystray.Icon("tubecli", img, APP, menu).run()


def status_window(bridge: "Bridge") -> None:
    """Cửa sổ nhỏ luôn nhìn thấy: trạng thái + đúng những nút người ta cần.

    Đây là đường lui khi máy không có pystray, và nó phải TỰ ĐỦ: đóng cửa sổ là
    dừng hẳn cầu nối, để không có tiến trình mồ côi giữ cổng 5295 và tunnel.
    """
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.after(1500, lambda: root.attributes("-topmost", False))
    root.lift()
    frm = ttk.Frame(root, padding=14)
    frm.grid()

    conf = bridge.conf
    ttk.Label(frm, text=conf.get("name") or APP, font=("Segoe UI", 11, "bold")).grid(column=0, row=0, sticky="w")
    ttk.Label(frm, text=conf.get("url") or "", foreground="#5276EB").grid(column=0, row=1, sticky="w", pady=(0, 8))
    state = ttk.Label(frm, text="", font=("Consolas", 9))
    state.grid(column=0, row=2, sticky="w", pady=(0, 10))

    bar = ttk.Frame(frm)
    bar.grid(column=0, row=3, sticky="w")
    ttk.Button(bar, text="Mở dashboard", command=lambda: os.startfile(DASH)).grid(column=0, row=0, padx=(0, 6))
    ttk.Button(bar, text="Mở cloud", command=lambda: os.startfile(CLOUD + "/dash")).grid(column=1, row=0, padx=(0, 6))
    ttk.Button(bar, text="Xem log",
               command=lambda: os.startfile(LOG) if os.path.isfile(LOG) else None).grid(column=2, row=0, padx=(0, 6))

    auto = tk.BooleanVar(value=autostart_on())
    ttk.Checkbutton(frm, text="Khởi động cùng Windows", variable=auto,
                    command=lambda: set_autostart(auto.get())).grid(column=0, row=4, sticky="w", pady=(10, 0))

    def tick():
        state.config(text=bridge.status())
        root.after(2000, tick)

    def close():
        bridge.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    tick()
    root.mainloop()


def main() -> int:
    os.makedirs(HOME, exist_ok=True)
    conf = conf_read()
    # Dòng đầu tiên của mỗi lượt chạy: log rỗng thì không ai biết client đã khởi động
    # hay chết trước cả khi kịp mở cửa sổ.
    log(f"khởi động (pid {os.getpid()}, {os.path.basename(sys.executable)}), "
        f"đã ghép nối: {bool(conf.get('tunnel_token'))}")

    if "--status" in sys.argv:
        print(json.dumps({"tubecli": tubecli_up(), "conf": {k: v for k, v in conf.items()
                                                            if k != "tunnel_token"}}, ensure_ascii=False))
        return 0

    if not conf.get("tunnel_token"):
        code = ""
        for arg in sys.argv[1:]:
            if arg.startswith("--code="):
                code = arg.split("=", 1)[1].strip().upper()
        # Cửa sổ tự dò cổng 5295 → bật bản đã cài → cài mới nếu chưa có, rồi mới mở
        # nút Kết nối. Người dùng chỉ gõ mã khi máy đã sẵn sàng.
        # Đăng nhập + đổi mã diễn ra BÊN TRONG cửa sổ: sai mật khẩu hay mã hết hạn
        # thì báo tại chỗ và gõ lại, không thoát. Ra tới đây mà không có info nghĩa
        # là người dùng tự đóng cửa sổ.
        code, password, info = ask_pairing(code, lang=conf.get("lang", "vi"))
        if not info:
            log("người dùng đóng cửa sổ trước khi ghép nối xong")
            return 1
        conf = {**conf, **info, "password": password}
        conf_write(conf)
        set_autostart(True)
        notify(APP, f"Đã kết nối: {info.get('name')}\n{info.get('url')}\n\n"
                    "Máy này đã hiện trên cloud. Cứ để cửa sổ chạy nền.")

    bridge = Bridge(conf)
    threading.Thread(target=bridge.watch, daemon=True).start()
    tray(bridge)
    bridge.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
