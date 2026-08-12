"""Plain-language access to the scraped corpus.

One implementation, three front doors: the "📚 Dữ liệu đã cào" skill, the
zero-token chat/Telegram fast-path, and `tubecli scraped`. They all end up in
`answer()`, so a phrasing that works in one works in all of them — the
divergence between the Telegram and web-chat dispatchers was exactly the bug
the intent_handlers registry was created to stop, and there is no reason to
reintroduce it one layer down.

`parse()` turns a sentence into filters. It is deliberately small: date words,
a domain, a count, and whatever is left over as the search text. Anything it
cannot recognise stays in the query string rather than being dropped, so a
request it half-understands still searches for the right words.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from tubecli.core import scraped_store as store

# Words that only say "fetch the scraped data" — they carry no search value, so
# leaving them in the query would make every request match nothing.
#
# Matched against ACCENTED lowercase text, not folded text, and that is not a
# detail. Folded, "từ" and "tư" are both "tu", so stripping the preposition
# also amputated "đầu tư" down to "đầu" — the single most likely search term
# for a legal/investment agent. Keeping the accents apart keeps them distinct.
#
# The unaccented twins of those two are deliberately ABSENT below: someone
# typing "dau tu" without accents means đầu tư, so "tu" must survive there.
# Removal is by accented form only, which gets both readings right.
_STOPWORDS = [
    "lấy", "cho tôi", "cho toi", "xem", "đọc", "doc", "read",
    "liệt kê", "liet ke", "danh sách", "danh sach",
    "dữ liệu", "du lieu", "nội dung", "noi dung", "bài viết", "bai viet", "bài", "bai",
    "đã cào", "da cao", "đã thu thập", "da thu thap", "cào được", "cao duoc", "cào", "cao",
    "đã", "da", "được", "duoc", "kho", "corpus",
    "scraped", "scrape", "crawled", "crawl", "articles", "article", "data", "content",
    "list", "show", "get", "fetch", "give me", "của agent", "cua agent", "agent",
    "từ", "trong", "về", "the", "all", "me",
    # Unaccented twins, for people who type without diacritics. "tu" is the one
    # that stays out — see above; the rest have no valuable homonym in a news
    # corpus, so stripping them costs nothing and cleans up the query.
    "lay", "ve",
]

_DAY_WORDS = [
    (r"\bhôm\s*nay\b|\btoday\b|\bhom\s*nay\b", "today"),
    (r"\bhôm\s*qua\b|\byesterday\b|\bhom\s*qua\b", "yesterday"),
]

_COUNT_RE = re.compile(r"\b(\d{1,3})\s*(bài|bai|articles?|items?|kết quả|ket qua)?\b")
_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# A bare number is a count only when it was actually asked for; "10 bài" is a
# limit, "Luật 68" is not. Requiring the unit word keeps article numbers intact.
_COUNT_WITH_UNIT = re.compile(r"\b(\d{1,3})\s*(bài|bai|articles?|items?|kết quả|ket qua)\b", re.I)


# "full/toàn văn" asks for bodies; it is an instruction, not something to
# search FOR, so it comes out of the query text as well as flagging the mode.
_FULLTEXT_WORDS = ["full", "toàn văn", "toan van", "đầy đủ", "day du",
                   "chi tiết", "chi tiet", "nguyên văn", "nguyen van", "body"]


def parse(text: str) -> Dict[str, Any]:
    """Sentence → query filters.

    Works on accented lowercase and returns an accented query; store.query()
    folds the needle itself, so nothing is lost by leaving the diacritics on.
    """
    raw = (text or "").strip()
    low = raw.lower()
    out: Dict[str, Any] = {"q": "", "day": None, "since": None, "until": None,
                           "domain": "", "limit": 10}

    for pattern, word in _DAY_WORDS:
        if re.search(pattern, low):
            out["day"] = word
            low = re.sub(pattern, " ", low)
            break

    dates = _DATE_RE.findall(raw)
    if dates and not out["day"]:
        if len(dates) >= 2:
            out["since"], out["until"] = dates[0], dates[1]
        else:
            out["day"] = dates[0]
        for d in dates:
            low = low.replace(d, " ")

    m = _COUNT_WITH_UNIT.search(low)
    if m:
        out["limit"] = max(1, min(int(m.group(1)), 50))
        low = low[:m.start()] + " " + low[m.end():]

    m = _DOMAIN_RE.search(low)
    if m:
        out["domain"] = m.group(1).lower()
        low = low[:m.start()] + " " + low[m.end():]

    for w in _FULLTEXT_WORDS + _STOPWORDS:
        # \b does not work against Vietnamese letters on either side (they are
        # word characters, so "cào" inside "cào" is fine, but a trailing "ề"
        # would still be \w). Anchoring on whitespace/edges is what actually
        # matches a whole word here.
        low = re.sub(rf"(?<![^\s]){re.escape(w)}(?![^\s])", " ", low)

    out["q"] = " ".join(low.split())
    return out


def _line(idx: int, rec: Dict[str, Any]) -> str:
    when = (rec.get("scraped_at_local") or "")[:16].replace("T", " ")
    bits = [f"{idx}. {rec.get('title') or '(không tiêu đề)'}"]
    meta = " · ".join(x for x in [when, rec.get("domain", ""), rec.get("profile", "")] if x)
    if meta:
        bits.append(f"   {meta}")
    if rec.get("url"):
        bits.append(f"   {rec['url']}")
    if rec.get("snippet"):
        bits.append(f"   {rec['snippet'][:180]}")
    elif not rec.get("has_content"):
        # Only reachable when the caller explicitly asked to see bodiless rows.
        # Two different reasons, and saying the wrong one sends the user to fix
        # the wrong thing: a retention cap they cannot control, versus a page
        # the agent merely opened and never harvested.
        bits.append("   (chỉ ghé qua, chưa cào nội dung)" if not rec.get("is_scraped")
                    else "   (đã cào nhưng nội dung đã bị xoay vòng khỏi kho)")
    return "\n".join(bits)


def answer(text: str = "", *, agent_id: Optional[str] = None,
           allowed_profiles: Iterable[str] = (), with_content: bool = False,
           include_visits: bool = False, max_chars: int = 3500) -> str:
    """Answer a plain-language request about the scraped corpus.

    Returns only pages that actually HAVE text. A history row is written for
    every page the browser opened, and most of those are search results,
    skip-listed domains, or pages a run died on before extraction — on a real
    corpus that was 46 of 49 rows. Listing them as "bài đã cào" with an empty
    body is noise, so they are excluded unless asked for.

    Every empty result still gets its own sentence. "Không có dữ liệu" would
    read the same whether the corpus is missing, the agent has never harvested
    anything, or one filter was too narrow — three different problems with
    three different fixes.
    """
    filters = parse(text)
    common = dict(agent_id=agent_id, allowed_profiles=allowed_profiles)
    res = store.query(
        **common, q=filters["q"], domain=filters["domain"], day=filters["day"],
        since=filters["since"], until=filters["until"], with_content=with_content,
        only_with_content=not include_visits, limit=filters["limit"],
    )

    if res["total"] == 0:
        st = store.stats(**common)
        if st["total"] == 0:
            if not store.profiles():
                return ("Chưa có kho dữ liệu cào nào trên máy này. "
                        "Bật 'Tự động cào dữ liệu' trong tab Lịch sử của agent rồi cho agent chạy.")
            return ("Kho dữ liệu cào đang trống — có thư mục profile nhưng chưa bài nào được lưu. "
                    "Kiểm tra xem agent đã bật 'Tự động cào dữ liệu' chưa.")
        if st["with_content"] == 0:
            # Pages were opened, nothing was harvested. Naming the count makes
            # it obvious this is an extraction problem, not an empty schedule.
            return (f"Agent đã ghé {st['total']} trang nhưng chưa cào được nội dung bài nào. "
                    f"Thường là do trang nằm trong danh sách bỏ qua (google, youtube…), "
                    f"hoặc phiên chạy dừng trước bước trích nội dung — xem tab Nhật ký chạy.")
        # There IS harvested text; the filter is what excluded it.
        why = []
        if filters["day"]:
            why.append(f"ngày '{filters['day']}'")
        if filters["q"]:
            why.append(f"từ khoá '{filters['q']}'")
        if filters["domain"]:
            why.append(f"tên miền '{filters['domain']}'")
        cond = ", ".join(why) if why else "điều kiện đã lọc"
        return (f"Không có bài nào khớp {cond}. "
                f"Kho hiện có {st['with_content']} bài có nội dung — bỏ bớt điều kiện để xem tất cả.")

    head = f"📚 {res['total']} bài đã cào"
    if filters["day"]:
        head += f" ({filters['day']})"
    if filters["q"]:
        head += f" khớp '{filters['q']}'"
    if res["count"] < res["total"]:
        head += f" — hiện {res['count']} bài mới nhất"

    parts = [head, ""]
    for i, rec in enumerate(res["items"], 1):
        parts.append(_line(i, rec))
        if with_content and rec.get("content"):
            parts.append("")
            parts.append(rec["content"][:1500])
        parts.append("")

    text_out = "\n".join(parts).rstrip()
    if len(text_out) > max_chars:
        text_out = text_out[:max_chars].rsplit("\n", 1)[0] + "\n…"
    return text_out
