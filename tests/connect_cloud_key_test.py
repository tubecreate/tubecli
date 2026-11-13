"""TubeCLI Connect ghép nối bằng KHOÁ CLOUD, không hỏi mật khẩu dashboard (13/11/2026).

Chạy:  python tests/connect_cloud_key_test.py      (mã thoát 0 = đạt)

Vì sao: user gửi ảnh cửa sổ ghép nối với 6 dòng «Mật khẩu dashboard TubeCLI không đúng» — «cái phần ghép nối và
mật khẩu này nó phức tạp quá cứ lỗi hoài». Client chạy ngay trên máy nên tự xin khoá cloud bằng
`tubecli cloud-key --new` và giao khoá cho cloud; ô mật khẩu chỉ còn là đường lùi cho lõi cũ.

Cách ly: APPDATA tạm; subprocess / node_login / claim đều giả — KHÔNG chạy lệnh tubecli thật, không mạng.
"""
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
TXT = SRC.read_text(encoding="utf-8")
TMP = tempfile.mkdtemp(prefix="tc_cloudkey_")
os.environ["APPDATA"] = TMP

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(TXT, str(SRC), "exec"), mod.__dict__)

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        failures += 1


LOGS = []
mod.log = lambda m: LOGS.append(str(m))
KEY = "tck_" + "A1b2C3d4" * 5 + "xyz"
KEY2 = "tck_" + "Z9y8X7w6" * 5 + "abc"

# ── A. mint_cloud_key: đọc khoá từ stdout của lệnh ────────────────────────────
RUNS = []


class R:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def fake_run(reply):
    def run(cmd, **kw):
        RUNS.append(list(cmd))
        return reply
    return run


real_run = mod.subprocess.run
mod.server_cmd = lambda: ([r"C:\py\pythonw.exe", "-m", "tubecli"] + list(mod.SERVE_ARGS), r"C:\TubeCLI")
mod.os.path.isfile = lambda p, _real=os.path.isfile: True if str(p).endswith("python.exe") else _real(p)
mod.subprocess.run = fake_run(R(0, KEY + "\n"))
key, why = mod.mint_cloud_key()
check("A1 lệnh chạy là «<tubecli> cloud-key --new», không kèm «api start»",
      RUNS and RUNS[-1][-2:] == ["cloud-key", "--new"] and "api" not in RUNS[-1], RUNS[-1:])
check("A2 pythonw.exe đổi sang python.exe (pythonw không có stdout để đọc khoá)",
      RUNS[-1][0].lower().endswith("python.exe") and not RUNS[-1][0].lower().endswith("pythonw.exe"), RUNS[-1][0])
check("A3 trả đúng khoá", key == KEY and why == "", (key, why))
mod.subprocess.run = fake_run(R(0, "some banner line\n" + KEY + "\n"))
check("A4 có dòng rác phía trên vẫn lấy đúng dòng khoá", mod.mint_cloud_key() == (KEY, ""))
mod.subprocess.run = fake_run(R(2, "", "Usage: tubecli [OPTIONS] COMMAND [ARGS]...\nError: No such command 'cloud-key'.\n"))
check("A5 lõi cũ (No such command) → KEY_OLD_CORE", mod.mint_cloud_key() == ("", mod.KEY_OLD_CORE))
mod.subprocess.run = fake_run(R(1, "", "Traceback ... PermissionError: cloud_key.json"))
key, why = mod.mint_cloud_key()
check("A6 lỗi khác → câu lỗi đọc được, không coi là lõi cũ", key == "" and why != mod.KEY_OLD_CORE and "PermissionError" in why, why)
mod.subprocess.run = fake_run(R(0, "cloud key: not set\n"))
check("A7 mã thoát 0 mà không có dòng khoá → lỗi, không trả rác", mod.mint_cloud_key()[0] == "")
mod.server_cmd = lambda: ([], "")
check("A8 máy chưa có TubeCLI → nói vậy", mod.mint_cloud_key() == ("", "Máy chưa có TubeCLI."))
check("A9 khoá không bao giờ vào log", not any("tck_" in ln for ln in LOGS), LOGS)
mod.subprocess.run = real_run

