# The browser-death reason must NAME RAM, with the numbers, from evidence the
# Python side collected while the browser was still alive.
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.browser import routes as R

# 1. the counter never raises, whatever the OS
v = R._oom_kill_counter()
assert v is None or isinstance(v, int), v
print(f"1 counter    : _oom_kill_counter() -> {v!r} (None trên Windows là đúng)")

# 2. SIGKILL → an OOM reason that names RAM and the numbers
R._available_ram_mb = lambda: 2100          # what the gauge shows AFTER the kill
R._preview_deaths["test5"] = {"at": time.time(), "code": -9, "ram_start": 940,
                              "ram_low": 88, "oom_delta": None, "sigkilled": True}
r = R._oom_death_reason("test5")
assert r and r["reason"] == "oom", r
m = r["message_vi"]
assert "hết RAM" in m and "88 MB" in m and "940 MB" in m, m
assert "2100 MB" in m and "trả lại" in m, "phải giải thích vì sao đồng hồ RAM đang báo trống"
assert r["free"] == 88 and "exit_code=-9" in r["detail"] and "ram_low=88MB" in r["detail"]
print("2 sigkill    : reason=oom | nêu đáy 88 MB, lúc mở 940 MB, và vì sao giờ thấy 2100 MB trống")

# 3. kernel OOM counter moved → still an OOM, even with an ordinary exit code
R._preview_deaths["t2"] = {"at": time.time(), "code": 1, "ram_start": 800,
                           "ram_low": 120, "oom_delta": 2, "sigkilled": False}
assert (R._oom_death_reason("t2") or {}).get("reason") == "oom"
print("3 counter+   : oom_kill của nhân tăng 2 → vẫn kết luận hết RAM")

# 4. an ordinary crash is NOT reported as RAM
R._preview_deaths["t3"] = {"at": time.time(), "code": 1, "ram_start": 3000,
                           "ram_low": 2900, "oom_delta": 0, "sigkilled": False}
assert R._oom_death_reason("t3") is None
print("4 khong nham : thoát mã 1, RAM dư, bộ đếm không đổi → KHÔNG đổ cho RAM")

# 5. a stale record does not haunt the next attempt
R._preview_deaths["t4"] = {"at": time.time() - 600, "code": -9, "ram_start": 500,
                           "ram_low": 60, "oom_delta": None, "sigkilled": True}
assert R._oom_death_reason("t4") is None
assert R._oom_death_reason("chua-bao-gio-mo") is None
print("5 het han    : bản ghi cũ 10 phút / hồ sơ chưa từng mở → None")

# 6. the watcher records a real process death (no browser needed)
import subprocess
proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(7)"])
R._watch_preview_death(proc, "watched", 1234, 5)
note = R._preview_deaths["watched"]
assert note["code"] == 7 and note["ram_start"] == 1234 and note["sigkilled"] is False, note
print("6 watcher    : ghi đúng mã thoát 7, giữ RAM lúc mở, không gán nhầm SIGKILL")

# 7. the per-session estimate is realistic and still overridable
assert R.PREVIEW_SESSION_MB_DEFAULT == 800, R.PREVIEW_SESSION_MB_DEFAULT
low = R._low_memory_reason(900, R._preview_session_mb(), in_flight_others=1)
assert low and low["reason"] == "low_memory" and low["need"] == 1600
assert R._low_memory_reason(3000, R._preview_session_mb(), 0) is None
print(f"7 uoc luong  : {R.PREVIEW_SESSION_MB_DEFAULT} MB/phiên — còn 900 MB mà cần 1600 MB → từ chối sớm, kèm số")
print()
print("ALL 7 GROUPS PASSED")
