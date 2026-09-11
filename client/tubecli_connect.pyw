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


def client_build() -> str:
    """Vân tay của CHÍNH file này.

    Raw GitHub cache khoảng 5 phút, nên "tải lại rồi mà vẫn lỗi y hệt" là chuyện
    thường gặp — và không có cách nào nhìn log mà biết được đang chạy bản nào.
    Băm nội dung file thì không bao giờ lệch với thực tế, khỏi phải nhớ tăng số.
    """
    try:
        import hashlib
        with open(os.path.abspath(__file__), "rb") as f:
            # Chuẩn hoá xuống dòng: git trả bản LF, Windows giữ bản CRLF — không bỏ
            # qua khác biệt đó thì hai bên ra hai mã khác nhau và vân tay vô dụng.
            data = f.read().replace(b"\r\n", b"\n")
        return hashlib.sha256(data).hexdigest()[:8]
    except Exception:
        return "?"


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


# `tubecli serve` KHÔNG TỒN TẠI — CLI chỉ có `api start`. Bản trước đoán tên lệnh
# và tiến trình con chết ngay với "No such command 'serve'" (đo 9/9/2026).
# --quiet: chạy nền thì log truy cập HTTP chỉ tổ làm phình tệp.
SERVE_ARGS = ["api", "start", "--port", str(PORT), "--quiet"]


def refresh_path_win() -> None:
    """Nạp lại PATH từ registry.

    install.ps1 thêm thư mục Scripts vào PATH của NGƯỜI DÙNG, nhưng tiến trình đang
    chạy giữ nguyên bản sao PATH lúc nó khởi động — nên ngay sau khi cài xong,
    chính client vẫn không nhìn thấy `tubecli` vừa được cài.
    """
    if not IS_WIN:
        return
    try:
        import winreg
        parts = []
        for root, key in ((winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    parts.append(os.path.expandvars(val))
            except OSError:
                pass
        if parts:
            merged = os.pathsep.join(parts + [os.environ.get("PATH", "")])
            seen, keep = set(), []
            for p in merged.split(os.pathsep):
                q = p.strip().rstrip("\\").lower()
                if p.strip() and q not in seen:
                    seen.add(q)
                    keep.append(p.strip())
            os.environ["PATH"] = os.pathsep.join(keep)
    except Exception as e:
        log(f"không nạp lại được PATH: {e}")


def _can_import_tubecli(py: str) -> bool:
    """Trình thông dịch này có THẬT SỰ chạy được TubeCLI không — hỏi nó, đừng đoán."""
    if not py or not os.path.isfile(py):
        return False
    try:
        r = subprocess.run([py, "-c", "import tubecli, click"], capture_output=True, timeout=40,
                           env=clean_env(),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0)
        return r.returncode == 0
    except Exception:
        return False


def python_with_tubecli(install_dir: str = "") -> str:
    """Đường dẫn tới trình thông dịch chạy được TubeCLI, hay "".

    Thứ tự: venv của bản cài → trình thông dịch NẰM CẠNH launcher `tubecli` (pip đặt
    launcher vào Scripts của đúng Python đã cài gói) → python trên PATH → python
    đang chạy client. Mỗi ứng viên đều bị thử `import tubecli, click` trước khi dùng.
    """
    exe = "pythonw.exe" if IS_WIN else "python"
    cands = []
    for d in ([install_dir] if install_dir else []):
        for venv in ("venv", ".venv"):
            cands.append(os.path.join(d, venv, "Scripts" if IS_WIN else "bin", exe))
    launcher = shutil.which("tubecli")
    if launcher:
        # …\PythonXX\Scripts\tubecli.exe → …\PythonXX\pythonw.exe
        base = os.path.dirname(os.path.dirname(launcher))
        cands.append(os.path.join(base, exe))
        cands.append(os.path.join(os.path.dirname(launcher), exe))
    cands += [shutil.which(exe), shutil.which("python3"), sys.executable]
    seen = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        if _can_import_tubecli(c):
            return c
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
            for venv in ("venv", ".venv"):
                py = os.path.join(d, venv, "Scripts", "pythonw.exe")
                if os.path.isfile(py):
                    return [py, "-m", "tubecli.main"] + SERVE_ARGS, d
            # install.ps1 không dựng venv trên Windows: nó pip install vào một Python
            # nào đó rồi để launcher `tubecli.exe` trong Scripts của Python ấy.
            # Launcher biết đúng trình thông dịch, còn `pythonw` trần thì không.
            launcher = shutil.which("tubecli")
            if launcher:
                return [launcher] + SERVE_ARGS, d
            py = python_with_tubecli(d)
            if py:
                return [py, "-m", "tubecli.main"] + SERVE_ARGS, d
            return ["pythonw", "-m", "tubecli.main"] + SERVE_ARGS, d
        # POSIX: chạy thẳng lệnh trong venv của bản cài. Gọi `python -m tubecli.main`
        # bằng python hệ thống thì thiếu sạch phụ thuộc — venv mới là bản có đủ.
        for rel in ((".venv", "bin", "tubecli"), ("venv", "bin", "tubecli")):
            p = os.path.join(d, *rel)
            if os.path.isfile(p):
                return [p] + SERVE_ARGS, d
        for rel in ((".venv", "bin", "python"), ("venv", "bin", "python")):
            p = os.path.join(d, *rel)
            if os.path.isfile(p):
                return [p, "-m", "tubecli.main"] + SERVE_ARGS, d
    exe = shutil.which("tubecli")
    if not exe and not IS_WIN:
        # install.sh đặt launcher ở ~/.local/bin — thư mục này thường CHƯA có trong
        # PATH của phiên hiện tại, nên which() trượt dù máy đã cài xong.
        cand = os.path.join(os.path.expanduser("~"), ".local", "bin", "tubecli")
        exe = cand if os.access(cand, os.X_OK) else ""
    if exe:
        return [exe] + SERVE_ARGS, os.path.dirname(exe)
    return [], ""


def have_tubecli() -> bool:
    """Máy này đã có TubeCLI chưa. ĐANG CHẠY là câu trả lời mạnh nhất và phải hỏi
    TRƯỚC: máy người dùng có thể cài ở một thư mục lạ, nhưng cổng 5295 đang trả lời
    thì chuyện "chưa cài" là sai, và cài chồng lên chỉ tổ mở ra một trình hướng dẫn
    đứng đợi người gõ."""
    return tubecli_up() or bool(server_cmd()[0])


# Biến môi trường CA trỏ vào một đường dẫn không tồn tại làm HỎNG MỌI kết nối TLS
# của tiến trình Python con. Đo trên máy khách 9/9/2026: SSL_CERT_FILE trỏ vào
# D:\T2Render\_internal\certifi\cacert.pem — rác còn lại của một app đóng gói bằng
# PyInstaller — nên pip không tải nổi gói nào, `pip install -e .` chưa bao giờ xong,
# thiếu `click`, và máy chủ chết ở mọi lượt chạy.
CA_VARS = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def clean_env() -> dict:
    """Bản sao môi trường đã gỡ những biến CA trỏ vào chỗ không còn tồn tại.

    Chỉ gỡ khi đường dẫn SAI: máy nào cố tình dùng CA riêng (proxy doanh nghiệp)
    thì vẫn phải được tôn trọng.
    """
    env = dict(os.environ)
    for k in CA_VARS:
        v = env.get(k)
        if v and not os.path.exists(v):
            log(f"bỏ {k} vì trỏ vào chỗ không tồn tại: {v}")
            env.pop(k, None)
    return env


def python_for_pip() -> str:
    """Một Python CÓ PIP để cài phụ thuộc. Không đòi nó import được tubecli — đó
    chính là thứ ta sắp đi cài."""
    cands = [shutil.which("python"), shutil.which("python3"), sys.executable]
    if IS_WIN:
        local = os.environ.get("LOCALAPPDATA", "")
        for ver in ("Python313", "Python312", "Python311", "Python310"):
            cands.append(os.path.join(local, "Programs", "Python", ver, "python.exe"))
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        try:
            r = subprocess.run([c, "-m", "pip", "--version"], capture_output=True, timeout=60,
                               env=clean_env(),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return ""


def repair_deps(d: str, say=None) -> bool:
    """Cài phụ thuộc cho một thư mục TubeCLI đã có mã nguồn nhưng chưa chạy được.

    Đo trên máy khách 9/9/2026: thư mục đủ mã nguồn mà không Python nào import nổi
    `click` — `pip install -e .` chưa từng chạy xong. Client cũ coi "thấy
    tubecli/main.py" là "đã cài", nên nó bật máy chủ, máy chủ chết vì thiếu phụ
    thuộc, và vòng đó lặp lại mãi. Có mã nguồn KHÔNG phải là cài được.
    """
    if not d or not os.path.isfile(os.path.join(d, "pyproject.toml")):
        return False
    py = python_for_pip()
    if not py:
        log("không tìm thấy Python nào có pip để cài phụ thuộc")
        return False
    msg = "Thiếu thư viện — đang cài phụ thuộc TubeCLI…"
    log(f"{msg} ({py})")
    if say:
        say(msg)
    # `-e .` là đường chính: nó cài phụ thuộc VÀ đặt luôn launcher `tubecli`.
    # Hỏng thì lùi về requirements.txt — máy chủ chạy với cwd là chính thư mục mã
    # nguồn, nên chỉ cần thư viện bên thứ ba là đủ để nó sống.
    attempts = [["-e", "."]]
    if os.path.isfile(os.path.join(d, "requirements.txt")):
        attempts.append(["-r", "requirements.txt"])
    rc = -1
    for args in attempts:
        cmd = [py, "-m", "pip", "install"] + args
        log("  pip| $ " + " ".join(args))
        try:
            p = subprocess.Popen(cmd, cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                 errors="replace", bufsize=1, env=clean_env(),
                                 **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}))
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    log(f"  pip| {line[:200]}")
            rc = p.wait(timeout=900)
        except Exception as e:
            log(f"cài phụ thuộc hỏng: {e}")
            continue
        refresh_path_win()
        if _can_import_tubecli(py) or shutil.which("tubecli"):
            log("cài phụ thuộc xong")
            return True
    log(f"pip trả mã {rc} — vẫn chưa import được tubecli")
    return False


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


def install_tubecli(lang: str = "vi", reason: str = "") -> bool:
    """Chạy trình cài CHÍNH THỨC và ĐỔ TỪNG DÒNG của nó vào log.

    Không mở cửa sổ console riêng nữa. Cửa sổ đen thứ hai vừa rối vừa vô dụng:
    đóng lại là mất sạch dấu vết, và người dùng chỉ còn một câu "Trình cài không
    hoàn tất" (9/9/2026). Log đi qua log() nên form hiện được ngay trong khung
    nhật ký của nó, mà file log vẫn giữ đủ để đọc lại sau.
    """
    cmd = install_command(lang)
    log(f"{reason or 'Chưa có TubeCLI'} — chạy trình cài ({OS_NAME}), có thể mất vài phút…")
    # stdin=DEVNULL: trình cài phải TỰ HỎNG NGAY nếu nó còn định hỏi han, thay vì
    # treo vô hạn trước một bàn phím không có ai ngồi.
    extra = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, text=True, env=clean_env(),
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


# Một lượt bật đang chạy dở. Vòng canh quay 20 giây một lần, còn máy chủ mất
# ~40 giây mới trả lời /health — không có cờ này thì vòng canh bắn phát thứ hai
# TRONG LÚC phát thứ nhất còn đang lên, và máy có HAI máy chủ. Cái thứ hai không
# giữ được cổng nên gần như vô hình, nhưng nó vẫn chạy worker: đo thật 10/9/2026,
# một lượt dựng video đang chạy bị giết giữa chừng với câu
# "Task was interrupted by a server restart."
# Bao nhiêu lượt dò trượt LIÊN TIẾP mới coi là chết. Vòng canh quay 20 giây,
# nên 3 lượt ≈ 1 phút im lặng — dài hơn mọi lúc bận thường gặp, ngắn hơn mức
# người dùng kịp nhận ra máy đã biến khỏi cloud.
DEAD_AFTER = 3

_STARTING = threading.Lock()


def start_tubecli() -> bool:
    """Bật máy chủ TubeCLI, không kèm cửa sổ đen. Trả True khi /health trả lời.

    Không bao giờ chạy hai lượt song song: lượt thứ hai thấy khoá đang giữ thì
    quay về ngay, để vòng canh đợi thêm một nhịp thay vì đẻ ra máy chủ thứ hai.
    """
    if tubecli_up():
        return True
    if not _STARTING.acquire(blocking=False):
        log("đã có một lượt bật đang chạy — bỏ qua lượt này")
        return False
    try:
        return _start_tubecli_locked()
    finally:
        _STARTING.release()


def _start_tubecli_locked() -> bool:
    if tubecli_up():
        return True
    # Cổng ĐANG BỊ GIỮ = có máy chủ sống, chỉ là đang bận: /health chờ có 2 giây,
    # còn lúc CapCut đọc hay ffmpeg dựng nó im lâu hơn thế nhiều. Phép chặn này
    # trước đây chỉ nằm trong watch(); ba đường khác (khởi động lại, tự bật, kết nối
    # lại) gọi thẳng vào đây và đẻ máy chủ ma. Đo thật 11/9/2026: 5 bản trong 3
    # phút, mỗi bản nạp toàn bộ extension rồi đánh dấu task đang dựng video của máy
    # chủ thật là "Orphaned by server restart" trước khi tự chết vì cổng bận.
    held = _pid_of_port(PORT)
    if held:
        log(f"cổng {PORT} đang do pid {held} giữ — máy chủ vẫn sống (đang bận), không bật thêm")
        return True
    cmd, d = server_cmd()
    if not cmd:
        return False
    log(f"bật TubeCLI từ {d}")
    # Máy chủ chạy nền không có console, nên nếu KHÔNG hứng output thì mọi lỗi khởi
    # động biến mất và tất cả những gì ta biết là "60 giây không trả lời". Chính
    # cái đó giấu mất "No such command 'serve'" suốt.
    out = os.path.join(HOME, "server.log")
    try:
        os.makedirs(HOME, exist_ok=True)
        fh = open(out, "a", encoding="utf-8", errors="replace")
        fh.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd)} (cwd={d})\n")
        fh.flush()
    except OSError:
        fh = None
    try:
        extra = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {
            # start_new_session: tách khỏi nhóm tiến trình của client, để đóng
            # client (hoặc Ctrl+C trong terminal) không kéo theo máy chủ.
            "start_new_session": True}
        proc = subprocess.Popen(cmd, cwd=d or None, env=clean_env(),
                                stdout=fh or subprocess.DEVNULL,
                                stderr=subprocess.STDOUT, **extra)
    except Exception as e:
        log(f"không bật được TubeCLI: {e}")
        return False
    _write_pid(proc.pid)
    for _ in range(60):
        if tubecli_up():
            log("TubeCLI đã sẵn sàng")
            return True
        if proc.poll() is not None:
            log(f"máy chủ TubeCLI thoát ngay (mã {proc.returncode}) — xem {out}")
            for ln in _tail_lines(out, 8):
                log(f"  máy chủ| {ln[:200]}")
            return False
        time.sleep(1)
    log(f"TubeCLI không trả lời sau 60 giây — xem {out}")
    return False


