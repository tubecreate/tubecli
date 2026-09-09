# Client "TubeCLI Connect" (client/tubecli_connect.pyw): cầu nối máy nhà ↔ cloud.
#
# File .pyw ấy chạy trên máy người dùng, không ai xem log, nên những chỗ dễ hỏng
# lặng lẽ phải có test canh: dò được bản TubeCLI đã cài (hai bố cục), đọc/ghi cấu
# hình đúng chỗ, và câu lỗi của cloud phải đi tới người dùng chứ không nuốt.
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

SRC = ROOT / "client" / "tubecli_connect.pyw"
if not SRC.exists():
    print(f"SKIP: không có {SRC}")
    sys.exit(0)

TMP = tempfile.mkdtemp(prefix="tc_connect_")
os.environ["APPDATA"] = TMP            # cấu hình/log của test không chạm máy thật

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), mod.__dict__)

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    if ok:
        print(f"  ok  {name}")
        return
    failures += 1
    print(f"  FAIL {name} — {detail}")


# 1. Dò bản TubeCLI: nhận cả bản cài (TubeCLI.bat) lẫn bản git (tubecli/main.py)
d_bat = os.path.join(TMP, "cai_dat")
os.makedirs(d_bat, exist_ok=True)
open(os.path.join(d_bat, "TubeCLI.bat"), "w").close()
d_git = os.path.join(TMP, "ban_git", "tubecli")
os.makedirs(d_git, exist_ok=True)
open(os.path.join(d_git, "main.py"), "w").close()
check("nhận bản cài bằng install.ps1", mod.is_tubecli_dir(d_bat))
check("nhận bản lấy từ git", mod.is_tubecli_dir(os.path.dirname(d_git)))
check("thư mục lạ thì không", not mod.is_tubecli_dir(os.path.join(TMP, "khong_co")))
check("chuỗi rỗng không làm nó ngã", not mod.is_tubecli_dir(""))
check("client nằm trong repo thì tự tìm ra chính repo ấy",
      mod.find_install() == str(ROOT), mod.find_install())

# 1b. "Máy đã cài rồi thì sao": ĐANG CHẠY là câu trả lời mạnh nhất và phải hỏi TRƯỚC.
# Đo trên máy người dùng 8/9/26: TubeCLI đang chạy ở cổng 5295 nhưng nằm ở
# C:\tubecreate-vue\tubecli (không phải ~/TubeCLI), client thì tải về %TEMP% — nên
# find_install() rỗng và client gọi trình cài, trình cài kết thúc bằng `tubecli init`
# (một wizard ĐỢI NGƯỜI GÕ) rồi trả mã 1. Log ghi đúng chuỗi đó.
mod.tubecli_up = lambda timeout=2.0: True
mod.find_install = lambda: ""
mod.shutil.which = lambda name: None
check("máy chủ đang trả lời → coi như đã có, không cài chồng", mod.have_tubecli())
mod.tubecli_up = lambda timeout=2.0: False
check("không chạy, không thư mục, không PATH → mới là chưa có", not mod.have_tubecli())
mod.shutil.which = lambda name: r"C:\Python\Scripts\tubecli.exe" if name == "tubecli" else None
check("cài bằng pip (có lệnh trên PATH) cũng là đã có", mod.have_tubecli())
cmd, cwd = mod.server_cmd()
# `serve` không phải lệnh của TubeCLI — CLI chỉ có `api start`. Bản trước đoán tên
# lệnh, tiến trình con chết ngay với "No such command 'serve'" và vì nó chạy dưới
# pythonw nên không ai thấy; client chỉ báo "không trả lời sau 60 giây" (9/9/2026).
check("bật bằng chính lệnh tubecli trên PATH",
      cmd[:3] == [r"C:\Python\Scripts\tubecli.exe", "api", "start"], cmd)
check("cổng đi kèm và chạy im (không log truy cập)",
      "--port" in cmd and str(mod.PORT) in cmd and "--quiet" in cmd, cmd)
