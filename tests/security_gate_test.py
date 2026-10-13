"""Security gates must FAIL CLOSED, and installs / secret files must be guarded.

Run:  python tests/security_gate_test.py     (exit 0 = pass; loads the real app, ~40 s)

Why this file exists (security review, 13/10/2026). The login middleware wrapped its
whole decision in `try … except Exception: pass` and then called the endpoint, so any
exception — in check_request, the guest lookup, or while building the 401 — let an
unauthenticated request through. Reproduced on the real app before the fix: a raising
check_request turned 401 into 200. The origin guard had the same shape. These checks
drive the REAL FastAPI app (TestClient's client host is "testclient", i.e. remote) in a
throw-away DATA_DIR, so the machine's own data/ is never touched.
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="secgate_"))
cfg.DATA_DIR = TMP

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f"  ({detail})" if detail else ""))


# ── A. git URL policy (pure) ──────────────────────────────────────────────────
from tubecli.core.extension_manager import _git_url_refusal  # noqa: E402

for url in ("https://github.com/tubecreate/tubecli.git", "https://gh-proxy.com/https://github.com/x/y.git",
            "git@github.com:tubecreate/tubecli.git", str(TMP)):
    check(f"A accepted: {url[:48]}", _git_url_refusal(url) == "", _git_url_refusal(url))
for url in ("--upload-pack=touch /tmp/pwned", "-c core.sshCommand=calc", "ext::sh -c touch% /tmp/x",
            "file:///etc", "http://example.com/x.git", "https://user:pass@github.com/x/y.git",
            "https://github.com/x/y.git\n--upload-pack=x", "", "fd::3", "C:/nope/not-a-dir-here"):
    check(f"A refused: {url[:40]!r}", _git_url_refusal(url) != "")
from tubecli.core.extension_manager import extension_manager  # noqa: E402
r = extension_manager.install_from_git("--upload-pack=touch /tmp/pwned")
check("A install_from_git refuses an option-looking URL before cloning", r.get("status") == "error", r.get("message"))
src = Path(sys.modules["tubecli.core.extension_manager"].__file__).read_text(encoding="utf-8")
check("A git clone passes `--` before the URL", '"clone", "--depth", "1", "--", git_url, target_dir' in src)

# ── B. secret files are written owner-only and atomically ─────────────────────
from tubecli.core.private_file import write_json_private  # noqa: E402

p = TMP / "secret.json"
write_json_private(p, {"k": "v"})
check("B content written", p.read_text(encoding="utf-8").strip().startswith("{"))
check("B no .tmp left behind", not (TMP / "secret.json.tmp").exists())
if os.name != "nt":
    check("B mode 0600", stat.S_IMODE(os.stat(p).st_mode) == 0o600, oct(stat.S_IMODE(os.stat(p).st_mode)))
for rel in ("tubecli/extensions/cloud_api/extension.py", "tubecli/extensions/auth_manager/extension.py"):
    s = (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")
    body = s[s.index("    def _save(self):"):][:600]
    check(f"B {rel.split('/')[2]} saves through write_json_private", "write_json_private(" in body and "open(self.data_file, \"w\"" not in body)

# ── C. the real app: login gate and origin guard fail closed ──────────────────
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.api import server as S  # noqa: E402
from tubecli.core import auth  # noqa: E402
import tubecli.core.origin_guard as OG  # noqa: E402

auth.set_password("a-strong-test-password-1")
c = TestClient(S.app)
PROBE = "/api/v1/agents"

r = c.get(PROBE)
check("C remote, no session → 401", r.status_code == 401, r.status_code)

orig_check = auth.check_request
auth.check_request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated"))
try:
    r = c.get(PROBE)
    check("C auth check raises → 503 auth_unavailable (never 200)",
          r.status_code == 503 and r.json().get("code") == "auth_unavailable", r.status_code)
    r = c.post("/api/v1/extensions/install", json={"git_url": "https://github.com/x/y.git"})
    check("C auth check raises → extension install refused", r.status_code == 503, r.status_code)
finally:
    auth.check_request = orig_check

tok = auth.create_session()
c.cookies.set(auth.SESSION_COOKIE, tok)
r = c.get(PROBE)
check("C valid session → through", r.status_code == 200, r.status_code)

orig_guard = OG.is_origin_allowed
OG.is_origin_allowed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("guard broke"))
try:
    r = c.get(PROBE, headers={"origin": "https://evil.example"})
    check("C origin guard raises → 403 (never 200)", r.status_code == 403, r.status_code)
finally:
    OG.is_origin_allowed = orig_guard

r = c.get(PROBE, headers={"origin": "https://evil.example"})
check("C foreign Origin with a valid session → 403 (CSRF)", r.status_code == 403, r.status_code)

c.cookies.clear()
r = c.post("/api/v1/extensions/install", json={"git_url": "https://github.com/x/y.git"})
check("C extension install without a session → 401", r.status_code == 401, r.status_code)

# ── D. default password: a REMOTE session may only change it (owner decision 13/10/2026) ──
check("D local (loopback, not proxied) is never blocked",
      auth.default_password_refusal("127.0.0.1", {}, "/api/v1/agents") is None)
auth.set_password(auth.DEFAULT_PASSWORD, _is_default=True)
check("D loopback behind a tunnel is remote → blocked",
      (auth.default_password_refusal("127.0.0.1", {"cf-connecting-ip": "203.0.113.9"}, "/api/v1/agents") or {})
      .get("reason") == "password_change_required")
c.cookies.clear()
r = c.post("/api/v1/auth/login", json={"password": auth.DEFAULT_PASSWORD})
d = r.json() if r.status_code == 200 else {}
check("D remote login with 123456 works and says must_change, not local",
      r.status_code == 200 and d.get("must_change_password") is True and d.get("local") is False, (r.status_code, d))
st = c.get("/api/v1/auth/status").json()
check("D status: remote_locked", st.get("remote_locked") is True and st.get("local") is False, st)
r = c.get(PROBE)
check("D that session cannot use the API → 403 password_change_required",
      r.status_code == 403 and r.json().get("code") == "password_change_required", r.status_code)
r = c.post("/api/v1/extensions/install", json={"git_url": "https://github.com/x/y.git"})
check("D that session cannot install extensions → 403", r.status_code == 403, r.status_code)
r = c.get("/dashboard", headers={"accept": "text/html"}, follow_redirects=False)
check("D a page request is sent to /login", r.status_code == 302 and r.headers.get("location", "").startswith("/login"),
      (r.status_code, r.headers.get("location")))
r = c.post("/api/v1/auth/password", json={"current_password": auth.DEFAULT_PASSWORD, "new_password": "brand-new-pass-77"})
check("D but it CAN change the password", r.status_code == 200, (r.status_code, r.text[:120]))
r = c.get(PROBE)
check("D after the change the API opens", r.status_code == 200, r.status_code)
check("D login page offers skip only when local", "$('skip').hidden=!local;" in
      (Path(__file__).resolve().parent.parent / "tubecli/api/auth_routes.py").read_text(encoding="utf-8"))

# ── E. the install endpoints have no way around the gate (review point 6) ─────
# A stub records every call that REACHES install_from_git, so "refused" below means
# the clone never started — not merely that the status code looked right. Positive
# controls at the end (loopback, valid session) prove the stub is actually wired.
calls = []
_real_install = extension_manager.install_from_git
extension_manager.install_from_git = lambda url, commit=None: (
    calls.append((url, commit)) or {"status": "error", "message": "stub: not cloned"})
BODY = {"git_url": "https://github.com/x/y.git"}
INSTALLS = [p for p in ("/api/v1/extensions/install", "/api/v1/market/items/install-git")
            if any(getattr(rt, "path", "") == p for rt in S.app.routes)]
check("E both install routes are mounted in the app under test", len(INSTALLS) == 2, INSTALLS)
remote = TestClient(S.app)                              # client host "testclient" = remote
local = TestClient(S.app, client=("127.0.0.1", 50000))  # the machine itself


def attempt(label, client, path, headers=None, cookies=None, expect=(401,)):
    calls.clear()
    client.cookies.clear()
    for k, v in (cookies or {}).items():
        client.cookies.set(k, v)
    r = client.post(path, json=BODY, headers=headers or {})
    client.cookies.clear()
    check(f"E {label} [{path.rsplit('/', 2)[-2]}] → {r.status_code}, install never reached",
          r.status_code in expect and not calls, (r.status_code, r.text[:100], calls))


read_key = auth.scraped_read_token()
ws_guest = auth.mint_guest_token({"profiles": ["p1"], "access": "full"})["guest_token"]
pub_guest = auth.mint_guest_token({"public": True, "profiles": ["p1"]})["guest_token"]
for path in INSTALLS:
    attempt("remote, no session", remote, path)
    for h, v in (("X-Forwarded-For", "203.0.113.9"), ("X-Real-IP", "203.0.113.9"),
                 ("Forwarded", "for=203.0.113.9"), ("X-Forwarded-Host", "evil.example"),
                 ("CF-Connecting-IP", "203.0.113.9"), ("x-forwarded-for", "127.0.0.1")):
        attempt(f"loopback via proxy ({h}: {v}), no session", local, path, headers={h: v})
    attempt("forged session cookie", remote, path, cookies={auth.SESSION_COOKIE: "forged"})
    attempt("scraped read key as Bearer", remote, path, headers={"authorization": f"Bearer {read_key}"})
    attempt("scraped read key as x-tubecli-token", remote, path, headers={"x-tubecli-token": read_key})
    attempt("Muse node-key style Bearer", remote, path, headers={"authorization": "Bearer " + "k" * 40})
    attempt("workspace guest cookie (full access)", remote, path,
            cookies={auth.GUEST_COOKIE: ws_guest}, expect=(403,))
    attempt("public guest header", remote, path, headers={auth.GUEST_HEADER: pub_guest}, expect=(403,))
# Path spellings: either the gate answers (401) or nothing routes (404) — never the endpoint.
for p in ("/api/v1/extensions/install/", "//api/v1/extensions/install", "/API/V1/EXTENSIONS/INSTALL",
          "/s/../api/v1/extensions/install", "/static/..%2fapi/v1/extensions/install",
          "/api/v1/public/hire/file/%2e%2e/%2e%2e/%2e%2e/extensions/install"):
    attempt(f"path spelling {p!r}", remote, p, expect=(401, 404, 405))


def raising(*_a, **_k):
    raise RuntimeError("simulated")


# The gate's own failures, on the LOOPBACK client that would otherwise be let through.
for mod, fn, kw in ((auth, "check_request", {}), (auth, "default_password_refusal", {}),
                    (auth, "behind_proxy", {"headers": {"X-Forwarded-For": "203.0.113.9"}})):
    orig = getattr(mod, fn)
    setattr(mod, fn, raising)
    try:
        attempt(f"{fn} raises", local, INSTALLS[0], expect=(503,), **kw)
    finally:
        setattr(mod, fn, orig)
orig = auth.guest_scope_for
auth.guest_scope_for = raising
try:  # a broken guest lookup falls back to the owner refusal — 401, not "guest allowed"
    attempt("guest lookup raises", remote, INSTALLS[0], cookies={auth.GUEST_COOKIE: ws_guest})
finally:
    auth.guest_scope_for = orig

# Positive controls — the stub IS reached when the caller is the owner.
calls.clear()
r = local.post(INSTALLS[0], json={**BODY, "commit": "a" * 40})
check("E control: loopback without proxy headers reaches install (commit passed through)",
      r.status_code == 400 and calls == [(BODY["git_url"], "a" * 40)], (r.status_code, calls))
calls.clear()
remote.cookies.set(auth.SESSION_COOKIE, auth.create_session())
r = remote.post(INSTALLS[0], json=BODY)
remote.cookies.clear()
check("E control: remote with a valid session reaches install", r.status_code == 400 and len(calls) == 1,
      (r.status_code, calls))
extension_manager.install_from_git = _real_install

# ── F. commit pin + provenance (review point 5) ───────────────────────────────
import shutil  # noqa: E402
import subprocess as sp  # noqa: E402
from types import SimpleNamespace  # noqa: E402
import tubecli.core.extension_manager as EM  # noqa: E402


def git(*a, cwd):
    return sp.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *a],
                  cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


repo = TMP / "pin_src"
repo.mkdir()
git("init", "-q", cwd=repo)
(repo / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")
(repo / "tubecli-extension.json").write_text('{"name": "pin_demo", "version": "1.0.0"}', encoding="utf-8")
git("add", "-A", cwd=repo)
git("commit", "-q", "-m", "reviewed", cwd=repo)
A = git("rev-parse", "HEAD", cwd=repo)
(repo / "requirements.txt").write_text("requests==2.32.3\nsomething-unreviewed\n", encoding="utf-8")
git("commit", "-q", "-am", "later", cwd=repo)
B = git("rev-parse", "HEAD", cwd=repo)

U = "https://github.com/x/y.git"
check("F #<full hash> suffix is split off as the pin", EM._split_pin(f"{U}#{A}") == (U, A, ""), EM._split_pin(f"{U}#{A}"))
check("F commit field works and is case-insensitive", EM._split_pin(U, A.upper()) == (U, A, ""))
check("F no pin → unpinned, URL unchanged", EM._split_pin(U) == (U, "", ""))
for label, args in (("short hash", (f"{U}#{A[:7]}",)), ("branch name", (f"{U}#main",)),
                    ("tag-like", (U, "v1.2.3")), ("URL and field disagree", (f"{U}#{A}", B))):
    check(f"F refused pin: {label}", EM._split_pin(*args)[2] != "", EM._split_pin(*args))
r = extension_manager.install_from_git(f"{U}#{A[:7]}")
check("F install refuses a short-hash pin before cloning", r.get("status") == "error" and "full commit" in r.get("message", ""),
      r.get("message"))

clone1 = TMP / "clone1"
sp.run(["git", "clone", "-q", "--", str(repo), str(clone1)], check=True, capture_output=True)
check("F fresh clone starts on the newest commit", EM._git_head(clone1) == B)
check("F _checkout_pin moves to the pinned commit", EM._checkout_pin(str(clone1), A) == "")
check("F … and HEAD is exactly that commit", EM._git_head(clone1) == A, EM._git_head(clone1))
check("F … so the unreviewed dependency is not there",
      "something-unreviewed" not in (clone1 / "requirements.txt").read_text(encoding="utf-8"))
clone2 = TMP / "clone2"
sp.run(["git", "clone", "-q", "--", str(repo), str(clone2)], check=True, capture_output=True)
check("F a commit that is not in the repo is refused", EM._checkout_pin(str(clone2), "0" * 40) != "")

_real_ext_dir = EM.EXTENSIONS_EXTERNAL_DIR
EM.EXTENSIONS_EXTERNAL_DIR = TMP / "ext"
try:
    r = extension_manager.install_from_git(str(repo), commit="0" * 40)
    check("F install with an unknown pin → error, nothing loaded", r.get("status") == "error", r.get("message"))
    check("F … and the clone is removed", not (TMP / "ext" / "pin_src").exists())
finally:
    EM.EXTENSIONS_EXTERNAL_DIR = _real_ext_dir
body = src[src.index("    def install_from_git"):src.index("    def update_extension")]
check("F the pin is applied BEFORE the manifest is read or dependencies installed",
      body.index("_checkout_pin(target_dir, pin)") < body.index("# Validate manifest")
      < body.index('"pip", "install"'))
check("F refused clones are removed with _remove_tree (read-only git objects on Windows)",
      "_remove_tree(target_dir)" in body and "rmtree(target_dir, ignore_errors=True)" not in body)

e = EM._provenance_entry(U, str(clone1), A)
check("F provenance: commit, pinned, source", e["commit"] == A and e["pinned"] is True and e["source"] == U, e)
check("F provenance: sha256 of requirements.txt", len(e["dependency_files"].get("requirements.txt", "")) == 64, e)
check("F provenance: previous commit kept on change",
      EM._provenance_entry(U, str(clone1), "", previous={"commit": B}).get("previous_commit") == B)
EM._record_provenance("pin_demo", e)
check("F provenance stored in DATA_DIR", EM._provenance_file().parent == TMP and
      EM.read_provenance("pin_demo")["commit"] == A)
extension_manager._extensions["pin_demo"] = SimpleNamespace(
    name="pin_demo", extension_type="external", extension_dir=str(clone1), get_manifest=lambda: {})
try:
    r = extension_manager.update_extension("pin_demo")
    check("F a pinned extension is not auto-updated", r.get("status") == "error" and r.get("pinned") is True, r)
    check("F … and stays on its commit", EM._git_head(clone1) == A)
finally:
    extension_manager._extensions.pop("pin_demo", None)
EM._record_provenance("pin_demo", None)
check("F provenance forgotten on uninstall", EM.read_provenance("pin_demo") is None)
shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
