"""Két tài khoản Codex: mỗi gói đăng ký (ChatGPT Plus/Pro/Team… hoặc API key) một auth.json riêng.

  <root>/accounts.json            danh sách + thông tin công khai (email, gói, hạn mức gần nhất)
  <root>/accounts/<id>/auth.json  khoá đăng nhập — KHÔNG BAO GIỜ đi ra API/trang

auth.json ghi 0600 trên Linux. public() là thứ duy nhất trang được thấy.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cli import data_root

_LOCK = threading.RLock()


def _now() -> int:
    return int(time.time())


def _atomic_write(path: Path, data: bytes, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{secrets.token_hex(3)}")
    with open(tmp, "wb") as f:
        f.write(data)
    if private and os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _index_path() -> Path:
    return data_root() / "accounts.json"


def auth_path(acc_id: str) -> Path:
    return data_root() / "accounts" / acc_id / "auth.json"


def _load() -> List[Dict[str, Any]]:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    _atomic_write(_index_path(), json.dumps(items, ensure_ascii=False, indent=1).encode("utf-8"))


def all_accounts() -> List[Dict[str, Any]]:
    with _LOCK:
        return [a for a in _load() if auth_path(a.get("id", "")).is_file()]


def get(acc_id: str) -> Optional[Dict[str, Any]]:
    for a in all_accounts():
        if a.get("id") == acc_id:
            return a
    return None


def read_auth(acc_id: str) -> bytes:
    with open(auth_path(acc_id), "rb") as f:
        return f.read()


def write_auth(acc_id: str, data: bytes) -> None:
    _atomic_write(auth_path(acc_id), data, private=True)


def add_or_update(meta: Dict[str, Any], auth: bytes) -> Dict[str, Any]:
    """Thêm tài khoản; cùng email + cùng loại (đăng nhập lại) thì thay khoá cho tài khoản cũ."""
    with _LOCK:
        items = _load()
        hit = None
        if meta.get("email"):
            hit = next((a for a in items if a.get("email") == meta["email"] and a.get("kind") == meta.get("kind")), None)
        if hit is None:
            hit = {"id": secrets.token_hex(4), "created_at": _now(), "disabled": False, "limits": {},
                   "limited_until": 0, "last_used_at": 0}
            items.append(hit)
        for k in ("label", "kind", "email", "plan"):
            if meta.get(k) is not None:
                hit[k] = meta[k]
        if meta.get("limits"):
            hit["limits"] = meta["limits"]
        hit.setdefault("label", hit.get("email") or "Codex")
        write_auth(hit["id"], auth)
        _save(items)
        return dict(hit)


def update(acc_id: str, **fields) -> Optional[Dict[str, Any]]:
    with _LOCK:
        items = _load()
        for a in items:
            if a.get("id") == acc_id:
                a.update(fields)
                _save(items)
                return dict(a)
    return None


def remove(acc_id: str) -> bool:
    with _LOCK:
        items = _load()
        keep = [a for a in items if a.get("id") != acc_id]
        if len(keep) == len(items):
            return False
        _save(keep)
        try:
            auth_path(acc_id).unlink()
            auth_path(acc_id).parent.rmdir()
        except OSError:
            pass
        return True


def limits_from(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """RateLimitSnapshot của Codex → dạng gọn: phần trăm đã dùng, cửa sổ (phút), lúc đặt lại."""
    s = snapshot or {}

    def win(w):
        if not isinstance(w, dict):
            return None
        return {"used": int(w.get("usedPercent") or 0), "window_mins": w.get("windowDurationMins"),
                "resets_at": w.get("resetsAt")}
    return {"primary": win(s.get("primary")), "secondary": win(s.get("secondary")),
            "plan": s.get("planType"), "reached": s.get("rateLimitReachedType"),
            "credits": s.get("credits"), "at": _now()}


def usage_score(acc: Dict[str, Any]) -> int:
    """Phần trăm đã dùng cao nhất trong hai cửa sổ — tài khoản điểm thấp được ưu tiên."""
    lim = acc.get("limits") or {}
    vals = [w.get("used", 0) for w in (lim.get("primary"), lim.get("secondary")) if isinstance(w, dict)]
    return max(vals) if vals else 0


def usable(acc: Dict[str, Any], now: Optional[int] = None) -> bool:
    now = _now() if now is None else now
    # auth_error (30/10/2026): đăng nhập hỏng (token bị thu hồi / hết hạn) — đổi sang nó cũng chỉ nhận 401.
    return not acc.get("disabled") and not acc.get("auth_error") and int(acc.get("limited_until") or 0) <= now


def best(exclude: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """Tài khoản nên dùng: còn hạn mức, không tắt, dùng ít nhất; hoà thì lâu chưa dùng nhất.

    Gói ChatGPT trước, API key sau cùng: API key không có hạn mức (điểm luôn 0) nhưng TÍNH TIỀN theo
    token — chỉ dùng khi mọi gói đăng ký đã hết."""
    ex = exclude or set()
    cands = [a for a in all_accounts() if a.get("id") not in ex and usable(a)]
    if not cands:
        return None
    cands.sort(key=lambda a: (a.get("kind") == "apiKey", usage_score(a), int(a.get("last_used_at") or 0)))
    return cands[0]


def public(acc: Dict[str, Any], active_id: Optional[str] = None) -> Dict[str, Any]:
    keys = ("id", "label", "kind", "email", "plan", "disabled", "limits", "limited_until", "created_at", "last_used_at",
            "auth_error", "auth_checked_at", "probe_error")
    out = {k: acc.get(k) for k in keys}
    out["active"] = acc.get("id") == active_id
    return out
