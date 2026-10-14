# -*- coding: utf-8 -*-
"""Content Studio + TTS VibeVoice cài sẵn từ Chợ — MỘT lần mỗi máy, chạy nền (user 14/10/2026).

Run:  python tests/market_defaults_test.py     (exit 0 = pass)

Chợ và hàm cài đều được thay bằng đồ giả: không gọi mạng, không cài gì thật. DATA_DIR và thư mục extension
trỏ vào thư mục tạm, nên data/ của máy không bị đụng. Mục G (Chợ thật) chỉ ĐỌC, mạng hỏng thì bỏ qua.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="mkt_defaults_"))
cfg.DATA_DIR = TMP
cfg.EXTENSIONS_EXTERNAL_DIR = TMP / "extensions_external"
cfg.EXTENSIONS_EXTERNAL_DIR.mkdir()

from fastapi import HTTPException  # noqa: E402

from tubecli.extensions.market import defaults as D  # noqa: E402
from tubecli.extensions.market import routes as R  # noqa: E402
from tubecli.extensions.market.market_service import market_service  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


MARKET = {
    "con_st": {"public_id": "con_st", "title": "Content Studio", "category": "extension", "price": 0,
               "item_data": '{"pkg": "content-studio"}'},
    "tts_vb": {"public_id": "tts_vb", "title": "TTS VibeVoice", "category": "extension", "price": 0,
               "item_data": '{"pkg": "vibevoice"}'},
}
MODE = {"detail": "ok", "install": "ok"}
INSTALLS = []


async def fake_detail(pid):
    if MODE["detail"] == "down":
        return {"status": "error"}
    it = dict(MARKET[pid])
    if MODE["detail"] == "paid":
        it["price"] = 3
    return {"status": "success", "item": it, "reviews": []}


async def fake_install(pid, req, authorization=None):
    INSTALLS.append((pid, req, authorization))
    if MODE["install"] == "409":
        raise HTTPException(409, {"message": "already installed", "already_installed": True})
    return {"status": "success", "message": f"Extension '{req.item_name}' installed and enabled."}


market_service.get_detail = fake_detail
R.install_from_market = fake_install


def reset():
    INSTALLS.clear()
    MODE.update(detail="ok", install="ok")
    try:
        D._state_file().unlink()
    except OSError:
        pass
    for p in cfg.EXTENSIONS_EXTERNAL_DIR.iterdir():
        for f in p.iterdir():
            f.unlink()
        p.rmdir()


def run(**kw):
    return asyncio.run(D.ensure_defaults(delay=0, **kw))


# ── A. máy mới: cài cả hai, gói lấy từ Chợ, không tự khởi động lại ─────────────────────────────────
reset()
st = run()
check("A1 máy mới → cài Content Studio + TTS VibeVoice", [p for p, _, _ in INSTALLS] == ["con_st", "tts_vb"], INSTALLS)
req = INSTALLS[0][1] if INSTALLS else None
check("A2 gói = item_data Chợ trả về; tên = tên trên Chợ; category extension",
      req and req.item_data == MARKET["con_st"]["item_data"] and req.item_name == "Content Studio"
      and req.category == "extension", req)
check("A3 không ép cập nhật, không tự khởi động lại, không cần đăng nhập Chợ",
      req and req.force_update is False and req.auto_restart is False and INSTALLS[0][2] is None, req)
check("A4 ghi trạng thái installed cho cả hai",
      st.get("con_st", {}).get("status") == "installed" and st.get("tts_vb", {}).get("status") == "installed", st)
check("A5 trạng thái nằm trong DATA_DIR/default_extensions.json", D._state_file() == TMP / "default_extensions.json"
      and json.loads(D._state_file().read_text(encoding="utf-8")).get("tts_vb", {}).get("status") == "installed")

# ── B. MỘT lần mỗi máy: lần sau không cài lại, kể cả khi chủ đã gỡ ─────────────────────────────────
INSTALLS.clear()
run()
check("B1 khởi động lần hai → không cài lại (chủ gỡ đi thì giữ nguyên ý chủ)", not INSTALLS and not D.todo(), INSTALLS)

# ── C. đã có sẵn trên máy → «present», không đụng ─────────────────────────────────────────────────────
reset()
(cfg.EXTENSIONS_EXTERNAL_DIR / "my_cs").mkdir()
(cfg.EXTENSIONS_EXTERNAL_DIR / "my_cs" / "tubecli-extension.json").write_text('{"name": "content_studio"}', encoding="utf-8")
st = run()
check("C1 Content Studio có sẵn (thư mục khác tên) → present, chỉ cài TTS VibeVoice",
      st.get("con_st", {}).get("status") == "present" and [p for p, _, _ in INSTALLS] == ["tts_vb"], (st, INSTALLS))

# ── D. Chợ không trả lời → thử lại lần khởi động sau, tối đa MAX_ATTEMPTS ─────────────────────────────
reset()
MODE["detail"] = "down"
st = run()
check("D1 Chợ hỏng → failed, attempts 1, không cài", st.get("con_st", {}).get("status") == "failed"
      and st["con_st"].get("attempts") == 1 and not INSTALLS, st)
check("D2 còn trong danh sách phải thử", {d["id"] for d in D.todo()} == {"con_st", "tts_vb"})
for _ in range(D.MAX_ATTEMPTS + 2):
    run()
st = D.load_state()
check("D3 dừng sau MAX_ATTEMPTS lần (không gõ Chợ mãi)",
      st["con_st"].get("attempts") == D.MAX_ATTEMPTS and not D.todo(), st)
MODE["detail"] = "ok"
reset()
MODE["detail"] = "down"
run()
MODE["detail"] = "ok"
st = run()
check("D4 lần sau Chợ lên lại → cài được", st.get("con_st", {}).get("status") == "installed", st)

# ── E. gói không còn miễn phí / Chợ báo đã cài ─────────────────────────────────────────────────────────
reset()
MODE["detail"] = "paid"
st = run()
check("E1 gói có phí → KHÔNG cài (không bao giờ mua hộ chủ)", not INSTALLS and st["con_st"]["status"] == "failed", st)
reset()
MODE["install"] = "409"
st = run()
check("E2 route cài báo 409 (đã cài) → present", st.get("con_st", {}).get("status") == "present", st)

# ── F. tắt hẳn bằng biến môi trường; khởi động server lên lịch chạy nền ───────────────────────────────
reset()
os.environ[D.OPT_OUT_ENV] = "1"
try:
    st = run()
finally:
    del os.environ[D.OPT_OUT_ENV]
check("F1 TUBECLI_NO_DEFAULT_EXTENSIONS=1 → không làm gì", st == {} and not INSTALLS, (st, INSTALLS))
src = (ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8")
start = src[src.index("async def startup_event"):src.index('@app.on_event("shutdown")')]
check("F2 startup chạy ensure_defaults NỀN (create_task), bọc try — không chặn / không làm hỏng khởi động",
      "asyncio.create_task(_market_defaults.ensure_defaults())" in start and "[defaults] skipped" in start)

# ── G. Chợ thật (chỉ đọc): hai mã còn là extension miễn phí — mạng hỏng thì bỏ qua ────────────────────
try:
    import urllib.request
    for d in D.DEFAULTS:
        url = f"https://market.tubecreate.com/api/market-cli/detail.php?id={d['id']}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tubecli-test"}), timeout=20) as r:
            it = json.loads(r.read().decode("utf-8")).get("item") or {}
        check(f"G {d['id']} trên Chợ thật = extension miễn phí '{d['title']}'",
              it.get("category") == "extension" and float(it.get("price") or 0) == 0 and it.get("title") == d["title"],
              {k: it.get(k) for k in ("category", "price", "title")})
except Exception as e:
    print(f"[SKIP] G Chợ thật: {e}")

import shutil  # noqa: E402

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
