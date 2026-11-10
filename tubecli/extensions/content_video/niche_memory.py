"""Trí nhớ của bộ lọc ngách theo từng agent (10/11/2026).

Hai việc mà mỗi lượt tự động trước đây làm lại từ đầu:

1. NGUỒN ĐÃ BỊ LOẠI (GATE_REJECT). Kênh Kinh Thánh «Deep Biblical Echoes» đọc lại đúng 30 bài công nghệ mỗi ngày, chấm
   lại 30 lần, loại lại 30 lần — tốn 30 lượt gọi model và lần nào cũng dừng «0 of 30 sources fit». Bài đã bị loại thì
   đánh dấu ở đây; bước gom bỏ qua chúng trong REJECT_DAYS ngày (không xoá khỏi kho thu thập — kho là của người dùng).
2. CHỦ ĐỀ ĐÃ DÙNG. Khi nguồn đúng ngách không đủ, pipeline lấy chủ đề trong kho từ khoá của agent (daily_keywords);
   chủ đề đã làm trong cooldown_days ngày (mặc định 21, agent.niche.cooldown_days) thì không lấy lại.

Lưu ở <ext data>/content_video/niche_memory.json, ghi tmp + os.replace như autopublish. Best-effort: đọc hỏng → {},
ghi hỏng → log rồi bỏ — trí nhớ hỏng chỉ làm lượt sau chấm lại, không bao giờ chặn một video.
"""
import datetime
import json
import logging
import os
import re
import threading
import unicodedata
from typing import Any, Dict, Iterable, List

logger = logging.getLogger("ContentVideo")

STORE_FILE = "niche_memory.json"
REJECT_DAYS = 30            # nguồn bị loại được bỏ qua chừng này ngày (bài cũ hơn cũng đã quá hạn độ mới)
REJECT_MAX = 3000           # mỗi agent giữ tối đa chừng này URL bị loại (mới nhất thắng)
TOPIC_MAX = 500
_LOCK = threading.Lock()


def _store_path():
    from tubecli.config import ext_data_path

    return ext_data_path("content_video", STORE_FILE)


def _read() -> Dict[str, Dict[str, Any]]:
    try:
        path = str(_store_path())
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except Exception as e:      # noqa: BLE001
        logger.warning("[NicheMemory] store unreadable (%s) — starting from empty", e)
        return {}


def _write(data: Dict[str, Dict[str, Any]]) -> bool:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, str(path))
        return True
    except Exception as e:      # noqa: BLE001
        logger.warning("[NicheMemory] could not write the store (%s)", e)
        return False


def _today() -> str:
    return datetime.date.today().isoformat()


def _days_ago(day: str) -> int:
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(str(day)[:10])).days
    except (TypeError, ValueError):
        return 10 ** 6


def topic_key(text: str) -> str:
    """Khoá so chủ đề: chữ thường, bỏ dấu, bỏ dấu câu — «What does "salt of the earth" mean?» ≈ «what does salt …»."""
    s = unicodedata.normalize("NFKD", str(text or "")).casefold()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())[:160]


# ── nguồn bị loại ─────────────────────────────────────────────────────────────
def rejected_urls(agent_id: str) -> Dict[str, str]:
    """{url: ngày bị loại} còn hiệu lực (≤ REJECT_DAYS ngày)."""
    row = _read().get(str(agent_id)) or {}
    rej = row.get("rejected") if isinstance(row.get("rejected"), dict) else {}
    return {u: d for u, d in rej.items() if _days_ago(d) <= REJECT_DAYS}


def mark_rejected(agent_id: str, urls: Iterable[str]) -> int:
    urls = [str(u).strip() for u in urls if str(u or "").strip()]
    if not agent_id or not urls:
        return 0
    with _LOCK:
        data = _read()
        row = data.setdefault(str(agent_id), {})
        rej = row.get("rejected") if isinstance(row.get("rejected"), dict) else {}
        rej = {u: d for u, d in rej.items() if _days_ago(d) <= REJECT_DAYS}
        today = _today()
        for u in urls:
            rej[u] = today
        if len(rej) > REJECT_MAX:
            rej = dict(sorted(rej.items(), key=lambda kv: kv[1])[-REJECT_MAX:])
        row["rejected"] = rej
        _write(data)
    return len(urls)


def clear_rejected(agent_id: str, urls: Iterable[str] = ()) -> int:
    """Gỡ dấu loại (một số URL, hay tất cả khi `urls` rỗng) — chủ agent sửa ngách xong muốn chấm lại kho."""
    with _LOCK:
        data = _read()
        row = data.get(str(agent_id)) or {}
        rej = row.get("rejected") if isinstance(row.get("rejected"), dict) else {}
        want = [str(u) for u in urls if u]
        n = len(rej) if not want else sum(1 for u in want if u in rej)
        row["rejected"] = {} if not want else {u: d for u, d in rej.items() if u not in want}
        data[str(agent_id)] = row
        _write(data)
    return n


# ── chủ đề đã dùng ────────────────────────────────────────────────────────────
def used_topics(agent_id: str, within_days: int) -> Dict[str, str]:
    """{khoá chủ đề: ngày dùng} trong `within_days` ngày gần nhất."""
    row = _read().get(str(agent_id)) or {}
    used = row.get("topics") if isinstance(row.get("topics"), dict) else {}
    return {k: v.get("day", "") if isinstance(v, dict) else str(v) for k, v in used.items()
            if _days_ago(v.get("day", "") if isinstance(v, dict) else v) <= max(0, int(within_days))}


def mark_topic_used(agent_id: str, topic: str, task_id: str = "") -> None:
    key = topic_key(topic)
    if not agent_id or not key:
        return
    with _LOCK:
        data = _read()
        row = data.setdefault(str(agent_id), {})
        used = row.get("topics") if isinstance(row.get("topics"), dict) else {}
        used[key] = {"day": _today(), "topic": str(topic)[:200], "task_id": str(task_id or "")[:40]}
        if len(used) > TOPIC_MAX:
            used = dict(sorted(used.items(), key=lambda kv: str((kv[1] or {}).get("day", "")))[-TOPIC_MAX:])
        row["topics"] = used
        _write(data)


def bank_candidates(agent) -> List[str]:
    """Kho từ khoá của agent theo thứ tự ưu tiên: từ khoá HÔM NAY (daily_keywords, đủ 4 buổi) rồi các câu đã dùng gần
    đây (used_keywords_today) — không trùng. Chưa có «keyword bank» riêng (cụm + điểm): đây là thứ gần nhất mà agent đã
    tự sinh theo research brief và ngách của nó."""
    routine = getattr(agent, "routine", None) or {}
    out: List[str] = []
    seen = set()

    def add(q) -> None:
        q = " ".join(str(q or "").split())
        k = topic_key(q)
        if q and k and k not in seen:
            seen.add(k)
            out.append(q)

    dk = routine.get("daily_keywords") if isinstance(routine.get("daily_keywords"), dict) else {}
    for period in ("morning", "afternoon", "evening", "night"):
        for q in (dk.get(period) or []) if isinstance(dk.get(period), list) else []:
            add(q)
    used = routine.get("used_keywords_today") if isinstance(routine.get("used_keywords_today"), dict) else {}
    for qs in (used.get("used") or {}).values() if isinstance(used.get("used"), dict) else []:
        for q in qs if isinstance(qs, list) else []:
            add(q)
    return out
