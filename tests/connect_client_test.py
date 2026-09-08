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
    sent["body"] = json.loads(req.data.decode())
    return _Resp({"server_id": 41, "domain": "may.tubecreate.com", "tunnel_token": "T0K3N"})


mod.urllib.request.urlopen = _ok
info = mod.claim("B8H4U7", "MatKhau#1")
check("gọi đúng endpoint đổi mã", sent["url"].endswith("/api/servers/pair/claim"), sent["url"])
check("gửi kèm mã + mật khẩu dashboard",
      sent["body"] == {"code": "B8H4U7", "tubecli_password": "MatKhau#1"}, sent["body"])
check("trả token tunnel cho vòng canh", info["tunnel_token"] == "T0K3N")


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

print("=" * 62)
print(f"{failures} FAIL / {checks}" if failures else f"{checks}/{checks} PASS")
sys.exit(1 if failures else 0)
