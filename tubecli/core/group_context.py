"""Group context — what a Flow Builder group shares with the agents inside it.

WHY THIS EXISTS
    A node dropped inside a group on the Flow canvas is meant to be usable by
    every agent in that group: a spreadsheet on this machine, a folder, a
    Google Sheet, a note with the owner's instructions. The canvas knew the
    grouping; the server did not — so an agent either saw nothing, or
    (through the AI sandbox) saw far more than the owner intended.

    The cloud syncs one JSON per group into data/groups/<group_id>.json. This
    module is the only reader/writer of those files and the one place that
    answers "may this agent touch that entity, and how hard?". Extension action
    handlers (gsheet_* in auth_manager, xlsx_* in file_manager) call resolve_*
    and allows(); the chat and Telegram pipelines call prompt_block() to tell
    the model what exists. Nothing else looks at the files.

KINDS ARE PLUGGABLE
    A group is an agent's kit of materials, and the list of materials grows
    (browser profiles, scripts, schedules…). The core therefore owns no shape
    but `notes`: every other kind is an EntityKind that an extension registers
    through Extension.get_group_kinds() — file_manager brings `files` and
    `folders`, auth_manager brings `sheets`. Adding a material is a
    registration, never an edit to this file or to the pipeline. A kind whose
    extension is disabled is silent: its entries stay on disk but are neither
    described to the model nor exposed in the merged view.

CANVAS / SERVER
    The stored file keeps two halves. `canvas` is what the cloud last synced
    and is replaced wholesale on every PUT. `server` holds what was added on
    this machine afterwards (an agent's own schedule, a skill it wrote) and
    survives the next sync. load() hands callers the merged flat view, so the
    handlers never need to know which half an entry came from.

THE RULES
    * Deny by default: an entity that is not in one of the agent's groups does
      not exist. The model addresses Google Sheets by ALIAS only — sheet ids
      and credential ids never reach the prompt; the server resolves them.
    * Paths are compared the way tubecli.core.auth compares shared files:
      realpath(normpath(abspath(expanduser()))) plus an os.sep-aware prefix,
      so "..", symlinks and /a/x vs /a/xy cannot slip through.
    * The group id becomes a file name and comes from the canvas, so it is
      checked against GROUP_ID_RE before it ever touches the filesystem.
"""
from __future__ import annotations

import datetime
import importlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("GroupContext")

# read < use/run < append < write/edit < manage. Driving something the group
# owns — a browser profile, a script — is more than looking at it and less
# than writing data into it, so `use` and `run` share the rung between read
# and append. `edit` is `write` under the name the Script node shows. Two
# spellings on one rung is deliberate: allows() compares rungs, and a kind
# should be able to name its levels the way its owner thinks about them.
ACCESS_ORDER = {"read": 0, "use": 1, "run": 1, "append": 2, "write": 3, "edit": 3, "manage": 4}
GROUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
KIND_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

WORKLOG_TAB = "Log"
WORKLOG_HEADER = ["Time", "Agent", "Task", "Result", "Files", "Status"]

# Entities listed per kind in prompt_block. A group holding hundreds of files
# would otherwise crowd the agent's own instructions out of the prompt.
PROMPT_LIST_CAP = 20
# Entries kept per registered kind and per group.
MAX_ENTRIES = 500
# A list under a key no kind claims (synced before its extension was enabled,
# or written by a newer cloud) is stored untouched — but bounded, because
# "untouched" must not become "unbounded".
VERBATIM_MAX_ENTRIES = 200
VERBATIM_MAX_BYTES = 64 * 1024
# …and per section (canvas or server) at most this many such lists, this
# many bytes in all. The per-list cap alone still let one PUT carry
# thousands of 64 KB lists, re-parsed on every chat turn.
VERBATIM_MAX_KEYS = 16
VERBATIM_SECTION_MAX_BYTES = 256 * 1024

# notes kind: one note's text, and all notes' text in one prompt.
NOTE_TEXT_CAP = 2000
NOTE_ALIAS_CAP = 40
NOTES_PROMPT_CAP = 6000
NOTES_MAX_IN_PROMPT = 30

# Top-level keys of the stored file / PUT body that are not entity lists.
RESERVED_KEYS = frozenset({"group_id", "label", "updated_at", "agents", "canvas", "server"})

ACTION_SYNTAX_HEAD = ("ACTION SYNTAX (reply with exactly one ```json block when you act; "
                      "otherwise answer normally):")

_lock = threading.RLock()
# sheet_ids whose "Log" tab and header were verified in this process. Google
# is not asked again until restart; a row append on a missing tab fails loudly
# anyway, so the cache can only save calls, never hide a problem.
_ensured_worklogs: set = set()

_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


# ── Small normalisers (shared with the kinds extensions define) ───────