# ── B. cloud_credential ───────────────────────────────────────────────────────
STATE = {"conf": {}, "valid": set(), "mint": (KEY, ""), "minted": 0}
mod.conf_read = lambda: dict(STATE["conf"])
mod.node_login = lambda pw: pw in STATE["valid"]


def _mint():
    STATE["minted"] += 1
    if STATE["mint"][0]:
        STATE["valid"] = (STATE["valid"] - {k for k in STATE["valid"] if k.startswith("tck_")}) | {STATE["mint"][0]}
    return STATE["mint"]


mod.mint_cloud_key = _mint
check("B1 chưa có khoá → xin khoá mới", mod.cloud_credential() == (KEY, "key", "") and STATE["minted"] == 1)
STATE["conf"] = {"cloud_key": KEY}
check("B2 khoá đang nhớ còn mở được máy → DÙNG LẠI, không xin mới (không giết kết nối cloud đang sống)",
      mod.cloud_credential() == (KEY, "key", "") and STATE["minted"] == 1, STATE)
STATE["valid"] = set()
STATE["mint"] = (KEY2, "")
check("B3 khoá đang nhớ đã bị thu hồi → xin khoá mới", mod.cloud_credential() == (KEY2, "key", "") and STATE["minted"] == 2)
STATE["conf"], STATE["valid"], STATE["mint"] = {}, set(), ("", mod.KEY_OLD_CORE)
check("B4 lõi cũ → «legacy» (phải hỏi mật khẩu)", mod.cloud_credential() == ("", "legacy", ""))
STATE["mint"] = ("", "đĩa đầy")
check("B5 lỗi khác → «error» kèm câu", mod.cloud_credential() == ("", "error", "đĩa đầy"))
mod.mint_cloud_key = lambda: (KEY, "")          # tạo được mà máy chủ đang chạy không nhận (hai bản cài)
STATE["valid"] = set()
cred, kind, err = mod.cloud_credential()
check("B6 máy chủ đang chạy không nhận khoá vừa tạo → lỗi nói rõ, không giao khoá chết cho cloud",
      kind == "error" and "hai bản cài" in err, (cred, kind, err))

# ── C. adopt_pairing ──────────────────────────────────────────────────────────
WRITTEN = []
mod.conf_write = lambda d: WRITTEN.append(dict(d))
INFO = {"server_id": 7, "name": "may-moi", "url": "https://may-moi.tubecreate.com", "tunnel_token": "TOK"}
new = mod.adopt_pairing({"lang": "vi", "password": "mk-cu"}, INFO, KEY)
check("C1 ghép nối bằng khoá: nhớ cloud_key, GIỮ mật khẩu đang nhớ, không ghi khoá vào ô password",
      new["cloud_key"] == KEY and new["password"] == "mk-cu" and new["tunnel_token"] == "TOK", new)
new = mod.adopt_pairing({"lang": "vi", "cloud_key": KEY}, INFO, "mat-khau-thuong")
check("C2 ghép nối kiểu cũ (mật khẩu): nhớ password, bỏ cloud_key cũ", new["password"] == "mat-khau-thuong"
      and "cloud_key" not in new, new)

# ── D. Bridge.repair (nút «Nhập mã mới») ──────────────────────────────────────
CLAIMS = []
mod.tubecli_up = lambda timeout=2.0: True
mod.start_tubecli = lambda: True
mod.claim = lambda code, pw: CLAIMS.append((code, pw)) or dict(INFO)
mod.start_tunnel = lambda token: object()
mod.Bridge._kill_tunnel = lambda self: None
mod.mint_cloud_key = _mint
STATE.update(conf={}, valid=set(), mint=(KEY, ""))
b = mod.Bridge({"lang": "vi", "tunnel_token": "CU", "url": "https://cu.tubecreate.com"})
ok, text = b.repair("ABC123", "")
check("D1 không cần mật khẩu: cloud nhận KHOÁ kèm mã", ok and CLAIMS[-1] == ("ABC123", KEY), (ok, text, CLAIMS))
check("D2 cấu hình mới có cloud_key", b.conf.get("cloud_key") == KEY, b.conf)
STATE.update(valid=set(), mint=("", mod.KEY_OLD_CORE))
b = mod.Bridge({"lang": "vi", "tunnel_token": "CU"})
n = len(CLAIMS)
ok, text = b.repair("ABC123", "")
check("D3 lõi cũ + chưa nhập mật khẩu → trả OLD_CORE_HINT, chưa gọi cloud", (not ok) and text == mod.OLD_CORE_HINT
      and len(CLAIMS) == n, (ok, text))
