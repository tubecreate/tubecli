"""An extension whose routes fail to load must SAY so, not 404 in silence.

Run:  python tests/extension_route_error_test.py     (exit 0 = pass)

Background (2026-08-20): a buyer installed CapCut TTS from the Marketplace. It
appeared in the sidebar — the extension object had loaded — but every URL
answered {"detail":"Not Found"}. Two swallowed failures stacked:

  - register_api_routes caught the exception from get_routes() (an ImportError
    for a Python package TubeCLI itself does not ship) and only logged it.
    Nothing reached the API or the dashboard.
  - The market installer's hot-mount passed get_routes()'s return value straight
    to app.include_router(); an extension returning a LIST of routers raised,
    was swallowed, and the response still said "Refresh page to use".

Guards here, each verified against the real ExtensionManager:
  1. get_routes() raising → extension.route_error is set and to_dict() exposes it
  2. get_routes() returning a list → every router is mounted
  3. a later successful registration clears route_error
  4. _ensure_extension_deps with an uninstallable package records deps_error
     instead of printing "installed successfully"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tubecli.core.extension_manager import Extension, ExtensionManager  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class Broken(Extension):
    name = "broken_ext"
    version = "1.0.0"
    description = "routes import fails"
    extension_type = "external"

    def get_routes(self):
        raise ImportError("No module named 'cryptography'")


class ListRoutes(Extension):
    name = "list_ext"
    version = "1.0.0"
    description = "returns two routers"
    extension_type = "external"

    def get_routes(self):
        a = APIRouter(prefix="/api/v1/list-ext")
        b = APIRouter()

        @a.get("/ping")
        def ping():
            return {"ok": True}

        @b.get("/list-ext")
        def page():
            return {"page": True}

        return [a, b]


class Healed(Extension):
    name = "healed_ext"
    version = "1.0.0"
    description = "fails once, then works"
    extension_type = "external"
    attempts = 0

    def get_routes(self):
        Healed.attempts += 1
        if Healed.attempts == 1:
            raise ImportError("first time")
        r = APIRouter()

        @r.get("/healed")
        def ok():
            return {"ok": True}

        return r


print("=" * 70)
print("EXTENSION ROUTE ERRORS ARE VISIBLE")
print("=" * 70)

mgr = ExtensionManager()
broken, listed, healed = Broken(), ListRoutes(), Healed()
for e in (broken, listed, healed):
    e.enabled = True
    mgr._extensions[e.name] = e

app = FastAPI()
mgr.register_api_routes(app)
client = TestClient(app)

# 1. the failure is recorded and exposed
check("broken extension records route_error", bool(getattr(broken, "route_error", None)),
      getattr(broken, "route_error", None))
check("route_error names the missing module", "cryptography" in (broken.route_error or ""), broken.route_error)
d = broken.to_dict()
check("to_dict exposes route_error", d.get("route_error") == broken.route_error, d.get("route_error"))
check("to_dict exposes dependencies list", isinstance(d.get("dependencies"), list), d.get("dependencies"))

# 2. a list of routers is mounted in full
check("list: api router mounted", client.get("/api/v1/list-ext/ping").status_code == 200,
      client.get("/api/v1/list-ext/ping").status_code)
check("list: page router mounted", client.get("/list-ext").status_code == 200,
      client.get("/list-ext").status_code)
check("list extension has no route_error", getattr(listed, "route_error", None) is None,
      getattr(listed, "route_error", None))

# 3. a later success clears the error
check("healed: first pass recorded the error", bool(getattr(healed, "route_error", None)))
mgr.register_api_routes(app)
check("healed: second pass clears route_error", getattr(healed, "route_error", None) is None,
      getattr(healed, "route_error", None))
check("healed: route now serves", client.get("/healed").status_code == 200, client.get("/healed").status_code)

# 4. pip failure is recorded, not reported as success
class NeedsImpossible(Extension):
    name = "impossible_deps"
    version = "1.0.0"
    description = "declares a package that cannot exist"
    extension_type = "external"


imp = NeedsImpossible()
imp._manifest = {"dependencies": ["tubecli-test-package-that-does-not-exist-0xdeadbeef"]}
mgr._ensure_extension_deps(imp)
check("uninstallable dep records deps_error", bool(getattr(imp, "deps_error", None)), getattr(imp, "deps_error", None))
check("deps_error names the package", "0xdeadbeef" in (imp.deps_error or ""), imp.deps_error)

# ── report ────────────────────────────────────────────────────────────────
print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