mod.shutil.which = lambda name: None
mod.find_install = lambda: d_bat
cmd, cwd = mod.server_cmd()
check("có thư mục → chạy module trong thư mục ấy",
      cmd[1:5] == ["-m", "tubecli.main", "api", "start"] and cwd == d_bat, (cmd, cwd))
mod.find_install = lambda: str(ROOT)
mod.tubecli_up = lambda timeout=2.0: True

# 1c. Không có pystray thì phải MỞ CỬA SỔ, không được ngủ im trong nền: pythonw không
# có cửa sổ, người dùng không thấy gì và tưởng client chết ("không thấy client?").
src_text = SRC.read_text(encoding="utf-8")
tray_src = src_text[src_text.index("def tray("):src_text.index("def status_window(")]
check("thiếu pystray → gọi cửa sổ trạng thái", "status_window(bridge)" in tray_src, tray_src[-200:])
check("không còn nhánh ngủ im", "wait(3600)" not in src_text)
check("cửa sổ có nút mở dashboard, log và tuỳ chọn khởi động cùng Windows",
      all(x in src_text for x in ("Mở dashboard", "Xem log", "Khởi động cùng Windows")))
check("đóng cửa sổ là dừng hẳn cầu nối (không để tiến trình mồ côi)",
      "bridge.shutdown()" in src_text[src_text.index("def status_window("):])

# 1d. Thứ tự khi mở client (đúng như người dùng mong đợi): DÒ trước, hỏi mã sau.
#   cổng 5295 trả lời        → dùng luôn, không đụng gì
#   đã cài mà chưa chạy      → tự bật
#   chưa cài gì              → chạy trình cài rồi bật (mật khẩu khi ấy là mặc định)
# Bản đầu hỏi mã TRƯỚC rồi mới đi cài, nên người ta gõ mã vào một cái máy mà client
# còn chưa biết có TubeCLI hay không.
_up = mod.tubecli_up
_cmd = mod.server_cmd
_start = mod.start_tubecli
_install = mod.install_tubecli
try:
    said = []
    mod.tubecli_up = lambda timeout=2.0: True
    mod.install_tubecli = lambda lang="vi": (_ for _ in ()).throw(AssertionError("không được cài khi máy đang chạy"))
    mod.start_tubecli = lambda: (_ for _ in ()).throw(AssertionError("không được bật lại khi máy đang chạy"))
    check("đang chạy → không cài, không bật lại", mod.prepare_node(said.append) == (True, ""))
    check("nói đúng trạng thái", said == ["TubeCLI đang chạy ✓"], said)

    said.clear()
    started = []
    mod.tubecli_up = lambda timeout=2.0: False
    mod.server_cmd = lambda: (["pythonw"], r"D:\TubeCLI")
    mod.start_tubecli = lambda: started.append(1) or True
    check("đã cài mà chưa chạy → TỰ BẬT, không cài lại", mod.prepare_node(said.append) == (True, "") and started)
    check("nói rõ đang bật bản đã cài", any("Đã cài sẵn" in m for m in said), said)

    said.clear()
    installed = []
    mod.server_cmd = lambda: ([], "")
    mod.install_tubecli = lambda lang="vi": installed.append(lang) or True
    ok, suggest = mod.prepare_node(said.append, "vi")
    check("chưa cài gì → chạy trình cài rồi bật", ok and installed == ["vi"])
    check("máy mới cài thì gợi ý mật khẩu mặc định", suggest == "123456", suggest)
    check("báo trước rằng trình cài sẽ HỎI vài câu", any("HỎI" in m for m in said), said)

    said.clear()
    mod.install_tubecli = lambda lang="vi": False
    check("trình cài hỏng → trả False, không nói dối là xong", mod.prepare_node(said.append)[0] is False)
    check("nói rõ hỏng ở đâu", any("Trình cài" in m for m in said), said)
finally:
    mod.tubecli_up, mod.server_cmd = _up, _cmd
    mod.start_tubecli, mod.install_tubecli = _start, _install

