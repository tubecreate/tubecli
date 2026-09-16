# TubeCLI Connect: chạy lệnh ghép nối với MÃ MỚI khi máy đã ghép nối → tự ghép nối lại.
#
# VÌ SAO CÓ FILE NÀY (máy «quan», 16/9/2026)
#   Người dùng xoá máy trên cloud, tạo máy mới, chạy lệnh ghép nối với mã mới. Client
#   thấy connect.json đã có token nên BỎ QUA mã, chạy tiếp bằng token của tunnel đã bị
#   xoá; cửa sổ không có chỗ nào nhập mã. Còn client cũ (bản tự khởi động) vẫn sống giữ
#   cloudflared cũ. Phải tự xoá connect.json bằng tay mới nối lại được.
#
#   1. main(): --code khi đã ghép nối → mở cửa sổ ghép nối (điền sẵn mật khẩu đã nhớ),
#      xong thì dọn client + tunnel cũ, ghi connect.json mới, chạy với máy mới;
#      đóng cửa sổ giữa chừng thì KHÔNG đụng kết nối cũ
#   2. Bridge.repair (nút «Nhập mã mới»): hỏng bước nào thì kết nối cũ nguyên vẹn
#   3. take_over: dừng đúng client Connect khác + cloudflared của client, không dừng
#      chính mình, không dừng powershell đang chạy lệnh, không dừng cloudflared lạ
#   4. cửa sổ + khay có lối nhập mã mới; tên/địa chỉ cập nhật sau ghép nối lại
#
# Run:  python tests/connect_repair_test.py      (exit 0 = pass)
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

TMP = tempfile.mkdtemp(prefix="tc_repair_")
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


OLD = {"name": "quan", "url": "https://quan-19.tubecreate.com", "tunnel_token": "TOKEN-CU",
       "server_id": 19, "lang": "vi", "password": "mk-dang-nho"}
INFO = {"server_id": 26, "name": "quanbui", "lang": "vi", "domain": "quanbui-26.tubecreate.com",
        "url": "https://quanbui-26.tubecreate.com", "tunnel_token": "TOKEN-MOI"}


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        return self.ret

    ret = None


class FakeBridge:
    made = []

    def __init__(self, conf):
        self.conf = conf
        FakeBridge.made.append(conf)

    def watch(self):
        pass

    def shutdown(self):
        pass


def run_main(conf, argv, pairing_result):
    """Chạy main() thật với mọi thứ chạm máy/mạng/cửa sổ thay bằng bản ghi."""
    saved = {k: mod.__dict__[k] for k in ("conf_read", "conf_write", "ask_pairing", "take_over", "set_autostart",
                                           "notify", "Bridge", "tray", "win_app_id")}
    rec = {"ask": Rec(), "take": Rec(), "write": Rec(), "auto": Rec()}
    rec["ask"].ret = pairing_result
    rec["take"].ret = 2
    FakeBridge.made = []
    mod.conf_read = lambda: dict(conf)
    mod.conf_write = rec["write"]
    mod.ask_pairing = rec["ask"]
    mod.take_over = rec["take"]
    mod.set_autostart = rec["auto"]
    mod.notify = lambda *a, **k: None
    mod.Bridge = FakeBridge
    mod.tray = lambda b: None
    mod.win_app_id = lambda: None
    old_argv = sys.argv
    sys.argv = ["tubecli_connect.pyw"] + argv
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv
        mod.__dict__.update(saved)
    return rc, rec


# ── 1. main() ────────────────────────────────────────────────────────────────
print("── 1. chạy lệnh ghép nối với mã mới")
rc, rec = run_main(OLD, ["--code=ab-cd12"], ("ABCD12", "mk-moi", dict(INFO)))
ask_a, ask_kw = rec["ask"].calls[0] if rec["ask"].calls else ((), {})
check("đã ghép nối + --code → MỞ cửa sổ ghép nối với đúng mã", len(rec["ask"].calls) == 1 and ask_a[:1] == ("AB-CD12",),
      rec["ask"].calls)
check("…điền sẵn mật khẩu client đang nhớ, nói rõ đang thay kết nối nào",
      ask_kw.get("default_password") == "mk-dang-nho" and ask_kw.get("replacing") == OLD["url"], ask_kw)
check("ghép nối xong → dọn client + tunnel cũ ĐÚNG một lần", len(rec["take"].calls) == 1, rec["take"].calls)
written = rec["write"].calls[-1][0][0] if rec["write"].calls else {}
check("connect.json mới: token/tên/địa chỉ/server của máy mới, mật khẩu vừa nhập, giữ ngôn ngữ",
      written.get("tunnel_token") == "TOKEN-MOI" and written.get("url") == INFO["url"] and written.get("server_id") == 26
      and written.get("name") == "quanbui" and written.get("password") == "mk-moi" and written.get("lang") == "vi", written)