PIDFILE = os.path.join(HOME, "server.pid")


def _write_pid(pid: int) -> None:
    """Nhớ pid máy chủ để nút «Khởi động lại» tắt ĐÚNG tiến trình.

    Không có file này thì cách duy nhất là dò ai đang giữ cổng 5295 — mà trên
    máy người dùng, cổng ấy có thể là một bản TubeCLI khác họ tự bật, và tắt
    nhầm nó là mất việc đang chạy dở.
    """
    try:
        with open(PIDFILE, "w", encoding="utf-8") as f:
            f.write(str(int(pid)))
    except OSError:
        pass


def _pid_of_port(port: int) -> int:
    """Ai đang nghe cổng này. 0 nếu không rõ — đường lui khi mất file pid."""
    try:
        if IS_WIN:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                 text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 5 and p[3].upper() == "LISTENING" and p[1].endswith(f":{port}"):
                    return int(p[4])
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in out.split():
                return int(line)
    except Exception:      # noqa: BLE001 — thiếu netstat/lsof, timeout, gì cũng vậy
        pass
    return 0


def node_stop(timeout: float = 12.0) -> bool:
    """Tắt máy chủ TubeCLI. True khi cổng đã im.

    Tắt CẢ CÂY tiến trình: máy chủ đẻ ra Chromium, ffmpeg, cloudflared con — giết
    mỗi tiến trình cha thì đám con thành mồ côi, vẫn giữ cổng và vẫn ăn RAM, và
    lần bật sau báo «cổng đang bận» mà không ai hiểu vì sao.
    """
    # AI ĐANG GIỮ CỔNG mới là máy chủ — hỏi hệ điều hành TRƯỚC, file pid chỉ là
    # đường lui. Bản đầu làm ngược lại và đã giết nhầm: máy này có HAI bản cài
    # TubeCLI, `server.pid` giữ pid của lượt bật sau (đã chết), còn cổng 5295 thì
    # do lượt bật trước nắm. Giết pid trong file xong cổng vẫn kêu, hàm chờ hết
    # 12 giây rồi báo "vẫn trả lời sau khi đã bảo tắt" — mà thủ phạm là chính
    # cái file sinh ra để tránh giết nhầm. Đo thật 10/9/2026.
    pid = _pid_of_port(PORT)
    if not pid:
        try:
            with open(PIDFILE, encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
        except (OSError, ValueError):
            pid = 0
    if not pid:
        return not tubecli_up()
    log(f"tắt máy chủ TubeCLI (pid {pid})")
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, AttributeError):
                os.kill(pid, signal.SIGTERM)
    except Exception as e:      # noqa: BLE001
        log(f"tắt máy chủ hỏng: {e}")
    end = time.time() + timeout
    while time.time() < end:
        if not tubecli_up():
            try:
                os.remove(PIDFILE)
            except OSError:
                pass
            return True
        time.sleep(0.4)
    log("máy chủ vẫn trả lời sau khi đã bảo tắt")
    return False


def node_restart(say=None) -> bool:
    """Tắt rồi bật lại máy chủ. Đây là thứ người dùng cần sau mỗi lần cập nhật
    extension: mã Python nằm trong RAM, sửa file trên đĩa xong vẫn chạy bản cũ."""
    def _s(m):
        log(m)
        if say:
            try:
                say(m)
            except Exception:      # noqa: BLE001
                pass
    _s("đang tắt máy chủ…")
    if not node_stop() and _pid_of_port(PORT):
        # Máy chủ cũ chưa nhả cổng. Bật lúc này thì start_tubecli coi "cổng bị giữ"
        # là "đang chạy" và báo thành công cho một lượt khởi động lại chưa hề xảy ra.
        _s("máy chủ cũ chưa chịu tắt — KHÔNG bật chồng lên; thử lại sau ít phút")
        return False
    _s("đang bật lại…")
    ok = start_tubecli()
    _s("máy chủ đã chạy lại" if ok else "bật lại KHÔNG thành công — xem log")
    return ok


def _tail_lines(path: str, n: int) -> list:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip() for ln in f.read().splitlines() if ln.strip()][-n:]
    except OSError:
        return []