# Cửa sổ phải khoá nút Kết nối tới khi máy chủ trả lời, và dò ở LUỒNG NỀN (trình cài
# mất vài phút; cửa sổ đứng đơ là Windows dán nhãn "Not responding").
_src = SRC.read_text(encoding="utf-8")
_ask = _src[_src.index("def ask_pairing("):_src.index("def notify(")]
check("nút Kết nối khoá lúc đầu", 'btn.state(["disabled"])' in _ask)
check("dò/bật/cài chạy ở luồng nền", "threading.Thread(target=prepare" in _ask)
check("xong mới mở nút", 'btn.state(["!disabled"])' in _ask)
check("main không còn tự cài sau khi hỏi mã",
      "ask_pairing(code, lang=" in _src and "install_tubecli(lang=conf" not in _src)

# 1e. log() KHÔNG ĐƯỢC GIẾT TIẾN TRÌNH.
# Đo thật ngày 8/9/26: client chạy bằng pythonw chết ngay dòng log đầu tiên —
#   UnicodeEncodeError('charmap', '20:02:42 thử ghi log dưới pythonw', …)
# vì pythonw không có console tử tế, print() tiếng Việt vào đó là ném lỗi. Log rỗng,
# không icon, không cửa sổ: người dùng chỉ thấy "client biến mất".
class _StdoutHong:
    def write(self, *a):
        raise UnicodeEncodeError("charmap", "x", 0, 1, "character maps to <undefined>")

    def flush(self):
        raise OSError("console đã đóng")


# check() cũng in ra màn hình, nên phải TRẢ LẠI stdout trước khi gọi nó — nếu không
# chính bài test lại ngã vì đúng cái lỗi nó đang đi bắt.
_stdout = sys.stdout
_crash = None
try:
    sys.stdout = _StdoutHong()
    try:
        mod.log("thử ghi log tiếng Việt dưới pythonw")
    except BaseException as e:      # noqa: BLE001 — đây chính là thứ cần bắt
        _crash = repr(e)
finally:
    sys.stdout = _stdout
check("stdout hỏng cũng không ném ra ngoài", _crash is None, _crash or "")
check("dòng log vẫn vào file dù stdout hỏng",
      "thử ghi log tiếng Việt" in open(mod.LOG, encoding="utf-8").read())

# Thư mục log không ghi được thì cũng chỉ im lặng bỏ qua, không được ngã.
_home, _log = mod.HOME, mod.LOG
_crash2 = None
try:
    mod.HOME = os.path.join(TMP, "khong_ghi_duoc", "\x00")
    mod.LOG = os.path.join(mod.HOME, "connect.log")
    mod.log("thử ghi vào chỗ không hợp lệ")
except BaseException as e:      # noqa: BLE001
    _crash2 = repr(e)
finally:
    mod.HOME, mod.LOG = _home, _log
check("đường dẫn log hỏng cũng không ngã", _crash2 is None, _crash2 or "")

# Và phải ghi một dòng NGAY khi khởi động: log rỗng thì không ai biết nó đã chạy chưa.
_src2 = SRC.read_text(encoding="utf-8")
_main = _src2[_src2.index("def main("):]
check("khởi động là ghi log ngay", "khởi động (pid" in _main)
check("cửa sổ được kéo lên trước (mở sau lưng trình duyệt thì như không mở)",
      _src2.count('attributes("-topmost", True)') >= 2 and "focus_force" in _src2)

# 1f. BẤM "KẾT NỐI" RỒI CLIENT BIẾN MẤT, LOG IM.
# Đo thật 8/9/26: cả ba nhánh hỏng (TubeCLI tắt / sai mật khẩu dashboard / cloud từ
# chối mã) đều làm đúng một việc — notify() rồi `return 1`. notify() vẽ hộp thoại
# trong thread DAEMON, nên sys.exit() giết tiến trình trước khi hộp thoại kịp hiện,
# và không nhánh nào ghi log. Người dùng: "tôi nhập mã và mật khẩu xong mất luôn
# client", server không thấy gì, log không có thêm dòng nào sau lúc khởi động.
_ask2 = _src[_src.index("def ask_pairing("):_src.index("def notify(")]
_main = _src[_src.index("def main("):]

