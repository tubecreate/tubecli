# -*- coding: utf-8 -*-
"""Seed tubecli-scripts-db from t2login.

Two sources, because neither is complete on its own:
  - the live API (17 rows) carries scripts that were never shipped to disk;
  - launcher/scripts/*.json (18 files) carries the "global" pack the client
    keeps locally and the server never serves back (news_cnn, news_reuters,
    shopping_ebay ...). script_sync.py calls these _BUILTIN_KEEP.
Overlaps are resolved the way script_sync resolves them: newest updated_at wins.
"""
import json
import os
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_DIR = r"C:\tubecreate-vue\t2login\launcher\scripts"

ACC = os.environ["CF_GLOBAL_KEY"]
EMAIL = os.environ["CF_EMAIL"]
KEY = os.environ["CF_TOKEN"]
DB = "6cce8231-6a45-43ed-b115-f060758134a6"
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC}/d1/database/{DB}/query"

JSON_FIELDS = ("tags", "steps", "variables", "function_inputs", "function_outputs")


def q(sql, params=None):
    body = json.dumps({"sql": sql, "params": params or []}).encode()
    req = urllib.request.Request(
        URL, data=body,
        headers={"X-Auth-Email": EMAIL, "X-Auth-Key": KEY,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        r = json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        r = json.loads(e.read().decode())
    if not r.get("success"):
        raise SystemExit("D1 error: " + json.dumps(r.get("errors"))[:500])
    return r["result"][0].get("results", [])


def as_json_text(v, default="[]"):
    """Normalise a field to a JSON string. The API hands some of these back
    already-encoded, the files hand them back as real lists."""
    if v is None or v == "":
        return default
    if isinstance(v, str):
        try:
            json.loads(v)
            return v
        except Exception:
            # a bare comma list, which is how tags sometimes arrive
            return json.dumps([t.strip() for t in v.split(",") if t.strip()],
                              ensure_ascii=False)
    return json.dumps(v, ensure_ascii=False)


def normalise(raw):
    slug = (raw.get("slug") or "").strip()
    if not slug:
        return None
    upd = str(raw.get("updated_at") or raw.get("created_at") or "")
    return {
        "slug": slug,
        "name": raw.get("name") or slug,
        "description": raw.get("description") or "",
        "category": (raw.get("category") or "general").strip().lower(),
        "target_url": raw.get("target_url") or "",
        "tags": as_json_text(raw.get("tags")),
        "steps": as_json_text(raw.get("steps")),
        "variables": as_json_text(raw.get("variables")),
        "is_function": 1 if raw.get("is_function") in (1, True, "1", "true") else 0,
        "function_inputs": as_json_text(raw.get("function_inputs")),
        "function_outputs": as_json_text(raw.get("function_outputs")),
        "engine": "any",
        "min_client": "",
        "enabled": 1,
        "created_at": str(raw.get("created_at") or upd),
        "updated_at": upd,
    }


T2 = "https://t2login-license.tiensyk09.workers.dev/api"


def fetch_t2(path, cache_name):
    """Read t2login live, falling back to a cached snapshot only if it is down.

    Reading a snapshot by preference is how three of the sixteen migrated stat
    rows ended up behind t2login's real numbers: the file was captured minutes
    before the seed ran and t2login kept working in between.
    """
    try:
        req = urllib.request.Request(T2 + path,
                                     headers={"User-Agent": "tubecli/1.0 ScriptSync"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        with open(os.path.join(HERE, cache_name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  fetched {path} live from t2login")
        return data
    except Exception as e:
        print(f"  ! t2login unreachable ({e}); falling back to cached {cache_name}")
        return json.load(open(os.path.join(HERE, cache_name), encoding="utf-8"))


# ── gather ────────────────────────────────────────────────────────────────────
catalog = {}
srcs = {"server": 0, "local": 0, "kept-newer": 0}

api = fetch_t2("/scripts", "t2_scripts.json")
for row in api.get("scripts", []):
    rec = normalise(row)
    if rec:
        catalog[rec["slug"]] = rec
        srcs["server"] += 1

for fn in sorted(os.listdir(LOCAL_DIR)):
    if not fn.endswith(".json"):
        continue
    try:
        rec = normalise(json.load(open(os.path.join(LOCAL_DIR, fn), encoding="utf-8")))
    except Exception as e:
        print(f"  ! skip {fn}: {e}")
        continue
    if not rec:
        continue
    prev = catalog.get(rec["slug"])
    if prev and prev["updated_at"] >= rec["updated_at"]:
        srcs["kept-newer"] += 1
        continue
    catalog[rec["slug"]] = rec
    srcs["local"] += 1

print(f"catalog: {len(catalog)} scripts  (from API {srcs['server']}, "
      f"file wins {srcs['local']}, API wins {srcs['kept-newer']})")

# ── write ─────────────────────────────────────────────────────────────────────
COLS = ["slug", "name", "description", "category", "target_url", "tags", "steps",
        "variables", "is_function", "function_inputs", "function_outputs",
        "engine", "min_client", "enabled", "created_at", "updated_at"]
SQL = (f"INSERT OR REPLACE INTO scripts ({','.join(COLS)}) "
       f"VALUES ({','.join('?' * len(COLS))})")

for slug, rec in sorted(catalog.items()):
    q(SQL, [rec[c] for c in COLS])
    n = len(json.loads(rec["steps"]))
    print(f"  + {slug:30} {rec['category']:14} steps={n}")

# ── inherited stats ───────────────────────────────────────────────────────────
# Real numbers from t2login for these exact scripts. Seeding them gives the
# epsilon-greedy selector a prior instead of making it rediscover, from scratch,
# that news_cnn fails 25 times out of 26.
stats = fetch_t2("/script-stats", "t2_stats.json").get("stats", {})
kept = 0
for slug, s in stats.items():
    if slug not in catalog:
        print(f"  ~ stats for unknown script, skipped: {slug}")
        continue
    # seed_* is the immutable record of what was inherited. attempts/successes
    # are what gets published, and a later /stats/recompute rebuilds them as
    # seed + this store's own raw log — never from the log alone, which would
    # erase history this store never witnessed.
    q("INSERT INTO script_stats "
      "(slug, attempts, successes, last_success_at, last_failure_at, last_error, "
      " seed_attempts, seed_successes) VALUES (?,?,?,?,?,'',?,?) "
      "ON CONFLICT(slug) DO UPDATE SET "
      "  seed_attempts = excluded.seed_attempts, "
      "  seed_successes = excluded.seed_successes, "
      "  attempts = excluded.attempts, successes = excluded.successes, "
      "  last_success_at = MAX(script_stats.last_success_at, excluded.last_success_at), "
      "  last_failure_at = MAX(script_stats.last_failure_at, excluded.last_failure_at)",
      [slug, int(s.get("attempts", 0)), int(s.get("successes", 0)),
       s.get("last_success_at") or "", s.get("last_failure_at") or "",
       int(s.get("attempts", 0)), int(s.get("successes", 0))])
    kept += 1

print(f"\nseeded {len(catalog)} scripts, {kept} stat rows")
rows = q("SELECT COUNT(*) c FROM scripts")
print("scripts in D1:", rows[0]["c"])
rows = q("SELECT COUNT(*) c FROM script_stats")
print("stat rows in D1:", rows[0]["c"])
