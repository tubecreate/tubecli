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

BA NỀN TẢNG, MỘT FILE:
  Windows  pythonw tubecli_connect.pyw     (cài bằng install.ps1)
  macOS    python3 tubecli_connect.py      (cài bằng install.sh, cần Homebrew)
  Linux    python3 tubecli_connect.py      (cài bằng install.sh)
Mọi chỗ khác nhau giữa ba hệ (thư mục cấu hình, trình cài, bản cloudflared, cách
khởi động cùng máy, cách mở URL) gom trong đúng một hàm mỗi thứ — rắc `if
sys.platform` khắp file thì không còn đọc ra luồng chính nữa.

Chạy:  <python> tubecli_connect.py           (lần đầu sẽ hỏi mã ghép nối)
       <python> tubecli_connect.py --status  (in trạng thái rồi thoát)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WIN and not IS_MAC
OS_NAME = "Windows" if IS_WIN else ("macOS" if IS_MAC else "Linux")

APP = "TubeCLI Connect"
# Cloudflare chặn thẳng User-Agent mặc định của urllib ("Python-urllib/3.12") bằng
# lỗi 1010 — request chết ở edge, không tới Worker, nên mã đúng hay sai cũng ra 403.
# Đo trên máy người dùng 8/9/26: urllib → 403 "error code: 1010", cùng URL với UA
# thường → 410 (câu trả lời thật). Mọi cuộc gọi ra ngoài phải tự xưng tên.
UA = f"TubeCLI-Connect/1.0 (Windows; Python {sys.version_info.major}.{sys.version_info.minor})"
CLOUD = os.environ.get("TUBECLI_CLOUD", "https://cloud.tubecreate.com")
PORT = int(os.environ.get("TUBECLI_PORT", "5295"))
def _home_dir() -> str:
    """Chỗ mỗi hệ điều hành muốn app cất cấu hình. Không dùng chung ~/.tubecli cho
    cả ba: trên macOS thư mục ẩn ở $HOME là thứ không ai tìm ra, còn trên Linux nó
    phá quy ước XDG mà các công cụ sao lưu dựa vào."""
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TubeCLI")
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "TubeCLI")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "tubecli")


HOME = _home_dir()
CONF = os.path.join(HOME, "connect.json")
LOG = os.path.join(HOME, "connect.log")
CLOUDFLARED = os.path.join(HOME, "cloudflared.exe" if IS_WIN else "cloudflared")
RAW = "https://raw.githubusercontent.com/tubecreate/tubecli/main"
INSTALL_PS1 = f"{RAW}/install.ps1"
INSTALL_SH = f"{RAW}/install.sh"


def cpu_arch() -> str:
    """Tên kiến trúc theo cách Cloudflare đặt tên file phát hành."""
    m = (platform.machine() or "").lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m == "arm" or m.startswith("armv"):
        return "arm"
    if m in ("i386", "i686", "x86"):
        return "386"
    return "amd64"


def cloudflared_url() -> str:
    """Bản cloudflared đúng cho máy này.

    Ba hệ ba kiểu đóng gói, và đây là chỗ dễ sai âm thầm: macOS phát hành .tgz chứ
    không phải binary trần, nên tải về rồi chạy thẳng là "Exec format error".
    """
    base = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-"
    a = cpu_arch()
    if IS_WIN:
        return f"{base}windows-{'386' if a == '386' else 'amd64'}.exe"
    if IS_MAC:
        return f"{base}darwin-{'arm64' if a == 'arm64' else 'amd64'}.tgz"
    return f"{base}linux-{a}"


CF_URL = cloudflared_url()
HEALTH = f"http://127.0.0.1:{PORT}/api/v1/health"
DASH = f"http://127.0.0.1:{PORT}/dashboard"

def _install_ua_opener() -> None:
    """Gắn UA cho cả những chỗ gọi urlopen(chuỗi) — như lúc tải cloudflared."""
    op = urllib.request.build_opener()
    op.addheaders = [("User-Agent", UA)]
    urllib.request.install_opener(op)


_install_ua_opener()

