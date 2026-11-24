"""Két tài khoản mạng xã hội của người dùng — CRUD + mã hoá at-rest.

Mỗi mục là MỘT tài khoản người dùng đang có (Facebook, TikTok, X, Discord,
Telegram, Google, hoặc generic). Ba trường nhạy cảm — mật khẩu, khôi phục, 2FA
— chỉ tồn tại trên đĩa dưới dạng đã mã hoá; mọi nơi khác (list, log, ngữ cảnh
agent) chỉ thấy bản CHE. Chủ mở một mục ra sửa mới giải mã, và chỉ cho chủ.
"""
import os
import re
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
# proxy (24/11/2026): chuỗi proxy thường mang user:mật khẩu của nhà cung cấp — cũng là bí mật; danh sách chỉ hiện host:port.
_SECRET_FIELDS = ("secret", "recovery", "totp", "proxy")
# Cloud đọc để biết két này hiểu nhóm / proxy / dán hàng loạt chưa (máy cũ bỏ qua trường lạ = mất dữ liệu người dùng dán).
FEATURES = ["groups", "proxy", "bulk"]
MAX_GROUP = 60
MAX_BULK = 2000

_PROXY_AT = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?\S*@\[?([A-Za-z0-9.\-]+|[0-9a-fA-F:]+)\]?:(\d{1,5})/?$", re.I)
_PROXY_PLAIN = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?\[?([A-Za-z0-9.\-]+|[0-9a-fA-F:]+)\]?:(\d{1,5})(?::[^:\s]+:.+)?/?$", re.I)


def proxy_host(raw: str) -> str:
    """host:port của một chuỗi proxy (không bao giờ kèm user/mật khẩu); "" nếu không đọc được.

    Nhận: host:port · host:port:user:pass (dạng nhà cung cấp) · user:pass@host:port · scheme://… của các dạng trên."""
    v = str(raw or "").strip()
    if not v or any(c.isspace() for c in v):
        return ""
    m = _PROXY_AT.match(v) if "@" in v else _PROXY_PLAIN.match(v)
    if not m or not (0 < int(m.group(2)) < 65536):
        return ""
    host = m.group(1)
    return f"[{host}]:{m.group(2)}" if ":" in host else f"{host}:{m.group(2)}"


