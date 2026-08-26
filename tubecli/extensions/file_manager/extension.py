"""
File Manager Extension — Quản lý file/folder cho AI agents và WebUI.
Cung cấp API tạo, xóa, di chuyển, sao chép file/folder.
"""
import asyncio
import logging
import os
from tubecli.core.extension_manager import Extension

logger = logging.getLogger("FileManagerExtension")

# ── Group kinds: what a File / Folder node on the Flow canvas shares ──────
# tubecli.core.group_context owns the kind registry and only the `notes`
# kind; the shapes of `files` and `folders` live here, next to the xlsx_*
# handlers that consume them, so the next material is a registration, never
# a core edit. The import is guarded because this file is also hot-patched
# onto servers whose core predates the registry — there get_group_kinds()
# simply has nothing to offer and the handlers keep working as before.
try:
    from tubecli.core import group_context as _gc
    _EntityKind = _gc.EntityKind
except Exception:
    _gc, _EntityKind = None, None

_PROMPT_LIST_CAP = getattr(_gc, "PROMPT_LIST_CAP", 20)
_SPREADSHEET_EXT = ("xlsx", "xlsm", "xls", "csv", "tsv")
_IMAGE_EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp")
_DOCUMENT_EXT = ("docx", "doc", "pdf", "txt", "md", "json", "html")
# Described by type so the model reaches for the right verb: xlsx_* for
# workbooks, file_action read for documents — and never xlsx_read on a png.
_FILE_BUCKETS = (
    ("Spreadsheet files (xlsx_read / xlsx_append / xlsx_write):", _SPREADSHEET_EXT),
    ("Images:", _IMAGE_EXT),
    ("Documents (read with file_action read):", _DOCUMENT_EXT),
)
_OTHER_FILES_HEADING = "Other files:"
_XLSX_SYNTAX = (
    '{"action":"xlsx_read","path":"/abs/or/~/file.xlsx","sheet":"Sheet1","max_rows":100}',
    '{"action":"xlsx_append","path":"...","sheet":"Sheet1","rows":[["a","b"]]}',
    '{"action":"xlsx_write","path":"...","sheet":"Sheet1","cells":{"A1":"v","B2":3}}',
)


def _file_normalise(raw, index: int):
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict):
        return None
    path = _gc.norm_str(raw.get("path"), 1000)
    if not path:
        return None
    alias = _gc.norm_str(raw.get("alias"), 200) or os.path.basename(path.rstrip("/\\")) or path
    ext = (_gc.norm_str(raw.get("ext"), 16) or os.path.splitext(path)[1]).lower().lstrip(".")
    # The owner's own files: write unless the node says otherwise.
    return {"alias": alias, "path": path, "ext": ext, "access": _gc.norm_access(raw.get("access"), "write")}


def _file_line(f: dict) -> str:
    return f'- "{f.get("alias", "")}" — {f.get("path", "")} (access: {f.get("access", "write")})'


def _files_describe(entries: list) -> list:
    shown = entries[:_PROMPT_LIST_CAP]
    buckets = {heading: [] for heading, _ in _FILE_BUCKETS}
    other = []
    for f in shown:
        ext = str(f.get("ext") or "").lower()
        for heading, exts in _FILE_BUCKETS:
            if ext in exts:
                buckets[heading].append(f)
                break
        else:
            other.append(f)
    lines = []
    for heading, _ in _FILE_BUCKETS:
        if buckets[heading]:
            lines.append(heading)
            lines.extend(_file_line(f) for f in buckets[heading])
    if other:
        lines.append(_OTHER_FILES_HEADING)
        lines.extend(_file_line(f) for f in other)
    if len(entries) > _PROMPT_LIST_CAP:
        lines.append(f"- …and {len(entries) - _PROMPT_LIST_CAP} more files (ask the user for the exact path).")
    return lines


