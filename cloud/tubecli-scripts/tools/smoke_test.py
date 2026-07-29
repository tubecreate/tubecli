# -*- coding: utf-8 -*-
"""Smoke test the deployed worker.

Everything that writes goes through a throwaway script slug, so the seeded
t2login history is never touched. The teardown removes it from all three tables.
"""
import json
import os
import urllib.error
import urllib.request

BASE = "https://tubecli-scripts.tubecli.workers.dev"
HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = json.load(open(os.path.join(HERE, "secrets.json"), encoding="utf-8"))
ADMIN = {"X-Admin-Token": CREDS["ADMIN_TOKEN"]}
CLIENT = {"X-Client-Key": CREDS["CLIENT_KEY"]}
SLUG = "__smoke_test__"

fails = []


# Cloudflare's bot protection answers "error code: 1010" to the default
# Python-urllib agent. Every client has to name itself — t2login learned this
# too, which is why its sync sets "T2Login/1.0 ScriptSync".
UA = "tubecli/1.0 ScriptSync"


def req(path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, **(headers or {})}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def jreq(path, **kw):
    code, raw = req(path, **kw)
    try:
        return code, json.loads(raw)
    except Exception:
        return code, {"_raw": raw[:200]}


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f"   {str(detail)[:200]}"))
    if not ok:
        fails.append(label)


# A previous run may have left the test slug behind: DELETE keeps history on
# purpose, so only a purge truly resets the fixture.
jreq(f"/api/admin/scripts/{SLUG}?purge=1", method="DELETE", headers=ADMIN)
_, _base = jreq("/api/script-stats")
BASE_STATS = len(_base.get("stats", {}))
_, _bc = jreq("/api/admin/clients", headers=ADMIN)
BASE_RUNS = next((c["runs"] for c in _bc.get("clients", []) if c["machine_id"] == "smoke-machine"), 0)

print("=== 1. Public reads ===")
code, d = jreq("/health")
check("GET /health", code == 200 and d.get("ok") is True, d)
check("health reports the seeded catalogue", d.get("scripts") == 22, d.get("scripts"))

code, d = jreq("/api/scripts")
check("GET /api/scripts", code == 200 and isinstance(d.get("scripts"), list), code)
scripts = d.get("scripts", [])
check("all 22 scripts served", len(scripts) == 22, len(scripts))
one = next((s for s in scripts if s["slug"] == "news_reuters"), None)
check("steps arrive decoded, not as a JSON string",
      isinstance(one and one.get("steps"), list) and len(one["steps"]) == 9,
      type(one.get("steps")) if one else None)
check("tags decoded too", isinstance(one.get("tags"), list), one.get("tags"))
check("is_function is a real boolean", one.get("is_function") is False, one.get("is_function"))

code, d = jreq("/api/scripts/youtube_upload")
check("GET /api/scripts/{slug}", code == 200 and d["script"]["slug"] == "youtube_upload", code)
check("the 36-step script is intact", len(d["script"]["steps"]) == 36, len(d["script"]["steps"]))

code, d = jreq("/api/scripts/nope_does_not_exist")
check("unknown slug is a clean 404", code == 404 and d.get("code") == "NOT_FOUND", (code, d))

code, d = jreq("/api/script-stats")
st = d.get("stats", {})
check("GET /api/script-stats", code == 200 and len(st) == BASE_STATS, (len(st), BASE_STATS))
# Pinned exact numbers rot: t2login keeps running and the baseline gets
# refreshed. What must hold is that the migration never LOSES history.
_ys = st.get("youtube_search_watch", {})
check("inherited t2login history survived the migration",
      _ys.get("attempts", 0) >= 196 and _ys.get("successes", 0) >= 114, _ys)

