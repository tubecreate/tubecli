"""The Cloud API key store must not lie, lose keys, or strand them disabled.

Run:  python tests/cloud_api_keys_test.py     (exit 0 = pass)

Everything runs against a temporary key file. The real data/cloud_api_keys.json
is never touched.

The audit found this system scoring 27-38/100 across five user roles. The
defects this file locks in are the ones Trụ A fixes:

  - "Active" was a lie. add_key marked every key active and test_key marked
    six of ten providers active with NO network call, so a typo'd key read as
    "hoạt động" until an agent died on it. There is now a `verified` flag that
    is True only after a real call confirmed the key.

  - A quota-hit key could only be revived by hand-editing JSON — no route, no
    method. enable_key() and the /keys/enable route now exist.

  - One transient 429 killed a key forever, and with two labels holding the
    SAME key value it disabled only the first, so failover retried the identical
    twin. report_key_error now separates transient (revives after a cooldown)
    from hard (stays off), and disables EVERY label that shares the key.

  - Cloudflare is a real chat provider (Workers AI). The registry marks it
    capability=chat/compound, and brain routes @cf/ models to it — the network
    call itself is exercised separately, live, not here.

Each guard is verified against the real KeyManager, and the load-bearing ones
by reintroducing the fault.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.cloud_api import extension as ext  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


def fresh():
    """A KeyManager backed by a throwaway file."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return ext.KeyManager(data_file=path), path


print("=" * 70)
print("CLOUD API KEYS")
print("=" * 70)

# ── provider metadata the dashboard depends on ──────────────────────────────
km, _ = fresh()
provs = {p["id"]: p for p in km.list_providers()}
check("all ten providers listed", len(provs) == 10, sorted(provs))
check("gemini is a chat provider", provs["gemini"]["capabilities"] == ["chat"], provs["gemini"])
check("github has no consumer", provs["github"]["capabilities"] == [], provs["github"])
check("everai has no consumer", provs["everai"]["capabilities"] == [], provs["everai"])
# Cloudflare is the case that forced capabilities to be a LIST: ONE stored
# credential backs both Workers AI chat and website_manager's wrangler deploys.
# Calling it "chat" alone told a website_manager user their deploy credential
# was a chat key.
check("cloudflare is BOTH chat and deploy",
      sorted(provs["cloudflare"]["capabilities"]) == ["chat", "deploy"],
      provs["cloudflare"].get("capabilities"))
check("legacy single-value field still resolves",
      provs["cloudflare"]["capability"] in ("chat", "deploy")
      and provs["github"]["capability"] == "none",
      "the old field broke for a consumer that has not migrated")
check("cloudflare is compound", provs["cloudflare"]["compound"] is True, "compound stripped again")
check("cloudflare exposes its fields", len(provs["cloudflare"]["fields"]) == 2,
      "the dashboard cannot render the two-field form without these")
check("cloudflare ships Workers AI models", len(provs["cloudflare"]["models"]) >= 4,
      provs["cloudflare"]["models"])
check("cloudflare models are @cf/ ids", all(m.startswith("@cf/") for m in provs["cloudflare"]["models"]),
      provs["cloudflare"]["models"])
# The fallback lists must not regress to the rotten 2025 names: the registry
# said gemini-2.5 while Google's own /models endpoint served gemini-3.7.
check("gemini fallback leads with a 3.x model", provs["gemini"]["models"][0].startswith("gemini-3"),
      provs["gemini"]["models"][:3])
check("provider metadata carries models_source", "models_source" in provs["gemini"],
      "the UI cannot say where the list came from")

