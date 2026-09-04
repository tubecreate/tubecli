"""Per-period scheduled BEHAVIOR resolution + email action prompts.

Run:  python tests/schedule_behavior_test.py     (exit 0 = pass)

The Schedule tab now writes explicit behavior keys per agent, per period:
dailyRoutine[period] = {browse_topic|news|watch_video|study|check_email|
reply_email|send_report: true}. The scheduler must:

  * map those EXPLICIT keys straight to an internal behavior (robust, not
    guessing at free text), while still fuzzy-mapping old free-text labels so
    pre-UI configs keep working;
  * turn reply_email / send_report into a single natural-language gmail
    instruction for open.js (behaviors are prompts — no new skill);
  * NEVER email nobody: a send_report with no recipients is skipped, honestly.

These are the pure resolver + prompt helpers the scheduler callback itself now
calls (single source of truth), so proving them proves the live path. What can
NOT be proven in a harness — that gmail actually accepts the click/type/send —
is called out in the builder's report, not faked here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tubecli.api.server import (  # noqa: E402
    resolve_task_behavior,
    select_period_behavior,
    normalize_report_recipients,
    build_email_prompt,
    FALLBACK_BEHAVIORS,
)

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("SCHEDULE PER-PERIOD BEHAVIOR + EMAIL PROMPTS")
print("=" * 70)

# ── explicit keys map to the right internal behavior ───────────────────────
EXPECTED = {
    "browse_topic": "work",
    "news": "morningCheck",
    "watch_video": "watchVideos",
    "study": "study",
    "check_email": "checkEmails",
    "reply_email": "replyEmail",
    "send_report": "sendReport",
}
for key, want in EXPECTED.items():
    got = resolve_task_behavior(key)
    check(f"explicit key '{key}' -> {want}", got == want, f"got {got!r}")

# Case-insensitive explicit match still counts as explicit.
check("explicit key is case-insensitive",
      resolve_task_behavior("Send_Report") == "sendReport",
      resolve_task_behavior("Send_Report"))

# ── explicit keys WIN over what fuzzy text would have done ──────────────────
# 'reply_email' as free text contains 'email' -> the old fuzzy path returns
# 'checkEmails' (READ ONLY). The explicit key must instead give 'replyEmail'
# (which actually replies). This is the sharpest proof explicit wins.
check("explicit reply_email beats fuzzy 'checkEmails'",
      resolve_task_behavior("reply_email") == "replyEmail",
      "explicit key did not win over the email->checkEmails fuzzy rule")
# And the fuzzy fallback itself is still alive for genuine free text.
check("free text 'check the morning email' fuzzy-maps to checkEmails",
      resolve_task_behavior("check the morning email") == "checkEmails",
      resolve_task_behavior("check the morning email"))
check("free text 'read the news' fuzzy-maps to morningCheck",
      resolve_task_behavior("read the news") == "morningCheck",
      resolve_task_behavior("read the news"))
# 'send_report' as free text has no fuzzy keyword -> would default to 'work';
# the explicit key rescues it to 'sendReport'.
check("explicit send_report beats fuzzy default 'work'",
      resolve_task_behavior("send_report") == "sendReport" != "work",
      resolve_task_behavior("send_report"))

# ── period selection: a fake agent with check_email in the morning ─────────
daily_routine = {"morning": {"check_email": True}}
behavior, period_tasks, chosen = select_period_behavior(daily_routine, "morning")
check("morning check_email resolves to checkEmails",
      behavior == "checkEmails", behavior)
check("chosen task is reported back", chosen == "check_email", chosen)
check("period_tasks handed back for the run context",
      period_tasks == {"check_email": True}, period_tasks)
# check_email vẫn phải là ĐỌC-THÔI. Trước đây build_email_prompt trả (None, None)
# và để caller tự lo; nay nó trả một câu lệnh script để đỡ tốn quota AI. Điều
# PHẢI giữ không phải con số None, mà là: không soạn, không trả lời, không gửi.
read_prompt, read_skip = build_email_prompt("checkEmails", "morning", ["AI"], [])
check("check_email vẫn ra câu lệnh, không bị bỏ qua",
      isinstance(read_prompt, str) and read_prompt and read_skip is None, (read_prompt, read_skip))
_low = (read_prompt or "").lower()
check("check_email KHÔNG phải luồng soạn/gửi thư",
      not any(w in _low for w in ("compose", "reply", "send", "click send", "write")), read_prompt)
# Câu lệnh phải đúng dạng "..., then ..." để open.js bắt được fast-path
# [navigate, read_gmail] — sai dạng là rơi về vòng AI lái từng bước, tốn quota
# đúng bằng thứ nhánh này sinh ra để tránh.
check("đúng dạng script fast-path (navigate + read gmail)",
      "navigate" in _low and "then" in _low and "read gmail" in _low, read_prompt)

# Disabled task in the period -> falls back to random (not the disabled task).
b2, _, chosen2 = select_period_behavior({"morning": {"check_email": False}}, "morning")
check("a disabled task is not selected",
      chosen2 is None and b2 in FALLBACK_BEHAVIORS, (b2, chosen2))

# A period may hold several behaviors; one enabled key is picked each run.
multi = {"evening": {"watch_video": True, "study": True}}
seen = {select_period_behavior(multi, "evening")[0] for _ in range(40)}
check("multiple enabled behaviors are all reachable",
      seen == {"watchVideos", "study"}, seen)

# ── empty dailyRoutine -> the OLD random fallback still works ───────────────
for shape in ({}, {"morning": {}}, {"afternoon": {"x": False}}, None, []):
    b, _, ch = select_period_behavior(shape, "morning")
    check(f"empty routine {shape!r} uses random fallback",
          ch is None and b in FALLBACK_BEHAVIORS, (b, ch))

# ── reply_email prompt: open gmail, read newest UNREAD, reply, send ────────
rp, rskip = build_email_prompt("replyEmail", "morning", ["market research"], [])
check("reply_email produces a prompt (no skip)", rp is not None and rskip is None, (rp, rskip))
low = rp.lower()
check("reply prompt goes to gmail", "gmail.com" in low, rp)
check("reply prompt reads the newest unread", "unread" in low and "read" in low, rp)
check("reply prompt composes a reply and sends",
      "reply" in low and "send" in low, rp)
check("reply prompt is on-topic (uses the agent's interests)",
      "market research" in low, rp)
check("reply prompt does nothing when inbox has no unread (never invents mail)",
      "no unread" in low, rp)
check("reply prompt says no attachment (body text only)", "attachment" in low, rp)

# ── send_report WITH recipients: names them, sends a summary email ──────────
recips = ["alice@team.co", "bob@team.co"]
sp, sskip = build_email_prompt("sendReport", "afternoon", ["sales", "growth"], recips)
check("send_report with recipients produces a prompt (no skip)",
      sp is not None and sskip is None, (sp, sskip))
slow = sp.lower()
check("send_report composes a new email", "compose" in slow, sp)
check("send_report names ALL recipients in To",
      "alice@team.co" in sp and "bob@team.co" in sp, sp)
check("send_report has a subject and body", "subject" in slow and "body" in slow, sp)
check("send_report summary names the period", "afternoon" in slow, sp)
check("send_report summary names the topics collected",
      "sales" in slow and "growth" in slow, sp)
check("send_report sends", "send" in slow, sp)
check("send_report says no attachment (summary in body)", "attachment" in slow, sp)

# ── send_report with NO recipients -> SKIPPED, no prompt, honest reason ─────
np, nskip = build_email_prompt("sendReport", "afternoon", ["sales"], [])
check("send_report with no recipients yields NO prompt", np is None, np)
check("send_report with no recipients is skipped with a reason",
      isinstance(nskip, str) and nskip, nskip)
check("skip reason is honest about missing recipients",
      "recipient" in nskip.lower() and "skip" in nskip.lower(), nskip)
# whitespace-only recipients are treated as none, too.
np2, nskip2 = build_email_prompt("sendReport", "night", [], ["   ", ""])
check("blank recipients count as none -> skipped", np2 is None and nskip2, (np2, nskip2))

# ── recipient normalization: routine is home, persona is fallback ──────────
check("routine.reportRecipients is the home of record",
      normalize_report_recipients({"reportRecipients": ["a@x.co"]},
                                  {"reportRecipients": ["ignored@x.co"]}) == ["a@x.co"],
      "persona overrode routine")
check("persona.reportRecipients is the fallback when routine has none",
      normalize_report_recipients({}, {"reportRecipients": ["p@x.co"]}) == ["p@x.co"])
check("comma/semicolon string is parsed and trimmed",
      normalize_report_recipients({"reportRecipients": " a@x.co , b@x.co ; c@x.co "}, {})
      == ["a@x.co", "b@x.co", "c@x.co"])
check("no recipients anywhere -> empty list",
      normalize_report_recipients({}, {}) == [])

# The recipients build_email_prompt consumes come from this same normalizer,
# so a routine-configured report reaches the To line end to end.
routine = {"reportRecipients": "lead@team.co; peer@team.co"}
persona = {}
e2e_recips = normalize_report_recipients(routine, persona)
e2e_prompt, _ = build_email_prompt("sendReport", "morning", ["ops"], e2e_recips)
check("end to end: routine recipients reach the send_report To line",
      "lead@team.co" in e2e_prompt and "peer@team.co" in e2e_prompt, e2e_prompt)

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
