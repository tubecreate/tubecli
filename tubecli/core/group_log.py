"""Group activity log — what the agents inside one Flow group just did.

WHY THIS EXISTS
    A Flow group already decides what an agent may touch (group_context) and
    already records finished work into the owner's worklog SHEET. Neither
    answers the question the canvas asks: "what is happening right now?".
    The owner drops a Browser node and a Script node into a group, tells the
    agent to go, and then watches a chat bubble that says nothing until the
    whole turn is over — a refused action, a script that stopped on step 4, a
    Sheet append that went to the wrong tab all look identical from outside.

    This module is the ticker behind the log panel on the canvas: one line per
    thing an agent did, per group, read back by sequence number so the panel
    can poll for "anything after N?" instead of re-downloading the file.

    It is deliberately modelled on run_log.py — same jsonl-with-a-lock shape,
    same torn-tail repair, same "never raise into the caller" rule, and the
    same redactor. A logger that can break the action it is logging is worse
    than no logger at all.

WHAT MAKES IT DIFFERENT FROM run_log
    run_log is the OWNER's forensic record of scheduled browser runs, read on
    a dashboard page. This one is shown live, beside the canvas, and it is fed
    by handler replies that were written for an AI model, not for a log panel.
    Those replies are far more likely to carry things that must not be kept:
    a spreadsheet id, a Google credential id, the absolute path of a browser
    profile (which spells out the server's home directory), and script
    variables — the exact place a password leaked once already. So on top of
    run_log.redact() there is _scrub(), and titles are built from an ALLOWLIST
    of action fields rather than from whatever the model happened to send.

SEQUENCE NUMBERS
    seq is per group and strictly increasing, never reused — including across
    a trim, so a client that asks "give me everything after 1840" keeps
    working after the file has been rewritten. The last value is read off disk
    once per group per process and then kept in memory.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GroupLog")

# Lines kept per group. Above this the file is rewritten holding the newer
# half — a VPS running a busy group for a month must not grow a log file the
# panel then has to parse on every poll.
MAX_LINES = 2000
# How much of a handler's reply is kept as the expandable detail.
DETAIL_CAP = 400
# The one-line summary shown on the row itself.
TITLE_CAP = 200
# Ceiling on ?limit= — a poll asking for everything must not be able to make
# the server serialise the whole file into one response.
READ_LIMIT_MAX = 500

# One re-entrant lock for every writer, like run_log. Three kinds of thread
# reach this module: the FastAPI threadpool (chat turns), the scheduler
# thread, and the daemon threads extension handlers spawn.
_LOCK = threading.RLock()
# group_id -> last seq written, and group_id -> lines currently in the file.
# Both are filled by the same one-off scan the first time a group is touched.
_seq: Dict[str, int] = {}
_lines: Dict[str, int] = {}


# ── Redaction ────────────────────────────────────────────────────────
#
# run_log.redact() strips secrets off a COMMAND LINE. Everything below strips
# what a handler REPLY carries, which is a different set of leaks.

# https://docs.google.com/spreadsheets/d/<id>/edit — the id is the sheet's
# capability: anyone holding it plus the owner's Google session can open it.
_SHEET_URL_RE = re.compile(r"(/spreadsheets/d/)[A-Za-z0-9_-]+")
# cred_1a2b3c4d / tok_xxxx as they appear in auth_manager's own messages.
_CRED_ID_RE = re.compile(r"\b(?:cred|tok|token)_[A-Za-z0-9_-]{3,}", re.IGNORECASE)
# ...and the same ids when they are named by a key instead of by prefix.
# ONE name list, BOTH separators. These two rules used to split the work the
# wrong way round: this one knew `:` but only the id names, while _SECRET_KV_RE
# below knew the secret names but demanded an `=`. So `{"password": "…"}`
# matched neither and reached disk verbatim — and a handler reply is JSON far
# more often than it is `k = v`: GET /api/v1/browser/profiles/<name> answers
# with the profile dict, google_account (password, recovery address, 2FA codes)
# included, and run_api hands that straight to the logger as `detail`.
# `\w{0,24}` on both sides of the name catches login_password, twoFactorCodes
# and recoveryEmail. It is BOUNDED rather than `\w*` on purpose: an unbounded
# prefix makes this a quadratic walk over the 8 KB window below.
_ID_FIELD_RE = re.compile(
    r"([\"']?\b\w{0,24}(?:sheet_id|spreadsheet_id|cred_id|credential_id|token_id|"
    r"access_token|refresh_token|api[_-]?key|apikey|token|password|passwd|pwd|"
    r"secret|otp|cookie|recovery|two[_-]?factor|2fa|totp|mat_?khau)\w{0,24}\b[\"']?\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|\[[^\]\r\n]*\]|[^\s,;}\)]+)", re.IGNORECASE)
# An HTTP auth header carries the whole credential behind a scheme word, with
# no field name any rule above would recognise ("Authorization: Bearer ya29.…").
_AUTH_HEADER_RE = re.compile(r"\b((?:Bearer|Basic)[ \t]+)[A-Za-z0-9._~+/=-]{8,}",
                             re.IGNORECASE)
# Script output variables come back as `name = value` lines (group_scripts.
# summarise_output). A run that echoes back what it typed into a login form
# would otherwise put the password on the canvas.
# `.*?` (non-greedy) on purpose: it anchors on the FIRST secret-looking name
# on the line and `(.+)$` then swallows the whole rest of it. Redacting too
# much of a log row costs nothing; redacting too little is the bug.
_SECRET_KV_RE = re.compile(
    r"(?im)^(.*?\b(?:password|passwd|pwd|secret|token|otp|cookie|"
    r"api[_-]?key|mat_?khau)[^\n=]*=\s*)(.+)$")
# The absolute path of a browser profile names the server's user account and
# home directory. The tail (browser_profiles/<name>/…) is what the owner
# actually wants to read, so only the prefix is cut.
# The body has to be allowed to contain SPACES. On Windows the drive letter is
# the only anchor there is, so excluding whitespace meant `C:\Users\John Doe\…
# \browser_profiles\` did not match AT ALL and the whole path — account name
# and layout included — was stored. Bounded to 400 characters so a long line of
# slashes cannot turn this into a quadratic scan.
_PROFILE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/)[^\r\n\"']{0,400}?[\\/](browser_profiles[\\/])")

_SCRUB_RULES = (
    (_SHEET_URL_RE, r"\1***"),
    (_ID_FIELD_RE, r"\1***"),
    (_AUTH_HEADER_RE, r"\1***"),
    (_CRED_ID_RE, "***"),
    (_SECRET_KV_RE, r"\1***"),
    (_PROFILE_PATH_RE, r"…/\1"),
)

WITHHELD = "(redaction failed — content withheld)"

# How much of the input the patterns are allowed to see, over and above what
# will be kept. The input is a handler REPLY — including replies from
# extensions installed off the market, so its length is not ours to assume —
# and _SECRET_KV_RE walks a line character by character looking for a secret
# name: one 200 KB line densely packed with the word "token" costs ~10s of CPU,
# on the event loop, for 400 characters of output. Slicing first cannot change
# what is stored: a rule can only affect the kept prefix if it MATCHES inside
# it, and every rule here matches within its own line, so a margin this many
# times the cap leaves each of them far more context than it can use.
_SCRUB_WINDOW = 8000


def scrub(value: Any, cap: int = DETAIL_CAP) -> str:
    """Everything stored here goes through this. Fails CLOSED.

    If the redactor cannot run at all, the text is dropped rather than kept:
    this file is served to a browser panel, so "we could not check it" must
    never mean "we stored it anyway".
    """
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return ""
    if not text.strip():
        return ""
    # cap=0 means "keep everything", so there is no prefix to protect and no
    # window to slice to — that caller asked for the whole thing.
    keep = max(0, int(cap)) if cap else 0
    window = max(_SCRUB_WINDOW, keep * 4)
    if keep and len(text) > window:
        text = text[:window]
    try:
        from tubecli.core import run_log

        text = run_log.redact(text) or ""
    except Exception as e:
        logger.warning("group_log: redactor unavailable (%s)", e)
        return WITHHELD
    try:
        for pattern, repl in _SCRUB_RULES:
            text = pattern.sub(repl, text)
    except Exception as e:
        logger.warning("group_log: scrub failed (%s)", e)
        return WITHHELD
    text = text.strip()
    return text[:max(0, int(cap))] if cap else text


# ── Titles: an allowlist, not whatever the model sent ─────────────────
#
# action_data is written by the LLM and can hold anything — `variables`,
# `rows`, `values`, a pasted credential. Summarising by picking known-safe
# keys means a new leaky field cannot appear in the panel by accident; the
# worst a new action can do is show no summary at all.

# What the action acts ON, most specific first. `profile` is LAST on purpose:
# for browser_* it is the whole subject, but for script_run it is only where
# the work happened, and the script's name is what the reader is looking for.
_SUBJECT_KEYS = ("script", "sheet", "file", "folder", "alias", "name", "path", "profile")
# ...and where it points. Rendered after an arrow.
_TARGET_KEYS = ("url", "tab", "range", "query", "dest", "to")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def _one_line(value: Any, cap: int = 60) -> str:
    # None is nothing, not the four letters "None": str(None) once put
    # "gsheet_append KH @None" on a row for an action with no profile.
    if value is None or value == "":
        return ""
    try:
        text = " ".join(str(value).split())
    except Exception:
        return ""
    return text[:cap]


def _short_url(raw: Any) -> str:
    """host/path only. The query string is where one-time tokens live, and a
    scheme costs width the panel does not have."""
    text = _one_line(raw, 300)
    if not text:
        return ""
    text = _SCHEME_RE.sub("", text)
    text = text.split("?")[0].split("#")[0]
    return text.rstrip("/")[:120]


def _short_path(raw: Any) -> str:
    """A path is shown by its last component: the folders above it are the
    owner's directory layout, and the panel row has no room for them."""
    text = _one_line(raw, 300)
    if not text:
        return ""
    return os.path.basename(text.replace("\\", "/").rstrip("/"))[:80] or text[:80]


