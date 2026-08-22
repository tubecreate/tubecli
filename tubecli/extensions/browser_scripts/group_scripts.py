"""What a Script node dropped into a Flow Builder group gives the agents in it.

WHY THIS FILE
    The Flow canvas is where the owner decides. A Script node inside a group
    means "the agents of this group may run this script" — nothing more, and
    nothing for anyone outside the group. This module turns that decision into
    the two halves the server needs: the `scripts` entity kind (how the synced
    manifest entry is stored and how it is described to the model) and the
    `script_run` action handler (how the model asks for a run). It lives next
    to script_routes.py, the code that actually spawns the runner, so
    tubecli.core.group_context never learns what a browser script is — a new
    material is a registration, never a core edit.

THE RULES
    * The model addresses a script by ALIAS. It never sees a script id, and a
      script outside its group(s) simply does not exist: asking for one is a
      refusal that lists only the aliases it may use.
    * The browser profile a run uses belongs to the group too. It is resolved
      through the same registry (the `profiles` kind the browser extension
      registers) or is the group's only profile; a profile name the model
      invented is refused and never reaches the runner. When the group shares
      no profile at all, the run is headless and profile-less.
    * `variables` are the script's own inputs, so they are flattened and capped
      before they leave this file: nested objects, novel-length strings and a
      hundred keys are dropped here, not forwarded to a subprocess.
    * A run is a real browser in a subprocess. One at a time per profile (the
      same rule POST /{id}/run enforces with _attach_running), and a run that
      outlives RUN_TIMEOUT is reported as "still running" instead of holding
      the chat turn open until the browser gives up.
"""
import asyncio
import functools
import inspect
import json
import logging
import os
import re
import sys
import time

logger = logging.getLogger("ScriptStudio.Groups")

# tubecli.core.group_context owns the kind registry; the `scripts` shape lives
# here. The import is guarded because this extension can meet a core that
# predates the registry — there get_group_kinds() has nothing to offer and the
# handler refuses cleanly instead of raising inside a chat turn.
try:
    from tubecli.core import group_context as _gc
    _EntityKind = _gc.EntityKind
except Exception:  # pragma: no cover - only on an out-of-date core
    _gc, _EntityKind = None, None

PROMPT_LIST_CAP = getattr(_gc, "PROMPT_LIST_CAP", 20)

# The canvas offers exactly two levels for a script: run it, or edit it in
# Script Studio. In the core ladder `run` sits where `use` sits (below writing
# data) and `edit` where `write` does. This two-level order is the fallback for
# a core that does not know the words yet; when it does, its ladder decides, so
# a value from it ("read") keeps meaning what it means there.
SCRIPT_ACCESS_ORDER = {"run": 0, "edit": 1}
DEFAULT_ACCESS = "run"
_ACCESS_ALIASES = {"use": "run", "write": "edit", "manage": "edit", "admin": "edit"}

RUN_TIMEOUT = 180          # seconds a chat turn will wait for the browser
MAX_VARIABLES = 20
MAX_VALUE_LEN = 500
MAX_KEY_LEN = 64
OUTPUT_CAP = 800           # characters of run output quoted back to the model
LIST_IN_REFUSAL = 20

SCRIPT_SYNTAX = (
    '{"action":"script_run","script":"<alias>","profile":"<alias>","variables":{"caption":"…"}}',
)

NO_CORE_MSG = ("❌ Group context is not available on this server "
               "(update TubeCLI to run scripts shared with a group).")
NO_SCRIPT_MSG = ("❌ No browser script is shared with this agent. "
                 "Add a Script node to the agent's group.")
NO_RUNNER_MSG = "❌ Script Studio is not available on this server, so no script can be run."

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── Small normalisers ────────────────────────────────────────────────

def _one_line(value, cap: int) -> str:
    """One line, no control characters — an alias is printed at column 0 of the
    prompt, so a multi-line alias could forge a section heading."""
    fn = getattr(_gc, "_one_line", None)
    if callable(fn):
        try:
            return fn(value, cap)
        except Exception:
            pass
    text = _CONTROL_RE.sub("", str(value or "")).replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())[:cap]