def clean_group(raw) -> str:
    return " ".join(str(raw or "").split())[:MAX_GROUP]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KeychainStore:
    def __init__(self, data_file: str):
        self._file = data_file
        self._lock = threading.RLock()
        self._items: Dict[str, Dict[str, Any]] = {}
        self._groups: List[str] = []          # nhóm chủ tạo bằng «+» — sống cả khi chưa có tài khoản nào
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
                self._groups = [g for g in (clean_group(x) for x in data.get("groups") or []) if g]
            except Exception as e:
                logger.error("Keychain: đọc %s lỗi: %s", self._file, e)
                self._items = {}
        self._loaded = True

    def _save(self):
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"accounts": list(self._items.values()), "groups": self._groups}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self._file)   # thay nguyên tử, không để file dở

    # ── che / dựng ───────────────────────────────────────────────────────
    def _public(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Bản AI/giao diện được thấy: có mặt tài khoản, KHÔNG có bí mật."""
        out = {k: item.get(k) for k in
               ("id", "platform", "label", "username", "notes", "status",
                "profile", "profiles", "created_at", "updated_at")}
        out["group"] = item.get("group") or ""
        out["proxy_host"] = item.get("proxy_host") or ""
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
        if "proxy" in src:
            item["proxy_host"] = proxy_host(src.get("proxy"))

    # ── CRUD ─────────────────────────────────────────────────────────────
    def list(self, platform: str = "", status: str = "", group: Optional[str] = None) -> List[Dict[str, Any]]:
        """group=None: mọi nhóm; group="": tài khoản chưa có nhóm."""
        with self._lock:
            self._ensure()
            items = list(self._items.values())
        if platform:
            items = [x for x in items if x.get("platform") == platform]
        if status:
            items = [x for x in items if x.get("status") == status]
        if group is not None:
            g = clean_group(group).lower()
            items = [x for x in items if (x.get("group") or "").lower() == g]
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
        with self._lock:
            self._ensure()
            if data.get("group"):
                data = {**data, "group": self._group_name(data["group"])}
        item = self._new_item(data)
        with self._lock:
            self._ensure()
            self._items[item["id"]] = item
            self._save()
        return self._public(item)

    def _new_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
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
            "profile": str(data.get("profile") or "").strip(),
            "profiles": [str(p) for p in (data.get("profiles") or []) if p],
            "group": clean_group(data.get("group")),
            "created_at": _now(), "updated_at": _now(),
        }
        self._apply_secrets(item, data)
        for f in _SECRET_FIELDS:
            item.setdefault(f, "")
        item.setdefault("proxy_host", "")
        return item

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
            if "group" in data:
                item["group"] = self._group_name(data.get("group"))
            if "profile" in data:
                item["profile"] = str(data.get("profile") or "").strip()
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

    def find(self, platform: str, username: str) -> Optional[Dict[str, Any]]:
        """Tài khoản cùng nền tảng + tên đăng nhập (không phân biệt hoa thường) — bản công khai."""
        u = str(username or "").strip().lower()
        if not u:
            return None
        with self._lock:
            self._ensure()
            for x in self._items.values():
                if x.get("platform") == platform and (x.get("username") or "").strip().lower() == u:
                    return self._public(x)
        return None

    def bulk_upsert(self, rows: List[Dict[str, Any]], on_exists: str = "update") -> Dict[str, Any]:
        """Nhập nhiều tài khoản, GHI ĐĨA MỘT LẦN. on_exists: update (ghi đè trường được đưa) | skip.

        Mỗi dòng: {platform, username, secret?, recovery?, totp?, proxy?, group?, label?, notes?, status?, _line?}.
        Kết quả không bao giờ chứa bí mật."""
        made, updated, skipped, errors = 0, 0, 0, []
        with self._lock:
            self._ensure()
            index = {((x.get("platform") or ""), (x.get("username") or "").strip().lower()): x
                     for x in self._items.values()}
            for i, raw in enumerate(rows[:MAX_BULK], 1):
                line = raw.get("_line") or i
                data = {k: v for k, v in raw.items() if not str(k).startswith("_")}
                platform = str(data.get("platform") or "generic").lower()
                user = str(data.get("username") or "").strip()
                if platform not in PLATFORMS:
                    errors.append({"line": line, "reason": "unknown platform"})
                    continue
                if not user:
                    errors.append({"line": line, "reason": "missing username / email"})
                    continue
                if data.get("proxy") and not proxy_host(data["proxy"]):
                    errors.append({"line": line, "user": user, "reason": "proxy not understood"})
                    continue
                cur = index.get((platform, user.lower()))
                if cur is not None:
                    if on_exists == "skip":
                        skipped += 1
                        continue
                    for k in ("label", "notes"):
                        if data.get(k):
                            cur[k] = str(data[k]).strip()
                    if "group" in data:
                        cur["group"] = self._group_name(data.get("group"))
                    if data.get("status") in STATUSES:
                        cur["status"] = data["status"]
                    # chuỗi rỗng KHÔNG xoá bí mật đã lưu (ô trống trong bảng dán ≠ «xoá mật khẩu»)
                    self._apply_secrets(cur, {f: data[f] for f in _SECRET_FIELDS if data.get(f)})
                    cur["updated_at"] = _now()
                    updated += 1
                    continue
                if not data.get("label"):
                    data["label"] = user
                data["platform"], data["username"] = platform, user
                if "group" in data:
                    data["group"] = self._group_name(data.get("group"))
                item = self._new_item(data)
                self._items[item["id"]] = item
                index[(platform, user.lower())] = item
                made += 1
            if len(rows) > MAX_BULK:
                errors.append({"line": MAX_BULK + 1, "reason": "too many rows (max %d per paste)" % MAX_BULK})
            if made or updated:
                self._save()
        return {"created": made, "updated": updated, "skipped": skipped, "errors": errors}

    def groups(self) -> Dict[str, int]:
        """Tên nhóm → số tài khoản ("" = chưa có nhóm). Gồm cả nhóm đã tạo mà chưa có tài khoản."""
        with self._lock:
            self._ensure()
            items = list(self._items.values())
            out: Dict[str, int] = {g: 0 for g in self._groups}
        for x in items:
            g = x.get("group") or ""
            out[g] = out.get(g, 0) + 1
        return out

    def _group_name(self, name: str) -> str:
        """Tên nhóm đã có (giữ cách viết cũ khi chỉ khác hoa thường), hoặc tên đã làm sạch."""
        g = clean_group(name)
        for known in list(self._groups) + [x.get("group") or "" for x in self._items.values()]:
            if known and known.lower() == g.lower():
                return known
        return g

    def add_group(self, name: str) -> str:
        with self._lock:
            self._ensure()
            g = self._group_name(name)
            if not g:
                raise ValueError("group name is empty")
            if g not in self._groups:
                self._groups.append(g)
                self._save()
            return g

    def delete_group(self, name: str) -> Dict[str, Any]:
        """Xoá NHÓM, không xoá tài khoản: tài khoản trong nhóm về «chưa có nhóm»."""
        with self._lock:
            self._ensure()
            g = clean_group(name).lower()
            if not g:
                raise ValueError("group name is empty")
            moved = 0
            for x in self._items.values():
                if (x.get("group") or "").lower() == g:
                    x["group"] = ""
                    x["updated_at"] = _now()
                    moved += 1
            before = len(self._groups)
            self._groups = [x for x in self._groups if x.lower() != g]
            if moved or len(self._groups) != before:
                self._save()
            return {"deleted": bool(moved or len(self._groups) != before), "moved": moved}

    def counts(self) -> Dict[str, int]:
        with self._lock:
            self._ensure()
            items = list(self._items.values())
        by = {}
        for x in items:
            by[x.get("platform") or "?"] = by.get(x.get("platform") or "?", 0) + 1
        by["total"] = len(items)
        return by
