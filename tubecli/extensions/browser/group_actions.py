"""Browser profiles as group material, and the four actions that drive them.

WHY THIS FILE EXISTS
    A Browser node dropped inside a Flow Builder group is the owner saying
    "this agent may drive this profile". tubecli.core.group_context keeps the
    registry of what a group can hold; the SHAPE of a browser profile belongs
    here, next to the handlers that consume it, so adding a material stays a
    registration and never becomes a core edit (same arrangement as `sheets`
    in auth_manager and `files` in file_manager).

    The chain the owner is after — the agent opens the group's profile, goes
    to a page, attaches the group's file, closes the profile — only holds if
    every step is checked on the server. So:

    * The model addresses a profile by ALIAS. The profile name, the port and
      the file path stay on this side; a prompt-injected reply cannot name a
      profile the owner did not share, because it never learns one exists.
    * Deny by default: no group ⇒ no profile ⇒ refusal with a sentence that
      tells the owner what to do on the canvas.
    * browser_upload attaches ONLY the path stored in the group entry. A path
      the model wrote is never opened — that is the whole point of the entry.
    * Only http/https, and never back into this machine's own ports: the
      browser runs here, with the owner's cookies, one hop from the API.

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


def _profiles_describe(entries) -> list:
    lines = ["Browser profiles you may drive (use browser_open / browser_goto / "
             "browser_close / browser_upload):"]
    for p in entries[:_PROMPT_LIST_CAP]:
        line = f'- "{p.get("alias", "")}"'
        access = str(p.get("access") or "use")
        # "use" is the norm and saying so on every line only spends prompt;
        # anything else is worth the model knowing.
        if access != "use":
            line += f" (access: {access})"
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
            f"Use browser_goto to navigate, browser_upload to attach a file from the group, "
            f"browser_close when you are done.")


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
        return f'🌐 Browser profile "{alias}" was not open — opened it at {url}.'

    try:
        from .routes import proxy_preview_control
        res = await proxy_preview_control(int(port), "navigate", _BodyOnlyRequest({"url": url}))
    except Exception as e:
        return f'❌ Could not navigate profile "{alias}" to {url}: {_detail(e)}'
    if isinstance(res, dict) and res.get("error"):
        return f'❌ Profile "{alias}" could not load {url}: {_line(res.get("error"), 300)}'
    landed = _line((res or {}).get("url"), 500) if isinstance(res, dict) else ""
    return f'🌐 Browser profile "{alias}" is now at {landed or url}.'


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
    "browser_close": browser_close,
    "browser_upload": browser_upload,
}
