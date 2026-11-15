"""Sao lưu ẢNH / VIDEO của Content Studio lên Google Drive — cửa HẸP cho trình kết nối MCP (15/11/2026).

Vì sao có: chủ máy giao agent (claude.ai qua TubeCLI Cloud) «sao lưu video lên Drive», agent báo bị chặn — File Manager
và Drive nằm trong BLOCK_ALL của trình kết nối (codex_gpt/tools.py) vì một agent bị chèn lệnh có thể đọc file bất kỳ rồi
đẩy ra ngoài. Cửa này KHÔNG mở lại hai thứ đó; nó chỉ làm đúng một việc:

- NGUỒN: file nằm TRỰC TIẾP trong một thư mục con của <DATA_DIR>/extensions_data/content_studio (không đệ quy), phải là
  ảnh / video thật (core/public_share.resolve: đuôi + magic bytes + chặn đường nhạy cảm).
- ĐÍCH: một tài khoản Google ĐÃ cấp quyền Drive trên chính máy này (Auth Manager) — không nhận token từ ngoài.
- KHÔNG xoá, không sửa file trên máy; không chia sẻ công khai gì trên Drive.
- Chủ phải bật quyền «drive» cho kết nối trên TubeCLI Cloud › Connectors (codex_gpt/tools.py DRIVE_PERM).

Một việc sao lưu chạy ở luồng nền (hàng chục GB mất nhiều giờ), mỗi lúc MỘT việc; trạng thái ghi ra đĩa sau mỗi file nên
khởi động lại không mất dấu — chạy lại cùng lệnh thì file đã lên đủ (cùng tên, cùng dung lượng) được bỏ qua.
"""
import fnmatch
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("DriveBackup")

STUDIO_REL = ("extensions_data", "content_studio")
MAX_FILES = 5000
MAX_FOLDER_DEPTH = 6
RETRIES = 2                     # thử lại tối đa 2 lần sau lượt đầu
ROWS_IN_STATUS = 400

_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_CANCEL: Dict[str, bool] = {}
_THREADS: Dict[str, threading.Thread] = {}


class BackupRefused(Exception):
    """Lời gọi không hợp lệ / ngoài phạm vi — câu tiếng Anh đưa thẳng cho agent."""


# ── Phạm vi ───────────────────────────────────────────────────────────────────

def studio_root() -> str:
    from tubecli import config
    return os.path.realpath(os.path.join(str(config.DATA_DIR), *STUDIO_REL))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:
        return False


def resolve_source(raw: Any) -> str:
    """Thư mục nguồn (đường thật). Nhận đường tuyệt đối hoặc đường tính từ thư mục Content Studio («outputs/exports»,
    «hook_videos»). Ngoài Content Studio → BackupRefused."""
    from tubecli.core import public_share as PS
    s = str(raw or "").strip().strip('"')
    if not s:
        raise BackupRefused("source is required: a folder inside the Content Studio data folder, for example "
                            "'outputs/exports' or 'hook_videos'")
    root = studio_root()
    cand = s if os.path.isabs(s) else os.path.join(root, *[p for p in s.replace("\\", "/").split("/") if p])
    real = os.path.realpath(cand)
    if not _inside(real, root):
        raise BackupRefused("Only folders inside the Content Studio data folder can be backed up "
                            f"({root}). '{s}' is outside it.")
    rel = os.path.relpath(real, root).replace("\\", "/").lower().split("/")
    if any(seg in PS.BLOCKED_SEGMENTS for seg in rel):
        raise BackupRefused(f"'{s}' is a protected folder and cannot be backed up.")
    if not os.path.isdir(real):
        raise BackupRefused(f"Folder not found on this server: {real}")
    return real


def scan(source: str, pattern: str = "") -> Tuple[List[Dict[str, Any]], int]:
    """([{name, path, size}], số file bị bỏ vì không phải ảnh/video thật). Chỉ file nằm TRỰC TIẾP trong `source`."""
    from tubecli.core import public_share as PS
    pat = (pattern or "*").strip().lower()
    rows, skipped = [], 0
    with os.scandir(source) as it:
        for e in it:
            if not e.is_file(follow_symlinks=False):
                continue
            name = e.name
            if not fnmatch.fnmatchcase(name.lower(), pat):
                continue
            if os.path.splitext(name)[1].lower() not in PS.SHAREABLE_EXTS:
                continue
            try:
                real, _kind, _mime = PS.resolve(e.path)
                rows.append({"name": name, "path": real, "size": os.path.getsize(real)})
            except (PS.ShareRefused, OSError):
                skipped += 1
            if len(rows) > MAX_FILES:
                raise BackupRefused(f"More than {MAX_FILES} files match — narrow the pattern.")
    return rows, skipped