# Nơi trình cài đặt TubeCLI. Người dùng có thể đổi, nên còn dò thêm ở dưới.
# install.ps1 dùng ~/TubeCLI, install.sh dùng ~/tubecli (chữ thường) — trên Linux
# hai cái đó là hai thư mục khác nhau, nên phải kể cả hai.
_H = os.path.expanduser("~")
DEFAULT_DIRS = ([os.path.join(_H, "TubeCLI"), r"C:\TubeCLI"] if IS_WIN
                else [os.path.join(_H, "tubecli"), os.path.join(_H, "TubeCLI"), "/opt/tubecli"])


# Form đăng ký một hàm vào đây để mọi dòng log hiện luôn trong khung nhật ký của
# nó. Danh sách chứ không phải một biến: cửa sổ trạng thái mở sau cũng nghe được.
_LOG_SINKS = []


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
    for sink in list(_LOG_SINKS):
        try:
            sink(line)
        except Exception:
            pass


def open_url(target: str) -> None:
    """Mở link hay file bằng trình mặc định của hệ. os.startfile CHỈ có trên
    Windows — gọi nó ở nơi khác là AttributeError giết luôn menu khay."""
    try:
        if IS_WIN:
            os.startfile(target)          # noqa: S606 — Windows-only API
        elif IS_MAC:
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
    except Exception as e:
        log(f"không mở được {target}: {e}")


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
        if IS_WIN:
            subprocess.run(["icacls", CONF, "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME')}:F"],
                           capture_output=True, timeout=10)
        else:
            os.chmod(CONF, 0o600)
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
    return bool(d) and any(os.path.isfile(os.path.join(d, *p)) for p in (
        ("TubeCLI.bat",),                      # install.ps1
        ("tubecli", "main.py"),                # bản git (máy người phát triển)
        (".venv", "bin", "tubecli"),           # install.sh
        ("venv", "bin", "tubecli"),
    ))


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
    if IS_WIN and os.path.isfile(lnk):
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
        if IS_WIN:
            py = os.path.join(d, "venv", "Scripts", "pythonw.exe")
            exe = py if os.path.isfile(py) else "pythonw"
            return [exe, "-m", "tubecli.main", "serve", "--port", str(PORT)], d
        # POSIX: chạy thẳng lệnh trong venv của bản cài. Gọi `python -m tubecli.main`
        # bằng python hệ thống thì thiếu sạch phụ thuộc — venv mới là bản có đủ.
        for rel in ((".venv", "bin", "tubecli"), ("venv", "bin", "tubecli")):
            p = os.path.join(d, *rel)
            if os.path.isfile(p):
                return [p, "serve", "--port", str(PORT)], d
        for rel in ((".venv", "bin", "python"), ("venv", "bin", "python")):
            p = os.path.join(d, *rel)
            if os.path.isfile(p):
                return [p, "-m", "tubecli.main", "serve", "--port", str(PORT)], d
    exe = shutil.which("tubecli")
    if not exe and not IS_WIN:
        # install.sh đặt launcher ở ~/.local/bin — thư mục này thường CHƯA có trong
        # PATH của phiên hiện tại, nên which() trượt dù máy đã cài xong.
        cand = os.path.join(os.path.expanduser("~"), ".local", "bin", "tubecli")
        exe = cand if os.access(cand, os.X_OK) else ""
    if exe:
        return [exe, "serve", "--port", str(PORT)], os.path.dirname(exe)
    return [], ""


def have_tubecli() -> bool:
    """Máy này đã có TubeCLI chưa. ĐANG CHẠY là câu trả lời mạnh nhất và phải hỏi
    TRƯỚC: máy người dùng có thể cài ở một thư mục lạ, nhưng cổng 5295 đang trả lời
    thì chuyện "chưa cài" là sai, và cài chồng lên chỉ tổ mở ra một trình hướng dẫn
    đứng đợi người gõ."""
    return tubecli_up() or bool(server_cmd()[0])


def install_command(lang: str = "vi") -> list:
    """Lệnh gọi trình cài CHÍNH THỨC của từng hệ. Không tự dựng bản cài riêng: một
    bản thứ hai là một bộ bug thứ hai."""
    if IS_WIN:
        ps = ("$ErrorActionPreference='Stop'; "
              f"$s = irm {INSTALL_PS1}; "
              f"& ([scriptblock]::Create($s)) -Lang {lang} -NonInteractive")
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]
    # bash -s -- truyền tham số cho script đọc từ stdin. --non-interactive vì ở đây
    # không có ai ngồi trước bàn phím: client đang chạy sau một cửa sổ đồ hoạ.
    sh = f"curl -fsSL {INSTALL_SH} | bash -s -- --lang {lang} --non-interactive"
    return ["bash", "-lc", sh]