def _str(value, limit: int = 200) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _core_order():
    order = getattr(_gc, "ACCESS_ORDER", None)
    return order if isinstance(order, dict) else {}


def norm_script_access(value) -> str:
    """What the node said, as one of the words the ladder in force understands.

    Unknown wording is the default ("run"), not a refusal: the node is IN the
    group, which is what grants — the level only says how far.
    """
    v = _str(value, 20).lower()
    if v in SCRIPT_ACCESS_ORDER:
        return v
    if v in _ACCESS_ALIASES:
        return _ACCESS_ALIASES[v]
    if v in _core_order():
        return v          # a word from the core ladder ("read"): let it decide
    return DEFAULT_ACCESS


def allows(have, need) -> bool:
    """Is `have` at least `need`? The core ladder when it knows both words
    (read < use/run < append < write/edit < manage), the two-level script
    ladder otherwise. Like the core's allows(), an unknown requirement
    refuses — a typo in a handler must not grant."""
    h, n = _str(have, 20).lower(), _str(need, 20).lower()
    order = _core_order()
    if h in order and n in order:
        return order[h] >= order[n]
    if h in SCRIPT_ACCESS_ORDER and n in SCRIPT_ACCESS_ORDER:
        return SCRIPT_ACCESS_ORDER[h] >= SCRIPT_ACCESS_ORDER[n]
    return False


# ── The `scripts` entity kind ────────────────────────────────────────

def script_normalise(raw, index: int):
    """Manifest entry → stored entry, or None to drop it.

    A script with no id cannot be run, so it is not material. The alias never
    falls back to the id: aliases are printed into the prompt and the id is
    exactly what the model must not see.
    """
    if isinstance(raw, str):
        raw = {"script_id": raw}
    if not isinstance(raw, dict):
        return None
    slug = _str(raw.get("slug"))
    script_id = _str(raw.get("script_id") or raw.get("id")) or slug
    if not script_id:
        return None
    alias = (_one_line(raw.get("alias"), 200) or _one_line(raw.get("name"), 200)
             or _one_line(slug, 200) or f"Script {index + 1}")
    return {
        "alias": alias,
        "script_id": script_id,
        "slug": slug,
        "access": norm_script_access(raw.get("access")),
    }


def scripts_describe(entries: list) -> list:
    lines = ["Browser scripts you may run (script_run):"]
    for s in entries[:PROMPT_LIST_CAP]:
        line = f'- "{_one_line(s.get("alias"), 200)}"'
        access = _str(s.get("access"), 20) or DEFAULT_ACCESS
        if access != DEFAULT_ACCESS:
            line += f" (access: {access})"
        lines.append(line)
    if len(entries) > PROMPT_LIST_CAP:
        lines.append(f"- …and {len(entries) - PROMPT_LIST_CAP} more scripts "
                     f"(ask the user for the name).")
    return lines


def scripts_action_docs(entries: list) -> list:
    return list(SCRIPT_SYNTAX)


GROUP_KINDS = [] if _EntityKind is None else [
    # access_default is declarative; an older core normalises "run" away to
    # "read" because its ladder has no such word. Harmless: script_normalise
    # is the authority on what an entry's access is.
    _EntityKind(key="scripts", label="Browser scripts", normalise=script_normalise,
                describe=scripts_describe, action_docs=scripts_action_docs,
                access_default="run", order=35, identity="script_id"),
]


# ── The runner module ────────────────────────────────────────────────
# script_routes.py is loaded by file path in get_routes() (module name
# "script_studio_routes"), so importing it again as a package submodule would
# create a SECOND module object: a second _attach_running dict and a second
# store singleton, which would make the lock the HTTP /run route holds
# invisible here. The extension hands us the module it already loaded;
# everything below is only for the paths where that never happened (tests, a
# server whose routes failed to load).

_routes_mod = None
ROUTES_MODULE_NAME = "script_studio_routes"


def set_routes_module(mod) -> None:
    """Called by the extension right after it loads script_routes.py."""
    global _routes_mod
    _routes_mod = mod


