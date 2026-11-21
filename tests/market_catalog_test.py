"""21/11/2026 — Chợ mở chậm: mỗi lần mở / lọc / gõ tìm là một lượt hỏi market.tubecreate.com (~2 s, lâu hơn qua tunnel).
User: «data kèm luôn trên local trước, chạy đồng bộ dữ liệu ngầm nếu có update extension chứ không mỗi lần mỗi load».

A. load(): không mạng — bản đồng bộ trên máy, hoặc bản chụp kèm lõi (catalog_seed.json) khi chưa có / bản chụp mới hơn.
B. get(): trả NGAY; danh mục cũ → MỘT lượt đồng bộ ngầm (nhiều người hỏi cùng lúc vẫn một lượt); wait=1 chờ bản mới;
   chữ ký (sig) chỉ đổi khi danh mục đổi; mạng lỗi → giữ danh mục cũ + sync_error, không ném.
C. fetch_remote lật hết các trang, bỏ trùng.
D. GET /api/v1/market/catalog kèm trạng thái đã cài.
E. Bản chụp kèm lõi có thật, đủ extension + mẫu.

Cách ly: DATA_DIR tạm; Chợ giả (market_service._get thay bằng hàm giả); không mạng.
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
TMP = Path(tempfile.mkdtemp(prefix="market_catalog_"))
os.environ["TUBECLI_DATA_DIR"] = str(TMP)
os.environ.setdefault("TUBECLI_SKIP_STARTUP", "1")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


import tubecli.config as cfg  # noqa: E402

cfg.DATA_DIR = TMP
from tubecli.extensions.market import catalog as C  # noqa: E402
from tubecli.extensions.market.market_service import market_service as MS  # noqa: E402

C.DATA_DIR = TMP
REAL_SEED = C.SEED_PATH
SEED = TMP / "seed.json"
C.SEED_PATH = str(SEED)
check("0 sổ danh mục nằm trong DATA_DIR tạm", C.cache_path().startswith(str(TMP)), C.cache_path())


def item(pid, ver="1.0.0", cat="extension", **kw):
    return {"public_id": pid, "title": pid.upper(), "category": cat, "version": ver, "price": "0",
            "created_at": "2026-11-01 00:00:00", "updated_at": "2026-11-01 00:00:00", **kw}


REMOTE = {"items": [item("a"), item("b", cat="template", tpl_kind="content")], "calls": 0, "fail": False, "delay": 0}


async def fake_get(url, params=None, headers=None, timeout=None):
    REMOTE["calls"] += 1
    if REMOTE["delay"]:
        await asyncio.sleep(REMOTE["delay"])
    if REMOTE["fail"]:
        raise RuntimeError("network down")
    assert url.endswith("/list.php"), url
    page, limit = int(params["page"]), int(params["limit"])
    data = REMOTE["items"][(page - 1) * limit: page * limit]
    total = len(REMOTE["items"])
    return {"status": "success", "data": data,
            "pagination": {"page": page, "limit": limit, "total": total, "total_pages": max(1, -(-total // limit))}}


MS._get = fake_get


def reset():
    C._task = None
    C._last_error = ""
    for p in (C.cache_path(), str(SEED)):
        if os.path.exists(p):
            os.remove(p)
    REMOTE.update(calls=0, fail=False, delay=0)


def run(coro):
    return asyncio.run(coro)


# ── A. load() ──
reset()
cat = C.load()
check("A1 chưa có gì → items rỗng, synced_at 0, không gọi mạng", cat["items"] == [] and cat["synced_at"] == 0
      and REMOTE["calls"] == 0, cat)
C.save([item("s1")], str(SEED))
cat = C.load()
check("A2 chỉ có bản chụp kèm lõi → dùng bản chụp (source=seed)", cat["source"] == "seed"
      and [i["public_id"] for i in cat["items"]] == ["s1"], cat)
time.sleep(0.01)
C.save([item("c1"), item("c2")])
cat = C.load()
check("A3 bản đồng bộ mới hơn bản chụp → dùng bản đồng bộ (source=cache)", cat["source"] == "cache"
      and len(cat["items"]) == 2, cat)
time.sleep(0.01)
C.save([item("s2")], str(SEED))
check("A4 bản chụp mới hơn (vừa cập nhật lõi) → dùng bản chụp", C.load()["source"] == "seed")
with open(C.cache_path(), "w", encoding="utf-8") as f:
    f.write("{hỏng")
os.remove(str(SEED))
check("A5 sổ hỏng → coi như chưa có, không ném", C.load()["items"] == [])

# ── B. get() ──
reset()


async def b1():
    r = await C.get(wait=False)
    first_items = len(r["items"])
    await asyncio.sleep(0.05)
    return first_items, r["syncing"]


n, syncing = run(b1())
check("B1 chưa có danh mục → trả ngay (rỗng) và mở lượt đồng bộ ngầm", n == 0 and syncing is True, (n, syncing))
check("B1b lượt ngầm đã ghi danh mục xuống đĩa", len(C.load()["items"]) == 2 and REMOTE["calls"] == 1, REMOTE)

reset()
C.save([item("a")])
REMOTE["calls"] = 0


async def b2():
    r = await C.get(wait=True)
    return r


r = run(b2())
check("B2 danh mục còn mới → wait=1 cũng KHÔNG gọi Chợ", REMOTE["calls"] == 0 and r["syncing"] is False
      and len(r["items"]) == 1, (REMOTE, r["syncing"]))

old = C.load()
d = json.load(open(C.cache_path(), encoding="utf-8"))
d["synced_at"] = time.time() - C.FRESH_SEC - 5
json.dump(d, open(C.cache_path(), "w", encoding="utf-8"))
C._task = None


async def b3():
    fast = await C.get(wait=False)
    slow = await C.get(wait=True)
    return fast, slow


fast, slow = run(b3())
check("B3 danh mục cũ → wait=0 trả NGAY bản cũ (1 món), đang đồng bộ", len(fast["items"]) == 1 and fast["syncing"], fast)
check("B3b wait=1 → bản mới (2 món), chữ ký đổi", len(slow["items"]) == 2 and slow["sig"] != old["sig"], slow["sig"])
check("B3c hai lượt hỏi chung MỘT lượt đồng bộ", REMOTE["calls"] == 1, REMOTE)

REMOTE["calls"] = 0
C._task = None
again = run(C.get(wait=True, force=True))
check("B4 force=1 → hỏi Chợ dù còn mới; danh mục không đổi thì chữ ký giữ nguyên",
      REMOTE["calls"] == 1 and again["sig"] == slow["sig"], (REMOTE, again["sig"]))

REMOTE["items"] = [item("a", ver="1.1.0"), item("b", cat="template", tpl_kind="content")]
C._task = None
upd = run(C.get(wait=True, force=True))
check("B5 extension lên phiên bản mới → chữ ký đổi (trang biết mà vẽ lại)", upd["sig"] != again["sig"]
      and upd["items"][0]["version"] == "1.1.0", upd["sig"])

REMOTE["fail"] = True
C._task = None
off = run(C.get(wait=True, force=True))
check("B6 Chợ lỗi mạng → vẫn trả danh mục đã lưu + sync_error, không ném", len(off["items"]) == 2
      and "network down" in off["sync_error"], off.get("sync_error"))
REMOTE["fail"] = False


async def b7():
    REMOTE["delay"] = 0.05
    REMOTE["calls"] = 0
    C._task = None
    rs = await asyncio.gather(*[C.get(wait=True, force=True) for _ in range(5)])
    REMOTE["delay"] = 0
    return rs


rs = run(b7())
check("B7 năm trang mở cùng lúc (force) → MỘT lượt hỏi Chợ", REMOTE["calls"] == 1 and all(len(x["items"]) == 2 for x in rs),
      REMOTE)
check("B8 sync_error xoá sau lượt thành công", rs[0]["sync_error"] == "", rs[0]["sync_error"])

# ── C. lật trang ──
REMOTE["items"] = [item(f"x{i}") for i in range(230)] + [item("x5")]
C.PAGE_LIMIT_SAVE, C.PAGE_LIMIT = C.PAGE_LIMIT, 100
items = run(C.fetch_remote())
check("C1 230 món / 3 trang → đủ 230, bỏ trùng", len(items) == 230 and REMOTE["calls"] >= 3, len(items))
REMOTE["items"] = [item("a"), item("b", cat="template", tpl_kind="content")]

# ── D. route ──
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.extensions.market import routes as R  # noqa: E402

calls = []


def fake_installed(pid, name, category):
    calls.append(pid)
    return {"installed": pid == "a", "path": "", "install_id": pid, "local_version": "0.9.0" if pid == "a" else "0.0.0"}


R._check_item_installed = fake_installed
reset()
C.save(REMOTE["items"])
app = FastAPI()
app.include_router(R.router)
cl = TestClient(app)
res = cl.get("/api/v1/market/catalog")
j = res.json()
check("D1 GET /catalog → 200, đủ món, có sig / synced_at", res.status_code == 200 and len(j["items"]) == 2
      and j["sig"] and j["synced_at"] > 0, j)
check("D2 kèm trạng thái đã cài từng món (bản đã cài 0.9.0)", j["installed"]["a"]["installed"] is True
      and j["installed"]["a"]["local_version"] == "0.9.0" and j["installed"]["b"]["installed"] is False, j.get("installed"))
calls.clear()
j2 = cl.get("/api/v1/market/catalog?installed=0").json()
check("D3 installed=0 → không quét đĩa", "installed" not in j2 and calls == [], calls)
check("D4 danh mục mới → không gọi Chợ", REMOTE["calls"] == 0, REMOTE)

# ── E. bản chụp kèm lõi ──
seed = json.load(open(REAL_SEED, encoding="utf-8"))
cats = {i.get("category") for i in seed.get("items", [])}
check("E1 catalog_seed.json có thật, có extension và mẫu", {"extension", "template"} <= cats and seed.get("sig"), cats)
check("E2 bản chụp chỉ hàng PUBLIC", all(str(i.get("visibility", "PUBLIC")).upper() == "PUBLIC" for i in seed["items"]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
