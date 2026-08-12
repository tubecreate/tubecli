"""The scraped corpus must be answerable, and answerable correctly.

Run:  python tests/scraped_store_test.py     (exit 0 = pass)

Everything runs against a temporary scraped_data tree. The real one is never
opened.

The three things this locks in, all of which are easy to get wrong and none of
which a "does the function return something" check would notice:

1. THE JOIN. articles.json carries the body but has no agentId; history.json
   carries agentId but no body. Filtering articles.json by agent therefore
   matches nothing at all — not "fewer results", zero. Ownership comes from
   history and the two are joined on url.

2. THE DAY. The scraper stamps UTC. "Hôm nay" is local. Unless the offset is
   zero a local day straddles two UTC dates, so a substring match on one date
   is wrong in both directions: on UTC+7 it loses midnight-to-07:00 (which
   carries yesterday's UTC date) and wrongly admits tomorrow's small hours.
   Which end shifts depends on the sign of the offset, so the fixture puts an
   article at BOTH 00:30 and 23:30 local and asserts at least one of them
   defeats the naive comparison on this host.

3. THE PATH. `profile` arrives from a query string and used to be joined
   straight into a path. Names are matched against the directory listing, so
   "../.." resolves to no profile rather than to a parent directory.

Plus the smaller ones that bit in review: đ is not decomposed by NFD, so accent
folding needs it mapped explicitly, and an article whose body has rotated out
of articles.json must say so rather than return "".

And the one the live corpus taught, after 46 of 49 rows came back labelled
"body rotated out": a history row is written for every page VISITED, so most
rows were never scraped at all. Blaming the retention cap for text that never
existed pointed at the wrong fix entirely. The three states — harvested,
harvested-then-aged-out, only-visited — are counted separately.
"""
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.core import scraped_store as store  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


LOCAL = datetime.now().astimezone().tzinfo


def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def at_local(day_offset, hour, minute=0):
    """A UTC stamp for a given LOCAL wall-clock time, as the scraper writes it."""
    base = datetime.now(LOCAL).replace(hour=hour, minute=minute, second=0, microsecond=0)
    base += timedelta(days=day_offset)
    return base.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build(root: Path):
    """Two profiles, with the awkward cases deliberately present."""
    luatsu = root / "luatsu"
    news = root / "news"
    (luatsu / "images").mkdir(parents=True)
    news.mkdir(parents=True)

    # Both ends of the local day, because which one shifts depends on the sign
    # of the offset: east of UTC (+07:00 here) the small hours carry
    # YESTERDAY's UTC date, west of it the late evening carries tomorrow's.
    # Whichever way the host leans, one of these two defeats a substring match
    # on today's UTC date.
    early = at_local(0, 0, 30)
    late = at_local(0, 23, 30)
    morning = at_local(0, 9, 12)
    yesterday = at_local(-1, 14, 0)

    history = {"scrapedArticles": [
        {"title": "Luật Đầu tư 2020", "url": "https://vietnam-briefing.com/dau-tu",
         "scrapedAt": morning, "isScraped": True, "agentId": "agent-A",
         "agentName": "VietLaw", "contentLength": 120, "imageCount": 1, "ip": "1.2.3.4"},
        {"title": "Quy định muộn", "url": "https://vietnam-briefing.com/muon",
         "scrapedAt": late, "isScraped": True, "agentId": "agent-A", "agentName": "VietLaw"},
        {"title": "Quy định rạng sáng", "url": "https://vietnam-briefing.com/sang",
         "scrapedAt": early, "isScraped": True, "agentId": "agent-A", "agentName": "VietLaw"},
        {"title": "Bài của agent khác", "url": "https://other.com/x",
         "scrapedAt": morning, "isScraped": True, "agentId": "agent-B", "agentName": "Other"},
        {"title": "Bài cũ mất xác", "url": "https://vietnam-briefing.com/rotated",
         "scrapedAt": yesterday, "isScraped": True, "agentId": "agent-A"},
        {"title": "Không gán agent", "url": "https://legacy.vn/old",
         "scrapedAt": yesterday, "isScraped": True},
        # Opened, never harvested — what a search page or a skip-listed domain
        # leaves behind. 46 of the 49 rows on the real server look like this.
        {"title": "Chỉ ghé qua", "url": "https://google.com/search?q=x",
         "scrapedAt": morning, "isScraped": False, "agentId": "agent-A"},
    ]}
    (luatsu / "history.json").write_text(json.dumps(history), encoding="utf-8")

    # Note what is NOT here: agentId. And note that /rotated is missing
    # entirely — it is in history but its body has aged out.
    articles = [
        {"title": "Luật Đầu tư 2020", "url": "https://vietnam-briefing.com/dau-tu",
         "content": "Doanh nghiệp nước ngoài được phép góp vốn theo Luật Đầu tư.",
         "author": "VB", "publishedDate": "2020-06-17", "imageCount": 1,
         "images": [{"url": "https://x/i.jpg", "alt": "", "localPath": str(luatsu / "images" / "img_0.jpg")}],
         "scrapedAt": morning},
        {"title": "Quy định muộn", "url": "https://vietnam-briefing.com/muon",
         "content": "Nội dung cào lúc nửa đêm.", "scrapedAt": late},
        {"title": "Quy định rạng sáng", "url": "https://vietnam-briefing.com/sang",
         "content": "Nội dung cào lúc rạng sáng.", "scrapedAt": early},
        {"title": "Bài của agent khác", "url": "https://other.com/x",
         "content": "Không thuộc agent-A.", "scrapedAt": morning},
        {"title": "Không gán agent", "url": "https://legacy.vn/old",
         "content": "Bài cũ chưa có agentId.", "scrapedAt": yesterday},
    ]
    (luatsu / "articles.json").write_text(json.dumps(articles), encoding="utf-8")
    (luatsu / "images" / "img_0.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")

    (news / "history.json").write_text(json.dumps({"scrapedArticles": [
        {"title": "Tin khác", "url": "https://news.vn/a", "scrapedAt": morning,
         "isScraped": True, "agentId": "agent-B"},
    ]}), encoding="utf-8")
    (news / "articles.json").write_text(json.dumps([
        {"title": "Tin khác", "url": "https://news.vn/a", "content": "x", "scrapedAt": morning},
    ]), encoding="utf-8")