def routes_module():
    global _routes_mod
    if _routes_mod is not None:
        return _routes_mod
    mod = sys.modules.get(ROUTES_MODULE_NAME)
    if mod is None:
        try:
            from tubecli.extensions.browser_scripts import script_routes as mod  # noqa: WPS433
        except Exception:
            try:
                import importlib.util
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "script_routes.py")
                spec = importlib.util.spec_from_file_location("script_studio_routes_group", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                logger.warning(f"[scripts] runner unavailable: {e}")
                return None
    _routes_mod = mod
    return mod


# ── Group resolution ─────────────────────────────────────────────────

def group_context_module():
    """Imported lazily so tests can stub it and an older core refuses cleanly."""
    try:
        import importlib
        return importlib.import_module("tubecli.core.group_context")
    except Exception as e:  # pragma: no cover - only on an out-of-date core
        logger.warning(f"[scripts] group_context unavailable: {e}")
        return None


def groups_in_effect(gc, context: dict) -> list:
    """Groups this call works in. The web pipeline and the Telegram listener
    pass `group_ids` when they already decided (an empty list means "this turn
    belongs to no group" — it must NOT be read as "compute the union"); an
    older caller without the key gets the union for the agent."""
    ctx = context or {}
    agent_id = _str((ctx.get("agent") or {}).get("id"), 200)
    gids = ctx.get("group_ids")
    try:
        if isinstance(gids, (list, tuple)):
            return [g for g in (gc.load(_str(gid, 64)) for gid in gids) if g]
        if not agent_id:
            return []
        return list(gc.effective_groups(agent_id, _str(ctx.get("group_id"), 64)) or [])
    except Exception as e:
        logger.warning(f"[scripts] cannot load groups: {e}")
        return []


def entries_of(groups: list, kind_key: str) -> list:
    out = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for e in g.get(kind_key) or []:
            if isinstance(e, dict):
                out.append(e)
    return out


def _local_resolve(groups: list, kind_key: str, ref: str, identity: str, match_keys: tuple):
    """The core's resolve_entry rule, applied here for a core that does not
    have it yet: alias first (trimmed, casefolded), then the kind's own id
    fields. One name pointing at two different entities is ambiguous, never a
    silent pick — the agent may sit in several groups."""
    key = _str(ref, 2000).casefold()
    if not key:
        return None
    best = None
    distinct = {}
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for e in g.get(kind_key) or []:
            if not isinstance(e, dict):
                continue
            hit = _str(e.get("alias"), 200).casefold() == key
            if not hit:
                hit = any(_str(e.get(k), 200).casefold() == key for k in match_keys)
            if not hit:
                continue
            cand = dict(e)
            cand["group_id"] = g.get("group_id", "")
            cand["group_label"] = g.get("label", "")
            distinct.setdefault(_str(e.get(identity), 200).casefold()
                                or _str(e.get("alias"), 200).casefold(), cand)
            best = best or cand
    if len(distinct) > 1:
        return {"ambiguous": True,
                "choices": [{"alias": c.get("alias", ""), "group_label": c.get("group_label", "")}
                            for c in distinct.values()]}
    return best


def resolve_entry(gc, groups: list, kind_key: str, ref: str, identity: str, match_keys: tuple = ()):
    """gc.resolve_entry when the core has it, the same rule locally otherwise.

    The local pass also runs when the core found nothing: the core matches
    alias + identity, and the model likes to name a script by its slug.
    """
    fn = getattr(gc, "resolve_entry", None)
    if callable(fn):
        try:
            found = fn(groups, kind_key, ref)
        except Exception as e:
            logger.warning(f"[scripts] resolve_entry('{kind_key}') failed: {e}")
            found = None
        if found:
            return found
    return _local_resolve(groups, kind_key, ref, identity, match_keys)


def only_entry(gc, groups: list, kind_key: str, identity: str):
    """The single entry of that kind in scope, or None when there are 0 or 2+."""
    fn = getattr(gc, "only_entry", None)
    if callable(fn):
        try:
            found = fn(groups, kind_key)
        except Exception as e:
            logger.warning(f"[scripts] only_entry('{kind_key}') failed: {e}")
            found = None
        if found:
            return found
    distinct = {}
    for e in entries_of(groups, kind_key):
        distinct.setdefault(_str(e.get(identity), 200).casefold()
                            or _str(e.get("alias"), 200).casefold(), e)
    if len(distinct) == 1:
        return list(distinct.values())[0]
    return None


def _alias_list(entries: list) -> str:
    """The names a refusal may print — aliases, the same names prompt_block
    taught the model (for a profile the alias defaults to the profile name).
    Never an id: a refusal must not become the id lookup the prompt refuses."""
    names = [f'"{_one_line(e.get("alias"), 120) or "?"}"' for e in entries[:LIST_IN_REFUSAL]]
    return ", ".join(names) or "(none)"


def _ambiguous_msg(ref: str, entry: dict, what: str) -> str:
    opts = "; ".join(f'"{c.get("alias")}" (group {c.get("group_label") or "?"})'
                     for c in entry.get("choices") or [])
    return f'❌ "{ref}" matches more than one {what}: {opts}. Say which group you mean.'


def resolve_script(gc, groups: list, action_data: dict):
    """→ (entry, None) when the script is shared with enough access, else (None, refusal)."""
    shared = entries_of(groups, "scripts")
    if not shared:
        return None, NO_SCRIPT_MSG
    ref = _str(action_data.get("script") or action_data.get("alias")
               or action_data.get("name") or action_data.get("slug")
               or action_data.get("script_id"), 2000)
    entry = None
    if ref:
        entry = resolve_entry(gc, groups, "scripts", ref, "script_id", ("script_id", "slug"))
    elif len(shared) == 1:
        entry = shared[0]           # one script in scope: "the script" is unambiguous
    if isinstance(entry, dict) and entry.get("ambiguous"):
        return None, _ambiguous_msg(ref, entry, "script")
    if not entry:
        names = _alias_list(shared)
        if ref:
            return None, f'❌ Script "{ref}" is not shared with this agent. Shared scripts: {names}.'
        return None, f'❌ Which script? Set "script" to one of: {names}.'
    have = _str(entry.get("access"), 20) or DEFAULT_ACCESS
    if not allows(have, "run"):
        return None, (f'❌ Script "{entry.get("alias")}" is shared with access "{have}"; '
                      f'script_run needs "run".')
    if not (entry.get("slug") or entry.get("script_id")):
        return None, (f'❌ Script "{entry.get("alias")}" has no script attached '
                      f'— re-pick it in the Script node.')
    return entry, None


def profile_level_refusal(entry: dict) -> str:
    """Empty when this profile may be driven, else the refusal to send back.

    A run launches a real Chromium on that profile's user-data-dir with the
    owner's cookies — exactly what browser_open does, and the browser extension
    refuses a profile shared below "use" (group_actions._resolve_profile). This
    handler checked the SCRIPT's level and not the PROFILE's, so a `profiles`
    entry stored read-only was refused by browser_open and silently driven here.
    The word is normalised first: on a core whose ladder has no "use"/"run",
    allows() would refuse every profile the canvas ever wrote.
    """
    raw = _str((entry or {}).get("access"), 20)
    have = norm_script_access(raw)
    if allows(have, DEFAULT_ACCESS):
        return ""
    return (f'❌ Browser profile "{_one_line((entry or {}).get("alias"), 200)}" is shared with '
            f'access "{raw or have}"; script_run drives that browser, which needs at least "run".')


def resolve_profile(gc, groups: list, action_data: dict):
    """→ (profile_name, refusal). "" with no refusal = run headless, no profile.

    A profile is material like anything else: named by alias, resolved in the
    group, or the group's only one. What the model wrote is never passed to the
    runner — only the `profile` field of the entry the owner shared is.
    """
    shared = entries_of(groups, "profiles")
    ref = _str(action_data.get("profile") or action_data.get("browser"), 2000)
    if ref:
        if not shared:
            return "", ('❌ No browser profile is shared with this agent. Add a Browser node to '
                        'the group, or run the script without "profile".')
        entry = resolve_entry(gc, groups, "profiles", ref, "profile", ("profile",))
        if isinstance(entry, dict) and entry.get("ambiguous"):
            return "", _ambiguous_msg(ref, entry, "browser profile")
        if not entry:
            return "", (f'❌ Browser profile "{ref}" is not shared with this agent. '
                        f'Shared profiles: {_alias_list(shared)}.')
        refusal = profile_level_refusal(entry)
        if refusal:
            return "", refusal
        # The stored profile name, not the model's spelling of it.
        name = _str(entry.get("profile"), 200) or _str(entry.get("alias"), 200)
        if not name:
            return "", f'❌ Browser profile "{ref}" has no profile attached — re-pick it in the Browser node.'
        return name, None
    if not shared:
        return "", None             # nothing shared: headless run, no profile
    picked = only_entry(gc, groups, "profiles", "profile")
    if picked is None:
        return "", (f'❌ Which browser profile? Set "profile" to one of: {_alias_list(shared)}.')
    refusal = profile_level_refusal(picked)
    if refusal:
        return "", refusal
    return _str(picked.get("profile"), 200) or _str(picked.get("alias"), 200), None


# ── Variables ────────────────────────────────────────────────────────

def sanitise_variables(raw):
    """→ (variables, dropped_keys). Flat str→(str|int|float|bool) only.

    Whatever the model wrote lands in a JSON file a Node subprocess reads, so
    it is bounded here: a nested object, a 50 KB caption or a hundred keys are
    dropped rather than forwarded. SHAPE only — which names may be filled at
    all, and whether a value fits the hole it is pasted into, is what
    filter_variables decides once the script itself is known.
    """
    if not isinstance(raw, dict):
        return {}, []
    out, dropped = {}, []
    for key, value in raw.items():
        name = _one_line(key, MAX_KEY_LEN)
        if not name:
            dropped.append(_one_line(key, 24) or "?")
            continue
        if len(out) >= MAX_VARIABLES:
            dropped.append(name)
            continue
        if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
            out[name] = value
        elif isinstance(value, str):
            # Control characters would be written into the runner's JSON as-is;
            # a caption is one value, not a file.
            out[name] = _CONTROL_RE.sub("", value)[:MAX_VALUE_LEN]
        else:
            dropped.append(name)
    return out, dropped


# Placeholders the runner does not merely SHOW. runner/script_runner.js
# substitutes {{name}} by plain string replacement and then hands the result to
# page.evaluate() (`code`, `break_on`), to page.goto() (`url`) or to path.join()
# (`output_dir`, `filename`). A value landing in one of those is code, a URL or
# a path — so it is checked like one, not like a caption.
_CODE_PARAMS = {"code", "break_on", "expression", "js", "script"}
_PATH_PARAMS = {"output_dir", "filename", "path", "save_path", "save_to", "download_dir", "file"}
_URL_PARAMS = {"url", "target_url", "href"}
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
# Everything that can end the JS string a value is pasted into, or start a new
# expression inside it.
_CODE_UNSAFE_RE = re.compile(r"""['"`\\;<>(){}\n\r]|\$\{""")
# A download path must stay a name inside the directory the author chose.
_PATH_UNSAFE_RE = re.compile(r"""[/\\:*?"<>|]|\.\.|^~""")
_SCHEME_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9+.\-]*:")


