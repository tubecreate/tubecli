"""
Google Sheets client for the auth_manager extension — plain REST v4 over httpx.

Why it lives here and not in sheets_manager: auth_manager owns the Google tokens,
so the group-context actions (gsheet_*) and the worklog writer can depend on a
module that is always installed instead of an optional external extension. No
google-api-python-client either: the handful of calls we need map 1:1 onto REST,
stay mockable in tests (swap `_client` / `_token`), and add no import cost.

Every public function is synchronous on purpose — record_worklog runs it in a
daemon thread and the async routes/handlers wrap it in asyncio.to_thread.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("AuthManagerExtension.gsheets")

API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
TIMEOUT = 20.0

_ID_IN_URL = re.compile(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)")
_ID_PARAM = re.compile(r"[?&#](?:id|key)=([A-Za-z0-9_-]+)")
# Real ids are 44 chars; the floor only has to keep tab names / aliases from
# being mistaken for an id when a caller passes free text.
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{20,}$")


class GSheetsError(Exception):
    """Google said no (or could not be reached). `status` keeps Google's HTTP
    code so the route layer can pick 400/403/404/502 without re-parsing text."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = int(status or 0)
        self.message = message

    def __str__(self):
        return self.message


# ── Pure helpers (no network) ────────────────────────────────────

def parse_sheet_id(url_or_id: str) -> str:
    """Spreadsheet id out of a docs.google.com URL (any /edit#gid=… suffix),
    a legacy ?key=/?id= link, or a bare id. "" when nothing looks like one."""
    s = (url_or_id or "").strip()
    if not s:
        return ""
    m = _ID_IN_URL.search(s)
    if m:
        return m.group(1)
    m = _ID_PARAM.search(s)
    if m:
        return m.group(1)
    if _BARE_ID.match(s):
        return s
    return ""


def a1_range(tab: str, rng: str = "") -> str:
    """'My Tab'!A1:B2 — Google requires quotes once a tab name has a space or
    punctuation, and tolerates them always, so quote unconditionally (an
    apostrophe inside the name is doubled, like SQL)."""
    tab = (tab or "").strip()
    rng = (rng or "").strip()
    if not tab:
        return rng
    quoted = "'" + tab.replace("'", "''") + "'"
    return f"{quoted}!{rng}" if rng else quoted


def split_range(rng: str):
    """"Tasks!A1:B2" → ("Tasks", "A1:B2"); "A1:B2" → ("", "A1:B2"). Lets a caller
    pass a full A1 reference in `range` without the tab doubling up."""
    rng = (rng or "").strip()
    if "!" not in rng:
        return "", rng
    tab, _, cells = rng.rpartition("!")
    tab = tab.strip()
    if len(tab) >= 2 and tab[0] == "'" and tab[-1] == "'":
        tab = tab[1:-1].replace("''", "'")
    return tab, cells.strip()


def normalise_rows(rows: Any) -> List[List[Any]]:
    """Coerce what an LLM is likely to emit into the list-of-rows Google wants:
    a flat list becomes one row, a scalar row becomes a 1-cell row, None → "",
    nested structures are serialised so the API never rejects a cell."""
    if rows is None:
        return []
    if not isinstance(rows, (list, tuple)):
        raise GSheetsError(400, "rows must be a list of rows (each row a list of cells)")
    if rows and all(not isinstance(r, (list, tuple)) for r in rows):
        rows = [list(rows)]
    out: List[List[Any]] = []
    for r in rows:
        if not isinstance(r, (list, tuple)):
            r = [r]
        out.append([_cell(c) for c in r])
    return out


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (bool, int, float, str)):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


# ── Transport (swapped out by tests) ─────────────────────────────

def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


def _token(cred_id: str) -> str:
    from tubecli.extensions.auth_manager.extension import auth_manager
    token = auth_manager.get_active_token(cred_id) if cred_id else None
    if not token:
        raise GSheetsError(
            403, f"no active Google token for credential '{cred_id}' — authorize it in Auth Manager")
    return token


def _authorized_email(cred_id: str) -> str:
    try:
        from tubecli.extensions.auth_manager.extension import auth_manager
        data = auth_manager.get_token_data(cred_id) or {}
        if data.get("authorized_email"):
            return data["authorized_email"]
        cred = auth_manager.get_credential(cred_id) or {}
        return cred.get("service_account_email", "") or ""
    except Exception:
        return ""


