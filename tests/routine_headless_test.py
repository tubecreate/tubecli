# -*- coding: utf-8 -*-
"""Lượt chạy theo lịch / Run now mở trình duyệt ẨN (15/9/2026).

User: "chế độ auto browser hằng ngày, trên Windows tắt chế độ bật browser trực tiếp, chỉ chạy
nền trên Flow". Trước đây run_agent_routine spawn với headless=False cứng.

Kiểm:
  A. Agent: routine_headless mặc định True; nhận False; None → True; to_dict/from_dict giữ; JSON
     cũ không có khoá vẫn nạp được (mặc định ẩn)
  B. server.py: spawn của lượt chạy dùng _routine_headless(agent), không còn headless=False cứng;
     _routine_headless đọc cờ (thiếu → True); AgentCreate/UpdateRequest có trường
  C. cloud AgentEditModal: khởi tạo mặc định true, gửi khi lưu, ô tick trong tab Lịch
     (chỉ kiểm nếu repo cloud có cạnh bên)

Run:  python tests/routine_headless_test.py
"""
import os
import re
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.core.agent import Agent  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {detail}"))
    if not ok:
        failures.append(label)


print("── A. model Agent ──────────────────────────────────────────")
a = Agent(id="a1", name="A", role="r")
check("A1 mặc định ẩn cửa sổ", a.routine_headless is True)
b = Agent(id="a2", name="B", role="r", routine_headless=False)
check("A2 nhận False (muốn cửa sổ thật)", b.routine_headless is False)
c = Agent(id="a3", name="C", role="r", routine_headless=None)
check("A3 None → mặc định True", c.routine_headless is True)
d = Agent.from_dict(b.to_dict())
check("A4 to_dict/from_dict giữ nguyên", b.to_dict().get("routine_headless") is False and d.routine_headless is False)
old = a.to_dict()
old.pop("routine_headless", None)
e = Agent.from_dict(old)
check("A5 JSON cũ không có khoá → nạp được, mặc định ẩn", e.routine_headless is True)

print("── B. lượt chạy trong server.py ───────────────────────────")
src = open(os.path.join(ROOT, "tubecli", "api", "server.py"), encoding="utf-8").read()
m = re.search(r"\ndef run_agent_routine\(.*?\n(?=\ndef |\n@app\.|\nclass )", src, re.S)
body = m.group(0) if m else ""
check("B1 spawn dùng _routine_headless(agent)", "headless=_routine_headless(agent)" in body, body[:80])
check("B2 hết headless=False cứng trong lượt chạy", "headless=False" not in body)
hm = re.search(r"\ndef _routine_headless\(agent\) -> bool:\n(.*?)\n(?=\ndef )", src, re.S)
check("B3 có helper _routine_headless", bool(hm))
if hm:
    ns = {}
    exec("def _routine_headless(agent) -> bool:\n" + hm.group(1), ns)
    f = ns["_routine_headless"]
    check("B4 helper: True/False theo cờ, thiếu cờ → True",
          f(SimpleNamespace(routine_headless=False)) is False and f(SimpleNamespace(routine_headless=True)) is True
          and f(SimpleNamespace()) is True and f(SimpleNamespace(routine_headless=None)) is False)
check("B5 AgentCreateRequest mặc định True, AgentUpdateRequest None (không đụng)",
      "    routine_headless: Optional[bool] = True\n" in src and "    routine_headless: Optional[bool] = None\n" in src)

print("── C. cloud AgentEditModal ─────────────────────────────────")
cloud = os.path.join(os.path.dirname(ROOT), "tubecli-cloud", "components", "flow", "AgentEditModal.js")
if os.path.isfile(cloud):
    js = open(cloud, encoding="utf-8").read()
    check("C1 khởi tạo: mặc định true trừ khi false", "routine_headless: agent.routine_headless !== false," in js)
    check("C2 gửi khi lưu", "routine_headless: !!f.routine_headless," in js)
    check("C3 ô tick trong tab Lịch + gợi ý", "set('routine_headless', e.target.checked)" in js and "t('flow.agent.routineHeadlessHint')" in js)
    for lang in ("en", "vi"):
        loc = open(os.path.join(os.path.dirname(ROOT), "tubecli-cloud", "lib", "locales", lang + ".js"), encoding="utf-8").read()
        check(f"C4 locale {lang} có 2 khoá", "'flow.agent.routineHeadless'" in loc and "'flow.agent.routineHeadlessHint'" in loc)
else:
    print("  (không có repo cloud cạnh bên — bỏ phần C)")

print()
if failures:
    print(f"{checks - len(failures)}/{checks} PASS — {len(failures)} HỎNG")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
