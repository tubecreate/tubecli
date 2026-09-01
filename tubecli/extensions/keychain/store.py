"""Két tài khoản mạng xã hội của người dùng — CRUD + mã hoá at-rest.

Mỗi mục là MỘT tài khoản người dùng đang có (Facebook, TikTok, X, Discord,
Telegram, Google, hoặc generic). Ba trường nhạy cảm — mật khẩu, khôi phục, 2FA
— chỉ tồn tại trên đĩa dưới dạng đã mã hoá; mọi nơi khác (list, log, ngữ cảnh
agent) chỉ thấy bản CHE. Chủ mở một mục ra sửa mới giải mã, và chỉ cho chủ.
"""
import os
import json
import uuid
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from . import crypto

logger = logging.getLogger("KeychainStore")

# Các nền tảng két nhận biết. 'generic' là lối thoát cho dịch vụ không có mục
# riêng (một cặp user/mật khẩu, hoặc một API key nhét vào 'secret').
PLATFORMS = ["facebook", "tiktok", "x", "discord", "telegram", "google", "generic"]
STATUSES = ["active", "checkpoint", "dead"]   # đang dùng / bị chặn-xác minh / hỏng

# Trường nhạy cảm: mã hoá khi ghi, che khi đọc, giải mã CHỈ khi chủ xin reveal.
_SECRET_FIELDS = ("secret", "recovery", "totp")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KeychainStore:
    def __init__(self, data_file: str):
        self._file = data_file
        self._lock = threading.RLock()
        self._items: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ── nạp / lưu ────────────────────────────────────────────────────────
    def _ensure(self):
        if self._loaded:
            return
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        if os.path.exists(self._file):
            try:
                with open(self._file, encoding="utf-8") as f:
                    data = json.load(f)
                self._items = {x["id"]: x for x in data.get("accounts", []) if x.get("id")}
            except Exception as e:
                logger.error("Keychain: đọc %s lỗi: %s", self._file, e)
                self._items = {}
        self._loaded = True

    def _save(self):
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"accounts": list(self._items.values())}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self._file)   # thay nguyên tử, không để file dở

    # ── che / dựng ───────────────────────────────────────────────────────
    def _public(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Bản AI/giao diện được thấy: có mặt tài khoản, KHÔNG có bí mật."""
        out = {k: item.get(k) for k in
               ("id", "platform", "label", "username", "notes", "status",
                "profiles", "created_at", "updated_at")}
        # Cờ 'có hay không' thay cho giá trị — đủ để UI vẽ ô đã điền/để trống.
        for f in _SECRET_FIELDS:
            out["has_" + f] = bool(item.get(f))
        return out

    def _reveal(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Bản CHỦ sửa: giải mã bí mật ra. KHÔNG bao giờ vào log/agent/guest."""
        out = self._public(item)
        for f in _SECRET_FIELDS:
            out[f] = crypto.decrypt(item.get(f))
        return out

    def _apply_secrets(self, item: Dict[str, Any], src: Dict[str, Any]):
        """Mã hoá và ghi các bí mật CÓ MẶT trong src (thiếu thì giữ nguyên)."""
        for f in _SECRET_FIELDS:
            if f in src:
                item[f] = crypto.encrypt(src.get(f) or "")

    # ── CRUD ─────────────────────────────────────────────────────────────
    def list(self, platform: str = "", status: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure()
            items = list(self._items.values())
        if platform:
            items = [x for x in items if x.get("platform") == platform]
        if status:
            items = [x for x in items if x.get("status") == status]
        items.sort(key=lambda x: (x.get("platform") or "", (x.get("label") or "").lower()))
        return [self._public(x) for x in items]

    def get(self, acc_id: str, reveal: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure()
            item = self._items.get(acc_id)
            if not item:
                return None
            return self._reveal(item) if reveal else self._public(item)

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        platform = str(data.get("platform") or "generic").lower()
        if platform not in PLATFORMS:
            raise ValueError("platform không hợp lệ: %s" % platform)
        item = {
            "id": uuid.uuid4().hex,
            "platform": platform,
            "label": str(data.get("label") or "").strip(),
            "username": str(data.get("username") or "").strip(),
            "notes": str(data.get("notes") or "").strip(),
            "status": data.get("status") if data.get("status") in STATUSES else "active",
            "profiles": [str(p) for p in (data.get("profiles") or []) if p],
            "created_at": _now(), "updated_at": _now(),
        }
        self._apply_secrets(item, data)
        for f in _SECRET_FIELDS:
            item.setdefault(f, "")
        with self._lock:
            self._ensure()
            self._items[item["id"]] = item
            self._save()
        return self._public(item)

    def update(self, acc_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure()
            item = self._items.get(acc_id)
            if not item:
                return None
            for k in ("label", "username", "notes"):
                if k in data:
                    item[k] = str(data.get(k) or "").strip()
            if data.get("platform") in PLATFORMS:
                item["platform"] = data["platform"]
            if data.get("status") in STATUSES:
                item["status"] = data["status"]
            if "profiles" in data:
                item["profiles"] = [str(p) for p in (data.get("profiles") or []) if p]
            self._apply_secrets(item, data)
            item["updated_at"] = _now()
            self._save()
            return self._public(item)

    def delete(self, acc_id: str) -> bool:
        with self._lock:
            self._ensure()
            if acc_id in self._items:
                del self._items[acc_id]
                self._save()
                return True
            return False

    def set_status(self, acc_id: str, status: str) -> Optional[Dict[str, Any]]:
        if status not in STATUSES:
            raise ValueError("status không hợp lệ")
        return self.update(acc_id, {"status": status})

    def counts(self) -> Dict[str, int]:
        with self._lock:
            self._ensure()
            items = list(self._items.values())
        by = {}
        for x in items:
            by[x.get("platform") or "?"] = by.get(x.get("platform") or "?", 0) + 1
        by["total"] = len(items)
        return by