check("ghép nối chạy NGAY TRONG cửa sổ",
      "def connect(code: str, pw: str)" in _ask2
      and "node_login(pw)" in _ask2 and "claim(code, pw)" in _ask2)
check("hỏng thì Ở LẠI cửa sổ, mở lại nút để gõ lại",
      "def fail(text: str)" in _ask2 and 'btn.state(["!disabled"])' in _ask2)
check("nhánh hỏng KHÔNG đóng cửa sổ",
      "root.destroy" not in _ask2[_ask2.index("def fail("):_ask2.index("def connect(")])
check("mọi câu hỏng đều vào log", 'log(f"ghép nối hỏng: {text}")' in _ask2)
check("ba nguyên nhân được gọi tên riêng, không gộp một câu chung",
      "cổng 5295" in _ask2 and "Mật khẩu dashboard" in _ask2 and "Cloud không nhận mã" in _ask2)
check("ghép nối chạy luồng nền để cửa sổ không đơ",
      "threading.Thread(target=connect" in _ask2)
check("chỉ thành công mới đóng cửa sổ",
      'out["info"] = code, pw, info' in _ask2 and "root.after(0, root.destroy)" in _ask2)
check("cửa sổ trả về cả kết quả ghép nối",
      'return out["code"], out["password"], out["info"]' in _ask2)

check("main không còn ba nhánh notify-rồi-thoát-câm",
      "notify(APP, \"TubeCLI chưa chạy" not in _main
      and "Mật khẩu dashboard không đúng, nên cloud" not in _main
      and "Ghép nối thất bại" not in _main)
check("main dùng thẳng kết quả cửa sổ trả về",
      "code, password, info = ask_pairing(" in _main and "if not info:" in _main)
check("người dùng tự đóng cửa sổ thì log nói ra",
      "người dùng đóng cửa sổ" in _main)

# notify(): log TRƯỚC khi vẽ — hộp thoại có thể không hiện được, log thì đọc lại được.
_notify = _src[_src.index("def notify("):_src.index("class Bridge")]
check("notify ghi log trước khi vẽ", _notify.index("log(f\"{title}: {body}\")") < _notify.index("def run()"))
check("notify biết chờ khi đó là lời cuối trước khi thoát",
      "wait: bool = False" in _notify and "if wait:" in _notify)


class _ThreadGia:
    """Chặn thread thật: test này không được mở hộp thoại lên màn hình người dùng."""

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


_th = mod.threading
try:
    mod.threading = types.SimpleNamespace(Thread=_ThreadGia)
    mod.notify("Tiêu đề", "Nội dung cần đọc lại được")
finally:
    mod.threading = _th
check("nội dung notify nằm trong log kể cả khi không vẽ được",
      "Nội dung cần đọc lại được" in open(mod.LOG, encoding="utf-8").read())

# 2. Cấu hình: ghi rồi đọc lại đúng, và nằm trong thư mục dữ liệu của người dùng
check("cấu hình nằm trong APPDATA/TubeCLI", mod.CONF.startswith(TMP), mod.CONF)
check("chưa ghi gì thì đọc ra rỗng", mod.conf_read() == {})
mod.conf_write({"server_id": 41, "tunnel_token": "T0K3N", "url": "https://may.tubecreate.com"})
check("đọc lại đúng thứ đã ghi", mod.conf_read()["tunnel_token"] == "T0K3N")
check("ghi bằng file tạm rồi mới thay (không để lại .tmp)",
      not os.path.exists(mod.CONF + ".tmp"))

# 3. Đổi mã: lỗi của cloud phải NGUYÊN VĂN tới người dùng, không nuốt thành 'lỗi lạ'
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


sent = {}


def _ok(req, timeout=0):
    sent["url"] = req.full_url
    sent["req"] = req
    sent["body"] = json.loads(req.data.decode())
    return _Resp({"server_id": 41, "domain": "may.tubecreate.com", "tunnel_token": "T0K3N"})