def _map_error(resp: httpx.Response) -> GSheetsError:
    status = resp.status_code
    detail = ""
    try:
        err = (resp.json() or {}).get("error") or {}
        detail = str(err.get("message") or "")
    except Exception:
        detail = (resp.text or "")[:200]
    if status in (401, 403):
        msg = "token lacks access or the spreadsheets scope"
    elif status == 404:
        msg = "spreadsheet not found"
    elif status == 429:
        msg = "Google Sheets rate limit hit, try again later"
    elif status >= 500:
        msg = f"Google Sheets error {status}"
    else:
        msg = detail or f"Google Sheets error {status}"
    if detail and status in (401, 403, 404):
        msg += f" ({detail})"
    return GSheetsError(status, msg)


def _request(cred_id: str, method: str, path: str, params: Optional[dict] = None,
             body: Optional[dict] = None) -> dict:
    token = _token(cred_id)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        with _client() as client:
            resp = client.request(method, API_BASE + path, params=params, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise GSheetsError(502, f"cannot reach Google Sheets: {e}") from e
    if resp.status_code >= 400:
        raise _map_error(resp)
    if not resp.content:
        return {}
    try:
        return resp.json() or {}
    except ValueError:
        raise GSheetsError(502, "Google Sheets returned a non-JSON response")


def _values_path(sheet_id: str, a1: str, suffix: str = "") -> str:
    # The A1 reference is a path segment: quotes, '!' and ':' must be escaped,
    # otherwise "'My Tab'!A1:B2" is read as a different resource.
    return f"/{sheet_id}/values/{quote(a1, safe='')}{suffix}"


# ── Metadata ─────────────────────────────────────────────────────

def _tab_props(sheet: dict) -> dict:
    p = sheet.get("properties") or {}
    grid = p.get("gridProperties") or {}
    return {
        "title": p.get("title", ""),
        "gid": p.get("sheetId", 0),
        "index": p.get("index", 0),
        "rows": grid.get("rowCount", 0),
        "cols": grid.get("columnCount", 0),
    }


def inspect(cred_id: str, sheet_id: str) -> dict:
    """{sheet_id, title, tabs:[{title, gid, index, rows, cols}], authorized_email}.
    rows/cols are the grid size Google reports, not the number of filled rows."""
    data = _request(cred_id, "GET", f"/{sheet_id}",
                    params={"fields": "spreadsheetId,properties.title,sheets.properties"})
    return {
        "sheet_id": data.get("spreadsheetId") or sheet_id,
        "title": (data.get("properties") or {}).get("title", ""),
        "tabs": [_tab_props(s) for s in (data.get("sheets") or [])],
        "authorized_email": _authorized_email(cred_id),
    }


def tabs(cred_id: str, sheet_id: str) -> List[dict]:
    return inspect(cred_id, sheet_id)["tabs"]


def _first_tab(cred_id: str, sheet_id: str) -> str:
    found = tabs(cred_id, sheet_id)
    if not found:
        raise GSheetsError(404, "spreadsheet has no tabs")
    return found[0]["title"]


def _resolve_tab(cred_id: str, sheet_id: str, tab: str, rng: Optional[str]):
    """Apply the "tab missing → first tab" tolerance and let a full A1 ref in
    `rng` supply the tab. One metadata round-trip only when really needed."""
    ref_tab, cells = split_range(rng or "")
    tab = (tab or "").strip() or ref_tab
    if not tab:
        tab = _first_tab(cred_id, sheet_id)
    return tab, cells


# ── Values ───────────────────────────────────────────────────────

def read(cred_id: str, sheet_id: str, tab: str = "", rng: Optional[str] = None,
         max_rows: int = 200, tail: int = 0, render: str = "FORMATTED_VALUE") -> dict:
    """{tab, range, values, total_rows, truncated}. `tail=N` keeps the last N
    rows of the range instead of the first `max_rows`; 0 for either means "all".

    render="FORMULA" trả về CÔNG THỨC thô ("=SUM(A1:A9)") thay vì kết quả đã
    tính. Trình sửa ô phải đọc bằng bản này: hiện kết quả rồi ghi đè lại chính
    kết quả đó là xoá mất công thức của người dùng."""
    render = str(render or "").upper()
    if render not in ("FORMATTED_VALUE", "FORMULA", "UNFORMATTED_VALUE"):
        render = "FORMATTED_VALUE"
    tab, cells = _resolve_tab(cred_id, sheet_id, tab, rng)
    a1 = a1_range(tab, cells)
    data = _request(cred_id, "GET", _values_path(sheet_id, a1),
                    params={"majorDimension": "ROWS", "valueRenderOption": render})
    values = data.get("values") or []
    total = len(values)
    tail = int(tail or 0)
    max_rows = int(max_rows or 0)
    if tail > 0:
        out = values[-tail:]
    elif max_rows > 0:
        out = values[:max_rows]
    else:
        out = values
    return {
        "tab": tab,
        "range": data.get("range") or a1,
        "values": out,
        "total_rows": total,
        "truncated": len(out) < total,
    }


# ── Định dạng ô: đọc để VẼ ĐÚNG, ghi để sửa ngay trên canvas ─────────────
# values API chỉ trả chữ. Ô GỘP vì thế hiện sai (chữ nằm ở ô đầu, các ô còn lại
# trống trơ), còn đậm/cỡ/màu thì mất sạch — nhìn không ra bảng của mình nữa.
# spreadsheets.get?includeGridData=true trả cả `merges` lẫn effectiveFormat.

_GRID_FIELDS = ("sheets(properties(sheetId,title),merges,"
                "data(rowData(values(formattedValue,"
                "effectiveFormat(textFormat(bold,italic,fontSize,fontFamily,foregroundColor),"
                "backgroundColor,horizontalAlignment)))))")

_COL_A = ord("A")


def colname(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    out = ""
    i = int(i)
    while True:
        out = chr(_COL_A + (i % 26)) + out
        i = i // 26 - 1
        if i < 0:
            return out


def col_index(letters: str) -> int:
    """A → 0, Z → 25, AA → 26."""
    n = 0
    for ch in (letters or "").upper():
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch) - _COL_A + 1)
    return max(0, n - 1)


