"""Chromium NGOÀI SỔ đang giữ hồ sơ: có người lái → báo bận + mời xem; không ai lái → dọn rồi mở.

Run:  python tests/untracked_holder_test.py     (exit 0 = pass)

Bối cảnh (7/10/2026, máy Windows, hồ sơ «muse»): bấm Mở → «Failed after 3 attempts … Failed to launch the
browser process». Một Chromium sót lại qua lần khởi động lại TubeCLI vẫn giữ hồ sơ, không nằm trong sổ nên
preflight không thấy và force-kill (chỉ chạy khi sổ còn ghi) không dọn; Windows không có đường gặt qua
SingletonLock như Linux → Chrome mới chuyển lệnh sang con cũ rồi thoát. KHÔNG được dọn mù: core/muse.py cố ý
nối lại đúng loại trình duyệt này để vẽ ảnh tiếp — nên tách theo «có kết nối CDP đang mở không».
"""
import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.browser import routes as R  # noqa: E402
from tubecli.extensions.browser import profile_manager as PM  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


# ── A. preflight + lời mời xem (thuần, holder giả) ─────────────────────────────
_orig_ram, _orig_blk = R._available_ram_mb, R.check_launch_blockers
try:
    R.check_launch_blockers = lambda p: None
    R._available_ram_mb = lambda: 4000
    driven = {"pid": 4242, "started_at": time.time() - 600, "cdp_port": 65454, "cdp_clients": 1}
    r = R.preview_preflight("muse", {}, [], in_flight_others=0, holder=driven)
    check("A1 có người lái → profile_busy by=manual", r and r.get("reason") == "profile_busy"
          and r.get("by") == "manual" and r.get("untracked") is True, r)
    check("A2 mins từ create_time", r and r.get("mins") == 10, r)
    att = (r or {}).get("attach") or {}
    check("A3 mời xem qua CDP cổng đã dò", att.get("available") is True and att.get("mode") == "cdp"
          and att.get("cdp_port") == 65454 and att.get("endpoint") == "/api/v1/browser/preview/attach", att)
    idle = dict(driven, cdp_clients=0)
    check("A4 không ai lái → preflight cho qua (route sẽ dọn)",
          R.preview_preflight("muse", {}, [], in_flight_others=0, holder=idle) is None)
    check("A5 không có holder → như cũ",
          R.preview_preflight("muse", {}, [], in_flight_others=0) is None)
    inst_agent = [{"profile": "muse", "_process": type("P", (), {"poll": lambda self: None})(),
                   "_agent_id": "a1", "started_at": None, "pid": 1}]
    r = R.preview_preflight("muse", {}, inst_agent, in_flight_others=0, holder=driven)
    check("A6 phiên trong sổ thắng holder (by=agent)", r and r.get("by") == "agent", r)
finally:
    R._available_ram_mb, R.check_launch_blockers = _orig_ram, _orig_blk

# ── B. dò thật: một tiến trình mang --user-data-dir=<hồ sơ> + khoá hồ sơ ───────
tmp = tempfile.mkdtemp(prefix="holder_test_")
_orig_pd = PM.PROFILES_DIR
child = None
handle = None
try:
    PM.PROFILES_DIR = tmp
    prof = os.path.join(tmp, "fakeprof")
    os.makedirs(prof)
    check("B1 không dấu khoá → không quét, None", R._untracked_holder("fakeprof") is None)

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                              f"--user-data-dir={prof}"])
    time.sleep(0.8)
    if os.name == "nt":
        # Chromium mở «lockfile» không chia sẻ — làm y vậy bằng CreateFileW share=0.
        import ctypes
        lf = os.path.join(prof, "lockfile")
        open(lf, "w").close()
        check("B2 lockfile mở được (khoá cũ) → không giữ", R._profile_maybe_held("fakeprof") is False)
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        handle = k32.CreateFileW(lf, 0x80000000, 0, None, 3, 0, None)
        check("B3 lockfile bị khoá → đang giữ", R._profile_maybe_held("fakeprof") is True)
    else:
        os.symlink(f"host-{child.pid}", os.path.join(prof, "SingletonLock"))
        check("B3 SingletonLock → đang giữ", R._profile_maybe_held("fakeprof") is True)
    h = R._untracked_holder("fakeprof")
    check("B4 tìm đúng tiến trình giữ hồ sơ", h and h.get("pid") == child.pid, h)
    check("B5 không cổng CDP, không ai lái", h and h.get("cdp_port") == 0 and h.get("cdp_clients") == 0, h)
    check("B6 hồ sơ có tên là tiền tố KHÔNG bị nhận nhầm", R._untracked_holder("fakepro") is None)
finally:
    if handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass
    if child:
        child.kill()
        child.wait(5)
    PM.PROFILES_DIR = _orig_pd
    shutil.rmtree(tmp, ignore_errors=True)

# ── C. route: dò holder trước preflight; bỏ hoang mới dọn; attach thử ngoài sổ ─
src = (ROOT / "tubecli" / "extensions" / "browser" / "routes.py").read_text(encoding="utf-8")
i_h = src.find("_holder = await asyncio.to_thread(_untracked_holder, profile)")
i_pf = src.find("in_flight_others=_in_flight, holder=_holder)")
i_kill = src.find("elif force and _holder:")
i_spawn = src.find("proc, port, early_output = await _spawn_preview_server(profile, url)")
check("C1 thứ tự: dò → preflight → dọn bỏ hoang → spawn", 0 < i_h < i_pf < i_kill < i_spawn,
      (i_h, i_pf, i_kill, i_spawn))
check("C2 /preview/attach thử Chromium ngoài sổ khi sổ không có phiên",
      'if not cdp_port and why == "no_session":' in src and "_h = await asyncio.to_thread(_untracked_holder, profile)" in src)

if failures:
    print("\n".join("FAIL " + f for f in failures))
    sys.exit(1)
print(f"{checks}/{checks} PASS")