# ── refresh_models: the live catalogue replaces the fallback ────────────────
km, _ = fresh()
_orig_fetch = ext.KeyManager._fetch_json
try:
    # Stub the network: gemini answers with a catalogue containing newer models
    # AND noise (tts/image/embedding) that must be filtered out of a chat list.
    def fake_fetch(url, headers=None):
        assert "generativelanguage" in url, url
        mk = lambda n, methods: {"name": f"models/{n}", "supportedGenerationMethods": methods}
        return {"models": [
            mk("gemini-9.9-flash", ["generateContent"]),
            mk("gemini-2.5-flash", ["generateContent"]),
            mk("gemma-4-31b-it", ["generateContent"]),
            mk("gemini-9.9-flash-tts", ["generateContent"]),     # non-chat: tts
            mk("text-embedding-005", ["embedContent"]),           # wrong method
            mk("gemini-9.9-image", ["generateContent"]),          # non-chat: image
        ]}
    ext.KeyManager._fetch_json = staticmethod(fake_fetch)
    km.add_key("gemini", "AIzaSomeKey", "k")
    r = km.refresh_models("gemini")
    check("refresh_models succeeds", r["status"] == "success", r)
    got = km.get_models("gemini")
    check("live catalogue replaces the fallback", "gemini-9.9-flash" in got, got)
    check("newest version sorts first", got[0] == "gemini-9.9-flash", got[:3])
    check("gemma sorts after gemini", got.index("gemma-4-31b-it") > got.index("gemini-2.5-flash"), got)
    check("tts/image/embedding are filtered out",
          not any(("tts" in m or "image" in m or "embedding" in m) for m in got), got)
    meta = km.models_meta("gemini")
    check("refresh stamps source=api with a time", meta["models_source"] == "api" and meta["models_updated_at"], meta)

    # An empty or failing fetch must NOT wipe a working list.
    ext.KeyManager._fetch_json = staticmethod(lambda url, headers=None: {"models": []})
    r = km.refresh_models("gemini")
    check("an empty catalogue is refused", r["status"] == "error", r)
    check("the previous list survives an empty fetch", km.get_models("gemini") == got, km.get_models("gemini")[:3])

    def boom(url, headers=None): raise RuntimeError("network down")
    ext.KeyManager._fetch_json = staticmethod(boom)
    r = km.refresh_models("gemini")
    check("a failed fetch is an error, not an exception", r["status"] == "error", r)
    check("the previous list survives a failed fetch", km.get_models("gemini") == got, "list was clobbered")
finally:
    ext.KeyManager._fetch_json = _orig_fetch

# ── add_key stores as UNVERIFIED, not a fake green ──────────────────────────
km, _ = fresh()
km.add_key("gemini", "AIzaSyTOTALLYFAKEKEY000000", "main")
row = km.list_keys("gemini")["gemini"]["main"]
check("a new key is active but not verified", row["active"] is True and row["verified"] is False,
      f"active={row['active']} verified={row['verified']}")

# ── test_key: unverifiable providers say so instead of faking success ───────
km, _ = fresh()
km.add_key("claude", "sk-ant-fake", "c")
res = km.test_key("claude", "c")
check("claude test does not claim success", res["status"] == "info" and res["verified"] is False,
      res)
km.add_key("github", "ghp_fake", "g")
res = km.test_key("github", "g")
check("an unknown provider is stored_unverified, not verified", res.get("verified") is False,
      res)
row = km.list_keys("github")["github"]["g"]
check("stored-unverified key reads unverified in the table", row["verified"] is False, row)

# ── enable_key: the revival path that did not exist ─────────────────────────
km, _ = fresh()
km.add_key("gemini", "AIzaKEY", "k")
km.report_key_error("gemini", "AIzaKEY", "Quota Exceeded", transient=False)
check("hard error disables the key", km.list_keys("gemini")["gemini"]["k"]["active"] is False, "still active")
enabled = km.enable_key("gemini", "k")
check("enable_key succeeds", enabled["status"] == "success", enabled)
check("enable_key clears the disabled state",
      km.list_keys("gemini")["gemini"]["k"]["active"] is True
      and not km.list_keys("gemini")["gemini"]["k"]["status_msg"],
      km.list_keys("gemini")["gemini"]["k"])
check("enable_key on a missing key errors", km.enable_key("gemini", "nope")["status"] == "error", "accepted")

# ── transient vs hard ───────────────────────────────────────────────────────
orig_cd = ext.TRANSIENT_COOLDOWN_SECONDS
ext.TRANSIENT_COOLDOWN_SECONDS = 1
try:
    km, _ = fresh()
    km.add_key("gemini", "AIzaTRANSIENT", "t")
    km.report_key_error("gemini", "AIzaTRANSIENT", "429 rate limit", transient=True)
    check("a transient error parks the key immediately", km.get_active_key("gemini") is None,
          "key still served before cooldown")
    time.sleep(1.2)
    check("a transient key revives after the cooldown", km.get_active_key("gemini") == "AIzaTRANSIENT",
          "still parked after cooldown — auto-revive broken")

    km, _ = fresh()
    km.add_key("gemini", "AIzaHARD", "h")
    km.report_key_error("gemini", "AIzaHARD", "insufficient_quota", transient=False)
    time.sleep(1.2)
    check("a hard error does NOT revive", km.get_active_key("gemini") is None,
          "hard-disabled key came back on its own")
finally:
    ext.TRANSIENT_COOLDOWN_SECONDS = orig_cd

# ── duplicate key value: BOTH labels disabled, so failover finds a real spare ─
km, _ = fresh()
km.add_key("gemini", "AIzaSAME", "a")
km.add_key("gemini", "AIzaSAME", "b")   # same underlying key, two labels — the live data shape
km.add_key("gemini", "AIzaOTHER", "c")  # a genuine spare
km.report_key_error("gemini", "AIzaSAME", "Quota Exceeded", transient=False)
rows = km.list_keys("gemini")["gemini"]
check("disabling a shared key disables ALL its labels",
      rows["a"]["active"] is False and rows["b"]["active"] is False,
      f"a={rows['a']['active']} b={rows['b']['active']} — the twin was left active")