def _files_action_docs(entries: list) -> list:
    # Only a workbook earns the xlsx verbs; a group of images gets none.
    if any(str(f.get("ext") or "").lower() in _SPREADSHEET_EXT for f in entries):
        return list(_XLSX_SYNTAX)
    return []


def _folder_normalise(raw, index: int):
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict):
        return None
    path = _gc.norm_str(raw.get("path"), 1000)
    if not path:
        return None
    return {"path": path, "access": _gc.norm_access(raw.get("access"), "write")}


def _folders_describe(entries: list) -> list:
    lines = ["Folders you may read and write in:"]
    for d in entries[:_PROMPT_LIST_CAP]:
        lines.append(f'- {d.get("path", "")} (access: {d.get("access", "write")})')
    if len(entries) > _PROMPT_LIST_CAP:
        lines.append(f"- …and {len(entries) - _PROMPT_LIST_CAP} more folders.")
    return lines


def _folders_action_docs(entries: list) -> list:
    # A folder may hold workbooks the canvas never listed one by one.
    return list(_XLSX_SYNTAX)


GROUP_KINDS = [] if _EntityKind is None else [
    _EntityKind(key="files", label="Files", normalise=_file_normalise, describe=_files_describe,
                action_docs=_files_action_docs, access_default="write", order=20, identity="path"),
    _EntityKind(key="folders", label="Folders", normalise=_folder_normalise, describe=_folders_describe,
                action_docs=_folders_action_docs, access_default="write", order=30, identity="path"),
]


