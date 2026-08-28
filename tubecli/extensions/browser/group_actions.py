"""Browser profiles as group material, and the five actions that drive them.

WHY THIS FILE EXISTS
    A Browser node dropped inside a Flow Builder group is the owner saying
    "this agent may drive this profile". tubecli.core.group_context keeps the
    registry of what a group can hold; the SHAPE of a browser profile belongs
    here, next to the handlers that consume it, so adding a material stays a
    registration and never becomes a core edit (same arrangement as `sheets`
    in auth_manager and `files` in file_manager).

    The chain the owner is after — the agent opens the group's profile, goes
    to a page, READS what is on it, attaches the group's file, closes the
    profile — only holds if every step is checked on the server. So:

    * The model addresses a profile by ALIAS. The profile name, the port and
      the file path stay on this side; a prompt-injected reply cannot name a
      profile the owner did not share, because it never learns one exists.
    * Deny by default: no group ⇒ no profile ⇒ refusal with a sentence that
      tells the owner what to do on the canvas.
    * browser_upload attaches ONLY the path stored in the group entry. A path
      the model wrote is never opened — that is the whole point of the entry.
    * Only http/https, and never back into this machine's own ports: the
      browser runs here, with the owner's cookies, one hop from the API.
    * browser_read comes back wrapped as EXTERNAL DATA. It reads through the
      owner's LOGGED-IN session, so the page is written by strangers and can
      be hostile in a way an anonymous fetch is not: the wrapper (and the rule
      that travels with it in the system prompt) is what keeps a paragraph
      saying "ignore your instructions" a paragraph and not an order.

WHY THE DESCRIPTION KNOWS WHERE THE BROWSER IS
    "- \"Test\"" tells the model a profile exists; it does not tell it that the
    profile is already sitting on the page the user is asking about, which is
    the single fact that decides between browser_read and a web search. So the
    description carries live state — on a HARD budget, because it is built on
    the chat's critical path: at most _LIVE_CAP profiles, _LIVE_BUDGET seconds
    for all of them together, a _LIVE_TTL-second cache, and SILENCE (the line
    exactly as it read before) whenever the answer does not arrive in time.
    Chat latency wins every argument with this feature.

DEGRADING INSTEAD OF CRASHING
    group_context grows in the same wave as this file, and hot-patched
    extensions also meet older cores. Every core helper is looked up at call
    time; a missing one becomes a refusal the owner can read, not a traceback
    inside a chat turn.
"""
import asyncio
import importlib
import ipaddress
import logging
import os
import re
import threading
import time
from urllib.parse import unquote, urlsplit

logger = logging.getLogger("BrowserGroup")

# Guarded, exactly like the other kind-owning extensions: this module is
# imported by extension.py at load time and must not take the extension down
# on a core that predates the registry.
try:
    from tubecli.core import group_context as _gc_module
    _EntityKind = _gc_module.EntityKind
except Exception:                                        # pragma: no cover
    _gc_module, _EntityKind = None, None

_PROMPT_LIST_CAP = getattr(_gc_module, "PROMPT_LIST_CAP", 20)

# read < use < append < write < manage. The core ladder (ACCESS_ORDER) knows
# nothing about "use" until the group_context change lands, and allows()
# refuses values it does not know — which would refuse every profile. So the
# rank of a value the core does not have is decided here, and the core stays
# the authority for the values it does have (see _allowed).
_LOCAL_RANK = {"read": 0, "use": 1, "run": 1, "append": 2, "write": 3, "edit": 3, "manage": 4}