mod.urllib.request.urlopen = _ok
info = mod.claim("B8H4U7", "MatKhau#1")
check("gọi đúng endpoint đổi mã", sent["url"].endswith("/api/servers/pair/claim"), sent["url"])
check("gửi kèm mã + mật khẩu dashboard",
      sent["body"] == {"code": "B8H4U7", "tubecli_password": "MatKhau#1"}, sent["body"])
check("trả token tunnel cho vòng canh", info["tunnel_token"] == "T0K3N")

# 3b. CLOUDFLARE CHẶN CLIENT Ở CỬA — 403 "error code: 1010".
# Đo thật 8/9/26 từ máy người dùng: cùng một URL, cùng một body,
#     urllib mặc định (UA "Python-urllib/3.12") → 403, thân là "error code: 1010"
#     UA thường                                 → 410 (câu trả lời THẬT của route)
# 1010 là Cloudflare chặn theo chữ ký User-Agent: request chết ở edge, không tới
# Worker. Nên mã còn hạn và mật khẩu đúng cũng vô ích, và D1 không ghi nhận lấy một
# lượt claim nào. Người dùng chỉ thấy "Cloud trả HTTP 403".
check("client tự xưng tên riêng", "TubeCLI-Connect" in mod.UA, mod.UA)
check("KHÔNG để lộ UA mặc định của urllib", "Python-urllib" not in mod.UA)
check("mọi request lên cloud đều mang UA ấy",
      sent["req"].get_header("User-agent") == mod.UA, sent["req"].get_header("User-agent"))
check("opener toàn cục cũng gắn UA (bắt cả urlopen(chuỗi) lúc tải cloudflared)",
      "_install_ua_opener()" in _src and 'op.addheaders = [("User-Agent", UA)]' in _src)
check("tải cloudflared đi qua Request có UA, không phải chuỗi trần",
      "cf_req = urllib.request.Request(CF_URL, headers={\"User-Agent\": UA})" in _src)
check("đăng nhập node cũng mang UA (node cũng có thể ngồi sau proxy)",
      _src.count('"User-Agent": UA') >= 2)


# Thân lỗi KHÔNG phải JSON (Cloudflare trả text/HTML) thì vẫn phải đọc được: nuốt nó
# đi là bỏ mất manh mối duy nhất, và "Cloud trả HTTP 403" thì không ai đoán ra 1010.
def _http403(req, timeout=0):
    raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                 __import__("io").BytesIO(b"error code: 1010\n"))


mod.urllib.request.urlopen = _http403
try:
    mod.claim("B8H4U7", "x")
    check("403 phải ném lỗi", False)
except RuntimeError as e:
    check("thân lỗi không-JSON vẫn tới người dùng nguyên văn",
          "1010" in str(e) and "403" in str(e), str(e))


def _http410(req, timeout=0):
    raise urllib.error.HTTPError(req.full_url, 410, "Gone", {},
                                 __import__("io").BytesIO(json.dumps({"error": "Mã không đúng hoặc đã hết hạn"}).encode()))


mod.urllib.request.urlopen = _http410
try:
    mod.claim("SAIMA", "x")
    check("mã sai phải ném lỗi", False)
except RuntimeError as e:
    check("mã sai → câu lỗi của cloud tới thẳng người dùng", "hết hạn" in str(e), str(e))


def _down(req, timeout=0):
    raise OSError("mạng chết")


mod.urllib.request.urlopen = _down
try:
    mod.claim("B8H4U7", "x")
    check("mất mạng phải ném lỗi", False)
except RuntimeError as e:
    check("mất mạng → nói rõ là không gọi được cloud", "Không gọi được cloud" in str(e), str(e))

# 4. Khởi động cùng Windows: bật rồi tắt phải sạch
check("mặc định chưa bật", not mod.autostart_on())
mod.set_autostart(True)
check("bật thì có lối tắt trong Startup", mod.autostart_on())
body = Path(mod.startup_path()).read_text(encoding="utf-8")
check("lối tắt trỏ đúng file client", "tubecli_connect.pyw" in body, body[:120])
mod.set_autostart(False)
check("tắt thì xoá sạch", not mod.autostart_on())
mod.set_autostart(False)
check("tắt hai lần không ngã", True)