def folder_parts(raw: Any) -> List[str]:
    parts = [p.strip() for p in str(raw or "").replace("\\", "/").split("/") if p.strip()]
    if not parts:
        raise BackupRefused("folder is required: the Drive folder path under My Drive, for example "
                            "'Archive 2026/TubeCLI exports' (missing folders are created)")
    if len(parts) > MAX_FOLDER_DEPTH or any(len(p) > 150 for p in parts):
        raise BackupRefused(f"folder: at most {MAX_FOLDER_DEPTH} levels, 150 characters each")
    return parts


def accounts() -> List[Dict[str, Any]]:
    """Tài khoản Google trên máy GHI được Drive: [{email, token_id, status}]."""
    from tubecli.extensions.content_video import drive_export as DX
    out = []
    for t in DX.google_tokens():
        if DX.can_write(t.get("scopes")):
            out.append({"email": str(t.get("authorized_email") or ""), "token_id": str(t.get("token_id") or ""),
                        "status": str(t.get("status") or "")})
    return out


def pick_account(email: Any) -> Dict[str, Any]:
    want = str(email or "").strip().lower()
    rows = accounts()
    if not want:
        raise BackupRefused("account is required: the Google account email (see drive_accounts)")
    hits = [a for a in rows if a["email"].lower() == want]
    if not hits:
        raise BackupRefused(f"No Google account '{email}' with Drive write access on this server. Available: "
                            + (", ".join(a["email"] for a in rows) or "none — authorize one in Auth Manager with "
                                                                      "the Google Drive scope"))
    live = [a for a in hits if a["status"] == "active"]
    return (live or hits)[0]


# ── Lưu trạng thái ────────────────────────────────────────────────────────────

def _state_dir() -> str:
    from tubecli import config
    d = os.path.join(str(config.DATA_DIR), "drive_backups")
    os.makedirs(d, exist_ok=True)
    return d


def _report_dir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    if os.path.isdir(docs):
        d = os.path.join(docs, "TubeCLI backups")
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except OSError:
            pass
    return _state_dir()


