# -*- coding: utf-8 -*-
"""File Manager — lối tắt thư mục (GET/POST/DELETE /shortcuts).

Chạy: python tests/fm_shortcuts_test.py
Kiểm: ghim thư mục có thật; từ chối file và đường dẫn bị chặn; không trùng; bỏ ghim;
cờ `exists` tắt khi thư mục bị xoá; lưu ra <data>/file_manager/shortcuts.json.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# KHÔNG dùng %TEMP%: nó nằm trong ~/AppData/Local, tức vùng BLOCKED_PATHS của sandbox
# (đúng chốt kiểm mà route lối tắt phải đi qua) — thư mục tạm đặt trong repo.
_TMP_ROOT = os.path.join(os.path.dirname(HERE), "_tmp_tests")
os.makedirs(_TMP_ROOT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="fm_shortcuts_", dir=_TMP_ROOT)
os.environ["TUBECLI_DATA_DIR"] = os.path.join(TMP, "data")
os.makedirs(os.environ["TUBECLI_DATA_DIR"], exist_ok=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import tubecli.extensions.file_manager.routes as R  # noqa: E402

COUNT = [0]
FAILS = []


def check(cond, msg):
    COUNT[0] += 1
    print(("  ok  " if cond else "  FAIL") + " " + msg)
    if not cond:
        FAILS.append(msg)


# thư mục lưu lối tắt → thư mục tạm (không đụng data thật)
R._shortcuts_file = lambda: os.path.join(TMP, "shortcuts.json")

app = FastAPI()
app.include_router(R.router_fm)
c = TestClient(app)
P = R.router_fm.prefix + "/shortcuts"

folder = os.path.join(TMP, "Videos ABC")
os.makedirs(folder)
afile = os.path.join(TMP, "note.txt")
open(afile, "w").write("x")

r = c.get(P)
check(r.status_code == 200 and r.json()["shortcuts"] == [], "danh sách rỗng lúc đầu")

r = c.post(P, json={"path": folder})
check(r.status_code == 200 and [s["path"] for s in r.json()["shortcuts"]] == [os.path.normpath(folder)], f"ghim thư mục: {r.status_code} {r.text[:120]}")
check(r.json()["shortcuts"][0]["name"] == "Videos ABC" and r.json()["shortcuts"][0]["exists"] is True, "tên = tên thư mục, exists=True")

r = c.post(P, json={"path": folder + os.sep})
check(r.status_code == 200 and len(r.json()["shortcuts"]) == 1, "ghim lại cùng thư mục (có dấu / cuối) → không trùng")

r = c.post(P, json={"path": afile})
check(r.status_code == 400, f"ghim FILE bị từ chối: {r.status_code}")

r = c.post(P, json={"path": os.path.join(TMP, "khong_co")})
check(r.status_code in (400, 403, 404), f"thư mục không có bị từ chối: {r.status_code}")

r = c.post(P, json={"path": ""})
check(r.status_code == 400, "thiếu path → 400")

r = c.post(P, json={"path": folder, "name": "Kho video của tôi"})
check(r.status_code == 200 and r.json()["shortcuts"][0]["name"] == "Kho video của tôi", "đặt tên riêng khi ghim")

with open(os.path.join(TMP, "shortcuts.json"), encoding="utf-8") as f:
    saved = json.load(f)
check(saved["shortcuts"][0]["path"] == os.path.normpath(folder), "lưu ra shortcuts.json trong thư mục data")

shutil.rmtree(folder)
r = c.get(P)
check(r.json()["shortcuts"][0]["exists"] is False, "thư mục bị xoá → exists=False (vẫn giữ lối tắt)")

r = c.delete(P, params={"path": folder})
check(r.status_code == 200 and r.json()["removed"] is True and r.json()["shortcuts"] == [], "bỏ ghim")
r = c.delete(P, params={"path": folder})
check(r.status_code == 200 and r.json()["removed"] is False, "bỏ ghim cái không có → không lỗi")

# đường dẫn bị chặn (BLOCKED_PATHS của sandbox) không ghim được
blocked = [p for p in ("/etc", "C:\\Windows\\System32") if os.path.isdir(p)]
if blocked:
    r = c.post(P, json={"path": blocked[0]})
    check(r.status_code in (400, 403), f"đường dẫn bị chặn {blocked[0]} → {r.status_code}")

# file hỏng → coi như rỗng, không nổ
open(os.path.join(TMP, "shortcuts.json"), "w").write("{not json")
r = c.get(P)
check(r.status_code == 200 and r.json()["shortcuts"] == [], "shortcuts.json hỏng → danh sách rỗng, không 500")

# giao diện có đủ móc
ST = os.path.join(os.path.dirname(HERE), "tubecli", "extensions", "file_manager", "static")
html = open(os.path.join(ST, "file_manager.html"), encoding="utf-8").read()
js = open(os.path.join(ST, "file_manager.js"), encoding="utf-8").read()
acts = open(os.path.join(ST, "fm_actions.js"), encoding="utf-8").read()
check('id="fmShortcuts"' in html and 'data-fm-action="shortcut-toggle"' in html and 'data-fm-dir-only' in html, "HTML: mục Lối tắt + menu chuột phải")
check("loadShortcuts" in js and "toggleShortcut" in js and "renderShortcuts" in js and "data-fm-dir-only" in js, "JS: nạp/ghim/vẽ lối tắt, ẩn mục với file")
check("'shortcut-toggle': actShortcutToggle" in acts and "'shortcut-remove': actShortcutRemove" in acts, "fm_actions: đăng ký hành động")
for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
    with open(os.path.join(os.path.dirname(ST), "locales", lang + ".json"), encoding="utf-8") as f:
        d = json.load(f)
    check(all(k in d for k in ("fm.nav.shortcuts", "fm.browse.shortcut_add", "fm.browse.shortcut_remove", "fm.shortcuts.hint")), f"locale {lang} có khoá lối tắt")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    print("FAILED:")
    for m in FAILS:
        print(" -", m)
    sys.exit(1)
print("OK")