def summarise_action(action_type: str, action_data: Any) -> str:
    """`browser_open tuan5 → tiktok.com/upload` — the row's one line."""
    kind = _one_line(action_type, 60) or "action"
    data = action_data if isinstance(action_data, dict) else {}

    # `sheet` names opposite things in the two spreadsheet families: for
    # gsheet_* it is the SPREADSHEET (the subject, with `tab` as the target),
    # for xlsx_* it is a TAB inside the workbook that `path` names. One shared
    # order put "xlsx_append Data" on the row — the tab, and not a word about
    # which workbook was written to.
    if kind.startswith("xlsx"):
        subject_keys = tuple(k for k in _SUBJECT_KEYS if k != "sheet")
        target_keys = ("sheet",) + _TARGET_KEYS
    else:
        subject_keys, target_keys = _SUBJECT_KEYS, _TARGET_KEYS

    subject = ""
    picked = ""
    for key in subject_keys:
        raw = data.get(key)
        if raw in (None, "", [], {}):
            continue
        subject = _short_path(raw) if key in ("path", "folder") else _one_line(raw, 60)
        if subject:
            picked = key
            break

    # The same script run on five profiles is five different jobs, so when the
    # subject is not the profile itself, say which browser it happened in.
    profile = _one_line(data.get("profile"), 40)
    if profile and picked != "profile":
        subject = f"{subject} @{profile}" if subject else f"@{profile}"

    target = ""
    for key in target_keys:
        raw = data.get(key)
        if raw in (None, "", [], {}):
            continue
        target = _short_url(raw) if key in ("url", "dest", "to") else _one_line(raw, 60)
        if target:
            break

    title = kind
    if subject:
        title += f" {subject}"
    if target:
        title += f" → {target}"
    return scrub(title, TITLE_CAP)


