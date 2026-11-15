"""TubeCLI Connect tải cloudflared: Python hỏng chứng chỉ → curl → PowerShell; hỏng thì giãn nhịp + nói lý do.

Chạy:  python tests/connect_cloudflared_download_test.py      (mã thoát 0 = đạt)

Vì sao (14/11/2026, máy «maycongty»): ghép nối xong mà cửa sổ chỉ ghi «Tunnel: TẮT»; connect.log 20 giây một dòng
«không tải được cloudflared: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] … unable to get issuer certificate>».
Python trên Windows không tự nạp chứng chỉ gốc còn thiếu trong kho của Windows; curl.exe / PowerShell thì dùng thẳng
kho đó. Không bao giờ tắt kiểm chứng chỉ.

Cách ly: APPDATA tạm; mọi lượt tải là GIẢ (không mạng, không chạy curl / powershell thật).
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
TMP = tempfile.mkdtemp(prefix="tc_cfdl_")
os.environ["APPDATA"] = TMP

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(TXT, str(SRC), "exec"), mod.__dict__)
mod.mint_cloud_key = lambda: ("", mod.KEY_OLD_CORE)        # không bao giờ chạy lệnh tubecli thật
# 14/11/2026: lõi cũ → client tự cập nhật TubeCLI (git fetch / merge + tắt máy chủ). Test KHÔNG BAO GIỜ được làm
# việc đó trên bản cài thật của máy; bài test riêng ở tests/connect_auto_update_test.py dùng repo git tạm.
mod.update_tubecli = lambda say=None: (False, "")

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:300]}"))
    if not ok:
        failures += 1


LOGS = []
mod.log = lambda m: LOGS.append(str(m))
BIG = b"MZ" + b"\0" * (mod.CF_MIN_BYTES + 10)
SSL_ERR = "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get issuer certificate>"
CALLS = []


def writer(name, data=BIG, exc=None):
    def fn(url, dest):
        CALLS.append(name)
        if exc:
            raise RuntimeError(exc)
        with open(dest, "wb") as f:
            f.write(data)
    return fn


def use(py, curl, ps):
    CALLS.clear()
    mod._download_urllib, mod._download_curl, mod._download_powershell = py, curl, ps


dest = os.path.join(TMP, "x.part")

# ── A. download_file: thứ tự + đường lùi ──────────────────────────────────────
use(writer("python"), writer("curl"), writer("powershell"))
check("A1 Python tải được → không đụng curl / PowerShell", mod.download_file("u", dest) == "python" and CALLS == ["python"], CALLS)
use(writer("python", exc=SSL_ERR), writer("curl"), writer("powershell"))
check("A2 Python hỏng chứng chỉ → curl tải", mod.download_file("u", dest) == "curl" and CALLS == ["python", "curl"]
      and os.path.getsize(dest) == len(BIG), CALLS)
use(writer("python", exc=SSL_ERR), writer("curl", exc="máy không có curl"), writer("powershell"))
check("A3 không có curl → PowerShell tải", mod.download_file("u", dest) == "powershell"
      and CALLS == ["python", "curl", "powershell"], CALLS)
use(writer("python", data=b"<html>error</html>"), writer("curl"), writer("powershell"))
check("A4 file tải về quá nhỏ (trang lỗi) không được coi là cloudflared → thử cách kế", mod.download_file("u", dest) == "curl", CALLS)
use(writer("python", exc=SSL_ERR), writer("curl", exc="curl: (35) schannel"), writer("powershell", exc="403"))
try:
    mod.download_file("u", dest)
    err = ""
except RuntimeError as e:
    err = str(e)
check("A5 mọi cách hỏng → lỗi gom lý do của CẢ BA cách", "python:" in err and "curl:" in err and "powershell:" in err
      and "CERTIFICATE_VERIFY_FAILED" in err, err)

# ── B. ensure_cloudflared: giãn nhịp + lý do ──────────────────────────────────
mod.CLOUDFLARED = os.path.join(TMP, "cloudflared.exe")
mod.CF_URL = "https://example.invalid/cloudflared-windows-amd64.exe"
mod.TUNNEL_STATE.update(error="", fails=0, next_try=0.0)
NOW = [1000.0]
mod.time.time = lambda: NOW[0]
use(writer("python", exc=SSL_ERR), writer("curl", exc="x"), writer("powershell", exc="y"))
LOGS.clear()
check("B1 tải hỏng → False, có lý do đọc được kèm chỗ tải tay", mod.ensure_cloudflared() is False
      and "không tải được cloudflared" in mod.tunnel_problem() and mod.CF_URL in mod.tunnel_problem()
      and mod.CLOUDFLARED in mod.tunnel_problem(), mod.tunnel_problem())
n = len(CALLS)
NOW[0] += 20
check("B2 20 giây sau (nhịp canh): KHÔNG thử lại, không ghi thêm dòng log", mod.ensure_cloudflared() is False
      and len(CALLS) == n and sum("tải cloudflared…" in ln for ln in LOGS) == 1, (CALLS, LOGS))
NOW[0] += 15
check("B3 quá 30 giây: thử lại lần hai", mod.ensure_cloudflared() is False and len(CALLS) > n)
waits = []
for _ in range(8):
    NOW[0] = mod.TUNNEL_STATE["next_try"] + 1
    before = NOW[0]
    mod.ensure_cloudflared()
    waits.append(round(mod.TUNNEL_STATE["next_try"] - before))
check("B4 hỏng liên tiếp: giãn dần, trần 10 phút", waits == sorted(waits) and waits[-1] == mod.CF_RETRY_MAX, waits)
use(writer("python", exc=SSL_ERR), writer("curl"), writer("powershell"))
NOW[0] = mod.TUNNEL_STATE["next_try"] + 1
LOGS.clear()
check("B5 lần sau curl tải được → True, file vào đúng chỗ, xoá lỗi + bộ đếm", mod.ensure_cloudflared() is True
      and os.path.isfile(mod.CLOUDFLARED) and mod.tunnel_problem() == "" and mod.TUNNEL_STATE["fails"] == 0)
check("B6 log ghi đã tải bằng curl (để biết máy này Python hỏng chứng chỉ)", any("đã tải bằng curl" in ln for ln in LOGS), LOGS)
use(writer("python"), writer("curl"), writer("powershell"))
check("B7 đã có file → không tải nữa", mod.ensure_cloudflared() is True and CALLS == [])

# ── C. dòng trạng thái nói lý do ──────────────────────────────────────────────
mod.tubecli_up = lambda timeout=2.0: True
b = mod.Bridge({"tunnel_token": "T", "url": "https://m.tubecreate.com"})
mod.TUNNEL_STATE["error"] = "không tải được cloudflared (x)"
check("C1 tunnel tắt + biết lý do → dòng trạng thái có «⚠ Tunnel: …»", "Tunnel: TẮT" in b.status() and "⚠ Tunnel: không tải được" in b.status(), b.status())


class Alive:
    def poll(self):
        return None


b.tunnel = Alive()
check("C2 tunnel đang chạy → không kèm cảnh báo cũ", "đang chạy" in b.status() and "⚠" not in b.status(), b.status())

# ── D. tĩnh ───────────────────────────────────────────────────────────────────
dl = TXT[TXT.index("def _download_urllib"):TXT.index("def start_tunnel")]
check("D1 không có chỗ nào tắt kiểm chứng chỉ", not any(x in dl for x in ("CERT_NONE", "_create_unverified_context",
      "--insecure", " -k ", "SkipCertificateCheck", "ServerCertificateValidationCallback")))
check("D2 PowerShell nhận URL / đường dẫn qua biến môi trường (không ghép chuỗi lệnh)",
      "$env:TC_DL_URL" in dl and "$env:TC_DL_OUT" in dl)
st = TXT[TXT.index("def start_tunnel"):TXT.index("# ── Ghép nối với cloud")]
check("D3 cloudflared ghi log ra file (hết đổ lỗi vào hư không)", '"--logfile", cf_log' in st)

print(f"\n{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
