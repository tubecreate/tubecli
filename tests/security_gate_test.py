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

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
