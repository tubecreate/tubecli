"""Danh mục Chợ giữ sẵn trên máy (21/11/2026).

User: «chợ load chậm — data kèm luôn trên local trước, chạy đồng bộ ngầm nếu có update extension chứ không mỗi lần
mỗi load». Trước đây mỗi lần mở Chợ (cả mỗi lần đổi bộ lọc, lật trang, gõ tìm) là một lượt hỏi
market.tubecreate.com (~2 s, chậm hơn nhiều qua tunnel / máy ở xa) và trang đứng ở «Loading marketplace...».

Nay:
  • Toàn bộ danh mục công khai (vài chục món, ~50 KB) nằm trên máy: DATA_DIR/market_catalog.json, lần đầu chưa có thì
    dùng bản chụp kèm theo lõi (catalog_seed.json — làm mới mỗi lần phát hành bằng
    `python -m tubecli.extensions.market.catalog --write-seed`).
  • Trang Chợ lọc / sắp xếp / tìm NGAY trên trình duyệt từ danh mục này — không chờ mạng.
  • Đồng bộ ngầm: danh mục cũ hơn FRESH_SEC thì kéo bản mới trong nền (một lượt duy nhất dù nhiều người mở cùng
    lúc); trang hỏi lại với wait=1 và chỉ vẽ lại khi chữ ký (sig) đổi — có bản mới / extension mới / phiên bản mới.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

from tubecli.config import DATA_DIR

SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_seed.json")
FRESH_SEC = 10 * 60          # danh mục trẻ hơn mức này thì không kéo lại
PAGE_LIMIT = 100
MAX_PAGES = 20               # chặn vòng lặp nếu máy chủ báo total_pages sai

_task: Optional[asyncio.Task] = None
_last_error = ""
_last_error_at = 0.0


def cache_path() -> str:
    return os.path.join(str(DATA_DIR), "market_catalog.json")


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except (OSError, ValueError):
        pass
    return None


def signature(items: List[Dict[str, Any]]) -> str:
    """Chữ ký danh mục: đổi khi có món mới / bị gỡ / đổi phiên bản, giá, mô tả, lượt tải… — trang so chữ ký để biết
    có cần vẽ lại không (không đổi thì im, khỏi nháy)."""
    rows = sorted(json.dumps(it, sort_keys=True, ensure_ascii=False) for it in items if isinstance(it, dict))
    return hashlib.md5("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def load() -> Dict[str, Any]:
    """Danh mục trên máy, KHÔNG gọi mạng: bản đồng bộ gần nhất, hoặc bản chụp kèm lõi nếu nó mới hơn / chưa có bản
    đồng bộ. Không có gì cả ⇒ items rỗng, synced_at 0 (trang hiện vòng chờ và đợi lượt đồng bộ đầu)."""
    cache = _read(cache_path())
    seed = _read(SEED_PATH)
    best, source = None, "none"
    if cache and (not seed or float(cache.get("synced_at") or 0) >= float(seed.get("synced_at") or 0)):
        best, source = cache, "cache"
    elif seed:
        best, source = seed, "seed"
    if not best:
        return {"items": [], "synced_at": 0, "sig": "", "source": source}
    items = [it for it in best.get("items") or [] if isinstance(it, dict)]
    return {"items": items, "synced_at": float(best.get("synced_at") or 0),
            "sig": best.get("sig") or signature(items), "source": source}


def age_sec(cat: Dict[str, Any]) -> float:
    at = float(cat.get("synced_at") or 0)
    return max(0.0, time.time() - at) if at else float("inf")


def is_syncing() -> bool:
    return _task is not None and not _task.done()


def last_error() -> str:
    # Lỗi cũ hơn một giờ coi như hết — đừng hiện «offline» mãi chỉ vì một lần mạng chập chờn.
    return _last_error if _last_error and time.time() - _last_error_at < 3600 else ""


async def fetch_remote() -> List[Dict[str, Any]]:
    """Kéo TOÀN BỘ danh mục công khai từ market.tubecreate.com, lật hết các trang."""
    from tubecli.extensions.market.market_service import market_service as ms

    items: List[Dict[str, Any]] = []
    seen = set()
    page = 1
    while page <= MAX_PAGES:
        res = await ms._get(f"{ms.api_base}/list.php",
                            params={"page": page, "limit": PAGE_LIMIT, "sort": "newest", "mode": "public"})
        if not isinstance(res, dict) or res.get("status") != "success":
            raise RuntimeError(f"market list failed: {str((res or {}).get('message') or res)[:200]}")
        for it in res.get("data") or []:
            pid = isinstance(it, dict) and it.get("public_id")
            if pid and pid not in seen:
                seen.add(pid)
                items.append(it)
        pag = res.get("pagination") or {}
        if page >= int(pag.get("total_pages") or 1) or not res.get("data"):
            break
        page += 1
    return items


def save(items: List[Dict[str, Any]], path: Optional[str] = None) -> Dict[str, Any]:
    data = {"synced_at": time.time(), "sig": signature(items), "items": items}
    path = path or cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return data


async def _refresh() -> Dict[str, Any]:
    global _last_error, _last_error_at
    try:
        items = await fetch_remote()
        data = await asyncio.to_thread(save, items)
        _last_error = ""
        print(f"[MarketCatalog] synced {len(items)} items (sig {data['sig']})")
        return {**data, "source": "cache"}
    except Exception as e:      # noqa: BLE001 — mạng lỗi: giữ danh mục cũ, báo nhẹ trên trang
        _last_error, _last_error_at = str(e)[:200] or e.__class__.__name__, time.time()
        print(f"[MarketCatalog] sync failed, keeping the saved catalog: {_last_error}")
        raise


def start_refresh() -> asyncio.Task:
    """Một lượt đồng bộ dùng chung: đang có lượt chạy thì trả lại chính nó."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_refresh())
        # Không ai chờ ⇒ nuốt lỗi để asyncio khỏi in «Task exception was never retrieved».
        _task.add_done_callback(lambda t: t.cancelled() or t.exception())
    return _task


async def get(wait: bool = False, force: bool = False) -> Dict[str, Any]:
    """Danh mục cho trang Chợ. wait=False: trả NGAY bản trên máy (cũ thì mở lượt đồng bộ ngầm). wait=True: chờ lượt
    đồng bộ (nếu cần) rồi trả bản mới nhất — lỗi mạng thì vẫn trả bản trên máy kèm sync_error."""
    cat = load()
    need = force or age_sec(cat) > FRESH_SEC or not cat["items"]
    task = start_refresh() if need else (_task if is_syncing() else None)
    if wait and task is not None:
        try:
            cat = await asyncio.shield(task)
        except Exception:       # noqa: BLE001
            cat = load()
    return {**cat, "age_sec": None if cat["synced_at"] == 0 else round(age_sec(cat)),
            "syncing": is_syncing(), "sync_error": last_error(), "fresh_sec": FRESH_SEC}


def _main(argv: List[str]) -> int:
    """`python -m tubecli.extensions.market.catalog --write-seed` — chụp danh mục hiện tại vào catalog_seed.json
    (chạy trước mỗi lần phát hành để người mới cài mở Chợ là thấy ngay)."""
    if "--write-seed" not in argv:
        print("usage: python -m tubecli.extensions.market.catalog --write-seed")
        return 2
    items = asyncio.run(fetch_remote())
    data = save(items, SEED_PATH)
    print(f"wrote {SEED_PATH}: {len(items)} items, sig {data['sig']}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