def _str(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _str_list(values: Any, limit: int = 200) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out: List[str] = []
    for v in values:
        s = _str(v)
        if s and s not in out:
            out.append(s)
    return out[:limit]


def _norm_access(value: Any, default: str) -> str:
    v = _str(value, 20).lower()
    return v if v in ACCESS_ORDER else default


# Public names for the extensions that define kinds, so every kind trims and
# validates the same way without copying these helpers.
norm_str = _str
norm_str_list = _str_list
norm_access = _norm_access


# ── Entity kinds ─────────────────────────────────────────────────────

@dataclass
class EntityKind:
    """One kind of material a group can hold.

    normalise(raw_entry, index) turns what the canvas sent into the stored
    entry, or returns None to drop it (a file node without a path is simply
    not shareable). describe(entries) returns the prompt lines for a group's
    entries of this kind and MUST NOT include ids or credentials — the model
    works by alias. action_docs(entries) returns the JSON syntax lines the
    model needs for these entries; they are pooled and de-duplicated across
    groups and kinds, and only kinds with entries are asked. `identity` names
    the entry field that makes two entries the same thing (path for files,
    sheet_id for sheets, alias otherwise) — add_server_entry replaces rather
    than duplicates on it. `finalise` is an optional whole-list pass after the
    per-entry step, for rules that span entries (sheets: one worklog per group).
    """
    key: str
    label: str
    normalise: Callable[[Any, int], Optional[Dict[str, Any]]]
    describe: Callable[[List[Dict[str, Any]]], List[str]]
    action_docs: Callable[[List[Dict[str, Any]]], List[str]] = lambda entries: []
    access_default: str = "read"
    order: int = 100
    identity: str = "alias"
    finalise: Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]] = None

    def __post_init__(self):
        # The key becomes a JSON key in the stored file and a list key in the
        # manifest; a key that collides with the container fields would make
        # "agents" an entity list and break every reader.
        if not isinstance(self.key, str) or not KIND_KEY_RE.match(self.key) or self.key in RESERVED_KEYS:
            raise ValueError(f"invalid kind key: {self.key!r}")
        if not callable(self.normalise) or not callable(self.describe) or not callable(self.action_docs):
            raise ValueError(f"kind {self.key!r}: normalise/describe/action_docs must be callable")
        self.access_default = _norm_access(self.access_default, "read")


_kinds: Dict[str, EntityKind] = {}
# Keys unregistered on purpose (their extension was disabled). ensure_default_kinds
# must not bring these back, otherwise "disabled" would last until the next prompt.
_withdrawn: set = set()

# The built-in kinds and the module that defines each. Registered lazily by
# ensure_default_kinds() because the chat pipeline and the tests may call
# prompt_block()/save() before the extension manager has loaded anything.
DEFAULT_KIND_OWNERS = {
    "files": "tubecli.extensions.file_manager.extension",
    "folders": "tubecli.extensions.file_manager.extension",
    "sheets": "tubecli.extensions.auth_manager.extension",
}


def register_kind(kind: EntityKind) -> None:
    """Idempotent by key: registering a key again replaces the earlier kind."""
    if not isinstance(kind, EntityKind):
        raise TypeError("register_kind expects an EntityKind")
    with _lock:
        _kinds[kind.key] = kind
        _withdrawn.discard(kind.key)


def unregister_kind(key: str) -> None:
    with _lock:
        _kinds.pop(key, None)
        _withdrawn.add(key)


def kinds() -> List[EntityKind]:
    """Registered kinds in prompt order (order, then key)."""
    return sorted(_kinds.values(), key=lambda k: (k.order, k.key))


def kind(key: str) -> Optional[EntityKind]:
    return _kinds.get(key)


def ensure_default_kinds() -> None:
    """Register the built-in kinds whose extension module can be imported.

    Only kinds that were never registered are tried; a key that an extension
    withdrew stays withdrawn. The import is cached by Python, so after the
    first call this is an attribute lookup per missing key.
    """
    missing = [k for k in DEFAULT_KIND_OWNERS if k not in _kinds and k not in _withdrawn]
    if not missing:
        return
    for module_name in dict.fromkeys(DEFAULT_KIND_OWNERS[k] for k in missing):
        try:
            mod = importlib.import_module(module_name)
            for k in getattr(mod, "GROUP_KINDS", None) or []:
                if isinstance(k, EntityKind) and k.key not in _kinds and k.key not in _withdrawn:
                    register_kind(k)
        except Exception as e:
            logger.warning(f"[Groups] default kinds from {module_name} unavailable: {e}")


# ── Built-in kind: notes (the group's playbook) ──────────────────────

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _one_line(value, cap: int) -> str:
    """Một dòng, không ký tự điều khiển: alias được in ở cột 0 của prompt, nên một
    alias nhiều dòng có thể giả làm tiêu đề mục hệ thống ("### ACTION SYNTAX")."""
    text = _CONTROL_RE.sub("", str(value or "")).replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())[:cap]


def _note_alias(text: str, index: int) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:NOTE_ALIAS_CAP]
    return f"Note {index + 1}"


