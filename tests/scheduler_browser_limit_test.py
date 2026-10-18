# -*- coding: utf-8 -*-
"""Trần trình duyệt chạy cùng lúc của bộ hẹn giờ (13/10/2026): global setting `max_scheduled_browsers` thắng biến môi
trường; giá trị hỏng / < 1 về mặc định; đọc lại mỗi lần gọi (đổi trên trang Settings không cần khởi động lại)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli import config            # noqa: E402
from tubecli.core import scheduler as S  # noqa: E402

ok = fail = 0


def check(name, got, want):
    global ok, fail
    if got == want:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


real = config.get_global_setting
store = {}
config.get_global_setting = lambda k, d=None: store.get(k, d)
try:
    S.MAX_CONCURRENT_AGENT_BROWSERS, env_default = 3, S.MAX_CONCURRENT_AGENT_BROWSERS
    check("chưa đặt → biến môi trường", S.max_concurrent_browsers(), 3)
    store[S.MAX_BROWSERS_SETTING] = 5
    check("đặt 5 → 5", S.max_concurrent_browsers(), 5)
    store[S.MAX_BROWSERS_SETTING] = "7"
    check("chuỗi số → số", S.max_concurrent_browsers(), 7)
    for bad in (0, -2, "abc", None, ""):
        store[S.MAX_BROWSERS_SETTING] = bad
        check(f"hỏng {bad!r} → mặc định", S.max_concurrent_browsers(), 3)
    S.MAX_CONCURRENT_AGENT_BROWSERS = 0
    store.pop(S.MAX_BROWSERS_SETTING)
    check("môi trường 0 → tối thiểu 1", S.max_concurrent_browsers(), 1)
    S.MAX_CONCURRENT_AGENT_BROWSERS = env_default
finally:
    config.get_global_setting = real

print(f"\n{ok}/{ok + fail} PASS")
sys.exit(1 if fail else 0)
