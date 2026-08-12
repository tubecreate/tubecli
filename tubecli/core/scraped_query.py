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


# ── Handover brief ──────────────────────────────────────────────────────────

# Never interpolated into the brief. The password is the one credential that
# reaches the whole dashboard, so it stays out of a document whose entire
# purpose is to be pasted into another agent's chat window — the user hands it
# over on a separate channel, or not at all when the consumer runs on the box
# itself and the loopback exemption applies.
_PASSWORD_PLACEHOLDER = {"vi": "<MẬT_KHẨU_DASHBOARD>", "en": "<DASHBOARD_PASSWORD>"}


def build_guide(*, base_url: str, agent_id: str, agent_name: str = "",
                profiles_list: Iterable[str] = (), lang: str = "vi") -> str:
    """A self-contained brief another AI can act on with no further context.

    Generated server-side and not hardcoded in the dashboard's JavaScript, so
    it cannot drift from the endpoints it documents: the parameter names, the
    three stats buckets and the has_content rule all come from the same module
    that implements them.
    """
    base = (base_url or "").rstrip("/")
    pw = _PASSWORD_PLACEHOLDER.get(lang, _PASSWORD_PLACEHOLDER["en"])
    profs = ", ".join(profiles_list) or ("(chưa có)" if lang == "vi" else "(none)")
    who = agent_name or agent_id

    if lang == "vi":
        return f"""\
NHIỆM VỤ: lấy nội dung các bài mà agent "{who}" đã cào về từ máy chủ TubeCLI.

Máy chủ  : {base}
Agent ID : {agent_id}
Profile  : {profs}

BƯỚC 1 — Đăng nhập lấy phiên (mật khẩu do người dùng đưa riêng, KHÔNG có trong
tài liệu này). Bỏ qua bước này nếu bạn chạy ngay trên máy chủ và gọi localhost.

  curl -c ck.txt -X POST {base}/api/v1/auth/login \\
       -H 'Content-Type: application/json' \\
       -d '{{"password":"{pw}"}}'

BƯỚC 2 — Lấy các bài CÓ nội dung của agent này:

  curl -b ck.txt '{base}/api/v1/agents/{agent_id}/scraped?with_content=true&limit=20'

Tham số lọc (ghép bằng &):
  day=today | yesterday | YYYY-MM-DD   lọc theo NGÀY ĐỊA PHƯƠNG của máy chủ
  since=YYYY-MM-DD  until=YYYY-MM-DD   khoảng ngày
  q=<từ khoá>                          tìm trong tiêu đề, URL và nội dung;
                                       không phân biệt dấu ("dau tu" ra "đầu tư")
  limit=<1..500>  offset=<n>            phân trang
  with_content=true                    kèm toàn văn (mặc định chỉ trích đoạn)
  only_with_content=false              xem thêm cả trang chỉ ghé qua

Kết quả JSON:
  {{"total":N, "count":N, "items":[{{
      "url", "title", "domain", "profile", "author",
      "scraped_at"        — ISO, giờ UTC
      "scraped_at_local"  — ISO, giờ máy chủ
      "has_content"       — true thì mới có trường "content"
      "content"           — toàn văn, chỉ khi with_content=true
      "snippet", "content_length", "image_count"
  }}]}}

XUẤT FILE (tải thẳng, có sẵn nội dung):
  {base}/api/v1/scraped/export?agent_id={agent_id}&fmt=csv&day=today
  fmt nhận: json, jsonl, csv, md, txt

THỐNG KÊ:
  {base}/api/v1/scraped/stats?agent_id={agent_id}
  Ba con số KHÁC NHAU, đừng gộp:
    with_content          — số bài thật sự có nội dung
    visited_not_scraped   — trang chỉ mở ra xem, chưa trích nội dung
                            (trang tìm kiếm, tên miền trong danh sách bỏ qua…)
    scraped_but_body_gone — đã cào nhưng nội dung bị xoay vòng khỏi kho
                            (kho giữ tối đa 100 bài mỗi profile)

LƯU Ý QUAN TRỌNG:
- Chỉ bài có has_content=true mới dùng được; bài khác chỉ có tiêu đề và URL.
- Mặc định các endpoint trên CHỈ trả bài có nội dung.
- Mọi endpoint đều cần cookie phiên ở BƯỚC 1, trừ khi gọi từ localhost.
- Không tự bịa nội dung bài. Nếu total=0 thì báo lại đúng như vậy.
"""

    return f"""\
TASK: retrieve the articles the agent "{who}" has scraped, from a TubeCLI server.

Server   : {base}
Agent ID : {agent_id}
Profiles : {profs}

STEP 1 — Log in for a session cookie. The password is supplied separately by
the user and is deliberately NOT in this document. Skip this step entirely if
you are running on the server itself and calling localhost.

  curl -c ck.txt -X POST {base}/api/v1/auth/login \\
       -H 'Content-Type: application/json' \\
       -d '{{"password":"{pw}"}}'

STEP 2 — Fetch this agent's articles that HAVE text:

  curl -b ck.txt '{base}/api/v1/agents/{agent_id}/scraped?with_content=true&limit=20'

Filters (combine with &):
  day=today | yesterday | YYYY-MM-DD   filtered by the server's LOCAL day
  since=YYYY-MM-DD  until=YYYY-MM-DD   date range
  q=<terms>                            searches title, URL and body;
                                       accent-insensitive for Vietnamese
  limit=<1..500>  offset=<n>            paging
  with_content=true                    include full text (default: snippet only)
  only_with_content=false              also list pages that were merely visited

Response JSON:
  {{"total":N, "count":N, "items":[{{
      "url", "title", "domain", "profile", "author",
      "scraped_at"        — ISO, UTC
      "scraped_at_local"  — ISO, server local time
      "has_content"       — only then is "content" present
      "content"           — full text, only when with_content=true
      "snippet", "content_length", "image_count"
  }}]}}

EXPORT (downloads with bodies included):
  {base}/api/v1/scraped/export?agent_id={agent_id}&fmt=csv&day=today
  fmt accepts: json, jsonl, csv, md, txt

STATS:
  {base}/api/v1/scraped/stats?agent_id={agent_id}
  Three DIFFERENT numbers — do not add them together and call it a loss:
    with_content          — articles that actually have text
    visited_not_scraped   — pages only opened, never harvested
                            (search pages, skip-listed domains…)
    scraped_but_body_gone — harvested, body since rotated out
                            (the store keeps 100 articles per profile)

IMPORTANT:
- Only records with has_content=true are usable; the rest are title and URL.
- These endpoints return only articles with text by default.
- Every endpoint needs the STEP 1 cookie unless called from localhost.
- Do not invent article content. If total=0, report exactly that.
"""


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