def _note_normalise(raw: Any, index: int) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text).strip()
    if not text:
        return None
    if len(text) > NOTE_TEXT_CAP:
        text = text[:NOTE_TEXT_CAP].rstrip() + " …[truncated]"
    return {"alias": _one_line(raw.get("alias"), 120) or _note_alias(text, index), "text": text}


def _notes_describe(entries: List[Dict[str, Any]]) -> List[str]:
    lines = ["GROUP PLAYBOOK (written by the owner — follow it):"]
    used = 0
    for i, n in enumerate(entries):
        text = str(n.get("text") or "")
        alias = _one_line(n.get("alias"), NOTE_ALIAS_CAP) or "Note"
        # Ngân sách tính cả dòng alias, và chặn số lượng: nhiều ghi chú ngắn cũng
        # không được lách cap. Ghi chú đầu luôn in (đã cap riêng ở normalise).
        cost = len(text) + len(alias) + 4
        if i and (used + cost > NOTES_PROMPT_CAP or i >= NOTES_MAX_IN_PROMPT):
            lines.append("(more notes omitted)")
            break
        used += cost
        lines.append(f"• {alias}:")
        lines.extend("  " + ln for ln in text.splitlines())
    return lines


NOTES_KIND = EntityKind(
    key="notes", label="Playbook", normalise=_note_normalise, describe=_notes_describe,
    access_default="read", order=10, identity="alias",
)
register_kind(NOTES_KIND)


# ── Storage ──────────────────────────────────────────────────────────

def _groups_dir() -> str:
    # Imported late, like auth.py does, so a test (or a future workspace
    # switch) that rebinds tubecli.config.DATA_DIR is honoured.
    from tubecli.config import DATA_DIR

    return os.path.join(str(DATA_DIR), "groups")


def valid_group_id(group_id: Any) -> bool:
    return isinstance(group_id, str) and bool(GROUP_ID_RE.match(group_id))


def _file_for(group_id: str) -> str:
    if not valid_group_id(group_id):
        raise ValueError(f"invalid group_id: {group_id!r}")
    return os.path.join(_groups_dir(), f"{group_id}.json")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_raw(path: str) -> Optional[Dict[str, Any]]:
    """The file as written, or None when absent/unreadable."""
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"[Groups] unreadable {path}: {e}")
        return None
    return data if isinstance(data, dict) else None


def _write(path: str, stored: Dict[str, Any]) -> None:
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def _cap_verbatim(values: list, budget: int = VERBATIM_MAX_BYTES) -> Tuple[list, int]:
    """The longest prefix of `values` (at most VERBATIM_MAX_ENTRIES entries)
    whose JSON form fits in `budget` bytes, and that size.

    Measured entry by entry in one pass. The earlier pop-and-re-dump loop
    serialised the whole list once per dropped entry — O(n²), around a
    gigabyte of json.dumps for a single 200 × 64 KB list — on the one path
    where the body is whatever the caller chose to send.
    """
    out: list = []
    used = 2                                    # "[" and "]"
    for v in values[:VERBATIM_MAX_ENTRIES]:
        size = len(json.dumps(v, ensure_ascii=False).encode("utf-8")) + (2 if out else 0)  # ", "
        if used + size > budget:
            break
        used += size
        out.append(v)
    return out, used


def _normalise_kind(k: EntityKind, raw_list: list) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_list):
        try:
            entry = k.normalise(raw, i)
        except Exception as e:
            # One odd entry costs itself, not the group: a kind's bug must not
            # make the whole manifest unloadable.
            logger.warning(f"[Groups] kind '{k.key}' rejected entry #{i}: {e}")
            entry = None
        if isinstance(entry, dict):
            out.append(entry)
        if len(out) >= MAX_ENTRIES:
            break
    if k.finalise is not None:
        try:
            out = list(k.finalise(out))
        except Exception as e:
            logger.warning(f"[Groups] kind '{k.key}' finalise failed: {e}")
    return out


def _normalise_section(data: Dict[str, Any]) -> Dict[str, Any]:
    """One half (canvas or server): registered kinds normalised; any other
    list under a kind-shaped key kept verbatim, bounded. A registered key
    holding a non-list is refused — that is a client bug the sync should
    surface rather than silently store an empty group for."""
    out: Dict[str, Any] = {}
    for k in kinds():
        raw = data.get(k.key)
        if raw is None:
            out[k.key] = []
            continue
        if not isinstance(raw, list):
            raise ValueError(f"'{k.key}' must be a list")
        out[k.key] = _normalise_kind(k, raw)
    # Verbatim lists: only under a key a kind could ever claim (EntityKind
    # refuses anything else, so "" or a 100 KB key would sit on disk for
    # nothing), and bounded in number and total size as well as per list —
    # what is stored here is re-read on every chat turn.
    kept_keys = 0
    used = 0
    for key, raw in data.items():
        if not isinstance(key, str) or key in RESERVED_KEYS or key in out:
            continue
        if not KIND_KEY_RE.match(key) or not isinstance(raw, list):
            continue
        if kept_keys >= VERBATIM_MAX_KEYS or used >= VERBATIM_SECTION_MAX_BYTES:
            logger.warning(f"[Groups] verbatim lists cut at '{key}': "
                           f"{VERBATIM_MAX_KEYS} keys / {VERBATIM_SECTION_MAX_BYTES} bytes per section")
            break
        out[key], size = _cap_verbatim(raw, min(VERBATIM_MAX_BYTES, VERBATIM_SECTION_MAX_BYTES - used))
        kept_keys += 1
        used += size
    return out