def supervisor_beat() -> bool:
    """Báo cho TubeCLI biết CLIENT NÀY đang canh nó.

    Nút "Cập nhật" trên cloud kéo code mới rồi cần khởi động lại; node chỉ dám tự
    thoát khi biết chắc có ai dựng nó dậy. Trên Linux đó là systemd — trên Windows
    và macOS thì không có gì cả, nên trước đây bấm Cập nhật xong máy chủ vẫn chạy
    bản cũ trong RAM (người dùng hỏi 9/9/2026).

    Vòng canh dưới đây CHÍNH LÀ thứ dựng nó dậy: 20 giây một lần, thấy cổng chết là
    bật lại. Nhịp tim này chỉ để nói ra điều đó — node hết hạn 90 giây không nghe
    thấy gì thì lại thôi không dám tự thoát nữa.
    """
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/v1/system/supervisor", method="POST",
            data=json.dumps({"by": APP, "pid": os.getpid()}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        # Bản TubeCLI cũ chưa có route này (404) — không sao, chỉ là không có
        # cập nhật một chạm; mọi thứ khác vẫn chạy.
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


def password_problem(new_pw: str, again: str) -> str:
    """Câu báo lỗi cho ô mật khẩu mới, hay "" nếu dùng được — cùng luật với lõi."""
    if len(new_pw or "") < 6:
        return "Mật khẩu phải có ít nhất 6 ký tự."
    if new_pw != again:
        return "Hai lần nhập không khớp."
    if new_pw == "123456":
        return "Không đặt lại đúng mật khẩu mặc định 123456."
    return ""


def _http_detail(e) -> str:
    """Câu lỗi mà máy chủ/cloud gửi kèm một HTTPError, hay "" nếu không đọc được."""
    try:
        body = json.loads(e.read().decode("utf-8", "replace") or "{}")
        return str(body.get("detail") or body.get("error") or "")
    except Exception:
        return ""


def change_node_password(new_pw: str, current: str = "") -> tuple:
    """Đổi mật khẩu dashboard. Trả (ok, câu người đọc được, "api" | "cli").

    Hai đường, thử theo thứ tự:
      1. /api/v1/auth/password với mật khẩu ĐANG DÙNG (Connect nhớ nó từ lúc ghép
         nối). Đổi BÊN TRONG máy chủ nên huỷ luôn mọi phiên đang mở — đúng nghĩa
         "đổi mật khẩu".
      2. `tubecli password --new` khi mật khẩu đã nhớ không còn đúng (đổi ở chỗ
         khác, hoặc quên). Cùng quyền với việc chủ máy mở terminal gõ lệnh ấy —
         Connect chạy trên chính máy đó. Máy chủ đọc lại auth.json ở MỖI lần đăng
         nhập nên mật khẩu mới có hiệu lực ngay; nhưng phiên đang mở nằm trong RAM
         của máy chủ nên còn sống tới lần khởi động lại, và câu trả về nói rõ thế.

    Mật khẩu KHÔNG bao giờ vào log.
    """
    if current:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/v1/auth/password", method="POST",
                data=json.dumps({"current_password": current, "new_password": new_pw}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return True, "Đã đổi mật khẩu.", "api"
        except urllib.error.HTTPError as e:
            if e.code != 401:           # 401 = mật khẩu đã nhớ không còn đúng → đường 2
                return False, _http_detail(e) or f"máy chủ trả HTTP {e.code}", "api"
        except Exception:
            pass                        # máy chủ không trả lời → đường 2 vẫn ghi được tệp

    cmd, d = server_cmd()
    if not cmd:
        return False, "Máy chưa có TubeCLI.", "cli"
    base = list(cmd[:-len(SERVE_ARGS)] if cmd[-len(SERVE_ARGS):] == SERVE_ARGS else cmd)
    # pythonw không có stdout: rich in lời xác nhận vào hư không rồi ngã, và một lần
    # đổi mật khẩu THÀNH CÔNG bị báo là hỏng. python.exe cạnh nó + CREATE_NO_WINDOW
    # thì vẫn không có cửa sổ đen nào hiện ra.
    if base and os.path.basename(base[0]).lower() == "pythonw.exe":
        py = os.path.join(os.path.dirname(base[0]), "python.exe")
        if os.path.isfile(py):
            base[0] = py
    # `--new` nằm trên dòng lệnh trong vài giây lệnh chạy: chấp nhận được trên máy
    # một người dùng, và là đường duy nhất chạy được khi không có console để hỏi.
    try:
        r = subprocess.run(base + ["password", "--new", new_pw], cwd=d or None, env=clean_env(),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, stdin=subprocess.DEVNULL,
                           **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WIN else {}))
    except Exception as e:
        return False, f"Không chạy được lệnh đổi mật khẩu: {e}", "cli"
    if r.returncode != 0:
        tail = " ".join((r.stdout or "").split())[-200:]
        return False, tail or f"lệnh đổi mật khẩu trả mã {r.returncode}", "cli"
    return True, ("Đã đặt mật khẩu mới. Trình duyệt nào đang đăng nhập sẵn vẫn giữ phiên "
                  "tới lần khởi động lại máy chủ."), "cli"


def sync_cloud_password(conf: dict, new_pw: str) -> tuple:
    """Báo cloud mật khẩu mới, để cloud còn đăng nhập hộ được (live view, Flow).

    Không có nó thì cloud vẫn cầm mật khẩu cũ và mọi nút «Open TubeCLI» trên cloud
    hỏng với "TubeCLI login thất bại". Chứng minh danh tính bằng tunnel token — thứ
    chỉ máy này và cloud biết — và cloud tự đăng nhập thử vào máy bằng mật khẩu ấy
    trước khi lưu, nên không ai ghi đè được bằng một mật khẩu sai.
    """
    token = conf.get("tunnel_token") or ""
    if not token:
        return False, "máy chưa ghép nối với cloud"
    req = urllib.request.Request(
        f"{CLOUD}/api/servers/pair/password", method="POST",
        data=json.dumps({"tunnel_token": token, "tubecli_password": new_pw}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        return True, "cloud đã nhận mật khẩu mới"
    except urllib.error.HTTPError as e:
        return False, _http_detail(e) or f"cloud trả HTTP {e.code}"
    except Exception as e:
        return False, f"không gọi được cloud: {e}"


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
    refresh_path_win()          # bản cài từ lượt trước có thể vừa thêm vào PATH
    cmd, d = server_cmd()
    if cmd:
        say("Đã cài sẵn — đang bật TubeCLI…")      # đường dẫn đã có trong log
        if start_tubecli():
            say("TubeCLI đang chạy ✓")
            return True, ""
        # Bật hỏng ở đây gần như luôn là THIẾU PHỤ THUỘC: thư mục có mã nguồn nhưng
        # `pip install -e .` chưa chạy xong. Sửa tại chỗ rồi thử lại, thay vì báo
        # "không bật được" cho một máy chỉ thiếu đúng một lệnh pip.
        if repair_deps(d, say) and start_tubecli():
            say("TubeCLI đang chạy ✓")
            return True, ""
        say("Không bật được TubeCLI — xem log.")
        return False, ""
    say("Máy chưa có TubeCLI — đang cài. Cửa sổ cài đặt sẽ HỎI vài câu.")
    if not install_tubecli(lang=lang):
        say("Trình cài không hoàn tất — xem log.")
        return False, ""
    # PATH của tiến trình này vẫn là bản chụp lúc khởi động: không nạp lại thì
    # `tubecli` vừa cài xong vẫn "không tồn tại" với chính client.
    refresh_path_win()
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
    "iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAFiElEQVR4nLxYfWwURRR/M7t7V1qa0PbuIjEqEBMTjYlG"
    "QwQlof6jBlCuAYOJhkQTUzQGTLkrGBEwBttrkSYYg4qRSmKUxmuhLegfxUZjgJr4AUExRoumfrR3LaWt7fV2dp5vD3of"
    "7fVud3vll1xmdvfNzG9+897bt6dCFqzZMVzmNuJbAFglAkoG7AeJ7AIX2BVu8v4DNxBs+o2q2sgaRGwmUhXZBiDAJwx4"
    "IByq6IMbgAyCVTuGl4HUf7My0CQqpPZKe+OiXphH8IwrQ98HFkE726Rx/Xd/YODYxp2jXpgnJBX07xypYMZkFByA1Byl"
    "X1NbyPsaFBhJBVGPPwYOQbsspYl2+YORc1XBwQ1QQCQJco73wRxBRJcDyBZ/cKDXXzvwEBQAKQUBiqBAoAywhCH7moge"
    "WVcz4oE5IBUkiAY4BKWlM4DsDepkRDQR3awpkxEKpLedBhKHAsBgbEO4wbOLobo+23PG2IuGiF1avz36NNhEQQhyAxab"
    "LYL0zWrEoJz8/Cip2U/BVA0WkUozdAzmTsEJ6GgV4b3L0CJDNKUlXyaf76E30lZ6I53NZVcQBekMy0XRaLFVcokh1yL+"
    "jD8Q/WBjYOCm2exUcABEOM0YnqNl4teuWUy4Sye08cm9GXaAS8xAyTUXzfOsoLdSVSC6l/w4BHMlSGQ2j3J+vIgZ96ZT"
    "gVh0eZxDd7qtPuk+X6zqw0Ria645aRPFwLDeH4isUoXnyZYDbMIxQV1AV7FLf5M4bcln69ZiexGUj+k4t4IFMAZrhRrp"
    "ou7KqXu2fXABaObuSiwZMygFrgyADVCgrvAHo0m3sE1wTAhhOtfUNfljl2S8knqDiWvAdmpqzb40q10p4mATDGS1JYK0"
    "eIeUUEmdb6buqRXlItOGvV+mXumnaZuvT/83SHY+0WOAbkSZtAU4RM3D1PsCclN8YOPLV8vzElSFa3Nbo7db6tpak6gy"
    "hqXte9h4ihxGuTbWTRQ6iMuRGcuQgi0Nvn/DIS9TEBeLYk8N9b9EqW6HPNB5fGmCQy4jQ9M3UfMO04wAtQ+KkkReX43E"
    "5nqGbyrjxkJD4lHXAt4bG5c9pmzJDdAJr60dulWTxkem7K7/ImYaOcm4WJflayMDqCoJ17D9JlF0T3FM6z9Its8B8puR"
    "GS8RkxUIPMzJD4n5KiZZG3A8RQT3qbrSzFT4BWzCVN1sbaeZMTGkaS7aGAJVP/J52uN2Ek0lsZYgsE7a+/30dGHCGDka"
    "LjpQyWyukvJR2wSLFmqaMHQkUgpd7p5amhS9jZoXEofCIFH8mkfsolIHbfKTktU5Jogidgs1PbT47flsKUh+Bq4ug1Qg"
    "558fsa6t0dcNTglyxt4SuvpMxwHPe/lsn6gZvBOZPAYWQWltd2uD7/X0e2kEuYBU/s2FSpeGfVTOXyCFltHZltCwv3Tp"
    "vsesnjNNrSlHxL6jwKpu3e/5dvozR9WMCXrB352WKRYUqUI3LO0vnRhGyUFfbW30vjubTWHqQYBfW+rLr1L7leURCJ8K"
    "dC0P5yBnwrGC6ZhUtMQ3tWHwLYoiL+YxP0F2O4/vr/gJLKAgBN3SuIOas1yVj87mxhT1l+nA9rSGPM1gAymCDOxm07TF"
    "5Ul6E12ioFmR9TnC4bjiCnbWLboCNpGmIApwCNpZGUXzDHKkWj1y7VBbXdllcIgkQYqoPxlzLGImED8DqdW07i/7A+aI"
    "JEHO4XuwmSayoI/krA6HfJ1QIGRIRh/UQ4njsgk6yn4qwOpbG7wHoMCYngcPgx0gDJHoQVX3Lp0PciZm/kcdHKDynq3M"
    "N5BU+zA2oWw7dbBiBOYRM/KgMgaPiBJop3hZnW0ABdPnVEFtOxHy2S5CnWDWsF0fiDxFJB8nqXxUnV4kyx916To933+a"
    "T8f/AAAA//9Fe9JiAAAABklEQVQDAE8bLaMKk8cpAAAAAElFTkSuQmCC"
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


def win_app_id() -> None:
    """Tách nút thanh tác vụ ra khỏi pythonw.exe.

    Windows gộp cửa sổ theo AppUserModelID, và tiến trình này mặc định mang id của
    trình thông dịch — nên dù cửa sổ đã có icon TubeCLI, nút dưới thanh tác vụ vẫn
    là con rắn Python và nằm chung nhóm với mọi script Python khác đang mở.
    PHẢI gọi TRƯỚC khi dựng cửa sổ đầu tiên.
    """
    if not IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TubeCreate.TubeCLI.Connect")
    except Exception as e:
        log(f"không đặt được AppUserModelID: {e}")


# Icon Windows: ICO cổ điển (mục BMP 16/24/32/48), KHÔNG phải ICO nhồi PNG.
# Đo thật 9/9/2026: gói PNG vào ICO thì Tk 8.6 lặng lẽ bỏ qua và nút thanh tác vụ
# giữ nguyên icon pythonw.exe — người dùng chụp ảnh hỏi "chưa được". PIL cũng chỉ
# xuất mục PNG, nên tệp này được mã hoá tay lúc dựng.
LOGO_ICO_B64 = (
    "AAABAAQAEBAAAAEAIABoBAAARgAAABgYAAABACAAiAkAAK4EAAAgIAAAAQAgAKgQAAA2DgAAMDAAAAEAIACoJQAA3h4A"
    "ACgAAAAQAAAAIAAAAAEAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/////q6al/zMnJf8eEAz/HA8L/x4QDP8eEAz/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Micl/6unpf//////q6ak/xMFAv8WCQX/EwsI/xwPC/8SCgj/EgoI/x8QDP8e"
    "EAz/HA8L/xwPC/8cDwv/HRAM/xYJBf8TBQL/q6al/zImI/8XCQX/GA8M/4BALf/Ta0r/qlY8/0ckGv8MBwb/FgwJ/yAR"
    "DP8dDwv/HA8L/xwPC/8fEg7/FgkF/zImI/8eEAz/FQwJ/0AhF//1e1X/83pV//d8Vv/weFT/qlU8/zUcFP8MBwb/GQ4K"
    "/yARDP8cDwv/HA8L/x0QDP8cDwv/HxAM/xAJB/9ZLiD/9HpV/+d0UP/odFH/6nZS/8hlRv/lc1D/iUUw/yUUDv8NCAb/"
    "HRAL/x0QC/8cDwv/HA8L/x8QDP8QCQf/WC0g//V7Vv/mdFD/7nhT/95wTv9xOSj/3W9N//+AWf/Wa0v/bDcm/xYMCf8Z"
    "Dgr/HQ8L/xwPC/8fEAz/EAkH/1gtIP/0elX//X9Y/8FhQ/+VTDP/rFc6/5JLMv+3XED//4Na//t+WP+tVz3/HxAM/xsP"
    "C/8dDwv/HxAM/xAJB/9YLSD/8npV/7ldQf+USzT/o1Q3/6FTN/+iUzb/lUs0/7ldQf/hcU7//4BZ/2w3Jv8OCAb/HxEM"
    "/x8QDP8QCQf/WS0g//J6Vf+fUDj/jEcx/7RdPf+dUTf/rVg6/4lGMP+eUDj/33BO//+BWf9yOij/DggG/yARDP8fEAz/"
    "EAkH/1ktIP/zelX//4BZ/7teQv+UTDL/s1s9/5ZNM/+xWT7//4Nb//x+WP+3XED/IxIN/xoOCv8dDwv/HxAM/xAJB/9Y"
    "LSD/9XtW/+Z0UP/rdlL/1GpK/3E5KP/RaUn/+35X/9tuTP93PCr/GQ4K/xgNCv8dEAv/HA8L/yAQDP8QCQf/XC8h//V6"
    "Vv/ndFD/6XVR/+13U/+/YEP/6XVR/45IMv8pFQ//DQgG/xwPC/8dEAv/HA8L/xwPC/8eEAz/FAsJ/0YkGf/4fFb/8XlU"
    "//d8Vv/weVT/rVc9/zgdFP8MBwb/GQ0K/yARDP8cDwv/HA8L/x0QDP8cDwv/MiYj/xcJBf8ZDwz/jEcx/9htTP+qVjz/"
    "SCUa/wwHBv8VCwn/IBEM/x0QC/8cDwv/HA8L/x8SDv8WCQX/MiYj/6ynpf8TBgL/FQkF/xQLCf8fEQz/EgoH/xIKCP8f"
    "EAz/HhAM/xwPC/8cDwv/HA8L/x0QDP8WCQX/EwUC/6ynpv//////qaSj/zInJf8eEAz/Gw8L/x4QDP8eEAz/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwz/Micl/6qlo///////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgAAAAYAAAAMAAAAAEAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD8/Pz/"
    "/////8jFxP9WTEr/JBgV/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/JBgV/1ZMSv/IxcT///////z8/P//////pqGf/xcKCP8SBQH/Gw4K/x8QDP8dDwv/HRAL/x8RDP8dDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gw4K/xIFAf8XCgj/pqGf///////IxMT/FQgE/xkLCP8gEw7/HA8L"
    "/w8JB/8XDAn/FQsJ/w0IBv8aDgr/HxEM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8SDv8ZCwj/"
    "FQgE/8jFxP9WTEn/EgUB/yATD/8cDwv/FwwJ/3k+K//EYkX/ul1B/3U7Kv8iEg3/DggG/x0PC/8fEAz/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8fEw//EgUB/1ZMSf8kGBT/Gw4K/x8RDP8PCQf/dDsp//+BWv/zelX/9XtV//p+"
    "V//SaUn/ajUl/xcMCf8QCQf/HhAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gw4K/yUYFP8cDwv/HA8L"
    "/x0PC/8XDAn/w2JE//N6Vf/mdFD/6XVR/+d0Uf/xeVT/+n1X/8RjRf9SKh3/EQoH/xQLCP8fEQz/HRAL/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8hEg3/0WlJ//F5VP/qdVL/63ZS/+t2Uv/qdlL/5HNQ/+p1Uv/1"
    "e1b/rVc9/0AhF/8NCAb/GA0K/yARDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8iEg3/0mpK//F5"
    "VP/qdVL/63ZS/+d0Uf/3fFb/rFc8/0MiGP/sdlL/9nxW/+t2Uv+WTDX/LBcQ/w0HBv8cDwv/HhAM/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HQ8L/xoOCv8iEg3/02pK//F5VP/qdVL/6nZS//B5VP/0elX/y2ZH/4NCLv/0elX/7XdT/+53U//6fVf/"
    "33BO/3c8Kv8YDQr/FwwJ/x4QDP8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8iEg3/02pK//F5VP/lc1D/8XlU/7NaP/9z"
    "Oyj/eT4q/2s2Jf99QCz/fD8r/99wTv/ndFH/7HdS//t+WP+/YEP/LhgR/xcMCf8dEAv/HA8L/xwPC/8cDwv/HQ8L/xoO"
    "Cv8iEg3/02pK//B5VP/0e1b//4Jb/39ALf+2XT3/63hO/9lvSf/eckr/gkIs/7teQv//hFz/7nhT/+RzUP/+f1n/uV1B"
    "/xcMCf8dDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8iEg3/0mpK//V7Vv+XTDX/sVk+/3s+K/+pVzn/ekAs/39CLP+YTjP/"
    "j0kw/55POP+bTjb/xGNE//J5VP/odFH/7XdT/z4gF/8UCwj/HhAM/xwPC/8cDwv/HQ8L/xoOCv8iEg3/0mpJ//d8Vv9n"
    "NSX/hEMv/2U0JP/Xbkf/ZTYn/5VNNP+bTzT/ikcv/4FBLv9iMiP/rFc8//Z8Vv/mdFH/73hT/0MiGP8TCwj/HhAM/xwP"
    "C/8cDwv/HQ8L/xoOCv8iEg3/02pK//F5VP/yeVX//4Nb/39ALf/VbUf/3HBJ/+FzS//pd07/jUgw/7peQf//hFv/7ndT"
    "/+RzUP/7flf/xmRG/xsPC/8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8iEg3/02pK//F5VP/mc1D/83pV/6FROf9qNyX/"
    "g0Mt/3Y8Kf+FRC3/bzgn/9RrSv/qdVL/6nZR//x+WP/MZ0f/OB0V/xUMCf8eEAz/HA8L/xwPC/8cDwv/HQ8L/xoOCv8i"
    "Eg3/02pK//F5VP/qdVL/63ZS/+54U//hcU//vmBD/4NCL//eb03/4HBO/+94U//4fVf/53RR/4ZEL/8fEAz/FQsI/x4Q"
    "DP8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8iEg3/02pK//F5VP/qdVL/63ZS/+h0Uf/8flj/r1k9/0AhF//yeVT/+H1X"
    "/+53U/+eUDf/NhwU/w0HBv8bDgv/HhAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HQ8L/xoOCv8kEw7/1WtK//B5VP/qdVL/"
    "63ZS/+t2Uv/rdlL/3W9N/9hsS//2fFb/s1o//0UjGf8OCAb/FgwJ/yARDP8dDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8bDgv/ymZH//F5VP/ndFH/6XVR/+d0Uf/weVT//H5Y/8tmR/9YLR//EwoI/xMKCP8fEQz/HhAM/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8kGBT/Gw4K/x8RDP8OCAb/gEEt//+CWv/weFT/9XtV//p+V//Takr/bDcm"
    "/xgNCv8QCQf/HhAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gw4K/yUYFP9VTEn/EgQB/yATD/8bDgr/"
    "HA8L/4xHMf/OZ0j/u15C/3Y8Kv8iEg3/DQgG/xwPC/8fEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8f"
    "Ew//EgQB/1VMSf/IxcX/FgkF/xkMCP8gEw//Gw8L/xAJB/8cDwv/FgwJ/w0IBv8aDgr/HxEM/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8SDv8ZDAj/FgkF/8nGxf//////pqGf/xUJB/8SBQH/Gw4K/x8QDP8cDwv/HRAL"
    "/x8RDP8dDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gw4K/xIFAf8VCQf/pqGf///////8/Pz/"
    "/////8XCwP9VS0n/JBgV/xwPC/8dEAv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/JBgV/1VMSv/FwsH///////z8/P8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAoAAAAIAAAAEAAAAABACAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAA//////z8/P//////5ePj/312dP85Liv/HxMP/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8TD/85LSv/fXZ0/+Xj4v//"
    "/////Pz8///////8/Pz//////7Gtq/8pHRv/DwEA/xcKBv8bDgr/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gw4K/xcKBv8PAQD/KR0b/7Ktq////////Pz8"
    "//////+vqqn/DAAA/xcKBv8gEw//HRAM/xwPC/8fEAz/HhAM/x0QC/8fEQz/HhAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HRAM/yATD/8XCgb/DAAA/7Crqv//////4+Lh/ycbF/8X"
    "Cgf/HxIO/xwPC/8cDwv/HQ8L/w8JB/8SCgf/FQsJ/w4IBv8TCwj/HxAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8SDv8XCgf/JxsX/+Ti4f99dnP/DwEA/yATD/8cDwv/HA8L"
    "/xwPC/8WDAn/bTcn/7JaP/+6XUH/kkkz/0MiGP8PCQf/FQwJ/yARDP8dEAv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/yATD/8PAQD/fnZ0/zgtKf8XCgb/HRAM/xwPC/8eEAz/EgoI/45IMv//"
    "gFn/9ntW//V7Vf/6fVf/73hT/6JSOf84HRX/DQgG/xgNCv8gEQz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HRAM/xcKBv84LSr/IBMP/xwOCv8cDwv/HhAM/xQLCP9DIhj/83pV/+l1Uf/odFH/6XVR"
    "/+d0Uf/qdlL/+X1X/+l1Uf+PSDL/KRUP/w0HBv8bDwv/HxEM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA4K/yATD/8cDwv/HA8L/xwPC/8fEQz/DQgG/3g9K//5fVf/53RR/+t2Uv/rdlL/63ZS/+t2Uv/o"
    "dFH/7HdS//h8Vv/abUz/djwq/x0QC/8PCQb/HhAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8NCAb/jkgy//p9V//odFH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/qdlL/8npV"
    "//t+V//6flf/zWdH/2EyI/8UCwj/EgoI/x8QDP8eEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HxEM/w4IBv+RSTP/+n1X/+h0Uf/rdlL/63ZS/+t2Uv/rdlL/6XVR//N6Vf+DQi7/djwq/+13U//y"
    "eVT/+HxW/7ldQf9KJhv/DwkH/xYMCf8gEQz/HQ8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8fEQz/DggG/5FJM//6fVf/6HRR/+t2Uv/rdlL/63ZS/+l1Uf/ndFH/9HtV/1UsHv9BIhj/8HlU/+VzUP/mc1D/9ntW"
    "//J5VP+hUTj/MhoT/w0HBv8bDwv/HhAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8OCAb/"
    "kkkz//p9V//odFH/63ZS/+t2Uv/qdVL/83pV//V7Vf//g1v/s1o//6hUO///hVz/9nxW//V7Vf/ndFH/6nVS//l9V//l"
    "c1D/gUEu/xsPC/8UCwj/HxAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HxEM/w4IBv+SSTP/+n1X/+h0"
    "Uf/rdlL/6XVR//N6Vf+4XUH/XTAh/2o2Jv9OJxz/SSUa/2g1Jf9fMSL/rlc9//N6Vf/pdVH/6HRR/+13U//6flf/ymVG"
    "/z0gFv8SCgj/HxAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8fEQz/DggG/5JJM//6fVf/6HRR/+l1Uf/ndFH/"
    "8XlU/1YsH/+mVTj/0GpF/8RkQv/NaUX/yGdD/65ZOv9LJxv/6HRR/+l1Uf/pdVH/6nZS/+Z0UP/3fFb/33BO/zQbE/8W"
    "DAn/HRAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8OCAb/kkkz//p9V//odFH/9nxW//p9V//4fFb/XzAi/8to"
    "RP/BY0H/9HxR/7tgP/+9YD//3nFK/1ouIP/rdlL/+35Y//h8Vv/rdlL/63ZS/+VzUP/8flj/nE83/w4IBv8fEQz/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HxEM/w4IBv+SSjP/+HxW//B4VP+RSTP/fT8s/8NiRf9MJxv/z2pF/14xIf9oOCj/"
    "dDwo/3I7J/+/YkD/Viwe/8BgQ/+IRDD/h0Qw//F5VP/qdlL/6XVR//F5VP/LZkf/HQ8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8fEQz/DggG/5JKM//4fFb/8nlU/1YsH/8zGxP/iEUw/zoeFf/kdUz/qVc6/z4lHv/GZUL/dTwo/8Rk"
    "Qv9LJhr/hUMv/0EhF/9FIxn/8XlU/+p2Uv/pdVH/8HlU/9BoSf8gEQz/Gw4L/x0PC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/x8RDP8OCAb/kkoz//p9V//qdVL/6HVR/+p2Uv//gFn/XS8h/9huSP/ecUr/czsm/+96UP+aTzT/0GpG/1wvIP/ueFP/"
    "73hT/+Z0Uf/td1P/63ZS/+Z0UP/5fVf/q1Y8/xAJB/8eEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HxEM/w4IBv+S"
    "SjP/+n1X/+h0Uf/sd1L/63ZS/+13U/9TKx7/xWVC/+t4T//velD/5HRM/+x5T//ab0n/TCcb/+BxT//ud1P/7HdT/+p2"
    "Uv/ndFH/8nlV/+13U/9DIhj/FAsI/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8fEQz/DggG/5JKM//6fVf/6HRR"
    "/+p2Uv/odVH/9XtV/5dMNf9MJxv/Wy4g/0wnG/9MJxv/XC8g/1EqHf+JRTD/83pV/+l1Uf/ndFH/6nZS//p+V//ZbUz/"
    "TScc/xIKB/8eEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8OCAb/kkoz//p9V//odFH/63ZS/+t2Uv/r"
    "dlL/83pV/+JxT//td1P/p1Q7/5xPN//vd1P/3nBO//N6Vf/pdVH/6XVR//d8Vv/ud1P/lks1/ycUD/8RCgf/HxAM/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HxEM/w4IBv+SSjP/+n1X/+h0Uf/rdlL/63ZS/+t2Uv/pdVH/63ZS"
    "//t+V/9rNib/WS4g//h9V//rdlL/5nRQ//R7Vf/0e1X/slk+/0MiGf8NCAb/GQ0K/x8QDP8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8fEQz/DggG/5NKNP/5fVf/6HRR/+t2Uv/rdlL/63ZS/+t2Uv/pdVH/9HtV/2g1Jf9Y"
    "LR//7XdT//B4VP/5fVf/wWFE/1MqHv8SCgf/EwsI/x8RDP8dEAv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/x8RDP8OCAb/lks1//l9V//odFH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/7XdT//R6Vf/8flj/02pK"
    "/2k1Jf8XDQn/EAkH/x4QDP8eEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HxEM/w0IBv+GRC//+n1X/+h0Uf/rdlL/63ZS/+t2Uv/rdlL/6HRR/+t2Uv/5fVf/33BO/3w/LP8hEg3/DggG/x0PC/8f"
    "EAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8gEw//Gw4K/xwPC/8eEAz/EgoI/00n"
    "HP/2e1b/53RR/+l1Uf/pdVH/53RR/+p2Uv/5fVf/6nVS/5NKNP8sFxH/DQgG/xoOCv8fEQz/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDgr/IBMQ/zgtKf8XCgb/HRAM/xwPC/8dEAz/FAsI/6VTOv//gVr/"
    "8npV//R6Vf/6fVf/73hT/6RTOv87Hhb/DQgG/xgNCv8gEQz/HQ8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HRAM/xcKBv84LSn/fXZz/w8BAP8gEw//HA8L/x0PC/8aDgr/HhAM/4VDL//DYkT/v2BD/5NK"
    "NP9EIxn/DwkH/xULCf8fEQz/HRAL/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8gEw//DwEA/312c//k4+L/KBwY/xcKB/8fEg7/HA8L/x0PC/8bDgv/DggG/xgNCf8XDQn/DQgG/xMLCP8fEAz/"
    "HhAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HxIO/xcKB/8o"
    "HBj/5ePj//////+xraz/DAAA/xcKB/8gEw//HRAM/x0PC/8fEQz/HQ8L/x0PC/8fEQz/HhAM/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HRAM/yATD/8XCgf/DAAA/7KurP///////Pz8"
    "//////+vqqj/JxsY/w8BAP8XCgb/Gw4K/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xsOCv8XCgb/DwIA/ycbGP+vqqn///////z8/P///////Pz8///////h"
    "39//e3Ry/zktK/8fEw//HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HxMP/zkuK/98dHP/4uDf///////8/Pz//////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKAAAADAAAABgAAAAAQAgAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAP////////////////z8/P///////////8nGxf96cnH/PjMx/yUZFf8dEAz/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8dEAz/JRkV/z4zMf96cnH/ycbF/////////////Pz8////////////////////////////"
    "/Pz8///////e3Nz/Y1pY/xoNCf8QAgD/FgkF/xoNCf8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/Gg0J/xYJBf8QAgD/Gg0J/2NaWP/e3Nz///////z8/P/////////////////8/Pz//////7ezsf8hFRL/DAAA"
    "/x0QC/8fEg7/HRAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0QDP8f"
    "Eg7/HRAL/wwAAP8iFRP/uLSy///////8/Pz///////z8/P//////s66s/xMGA/8YCwf/IBQQ/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/yAUEP8YCwf/"
    "EwYD/7Svrv///////Pz8//7+/v/c2tn/HREO/xkMCP8fEg7/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HhAM/x8RDP8f"
    "EAz/HxAM/x8RDP8dEAv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8fEg7/GQwI/x4RD//c2tn//v7+"
    "//////9fVlP/DQAA/yAUEP8cDwv/HA8L/xwPC/8cDwv/HA8L/x0PC/8eEAz/EgoH/w0HBv8QCQf/DwgH/w0IBv8WDAn/"
    "HxAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/IBQQ/w0AAP9fVlP//////8vIx/8ZDAj/HRAL/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HRAL/xsPC/8SCgj/Tygc/4tGMf+lUzr/oFA4/3U7Kf81GxP/DwgH/xULCP8fEQz/HRAL"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0QC/8ZDAj/zMjI/3dvbf8QAgD/HxIO/xwPC/8cDwv/HA8L/xwPC/8d"
    "Dwv/Gw8L/xgNCv+XTDX/9nxW//p9V//4fFb/+H1X//p9V//mdFD/n1A4/zsfFv8NCAb/GA0K/yARDP8dDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/x8SDv8QAgD/eHBu/z80Mf8WCQT/HRAM/xwPC/8cDwv/HA8L/xwPC/8fEAz/EAkH/49IMv//gFn/"
    "6HRR/+d0Uf/odVH/6HRR/+h0Uf/sd1P/+X1X/+p1Uf+PSDL/LRcR/w0HBv8aDgr/HxEM/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0Q"
    "DP8WCQT/PzQx/yUZFf8aDQn/HA8L/xwPC/8cDwv/HA8L/x4QDP8UCwj/QiIY//B5VP/qdVL/6nZS/+t2Uv/rdlL/63ZS"
    "/+t2Uv/qdlL/6HRR/+x2Uv/6flf/4HFO/39ALf8gEQz/DggG/x0QC/8fEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8aDQn/JRkV/x0QDP8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8NCAb/hEMv//p9V//ndFH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+p2"
    "Uv/ndFH/7nhT//p+V//RaUn/ZDMk/xYMCf8RCgf/HxAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HRAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/x4QDP8RCgf/rVc9//d8Vv/odVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6nZS/+d0Uf/w"
    "eVT/+HxW/71fQv9PKBz/EAkH/xQLCP8fEQz/HRAL/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0PC/8YDQr/wGBD"
    "//R6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/veFP/6HRR//V7Vf/zelT/"
    "qlU8/z8gF/8NCAb/GA0K/yARDP8dDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/xmRF//N6Vf/pdVH/63ZS/+t2"
    "Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/7HZS/+94U//Ua0r/7ndT/+p2Uv/pdVH/+HxW/+x2Uv+TSjT/LBcQ"
    "/w0HBv8bDgv/HxEM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/xmRF//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/r"
    "dlL/63ZS/+t2Uv/pdVH/9nxW/4pGMf8RCQf/dDsp//N6Vf/pdVL/6HRR/+t2Uv/6flf/3W9N/3k9Kv8gEQz/DwkH/x4Q"
    "DP8eEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8bDwv/x2RF//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/odVH/"
    "93xW/2QzJP8AAQH/SiYa//B4VP/qdVL/63ZS/+t2Uv/ndFH/73hT//p+V//PaEj/XjAi/xIKCP8TCwj/HxEM/x0PC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8bDwv/x2RF//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6nVR/+h0Uf/ndFH/7HdS/9ptTP8zGhL/wmJE"
    "//F5VP/mc1H/53RR/+l1Uf/rdlL/6nVS/+d0Uf/yelT/93xW/7JaPv9FIxn/DggG/xkOCv8fEQz/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/x2RF//N6Vf/p"
    "dVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/qdVL/8XlU//1/WP/8f1j//oBZ//d8Vv9QKR3/6XVR//+CWv/8flj//X9Y//N6"
    "Vf/qdVL/63ZS/+t2Uv/pdVH/6HVR//Z8Vv/weFT/lEs0/yUTDv8PCQf/HxAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/x2RF//N6Vf/pdVH/63ZS/+t2Uv/rdlL/"
    "63ZS/+p1Uv/xeVT/0GhJ/3o9K/9yOin/fD4s/3M6Kf8iEg3/bzgn/30/LP96Piv/gEEt/8NiRP/zelX/6XVR/+t2Uv/r"
    "dlL/63ZS/+h1Uf/qdlL/+n1X/9dsS/9aLiD/EAkH/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/x2RF//N6Vf/pdVH/63ZS/+t2Uv/rdlL/6nZS/+13U//kc1D/NhwU"
    "/0IjF/9bLx//Viwd/1guHv9jMyL/VCsd/0wnGv9PKRv/RSQY/ycUD//RaUn/8XlU/+l1Uf/rdlL/63ZS/+t2Uv/rdlL/"
    "53RR//F5VP/4fFb/cDko/w8IBv8fEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/x2RF//N6Vf/pdVH/63ZS/+t2Uv/qdlL/6XVR//R7Vf/CYkT/JBMN/+V1Tf//hVb/+4BU//Z+"
    "Uv/3flP//4JV//2BVf/+gVX/935T/y4YEP+eTzf/+n1X/+h1Uf/qdlL/63ZS/+t2Uv/rdlL/63ZS/+l1Uf/qdlL/9ntW"
    "/1csH/8RCgf/HxAM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8bDwv/"
    "x2RF//N6Vf/pdVH/63ZS/+p1Uv/td1P/6HRQ//N6VP+9X0L/JhQO/9twSf/PakX/2G9J//N9Uv/ldU3/yWdD/9FrRv/R"
    "a0b/7XlP/zIaEv+cTjf/+HxW/+Z0UP/td1P/6nVS/+t2Uv/rdlL/63ZS/+t2Uv/odFH/9XtV/8RiRP8ZDQr/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RF//N6Vf/pdVH/63ZS"
    "//J5VP/ick//8XlU//+CWv/GZEX/IRIN/+x4T/+BQiz/Viwe/9hxSf+FRC3/ZTQj/39BK/9vOSb//4JV/y8ZEf+lUzr/"
    "/4Nb//J6VP/ick//8nlU/+x2Uv/rdlL/63ZS/+t2Uv/rdlL/6nVS/+54U/9EIxj/EwsI/x4QDP8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6Vf/ndFD/9XtW/51PN/8lEw7/ez4r/8Rj"
    "Rf+PSDL/JBMN/+JzTP/TbEf/JRQO/2s7LP8lFBD/t109/4JCLP9vOSb//4JV/zMbEv+AQS3/zGhJ/4tGMf8mFA7/iEQw"
    "//N6Vf/pdVH/63ZS/+t2Uv/rdlL/6HVR//d8Vv9kMyP/DwgG/x8QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6Vf/mdFH/+H1W/1ouIP8AAAD/IxIN/1EpHf84HRX/KBUP/9lvSf/6"
    "gFT/YzMi/5pYQ/9VLSD/8HpP/3k+Kf9zOyf//oFV/zsfFf8vGRH/Wi8h/y4YEf8AAAD/PyAX//F5VP/qdVL/63ZS/+t2"
    "Uv/rdlL/6HVR//h8Vv9pNib/DggG/x8RDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/x2RG//N6Vf/odFH/8HlU/9BpSf95PSv/x2RF//+DW//AYEP/JRQO/9lvSf/5f1P/rlk7/wYEBf95Pin/"
    "/4hZ/2g2JP9pNiT//4RW/zEaEv+WSzX//4Vc/9JpSf95PSv/xmNF//J5VP/qdVH/63ZS/+t2Uv/rdlL/6XVR//R6Vf9S"
    "Kh3/EQkH/x8QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6"
    "Vf/pdVH/6nZS//B5VP/8flj/73hT//J6VP+/YEP/JxQO/9lvSf/seE//4XNL/3k+Kf/JZ0T/8n1S/6dVOP+nVTj/9X5S"
    "/zQbE/+WTDX/+H1W/+12U//7flj/8nlU/+p1Uv/rdlL/63ZS/+t2Uv/pdVH/8HhU/9dsS/8kEw3/Gg4K/x0PC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6Vf/pdVH/63ZS/+p1Uv/n"
    "dFH/53RQ//R7Vf/AYUP/KhYQ/+p3T//7gFT/939T//+GWP/6gFT/9n1S//+CVf/+glX/+4BU/zoeFP+YTTX/+n5X/+d0"
    "Uf/ndFH/6XVR/+t2Uv/rdlL/63ZS/+p1Uv/ndFH//oBZ/3I6KP8PCAb/HxEM/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6Vf/pdVH/63ZS/+t2Uv/rdlL/6nVR//F5VP/Uakr/"
    "HhAM/4dFLv+mVTj/n1I2/51RNf+lVTj/oVM2/6BSNv+qVzn/oFI2/xsPC/+2XED/9ntW/+l1Uf/rdlL/63ZS/+t2Uv/r"
    "dlL/6HRR/+x3Uv/7flj/lEs0/xULCf8dDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/x2RG//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+l1Uv/yelX/l0w1/zUbFP80GhP/MxoT"
    "/zUbFP8aDgv/MRkS/zUbE/83HBT/MxoT/4FBLv/veFP/6nZS/+t2Uv/rdlL/63ZS/+l1Uf/odVH/93xW/+p1Uf92PCr/"
    "EQkH/xwPC/8dDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/x2RG//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/9ntW//N6Vf/ud1P/73hU/+t2Uv9QKR3/2W1M//J6"
    "Vf/sd1P/8HhU//d8Vv/sdlL/63ZS/+t2Uv/qdVL/53RR//J6VP/3fFb/s1o//zwfFv8OBwb/HhAM/x0PC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/yGRG//N6Vf/pdVH/"
    "63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6XVR/+p2Uv/rdlL/7nhT/+h0Uf8/IBf/1mxL//J6Vf/qdlL/63ZS/+h1Uf/r"
    "dlL/6nZS/+d0Uf/veFP/+n5X/85nSP9fMCL/EwsI/xQLCP8gEQz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/yGRG//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS"
    "/+t2Uv/rdlL/63ZS/+t2Uv/odFH/9ntW/4NCLv8KBgX/ajUl//J6Vf/pdVH/63ZS/+t2Uv/odFH/7XdT//p+V//bbkz/"
    "fD4s/x8RDP8PCAb/HhAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/yGVG//N6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2"
    "Uv/odVH/93xW/2w3Jv8AAAD/Uiod//J5VP/qdVL/6HVR/+p1Uv/5fVf/5XNQ/4lFMP8oFQ//DQcG/xsOC/8fEQz/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xsPC/8eEAz/zGZH//J6VP/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/qdlL/7ndT/+NyT/+k"
    "Ujr/3G5N/+13U//ndFH/9ntW//B4VP+gUTj/NhwU/w0HBv8ZDQr/IBEM/x0PC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xsPC/8dEAv/ymVH"
    "//J6Vf/pdVH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6nZS/+13U//3fFb/63ZS//N6Vf/2fFb/"
    "t1xA/0glGv8OCAb/FgwJ/yARDP8dEAv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0PC/8YDQr/wGFD//R7Vf/pdVH/63ZS/+t2"
    "Uv/rdlL/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6nZS/+d0UP/ud1P/+X1X/8VjRf9ZLSD/FAsI/xIKCP8fEQz/HhAM"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/x0QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/x8RDP8OCAb/l0w1//l9V//odFH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/r"
    "dlL/63ZS/+t2Uv/ndFH/7ndT//t+V//Ua0r/bzgn/xoOCv8PCQf/HhAM/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HRAM/yYZFf8aDQn/HA8L"
    "/xwPC/8cDwv/HA8L/x4QDP8SCgf/UCkc//V7Vf/odFH/63ZS/+t2Uv/rdlL/63ZS/+t2Uv/rdlL/6HRR/+t2Uv/6fVf/"
    "4XFP/4ZDL/8jEw7/DQgG/xwPC/8fEQz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8aDQn/JhoW/z80Mf8WCQT/HRAM/xwPC/8cDwv/HA8L/xwP"
    "C/8eEAz/EwsI/65XPf/+f1n/5XNQ/+h1Uf/pdVH/6HVR/+h0Uf/sd1L/+X1X/+t2Uv+VSzT/LxgS/w0HBv8aDgr/IBEM"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/x0QDP8WCQT/PzQx/3ZubP8QAwD/HxIO/xwPC/8cDwv/HA8L/xwPC/8dEAv/GA0K/ykWD/++"
    "YEL//H9Y//d8Vv/1e1b/+HxW//p9V//odVH/n1A4/zwfFv8OCAb/FwwJ/yARDP8dDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/x8SDv8QAgD/dm5s/8vIx/8ZDAj/HRAL/xwPC/8cDwv/HA8L/xwPC/8cDwv/HhAM/xcMCf8cDwv/bjgn/6pWPP+4XED/"
    "pVM5/3Y8Kv84HRX/DwgH/xQLCP8fEQz/HRAL/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0QC/8ZDAj/zMnI////"
    "//9hWFX/DQAA/yAUEP8cDwv/HA8L/xwPC/8cDwv/HA8L/x4QDP8bDwv/DggG/xEJB/8VCwn/EAkH/w0IBv8WDAn/HxAM"
    "/x4QDP8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/IBQQ/w0AAP9iWVb///////7+/v/e3Nv/HxMQ/xgLCP8f"
    "Eg7/HA8L/xwPC/8cDwv/HA8L/xwPC/8dDwv/HxEM/x4QDP8dEAv/HxAM/x8RDP8eEAz/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8fEg7/GAsI/x8TEf/e3dz//v7+//z8/P//////t7Kx/xMGA/8ZCwj/IBMP/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/yAU"
    "D/8YCwj/EwYD/7ezsv///////Pz8///////8/Pz//////7Ovrf8fEhD/DQAA/x0QDP8fEg7/HRAM/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/"
    "HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/x0QDP8fEg7/HRAM/w0AAP8fEhD/tK+u///////8"
    "/Pz//////////////////Pz8///////a2Nj/W1JQ/xkMCf8QAwD/FgkE/xoNCf8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L"
    "/xwPC/8cDwv/HA8L/xwPC/8cDwv/Gg0J/xYJBP8QAwD/GQwJ/1xTUf/b2dj///////z8/P//////////////////////"
    "//////z8/P///////////8fDw/95cnD/PjMx/yUYFf8dEAz/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8c"
    "Dwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwPC/8cDwv/HA8L/xwP"
    "C/8dEAz/JRkV/z8zMf96cnH/x8TD/////////////Pz8/////////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAA=="
)


def _ico_path() -> str:
    """Ghi tệp .ico ra đĩa và trả đường dẫn (hay ""). Windows lấy icon thanh tác vụ
    từ .ico chứ không từ iconphoto, và Tk chỉ nhận đường dẫn tệp."""
    if not IS_WIN:
        return ""
    try:
        import base64
        path = os.path.join(HOME, "tubecli.ico")
        os.makedirs(HOME, exist_ok=True)
        data = base64.b64decode(LOGO_ICO_B64)
        if not (os.path.isfile(path) and os.path.getsize(path) == len(data)):
            with open(path, "wb") as f:
                f.write(data)
        return path
    except Exception as e:
        log(f"không dựng được .ico: {e}")
        return ""


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
    ico = _ico_path()
    if not ico:
        return
    try:
        root.iconbitmap(default=ico)
    except Exception:
        pass
    # `iconphoto`/`iconbitmap` của Tk chỉ đặt được icon NHỎ (thanh tiêu đề); nút
    # trên thanh tác vụ đọc icon LỚN, nên nó giữ nguyên icon của pythonw.exe.
    # Đo thật 9/9/2026: tiêu đề đã ra logo TubeCLI mà thanh tác vụ vẫn là con rắn.
    # Nạp HICON từ chính tệp .ico rồi gửi WM_SETICON cho cả hai cỡ.
    try:
        import ctypes
        root.update_idletasks()            # phải có HWND thật rồi mới gửi được
        hwnd = int(root.wm_frame(), 16)
        u32 = ctypes.windll.user32
        WM_SETICON, IMAGE_ICON, LR_LOADFROMFILE = 0x0080, 1, 0x0010
        for size, which in ((32, 1), (16, 0)):          # ICON_BIG = 1, ICON_SMALL = 0
            h = u32.LoadImageW(None, ico, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if h:
                u32.SendMessageW(hwnd, WM_SETICON, which, h)
    except Exception as e:
        log(f"không đặt được icon thanh tác vụ: {e}")


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
                # VẪN mở nút: có thể máy chủ đang chạy mà client dò trượt, và một
                # cái nút mờ vĩnh viễn thì không chừa cho người dùng đường nào.
                # Bấm mà thật sự chưa chạy thì connect() nói rõ lý do.
                btn.state(["!disabled"])
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
        # Người dùng CHỦ ĐỘNG ngắt thì vòng canh phải im. Không có cờ này thì
        # bấm «Ngắt kết nối» xong 20 giây sau vòng canh dựng lại tất cả, và
        # trông như nút bị hỏng.
        self.paused = threading.Event()
        self.busy = ""
        self.miss = 0

    def status(self) -> str:
        if self.busy:
            return self.busy
        if self.paused.is_set():
            return "ĐÃ NGẮT KẾT NỐI — bấm «Kết nối lại» để bật lại"
        node = "đang chạy" if tubecli_up() else "TẮT"
        tun = "đang chạy" if (self.tunnel and self.tunnel.poll() is None) else "TẮT"
        return f"TubeCLI: {node} · Tunnel: {tun} · {self.conf.get('url', '')}"

    def watch(self) -> None:
        while not self.stop.is_set():
            try:
                if self.paused.is_set() or self.busy:
                    self.stop.wait(2)
                    continue
                if not tubecli_up():
                    # MỘT lượt dò trượt KHÔNG có nghĩa là máy chủ chết. Lúc đang
                    # dựng video nó bận tới mức /health mất ~40 giây (đo thật
                    # 10/9/2026), mà `tubecli_up` chỉ chờ 2 giây. Bật lại ngay là
                    # đẻ ra một máy chủ ma: nó không bind được cổng nên tự thoát,
                    # nhưng trước khi thoát đã kịp nạp toàn bộ extension — càng
                    # làm máy chủ thật đói thêm, và cứ 70 giây lại một lần.
                    self.miss += 1
                    # AI ĐANG GIỮ CỔNG mới là câu hỏi đúng. `/health` chờ 2 giây,
                    # nhưng lúc dựng video máy chủ bận tới mức im hàng PHÚT — đo
                    # thật 10/9/2026: /health mất 39,5s, và bộ đếm 3 lượt vẫn
                    # không đủ. Máy chủ BẬN thì vẫn giữ cổng; máy chủ CHẾT thì
                    # nhả. Bật thêm một cái trong lúc cổng còn bị giữ chỉ đẻ ra
                    # máy chủ ma: nó không bind được nên tự thoát, nhưng trước
                    # khi thoát đã nạp xong toàn bộ extension và ăn mất một phần
                    # tài nguyên của chính lượt dựng đang chạy.
                    held = _pid_of_port(PORT)
                    if held:
                        if self.miss in (1, DEAD_AFTER) or self.miss % 15 == 0:
                            log(f"máy chủ chưa trả lời ({self.miss}) nhưng pid {held} "
                                f"vẫn giữ cổng {PORT} — đang bận, KHÔNG bật lại")
                    elif self.miss >= DEAD_AFTER:
                        log(f"máy chủ không trả lời {self.miss} lượt và cổng {PORT} "
                            f"đã trống — bật lại")
                        if start_tubecli():
                            self.miss = 0
                    else:
                        log(f"máy chủ chưa trả lời ({self.miss}/{DEAD_AFTER}) — chờ thêm")
                else:
                    self.miss = 0
                    # Chỉ báo khi máy chủ ĐANG SỐNG: nhịp tim là lời hứa "nếu nó
                    # chết tôi sẽ dựng lại", và vòng ngay trên đây giữ lời hứa đó.
                    supervisor_beat()
                if self.conf.get("tunnel_token") and (self.tunnel is None or self.tunnel.poll() is not None):
                    if self.tunnel is not None:
                        log("cloudflared đã dừng — chạy lại")
                    self.tunnel = start_tunnel(self.conf["tunnel_token"])
            except Exception as e:
                log(f"vòng canh: {e}")
            self.stop.wait(20)

    def shutdown(self) -> None:
        self.stop.set()
        self._kill_tunnel()

    def _kill_tunnel(self) -> None:
        if self.tunnel and self.tunnel.poll() is None:
            try:
                self.tunnel.terminate()
            except Exception:      # noqa: BLE001
                pass
        self.tunnel = None

    def reset(self, say=None) -> None:
        """Khởi động lại máy chủ, GIỮ nguyên tunnel.

        Đây là việc hay cần nhất: cài/cập nhật extension xong, mã Python vẫn nằm
        trong RAM nên máy chủ chạy bản cũ. Tunnel không liên quan nên đừng đụng
        vào — dựng lại nó là địa chỉ công khai chớp tắt vài giây.
        """
        if self.busy:
            return
        self.busy = "đang khởi động lại máy chủ…"
        try:
            node_restart(say)
        finally:
            self.busy = ""

    def disconnect(self, say=None) -> None:
        """Ngắt hẳn: tắt tunnel VÀ máy chủ, rồi im. Máy biến khỏi cloud."""
        if self.busy:
            return
        self.busy = "đang ngắt kết nối…"
        try:
            self.paused.set()
            self._kill_tunnel()
            node_stop()
            log("người dùng ngắt kết nối")
        finally:
            self.busy = ""

    def reconnect(self, say=None) -> None:
        """Bật lại. Vòng canh lo phần còn lại — nó vốn đã biết dựng cả hai."""
        if self.busy:
            return
        self.busy = "đang kết nối lại…"
        try:
            self.paused.clear()
            start_tubecli()
            if self.conf.get("tunnel_token"):
                self.tunnel = start_tunnel(self.conf["tunnel_token"])
            log("người dùng kết nối lại")
        finally:
            self.busy = ""

    def change_password(self, new_pw: str, done=None) -> None:
        """Đổi mật khẩu TubeCLI rồi báo cloud. `done(ok, câu)` chạy ở luồng này."""
        if self.busy:
            if done:
                done(False, "Đang bận việc khác — thử lại sau.")
            return
        self.busy = "đang đổi mật khẩu…"
        ok, msg = False, ""
        try:
            ok, msg, how = change_node_password(new_pw, self.conf.get("password") or "")
            if ok:
                # Nhớ ngay: lần đổi sau đi được đường 1 (đổi trong máy chủ, huỷ phiên).
                self.conf = {**self.conf, "password": new_pw}
                conf_write(self.conf)
                c_ok, c_msg = sync_cloud_password(self.conf, new_pw)
                log(f"đổi mật khẩu TubeCLI ({how}) — cloud: {'đã cập nhật' if c_ok else c_msg}")
                msg += " Cloud đã nhận mật khẩu mới." if c_ok else (
                    f" Nhưng cloud CHƯA nhận ({c_msg}) — bấm đổi lại lần nữa để báo lại.")
            else:
                log(f"đổi mật khẩu TubeCLI hỏng: {msg}")
        finally:
            self.busy = ""
            if done:
                done(ok, msg)

    def reinstall(self, say=None) -> None:
        """Cài lại TubeCLI bằng trình cài CHÍNH THỨC: tắt máy chủ → cài → bật lại.

        `busy` giữ suốt lượt cài (có thể vài phút) để vòng canh không coi cái máy
        chủ đang tắt có chủ ý là "chết" rồi bật chen vào giữa trình cài.
        """
        if self.busy:
            return
        self.busy = "đang cài lại TubeCLI… (vài phút)"
        try:
            log("người dùng bấm «Cài lại»")
            node_stop()
            ok = install_tubecli(lang=self.conf.get("lang", "vi"), reason="Cài lại theo yêu cầu")
            started = start_tubecli()
            msg = ("Đã cài lại xong, TubeCLI đang chạy." if ok and started else
                   "Cài xong nhưng TubeCLI chưa bật lên — xem log." if ok else
                   "Cài lại KHÔNG thành công — xem log.")
            log(msg)
            notify(APP, msg)
        finally:
            self.busy = ""


def tray(bridge: Bridge) -> None:
    """Giao diện nền: cửa sổ trạng thái, và icon khay do chính cửa sổ dựng.

    Khay giờ là `WinTray` viết bằng ctypes, nên nhánh pystray cũ đã BỎ HẲN —
    giữ hai đường làm cùng một việc là cách chắc chắn nhất để chúng lệch nhau,
    và pystray lại kéo theo Pillow trên máy trần.

    Còn đúng một đường lui: máy không có tkinter (Linux server, WSL trần) thì in
    trạng thái ra terminal, vì đó là màn hình duy nhất người dùng có ở đó.
    """
    if has_tk():
        status_window(bridge)
        return
    log("không có tkinter — chạy ở chế độ terminal, Ctrl+C để dừng")
    try:
        while True:
            log(bridge.status())
            time.sleep(60)
    except KeyboardInterrupt:
        log("dừng theo yêu cầu")




# ── Khay hệ thống, viết bằng ctypes ───────────────────────────────────────
# VÌ SAO KHÔNG DÙNG pystray
#   Client phải chạy được trên MÁY TRẦN: người dùng tải một file về, bấm, xong.
#   pystray kéo theo Pillow, và trên máy chưa có pip lành lặn thì cài được hay
#   không là chuyện hên xui — đúng cái đã làm hỏng mấy lần cài đầu tiên. Phần
#   icon thanh tác vụ trong file này vốn đã gọi Win32 qua ctypes, nên khay đi
#   cùng đường ấy là nhất quán và không thêm phụ thuộc nào.
#
# VÌ SAO CÓ CỬA SỔ ẨN RIÊNG VÀ LUỒNG RIÊNG
#   Icon khay gửi sự kiện chuột bằng thông điệp Windows, mà thông điệp thì phải
#   có cửa sổ để nhận và một vòng lặp để bơm. tkinter có vòng lặp riêng và không
#   cho ta chen thông điệp lạ vào, nên khay tự nuôi cửa sổ ẩn + vòng lặp của nó
#   trong một luồng, rồi đẩy hành động sang tkinter qua hàng đợi. Cách khác là
#   thay window proc của tkinter — làm được, nhưng một lỗi nhỏ ở đó là sập cả
#   tiến trình chứ không phải mất cái icon.

TRAY_ITEMS = [
    ("show",       "Hiện cửa sổ"),
    ("dashboard",  "Mở dashboard"),
    ("cloud",      "Mở cloud"),
    ("log",        "Xem log"),
    ("-",          ""),
    ("reset",      "Khởi động lại máy chủ"),
    ("toggle",     "Ngắt kết nối"),
    ("password",   "Đổi mật khẩu TubeCLI…"),
    ("reinstall",  "Cài lại TubeCLI…"),
    ("-",          ""),
    ("quit",       "Thoát hẳn"),
]


class WinTray:
    """Icon khay. `on_action(tên)` được gọi TRONG luồng khay — người gọi tự đẩy
    về luồng giao diện của mình."""

    def __init__(self, on_action, tip: str = APP):
        self.on_action = on_action
        self.tip = tip
        self.hwnd = None
        self._thread = None
        self._alive = False
        self._label = {k: v for k, v in TRAY_ITEMS}

    # -- công khai ---------------------------------------------------------
    def start(self) -> bool:
        if not IS_WIN:
            return False
        try:
            import ctypes
            from ctypes import wintypes      # noqa: F401  (kiểm có sẵn)
        except Exception:      # noqa: BLE001
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        for _ in range(40):                  # chờ cửa sổ ẩn dựng xong
            if self._alive:
                return True
            time.sleep(0.05)
        return self._alive

    def set_label(self, key: str, text: str) -> None:
        """Đổi chữ một mục. Menu dựng lại mỗi lần bấm chuột phải nên chỉ cần
        sửa bảng chữ, không phải sờ vào Win32."""
        self._label[key] = text

    def stop(self) -> None:
        if not self._alive or self.hwnd is None:
            return
        try:
            import ctypes
            ctypes.windll.user32.PostMessageW(self.hwnd, 0x0002, 0, 0)   # WM_DESTROY
        except Exception:      # noqa: BLE001
            pass

    # -- bên trong ---------------------------------------------------------
    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.windll.user32
        shell = ctypes.windll.shell32
        k32 = ctypes.windll.kernel32

        # KHAI KIỂU CHO TỪNG HÀM. Không khai thì ctypes đoán `int` 32 bit, và
        # trên Windows 64 bit chuyện đó hỏng hai kiểu:
        #   · CreateWindowExW trả handle bị CẮT CỤT — máy nào cấp handle nhỏ thì
        #     chạy tốt, máy nào cấp handle lớn thì im lặng sai;
        #   · DefWindowProcW nhận lParam lớn hơn 2^31 và ném OverflowError, mỗi
        #     lần chuột đi qua icon lại một dòng traceback (đo thật 10/9/2026).
        LRESULT = ctypes.c_ssize_t
        u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       ctypes.c_size_t, LRESULT]
        u32.DefWindowProcW.restype = LRESULT
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                        wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                        wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u32.LoadImageW.restype = wintypes.HANDLE
        u32.LoadIconW.restype = wintypes.HICON
        u32.CreatePopupMenu.restype = wintypes.HMENU
        u32.TrackPopupMenu.restype = ctypes.c_int
        u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT]
        k32.GetModuleHandleW.restype = wintypes.HMODULE

        WM_DESTROY, WM_COMMAND, WM_TRAY = 0x0002, 0x0111, 0x0400 + 17
        WM_RBUTTONUP, WM_LBUTTONDBLCLK, WM_LBUTTONUP = 0x0205, 0x0203, 0x0202
        NIM_ADD, NIM_DELETE = 0x0, 0x2
        NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
        MF_STRING, MF_SEPARATOR = 0x0, 0x800
        TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100

        class NOTIFYICONDATA(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                        ("szTip", wintypes.WCHAR * 128)]

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     ctypes.c_size_t, ctypes.c_ssize_t)

        def proc(hwnd, msg, wp, lp):
            if msg == WM_TRAY:
                low = lp & 0xFFFF
                if low == WM_RBUTTONUP:
                    self._popup(hwnd, u32)
                elif low in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                    self._fire("show")
                return 0
            if msg == WM_DESTROY:
                u32.PostQuitMessage(0)
                return 0
            return u32.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc = WNDPROC(proc)           # GIỮ tham chiếu, mất là sập ngay

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        hinst = k32.GetModuleHandleW(None)
        cls = WNDCLASS()
        cls.lpfnWndProc = self._proc
        cls.hInstance = hinst
        cls.lpszClassName = "TubeCliConnectTray"
        try:
            u32.RegisterClassW(ctypes.byref(cls))
        except Exception:      # noqa: BLE001
            return
        hwnd = u32.CreateWindowExW(0, "TubeCliConnectTray", APP, 0,
                                   0, 0, 0, 0, None, None, hinst, None)
        if not hwnd:
            log("khay: không dựng được cửa sổ ẩn")
            return
        self.hwnd = hwnd

        hicon = 0
        try:
            p = _ico_path()
            if p:
                # LR_LOADFROMFILE | LR_DEFAULTSIZE | LR_SHARED
                hicon = u32.LoadImageW(None, p, 1, 0, 0, 0x10 | 0x40 | 0x8000)
        except Exception:      # noqa: BLE001
            hicon = 0
        if not hicon:
            hicon = u32.LoadIconW(None, wintypes.LPCWSTR(32512))       # IDI_APPLICATION

        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = hicon
        nid.szTip = self.tip[:127]
        if not shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            log("khay: Shell_NotifyIconW từ chối")
            return
        self._nid = nid
        self._alive = True
        log("khay hệ thống đã bật")

        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        try:
            shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        except Exception:      # noqa: BLE001
            pass
        self._alive = False

    def _popup(self, hwnd, u32) -> None:
        import ctypes
        MF_STRING, MF_SEPARATOR = 0x0, 0x800
        TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
        menu = u32.CreatePopupMenu()
        ids = {}
        for i, (key, _default) in enumerate(TRAY_ITEMS, start=1):
            if key == "-":
                u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            ids[i] = key
            u32.AppendMenuW(menu, MF_STRING, i, self._label.get(key, key))
        from ctypes import wintypes      # noqa: WPS433 — POINT nằm ở đây
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        # SetForegroundWindow trước TrackPopupMenu: thiếu nó thì menu không tự
        # đóng khi bấm ra ngoài và treo lại giữa màn hình — lỗi kinh điển của
        # menu khay, và nó chỉ lộ ra khi người dùng bấm nhầm chỗ.
        u32.SetForegroundWindow(hwnd)
        cmd = u32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                 pt.x, pt.y, 0, hwnd, None)
        u32.PostMessageW(hwnd, 0x0000, 0, 0)
        u32.DestroyMenu(menu)
        if cmd in ids:
            self._fire(ids[cmd])

    def _fire(self, name: str) -> None:
        try:
            self.on_action(name)
        except Exception as e:      # noqa: BLE001
            log(f"khay: {name} hỏng: {e}")


