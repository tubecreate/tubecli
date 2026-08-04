"""End-to-end smoke test for GET /cleanup/scan and POST /cleanup/apply.

Run:  python tests/file_manager_cleanup_smoke.py     (exit 0 = pass)

Why this file exists. routes._call pre-binds the arguments with
inspect.Signature.bind before calling a backend, which only catches a MISSING
REQUIRED parameter. cleanup.apply_cleanup declares `service: Any = None`, so the
bind succeeded, nothing in the codebase complained, and the endpoint still
answered 400 "Thiếu FileService" to every preview and every real run — the
feature had never executed once. A static check cannot see that class of bug;
only an actual request can, so this asserts on status codes and on the files
that are or are not left on disk afterwards.

The fixture lives under ~/Downloads (a default allowed root) and contains
nothing but junk this test created itself, so the non-dry-run leg can delete for
real without risking anything of the user's.
"""
import os
import shutil
import sys
import time

# sys.path[0] is tests/, not the repo root, so `import tubecli` only works on a
# machine where the package happens to be pip-installed. Without this the test
# fails with ImportError on a fresh checkout, which reads as "the fix is broken"
# rather than "the package is not installed".
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The backend messages are Vietnamese; a cp1252 console would otherwise abort
# the run with UnicodeEncodeError and look like a test failure.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tubecli.extensions.file_manager.routes import router_fm
from tubecli.extensions.file_manager.file_service import file_service

PREFIX = "/api/v1/file-manager"
_failures = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (("  -- %s" % (detail,)) if detail != "" else ""))
    if not ok:
        _failures.append(label)


def build_tree(root):
    os.makedirs(os.path.join(root, "pkg", "__pycache__"), exist_ok=True)
    with open(os.path.join(root, "pkg", "__pycache__", "mod.cpython-312.pyc"), "wb") as f:
        f.write(b"\x00" * 4096)
    with open(os.path.join(root, "Thumbs.db"), "wb") as f:
        f.write(b"\x00" * 2048)

    stale = os.path.join(root, "half.tmp")
    with open(stale, "wb") as f:
        f.write(b"\x00" * 8192)
    # temp_files has a deliberate 24h age gate so an in-progress download is
    # never proposed for deletion. A freshly written .tmp is therefore INVISIBLE
    # to the detector; backdating it is what makes this leg test anything.
    old = time.time() - (48 * 3600)
    os.utime(stale, (old, old))

    os.makedirs(os.path.join(root, "empty_here"), exist_ok=True)
    # Identical size AND identical bytes: the duplicate detector must agree on
    # the sha256, never on the size alone.
    for name in ("dup_a.bin", "dup_b.bin"):
        with open(os.path.join(root, name), "wb") as f:
            f.write(b"TUBECLI-DUPLICATE-PAYLOAD" * 500)


def count_files(root):
    return sum(len(files) for _, _, files in os.walk(root))


def main():
    base = os.path.join(os.path.expanduser("~"), "Downloads",
                        "_fm_cleanup_smoke_%d" % os.getpid())
    try:
        file_service._validate_path(os.path.dirname(base))
    except ValueError as e:
        print("SKIP: ~/Downloads is not inside the sandbox on this machine:\n%s" % e)
        return 0

    shutil.rmtree(base, ignore_errors=True)
    build_tree(base)
    before = count_files(base)
    print("fixture: %s  (%d files)" % (base, before))

    app = FastAPI()
    app.include_router(router_fm)
    client = TestClient(app)

    try:
        r = client.get(PREFIX + "/cleanup/scan", params={"path": base})
        check("GET /cleanup/scan -> 200", r.status_code == 200,
              "%s %s" % (r.status_code, r.text[:200]))
        categories = r.json().get("categories") if r.status_code == 200 else None
        check("scan returns a categories list", isinstance(categories, list),
              type(categories).__name__)
        if not isinstance(categories, list):
            return 1

        hits = sorted({c["id"] for c in categories if c.get("count")})
        print("       categories with hits: %s" % hits)
        for expected in ("pycache", "os_junk", "temp_files", "empty_dirs", "duplicates"):
            check("scan detected %s" % expected, expected in hits, hits)

        r = client.post(PREFIX + "/cleanup/apply",
                        json={"path": base, "category_ids": hits, "dry_run": True})
        check("POST /cleanup/apply dry_run=true -> 200", r.status_code == 200,
              "%s %s" % (r.status_code, r.text[:200]))
        if r.status_code == 200:
            body = r.json()
            check("dry run echoes dry_run=true", body.get("dry_run") is True, body.get("dry_run"))
            check("dry run listed deletions", len(body.get("deleted", [])) > 0,
                  len(body.get("deleted", [])))
            check("dry run touched nothing on disk", count_files(base) == before,
                  "%d -> %d" % (before, count_files(base)))

        r = client.post(PREFIX + "/cleanup/apply",
                        json={"path": base, "category_ids": hits, "dry_run": False})
        check("POST /cleanup/apply dry_run=false -> 200", r.status_code == 200,
              "%s %s" % (r.status_code, r.text[:200]))
        if r.status_code == 200:
            body = r.json()
            after = count_files(base)
            check("real run echoes dry_run=false", body.get("dry_run") is False, body.get("dry_run"))
            check("real run freed bytes", body.get("freed", 0) > 0, body.get("freed"))
            check("real run removed files", after < before, "%d -> %d" % (before, after))
            check("real run reported no failures", not body.get("failed"), body.get("failed"))
            survivors = [n for n in ("dup_a.bin", "dup_b.bin")
                         if os.path.exists(os.path.join(base, n))]
            check("duplicates kept exactly one copy", len(survivors) == 1, survivors)

        # A blocked root must still be refused after the fix, not merely before.
        outside = "C:\\Windows" if os.name == "nt" else "/etc"
        r = client.post(PREFIX + "/cleanup/apply",
                        json={"path": outside, "category_ids": ["pycache"], "dry_run": True})
        check("apply outside the allowed roots is refused",
              r.status_code in (400, 403), r.status_code)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n%d check(s) failed" % len(_failures))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