def installed_now() -> bool:
    """TubeCLI đã có mặt trên máy CHƯA — hỏi máy, đừng hỏi mã thoát của trình cài.

    install.ps1 kết thúc bằng `tubecli init`, một bảng điều khiển tương tác không
    bao giờ trả về khi không có ai gõ; nó thoát khác 0 và chính nó in ra
    "TubeCLI itself is installed". Tin mã thoát ở đây là báo "cài hỏng" cho một
    máy vừa cài xong — đúng chuyện xảy ra với mọi máy Windows sạch (9/9/2026).
    """
    return tubecli_up() or bool(server_cmd()[0])


INSTALL_TIMEOUT = 1800        # 30 phút: tải Git + Python + clone trên mạng chậm


def install_tubecli(lang: str = "vi") -> bool:
    """Chạy trình cài CHÍNH THỨC và ĐỔ TỪNG DÒNG của nó vào log.

    Không mở cửa sổ console riêng nữa. Cửa sổ đen thứ hai vừa rối vừa vô dụng:
    đóng lại là mất sạch dấu vết, và người dùng chỉ còn một câu "Trình cài không
    hoàn tất" (9/9/2026). Log đi qua log() nên form hiện được ngay trong khung
    nhật ký của nó, mà file log vẫn giữ đủ để đọc lại sau.
    """
    cmd = install_command(lang)
    log(f"Chưa có TubeCLI — chạy trình cài ({OS_NAME}), có thể mất vài phút…")
    # stdin=DEVNULL: trình cài phải TỰ HỎNG NGAY nếu nó còn định hỏi han, thay vì
    # treo vô hạn trước một bàn phím không có ai ngồi.
    extra = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace", bufsize=1, **extra)
    except Exception as e:
        log(f"cài thất bại: {e}")
        return False

    deadline = time.time() + INSTALL_TIMEOUT
    try:
        for line in p.stdout:
            line = line.rstrip()
            if line:
                log(f"  cài| {line[:200]}")
            if time.time() > deadline:
                p.kill()
                log(f"trình cài quá {INSTALL_TIMEOUT // 60} phút — đã dừng")
                break
        rc = p.wait(timeout=60)
    except Exception as e:
        log(f"trình cài đứt giữa chừng: {e}")
        rc = -1

    # Hỏi lại chính cái máy, đừng hỏi mã thoát: install.ps1 kết thúc bằng
    # `tubecli init` và tự trả mã khác 0 dù đã cài xong.
    if installed_now():
        log("cài xong" if rc == 0 else f"cài xong (trình cài trả mã {rc}, nhưng TubeCLI đã có mặt)")
        return True
    log(f"trình cài trả mã {rc} — TubeCLI vẫn chưa có mặt")
    return False


