"""
Disk usage — volume enumeration and cancellable background directory scans.

Implements the /disk and /usage/* half of the file-manager API contract:

    GET  /disk                        -> list_volumes()
    POST /usage/scan                  -> start_scan(path, service)
    GET  /usage/scan/{scan_id}        -> get_scan(scan_id)
    POST /usage/scan/{scan_id}/cancel -> cancel_scan(scan_id)
    (housekeeping)                    -> scan_gc()

Nothing here writes to the filesystem; every call is read-only.

Design notes that are load-bearing (measured on this repo, Python 3.12 / Windows 11,
against C:\\tubecreate-vue\\tubecli\\data):

* A directory tree is walked with an explicit stack, never os.walk. os.walk cannot
  report the errors this contract has to surface, and its `followlinks=False`
  does NOT stop it from descending into Windows junctions — measured on data/:
  followlinks=True and followlinks=False both returned 95,295,414,862 bytes /
  422,230 files, while pruning reparse points returned 52,611,419,856 bytes /
  289,740 files. The naive walk over-reports by 42.68 GB because the 23 junctions
  under data/ point back inside data/, so the same bytes are counted twice.

* Link detection is by reparse TAG, not by the reparse attribute alone.
  os.path.islink()/stat.S_ISLNK() are both False for a junction (verified), so the
  attribute is the only portable signal — but OneDrive "Files On-Demand"
  placeholders also carry the reparse attribute, and ~/Documents is an allowed
  root. Pruning every reparse point would silently report ~0 bytes for a
  OneDrive-backed Documents folder. Only IO_REPARSE_TAG_MOUNT_POINT and
  IO_REPARSE_TAG_SYMLINK are treated as links; any other tag is a real directory.

* Directory identity comes from DirEntry.inode(), not DirEntry.stat().st_ino.
  Verified on Windows: DirEntry.stat(follow_symlinks=False) returns st_ino=0 and
  st_dev=0, while DirEntry.inode() on the same entry returns the real file index
  (2814749768947096) at a measured 10.7 us per directory. Keying the loop guard on
  st_ino would collapse every directory to the same key and prune the whole tree.
"""

from __future__ import annotations

import heapq
import os
import stat
import string
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# psutil is a declared dependency (pyproject.toml), so it is the primary path for
# /disk. The stdlib fallback below still has to be a real implementation, not a
# stub: a broken psutil build must not take the whole endpoint down with it.
try:
    import psutil
except Exception as _psutil_exc:  # not just ImportError — a broken build raises OSError
    psutil = None
    _PSUTIL_ERROR: Optional[str] = "%s: %s" % (type(_psutil_exc).__name__, _psutil_exc)
else:
    _PSUTIL_ERROR = None


# ── Tunables ──────────────────────────────────────────────────────────────────

SCAN_TTL_SECONDS = 3600.0        # contract: drop finished scans older than 1h
MAX_CONCURRENT_SCANS = 3         # a scan is disk-bound; more in parallel is slower, not faster
MAX_TRACKED_SCANS = 64           # hard ceiling so an automated client cannot grow the registry
LARGEST_FILES_LIMIT = 50         # contract: largest = top 50 files in the tree
MAX_REPORTED_ERRORS = 200        # every error is COUNTED; this caps only how many are echoed
MAX_DEPTH = 512                  # backstop for pathological nesting the identity guard misses
FLUSH_EVERY_ENTRIES = 256        # progress publish + cancel check cadence, in directory entries
GC_MIN_INTERVAL = 60.0           # throttle for the opportunistic gc run inside get_scan()
VOLUME_CACHE_SECONDS = 5.0       # /disk is polled; stat'ing a slow network drive per poll hurts

_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_IO_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
_IO_REPARSE_TAG_SYMLINK = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
_LINK_REPARSE_TAGS = frozenset((_IO_REPARSE_TAG_MOUNT_POINT, _IO_REPARSE_TAG_SYMLINK))

_IS_WINDOWS = os.name == "nt"
_IS_DARWIN = sys.platform == "darwin"

# Filesystems that do not describe storage the user can manage. Kept as an
# explicit deny-list rather than an allow-list so an unusual-but-real filesystem
# (exfat, xfs, zfs, btrfs, apfs, iso9660 …) is never hidden by accident.
_PSEUDO_FSTYPES = frozenset({
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs",
    "devfs", "devpts", "devtmpfs", "efivarfs", "fuse.gvfsd-fuse", "fuse.portal",
    "fuse.snapfuse", "fusectl", "hugetlbfs", "mqueue", "nsfs", "overlay",
    "overlayfs", "pstore", "proc", "procfs", "ramfs", "rpc_pipefs", "securityfs",
    "selinuxfs", "squashfs", "sysfs", "tmpfs", "tracefs",
})


# ── Small helpers ─────────────────────────────────────────────────────────────

