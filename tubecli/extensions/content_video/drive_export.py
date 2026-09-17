# -*- coding: utf-8 -*-
"""Lưu thành phẩm một lượt content_video lên Google Drive — bước "drive" (user 15/9/2026).

Một thư mục mang tên tiêu đề video: Google Sheet nội dung (tổng quan · từng cảnh · kịch bản) + video,
ảnh đại diện, ảnh từng cảnh (images/) và giọng từng cảnh (audio/). Tài khoản = token của Auth Manager.

Gọi thẳng googleapiclient trong tiến trình, KHÔNG qua POST /api/v1/file-manager/drive/upload: route đó
cố ý chặn đường dẫn ngoài hộp cát của AI và có trần 512 MB (video dài vượt), lại ném HTTPException.
Chỉ file nằm trong DATA_DIR mới được đưa lên — pipeline.py (_data_file) lọc trước khi gọi vào đây.

Mọi lời gọi mạng nằm trong các hàm cấp module để test thay được, không gửi gì thật.
"""
import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("ContentVideo")

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
CHUNK_BYTES = 8 * 1024 * 1024        # mỗi lượt next_chunk — đủ nhỏ để báo tiến độ, huỷ giữa chừng
CELL_MAX = 49000                     # Google Sheets: tối đa 50 000 ký tự một ô
FILE_FIELDS = "id, name, size, mimeType, webViewLink"
# Hai lượt đồng bộ chạy song song (task Drive không chung làn) cùng tìm-rồi-tạo thư mục của máy → khoá, kẻo đẻ
# hai thư mục «user-vps-9» cùng tên.
_FOLDER_LOCK = threading.Lock()


class DriveExportError(RuntimeError):
    """Lỗi nói được cho người dùng: thiếu tài khoản, chỉ có quyền đọc, token hết hạn, thiếu thư viện."""


# ── Tài khoản ────────────────────────────────────────────────────────

def can_write(scopes) -> bool:
    """Ghi được Drive không. Auth Manager lưu khoá NGẮN ('drive', 'drive_file', 'drive_readonly'); token
    cấp bằng chuỗi scope thô thì là URL — nhận cả hai, như file_manager/drive.py _is_readonly."""
    joined = " " + " ".join(str(s) for s in (scopes or [])) + " "
    return (" drive " in joined or " drive_file " in joined
            or "auth/drive " in joined or "auth/drive.file" in joined)


def google_tokens() -> List[Dict[str, Any]]:
    from tubecli.extensions.auth_manager.extension import auth_manager
    return [t for t in (auth_manager.list_tokens("google") or []) if isinstance(t, dict)]


def token_label(tok: Dict[str, Any]) -> str:
    return str(tok.get("authorized_email") or tok.get("credential_name") or tok.get("token_id") or "")


def resolve_token(token_id: str, granted: List[str], strict: bool) -> Dict[str, Any]:
    """Token Google sẽ nhận file.

    token_id chọn trên form Codex thắng — so ĐÚNG token_id, không nhận credential_id (một credential giữ
    được nhiều tài khoản Google, tra theo nó là bốc nhầm người). Không chọn → tài khoản đã cấp cho agent ở
    tab Auth (`granted` = credential_id, theo thứ tự đã tick). strict=True (việc không do người bấm tạo:
    AI tự gọi, lịch, kho nội dung) → token phải thuộc tài khoản đã cấp cho agent."""
    tokens = google_tokens()
    granted = [str(c) for c in (granted or []) if c]
    token_id = str(token_id or "").strip()
    if token_id:
        tok = next((t for t in tokens if t.get("token_id") == token_id), None)
        if not tok:
            raise DriveExportError("The Google account chosen for Drive is no longer in Auth Manager — "
                                   "authorize it again or pick another account.")
        if strict and tok.get("credential_id") not in granted:
            raise DriveExportError(f"{token_label(tok)} is not granted to this agent in its Auth tab — grant it "
                                   "there, or pick the account yourself in the Codex form.")
        if tok.get("status") == "revoked":
            raise DriveExportError(f"Access for {token_label(tok)} was revoked — authorize it again in Auth Manager.")
        if not can_write(tok.get("scopes")):
            raise DriveExportError(f"{token_label(tok)} can only read Google Drive — authorize it again in "
                                   "Auth Manager with the Google Drive scope.")
        return tok
    # Chỉ tài khoản có dính Drive: tài khoản cấp cho agent để đăng YouTube không phải "Drive chỉ đọc".
    mine = [t for t in tokens if t.get("credential_id") in granted and t.get("status") != "revoked"
            and "drive" in " ".join(str(s) for s in (t.get("scopes") or []))]
    usable = [t for t in mine if can_write(t.get("scopes"))]
    if usable:
        usable.sort(key=lambda t: (t.get("status") != "active", granted.index(t["credential_id"])))
        return usable[0]
    if mine:
        raise DriveExportError(f"{token_label(mine[0])} (granted to this agent) can only read Google Drive — "
                               "authorize it again in Auth Manager with the Google Drive scope.")
    raise DriveExportError("No Google account with Drive access is granted to this agent — pick an account under "
                           "«Save to Google Drive» in the Codex form, or grant one in the agent's Auth tab.")


