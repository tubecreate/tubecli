"""Extension CÀI SẴN từ Chợ: Content Studio + TTS VibeVoice.

User 14/10/2026: «chỗ extension content studio, vibe tts tôi nghĩ nên cho cài sẵn khi cài tubecli» — máy mới
cài xong chưa làm được video: Codex GPT trên một VPS mới phải đi tìm và cài hai gói này trước.

Vì sao không chép vào lõi: hai gói có nhịp phát hành riêng trên Chợ (Content Studio đổi gần như mỗi ngày) và cập
nhật qua Chợ; chép vào repo lõi là tách đôi đường cập nhật. Nên máy tự cài chúng TỪ CHỢ, MỘT LẦN, chạy nền sau khi
server đã lên — không chặn khởi động, máy không có mạng vẫn bật bình thường — qua đúng hàm cài của trang Chợ
(routes.install_from_market), nên hành vi giống hệt bấm «Cài đặt» tay. Cả hai đều nhẹ lúc cài (gói ~2,9 MB và
~84 KB; Content Studio cần httpx + pillow, TTS VibeVoice cần edge-tts; torch của VibeVoice chỉ tải khi dùng engine đó).

Luật:
  * Mỗi gói cài MỘT LẦN cho mỗi máy, ghi vào data/default_extensions.json. Chủ gỡ đi rồi thì KHÔNG cài lại.
  * Máy đã có sẵn (cài tay, bản dev) → ghi «present», không đụng tới.
  * Chợ không trả lời / lỗi mạng → thử lại ở lần khởi động sau, tối đa MAX_ATTEMPTS lần.
  * Tắt hẳn: biến môi trường TUBECLI_NO_DEFAULT_EXTENSIONS=1.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("MarketDefaults")

# id trên Chợ (public_id) → tên trong tubecli-extension.json
DEFAULTS = (
    {"id": "con_st", "name": "content_studio", "title": "Content Studio"},
    {"id": "tts_vb", "name": "tts_vibevoice", "title": "TTS VibeVoice"},
)
START_DELAY_S = 20          # để server lên hẳn và trang chủ mở được trước khi tải gói
MAX_ATTEMPTS = 5
DONE = ("installed", "present")
OPT_OUT_ENV = "TUBECLI_NO_DEFAULT_EXTENSIONS"


def _state_file() -> Path:
    import tubecli.config as cfg  # đọc lúc gọi (test trỏ DATA_DIR đi chỗ khác)

    return Path(cfg.DATA_DIR) / "default_extensions.json"


def load_state() -> Dict[str, Any]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        from tubecli.core.private_file import write_json_private

        write_json_private(_state_file(), state)
    except Exception as e:
        logger.warning(f"[defaults] could not save state: {e}")


def _ext_dir() -> Path:
    import tubecli.config as cfg

    return Path(cfg.EXTENSIONS_EXTERNAL_DIR)


def is_present(name: str) -> bool:
    """Extension `name` đã có trên máy chưa — đã nạp, hoặc có thư mục mang manifest đúng tên."""
    try:
        from tubecli.core.extension_manager import extension_manager

        if extension_manager.get(name) is not None:
            return True
    except Exception:
        pass
    root = _ext_dir()
    try:
        entries = list(root.iterdir())
    except OSError:
        return False
    for entry in entries:
        mf = entry / "tubecli-extension.json"
        try:
            if mf.is_file() and json.loads(mf.read_text(encoding="utf-8-sig")).get("name") == name:
                return True
        except Exception:
            continue
    return False


def todo(state: Optional[Dict[str, Any]] = None) -> list:
    """Gói còn phải thử cài: chưa xong và chưa hết lượt."""
    state = load_state() if state is None else state
    out = []
    for d in DEFAULTS:
        st = state.get(d["id"]) or {}
        if st.get("status") in DONE or int(st.get("attempts") or 0) >= MAX_ATTEMPTS:
            continue
        out.append(d)
    return out


async def _install(d: Dict[str, str]) -> str:
    """Tải gói từ Chợ rồi cài như nút «Cài đặt» của trang Chợ. Trả câu báo; lỗi thì ném."""
    from fastapi import HTTPException

    from .market_service import market_service
    from .routes import MarketInstallRequest, install_from_market

    det = await market_service.get_detail(d["id"])
    it = det.get("item") if isinstance(det, dict) else None
    if not isinstance(it, dict) or det.get("status") != "success":
        raise RuntimeError("the Market did not return the item")
    if str(it.get("category") or "") != "extension":
        raise RuntimeError(f"Market item {d['id']} is not an extension")
    try:
        price = float(it.get("price") or 0)
    except (TypeError, ValueError):
        price = 1.0
    if price > 0:
        raise RuntimeError(f"Market item {d['id']} is not free")
    req = MarketInstallRequest(item_data=it.get("item_data") or json.dumps(it, ensure_ascii=False),
                               item_name=str(it.get("title") or d["title"]), category="extension",
                               force_update=False, auto_restart=False)
    try:
        res = await install_from_market(d["id"], req, authorization=None)
    except HTTPException as e:
        if e.status_code == 409:                      # đã cài / có sẵn trong lõi
            return "present"
        raise RuntimeError(f"HTTP {e.status_code}: {e.detail}")
    if not isinstance(res, dict) or res.get("status") != "success":
        raise RuntimeError(str(res)[:300])
    return str(res.get("message") or "installed")


async def ensure_defaults(delay: float = START_DELAY_S) -> Dict[str, Any]:
    """Cài các gói mặc định còn thiếu. Gọi nền từ startup của server; không bao giờ ném."""
    if os.environ.get(OPT_OUT_ENV, "").strip() not in ("", "0", "false", "no"):
        return {}
    state = load_state()
    if not todo(state):
        return state
    if delay:
        await asyncio.sleep(delay)
    for d in todo(state):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        prev = state.get(d["id"]) or {}
        if is_present(d["name"]):
            state[d["id"]] = {"status": "present", "at": now}
            _save_state(state)
            continue
        print(f"📦 Installing {d['title']} from the TubeCLI Market (comes with every TubeCLI)...", flush=True)
        try:
            msg = await _install(d)
            state[d["id"]] = {"status": "present" if msg == "present" else "installed", "at": now}
            print(f"✅ {d['title']}: {msg}", flush=True)
        except Exception as e:
            attempts = int(prev.get("attempts") or 0) + 1
            state[d["id"]] = {"status": "failed", "attempts": attempts, "error": f"{type(e).__name__}: {e}"[:300],
                              "at": now}
            print(f"⚠️ {d['title']} not installed ({attempts}/{MAX_ATTEMPTS}), will retry next start: {e}", flush=True)
        _save_state(state)
    return state
