"""Read layer for everything the browser agents have scraped.

The scraper writes TWO files per profile and they hold different halves of the
same record:

  scraped_data/<profile>/history.json   {"scrapedArticles": [...]}   ~500 rows
        title, url, ip, author, imageCount, contentLength, scrapedAt,
        isScraped, agentId, agentName
  scraped_data/<profile>/articles.json  [...]                        ~100 rows
        title, url, description, author, publishedDate, content,
        images[], imageCount, scrapedAt

Note which field is missing from the second one: **articles.json has no
agentId**. Only the history knows who scraped what. So "give me the articles
this agent collected" cannot be answered by filtering articles.json — that
filter matches nothing, every time. The two files are joined on `url`, and
history is the side that carries ownership.

The caps differ too (500 vs 100), and they are separate slices of separate
lists. An entry can therefore be listed in history with `isScraped: true` while
its body has already aged out of articles.json. That is not corruption, it is
the retention policy, and it is reported as `has_content: false` rather than
being silently dropped or served as an empty string.

Times: the scraper stamps `new Date().toISOString()`, which is UTC. "Hôm nay"
is not. Unless the offset is exactly zero, a local day straddles two UTC dates,
so matching one UTC date as a substring is wrong in both directions at once. In
UTC+7 the local day runs from 17:00Z the previous day to 17:00Z: anything
scraped between midnight and 07:00 local carries YESTERDAY's UTC date and is
lost, while tomorrow's small hours carry today's and are counted in. Day
boundaries here are computed in the machine's local zone and converted to real
instants, never string-matched.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import unicodedata
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Retention, as implemented by the scraper. Named here so the numbers in a
# "why is the body missing" answer come from one place.
HISTORY_CAP = 500
ARTICLE_CAP = 100

_SNIPPET = 240


# ── Where the data lives ────────────────────────────────────────────────────

def data_root() -> Path:
    """The scraped_data directory the scraper actually writes to.

    extract_content.js resolves it relative to its own file, so the package
    directory is canonical. extensions_data/ is checked first anyway: if this
    folder is ever migrated like the others, a junction at the old path keeps
    both answers correct, and if the junction is missing this still finds it.
    """
    candidates = []
    try:
        from tubecli.config import ext_data_path
        candidates.append(ext_data_path("browser", "scraped_data"))
    except Exception:
        pass
    candidates.append(Path(__file__).resolve().parent.parent / "extensions" / "browser" / "scraped_data")

    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return candidates[-1]


def profiles() -> List[str]:
    """Profile folders that exist on disk, sorted."""
    root = data_root()
    if not root.is_dir():
        return []
    out = []
    for child in root.iterdir():
        try:
            if child.is_dir():
                out.append(child.name)
        except OSError:
            continue
    return sorted(out)


def resolve_profiles(requested: Optional[Iterable[str]]) -> List[str]:
    """Turn caller-supplied profile names into real ones.

    `profile` arrives from a query string, and it used to be joined straight
    into a path. A value of "../../.." would have walked out of scraped_data
    entirely. Names are therefore matched against the directory listing —
    anything not on disk simply is not a profile, so traversal has nothing to
    resolve to.
    """
    known = set(profiles())
    if not requested:
        return sorted(known)
    return sorted(p for p in requested if p in known)


# ── Text handling ───────────────────────────────────────────────────────────

def fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics so "dau tu" finds "đầu tư".

    NFD decomposition handles the tone and vowel marks, but NOT đ/Đ — those are
    single letters with no combining form, so a plain NFD pass leaves "đầu" as
    "đau" and the query "dau" still misses. They are mapped explicitly.
    """
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower()


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _snippet(content: str, needle_folded: str = "", size: int = _SNIPPET) -> str:
    """A short excerpt, centred on the match when there is one."""
    if not content:
        return ""
    flat = " ".join(content.split())
    if needle_folded:
        pos = fold(flat).find(needle_folded)
        if pos > 0:
            start = max(0, pos - size // 3)
            piece = flat[start:start + size]
            return ("…" if start else "") + piece + ("…" if start + size < len(flat) else "")
    return flat[:size] + ("…" if len(flat) > size else "")


# ── Time handling ───────────────────────────────────────────────────────────

def _parse_utc(stamp: str) -> Optional[datetime]:
    """Parse the scraper's ISO stamp into an aware UTC datetime."""
    if not stamp:
        return None
    try:
        s = stamp.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _local_tz():
    return datetime.now().astimezone().tzinfo


def day_bounds(day: date) -> tuple:
    """UTC instants for the start and end of a LOCAL calendar day.

    This is the whole reason the date filter is not a string comparison. On a
    UTC+7 host, local 2026-08-12 runs from 2026-08-11T17:00Z to
    2026-08-12T17:00Z: its first seven hours carry yesterday's UTC date and the
    rest carry today's.
    """
    tz = _local_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _parse_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    v = value.strip().lower()
    today = datetime.now(_local_tz()).date()
    if v in ("today", "hom nay", "hôm nay"):
        return today
    if v in ("yesterday", "hom qua", "hôm qua"):
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


# ── Loading ─────────────────────────────────────────────────────────────────

def _read_json(path: Path, default):
    try:
        if not path.is_file():
            return default
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning("[scraped] unreadable %s: %s", path, e)
        return default


def raw_history(profile: str) -> List[Dict[str, Any]]:
    """history.json rows for one profile, exactly as written.

    The dashboard's history tab consumes this shape, so it is passed through
    untouched; the normalised view lives in query().
    """
    data = _read_json(data_root() / profile / "history.json", {})
    rows = data.get("scrapedArticles") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def raw_articles(profile: str) -> List[Dict[str, Any]]:
    data = _read_json(data_root() / profile / "articles.json", [])
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def owns(row: Dict[str, Any], agent_id: str, allowed_profiles: Iterable[str], profile: str) -> bool:
    """Does `agent_id` own this scraped row?

    Attributed rows are matched by id. Rows with no agentId predate the field
    (or were scraped by hand) and are credited to any agent that holds the
    profile — the same rule /api/v1/agents/{id}/history has always used. Keeping
    it means the history tab does not suddenly empty out for anyone.
    """
    row_agent = row.get("agentId") or row.get("agent_id")
    if row_agent:
        return row_agent == agent_id
    return profile in set(allowed_profiles or ())


def normalise(hist: Dict[str, Any], article: Optional[Dict[str, Any]], profile: str,
              *, with_content: bool = False, needle: str = "") -> Dict[str, Any]:
    """One record from both halves. `article` is None when the body has aged out."""
    stamp = hist.get("scrapedAt") or (article or {}).get("scrapedAt") or ""
    utc = _parse_utc(stamp)
    content = (article or {}).get("content") or ""
    rec = {
        "url": hist.get("url") or (article or {}).get("url") or "",
        "title": hist.get("title") or (article or {}).get("title") or "",
        "profile": profile,
        "agent_id": hist.get("agentId") or hist.get("agent_id"),
        "agent_name": hist.get("agentName") or hist.get("agent_name"),
        "author": (article or {}).get("author") or hist.get("author") or "",
        "description": (article or {}).get("description") or "",
        "published_date": (article or {}).get("publishedDate") or "",
        "scraped_at": utc.isoformat() if utc else stamp,
        "scraped_at_local": utc.astimezone(_local_tz()).isoformat() if utc else "",
        "content_length": hist.get("contentLength") or len(content),
        "image_count": hist.get("imageCount") or (article or {}).get("imageCount") or 0,
        "ip": hist.get("ip") or "",
        # Listed in history, body already rotated out of articles.json. Said
        # plainly instead of returning content: "".
        "has_content": bool(content),
        "is_scraped": bool(hist.get("isScraped")) or bool(content),
    }
    rec["domain"] = _domain(rec["url"])
    rec["snippet"] = _snippet(content, needle) if content else ""
    if with_content:
        rec["content"] = content
        rec["images"] = (article or {}).get("images") or []
    return rec


def _collect(profile_list: List[str], agent_id: Optional[str],
             allowed_profiles: Iterable[str], need_articles: bool) -> List[tuple]:
    """(hist_row, article_or_None, profile) for every owned record."""
    out = []
    for profile in profile_list:
        hist = raw_history(profile)
        by_url = {}
        if need_articles:
            for a in raw_articles(profile):
                if a.get("url"):
                    by_url[a["url"]] = a
        # Two sets, and the difference matters. `known` is every url the
        # history mentions; `taken` is the ones this agent owns. Collapsing
        # them into one lets a REJECTED row come back through the orphan pass
        # below — it was never added to the set, so it looked like an article
        # with no history at all, and agent A saw agent B's articles.
        known, taken = set(), set()
        for row in hist:
            url = row.get("url")
            if not url or url in taken:
                continue
            known.add(url)
            if agent_id and not owns(row, agent_id, allowed_profiles, profile):
                continue
            taken.add(url)
            out.append((row, by_url.get(url), profile))
        # An article with no history row is still real data — it happens when
        # history was trimmed first. Do not lose it, but it has no agentId to
        # check, so it follows the unattributed rule.
        if need_articles and (not agent_id or profile in set(allowed_profiles or ())):
            for url, art in by_url.items():
                if url not in known:
                    out.append(({"url": url, "title": art.get("title", "")}, art, profile))
    return out


# ── The query ───────────────────────────────────────────────────────────────

def query(*, agent_id: Optional[str] = None, allowed_profiles: Iterable[str] = (),
          profile: Optional[Iterable[str]] = None, q: str = "", domain: str = "",
          since: Optional[str] = None, until: Optional[str] = None, day: Optional[str] = None,
          with_content: bool = False, only_with_content: bool = False,
          limit: int = 50, offset: int = 0, order: str = "desc") -> Dict[str, Any]:
    """Search the scraped corpus. Returns {total, count, items, ...}.

    `q` matches title, url and body, accent-insensitively. Searching the body
    means articles.json has to be read, so it is loaded when the query needs it
    and skipped when it does not.
    """
    profile_list = resolve_profiles(profile if profile else (allowed_profiles or None))
    needle = fold(q.strip())

    # articles.json is read on EVERY query, including the ones that do not ask
    # for bodies. Skipping it when `with_content` was false looked like a free
    # optimisation and was not: every record then came back has_content=False
    # and snippet="", so a plain listing announced "nội dung đã bị xoay vòng
    # khỏi kho" for articles whose text was sitting right there. The flag
    # reports a fact about the data, so the data has to be looked at. It costs
    # one file per profile, capped at ARTICLE_CAP rows.
    pairs = _collect(profile_list, agent_id, allowed_profiles, need_articles=True)

    lo = hi = None
    d = _parse_day(day)
    if d:
        lo, hi = day_bounds(d)
    else:
        s, u = _parse_day(since), _parse_day(until)
        if s:
            lo = day_bounds(s)[0]
        if u:
            hi = day_bounds(u)[1]

    want_domain = (domain or "").lower().lstrip(".")
    items = []
    for hist, art, prof in pairs:
        rec = normalise(hist, art, prof, with_content=with_content, needle=needle)
        if only_with_content and not rec["has_content"]:
            continue
        if want_domain and not (rec["domain"] == want_domain or rec["domain"].endswith("." + want_domain)):
            continue
        if lo or hi:
            when = _parse_utc(rec["scraped_at"])
            if when is None or (lo and when < lo) or (hi and when >= hi):
                continue
        if needle:
            body = (art or {}).get("content") or ""
            hay = fold(f"{rec['title']} {rec['url']} {rec['description']} {body}")
            if needle not in hay:
                continue
        items.append(rec)

    items.sort(key=lambda r: r.get("scraped_at") or "", reverse=(order != "asc"))
    total = len(items)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    page = items[offset:offset + limit]

    return {
        "total": total,
        "count": len(page),
        "offset": offset,
        "limit": limit,
        "profiles": profile_list,
        "query": q,
        "items": page,
    }


def get_article(url: str, *, profile: Optional[str] = None,
                allowed_profiles: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """One full record by URL, body included."""
    search = resolve_profiles([profile] if profile else (allowed_profiles or None))
    for prof in search:
        art = next((a for a in raw_articles(prof) if a.get("url") == url), None)
        hist = next((h for h in raw_history(prof) if h.get("url") == url), None)
        if art or hist:
            return normalise(hist or {"url": url}, art, prof, with_content=True)
    return None


def stats(*, agent_id: Optional[str] = None, allowed_profiles: Iterable[str] = (),
          profile: Optional[Iterable[str]] = None, days: int = 14) -> Dict[str, Any]:
    """Counts by profile, domain and local day, plus how much body text survives."""
    profile_list = resolve_profiles(profile if profile else (allowed_profiles or None))
    pairs = _collect(profile_list, agent_id, allowed_profiles, need_articles=True)

    by_profile: Dict[str, int] = {}
    by_domain: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    by_agent: Dict[str, int] = {}
    with_body = 0
    newest = oldest = ""

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    for hist, art, prof in pairs:
        rec = normalise(hist, art, prof)
        by_profile[prof] = by_profile.get(prof, 0) + 1
        if rec["domain"]:
            by_domain[rec["domain"]] = by_domain.get(rec["domain"], 0) + 1
        name = rec["agent_name"] or rec["agent_id"] or "(chưa gán agent)"
        by_agent[name] = by_agent.get(name, 0) + 1
        if rec["has_content"]:
            with_body += 1
        when = _parse_utc(rec["scraped_at"])
        if when:
            if when >= cutoff:
                key = when.astimezone(_local_tz()).date().isoformat()
                by_day[key] = by_day.get(key, 0) + 1
            iso = when.isoformat()
            newest = max(newest, iso) if newest else iso
            oldest = min(oldest, iso) if oldest else iso

    total = len(pairs)
    return {
        "total": total,
        "with_content": with_body,
        # The gap is retention, not loss of data the caller can fix by re-running.
        "body_rotated_out": total - with_body,
        "caps": {"history": HISTORY_CAP, "articles": ARTICLE_CAP},
        "profiles": by_profile,
        "domains": dict(sorted(by_domain.items(), key=lambda kv: -kv[1])[:20]),
        "agents": by_agent,
        "by_day": dict(sorted(by_day.items(), reverse=True)),
        "newest": newest,
        "oldest": oldest,
        "root": str(data_root()),
    }


# ── Export ──────────────────────────────────────────────────────────────────

EXPORT_FORMATS = ("json", "jsonl", "csv", "md", "txt")

_CSV_COLUMNS = ["scraped_at_local", "title", "url", "domain", "profile", "agent_name",
                "author", "published_date", "content_length", "image_count", "has_content"]


def export(items: List[Dict[str, Any]], fmt: str = "json") -> tuple:
    """Serialise records. Returns (text, media_type, suggested_filename)."""
    fmt = (fmt or "json").lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}' (use: {', '.join(EXPORT_FORMATS)})")
    stamp = datetime.now(_local_tz()).strftime("%Y%m%d-%H%M")

    if fmt == "json":
        return json.dumps(items, ensure_ascii=False, indent=2), "application/json", f"scraped-{stamp}.json"

    if fmt == "jsonl":
        body = "\n".join(json.dumps(i, ensure_ascii=False) for i in items)
        return body, "application/x-ndjson", f"scraped-{stamp}.jsonl"

    if fmt == "csv":
        buf = io.StringIO()
        # Excel opens UTF-8 CSV as mojibake unless it sees a BOM, and these
        # titles are Vietnamese. \r\n for the same reason.
        buf.write("\ufeff")
        w = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        for i in items:
            w.writerow({k: i.get(k, "") for k in _CSV_COLUMNS})
        return buf.getvalue(), "text/csv; charset=utf-8", f"scraped-{stamp}.csv"

    if fmt == "md":
        out = [f"# Dữ liệu đã cào ({len(items)} bài)", ""]
        for i in items:
            out.append(f"## {i.get('title') or '(không tiêu đề)'}")
            meta = [i.get("scraped_at_local", ""), i.get("domain", ""), i.get("profile", "")]
            out.append("*" + " · ".join(m for m in meta if m) + "*")
            out.append("")
            out.append(f"<{i.get('url','')}>")
            out.append("")
            if i.get("content"):
                out.append(i["content"])
            elif i.get("snippet"):
                out.append(i["snippet"])
            out.append("")
        return "\n".join(out), "text/markdown; charset=utf-8", f"scraped-{stamp}.md"

    out = []
    for i in items:
        out.append(i.get("title") or "(không tiêu đề)")
        out.append(i.get("url", ""))
        if i.get("content"):
            out.append(i["content"])
        elif i.get("snippet"):
            out.append(i["snippet"])
        out.append("-" * 60)
    return "\n".join(out), "text/plain; charset=utf-8", f"scraped-{stamp}.txt"


def image_path(url_or_name: str, *, profile: str, allowed_profiles: Iterable[str] = ()) -> Optional[Path]:
    """Resolve a downloaded image to a real file inside scraped_data.

    localPath in the article is absolute and was written by the scraper, so it
    is trusted only after being confirmed to sit under this profile's folder —
    a record naming C:\\Windows\\... must not turn into a file read.
    """
    valid = resolve_profiles([profile] if profile else (allowed_profiles or None))
    if profile not in valid:
        return None
    base = (data_root() / profile).resolve()
    try:
        candidate = Path(url_or_name)
        if not candidate.is_absolute():
            candidate = base / url_or_name
        resolved = candidate.resolve()
        resolved.relative_to(base)
    except (ValueError, OSError):
        return None
    return resolved if resolved.is_file() else None