# ── Storage ──────────────────────────────────────────────────────────

def _valid(group_id: Any) -> bool:
    """The id becomes a file name, so it is checked by the one authority on
    group ids. An import failure refuses — nothing is written."""
    try:
        from tubecli.core import group_context

        return bool(group_context.valid_group_id(group_id))
    except Exception as e:
        logger.warning("group_log: cannot validate group id (%s)", e)
        return False


def _dir() -> Path:
    # Imported late, exactly like run_log._dir, so a test that rebinds
    # tubecli.config.ext_data_path is honoured.
    from tubecli.config import ext_data_path

    return ext_data_path("group_logs")


def _file_for(group_id: str) -> Path:
    return _dir() / f"{group_id}.jsonl"


def _now() -> str:
    # Local naive ISO, like run_log: the panel compares it against the
    # viewer's own clock and renders HH:mm:ss.
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _load(path: Path) -> List[Dict[str, Any]]:
    """Every parseable line, oldest first. A torn line is skipped, never fatal."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("group_log: cannot read %s (%s)", path.name, e)
        return []
    out: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _prime(group_id: str, path: Path) -> None:
    """Learn this group's last seq and line count — once per process.

    Done by reading the file, which is bounded by MAX_LINES, and only on the
    first write/clear of a group in this process.
    """
    if group_id in _seq:
        return
    rows = _load(path)
    last = 0
    for row in reversed(rows):
        try:
            last = int(row.get("seq") or 0)
        except (TypeError, ValueError):
            last = 0
        if last:
            break
    _seq[group_id] = last
    _lines[group_id] = len(rows)


def _append_line(path: Path, row: Dict[str, Any]) -> None:
    """Append one line, repairing a torn tail first.

    If the process died mid-append the file can end without a newline;
    appending after that would fuse the survivor of the old line onto this
    one and corrupt two records instead of one.

    The last byte is probed in BINARY, never through the text decoder. Every
    line here is written with ensure_ascii=False and carries ✅/❌ and Vietnamese
    text, so a tail cut by a killed process very often ends in the MIDDLE of a
    multi-byte character — and reading one byte of that as strict utf-8 raises
    before the repair can write its newline. append() swallows the exception,
    so nothing is reported: the panel simply stops gaining lines, for that group,
    forever, because every later append hits the same undecodable tail. It also
    drops the read-write open ("a+") for a plain append plus a one-byte stat
    probe, which on some volumes is most of what a log line costs.
    """
    needs_nl = False
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size:
        try:
            with open(path, "rb") as probe:
                probe.seek(-1, os.SEEK_END)
                needs_nl = probe.read(1) != b"\n"
        except OSError as e:
            # Unreadable tail: assume torn. A spare blank line costs one
            # skipped record at read time; a fused one corrupts two.
            logger.warning("group_log: cannot probe tail of %s (%s)", path.name, e)
            needs_nl = True
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(("\n" if needs_nl else "") + json.dumps(row, ensure_ascii=False) + "\n")


def _trim(group_id: str, path: Path) -> None:
    """Over MAX_LINES: rewrite holding the newer half. seq keeps counting, so
    a client polling with since= is unaffected by the rewrite."""
    if _lines.get(group_id, 0) <= MAX_LINES:
        return
    rows = _load(path)
    keep = rows[-(MAX_LINES // 2):] if len(rows) > MAX_LINES // 2 else rows
    tmp = path.with_suffix(".jsonl.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for row in keep:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(str(tmp), str(path))
        _lines[group_id] = len(keep)
    except Exception as e:
        # A failed trim leaves the full file in place — oversized but intact,
        # which is the right way round.
        logger.warning("group_log: trim failed for %s (%s)", group_id, e)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def append(group_id: str, agent_id: str, agent_name: str, kind: str, title: str,
           detail: str = "", ok: bool = True, extra: Optional[Dict[str, Any]] = None) -> None:
    """One line on one group's log. Best effort — never raises into a caller."""
    try:
        if not _valid(group_id):
            return
        row: Dict[str, Any] = {
            "seq": 0,
            "at": _now(),
            "agent_id": _one_line(agent_id, 80),
            "agent": _one_line(agent_name, 80) or _one_line(agent_id, 80),
            "kind": _one_line(kind, 40) or "action",
            "title": scrub(title, TITLE_CAP),
            "detail": scrub(detail, DETAIL_CAP),
            "ok": bool(ok),
        }
        if isinstance(extra, dict):
            # Bounded and scrubbed like everything else, and it can never
            # overwrite a field the panel relies on.
            for key, value in list(extra.items())[:8]:
                name = _one_line(key, 32)
                if not name or name in row:
                    continue
                row[name] = scrub(value, 120)

        path = _file_for(group_id)
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _prime(group_id, path)
            row["seq"] = _seq[group_id] = _seq.get(group_id, 0) + 1
            _append_line(path, row)
            _lines[group_id] = _lines.get(group_id, 0) + 1
            _trim(group_id, path)
    except Exception as e:
        logger.warning("group_log: could not append to '%s' (%s)", group_id, e)


