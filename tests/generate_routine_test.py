"""Persona-derived per-period BEHAVIOR routine generation.

Run:  python tests/generate_routine_test.py     (exit 0 = pass)

The Schedule tab's 7 behavior chips per period STAY exactly as they are and stay
manually editable. What is new: when an agent is created (and on demand via the
"Sinh theo vai trò" button) the appropriate behaviors per period are PRE-SELECTED
from the agent's own persona instead of a blank identical default — a teacher
should study/browse curricula, not "check email every morning".

The behaviors are a FIXED set of 7 keys the scheduler understands
(browse_topic, news, watch_video, study, check_email, reply_email, send_report).
Generation must only ever pick a subset of THOSE keys — never invent new ones.

What this harness proves (offline, no network — _call_llm is monkeypatched):
  * a well-formed LLM reply parses into {period: {validKey: True}} with ONLY the
    7 keys and ONLY the enabled ones;
  * a reply padded with junk keys is sanitized down to just the valid keys;
  * "false" values (incl. the string "false") do not enable a behavior;
  * a malformed reply, and a reply that RAISES, both yield the generic fallback
    routine — never a crash, never garbage stored;
  * the create-time seed hook STORES the routine into persona.dailyRoutine and
    does not raise even when the LLM throws.

What this CANNOT prove — and is left to the builder's honesty report — is the
QUALITY of the LLM's role reasoning (does a real teacher truly get study+browse
and not an email desk). That is LLM-dependent; here the reply is a fixture. Only
the validation, the fallback, the create-stays-robust guarantee, and the wiring
are asserted.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tubecli.core.brain import AgentBrain  # noqa: E402
from tubecli.core.agent import Agent, agent_manager  # noqa: E402
from tubecli.api import server  # noqa: E402
from tubecli.api.server import (  # noqa: E402
    BEHAVIOR_MEANINGS,
    EXPLICIT_BEHAVIOR_MAP,
    PERIODS,
    generate_daily_routine,
    _sanitize_daily_routine,
    _default_daily_routine,
    _seed_agent_routine,
)

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("PERSONA-DERIVED PER-PERIOD ROUTINE GENERATION")
print("=" * 70)

# The 7 valid keys must be exactly the scheduler's EXPLICIT_BEHAVIOR_MAP keys —
# one source of truth, so generation can never drift from what runs.
VALID = set(EXPLICIT_BEHAVIOR_MAP.keys())
check("the 7 valid keys match the scheduler's behavior map",
      set(BEHAVIOR_MEANINGS.keys()) == VALID and len(VALID) == 7, sorted(VALID))
check("periods are the four expected",
      tuple(PERIODS) == ("morning", "afternoon", "evening", "night"), PERIODS)


# ── LLM monkeypatch: a mutable fixture we flip per case ─────────────────────
_reply = {"text": "{}", "fail": False}


def fake_llm(agent, messages, temperature=0.7):
    if _reply.get("fail"):
        raise RuntimeError("simulated LLM outage")
    return _reply["text"]


_orig_call_llm = AgentBrain._call_llm
AgentBrain._call_llm = staticmethod(fake_llm)


def make_agent(name="Teacher Bot", description="A high-school teacher agent"):
    return Agent(name=name, description=description,
                 persona={"interests": ["curriculum", "pedagogy"]})


try:
    # ── 1. well-formed reply -> only valid, only enabled keys ───────────────
    well_formed = {
        "morning": {"study": True, "browse_topic": True, "check_email": False},
        "afternoon": {"study": True, "news": False},
        "evening": {"watch_video": True},
        "night": {"study": True},
    }
    _reply.update(text=json.dumps(well_formed), fail=False)
    r = generate_daily_routine(make_agent())

    check("result has exactly the 4 periods", set(r.keys()) == set(PERIODS), list(r.keys()))
    all_keys = {k for period in r.values() for k in period.keys()}
    check("every key produced is one of the 7 valid keys",
          all_keys.issubset(VALID), sorted(all_keys - VALID))
    check("only ENABLED behaviors are stored (false ones dropped)",
          r["morning"] == {"study": True, "browse_topic": True}, r["morning"])
    check("a period keeps only its enabled key",
          r["afternoon"] == {"study": True}, r["afternoon"])
    check("every stored value is boolean True",
          all(v is True for period in r.values() for v in period.values()), r)

    # ── 2. junk keys are sanitized OUT, valid keys survive ──────────────────
    junk = {
        "morning": {"study": True, "fly_to_moon": True, "delete_all": True},
        "afternoon": {"news": True, "": True, "browse_topic": "yes"},
        "evening": {"watch_video": 1},
        "night": {"nonsense": True},
    }
    _reply.update(text=json.dumps(junk), fail=False)
    r2 = generate_daily_routine(make_agent())
    r2_keys = {k for period in r2.values() for k in period.keys()}
    check("junk/hallucinated keys never reach the routine",
          r2_keys.issubset(VALID), sorted(r2_keys - VALID))
    check("valid key beside junk survives", r2["morning"] == {"study": True}, r2["morning"])
    check("truthy non-bool ('yes', 1) still enables a valid key",
          r2["afternoon"] == {"news": True, "browse_topic": True}
          and r2["evening"] == {"watch_video": True},
          (r2["afternoon"], r2["evening"]))
    check("a period of pure junk collapses to empty (scheduler will random-fill)",
          r2["night"] == {}, r2["night"])

    # ── 3. the string "false" must NOT enable a behavior ────────────────────
    stringy = {"morning": {"study": "false", "news": "true"},
               "afternoon": {}, "evening": {}, "night": {}}
    _reply.update(text=json.dumps(stringy), fail=False)
    r3 = generate_daily_routine(make_agent())
    check('string "false" does not enable; string "true" does',
          r3["morning"] == {"news": True}, r3["morning"])

    # ── 4a. malformed reply (not JSON) -> fallback, no crash ────────────────
    _reply.update(text="I am not JSON at all, sorry!", fail=False)
    r4 = generate_daily_routine(make_agent())
    check("malformed non-JSON reply yields the generic fallback",
          r4 == _default_daily_routine(), r4)

    # ── 4b. reply that is valid JSON but ALL keys junk/false -> fallback ────
    _reply.update(text=json.dumps({"morning": {"junk": True}, "afternoon": {},
                                   "evening": {}, "night": {"x": False}}), fail=False)
    r5 = generate_daily_routine(make_agent())
    check("a reply with zero usable behaviors falls back to default",
          r5 == _default_daily_routine(), r5)

    # ── 4c. the LLM itself RAISES -> fallback, still no crash ───────────────
    _reply.update(text="", fail=True)
    r6 = generate_daily_routine(make_agent())
    check("an LLM exception yields the fallback, not a crash",
          r6 == _default_daily_routine(), r6)

    # fallback is a fresh copy each call (not a shared mutable) ---------------
    a, b = _default_daily_routine(), _default_daily_routine()
    a["morning"]["news"] = "MUTATED"
    check("each fallback is an independent copy", b["morning"]["news"] is True, b["morning"])

    # ── 5. the CREATE seed hook: stores routine, never raises on LLM error ──
    # Redirect the singleton to a throwaway file so the real agents store is
    # untouched, then drive the exact function the create endpoint threads.
    tmp = Path(tempfile.mkdtemp()) / "agents_test.json"
    _orig_file, _orig_agents = agent_manager.agents_file, agent_manager.agents
    agent_manager.agents_file = tmp
    agent_manager.agents = {}
    try:
        created = agent_manager.create(name="Sales Manager",
                                       description="Runs the sales desk",
                                       persona={"interests": ["pipeline"]})
        # 5a. happy path: a well-formed reply is stored under persona.dailyRoutine
        _reply.update(text=json.dumps(well_formed), fail=False)
        seeded = _seed_agent_routine(created.id)
        stored = (agent_manager.get(created.id).persona or {}).get("dailyRoutine")
        check("seed returns the routine it stored", seeded == stored and seeded is not None,
              (seeded, stored))
        seed_keys = {k for period in (stored or {}).values() for k in period.keys()}
        check("seeded routine holds only valid keys", seed_keys.issubset(VALID),
              sorted(seed_keys - VALID))

        # 5b. LLM throws -> seed must NOT raise and must still store the fallback
        created2 = agent_manager.create(name="Broken LLM Agent", description="x")
        _reply.update(text="", fail=True)
        raised = False
        try:
            seeded2 = _seed_agent_routine(created2.id)
        except Exception as e:  # the whole point: this must never happen
            raised = True
            seeded2 = None
            failures.append(f"seed raised on LLM error: {e}")
        stored2 = (agent_manager.get(created2.id).persona or {}).get("dailyRoutine")
        check("create seed does not raise when the LLM throws", not raised)
        check("create seed stores the fallback routine on LLM failure",
              seeded2 == _default_daily_routine() and stored2 == _default_daily_routine(),
              (seeded2, stored2))

        # 5c. a missing agent id is handled quietly (returns None, no raise)
        check("seeding an unknown agent id returns None without raising",
              _seed_agent_routine("does-not-exist") is None)
    finally:
        agent_manager.agents_file, agent_manager.agents = _orig_file, _orig_agents

    # ── _sanitize_daily_routine direct edge cases ───────────────────────────
    check("sanitize rejects a non-dict (returns None -> caller defaults)",
          _sanitize_daily_routine(["not", "a", "dict"]) is None)
    check("sanitize of an empty dict returns None",
          _sanitize_daily_routine({}) is None)
    ok = _sanitize_daily_routine({"morning": {"study": True}})
    check("sanitize fills all 4 periods even if reply gave one",
          set(ok.keys()) == set(PERIODS) and ok["morning"] == {"study": True}, ok)

finally:
    AgentBrain._call_llm = staticmethod(_orig_call_llm)

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
