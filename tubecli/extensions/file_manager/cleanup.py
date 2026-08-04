"""
Cleanup — detect and remove regenerable junk inside the File Manager sandbox.

Implements the /cleanup/* half of the file-manager contract:

    scan_categories(path, service)  -> list[category dict]
    apply_cleanup(path, category_ids, dry_run, service) -> result dict

Design invariants (each one exists because breaking it caused a real bug):

1. ONE walker, used by every detector and by the apply step. It prunes on the
   reparse-point bit rather than on os.walk(followlinks=False), because every
   link under this repo's data/ is a Windows *junction*: os.path.islink() and
   stat.S_ISLNK() both report False for those and os.walk descends into them
   regardless of followlinks. Measured on data/: the "safe-looking" walk
   reported 95,295,414,862 bytes / 422,230 files while the reparse-pruned walk
   reported 52,611,419,856 / 289,740 — a 42.68 GB, 132,490-file phantom
   over-count caused by enumerating the same files through their aliases.

2. The walk is IDENTICAL for a given root no matter which categories were
   requested. Pruning never depends on category_ids, so the set of candidates
   a preview shows is the set an apply acts on. Only the duplicate *hashing*
   stage is skipped when duplicates were not requested, and that stage has no
   effect on any other detector.

3. Every path is claimed by exactly ONE category, resolved by the fixed
   priority in _CATEGORY_ORDER. Categories therefore never double-count bytes,
   and the per-category number in a scan is exactly what an apply of that
   category deletes.

4. dry_run and a real run execute the same plan through the same executor.
   Only the terminal os.unlink / os.rmdir call is gated. Re-enumerating at
   apply time instead was measured to diverge three ways at once (a target
   vanished, a target the user never saw appeared, and a surviving target grew
   from 100 B to 5,100 B).

5. Nothing is reported as freed unless it actually went away: sizes are re-read
   immediately before the unlink and added only after the unlink returns.

Code, comments and identifiers are English; every string the user reads is
Vietnamese.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple


# ── Platform capabilities, probed once ───────────────────────────────────────
# Branch on capabilities, not on sys.platform: every trap in this area
# (pwd/grp, os.getxattr, effective_ids, junctions) is a capability question
# that sys.platform answers incorrectly for at least one of the three targets.

_IS_WINDOWS = os.name == "nt"
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_HAS_ST_FILE_ATTRIBUTES = hasattr(os.stat_result, "st_file_attributes")
_HAS_PROC_FD = os.path.isdir("/proc/self/fd")


# ── Tuning constants ─────────────────────────────────────────────────────────

# Deterministic caps. A wall-clock cap must never decide what is in the plan:
# the scan runs cold and the apply runs warm (measured 227 files/s cold versus
# 271.6 MB/s warm, a 42x difference), so a time-based cut point would let the
# apply reach files the preview never showed. File counts cut at the same place
# every time for the same tree.
_MAX_WALK_FILES = 400_000
_MAX_TREE_ENTRIES = 200_000

# Duplicate detection. 85.6% of candidates in the measured tree were <= 128 KB,
# so hashing those fully during the single open they already need removes a
# whole reopen pass for zero extra I/O.
_DUP_FULL_HASH_MAX = 128 * 1024
_DUP_PARTIAL_CHUNK = 64 * 1024
_DUP_MIN_SIZE = 4096
_DUP_MAX_CANDIDATES = 60_000
_DUP_MAX_REPORTED_GROUPS = 200
# One real group in this repo holds 4,460 byte-identical rendered frames, so a
# per-group cap is needed too or a single group serialises to ~670 KB of JSON.
_DUP_MAX_REPORTED_MEMBERS = 50
_READ_BLOCK = 1 << 20

_TEMP_MIN_AGE_SECONDS = 24 * 3600
_LOG_MIN_AGE_SECONDS = 30 * 86400
_SAMPLE_LIMIT = 12

_PLAN_CACHE_TTL = 600.0
_PLAN_CACHE_MAX = 8


# ── Names and patterns ───────────────────────────────────────────────────────

_CATEGORY_ORDER = [
    "pycache",
    "build_artifacts",
    "package_caches",
    "node_modules",
    "venv",
    "os_junk",
    "desktop_ini",
    "temp_files",
    "old_logs",
    "empty_dirs",
    "duplicates",
]

# Version-control metadata. Git object files across repos cloned from one
# template are frequently byte-identical, so a duplicate detector that can see
# inside .git will happily corrupt a repository.
_VCS_DIR_NAMES = {".git", ".hg", ".svn", "_darcs", ".bzr"}

_SYSTEM_DIR_NAMES = {
    "system volume information", "$recycle.bin", ".trash", ".trashes",
    "lost+found", ".spotlight-v100", ".fseventsd", ".documentrevisions-v100",
}

_BUILD_CACHE_DIR_NAMES = {
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".eggs",
    ".ipynb_checkpoints", ".parcel-cache", ".turbo", ".sass-cache",
}

_PACKAGE_CACHE_DIR_NAMES = {
    "_cacache", ".pnpm-store", ".yarn-cache", ".npm-cache",
    "pip-wheel-metadata",
}
_PIP_CACHE_CHILD_NAMES = {"http", "http-v2", "wheels", "selfcheck"}
_TOOL_CACHE_PARENTS = {"pip", "uv", "npm", "yarn", "pnpm"}

_NPM_LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "npm-shrinkwrap.json", "bun.lockb",
}

_OS_JUNK_NAMES = {"thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", ".ds_store"}

_TEMP_SUFFIXES = (".tmp", ".temp", ".part", ".crdownload", ".partial", ".download")

# Files that are never junk under any detector, whichever pattern matched.
_PROTECTED_FILE_NAMES = {
    "auth_manager.json", "cloud_api_keys.json", "credentials.json",
    "token.json", "secrets.json", ".env", "pyvenv.cfg",
    "id_rsa", "id_ed25519", "id_ecdsa", ".htpasswd",
}
_PROTECTED_FILE_SUFFIXES = (
    ".key", ".pem", ".pfx", ".p12", ".keystore", ".jks", ".env",
    ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal",
    ".mdb", ".realm", ".accdb",
)

# LevelDB/RocksDB write-ahead logs are named 000123.log and are DATABASE
# CONTENT, not logs. In the measured tree 1,782 of 2,414 stale *.log files
# (73.8% by count, 56.7% by bytes) were WALs inside Chrome profile IndexedDB /
# Local Storage directories; "cleaning" them destroys the user's logins.
_LEVELDB_LOG_RE = re.compile(r"^\d{6}\.log$")
_ROTATED_LOG_RE = re.compile(r"^.+\.log\.(\d+|gz|bz2|xz|zip)$", re.IGNORECASE)


class CleanupCancelled(Exception):
    """Raised when a caller-supplied should_cancel() asked the scan to stop."""


# ── Small helpers ────────────────────────────────────────────────────────────

def _nc(path: str) -> str:
    """Comparison key for a path: case-folded on Windows, normalised everywhere."""
    return os.path.normcase(os.path.normpath(path))


def _path_under(path: str, root: str) -> bool:
    """Is `path` the root itself, or something inside it?

    Deliberately mirrors FileService._under instead of importing it, so this
    module stays importable on its own. A bare startswith() would treat
    ".../Downloads_evil" as inside ".../Downloads", so the separator has to be
    part of the comparison, and Windows paths are case-insensitive.
    """
    p = _nc(path)
    r = _nc(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _safe_str(value: str) -> str:
    """Make a path safe to put in a JSON response.

    On POSIX os.scandir returns undecodable bytes as lone surrogates, which
    every UTF-8 encoder rejects. Formatting a real profile directory name from
    this repo already crashed a scan with UnicodeEncodeError on the cp1252
    console, and a background scan that dies that way leaves its job stuck in
    "running" forever with no error to report.
    """
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-8", "replace").decode("utf-8", "replace")


def _human_size(size_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _is_link(st: os.stat_result) -> bool:
    """True for POSIX symlinks and for every Windows reparse point.

    stat.S_ISLNK() is False for a Windows junction and os.path.isjunction()
    only exists on 3.12 while pyproject.toml allows >=3.10, so the reparse bit
    is the only portable test. Non-link reparse points (OneDrive placeholders,
    dedup stubs) are treated the same way on purpose: refusing to descend into
    or delete something we cannot classify is the safe direction.
    """
    if stat.S_ISLNK(st.st_mode):
        return True
    if _HAS_ST_FILE_ATTRIBUTES:
        return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _depth(path: str) -> int:
    return len(os.path.normpath(path).split(os.sep))


def _relative(path: str, root: str) -> str:
    try:
        rel = os.path.relpath(path, root)
    except ValueError:  # different drive on Windows
        rel = path
    return _safe_str(rel)


def _running_python_prefixes() -> List[str]:
    """Real paths of the interpreter trees that must never be offered for deletion.

    Detecting a venv by the name ".venv" is not enough — it can be called env,
    venv or .direnv — and pyvenv.cfg alone does not say whether deleting it
    would kill the running process. Only an explicit prefix comparison does.
    """
    prefixes: Set[str] = set()
    for candidate in (
        sys.prefix,
        sys.base_prefix,
        getattr(sys, "real_prefix", None),
        os.environ.get("VIRTUAL_ENV"),
        os.environ.get("CONDA_PREFIX"),
        os.path.dirname(sys.executable or ""),
    ):
        if not candidate:
            continue
        try:
            prefixes.add(_nc(os.path.realpath(candidate)))
        except OSError:
            continue
    return sorted(prefixes)


def _explain_os_error(exc: OSError) -> str:
    """Plain-language Vietnamese cause, with the raw code kept for diagnosis."""
    winerror = getattr(exc, "winerror", None)
    errno = exc.errno
    code = f"winerror {winerror}" if winerror else f"errno {errno}"

    if winerror == 32:
        return (
            f"File đang được một tiến trình khác mở nên Windows từ chối xoá ({code}). "
            "Hãy đóng ứng dụng đang dùng file rồi thử lại."
        )
    if winerror == 5:
        return (
            f"Bị từ chối quyền, thường do file có thuộc tính chỉ đọc ({code}). "
            "TubeCLI không tự gỡ thuộc tính chỉ đọc vì đó là lựa chọn có chủ đích "
            "của bạn — hãy bỏ dấu Read-only rồi thử lại."
        )
    if winerror in (145, 91) or errno == 39:
        return (
            f"Thư mục vẫn còn nội dung nên không xoá được ({code}). "
            "Thường là do một mục con bên trong đã xoá thất bại."
        )
    if winerror in (3, 206) or errno == 36:
        return (
            f"Đường dẫn quá dài hoặc không hợp lệ với Windows ({code}). "
            "Hãy bật hỗ trợ đường dẫn dài hoặc rút ngắn tên thư mục."
        )
    if errno == 13:
        return (
            f"Không có quyền xoá ({code}). Trên Linux/macOS quyền xoá phụ thuộc "
            "vào quyền ghi của THƯ MỤC CHA, không phải của chính file."
        )
    if errno == 2:
        return f"Không còn tồn tại, có thể đã bị tiến trình khác xoá ({code})."
    if errno == 16:
        return f"Đang được hệ thống sử dụng ({code})."
    if errno == 30:
        return f"Hệ thống file ở chế độ chỉ đọc ({code})."
    return f"{type(exc).__name__}: {_safe_str(str(exc))} ({code})"


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Action:
    """One leaf operation. Never a "remove this tree" — that cannot be previewed."""
    kind: str        # "file" | "dir" | "link"
    path: str
    category: str
    size: int = 0    # measured at scan time; informational only, never used for freed


@dataclass
class _DirRecord:
    path: str
    child_dirs: List[str]
    file_count: int
    link_count: int
    other_count: int


@dataclass
class _Listing:
    path: str
    dirs: List[Tuple[str, str, os.stat_result]] = field(default_factory=list)
    files: List[Tuple[str, str, os.stat_result]] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)
    others: List[str] = field(default_factory=list)
    names: FrozenSet[str] = frozenset()


@dataclass
class _Plan:
    root: str
    actions: List[_Action]
    per_category: Dict[str, List[_Action]]
    dup_groups: List[Dict[str, Any]]
    dup_group_count: int
    walk_errors: List[Dict[str, str]]
    pruned: List[Tuple[str, str]]
    skipped_links: List[str]
    protected_skipped: int
    truncated: bool
    duplicates_scanned: bool
    duplicates_reason: str
    notes: List[str]
    files_seen: int
    dirs_seen: int


class _ScanContext:
    """Mutable state shared by the walker and every detector."""

    def __init__(self, root: str, service: Any, max_files: int):
        self.root = root
        self.service = service
        self.max_files = max_files
        self.running_prefixes = _running_python_prefixes()
        self.allowed_roots = [
            _nc(r) for r in getattr(service, "allowed_roots", []) or []
        ]

        self.file_claims: List[_Action] = []
        self.tree_claims: List[Tuple[str, str]] = []      # (category, dirpath)
        self.dir_records: List[_DirRecord] = []
        self.dup_candidates: List[Tuple[str, os.stat_result]] = []

        self.walk_errors: List[Dict[str, str]] = []
        self.pruned: List[Tuple[str, str]] = []
        self.skipped_links: List[str] = []
        self.protected_skipped = 0
        self.files_seen = 0
        self.dirs_seen = 0
        self.truncated = False

    def add_walk_error(self, path: str, exc: OSError) -> None:
        """os.walk's default onerror=None silently discards every scandir failure.

        Verified: an unreadable directory simply vanished from the results with
        no exception raised, so a cleanup that trusts the walk to confirm its own
        work reports nothing wrong while skipping an entire subtree.
        """
        self.walk_errors.append(
            {"path": _safe_str(path), "error": _explain_os_error(exc)}
        )


# ── The shared walker ────────────────────────────────────────────────────────

def _list_dir(dirpath: str, ctx: _ScanContext) -> Optional[_Listing]:
    """One directory, link-safe, with every error surfaced rather than swallowed."""
    try:
        scanner = os.scandir(dirpath)
    except OSError as exc:
        ctx.add_walk_error(dirpath, exc)
        return None

    entries = []
    with scanner:
        while True:
            try:
                entries.append(next(scanner))
            except StopIteration:
                break
            except OSError as exc:
                # Partial results are kept: a failure halfway through an
                # enumeration must not discard the entries already read.
                ctx.add_walk_error(dirpath, exc)
                break

    listing = _Listing(path=dirpath)
    names = set()
    for entry in sorted(entries, key=lambda e: e.name):
        names.add(entry.name)
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError as exc:
            ctx.add_walk_error(entry.path, exc)
            continue
        if _is_link(st):
            listing.links.append((entry.name, entry.path))
            ctx.skipped_links.append(_safe_str(entry.path))
            continue
        if stat.S_ISDIR(st.st_mode):
            listing.dirs.append((entry.name, entry.path, st))
        elif stat.S_ISREG(st.st_mode):
            listing.files.append((entry.name, entry.path, st))
        else:
            listing.others.append(entry.path)  # fifo, socket, device node
    listing.names = frozenset(names)
    return listing


def _is_leveldb_dir(name: str, listing: _Listing) -> bool:
    if name.lower().endswith(".leveldb"):
        return True
    if "CURRENT" in listing.names:
        return True
    return any(n.startswith("MANIFEST-") for n in listing.names)


def _is_browser_profile_dir(name: str, listing: _Listing) -> bool:
    """A Chromium/Firefox profile. Pruned entirely, not merely skipped for dedupe.

    Two thirds of the naive duplicate claim in the measured tree lived here
    (7.6 GB across 106,949 files), and so did the LevelDB WALs that the stale-log
    detector would otherwise have destroyed. Nothing inside a live browser
    profile is regenerable junk, so the whole subtree leaves the candidate set.
    """
    lowered = name.lower()
    if lowered in {"browser_profiles", "user data", "profiles"}:
        return True
    if "Local State" in listing.names and "Preferences" in listing.names:
        return True
    if "Preferences" in listing.names and "History" in listing.names:
        return True
    if "cookies.sqlite" in {n.lower() for n in listing.names}:
        return True
    return False


def _prune_reason(name: str, dirpath: str, listing: _Listing,
                  parent_names: FrozenSet[str], ctx: _ScanContext) -> str:
    """Why this subtree is excluded from every category. Never returns silently."""
    lowered = name.lower()
    if name in _VCS_DIR_NAMES:
        return "kho mã nguồn (git/hg/svn) — xoá sẽ hỏng repository"
    if lowered in _SYSTEM_DIR_NAMES:
        return "thư mục hệ thống"
    if _is_leveldb_dir(name, listing):
        return "kho dữ liệu LevelDB/RocksDB — đây là dữ liệu ứng dụng, không phải log"
    if _is_browser_profile_dir(name, listing):
        return "hồ sơ trình duyệt — chứa phiên đăng nhập và dữ liệu người dùng"

    is_venv = "pyvenv.cfg" in listing.names or "conda-meta" in listing.names
    if is_venv:
        try:
            real = _nc(os.path.realpath(dirpath))
        except OSError:
            real = _nc(dirpath)
        for prefix in ctx.running_prefixes:
            if real == prefix or _path_under(prefix, real) or _path_under(real, prefix):
                return "môi trường Python đang chạy TubeCLI — xoá sẽ giết tiến trình này"

    if name == "node_modules":
        # Gated on the parent listing the walker already read, so a failure to
        # re-read it cannot silently turn into "no lockfile, prune it".
        if not ("package.json" in parent_names and parent_names & _NPM_LOCKFILES):
            return (
                "node_modules không có package.json kèm lockfile nên không chứng "
                "minh được là tái tạo lại được"
            )
    return ""


def _tree_category(name: str, dirpath: str, listing: _Listing) -> str:
    """Which category claims this whole directory. Checked in _CATEGORY_ORDER."""
    lowered = name.lower()
    if name == "__pycache__":
        return "pycache"
    if lowered in _BUILD_CACHE_DIR_NAMES or lowered.endswith(".egg-info"):
        return "build_artifacts"
    if lowered in _PACKAGE_CACHE_DIR_NAMES:
        return "package_caches"
    parent_name = os.path.basename(os.path.dirname(dirpath)).lower()
    if lowered in _PIP_CACHE_CHILD_NAMES and parent_name == "pip":
        return "package_caches"
    if lowered == ".cache" and parent_name in _TOOL_CACHE_PARENTS:
        return "package_caches"
    if name == "node_modules":
        # The gate lives in _prune_reason; reaching here means it passed.
        return "node_modules"
    if "pyvenv.cfg" in listing.names or "conda-meta" in listing.names:
        return "venv"
    return ""


def _is_protected_file(lowered: str) -> bool:
    # An exact name match for known junk beats the generic extension heuristic:
    # Thumbs.db ends in ".db" and was being protected as a database, so the
    # whole OS-junk category silently lost its main Windows entry.
    if lowered in _OS_JUNK_NAMES:
        return False
    if lowered in _PROTECTED_FILE_NAMES:
        return True
    return lowered.endswith(_PROTECTED_FILE_SUFFIXES)


def _is_old_log(name: str, lowered: str, dirpath: str, st: os.stat_result,
                listing: _Listing, now: float) -> bool:
    if not (lowered.endswith(".log") or _ROTATED_LOG_RE.match(name)):
        return False
    # Defence in depth: the LevelDB directory itself is already pruned, but a
    # single misdetected store must not be able to reach the deletion plan.
    if _LEVELDB_LOG_RE.match(name):
        return False
    if "CURRENT" in listing.names or any(n.startswith("MANIFEST-") for n in listing.names):
        return False
    if os.path.basename(dirpath).lower().endswith(".leveldb"):
        return False
    return (now - st.st_mtime) >= _LOG_MIN_AGE_SECONDS


def _classify_file(name: str, fpath: str, st: os.stat_result,
                   listing: _Listing, ctx: _ScanContext, now: float) -> None:
    """Assign a file to at most one category, else offer it as a dedupe candidate."""
    lowered = name.lower()

    if _is_protected_file(lowered):
        ctx.protected_skipped += 1
        return

    if lowered.endswith((".pyc", ".pyo")):
        ctx.file_claims.append(_Action("file", fpath, "pycache", st.st_size))
        return

    if lowered in _OS_JUNK_NAMES:
        ctx.file_claims.append(_Action("file", fpath, "os_junk", st.st_size))
        return

    # An AppleDouble sidecar carries the resource fork and extended attributes
    # of its partner file, so it is only junk once the partner is gone.
    if name.startswith("._") and len(name) > 2 and name[2:] not in listing.names:
        ctx.file_claims.append(_Action("file", fpath, "os_junk", st.st_size))
        return

    if lowered == "desktop.ini":
        ctx.file_claims.append(_Action("file", fpath, "desktop_ini", st.st_size))
        return

    if lowered.endswith(_TEMP_SUFFIXES):
        # A .part file is an IN-PROGRESS download; without the age gate the same
        # detector matches a transfer that started five seconds ago.
        if (now - st.st_mtime) >= _TEMP_MIN_AGE_SECONDS:
            ctx.file_claims.append(_Action("file", fpath, "temp_files", st.st_size))
        return

    if _is_old_log(name, lowered, listing.path, st, listing, now):
        ctx.file_claims.append(_Action("file", fpath, "old_logs", st.st_size))
        return

    # Zero-length files are all "identical"; deduplicating them frees nothing
    # and destroys meaningful placeholders such as __init__.py.
    if st.st_size >= _DUP_MIN_SIZE:
        ctx.dup_candidates.append((fpath, st))


def _walk(root: str, ctx: _ScanContext,
          should_cancel: Optional[Callable[[], bool]],
          progress: Optional[Callable[[int, str], None]]) -> None:
    """The single pass every detector shares. Identical for a root, always."""
    now = time.time()
    stack: List[Tuple[str, str, FrozenSet[str]]] = [
        (root, os.path.basename(root.rstrip(os.sep)) or root, frozenset())
    ]

    while stack:
        if should_cancel is not None and should_cancel():
            raise CleanupCancelled("Người dùng đã huỷ lượt quét.")

        dirpath, dirname, parent_names = stack.pop()
        listing = _list_dir(dirpath, ctx)
        if listing is None:
            continue
        ctx.dirs_seen += 1

        if dirpath != root:
            reason = _prune_reason(dirname, dirpath, listing, parent_names, ctx)
            if reason:
                ctx.pruned.append((_safe_str(dirpath), reason))
                continue
            category = _tree_category(dirname, dirpath, listing)
            if category:
                ctx.tree_claims.append((category, dirpath))
                continue

        # Pruned and tree-claimed directories deliberately never reach
        # dir_records: their absence is what stops _collect_empty_dirs from
        # treating a parent as empty just because its child was excluded.

        ctx.dir_records.append(_DirRecord(
            path=dirpath,
            child_dirs=[p for _, p, _ in listing.dirs],
            file_count=len(listing.files),
            link_count=len(listing.links),
            other_count=len(listing.others),
        ))

        for name, fpath, st in listing.files:
            ctx.files_seen += 1
            if ctx.files_seen > ctx.max_files:
                ctx.truncated = True
                return
            _classify_file(name, fpath, st, listing, ctx, now)

        if progress is not None and ctx.dirs_seen % 200 == 0:
            progress(ctx.files_seen, _safe_str(dirpath))

        for name, path, _ in listing.dirs:
            stack.append((path, name, listing.names))


def _expand_tree(tree_root: str, category: str, ctx: _ScanContext
                 ) -> Optional[List[_Action]]:
    """Turn a claimed directory into leaf actions: files, then directories.

    Uses the same link-safe listing as the main walk. A nested junction becomes
    a "link" action that always reports a refusal, so the user sees why the
    parent rmdir will fail instead of the tool silently deleting through the
    link into whatever it points at.
    """
    actions: List[_Action] = []
    dirs_found: List[str] = [tree_root]
    stack = [tree_root]
    seen = 0

    while stack:
        dirpath = stack.pop()
        listing = _list_dir(dirpath, ctx)
        if listing is None:
            continue
        for _, fpath, st in listing.files:
            seen += 1
            if seen > _MAX_TREE_ENTRIES:
                # Refuse the whole tree rather than plan a partial delete whose
                # byte total would be a lie and whose rmdirs would all fail.
                return None
            actions.append(_Action("file", fpath, category, st.st_size))
        for _, lpath in listing.links:
            actions.append(_Action("link", lpath, category, 0))
        for _, dpath, _ in listing.dirs:
            dirs_found.append(dpath)
            stack.append(dpath)

    for dpath in dirs_found:
        actions.append(_Action("dir", dpath, category, 0))
    return actions


# ── Empty directories ────────────────────────────────────────────────────────

def _collect_empty_dirs(ctx: _ScanContext) -> List[_Action]:
    """Directories that hold nothing at all, parents included, deepest-first later.

    Emptiness is judged on what is physically there, never on what other
    categories would delete — otherwise the result would depend on which
    categories were selected and the preview would stop matching the apply.
    A single top-down pass under-reports: verified on emptyA/emptyB/emptyC it
    removed 1 directory and left the parent, while the bottom-up cascade
    removed all 3.
    """
    removable: Dict[str, bool] = {}
    # The DFS pushes children after popping their parent, so the parent's record
    # always precedes its children's; reversing gives children-before-parents.
    for record in reversed(ctx.dir_records):
        if record.file_count or record.link_count or record.other_count:
            removable[_nc(record.path)] = False
            continue
        # A child that was pruned, claimed as a tree, or never reached because
        # of the file budget is absent from `removable` and counts as non-empty.
        removable[_nc(record.path)] = all(
            removable.get(_nc(child), False) for child in record.child_dirs
        )

    actions: List[_Action] = []
    for record in ctx.dir_records:
        if record.path == ctx.root:
            continue
        if _nc(record.path) in ctx.allowed_roots:
            continue
        if removable.get(_nc(record.path)):
            actions.append(_Action("dir", record.path, "empty_dirs", 0))
    return actions


# ── Duplicate detection ──────────────────────────────────────────────────────

def _fingerprint(path: str, size: int
                 ) -> Tuple[Optional[Tuple[int, int]], str, Optional[str]]:
    """One open per candidate. Returns (identity, key, full_digest_or_None).

    Identity comes from os.fstat on the handle already open for hashing:
    os.DirEntry.stat() reports st_ino=0 and st_nlink=0 on Windows, so a
    scandir-based detector is blind to hardlinks and would "free" bytes by
    deleting one of two names pointing at a single inode.
    """
    with open(path, "rb", buffering=0) as handle:
        identity: Optional[Tuple[int, int]] = None
        try:
            fst = os.fstat(handle.fileno())
            if fst.st_ino:
                identity = (fst.st_dev, fst.st_ino)
        except OSError:
            identity = None

        digest = hashlib.sha256()
        if size <= _DUP_FULL_HASH_MAX:
            while True:
                block = handle.read(_READ_BLOCK)
                if not block:
                    break
                digest.update(block)
            full = digest.hexdigest()
            return identity, "f:" + full, full

        head = handle.read(_DUP_PARTIAL_CHUNK)
        handle.seek(max(size - _DUP_PARTIAL_CHUNK, 0))
        tail = handle.read(_DUP_PARTIAL_CHUNK)
        digest.update(head)
        digest.update(tail)
        return identity, "p:" + digest.hexdigest(), None


def _full_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb", buffering=0) as handle:
        while True:
            block = handle.read(_READ_BLOCK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _pick_survivor(members: List[Tuple[str, os.stat_result]]
                   ) -> Tuple[str, os.stat_result]:
    """The copy that is kept: oldest first, then shallowest, then lexicographic.

    A pure function of the group, so a preview and an apply always keep the same
    file. Letting dict or iteration order decide would make the survivor drift
    between the two runs.
    """
    return min(members, key=lambda item: (item[1].st_mtime, _depth(item[0]), _nc(item[0])))


def _scan_duplicates(ctx: _ScanContext,
                     should_cancel: Optional[Callable[[], bool]],
                     progress: Optional[Callable[[int, str], None]]
                     ) -> Tuple[List[_Action], List[Dict[str, Any]], int, str]:
    """Size groups -> one open per file -> full sha256 only for real collisions.

    Never size alone: on the measured tree size-only claimed 5,785,437,748 bytes
    against a confirmed 4,756,065,976, so 1.03 GB of distinct files would have
    been deleted as "duplicates".
    """
    if not ctx.dup_candidates:
        return [], [], 0, ""
    if len(ctx.dup_candidates) > _DUP_MAX_CANDIDATES:
        return [], [], 0, (
            f"Có {len(ctx.dup_candidates):,} file cần đối chiếu, vượt giới hạn "
            f"{_DUP_MAX_CANDIDATES:,} của một lượt quét. Hãy chọn một thư mục con "
            "nhỏ hơn — kết quả một phần sẽ không đáng tin nên không được đưa ra."
        )

    by_size: Dict[int, List[Tuple[str, os.stat_result]]] = {}
    for path, st in ctx.dup_candidates:
        by_size.setdefault(st.st_size, []).append((path, st))

    hashed = 0
    by_key: Dict[Tuple[int, str], List[Tuple[str, os.stat_result]]] = {}
    for size, members in sorted(by_size.items()):
        if len(members) < 2:
            continue
        seen_identity: Set[Tuple[int, int]] = set()
        for path, st in sorted(members, key=lambda item: _nc(item[0])):
            if should_cancel is not None and should_cancel():
                raise CleanupCancelled("Người dùng đã huỷ lượt quét.")
            try:
                identity, key, _full = _fingerprint(path, size)
            except OSError as exc:
                ctx.walk_errors.append(
                    {"path": _safe_str(path), "error": _explain_os_error(exc)}
                )
                continue
            # Hardlinks and case-variant spellings of one inode free nothing.
            if identity is not None:
                if identity in seen_identity:
                    continue
                seen_identity.add(identity)
            by_key.setdefault((size, key), []).append((path, st))
            hashed += 1
            if progress is not None and hashed % 500 == 0:
                progress(hashed, _safe_str(path))

    confirmed: Dict[Tuple[int, str], List[Tuple[str, os.stat_result]]] = {}
    for (size, key), members in by_key.items():
        if len(members) < 2:
            continue
        if key.startswith("f:"):
            confirmed[(size, key)] = members       # already a full sha256
            continue
        for path, st in members:                    # large files: confirm in full
            if should_cancel is not None and should_cancel():
                raise CleanupCancelled("Người dùng đã huỷ lượt quét.")
            try:
                full = _full_digest(path)
            except OSError as exc:
                ctx.walk_errors.append(
                    {"path": _safe_str(path), "error": _explain_os_error(exc)}
                )
                continue
            confirmed.setdefault((size, "f:" + full), []).append((path, st))

    actions: List[_Action] = []
    groups: List[Dict[str, Any]] = []
    group_count = 0
    for (size, key), members in sorted(confirmed.items(), key=lambda kv: -kv[0][0]):
        if len(members) < 2:
            continue
        group_count += 1
        keeper = _pick_survivor(members)
        removals = [item for item in members if _nc(item[0]) != _nc(keeper[0])]
        for path, st in removals:
            actions.append(_Action("file", path, "duplicates", st.st_size))
        if len(groups) < _DUP_MAX_REPORTED_GROUPS:
            groups.append({
                "sha256": key[2:],
                "bytes": size,
                "copies": len(members),
                "keep": {
                    "path": _safe_str(keeper[0]),
                    "name": _safe_str(os.path.basename(keeper[0])),
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(keeper[1].st_mtime)
                    ),
                },
                "remove": [
                    {"path": _safe_str(p), "name": _safe_str(os.path.basename(p)),
                     "bytes": s.st_size}
                    for p, s in removals[:_DUP_MAX_REPORTED_MEMBERS]
                ],
                "remove_total": len(removals),
                "remove_truncated": len(removals) > _DUP_MAX_REPORTED_MEMBERS,
            })
    return actions, groups, group_count, ""


# ── Plan construction ────────────────────────────────────────────────────────

_CATEGORY_META: Dict[str, Tuple[str, str, str]] = {
    "pycache": (
        "Bytecode Python",
        "Thư mục __pycache__ và file *.pyc/*.pyo. Python tự tạo lại ở lần chạy "
        "kế tiếp nên xoá hoàn toàn an toàn, nhưng dung lượng thu về thường rất nhỏ.",
        "safe",
    ),
    "build_artifacts": (
        "Cache của công cụ build",
        "Cache do công cụ sinh ra: .pytest_cache, .mypy_cache, .ruff_cache, .tox, "
        ".nox, *.egg-info… KHÔNG bao gồm thư mục build/ và dist/, vì chúng có thể "
        "chứa bản dựng duy nhất mà bạn chưa phát hành.",
        "safe",
    ),
    "package_caches": (
        "Cache tải gói",
        "Cache tải xuống của pip/npm/yarn/pnpm. Xoá xong lần cài kế tiếp sẽ tải "
        "lại từ mạng, nên sẽ chậm hơn nhưng không mất gì.",
        "safe",
    ),
    "node_modules": (
        "Thư mục node_modules",
        "Chỉ tính node_modules có kèm package.json VÀ lockfile. Khôi phục cần chạy "
        "npm install và CÓ kết nối mạng — nếu máy đang ngoại tuyến thì đây là mất "
        "vĩnh viễn, không phải rác tái tạo được.",
        "review",
    ),
    "venv": (
        "Môi trường ảo Python",
        "Thư mục có pyvenv.cfg hoặc conda-meta. Môi trường đang chạy TubeCLI đã "
        "được loại trừ tuyệt đối. Tạo lại cần cài lại toàn bộ gói qua mạng.",
        "review",
    ),
    "os_junk": (
        "Rác hệ điều hành",
        "Thumbs.db, .DS_Store và file ._* mồ côi (đã mất file gốc đi kèm). "
        "Thumbs.db thường bị Explorer giữ nên có thể báo lỗi khi xoá.",
        "safe",
    ),
    "desktop_ini": (
        "File desktop.ini",
        "desktop.ini lưu biểu tượng, tên hiển thị và kiểu hiển thị của thư mục "
        "trong Explorer. Đây KHÔNG phải rác: xoá đi thư mục sẽ hiển thị khác trước.",
        "review",
    ),
    "temp_files": (
        "File tạm và tải dở",
        "*.tmp, *.temp, *.part, *.crdownload, *.partial không được chạm tới quá "
        "24 giờ. File mới hơn bị bỏ qua vì có thể là một lượt tải đang chạy.",
        "safe",
    ),
    "old_logs": (
        "Log cũ",
        "File *.log cũ hơn 30 ngày. Đã loại trừ WAL của LevelDB/RocksDB (dạng "
        "000123.log, hoặc thư mục có CURRENT/MANIFEST-*) — đó là dữ liệu ứng dụng, "
        "xoá sẽ hỏng phiên đăng nhập trình duyệt.",
        "safe",
    ),
    "empty_dirs": (
        "Thư mục rỗng",
        "Thư mục hoàn toàn không có gì bên trong. Xoá từ trong ra ngoài nên thư "
        "mục cha vừa trở nên rỗng cũng được dọn theo.",
        "safe",
    ),
    "duplicates": (
        "File trùng lặp",
        "File giống nhau theo kích thước VÀ sha256 — không bao giờ chỉ theo kích "
        "thước. Luôn giữ lại bản CŨ NHẤT. Lưu ý: trùng từng byte không có nghĩa là "
        "thừa — vị trí và tên file cũng mang ý nghĩa, ví dụ các frame ảnh giống hệt "
        "nhau trong một chuỗi render.",
        "review",
    ),
}


def _validate_root(path: str, service: Any) -> str:
    """Validate through FileService and refuse clearly rather than returning nothing.

    _validate_path denies the repo root, .venv and the root node_modules, so
    swallowing its ValueError and answering categories:[] would tell the user
    "nothing to clean" about a 69 GB tree — a silent failure, not a result.
    """
    if service is None:
        raise ValueError(
            "Thiếu FileService: mọi thao tác dọn dẹp phải đi qua lớp kiểm tra "
            "đường dẫn, không được truy cập ổ đĩa trực tiếp."
        )
    validator = getattr(service, "validate_path", None) or getattr(service, "_validate_path", None)
    if validator is None:
        raise ValueError(
            "FileService không có hàm kiểm tra đường dẫn (_validate_path); "
            "không thể xác định vùng an toàn nên từ chối thao tác."
        )
    safe = validator(path)
    if not os.path.isdir(safe):
        raise FileNotFoundError(f"Thư mục không tồn tại: {_safe_str(path)}")
    try:
        st = os.lstat(safe)
    except OSError as exc:
        raise FileNotFoundError(
            f"Không đọc được thư mục: {_safe_str(path)} — {_explain_os_error(exc)}"
        )
    if _is_link(st):
        raise ValueError(
            f"Đường dẫn là junction/symlink: {_safe_str(path)}. Hãy chọn thư mục "
            "gốc thật, vì dọn dẹp qua liên kết có thể xoá nhầm sang thư mục đích."
        )
    return safe


def _build_plan(path: str, service: Any, category_ids: Optional[Sequence[str]],
                should_cancel: Optional[Callable[[], bool]] = None,
                progress: Optional[Callable[[int, str], None]] = None,
                max_files: int = _MAX_WALK_FILES) -> _Plan:
    """Walk once, run every detector, then filter. The walk never varies."""
    root = _validate_root(path, service)
    wanted: Optional[Set[str]] = set(category_ids) if category_ids is not None else None

    ctx = _ScanContext(root, service, max_files)
    _walk(root, ctx, should_cancel, progress)

    per_category: Dict[str, List[_Action]] = {cid: [] for cid in _CATEGORY_ORDER}
    notes: List[str] = []

    for action in ctx.file_claims:
        per_category[action.category].append(action)

    # Expanding a claimed tree is a pure read, so skipping it for a category the
    # caller did not ask for cannot change any other category's contents.
    for category, tree_root in ctx.tree_claims:
        if wanted is not None and category not in wanted:
            continue
        actions = _expand_tree(tree_root, category, ctx)
        if actions is None:
            notes.append(
                f"Bỏ qua {_safe_str(tree_root)}: cây thư mục có hơn "
                f"{_MAX_TREE_ENTRIES:,} mục nên không lập được kế hoạch xoá chính "
                "xác. Hãy dọn từ thư mục con."
            )
            continue
        per_category[category].extend(actions)

    if wanted is None or "empty_dirs" in wanted:
        per_category["empty_dirs"].extend(_collect_empty_dirs(ctx))

    # Everything already claimed leaves the duplicate candidate pool, so a path
    # can never appear under two categories and bytes are never double counted.
    claimed = {_nc(a.path) for actions in per_category.values() for a in actions}
    ctx.dup_candidates = [
        (p, st) for p, st in ctx.dup_candidates if _nc(p) not in claimed
    ]

    dup_groups: List[Dict[str, Any]] = []
    dup_group_count = 0
    dup_reason = ""
    duplicates_scanned = wanted is None or "duplicates" in wanted
    if duplicates_scanned:
        dup_actions, dup_groups, dup_group_count, dup_reason = _scan_duplicates(
            ctx, should_cancel, progress
        )
        per_category["duplicates"].extend(dup_actions)
    else:
        dup_reason = "Không được yêu cầu trong lượt này."

    if wanted is not None:
        per_category = {cid: acts for cid, acts in per_category.items() if cid in wanted}

    ordered = _order_actions(
        [a for cid in _CATEGORY_ORDER for a in per_category.get(cid, [])]
    )

    if ctx.truncated:
        notes.append(
            f"Đã đạt giới hạn {max_files:,} file trong một lượt quét nên kết quả "
            "CHƯA ĐẦY ĐỦ. Hãy quét từng thư mục con để có con số đúng."
        )
    if ctx.walk_errors:
        notes.append(
            f"{len(ctx.walk_errors)} thư mục/file không đọc được và đã bị bỏ qua — "
            "con số bên dưới có thể thiếu. Chi tiết ở mục lỗi."
        )
    if ctx.skipped_links:
        notes.append(
            f"Đã bỏ qua {len(ctx.skipped_links)} liên kết (junction/symlink): "
            "không đi vào và không xoá, để tránh chạm tới thư mục đích nằm ngoài "
            "vùng cho phép."
        )
    if ctx.pruned:
        notes.append(
            f"Đã loại {len(ctx.pruned)} thư mục khỏi mọi hạng mục (kho git, hồ sơ "
            "trình duyệt, kho LevelDB, môi trường Python đang chạy)."
        )
    if ctx.protected_skipped:
        notes.append(
            f"Đã bảo vệ {ctx.protected_skipped} file nhạy cảm (khoá, .env, cơ sở "
            "dữ liệu) — không bao giờ đưa vào danh sách xoá."
        )

    return _Plan(
        root=root,
        actions=ordered,
        per_category=per_category,
        dup_groups=dup_groups,
        dup_group_count=dup_group_count,
        walk_errors=ctx.walk_errors,
        pruned=ctx.pruned,
        skipped_links=ctx.skipped_links,
        protected_skipped=ctx.protected_skipped,
        truncated=ctx.truncated,
        duplicates_scanned=duplicates_scanned,
        duplicates_reason=dup_reason,
        notes=notes,
        files_seen=ctx.files_seen,
        dirs_seen=ctx.dirs_seen,
    )


def _order_actions(actions: Sequence[_Action]) -> List[_Action]:
    """Files, then links, then directories deepest-first.

    os.rmdir raises ENOTEMPTY (winerror 145) on a non-empty directory, so the
    ordering is a correctness requirement, not a cosmetic one. Deduplicated by
    path so the client-side invariant len(deleted) + len(failed) == len(plan)
    holds with every planned path appearing exactly once.
    """
    seen: Set[str] = set()
    files: List[_Action] = []
    links: List[_Action] = []
    dirs: List[_Action] = []
    for action in actions:
        key = _nc(action.path)
        if key in seen:
            continue
        seen.add(key)
        if action.kind == "file":
            files.append(action)
        elif action.kind == "link":
            links.append(action)
        else:
            dirs.append(action)
    files.sort(key=lambda a: _nc(a.path))
    links.sort(key=lambda a: _nc(a.path))
    dirs.sort(key=lambda a: (-_depth(a.path), _nc(a.path)))
    return files + links + dirs


# ── Public: scan ─────────────────────────────────────────────────────────────

def scan_categories(path: str, service: Any, *,
                    should_cancel: Optional[Callable[[], bool]] = None,
                    progress: Optional[Callable[[int, str], None]] = None,
                    max_files: int = _MAX_WALK_FILES) -> List[Dict[str, Any]]:
    """Detect regenerable junk under `path`.

    Returns the contract's category list, biggest first. Duplicate hashing is
    bounded by file COUNT rather than bytes because the cost here is per-file
    open latency (measured 227 files/s cold against 271.6 MB/s warm), so this
    should be driven from a background job; pass should_cancel/progress to do so.

    Raises ValueError for a path outside the sandbox and FileNotFoundError for a
    missing one — never an empty list, which would read as "nothing to clean".
    """
    plan = _build_plan(path, service, None, should_cancel, progress, max_files)
    return _categories_from_plan(plan)


def _categories_from_plan(plan: _Plan) -> List[Dict[str, Any]]:
    categories: List[Dict[str, Any]] = []
    for cid in _CATEGORY_ORDER:
        actions = plan.per_category.get(cid, [])
        label, description, risk = _CATEGORY_META[cid]
        file_actions = [a for a in actions if a.kind == "file"]
        dir_actions = [a for a in actions if a.kind == "dir"]
        total_bytes = sum(a.size for a in file_actions)

        notes = list(plan.notes)
        if plan.truncated:
            description = description + " ⚠ Lượt quét chưa đi hết cây thư mục nên con số dưới đây là tối thiểu."
        if cid == "duplicates" and plan.duplicates_reason:
            notes.insert(0, plan.duplicates_reason)
            description = description + " ⚠ " + plan.duplicates_reason

        samples = [
            f"{_relative(a.path, plan.root)} ({_human_size(a.size)})"
            for a in sorted(file_actions, key=lambda a: -a.size)[:_SAMPLE_LIMIT]
        ]
        if not samples:
            samples = [
                _relative(a.path, plan.root)
                for a in sorted(dir_actions, key=lambda a: _nc(a.path))[:_SAMPLE_LIMIT]
            ]

        entry: Dict[str, Any] = {
            "id": cid,
            "label": label,
            "description": description,
            "bytes": total_bytes,
            "bytes_human": _human_size(total_bytes),
            "count": len(actions),
            "file_count": len(file_actions),
            "dir_count": len(dir_actions),
            "risk": risk,
            "samples": samples,
            "notes": notes,
        }
        if cid == "duplicates":
            entry["groups"] = plan.dup_groups
            entry["group_count"] = plan.dup_group_count
            entry["groups_truncated"] = plan.dup_group_count > len(plan.dup_groups)
        categories.append(entry)

    categories.sort(key=lambda c: (-c["bytes"], -c["count"], c["id"]))
    return categories


def scan_report(path: str, service: Any, **kwargs: Any) -> Dict[str, Any]:
    """scan_categories plus everything the walk learned but the contract omits.

    A caller that only renders `categories` still sees the caveats, because the
    same warnings are repeated inside each category's `notes`.
    """
    plan = _build_plan(path, service, None,
                       kwargs.get("should_cancel"), kwargs.get("progress"),
                       kwargs.get("max_files", _MAX_WALK_FILES))
    return {
        "path": _safe_str(plan.root),
        "categories": _categories_from_plan(plan),
        "notes": plan.notes,
        "errors": plan.walk_errors,
        "pruned": [{"path": p, "reason": r} for p, r in plan.pruned],
        "skipped_links": plan.skipped_links[:200],
        "skipped_links_total": len(plan.skipped_links),
        "protected_skipped": plan.protected_skipped,
        "truncated": plan.truncated,
        "files_scanned": plan.files_seen,
        "dirs_scanned": plan.dirs_seen,
    }


# ── Plan reuse ───────────────────────────────────────────────────────────────
# Keyed by (root, requested categories) so a preview and the confirmation that
# follows it consume the SAME plan object, not two independent enumerations.
# Reuse is never trusted on its own: every action is re-validated and re-stat'ed
# at execution time, and the entry is dropped as soon as a real run consumes it.

_PLAN_CACHE: Dict[Tuple[str, Tuple[str, ...]], Tuple[float, _Plan]] = {}


def _cache_key(root: str, category_ids: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
    return (_nc(root), tuple(sorted(set(category_ids))))


def _cache_get(key: Tuple[str, Tuple[str, ...]]) -> Optional[_Plan]:
    entry = _PLAN_CACHE.get(key)
    if entry is None:
        return None
    created, plan = entry
    if (time.time() - created) > _PLAN_CACHE_TTL:
        _PLAN_CACHE.pop(key, None)
        return None
    return plan


def _cache_put(key: Tuple[str, Tuple[str, ...]], plan: _Plan) -> None:
    if len(_PLAN_CACHE) >= _PLAN_CACHE_MAX:
        oldest = min(_PLAN_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _PLAN_CACHE.pop(oldest, None)
    _PLAN_CACHE[key] = (time.time(), plan)


# ── Execution ────────────────────────────────────────────────────────────────

def _revalidate(action: _Action, plan_root: str, service: Any
                ) -> Tuple[str, Optional[os.stat_result], str]:
    """Re-check a planned path immediately before its syscall.

    Validation at scan time is not enough: minutes can pass between the preview
    and the confirmation, and in that window a parent directory can be replaced
    by a junction pointing anywhere. Returns ("", stat, target) when the action
    may proceed, or (reason, None, ""). The caller must issue its syscall on
    `target` — the exact string every check below was run against — because
    checking one path and deleting another is how this function silently
    approves the wrong file (see the rewrite guard below).
    """
    validator = getattr(service, "validate_path", None) or getattr(service, "_validate_path", None)
    if validator is None:
        return ("FileService không có hàm kiểm tra đường dẫn nên từ chối xoá.", None, "")
    try:
        safe = validator(action.path)
    except ValueError as exc:
        return (f"Từ chối vì kiểm tra vùng an toàn thất bại: {_safe_str(str(exc))}", None, "")
    except Exception as exc:  # noqa: BLE001 - any validator failure must block, loudly
        return (f"Không kiểm tra được đường dẫn ({type(exc).__name__}): "
                f"{_safe_str(str(exc))}", None, "")

    # _validate_path no longer expands %VAR%/$VAR and refuses an ambiguous "~name"
    # rewrite (file_service.py), so this is a backstop, not the primary guard. It
    # stays because a validator that returns a different path than it was given
    # hands every check below — existence, S_ISREG/S_ISDIR, _is_link,
    # realpath-under-root — a decoy to inspect while the delete removes the real
    # name, which voids the whole anti-TOCTOU purpose of this function and reports
    # the decoy's size as freed. disk_usage.py blocks the same rewrite on read.
    if _nc(safe) != _nc(action.path):
        # No literal list of "dangerous characters" here: the mismatch is the
        # only thing actually observed, and naming a cause the validator no
        # longer has would send the user hunting for the wrong thing.
        return (
            f"Tên bị lớp kiểm tra diễn giải thành một đường dẫn khác "
            f"({_safe_str(safe)}) nên không xác minh được an toàn trước khi xoá. "
            f"Hãy đổi tên mục này rồi quét lại nếu vẫn muốn xoá.", None, ""
        )

    if not _path_under(safe, plan_root):
        return (f"Nằm ngoài thư mục đã quét ({_safe_str(plan_root)}) nên bị từ chối.", None, "")
    if _nc(safe) == _nc(plan_root):
        return ("Đây là thư mục gốc của lượt quét, không bao giờ được xoá.", None, "")
    for root in getattr(service, "allowed_roots", []) or []:
        if _nc(safe) == _nc(root):
            return ("Đây là một thư mục gốc được phép, không bao giờ được xoá.", None, "")

    try:
        st = os.lstat(safe)
    except FileNotFoundError:
        return ("Không còn tồn tại (có thể đã bị xoá từ trước lượt này).", None, "")
    except OSError as exc:
        return (_explain_os_error(exc), None, "")

    if _is_link(st):
        return (
            "Là junction/symlink nên không xoá: xoá liên kết có thể ảnh hưởng "
            "tới thư mục đích nằm ngoài vùng cho phép.", None, ""
        )

    # A junction swapped in above this path between scan and apply would make
    # realpath escape the root even though the path string still looks fine.
    try:
        real = os.path.realpath(safe)
    except OSError as exc:
        return (_explain_os_error(exc), None, "")
    if not _path_under(real, plan_root):
        return (
            f"Đường dẫn thật ({_safe_str(real)}) đã trỏ ra ngoài thư mục đã quét — "
            "có thể một thư mục cha đã bị thay bằng liên kết. Từ chối xoá.", None, ""
        )

    if action.kind == "file" and not stat.S_ISREG(st.st_mode):
        return ("Không còn là file thường (kiểu đối tượng đã thay đổi).", None, "")
    if action.kind == "dir" and not stat.S_ISDIR(st.st_mode):
        return ("Không còn là thư mục (kiểu đối tượng đã thay đổi).", None, "")
    return ("", st, safe)


def _posix_open_identities() -> Tuple[Optional[Set[Tuple[int, int]]], bool]:
    """(st_dev, st_ino) of files currently held open, and whether the list is complete.

    On POSIX unlink() of an open file SUCCEEDS but the blocks are not released
    until the last descriptor closes, so counting those bytes as freed would be
    a green success for work that did not happen. Windows refuses loudly
    instead (winerror 32), which needs no detection.
    """
    if _IS_WINDOWS or not _HAS_PROC_FD:
        return None, False
    identities: Set[Tuple[int, int]] = set()
    complete = True
    try:
        pids = os.listdir("/proc")
    except OSError:
        return None, False
    for pid in pids:
        if not pid.isdigit():
            continue
        fd_dir = os.path.join("/proc", pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            # Another user's process, or one that exited mid-scan. Either way we
            # cannot see its descriptors, so the answer is partial and says so.
            complete = False
            continue
        for fd in fds:
            try:
                st = os.stat(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                identities.add((st.st_dev, st.st_ino))
    return identities, complete


def _execute(plan: _Plan, service: Any, dry_run: bool) -> Dict[str, Any]:
    """Run the plan. Only the terminal unlink/rmdir is gated on dry_run."""
    deleted: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    freed = 0
    pending_bytes = 0

    planned = {_nc(a.path) for a in plan.actions}
    resolved_ok: Set[str] = set()   # planned paths that will be gone by the end
    open_ids, open_scan_complete = (None, False)
    if not dry_run:
        open_ids, open_scan_complete = _posix_open_identities()

    for action in plan.actions:
        # `target` is the string _revalidate actually stat'ed and cleared; every
        # syscall below uses it so nothing is ever deleted on the strength of
        # checks that ran against a different path. It is normcase-equal to
        # action.path (the guard in _revalidate enforces that), so the
        # resolved_ok/planned bookkeeping keyed on action.path stays in step.
        reason, st, target = _revalidate(action, plan.root, service)
        if reason:
            failed.append({
                "path": _safe_str(action.path),
                "category": action.category,
                "error": reason,
            })
            continue

        if action.kind == "link":
            failed.append({
                "path": _safe_str(action.path),
                "category": action.category,
                "error": (
                    "Là junction/symlink nằm trong thư mục cần xoá. TubeCLI không "
                    "xoá liên kết vì trên Python 3.10/3.11 thao tác đệ quy có thể "
                    "đi xuyên qua nó và xoá thư mục đích thật. Hãy tự kiểm tra và "
                    "gỡ liên kết này nếu chắc chắn."
                ),
            })
            continue

        if action.kind == "file":
            assert st is not None
            size = st.st_size                      # re-read now, not at scan time
            if dry_run:
                deleted.append({
                    "path": _safe_str(action.path), "bytes": size,
                    "category": action.category,
                })
                freed += size
                resolved_ok.add(_nc(action.path))
                continue
            try:
                os.unlink(target)
            except OSError as exc:
                failed.append({
                    "path": _safe_str(action.path),
                    "category": action.category,
                    "error": _explain_os_error(exc),
                })
                continue
            resolved_ok.add(_nc(action.path))
            held_open = (
                open_ids is not None and st.st_ino and (st.st_dev, st.st_ino) in open_ids
            )
            if held_open:
                # The name is gone but the blocks are not; reporting these bytes
                # as freed would be a lie that `df` immediately contradicts.
                pending_bytes += size
                deleted.append({
                    "path": _safe_str(action.path), "bytes": 0,
                    "pending_bytes": size, "category": action.category,
                    "note": (
                        "Đã xoá tên file, nhưng một tiến trình vẫn đang mở file này "
                        "nên dung lượng chỉ thực sự được giải phóng khi tiến trình "
                        "đó đóng file lại."
                    ),
                })
            else:
                freed += size
                deleted.append({
                    "path": _safe_str(action.path), "bytes": size,
                    "category": action.category,
                })
            continue

        # Directory. The emptiness pre-check runs in BOTH modes so the preview
        # reports exactly the reason the real run would, instead of predicting a
        # failure for every directory whose children simply have not gone yet.
        try:
            remaining = os.listdir(target)
        except OSError as exc:
            failed.append({
                "path": _safe_str(action.path),
                "category": action.category,
                "error": _explain_os_error(exc),
            })
            continue
        blocking = [
            name for name in remaining
            if _nc(os.path.join(action.path, name)) not in resolved_ok
        ]
        if blocking:
            shown = ", ".join(_safe_str(n) for n in sorted(blocking)[:5])
            extra = f" và {len(blocking) - 5} mục khác" if len(blocking) > 5 else ""
            unplanned = [
                name for name in blocking
                if _nc(os.path.join(action.path, name)) not in planned
            ]
            cause = (
                "có nội dung không nằm trong kế hoạch xoá"
                if unplanned else "có mục con đã xoá thất bại"
            )
            failed.append({
                "path": _safe_str(action.path),
                "category": action.category,
                "error": f"Không xoá được thư mục vì {cause}: {shown}{extra}.",
            })
            continue

        if dry_run:
            deleted.append({
                "path": _safe_str(action.path), "bytes": 0,
                "category": action.category,
            })
            resolved_ok.add(_nc(action.path))
            continue
        try:
            os.rmdir(target)
        except OSError as exc:
            failed.append({
                "path": _safe_str(action.path),
                "category": action.category,
                "error": _explain_os_error(exc),
            })
            continue
        resolved_ok.add(_nc(action.path))
        deleted.append({
            "path": _safe_str(action.path), "bytes": 0, "category": action.category,
        })

    notes = list(plan.notes)
    if dry_run:
        notes.insert(0, (
            "Đây là bản xem trước, chưa xoá gì. Lượt xoá thật sẽ chạy đúng danh "
            "sách này; chỉ những lỗi phát sinh ngay lúc gọi hệ điều hành (file bị "
            "khoá, mất quyền) mới có thể khác."
        ))
    if pending_bytes:
        notes.append(
            f"{_human_size(pending_bytes)} đã xoá tên nhưng chưa được giải phóng vì "
            "còn tiến trình đang mở. Số 'freed' không tính phần này."
        )
    if not dry_run and not _IS_WINDOWS and open_ids is None:
        notes.append(
            "Không kiểm tra được file nào đang bị tiến trình khác mở (không có "
            "/proc). Trên Linux/macOS, xoá một file đang mở vẫn thành công nhưng "
            "dung lượng chỉ được trả lại khi tiến trình đó đóng file."
        )
    elif not dry_run and open_ids is not None and not open_scan_complete:
        notes.append(
            "Danh sách file đang mở chỉ đọc được một phần (không có quyền xem tiến "
            "trình của người dùng khác), nên con số giải phóng có thể lạc quan hơn "
            "thực tế."
        )

    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "freed": freed,
        "failed": failed,
        "planned": len(plan.actions),
        "pending_bytes": pending_bytes,
        "freed_human": _human_size(freed),
        "notes": notes,
        "errors": plan.walk_errors,
    }


# ── Public: apply ────────────────────────────────────────────────────────────

def apply_cleanup(path: str, category_ids: List[str], dry_run: bool = True,
                  service: Any = None, *,
                  should_cancel: Optional[Callable[[], bool]] = None,
                  progress: Optional[Callable[[int, str], None]] = None,
                  max_files: int = _MAX_WALK_FILES) -> Dict[str, Any]:
    """Delete (or preview deleting) the selected categories under `path`.

    dry_run defaults to True: deletion is irreversible, so it has to be asked
    for explicitly. Preview and real run share one plan and one executor, so the
    only difference between them is whether os.unlink/os.rmdir is called.

    `service` is keyword-defaulted only because the contract puts it after
    dry_run; it is required, and a missing one is refused rather than worked
    around.
    """
    if service is None:
        raise ValueError(
            "Thiếu FileService: mọi thao tác xoá phải đi qua lớp kiểm tra đường "
            "dẫn, không được truy cập ổ đĩa trực tiếp."
        )
    if not isinstance(dry_run, bool):
        dry_run = bool(dry_run)

    root = _validate_root(path, service)

    if category_ids is None:
        category_ids = []
    unknown = [cid for cid in category_ids if cid not in _CATEGORY_META]
    if unknown:
        raise ValueError(
            "Hạng mục không hợp lệ: " + ", ".join(sorted(set(unknown))) +
            ". Các hạng mục hợp lệ: " + ", ".join(_CATEGORY_ORDER)
        )
    if not category_ids:
        return {
            "dry_run": dry_run,
            "deleted": [],
            "freed": 0,
            "failed": [],
            "planned": 0,
            "pending_bytes": 0,
            "freed_human": _human_size(0),
            "notes": ["Chưa chọn hạng mục nào nên không có gì để xoá."],
            "errors": [],
        }

    key = _cache_key(root, category_ids)
    plan = _cache_get(key)
    if plan is None:
        plan = _build_plan(root, service, category_ids, should_cancel, progress, max_files)
        _cache_put(key, plan)

    if plan.truncated:
        # A truncated walk saw only part of the tree. Deleting that part would
        # be a real deletion presented as if it were the whole job.
        return {
            "dry_run": dry_run,
            "deleted": [],
            "freed": 0,
            "failed": [{
                "path": _safe_str(root),
                "error": (
                    f"Lượt quét dừng ở giới hạn {max_files:,} file nên danh sách "
                    "chưa đầy đủ. TubeCLI từ chối xoá một phần không xác định — "
                    "hãy chọn thư mục con nhỏ hơn rồi dọn lần lượt."
                ),
            }],
            "planned": 0,
            "pending_bytes": 0,
            "freed_human": _human_size(0),
            "notes": plan.notes,
            "errors": plan.walk_errors,
        }

    result = _execute(plan, service, dry_run)
    if not dry_run:
        # The paths are gone; keeping the plan would make the next run report
        # every one of them as "không còn tồn tại".
        _PLAN_CACHE.pop(key, None)
    result["path"] = _safe_str(root)
    result["categories"] = sorted(set(category_ids))
    return result


def preview_cleanup(path: str, category_ids: List[str], service: Any) -> Dict[str, Any]:
    """Explicit dry run, for callers that would rather not pass a boolean."""
    return apply_cleanup(path, category_ids, True, service)


def category_ids() -> List[str]:
    """Every category id this module can detect, in claim-priority order."""
    return list(_CATEGORY_ORDER)