def read(group_id: str, since_seq: int = 0, limit: int = 200) -> Dict[str, Any]:
    """{"lines": [...], "next_seq": N, "total": N} — the panel's poll.

    `since_seq` is the last seq the caller already has; 0 means "start me
    off". When more than `limit` lines are new, the NEWEST ones are returned
    — a log panel that has fallen behind wants the tail, not the backlog.
    next_seq is always safe to send back as the next since_seq, including
    when nothing was returned; it moves BACKWARDS only when the group's
    numbering itself restarted, which is what tells the panel to start over.
    """
    empty = {"lines": [], "next_seq": 0, "total": 0}
    try:
        if not _valid(group_id):
            return empty
        rows = _load(_file_for(group_id))
        if not rows:
            return empty
        try:
            since = max(0, int(since_seq or 0))
        except (TypeError, ValueError):
            since = 0
        try:
            cap = int(limit or 200)
        except (TypeError, ValueError):
            cap = 200
        cap = max(1, min(cap, READ_LIMIT_MAX))

        def _seq_of(row: Dict[str, Any]) -> int:
            try:
                return int(row.get("seq") or 0)
            except (TypeError, ValueError):
                return 0

        highest = max((_seq_of(r) for r in rows), default=0)
        fresh = [r for r in rows if _seq_of(r) > since] if since else list(rows)
        fresh = fresh[-cap:]
        # Deliberately NOT clamped up to `since`. A next_seq that walks
        # backwards is the panel's only signal that this log was renumbered,
        # and renumbering does happen: seq lives in this process's memory, so a
        # clear() followed by a restart starts the group again at 1. Answering
        # `since` there would hide it — every later poll asks for lines above a
        # number the file will not reach again, and the panel sits at "nothing
        # new" forever with no way to notice. `or since` covers the one case
        # where a lower number would be a lie rather than a signal: a file of
        # rows that carry no seq at all (hand-edited), where standing still
        # beats making the panel refetch everything every two seconds.
        next_seq = _seq_of(fresh[-1]) if fresh else (highest or since)
        return {"lines": fresh, "next_seq": next_seq, "total": len(rows)}
    except Exception as e:
        logger.warning("group_log: could not read '%s' (%s)", group_id, e)
        return empty


def clear(group_id: str) -> bool:
    """Drop this group's log. True when a file was removed.

    The seq counter is NOT reset: a panel still polling with an old since=
    would otherwise be handed lines it has already shown as if they were new.
    """
    try:
        if not _valid(group_id):
            return False
        path = _file_for(group_id)
        with _LOCK:
            _prime(group_id, path)
            _lines[group_id] = 0
            try:
                path.unlink()
            except FileNotFoundError:
                return False
        return True
    except Exception as e:
        logger.warning("group_log: could not clear '%s' (%s)", group_id, e)
        return False
