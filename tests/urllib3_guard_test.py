# -*- coding: utf-8 -*-
"""yt-dlp bọc chồng urllib3 làm requests hỏng + danh sách nhân thiếu nhân đã cài (24/11/2026, contabo: «Download failed:
download failed after 4 attempts: 'Urllib3PercentREOverride' object has no attribute 'sub'», «server mới 158 mà contabo vẫn
tải 157», «tải mới không được thì xài bản đã cài, không chọn được nhân khác»).

  A. yt-dlp THẬT: nạp lại kiểu ytdlp_manager nhiều lần → vẫn đúng MỘT lớp bọc, .sub (urllib3 ≥ 2.8 gọi) chạy
  B. heal(): gộp chồng 2–5 lớp còn 1, giữ lớp ngoài cùng; unwrap(): về regex gốc; không có bọc thì không đụng
  C. tải nhân + đọc manifest gọi heal trước khi dùng requests
  D. /engine/versions liệt kê cả nhân ShardX đã cài (mới nhất trước), đánh dấu đã cài; chạy được với shardx_runtime cũ

Chạy:  python tests/urllib3_guard_test.py   (exit 0 = pass). Không gọi mạng.
"""
import asyncio
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {str(detail)[:300]}")


import urllib3.util.url as U  # noqa: E402

from tubecli.core import urllib3_guard as G  # noqa: E402

RAW = U._PERCENT_RE if not hasattr(U._PERCENT_RE, "re") else None
while RAW is None:
    G.unwrap()
    RAW = U._PERCENT_RE
check("0 bắt đầu từ regex gốc", isinstance(RAW, re.Pattern) and G.depth() == 0)


def sub_works():
    try:
        return U._PERCENT_RE.sub(lambda m: m.group(0).upper(), "a%2fb") == "a%2Fb"
    except AttributeError:
        return False


# ── A ──
try:
    import yt_dlp  # noqa: F401
    import yt_dlp.networking._requests  # noqa: F401
    have_ytdlp = True
except Exception as e:      # noqa: BLE001
    have_ytdlp = False
    print("yt_dlp không có trên máy này:", e)
if have_ytdlp:
    from tubecli.core import ytdlp_manager as YM
    check("A1 import yt-dlp: đúng một lớp", G.depth() == 1 and sub_works(), G.depth())
    # cách CŨ (không unwrap): mô phỏng đúng ca contabo để chắc test bắt được lỗi
    for _ in range(2):
        for k in [k for k in list(sys.modules) if k == "yt_dlp" or k.startswith("yt_dlp.")]:
            sys.modules.pop(k)
        importlib.import_module("yt_dlp.networking._requests")
    check("A2 (đối chứng) nạp lại kiểu cũ → chồng lớp, .sub hỏng", G.depth() == 3 and not sub_works(), G.depth())
    G.heal()
    for i in range(3):
        YM._reload_module()
        importlib.import_module("yt_dlp.networking._requests")
    check("A3 ytdlp_manager nạp lại 3 lần: vẫn một lớp, .sub chạy", G.depth() == 1 and sub_works(), G.depth())
    from tubecli.extensions.video_downloader import routes as VR
    YM._reload_module()
    VR._reload_ytdlp(None)
    importlib.import_module("yt_dlp.networking._requests")
    check("A4 đường video_downloader._reload_ytdlp: một lớp", G.depth() == 1 and sub_works(), G.depth())

# ── B ──
G.unwrap()


class Urllib3PercentREOverride:          # cùng tên + cùng cách viết với yt-dlp
    def __init__(self, r):
        self.re = r

    def __getattr__(self, item):
        return self.re.__getattribute__(item)

    def subn(self, repl, string, *a, **k):
        return string, self.re.subn(repl, string, *a, **k)[1]