STATE["valid"] = {"dung"}
ok, text = b.repair("ABC123", "dung")
check("D4 lõi cũ + mật khẩu đúng → ghép nối kiểu cũ", ok and CLAIMS[-1] == ("ABC123", "dung"))
ok, text = b.repair("ABC123", "sai")
check("D5 lõi cũ + mật khẩu sai → báo sai mật khẩu", (not ok) and "Mật khẩu dashboard" in text)

# ── E. đổi mật khẩu dashboard khi máy nối bằng khoá ───────────────────────────
SYNCED = []
mod.change_node_password = lambda new_pw, current="": (True, "Đã đổi mật khẩu.", "api")
mod.sync_cloud_password = lambda conf, pw: SYNCED.append(pw) or (True, "ok")
b = mod.Bridge({"lang": "vi", "tunnel_token": "T", "cloud_key": KEY})
got = []
b.change_password("mat-khau-moi-9", done=lambda ok, m: got.append((ok, m)))
check("E1 máy nối bằng khoá: đổi mật khẩu KHÔNG gửi mật khẩu lên cloud", got and got[0][0] and not SYNCED
      and "khoá riêng" in got[0][1], (got, SYNCED))
b = mod.Bridge({"lang": "vi", "tunnel_token": "T", "password": "cu"})
got = []
b.change_password("mat-khau-moi-9", done=lambda ok, m: got.append((ok, m)))
check("E2 máy nối kiểu cũ: vẫn báo cloud như trước", SYNCED == ["mat-khau-moi-9"], SYNCED)

# ── F. tĩnh: cửa sổ ghép nối ──────────────────────────────────────────────────
pair = TXT[TXT.index("def ask_pairing(default_code"):TXT.index("def notify(title")]
check("F1 ô mật khẩu nằm trong khung pw_box và KHÔNG được pack sẵn",
      'pw_box = tk.Frame(body' in pair and 'e_pw = ttk.Entry(pw_box' in pair
      and pair.count("pw_box.pack(") == 1 and "pw_box.pack(fill=\"x\", before=msg)" in pair)
check("F2 chỉ need_password() mới hiện ô mật khẩu",
      pair.index("def need_password():") < pair.index("pw_box.pack(") < pair.index("def set_dot("))
check("F3 nút Kết nối chỉ đòi mã (mật khẩu chỉ khi ô đang hiện)",
      'pw = e_pw.get() if pw_shown["on"] else ""' in pair and 'msg.config(text="Nhập mã ghép nối."' in pair)
check("F4 connect() hỏi cloud_credential trước, lõi cũ mới kiểm mật khẩu",
      pair.index("cred, kind, err = cloud_credential()") < pair.index("if not node_login(pw):"))
con = TXT[TXT.index("def ask_pairing_console("):TXT.index("# ── Giao diện: bảng màu")]
check("F5 dòng lệnh: có khoá thì không hỏi mật khẩu",
      con.index('if kind == "key":') < con.index("getpass.getpass(f\"Mật khẩu dashboard TubeCLI"))
check("F6 khoá không nằm trong bất kỳ lời log() nào của client",
      "log(f\"" not in TXT[TXT.index("def mint_cloud_key"):TXT.index("OLD_CORE_HINT =")]
      or "key" not in "".join(ln for ln in TXT[TXT.index("def mint_cloud_key"):TXT.index("OLD_CORE_HINT =")].splitlines()
                              if "log(" in ln))

print(f"\n{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
