# -*- coding: utf-8 -*-
"""Cai lai extension tu Cho thi co hen khoi dong lai khong.

Khong the that su giet tien trinh test, nen thay `_schedule_restart` bang ban
gia va xem no CO duoc goi dung luc khong: cai moi thi khong, cai de len ban dang
chay thi co. Do la toan bo logic can dung.

Chay: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/market_restart_test.py
"""
import base64
import gzip
import json
import os
import sys
import tempfile

sys.path.insert(0, r"c:\tubecreate-vue\tubecli")

TMP = tempfile.mkdtemp(prefix="mkt_")
os.environ["TUBECLI_DATA_DIR"] = TMP

FAILS = []
COUNT = [0]


def check(cond, msg):
    COUNT[0] += 1
    if not cond:
        FAILS.append(msg)
        print("  FAIL", msg)


import tubecli.api.server as srv                      # noqa: E402
from tubecli.extensions.market import routes as mkt   # noqa: E402

calls = []
srv._schedule_restart = lambda delay=2.0: (calls.append(delay), True)[1]

print("== A. quyet dinh khoi dong lai")
r = mkt._maybe_restart_after_install(was_installed=False, force=False, auto=True)
check(r["restart_required"] is False and r["restarting"] is False,
      f"cai MOI, nap nong tron lot -> khong khoi dong lai: {r}")
check(not calls, "khong goi _schedule_restart cho ca cai moi")

r = mkt._maybe_restart_after_install(was_installed=True, force=False, auto=True)
check(r["restart_required"] is True and r["restarting"] is True,
      f"CAP NHAT de len ban dang chay -> khoi dong lai: {r}")
check(len(calls) == 1, "co goi _schedule_restart dung mot lan")
check(r["restart_seconds"] > 0, "co bao bao nhieu giay de trang con doi")

r = mkt._maybe_restart_after_install(was_installed=False, force=True, auto=True)
check(r["restarting"] is True, f"nap nong HONG -> van phai khoi dong lai: {r}")

r = mkt._maybe_restart_after_install(was_installed=True, force=False, auto=False)
check(r["restart_required"] is True and r["restarting"] is False,
      f"nguoi dung tat auto_restart -> bao can, nhung KHONG tu thoat: {r}")

print("== B. khong hen duoc thi noi that")
srv._schedule_restart = lambda delay=2.0: False
r = mkt._maybe_restart_after_install(was_installed=True, force=False, auto=True)
check(r["restart_required"] is True and r["restarting"] is False,
      f"chay tay khong co systemd -> noi that: {r}")

print("== C. fail-safe cua _schedule_restart")
import importlib                                       # noqa: E402
importlib.reload  # giu ten cho ro y
srv._schedule_restart = srv.__dict__["_schedule_restart"]  # tra lai ban that
old_env = {k: os.environ.pop(k, None) for k in ("INVOCATION_ID", "JOURNAL_STREAM")}
check(srv._under_systemd() is False, "khong co bien systemd -> khong nhan nham")
os.environ["INVOCATION_ID"] = "x"
check(srv._under_systemd() is True, "co INVOCATION_ID -> biet la systemd dang trong")
for k, v in old_env.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

print("== D. route /api/v1/system/restart")
paths = {getattr(r, "path", "") for r in srv.app.routes}
check("/api/v1/system/restart" in paths, "co route khoi dong lai theo yeu cau")

print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} passed")
if FAILS:
    print("FAILED:")
    for m in FAILS:
        print(" -", m)
    sys.exit(1)
print("OK")