def _describe_os_error(exc: BaseException) -> str:
    """Turn an OSError into something a non-technical user can act on.

    The bare str(OSError) on Windows is often just a number, and errno alone
    tells the user nothing. Keep both the human sentence and the machine code so
    a support request can be diagnosed.
    """
    if not isinstance(exc, OSError):
        return "%s: %s" % (type(exc).__name__, exc)
    parts = []
    text = exc.strerror or str(exc)
    if text:
        parts.append(text)
    winerror = getattr(exc, "winerror", None)
    if winerror:
        parts.append("winerror %s" % winerror)
    elif exc.errno:
        parts.append("errno %s" % exc.errno)
    return " — ".join(parts) if parts else type(exc).__name__


def _safe_str(value: str) -> str:
    """Make a filesystem string safe to hand to the JSON encoder.

    On POSIX a filename may hold bytes that are not valid UTF-8, and os.scandir
    (like psutil) hands them back as lone surrogates — PEP 383's surrogateescape.
    Starlette's JSONResponse.render is json.dumps(..., ensure_ascii=False).encode
    ("utf-8") (verified against the installed starlette 0.50.0), and that encoder
    rejects a lone surrogate: 'utf-8' codec can't encode character '\\udcff'.
    So one such name anywhere in the tree used to make GET /usage/scan/{id} raise
    inside the encoder on every poll — the walk itself had finished, but its
    result was permanently unreadable and the UI polled a job it would never see
    complete. Windows cannot hit this (NTFS names are valid UTF-16), which is why
    it went unnoticed here.

    Duplicated from cleanup._safe_str rather than imported: pulling in that
    1,643-line module would make a background scan depend on the whole cleanup
    engine importing successfully, and this module is deliberately standalone for
    that reason (see the deferred file_service import in start_scan).
    """
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-8", "replace").decode("utf-8", "replace")