print("\n=== 2. Delta sync ===")
code, d = jreq("/api/scripts?since=2099-01-01%2000:00:00")
check("a future cursor returns nothing", code == 200 and d.get("count") == 0, d.get("count"))
check("a delta response carries the deleted list", isinstance(d.get("deleted"), list), d.get("deleted"))
code, d = jreq("/api/scripts?since=2000-01-01%2000:00:00")
check("an old cursor returns everything", d.get("count") == 22, d.get("count"))
# A script saved in the same second as the client's cursor must still arrive:
# with one-second timestamps a strict > would strand it permanently.
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "__edge_since__", "steps": []})
_, _s = jreq("/api/admin/scripts/__edge_since__", headers=ADMIN)
stamp = _s["script"]["updated_at"]
code, d = jreq("/api/scripts?since=" + stamp.replace(" ", "%20"))
check("a script saved on the cursor second is still delivered",
      any(x["slug"] == "__edge_since__" for x in d.get("scripts", [])), d.get("count"))
jreq("/api/admin/scripts/__edge_since__?purge=1", method="DELETE", headers=ADMIN)

code, d = jreq("/api/scripts?category=news")
# news_reading + cnn + reuters + guardian + google_policy_reading, which t2login
# also files under news.
check("category filter works", d.get("count") == 5, d.get("count"))

print("\n=== 3. Auth ===")
code, d = jreq("/api/admin/overview")
check("admin without a token is 401", code == 401 and d.get("code") == "ADMIN_TOKEN_REQUIRED", (code, d))
code, d = jreq("/api/admin/overview", headers={"X-Admin-Token": "wrong-but-same-length-xxxxxxxxxx"})
check("a wrong admin token is 401", code == 401, code)
code, d = jreq("/api/script-outcome", method="POST", body={"slug": "news_cnn", "success": True})
check("posting an outcome without the client key is 401",
      code == 401 and d.get("code") == "CLIENT_KEY_REQUIRED", (code, d))
code, d = jreq("/api/admin/overview", headers=ADMIN)
check("the real admin token works", code == 200 and "totals" in d, code)
check("overview counts every script including disabled", d["totals"]["scripts"] == 22, d["totals"])

print("\n=== 4. Admin write ===")
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN, body={
    "slug": SLUG, "name": "Smoke test", "category": "test",
    "target_url": "https://example.com", "tags": ["test"],
    "steps": [{"type": "navigate", "label": "open", "params": {"url": "https://example.com"}},
              {"type": "sleep", "label": "wait", "params": {"ms": 500}}],
})
check("create a script", code == 200 and d.get("created") is True, (code, d))

code, d = jreq(f"/api/admin/scripts/{SLUG}", headers=ADMIN)
check("read it back", code == 200 and len(d["script"]["steps"]) == 2, code)

code, d = jreq(f"/api/admin/scripts/{SLUG}", method="POST", headers=ADMIN,
               body={"name": "Smoke test renamed"})
check("a partial update keeps the untouched fields",
      code == 200 and d.get("created") is False, (code, d))
code, d = jreq(f"/api/admin/scripts/{SLUG}", headers=ADMIN)
check("name changed but steps survived",
      d["script"]["name"] == "Smoke test renamed" and len(d["script"]["steps"]) == 2,
      d["script"].get("name"))

code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "bad_steps", "steps": "not json at all"})
check("garbage steps are rejected, not stored", code == 400, (code, d))

# A slug in the body must not be able to redirect a write aimed at the path.
code, d = jreq(f"/api/admin/scripts/{SLUG}", method="POST", headers=ADMIN,
               body={"slug": "hijacked_slug", "description": "path must win"})
check("body slug cannot hijack the path", code == 200 and d.get("slug") == SLUG, (code, d))
code, d = jreq("/api/admin/scripts/hijacked_slug", headers=ADMIN)
check("and no stray script was created", code == 404, code)
code, d = jreq(f"/api/admin/scripts/{SLUG}", headers=ADMIN)
check("the addressed script got the update",
      d["script"]["description"] == "path must win", d["script"].get("description"))

# The slug is a filename on every client, so it is folded — but not trimmed.
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "Weird Name!!", "steps": []})
check("an unsafe slug is folded, not rejected", d.get("slug") == "weird_name_", (code, d))
jreq("/api/admin/scripts/weird_name_", method="DELETE", headers=ADMIN)