def _build(group_id: str, raw: Any) -> Dict[str, Any]:
    """The stored shape from either form on disk: the phase-1 flat file (the
    whole dict is the canvas) or the canvas/server split."""
    if not isinstance(raw, dict):
        raise ValueError("group context must be a JSON object")
    canvas_raw = raw["canvas"] if isinstance(raw.get("canvas"), dict) else raw
    server_raw = raw["server"] if isinstance(raw.get("server"), dict) else {}
    canvas: Dict[str, Any] = {"agents": _str_list(canvas_raw.get("agents"), 500)}
    canvas.update(_normalise_section(canvas_raw))
    return {
        "group_id": group_id,
        # _one_line, not _str: prompt_block prints the label right after
        # "### GROUP WORKSPACE: " at column 0, so a label with a newline in it
        # forged a second section heading — and every line after it — inside
        # the model's prompt. Aliases are sanitised for that reason already.
        "label": _one_line(raw.get("label"), 120) or "Group",
        "updated_at": _str(raw.get("updated_at"), 40),
        "canvas": canvas,
        "server": _normalise_section(server_raw),
    }


def _view(stored: Dict[str, Any]) -> Dict[str, Any]:
    """The merged flat view every caller works on: per registered kind, canvas
    entries then server entries (the latter tagged source="server"), plus the
    two halves for callers that need the split. Unregistered lists stay inside
    the halves only — un-normalised entries must not reach the handlers."""
    canvas = stored["canvas"]
    server = stored["server"]
    view: Dict[str, Any] = {
        "group_id": stored["group_id"],
        "label": stored["label"],
        "updated_at": stored["updated_at"],
        "agents": list(canvas.get("agents") or []),
    }
    for k in kinds():
        merged = [dict(e) for e in canvas.get(k.key) or []]
        merged.extend(dict(e, source="server") for e in server.get(k.key) or [])
        # Luat xuyen-muc (sheets: mot nhat ky/nhom) da chay rieng cho tung nua;
        # gop hai nua lai thi phai chay lai, neu khong moi nua gop mot nhat ky.
        if k.finalise is not None and merged:
            try:
                merged = list(k.finalise(merged))
            except Exception as e:
                logger.warning(f"[Groups] kind '{k.key}' finalise (merged view) failed: {e}")
        view[k.key] = merged
    view["canvas"] = canvas
    view["server"] = server
    return view


def load(group_id: str) -> Optional[Dict[str, Any]]:
    """The merged context (see _view), or None when there is none (or the id is bad)."""
    if not valid_group_id(group_id):
        return None
    raw = _read_raw(os.path.join(_groups_dir(), f"{group_id}.json"))
    if raw is None:
        return None
    ensure_default_kinds()
    # Re-normalised on the way in, so a file edited by hand still carries
    # every key the callers index without checking.
    try:
        return _view(_build(group_id, raw))
    except ValueError as e:
        logger.warning(f"[Groups] {group_id}: {e}")
        return None