def _save(job: Dict[str, Any]) -> None:
    tmp = os.path.join(_state_dir(), f"{job['id']}.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(_state_dir(), f"{job['id']}.json"))
    except OSError as e:
        logger.warning(f"[DriveBackup] could not save job state: {e}")


def _load_all() -> None:
    """Nạp việc cũ từ đĩa (một lần). Việc ghi «running» mà không còn luồng nào chạy = server đã khởi động lại."""
    if _JOBS.get("__loaded__"):
        return
    _JOBS["__loaded__"] = {"id": "__loaded__"}
    try:
        names = [n for n in os.listdir(_state_dir()) if n.endswith(".json")]
    except OSError:
        return
    for n in names:
        try:
            with open(os.path.join(_state_dir(), n), encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(job, dict) and job.get("id"):
            if job.get("status") in ("running", "queued"):
                job["status"] = "interrupted"
                job["note"] = ("TubeCLI restarted while this backup was running. Start it again with the same "
                               "arguments: files already on Drive are skipped.")
            _JOBS.setdefault(job["id"], job)


def _gb(n: int) -> str:
    return f"{n / 1073741824:.2f} GB"


# ── Chạy ──────────────────────────────────────────────────────────────────────

def start(account: Any, source: Any, folder: Any, pattern: Any = "", largest_first: bool = True,
          runner: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Tạo một việc sao lưu và chạy nền. `runner` chỉ để test thay luồng thật."""
    acc = pick_account(account)
    src = resolve_source(source)
    parts = folder_parts(folder)
    rows, skipped = scan(src, str(pattern or ""))
    if not rows:
        raise BackupRefused(f"No image or video file matches '{pattern or '*'}' directly inside {src}.")
    rows.sort(key=lambda r: (-r["size"], r["name"]) if largest_first else (r["name"],))
    with _LOCK:
        _load_all()
        busy = next((j for j in _JOBS.values() if j.get("status") in ("running", "queued")), None)
        if busy:
            raise BackupRefused(f"Backup {busy['id']} is still running ({busy.get('done', 0)} of {busy.get('total', 0)} "
                                "files). One backup runs at a time — follow it with drive_backup_status, or cancel it.")
        job = {
            "id": "bk_" + uuid.uuid4().hex[:10], "status": "queued", "account": acc["email"], "token_id": acc["token_id"],
            "source": src, "pattern": str(pattern or "*"), "folder": "/".join(parts), "folder_id": "",
            "total": len(rows), "total_bytes": sum(r["size"] for r in rows), "done": 0, "uploaded": 0, "already": 0,
            "failed": 0, "uploaded_bytes": 0, "skipped_not_media": skipped, "current": "", "current_bytes": 0,
            "started_at": time.time(), "finished_at": 0, "note": "", "report": "", "drive_free_bytes": None,
            "files": [{"name": r["name"], "path": r["path"], "size": r["size"], "status": "pending", "drive_id": "",
                       "error": ""} for r in rows],
        }
        _JOBS[job["id"]] = job
        _CANCEL[job["id"]] = False
    _save(job)
    th = threading.Thread(target=runner or _run, args=(job,), name=f"drive-backup-{job['id']}", daemon=True)
    _THREADS[job["id"]] = th
    th.start()
    return job


def cancel(job_id: str) -> Dict[str, Any]:
    job = get(job_id)
    if job.get("status") in ("running", "queued"):
        _CANCEL[job["id"]] = True
        job["note"] = "Cancel requested — the backup stops after the current chunk."
    return job


def get(job_id: str = "") -> Dict[str, Any]:
    with _LOCK:
        _load_all()
        jobs = [j for k, j in _JOBS.items() if k != "__loaded__"]
    if not jobs:
        raise BackupRefused("No backup has been started on this server yet.")
    if job_id:
        hit = next((j for j in jobs if j["id"] == str(job_id).strip()), None)
        if not hit:
            raise BackupRefused(f"No backup '{job_id}'. Known: " + ", ".join(j["id"] for j in jobs[-10:]))
        return hit
    return max(jobs, key=lambda j: j.get("started_at") or 0)


def _quota_free(drive) -> Optional[int]:
    try:
        q = (drive.about().get(fields="storageQuota").execute() or {}).get("storageQuota") or {}
        if q.get("limit") is None:
            return None                 # không giới hạn (Workspace)
        return max(0, int(q["limit"]) - int(q.get("usage") or 0))
    except Exception:                   # noqa: BLE001
        return None


def _is_quota_error(e: Exception) -> bool:
    s = str(e)
    return "storageQuotaExceeded" in s or "quotaExceeded" in s and "storage" in s.lower()


def _run(job: Dict[str, Any]) -> None:
    from tubecli.extensions.content_video import drive_export as DX
    jid = job["id"]
    cancelled = lambda: bool(_CANCEL.get(jid))      # noqa: E731

    class _Stop(Exception):
        pass

    try:
        job["status"] = "running"
        drive, _sheets = DX.services(job["token_id"])
        parent = "root"
        for name in job["folder"].split("/"):
            parent = str(DX.find_or_create_folder(drive, parent, name)["id"])
        job["folder_id"] = parent
        job["drive_free_bytes"] = _quota_free(drive)
        there = DX.list_children(drive, parent)
        _save(job)
        for row in job["files"]:
            if cancelled():
                raise _Stop()
            hit = there.get(row["name"])
            if hit and str(hit.get("size") or "") == str(row["size"]):
                row.update(status="already", drive_id=str(hit.get("id") or ""))
                job["already"] += 1
                job["done"] += 1
                _save(job)
                continue
            job["current"], job["current_bytes"] = row["name"], 0
            last = ""
            for attempt in range(1 + RETRIES):
                try:
                    if not os.path.isfile(row["path"]) or os.path.getsize(row["path"]) != row["size"]:
                        raise OSError("the file changed or disappeared on the server")

                    def _progress(n, _job=job):
                        _job["current_bytes"] = int(n)

                    resp = DX.upload_file(drive, row["path"], row["name"], parent, on_progress=_progress,
                                          cancelled=cancelled, cancel_exc=_Stop) or {}
                    if str(resp.get("size") or "") != str(row["size"]):
                        raise RuntimeError(f"Drive reports {resp.get('size')} bytes, the file has {row['size']}")
                    row.update(status="ok", drive_id=str(resp.get("id") or ""), error="")
                    job["uploaded"] += 1
                    job["uploaded_bytes"] += row["size"]
                    last = ""
                    break
                except _Stop:
                    raise
                except Exception as e:      # noqa: BLE001
                    last = str(e)[:300]
                    logger.warning(f"[DriveBackup] {row['name']} attempt {attempt + 1}: {last}")
                    if _is_quota_error(e):
                        row.update(status="error", error="Google Drive is full (storage quota exceeded)")
                        job["failed"] += 1
                        job["done"] += 1
                        job["note"] = ("Stopped: Google Drive is full. Free space on the account or buy storage, "
                                       "then start the backup again — files already uploaded are skipped.")
                        raise _Stop()
                    time.sleep(min(30, 5 * (attempt + 1)))
            if last:
                row.update(status="error", error=last)
                job["failed"] += 1
            job["done"] += 1
            job["current"], job["current_bytes"] = "", 0
            _save(job)
        job["status"] = "done" if not job["failed"] else "done_with_errors"
    except _Stop:
        job["status"] = "cancelled" if cancelled() else "stopped"
    except Exception as e:      # noqa: BLE001
        job["status"] = "failed"
        job["note"] = str(e)[:400]
        logger.warning(f"[DriveBackup] job {jid} failed: {e}")
    finally:
        job["current"], job["current_bytes"] = "", 0
        job["finished_at"] = time.time()
        try:
            job["report"] = write_report(job)
        except OSError as e:
            job["note"] = (job.get("note") or "") + f" (report not written: {e})"
        _save(job)


def write_report(job: Dict[str, Any]) -> str:
    """Báo cáo .txt: mỗi file một dòng (tên, dung lượng, Drive file ID, OK/ERROR) + tổng máy so với Drive."""
    path = os.path.join(_report_dir(), f"drive_backup_{job['id']}.txt")
    on_drive = [r for r in job["files"] if r["status"] in ("ok", "already")]
    lines = [
        f"TubeCLI Drive backup {job['id']} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(job.get('finished_at') or time.time()))}",
        f"Status: {job['status']}" + (f" — {job['note']}" if job.get("note") else ""),
        f"Google account: {job['account']}",
        f"Drive folder: {job['folder']} (id {job.get('folder_id') or '?'})",
        f"Source: {job['source']} (pattern {job['pattern']})",
        f"On this server: {job['total']} files, {job['total_bytes']} bytes ({_gb(job['total_bytes'])})",
        f"On Drive (same name and size): {len(on_drive)} files, {sum(r['size'] for r in on_drive)} bytes "
        f"({_gb(sum(r['size'] for r in on_drive))})",
        f"Uploaded now: {job['uploaded']} · already there: {job['already']} · failed: {job['failed']} · "
        f"not started: {sum(1 for r in job['files'] if r['status'] == 'pending')}",
        "Nothing was deleted on this server.",
        "",
        "STATUS\tSIZE_BYTES\tDRIVE_FILE_ID\tNAME\tERROR",
    ]
    label = {"ok": "OK", "already": "OK", "error": "ERROR", "pending": "NOT_STARTED"}
    for r in job["files"]:
        lines.append("\t".join([label.get(r["status"], r["status"]), str(r["size"]), r.get("drive_id") or "-",
                                r["name"], r.get("error") or ""]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def summary(job: Dict[str, Any], files: bool = False) -> Dict[str, Any]:
    """Bản gọn cho agent: số đếm, file đang tải, lỗi; `files=True` thêm từng dòng (tối đa ROWS_IN_STATUS)."""
    out = {k: job.get(k) for k in ("id", "status", "account", "folder", "folder_id", "source", "pattern", "total",
                                   "done", "uploaded", "already", "failed", "skipped_not_media", "note", "report")}
    out["total_size"] = _gb(job["total_bytes"])
    out["uploaded_size"] = _gb(job["uploaded_bytes"])
    if job.get("drive_free_bytes") is not None:
        out["drive_free_at_start"] = _gb(job["drive_free_bytes"])
        left = sum(r["size"] for r in job["files"] if r["status"] == "pending")
        if job["status"] in ("running", "queued") and left > job["drive_free_bytes"]:
            out["warning"] = (f"Drive had {_gb(job['drive_free_bytes'])} free at the start; this backup needs more. "
                              "It stops with a clear error when Drive is full.")
    if job.get("current"):
        size = next((r["size"] for r in job["files"] if r["name"] == job["current"]), 0)
        out["uploading"] = f"{job['current']} ({job.get('current_bytes', 0) * 100 // max(1, size)}%)"
    out["errors"] = [{"name": r["name"], "error": r["error"]} for r in job["files"] if r["status"] == "error"][:50]
    if files:
        out["files"] = [{"name": r["name"], "size": r["size"], "drive_id": r.get("drive_id") or "", "status": r["status"]}
                        for r in job["files"][:ROWS_IN_STATUS]]
        if len(job["files"]) > ROWS_IN_STATUS:
            out["files_note"] = f"first {ROWS_IN_STATUS} of {len(job['files'])} — the full list is in the report file"
    return out
