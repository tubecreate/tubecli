# -*- coding: utf-8 -*-
"""Cài / cập nhật extension LỚN từ Chợ (VPS 49, 22/10/2026): tải Content Studio 4,5 MB hỏng đúng mốc 15 s → cài rơi xuống
«chép từ nguồn cục bộ» = chính thư mục đang cài → shutil.SameFileError, HTTP 500, không nói gì.

Kiểm (HTTP giả, thư mục tạm — không gọi Chợ thật, không đụng extensions_external thật):
  A. download_item_data dùng TIMEOUT_LONG (không phải 15 s) và trả lý do khi hỏng
  B. cập nhật mà tải hỏng ⇒ 502 «Could not download … kept», KHÔNG SameFileError, bản đang có còn nguyên

Run:  python tests/market_download_timeout_test.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


from tubecli.extensions.market import market_service as MS  # noqa: E402

print("A. thời gian chờ tải gói")
seen = {}


async def fake_get(url, params=None, headers=None, timeout=None):
    seen["timeout"] = timeout
    raise TimeoutError("read timed out")

svc = MS.market_service
real_get = svc._get
svc._get = fake_get
out = asyncio.run(svc.download_item_data("con_st"))
svc._get = real_get
check("download_item_data xin TIMEOUT_LONG", seen.get("timeout") == MS.TIMEOUT_LONG and MS.TIMEOUT_LONG >= 60, seen)
check("hỏng ⇒ status error + lý do", out.get("status") == "error" and "TimeoutError" in out.get("message", ""), out)

print("B. cập nhật mà tải hỏng")
import tubecli.config as CFG  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from tubecli.extensions.market import routes as MR  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="mkt_dl_"))
ext = TMP / "content_studio"
ext.mkdir()
(ext / "tubecli-extension.json").write_text('{"name": "content_studio", "version": "1"}', encoding="utf-8")
(ext / "studio_routes.py").write_text("# old", encoding="utf-8")
MR_EXT = TMP
CFG.EXTENSIONS_EXTERNAL_DIR = MR_EXT


async def fake_dl(public_id):
    return {"status": "error", "message": "ReadTimeout: "}

svc.download_item_data = fake_dl
MR._make_install_id = lambda name, pid: "content_studio"
MR._check_item_installed = lambda pid, name, cat: {"installed": True, "path": str(ext)}
MR._builtin_extension = lambda name: None
req = MR.MarketInstallRequest(item_data="", item_name="content_studio", category="extension", force_update=True,
                              auto_restart=False)
try:
    asyncio.run(MR.install_from_market("con_st", req, authorization=None))
    check("tải hỏng ⇒ phải báo lỗi", False)
except HTTPException as e:
    msg = str((e.detail or {}).get("message") if isinstance(e.detail, dict) else e.detail)
    check("tải hỏng ⇒ 502 nói rõ: tải hỏng, giữ bản đang có", e.status_code == 502 and "Could not download" in msg
          and "kept" in msg and "ReadTimeout" in msg, (e.status_code, msg))
except Exception as e:      # noqa: BLE001
    check("không còn SameFileError / lỗi lạ", False, repr(e))
check("bản đang cài còn nguyên", (ext / "studio_routes.py").read_text(encoding="utf-8") == "# old"
      and (ext / "tubecli-extension.json").exists())

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
