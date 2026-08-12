"""The read key must open the corpus and nothing else.

Run:  python tests/scraped_read_key_test.py     (exit 0 = pass)

Why the key exists. A session cookie takes three stateful steps — POST the
password, keep the Set-Cookie, send it back — and most cloud AI tools cannot do
that. Some manage exactly one fetch, with no way to set a header. Handing them
a cookie-based brief hands them something they cannot use.

So there is now a bearer key that works in a single request. That is a new door
into a server whose password reaches /read, cloud_api_keys.json and code
installation, and the brief carrying this key is written to be pasted into a
third-party AI — it WILL be seen by something the owner does not control. The
key is therefore narrow by construction, and this file is the proof, run
through the real middleware stack rather than by reading the regex:

  - GET only. A POST with the key is refused, so nothing can be changed.
  - Scraped data paths only. Not /agents (the roster), not /files/read, not
    /settings, not even /scraped-guide — a key that could fetch the brief could
    fetch itself, and rotation is POST for the same reason.
  - The right key only, compared in constant time.

Every assertion goes through TestClient, so the path regex, the method check
and the middleware ordering are all exercised together. A test that called
_read_key_authorised() directly would pass while the middleware ignored it.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp_home = Path(tempfile.mkdtemp(prefix="tubecli-readkey-"))

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("SCRAPED READ KEY")
print("=" * 70)

from tubecli.core import auth, scraped_store  # noqa: E402
from tubecli.config import DATA_DIR  # noqa: E402

# DATA_DIR is a module constant with no env override, so it is repointed here.
# Both _auth_file() and _read_token_file() import it INSIDE the function body,
# so patching the module attribute reaches them and they still choose their own
# filenames — which is the point. Replacing the two functions with fixed paths
# was the first attempt and it was worthless: the test then asserted the name
# its own lambda had returned, so moving the key into auth.json for real went
# completely unnoticed.
import tubecli.config as _cfg  # noqa: E402

_cfg.DATA_DIR = _tmp_home

# Proof the redirect took, checked before anything is written. A test that
# silently fell back to the real directory would still go green while
# clobbering the running install's credentials.
_real = Path(DATA_DIR).resolve()
_before = {p.name for p in _real.iterdir()} if _real.is_dir() else set()

corpus = _tmp_home / "corpus"
(corpus / "luatsu").mkdir(parents=True)
(corpus / "luatsu" / "history.json").write_text(json.dumps({"scrapedArticles": [
    {"title": "Bài mẫu", "url": "https://vb.com/a", "scrapedAt": "2026-08-12T02:00:00.000Z",
     "isScraped": True, "agentId": "A"},
]}), encoding="utf-8")
(corpus / "luatsu" / "articles.json").write_text(json.dumps([
    {"title": "Bài mẫu", "url": "https://vb.com/a", "content": "Nội dung.",
     "scrapedAt": "2026-08-12T02:00:00.000Z"},
]), encoding="utf-8")
scraped_store.data_root = lambda: corpus

try:
    # ── the key itself ─────────────────────────────────────────────────────
    key = auth.scraped_read_token()
    check("a key is minted on first use", bool(key), "none returned")
    check("key is prefixed", key.startswith(auth.READ_TOKEN_PREFIX), key)
    check("key is long enough to not be guessed", len(key) >= 28, f"len {len(key)}")
    check("key is stable across calls", auth.scraped_read_token() == key, "changed on re-read")

    # Where the production code chose to put it, not where the test told it to.
    _key_file = auth._read_token_file()
    check("key file lives under the data dir", _key_file.parent == _tmp_home, str(_key_file))
    check("key is stored in its own file", _key_file.is_file(), "not written where expected")
    check("key file is not auth.json", _key_file.name != "auth.json",
          "the key shares the password file, which set_password() rewrites wholesale")
    if _key_file.is_file() and os.name != "nt":
        mode = _key_file.stat().st_mode & 0o777
        check("key file is owner-only", mode == 0o600, oct(mode))

    # set_password() replaces auth.json wholesale to invalidate sessions. The
    # key lives in its own file precisely so that does not silently revoke it.
    auth.set_password("a-new-password-123")
    check("changing the password keeps the key", auth.scraped_read_token(create=False) == key,
          "password change revoked the read key")

    check("wrong key rejected", not auth.scraped_read_token_valid("tcs_wrong"), "accepted")
    check("empty rejected", not auth.scraped_read_token_valid(""), "accepted")
    check("None rejected", not auth.scraped_read_token_valid(None), "accepted")
    check("non-string rejected", not auth.scraped_read_token_valid(12345), "accepted")
    # A prefix of the real key must not pass — the comparison is whole-value.
    check("truncated key rejected", not auth.scraped_read_token_valid(key[:-4]), "accepted a prefix")
    check("right key accepted", auth.scraped_read_token_valid(key), "rejected the real key")

    old = key
    rotated = auth.rotate_scraped_read_token()
    check("rotation returns a different key", rotated != old, "same key back")
    check("rotation revokes the old one", not auth.scraped_read_token_valid(old), "old key still works")
    check("rotated key works", auth.scraped_read_token_valid(rotated), "new key rejected")
    key = rotated

    # ── the gate, through the real middleware ──────────────────────────────
    from fastapi.testclient import TestClient
    from tubecli.api.server import app

    class FakeAgent:
        id = "A"
        name = "VietLaw"
        allowed_profiles = ["luatsu"]

    from tubecli.core import agent as agent_mod
    agent_mod.agent_manager.get = lambda i: FakeAgent() if i == "A" else None

    # A remote client: loopback is exempt by design, so testing from 127.0.0.1
    # would prove nothing about the key at all.
    c = TestClient(app, base_url="http://10.1.2.3:5295",
                   headers={"x-forwarded-for": "10.9.9.9"})

    DATA = "/api/v1/agents/A/scraped"

    check("no key is refused", c.get(DATA).status_code == 401, c.get(DATA).status_code)
    r = c.get(DATA, headers={"X-TubeCLI-Token": "tcs_not-the-key"})
    check("wrong key is refused", r.status_code == 401, r.status_code)

    # The three carriers a one-shot client might have.
    for label, kwargs in [
        ("header", {"headers": {"X-TubeCLI-Token": key}}),
        ("bearer", {"headers": {"Authorization": f"Bearer {key}"}}),
        ("query", {"params": {"token": key}}),
    ]:
        r = c.get(DATA, **kwargs)
        check(f"{label} carries the key", r.status_code == 200, f"{r.status_code} {r.text[:80]}")
        if r.status_code == 200:
            check(f"{label} returns real data", "items" in r.json(), r.text[:80])

    for path in ["/api/v1/scraped/articles", "/api/v1/scraped/stats",
                 "/api/v1/scraped/profiles", "/api/v1/scraped/export?fmt=json"]:
        r = c.get(path, headers={"X-TubeCLI-Token": key})
        check(f"key opens {path.split('?')[0]}", r.status_code == 200, f"{r.status_code}")

    # ── and nothing else ───────────────────────────────────────────────────
    # The list that matters. Each of these is refused WITH a valid key, so a
    # failure here means the key reaches further than the corpus.
    for path in [
        "/api/v1/agents",                       # the whole agent roster
        "/api/v1/agents/A",                     # one agent, with its config
        "/api/v1/agents/A/scraped-guide",       # would hand back the key itself
        "/api/v1/agents/A/history",             # browsing history, not articles
        "/api/v1/settings",
        "/api/v1/skills",
        "/api/v1/files/read?path=data/cloud_api_keys.json",
        "/api/v1/scraped/articles/../../agents",
    ]:
        r = c.get(path, headers={"X-TubeCLI-Token": key})
        check(f"key does NOT open {path[:52]}", r.status_code in (401, 403, 404, 405),
              f"got {r.status_code} — the read key reached beyond the corpus")

    # Write methods, with a valid key. A read key that can POST is not a read key.
    for method, path in [("post", DATA), ("post", "/api/v1/scraped/read-key/rotate"),
                         ("delete", "/api/v1/agents/A"), ("put", "/api/v1/agents/A"),
                         ("post", "/api/v1/agents")]:
        kw = {"headers": {"X-TubeCLI-Token": key}}
        if method != "delete":       # httpx forbids a body on DELETE
            kw["json"] = {}
        r = getattr(c, method)(path, **kw)
        check(f"{method.upper()} {path[:40]} refused with the key",
              r.status_code in (401, 403, 404, 405),
              f"got {r.status_code} — the read key performed a write")

    # The GET-only rule, asserted directly on the authoriser.
    #
    # The HTTP checks above cannot reach it: no route that matches the path
    # pattern accepts anything but GET, so FastAPI answers 405 and the request
    # is refused whether or not the method rule exists. Deleting the rule today
    # changes nothing observable — and that is exactly why it needs a test of
    # its own. The day someone adds POST /api/v1/scraped/articles, this rule is
    # the only thing standing between a leaked read key and a write.
    from tubecli.api import server as srv

    class FakeURL:
        def __init__(self, path):
            self.path = path

    class FakeReq:
        def __init__(self, method, path, key):
            self.method = method
            self.url = FakeURL(path)
            self.headers = {"x-tubecli-token": key}
            self.query_params = {}

    check("authoriser allows GET on a data path",
          srv._read_key_authorised(FakeReq("GET", "/api/v1/scraped/articles", key)),
          "refused a legitimate read")
    for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
        check(f"authoriser refuses {method} even on a data path",
              not srv._read_key_authorised(FakeReq(method, "/api/v1/scraped/articles", key)),
              "a write method was authorised by a read key")
    check("authoriser refuses a non-data path",
          not srv._read_key_authorised(FakeReq("GET", "/api/v1/settings", key)),
          "path scope not enforced")
    check("authoriser refuses a wrong key",
          not srv._read_key_authorised(FakeReq("GET", "/api/v1/scraped/articles", "tcs_nope")),
          "accepted a bad key")

    # Rotation is POST on purpose: a GET-only key must not be able to replace
    # itself, which would let a leaked key lock the owner out of their own brief.
    r = c.get("/api/v1/scraped/read-key/rotate", headers={"X-TubeCLI-Token": key})
    check("key cannot rotate itself", r.status_code in (401, 403, 404, 405), r.status_code)
    check("key still valid after that attempt", auth.scraped_read_token_valid(key), "it rotated")

    # ── the brief the dashboard hands out ──────────────────────────────────
    auth.check_request = lambda *a, **k: None      # now as a logged-in owner
    r = c.get("/api/v1/agents/A/scraped-guide")
    check("brief renders for a session user", r.status_code == 200, r.status_code)
    if r.status_code == 200:
        text = r.json().get("text", "")
        check("brief embeds the current key", key in text, "key missing from brief")
        check("brief names the address used", "10.1.2.3:5295" in text, "wrong base url")
        check("brief never contains the password", "a-new-password-123" not in text,
              "the dashboard password leaked into a document meant to be forwarded")

    # Nothing new appeared in the real data directory — the redirect held for
    # the whole run, including set_password().
    after = {p.name for p in _real.iterdir()} if _real.is_dir() else set()
    check("the real data directory was not touched", after == _before,
          f"appeared: {sorted(after - _before)}")

finally:
    shutil.rmtree(_tmp_home, ignore_errors=True)

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
