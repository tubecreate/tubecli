"""One chain decides which AI drives a browser session. Four steps, in order.

Run:  python tests/browser_ai_resolver_test.py     (exit 0 = pass)

Why this file exists. The chain was not a chain — it was the literal
"qwen:latest" typed at nine separate call sites (api/server.py, core/agent.py,
core/brain.py, nodes/browser_node.py, the browser extension's routes and
process_manager, and twice in open.js). qwen:latest is an Ollama model name and
Ollama does not run on a hosted TubeCLI server, so every agent that had never
opened the browser-AI picker was launched against a model that never answers.
The user's own default AI — the one already configured and working everywhere
else in the product — was sitting right there in global_settings.json and was
never consulted.

Worse, the agent editor pre-filled its picker with that same literal, so saving
an agent's form wrote "qwen:latest" into the agent as if the user had chosen it.
An agent could therefore be *stuck* on the dead model without anyone ever having
picked it.

What is locked in here:

  1. the four steps resolve in exactly this priority —
     agent -> global_settings "browser_ai_model" -> global_settings
     "default_model" -> LAST_RESORT_AI_MODEL;
  2. "" (and whitespace, and a missing key) means NOT SET at every step and
     falls through rather than blocking the steps below it — this is the case
     that was broken, because an empty agent field used to be replaced by a
     literal instead of deferring;
  3. an agent still carrying the birth-default "qwen:latest" defers to a real
     setting, but is honoured when there is no real setting to defer to;
  4. `source` reports which step won, so a UI can say "using your default AI"
     rather than showing a blank box the user reads as broken.

The chain reads one JSON file, so the test points GLOBAL_SETTINGS_FILE at a temp
copy instead of touching the developer's own settings.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from pathlib import Path

from tubecli import config

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


class Settings:
    """Point config.GLOBAL_SETTINGS_FILE at a throwaway file."""

    def __init__(self, tmp):
        self.path = Path(tmp) / "global_settings.json"
        self.original = config.GLOBAL_SETTINGS_FILE
        config.GLOBAL_SETTINGS_FILE = self.path

    def write(self, **keys):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(keys, f)

    def remove(self):
        if self.path.exists():
            os.remove(self.path)

    def restore(self):
        config.GLOBAL_SETTINGS_FILE = self.original


class FakeAgent:
    """An Agent object as the scheduler holds it (attribute, not dict key)."""

    def __init__(self, browser_ai_model):
        self.browser_ai_model = browser_ai_model


def main():
    tmp = tempfile.mkdtemp(prefix="browserai_")
    s = Settings(tmp)
    last = config.LAST_RESORT_AI_MODEL
    try:
        print("\n=== 1. the four steps, in order ===")

        # Everything set: step 1 wins.
        s.write(browser_ai_model="setting-browser", default_model="setting-global")
        r = config.resolve_browser_ai({"browser_ai_model": "agent-pick"})
        check("step 1 — the agent's own model beats both settings",
              r["model"] == "agent-pick" and r["source"] == "agent", r["model"])

        # Agent silent: step 2 wins.
        r = config.resolve_browser_ai({"browser_ai_model": ""})
        check("step 2 — the default browser AI beats the default AI",
              r["model"] == "setting-browser" and r["source"] == "browser_default",
              r["model"])

        # Agent and browser default silent: step 3 wins.
        s.write(browser_ai_model="", default_model="setting-global")
        r = config.resolve_browser_ai({"browser_ai_model": ""})
        check("step 3 — the AI the user already uses everywhere else",
              r["model"] == "setting-global" and r["source"] == "global_default",
              r["model"])

        # Nothing configured anywhere: step 4.
        s.write(browser_ai_model="", default_model="")
        r = config.resolve_browser_ai({"browser_ai_model": ""})
        check("step 4 — last resort, and it is flagged as unconfigured",
              r["model"] == last and r["source"] == "last_resort"
              and r["is_configured"] is False, r["model"])

        check("the last resort is not the dead Ollama model",
              last != "qwen:latest", last)

        print("\n=== 2. empty means NOT SET, at every step ===")

        s.write(browser_ai_model="setting-browser", default_model="setting-global")
        for label, stored in [("empty string", ""), ("whitespace", "   "),
                              ("None", None), ("missing key", "__ABSENT__")]:
            agent = {} if stored == "__ABSENT__" else {"browser_ai_model": stored}
            r = config.resolve_browser_ai(agent)
            check(f"agent stores {label} -> falls through, does not block",
                  r["model"] == "setting-browser" and r["agent_model"] == "",
                  r["model"])

        # The step-2 setting must fall through the same way, or "unset" would
        # mean two different things depending on where it was unset.
        s.write(browser_ai_model="   ", default_model="setting-global")
        r = config.resolve_browser_ai(None)
        check("blank browser_ai_model setting -> falls through to default_model",
              r["model"] == "setting-global", r["model"])

        s.write(default_model="setting-global")   # browser_ai_model key absent
        r = config.resolve_browser_ai(None)
        check("missing browser_ai_model key -> falls through to default_model",
              r["model"] == "setting-global", r["model"])

        s.remove()
        r = config.resolve_browser_ai(None)
        check("no settings file at all -> last resort, not a crash",
              r["model"] == last and r["source"] == "last_resort", r["model"])

        with open(s.path, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        r = config.resolve_browser_ai({"browser_ai_model": "agent-pick"})
        check("corrupt settings file -> the agent's own pick still works",
              r["model"] == "agent-pick", r["model"])

        print("\n=== 3. a value the agent was born with is not a choice ===")

        s.write(browser_ai_model="", default_model="setting-global")
        r = config.resolve_browser_ai({"browser_ai_model": "qwen:latest"})
        check("stored qwen:latest defers to a real setting",
              r["model"] == "setting-global"
              and r["ignored_legacy_model"] == "qwen:latest", r["model"])

        s.write(browser_ai_model="", default_model="")
        r = config.resolve_browser_ai({"browser_ai_model": "qwen:latest"})
        check("...but is honoured when there is nothing to defer to",
              r["model"] == "qwen:latest" and r["source"] == "agent", r["model"])

        s.write(browser_ai_model="qwen:latest", default_model="setting-global")
        r = config.resolve_browser_ai(None)
        check("qwen:latest chosen AS THE SETTING is a real choice and wins",
              r["model"] == "qwen:latest" and r["source"] == "browser_default",
              r["model"])

        print("\n=== 4. every caller's shape reaches the same chain ===")

        s.write(browser_ai_model="setting-browser", default_model="setting-global")
        check("Agent object (the scheduler)",
              config.resolve_browser_ai(FakeAgent("agent-pick"))["model"] == "agent-pick")
        check("Agent object with an empty field falls through",
              config.resolve_browser_ai(FakeAgent(""))["model"] == "setting-browser")
        check("plain dict (the brain, the run log)",
              config.resolve_browser_ai({"browser_ai_model": "agent-pick"})["model"]
              == "agent-pick")
        check("bare string (a node config, an argv value)",
              config.resolve_browser_ai("argv-pick")["model"] == "argv-pick")
        check("empty string argument (the browser launcher passed nothing)",
              config.resolve_browser_ai("")["model"] == "setting-browser")
        check("None (the settings page previewing its own fallback)",
              config.resolve_browser_ai(None)["model"] == "setting-browser")
        check("resolve_browser_ai_model() is the same answer, name only",
              config.resolve_browser_ai_model(FakeAgent("agent-pick")) == "agent-pick")

        print("\n=== 5. the answer explains itself ===")

        s.write(browser_ai_model="", default_model="setting-global")
        r = config.resolve_browser_ai(None)
        for key in ("model", "source", "is_configured", "agent_model",
                    "browser_default", "global_default", "last_resort",
                    "ignored_legacy_model"):
            check(f"payload carries '{key}' for the UI", key in r)
        check("every step's raw value is reported, not just the winner",
              r["agent_model"] == "" and r["browser_default"] == ""
              and r["global_default"] == "setting-global"
              and r["last_resort"] == last)
        check("the resolved model is never empty — a blank box is the bug",
              bool(config.resolve_browser_ai(None)["model"]))

        print("\n=== 6. no agent is born holding a model ===")

        from tubecli.core.agent import Agent
        born = Agent(name="fresh")
        check("a new Agent's browser_ai_model is empty, not qwen:latest",
              born.browser_ai_model == "", repr(born.browser_ai_model))
        check("to_dict() reports it empty rather than inventing a literal",
              born.to_dict()["browser_ai_model"] == "",
              repr(born.to_dict()["browser_ai_model"]))
        s.write(browser_ai_model="", default_model="setting-global")
        check("so a fresh agent resolves to the user's default AI",
              config.resolve_browser_ai(born)["model"] == "setting-global")

    finally:
        s.restore()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
