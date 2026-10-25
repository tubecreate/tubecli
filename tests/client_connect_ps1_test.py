# -*- coding: utf-8 -*-
"""client/connect.ps1 — bootstrap Windows cho lệnh «Connect my computer» (user 25/10/2026: «lỗi cài window»,
ảnh: `pythonw : The term 'pythonw' is not recognized` trên máy chưa có Python).

Chạy:  python tests/client_connect_ps1_test.py   (exit 0 = pass; phần chạy thật cần powershell — Windows / pwsh)

Luật canh:
  1. File parse được bằng PowerShell 5.1 (không &&, ??, ?.), có đủ tham số -Code -GhProxy -ClientPath -NoInstall -DryRun.
  2. Tìm Python đúng thứ tự install.ps1: PATH (bỏ alias Store «WindowsApps»), py launcher, thư mục quen; cài bằng
     winget Python.Python.3.11 rồi python.org 3.11.9; bật TLS 1.2; làm mới PATH sau khi cài.
  3. Chạy thật -DryRun -NoInstall -ClientPath <repo client>: in «[dry-run] <pythonw> "<client>" --code=…», exit 0,
     KHÔNG tải mạng, KHÔNG khởi động gì; -GhProxy đặt TUBECLI_GH_PROXY cho tiến trình con.
  4. Mã nối (-Code) đi nguyên vào --code=.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PS1 = ROOT / "client" / "connect.ps1"
CLIENT = ROOT / "client" / "tubecli_connect.pyw"
ok = fail = skipped = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name}  {detail}")


src = PS1.read_text(encoding="utf-8")
print("1. hình thức")
check("có param Code/GhProxy/ClientPath/NoInstall/DryRun", all(x in src for x in ("[string]$Code", "[string]$GhProxy", "[string]$ClientPath", "[switch]$NoInstall", "[switch]$DryRun")))
check("không dùng cú pháp PowerShell 7 (&&, ??, ?.)", " && " not in src and " ?? " not in src and "?." not in src.replace("?.exe", ""))
check("bật TLS 1.2 (Windows 10 cũ tải python.org/github hỏng)", "SecurityProtocolType]::Tls12" in src)
print("2. tìm / cài Python")
check("bỏ alias Microsoft Store (WindowsApps)", "WindowsApps" in src)
check("hỏi py launcher + thư mục quen 310..314", "py -3 -c" in src and "Programs\\Python\\Python$ver" in src and '"314", "313", "312", "311", "310"' in src)
check("winget Python.Python.3.11 với PrependPath + launcher", "winget install --id Python.Python.3.11" in src and "PrependPath=1" in src and "Include_launcher=1" in src)
check("fallback python.org 3.11.9 theo kiến trúc", '$PY_VER = "3.11.9"' in src and "python.org/ftp/python/$PY_VER/python-$PY_VER-$arch.exe" in src and 'ARM64' in src)
check("làm mới PATH sau khi cài (registry → tiến trình)", 'GetEnvironmentVariable("Path", "Machine")' in src and 'GetEnvironmentVariable("Path", "User")' in src)
check("ưu tiên pythonw.exe cạnh python.exe (không cửa sổ đen)", 'Join-Path (Split-Path -Parent $py.exe) "pythonw.exe"' in src)
check("-GhProxy → URL tải + TUBECLI_GH_PROXY", '"$GhProxy$RAW" + "client/tubecli_connect.pyw"' in src and '$env:TUBECLI_GH_PROXY = $GhProxy' in src)
check("không có Python + -NoInstall → exit 2; cài xong vẫn không có → exit 3 kèm hướng dẫn", "exit 2" in src and "exit 3" in src and "python.org/downloads" in src)

print("3. chạy thật (powershell)")
ps = shutil.which("powershell") or shutil.which("pwsh")
if not ps:
    skipped += 1
    print("  skip  không có powershell trên máy này")
else:
    def run(args, env_extra=None):
        env = dict(os.environ)
        env.update(env_extra or {})
        return subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1)] + args,
                              capture_output=True, text=True, timeout=180, env=env)
    r = subprocess.run([ps, "-NoProfile", "-Command", "[void][scriptblock]::Create((Get-Content -Raw '%s')); 'parsed'" % PS1],
                       capture_output=True, text=True, timeout=60)
    check("parse bằng scriptblock::Create (cùng cách cloud gọi qua irm)", "parsed" in r.stdout, r.stderr[:300])
    r = run(["-Code", "TEST01", "-ClientPath", str(CLIENT), "-NoInstall", "-DryRun"])
    out = r.stdout
    m = re.search(r"\[dry-run\] (.+?python w?\.?exe|.+?pythonw?\.exe) \"(.+?)\" --code=TEST01", out, re.I)
    check("dry-run: tìm được Python trên máy, in lệnh pythonw \"<client>\" --code=TEST01, exit 0", r.returncode == 0 and m is not None and os.path.normcase(m.group(2)) == os.path.normcase(str(CLIENT)), out[-400:] + r.stderr[-300:])
    check("dry-run: báo [OK] Python x.y.z", re.search(r"\[OK\] Python 3\.\d+\.\d+", out) is not None, out[-300:])
    check("dry-run: không tải mạng khi có -ClientPath", "downloading" not in out)
    r2 = run(["-Code", "TEST01", "-ClientPath", str(CLIENT), "-NoInstall", "-DryRun", "-GhProxy", "https://gh-proxy.com/"])
    check("có -GhProxy vẫn dry-run OK", r2.returncode == 0 and "[dry-run]" in r2.stdout, r2.stdout[-200:])
    r3 = run(["-Code", "TEST01", "-ClientPath", str(ROOT / "client" / "khong_co.pyw"), "-NoInstall", "-DryRun"])
    check("client không tồn tại → exit 4", r3.returncode == 4, f"rc={r3.returncode} {r3.stdout[-200:]}")

print(f"\n{ok}/{ok + fail} PASS" + (f", {skipped} skip" if skipped else ""))
sys.exit(1 if fail else 0)
