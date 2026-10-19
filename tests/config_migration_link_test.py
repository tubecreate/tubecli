# -*- coding: utf-8 -*-
"""BƯỚC DỜI FILE extension (config.migrate_and_link_extensions_data) KHÔNG ĐƯỢC ĐÈ BẢN MỚI BẰNG BẢN CŨ (19/10/2026).

Từ ce4b1c3 (13/10) auth_manager ghi nguyên tử ⇒ hard link data/auth_manager.json ↔ extensions_data/auth_manager/…
đứt ngay lần lưu đầu; bản cũ đứng yên. Bước dời từng `os.remove(bản mới)` + move(bản cũ) ở MỖI lần nạp config (khởi
động máy chủ, cả script test) ⇒ token Google cấp sau lần liên kết cuối bị xoá. Giờ giữ bản sửa sau cùng, cất bản kia.

  A. bản mới SỬA SAU (ca thật): giữ bản mới, bản cũ → .legacy.bak, rồi đường cũ liên kết lại vào bản mới
  B. bản cũ sửa sau: bản cũ thành bản mới, bản mới cũ → .legacy.bak
  C. đã liên kết: không đụng gì; chỉ có bản cũ: chuyển sang như trước

Run:  python tests/config_migration_link_test.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.config as cfg  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write(p, data, age=0):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    t = time.time() - age
    os.utime(p, (t, t))


TMP = Path(tempfile.mkdtemp(prefix="cfgmig-"))
saved = (cfg.DATA_DIR, cfg.EXTENSIONS_DATA_DIR)
try:
    cfg.DATA_DIR = TMP / "data"
    cfg.EXTENSIONS_DATA_DIR = TMP / "data" / "extensions_data"
    old = cfg.DATA_DIR / "auth_manager.json"
    new = cfg.EXTENSIONS_DATA_DIR / "auth_manager" / "auth_manager.json"

    print("A. bản mới sửa sau (link đứt vì ghi nguyên tử)")
    write(old, {"tokens": {"t_old": 1}}, age=6 * 86400)
    write(new, {"tokens": {"t_old": 1, "t_new_google": 2}}, age=60)
    cfg.migrate_and_link_extensions_data()
    ok(read(new) == {"tokens": {"t_old": 1, "t_new_google": 2}}, "bản mới GIỮ NGUYÊN (token mới còn)", read(new))
    ok(read(str(old) + ".legacy.bak") == {"tokens": {"t_old": 1}}, "bản cũ cất .legacy.bak")
    ok(old.exists() and os.path.samefile(old, new), "đường cũ liên kết lại vào bản mới")
    cfg.migrate_and_link_extensions_data()
    ok(read(new)["tokens"].get("t_new_google") == 2, "chạy lại lần nữa vẫn không mất gì")

    print("B. bản cũ sửa sau")
    shutil.rmtree(TMP / "data")
    write(new, {"v": "older"}, age=3600)
    write(old, {"v": "newer"}, age=10)
    cfg.migrate_and_link_extensions_data()
    ok(read(new) == {"v": "newer"} and read(str(new) + ".legacy.bak") == {"v": "older"},
       "bản cũ (mới hơn) thành bản dùng; bản kia cất .legacy.bak", read(new))

    print("C. đã liên kết / chỉ có bản cũ")
    before = new.stat().st_mtime
    cfg.migrate_and_link_extensions_data()
    ok(read(new) == {"v": "newer"} and new.stat().st_mtime == before, "đã liên kết ⇒ không đụng")
    shutil.rmtree(TMP / "data")
    write(old, {"only": "old"})
    cfg.migrate_and_link_extensions_data()
    ok(read(new) == {"only": "old"} and not Path(str(new) + ".legacy.bak").exists(), "chỉ có bản cũ ⇒ chuyển như trước")

    src = (ROOT / "tubecli" / "config.py").read_text(encoding="utf-8")
    body = src[src.index("def migrate_and_link_extensions_data"):]
    body = body[:body.index("# Link the files")]
    ok("os.remove(new_file_path)" not in body, "không còn xoá bản ở đường mới")
finally:
    cfg.DATA_DIR, cfg.EXTENSIONS_DATA_DIR = saved
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