def start_tubecli() -> bool:
    """Bật máy chủ TubeCLI, không kèm cửa sổ đen. Trả True khi /health trả lời."""
    if tubecli_up():
        return True
    cmd, d = server_cmd()
    if not cmd:
        return False
    log(f"bật TubeCLI từ {d}")
    try:
        extra = ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN
                 # start_new_session: tách khỏi nhóm tiến trình của client, để đóng
                 # client (hoặc Ctrl+C trong terminal) không kéo theo máy chủ.
                 else {"start_new_session": True,
                       "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
        subprocess.Popen(cmd, cwd=d or None, **extra)
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
        part = CLOUDFLARED + ".part"
        cf_req = urllib.request.Request(CF_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(cf_req, timeout=180) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
        if CF_URL.endswith(".tgz"):
            # macOS phát hành .tgz, bên trong đúng một file `cloudflared`. Chạy thẳng
            # file vừa tải là "Exec format error" — nó là gói nén, không phải binary.
            with tarfile.open(part) as tf:
                member = next((m for m in tf.getmembers()
                               if m.isfile() and os.path.basename(m.name) == "cloudflared"), None)
                if member is None:
                    raise RuntimeError("gói cloudflared không có binary bên trong")
                src = tf.extractfile(member)
                with open(CLOUDFLARED, "wb") as out:
                    shutil.copyfileobj(src, out)
            os.remove(part)
        else:
            os.replace(part, CLOUDFLARED)
        if not IS_WIN:
            os.chmod(CLOUDFLARED, 0o755)      # tải về là 0644 → không chạy được
        log(f"đã tải cloudflared ({OS_NAME}/{cpu_arch()})")
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


# ── Khởi động cùng máy ──────────────────────────────────────────────────────

def script_home() -> str:
    """Đường dẫn ổn định của chính client này.

    Lệnh cài tải file về thư mục tạm, mà %TEMP% (và /tmp) bị dọn định kỳ — trỏ mục
    "khởi động cùng máy" vào đó là hẹn ngày nó trỏ vào hư không. Nên lần ghép nối
    đầu tiên client tự chép mình sang thư mục cấu hình rồi mới cắm lối tắt.
    """
    name = "tubecli_connect.pyw" if IS_WIN else "tubecli_connect.py"
    dest = os.path.join(HOME, name)
    here = os.path.abspath(__file__)
    if os.path.normcase(here) == os.path.normcase(dest):
        return dest
    try:
        os.makedirs(HOME, exist_ok=True)
        shutil.copyfile(here, dest)
        if not IS_WIN:
            os.chmod(dest, 0o755)
        return dest
    except OSError as e:
        log(f"không chép được client vào {HOME}: {e}")
        return here


def runner() -> str:
    """Trình thông dịch dùng để chạy lại client — trên Windows là pythonw để không
    kèm cửa sổ đen."""
    if IS_WIN:
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return exe if os.path.isfile(exe) else sys.executable
    return sys.executable or "python3"


def startup_path() -> str:
    """Chỗ mỗi hệ đọc danh sách "chạy khi đăng nhập"."""
    h = os.path.expanduser("~")
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                            "Start Menu", "Programs", "Startup", "TubeCLI Connect.cmd")
    if IS_MAC:
        return os.path.join(h, "Library", "LaunchAgents", "com.tubecreate.connect.plist")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(h, ".config")
    return os.path.join(base, "autostart", "tubecli-connect.desktop")


def autostart_on() -> bool:
    return os.path.isfile(startup_path())


def _autostart_body(exe: str, script: str) -> str:
    if IS_WIN:
        return f'@echo off\r\nstart "" "{exe}" "{script}"\r\n'
    if IS_MAC:
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict>\n'
                '  <key>Label</key><string>com.tubecreate.connect</string>\n'
                f'  <key>ProgramArguments</key><array><string>{exe}</string>'
                f'<string>{script}</string></array>\n'
                '  <key>RunAtLoad</key><true/>\n'
                '</dict></plist>\n')
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP}\n"
            f"Exec={exe} {script}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Terminal=false\n")


def set_autostart(on: bool) -> None:
    p = startup_path()
    if not on:
        try:
            if IS_MAC:
                subprocess.run(["launchctl", "unload", p], capture_output=True, timeout=10)
            os.remove(p)
        except (OSError, Exception):
            pass
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(_autostart_body(runner(), script_home()))
        if not IS_WIN:
            os.chmod(p, 0o644 if IS_MAC else 0o755)
        if IS_MAC:
            # launchctl load để nó chạy ngay lần đăng nhập này, không phải đợi
            # khởi động lại máy.
            subprocess.run(["launchctl", "load", "-w", p], capture_output=True, timeout=10)
    except OSError as e:
        log(f"không đặt được khởi động cùng máy: {e}")


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
        say("Đã cài sẵn — đang bật TubeCLI…")      # đường dẫn đã có trong log
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

def has_tk() -> bool:
    try:
        import tkinter                      # noqa: F401
        return True
    except Exception:
        return False