for n in (2, 5):
    G.unwrap()
    for _ in range(n):
        U._PERCENT_RE = Urllib3PercentREOverride(U._PERCENT_RE)
    outer = U._PERCENT_RE
    bad = not sub_works()
    removed = G.heal()
    check(f"B1 chồng {n} lớp: hỏng trước, heal gộp còn 1 lớp (giữ lớp ngoài cùng), .sub chạy",
          bad and removed == n - 1 and G.depth() == 1 and U._PERCENT_RE is outer and sub_works(), (removed, G.depth()))
    check(f"B2 chồng {n} lớp: subn của yt-dlp vẫn giữ nguyên chuỗi (hành vi yt-dlp muốn)", U._PERCENT_RE.subn("x", "a%2fb") == ("a%2fb", 1))
check("B3 một lớp: heal không đụng", G.heal() == 0 and G.depth() == 1)
check("B4 unwrap về regex gốc", G.unwrap() == 1 and U._PERCENT_RE is RAW and G.unwrap() == 0)

# ── C ──
from tubecli.extensions.browser import shardx_runtime as SX  # noqa: E402

for _ in range(3):
    U._PERCENT_RE = Urllib3PercentREOverride(U._PERCENT_RE)
calls = []


class FakeResp:
    status_code = 200

    def json(self):
        return {"chromium_version": "158.0.1.2"}


import requests  # noqa: E402

real_get = requests.get
requests.get = lambda *a, **k: (calls.append(G.depth()), FakeResp())[1]
try:
    SX._manifest_cache.update(at=0.0, data={})
    m = SX.fetch_manifest(force=True)
finally:
    requests.get = real_get
check("C1 đọc manifest: gộp lớp trước khi gọi requests", calls == [1] and m.get("chromium_version") == "158.0.1.2", calls)
for _ in range(2):
    U._PERCENT_RE = Urllib3PercentREOverride(U._PERCENT_RE)
src = (ROOT / "tubecli/extensions/browser/shardx_runtime.py").read_text(encoding="utf-8")
dl = src.split("def download(")[1].split("\ndef ")[0]
check("C2 tải nhân gọi _heal_requests trước vòng thử", dl.index("_heal_requests()") < dl.index("for attempt in range"))
G.heal()

# ── D ──
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.extensions.browser import routes as BR  # noqa: E402

saved = {k: getattr(SX, k) for k in ("available_versions", "installed_versions", "current_version", "supports_bas", "binary_path")}
SX.available_versions = lambda: ["158.0.8130.10"]
SX.installed_versions = lambda: ["157.0.8103.39", "156.0.8078.48", "152.0.7977.65"]
SX.current_version = lambda: "158.0.8130.10"
SX.supports_bas = lambda: False
inst = {"157.0.8103.39", "156.0.8078.48", "152.0.7977.65"}


class P:
    def __init__(self, ok):
        self.ok = ok

    def exists(self):
        return self.ok

    @property
    def parent(self):
        return "x"


SX.binary_path = lambda v: P(v in inst)
real_post = requests.post
requests.post = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline in test"))
try:
    app = FastAPI()
    app.include_router(BR.router)
    j = TestClient(app).get("/api/v1/browser/engine/versions").json()
finally:
    requests.post = real_post
    for k, v in saved.items():
        setattr(SX, k, v)
sxv = [v for v in j.get("versions", []) if v.get("is_shardx")]
check("D1 có cả bản mới nhất (chưa cài) lẫn 3 nhân đã cài, mới nhất trước", [v["bas_version"] for v in sxv] == [
    "ShardX-158.0.8130.10", "ShardX-157.0.8103.39", "ShardX-156.0.8078.48", "ShardX-152.0.7977.65"], [v["bas_version"] for v in sxv])
check("D2 nhân đã cài đánh dấu downloaded, bản mới nhất thì chưa", [v["downloaded"] for v in sxv] == [False, True, True, True]
      and sxv[0].get("is_current") is True, [(v["bas_version"], v["downloaded"]) for v in sxv])
rsrc = (ROOT / "tubecli/extensions/browser/routes.py").read_text(encoding="utf-8")
check("D3 routes.py (đi qua hot-patch) chịu được shardx_runtime cũ thiếu installed_versions / _version_key",
      'getattr(sx, "installed_versions"' in rsrc and 'getattr(sx, "_version_key"' in rsrc)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
