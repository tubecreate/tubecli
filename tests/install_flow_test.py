"""The Linux install flow: one command must end at a working server.

Run:  python tests/install_flow_test.py     (exit 0 = pass)

What is locked in here, and why each rule exists:

- install.sh's tail must fork: headless → `tubecli init --server` (password,
  systemd service, summary, exit), desktop → the interactive panel. Before the
  fork existed, a VPS user was handed an interactive control panel over SSH,
  a dashboard URL of 127.0.0.1 their laptop could never reach, and a foreground
  start command that died with their session.
- The wizard must NOT fire on the server path. It runs on "first run", and a
  fresh VPS is exactly that — this was the design review's one CRITICAL finding.
- Public vs private addresses must be classified, not assumed: NAT clouds
  (Tencent/AWS) only see private addresses, but Hetzner/DO-style hosts carry
  the public IPv4 on eth0 and deserve a literally clickable URL. IPv6 is
  excluded — the first smoke run printed a bare v6 in a URL, which is invalid
  without brackets.
- The owner's password decision stands: default 123456, warn, never block,
  never auto-generate. TUBECLI_PASSWORD exists for provisioning and must fall
  back to the default (not abort) when invalid — an aborted finisher would
  leave no systemd unit behind.
"""
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# Point the data dir at a sandbox BEFORE anything imports config/auth.
import tubecli.config as cfg
TMP = Path(tempfile.mkdtemp(prefix="install_flow_"))
cfg.DATA_DIR = TMP / "data"
cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def main():
    sh = (ROOT / "install.sh").read_text(encoding="utf-8", errors="replace")

    print("=== 1. install.sh: cu phap va cac tinh chat cua duoi ===")
    bash = shutil.which("bash")
    if bash:
        r = subprocess.run([bash, "-n", str(ROOT / "install.sh")],
                           capture_output=True, text=True)
        check("bash -n khong loi", r.returncode == 0, (r.stderr or "")[:150])
    else:
        print("  (khong co bash — bo qua)")

    check("khong con ep --port 5295 moi lan chay", "--port 5295" not in sh)
    check("co duong --server cho headless", '"--server"' in sh)
    check("pull dung --ff-only (update khong pha checkout)", "--ff-only" in sh)
    check("mang rong an toan voi set -u tren bash 3.2",
          '${INIT_ARGS[@]+' in sh)
    check("probe headless quyet dinh bang exit code, khong doc stdout",
          "sys.exit(3" in sh)
    check("PYEXE tuyet doi (sudo reset PATH)",
          'PYEXE="$(command -v python3)"' in sh)
    check("URL 127.0.0.1 hardcode da bien khoi duoi",
          "Dashboard: http://127.0.0.1" not in sh)
    check("thu vien browser cai luc co quyen, co cong tac TUBECLI_MINIMAL",
          "TUBECLI_MINIMAL" in sh and "install_chromium_libs" in sh)

    print("\n=== 2. init: --server phai chan wizard (loi CRITICAL cua review) ===")
    src = (ROOT / "tubecli" / "cli" / "init_cmd.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    code = ast.unparse(tree)   # comments stripped — a comment must not satisfy these
    check("co co --server va --panel", "--server" in src and "--panel" in src)
    check("server_mode tinh truoc wizard",
          code.find("server_mode = ") < code.find("_run_setup_wizard()"),
          "thu tu nguoc")
    # Walk the AST for the If whose body calls _run_setup_wizard and demand
    # `server_mode` appears in its test — string-matching the condition broke
    # on ast.unparse's parenthesisation.
    wizard_guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(
                isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_run_setup_wizard"
                for b in node.body for n in ast.walk(b)):
            wizard_guarded = any(isinstance(n, ast.Name) and n.id == "server_mode"
                                 for n in ast.walk(node.test))
            break
    check("wizard bi chan boi server_mode", wizard_guarded)
    check("bare init headless -> finisher, khong restart service",
          "_finish_server_setup(restart_service=server)" in code)

    print("\n=== 3. phan loai dia chi ===")
    from tubecli.cli import server_summary as ss
    # 8.8.8.8, not 203.0.113.x: the latter is TEST-NET-3, a documentation range
    # that ipaddress correctly refuses to call global — the first version of
    # this test used it and accused the code of a bug the test data had.
    pub, priv = ss.split_public_private(
        ["8.8.8.8", "10.0.4.7", "192.168.1.5", "100.64.3.2", "169.254.1.1",
         "2402:800::1", "khong-phai-ip", "172.20.0.9"])
    check("public: chi IP cong khai v4", pub == ["8.8.8.8"], str(pub))
    check("private: RFC1918 + CGNAT + link-local",
          set(priv) == {"10.0.4.7", "192.168.1.5", "100.64.3.2",
                        "169.254.1.1", "172.20.0.9"}, str(priv))
    check("IPv6 va rac bi loai", all(":" not in a for a in pub + priv))

    print("\n=== 4. service: khong systemd thi noi that ===")
    check("service_state tren Windows -> no-systemd",
          ss.service_state() == "no-systemd", ss.service_state())
    from tubecli.cli.service_cmd import install_service, _systemd_available
    check("_systemd_available False khi khong co /run/systemd/system",
          _systemd_available() is False)
    check("install_service tra False thay vi nem",
          install_service(quiet=True) is False)

    print("\n=== 5. finisher: quyet dinh mat khau cua chu du an duoc giu ===")
    # Default stays 123456; TUBECLI_PASSWORD provisions; invalid value falls back.
    from tubecli.core import auth
    auth.ensure_initialised()
    check("khoi dau: mat khau mac dinh", auth.is_default_password())

    from tubecli.cli.init_cmd import _finish_server_setup

    os.environ["TUBECLI_PASSWORD"] = "abc"           # too short
    try:
        _finish_server_setup(restart_service=False)  # must not raise
        check("TUBECLI_PASSWORD ngan: finisher van chay het", True)
    except Exception as e:
        check("TUBECLI_PASSWORD ngan: finisher van chay het", False, str(e))
    check("  va mat khau mac dinh duoc GIU, khong sinh ngau nhien",
          auth.is_default_password())

    os.environ["TUBECLI_PASSWORD"] = "MatKhauCaiDat9"
    _finish_server_setup(restart_service=False)
    check("TUBECLI_PASSWORD hop le: duoc dat", auth.verify_password("MatKhauCaiDat9"))
    del os.environ["TUBECLI_PASSWORD"]

    # No tty (this test process), password already set → nothing changes.
    _finish_server_setup(restart_service=False)
    check("khong tty + da co mat khau: giu nguyen",
          auth.verify_password("MatKhauCaiDat9"))

    print("\n=== 6. man hinh tong ket: in duoc trong moi trang thai ===")
    from rich.console import Console
    buf = io.StringIO()
    real = ss.console
    ss.console = Console(file=buf, force_terminal=False, width=100)
    try:
        ss.print_server_ready(update_status="stale")
    finally:
        ss.console = real
    out = buf.getvalue()
    check("co URL dashboard", "/dashboard" in out)
    check("co nhac firewall", "5295" in out)
    check("co canh bao update stale", "NOT updated" in out or "CHƯA cập nhật" in out)
    check("co lenh tubecli info", "tubecli info" in out)

    print("\n=== 7. i18n: en/vi du cap key moi ===")
    import importlib
    en = importlib.import_module("tubecli.i18n.en").MESSAGES
    vi = importlib.import_module("tubecli.i18n.vi").MESSAGES
    new_en = {k for k in en if k.startswith("server.")}
    new_vi = {k for k in vi if k.startswith("server.")}
    check("en co key server.*", len(new_en) >= 20, str(len(new_en)))
    check("vi phu day du en (khong roi ve tieng Anh)",
          new_vi >= new_en, f"thieu: {sorted(new_en - new_vi)[:4]}")
    try:
        ok = all("{" not in en[k].replace("{port}", "").replace("{lang}", "")
                 .replace("{private}", "").replace("{version}", "") for k in new_en)
        check("khong co placeholder la", ok)
    except Exception as e:
        check("khong co placeholder la", False, str(e))

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