check("chạy tiếp vòng canh với cấu hình MỚI", FakeBridge.made and FakeBridge.made[-1].get("tunnel_token") == "TOKEN-MOI",
      FakeBridge.made)
check("bản tự khởi động được chép lại (bản client mới)", rec["auto"].calls == [((True,), {})], rec["auto"].calls)
check("trả 0", rc == 0, rc)

rc, rec = run_main(OLD, ["--code=ABCD12"], ("ABCD12", "", None))
check("đóng cửa sổ giữa chừng → trả 1, KHÔNG dọn client cũ, KHÔNG ghi connect.json, không chạy vòng canh",
      rc == 1 and not rec["take"].calls and not rec["write"].calls and not FakeBridge.made,
      (rc, rec["take"].calls, rec["write"].calls, FakeBridge.made))

rc, rec = run_main(OLD, [], ("x", "y", dict(INFO)))
check("đã ghép nối, KHÔNG có mã → chạy thẳng như cũ, không hỏi, không dọn",
      not rec["ask"].calls and not rec["take"].calls and FakeBridge.made and FakeBridge.made[-1]["tunnel_token"] == "TOKEN-CU")

rc, rec = run_main({"lang": "en"}, ["--code=ABCD12"], ("ABCD12", "123456", dict(INFO)))
check("lần ghép nối ĐẦU (chưa có token) → hỏi mã nhưng KHÔNG đi dọn tiến trình nào",
      len(rec["ask"].calls) == 1 and not rec["take"].calls and rec["ask"].calls[0][1].get("replacing") == "",
      (rec["ask"].calls, rec["take"].calls))

# ── 2. Bridge.repair (nút «Nhập mã mới») ─────────────────────────────────────
print("── 2. nút «Nhập mã mới» trong client đang chạy")


class FakeProc:
    def __init__(self, token="TOKEN-CU"):
        self.token = token
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True


def bridge_env(login_ok=True, claim_exc=None, up=True, start_ok=True):
    saved = {k: mod.__dict__[k] for k in ("tubecli_up", "start_tubecli", "node_login", "claim", "conf_write", "start_tunnel")}
    st = {"claimed": [], "written": [], "started": []}
    mod.tubecli_up = lambda timeout=2.0: up
    mod.start_tubecli = lambda: start_ok
    mod.node_login = lambda pw: login_ok and pw == "dung"

    def _claim(code, pw):
        st["claimed"].append((code, pw))
        if claim_exc:
            raise RuntimeError(claim_exc)
        return dict(INFO)
    mod.claim = _claim
    mod.conf_write = lambda d: st["written"].append(dict(d))

    def _start(token):
        st["started"].append(token)
        return FakeProc(token)
    mod.start_tunnel = _start
    return saved, st


def new_bridge():
    b = mod.Bridge(dict(OLD))
    old_tunnel = FakeProc()
    b.tunnel = old_tunnel
    return b, old_tunnel


for label, kw, pw, expect in [
    ("sai mật khẩu", {}, "sai", "Mật khẩu dashboard"),
    ("cloud không nhận mã", {"claim_exc": "Mã không đúng hoặc đã hết hạn"}, "dung", "Cloud không nhận mã"),
    ("TubeCLI tắt mà bật không lên", {"up": False, "start_ok": False}, "dung", "TubeCLI chưa chạy"),
]:
    saved, st = bridge_env(**kw)
    try:
        b, old_tunnel = new_bridge()
        ok, msg = b.repair("ABCD12", pw)
    finally:
        mod.__dict__.update(saved)
    check(f"{label} → (False, lý do) và kết nối cũ NGUYÊN: token cũ, tunnel cũ còn chạy, không ghi file",
          ok is False and expect in msg and b.conf["tunnel_token"] == "TOKEN-CU" and not old_tunnel.terminated
          and b.tunnel is old_tunnel and not st["written"] and not st["started"] and b.busy == "",
          (ok, msg, b.conf.get("tunnel_token"), old_tunnel.terminated, st))
    if label == "sai mật khẩu":
        check("…sai mật khẩu thì không tốn mã (chưa gọi cloud)", not st["claimed"], st["claimed"])

saved, st = bridge_env()
try:
    b, old_tunnel = new_bridge()
    b.paused.set()
    ok, msg = b.repair("ABCD12", "dung")
finally:
    mod.__dict__.update(saved)
check("đúng mã + mật khẩu → True, câu có địa chỉ máy mới", ok is True and INFO["url"] in msg, (ok, msg))
check("…ghi connect.json máy mới rồi thay tunnel: cũ dừng, mới chạy bằng token mới",
      st["written"] and st["written"][-1]["tunnel_token"] == "TOKEN-MOI" and old_tunnel.terminated
      and st["started"] == ["TOKEN-MOI"] and b.tunnel.token == "TOKEN-MOI", (st, old_tunnel.terminated))