class FileManagerExtension(Extension):
    name = "file_manager"
    version = "1.0.0"
    description = "Quản lý file & folder — API + WebUI file browser"
    author = "TubeCreate"
    enabled_by_default = True

    def setup(self):
        logger.info("File Manager Extension loaded")

    def get_routes(self):
        from tubecli.extensions.file_manager.routes import router
        return router

    def get_nodes(self):
        from tubecli.nodes.file_manager_node import FileManagerNode
        return {"file_manager": FileManagerNode}

    def get_group_kinds(self):
        return list(GROUP_KINDS)

    # ── Google Drive actions (chat / Telegram AI) ────────────────
    # The AI emits JSON action blocks; handle_extension_action routes them here.
    # Handlers call this server's own Drive API over HTTP (same pattern as
    # sheets_manager) so validation, threadpooling and error text live in ONE
    # place — drive.py — no matter who triggered the operation.

    def get_telegram_actions(self):
        return {
            "drive_list": self._action_drive_list,
            "drive_upload": self._action_drive_upload,
            "drive_download": self._action_drive_download,
            "drive_rename": self._action_drive_rename,
            "drive_share": self._action_drive_share,
            "drive_mkdir": self._action_drive_mkdir,
            "drive_delete": self._action_drive_delete,
            "xlsx_read": self._action_xlsx_read,
            "xlsx_append": self._action_xlsx_append,
            "xlsx_write": self._action_xlsx_write,
        }

    async def _drive_call(self, method: str, path: str, payload: dict = None, params: dict = None):
        import httpx
        from tubecli.config import get_api_port
        base = f"http://localhost:{get_api_port()}/api/v1/file-manager/drive"
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.request(method, base + path, json=payload, params=params)
            try:
                data = resp.json()
            except Exception:
                data = {"detail": resp.text}
            if resp.status_code != 200:
                raise RuntimeError(str(data.get("detail") or data))
            return data

    @staticmethod
    def _drive_err(e: Exception) -> str:
        return f"❌ Lỗi Google Drive: {e}"

    async def _action_drive_list(self, action_data: dict, context: dict) -> str:
        try:
            params = {
                "folder_id": action_data.get("folder_id") or "root",
                "page_size": 30,
            }
            if action_data.get("cred_id"):
                params["cred_id"] = action_data["cred_id"]
            if action_data.get("query"):
                params["q"] = action_data["query"]
            data = await self._drive_call("GET", "/list", params=params)
            files = data.get("files", [])
            if not files:
                return f"📂 Drive ({data.get('owner_email', '')}): thư mục trống hoặc không có kết quả."
            lines = [f"📂 **Google Drive** — 👤 {data.get('owner_email', '')}"]
            for f in files[:30]:
                icon = "📁" if f.get("is_folder") else "📄"
                link = f" — [mở]({f['url']})" if f.get("url") else ""
                fid = f" `{f.get('id')}`"
                lines.append(f"{icon} {f.get('name')}{fid}{link}")
            if data.get("next_page_token"):
                lines.append("… còn nữa (danh sách đã cắt ở 30 mục).")
            return "\n".join(lines)
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_upload(self, action_data: dict, context: dict) -> str:
        local_path = action_data.get("local_path") or action_data.get("path") or ""
        if not local_path:
            return "❌ Thiếu 'local_path' — đường dẫn file trên máy chủ cần upload."
        try:
            data = await self._drive_call("POST", "/upload", payload={
                "local_path": local_path,
                "folder_id": action_data.get("folder_id") or "root",
                "cred_id": action_data.get("cred_id"),
                "name": action_data.get("name"),
            })
            f = data.get("file", {})
            msg = "✅ **Đã upload lên Google Drive!**\n\n"
            msg += f"📄 {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}\n"
            if f.get("url"):
                msg += f"🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_download(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file trên Drive."
        try:
            data = await self._drive_call("POST", "/download", payload={
                "file_id": file_id,
                "dest_dir": action_data.get("dest_dir") or "~/Downloads",
                "cred_id": action_data.get("cred_id"),
            })
            return (
                "✅ **Đã tải file từ Drive về máy chủ!**\n\n"
                f"📄 {data.get('name')}\n📍 {data.get('path')}\n"
                f"👤 Tài khoản: {data.get('owner_email', '')}"
            )
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_rename(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        new_name = action_data.get("new_name") or action_data.get("name") or ""
        if not file_id or not new_name:
            return "❌ Cần cả 'file_id' và 'new_name' để đổi tên."
        try:
            data = await self._drive_call("POST", "/rename", payload={
                "file_id": file_id, "new_name": new_name,
                "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            msg = f"✅ **Đã đổi tên thành:** {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}"
            if f.get("url"):
                msg += f"\n🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_share(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file cần chia sẻ."
        try:
            data = await self._drive_call("POST", "/share", payload={
                "file_id": file_id,
                "cred_id": action_data.get("cred_id"),
                "type": action_data.get("type") or ("user" if action_data.get("email") else "anyone"),
                "role": action_data.get("role") or "reader",
                "email": action_data.get("email") or "",
            })
            f = data.get("file", {})
            msg = "✅ **Đã chia sẻ!**\n\n"
            msg += f"📄 {f.get('name')}\n🛡️ {data.get('shared_with')} — quyền {data.get('role')}\n"
            msg += f"👤 Tài khoản: {data.get('owner_email', '')}\n"
            if f.get("url"):
                msg += f"🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_mkdir(self, action_data: dict, context: dict) -> str:
        name = action_data.get("name") or ""
        if not name:
            return "❌ Thiếu 'name' — tên thư mục cần tạo trên Drive."
        try:
            data = await self._drive_call("POST", "/mkdir", payload={
                "name": name,
                "parent_id": action_data.get("parent_id") or "root",
                "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            msg = f"✅ **Đã tạo thư mục Drive:** {f.get('name')}\n👤 Tài khoản: {data.get('owner_email', '')}"
            if f.get("url"):
                msg += f"\n🔗 {f['url']}"
            return msg
        except Exception as e:
            return self._drive_err(e)

    async def _action_drive_delete(self, action_data: dict, context: dict) -> str:
        file_id = action_data.get("file_id") or ""
        if not file_id:
            return "❌ Thiếu 'file_id' của file cần xóa."
        try:
            data = await self._drive_call("POST", "/trash", payload={
                "file_id": file_id, "cred_id": action_data.get("cred_id"),
            })
            f = data.get("file", {})
            return (
                f"✅ **Đã chuyển vào thùng rác Drive:** {f.get('name')}\n"
                f"👤 Tài khoản: {data.get('owner_email', '')}\n"
                f"(Khôi phục được trong 30 ngày tại drive.google.com/drive/trash)"
            )
        except Exception as e:
            return self._drive_err(e)

    # ── Spreadsheet actions (xlsx_read / xlsx_append / xlsx_write) ─────────
    # Boundary first, file second. A group manifest (tubecli.core.group_context)
    # is the whole world for an agent that has one: a path no File/Folder node
    # covers does not exist for it, whatever the sandbox would say, and the
    # entry's `access` decides read/append/write. Resolved group paths go
    # through user_file_service (BLOCKED_PATHS still applies) because the
    # owner put that exact file in the group on purpose and it may live
    # outside ~/Desktop|Documents|Downloads. Without any group the classic AI
    # sandbox (file_service) applies — the same line file_action has always
    # drawn. The workbook is edited IN PLACE (append_sheet_rows /
    # update_sheet_cells), never rebuilt through write_sheet.

    _XLSX_NEED = {"xlsx_read": "read", "xlsx_append": "append", "xlsx_write": "write"}
    _XLSX_MAX_CHARS = 12000   # a 500×60 sheet would flood the model's context
    _XLSX_TEXT = {
        "en": {
            "missing_path": "❌ Missing 'path' — the spreadsheet file (.xlsx/.xlsm/.csv) to work on.",
            "not_shared": "❌ {path} is not shared with this agent's group. Only spreadsheet files or folders "
                          "placed in the group are available — ask the owner to add a File/Folder node for it.",
            # group_context returns this when the SAME file is shared by two
            # groups at two different access levels. It IS shared — what is
            # missing is which permission applies — so "not shared" would be a
            # lie, and one that sends the owner hunting for a node they already added.
            "ambiguous": "❌ {path} is shared by more than one group, at different access levels "
                         "({choices}). Say which group you mean, or ask the owner to make the "
                         "access match.",
            "no_access": "❌ '{name}' is shared with access '{have}' but {action} needs '{need}'. "
                         "Change the access on its node in the group.",
            "read_err": "❌ Cannot read {path}: {err}",
            "write_err": "❌ Cannot write {path}: {err}",
            "appended": "✅ Appended {n} row(s) to {name}{sheet_part} at rows {first}–{last}.\n📍 {path}",
            "written": "✅ Wrote {targets} in {name}{sheet_part}.\n📍 {path}",
            "read_head": "📊 {name}{sheet_part} — showing {shown} of {total} row(s)\n📍 {path}",
            "other_sheets": "\nOther sheets: {sheets}",
            "empty": "(empty — no rows)",
            "truncated": "… {more} more row(s) not shown. Raise max_rows (up to 500) to read further.",
            "cut": "… output cut at {n} characters; ask for fewer rows.",
            "sheet_part": " — sheet '{sheet}'",
            "uncomputed": "ℹ️ {n} formula cell(s) show the formula instead of a result: this server does not "
                          "calculate spreadsheets, and saving an edit here drops the results Excel had cached. "
                          "Work the number out from the rows yourself, or open and save the file in "
                          "Excel/LibreOffice to refresh it.",
        },
        "vi": {
            "missing_path": "❌ Thiếu 'path' — file bảng tính (.xlsx/.xlsm/.csv) cần thao tác.",
            "not_shared": "❌ {path} không được chia sẻ với nhóm của agent này. Chỉ file/thư mục bảng tính "
                          "đã đặt trong nhóm mới dùng được — nhờ chủ thêm node File/Folder cho nó.",
            "ambiguous": "❌ {path} đang được chia sẻ ở nhiều nhóm với mức quyền khác nhau "
                         "({choices}). Hãy nói rõ nhóm nào, hoặc nhờ chủ chỉnh cho hai bên "
                         "cùng một mức quyền.",
            "no_access": "❌ '{name}' được chia sẻ với quyền '{have}' nhưng {action} cần quyền '{need}'. "
                         "Đổi quyền trên node đó trong nhóm.",
            "read_err": "❌ Không đọc được {path}: {err}",
            "write_err": "❌ Không ghi được {path}: {err}",
            "appended": "✅ Đã thêm {n} dòng vào {name}{sheet_part} ở dòng {first}–{last}.\n📍 {path}",
            "written": "✅ Đã ghi {targets} trong {name}{sheet_part}.\n📍 {path}",
            "read_head": "📊 {name}{sheet_part} — hiện {shown}/{total} dòng\n📍 {path}",
            "other_sheets": "\nSheet khác: {sheets}",
            "empty": "(trống — không có dòng nào)",
            "truncated": "… còn {more} dòng chưa hiện. Tăng max_rows (tối đa 500) để đọc tiếp.",
            "cut": "… kết quả bị cắt ở {n} ký tự; hãy xin ít dòng hơn.",
            "sheet_part": " — sheet '{sheet}'",
            "uncomputed": "ℹ️ {n} ô công thức đang hiện chính công thức thay vì kết quả: máy chủ không tính "
                          "bảng tính, và lưu sửa đổi ở đây làm mất kết quả Excel đã cache. Hãy tự tính từ "
                          "các dòng, hoặc mở và lưu file bằng Excel/LibreOffice để cập nhật.",
        },
    }

    @classmethod
    def _xt(cls, context: dict, key: str, **kw) -> str:
        """Handler text in the bot language (vi/en); everything else falls back to
        English because that is the language of the group prompt block."""
        lang = str((context or {}).get("lang") or "en").lower()
        table = cls._XLSX_TEXT["vi"] if lang.startswith("vi") else cls._XLSX_TEXT["en"]
        try:
            return table[key].format(**kw)
        except Exception:
            return cls._XLSX_TEXT["en"].get(key, key)

    @staticmethod
    def _groups_in_effect(context: dict) -> list:
        """Groups the calling agent works in. The pipeline / Telegram listener pass
        `group_ids` when they already know them; otherwise the union of every
        group containing the agent (scheduled and Telegram runs). Empty list =
        no group, and any failure also lands there: the sandbox is still a
        boundary, a missing module must not turn into a crash."""
        try:
            from tubecli.core import group_context
        except Exception:
            return []
        ctx = context or {}
        agent_id = str((ctx.get("agent") or {}).get("id") or "")
        try:
            gids = ctx.get("group_ids")
            if isinstance(gids, (list, tuple)):
                # Khoá có mặt = người gọi đã quyết định (pipeline web gửi [] khi lượt
                # chat không thuộc nhóm nào). Danh sách rỗng KHÔNG được hiểu là "tự
                # tính hợp các nhóm": sau khi route sang specialist, "agent" trong
                # context là agent khác, và hợp của nó không phải quyền của lượt này.
                return [g for g in (group_context.load(str(gid)) for gid in gids) if g]
            return list(group_context.effective_groups(agent_id, str(ctx.get("group_id") or "")) or [])
        except Exception as e:
            logger.warning(f"[xlsx] group context unavailable, falling back to sandbox: {e}")
            return []

    @staticmethod
    def _alias_entry(groups: list, ref: str):
        """The prompt block names files as "alias" — path, so the model sometimes
        sends just the alias or the file name. Map it onto the group's own entry;
        nothing outside the manifest can match, so this loosens nothing."""
        key = str(ref or "").strip().casefold()
        if not key:
            return None
        for g in groups:
            for f in (g.get("files") or []):
                p = str(f.get("path") or "")
                if not p:
                    continue
                if key in (str(f.get("alias") or "").strip().casefold(), os.path.basename(p).casefold()):
                    return f
        return None

    def _sheet_target(self, action: str, path: str, context: dict):
        """(service, path, None) to operate on, or (None, None, refusal text)."""
        from tubecli.extensions.file_manager.file_service import file_service, user_file_service
        groups = self._groups_in_effect(context)
        if not groups:
            return file_service, path, None
        from tubecli.core import group_context
        entry = group_context.resolve_xlsx(groups, path)
        if not entry:
            alias = self._alias_entry(groups, path)
            if alias:
                entry = group_context.resolve_xlsx(groups, alias["path"])
        if isinstance(entry, dict) and entry.get("ambiguous"):
            # Cùng một file, hai nhóm cho hai mức quyền: đoán bừa một mức là ghi
            # bằng quyền mà chủ của nhóm kia chưa hề đồng ý (group_context._merge_shared).
            choices = "; ".join(
                f'{c.get("alias") or "?"} (nhóm {c.get("group_label") or "?"})'
                for c in (entry.get("choices") or []))
            return None, None, self._xt(context, "ambiguous", path=path, choices=choices)
        if not entry or not entry.get("path"):
            return None, None, self._xt(context, "not_shared", path=path)
        need = self._XLSX_NEED[action]
        have = str(entry.get("access") or "write")
        if not group_context.allows(have, need):
            return None, None, self._xt(context, "no_access", name=os.path.basename(entry["path"]),
                                        have=have, need=need, action=action)
        return user_file_service, entry["path"], None

    @staticmethod
    def _xlsx_cell(v) -> str:
        s = "" if v is None else str(v)
        s = s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")
        return s if len(s) <= 120 else s[:117] + "…"

    @classmethod
    def _xlsx_render(cls, context: dict, r: dict) -> str:
        name = os.path.basename(r["path"])
        sheet_part = cls._xt(context, "sheet_part", sheet=r["sheet"]) if r.get("sheet") else ""
        shown, total = len(r["rows"]), r["total_rows"]
        out = cls._xt(context, "read_head", name=name, sheet_part=sheet_part, shown=shown, total=total, path=r["path"])
        others = [x for x in (r.get("sheets") or []) if x != r.get("sheet")]
        if others:
            out += cls._xt(context, "other_sheets", sheets=", ".join(others[:20]))
        if not r["rows"]:
            return out + "\n" + cls._xt(context, "empty")
        body = "\n".join("| " + " | ".join(cls._xlsx_cell(c) for c in row) + " |" for row in r["rows"])
        if len(body) > cls._XLSX_MAX_CHARS:
            body = body[: cls._XLSX_MAX_CHARS].rsplit("\n", 1)[0] + "\n" + cls._xt(context, "cut", n=cls._XLSX_MAX_CHARS)
        out += "\n" + body
        if r.get("truncated"):
            out += "\n" + cls._xt(context, "truncated", more=total - shown)
        # A blank where a total should be is the one thing the model must not
        # take at face value — see FileService._xlsx_rows for why it happens.
        if r.get("formulas_uncomputed"):
            out += "\n" + cls._xt(context, "uncomputed", n=r["formulas_uncomputed"])
        return out

    async def _action_xlsx_read(self, action_data: dict, context: dict) -> str:
        path = str(action_data.get("path") or "").strip()
        if not path:
            return self._xt(context, "missing_path")
        svc, target, err = self._sheet_target("xlsx_read", path, context)
        if err:
            return err
        try:
            # openpyxl is synchronous; on the event loop it would stall every other request.
            r = await asyncio.to_thread(svc.read_sheet_rows, target, action_data.get("sheet"),
                                        action_data.get("max_rows") or 100)
        except Exception as e:
            return self._xt(context, "read_err", path=path, err=e)
        return self._xlsx_render(context, r)

    async def _action_xlsx_append(self, action_data: dict, context: dict) -> str:
        path = str(action_data.get("path") or "").strip()
        if not path:
            return self._xt(context, "missing_path")
        svc, target, err = self._sheet_target("xlsx_append", path, context)
        if err:
            return err
        rows = action_data.get("rows")
        if rows is None:
            rows = action_data.get("values")
        try:
            r = await asyncio.to_thread(svc.append_sheet_rows, target, action_data.get("sheet"), rows)
        except Exception as e:
            return self._xt(context, "write_err", path=path, err=e)
        sheet_part = self._xt(context, "sheet_part", sheet=r["sheet"]) if r.get("sheet") else ""
        return self._xt(context, "appended", n=r["rows_added"], name=os.path.basename(r["path"]),
                        sheet_part=sheet_part, first=r["first_row"], last=r["last_row"], path=r["path"])

    async def _action_xlsx_write(self, action_data: dict, context: dict) -> str:
        path = str(action_data.get("path") or "").strip()
        if not path:
            return self._xt(context, "missing_path")
        svc, target, err = self._sheet_target("xlsx_write", path, context)
        if err:
            return err
        cells = action_data.get("cells")
        rows = action_data.get("rows")
        start = action_data.get("start") or "A1"
        # Models trained on the gsheet_update shape send range + values; honour it
        # instead of bouncing a perfectly clear request.
        if rows is None and action_data.get("values") is not None:
            rows = action_data.get("values")
            rng = str(action_data.get("range") or "").strip()
            if rng:
                start = rng.split(":", 1)[0]
        try:
            r = await asyncio.to_thread(svc.update_sheet_cells, target, action_data.get("sheet"),
                                        cells, rows, start)
        except Exception as e:
            return self._xt(context, "write_err", path=path, err=e)
        sheet_part = self._xt(context, "sheet_part", sheet=r["sheet"]) if r.get("sheet") else ""
        targets = ", ".join(r.get("targets") or []) or "0 cells"
        return self._xt(context, "written", targets=targets, name=os.path.basename(r["path"]),
                        sheet_part=sheet_part, path=r["path"])

    def get_skills(self):
        return [
            {
                "name": "📁 File Manager",
                "description": "Tạo, xóa, di chuyển, liệt kê file và folder trên máy tính. AI có thể quản lý file trực tiếp.",
                "skill_type": "Skill",
                "commands": [
                    "tạo folder", "tạo thư mục", "create folder",
                    "tạo file", "create file",
                    "xóa file", "delete file",
                    "liệt kê file", "list files", "duyệt file", "xem thư mục", "browse files",
                    "tìm file", "search file", "lọc", "filter file", "tìm kiếm",
                    "quản lý file", "file manager",
                    "google drive", "drive", "upload drive", "tải lên drive",
                    "upload lên drive", "đưa lên drive", "tải từ drive",
                    "chia sẻ file", "share file", "đổi tên file drive",
                    "liệt kê drive", "xem drive", "list drive",
                ],
                "workflow_data": {
                    "name": "File Manager",
                    "nodes": [
                        {
                            "id": "user_input",
                            "type": "text_input",
                            "label": "📝 Input",
                            "config": {"text": ""},
                        },
                        {
                            "id": "file_op",
                            "type": "file_manager",
                            "label": "📁 File Manager",
                            "config": {"action": "auto"},
                        },
                        {
                            "id": "result_output",
                            "type": "output",
                            "label": "📤 Output",
                            "config": {"print": True},
                        },
                    ],
                    "connections": [
                        {
                            "from_node_id": "user_input",
                            "from_port_id": "content",
                            "to_node_id": "file_op",
                            "to_port_id": "command",
                        },
                        {
                            "from_node_id": "file_op",
                            "from_port_id": "result",
                            "to_node_id": "result_output",
                            "to_port_id": "data",
                        },
                    ],
                },
            }
        ]
