"""Việc nào đang chạy cho cảnh nào — model gì, ghế nào, máy nào (22/10/2026).

User (Live view của bảng việc, ô cảnh chưa có ảnh): «chỗ placeholder hiển thị loading biết ảnh đó đang chạy model nào ở ghế
nào, ở máy chủ nào». Ai GỌI biết cảnh (Content Studio: lô vẽ ảnh, lô clip Muse); ai CHẠY biết model thật sau đường lùi
(image_gen._generate_bytes) và ghế / nút Muse (muse.ask). Hai bên không gọi thẳng nhau nên nhãn cảnh đi theo
`contextvars`: bên gọi `begin("shot:<id>")` trong coroutine của cảnh, mọi lượt vẽ / quay bên dưới — kể cả qua
asyncio.to_thread (chép context) — `note(...)` vào đúng dòng ấy. Không có nhãn thì note() không làm gì.

Chỉ là bảng báo cáo: không hàm nào được ném lỗi ra ngoài.
"""
import contextvars
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

TAG: "contextvars.ContextVar[str]" = contextvars.ContextVar("tubecli_live_job_tag", default="")
_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
# Dòng mồ côi (bên gọi chết giữa chừng, không kịp finish) — bỏ sau chừng này giây kể từ lần ghi cuối.
STALE_SEC = 3 * 3600
FIELDS = ("provider", "model", "seat", "server", "job")


class _Token:
    __slots__ = ("tag", "cv")

    def __init__(self, tag: str, cv):
        self.tag, self.cv = tag, cv


def begin(tag: str) -> Optional[_Token]:
    """Gắn nhãn `tag` cho coroutine / luồng hiện tại và mở một dòng. Trả token cho finish()."""
    tag = str(tag or "").strip()
    if not tag:
        return None
    try:
        cv = TAG.set(tag)
        with _LOCK:
            _JOBS[tag] = {"created": time.time(), "at": time.time()}
        return _Token(tag, cv)
    except Exception:       # noqa: BLE001
        return None


def finish(token: Optional[_Token]) -> None:
    """Đóng dòng của token và trả nhãn về như trước begin()."""
    if token is None:
        return
    try:
        with _LOCK:
            _JOBS.pop(token.tag, None)
        TAG.reset(token.cv)
    except Exception:       # noqa: BLE001 — reset ở context khác (hiếm) thì thôi, dòng đã gỡ
        pass


def note(since: Optional[bool] = None, **info: Any) -> None:
    """Ghi model / ghế / máy cho dòng của nhãn HIỆN TẠI. Không có nhãn → không làm gì.

    `since` = mốc «lần thử này chạy từ lúc» trên ô: True đặt lại = bây giờ (bắt đầu gọi nhà vẽ / vừa giữ được ghế Muse),
    False xoá (đang CHỜ ghế — chưa chạy), None giữ nguyên (lần ghi có model / ghế đầu tiên thì đặt)."""
    try:
        tag = TAG.get()
        if not tag:
            return
        now = time.time()
        with _LOCK:
            row = _JOBS.setdefault(tag, {"created": now})
            for k in FIELDS:
                v = info.get(k)
                if v is not None:
                    row[k] = str(v)[:120]
            if since is True or (since is None and "since" not in row and (info.get("model") or info.get("seat"))):
                row["since"] = now
            elif since is False:
                row.pop("since", None)
            row["at"] = now
    except Exception:       # noqa: BLE001
        pass


def snapshot(prefix: str = "") -> Dict[str, Dict[str, Any]]:
    """{nhãn: {provider, model, seat, server, job, since, at}} — bản sao, đã bỏ dòng mồ côi."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        now = time.time()
        with _LOCK:
            for tag in [t for t, r in _JOBS.items() if now - float(r.get("at") or 0) > STALE_SEC]:
                _JOBS.pop(tag, None)
            for tag, row in _JOBS.items():
                if not prefix or tag.startswith(prefix):
                    out[tag] = dict(row)
    except Exception:       # noqa: BLE001
        pass
    return out


def host_of(url: str) -> str:
    """Tên máy trong một địa chỉ (https://tungho2-23.tubecreate.com/api/v1/muse → tungho2-23.tubecreate.com)."""
    try:
        return urlparse(str(url or "")).hostname or ""
    except Exception:       # noqa: BLE001
        return ""


_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def server_of(url: str) -> str:
    """Máy chủ để HIỆN: «local» khi địa chỉ trỏ về chính máy này (9Router ở 127.0.0.1:20128), không thì tên máy."""
    h = host_of(url)
    return "local" if h in _LOOPBACK else h