def ask_pairing_console(default_code: str = "", lang: str = "vi") -> tuple:
    """Hỏi mã ngay trong terminal. Linux tối giản hay thiếu python3-tk, và một
    client không mở nổi cửa sổ mà cũng không hỏi được gì thì coi như hỏng hẳn."""
    print(f"\n=== {APP} ({OS_NAME}) ===")
    print("Thiếu tkinter nên dùng chế độ dòng lệnh "
          "(cài giao diện: sudo apt install python3-tk).")
    ok_node, suggest = prepare_node(lambda m: print(f"  {m}"), lang)
    if not ok_node:
        return "", "", None
    import getpass
    while True:
        code = (input(f"Mã ghép nối [{default_code}]: ").strip() or default_code).upper()
        pw = getpass.getpass(f"Mật khẩu dashboard TubeCLI{' [' + suggest + ']' if suggest else ''}: ") or suggest
        if len(code) < 4 or not pw:
            print("  Nhập đủ mã và mật khẩu.")
            continue
        if not node_login(pw):
            print("  Mật khẩu dashboard không đúng — thử lại.")
            continue
        try:
            info = claim(code, pw)
        except RuntimeError as e:
            print(f"  Cloud không nhận mã: {e}")
            continue
        log(f"ghép nối xong: {info.get('url')}")
        return code, pw, info


# ── Giao diện: bảng màu và những mảnh vẽ tay ───────────────────────────────
# Lấy đúng token của dashboard TubeCLI (webui/static/style.css) để client không
# trông như một phần mềm khác dán vào.
UI = {
    "bg": "#0e0e11", "panel": "#16161b", "panel2": "#1c1c22",
    "line": "#2a2a33", "text": "#f4f4f5", "muted": "#a1a1aa", "dim": "#71717a",
    "violet": "#7c3aed", "violet_hi": "#8b5cf6", "cyan": "#38bdf8",
    "green": "#22c55e", "red": "#f87171", "amber": "#f59e0b",
}
FONT = "Segoe UI" if IS_WIN else ("SF Pro Text" if IS_MAC else "DejaVu Sans")
MONO = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")


# Logo TubeCLI THẬT (tubecli-cloud/public/logo.svg) đã rasterize sẵn 40px.
# Nhúng base64 chứ không vẽ tay: hình thật là một path Bézier phức tạp — tam giác
# play với con chip "AI" bên trong — vẽ gần đúng bằng Canvas thì ra một logo KHÁC,
# và logo gần đúng còn tệ hơn không có logo.
LOGO_PNG_B64 = (
    "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"
)