def grid_range(gid: int, cells: str) -> dict:
    """B2:C5 → GridRange nửa mở của Google (chỉ số end là loại trừ)."""
    m = re.findall(r"([A-Za-z]*)(\d*)", (cells or "").replace("$", ""))
    parts = [(a, b) for a, b in m if a or b][:2]
    if not parts:
        return {"sheetId": gid}
    c0, r0 = parts[0]
    c1, r1 = parts[1] if len(parts) > 1 else parts[0]
    out = {"sheetId": gid}
    if r0:
        out["startRowIndex"] = int(r0) - 1
        out["endRowIndex"] = int(r1 or r0)
    if c0:
        out["startColumnIndex"] = col_index(c0)
        out["endColumnIndex"] = col_index(c1 or c0) + 1
    return out


def _gid_of(cred_id: str, sheet_id: str, tab: str):
    found = tabs(cred_id, sheet_id)
    if not found:
        raise GSheetsError(404, "spreadsheet has no tabs")
    if not tab:
        return found[0]["title"], found[0]["gid"]
    for t in found:
        if t["title"].casefold() == tab.casefold():
            return t["title"], t["gid"]
    raise GSheetsError(404, "tab not found: " + str(tab))


def _rgb(c):
    if not isinstance(c, dict):
        return None
    if not (c.get("red") or c.get("green") or c.get("blue")):
        return None   # trắng mặc định của Google — để trống cho theme tự lo
    return "#%02x%02x%02x" % (round((c.get("red") or 0) * 255),
                              round((c.get("green") or 0) * 255),
                              round((c.get("blue") or 0) * 255))