_BROWSER_SYNTAX = (
    '{"action":"browser_open","profile":"<alias>","url":"https://…"}',
    '{"action":"browser_goto","profile":"<alias>","url":"https://…"}',
    # Placed straight after browser_goto because that is the order the work
    # happens in: go to the page, then read it. A model that has just navigated
    # and finds no reading verb next to the navigating one goes looking for a
    # web search instead — which is the whole bug this verb exists to end.
    '{"action":"browser_read","profile":"<alias>"}'
    ' — returns the text of the page that profile currently has open (its own '
    'logged-in session), so you can summarise or quote it. It does NOT navigate: '
    'use browser_goto first when the page you want is not the one already open.',
    '{"action":"browser_close","profile":"<alias>"}',
    # The precondition rides on the syntax line on purpose: the preview server
    # only holds a file chooser while the page is asking for one, and it starts
    # asking when someone CLICKS the page's upload button. There is no click
    # The page must already show an upload box: browser_goto gets there first.
    '{"action":"browser_upload","file":"<alias of a file in the group>","profile":"<alias>","selector":"input[type=file]"}'
    ' — attaches a file of the group to the upload box of the page that profile has open; '
    '"selector" is optional (default: the first file input, frames included).',
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Page text keeps its newlines and tabs — a page read as one long line is
# unreadable to the model and to the owner who checks the log. Everything else
# in the C0/C1 range still goes: an ANSI escape or a NUL inside a chat turn is
# never content.
_TEXT_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# How much of a page reaches the model. 6000 characters is a long article and
# still a small slice of any context window; the point of the cap is that a
# page the agent did not choose (an infinite feed, a 2 MB log viewer) cannot
# spend the whole turn. Truncation is ANNOUNCED, outside the data wrapper.
_READ_CAP = 6000


# ── Small normalisers (kept local on purpose) ────────────────────────

def _line(value, cap: int = 200) -> str:
    """One line, no control characters, trimmed to `cap`.

    An alias is printed at column 0 of the prompt block, so an alias
    containing a newline could forge a section heading ("### ACTION SYNTAX")
    and teach the model verbs the owner never shared.
    """
    if value is None:
        return ""
    return _CONTROL_RE.sub(" ", str(value)).strip()[:cap]


def _access(value, default: str = "use") -> str:
    v = _line(value, 20).lower()
    return v if v in _LOCAL_RANK else default


def _aliases(entries, key: str = "alias", cap: int = 20) -> str:
    names = [f'"{_line(e.get(key), 120) or "?"}"' for e in entries[:cap] if isinstance(e, dict)]
    return ", ".join(names) or "(none)"


# ── The kind: what a Browser node inside a group shares ──────────────

def _profile_normalise(raw, index: int):
    """{alias, profile, access}; an entry without a profile name is dropped."""
    if isinstance(raw, str):
        raw = {"profile": raw}
    if not isinstance(raw, dict):
        return None
    profile = _line(raw.get("profile"), 200)
    if not profile:
        return None
    return {
        "alias": _line(raw.get("alias"), 200) or profile,
        "profile": profile,
        # The owner's own browser: driving it is the default, and the canvas
        # sends "use" explicitly anyway.
        "access": _access(raw.get("access"), "use"),
    }


# ── Live state, on a budget the chat can afford ──────────────────────
# Nothing below is allowed to make a chat turn slower than _LIVE_BUDGET, and
# nothing below is allowed to raise: a profile whose state we could not learn
# in time simply keeps the line it had before this feature existed.

_LIVE_CAP = 4            # profiles asked per prompt build
_LIVE_BUDGET = 0.30      # seconds, for ALL of them together
_LIVE_TTL = 5.0          # seconds a state is reused without asking again
_LIVE_CACHE_MAX = 64     # profile names remembered; a machine has far fewer

# profile -> (when, state). A state is {"known": False} when we could not find
# out, and that is CACHED too: without the negative entry a preview server that
# accepts connections and never answers would cost every single chat turn the
# full budget, for ever. Asked once per _LIVE_TTL is the whole idea.
_live_cache = {}
_UNKNOWN = {"known": False}
_live_lock = threading.Lock()
_live_pool = None


def _live_executor():
    """One small pool, created on first use and never shut down.

    A `with ThreadPoolExecutor(...)` here would block on shutdown until every
    worker returned — which is exactly the stall the budget exists to prevent.
    Workers are bounded by the socket timeout instead, and a straggler simply
    finishes into the cache for the next turn.
    """
    global _live_pool
    with _live_lock:
        if _live_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _live_pool = ThreadPoolExecutor(max_workers=_LIVE_CAP,
                                            thread_name_prefix="browser-live")
        return _live_pool


def _live_ask(port) -> dict:
    """Ask the preview server on this machine what it is showing.

    /status is the endpoint the live view already polls; `active_url` is the
    URL of the tab being streamed, i.e. the page a human would say the browser
    "is on". Loopback only, and the port comes from the server's own process
    table — never from the model.
    """
    import json as _json
    import urllib.request as _u
    with _u.urlopen(f"http://127.0.0.1:{int(port)}/status", timeout=_LIVE_BUDGET) as r:
        data = _json.loads(r.read().decode("utf-8", "replace"))
    if not isinstance(data, dict):
        return {"known": True, "open": True, "url": ""}
    # Capped and stripped of control characters like every other value that
    # reaches column 0 of the prompt: the URL is set by the page (pushState),
    # so it is not the owner's text.
    return {"known": True, "open": True, "url": _line(data.get("active_url"), 200)}


def _live_states(entries) -> dict:
    """{profile name: state} for the first _LIVE_CAP entries. Never raises.

    Absent from the result means "could not tell in time" — the caller then
    prints nothing extra, which is the pre-existing behaviour.
    """
    out, now, pending = {}, time.time(), []
    for p in (entries or [])[:_LIVE_CAP]:
        if not isinstance(p, dict):
            continue
        profile = str(p.get("profile") or "")
        if not profile or profile in out:
            continue
        hit = _live_cache.get(profile)
        if hit and (now - hit[0]) < _LIVE_TTL:
            out[profile] = hit[1]
            continue
        try:
            from .routes import _resolve_port_for_profile
            port = _resolve_port_for_profile(profile)
        except Exception:
            continue                       # no routes module ⇒ say nothing at all
        if not port:
            # Free and certain: the server's own process table has no live
            # preview for this profile. No HTTP call, no budget spent.
            out[profile] = _remember(profile, {"known": True, "open": False, "url": ""})
            continue
        pending.append((profile, port))
    if not pending:
        return out

    deadline = time.time() + _LIVE_BUDGET
    try:
        futures = [(name, _live_executor().submit(_live_ask, port)) for name, port in pending]
    except Exception as e:                                   # pragma: no cover
        logger.debug(f"[browser] live state pool unavailable: {e}")
        return out
    for name, fut in futures:
        left = deadline - time.time()
        try:
            if left <= 0:
                raise TimeoutError(name)
            out[name] = _remember(name, fut.result(timeout=left))
        except Exception:
            fut.cancel()
            stale = _live_cache.get(name)
            # Back off for a TTL either way; a state we already had is still
            # worth printing this turn (five seconds old beats nothing).
            _remember(name, _UNKNOWN)
            if stale and stale[1].get("known"):
                out[name] = stale[1]
    return out


def _remember(profile: str, state: dict) -> dict:
    if len(_live_cache) >= _LIVE_CACHE_MAX:
        _live_cache.clear()
    _live_cache[profile] = (time.time(), state)
    return state


def _where(raw) -> str:
    """Chỗ trình duyệt đang đứng, in được vào PROMPT HỆ THỐNG: origin + đầu path.

    Dòng bàn làm việc đi vào system prompt ở MỌI lượt chat, tức phần được tin
    nhất — mà URL thì do TRANG đặt (history.pushState), muốn đổi thành gì cũng
    được. _line chặn được việc giả tiêu đề mục, nhưng vẫn để lọt 200 ký tự văn
    xuôi do kẻ khác chọn nằm ở vị trí đó. Cắt còn origin + 40 ký tự đầu của
    path giữ lại đúng SỰ THẬT model cần (đang ở trang nào) và bỏ cái đuôi kia.

    Còn một lẽ nữa, không dính tới tấn công: query string và fragment của trang
    chủ máy đang mở — link đặt lại mật khẩu, URL S3 đã ký, ?token=…, id tài
    liệu riêng — trước đây được gửi NGUYÊN sang nhà cung cấp model ở mọi lượt,
    kể cả lượt chẳng liên quan gì tới trình duyệt.
    """
    parts = urlsplit(_line(raw, 300))
    if (parts.scheme or "").lower() not in _ALLOWED_SCHEMES or not parts.netloc:
        return ""
    shown = f"{parts.scheme}://{parts.netloc}{(parts.path or '')[:40]}"
    # _line MỘT LẦN NỮA ở đúng chỗ in ra (netloc/path vẫn là chữ của trang), và
    # tước cả dấu bọc dữ liệu ngoài kẻo một URL tự viết ra dấu đóng.
    return _line(shown, 80).replace(_ED_CLOSE, "…").replace(_ED_OPEN, "…")


def _profiles_describe(entries) -> list:
    live = _live_states(entries)
    lines = ["Browser profiles you may drive (use browser_open / browser_goto / "
             "browser_read / browser_close / browser_upload):"]
    for p in entries[:_PROMPT_LIST_CAP]:
        line = f'- "{p.get("alias", "")}"'
        access = str(p.get("access") or "use")
        # "use" is the norm and saying so on every line only spends prompt;
        # anything else is worth the model knowing.
        if access != "use":
            line += f" (access: {access})"
        # Where the browser actually IS. Appended to the same line, so the
        # shape of this list (and its cap) is the one the prompt always had.
        state = live.get(str(p.get("profile") or ""))
        if isinstance(state, dict) and state.get("known"):
            url = _where(state.get("url"))
            if not state.get("open"):
                line += " — not open"
            elif url:
                line += f" — open, showing {url}"
            else:
                line += " — open"
        lines.append(line)
    if len(entries) > _PROMPT_LIST_CAP:
        lines.append(f"- …and {len(entries) - _PROMPT_LIST_CAP} more profiles "
                     f"(ask the user which one).")
    return lines


def _profiles_action_docs(entries) -> list:
    return list(_BROWSER_SYNTAX)


GROUP_KINDS = [] if _EntityKind is None else [
    _EntityKind(key="profiles", label="Browser profiles", normalise=_profile_normalise,
                describe=_profiles_describe, action_docs=_profiles_action_docs,
                access_default="use", order=25, identity="profile"),
]


# ── Group gate ───────────────────────────────────────────────────────

_NO_PROFILE_MSG = ("❌ No browser profile is shared with this agent. Add a Browser node "
                   "to the agent's group on the Flow canvas.")
_NO_FILE_MSG = ("❌ No file is shared with this agent. Add the file (or the folder holding it) "
                "to the agent's group on the Flow canvas.")
_NO_UPLOAD_MSG = ("❌ browser_upload needs both a Browser node and the file (or the folder "
                  "holding it) in the agent's group on the Flow canvas; neither is shared "
                  "with this agent.")
_OLD_CORE_MSG = ("❌ This server cannot resolve group materials for the browser yet "
                 "(group_context is older than these actions). Update TubeCLI on the server.")


def _group_context():
    """The core module, or None. import_module honours sys.modules, so tests
    can hand this a stub the same way the gsheet handlers are tested."""
    try:
        return importlib.import_module("tubecli.core.group_context")
    except Exception as e:
        logger.warning(f"[browser] group_context unavailable: {e}")
        return None


def _groups_in_effect(gc, context: dict) -> list:
    """Groups this call runs in.

    The web pipeline and the Telegram listener pass `group_ids` — the key
    being PRESENT is the final word (an empty list means "this turn belongs
    to no group"), because after a hand-off to a specialist the agent in
    `context` is a different agent and its own union is not this turn's
    permission. An older caller without the key gets the union.
    """
    ctx = context or {}
    agent_id = str((ctx.get("agent") or {}).get("id") or "")
    try:
        gids = ctx.get("group_ids")
        if isinstance(gids, (list, tuple)):
            return [g for g in (gc.load(str(gid)) for gid in gids) if g]
        if not agent_id:
            return []
        return list(gc.effective_groups(agent_id, str(ctx.get("group_id") or "")) or [])
    except Exception as e:
        logger.warning(f"[browser] cannot load groups: {e}")
        return []


def _allowed(gc, have, need) -> bool:
    """Is `have` at least `need`? The core ladder decides whenever it knows
    both values; the local ladder covers "use"/"run", which the core may not
    have yet. An unknown value on either side is a refusal, never a grant."""
    h, n = _line(have, 20).lower(), _line(need, 20).lower()
    order = getattr(gc, "ACCESS_ORDER", None) or {}
    if h in order and n in order:
        try:
            return bool(gc.allows(h, n))
        except Exception:
            return False
    return h in _LOCAL_RANK and n in _LOCAL_RANK and _LOCAL_RANK[h] >= _LOCAL_RANK[n]


def _resolve_profile(gc, groups, action_data, need: str = "use"):
    """(entry, None) when the profile is shared with enough access, else (None, refusal)."""
    all_profiles = [p for g in groups for p in (g.get("profiles") or []) if isinstance(p, dict)]
    if not all_profiles:
        return None, _NO_PROFILE_MSG

    ref = _line(action_data.get("profile") or action_data.get("alias"), 200)
    resolve_entry = getattr(gc, "resolve_entry", None)
    only_entry = getattr(gc, "only_entry", None)
    if (ref and not callable(resolve_entry)) or (not ref and not callable(only_entry)):
        return None, _OLD_CORE_MSG

    entry = None
    try:
        entry = resolve_entry(groups, "profiles", ref) if ref else only_entry(groups, "profiles")
    except Exception as e:
        logger.warning(f"[browser] resolve profile failed: {e}")
        return None, f"❌ Could not look up browser profiles in this agent's groups: {e}"

    if isinstance(entry, dict) and entry.get("ambiguous"):
        # One alias, two different profiles (the agent is in several groups):
        # picking one silently would drive the wrong browser.
        opts = "; ".join(f'"{c.get("alias")}" (group {c.get("group_label") or "?"})'
                         for c in entry.get("choices") or [])
        return None, f'❌ "{ref}" matches more than one browser profile: {opts}. Say which group you mean.'
    if not isinstance(entry, dict) or not entry.get("profile"):
        names = _aliases(all_profiles)
        if ref:
            return None, (f'❌ Browser profile "{ref}" is not shared with this agent. '
                          f'Shared profiles: {names}.')
        return None, f'❌ Which browser profile? Set "profile" to one of: {names}.'

    have = str(entry.get("access") or "use")
    if not _allowed(gc, have, need):
        return None, (f'❌ Browser profile "{entry.get("alias")}" is shared with access "{have}"; '
                      f'this action needs "{need}".')
    return entry, None


def _gate(action_data: dict, context: dict, need: str = "use"):
    """(gc, groups, profile_entry, None) or (None, [], None, refusal)."""
    gc = _group_context()
    if gc is None:
        return None, [], None, _OLD_CORE_MSG
    groups = _groups_in_effect(gc, context)
    if not groups:
        return None, [], None, _NO_PROFILE_MSG
    entry, err = _resolve_profile(gc, groups, action_data or {}, need)
    if err:
        return None, groups, None, err
    return gc, groups, entry, None


# ── URL guard ────────────────────────────────────────────────────────

_ALLOWED_SCHEMES = ("http", "https")
# Hostnames that mean "this machine" or "the cloud metadata service" without
# looking like an IP address.
_BLOCKED_HOSTS = {"localhost", "ip6-localhost", "ip6-loopback",
                  "metadata", "metadata.google.internal", "instance-data"}


def _host_ip(host: str):
    """The address a browser would really dial, or None for a real hostname.

    127.0.0.1 can be written as 2130706433, 0x7f000001 or ::ffff:127.0.0.1 and
    Chrome dials every one of them; judging only the dotted form would leave
    the loopback door open. A numeric host we cannot parse is reported as
    "numeric but unknown" (False) so the caller refuses rather than guesses.
    """
    h = (host or "").strip("[]")
    ip = None
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        try:
            if re.fullmatch(r"\d+", h):
                ip = ipaddress.ip_address(int(h))
            elif re.fullmatch(r"0[xX][0-9a-fA-F]+", h):
                ip = ipaddress.ip_address(int(h, 16))
        except (ValueError, OverflowError):
            ip = None
    if ip is None:
        # 0177.0.0.1, 127.1 — numeric shorthands Python refuses and browsers accept.
        return False if re.fullmatch(r"[0-9a-fA-FxX.:]+", h) else None
    return getattr(ip, "ipv4_mapped", None) or ip


def _ascii_host(host: str):
    """(the host as the browser will resolve it, None) or (None, why refused).

    This guard compares strings; Chromium compares a host it has already
    canonicalised. It percent-decodes the host first, then applies IDNA/UTS-46:
    U+3002 "。", U+FF0E "．" and U+FF61 "｡" all become ".", fullwidth digits
    become ASCII digits and default-ignorable characters (U+00AD SOFT HYPHEN and
    friends) are dropped. Judging the raw characters therefore let
    "127。0。0。1" and "loc\xadalhost" through as ordinary hostnames while the
    browser dialled loopback. Python's IDNA codec splits labels on the same
    three dot forms and runs nameprep (NFKC + the "map to nothing" table), which
    is exactly the mapping that hides an address here.
    """
    h = unquote(host or "")          # WHATWG parses the host after percent-decoding
    # "localhost." is the fully-qualified spelling of "localhost" and resolves
    # to the same address, so the root label goes before anything is compared.
    h = h.rstrip(".。．｡")
    try:
        return h.encode("idna").decode("ascii").lower(), None
    except Exception:
        # An ASCII host the codec refuses (an empty or over-long label) is left
        # to the checks below, exactly as before. A non-ASCII one we cannot map
        # is refused instead of guessed: what Chromium makes of it is unknown.
        if any(ord(c) > 127 for c in h):
            return None, "the host is not a valid domain name"
        return h.lower(), None


def _safe_url(raw, required: bool = True):
    """(url, None) or ("", refusal).

    The browser we are about to drive sits on this machine with the owner's
    cookies and one hop from the TubeCLI API on 127.0.0.1. A URL the model
    wrote must therefore be a real remote page: http/https only (no file:,
    about:, chrome:, javascript:, data:) and never a loopback / link-local
    address, in ANY of the spellings a browser accepts for one (see _ascii_host
    for the character mapping and _host_ip for the numeric forms). A hostname
    that RESOLVES to loopback is not caught here — the browser does the
    resolving — which is why the API itself still requires its admin token.
    """
    url = _line(raw, 2000)
    if not url:
        if required:
            return "", '❌ This action needs a "url" (http:// or https://).'
        return "", None
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return "", (f'❌ Refused to open "{url[:120]}": only http:// and https:// pages can be '
                    f"opened. file:, about:, chrome: and javascript: are not allowed.")
    host = (parts.hostname or "").lower()
    if not host:
        return "", f'❌ Refused to open "{url[:120]}": the URL has no host.'
    # Every check below runs on the canonical spelling, never on the model's.
    host, why = _ascii_host(host)
    if not host:
        # None: unmappable. "": a host that was nothing but root labels.
        return "", f'❌ Refused to open "{url[:120]}": {why or "the URL has no host"}.'
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return "", f'❌ Refused to open "{url[:120]}": this server\'s own services are not browsable.'
    ip = _host_ip(host)
    if ip is False or (ip is not None and (ip.is_loopback or ip.is_link_local or ip.is_unspecified
                                           or ip.is_reserved or ip.is_multicast)):
        return "", f'❌ Refused to open "{url[:120]}": this server\'s own services are not browsable.'
    return url, None


# ── Talking to the browser routes ────────────────────────────────────

class _BodyOnlyRequest:
    """The minimum `launch_preview` / `proxy_preview_control` read: a JSON body.

    Those two are declared `async def f(request: Request)` and touch nothing
    else on it. Calling them in-process with this stand-in keeps the launch
    logic (port pick, node version check, force-kill of a stale session) in
    routes.py — the alternative, an HTTP loopback to /api/v1/browser/…, would
    need this handler to hold the owner's admin token.
    """

    def __init__(self, data: dict):
        self._data = dict(data or {})

    async def json(self):
        return dict(self._data)


def _detail(e: Exception, cap: int = 400) -> str:
    """The readable half of an HTTPException (or of anything else)."""
    detail = getattr(e, "detail", None)
    return _line(detail if detail not in (None, "") else e, cap) or e.__class__.__name__


def _port_for(profile: str):
    """Port of the preview session running this profile, or None. The port
    comes from the server's own process table — never from the model."""
    try:
        from .routes import _resolve_port_for_profile
        return _resolve_port_for_profile(profile)
    except Exception as e:
        logger.warning(f"[browser] cannot look up the running port: {e}")
        return None


async def _launch(profile: str, url: str):
    """(result, None) or (None, refusal)."""
    try:
        from .routes import launch_preview
        res = await launch_preview(_BodyOnlyRequest(
            # force: a stale session (a lock left by a killed Chrome) must not
            # turn the agent's first step into a dead end.
            {"profile": profile, "url": url, "force": True}))
        return res, None
    except Exception as e:
        return None, _detail(e)


async def _profile_exists(profile: str) -> bool:
    """A manifest can outlive the profile it names (the owner deleted it).
    Saying so beats letting the launcher create an empty profile directory."""
    try:
        from .profile_manager import get_profile
        return bool(await asyncio.to_thread(get_profile, profile))
    except Exception as e:
        logger.warning(f"[browser] cannot check profile '{profile}': {e}")
        return True  # unknown is not proof of absence — let the launcher decide


# ── Actions ──────────────────────────────────────────────────────────
# English on purpose: the pipeline already tells the model which language to
# answer the user in, and these strings are the model's input, not the user's.

async def browser_open(action_data: dict, context: dict) -> str:
    gc, groups, entry, err = _gate(action_data, context)
    if err:
        return err
    url, err = _safe_url((action_data or {}).get("url"), required=False)
    if err:
        return err
    alias, profile = entry.get("alias", ""), entry["profile"]
    if not await _profile_exists(profile):
        return (f'❌ Browser profile "{alias}" no longer exists on this machine. '
                f"Re-pick it in the Browser node on the canvas.")
    res, err = await _launch(profile, url)
    if err:
        return f'❌ Could not open browser profile "{alias}": {err}'
    where = url or "its start page"
    return (f'🌐 Opened browser profile "{alias}" at {where}. The live view is running on '
            f"this machine — the owner can watch it in the Browser node on the canvas. "
            f"Use browser_goto to navigate, browser_read to read the page it is on, "
            f"browser_upload to attach a file from the group, browser_close when you are done.")


async def browser_goto(action_data: dict, context: dict) -> str:
    gc, groups, entry, err = _gate(action_data, context)
    if err:
        return err
    url, err = _safe_url((action_data or {}).get("url"), required=True)
    if err:
        return err
    alias, profile = entry.get("alias", ""), entry["profile"]

    port = _port_for(profile)
    if not port:
        # Nothing running: opening it AT the url is the same navigation, one
        # step fewer, and no home-made protocol.
        if not await _profile_exists(profile):
            return (f'❌ Browser profile "{alias}" no longer exists on this machine. '
                    f"Re-pick it in the Browser node on the canvas.")
        res, err = await _launch(profile, url)
        if err:
            return f'❌ Browser profile "{alias}" was not open and could not be opened: {err}'
        return (f'🌐 Browser profile "{alias}" was not open — opened it at {url}. '
                f"Use browser_read to read what is on it.")

    try:
        from .routes import proxy_preview_control
        res = await proxy_preview_control(int(port), "navigate", _BodyOnlyRequest({"url": url}))
    except Exception as e:
        return f'❌ Could not navigate profile "{alias}" to {url}: {_detail(e)}'
    if isinstance(res, dict) and res.get("error"):
        return f'❌ Profile "{alias}" could not load {url}: {_line(res.get("error"), 300)}'
    landed = _line((res or {}).get("url"), 500) if isinstance(res, dict) else ""
    return (f'🌐 Browser profile "{alias}" is now at {landed or url}. '
            f"Use browser_read to read what is on it.")


# Bản sao CỨNG của delimiter (nguồn: extensions/chat/pipeline.py) — chỉ dùng
# cho đường dự phòng cuối cùng dưới đây.
_ED_OPEN = "<<<EXTERNAL_DATA"
_ED_CLOSE = "<<<END_EXTERNAL_DATA>>>"


def _wrap_local(body: str, source: str) -> str:
    """Bọc tại chỗ, y hệt pipeline.wrap_external."""
    def _defang(s) -> str:
        return str(s or "").replace(_ED_CLOSE, "[…]").replace(_ED_OPEN, "[…]")

    label = " ".join(_defang(source).split())[:120]
    head = f"{_ED_OPEN} source={label}>>>" if label else f"{_ED_OPEN}>>>"
    return "\n".join((head, _defang(body), _ED_CLOSE))


def _as_external_data(body: str, source: str) -> str:
    """Wrap page text so it enters the conversation as DATA, not instructions.

    The rule and the delimiters are defined in ONE place — the chat pipeline —
    and the note that explains them travels in the system prompt. The import is
    late because this is an extension reaching into another extension: with the
    chat extension disabled (Telegram-only host) the text still comes back,
    wrapped by the same helper the core's own file reader falls back to.

    The LAST resort wraps it here, locally. It never returns the body naked: on
    a host where neither module loads — the very case this chain exists for —
    the page's text would otherwise enter the model's context with no
    delimiters at all, while the RULE that names those delimiters is still
    printed (brain._external_data_note carries its own hardcoded fallback). A
    rule pointing at delimiters that are not there is worse than either half.
    """
    try:
        from tubecli.extensions.chat.pipeline import wrap_external
        return wrap_external(body, source)
    except Exception:
        pass
    try:
        from tubecli.core.telegram_actions import _as_external_data as _core_wrap
        return _core_wrap(body, source)
    except Exception as e:                                   # pragma: no cover
        logger.warning(f"[browser] external-data wrapper unavailable: {e}")
        return _wrap_local(body, source)


async def browser_read(action_data: dict, context: dict) -> str:
    """The text of the page the group's profile currently has open.

    SECURITY — this is not web_reader. web_reader fetches anonymously; this
    reads through the OWNER'S LOGGED-IN SESSION, so it can come back with a
    paid article, a private inbox, an intranet page — and with whatever a
    hostile page decided to put in front of a machine. Three things hold:

      * the same `_gate(..., need="use")` as every other verb, so the page can
        only belong to a profile the owner put in this agent's group;
      * `_as_external_data`, so the text arrives inside the delimiters the
        system prompt already teaches the model to distrust;
      * `_READ_CAP`, so one page cannot spend the whole turn.

    It deliberately does NOT navigate. The verb that changes where the browser
    is, is browser_goto, and keeping the two apart means a page swap is always
    a thing the owner can see in the group log as its own line.
    """
    gc, groups, entry, err = _gate(action_data, context, need="use")
    if err:
        return err
    alias, profile = entry.get("alias", ""), entry["profile"]

    port = _port_for(profile)
    if not port:
        return (f'❌ Browser profile "{alias}" is not open, so there is no page to read. '
                f'Run {{"action":"browser_goto","profile":"{alias}","url":"https://…"}} first '
                f"(it opens the profile if it has to), then browser_read.")

    try:
        from .routes import proxy_preview_control
        res = await proxy_preview_control(
            int(port), "read", _BodyOnlyRequest({"limit": _READ_CAP}))
    except Exception as e:
        return f'❌ Could not read the page open in browser profile "{alias}": {_detail(e)}'
    if not isinstance(res, dict) or res.get("error"):
        why = _line((res or {}).get("error"), 300) if isinstance(res, dict) else ""
        return (f'❌ Could not read the page open in browser profile "{alias}"'
                + (f": {why}." if why else "."))

    page_url = _line(res.get("url"), 300)
    where = f" ({page_url})" if page_url else ""
    if res.get("status") != "ok":
        # The preview server says the page had nothing to give: a bot check, a
        # blank tab, a page still loading. Saying which beats an empty block.
        return (f'⚠️ Nothing readable on the page open in browser profile "{alias}"{where}: '
                f'{_line(res.get("reason"), 200) or "the page has no text"}. '
                f"The owner can look at the live view in the Browser node on the canvas.")

    text = _TEXT_CONTROL_RE.sub(" ", str(res.get("text") or "")).strip()
    if not text:
        return (f'⚠️ The page open in browser profile "{alias}"{where} came back empty. '
                f"It may still be loading — try browser_read again, or check the live view.")
    # The title goes INSIDE the block, with the body. It is free-form prose the
    # page chose, so it is exactly as much "external content" as the article is;
    # printing it in the header would be a sentence the page wrote sitting
    # OUTSIDE the delimiters that say "this is not an instruction". Only the URL
    # stays outside, as wrap_external's own source label — capped, one line, and
    # the one fact the owner needs in the group log to see where this came from.
    title = _line(res.get("title"), 200)
    whole = f"TITLE: {title}\n\n{text}" if title else text
    # _READ_CAP bounds EVERYTHING the page contributes, title included: the
    # promise is a ceiling on how much of a turn one page can spend, and a
    # ceiling with an exception is not a ceiling.
    body = whole[:_READ_CAP].strip()
    try:
        total = int(res.get("length") or len(text))
    except Exception:
        total = len(text)
    cut = ""
    if res.get("truncated") or len(whole) > _READ_CAP:
        cut = (f"\n(Only the first {_READ_CAP} characters are shown, of about {total} on the "
               f"page. Say so if you answer from a partial page.)")

    head = f'📄 Read from browser profile "{alias}".'
    return f"{head}\n{_as_external_data(body, page_url or f'browser profile {alias}')}{cut}"


async def browser_close(action_data: dict, context: dict) -> str:
    gc, groups, entry, err = _gate(action_data, context)
    if err:
        return err
    alias, profile = entry.get("alias", ""), entry["profile"]
    try:
        from .routes import StopRequest, api_stop_browser
        # force: also clears an orphaned Chrome and the Singleton lock a hard
        # kill leaves behind, otherwise the next browser_open cannot start.
        res = await api_stop_browser(StopRequest(profile=profile, force=True))
    except Exception as e:
        return f'❌ Could not close browser profile "{alias}": {_detail(e)}'
    status = (res or {}).get("status") if isinstance(res, dict) else ""
    if status == "stopped":
        return f'🛑 Closed browser profile "{alias}".'
    return f'ℹ️ Browser profile "{alias}" was not running; nothing to close.'


async def browser_upload(action_data: dict, context: dict) -> str:
    action_data = action_data or {}
    gc, groups, entry, err = _gate(action_data, context)
    if err:
        # With no group at all, "no browser profile" is only half the story:
        # this action needs the FILE in the group as well, and the file is
        # what the model was reaching for. A group that shares the file but
        # has no Browser node keeps the precise message.
        return _NO_UPLOAD_MSG if (err is _NO_PROFILE_MSG and not groups) else err

    all_files = [f for g in groups for f in (g.get("files") or []) if isinstance(f, dict)]
    ref = _line(action_data.get("file") or action_data.get("path") or action_data.get("name"), 2000)
    if not ref:
        return f'❌ Which file? Set "file" to one of: {_aliases(all_files)}.'

    resolve_file = getattr(gc, "resolve_file", None)
    if not callable(resolve_file):
        return _OLD_CORE_MSG
    try:
        fentry = resolve_file(groups, ref)
    except Exception as e:
        logger.warning(f"[browser] resolve file failed: {e}")
        return f"❌ Could not look up files in this agent's groups: {e}"
    if isinstance(fentry, dict) and fentry.get("ambiguous"):
        opts = "; ".join(f'"{c.get("alias")}" (group {c.get("group_label") or "?"})'
                         for c in fentry.get("choices") or [])
        return f'❌ "{ref}" matches more than one file: {opts}. Say which group you mean.'
    if not isinstance(fentry, dict) or not fentry.get("path"):
        # A path the model invented lands here: not shared ⇒ does not exist.
        if not all_files:
            return _NO_FILE_MSG
        # Echo the model's own words back trimmed: a 2000-character "file name"
        # in the refusal is 2000 characters of prompt it wrote itself.
        return f'❌ File "{ref[:200]}" is not shared with this agent. Shared files: {_aliases(all_files)}.'
    if not _allowed(gc, fentry.get("access") or "write", "read"):
        return (f'❌ File "{fentry.get("alias") or ref}" is shared with access '
                f'"{fentry.get("access")}"; browser_upload needs at least "read".')

    # ONLY the stored path. Whatever the model wrote was a lookup key, never
    # a file name to open.
    path = str(fentry["path"])
    if not os.path.isfile(path):
        return f'❌ File "{fentry.get("alias") or ref}" is no longer on this machine ({path}).'

    alias, profile = entry.get("alias", ""), entry["profile"]
    port = _port_for(profile)
    if not port:
        return (f'❌ Browser profile "{alias}" is not open, so there is no file dialog to '
                f"attach to. Run browser_open first, then open the page's upload dialog.")
    selector = _line(action_data.get("selector"), 200)
    # Hai đường, thử theo đúng thứ tự đó:
    #  1. Hộp thoại chọn file đang chờ — chỉ có khi vừa có NGƯỜI bấm nút trên trang.
    #     Lúc ấy trang đang đợi hộp thoại trả lời, gắn thẳng vào input sẽ để nó treo.
    #  2. Không ai bấm (agent chạy một mình, chạy theo lịch): setInputFiles gắn thẳng
    #     vào ô <input type=file>. Thiếu đường này thì "media là nguyên liệu của nhóm"
    #     chỉ dùng được khi có người ngồi canh.
    try:
        from .routes import UploadLocalRequest, api_preview_upload_local
        await api_preview_upload_local(int(port), UploadLocalRequest(paths=[path]))
        return (f'📎 Attached "{os.path.basename(path)}" to the file dialog of browser profile '
                f'"{alias}". The page can now submit it.')
    except Exception as e:
        detail = _detail(e)
        if "chooser" not in detail.lower():
            return f'❌ Could not attach "{os.path.basename(path)}" to profile "{alias}": {detail}'
    try:
        from .routes import SetInputRequest, api_preview_set_input
    except ImportError:
        # Bản browser cũ chưa có đường gắn thẳng: quay lại cách cũ, nói rõ ai phải bấm.
        return (f'❌ Profile "{alias}" has no file dialog waiting, and this server\'s browser '
                f'extension is too old to attach a file on its own. Update TubeCLI, or ask the '
                f"person watching the live view to click the page's upload button, then send "
                f'browser_upload again.')
    try:
        res = await api_preview_set_input(
            int(port), SetInputRequest(paths=[path], selector=selector or None))
    except Exception as e:
        detail = _detail(e)
        if "không có ô chọn file" in detail or "no element" in detail.lower():
            return (f'❌ The page open in profile "{alias}" has no file input '
                    f'{f"matching {selector}" if selector else "(input[type=file])"}. '
                    f'Navigate to the upload page with browser_goto first, or pass "selector".')
        return f'❌ Could not attach "{os.path.basename(path)}" to profile "{alias}": {detail}'
    where = (res or {}).get("frame") if isinstance(res, dict) else None
    return (f'📎 Attached "{os.path.basename(path)}" to the upload box of browser profile '
            f'"{alias}"' + (f' (frame {where})' if where and where != "main" else "") +
            '. The page can now submit it.')


TELEGRAM_ACTIONS = {
    "browser_open": browser_open,
    "browser_goto": browser_goto,
    "browser_read": browser_read,
    "browser_close": browser_close,
    "browser_upload": browser_upload,
}