check("…bỏ trạng thái «đã ngắt kết nối» để vòng canh giữ máy mới sống", not b.paused.is_set())
b2 = mod.Bridge(dict(OLD))
b2.busy = "đang cài lại TubeCLI…"
check("đang bận việc khác → từ chối, không đụng gì", b2.repair("ABCD12", "dung")[0] is False and b2.conf["tunnel_token"] == "TOKEN-CU")

# ── 3. take_over ─────────────────────────────────────────────────────────────
print("── 3. dọn client + tunnel cũ")
me, parent = os.getpid(), os.getppid()
cf = mod.CLOUDFLARED
rows = [
    (me, "pythonw.exe", f"pythonw {TMP}\\tubecli_connect.pyw --code=ABCD12"),               # chính mình
    (parent, "pythonw.exe", "pythonw C:\\Temp\\tubecli_connect.pyw --code=ABCD12"),          # launcher của mình
    (4101, "pythonw.exe", '"C:\\Python312\\pythonw.exe" "C:\\Users\\q\\AppData\\Roaming\\TubeCLI\\tubecli_connect.pyw"'),
    (4102, "powershell.exe", 'powershell -c "irm https://raw.../tubecli_connect.pyw -OutFile x; pythonw x --code=AB"'),
    (4103, "python.exe", "python C:\\TubeCLI\\tubecli\\main.py api start"),                  # máy chủ TubeCLI
    (4104, "cloudflared.exe", f'"{cf}" tunnel --no-autoupdate run --token TOKEN-CU'),
    (4105, "cloudflared.exe", '"C:\\khac\\cloudflared.exe" tunnel run --token CUA-NGUOI-KHAC'),
]
check("client khác: chỉ tiến trình python chạy tubecli_connect, trừ chính mình + launcher",
      mod.other_clients(rows) == [4101], mod.other_clients(rows))
check("tunnel: chỉ cloudflared chạy bằng binary của client", mod.our_tunnels(rows) == [4104], mod.our_tunnels(rows))
saved = {k: mod.__dict__[k] for k in ("_list_procs", "_kill")}
killed = []
mod._list_procs = lambda: rows
mod._kill = lambda pid: killed.append(pid)
try:
    n = mod.take_over()
finally:
    mod.__dict__.update(saved)
check("take_over dừng client cũ TRƯỚC rồi mới cloudflared (không để vòng canh cũ dựng lại tunnel)",
      killed == [4101, 4104] and n == 2, killed)
check("không dừng máy chủ TubeCLI, powershell, cloudflared lạ", not {me, parent, 4102, 4103, 4105} & set(killed), killed)

saved_win, saved_sub = mod.IS_WIN, mod.subprocess
out = ("4101\tpythonw.exe\t\"C:\\Python312\\pythonw.exe\" C:\\Users\\q\\AppData\\Roaming\\TubeCLI\\tubecli_connect.pyw\n"
       "4104\tcloudflared.exe\tC:\\x\\cloudflared.exe tunnel run\n"
       "rác không phải dòng\n"
       "12\tSystem\t\n")
mod.IS_WIN = True
mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=out), CREATE_NO_WINDOW=0)
try:
    parsed = mod._list_procs()
finally:
    mod.IS_WIN, mod.subprocess = saved_win, saved_sub
check("_list_procs (Windows) đọc đúng pid/tên/dòng lệnh, bỏ dòng rác",
      [p[:2] for p in parsed] == [(4101, "pythonw.exe"), (4104, "cloudflared.exe"), (12, "System")]
      and "tubecli_connect.pyw" in parsed[0][2], parsed)

# ── 4. giao diện ─────────────────────────────────────────────────────────────
print("── 4. cửa sổ + khay")
src = SRC.read_text(encoding="utf-8")
check("khay có mục «Nhập mã ghép nối mới…»", '("repair",     "Nhập mã ghép nối mới…")' in src and 'elif name == "repair":' in src)
check("cửa sổ có nút «Nhập mã mới» gọi bridge.repair ở luồng nền",
      'ttk.Button(bar3, text="Nhập mã mới")' in src and "bridge.repair(code, pw)" in src and "btn_repair.config(command=do_repair)" in src)
check("tên + địa chỉ trên cửa sổ đọc lại bridge.conf mỗi nhịp", 'lbl_name.config(text=bridge.conf.get("name") or APP)' in src
      and 'lbl_url.config(text=bridge.conf.get("url") or "")' in src)
check("cửa sổ ghép nối nhận mật khẩu điền sẵn + địa chỉ đang bị thay",
      'default_password: str = ""' in src and "replacing: str = \"\"" in src and "e_pw.insert(0, default_password)" in src)

print(f"\n{checks - failures}/{checks} PASS" if not failures else f"\n{checks - failures}/{checks} PASS — {failures} HỎNG")
sys.exit(1 if failures else 0)