def grid(cred_id: str, sheet_id: str, tab: str = "", max_rows: int = 60,
         max_cols: int = 26) -> dict:
    """Chữ + định dạng + danh sách ô gộp của một vùng, đủ để vẽ lại y như trên
    Google: {tab, gid, values, formats, merges, total_rows}."""
    tab, gid = _gid_of(cred_id, sheet_id, tab)
    max_rows = max(1, min(int(max_rows or 60), 200))
    last_col = colname(max(0, min(int(max_cols or 26), 26) - 1))
    a1 = a1_range(tab, "A1:%s%d" % (last_col, max_rows))
    data = _request(cred_id, "GET", "/" + sheet_id,
                    params={"includeGridData": "true", "ranges": a1, "fields": _GRID_FIELDS})
    sheets = data.get("sheets") or []
    sh = sheets[0] if sheets else {}
    rowdata = ((sh.get("data") or [{}])[0]).get("rowData") or []
    values, formats = [], []
    for row in rowdata:
        cells = row.get("values") or []
        values.append([c.get("formattedValue", "") for c in cells])
        frow = []
        for c in cells:
            ef = c.get("effectiveFormat") or {}
            tf = ef.get("textFormat") or {}
            f = {}
            if tf.get("bold"):
                f["b"] = 1
            if tf.get("italic"):
                f["i"] = 1
            if tf.get("fontSize"):
                f["fs"] = tf["fontSize"]
            if tf.get("fontFamily"):
                f["ff"] = tf["fontFamily"]
            fg = _rgb(tf.get("foregroundColor"))
            if fg:
                f["fg"] = fg
            bg = _rgb(ef.get("backgroundColor"))
            if bg:
                f["bg"] = bg
            ha = ef.get("horizontalAlignment")
            if ha and ha != "LEFT":
                f["ha"] = ha.lower()
            frow.append(f or None)
        formats.append(frow)
    merges = []
    for m in (sh.get("merges") or []):
        r0 = m.get("startRowIndex", 0)
        c0 = m.get("startColumnIndex", 0)
        merges.append({"r": r0, "c": c0,
                       "rs": m.get("endRowIndex", r0 + 1) - r0,
                       "cs": m.get("endColumnIndex", c0 + 1) - c0})
    return {"tab": tab, "gid": gid, "values": values, "formats": formats,
            "merges": merges, "total_rows": len(values)}


def format_cells(cred_id: str, sheet_id: str, tab: str, rng: str, fmt: dict) -> dict:
    """Đậm/nghiêng/cỡ chữ/màu nền/canh lề cho một vùng. Fields mask chỉ liệt kê
    ĐÚNG thuộc tính người dùng vừa đổi — gửi cả cụm sẽ xoá những gì họ đã chỉnh
    trước đó trên Google."""
    tab, gid = _gid_of(cred_id, sheet_id, tab)
    cells = split_range(rng)[1] or rng
    if not cells:
        raise GSheetsError(400, "range is required")
    # Xoá sạch định dạng: userEnteredFormat rỗng + fields cả cụm → Google trả ô về
    # mặc định (bỏ đậm/nghiêng/cỡ/màu chữ/màu nền/căn lề). Khác bản áp từng field
    # (mask hẹp) nên xử lý riêng, trước.
    if fmt.get("clear"):
        _request(cred_id, "POST", "/" + sheet_id + ":batchUpdate", body={"requests": [{
            "repeatCell": {"range": grid_range(gid, cells),
                           "cell": {"userEnteredFormat": {}},
                           "fields": "userEnteredFormat"}}]})
        return {"tab": tab, "range": cells, "applied": ["userEnteredFormat(clear)"]}
    text, cell, fields = {}, {}, []
    if "bold" in fmt:
        text["bold"] = bool(fmt["bold"])
        fields.append("userEnteredFormat.textFormat.bold")
    if "italic" in fmt:
        text["italic"] = bool(fmt["italic"])
        fields.append("userEnteredFormat.textFormat.italic")
    if fmt.get("fontSize"):
        text["fontSize"] = max(6, min(int(fmt["fontSize"]), 96))
        fields.append("userEnteredFormat.textFormat.fontSize")
    if fmt.get("align"):
        cell["horizontalAlignment"] = str(fmt["align"]).upper()
        fields.append("userEnteredFormat.horizontalAlignment")
    if "bg" in fmt:
        hexv = str(fmt["bg"] or "").lstrip("#")
        if len(hexv) == 6:
            cell["backgroundColor"] = {"red": int(hexv[0:2], 16) / 255.0,
                                       "green": int(hexv[2:4], 16) / 255.0,
                                       "blue": int(hexv[4:6], 16) / 255.0}
            fields.append("userEnteredFormat.backgroundColor")
    if not fields:
        raise GSheetsError(400, "nothing to format")
    if text:
        cell["textFormat"] = text
    _request(cred_id, "POST", "/" + sheet_id + ":batchUpdate", body={"requests": [{
        "repeatCell": {"range": grid_range(gid, cells),
                       "cell": {"userEnteredFormat": cell},
                       "fields": ",".join(fields)}}]})
    return {"tab": tab, "range": cells, "applied": fields}