print("\n=== 5. Outcome recording ===")
for ok in (True, True, False):
    code, d = jreq("/api/script-outcome", method="POST", headers=CLIENT, body={
        "slug": SLUG, "success": ok, "machine_id": "smoke-machine",
        "client_version": "0.0.0-test", "engine": "shardx",
        "failed_step_index": None if ok else 1,
        "failed_step_label": "" if ok else "wait",
        "error": "" if ok else "timed out waiting for selector",
        "duration_ms": 1234,
    })
    check(f"record outcome success={ok}", code == 200 and d.get("success") is True, (code, d))

code, d = jreq("/api/script-stats")
s = d["stats"].get(SLUG, {})
check("the rollup counted all three runs", s.get("attempts") == 3, s)
check("and two successes", s.get("successes") == 2, s)
check("the failure message is kept for the board", "timed out" in (s.get("last_error") or ""), s)

code, d = jreq("/api/script-outcome", method="POST", headers=CLIENT,
               body={"slug": "no_such_script_at_all", "success": True})
check("an outcome for an unknown script is refused", code == 404, (code, d))

code, d = jreq(f"/api/admin/scripts/{SLUG}", headers=ADMIN)
check("the raw log is readable per script", len(d.get("outcomes", [])) == 3, len(d.get("outcomes", [])))
check("the failed step is recorded", any(o["failed_step_index"] == 1 for o in d["outcomes"]),
      d["outcomes"])

code, d = jreq("/api/admin/outcomes?failed=1&limit=50", headers=ADMIN)
check("the failures view finds it", any(o["slug"] == SLUG for o in d.get("outcomes", [])), d.get("count"))

code, d = jreq("/api/admin/clients", headers=ADMIN)
check("running a script bumps that machine's counter by three",
      any(c["machine_id"] == "smoke-machine" and c["runs"] == BASE_RUNS + 3
          for c in d.get("clients", [])),
      [(c["machine_id"], c["runs"]) for c in d.get("clients", [])])

print("\n=== 6. Toggle hides a script from clients ===")
code, d = jreq(f"/api/admin/scripts/{SLUG}/toggle", method="POST", headers=ADMIN)
check("toggle off", code == 200 and d.get("enabled") is False, (code, d))
code, d = jreq("/api/scripts")
check("a disabled script is withheld from clients",
      not any(s["slug"] == SLUG for s in d["scripts"]), d.get("count"))
code, d = jreq("/api/scripts?since=2000-01-01%2000:00:00")
check("but a delta sync tells clients to drop it", SLUG in (d.get("deleted") or []), d.get("deleted"))

print("\n=== 7. Dashboard ===")
code, raw = req("/")
check("GET / serves the dashboard", code == 200 and "<!doctype html>" in raw.lower(), code)
check("the text module really was bundled", "Tỉ lệ thành công script" in raw, len(raw))
check("it is not the worker source by mistake", "export default" not in raw, raw[:80])

print("\n=== 8. Teardown ===")
code, d = jreq(f"/api/admin/scripts/{SLUG}", method="DELETE", headers=ADMIN)
check("plain delete keeps the run history", code == 200 and d.get("history_kept") is True, (code, d))
code, d = jreq("/api/script-stats")
check("so the stats row survives the delete", SLUG in d.get("stats", {}), list(d.get("stats", {}))[:3])

# Recreate and purge, to prove the other half of the contract.
jreq("/api/admin/scripts", method="POST", headers=ADMIN, body={"slug": SLUG, "steps": []})
code, d = jreq(f"/api/admin/scripts/{SLUG}?purge=1", method="DELETE", headers=ADMIN)
check("purge deletes the script", code == 200 and d.get("history_kept") is False, (code, d))
code, d = jreq("/api/script-stats")
check("and forgets its history entirely", SLUG not in d.get("stats", {}), list(d.get("stats", {}))[:3])
code, d = jreq(f"/api/admin/outcomes?slug={SLUG}", headers=ADMIN)
check("the raw log is gone too", d.get("count") == 0, d.get("count"))
code, d = jreq("/api/scripts")
check("catalogue is back to 22", d.get("count") == 22, d.get("count"))

print()
if fails:
    print(f"FAILED: {len(fails)} check(s)")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("ALL WORKER CHECKS PASSED")