def save(group_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the canvas half with the manifest the cloud sent; keep the
    server half. Validates, normalises, writes atomically. Returns the merged
    view of what was stored."""
    path = _file_for(group_id)            # raises on a bad id
    if not isinstance(data, dict):
        raise ValueError("group context must be a JSON object")
    ensure_default_kinds()
    body = data["canvas"] if isinstance(data.get("canvas"), dict) else data
    # A merged view echoed back (GET then PUT) carries the server entries
    # tagged source="server"; they belong to the other half and would
    # otherwise be duplicated into the canvas on every round trip.
    body = {key: ([e for e in v if not (isinstance(e, dict) and e.get("source") == "server")]
                  if isinstance(v, list) else v)
            for key, v in body.items()}
    with _lock:
        previous = _read_raw(path) or {}
        stored = _build(group_id, {"label": data.get("label"), "canvas": body,
                                   "server": previous.get("server")})
        stored["updated_at"] = _utc_now()
        _write(path, stored)
    return _view(stored)


def _path_key(value: Any) -> str:
    r"""Comparable form of a path: the same canonical form resolve_xlsx uses,
    plus normcase so C:\X and c:\x meet on Windows while POSIX paths stay
    case-sensitive. "" when there is nothing usable to compare."""
    raw = _str(value, 2000)
    if not raw:
        return ""
    try:
        return os.path.normcase(_canon(raw))
    except Exception:
        return ""


def _entry_identity(identity: str, entry: Dict[str, Any]) -> str:
    """What makes two entries the same thing, as one comparable string.

    The kind names the field (path for files, sheet_id for sheets, profile
    for browser profiles, alias otherwise). An entry that has nothing under
    that field is only ever equal to itself — hence the whole-entry dump.
    """
    value = _str(entry.get(identity), 2000)
    if not value:
        return json.dumps(entry, sort_keys=True, ensure_ascii=False)
    if identity == "path":
        return _path_key(value) or value
    return value.casefold()


def _identity(k: EntityKind, entry: Dict[str, Any]) -> str:
    return _entry_identity(k.identity, entry)


def add_server_entry(group_id: str, kind_key: str, entry: Any) -> Dict[str, Any]:
    """Add (or replace, by the kind's identity) one entry in the server half.

    Raises ValueError for an unknown kind or an entry the kind rejects, and
    LookupError when the group has no file yet — the canvas creates groups,
    the server only adds to them.
    """
    path = _file_for(group_id)
    ensure_default_kinds()
    k = kind(kind_key)
    if k is None:
        raise ValueError(f"unknown kind: {kind_key!r}")
    with _lock:
        raw = _read_raw(path)
        if raw is None:
            raise LookupError(f"group not found: {group_id}")
        stored = _build(group_id, raw)
        entries: List[Dict[str, Any]] = list(stored["server"].get(k.key) or [])
        new = k.normalise(entry, len(entries))
        if not isinstance(new, dict):
            raise ValueError(f"entry rejected by kind '{k.key}'")
        ident = _identity(k, new)
        entries = [e for e in entries if _identity(k, e) != ident] + [new]
        if k.finalise is not None:
            entries = list(k.finalise(entries))
        stored["server"][k.key] = entries[:MAX_ENTRIES]
        stored["updated_at"] = _utc_now()
        _write(path, stored)
    return dict(new, source="server")


def remove_server_entry(group_id: str, kind_key: str,
                        predicate: Callable[[Dict[str, Any]], bool]) -> int:
    """Drop the server entries of a kind that `predicate` matches. Returns how
    many were removed; 0 when the group does not exist (idempotent)."""
    path = _file_for(group_id)
    ensure_default_kinds()
    k = kind(kind_key)
    if k is None:
        raise ValueError(f"unknown kind: {kind_key!r}")
    with _lock:
        raw = _read_raw(path)
        if raw is None:
            return 0
        stored = _build(group_id, raw)
        entries = list(stored["server"].get(k.key) or [])
        keep = [e for e in entries if not predicate(e)]
        removed = len(entries) - len(keep)
        if removed:
            stored["server"][k.key] = keep
            stored["updated_at"] = _utc_now()
            _write(path, stored)
    return removed


def delete(group_id: str) -> bool:
    """Idempotent: True when a file was removed, False when there was none."""
    if not valid_group_id(group_id):
        return False
    path = os.path.join(_groups_dir(), f"{group_id}.json")
    with _lock:
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"[Groups] could not delete {path}: {e}")
            return False


def list_all() -> List[Dict[str, Any]]:
    d = _groups_dir()
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning(f"[Groups] cannot list {d}: {e}")
        return []
    out: List[Dict[str, Any]] = []
    for name in names:
        if not name.endswith(".json"):
            continue
        ctx = load(name[:-5])
        if ctx is not None:
            out.append(ctx)
    return out


def groups_for_agent(agent_id: str) -> List[Dict[str, Any]]:
    aid = _str(agent_id)
    if not aid:
        return []
    return [g for g in list_all() if aid in (g.get("agents") or [])]


def effective_groups(agent_id: str, group_id: str = "") -> List[Dict[str, Any]]:
    """[that group] when one is named, exists AND lists the agent; [] when one
    is named but does not; the union of the agent's groups when none is named.

    The canvas chat names the group of the node that sent the message;
    Telegram and scheduled runs have no node, hence the union. A named group
    is never taken on its name alone, because the name can outlive the
    membership: a chat session remembers the group its node was in, and the
    manifest synced after the owner dragged the node out no longer lists the
    agent — the manifest is the owner's word, the session is not. Nor does a
    name that has no file (a group the canvas has not synced yet, a failed
    PUT) widen the turn to the union: the user is chatting inside ONE group,
    and handing that turn every other group's sheets is the opposite of
    deny by default.
    """
    gid = _str(group_id, 64)
    if gid:
        g = load(gid)
        if g is None or _str(agent_id) not in (g.get("agents") or []):
            return []
        return [g]
    return groups_for_agent(agent_id)


# ── Permission + resolution ──────────────────────────────────────────

def allows(have: str, need: str) -> bool:
    """Is `have` at least `need` on read < use/run < append < write/edit < manage?

    An unknown value on EITHER side is a refusal: a missing access on an entry
    must not grant, and a typo in a handler's requirement must not grant.
    """
    h = ACCESS_ORDER.get(_str(have, 20).lower())
    n = ACCESS_ORDER.get(_str(need, 20).lower())
    if h is None or n is None:
        return False
    return h >= n


def _better(current: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """When the same entity sits in two groups, the union grants the wider access."""
    if current is None:
        return candidate
    if ACCESS_ORDER.get(candidate.get("access", ""), -1) > ACCESS_ORDER.get(current.get("access", ""), -1):
        return candidate
    return current


def resolve_sheet(groups: List[Dict[str, Any]], ref: str) -> Optional[Dict[str, Any]]:
    """The sheet entry `ref` names, or None.

    `ref` is what the model wrote: the alias (compared case-insensitively,
    trimmed), or — because users paste links — the raw sheet id or a URL that
    contains it. The returned dict is the stored entry plus `group_id` and
    `group_label`, so a handler can say which group granted it.
    """
    key = _str(ref, 2000)
    if not key:
        return None
    folded = key.casefold()
    m = _SHEET_URL_RE.search(key)
    url_id = m.group(1) if m else None

    best: Optional[Dict[str, Any]] = None
    distinct: Dict[str, Dict[str, Any]] = {}
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for s in g.get("sheets") or []:
            sid = _str(s.get("sheet_id"), 200)
            alias = _str(s.get("alias"), 200).casefold()
            if not ((alias and alias == folded) or (sid and sid in (key, url_id))):
                continue
            cand = dict(s)
            cand["group_id"] = g.get("group_id", "")
            cand["group_label"] = g.get("label", "")
            distinct.setdefault(sid or alias, cand)
            best = _better(best, cand)
    # Cùng một tên trỏ tới HAI bảng khác nhau (agent ở nhiều nhóm): chọn thầm bảng
    # "rộng quyền hơn" là ghi nhầm chỗ. Trả về dấu hiệu mơ hồ để handler hỏi lại,
    # kèm nhãn nhóm để model phân biệt được.
    if len(distinct) > 1:
        return {
            "ambiguous": True,
            "choices": [{"alias": c.get("alias", ""), "group_label": c.get("group_label", "")}
                        for c in distinct.values()],
        }
    return best


def _canon(path_str: str) -> str:
    """Same canonical form auth._canon_fs uses: normalise FIRST, then resolve
    symlinks — the order the file routes actually open paths in. Resolving
    the other way round lets a symlink that points inward admit a path that
    is really outside."""
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(path_str))))
    return os.path.realpath(normalized)


def canon_path(path_str: str) -> str:
    """_canon for callers outside this module; "" instead of an exception."""
    try:
        return _canon(path_str) if _str(path_str, 2000) else ""
    except Exception:
        return ""


def resolve_xlsx(groups: List[Dict[str, Any]], path: str) -> Optional[Dict[str, Any]]:
    """The file entry `path` matches (exact) or the folder entry containing it
    (prefix), as {"path": <canonical absolute path>, "access": ..., ...}.

    None when no group shares it — which, for the handlers, means the file
    does not exist. `~` expands to the user's home in both the request and
    the stored entries. A folder entry that is a filesystem root shares the
    whole machine and is never honoured.
    """
    raw = _str(path, 2000)
    if not raw:
        return None
    try:
        rp = _canon(raw)
    except Exception:
        return None

    best: Optional[Dict[str, Any]] = None
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        gid = g.get("group_id", "")
        for f in g.get("files") or []:
            fp = _str(f.get("path"), 1000)
            if not fp or not os.path.isabs(os.path.expanduser(fp)):
                continue
            try:
                if _canon(fp) != rp:
                    continue
            except Exception:
                continue
            best = _better(best, {
                "path": rp, "access": f.get("access", "write"), "alias": f.get("alias", ""),
                "ext": f.get("ext", ""), "group_id": gid, "via": "file",
            })
        for d in g.get("folders") or []:
            dp = _str(d.get("path"), 1000)
            if not dp or not os.path.isabs(os.path.expanduser(dp)):
                continue
            try:
                rd = _canon(dp)
            except Exception:
                continue
            if not rd or os.path.dirname(rd) == rd:
                continue                  # "/" or "C:\" — the whole machine
            base = rd.rstrip(os.sep)
            # Prefix joined with os.sep so /a/x does not admit /a/xy.
            if rp == base or rp.startswith(base + os.sep):
                best = _better(best, {
                    "path": rp, "access": d.get("access", "write"), "folder": rd,
                    "group_id": gid, "via": "folder",
                })
    return best


def _kind_identity(kind_key: str) -> str:
    """The field the registered kind compares entries on.

    A kind nobody registered can still be asked for: load() keeps its entries
    out of the merged view, so this only happens for scopes a caller built by
    hand (tests, a handler assembling its own groups). Alias is the safe
    fallback — every kind has one, and it never grants more than the name.
    """
    k = kind(kind_key)
    return k.identity if k is not None else "alias"


def _stamped(entry: Dict[str, Any], group: Dict[str, Any]) -> Dict[str, Any]:
    """The stored entry plus which group granted it, so a handler can say so."""
    out = dict(entry)
    out["group_id"] = group.get("group_id", "")
    out["group_label"] = group.get("label", "")
    return out


def _ambiguous(candidates) -> Dict[str, Any]:
    """The same shape resolve_sheet returns: names and group labels only —
    an id must not leak through a refusal either."""
    return {
        "ambiguous": True,
        "choices": [{"alias": c.get("alias", ""), "group_label": c.get("group_label", "")}
                    for c in candidates],
    }


def resolve_entry(groups: List[Dict[str, Any]], kind_key: str, ref: str) -> Optional[Dict[str, Any]]:
    """The entry of `kind_key` that `ref` names, or None.

    `ref` is what the model wrote: the ALIAS first (that is what prompt_block
    taught it, and the comparison is trimmed + casefolded), then the kind's
    identity value — a profile name, a script id, a path — compared exactly,
    because an id that differs only in case is a different id. The result is
    the stored entry plus `group_id` and `group_label`.

    One name, two different entities (the agent is in several groups) is
    never resolved silently: {"ambiguous": True, "choices": [...]} comes back
    instead, exactly as resolve_sheet does, so the handler can ask which one.
    """
    key = _str(kind_key, 64)
    if not key:
        return None
    ensure_default_kinds()
    if key == "sheets":
        # Sheets keep their own resolver: people paste a whole spreadsheet
        # URL, and the id inside it still has to match.
        return resolve_sheet(groups, ref)
    raw = _str(ref, 2000)
    if not raw:
        return None
    folded = raw.casefold()
    identity = _kind_identity(key)
    want_path = _path_key(raw) if identity == "path" else ""

    best: Optional[Dict[str, Any]] = None
    distinct: Dict[str, Dict[str, Any]] = {}
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for e in g.get(key) or []:
            if not isinstance(e, dict):
                continue
            alias = _str(e.get("alias"), 200).casefold()
            value = _str(e.get(identity), 2000)
            hit = bool(alias) and alias == folded
            if not hit and value:
                if identity == "path":
                    hit = bool(want_path) and _path_key(value) == want_path
                else:
                    hit = value == raw
            if not hit:
                continue
            cand = _stamped(e, g)
            distinct.setdefault(_entry_identity(identity, e), cand)
            best = _better(best, cand)
    if len(distinct) > 1:
        return _ambiguous(distinct.values())
    return best


def only_entry(groups: List[Dict[str, Any]], kind_key: str) -> Optional[Dict[str, Any]]:
    """The single entry of this kind in scope, or None when there are none or
    several — what lets a handler act on "the group's browser profile" when
    the model named none.

    The same entity shared by two groups still counts as one (compared on the
    kind's identity) and comes back with the wider access. Two different ones
    are a question for the user, so None is the only safe answer.
    """
    key = _str(kind_key, 64)
    if not key:
        return None
    ensure_default_kinds()
    identity = _kind_identity(key)
    found: Dict[str, Dict[str, Any]] = {}
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for e in g.get(key) or []:
            if not isinstance(e, dict):
                continue
            ident = _entry_identity(identity, e)
            found[ident] = _better(found.get(ident), _stamped(e, g))
            if len(found) > 1:
                return None
    if len(found) != 1:
        return None
    return next(iter(found.values()))


def _abs_canon(value: Any) -> str:
    """A shared path an action may act on: absolute (after ~), canonical. ""
    for anything else — a relative entry would resolve against whatever
    directory the server happens to run in."""
    raw = _str(value, 1000)
    if not raw or not os.path.isabs(os.path.expanduser(raw)):
        return ""
    try:
        return _canon(raw)
    except Exception:
        return ""


def _looks_like_path(ref: str) -> bool:
    return ref.startswith("~") or "/" in ref or "\\" in ref or os.path.isabs(ref)


def resolve_file(groups: List[Dict[str, Any]], ref: str) -> Optional[Dict[str, Any]]:
    """Any file the groups share — of any type, not just workbooks — named by
    alias or by path, as an entry whose `path` is absolute and canonical.

    Alias first, because that is how the prompt lists file nodes. A path is
    accepted too: a model that just read a listing will paste one, and a file
    that lives inside a shared FOLDER has no entry of its own — resolve_xlsx
    already knows that rule (realpath + os.sep prefix) and is reused for it.
    Handlers must upload/open the path THIS returns and never the string the
    model sent; that substitution is the whole boundary.

    None when no group shares it, {"ambiguous": True, ...} when one alias
    names two different files.
    """
    raw = _str(ref, 2000)
    if not raw:
        return None
    entry = resolve_entry(groups, "files", raw)
    if isinstance(entry, dict) and entry.get("ambiguous"):
        return entry
    if isinstance(entry, dict):
        path = _abs_canon(entry.get("path"))
        if path:
            out = dict(entry)
            out["path"] = path
            out["access"] = entry.get("access") or "write"
            out.setdefault("via", "file")
            return out
        # An entry whose path is unusable is not a hit; the folder rule below
        # may still cover the same file.
    if not _looks_like_path(raw):
        return None
    hit = resolve_xlsx(groups, raw)
    if not hit:
        return None
    out = dict(hit)
    gid = out.get("group_id", "")
    for g in groups or []:
        if isinstance(g, dict) and g.get("group_id") == gid:
            out["group_label"] = g.get("label", "")
            break
    out.setdefault("group_label", "")
    return out


def worklog_sheet(groups: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first sheet marked as worklog across the groups, with `group_id`."""
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        for s in g.get("sheets") or []:
            if s.get("role") == "worklog" and s.get("sheet_id"):
                out = dict(s)
                out["group_id"] = g.get("group_id", "")
                return out
    return None


# ── Prompt ───────────────────────────────────────────────────────────

def prompt_block(groups: List[Dict[str, Any]]) -> str:
    """What to tell the model. English; the pipeline appends the language rule.

    Per group: the header, then each registered kind that has entries, in
    kind order (playbook first). Then ONE action-syntax section: the union of
    what the kinds with entries asked for — so an agent with a single Google
    Sheet is not taught three verbs it can never use. Kinds nobody registered
    are silent. "" when there is nothing to say.
    """
    ensure_default_kinds()
    sections: List[str] = []
    docs: List[str] = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        present = [(k, g.get(k.key)) for k in kinds()
                   if isinstance(g.get(k.key), list) and g.get(k.key)]
        if not present:
            continue
        lines = [
            f"### GROUP WORKSPACE: {g.get('label') or 'Group'}",
            "You are a member of this group. The entities below are shared with you. Nothing else is.",
        ]
        for k, entries in present:
            try:
                lines.extend(str(ln) for ln in k.describe(entries))
            except Exception as e:
                # The prompt survives a broken kind; the kind's entries are
                # simply not described this turn.
                logger.warning(f"[Groups] kind '{k.key}' describe failed: {e}")
                continue
            try:
                for d in k.action_docs(entries):
                    if d not in docs:
                        docs.append(str(d))
            except Exception as e:
                logger.warning(f"[Groups] kind '{k.key}' action_docs failed: {e}")
        sections.append("\n".join(lines))

    if not sections:
        return ""
    if docs:
        sections.append("\n".join([ACTION_SYNTAX_HEAD] + docs))
    return "\n\n".join(sections)


# ── Worklog ──────────────────────────────────────────────────────────

def _cell(text: Any, limit: int) -> str:
    """One line, trimmed: a multi-line reply would turn a log row into a wall."""
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _ensure_log_tab(gsheets, cred_id: str, sheet_id: str) -> None:
    if sheet_id in _ensured_worklogs:
        return
    try:
        gsheets.ensure_header(cred_id, sheet_id, WORKLOG_TAB, WORKLOG_HEADER)
    except Exception:
        # The client may refuse a tab that does not exist yet; create it and
        # write the header. Any other failure re-raises from the second call.
        gsheets.create_tab(cred_id, sheet_id, WORKLOG_TAB)
        gsheets.ensure_header(cred_id, sheet_id, WORKLOG_TAB, WORKLOG_HEADER)
    _ensured_worklogs.add(sheet_id)


def _append_worklog(sheet: Dict[str, Any], row: List[str]) -> None:
    # import_module, not `from … import`: the package __init__ instantiates
    # the extension, and import_module returns a cached module straight from
    # sys.modules without touching the parent — which is what lets a test
    # substitute the client.
    try:
        gsheets = importlib.import_module("tubecli.extensions.auth_manager.gsheets")
    except Exception as e:
        logger.warning(f"[Groups] worklog skipped — gsheets client unavailable: {e}")
        return
    cred_id = sheet.get("cred_id", "")
    sheet_id = sheet.get("sheet_id", "")
    try:
        _ensure_log_tab(gsheets, cred_id, sheet_id)
        gsheets.append(cred_id, sheet_id, WORKLOG_TAB, [row])
    except Exception as e:
        logger.warning(f"[Groups] worklog append failed for '{sheet.get('alias')}': {e}")


def record_worklog(groups: List[Dict[str, Any]], agent_dict: Dict[str, Any], task: str,
                   result: str, artifacts: List[str], status: str) -> None:
    """Append one row to the groups' worklog sheet. Fire-and-forget.

    Runs on a daemon thread and never raises: the reply the user is waiting
    for must not wait on Google, and a sheet problem is a warning in the log,
    not an error in the chat.
    """
    try:
        sheet = worklog_sheet(groups)
        if not sheet:
            return
        agent = agent_dict if isinstance(agent_dict, dict) else {}
        row = [
            datetime.datetime.now().replace(microsecond=0).isoformat(),
            _str(agent.get("name"), 80) or _str(agent.get("id"), 80),
            _cell(task, 120),
            _cell(result, 200),
            _cell("; ".join(str(a) for a in (artifacts or []) if a), 200),
            _str(status, 20) or "done",
        ]
        threading.Thread(target=_append_worklog, args=(sheet, row),
                         daemon=True, name="group-worklog").start()
    except Exception as e:
        logger.warning(f"[Groups] worklog skipped: {e}")
