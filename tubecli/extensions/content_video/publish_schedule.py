"""Hẹn giờ đăng YouTube theo KHUNG GIỜ HẰNG NGÀY.

User 10/10/2026: «thêm logic tự động up youtube (lập lịch hẹn giờ), chọn phương thức upload gồm auth hoặc
remote trình duyệt» — chốt: khung giờ hằng ngày (vd. 08:00, 19:00), video xong thì TẢI LÊN NGAY ở chế độ hẹn giờ
và YouTube tự công khai đúng khung trống kế tiếp, mỗi khung một video; có ở cả form Codex lẫn agent tự đăng.

Vì sao tải lên ngay thay vì giữ video chờ tới giờ: một lượt chờ nhiều giờ trong máy chết theo mọi lần restart,
còn mốc hẹn giờ nằm trên YouTube thì không. Sổ đặt chỗ (publish_slots.json) chỉ để hai video của CÙNG một kênh
không giành chung một khung.

Giờ của khung là giờ của NGƯỜI ĐẶT (trình duyệt gửi múi giờ IANA + phút lệch UTC), không phải giờ của máy chủ:
máy chủ thường là VPS ở múi giờ khác. Python không có dữ liệu múi giờ (tzdata thiếu trên Windows) thì lùi về số
phút lệch; không ai gửi gì thì dùng giờ máy.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STORE_FILE = "publish_slots.json"
# Khung gần hơn mức này thì lấy khung sau: tải lên + YouTube xử lý cần thời gian, và YouTube/Studio từ chối giờ
# công khai đã qua (lượt tải 30 phút xong thì khung 10 phút nữa đã thành quá khứ).
LEAD_SEC = 30 * 60
# Giờ tự chọn («Pick a date & time») phải còn ít nhất chừng này; sát hơn thì đăng ngay.
MIN_AHEAD_SEC = 15 * 60
HORIZON_DAYS = 60
MAX_SLOTS = 12
KEEP_SEC = 2 * 86400            # mốc đã qua 2 ngày thì bỏ khỏi sổ
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_LOCK = threading.Lock()
_SLOT_RE = re.compile(r"^(\d{1,2})(?:\s*[:hH.]\s*(\d{2})?)?\s*([aApP][mM])?$")


def parse_slots(value: Any) -> List[str]:
    """«08:00, 19h30, 7pm» → ["08:00", "19:00", "19:30"]: sắp xếp, bỏ trùng, bỏ ô hỏng, tối đa MAX_SLOTS."""
    if isinstance(value, (list, tuple)):
        tokens = [str(x) for x in value]
    else:
        tokens = re.split(r"[,;\n]+|\s{2,}|\s+(?=\d)", str(value or ""))
    out = set()
    for tok in tokens:
        m = _SLOT_RE.match(tok.strip())
        if not m:
            continue
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap:
            if not 1 <= h <= 12:
                continue
            h = (h % 12) + (12 if ap == "pm" else 0)
        if h > 23 or mi > 59:
            continue
        out.add(f"{h:02d}:{mi:02d}")
    return sorted(out)[:MAX_SLOTS]


def slots_text(value: Any) -> str:
    return ", ".join(parse_slots(value))


def resolve_tz(name: str = "", offset_min: Any = None) -> tzinfo:
    """Múi giờ IANA ("Asia/Ho_Chi_Minh") → ZoneInfo; không có dữ liệu múi giờ thì giờ lệch cố định offset_min
    (phút về phía đông UTC, như -Date.getTimezoneOffset()); không ai gửi gì → giờ của máy."""
    name = str(name or "").strip()
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:       # noqa: BLE001 — thiếu tzdata / tên lạ
            pass
    try:
        if offset_min not in (None, ""):
            off = max(-840, min(840, int(float(offset_min))))
            return timezone(timedelta(minutes=off), name) if name else timezone(timedelta(minutes=off))
    except (TypeError, ValueError):
        pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def tz_label(tz: tzinfo, at: int) -> str:
    """«Asia/Ho_Chi_Minh, GMT+07:00» — tên nếu có, luôn kèm độ lệch của đúng ngày đó (giờ mùa hè)."""
    d = datetime.fromtimestamp(at, tz)
    z = d.strftime("%z") or "+0000"
    off = f"GMT{z[0]}{z[1:3]}:{z[3:5]}"
    name = str(getattr(tz, "key", "") or "")
    return f"{name}, {off}" if name else off


def when_label(at: int, tz: tzinfo) -> str:
    return datetime.fromtimestamp(at, tz).strftime("%Y-%m-%d %H:%M") + f" ({tz_label(tz, at)})"


def iso_utc(at: int) -> str:
    """RFC 3339 cho status.publishAt của YouTube Data API."""
    return datetime.fromtimestamp(int(at), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def studio_date_time(at: int, tz: tzinfo) -> Dict[str, str]:
    """Ngày/giờ dạng script YouTube Studio đọc ('Oct 11, 2026' + '19:00') theo múi giờ `tz`. Bước
    t2:schedule-local trong script còn đổi lại theo múi giờ THẬT của trình duyệt (hồ sơ có thể giả múi giờ)."""
    d = datetime.fromtimestamp(at, tz)
    return {"date": f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}", "time": d.strftime("%H:%M")}


def candidates(slots: List[str], tz: tzinfo, after: float, days: int = HORIZON_DAYS):
    """Các mốc (epoch giây) theo thứ tự thời gian, từ sau `after`, qua `days` ngày theo lịch của `tz`."""
    start = datetime.fromtimestamp(after, tz).date()
    for i in range(days + 1):
        day = start + timedelta(days=i)
        for s in slots:
            h, m = (int(x) for x in s.split(":"))
            local = datetime(day.year, day.month, day.day, h, m)
            try:
                at = int(local.replace(tzinfo=tz).timestamp())
            except Exception:       # noqa: BLE001
                continue
            if at > after:
                yield at


# ── Sổ đặt chỗ ─────────────────────────────────────────────────────────
# {kênh: [{"at": epoch, "task": task_id, "booked_at": epoch}]}

def _store_path():
    from tubecli.config import ext_data_path

    return ext_data_path("content_video", STORE_FILE)


def _read() -> Dict[str, List[Dict[str, Any]]]:
    try:
        path = _store_path()
        if not os.path.isfile(str(path)):
            return {}
        with open(str(path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return {str(k): [e for e in v if isinstance(e, dict) and isinstance(e.get("at"), (int, float))]
                for k, v in data.items() if isinstance(v, list)}
    except Exception as e:      # noqa: BLE001
        logger.warning("[PublishSlots] store unreadable (%s) — starting from empty", e)
        return {}


def _write(data: Dict[str, List[Dict[str, Any]]]) -> None:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, str(path))
    except Exception as e:      # noqa: BLE001 — sổ hỏng không được chặn lượt đăng
        logger.warning("[PublishSlots] could not write the store (%s)", e)


def _prune(data: Dict[str, List[Dict[str, Any]]], now: float) -> None:
    for k in list(data):
        data[k] = [e for e in data[k] if e["at"] >= now - KEEP_SEC]
        if not data[k]:
            del data[k]


def book_next(key: str, slots: List[str], task_id: str = "", tz: Optional[tzinfo] = None,
              now: Optional[float] = None) -> Optional[int]:
    """Giữ khung trống kế tiếp của kênh `key` cho task. Task đã giữ một khung còn hợp lệ (chạy lại sau restart /
    Retry) thì dùng lại đúng khung đó. None = không có khung nào trong HORIZON_DAYS ngày tới."""
    if not slots:
        return None
    tz = tz or resolve_tz()
    now = time.time() if now is None else now
    key = str(key or "default")
    with _LOCK:
        data = _read()
        _prune(data, now)
        mine = data.setdefault(key, [])
        for e in mine:
            if task_id and e.get("task") == task_id and e["at"] >= now + LEAD_SEC:
                return int(e["at"])
        taken = {int(e["at"]) // 60 for e in mine if e.get("task") != task_id or not task_id}
        for at in candidates(slots, tz, now + LEAD_SEC):
            if at // 60 not in taken:
                mine[:] = [e for e in mine if not (task_id and e.get("task") == task_id)]
                mine.append({"at": at, "task": task_id, "booked_at": int(now)})
                _write(data)
                return at
    return None


def book_at(key: str, at: int, task_id: str = "", now: Optional[float] = None) -> int:
    """Ghi một giờ tự chọn vào sổ (để khung hằng ngày không xếp thêm video vào đúng phút đó)."""
    now = time.time() if now is None else now
    key = str(key or "default")
    with _LOCK:
        data = _read()
        _prune(data, now)
        mine = data.setdefault(key, [])
        mine[:] = [e for e in mine if not (task_id and e.get("task") == task_id)]
        mine.append({"at": int(at), "task": task_id, "booked_at": int(now)})
        _write(data)
    return int(at)


def release(key: str, at: Optional[int] = None, task_id: str = "") -> None:
    """Trả khung (lượt đăng hỏng) — khung đó lại trống cho video sau."""
    key = str(key or "default")
    with _LOCK:
        data = _read()
        before = len(data.get(key) or [])
        data[key] = [e for e in (data.get(key) or [])
                     if not ((task_id and e.get("task") == task_id) or (at is not None and int(e["at"]) == int(at)))]
        if len(data[key]) != before:
            if not data[key]:
                del data[key]
            _write(data)


def booked(key: str) -> List[Dict[str, Any]]:
    return list(_read().get(str(key or "default")) or [])
