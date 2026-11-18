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


# ── cụm chủ đề (18/11/2026) ───────────────────────────────────────────────────
# «Deep Biblical Echoes» làm «Matthew 6:33 — seek first the kingdom» 6 lần liền (#196–#206): mỗi ngày câu tìm kiếm
# viết khác đi một chút («what does 'seek first the kingdom' mean Matthew 6», «top What does "seek first…" mean in
# Matthew 6:33? tools»…) nên so khớp nguyên câu không bắt được. Cụm = MỘT chủ đề dù viết cách nào: cùng đoạn Kinh
# Thánh / cùng chương-câu, hay cùng phần lớn chữ mang nghĩa. Chủ đề đã có task mở, đã dựng hay đã đăng thì cả cụm nghỉ
# cooldown_days ngày (mặc định 21): không vào bộ từ khoá ngày, không làm chủ đề video.
CLUSTER_MAX = 400
CLUSTER_ALIASES = 8
CLUSTER_STATUS = ("open", "rendered", "published")       # thứ tự tăng dần — không bao giờ hạ cấp
# Chữ đứng trước một con số mà KHÔNG phải tên sách: «top 10», «part 2», «chapter 6»…
_NOT_BOOK = frozenset("""
top part parts chapter chapters verse verses episode ep day days week weeks year years month months minute minutes
step steps lesson lessons page pages vol volume no number video videos tip tips way ways reason reasons sign signs
the of in on at to for and or vs a an is are what how why
""".split())
_REF_RE = re.compile(r"\b((?:[123]\s)?[a-z]{2,})\s+(\d{1,3})(?:\s*[:.]\s*(\d{1,3})(?:\s*[-\u2013]\s*(\d{1,3}))?)?(?![0-9])")


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def scripture_refs(text: str) -> List[tuple]:
    """[(sách, chương, câu đầu | None, câu cuối | None)] — «Matthew 6:33» → ("matthew", 6, 33, 33); «Proverbs 3:5-6»
    → ("proverbs", 3, 5, 6); «Psalm 121» → ("psalm", 121, None, None). Chữ trước số không phải tên sách thì bỏ."""
    out = []
    s, pos = _fold(text), 0
    while True:
        m = _REF_RE.search(s, pos)
        if not m:
            break
        book = " ".join(m.group(1).split())
        if book.split()[-1] in _NOT_BOOK:
            pos = m.end(1)        # «and 1 Corinthians 13»: «and 1» không phải tham chiếu — tìm lại từ sau chữ «and»
            continue
        pos = m.end()
        ch = int(m.group(2))
        v1 = int(m.group(3)) if m.group(3) else None
        v2 = int(m.group(4)) if m.group(4) else v1
        out.append((book, ch, v1, v2))
    return out


def _content_words(text: str) -> frozenset:
    """Chữ mang nghĩa (bỏ chữ vỏ, bỏ số, bỏ tên sách của các tham chiếu)."""
    from .autopublish import topic_tokens

    books = {w for r in scripture_refs(text) for w in r[0].split()}
    return frozenset(t for t in topic_tokens(text) if not t.isdigit() and t not in books)


def same_cluster(a: str, b: str) -> bool:
    """Hai câu / tiêu đề cùng MỘT cụm chủ đề?

    - Cùng sách + chương: cùng câu (hay hai khoảng câu chồng nhau) ⇒ cùng cụm; câu khác hẳn («Matthew 6:9-13» và
      «Matthew 6:33») ⇒ KHÁC cụm; một bên không ghi câu ⇒ cùng cụm khi chung ≥ 2 chữ mang nghĩa («seek first»).
    - Không chung chương nào ⇒ so chữ như autopublish.similar_topic (≥ 3 chữ chung, phủ ≥ 75% câu ngắn hơn)."""
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    ra, rb = scripture_refs(a), scripture_refs(b)
    pairs = [(x, y) for x in ra for y in rb if x[0] == y[0] and x[1] == y[1]]
    if pairs:
        common = _content_words(a) & _content_words(b)
        for x, y in pairs:
            if x[2] is not None and y[2] is not None:
                if x[2] <= y[3] and y[2] <= x[3]:
                    return True
                continue
            if len(common) >= 2:
                return True
        return False
    from .autopublish import similar_topic

    return similar_topic(a, b)