def _context_of(key: str) -> str:
    key = str(key or "").lower()
    if key in _CODE_PARAMS:
        return "code"
    if key in _PATH_PARAMS:
        return "path"
    if key in _URL_PARAMS:
        return "url"
    return "plain"


def _collect_placeholders(node, sink: dict, context: str = "plain") -> None:
    """Walk the stored script and record every {{name}} with what it feeds.

    The walk is shape-agnostic on purpose: steps nest (loop.steps, if branches)
    and Script Studio keeps growing new step types — a walk that only knew
    today's shapes would quietly stop covering tomorrow's.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            _collect_placeholders(value, sink, _context_of(key))
    elif isinstance(node, (list, tuple)):
        for item in node:
            _collect_placeholders(item, sink, context)
    elif isinstance(node, str):
        for name in _PLACEHOLDER_RE.findall(node):
            sink.setdefault(name, set()).add(context)


def script_inputs(script: dict) -> dict:
    """{name: {contexts}} — the placeholders THIS script published as inputs."""
    sink = {}
    if not isinstance(script, dict):
        return sink
    _collect_placeholders(script.get("steps"), sink)
    _collect_placeholders(script.get("target_url"), sink, "url")
    for declared in (script.get("variables"), script.get("function_inputs")):
        for item in declared or []:
            name = item.get("name") if isinstance(item, dict) else item
            name = _one_line(name, MAX_KEY_LEN)
            if name:
                # Declared but unused: still an input the author published.
                sink.setdefault(name, set()).add("plain")
    return sink


def _unsafe_reason(context: str, value: str) -> str:
    if context == "code" and _CODE_UNSAFE_RE.search(value):
        return "it would end the JavaScript string it is pasted into"
    if context == "path" and _PATH_UNSAFE_RE.search(value):
        return "it carries a path separator or '..'"
    if context == "url" and (_SCHEME_RE.match(value) or "//" in value or "\\" in value):
        return "it carries a scheme or a host of its own"
    return ""


def filter_variables(script: dict, variables: dict):
    """→ (kept, dropped). The author's holes only, filled with values that fit.

    Type, length and key count are bounded upstream (sanitise_variables), and
    that is not enough: the runner pastes a value straight INTO the step text,
    so a value is safe only for the hole it goes in. A name the script never
    mentions is not an input at all; a value that would close the JS string of
    an `evaluate` body, jump host in a `navigate`, or climb out of a download
    directory is refused even under the right name. The model is told what was
    dropped (the `dropped` list), so it can ask the user instead of guessing.
    """
    inputs = script_inputs(script)
    kept, dropped = {}, []
    for name, value in (variables or {}).items():
        contexts = inputs.get(name)
        if not contexts:
            dropped.append(name)
            continue
        if isinstance(value, str):
            why = ""
            for context in sorted(contexts):
                why = _unsafe_reason(context, value)
                if why:
                    break
            if why:
                logger.info(f"[scripts] variable '{name}' refused: {why}")
                dropped.append(name)
                continue
        kept[name] = value
    return kept, dropped


def script_definition(routes, run_id: str):
    """The stored script, or None when it cannot be read.

    None means "unknown", never "empty": run_script_sync looks the same script
    up and raises when it is missing, so a lookup that fails here leaves the
    variables as they were and lets that path report the real problem.
    """
    store = getattr(routes, "_store", None)
    if not callable(store):
        return None
    try:
        script = store().get_script(run_id)
    except Exception as e:
        logger.warning(f"[scripts] cannot read script '{run_id}': {e}")
        return None
    return script if isinstance(script, dict) else None


def _truthy(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    return default


# ── Running ──────────────────────────────────────────────────────────

def profile_busy(routes, profile: str) -> bool:
    """The same rule POST /{id}/run answers with 409: one script per live
    browser profile, because two runners on one browser interleave clicks."""
    if not profile or routes is None:
        return False
    attach = getattr(routes, "_attach_running", None) or {}
    procs = getattr(routes, "_running_processes", None) or {}
    exec_id = attach.get(profile)
    if not exec_id:
        return False
    proc = procs.get(exec_id)
    if proc is None:
        return False
    try:
        return proc.poll() is None
    except Exception:
        return False


# A run blocks its thread on a subprocess for minutes. asyncio.to_thread takes
# that thread from the event loop's DEFAULT executor — min(32, cpu+4) threads the
# whole API shares with auth, the file manager and every profile lookup — and
# asyncio.wait_for only releases the WAITER, never the thread. A few timed-out
# group runs would therefore starve the server. They queue in their own small
# pool instead, and the run itself carries a deadline (see run_deadline).
_RUN_POOL = None
RUN_POOL_SIZE = 4


def run_pool():
    global _RUN_POOL
    if _RUN_POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _RUN_POOL = ThreadPoolExecutor(max_workers=RUN_POOL_SIZE,
                                       thread_name_prefix="group-script-run")
    return _RUN_POOL


def run_deadline(run_sync) -> dict:
    """The `timeout=` to hand run_script_sync, when it knows that word.

    The chat turn gives up at RUN_TIMEOUT; the SUBPROCESS gets a little longer
    so a run that is nearly done still finishes and lands in Script Studio.
    A hot-patched extension can meet an older script_routes.py that has no such
    parameter — passing it there would be a TypeError instead of a run.
    """
    try:
        if "timeout" in inspect.signature(run_sync).parameters:
            return {"timeout": RUN_TIMEOUT + 30}
    except (TypeError, ValueError):
        pass
    return {}


def log_tail(log, cap: int = 400) -> str:
    """The end of the runner's output — where the failure is.

    The runner speaks JSON lines ({"status":"log","message":…}); quoting them
    raw would spend the whole reply on braces.
    """
    lines = []
    for raw in str(log or "").splitlines()[::-1]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                raw = str(parsed.get("message") or parsed.get("error") or raw)
        except Exception:
            pass
        lines.append(raw)
        if len(lines) >= 3:
            break
    return _one_line(" | ".join(reversed(lines)), cap)


class _LiveRun:
    """A stand-in for subprocess.Popen inside script_routes' _running_processes:
    poll() is the only thing that dict is ever asked for. Alive until the run
    releases it, and never past `deadline` — a lock leaked by a server killed
    mid-run must not block the profile until the next restart."""

    def __init__(self, deadline: float):
        self.deadline = deadline
        self.done = False

    def poll(self):
        if self.done or time.time() > self.deadline:
            return 0
        return None


def take_profile(routes, profile: str) -> str:
    """Hold the profile in script_routes' OWN lock for the length of the run.

    run_script_sync never took it (only the attach route does), so without this
    a second agent — or the owner clicking Run — would put a second runner on
    the same browser profile. Publishing it there rather than in a private dict
    is what makes POST /{id}/run answer its 409 while an agent is working.
    """
    if not profile or routes is None:
        return ""
    attach = getattr(routes, "_attach_running", None)
    procs = getattr(routes, "_running_processes", None)
    if not isinstance(attach, dict) or not isinstance(procs, dict):
        return ""
    # A string key can never collide with the integer execution ids the routes
    # put in that dict, so their cleanup and ours never fight over an entry.
    key = f"group-run:{profile}:{time.time():.6f}"
    procs[key] = _LiveRun(time.time() + RUN_TIMEOUT + 120)
    attach[profile] = key
    return key


def preview_port_for(profile: str):
    """The port of a LIVE preview browser on this profile, or None.

    run_script_sync starts its own Chromium on the profile's user-data-dir, and
    a second Chromium on a directory another one already holds simply dies. The
    browser extension knows what is open, so ask it and say so, instead of
    handing the model a runner traceback. Read-only, lazy, and optional: if that
    extension is absent the run just goes ahead as before.
    """
    if not profile:
        return None
    try:
        from tubecli.extensions.browser.routes import _resolve_port_for_profile
        return _resolve_port_for_profile(profile)
    except Exception:
        return None


def release_profile(routes, profile: str, key: str) -> None:
    if not key or routes is None:
        return
    attach = getattr(routes, "_attach_running", None)
    procs = getattr(routes, "_running_processes", None)
    if isinstance(procs, dict):
        run = procs.pop(key, None)
        if isinstance(run, _LiveRun):
            run.done = True
    # Only if it is still OURS: a later run may already own the profile.
    if isinstance(attach, dict) and attach.get(profile) == key:
        attach.pop(profile, None)


def summarise_output(result) -> str:
    """The runner's output variables, short enough to sit in a chat reply."""
    if isinstance(result, dict) and result:
        parts = []
        used = 0
        for key, value in result.items():
            line = f"{_one_line(key, 60)} = {_one_line(value, 200)}"
            if used + len(line) > OUTPUT_CAP:
                parts.append("…")
                break
            parts.append(line)
            used += len(line) + 1
        return "\n".join(parts)
    if isinstance(result, str) and result.strip():
        return _one_line(result, OUTPUT_CAP)
    return "(no output variables)"