def _gapi():
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.credentials import Credentials
    except ImportError as e:
        raise DriveExportError(f"Google API libraries are missing ({e}) — run: "
                               "pip install google-api-python-client google-auth")
    return build, MediaFileUpload, Credentials


def services(token_id: str) -> Tuple[Any, Any]:
    """(drive v3, sheets v4) cho một token. Có refresh_token + client_id thì googleapiclient tự làm mới
    giữa chừng — một video dài tải lên lâu hơn tuổi thọ access token (1 giờ)."""
    build, _, Credentials = _gapi()
    from tubecli.extensions.auth_manager.extension import auth_manager as am

    access = am.get_active_token(token_id)
    if not access:
        raise DriveExportError("The Google token has expired and could not be refreshed — authorize the account "
                               "again in Auth Manager.")
    td = am.get_token_data(token_id) or {}
    cd = am.get_credential(td.get("credential_id")) or {}
    if td.get("refresh_token") and cd.get("client_id"):
        creds = Credentials(token=access, refresh_token=td["refresh_token"], client_id=cd["client_id"],
                            client_secret=cd.get("client_secret"), token_uri="https://oauth2.googleapis.com/token")
    else:
        creds = Credentials(token=access)
    # cache_discovery=False: bộ nhớ đệm discovery dạng file cần oauth2client, thiếu thì chỉ ghi cảnh báo ồn.
    return (build("drive", "v3", credentials=creds, cache_discovery=False),
            build("sheets", "v4", credentials=creds, cache_discovery=False))


# ── Drive ────────────────────────────────────────────────────────────

