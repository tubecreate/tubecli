"""Group context — what a Flow Builder group shares with the agents inside it.

WHY THIS EXISTS
    A node dropped inside a group on the Flow canvas is meant to be usable by
    every agent in that group: a spreadsheet on this machine, a folder, a
    Google Sheet. The canvas knew the grouping; the server did not — so an
    agent either saw nothing, or (through the AI sandbox) saw far more than
    the owner intended.

    The cloud syncs one JSON per group into data/groups/<group_id>.json. This
    module is the only reader/writer of those files and the one place that
    answers "may this agent touch that entity, and how hard?". Extension action
    handlers (gsheet_* in auth_manager, xlsx_* in file_manager) call resolve_*
    and allows(); the chat and Telegram pipelines call prompt_block() to tell
    the model what exists. Nothing else looks at the files.

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GroupContext")

ACCESS_ORDER = {"read": 0, "append": 1, "write": 2, "manage": 3}
GROUP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

WORKLOG_TAB = "Log"
WORKLOG_HEADER = ["Time", "Agent", "Task", "Result", "Files", "Status"]

# Entities listed per kind in prompt_block. A group holding hundreds of files
# would otherwise crowd the agent's own instructions out of the prompt.
PROMPT_LIST_CAP = 20

_lock = threading.RLock()
# sheet_ids whose "Log" tab and header were verified in this process. Google
# is not asked again until restart; a row append on a missing tab fails loudly
# anyway, so the cache can only save calls, never hide a problem.
_ensured_worklogs: set = set()

_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


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


def _entries(data: Dict[str, Any], key: str) -> list:
    raw = data.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"'{key}' must be a list")
    return raw


def _normalise(group_id: str, data: Any) -> Dict[str, Any]:
    """The stored shape. Malformed ENTRIES are dropped (a file node without a
    path is simply not shareable); a malformed CONTAINER is refused, because
    that is a client bug the sync should surface rather than silently store
    an empty group for."""
    if not isinstance(data, dict):
        raise ValueError("group context must be a JSON object")

    files: List[Dict[str, Any]] = []
    for raw in _entries(data, "files"):
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            continue
        path = _str(raw.get("path"), 1000)
        if not path:
            continue
        alias = _str(raw.get("alias"), 200) or os.path.basename(path.rstrip("/\\")) or path
        ext = (_str(raw.get("ext"), 16) or os.path.splitext(path)[1]).lower().lstrip(".")
        files.append({"alias": alias, "path": path, "ext": ext,
                      "access": _norm_access(raw.get("access"), "write")})

    folders: List[Dict[str, Any]] = []
    for raw in _entries(data, "folders"):
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            continue
        path = _str(raw.get("path"), 1000)
        if not path:
            continue
        folders.append({"path": path, "access": _norm_access(raw.get("access"), "write")})

    sheets: List[Dict[str, Any]] = []
    have_worklog = False
    for raw in _entries(data, "sheets"):
        if not isinstance(raw, dict):
            continue
        sheet_id = _str(raw.get("sheet_id"), 200)
        if not sheet_id:
            continue
        # Không bao giờ lấy sheet_id làm nhãn: nhãn này đi thẳng vào prompt của model,
        # mà quy ước là model không được thấy id. Thiếu alias lẫn title thì đánh số.
        alias = _str(raw.get("alias"), 200) or _str(raw.get("title"), 200) or f"Sheet {len(out) + 1}"
        tabs = _str_list(raw.get("tabs"), 100)
        default_tab = _str(raw.get("default_tab"), 100) or (tabs[0] if tabs else "")
        role = "worklog" if _str(raw.get("role"), 20).lower() == "worklog" else ""
        if role and have_worklog:
            role = ""          # one worklog per group — the first declared wins
        have_worklog = have_worklog or bool(role)
        sheets.append({
            "alias": alias,
            "sheet_id": sheet_id,
            "url": _str(raw.get("url"), 1000),
            "cred_id": _str(raw.get("cred_id"), 200),
            "tabs": tabs,
            "default_tab": default_tab,
            "access": _norm_access(raw.get("access"), "read"),
            "role": role,
        })

    return {
        "group_id": group_id,
        "label": _str(data.get("label"), 120) or "Group",
        "updated_at": _str(data.get("updated_at"), 40),
        "agents": _str_list(data.get("agents"), 500),
        "files": files[:500],
        "folders": folders[:200],
        "sheets": sheets[:100],
    }


def load(group_id: str) -> Optional[Dict[str, Any]]:
    """The stored context, or None when there is none (or the id is bad)."""
    if not valid_group_id(group_id):
        return None
    path = os.path.join(_groups_dir(), f"{group_id}.json")
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"[Groups] unreadable {path}: {e}")
        return None
    # Re-normalised on the way in, so a file edited by hand still carries
    # every key the callers index without checking.
    try:
        return _normalise(group_id, data)
    except ValueError as e:
        logger.warning(f"[Groups] {group_id}: {e}")
        return None


def save(group_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate, normalise, write atomically. Returns what was stored."""
    path = _file_for(group_id)            # raises on a bad id
    stored = _normalise(group_id, data)
    stored["updated_at"] = _utc_now()
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    return stored


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
    """Is `have` at least `need` on read < append < write < manage?

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

_GSHEET_SYNTAX = [
    '{"action":"gsheet_read","sheet":"<alias>","tab":"Tasks","range":"A1:F50","max_rows":100}',
    '{"action":"gsheet_append","sheet":"<alias>","tab":"Log","rows":[["a","b"],["c","d"]]}',
    '{"action":"gsheet_update","sheet":"<alias>","tab":"Tasks","range":"B2:C2","values":[["x","y"]]}',
    '{"action":"gsheet_tabs","sheet":"<alias>"}',
    '{"action":"gsheet_create_tab","sheet":"<alias>","title":"Week 35"}',
]
_XLSX_SYNTAX = [
    '{"action":"xlsx_read","path":"/abs/or/~/file.xlsx","sheet":"Sheet1","max_rows":100}',
    '{"action":"xlsx_append","path":"...","sheet":"Sheet1","rows":[["a","b"]]}',
    '{"action":"xlsx_write","path":"...","sheet":"Sheet1","cells":{"A1":"v","B2":3}}',
]


def prompt_block(groups: List[Dict[str, Any]]) -> str:
    """What to tell the model. English; the pipeline appends the language rule.

    Lists ONLY what the groups contain — and only the syntax for the kinds
    present — so an agent with a single Google Sheet is not taught three
    verbs it can never use. "" when there is nothing to say.
    """
    sections: List[str] = []
    kinds: set = set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        files = g.get("files") or []
        folders = g.get("folders") or []
        sheets = g.get("sheets") or []
        if not (files or folders or sheets):
            continue
        lines = [
            f"### GROUP WORKSPACE: {g.get('label') or 'Group'}",
            "You are a member of this group. The entities below are shared with you. Nothing else is.",
        ]
        if files:
            kinds.add("xlsx")
            lines.append("Spreadsheet files on this computer (use xlsx_read / xlsx_append / xlsx_write):")
            for f in files[:PROMPT_LIST_CAP]:
                lines.append(f'- "{f.get("alias", "")}" — {f.get("path", "")} (access: {f.get("access", "write")})')
            if len(files) > PROMPT_LIST_CAP:
                lines.append(f"- …and {len(files) - PROMPT_LIST_CAP} more files (ask the user for the exact path).")
        if sheets:
            kinds.add("gsheet")
            lines.append("Google Sheets (refer to them by alias; use gsheet_read / gsheet_append / "
                         "gsheet_update / gsheet_tabs / gsheet_create_tab):")
            for s in sheets[:PROMPT_LIST_CAP]:
                tabs = ", ".join(s.get("tabs") or []) or "unknown"
                line = f'- "{s.get("alias", "")}" — tabs: {tabs} (access: {s.get("access", "read")})'
                if s.get("role") == "worklog":
                    line += (" — THIS IS THE GROUP WORKLOG: after finishing a task, "
                             f'append one row to tab "{WORKLOG_TAB}".')
                lines.append(line)
            if len(sheets) > PROMPT_LIST_CAP:
                lines.append(f"- …and {len(sheets) - PROMPT_LIST_CAP} more sheets (ask the user for the alias).")
        if folders:
            kinds.add("xlsx")
            shown = ", ".join(d.get("path", "") for d in folders[:PROMPT_LIST_CAP])
            if len(folders) > PROMPT_LIST_CAP:
                shown += f" (+{len(folders) - PROMPT_LIST_CAP} more)"
            lines.append(f"Folders: {shown}")
        sections.append("\n".join(lines))

    if not sections:
        return ""
    syntax = ["ACTION SYNTAX (reply with exactly one ```json block when you act; "
              "otherwise answer normally):"]
    if "gsheet" in kinds:
        syntax.extend(_GSHEET_SYNTAX)
    if "xlsx" in kinds:
        syntax.extend(_XLSX_SYNTAX)
    sections.append("\n".join(syntax))
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