def merge_cells(cred_id: str, sheet_id: str, tab: str, rng: str, merge: bool = True) -> dict:
    """Gộp (hoặc bỏ gộp) một vùng ô."""
    tab, gid = _gid_of(cred_id, sheet_id, tab)
    cells = split_range(rng)[1] or rng
    if not cells or ":" not in cells:
        raise GSheetsError(400, "range must span more than one cell, e.g. A1:C1")
    gr = grid_range(gid, cells)
    req = ({"mergeCells": {"range": gr, "mergeType": "MERGE_ALL"}} if merge
           else {"unmergeCells": {"range": gr}})
    _request(cred_id, "POST", "/" + sheet_id + ":batchUpdate", body={"requests": [req]})
    return {"tab": tab, "range": cells, "merged": bool(merge)}


def append(cred_id: str, sheet_id: str, tab: str, rows: Any) -> dict:
    """Append rows after the last filled row of the tab. USER_ENTERED so "=SUM()"
    and "2026-08-22" behave as if typed; INSERT_ROWS so nothing below is overwritten."""
    rows = normalise_rows(rows)
    if not rows:
        raise GSheetsError(400, "nothing to append: rows is empty")
    tab = (tab or "").strip() or _first_tab(cred_id, sheet_id)
    a1 = a1_range(tab)
    data = _request(cred_id, "POST", _values_path(sheet_id, a1, ":append"),
                    params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                    body={"range": a1, "majorDimension": "ROWS", "values": rows})
    upd = data.get("updates") or {}
    return {
        "tab": tab,
        "updated_range": upd.get("updatedRange", ""),
        "updated_rows": upd.get("updatedRows", len(rows)),
        "updated_cells": upd.get("updatedCells", 0),
    }


def update(cred_id: str, sheet_id: str, tab: str, rng: str, values: Any) -> dict:
    """Overwrite the block starting at `rng` (e.g. "B2:C2" or just "B2"). An empty
    range writes from A1 — callers exposing this to an LLM should require one."""
    values = normalise_rows(values)
    if not values:
        raise GSheetsError(400, "nothing to write: values is empty")
    tab, cells = _resolve_tab(cred_id, sheet_id, tab, rng)
    a1 = a1_range(tab, cells or "A1")
    data = _request(cred_id, "PUT", _values_path(sheet_id, a1),
                    params={"valueInputOption": "USER_ENTERED"},
                    body={"range": a1, "majorDimension": "ROWS", "values": values})
    return {
        "tab": tab,
        "updated_range": data.get("updatedRange", a1),
        "updated_rows": data.get("updatedRows", 0),
        "updated_cells": data.get("updatedCells", 0),
    }


def create_tab(cred_id: str, sheet_id: str, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise GSheetsError(400, "tab title is required")
    data = _request(cred_id, "POST", f"/{sheet_id}:batchUpdate",
                    body={"requests": [{"addSheet": {"properties": {"title": title}}}]})
    replies = data.get("replies") or [{}]
    props = ((replies[0] or {}).get("addSheet") or {}).get("properties") or {}
    return {"title": props.get("title", title), "gid": props.get("sheetId", 0)}


def ensure_header(cred_id: str, sheet_id: str, tab: str, header: List[Any]) -> dict:
    """Make sure `tab` exists and its first row is `header`; never touches a tab
    that already has something in row 1 (the owner may have their own columns).
    Tab names are case-insensitive on Google's side, so "log" finds "Log"."""
    tab = (tab or "").strip()
    if not tab:
        raise GSheetsError(400, "tab name is required")
    existing = {t["title"].casefold(): t["title"] for t in tabs(cred_id, sheet_id)}
    created = False
    if tab.casefold() in existing:
        tab = existing[tab.casefold()]
        first = read(cred_id, sheet_id, tab, "1:1", max_rows=1).get("values") or []
    else:
        create_tab(cred_id, sheet_id, tab)
        created = True
        first = []
    wrote = False
    if not first or not any(str(c).strip() for c in first[0]):
        update(cred_id, sheet_id, tab, "A1", [list(header)])
        wrote = True
    return {"tab": tab, "created_tab": created, "wrote_header": wrote}