def status_window(bridge: "Bridge") -> None:
    """Cửa sổ nhỏ luôn nhìn thấy: trạng thái + đúng những nút người ta cần.

    Bấm X là ẨN xuống khay chứ không dừng — muốn dừng thì «Thoát hẳn» trong menu
    khay. Nhưng khi KHÔNG dựng được khay thì X quay lại nghĩa dừng hẳn, vì lúc ấy
    ẩn đi là không còn đường nào mở lại, và tiến trình mồ côi sẽ giữ cổng 5295
    lẫn tunnel mà không ai thấy nó ở đâu.
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

    bar2 = ttk.Frame(frm)
    bar2.grid(column=0, row=4, sticky="w", pady=(6, 0))
    btn_reset = ttk.Button(bar2, text="Khởi động lại")
    btn_reset.grid(column=0, row=0, padx=(0, 6))
    btn_conn = ttk.Button(bar2, text="Ngắt kết nối")
    btn_conn.grid(column=1, row=0, padx=(0, 6))
    btn_hide = ttk.Button(bar2, text="Ẩn")
    btn_hide.grid(column=2, row=0, padx=(0, 6))

    bar3 = ttk.Frame(frm)
    bar3.grid(column=0, row=5, sticky="w", pady=(6, 0))
    btn_pw = ttk.Button(bar3, text="Đổi mật khẩu")
    btn_pw.grid(column=0, row=0, padx=(0, 6))
    btn_reinstall = ttk.Button(bar3, text="Cài lại")
    btn_reinstall.grid(column=1, row=0, padx=(0, 6))

    auto = tk.BooleanVar(value=autostart_on())
    ttk.Checkbutton(frm, text="Khởi động cùng Windows", variable=auto,
                    command=lambda: set_autostart(auto.get())).grid(column=0, row=6, sticky="w", pady=(10, 0))

    tray_box = {"t": None}
    quitting = {"v": False}

    def run_bg(fn):
        """Việc nặng chạy ở LUỒNG KHÁC. Gọi thẳng trong tay bấm là cửa sổ đứng
        hình mấy giây, người dùng bấm tiếp, rồi hai lượt khởi động lại chồng
        nhau. `bridge.busy` chặn lượt thứ hai, `tick` hiện tiến độ."""
        threading.Thread(target=fn, daemon=True).start()

    def do_reset():
        run_bg(bridge.reset)

    def do_toggle():
        run_bg(bridge.reconnect if bridge.paused.is_set() else bridge.disconnect)

    def do_hide():
        """Ẩn xuống khay. KHÔNG có khay thì chỉ thu nhỏ — ẩn hẳn một cửa sổ mà
        không chừa đường quay lại là làm mất luôn client."""
        if tray_box["t"]:
            root.withdraw()
        else:
            root.iconify()

    def do_show():
        root.deiconify()
        root.lift()
        root.focus_force()

    def quit_all():
        quitting["v"] = True
        if tray_box["t"]:
            tray_box["t"].stop()
        bridge.shutdown()
        root.destroy()

    def do_password():
        """Hộp đổi mật khẩu. Không hỏi mật khẩu cũ: Connect chạy trên CHÍNH máy chủ
        nhân, cùng quyền với việc mở terminal gõ `tubecli password`."""
        if bridge.busy:
            return
        do_show()
        dlg = tk.Toplevel(root)
        dlg.title("Đổi mật khẩu TubeCLI")
        dlg.resizable(False, False)
        dlg.transient(root)
        _set_icon(dlg)
        box = ttk.Frame(dlg, padding=14)
        box.grid()
        ttk.Label(box, text="Mật khẩu mới (ít nhất 6 ký tự)").grid(column=0, row=0, sticky="w")
        e1 = ttk.Entry(box, show="•", width=34)
        e1.grid(column=0, row=1, sticky="we", pady=(2, 8))
        ttk.Label(box, text="Nhập lại").grid(column=0, row=2, sticky="w")
        e2 = ttk.Entry(box, show="•", width=34)
        e2.grid(column=0, row=3, sticky="we", pady=(2, 8))
        note = ttk.Label(box, text="Cloud sẽ được báo mật khẩu mới để vẫn mở được TubeCLI hộ bạn.",
                         foreground="#666666", wraplength=300, justify="left")
        note.grid(column=0, row=4, sticky="w", pady=(0, 10))
        row = ttk.Frame(box)
        row.grid(column=0, row=5, sticky="e")
        b_ok = ttk.Button(row, text="Đổi")
        b_ok.grid(column=0, row=0, padx=(0, 6))
        b_cancel = ttk.Button(row, text="Huỷ", command=dlg.destroy)
        b_cancel.grid(column=1, row=0)

        def finish(ok, msg):
            if not dlg.winfo_exists():
                return
            note.config(text=msg, foreground="#15803d" if ok else "#b91c1c")
            b_ok.config(state="normal")
            if ok:
                b_ok.grid_remove()
                b_cancel.config(text="Đóng")

        def submit(_evt=None):
            a, b = e1.get(), e2.get()
            err = password_problem(a, b)
            if err:
                note.config(text=err, foreground="#b91c1c")
                return
            b_ok.config(state="disabled")
            note.config(text="Đang đổi…", foreground="#666666")
            run_bg(lambda: bridge.change_password(
                a, done=lambda ok, msg: root.after(0, finish, ok, msg)))

        b_ok.config(command=submit)
        dlg.bind("<Return>", submit)
        e1.focus_set()

    def do_reinstall():
        """Hỏi rõ trước khi cài lại: máy chủ tắt vài phút và việc đang chạy sẽ dừng."""
        if bridge.busy:
            return
        from tkinter import messagebox
        do_show()
        where = find_install() or "thư mục cài mặc định"
        if not messagebox.askyesno(
                "Cài lại TubeCLI",
                "Cài lại TubeCLI bằng trình cài chính thức?\n\n"
                f"• Thư mục: {where}\n"
                "• Máy chủ tắt trong lúc cài (thường vài phút) — việc đang chạy sẽ dừng.\n"
                "• Dữ liệu (agent, cài đặt, mật khẩu, kho) nằm trong thư mục data, "
                "trình cài không xoá.\n\n"
                "Theo dõi tiến độ bằng «Xem log».", parent=root):
            return
        run_bg(bridge.reinstall)

    btn_reset.config(command=do_reset)
    btn_pw.config(command=do_password)
    btn_reinstall.config(command=do_reinstall)
    btn_conn.config(command=do_toggle)
    btn_hide.config(command=do_hide)

    def tray_action(name):
        """Chạy trong LUỒNG KHAY. Mọi thứ đụng tới tkinter phải nhảy về luồng
        giao diện bằng `after` — gọi thẳng từ luồng khác là tkinter sập, và nó
        sập kiểu ngẫu nhiên chứ không phải lần nào cũng sập."""
        if name == "show":
            root.after(0, do_show)
        elif name == "dashboard":
            open_url(DASH)
        elif name == "cloud":
            open_url(CLOUD + "/dash")
        elif name == "log":
            if os.path.isfile(LOG):
                open_url(LOG)
        elif name == "reset":
            root.after(0, do_reset)
        elif name == "toggle":
            root.after(0, do_toggle)
        elif name == "password":
            root.after(0, do_password)
        elif name == "reinstall":
            root.after(0, do_reinstall)
        elif name == "quit":
            root.after(0, quit_all)

    def tick():
        state.config(text=bridge.status())
        paused = bridge.paused.is_set()
        busy = bool(bridge.busy)
        btn_conn.config(text="Kết nối lại" if paused else "Ngắt kết nối",
                        state="disabled" if busy else "normal")
        btn_reset.config(state="disabled" if (busy or paused) else "normal")
        btn_pw.config(state="disabled" if busy else "normal")
        btn_reinstall.config(state="disabled" if (busy or paused) else "normal")
        if tray_box["t"]:
            tray_box["t"].set_label("toggle", "Kết nối lại" if paused else "Ngắt kết nối")
        root.after(1200, tick)

    def close():
        """Bấm X = ẩn xuống khay, KHÔNG tắt cầu nối.

        Trước đây X là dừng hẳn, và đó là cái bẫy: người dùng đóng cửa sổ cho
        gọn màn hình, mấy tiếng sau mới phát hiện máy đã biến khỏi cloud. Muốn
        dừng thật thì có «Thoát hẳn» trong menu khay, nói đúng điều nó làm.
        """
        if tray_box["t"]:
            root.withdraw()
        else:
            quit_all()

    if IS_WIN:
        _t = WinTray(tray_action, tip=(APP + " — " + str(conf.get("name") or "")).strip(" —"))
        if _t.start():
            tray_box["t"] = _t
        else:
            log("khay hệ thống không bật được — cửa sổ sẽ đóng là thoát hẳn")

    root.protocol("WM_DELETE_WINDOW", close)
    tick()
    root.mainloop()
    if tray_box["t"] and not quitting["v"]:
        tray_box["t"].stop()


def main() -> int:
    os.makedirs(HOME, exist_ok=True)
    win_app_id()                      # trước mọi cửa sổ, nếu không thanh tác vụ giữ icon Python
    conf = conf_read()
    # Dòng đầu tiên của mỗi lượt chạy: log rỗng thì không ai biết client đã khởi động
    # hay chết trước cả khi kịp mở cửa sổ.
    log(f"khởi động (pid {os.getpid()}, {os.path.basename(sys.executable)}, "
        f"bản {client_build()}), đã ghép nối: {bool(conf.get('tunnel_token'))}")

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