# 5. Địa chỉ node và cloud lấy từ env, để cắm vào máy chủ thử nghiệm được
check("cổng node theo TUBECLI_PORT", str(mod.PORT) in mod.HEALTH and mod.HEALTH.startswith("http://127.0.0.1:"))
check("cloud mặc định là cloud.tubecreate.com", mod.CLOUD == "https://cloud.tubecreate.com")

# 9. BA NỀN TẢNG. Client này chạy trên máy của khách, và máy đó có thể là Windows,
# macOS hay Linux. Bản đầu viết thẳng cho Windows (%APPDATA%, install.ps1,
# cloudflared .exe, lối tắt Startup, os.startfile) — trên hai hệ kia nó hỏng ngay từ
# dòng đường dẫn. Test nạp lại chính file ấy với sys.platform giả để soi từng hệ mà
# không cần ba cái máy.
def _load(plat, machine="x86_64"):
    import platform as _pl
    old_plat, old_machine = sys.platform, _pl.machine
    try:
        sys.platform = plat
        _pl.machine = lambda: machine
        m = types.ModuleType("tc_" + plat + machine)
        m.__file__ = str(SRC)
        exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), m.__dict__)
        return m
    finally:
        sys.platform, _pl.machine = old_plat, old_machine


_win = _load("win32")
_mac = _load("darwin")
_mac_arm = _load("darwin", "arm64")
_lin = _load("linux")
_lin_arm = _load("linux", "aarch64")

check("nhận đúng tên hệ", (_win.OS_NAME, _mac.OS_NAME, _lin.OS_NAME) == ("Windows", "macOS", "Linux"))

# Thư mục cấu hình: mỗi hệ một quy ước, và đi ngược quy ước thì công cụ sao lưu của
# người dùng bỏ sót nó.
check("Windows cất ở APPDATA/TubeCLI", _win.HOME.replace("\\", "/").endswith("TubeCLI"), _win.HOME)
check("macOS cất ở Library/Application Support",
      "Library/Application Support/TubeCLI" in _mac.HOME.replace("\\", "/"), _mac.HOME)
check("Linux theo XDG (~/.config/tubecli)",
      _lin.HOME.replace("\\", "/").endswith(".config/tubecli"), _lin.HOME)

# cloudflared: ba hệ ba kiểu đóng gói. macOS phát hành .tgz — tải về chạy thẳng là
# "Exec format error", nên phải giải nén; POSIX tải về 0644 nên phải chmod.
check("cloudflared Windows là .exe",
      _win.CF_URL.endswith("windows-amd64.exe") and _win.CLOUDFLARED.endswith("cloudflared.exe"), _win.CF_URL)
check("cloudflared macOS Intel là .tgz", _mac.CF_URL.endswith("darwin-amd64.tgz"), _mac.CF_URL)
check("cloudflared macOS Apple Silicon là bản arm64", _mac_arm.CF_URL.endswith("darwin-arm64.tgz"), _mac_arm.CF_URL)
check("cloudflared Linux là binary trần", _lin.CF_URL.endswith("linux-amd64"), _lin.CF_URL)
check("Linux ARM lấy đúng bản arm64", _lin_arm.CF_URL.endswith("linux-arm64"), _lin_arm.CF_URL)
check("tên file cloudflared trên POSIX không đuôi .exe",
      os.path.basename(_mac.CLOUDFLARED) == "cloudflared", _mac.CLOUDFLARED)
_cf_src = _src[_src.index("def ensure_cloudflared"):_src.index("def start_tunnel")]
check("gói .tgz được giải nén, không chạy thẳng", "tarfile.open(part)" in _cf_src)
check("POSIX cấp quyền chạy cho cloudflared", "os.chmod(CLOUDFLARED, 0o755)" in _cf_src)

# Trình cài: mỗi hệ gọi đúng trình cài CHÍNH THỨC của nó, không tự dựng bản riêng.
check("Windows cài bằng install.ps1",
      _win.install_command("vi")[0] == "powershell" and "install.ps1" in _win.install_command("vi")[-1])