def _q(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def list_children(drive, folder_id: str) -> Dict[str, Dict[str, Any]]:
    """{tên: file} trong một thư mục, bỏ thùng rác. Trùng tên → giữ cái đầu."""
    out: Dict[str, Dict[str, Any]] = {}
    page = None
    while True:
        resp = drive.files().list(q=f"'{_q(folder_id)}' in parents and trashed = false",
                                  fields=f"nextPageToken, files({FILE_FIELDS})",
                                  pageSize=1000, pageToken=page).execute() or {}
        for f in resp.get("files") or []:
            out.setdefault(str(f.get("name") or ""), f)
        page = resp.get("nextPageToken")
        if not page:
            return out


def file_alive(drive, file_id: str) -> Optional[Dict[str, Any]]:
    """File/thư mục còn đó (không nằm thùng rác) thì trả nó; bị xoá → None. Lỗi khác (mạng, quyền) thì ném."""
    try:
        f = drive.files().get(fileId=file_id, fields="id, name, mimeType, trashed, webViewLink, parents").execute() or {}
    except Exception as e:      # noqa: BLE001 — googleapiclient.errors.HttpError
        if "404" in str(e) or "notFound" in str(e):
            return None
        raise
    return None if f.get("trashed") else f


def create_folder(drive, name: str, parent: str = "root") -> Dict[str, Any]:
    return drive.files().create(body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
                                fields=FILE_FIELDS).execute()


def ensure_folder(drive, parent: str, name: str, known: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    known = list_children(drive, parent) if known is None else known
    hit = known.get(name)
    if hit and hit.get("mimeType") == FOLDER_MIME:
        return hit
    return create_folder(drive, name, parent)


def find_or_create_folder(drive, parent: str, name: str) -> Dict[str, Any]:
    """Thư mục tên ĐÚNG `name` ngay trong `parent`; chưa có thì tạo. Hỏi theo tên chứ không liệt kê cả thư mục cha:
    gốc My Drive của một tài khoản dùng chung có thể có hàng nghìn file."""
    with _FOLDER_LOCK:
        resp = drive.files().list(q=(f"'{_q(parent)}' in parents and trashed = false and "
                                     f"mimeType = '{FOLDER_MIME}' and name = '{_q(name)}'"),
                                  fields=f"files({FILE_FIELDS})", pageSize=10).execute() or {}
        files = resp.get("files") or []
        return files[0] if files else create_folder(drive, name, parent)


def my_drive_root_id(drive) -> str:
    """Id thật của gốc My Drive — "root" chỉ là bí danh, còn `parents` của file mang id thật."""
    return str((drive.files().get(fileId="root", fields="id").execute() or {}).get("id") or "")


def move_folder(drive, file_id: str, new_parent: str, old_parents: List[str]) -> None:
    drive.files().update(fileId=file_id, addParents=new_parent, removeParents=",".join(old_parents),
                         fields="id, parents").execute()


def unique_name(drive, parent: str, name: str) -> str:
    """Drive cho trùng tên; hai video cùng tiêu đề mà chung một tên thư mục thì không biết cái nào của lượt
    nào → thêm " (2)", " (3)"… """
    resp = drive.files().list(q=(f"'{_q(parent)}' in parents and trashed = false and "
                                 f"mimeType = '{FOLDER_MIME}' and name contains '{_q(name)}'"),
                              fields="files(name)", pageSize=1000).execute() or {}
    taken = {str(f.get("name") or "") for f in resp.get("files") or []}
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def upload_file(drive, path: str, name: str, parent: str,
                on_progress: Optional[Callable[[int], None]] = None,
                cancelled: Optional[Callable[[], bool]] = None,
                cancel_exc: Optional[Callable[[], Exception]] = None) -> Dict[str, Any]:
    """Tải lên kiểu resumable theo từng khúc CHUNK_BYTES: báo số byte đã gửi, huỷ được giữa hai khúc."""
    _, MediaFileUpload, _ = _gapi()
    media = MediaFileUpload(path, chunksize=CHUNK_BYTES, resumable=True)
    try:
        request = drive.files().create(body={"name": name, "parents": [parent]}, media_body=media,
                                       fields=FILE_FIELDS)
        resp = None
        while resp is None:
            if cancelled and cancelled():
                raise cancel_exc() if cancel_exc else RuntimeError("Cancelled by the user.")
            status, resp = request.next_chunk()
            if status is not None and on_progress:
                on_progress(int(getattr(status, "resumable_progress", 0) or 0))
        if on_progress:
            on_progress(os.path.getsize(path))
        return resp
    finally:
        # MediaFileUpload giữ file mở tới lúc bị dọn rác — trên Windows là khoá luôn file (nút Xoá của Codex hỏng).
        try:
            media.stream().close()
        except Exception:       # noqa: BLE001
            pass


def share_public(drive, file_id: str) -> None:
    """Ai có link cũng XEM và TẢI được.

    Hai việc, không phải một: (1) quyền `anyone/reader` — `allowFileDiscovery` để mặc định False nên chỉ ai có
    link mới vào được, không hiện trong tìm kiếm Google; (2) tắt `copyRequiresWriterPermission`, vì cờ đó bật là
    người xem KHÔNG tải/copy/in được — đúng thứ người dùng cần (user 16/9/2026). Quyền đặt trên THƯ MỤC thì mọi
    file bên trong hưởng theo, nên chỉ cần gọi một lần cho cả lượt."""
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}, fields="id").execute()
    drive.files().update(fileId=file_id, body={"copyRequiresWriterPermission": False}, fields="id").execute()