def _format_mtime(mtime: float) -> str:
    """Match the timestamp format file_service._file_info already returns."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
    except (OSError, ValueError, OverflowError):
        # A corrupt or out-of-range mtime must not kill the scan; say so instead.
        return ""


# ── /disk — volume enumeration ────────────────────────────────────────────────

def _windows_volume_details(root: str) -> Tuple[str, str]:
    """(label, fstype) for a Windows drive root, ("", "") if it cannot be read.

    Uses ctypes/kernel32 because pywin32 is not available in this environment and
    is not a declared dependency. Verified working: GetVolumeInformationW on C:\\
    returned fstype 'NTFS' with an empty label (this volume simply has no label).
    """
    if not _IS_WINDOWS:
        return "", ""
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        name_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        max_len = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), name_buf, 261,
            ctypes.byref(serial), ctypes.byref(max_len), ctypes.byref(flags),
            fs_buf, 261,
        )
        if not ok:
            return "", ""
        return name_buf.value or "", fs_buf.value or ""
    except Exception:
        # A missing/blocked kernel32 only costs us the label — the volume itself
        # is still reported from psutil/shutil data, so degrade quietly here.
        return "", ""


def _skip_darwin_system_volume(mountpoint: str) -> bool:
    """macOS splits one APFS container across /System/Volumes/{Preboot,VM,Update,…}.

    They all report the container's total/free, so listing them shows the user
    four or five identical copies of the same disk. /System/Volumes/Data is the
    real user data volume and is kept. NOT verified on a Mac — see the note in the
    module docstring of the caller's report.
    """
    if not _IS_DARWIN:
        return False
    prefix = "/System/Volumes/"
    if not mountpoint.startswith(prefix):
        return False
    return mountpoint.rstrip("/") != "/System/Volumes/Data"


def _volume_record(path: str, label: str, fstype: str) -> Dict[str, Any]:
    """Build one /disk entry, reporting a usage failure instead of hiding it."""
    # Only the emitted copies are repaired; every filesystem call below still gets
    # the caller's exact `path`. A POSIX mountpoint carries the volume label as
    # raw bytes (a FAT32 stick labelled in a legacy codepage auto-mounts under
    # /media/<label>), so the same lone-surrogate crash _safe_str describes would
    # take out the whole /disk list, not just that one volume.
    record: Dict[str, Any] = {
        "path": _safe_str(path),
        "label": _safe_str(label or path),
        "total": 0,
        "used": 0,
        "free": 0,
        "percent": 0.0,
        "fstype": fstype or "",
    }
    try:
        if psutil is not None:
            usage = psutil.disk_usage(path)
            total, used, free, percent = usage.total, usage.used, usage.free, usage.percent
        else:
            import shutil

            total, used, free = shutil.disk_usage(path)
            percent = round(used / (used + free) * 100.0, 1) if (used + free) else 0.0
    except OSError as exc:
        # An unmounted CD, a disconnected network drive or a permission problem.
        # The volume still exists, so keep it in the list and say what went wrong
        # rather than dropping it and showing the user a shorter disk list.
        record["error"] = "Không đọc được dung lượng: %s" % _describe_os_error(exc)
        return record
    except Exception as exc:
        record["error"] = "Không đọc được dung lượng: %s" % exc
        return record

    record["total"] = int(total)
    record["used"] = int(used)
    record["free"] = int(free)
    # percent comes from psutil so it matches `df`. On Linux, used + free < total
    # by the root-reserved block count, so the UI must render `free` as given and
    # never recompute it as total - used.
    record["percent"] = round(float(percent), 1)
    return record


def _volumes_via_psutil() -> List[Dict[str, Any]]:
    partitions = psutil.disk_partitions(all=False)
    volumes: List[Dict[str, Any]] = []
    seen_devices: set = set()
    seen_st_dev: set = set()

    for part in partitions:
        fstype = (part.fstype or "").strip()
        if fstype.lower() in _PSEUDO_FSTYPES:
            continue
        mountpoint = part.mountpoint
        if not mountpoint or _skip_darwin_system_volume(mountpoint):
            continue

        # Contract: skip duplicates of the same device. Bind mounts and btrfs
        # subvolumes appear once per mountpoint but share one pool of free space,
        # so listing them all would triple-count the same disk.
        device = os.path.normcase(part.device or "")
        if device and device in seen_devices:
            continue
        try:
            st_dev = os.stat(mountpoint).st_dev
        except OSError:
            st_dev = None
        # st_dev is 0 for every path on Windows, so it can only dedupe on POSIX.
        if st_dev and st_dev in seen_st_dev:
            continue

        label, win_fstype = _windows_volume_details(mountpoint)
        record = _volume_record(mountpoint, label, fstype or win_fstype)
        if record.get("total", 0) <= 0 and "error" not in record:
            # A zero-byte "volume" is a pseudo filesystem the fstype list missed.
            continue

        if device:
            seen_devices.add(device)
        if st_dev:
            seen_st_dev.add(st_dev)
        volumes.append(record)

    return volumes


def _volumes_via_stdlib() -> List[Dict[str, Any]]:
    """Fallback used when psutil is unavailable or returns nothing."""
    volumes: List[Dict[str, Any]] = []

    if _IS_WINDOWS:
        drive_mask = 0
        try:
            import ctypes

            drive_mask = ctypes.WinDLL("kernel32", use_last_error=True).GetLogicalDrives()
        except Exception:
            drive_mask = 0
        if not drive_mask:
            # Last resort: probe the letters directly. Slower, but never empty.
            for letter in string.ascii_uppercase:
                root = letter + ":" + os.sep
                if os.path.isdir(root):
                    volumes.append(_volume_record(root, *_windows_volume_details(root)))
            return volumes

        for index, letter in enumerate(string.ascii_uppercase):
            if not (drive_mask >> index) & 1:
                continue
            root = letter + ":" + os.sep
            label, fstype = _windows_volume_details(root)
            record = _volume_record(root, label, fstype)
            if record.get("total", 0) <= 0 and "error" not in record:
                continue
            volumes.append(record)
        return volumes

    # POSIX: /proc/mounts on Linux, `mount` output is not parsed — anything we
    # cannot read cleanly degrades to the root filesystem, which always exists.
    seen: set = set()
    candidates: List[Tuple[str, str]] = []
    for table in ("/proc/self/mounts", "/etc/mtab"):
        try:
            with open(table, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    fields = line.split()
                    if len(fields) < 3:
                        continue
                    device, mountpoint, fstype = fields[0], fields[1], fields[2]
                    if fstype.lower() in _PSEUDO_FSTYPES:
                        continue
                    # /proc/mounts octal-escapes spaces and tabs in mountpoints.
                    mountpoint = mountpoint.replace("\\040", " ").replace("\\011", "\t")
                    if _skip_darwin_system_volume(mountpoint) or mountpoint in seen:
                        continue
                    seen.add(mountpoint)
                    candidates.append((mountpoint, fstype))
            break
        except OSError:
            continue

    if not candidates:
        candidates = [("/", "")]

    seen_st_dev: set = set()
    for mountpoint, fstype in candidates:
        try:
            st_dev = os.stat(mountpoint).st_dev
        except OSError:
            st_dev = None
        if st_dev and st_dev in seen_st_dev:
            continue
        label = os.path.basename(mountpoint.rstrip("/")) or mountpoint
        record = _volume_record(mountpoint, label, fstype)
        if record.get("total", 0) <= 0 and "error" not in record:
            continue
        if st_dev:
            seen_st_dev.add(st_dev)
        volumes.append(record)

    return volumes


_volume_cache: Optional[List[Dict[str, Any]]] = None
_volume_cache_at = 0.0
_volume_lock = threading.Lock()


def list_volumes(refresh: bool = False) -> List[Dict[str, Any]]:
    """Enumerate mounted volumes for GET /disk.

    Returns a list of {path, label, total, used, free, percent, fstype}. A volume
    whose usage could not be read is still listed, with zeroed figures and an
    extra "error" key explaining why — dropping it would quietly show the user a
    shorter disk list than the machine actually has.

    Results are cached for VOLUME_CACHE_SECONDS because a disconnected network
    drive makes os.stat/disk_usage block, and /disk is a polled endpoint.

    Raises RuntimeError if no volume at all could be enumerated, so the caller
    returns a real error instead of an empty list that reads as "no disks".
    """
    global _volume_cache, _volume_cache_at

    now = time.monotonic()
    if not refresh:
        cached = _volume_cache
        if cached is not None and (now - _volume_cache_at) < VOLUME_CACHE_SECONDS:
            return [dict(item) for item in cached]

    with _volume_lock:
        now = time.monotonic()
        if not refresh and _volume_cache is not None and (now - _volume_cache_at) < VOLUME_CACHE_SECONDS:
            return [dict(item) for item in _volume_cache]

        reasons: List[str] = []
        volumes: List[Dict[str, Any]] = []

        if psutil is not None:
            try:
                volumes = _volumes_via_psutil()
            except Exception as exc:
                reasons.append("psutil: %s" % exc)
        elif _PSUTIL_ERROR:
            reasons.append("psutil không dùng được (%s)" % _PSUTIL_ERROR)

        if not volumes:
            try:
                volumes = _volumes_via_stdlib()
            except Exception as exc:
                reasons.append("stdlib: %s" % exc)

        if not volumes:
            raise RuntimeError(
                "Không liệt kê được ổ đĩa nào trên máy này."
                + (" Lý do: " + "; ".join(reasons) if reasons else "")
            )

        volumes.sort(key=lambda item: os.path.normcase(item["path"]))
        _volume_cache = volumes
        _volume_cache_at = time.monotonic()
        return [dict(item) for item in volumes]


# ── /usage/scan — cancellable background directory scan ───────────────────────

class _SkipDir(Exception):
    """Internal: this directory must not be read, and the reason is recorded."""


class _Scan:
    """One background scan. All mutable state is published under `_lock`.

    The worker thread keeps its hot counters in locals and copies them into the
    published fields every FLUSH_EVERY_ENTRIES entries, so the lock is held only
    for the duration of the copy and a reader never blocks the walk.
    """

    def __init__(self, scan_id: str, root: str, service: Any):
        self.id = scan_id
        self.root = root
        self._service = service
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.thread: Optional[threading.Thread] = None

        # ── published state (read only while holding _lock) ──
        self.status = "running"
        self.percent = 0
        self.scanned_files = 0
        self.scanned_dirs = 0
        self.total_bytes = 0
        self.current = root
        self.error: Optional[str] = None
        self.children: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, str]] = []
        self.error_count = 0
        self.permission_denied = 0
        self.skipped_links = 0
        self.skipped_loops = 0
        self.started_at = time.time()
        self.finished_at: Optional[float] = None

        # ── worker-thread-only state (never touched by readers) ──
        self._started_mono = time.monotonic()
        self._finished_mono: Optional[float] = None
        self._files = 0
        self._dirs = 0
        self._bytes = 0
        self._visited: set = set()
        self._largest: List[Tuple[int, int, str, str, float]] = []  # min-heap of top N
        self._largest_seq = 0
        self._child_records: List[Dict[str, Any]] = []
        self._unit_total = 1
        self._unit_done = 0
        self._unit_inner = 0.0
        self._entries_since_flush = 0

    # ── publishing ────────────────────────────────────────────────────────────

    def _compute_percent(self) -> int:
        """Progress as completed top-level children, refined by the current one.

        There is no way to know the size of a tree without walking it, so this is
        an estimate and is documented as such in the response. It is monotonic
        (clamped below) and capped at 99 until the walk really finishes, so it can
        never claim completion for work that has not happened.
        """
        if self._unit_total <= 0:
            return 0
        fraction = (self._unit_done + self._unit_inner) / float(self._unit_total)
        return max(0, min(99, int(fraction * 100)))

    def _publish(self, current: Optional[str] = None, force: bool = False) -> None:
        self._entries_since_flush = 0
        percent = self._compute_percent()
        with self._lock:
            if self.status != "running" and not force:
                return
            self.scanned_files = self._files
            self.scanned_dirs = self._dirs
            self.total_bytes = self._bytes
            if current is not None:
                self.current = current
            # Never let the bar go backwards when a subtree turns out to be
            # deeper than the previous estimate assumed.
            if percent > self.percent:
                self.percent = percent
            self.children = [dict(record) for record in self._child_records]

    def _tick(self, current: str) -> bool:
        """Cadence hook: publish progress and report whether we must stop.

        Called once per FLUSH_EVERY_ENTRIES directory entries and once per
        directory, which on the measured cold throughput of this repo (227 files
        per second) is several times a second — well inside the one-second
        cancellation budget the task requires.
        """
        self._entries_since_flush += 1
        if self._entries_since_flush >= FLUSH_EVERY_ENTRIES:
            self._publish(current=current)
        return self._cancel.is_set()

    def _add_error(self, path: str, message: str, exc: Optional[BaseException] = None,
                   permission: bool = False) -> None:
        detail = message if exc is None else "%s: %s" % (message, _describe_os_error(exc))
        with self._lock:
            self.error_count += 1
            if permission:
                self.permission_denied += 1
            if len(self.errors) < MAX_REPORTED_ERRORS:
                self.errors.append({"path": path, "error": detail})

    # ── path safety ───────────────────────────────────────────────────────────

    def _validate_dir(self, path: str) -> str:
        """Run every directory through FileService._validate_path before reading it.

        This is not free and the cost is worth stating plainly. Measured in situ
        on 18,621 directories, interleaved with the walk that actually reads them:

            full _validate_path        186-430 us/dir
            of which os.path.realpath  290 us/dir   (reproducible across rounds)
            everything except realpath  71 us/dir

        On a warm re-scan that roughly triples wall time (0.9s -> 5.4s for 145k
        files). On a first, cold scan — the case a user actually waits through —
        the measured walk throughput is 227 files/s, so the same 8s of validation
        is about 1% of the job. It is paid because the alternative is to
        re-implement the sandbox rules here, and a second copy of a security check
        is a copy that will drift out of step with file_service.py.

        The blocklist half is what earns it: if the sandbox is ever widened with
        extra_roots, a blocked path such as ~/.ssh or ~/AppData/Local can sit
        *inside* an allowed root, and only a per-directory check catches it on the
        way down.
        """
        try:
            validated = self._service._validate_path(path)
        except ValueError as exc:
            self._add_error(path, "Bỏ qua vì nằm ngoài vùng cho phép (%s)" % exc)
            raise _SkipDir from None
        except Exception as exc:
            self._add_error(path, "Không kiểm tra được đường dẫn", exc)
            raise _SkipDir from None

        # _validate_path no longer expands %VAR%/$VAR (file_service.py), and it
        # now refuses a "~name" rewrite itself, so this is a backstop rather than
        # the primary guard: whatever future rewrite creeps back into validation,
        # reading the rewritten path would silently measure a different folder
        # than the one the user asked about, so refuse instead of reporting it.
        if os.path.normcase(validated) != os.path.normcase(os.path.normpath(path)):
            self._add_error(
                path,
                "Tên thư mục chứa ký tự bị diễn giải thành đường dẫn khác nên không quét",
            )
            raise _SkipDir

        # Lexical backstop: the walk must never leave the tree the user asked for.
        if not self._service._under(validated, self.root):
            self._add_error(path, "Bỏ qua vì nằm ngoài thư mục đang quét")
            raise _SkipDir

        return validated

    # ── walking ───────────────────────────────────────────────────────────────

    @staticmethod
    def _identity(entry: os.DirEntry, st: os.stat_result) -> Optional[Tuple[int, int]]:
        """(st_dev, inode) for a directory entry, or None when it is unknowable.

        entry.inode() is free on POSIX (it comes from d_ino) and costs one lstat
        on Windows, where it is the only call that returns a real file index —
        entry.stat().st_ino is 0 there. st_dev is likewise 0 on Windows, which is
        harmless: it is a constant, so the key stays unique per file index, and a
        Windows volume can only be entered through a mount point, which is pruned
        as a link before we ever get here.

        Returning None means "do not prune". Guessing wrong in that direction
        counts a subtree twice; guessing wrong in the other direction deletes an
        entire branch from the user's report.
        """
        try:
            inode = entry.inode()
        except OSError:
            return None
        if not inode:
            return None
        return (getattr(st, "st_dev", 0) or 0, inode)

    def _read_dir(self, path: str, depth: int, acc: Optional[Dict[str, Any]],
                  collect: Optional[List[Dict[str, Any]]] = None) -> List[Tuple[str, int]]:
        """Read one directory. Returns the subdirectories to descend into.

        `acc` is the top-level child record these bytes belong to, or None while
        reading the scan root itself. `collect`, used only for the root, receives
        one display record per entry. Building those records here rather than
        re-reading the root afterwards is what keeps sum(children) equal to the
        totals: a second pass would see a directory that had changed in between
        and produce child rows that do not add up.
        """
        subdirs: List[Tuple[str, int]] = []
        try:
            validated = self._validate_dir(path)
        except _SkipDir:
            return subdirs

        try:
            iterator = os.scandir(validated)
        except PermissionError as exc:
            self._add_error(path, "Không có quyền đọc thư mục này", exc, permission=True)
            return subdirs
        except FileNotFoundError:
            self._add_error(path, "Thư mục đã bị xoá hoặc đổi tên trong lúc quét")
            return subdirs
        except OSError as exc:
            self._add_error(path, "Không mở được thư mục", exc)
            return subdirs

        with iterator:
            while True:
                # next() rather than `for entry in iterator`: on POSIX the
                # underlying readdir can fail partway through a large directory,
                # and a plain for-loop would let that OSError escape and abort the
                # whole scan instead of costing us one directory.
                try:
                    entry = next(iterator)
                except StopIteration:
                    break
                except PermissionError as exc:
                    self._add_error(path, "Mất quyền đọc giữa chừng, phần còn lại của thư mục bị bỏ qua",
                                    exc, permission=True)
                    break
                except OSError as exc:
                    self._add_error(path, "Lỗi khi đọc danh sách thư mục, phần còn lại bị bỏ qua", exc)
                    break

                if self._tick(path):
                    return subdirs

                self._consume_entry(entry, depth, acc, subdirs, collect)

        return subdirs

    @staticmethod
    def _new_child(entry: os.DirEntry, is_dir: bool, is_link: bool, size: int) -> Dict[str, Any]:
        """One row of the `children` array.

        `is_dir` is the no-follow answer, so a POSIX symlink pointing at a
        directory reports is_dir False while a Windows junction reports True. That
        asymmetry is deliberate — following the link to find out could block on a
        dead network target — so the UI should decide its icon from `is_link`
        first and only then from `is_dir`.
        """
        return {
            "name": entry.name,
            "path": entry.path,
            "is_dir": bool(is_dir),
            "bytes": size,
            "file_count": 0 if (is_dir or is_link) else 1,
            "dir_count": 0,
            "link_count": 0,
            "is_link": bool(is_link),
            "partial": bool(is_dir and not is_link),
        }

    def _consume_entry(self, entry: os.DirEntry, depth: int,
                       acc: Optional[Dict[str, Any]], subdirs: List[Tuple[str, int]],
                       collect: Optional[List[Dict[str, Any]]] = None) -> None:
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError as exc:
            self._add_error(entry.path, "Không đọc được thông tin mục này", exc,
                            permission=isinstance(exc, PermissionError))
            return

        try:
            is_symlink = entry.is_symlink()
        except OSError:
            is_symlink = False

        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError as exc:
            self._add_error(entry.path, "Không xác định được đây là tệp hay thư mục", exc,
                            permission=isinstance(exc, PermissionError))
            return

        if is_symlink:
            self._note_link(acc)
            if collect is not None:
                collect.append(self._new_child(entry, is_dir, True, 0))
            return

        if is_dir:
            attributes = getattr(st, "st_file_attributes", 0)
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                tag = getattr(st, "st_reparse_tag", 0)
                # Junction (MOUNT_POINT) or directory symlink: its contents are
                # counted under their real path, so descending double-counts them.
                # An unknown tag is left alone — OneDrive placeholders carry the
                # same attribute and are real data.
                if tag in _LINK_REPARSE_TAGS or not tag:
                    self._note_link(acc)
                    if collect is not None:
                        collect.append(self._new_child(entry, is_dir, True, 0))
                    return

            identity = self._identity(entry, st)
            if identity is not None:
                if identity in self._visited:
                    with self._lock:
                        self.skipped_loops += 1
                    return
                self._visited.add(identity)

            if depth >= MAX_DEPTH:
                self._add_error(entry.path, "Thư mục lồng nhau quá %d cấp nên dừng ở đây" % MAX_DEPTH)
                return

            self._dirs += 1
            if acc is not None:
                acc["dir_count"] += 1
            if collect is not None:
                collect.append(self._new_child(entry, True, False, 0))
            subdirs.append((entry.path, depth + 1))
            return

        # Everything that is not a directory counts as a file. Sockets and FIFOs
        # report st_size 0, which is the honest answer for how much disk they use.
        size = int(getattr(st, "st_size", 0) or 0)
        self._files += 1
        self._bytes += size
        if acc is not None:
            acc["file_count"] += 1
            acc["bytes"] += size
        if collect is not None:
            collect.append(self._new_child(entry, False, False, size))
        self._push_largest(entry.name, entry.path, size, getattr(st, "st_mtime", 0.0))

    def _note_link(self, acc: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self.skipped_links += 1
        if acc is not None:
            acc["link_count"] += 1

    def _push_largest(self, name: str, path: str, size: int, mtime: float) -> None:
        if size <= 0:
            return
        self._largest_seq += 1
        # The sequence number is the tiebreaker so equal-sized files never make
        # heapq fall through to comparing paths (fine, but order-dependent).
        item = (size, self._largest_seq, name, path, mtime)
        # The lock is taken only when the heap really changes — the size
        # comparison rejects the overwhelming majority of files, so a scan of
        # hundreds of thousands of files takes it a few dozen times.
        if len(self._largest) < LARGEST_FILES_LIMIT:
            with self._lock:
                heapq.heappush(self._largest, item)
        elif size > self._largest[0][0]:
            with self._lock:
                heapq.heappushpop(self._largest, item)

    def _walk_child(self, start_path: str, acc: Dict[str, Any]) -> None:
        """Walk one top-level child depth-first, updating its running totals."""
        stack: List[Tuple[str, int]] = [(start_path, 1)]
        done = 0
        while stack:
            if self._cancel.is_set():
                return
            path, depth = stack.pop()
            done += 1
            # Directory-queue ratio inside this child: converges to 1 as the
            # stack drains, which is what makes the overall percent move even when
            # the whole tree is one giant child.
            self._unit_inner = done / float(done + len(stack)) if (done + len(stack)) else 1.0
            self._publish(current=path)
            stack.extend(self._read_dir(path, depth, acc))

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        root = self.root

        # Seed the loop guard with the root so a link pointing back at it is
        # recognised rather than walked a second time. Both identities are seeded:
        # os.lstat for the root as named, and os.stat for what it resolves to, in
        # case the user asked to scan a junction — scandir follows it, so the
        # contents belong to the target and a child linking back to that target
        # would otherwise look new.
        for resolver in (os.lstat, os.stat):
            try:
                root_stat = resolver(root)
            except OSError as exc:
                if resolver is os.lstat:
                    self._add_error(root, "Không đọc được thông tin thư mục gốc", exc,
                                    permission=isinstance(exc, PermissionError))
                continue
            root_inode = getattr(root_stat, "st_ino", 0)
            if root_inode:
                self._visited.add((getattr(root_stat, "st_dev", 0) or 0, root_inode))

        # Pass 1 — the immediate children, in a single read. Files are finished
        # here; directories become the units of progress and are walked one at a
        # time so the UI fills in with real totals instead of staying empty until
        # the very end.
        self._read_dir(root, 0, None, collect=self._child_records)
        if self._cancel.is_set():
            self._finish("cancelled")
            return

        self._unit_total = 1 + sum(
            1 for record in self._child_records
            if record["is_dir"] and not record["is_link"]
        )
        self._unit_done = 1
        self._unit_inner = 0.0
        self._publish(current=root)

        for record in self._child_records:
            if self._cancel.is_set():
                self._finish("cancelled")
                return
            if not record["is_dir"] or record.get("is_link"):
                continue
            self._walk_child(record["path"], record)
            record["partial"] = False
            self._unit_done += 1
            self._unit_inner = 0.0
            self._publish(current=root)

        if self._cancel.is_set():
            self._finish("cancelled")
            return
        self._finish("done")

    def _finish(self, status: str, error: Optional[str] = None) -> None:
        self._publish(force=True)
        with self._lock:
            if self.status != "running":
                return
            self.status = status
            self.error = error
            if status == "done":
                self.percent = 100
            self.finished_at = time.time()
            self.children = [dict(record) for record in self._child_records]
        self._finished_mono = time.monotonic()

    def run_forever(self) -> None:
        """Thread entry point. Guarantees the scan never stays stuck in 'running'."""
        try:
            self._run()
        except Exception as exc:
            self._finish("error", "Quét thất bại: %s" % _describe_os_error(exc))
        finally:
            # A BaseException (MemoryError, a KeyboardInterrupt delivered here, an
            # interpreter shutdown) would otherwise leave status='running' forever
            # and the UI spinning with nothing to report.
            with self._lock:
                still_running = self.status == "running"
            if still_running:
                self._finish("error", "Quét dừng bất thường, kết quả không đầy đủ.")

    def snapshot(self) -> Dict[str, Any]:
        """Build the JSON body for GET /usage/scan/{id}.

        This is the single place where scan state crosses into a response, so it
        is also the single place that runs _safe_str over every string that came
        from the filesystem — see that helper for the crash it prevents.

        The sanitising deliberately happens HERE and not where the strings are
        produced. _child_records[i]["path"] is handed straight back to
        _walk_child (in _run), so a record holding a repaired path would send the
        walker to a directory that does not exist: the subtree would be reported
        as 0 bytes with only an "đã bị xoá hoặc đổi tên" error to show for it,
        which is a wrong number presented as a real one. Internal state therefore
        keeps the exact OS strings, and only the copies leaving the module are
        repaired.
        """
        with self._lock:
            status = self.status
            total_bytes = self.total_bytes
            children = [dict(record) for record in self.children]
            error_records = [dict(item) for item in self.errors]
            data: Dict[str, Any] = {
                "scan_id": self.id,
                "path": _safe_str(self.root),
                "status": status,
                "percent": int(self.percent),
                "scanned_files": self.scanned_files,
                "scanned_dirs": self.scanned_dirs,
                "total_bytes": total_bytes,
                "current": _safe_str(self.current),
                "error": _safe_str(self.error) if self.error else self.error,
                "errors": error_records,  # replaced below, once the lock is free
                "error_count": self.error_count,
                "errors_truncated": self.error_count > len(self.errors),
                "permission_denied": self.permission_denied,
                "skipped_links": self.skipped_links,
                "skipped_loops": self.skipped_loops,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }
            largest_raw = list(self._largest)

        elapsed_end = self._finished_mono if self._finished_mono is not None else time.monotonic()
        data["elapsed_seconds"] = round(elapsed_end - self._started_mono, 3)
        data["percent_is_estimate"] = status == "running"

        # Done outside the lock: the walker must not wait on this repair work.
        # An error's message is repaired as well as its path, because
        # _describe_os_error falls back to str(exc), and str(OSError) embeds the
        # offending filename.
        data["errors"] = [
            {
                "path": _safe_str(item.get("path", "")),
                "error": _safe_str(item.get("error", "")),
            }
            for item in error_records
        ]

        for child in children:
            child["name"] = _safe_str(child["name"])
            child["path"] = _safe_str(child["path"])
            child["percent"] = (
                round(child["bytes"] / total_bytes * 100.0, 1) if total_bytes > 0 else 0.0
            )
        children.sort(key=lambda item: item["bytes"], reverse=True)
        data["children"] = children

        data["largest"] = [
            {
                "name": _safe_str(name),
                "path": _safe_str(path),
                "bytes": size,
                "modified": _format_mtime(mtime),
            }
            for size, _seq, name, path, mtime in sorted(largest_raw, reverse=True)
        ]
        return data

    def request_cancel(self) -> None:
        self._cancel.set()


# ── registry ──────────────────────────────────────────────────────────────────

_scans: Dict[str, _Scan] = {}
_registry_lock = threading.Lock()
_last_gc = 0.0


def _gc_locked(now: float) -> int:
    """Drop finished scans older than SCAN_TTL_SECONDS. Caller holds _registry_lock."""
    dropped = 0
    for scan_id in list(_scans.keys()):
        scan = _scans[scan_id]
        with scan._lock:
            finished_at = scan.finished_at
            running = scan.status == "running"
        if running or finished_at is None:
            continue
        if (now - finished_at) >= SCAN_TTL_SECONDS:
            del _scans[scan_id]
            dropped += 1

    # Hard ceiling: if a client keeps starting scans faster than the TTL expires,
    # evict the oldest finished ones rather than growing without bound.
    if len(_scans) > MAX_TRACKED_SCANS:
        finished = []
        for scan_id, scan in _scans.items():
            with scan._lock:
                if scan.status != "running" and scan.finished_at is not None:
                    finished.append((scan.finished_at, scan_id))
        finished.sort()
        for _finished_at, scan_id in finished:
            if len(_scans) <= MAX_TRACKED_SCANS:
                break
            del _scans[scan_id]
            dropped += 1
    return dropped


def scan_gc() -> int:
    """Drop finished scans older than one hour. Returns how many were removed.

    Running scans are never dropped, however old — a scan of a multi-terabyte
    volume legitimately outlives the TTL, and forgetting it would strand a live
    thread with nowhere to publish.
    """
    global _last_gc
    now = time.time()
    with _registry_lock:
        _last_gc = time.monotonic()
        return _gc_locked(now)


def start_scan(path: str, service: Any = None) -> str:
    """Start a background scan of `path` and return its scan_id.

    `service` is the FileService instance whose sandbox applies; the path is
    validated through service._validate_path before anything is read, and again
    for every directory the walk descends into.

    It defaults to the file_service singleton — the same sandbox the rest of the
    extension uses — so both start_scan(path, service) and start_scan(path) work.
    routes.py calls the one-argument form, and a required second parameter there
    turns every scan into a 503 that looks like the feature is missing.

    Exceptions the caller should map to HTTP status codes:
        ValueError            -> 403  path is blocked or outside the allowed roots
        FileNotFoundError     -> 404  path does not exist
        NotADirectoryError    -> 400  path is a file, not a directory
        RuntimeError          -> 429  too many scans already running
        TypeError             -> 500  bad `service` argument (programming error)

    If an identical path is already being scanned, that scan's id is returned
    instead of starting a second walk over the same tree — two concurrent walks of
    one tree are slower than one and produce the same answer.
    """
    if service is None:
        # Imported here, not at module scope, so disk_usage stays importable even
        # if file_service ever fails to load — the caller then gets a clear error
        # from this line instead of the whole module refusing to import.
        from tubecli.extensions.file_manager.file_service import file_service

        service = file_service
    if not hasattr(service, "_validate_path") or not hasattr(service, "_under"):
        raise TypeError(
            "start_scan cần một FileService (thiếu _validate_path/_under), nhận được: %r"
            % type(service).__name__
        )
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Thiếu đường dẫn cần quét.")

    root = service._validate_path(path)  # ValueError propagates deliberately

    if not os.path.exists(root):
        raise FileNotFoundError("Đường dẫn không tồn tại: %s" % path)
    if not os.path.isdir(root):
        raise NotADirectoryError(
            "Chỉ quét được thư mục, đây là một tệp: %s" % path
        )

    now = time.time()
    with _registry_lock:
        _gc_locked(now)

        running = []
        for existing_id, existing in _scans.items():
            with existing._lock:
                if existing.status != "running":
                    continue
                same_root = os.path.normcase(existing.root) == os.path.normcase(root)
            if same_root:
                return existing_id
            running.append(existing_id)

        if len(running) >= MAX_CONCURRENT_SCANS:
            raise RuntimeError(
                "Đang có %d lượt quét chạy cùng lúc (tối đa %d). "
                "Hãy đợi hoặc huỷ bớt trước khi quét thư mục mới."
                % (len(running), MAX_CONCURRENT_SCANS)
            )

        scan_id = uuid.uuid4().hex
        scan = _Scan(scan_id, root, service)
        _scans[scan_id] = scan

    thread = threading.Thread(
        target=scan.run_forever,
        name="fm-usage-scan-%s" % scan_id[:8],
        daemon=True,
    )
    scan.thread = thread
    thread.start()
    return scan_id


def get_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    """Return the current state of a scan, or None if the id is unknown.

    None means either a wrong id or a scan already garbage-collected; the caller
    should answer 404 and say the result may have expired after one hour.
    """
    global _last_gc
    with _registry_lock:
        scan = _scans.get(scan_id)
        # Opportunistic housekeeping so a long-lived server that never starts new
        # scans still releases the memory of old ones.
        if (time.monotonic() - _last_gc) >= GC_MIN_INTERVAL:
            _last_gc = time.monotonic()
            _gc_locked(time.time())
    if scan is None:
        return None
    return scan.snapshot()


def cancel_scan(scan_id: str) -> bool:
    """Ask a scan to stop. True if the id exists, False if it is unknown.

    True does not promise the status is now "cancelled": a scan that had already
    finished keeps its "done" status, because saying "cancelled" for a completed
    walk would misreport what happened. Read the real status from get_scan and
    report that.
    """
    with _registry_lock:
        scan = _scans.get(scan_id)
    if scan is None:
        return False
    scan.request_cancel()
    return True
