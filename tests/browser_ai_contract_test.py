# -*- coding: utf-8 -*-
"""The browser-AI contract, end to end across the three surfaces that share it.

browser_ai_resolver_test.py locks the resolver's own chain. This file locks the
SEAMS: that the settings store, the agent payloads and the resolve endpoint all
speak the same field name and the same meaning of "" (not set), and that nothing
quietly re-seeds a model nobody chose.

Two regressions it exists to prevent, both found in review:

  1. PUT /api/v1/settings persisted _DEFAULT_SETTINGS.copy() merged with the
     body, so saving ANY unrelated setting (a theme, a language — even the new
     Default Browser AI picker itself) wrote "default_model": "qwen:latest" into
     global_settings.json. Step 3 of the chain reads that file, so a fresh
     install poisoned its own fallback the first time the user saved anything,
     and then reported the dead Ollama model as the user's "default AI" with
     is_configured true.

  2. POST /api/v1/ollama/assign passed browser_ai_model=req.model alongside the
     chat model, so assigning a chat model silently pinned the agent's browser
     AI to the same value — recording a choice the user never made, which is the
     exact state this whole chain exists to undo.
"""
import sys, json, asyncio, tempfile, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = 0
FAIL = 0
FAILURES = []


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        FAILURES.append("%s: got %r want %r" % (name, got, want))
        print("FAIL %s: got %r want %r" % (name, got, want))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


tmp = Path(tempfile.mkdtemp(prefix="browser_ai_contract_"))
try:
    import tubecli.config as config
    config.DATA_DIR = tmp
    config.GLOBAL_SETTINGS_FILE = tmp / "global_settings.json"

    from tubecli.extensions.webui import routes as wr
    wr._settings_path = lambda: str(tmp / "global_settings.json")

    SETTINGS = tmp / "global_settings.json"

    # ── 1. One field name, spoken by all three surfaces ──────────────
    check("config names the setting browser_ai_model",
          config.BROWSER_AI_SETTING, "browser_ai_model")
    check("dashboard defaults expose the key",
          "browser_ai_model" in wr._default_settings(), True)
    check("dashboard NEVER seeds it with a model name",
          wr._default_settings()["browser_ai_model"], "")

    # ── 2. REGRESSION: an unrelated save must not seed default_model ──
    check("fresh install has no settings file", SETTINGS.exists(), False)
    check("fresh install resolves to last_resort",
          config.resolve_browser_ai(None)["source"], "last_resort")

    run(wr.save_global_settings(Req({"theme": "dark"})))
    disk = json.loads(SETTINGS.read_text(encoding="utf-8"))
    check("saving only {'theme'} does NOT write default_model to disk",
          "default_model" in disk, False)
    check("saving only {'theme'} does NOT write browser_ai_model to disk",
          "browser_ai_model" in disk, False)
    check("...so the chain is still unpoisoned",
          config.resolve_browser_ai(None)["model"], config.LAST_RESORT_AI_MODEL)
    check("...and honestly reports nothing is configured",
          config.resolve_browser_ai(None)["is_configured"], False)

    # the PUT response still shows the EFFECTIVE settings (defaults merged)
    resp = run(wr.save_global_settings(Req({"theme": "light"})))
    body = json.loads(resp.body.decode("utf-8"))
    check("PUT response still carries merged defaults for the UI",
          body["settings"].get("default_model"), "qwen:latest")
    check("PUT response carries the new key", body["settings"].get("browser_ai_model"), "")

    # ── 3. The settings round-trip builder C could not test live ──────
    run(wr.save_global_settings(Req({"default_model": "deepseek-v4-flash"})))
    check("a real default_model persists",
          config.get_global_setting("default_model"), "deepseek-v4-flash")
    check("an unset browser AI inherits it",
          config.resolve_browser_ai(None)["model"], "deepseek-v4-flash")
    check("...reported as global_default",
          config.resolve_browser_ai(None)["source"], "global_default")

    run(wr.save_global_settings(Req({"browser_ai_model": "gemini-2.0-flash"})))
    check("a picked browser AI persists",
          config.get_global_setting("browser_ai_model"), "gemini-2.0-flash")
    check("...and outranks default_model",
          config.resolve_browser_ai(None)["source"], "browser_default")

    # "" is a legitimate value meaning "un-pick me", NOT a missing field
    run(wr.save_global_settings(Req({"browser_ai_model": ""})))
    disk = json.loads(SETTINGS.read_text(encoding="utf-8"))
    check("clearing writes '' rather than dropping the key",
          disk.get("browser_ai_model"), "")
    check("cleared browser AI falls back to default_model",
          config.resolve_browser_ai(None)["model"], "deepseek-v4-flash")

    # ── 4. Agent payloads carry the raw field (builder C's assumption 3) ──
    from tubecli.core.agent import Agent
    fresh = Agent(name="contract-agent")
    check("a new agent is born unset", fresh.browser_ai_model, "")
    check("to_dict carries browser_ai_model for the LIST payload",
          "browser_ai_model" in fresh.to_dict(), True)
    check("...as '' not a literal", fresh.to_dict()["browser_ai_model"], "")
    check("an unset agent inherits the user's default",
          config.resolve_browser_ai(fresh)["model"], "deepseek-v4-flash")

    # ── 5. The resolve payload's documented shape ─────────────────────
    info = config.resolve_browser_ai(fresh)
    for key in ("model", "source", "is_configured", "agent_model",
                "browser_default", "global_default", "last_resort",
                "ignored_legacy_model"):
        check("resolve payload has %s" % key, key in info, True)
    check("source is one of the documented enum",
          info["source"] in ("agent", "browser_default", "global_default", "last_resort"), True)
    check("model is never empty", bool(info["model"]), True)

    # ── 6. REGRESSION: assigning a CHAT model must not pin the browser AI ──
    import inspect
    from tubecli.extensions.ollama_manager import routes as om
    # Comments explain the old bug and name the argument, so look at CODE only.
    code = "\n".join(
        line for line in inspect.getsource(om.api_assign_model).splitlines()
        if not line.strip().startswith("#")
    )
    check("ollama assign no longer stamps browser_ai_model",
          "browser_ai_model=" in code, False)
    check("ollama assign still sets the chat model", "model=req.model" in code, True)

finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n%d/%d PASS" % (PASS, PASS + FAIL))
for f in FAILURES:
    print("  - " + f)
sys.exit(1 if FAIL else 0)