_sh = _mac.install_command("vi")
check("macOS/Linux cài bằng install.sh qua bash",
      _sh[:2] == ["bash", "-lc"] and "install.sh" in _sh[-1], _sh)
check("truyền ngôn ngữ và không hỏi han (không ai ngồi trước bàn phím)",
      "--lang vi" in _sh[-1] and "--non-interactive" in _sh[-1], _sh[-1])
check("Linux cũng đúng lệnh ấy", _lin.install_command("en")[-1].endswith("--lang en --non-interactive"))

# Khởi động cùng máy: ba cơ chế khác hẳn nhau.
check("Windows dùng thư mục Startup",
      _win.startup_path().replace("\\", "/").endswith("Startup/TubeCLI Connect.cmd"), _win.startup_path())
check("macOS dùng LaunchAgent",
      _mac.startup_path().replace("\\", "/").endswith("Library/LaunchAgents/com.tubecreate.connect.plist"))
check("Linux dùng autostart .desktop",
      _lin.startup_path().replace("\\", "/").endswith("autostart/tubecli-connect.desktop"))
check("nội dung plist chạy lúc đăng nhập",
      "RunAtLoad" in _mac._autostart_body("/usr/bin/python3", "/x/c.py")
      and "/x/c.py" in _mac._autostart_body("/usr/bin/python3", "/x/c.py"))
check("nội dung .desktop đúng chuẩn freedesktop",
      _lin._autostart_body("/usr/bin/python3", "/x/c.py").startswith("[Desktop Entry]")
      and "Exec=/usr/bin/python3 /x/c.py" in _lin._autostart_body("/usr/bin/python3", "/x/c.py"))

# Lối tắt phải trỏ vào một file CÒN SỐNG: lệnh cài tải client về %TEMP% (và /tmp),
# hai chỗ bị dọn định kỳ — trỏ vào đó là hẹn ngày nó trỏ vào hư không.
check("client tự chép sang thư mục cấu hình trước khi cắm lối tắt",
      "def script_home()" in _src and "shutil.copyfile(here, dest)" in _src)
check("set_autostart dùng đường dẫn ổn định ấy",
      "_autostart_body(runner(), script_home())" in _src)

# Bản cài trên POSIX: install.sh đặt ở ~/tubecli với .venv, launcher ~/.local/bin.
_pdir = os.path.join(TMP, "posix_tubecli")
os.makedirs(os.path.join(_pdir, ".venv", "bin"), exist_ok=True)
open(os.path.join(_pdir, ".venv", "bin", "tubecli"), "w").close()
check("nhận bản cài bằng install.sh (.venv/bin/tubecli)", _lin.is_tubecli_dir(_pdir))
_old_find = _lin.find_install
try:
    _lin.find_install = lambda: _pdir
    _cmd, _d = _lin.server_cmd()
    check("bật bằng lệnh trong venv, không phải python hệ thống",
          _cmd[0].endswith(os.path.join(".venv", "bin", "tubecli")) and _cmd[1:3] == ["api", "start"], _cmd)
finally:
    _lin.find_install = _old_find
check("~/.local/bin được dò kể cả khi chưa vào PATH", '".local", "bin", "tubecli"' in _src)

# Mở URL: os.startfile CHỈ có trên Windows — gọi nó ở nơi khác là AttributeError
# giết luôn menu khay.
check("không còn os.startfile trần ngoài hàm open_url",
      _src.count("os.startfile") == 2, "còn ở chỗ khác")
_open_src = _src[_src.index("def open_url"):_src.index("def conf_read")]
check("macOS mở bằng open, Linux bằng xdg-open",
      '"open", target' in _open_src and '"xdg-open", target' in _open_src)

# Máy không đồ hoạ: thiếu tkinter thì vẫn phải hỏi được mã và giữ được cầu nối.
check("thiếu tkinter → hỏi mã ngay trong terminal",
      "def ask_pairing_console(" in _src and "if not has_tk():" in _src)
check("thiếu cả pystray lẫn tkinter → vẫn chạy, in trạng thái ra terminal",
      "chế độ terminal" in _src)
