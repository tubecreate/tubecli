# -*- coding: utf-8 -*-
"""One test per confirmed audit finding.

The recompute test is the important one: it drives the exact sequence that used
to destroy the migrated t2login history — a seeded row that later logs a real
run — and proves the baseline survives. It does so on a synthetic slug whose
seed columns are set directly in D1, so the 16 real inherited rows are never
used as a guinea pig. They are snapshotted before and compared after anyway.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://tubecli-scripts.tubecli.workers.dev"
HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = json.load(open(os.path.join(HERE, "secrets.json"), encoding="utf-8"))
ADMIN = {"X-Admin-Token": CREDS["ADMIN_TOKEN"]}
CLIENT = {"X-Client-Key": CREDS["CLIENT_KEY"]}
UA = "tubecli-audit-fixes/1.0"
SLUG = "__fix_probe__"

ACC = os.environ["CF_GLOBAL_KEY"]
DB = "6cce8231-6a45-43ed-b115-f060758134a6"
D1H = {"X-Auth-Email": os.environ["CF_EMAIL"], "X-Auth-Key": os.environ["CF_TOKEN"],
       "Content-Type": "application/json", "User-Agent": UA}

fails = []


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


def d1(sql, params=None):
    r = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACC}/d1/database/{DB}/query",
        data=json.dumps({"sql": sql, "params": params or []}).encode(),
        headers=D1H, method="POST")
    try:
        d = json.load(urllib.request.urlopen(r, timeout=90))
    except urllib.error.HTTPError as e:
        d = json.loads(e.read().decode())
    if not d.get("success"):
        raise SystemExit("D1: " + json.dumps(d.get("errors"))[:300])
    return d["result"][-1].get("results", [])


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f"   {str(detail)[:220]}"))
    if not ok:
        fails.append(label)


jreq(f"/api/admin/scripts/{SLUG}?purge=1", method="DELETE", headers=ADMIN)

print("=== #1/2/4 HIGH — recompute must not eat the inherited baseline ===")
before = {r["slug"]: (r["attempts"], r["successes"])
          for r in d1("SELECT slug, attempts, successes FROM script_stats")}
inherited_total = sum(a for a, _ in before.values())
check("16 inherited rows are present before the test",
      len(before) == 16 and inherited_total > 900, (len(before), inherited_total))

jreq("/api/admin/scripts", method="POST", headers=ADMIN,
     body={"slug": SLUG, "name": "fix probe", "steps": []})
for ok in (True, False):
    jreq("/api/script-outcome", method="POST", headers=CLIENT,
         body={"slug": SLUG, "success": ok, "machine_id": "fix-probe-machine",
               "error": "" if ok else "boom"})
# Pretend this script arrived from t2login carrying 100 attempts / 60 successes,
# on top of the 2 runs just logged. This is precisely the state that used to be
# annihilated by pressing "Tính lại thống kê".
d1("UPDATE script_stats SET seed_attempts = 100, seed_successes = 60, "
   "attempts = 102, successes = 61 WHERE slug = ?", [SLUG])

code, d = jreq("/api/admin/stats/recompute", method="POST", headers=ADMIN)
check("recompute runs", code == 200, (code, d))

row = d1("SELECT attempts, successes FROM script_stats WHERE slug = ?", [SLUG])[0]
check("baseline + raw log, not raw log alone (102/61, not 2/1)",
      (row["attempts"], row["successes"]) == (102, 61), row)

after = {r["slug"]: (r["attempts"], r["successes"])
         for r in d1("SELECT slug, attempts, successes FROM script_stats")}
drift = {k: (before[k], after[k]) for k in before if before.get(k) != after.get(k)}
check("no inherited row was touched by the rebuild", not drift, drift)

print("\n=== #3 HIGH — creating over an existing slug must not overwrite it ===")
_, live = jreq("/api/scripts/youtube_upload")
steps_before = len(live["script"]["steps"])
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "youtube_upload", "name": "", "steps": [
                   {"type": "navigate", "label": "x", "params": {"url": "https://example.com"}}]})
check("a colliding create is refused with 409",
      code == 409 and d.get("code") == "SLUG_EXISTS", (code, d))
_, live2 = jreq("/api/scripts/youtube_upload")
check(f"the real script still has its {steps_before} steps",
      len(live2["script"]["steps"]) == steps_before, len(live2["script"]["steps"]))
check("and its name is intact", live2["script"]["name"] == live["script"]["name"],
      live2["script"]["name"])
code, d = jreq(f"/api/admin/scripts?overwrite=1", method="POST", headers=ADMIN,
               body={"slug": SLUG, "name": "overwritten on purpose", "steps": []})
check("an explicit ?overwrite=1 is still allowed", code == 200, (code, d))

print("\n=== #5 MEDIUM — punctuation-only slugs must not collide on '_' ===")
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "!!!", "steps": []})
check("'!!!' is rejected, not folded to '_'", code == 400, (code, d))
code, d = jreq("/api/admin/scripts", method="POST", headers=ADMIN,
               body={"slug": "@@@", "steps": []})
check("'@@@' likewise", code == 400, (code, d))
code, d = jreq("/api/admin/scripts/_", headers=ADMIN)
check("no stray '_' script was ever created", code == 404, code)

print("\n=== #6 LOW — a disabled script must be withheld from the single read too ===")
jreq(f"/api/admin/scripts/{SLUG}/toggle", method="POST", headers=ADMIN)
code, d = jreq(f"/api/scripts/{SLUG}")
check("GET /api/scripts/{slug} 404s once disabled", code == 404, (code, d))
code, d = jreq(f"/api/admin/scripts/{SLUG}", headers=ADMIN)
check("but an admin can still read it", code == 200, code)
jreq(f"/api/admin/scripts/{SLUG}/toggle", method="POST", headers=ADMIN)

print("\n=== #7 LOW — a malformed URL is a 400, not a 500 ===")
code, d = jreq("/api/scripts/%E0%A4%A")
check("bad percent-escape on the public read", code == 400 and d.get("code") == "BAD_PATH", (code, d))
code, d = jreq("/api/admin/scripts/%zz", headers=ADMIN)
check("and on the admin read", code == 400, (code, d))
code, d = jreq("/api/admin/scripts/%E0%A4%A/toggle", method="POST", headers=ADMIN)
check("and on toggle", code == 400, (code, d))

print("\n=== #8 LOW — a nested array must not blow the stack ===")
nested = ["x"]
for _ in range(2000):
    nested = [nested]
code, d = jreq("/api/script-outcome", method="POST", headers=CLIENT,
               body={"slug": nested, "success": True})
check("a deeply nested slug is a clean 400", code == 400, (code, str(d)[:120]))
code, d = jreq("/api/script-outcome", method="POST", headers=CLIENT,
               body={"slug": SLUG, "success": True, "machine_id": nested,
                     "error": {"a": 1}})
check("nested machine_id / object error do not crash it", code == 200, (code, str(d)[:120]))

print("\n=== #9 LOW — machine_id must be trimmed on both write paths ===")
jreq("/api/script-outcome", method="POST", headers=CLIENT,
     body={"slug": SLUG, "success": True, "machine_id": "  trim-me  "})
jreq("/api/register", method="POST", headers=CLIENT, body={"machine_id": "trim-me"})
_, d = jreq("/api/admin/clients", headers=ADMIN)
ids = [c["machine_id"] for c in d.get("clients", []) if "trim-me" in c["machine_id"]]
check("one machine, one row", ids == ["trim-me"], ids)

print("\n=== #10/11/12 LOW — the two headline tiles must agree ===")
code, d = jreq("/api/admin/overview", headers=ADMIN)
t = d.get("totals", {})
check("overview reports total attempts including inherited history",
      t.get("attempts", 0) >= 964, t)
check("and reports the logged subset separately",
      "logged_runs" in t and t["logged_runs"] <= t["attempts"], t)
seed_sum = d1("SELECT COALESCE(SUM(seed_attempts),0) s FROM script_stats")[0]["s"]
check("and how much of it is inherited", t.get("inherited") == seed_sum,
      (t.get("inherited"), seed_sum))
sum_rows = sum((s.get("stats") or {}).get("attempts", 0) for s in d.get("scripts", []))
check("the total is never smaller than the sum of the visible rows",
      t["attempts"] >= sum_rows, (t["attempts"], sum_rows))

print("\n=== #14 LOW — inherited numbers must match t2login ===")
live_t2 = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://t2login-license.tiensyk09.workers.dev/api/script-stats",
    headers={"User-Agent": UA}), timeout=30))["stats"]
_, ours = jreq("/api/script-stats")
mismatch = []
for slug, s in live_t2.items():
    o = ours["stats"].get(slug)
    if o and (o["attempts"], o["successes"]) != (s["attempts"], s["successes"]):
        mismatch.append((slug, (o["attempts"], o["successes"]), (s["attempts"], s["successes"])))
check("every inherited row matches t2login right now", not mismatch, mismatch)

print("\n=== teardown ===")
code, d = jreq(f"/api/admin/scripts/{SLUG}?purge=1", method="DELETE", headers=ADMIN)
check("probe purged", code == 200, (code, d))
# Remove every machine any test fixture invented. Asserting "zero clients"
# would be wrong as a rule — real machines are supposed to appear here — so the
# check is that no FIXTURE survives, not that the table is empty.
d1("DELETE FROM clients WHERE machine_id IN "
   "('fix-probe-machine','trim-me','smoke-machine','')")
final = d1("SELECT (SELECT COUNT(*) FROM scripts) s, (SELECT COUNT(*) FROM script_stats) t, "
           "(SELECT COUNT(*) FROM script_outcomes) o, (SELECT COUNT(*) FROM clients) c")[0]
check("catalogue and stats are back to 22 / 16 with an empty raw log",
      (final["s"], final["t"], final["o"]) == (22, 16, 0), final)
leftovers = d1("SELECT machine_id FROM clients WHERE machine_id LIKE '%probe%' "
               "OR machine_id LIKE '%smoke%' OR machine_id LIKE '%trim%'")
check("no test machine left behind", not leftovers, leftovers)

print()
if fails:
    print(f"FAILED: {len(fails)}")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("ALL AUDIT-FIX CHECKS PASSED")
