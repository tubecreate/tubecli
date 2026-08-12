"""A system prompt the user wrote must come back exactly as they wrote it.

Run:  python tests/agent_prompt_test.py     (exit 0 = pass)

The "Generate Agent with AI" dialog now has an optional System Prompt field.
Empty means "AI, write one". Filled means "use mine" — and that promise is the
thing worth proving, because it passes through a language model on the way.

The prompt sent to the model says "copy it into the system_prompt field exactly
as written, changing nothing". That is an instruction, not a mechanism. Models
paraphrase it, translate it, wrap it in a preamble, summarise it to one line,
or drop the field entirely — none of which raises an error, and all of which
would hand the user back an agent that does not follow the instructions they
typed. So the value is RESTORED after parsing rather than trusted.

Every case below runs generate_agent_json() for real with the network call
stubbed to return a specific kind of mangling. No regex over the source: a
check that the restore line exists says nothing about whether it runs on the
path that matters.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.core import ai_generator  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


USER_PROMPT = """You are VietLaw Business Advisor.
Answer only on Vietnamese corporate law. Cite the article number when you can.
Never guess at a figure — say you do not know."""

BASE = {
    "name": "VietLaw",
    "description": "Legal advisor",
    "persona": {"traits": ["precise"], "interests": ["Commercial Law"]},
    "routine": {"dailyRoutine": {}, "workHabits": {"focusAreas": ["Corporate Law"]}},
}


def run(model_reply: dict, system_prompt: str = USER_PROMPT):
    """Call the generator with the provider call stubbed to a fixed reply."""
    captured = {}

    def fake_ollama(model, prompt):
        captured["prompt"] = prompt
        return json.dumps(model_reply, ensure_ascii=False)

    original = ai_generator.call_ollama
    ai_generator.call_ollama = fake_ollama
    try:
        data = ai_generator.generate_agent_json(
            name="VietLaw", description="Legal advisor",
            provider="ollama", model="qwen:latest",
            system_prompt=system_prompt,
        )
    finally:
        ai_generator.call_ollama = original
    return data, captured.get("prompt", "")


print("=" * 70)
print("AGENT SYSTEM PROMPT")
print("=" * 70)

# ── the model behaves ──────────────────────────────────────────────────────
good = dict(BASE, system_prompt=USER_PROMPT)
data, sent = run(good)
check("obedient model: prompt preserved", data["system_prompt"] == USER_PROMPT,
      repr(data.get("system_prompt"))[:120])
check("obedient model: persona still returned", data["persona"]["interests"] == ["Commercial Law"],
      data.get("persona"))

# ── the four ways a model mangles it ───────────────────────────────────────
manglings = {
    "paraphrased": "You are a Vietnamese corporate law advisor who cites articles.",
    "preambled": "Sure! Here is the system prompt:\n\n" + USER_PROMPT,
    "truncated": USER_PROMPT.split("\n")[0],
    "translated": "Bạn là VietLaw Business Advisor. Chỉ trả lời về luật doanh nghiệp.",
    "emptied": "",
}
for label, mangled in manglings.items():
    data, _ = run(dict(BASE, system_prompt=mangled))
    check(f"{label} reply is corrected", data["system_prompt"] == USER_PROMPT,
          f"kept the model's version: {data.get('system_prompt')!r}"[:140])

# The field missing entirely — the most common failure for a small model given
# a long schema, and the one a "did it change the value" check would miss.
data, _ = run(dict(BASE))
check("dropped field is restored", data.get("system_prompt") == USER_PROMPT,
      repr(data.get("system_prompt"))[:120])

# ── the model's own prompt is left alone when the user wrote nothing ───────
written = dict(BASE, system_prompt="You are a careful legal research assistant.")
data, sent = run(written, system_prompt="")
check("no user prompt: the model's own is kept",
      data["system_prompt"] == "You are a careful legal research assistant.",
      data.get("system_prompt"))
check("no user prompt: no 'already written' block is sent",
      "ALREADY WRITTEN" not in sent,
      "an empty instruction block invites the model to fill the gap")

data, sent = run(written, system_prompt="   \n\t ")
check("whitespace-only counts as no prompt",
      data["system_prompt"] == "You are a careful legal research assistant.",
      "a blank string overwrote a real prompt")

# ── what the model is actually told ────────────────────────────────────────
_, sent = run(good)
check("the user's text reaches the model", USER_PROMPT in sent, "not included in the prompt")
check("the model is told to derive the persona from it",
      "Derive the traits" in sent or "derive the traits" in sent.lower(),
      "persona can end up describing a different agent than the instructions do")
check("the schema still asks for system_prompt", '"system_prompt"' in sent, "key not in schema")

# Surrounding whitespace is trimmed, not carried into the stored value.
padded = "\n\n  " + USER_PROMPT + "  \n\n"
data, _ = run(dict(BASE), system_prompt=padded)
check("surrounding whitespace is trimmed", data["system_prompt"] == USER_PROMPT,
      repr(data.get("system_prompt"))[:80])

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