check("the genuine spare is what get_active_key returns", km.get_active_key("gemini") == "AIzaOTHER",
      km.get_active_key("gemini"))

# ── add_key reloads first, so it cannot clobber a concurrent disable ────────
km, path = fresh()
km.add_key("gemini", "AIzaA", "a")
# Simulate another process disabling the key by writing the file directly.
data = json.loads(Path(path).read_text(encoding="utf-8"))
data["gemini"]["a"]["active"] = False
data["gemini"]["a"]["status_msg"] = "disabled elsewhere"
Path(path).write_text(json.dumps(data), encoding="utf-8")
# Now add a DIFFERENT key through the same manager instance (stale in memory).
km.add_key("gemini", "AIzaB", "b")
after = json.loads(Path(path).read_text(encoding="utf-8"))["gemini"]
check("add_key preserves a disable written by another path",
      after["a"]["active"] is False and after["b"]["active"] is True,
      f"a={after['a'].get('active')} b in file={'b' in after}")

# ── routing: @cf/ goes to Cloudflare, never OpenRouter ──────────────────────
from tubecli.core.brain import AgentBrain  # noqa: E402

calls = {}
orig_cf = AgentBrain._call_cloudflare
orig_oai = AgentBrain._call_openai
AgentBrain._call_cloudflare = staticmethod(lambda model, messages, temperature=0.7: f"CF::{model}")
AgentBrain._call_openai = staticmethod(lambda *a, **k: "OAI::" + (a[0] if a else "?"))
try:
    r = AgentBrain._call_provider("cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", {}, [], 0.2)
    check("_call_provider routes cloudflare to _call_cloudflare", r.startswith("CF::"), r)

    # The critical ordering: an @cf/ id contains a slash, so without the guard it
    # falls into the slash rule and ships to OpenRouter.
    agent = {"provider": "", "model": "@cf/openai/gpt-oss-20b", "cloud_api_keys": {}}
    r = AgentBrain._call_llm(agent, [{"role": "user", "content": "hi"}], 0.2)
    check("_call_llm routes an @cf/ model to Cloudflare, not OpenRouter", r.startswith("CF::"),
          f"got {r!r} — the slash rule swallowed the @cf/ id")
finally:
    AgentBrain._call_cloudflare = staticmethod(orig_cf)
    AgentBrain._call_openai = staticmethod(orig_oai)


# ── Cloudflare creds must agree with has_key: any active label, not only "default" ──
# The dashboard form lets the user NAME the profile ("tuan", an email, …).
# list_providers() then reported Cloudflare ready (get_active_key takes ANY active
# entry) while get_cloudflare_creds() looked only for the label "default" — so
# Workers AI chat and Content Studio's image engine both answered "no credential"
# on a box whose UI showed a green dot. Seen live 2026-09-04.
import unittest.mock as _mock
_fd, _cf_path = tempfile.mkstemp(suffix=".json")
os.close(_fd)
with open(_cf_path, "w", encoding="utf-8") as _f:
    _f.write("{}")
_cf_env = {k: "" for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_EMAIL")}
try:
    with _mock.patch.dict(os.environ, _cf_env):
        km = ext.KeyManager(data_file=_cf_path)
        km.add_cloudflare_key("tok-tuan", "acc-tuan", label="tuan")
        c = km.get_cloudflare_creds()
        check("creds fall back to the only active profile when 'default' is absent",
              c["api_token"] == "tok-tuan" and c["account_id"] == "acc-tuan" and c["label"] == "tuan", c)
        check("  and agree with what has_key saw", km.get_active_key("cloudflare") == "tok-tuan")
        km.add_cloudflare_key("tok-def", "acc-def", label="default")
        check("a real 'default' profile still wins", km.get_cloudflare_creds()["label"] == "default")
        km._keys["cloudflare"]["default"]["active"] = False
        km._save()
        check("a disabled 'default' is skipped for an active sibling",
              km.get_cloudflare_creds()["label"] == "tuan", km.get_cloudflare_creds())
        check("an explicit missing label does NOT silently swap accounts",
              km.get_cloudflare_creds("nope")["api_token"] == "", km.get_cloudflare_creds("nope"))
        km._keys["cloudflare"] = {"half": {"key": "t", "account_id": "", "active": True}}
        km._save()
        check("an entry missing account_id is not offered as a fallback",
              km.get_cloudflare_creds()["api_token"] == "", km.get_cloudflare_creds())
finally:
    os.unlink(_cf_path)

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