def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Tkinter không có hình chữ nhật bo góc; polygon smooth là cách chuẩn."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def _logo(parent, size=40):
    """Ô logo cho đầu cửa sổ.

    PhotoImage phải được GIỮ THAM CHIẾU, nếu không Python thu gom nó và tkinter vẽ
    ra một ô trống — cái bẫy kinh điển của tkinter, và nó im lặng.
    """
    import tkinter as tk
    cv = tk.Canvas(parent, width=size, height=size, bg=UI["panel"],
                   highlightthickness=0, bd=0)
    try:
        img = tk.PhotoImage(data=LOGO_PNG_B64)
        cv.create_image(size // 2, size // 2, image=img)
        cv.image = img                      # giữ tham chiếu
        return cv
    except Exception:
        pass
    # Tk quá cũ (chưa đọc được PNG) thì vẽ một dấu tối giản, còn hơn ô trống.
    k = size / 64.0
    _round_rect(cv, 1, 1, size - 1, size - 1, 12 * k, fill="#131318", outline=UI["line"])
    cv.create_polygon(22 * k, 14 * k, 50 * k, 32 * k, 22 * k, 50 * k,
                      fill="#5276EB", outline="")
    return cv


def _set_icon(root):
    """Icon cửa sổ + thanh tác vụ. Không đặt thì Tk dùng con lông vũ mặc định của
    nó — một cửa sổ hỏi mật khẩu mang icon lạ trông y như phần mềm giả mạo."""
    import tkinter as tk
    try:
        img = tk.PhotoImage(data=LOGO_PNG_B64)
        root.iconphoto(True, img)
        root._tc_icon = img            # giữ tham chiếu, nếu không tkinter xoá trắng
    except Exception:
        pass


def _theme(root):
    """ttk mặc định trên Windows không cho đổi màu nền ô nhập; 'clam' thì cho."""
    from tkinter import ttk
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass
    st.configure("TC.TEntry", fieldbackground=UI["panel2"], foreground=UI["text"],
                 bordercolor=UI["line"], lightcolor=UI["line"], darkcolor=UI["line"],
                 insertcolor=UI["text"], borderwidth=1, padding=9)
    st.map("TC.TEntry", bordercolor=[("focus", UI["violet"])],
           lightcolor=[("focus", UI["violet"])], darkcolor=[("focus", UI["violet"])])
    st.configure("TC.TButton", background=UI["violet"], foreground="#ffffff",
                 borderwidth=0, focusthickness=0, padding=(14, 10),
                 font=(FONT, 10, "bold"))
    st.map("TC.TButton",
           background=[("disabled", "#2a2233"), ("pressed", "#6d28d9"),
                       ("active", UI["violet_hi"])],
           foreground=[("disabled", UI["dim"])])
    # Thanh cuộn mặc định của 'clam' là màu sáng — một vệt trắng cạnh khung nhật ký
    # tối trông như lỗi hiển thị.
    st.configure("TC.Vertical.TScrollbar", background=UI["line"], troughcolor="#0a0a0d",
                 bordercolor="#0a0a0d", arrowcolor=UI["dim"], borderwidth=0)
    st.map("TC.Vertical.TScrollbar", background=[("active", UI["dim"])])
    st.configure("TC.Horizontal.TProgressbar", troughcolor=UI["panel2"],
                 background=UI["violet"], borderwidth=0, thickness=4,
                 lightcolor=UI["violet"], darkcolor=UI["violet"])
    return st


def ask_pairing(default_code: str = "", lang: str = "vi") -> tuple:
    if not has_tk():
        return ask_pairing_console(default_code, lang)
    import tkinter as tk
    from tkinter import ttk

    out = {"code": "", "password": "", "info": None}
    root = tk.Tk()
    root.title(APP)
    root.configure(bg=UI["bg"])
    root.resizable(False, False)
    _set_icon(root)
    # Cửa sổ mở sau lưng trình duyệt thì cũng như không mở — người dùng đang nhìn
    # trang cloud, không ai đi lục thanh tác vụ.
    root.attributes("-topmost", True)
    root.after(1200, lambda: root.attributes("-topmost", False))
    root.lift()
    try:
        root.focus_force()
    except Exception:
        pass
    _theme(root)

    wrap = tk.Frame(root, bg=UI["bg"])
    wrap.pack(fill="both", expand=True)

    # ── Đầu trang: logo + tên + hệ điều hành ──────────────────────────────
    head = tk.Frame(wrap, bg=UI["panel"])
    head.pack(fill="x")
    inner = tk.Frame(head, bg=UI["panel"])
    inner.pack(fill="x", padx=18, pady=14)
    _logo(inner, 40).pack(side="left")
    tit = tk.Frame(inner, bg=UI["panel"])
    tit.pack(side="left", padx=12)
    tk.Label(tit, text=APP, bg=UI["panel"], fg=UI["text"],
             font=(FONT, 13, "bold")).pack(anchor="w")
    tk.Label(tit, text="Nối máy này với cloud.tubecreate.com", bg=UI["panel"],
             fg=UI["muted"], font=(FONT, 9)).pack(anchor="w")
    tk.Label(inner, text=f" {OS_NAME} ", bg=UI["panel2"], fg=UI["dim"],
             font=(FONT, 8), padx=6, pady=3).pack(side="right")
    tk.Frame(wrap, bg=UI["line"], height=1).pack(fill="x")

    body = tk.Frame(wrap, bg=UI["bg"])
    body.pack(fill="both", expand=True, padx=18, pady=16)

    # ── Bước 1: chuẩn bị máy ──────────────────────────────────────────────
    srow = tk.Frame(body, bg=UI["bg"])
    srow.pack(fill="x")
    dot = tk.Canvas(srow, width=10, height=10, bg=UI["bg"], highlightthickness=0)
    dot.pack(side="left", pady=(4, 0))
    dot_id = dot.create_oval(1, 1, 9, 9, fill=UI["dim"], outline="")
    state = tk.Label(srow, text="Đang kiểm tra máy…", bg=UI["bg"], fg=UI["muted"],
                     font=(FONT, 9), anchor="w", justify="left", wraplength=380)
    state.pack(side="left", padx=8)

    bar = ttk.Progressbar(body, style="TC.Horizontal.TProgressbar", mode="indeterminate")
    bar.pack(fill="x", pady=(9, 0))
    bar.start(14)

    # ── Nhật ký NGAY TRONG FORM ───────────────────────────────────────────
    # Trước đây trình cài mở một cửa sổ PowerShell riêng: đóng lại là mất sạch dấu
    # vết, và người dùng chỉ còn đúng một câu "Trình cài không hoàn tất".
    logbox = tk.Frame(body, bg=UI["bg"])
    txt = tk.Text(logbox, height=7, bg="#0a0a0d", fg=UI["muted"], bd=0,
                  font=(MONO, 8), wrap="none", padx=10, pady=8,
                  insertbackground=UI["text"], highlightthickness=1,
                  highlightbackground=UI["line"], highlightcolor=UI["line"])
    sb = ttk.Scrollbar(logbox, orient="vertical", command=txt.yview,
                       style="TC.Vertical.TScrollbar")
    txt.configure(yscrollcommand=sb.set, state="disabled")
    txt.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def add_line(line: str):
        def put():
            txt.configure(state="normal")
            txt.insert("end", line + "\n")
            # Giữ 400 dòng cuối: trình cài Windows in rất nhiều, không cắt thì
            # widget phình ra và cuộn giật.
            if int(txt.index("end-1c").split(".")[0]) > 400:
                txt.delete("1.0", "100.0")
            txt.see("end")
            txt.configure(state="disabled")
        try:
            root.after(0, put)
        except Exception:
            pass

    _LOG_SINKS.append(add_line)

    shown = {"on": False}

    def toggle_log(force=None):
        want = (not shown["on"]) if force is None else force
        if want == shown["on"]:
            return
        shown["on"] = want
        if want:
            logbox.pack(fill="both", expand=True, pady=(10, 0), before=sep)
            more.config(text="Ẩn nhật ký ▴")
        else:
            logbox.pack_forget()
            more.config(text="Xem nhật ký ▾")

    more = tk.Label(body, text="Xem nhật ký ▾", bg=UI["bg"], fg=UI["dim"],
                    font=(FONT, 8), cursor="hand2")
    more.pack(anchor="e", pady=(7, 0))
    more.bind("<Button-1>", lambda _e: toggle_log())

    sep = tk.Frame(body, bg=UI["line"], height=1)
    sep.pack(fill="x", pady=12)

    # ── Bước 2: mã ghép nối ───────────────────────────────────────────────
    def field_label(parent, text):
        return tk.Label(parent, text=text, bg=UI["bg"], fg=UI["dim"],
                        font=(FONT, 8, "bold"), anchor="w")

    field_label(body, "MÃ GHÉP NỐI").pack(fill="x")
    e_code = ttk.Entry(body, style="TC.TEntry", font=(MONO, 15, "bold"), justify="center")
    e_code.pack(fill="x", pady=(4, 3))
    e_code.insert(0, default_code)
    tk.Label(body, text="Lấy trên cloud → Kết nối máy của tôi", bg=UI["bg"],
             fg=UI["dim"], font=(FONT, 8), anchor="w").pack(fill="x", pady=(0, 12))

    field_label(body, "MẬT KHẨU DASHBOARD TUBECLI").pack(fill="x")
    e_pw = ttk.Entry(body, style="TC.TEntry", show="•", font=(FONT, 11))
    e_pw.pack(fill="x", pady=(4, 3))
    tk.Label(body, text="Máy vừa cài xong thì để 123456.", bg=UI["bg"],
             fg=UI["dim"], font=(FONT, 8), anchor="w").pack(fill="x")

    msg = tk.Label(body, text="", bg=UI["bg"], fg=UI["red"], font=(FONT, 9),
                   anchor="w", justify="left", wraplength=400)
    msg.pack(fill="x", pady=(10, 0))

    btn = ttk.Button(body, text="Kết nối", style="TC.TButton")
    btn.pack(fill="x", pady=(12, 0))
    btn.state(["disabled"])                 # chỉ mở khi máy chủ đã trả lời

    foot = tk.Frame(wrap, bg=UI["bg"])
    foot.pack(fill="x", padx=18, pady=(0, 12))
    flog = tk.Label(foot, text="Mở tệp nhật ký", bg=UI["bg"], fg=UI["dim"],
                    font=(FONT, 8), cursor="hand2")
    flog.pack(side="left")
    flog.bind("<Button-1>", lambda _e: open_url(LOG) if os.path.isfile(LOG) else None)
    tk.Label(foot, text=CLOUD.replace("https://", ""), bg=UI["bg"], fg=UI["dim"],
             font=(FONT, 8)).pack(side="right")

    def set_dot(color):
        try:
            dot.itemconfig(dot_id, fill=color)
        except Exception:
            pass

    def fail(text: str):
        """Hỏng thì Ở LẠI cửa sổ. Mã sống 15 phút; bắt tải lại client rồi gõ lại từ
        đầu là ép người dùng chạy đua với đồng hồ vì một lỗi đánh máy."""
        log(f"ghép nối hỏng: {text}")

        def show():
            msg.config(text=text)
            state.config(text="Sửa rồi bấm Kết nối lại.", fg=UI["red"])
            set_dot(UI["red"])
            bar.stop()
            bar.pack_forget()
            btn.state(["!disabled"])
            toggle_log(True)
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
        state.config(text="Đang ghép nối với cloud…", fg=UI["muted"])
        set_dot(UI["amber"])
        bar.pack(fill="x", pady=(9, 0), after=srow)
        bar.start(14)
        threading.Thread(target=connect, args=(code, pw), daemon=True).start()

    btn.config(command=ok)
    root.bind("<Return>", lambda _e: ok() if "disabled" not in btn.state() else None)

    # Dò / bật / cài chạy ở LUỒNG NỀN: trình cài có thể mất vài phút, mà cửa sổ đứng
    # đơ mấy phút thì Windows dán nhãn "Not responding" và người dùng tắt nó đi.
    def prepare():
        # Mở sẵn: người dùng phải THẤY máy đang làm gì, nhất là lúc trình cài chạy
        # vài phút. Trước đây phần này nằm ở một cửa sổ PowerShell riêng.
        root.after(0, lambda: toggle_log(True))
        ok_node, suggest = prepare_node(lambda m: root.after(0, lambda: state.config(text=m)), lang)

        def done():
            bar.stop()
            bar.pack_forget()
            if ok_node:
                state.config(fg=UI["green"])
                set_dot(UI["green"])
                btn.state(["!disabled"])
                toggle_log(False)
                if suggest and not e_pw.get():
                    e_pw.insert(0, suggest)
                (e_code if not e_code.get() else e_pw).focus()
            else:
                state.config(fg=UI["red"])
                set_dot(UI["red"])
                toggle_log(True)
        root.after(0, done)

    threading.Thread(target=prepare, daemon=True).start()
    e_code.focus()
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
    root.mainloop()
    try:
        _LOG_SINKS.remove(add_line)
    except ValueError:
        pass
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
        if has_tk():
            log("thiếu pystray/Pillow — mở cửa sổ trạng thái thay cho icon khay")
            status_window(bridge)
            return
        # Máy không đồ hoạ (Linux server, WSL trần): giữ cầu nối sống và IN trạng
        # thái ra terminal theo nhịp — người dùng đang ngồi ở đó, đó là màn hình
        # duy nhất họ có.
        log("không có pystray lẫn tkinter — chạy ở chế độ terminal, Ctrl+C để dừng")
        try:
            while True:
                log(bridge.status())
                time.sleep(60)
        except KeyboardInterrupt:
            log("dừng theo yêu cầu")
        return

    img = Image.new("RGB", (64, 64), "#111827")
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill="#5276EB")

    def toggle_autostart(icon, item):
        set_autostart(not autostart_on())

    menu = pystray.Menu(
        pystray.MenuItem(lambda _i: bridge.status(), None, enabled=False),
        pystray.MenuItem("Mở dashboard", lambda: open_url(DASH)),
        pystray.MenuItem("Mở cloud", lambda: open_url(CLOUD + "/dash")),
        pystray.MenuItem("Xem log", lambda: open_url(LOG) if os.path.isfile(LOG) else None),
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
    _set_icon(root)
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
    ttk.Button(bar, text="Mở dashboard", command=lambda: open_url(DASH)).grid(column=0, row=0, padx=(0, 6))
    ttk.Button(bar, text="Mở cloud", command=lambda: open_url(CLOUD + "/dash")).grid(column=1, row=0, padx=(0, 6))
    ttk.Button(bar, text="Xem log",
               command=lambda: open_url(LOG) if os.path.isfile(LOG) else None).grid(column=2, row=0, padx=(0, 6))

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