tmp = Path(tempfile.mkdtemp(prefix="tubecli-scraped-"))
try:
    build(tmp)
    store.data_root = lambda: tmp  # every read goes through this one function

    print("=" * 70)
    print("SCRAPED STORE")
    print("=" * 70)

    # ── profiles & path safety ─────────────────────────────────────────────
    check("profiles listed", store.profiles() == ["luatsu", "news"], store.profiles())
    check("unknown profile dropped", store.resolve_profiles(["nope"]) == [], "accepted a name not on disk")

    # The traversal the old code allowed. resolve_profiles is a whitelist, so
    # there is nothing for "../.." to resolve TO.
    for evil in ["../..", "..", "../../../etc", "luatsu/../../..", "/etc"]:
        check(f"traversal {evil!r} refused", store.resolve_profiles([evil]) == [], "resolved to a real profile")

    # ── 1. the join ────────────────────────────────────────────────────────
    # This is the assertion that fails outright if ownership is taken from
    # articles.json, because that file has no agentId in it at all.
    raw = store.raw_articles("luatsu")
    check("fixture matches production shape (no agentId in articles.json)",
          all("agentId" not in a and "agent_id" not in a for a in raw),
          "fixture is not reproducing the real schema")

    a_res = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], with_content=True, limit=50)
    urls = {i["url"] for i in a_res["items"]}
    check("agent-A gets its own articles",
          "https://vietnam-briefing.com/dau-tu" in urls, f"got {urls}")
    check("agent-A does not get agent-B's",
          "https://other.com/x" not in urls, "leaked another agent's article")
    check("unattributed rows credited to the profile holder",
          "https://legacy.vn/old" in urls, "legacy row vanished")
    check("bodies actually joined on url",
          any(i["url"].endswith("/dau-tu") and "góp vốn" in i.get("content", "")
              for i in a_res["items"]),
          "content did not come through the join")

    b_res = store.query(agent_id="agent-B", allowed_profiles=["luatsu", "news"], limit=50)
    b_urls = {i["url"] for i in b_res["items"]}
    check("agent-B sees its own across profiles",
          "https://other.com/x" in b_urls and "https://news.vn/a" in b_urls, f"got {b_urls}")
    check("agent-B does not see agent-A's",
          "https://vietnam-briefing.com/dau-tu" not in b_urls, "cross-agent leak")

    # ── 2. the local day ───────────────────────────────────────────────────
    today = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], day="today", limit=50)
    t_urls = {i["url"] for i in today["items"]}
    check("today includes the 09:12 article", "https://vietnam-briefing.com/dau-tu" in t_urls, f"got {t_urls}")
    check("today includes 00:30 — east of UTC this one carries yesterday's date",
          "https://vietnam-briefing.com/sang" in t_urls,
          "small-hours article dropped; day filter is not timezone-aware")
    check("today includes 23:30 — west of UTC this one carries tomorrow's",
          "https://vietnam-briefing.com/muon" in t_urls,
          "late-evening article dropped; day filter is not timezone-aware")
    check("today excludes yesterday's", "https://vietnam-briefing.com/rotated" not in t_urls, f"got {t_urls}")

    # And prove the naive version really would have failed on this fixture,
    # so the checks above are testing something real rather than passing by
    # luck. Which of the two shifts depends on the sign of the offset, so the
    # assertion is that AT LEAST ONE does.
    naive_date = datetime.now().strftime("%Y-%m-%d")
    rows = json.loads((tmp / "luatsu" / "history.json").read_text(encoding="utf-8"))["scrapedArticles"]
    edges = [h["scrapedAt"] for h in rows if h["url"].endswith(("/muon", "/sang"))]
    offset = datetime.now(LOCAL).utcoffset() or timedelta(0)
    if offset != timedelta(0):
        check("fixture does defeat the substring match",
              any(naive_date not in s for s in edges),
              f"local offset {offset} should push one edge of the day onto another UTC date; got {edges}")
    else:
        # Exactly at UTC the two agree; the guard is then untestable, not wrong.
        print(f"  (note: local offset is {offset}; UTC and local days coincide here)")

    yday = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], day="yesterday", limit=50)
    check("yesterday resolves", {i["url"] for i in yday["items"]} == {
        "https://vietnam-briefing.com/rotated", "https://legacy.vn/old"}, [i["url"] for i in yday["items"]])

    # has_content is a claim about the data, so it must hold on the DEFAULT
    # query too — not only when the caller asked for bodies. Loading
    # articles.json lazily made every plain listing report "content rotated
    # out" for articles whose text was present, which is the worst kind of
    # wrong: confidently, in the user's own words, about data that exists.
    plain = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], limit=50)
    plain_by_url = {i["url"]: i for i in plain["items"]}
    check("default query still knows which bodies exist",
          plain_by_url["https://vietnam-briefing.com/dau-tu"]["has_content"] is True,
          "claimed the body was gone without looking")
    check("default query still knows which bodies are gone",
          plain_by_url["https://vietnam-briefing.com/rotated"]["has_content"] is False,
          "claimed a body it does not have")
    check("default query returns a snippet",
          bool(plain_by_url["https://vietnam-briefing.com/dau-tu"]["snippet"]),
          "no snippet without with_content")

    # ── 3. rotated-out bodies are stated, not faked ────────────────────────
    rotated = next((i for i in a_res["items"] if i["url"].endswith("/rotated")), None)
    check("rotated row still listed", rotated is not None, "history-only row was dropped")
    if rotated:
        check("rotated row admits it has no body", rotated["has_content"] is False,
              "claimed content it does not have")
        check("rotated row returns no fake content", not rotated.get("content"),
              f"returned {rotated.get('content')!r}")

    # ── accent-insensitive search ──────────────────────────────────────────
    check("fold strips tones", store.fold("Kinh Doanh") == "kinh doanh", store.fold("Kinh Doanh"))
    # NFD does not decompose đ — it needs an explicit map, or "dau tu" misses.
    check("fold maps đ to d", store.fold("Đầu tư") == "dau tu", store.fold("Đầu tư"))

    for needle in ["dau tu", "Đầu tư", "ĐẦU TƯ", "gop von"]:
        hit = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], q=needle, limit=50)
        check(f"search {needle!r} finds the article", hit["total"] >= 1, f"total={hit['total']}")

    body_only = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], q="nước ngoài", limit=50)
    check("search reaches the body, not just the title", body_only["total"] == 1, f"total={body_only['total']}")

    miss = store.query(agent_id="agent-A", allowed_profiles=["luatsu"], q="khong ton tai gi ca", limit=50)
    check("search can miss", miss["total"] == 0, f"total={miss['total']}")

    # ── filters, ordering, paging ──────────────────────────────────────────
    dom = store.query(allowed_profiles=["luatsu", "news"], domain="vietnam-briefing.com", limit=50)
    check("domain filter", all(i["domain"] == "vietnam-briefing.com" for i in dom["items"]) and dom["total"] == 4,
          [i["domain"] for i in dom["items"]])

    body = store.query(allowed_profiles=["luatsu"], only_with_content=True, limit=50)
    check("only_with_content drops the rotated row",
          all(i["has_content"] for i in body["items"]) and body["total"] == 5, f"total={body['total']}")

    ordered = store.query(allowed_profiles=["luatsu"], limit=50)["items"]
    stamps = [i["scraped_at"] for i in ordered]
    check("newest first", stamps == sorted(stamps, reverse=True), stamps)

    p1 = store.query(allowed_profiles=["luatsu"], limit=2, offset=0)
    p2 = store.query(allowed_profiles=["luatsu"], limit=2, offset=2)
    check("paging splits without overlap",
          p1["total"] == p2["total"] == 7 and len(p1["items"]) == 2
          and not ({i["url"] for i in p1["items"]} & {i["url"] for i in p2["items"]}),
          f"{[i['url'] for i in p1['items']]} / {[i['url'] for i in p2['items']]}")

    # ── single article ─────────────────────────────────────────────────────
    one = store.get_article("https://vietnam-briefing.com/dau-tu", allowed_profiles=["luatsu"])
    check("get_article returns the body", one and "góp vốn" in (one.get("content") or ""), one)
    check("get_article on a rotated url reports no body",
          (store.get_article("https://vietnam-briefing.com/rotated", allowed_profiles=["luatsu"]) or {}).get("has_content") is False,
          "claimed a body")
    check("get_article on an unknown url is None",
          store.get_article("https://nope.example/x", allowed_profiles=["luatsu"]) is None, "invented a record")

    # ── stats ──────────────────────────────────────────────────────────────
    st = store.stats(allowed_profiles=["luatsu", "news"])
    check("stats totals", st["total"] == 8, st["total"])
    # The distinction the real corpus exposed: 46 of 49 rows had never been
    # scraped at all, and reporting them as "body rotated out" blamed the
    # retention cap for text that never existed. /rotated was harvested and
    # lost its body; /visited was only ever opened.
    check("stats counts bodies lost to the cap", st["scraped_but_body_gone"] == 1,
          st["scraped_but_body_gone"])
    check("stats counts pages only visited", st["visited_not_scraped"] == 1,
          st["visited_not_scraped"])
    check("the two are not conflated",
          st["with_content"] + st["scraped_but_body_gone"] + st["visited_not_scraped"] == st["total"],
          "the three buckets do not add up")
    check("stats groups by domain", st["domains"].get("vietnam-briefing.com") == 4, st["domains"])
    check("stats groups by local day", len(st["by_day"]) == 2, st["by_day"])

    # ── export ─────────────────────────────────────────────────────────────
    items = store.query(allowed_profiles=["luatsu"], with_content=True, limit=50)["items"]
    for fmt in store.EXPORT_FORMATS:
        text, media, name = store.export(items, fmt)
        check(f"export {fmt} produces content", bool(text.strip()), "empty")
        check(f"export {fmt} names the file", name.endswith("." + fmt), name)
    check("export rejects an unknown format",
          _raises(lambda: store.export(items, "docx")), "accepted docx")

    csv_text = store.export(items, "csv")[0]
    # Excel reads UTF-8 CSV as mojibake without a BOM, and these titles are
    # Vietnamese — the whole point of exporting is that it opens.
    check("csv starts with a BOM", csv_text.startswith("﻿"), repr(csv_text[:6]))
    check("csv keeps the diacritics", "Đầu tư" in csv_text, "titles mangled")

    md = store.export(items, "md")[0]
    check("markdown carries bodies", "góp vốn" in md, "content missing from export")

    # ── image serving ──────────────────────────────────────────────────────
    good = store.image_path(str(tmp / "luatsu" / "images" / "img_0.jpg"), profile="luatsu")
    check("image inside the profile resolves", good is not None and good.is_file(), good)

    # localPath is absolute and comes out of a JSON file on disk; a record
    # naming something outside the profile must not become a file read.
    for evil in [str(tmp / "news" / "articles.json"), "../news/articles.json",
                 "../../etc/passwd", str(Path(sys.executable))]:
        check(f"image escape {evil!r} refused", store.image_path(evil, profile="luatsu") is None,
              "served a file outside the profile")
    check("image in an unknown profile refused",
          store.image_path("img_0.jpg", profile="../..") is None, "resolved")

    # ── the handover brief ─────────────────────────────────────────────────
    # A document written to be pasted into another AI's chat window. Two things
    # can go wrong with it and both are silent: it can leak the password, and
    # it can document parameters that no longer exist.
    from tubecli.core import scraped_query  # noqa: E402

    for lang in ("vi", "en"):
        g = scraped_query.build_guide(
            base_url="http://10.0.0.5:5295/", agent_id="agent-A",
            agent_name="VietLaw", profiles_list=["luatsu"], lang=lang)
        check(f"guide[{lang}] names the server", "http://10.0.0.5:5295" in g, "base url missing")
        check(f"guide[{lang}] has no double slash", "5295//api" not in g, "trailing slash not stripped")
        check(f"guide[{lang}] names the agent id", "agent-A" in g, "agent id missing")
        check(f"guide[{lang}] names the agent", "VietLaw" in g, "agent name missing")
        check(f"guide[{lang}] names the profile", "luatsu" in g, "profile missing")
        check(f"guide[{lang}] keeps the password a placeholder",
              "<" in g and "curl" in g and "auth/login" in g, "login step missing")

    # The brief DOES carry one credential now, deliberately: the read key, so a
    # cloud AI that cannot hold a cookie can still fetch. That makes the line
    # between the two credentials the thing to hold: the read key may appear,
    # the password may never.
    keyed = scraped_query.build_guide(base_url="http://x/", agent_id="a",
                                      read_key="tcs_TESTKEY123", lang="vi")
    check("guide embeds the read key", "tcs_TESTKEY123" in keyed, "key not in brief")
    for form in ("X-TubeCLI-Token", "Bearer", "token=tcs_TESTKEY123"):
        check(f"guide shows the {form!r} form", form in keyed, "carrier missing")
    check("guide says the key is read-only",
          "CHỈ ĐỌC" in keyed or "READ-ONLY" in keyed.upper(), "scope not stated")
    check("guide without a key shows a placeholder",
          "<KHOÁ_ĐỌC>" in scraped_query.build_guide(base_url="http://x/", agent_id="a", lang="vi"),
          "no placeholder when unkeyed")

    # Dangling cross-references. When the cookie steps were demoted from
    # "BƯỚC 1/BƯỚC 2" to "CÁCH 2", the closing notes were left saying "mọi
    # endpoint đều cần cookie phiên ở BƯỚC 1" — a rule that contradicted the
    # method above it and pointed at a section that no longer existed. The
    # brief still read as authoritative, which is the danger: an AI following
    # it would have concluded the key was insufficient and given up.
    for lang, words in (("vi", ("BƯỚC", "CÁCH")), ("en", ("STEP", "OPTION"))):
        g = scraped_query.build_guide(base_url="http://x/", agent_id="a",
                                      read_key="tcs_K", lang=lang)
        headings = set(re.findall(rf"^({'|'.join(words)}) (\d+)", g, re.M))
        referenced = set(re.findall(rf"\b({'|'.join(words)}) (\d+)", g))
        dangling = referenced - headings
        check(f"brief[{lang}] has no dangling section reference", not dangling,
              f"refers to {sorted(dangling)}, which is not a heading in the document")

    # And the notes must not contradict the method the brief recommends.
    vi = scraped_query.build_guide(base_url="http://x/", agent_id="a",
                                   read_key="tcs_K", lang="vi")
    notes = vi.split("LƯU Ý QUAN TRỌNG")[-1]
    check("closing notes do not claim a cookie is always required",
          "khoá đọc" in notes.lower() or "cách 1" in notes.lower(),
          "the notes still describe cookie-only auth")

    import inspect  # noqa: E402
    params = set(inspect.signature(scraped_query.build_guide).parameters)
    banned = {p for p in params if any(w in p for w in ("password", "passwd", "secret", "cookie", "session"))}
    check("guide builder cannot be handed the password", not banned, f"has {banned}")
    # Read the value out of the login command rather than scanning the whole
    # document for something that looks like a secret. The first attempt did
    # the latter and failed on the product's own name appearing in the header
    # X-TubeCLI-Token — a check that cannot tell a brand from a credential is
    # not checking anything.
    for lang, expected in (("vi", "<MẬT_KHẨU_DASHBOARD>"), ("en", "<DASHBOARD_PASSWORD>")):
        g = scraped_query.build_guide(base_url="http://x/", agent_id="a",
                                      read_key="tcs_TESTKEY123", lang=lang)
        found = re.findall(r'"password"\s*:\s*"([^"]*)"', g)
        check(f"login step[{lang}] passes only a placeholder", found == [expected],
              f"password field holds {found}")

    # The drift guard. Every query parameter the brief documents is looked up
    # in the signature that actually implements it, so renaming one without
    # updating the brief fails here instead of failing in someone else's agent
    # a week later.
    guide = scraped_query.build_guide(base_url="http://x/", agent_id="a", lang="en")
    documented = set(re.findall(r"^\s{2}([a-z_]+)=", guide, re.M))
    check("brief documents some parameters", len(documented) >= 5, documented)
    implemented = set(inspect.signature(store.query).parameters)
    unknown = documented - implemented - {"agent_id", "fmt"}
    check("every documented parameter exists in query()", not unknown,
          f"brief documents {unknown}, which query() does not accept")

    # Same for the three stats buckets it explains.
    st_keys = set(store.stats(allowed_profiles=["luatsu"]))
    for bucket in ("with_content", "visited_not_scraped", "scraped_but_body_gone"):
        check(f"brief's '{bucket}' is a real stats key", bucket in st_keys and bucket in guide,
              "documented but not returned" if bucket not in st_keys else "returned but not documented")

    # ── nothing at all ─────────────────────────────────────────────────────
    empty = Path(tempfile.mkdtemp(prefix="tubecli-scraped-empty-"))
    try:
        store.data_root = lambda: empty
        check("empty corpus lists nothing", store.profiles() == [], store.profiles())
        blank = store.query(limit=10)
        check("empty corpus queries cleanly", blank["total"] == 0 and blank["items"] == [], blank)
        check("empty corpus stats do not divide by zero", store.stats()["total"] == 0, "raised or wrong")
    finally:
        shutil.rmtree(empty, ignore_errors=True)

    # ── unreadable files ───────────────────────────────────────────────────
    broken = Path(tempfile.mkdtemp(prefix="tubecli-scraped-broken-"))
    try:
        (broken / "p").mkdir()
        (broken / "p" / "history.json").write_text("{not json", encoding="utf-8")
        (broken / "p" / "articles.json").write_text('{"not": "a list"}', encoding="utf-8")
        store.data_root = lambda: broken
        r = store.query(limit=10)
        check("corrupt files do not raise", r["total"] == 0, r)
    finally:
        shutil.rmtree(broken, ignore_errors=True)

finally:
    shutil.rmtree(tmp, ignore_errors=True)


print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
