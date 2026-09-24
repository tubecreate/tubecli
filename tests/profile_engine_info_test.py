# -*- coding: utf-8 -*-
"""Card hồ sơ trên Flow in nhân + Chrome mỗi hồ sơ SẼ chạy; xoá hồ sơ không xoá lan.

Run:  python tests/profile_engine_info_test.py     (exit 0 = pass)

profile_engine_info() phải đi đúng đường quyết định của browser_manager.js launch(),
nếu không card nói "ShardX 149" trong khi lần mở tới chạy 152. Không chạm mạng,
không đụng đĩa thật.
"""
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.browser import shardx_runtime as sx
from tubecli.extensions.browser import profile_manager as pm

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def ctx(**kw):
    base = {"policy": "latest", "latest": "152.0.7977.65",
            "shardx": ["152.0.7977.65", "149.0.7827.103"], "bas_usable": [],
            "rebuild": False, "stamp_build": {"152.0.7977.65": "4"}}
    base.update(kw)
    return base


i = sx.profile_engine_info("ShardX 149.0.7827.103", ctx())
check("ghim 149, chính sách latest → chạy 152", i["engine_version"] == "152.0.7977.65" and i["chrome_version"] == "152.0.7977.65", i)
check("đã mới nhất → không báo cập nhật", i["engine_update_to"] is None, i)
check("bản dựng lấy từ dấu cài đặt", i["engine_build"] == "4", i)

i = sx.profile_engine_info("ShardX 149.0.7827.103", ctx(policy="pinned"))
check("chính sách pinned → đúng bản ghim, báo có 152", i["engine_version"] == "149.0.7827.103" and i["engine_update_to"] == "152.0.7977.65", i)

i = sx.profile_engine_info("ShardX 149.0.7827.103", ctx(shardx=["149.0.7827.103"]))
check("chỉ có 149 → báo có bản 152", i["engine_update_to"] == "152.0.7977.65", i)

i = sx.profile_engine_info("ShardX 152.0.7977.65", ctx(rebuild=True))
check("cùng số nhưng ShardX dựng lại → báo cập nhật", i["engine_update_to"] == "152.0.7977.65", i)

i = sx.profile_engine_info("ShardX 152.0.7977.65", ctx(shardx=[]))
check("chưa cài nhân nào", not i["engine_installed"] and i["engine_update_to"] == "152.0.7977.65", i)

i = sx.profile_engine_info("149.0.7827.54", ctx(bas_usable=["30.8.0", "30.2.0"]))
check("ghim BAS 149 → gói 30.2.0", i["engine_family"] == "bas" and i["engine_version"] == "30.2.0"
      and i["chrome_version"] == "149.0.7827.54", i)

i = sx.profile_engine_info("149.0.7827.54", ctx(bas_usable=[]))
check("BAS không dùng được → mượn ShardX, có đánh dấu", i["engine_family"] == "shardx"
      and i["engine_substituted"] and i["engine_version"] == "152.0.7977.65", i)

i = sx.profile_engine_info(None, ctx(bas_usable=["30.8.0"]))
check("chưa ghim + có BAS → BAS mới nhất (Chromium 153)", i["engine_version"] == "30.8.0"
      and i["chrome_version"] == "153.0.8010.37", i)

check("parse ghim gạch nối", sx.parse_engine_pin("ShardX-152.0.7977.65") == ("shardx", "152.0.7977.65"))
check("parse ghim trống", sx.parse_engine_pin("latest") == (None, None))

with tempfile.TemporaryDirectory() as tmp:
    root = os.path.join(tmp, "profiles")
    os.makedirs(os.path.join(root, "a"))
    keep = os.path.join(tmp, "keep.txt")
    open(keep, "w").close()
    with mock.patch.object(pm, "PROFILES_DIR", root):
        for bad in ("..", ".", "", "a/..", "../profiles", os.path.join(tmp)):
            try:
                pm.delete_profile(bad)
                check(f"chặn tên xoá {bad!r}", False, "không ném lỗi")
            except ValueError:
                check(f"chặn tên xoá {bad!r}", True)
        check("thư mục cha còn nguyên", os.path.exists(keep) and os.path.isdir(root))
        check("xoá hồ sơ không tồn tại → False", pm.delete_profile("nope") is False)
        check("xoá hồ sơ thật", pm.delete_profile("a") is True and not os.path.exists(os.path.join(root, "a")))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