check("POSIX siết quyền file cấu hình bằng chmod 600",
      "os.chmod(CONF, 0o600)" in _src)

# 10. TRÌNH THÔNG DỊCH NÀO chạy được TubeCLI — phải kiểm chứng, không được đoán.
# Đo trên máy người dùng 9/9/2026 (server.log vừa thêm nói thẳng ra):
#   pythonw -m tubecli.main api start … → ModuleNotFoundError: No module named 'click'
# install.ps1 trên Windows KHÔNG dựng venv: nó pip install vào đúng cái `python` nó
# tìm được rồi thêm Scripts vào PATH của NGƯỜI DÙNG. Client đang chạy giữ PATH cũ,
# nên `pythonw` trần phân giải sang một Python khác, không có phụ thuộc nào.
_win2 = _load("win32")
_dir = os.path.join(TMP, "win_install")
os.makedirs(_dir, exist_ok=True)
open(os.path.join(_dir, "TubeCLI.bat"), "w").close()
_win2.find_install = lambda: _dir

# Có launcher trên PATH → dùng THẲNG launcher: pip đặt nó vào Scripts của đúng
# Python đã cài gói, nên nó biết trình thông dịch, còn ta thì không.
_win2.shutil.which = lambda name: r"C:\Py\Scripts\tubecli.exe" if name == "tubecli" else None
_cmd2, _d2 = _win2.server_cmd()
check("thư mục cài + có launcher → chạy launcher, KHÔNG phải pythonw trần",
      _cmd2[:3] == [r"C:\Py\Scripts\tubecli.exe", "api", "start"], _cmd2)
check("vẫn chạy trong thư mục cài", _d2 == _dir)

# Có venv thì venv thắng launcher (bản cài kiểu POSIX/thủ công).
_venv = os.path.join(_dir, "venv", "Scripts")
os.makedirs(_venv, exist_ok=True)
open(os.path.join(_venv, "pythonw.exe"), "w").close()
_cmd3, _ = _win2.server_cmd()
check("có venv thì ưu tiên trình thông dịch trong venv",
      _cmd3[0] == os.path.join(_venv, "pythonw.exe") and _cmd3[1:3] == ["-m", "tubecli.main"], _cmd3)

# Ứng viên không import được thì bị loại — đây chính là bài kiểm mà `pythonw` trần
# trên máy người dùng đã trượt.
check("trình thông dịch không import nổi tubecli thì bị loại",
      _win2._can_import_tubecli(r"C:\khong\ton\tai\pythonw.exe") is False)
check("đường dẫn rỗng cũng không làm nó ngã", _win2._can_import_tubecli("") is False)
check("python đang chạy bài test này thì import được", mod._can_import_tubecli(sys.executable))

# PATH phải được NẠP LẠI sau khi cài: tiến trình đang chạy giữ bản chụp PATH lúc
# khởi động, nên `tubecli` vừa cài xong vẫn "không tồn tại" với chính client.
check("có hàm nạp lại PATH từ registry", "def refresh_path_win()" in _src and "winreg" in _src)
check("gọi nó sau khi cài xong", _src.index("refresh_path_win()\n    say(\"Cài xong") > 0
      if 'refresh_path_win()\n    say("Cài xong' in _src else
      _src.count("refresh_path_win()") >= 3, _src.count("refresh_path_win()"))
check("và gọi trước khi dò bản cài", "refresh_path_win()          # bản cài từ lượt trước" in _src)

# Máy chủ chết ngay thì phải NÓI RA, không đếm hết 60 giây rồi báo chung chung.
check("hứng output máy chủ vào server.log", '"server.log"' in _src)
check("phát hiện tiến trình con thoát sớm", "proc.poll() is not None" in _src
      and "máy chủ TubeCLI thoát ngay" in _src)
check("và in mấy dòng cuối của nó ra log", "_tail_lines(out, 8)" in _src)

print("=" * 62)
print(f"{failures} FAIL / {checks}" if failures else f"{checks}/{checks} PASS")
sys.exit(1 if failures else 0)