def download_url(file_id: str) -> str:
    """Link tải THẲNG file (không qua trang xem trước) — dán vào Sheet cho người ta bấm là tải."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def trash_file(drive, file_id: str) -> None:
    drive.files().update(fileId=file_id, body={"trashed": True}, fields="id").execute()


def create_sheet(drive, name: str, parent: str) -> Dict[str, Any]:
    """Tạo Google Sheet NGAY TRONG thư mục — Sheets API tự tạo thì luôn nằm ở gốc Drive."""
    return drive.files().create(body={"name": name, "mimeType": SHEET_MIME, "parents": [parent]},
                                fields=FILE_FIELDS).execute()


# ── Sheets ───────────────────────────────────────────────────────────

def _a1(tab: str) -> str:
    return "'" + str(tab).replace("'", "''") + "'"


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v)
    return s if len(s) <= CELL_MAX else s[:CELL_MAX - 1] + "…"


def write_sheet(sheets, sheet_id: str, tabs: List[Tuple[str, List[List[Any]]]],
                widths: Optional[Dict[str, Dict[int, int]]] = None) -> None:
    """Ghi ĐÈ từng tab [(tên, hàng)]: tab mặc định ("Sheet1"/"Trang tính1") đổi tên thành tab đầu, tab thiếu thì
    thêm. RAW chứ không USER_ENTERED: câu thoại bắt đầu bằng "=", "+" hay "-" không được thành công thức."""
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties").execute() or {}
    props = [s.get("properties") or {} for s in meta.get("sheets") or []]
    wanted = [t for t, _ in tabs]
    ids = {p.get("title"): p.get("sheetId") for p in props}
    spare = [p for p in props if p.get("title") not in wanted]
    reqs = []
    for title in wanted:
        if title in ids:
            continue
        if spare:
            p = spare.pop(0)
            reqs.append({"updateSheetProperties": {"properties": {"sheetId": p.get("sheetId"), "title": title},
                                                   "fields": "title"}})
            ids[title] = p.get("sheetId")
        else:
            reqs.append({"addSheet": {"properties": {"title": title}}})
    if reqs:
        resp = sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute() or {}
        for r in resp.get("replies") or []:
            p = ((r or {}).get("addSheet") or {}).get("properties") or {}
            if p.get("title"):
                ids[p["title"]] = p.get("sheetId")
    sheets.spreadsheets().values().batchClear(spreadsheetId=sheet_id,
                                              body={"ranges": [_a1(t) for t in wanted]}).execute()
    data = [{"range": f"{_a1(t)}!A1", "majorDimension": "ROWS", "values": [[_cell(c) for c in row] for row in rows]}
            for t, rows in tabs if rows]
    if data:
        sheets.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id,
                                                   body={"valueInputOption": "RAW", "data": data}).execute()
    fmt = []
    for t, rows in tabs:
        sid = ids.get(t)
        if sid is None or not rows:
            continue
        fmt.append({"repeatCell": {"range": {"sheetId": sid},
                                   "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                                   "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}})
        fmt.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                                   "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                   "fields": "userEnteredFormat.textFormat.bold"}})
        fmt.append({"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                                              "fields": "gridProperties.frozenRowCount"}})
        for col, px in sorted(((widths or {}).get(t) or {}).items()):
            fmt.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                "properties": {"pixelSize": int(px)}, "fields": "pixelSize"}})
    if fmt:
        try:
            sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": fmt}).execute()
        except Exception as e:      # noqa: BLE001 — định dạng chỉ là phụ, nội dung đã ghi xong
            logger.info(f"[ContentVideo] sheet formatting skipped: {e}")