def _clusters(row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    c = row.get("clusters")
    return {str(k): v for k, v in c.items() if isinstance(v, dict)} if isinstance(c, dict) else {}


def _match(clusters: Dict[str, Dict[str, Any]], texts: Iterable[str]) -> str:
    texts = [t for t in (" ".join(str(x or "").split()) for x in texts) if t]
    for cid, c in clusters.items():
        aliases = [str(c.get("label") or "")] + [str(x) for x in (c.get("aliases") or [])]
        if any(same_cluster(t, a) for t in texts for a in aliases if a):
            return cid
    return ""


def mark_cluster_used(agent_id: str, texts: Iterable[str], task_id: str = "", status: str = "open") -> str:
    """Ghi một chủ đề vào cụm của nó (tạo cụm mới khi chưa khớp cụm nào): last_used = hôm nay, uses +1 cho mỗi task
    mới, status chỉ tăng (open → rendered → published). Trả id cụm, "" khi không có gì để ghi. Không bao giờ ném."""
    texts = [t for t in (" ".join(str(x or "").split())[:200] for x in (texts or [])) if t and topic_key(t)]
    if not agent_id or not texts:
        return ""
    status = status if status in CLUSTER_STATUS else "open"
    try:
        with _LOCK:
            data = _read()
            row = data.setdefault(str(agent_id), {})
            clusters = _clusters(row)
            cid = _match(clusters, texts)
            today = _today()
            if not cid:
                cid = topic_key(texts[0])[:80]
                clusters[cid] = {"label": texts[0], "aliases": [], "first_used": today, "uses": 0, "tasks": [],
                                 "status": status}
            c = clusters[cid]
            known = {topic_key(x) for x in [c.get("label")] + list(c.get("aliases") or [])}
            for t in texts:
                if topic_key(t) not in known and len(c.get("aliases") or []) < CLUSTER_ALIASES:
                    c.setdefault("aliases", []).append(t)
                    known.add(topic_key(t))
            tasks = [str(x) for x in (c.get("tasks") or [])]
            if not task_id or str(task_id) not in tasks:
                c["uses"] = int(c.get("uses") or 0) + 1
                if task_id:
                    tasks = (tasks + [str(task_id)])[-10:]
            c["tasks"] = tasks
            c["last_used"] = today
            old = str(c.get("status") or "open")
            if CLUSTER_STATUS.index(status) > (CLUSTER_STATUS.index(old) if old in CLUSTER_STATUS else 0):
                c["status"] = status
            if len(clusters) > CLUSTER_MAX:
                clusters = dict(sorted(clusters.items(), key=lambda kv: str(kv[1].get("last_used") or ""))[-CLUSTER_MAX:])
            row["clusters"] = clusters
            _write(data)
            return cid
    except Exception as e:      # noqa: BLE001
        logger.warning("[NicheMemory] could not mark the topic cluster (%s)", e)
        return ""


def _task_alive(task_id: str) -> bool:
    """Task còn tính là «đã làm chủ đề này»: còn mở, đã xong. Huỷ / hỏng / không tìm thấy thì không."""
    try:
        from tubecli.extensions.codex.manager import codex_manager

        t = codex_manager.get_task(str(task_id))
    except Exception:       # noqa: BLE001 — không hỏi được bảng việc thì coi như còn (thà nghỉ thêm còn hơn làm trùng)
        return True
    return bool(t) and str(t.get("status") or "") not in ("cancelled", "failed", "rejected")


def cooled_clusters(agent_id: str, within_days: int, exclude_task: str = "") -> List[Dict[str, Any]]:
    """Các cụm đang nghỉ (dùng trong `within_days` ngày gần nhất), mới nhất trước: [{id, label, last_used, uses,
    status, tasks}]. Cụm chỉ có task MỞ mà các task ấy đã bị huỷ / hỏng thì không tính — chủ đề chưa thật sự làm.
    exclude_task: task đang chạy — cụm chỉ do CHÍNH nó ghi thì không tính (task không tự chặn mình)."""
    days = max(0, int(within_days or 0))
    if days <= 0:
        return []
    seed_from_tasks(agent_id, days)
    out = []
    ex = str(exclude_task or "")
    for cid, c in _clusters(_read().get(str(agent_id)) or {}).items():
        if _days_ago(c.get("last_used", "")) > days:
            continue
        tasks = [str(t) for t in (c.get("tasks") or [])]
        others = [t for t in tasks if t != ex]
        if ex and tasks and not others:
            continue
        if str(c.get("status") or "open") == "open" and others and not any(_task_alive(t) for t in others):
            continue
        out.append(dict(c, id=cid))
    out.sort(key=lambda c: str(c.get("last_used") or ""), reverse=True)
    return out


_GENERIC_TITLES = ("auto publish:", "auto video:", "auto publish ·", "auto video ·")
_SEEDED: set = set()


def seed_from_tasks(agent_id: str, within_days: int) -> int:
    """MỘT lần cho mỗi agent: nạp sổ cụm từ các task video của agent trên bảng việc (trong `within_days` ngày) — máy
    vừa lên bản có sổ cụm vẫn biết «Matthew 6:33» đã làm 6 lần. Task huỷ / hỏng không tính. Trả số task đã nạp."""
    aid = str(agent_id or "")
    if not aid or aid in _SEEDED:
        return 0
    _SEEDED.add(aid)
    row = _read().get(aid) or {}
    if row.get("clusters_seeded"):
        return 0
    n = 0
    try:
        from tubecli.extensions.codex.manager import codex_manager as cm

        tasks = cm.list_tasks(limit=500) or []
        for t in reversed(tasks):           # cũ trước ⇒ last_used của task mới nhất thắng
            if str(t.get("assignee_id") or "") != aid:
                continue
            st = str(t.get("status") or "")
            if st in ("cancelled", "failed", "rejected"):
                continue
            day = str(t.get("created_at") or "")[:10]
            if _days_ago(day) > max(0, int(within_days or 0)):
                continue
            title = str(t.get("title") or "")
            meta = t.get("meta") or {}
            texts = [title if not title.casefold().startswith(_GENERIC_TITLES) else "",
                     str(meta.get("topic_query") or ""), str(meta.get("bank_topic") or "")]
            texts = [x for x in texts if x]
            if not texts:
                continue
            status = "open"
            if st == "done":
                try:
                    status = "published" if cm.published_video(str(t.get("id"))) else "rendered"
                except Exception:       # noqa: BLE001
                    status = "rendered"
            elif st == "review":
                status = "rendered"
            if mark_cluster_used(aid, texts, str(t.get("id") or ""), status):
                n += 1
                _set_last_used(aid, texts, day)
    except Exception as e:      # noqa: BLE001
        logger.info("[NicheMemory] could not seed topic clusters from the task board (%s)", e)
        _SEEDED.discard(aid)
        return n
    with _LOCK:
        data = _read()
        data.setdefault(aid, {})["clusters_seeded"] = _today()
        _write(data)
    return n


def _set_last_used(agent_id: str, texts: List[str], day: str) -> None:
    """Nạp từ lịch sử: last_used = ngày của task (không phải hôm nay), chỉ đi tới."""
    if not day:
        return
    with _LOCK:
        data = _read()
        row = data.get(str(agent_id)) or {}
        clusters = _clusters(row)
        cid = _match(clusters, texts)
        if not cid:
            return
        c = clusters[cid]
        if c.get("_seed_day") is None or day > str(c.get("_seed_day")):
            c["_seed_day"] = day
            c["last_used"] = day
            c["first_used"] = min(str(c.get("first_used") or day), day)
        row["clusters"] = clusters
        data[str(agent_id)] = row
        _write(data)


def cluster_cooldown(agent_id: str, text: str, within_days: int, cooled: List[Dict[str, Any]] = None):
    """Cụm đang nghỉ mà `text` thuộc về, hay None. Truyền `cooled` (từ cooled_clusters) khi so nhiều câu một lượt."""
    if not str(text or "").strip():
        return None
    for c in (cooled if cooled is not None else cooled_clusters(agent_id, within_days)):
        aliases = [str(c.get("label") or "")] + [str(x) for x in (c.get("aliases") or [])]
        if any(same_cluster(text, a) for a in aliases if a):
            return c
    return None


def cooldown_days_of(agent) -> int:
    """cooldown_days của ngách agent (mặc định 21)."""
    try:
        from tubecli.core import niche as _N

        cfg, _w = _N.effective(agent)
        return int(cfg.get("cooldown_days") or 0)
    except Exception:       # noqa: BLE001
        return 21