async def script_run(action_data: dict, context: dict) -> str:
    """`{"action":"script_run","script":"<alias>","profile":"<alias>","variables":{…}}`"""
    action_data = action_data if isinstance(action_data, dict) else {}
    gc = group_context_module()
    if gc is None:
        return NO_CORE_MSG
    groups = groups_in_effect(gc, context)
    entry, refusal = resolve_script(gc, groups, action_data)
    if refusal:
        return refusal
    profile, refusal = resolve_profile(gc, groups, action_data)
    if refusal:
        return refusal

    variables, dropped = sanitise_variables(action_data.get("variables"))
    headless = _truthy(action_data.get("headless"), True)

    routes = routes_module()
    run_sync = getattr(routes, "run_script_sync", None) if routes is not None else None
    if not callable(run_sync):
        return NO_RUNNER_MSG
    if profile_busy(routes, profile):
        return (f'❌ A script is already running on browser profile "{profile}". '
                f'Wait for it to finish and try again.')
    if preview_port_for(profile):
        return (f'❌ The browser profile "{profile}" is open in a live view, and a script '
                f'needs it to itself. Close it (browser_close) and run this again.')

    alias = _one_line(entry.get("alias"), 200)
    # get_script() keys on the slug; the id is only a fallback for old entries.
    run_id = _str(entry.get("slug"), 200) or _str(entry.get("script_id"), 200)
    where = f' on profile "{profile}"' if profile else " headless (no profile)"

    # Bound the variables to the holes THIS script left: the runner pastes them
    # into step text, `evaluate` bodies included, so an unannounced name is not
    # an input, it is a payload.
    definition = script_definition(routes, run_id)
    if definition is not None:
        variables, refused = filter_variables(definition, variables)
        dropped.extend(refused)

    lock_key = take_profile(routes, profile)
    release = True
    try:
        # run_script_sync blocks on a subprocess, so it goes to a thread — one of
        # OUR pool's, never the loop's shared default. wait_for releases the CHAT
        # TURN only; what releases the thread is the deadline the run itself
        # carries (run_deadline), a little past this one so a nearly finished run
        # still lands in Script Studio.
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(run_pool(), functools.partial(
                run_sync, run_id, variables, profile, headless, **run_deadline(run_sync))),
            timeout=RUN_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # The browser is still that run's. Keep the profile held (the sentinel
        # expires on its own) instead of inviting a second runner onto it.
        release = False
        return (f'⏳ Script "{alias}"{where} is still running after {RUN_TIMEOUT}s. '
                f'It keeps going in the background for a short while — check Script Studio '
                f'for the result before telling the user it worked.')
    except ValueError as e:
        # The store no longer has it: the node points at a deleted script.
        return f'❌ Script "{alias}" is no longer on this server ({_one_line(e, 200)}).'
    except Exception as e:
        return f'❌ Script "{alias}"{where} failed: {_one_line(e, OUTPUT_CAP)}'
    finally:
        if release:
            release_profile(routes, profile, lock_key)

    note = f'\n(ignored variables: {", ".join(dropped[:10])})' if dropped else ""
    if getattr(result, "success", True) is False:
        # A failed run writes its result file too, so "we got variables back"
        # never meant "the job is done". Saying ✅ here is what would make the
        # agent report an upload that never happened.
        tail = log_tail(getattr(result, "log", ""))
        return (f'❌ Script "{alias}"{where} stopped on a failed step — do not treat the job '
                f'as done. Variables at that point:\n{summarise_output(result)}'
                + (f'\nLast log: {tail}' if tail else "") + note)
    return f'✅ Script "{alias}" finished{where}.\n{summarise_output(result)}{note}'
