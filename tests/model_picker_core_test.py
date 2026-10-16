# -*- coding: utf-8 -*-
"""Phía lõi của bảng chọn model trên cloud (bước 3, 16/10/2026) — ba việc từng làm bảng «đơ» / thiếu:

  A. PUT /api/v1/settings {default_model}: đổi model MỌI agent nhưng ghi agents.json MỘT lần, ngoài event loop
     (trước: update() từng agent = N lần rewrite trọn file ngay trên loop).
  B. GET /api/v1/cloud-api/9router/status: requests.get chặn 3–10 s → chạy trong thread (loop vẫn trả lời).
  C. POST /api/v1/cloud-api/cloudflare/profiles: lưu xong tự tải danh sách model (test_key không làm).
  D. POST /api/v1/apps/{name}/start: bật app đã cài — có unit systemd thì systemctl start, không thì chạy binary rời;
     chưa cài → 409; đang chạy → running ngay; app lạ → 404.

Run:  python tests/model_picker_core_test.py     (exit 0 = pass). Không mạng, không ghi vào data/ thật.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="model_picker_core_"))
cfg.DATA_DIR = TMP

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


# ── A. một lần ghi ─────────────────────────────────────────────────────────────
from tubecli.core import agent as AG  # noqa: E402

am = AG.AgentManager.__new__(AG.AgentManager)
am.agents = {}
am.agents_file = TMP / "agents.json"
saves = []
am._save = lambda: saves.append(time.time())       # đếm lượt ghi
for i in range(5):
    a = AG.Agent(name=f"a{i}", model="old-model")
    am.agents[a.id] = a
n = am.set_model_for_all("new-model")
check("A1 đổi model cho mọi agent, ghi đúng MỘT lần", n == 5 and len(saves) == 1 and all(x.model == "new-model" for x in am.agents.values()),
      (n, len(saves)))
saves.clear()
n = am.set_model_for_all("new-model")
check("A2 không có gì đổi → không ghi", n == 0 and not saves, (n, saves))
src = (ROOT / "tubecli/extensions/webui/routes.py").read_text(encoding="utf-8")
body = src[src.index("async def save_global_settings"):src.index("# ── Pipeline Monitor API")]
check("A3 PUT /settings gọi set_model_for_all trong thread, không lặp update() từng agent",
      "await asyncio.to_thread(agent_manager.set_model_for_all, new_model)" in body and "agent_manager.update(agent.id" not in body)

# ── B. 9router/status không chặn loop ──────────────────────────────────────────
from tubecli.extensions.cloud_api import routes as RT  # noqa: E402
import requests  # noqa: E402

real_get = requests.get
ticks = []


def slow_get(url, headers=None, timeout=None):
    time.sleep(0.4)                                   # giả 9Router trả lời chậm
    class R:
        status_code = 200
        def json(self):
            return {"data": [{"id": "ag/gemini-3.8-flash"}, {"id": "ag/gpt-5.5"}]}
    return R()


async def b_run():
    requests.get = slow_get
    try:
        async def ticker():
            for _ in range(8):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)
        st, _ = await asyncio.gather(RT.api_9router_status(), ticker())
        return st
    finally:
        requests.get = real_get


st = asyncio.run(b_run())
gaps = [b - a for a, b in zip(ticks, ticks[1:])]
check("B1 /9router/status trả danh sách sống", st.get("running") is True and st.get("models") == ["ag/gemini-3.8-flash", "ag/gpt-5.5"], st)
check("B2 … trong lúc requests.get ngủ 0,4 s, event loop vẫn chạy (bước đếm ≤ 0,2 s)", gaps and max(gaps) < 0.2, [round(g, 3) for g in gaps])

# ── C. lưu Cloudflare → tự tải model ──────────────────────────────────────────
from tubecli.extensions.cloud_api import extension as EXT  # noqa: E402

km = EXT.key_manager
calls = []
old_add, old_refresh = km.add_cloudflare_key, km.refresh_models
km.add_cloudflare_key = lambda tok, acc, label, email: (calls.append(("add", tok, acc, label, email)) or {"status": "success", "label": label})
km.refresh_models = lambda p: (calls.append(("refresh", p)) or {"status": "success", "count": 7, "models": ["@cf/a"] * 7})
try:
    r = asyncio.run(RT.api_add_cloudflare_profile(RT.AddCloudflareKeyRequest(api_token="k", account_id="acc", email="me@x.com")))
    check("C1 lưu xong gọi refresh_models('cloudflare') và trả model_count",
          [c[0] for c in calls] == ["add", "refresh"] and calls[0][4] == "me@x.com" and r.get("models_refreshed") is True and r.get("model_count") == 7, (calls, r))
    calls.clear()
    km.refresh_models = lambda p: (calls.append(("refresh", p)) or {"status": "error", "message": "no creds"})
    r = asyncio.run(RT.api_add_cloudflare_profile(RT.AddCloudflareKeyRequest(api_token="k", account_id="acc")))
    check("C2 tải model hỏng → vẫn success của bước lưu, kèm models_error", r.get("status") == "success" and r.get("models_refreshed") is False and "no creds" in r.get("models_error", ""), r)
finally:
    km.add_cloudflare_key, km.refresh_models = old_add, old_refresh

# ── D. bật app ────────────────────────────────────────────────────────────────
from tubecli.api import app_routes as AP  # noqa: E402
from fastapi import HTTPException  # noqa: E402

AP._STATUS.clear()
old = {k: getattr(AP, k) for k in ("_port_alive", "_sudo")}
old_which, old_exists, old_popen = AP.shutil.which, AP.os.path.exists, AP.subprocess.Popen
sudo_calls, popen_calls = [], []
alive = {"v": False}
AP._port_alive = lambda port: alive["v"]
AP._sudo = lambda args, timeout=600: (sudo_calls.append(list(args)) or (0, ""))
AP.subprocess.Popen = lambda argv, **kw: (popen_calls.append((argv, kw)) or None)
try:
    try:
        asyncio.run(AP.start_app("nope"))
        check("D1 app lạ → 404", False)
    except HTTPException as e:
        check("D1 app lạ → 404", e.status_code == 404, e.status_code)
    AP.shutil.which = lambda b: None
    try:
        asyncio.run(AP.start_app("9router"))
        check("D2 chưa cài → 409", False)
    except HTTPException as e:
        check("D2 chưa cài → 409", e.status_code == 409, e.status_code)
    AP.shutil.which = lambda b: ("/usr/bin/systemctl" if b == "systemctl" else "/usr/local/bin/9router")
    alive["v"] = True
    r = asyncio.run(AP.start_app("9router"))
    check("D3 đang chạy sẵn → running ngay, không bật lại", r.get("status") == "running" and not sudo_calls and not popen_calls, r)
    # có unit systemd → systemctl start (worker chạy đồng bộ cho test)
    alive["v"] = False
    AP.os.path.exists = lambda p: p == "/etc/systemd/system/9router.service"
    AP.time.sleep = lambda s: alive.__setitem__("v", True)     # vòng chờ cổng: lượt đầu chưa sống, lượt sau sống
    AP._start_worker("9router", AP.APP_REGISTRY["9router"])
    check("D4 có unit → systemctl start 9router.service, rồi running",
          sudo_calls and sudo_calls[-1][:2] == ["systemctl", "start"] and AP._STATUS["9router"]["status"] == "running", (sudo_calls, AP._STATUS.get("9router")))
    # không có unit (Windows / không systemd) → chạy binary rời
    sudo_calls.clear(); alive["v"] = False
    AP.os.path.exists = lambda p: False
    AP._start_worker("9router", AP.APP_REGISTRY["9router"])
    argv = popen_calls[-1][0] if popen_calls else []
    check("D5 không unit → Popen binary rời với --port 20128, tách phiên; rồi running",
          argv[:1] == ["/usr/local/bin/9router"] and "20128" in argv and not sudo_calls and AP._STATUS["9router"]["status"] == "running"
          and (popen_calls[-1][1].get("start_new_session") or popen_calls[-1][1].get("creationflags")), (argv, AP._STATUS.get("9router")))
finally:
    for k, v in old.items():
        setattr(AP, k, v)
    AP.shutil.which, AP.os.path.exists, AP.subprocess.Popen = old_which, old_exists, old_popen
    import importlib
    AP.time = importlib.import_module("time")

import shutil  # noqa: E402

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
