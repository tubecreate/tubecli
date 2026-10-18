"""Trần trình duyệt chạy cùng lúc là THIẾT LẬP của máy (user 13/10: «đặt trong setting global»; 18/10: «node browser
hiển thị số browser chạy cùng lúc tối đa, chỉnh thủ công hoặc API»).

Chạy:  python tests/browser_cap_setting_test.py     (exit 0 = pass)

Luật canh:
  1. scheduler.max_concurrent_browsers(): global setting `max_scheduled_browsers` → env → 2 (chi tiết ở
     scheduler_browser_limit_test.py); clamp_browser_cap kẹp 1..20, chuỗi lạ → None.
  2. GET /api/v1/settings trả khoá (mặc định có trong _default_settings); PUT kẹp giá trị trước khi ghi — số vô
     nghĩa thì bỏ khoá, không ghi rác (scheduler đọc lại mỗi nhịp).
  3. Trang Settings của bảng điều khiển có ô «Browsers open at once» + 9 locale; __version__ ≥ .203.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.core import scheduler as S  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  PASS", name)
    else:
        fail += 1
        print(f"  FAIL {name}  {detail}")


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


print("1. scheduler")
check("MAX_BROWSERS_SETTING = max_scheduled_browsers", S.MAX_BROWSERS_SETTING == "max_scheduled_browsers")
check("clamp: '5' → 5, 3.7 → 3", S.clamp_browser_cap("5") == 5 and S.clamp_browser_cap(3.7) == 3)
check("clamp: 0 → 1, 99 → 20, -4 → 1", S.clamp_browser_cap(0) == 1 and S.clamp_browser_cap(99) == 20 and S.clamp_browser_cap(-4) == 1)
check("clamp: rác → None", S.clamp_browser_cap("abc") is None and S.clamp_browser_cap(None) is None and S.clamp_browser_cap({}) is None)
check("bộ hẹn giờ dùng max_concurrent_browsers() ở cửa «busy»", "limit = max_concurrent_browsers()" in read("tubecli/core/scheduler.py")
      and "if running_count >= limit:" in read("tubecli/core/scheduler.py"))

print("2. API")
routes = read("tubecli/extensions/webui/routes.py")
check("GET /settings có mặc định max_scheduled_browsers", '"max_scheduled_browsers": max_browsers,' in routes)
check("PUT /settings kẹp qua clamp_browser_cap", 'n = clamp_browser_cap(body.get("max_scheduled_browsers"))' in routes
      and 'body.pop("max_scheduled_browsers", None)' in routes and 'body["max_scheduled_browsers"] = n' in routes)
check("PUT kẹp TRƯỚC khi ghi đĩa", routes.index('clamp_browser_cap(body.get("max_scheduled_browsers"))') < routes.index("existing.update(body)"))

print("3. bảng điều khiển + locale + phiên bản")
html = read("tubecli/extensions/webui/static/index.html")
check("ô set-max-browsers 1..20 gọi autoSaveSetting", 'id="set-max-browsers"' in html and "autoSaveSetting('max_scheduled_browsers'" in html)
check("app.js đổ giá trị vào ô", "document.getElementById('set-max-browsers').value = s.max_scheduled_browsers" in read("tubecli/extensions/webui/static/app.js"))
for lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
    d = json.loads(read(f"tubecli/extensions/webui/locales/{lang}.json"))
    check(f"locale {lang} có settings.max_browsers + hint", bool(d.get("settings.max_browsers")) and bool(d.get("settings.max_browsers_hint")))
mv = re.search(r'^__version__ = "2026\.08\.09\.(\d+)"', read("tubecli/__init__.py"), re.M)
check("__version__ >= .203", mv is not None and int(mv.group(1)) >= 203, mv and mv.group(0))

print(f"\n{ok}/{ok + fail} PASS")
sys.exit(1 if fail else 0)
