"""
File Manager — permission reading and writing for Windows, Linux and macOS.

Implements the /permissions half of the file-manager contract:

    get_permissions(path, service) -> dict
    set_permissions(path, *, recursive, posix_mode, windows, service) -> dict

Design note (this is deliberately NOT one abstraction with a Windows adapter):
POSIX permissions are a mode, Windows permissions are an ACL. Presenting a
Windows file as "0755" would be a fabricated fact — os.chmod on Windows only
toggles FILE_ATTRIBUTE_READONLY, so the only two modes it can ever produce are
0o666 and 0o444. So the POSIX branch exposes the mode (read and write) and the
Windows branch exposes owner + ACEs (read via ctypes/advapi32, write via
icacls). Each branch says which mechanism produced its answer.

Error handling contract for the router:
  * ValueError          -> 403 (path outside the sandbox / rejected argument)
  * FileNotFoundError   -> 404 (validated path that does not exist)
  * an unsupported platform NEVER raises: it comes back as
    supported=false + reason, or status="error" + message.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import stat
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Capability probe
#
# Every trap this module has to avoid is a capability question that sys.platform
# answers wrongly for at least one of the three targets: pwd/grp exist on POSIX
# only, os.getxattr is missing on macOS even though macOS is POSIX,
# effective_ids is Linux-only, lchmod is BSD/macOS-only. So the code branches on
# these booleans, not on sys.platform.
# ─────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = os.name == "nt"
IS_POSIX = os.name == "posix"
IS_DARWIN = sys.platform == "darwin"


def _probe_posix_module(name: str) -> bool:
    """True when `name` can be imported. Returns False instead of raising.

    Guarded by os.name so `import pwd` is never even attempted on Windows,
    where it raises ModuleNotFoundError. A module-scope `import pwd` here would
    make this whole file unimportable on Windows and take every file-manager
    endpoint down with it, not just /permissions.
    """
    if not IS_POSIX:
        return False
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _find_icacls() -> Optional[str]:
    """icacls.exe, or None. PATH first, then the canonical System32 location."""
    if not IS_WINDOWS:
        return None
    found = shutil.which("icacls")
    if found:
        return found
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:\\Windows"
    candidate = os.path.join(system_root, "System32", "icacls.exe")
    return candidate if os.path.isfile(candidate) else None


def _find_powershell() -> Optional[str]:
    """PowerShell binary, or None.

    powershell.exe (5.1) ships with Windows; pwsh (7+) frequently does not
    exist, so it must be probed rather than assumed.
    """
    if not IS_WINDOWS:
        return None
    return shutil.which("powershell") or shutil.which("pwsh")


CAPABILITIES: Dict[str, Any] = {
    "has_pwd": _probe_posix_module("pwd"),
    "has_grp": _probe_posix_module("grp"),
    "has_geteuid": hasattr(os, "geteuid"),
    "access_effective_ids": os.access in os.supports_effective_ids,
    "chmod_follow_symlinks": os.chmod in os.supports_follow_symlinks,
    "has_lchmod": hasattr(os, "lchmod"),
    "has_listxattr": hasattr(os, "listxattr"),
    "icacls": _find_icacls(),
    "powershell": _find_powershell(),
    "ls": shutil.which("ls"),
}

# Enumerating first and refusing above this count is what keeps a recursive
# apply from becoming a half-finished change inside an HTTP request.
MAX_RECURSIVE_ITEMS = 20000

# Per-subprocess timeout. icacls is invoked once per item on a recursive apply,
# so this bounds one item, not the whole job.
SUBPROCESS_TIMEOUT_SEC = 30

# CreateProcess flag: keeps a console window from flashing when the API server
# runs under pythonw / as a service.
_CREATE_NO_WINDOW = 0x08000000

# lstat().st_file_attributes bit. Windows junctions report islink()=False and
# S_ISLNK()=False, so this bit is the only portable-to-3.10 way to spot them
# (os.path.isjunction is 3.12+ and this project supports >=3.10).
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_READONLY = 0x1


def _platform_name() -> str:
    if IS_WINDOWS:
        return "windows"
    if IS_DARWIN:
        return "darwin"
    if IS_POSIX:
        return "linux"
    return "unknown"


def _subprocess_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"capture_output": True, "timeout": SUBPROCESS_TIMEOUT_SEC}
    if IS_WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


def _decode_process_output(raw: Optional[bytes]) -> str:
    """Decode a child process's bytes without ever raising.

    Windows console tools write to a redirected pipe in the OEM codepage, not
    UTF-8 and not the ANSI codepage. Worse, icacls replaces characters it
    cannot encode with a literal '?' before the bytes leave the process, so
    non-ASCII text is destroyed at the source and no decoding choice recovers
    it — which is exactly why nothing here parses icacls stdout.
    """
    if not raw:
        return ""
    encodings: List[str] = []
    if IS_WINDOWS:
        try:
            encodings.append("cp%d" % ctypes.WinDLL("kernel32").GetOEMCP())
        except Exception:
            pass
    encodings.extend(["utf-8", "latin-1"])
    for enc in encodings:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _get_service(service):
    """Fall back to the module singleton so a caller that forgets `service`
    still gets sandbox validation instead of unchecked filesystem access."""
    if service is not None:
        return service
    from tubecli.extensions.file_manager.file_service import file_service
    return file_service


def _validated(path: str, service) -> str:
    """Sandbox-validate, then confirm existence.

    _validate_path does not check existence, so without this a missing path
    surfaces as a raw FileNotFoundError from deep inside a stat call (a 500)
    instead of a clean 404.
    """
    svc = _get_service(service)
    safe_path = svc._validate_path(path)
    if not os.path.lexists(safe_path):
        raise FileNotFoundError(f"Đường dẫn không tồn tại: {path}")
    return safe_path


def _is_link(path: str, st_result=None) -> bool:
    """Symlink on POSIX, symlink OR junction on Windows."""
    try:
        st = st_result if st_result is not None else os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


# ─────────────────────────────────────────────────────────────────────────────
# Windows: security descriptor reading via ctypes -> advapi32
# ─────────────────────────────────────────────────────────────────────────────

_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_GROUP_SECURITY_INFORMATION = 0x00000002
_DACL_SECURITY_INFORMATION = 0x00000004
_ERROR_INSUFFICIENT_BUFFER = 122

_ACCESS_ALLOWED_ACE_TYPE = 0x0
_ACCESS_DENIED_ACE_TYPE = 0x1
_INHERITED_ACE = 0x10
_OBJECT_INHERIT_ACE = 0x01
_CONTAINER_INHERIT_ACE = 0x02
_INHERIT_ONLY_ACE = 0x08


class _ACL(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", ctypes.c_ushort),
        ("AceCount", ctypes.c_ushort),
        ("Sbz2", ctypes.c_ushort),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    ]


class _ACCESS_ALLOWED_ACE(ctypes.Structure):
    """Only AceType 0 (ALLOWED) and 1 (DENIED) share this layout. Object ACEs
    (types 5/6) put a GUID where Mask/SidStart are, so casting them would read
    a GUID as an access mask and invent permissions that do not exist."""
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", ctypes.c_uint32),
        ("SidStart", ctypes.c_uint32),
    ]


# Presets first so the common cases read like the Windows security tab instead
# of a bit soup.
_RIGHTS_PRESETS: List[Tuple[int, str]] = [
    (0x1F01FF, "Full control"),
    (0x1301BF, "Modify"),
    (0x1200A9, "Read & execute"),
    (0x120089, "Read"),
    (0x120116, "Write"),
    (0x100000, "Synchronize"),
]

_RIGHTS_BITS: List[Tuple[int, str]] = [
    (0x00000001, "ReadData"),
    (0x00000002, "WriteData"),
    (0x00000004, "AppendData"),
    (0x00000008, "ReadEA"),
    (0x00000010, "WriteEA"),
    (0x00000020, "Execute"),
    (0x00000040, "DeleteChild"),
    (0x00000080, "ReadAttributes"),
    (0x00000100, "WriteAttributes"),
    (0x00010000, "Delete"),
    (0x00020000, "ReadPermissions"),
    (0x00040000, "ChangePermissions"),
    (0x00080000, "TakeOwnership"),
    (0x00100000, "Synchronize"),
    (0x10000000, "GenericAll"),
    (0x20000000, "GenericExecute"),
    (0x40000000, "GenericWrite"),
    (0x80000000, "GenericRead"),
]


def _describe_mask(mask: int) -> Tuple[str, List[str]]:
    """(human string, individual flag names) for an access mask."""
    mask &= 0xFFFFFFFF
    flags = [name for bit, name in _RIGHTS_BITS if mask & bit]
    for preset, label in _RIGHTS_PRESETS:
        if mask == preset:
            return label, flags
    if not flags:
        return "0x%08X" % mask, []
    residual = mask & ~sum(bit for bit, _ in _RIGHTS_BITS)
    text = ", ".join(flags)
    if residual:
        text += " + 0x%08X" % residual
    return text, flags


class _WinSecurityError(Exception):
    """A Windows security read failed. Carries a message meant for the user."""


def _sid_to_name(advapi32, kernel32, psid: ctypes.c_void_p) -> str:
    """Account name for a SID, falling back to the SID string.

    Never returns an empty string: an unresolvable SID (deleted account,
    unreachable domain) still has to be shown, because hiding the ACE would
    understate who has access.
    """
    name_len = ctypes.c_uint32(256)
    domain_len = ctypes.c_uint32(256)
    name = ctypes.create_unicode_buffer(name_len.value)
    domain = ctypes.create_unicode_buffer(domain_len.value)
    use = ctypes.c_uint32(0)

    ok = advapi32.LookupAccountSidW(
        None, psid, name, ctypes.byref(name_len), domain, ctypes.byref(domain_len), ctypes.byref(use)
    )
    if not ok and ctypes.get_last_error() == _ERROR_INSUFFICIENT_BUFFER:
        name = ctypes.create_unicode_buffer(name_len.value)
        domain = ctypes.create_unicode_buffer(domain_len.value)
        ok = advapi32.LookupAccountSidW(
            None, psid, name, ctypes.byref(name_len), domain, ctypes.byref(domain_len), ctypes.byref(use)
        )
    if ok:
        if domain.value and name.value:
            return f"{domain.value}\\{name.value}"
        return name.value or domain.value

    string_sid = ctypes.c_wchar_p()
    if advapi32.ConvertSidToStringSidW(psid, ctypes.byref(string_sid)) and string_sid.value:
        try:
            return string_sid.value
        finally:
            kernel32.LocalFree(ctypes.cast(string_sid, ctypes.c_void_p))
    return "(SID không đọc được)"


def _read_windows_security(path: str) -> Dict[str, Any]:
    """Owner + DACL through GetNamedSecurityInfoW. Raises _WinSecurityError.

    ctypes rather than icacls because it is stdlib-only, Unicode-correct, and
    returns structured data instead of localized text that icacls has already
    mangled on the way out.
    """
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception as exc:
        raise _WinSecurityError(f"Không nạp được advapi32/kernel32: {exc}")

    advapi32.GetNamedSecurityInfoW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.POINTER(_ACL)), ctypes.POINTER(ctypes.POINTER(_ACL)),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
    advapi32.GetAce.argtypes = [ctypes.POINTER(_ACL), ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = ctypes.c_int
    advapi32.LookupAccountSidW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.LookupAccountSidW.restype = ctypes.c_int
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def _call(target: str) -> Tuple[int, Any, Any, Any, Any]:
        psid_owner = ctypes.c_void_p()
        psid_group = ctypes.c_void_p()
        pdacl = ctypes.POINTER(_ACL)()
        psacl = ctypes.POINTER(_ACL)()
        psd = ctypes.c_void_p()
        rc = advapi32.GetNamedSecurityInfoW(
            target, _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _GROUP_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(psid_owner), ctypes.byref(psid_group),
            ctypes.byref(pdacl), ctypes.byref(psacl), ctypes.byref(psd),
        )
        return rc, psid_owner, psid_group, pdacl, psd

    rc, psid_owner, psid_group, pdacl, psd = _call(path)
    if rc != 0 and len(path) > 250 and re.match(r"^[A-Za-z]:\\", path):
        # Only worth trying for a long absolute drive path: the \\?\ prefix
        # disables path normalization, so it must never be applied blindly.
        rc, psid_owner, psid_group, pdacl, psd = _call("\\\\?\\" + path)
    if rc != 0:
        raise _WinSecurityError(
            f"GetNamedSecurityInfoW thất bại (mã lỗi Windows {rc}). "
            "Thường do không đủ quyền đọc mô tả bảo mật của đối tượng này."
        )

    try:
        owner = _sid_to_name(advapi32, kernel32, psid_owner) if psid_owner else None
        group = _sid_to_name(advapi32, kernel32, psid_group) if psid_group else None

        entries: List[Dict[str, Any]] = []
        skipped: List[str] = []
        null_dacl = not bool(pdacl)

        if null_dacl:
            # A NULL DACL grants everyone full access; an EMPTY DACL grants
            # nobody. Reporting either as "entries: []" inverts the meaning, so
            # the NULL case gets an explicit synthetic entry.
            entries.append({
                "identity": "Everyone (NULL DACL)",
                "rights": "Full control",
                "mask": 0x1F01FF,
                "rights_flags": ["GenericAll"],
                "type": "allow",
                "inherited": False,
                "applies_to": "đối tượng này",
                "synthetic": True,
            })
        else:
            ace_count = pdacl.contents.AceCount
            for index in range(ace_count):
                pace = ctypes.c_void_p()
                if not advapi32.GetAce(pdacl, index, ctypes.byref(pace)) or not pace:
                    skipped.append(f"ACE #{index}: GetAce thất bại")
                    continue
                header = ctypes.cast(pace, ctypes.POINTER(_ACE_HEADER)).contents
                if header.AceType not in (_ACCESS_ALLOWED_ACE_TYPE, _ACCESS_DENIED_ACE_TYPE):
                    skipped.append(f"ACE #{index}: loại {header.AceType} (audit/object) không được hiển thị")
                    continue
                ace = ctypes.cast(pace, ctypes.POINTER(_ACCESS_ALLOWED_ACE)).contents
                sid_ptr = ctypes.c_void_p(pace.value + _ACCESS_ALLOWED_ACE.SidStart.offset)
                rights_text, rights_flags = _describe_mask(ace.Mask)
                scope: List[str] = ["đối tượng này"] if not header.AceFlags & _INHERIT_ONLY_ACE else []
                if header.AceFlags & _CONTAINER_INHERIT_ACE:
                    scope.append("thư mục con")
                if header.AceFlags & _OBJECT_INHERIT_ACE:
                    scope.append("tập tin con")
                entries.append({
                    "identity": _sid_to_name(advapi32, kernel32, sid_ptr),
                    "rights": rights_text,
                    "mask": ace.Mask & 0xFFFFFFFF,
                    "rights_flags": rights_flags,
                    "type": "allow" if header.AceType == _ACCESS_ALLOWED_ACE_TYPE else "deny",
                    "inherited": bool(header.AceFlags & _INHERITED_ACE),
                    "applies_to": ", ".join(scope) if scope else "chỉ kế thừa",
                })

        return {
            "owner": owner,
            "group": group,
            "entries": entries,
            "null_dacl": null_dacl,
            "empty_dacl": (not null_dacl) and not entries and not skipped,
            "skipped_aces": skipped,
            "source": "ctypes:advapi32.GetNamedSecurityInfoW",
        }
    finally:
        if psd:
            kernel32.LocalFree(psd)


_POWERSHELL_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$target = $env:TUBECLI_ACL_PATH
$acl = Get-Acl -LiteralPath $target
$entries = @()
foreach ($ace in $acl.Access) {
  $entries += [ordered]@{
    identity  = $ace.IdentityReference.Value
    rights    = $ace.FileSystemRights.ToString()
    type      = $ace.AccessControlType.ToString()
    inherited = [bool]$ace.IsInherited
  }
}
$out = [ordered]@{ owner = $acl.Owner; group = $acl.Group; entries = @($entries) }
$out | ConvertTo-Json -Compress -Depth 5
"""


def _read_windows_security_powershell(path: str) -> Dict[str, Any]:
    """Documented fallback for the ctypes reader. Raises _WinSecurityError.

    The path travels in an environment variable because $args is NOT populated
    under `powershell -Command`: passing it as a trailing argv element sends an
    empty path and Get-Acl fails with "argument is null or empty".
    """
    shell = CAPABILITIES["powershell"]
    if not shell:
        raise _WinSecurityError("Không tìm thấy powershell.exe để đọc ACL.")
    env = dict(os.environ)
    env["TUBECLI_ACL_PATH"] = path
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _POWERSHELL_ACL_SCRIPT],
            env=env, **_subprocess_kwargs()
        )
    except subprocess.TimeoutExpired:
        raise _WinSecurityError(f"Get-Acl quá {SUBPROCESS_TIMEOUT_SEC}s không phản hồi.")
    except OSError as exc:
        raise _WinSecurityError(f"Không chạy được PowerShell: {exc}")

    if proc.returncode != 0:
        raise _WinSecurityError(
            "Get-Acl thất bại: " + (_decode_process_output(proc.stderr).strip() or f"mã thoát {proc.returncode}")
        )

    import json
    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise _WinSecurityError(f"Không đọc được JSON từ Get-Acl: {exc}")

    raw_entries = data.get("entries") or []
    # ConvertTo-Json emits a bare object, not a list, when the array holds one
    # element — iterating that would walk its keys instead of its entries.
    if isinstance(raw_entries, dict):
        raw_entries = [raw_entries]

    entries = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        entries.append({
            "identity": item.get("identity") or "(không rõ)",
            "rights": item.get("rights") or "(không rõ)",
            "mask": None,
            "rights_flags": [p.strip() for p in str(item.get("rights") or "").split(",") if p.strip()],
            "type": "deny" if str(item.get("type", "")).lower().startswith("deny") else "allow",
            "inherited": bool(item.get("inherited")),
            "applies_to": None,
        })
    return {
        "owner": data.get("owner"),
        "group": data.get("group"),
        "entries": entries,
        "null_dacl": False,
        "empty_dacl": not entries,
        "skipped_aces": [],
        "source": "powershell:Get-Acl",
    }


def _current_windows_identity() -> Optional[str]:
    """DOMAIN\\user for the account this process runs as, or None."""
    if not IS_WINDOWS:
        return None
    name = None
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        size = ctypes.c_uint32(256)
        buf = ctypes.create_unicode_buffer(size.value)
        if advapi32.GetUserNameW(buf, ctypes.byref(size)):
            name = buf.value
    except Exception:
        name = None
    if not name:
        name = os.environ.get("USERNAME")
    if not name:
        return None
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME")
    return f"{domain}\\{name}" if domain else name


def _identity_matches(candidate: str, identity: str) -> bool:
    """Loose comparison so "ADMIN" matches "DESKTOP-X\\ADMIN"."""
    if not candidate or not identity:
        return False
    a = candidate.strip().lower()
    b = identity.strip().lower()
    return a == b or a.split("\\")[-1] == b.split("\\")[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Windows: readable / writable / executable
# ─────────────────────────────────────────────────────────────────────────────

def _windows_effective_access(path: str, is_dir: bool) -> Tuple[Optional[bool], Optional[bool], Optional[bool], Dict[str, str]]:
    """Probe real access. Never uses os.access on Windows.

    os.access consults only the read-only attribute and existence; it ignores
    the DACL completely and returns True for a file that a DENY ACE makes
    unopenable — a lie in the permissive direction, which is the dangerous one.
    os.access(X_OK) is a constant True there and carries zero information.
    """
    methods = {
        "readable": "mở thử bằng os.open(O_RDONLY)",
        "writable": "mở thử bằng os.open(O_WRONLY|O_APPEND) — không đổi nội dung, kích thước hay mtime",
        "executable": "phần mở rộng so với PATHEXT",
    }
    binary = getattr(os, "O_BINARY", 0)

    readable: Optional[bool]
    writable: Optional[bool]
    executable: Optional[bool]

    if is_dir:
        methods["readable"] = "liệt kê thử bằng os.scandir()"
        try:
            with os.scandir(path) as it:
                next(it, None)
            readable = True
        except OSError:
            readable = False
        # Deciding this needs creating and deleting a temp entry inside the
        # user's directory. Reporting "unknown" beats a side effect the caller
        # did not ask for, and beats guessing.
        writable = None
        methods["writable"] = ("không xác định — chỉ có thể kiểm tra bằng cách tạo rồi xoá "
                               "một mục tạm trong thư mục, việc này để lại tác dụng phụ nên không thực hiện")
        executable = None
        methods["executable"] = "không áp dụng cho thư mục trên Windows"
        return readable, writable, executable, methods

    try:
        fd = os.open(path, os.O_RDONLY | binary)
        os.close(fd)
        readable = True
    except OSError:
        readable = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | binary)
        os.close(fd)
        writable = True
    except OSError:
        writable = False

    pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    # os.pathsep, never a hardcoded ';' — that has shipped here before and
    # breaks on POSIX where the separator is ':'.
    exts = {e.strip().lower() for e in pathext.split(os.pathsep) if e.strip()}
    executable = os.path.splitext(path)[1].lower() in exts
    return readable, writable, executable, methods


# ─────────────────────────────────────────────────────────────────────────────
# POSIX: mode, owner, ACL presence
# ─────────────────────────────────────────────────────────────────────────────

def _posix_owner_names(st_result) -> Tuple[str, str]:
    """(owner, group) names, falling back to the numeric ids.

    A uid with no /etc/passwd entry — containers, NFS, a deleted account —
    raises KeyError rather than returning a fallback, so the numeric id is the
    honest answer there.
    """
    uid = getattr(st_result, "st_uid", None)
    gid = getattr(st_result, "st_gid", None)
    owner = str(uid) if uid is not None else "?"
    group = str(gid) if gid is not None else "?"
    if CAPABILITIES["has_pwd"]:
        try:
            import pwd
            owner = pwd.getpwuid(st_result.st_uid).pw_name
        except (KeyError, OSError, ImportError, AttributeError):
            pass
    if CAPABILITIES["has_grp"]:
        try:
            import grp
            group = grp.getgrgid(st_result.st_gid).gr_name
        except (KeyError, OSError, ImportError, AttributeError):
            pass
    return owner, group


def _decompose_mode(mode: int) -> Dict[str, Dict[str, bool]]:
    return {
        "user": {
            "r": bool(mode & stat.S_IRUSR),
            "w": bool(mode & stat.S_IWUSR),
            "x": bool(mode & stat.S_IXUSR),
        },
        "group_perms": {
            "r": bool(mode & stat.S_IRGRP),
            "w": bool(mode & stat.S_IWGRP),
            "x": bool(mode & stat.S_IXGRP),
        },
        "other": {
            "r": bool(mode & stat.S_IROTH),
            "w": bool(mode & stat.S_IWOTH),
            "x": bool(mode & stat.S_IXOTH),
        },
    }


def _detect_posix_acl(path: str) -> Tuple[Optional[bool], str]:
    """(acl_present, explanation). None means "could not be determined".

    This matters because when a file carries an ACL the mode reported by
    S_IMODE is the ACL mask, not the effective permission — the UI can show
    0644 for a file a named user can write. Silently presenting the mode as the
    whole truth is the misleading-success pattern.
    """
    if IS_DARWIN:
        ls = CAPABILITIES["ls"] or "/bin/ls"
        try:
            proc = subprocess.run([ls, "-led", path], **_subprocess_kwargs())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"Không kiểm tra được ACL macOS ({exc})."
        if proc.returncode != 0:
            return None, "Không kiểm tra được ACL macOS (lệnh ls thất bại)."
        first_line = _decode_process_output(proc.stdout).splitlines()[:1]
        if not first_line:
            return None, "Không kiểm tra được ACL macOS (ls không trả về gì)."
        has_acl = "+" in first_line[0].split()[0]
        if has_acl:
            return True, ("Đối tượng có ACL kiểu NFSv4 của macOS. ACL ghi đè lên mode bên dưới, "
                          "nên quyền thực tế có thể khác con số hiển thị. Xem bằng: ls -led")
        return False, "Không phát hiện ACL (kiểm tra bằng ls -led)."

    if CAPABILITIES["has_listxattr"]:
        try:
            attrs = os.listxattr(path, follow_symlinks=False)
        except OSError as exc:
            return None, f"Không đọc được xattr để kiểm tra ACL ({exc})."
        if "system.posix_acl_access" in attrs:
            return True, ("Đối tượng có POSIX ACL. Khi có ACL, con số mode chính là ACL mask "
                          "chứ không phải quyền thực tế. Xem bằng: getfacl -p")
        return False, "Không phát hiện POSIX ACL (kiểm tra qua xattr system.posix_acl_access)."

    return None, "Không có cách kiểm tra ACL trên nền tảng này bằng thư viện chuẩn."


def _posix_access(path: str) -> Tuple[Optional[bool], Optional[bool], Optional[bool], Dict[str, str]]:
    kwargs: Dict[str, Any] = {}
    method = "os.access (uid/gid thực)"
    if CAPABILITIES["access_effective_ids"]:
        # By default os.access tests the REAL uid/gid, so a privilege-dropped
        # server would get the answer for the wrong identity.
        kwargs["effective_ids"] = True
        method = "os.access (uid/gid hiệu lực)"
    methods = {"readable": method, "writable": method, "executable": method}
    out: List[Optional[bool]] = []
    for flag in (os.R_OK, os.W_OK, os.X_OK):
        try:
            out.append(bool(os.access(path, flag, **kwargs)))
        except (OSError, NotImplementedError, TypeError):
            out.append(None)
    return out[0], out[1], out[2], methods


# ─────────────────────────────────────────────────────────────────────────────
# Public: read
# ─────────────────────────────────────────────────────────────────────────────

def get_permissions(path: str, service=None) -> Dict[str, Any]:
    """Read permissions for `path`.

    Raises ValueError (outside sandbox) or FileNotFoundError (missing). Never
    raises because of the platform: an unsupported one comes back as
    supported=false with a reason.
    """
    safe_path = _validated(path, service)
    platform_name = _platform_name()

    try:
        st = os.lstat(safe_path)
    except OSError as exc:
        return {
            "platform": platform_name, "platform_raw": sys.platform, "path": safe_path,
            "posix": None, "windows": None,
            "readable": None, "writable": None, "executable": None,
            "supported": False,
            "reason": f"Không đọc được thông tin của đường dẫn: {exc}",
            "notes": [],
        }

    is_link = _is_link(safe_path, st)
    is_dir = os.path.isdir(safe_path)
    notes: List[str] = []
    if is_link:
        try:
            target = os.path.realpath(safe_path)
        except OSError:
            target = "(không xác định)"
        notes.append(
            f"Đây là liên kết (symlink/junction) trỏ tới: {target}. "
            "Quyền hiển thị là quyền của chính liên kết, không phải của đích."
        )

    result: Dict[str, Any] = {
        "platform": platform_name,
        "platform_raw": sys.platform,
        "path": safe_path,
        "is_dir": is_dir,
        "is_symlink": is_link,
        "posix": None,
        "windows": None,
        "readable": None,
        "writable": None,
        "executable": None,
        "supported": False,
        "reason": "",
        "notes": notes,
        "checks": {},
        "can_edit": False,
    }

    if IS_WINDOWS:
        readable, writable, executable, methods = _windows_effective_access(safe_path, is_dir)
        result.update({"readable": readable, "writable": writable, "executable": executable, "checks": methods})

        errors: List[str] = []
        security: Optional[Dict[str, Any]] = None
        try:
            security = _read_windows_security(safe_path)
        except _WinSecurityError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"Lỗi không lường trước khi đọc ACL bằng ctypes: {exc}")
        if security is None:
            try:
                security = _read_windows_security_powershell(safe_path)
            except _WinSecurityError as exc:
                errors.append(str(exc))
            except Exception as exc:
                errors.append(f"Lỗi không lường trước khi đọc ACL bằng PowerShell: {exc}")

        if security is None:
            # Deliberately NOT an empty entries list: that reads as "không ai có
            # quyền" when the truth is "chưa đọc được".
            result["windows"] = None
            result["supported"] = False
            result["reason"] = "Không đọc được quyền Windows. " + " | ".join(errors)
            return result

        security["read_only_attribute"] = bool(
            getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_READONLY
        )
        result["windows"] = security
        result["supported"] = True
        result["can_edit"] = bool(CAPABILITIES["icacls"])

        reason = ("Windows dùng ACL. Chủ sở hữu và danh sách ACE đọc qua "
                  f"{security['source']}.")
        if errors:
            reason += " Cách đọc ưu tiên thất bại: " + " | ".join(errors)
        if security.get("null_dacl"):
            reason += (" Đối tượng có DACL rỗng kiểu NULL: mọi tài khoản đều có toàn quyền. "
                       "Đây KHÔNG giống danh sách ACE trống.")
        if security.get("empty_dacl"):
            reason += " DACL có nhưng không chứa ACE nào: không tài khoản nào được cấp quyền."
        if security.get("skipped_aces"):
            reason += " Có ACE không hiển thị được: " + "; ".join(security["skipped_aces"])
        if not CAPABILITIES["icacls"]:
            reason += (" Không tìm thấy icacls.exe nên chỉ đọc được, không sửa được quyền.")
        else:
            reason += (" Sửa quyền chỉ hỗ trợ cấp (grant) và gỡ cấp (revoke); "
                       "không hỗ trợ tạo ACE từ chối (deny) vì thao tác đó có thể khoá "
                       "vĩnh viễn thư mục và chỉ khôi phục được bằng quyền quản trị.")
        if security.get("read_only_attribute"):
            reason += " Đối tượng đang bật thuộc tính chỉ-đọc (read-only)."
        result["reason"] = reason
        return result

    if IS_POSIX:
        mode = stat.S_IMODE(st.st_mode)
        owner, group = _posix_owner_names(st)
        acl_present, acl_note = _detect_posix_acl(safe_path)
        readable, writable, executable, methods = _posix_access(safe_path)

        posix: Dict[str, Any] = {
            # 4 octal digits: S_IMODE masks with 0o7777 and keeps setuid/setgid/
            # sticky. ":03o" would truncate a setuid binary's 4755 to "755" and
            # echoing that back into a chmod would silently strip setuid.
            "mode": "%04o" % mode,
            "octal": mode,
            "owner": owner,
            "group": group,
            "uid": getattr(st, "st_uid", None),
            "gid": getattr(st, "st_gid", None),
            "filemode": stat.filemode(st.st_mode),
            "setuid": bool(mode & stat.S_ISUID),
            "setgid": bool(mode & stat.S_ISGID),
            "sticky": bool(mode & stat.S_ISVTX),
            "acl_present": acl_present,
            "acl_note": acl_note,
        }
        posix.update(_decompose_mode(mode))
        result["posix"] = posix
        result.update({"readable": readable, "writable": writable, "executable": executable, "checks": methods})
        result["supported"] = True
        result["can_edit"] = not is_link

        reason = "Quyền POSIX đọc từ os.lstat (không đi theo liên kết)."
        if not CAPABILITIES["has_pwd"] or not CAPABILITIES["has_grp"]:
            reason += " Không tra được tên chủ sở hữu/nhóm, hiển thị dạng số."
        if acl_present or acl_present is None:
            # Both "has an ACL" and "could not tell" mean the mode below is not
            # necessarily the effective permission, so neither may be silent.
            reason += " " + acl_note
        if CAPABILITIES["has_geteuid"]:
            try:
                if os.geteuid() == 0:
                    reason += (" Tiến trình đang chạy bằng root: các cờ readable/writable phản ánh "
                               "quyền bỏ qua kiểm tra DAC của root, không phải quyền của người dùng thường.")
            except OSError:
                pass
        if is_link:
            reason += " Không cho sửa quyền trực tiếp trên liên kết; hãy thao tác trên đường dẫn đích."
        result["reason"] = reason
        return result

    result["supported"] = False
    result["reason"] = (
        f"Nền tảng '{sys.platform}' không được hỗ trợ đọc quyền. "
        "Chỉ hỗ trợ Windows (ACL), Linux và macOS (chế độ POSIX)."
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────────────────────

def _error(message: str, *, applied: str = "", failed: Optional[List[Dict[str, str]]] = None,
           **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "status": "error",
        "applied": applied,
        "message": message,
        "failed": failed or [],
        "warnings": [],
        "applied_count": 0,
        "total_count": 0,
    }
    out.update(extra)
    return out


def _parse_posix_mode(raw: str) -> int:
    """"0755" / "755" / "0o755" -> int. Raises ValueError with a clear reason."""
    text = str(raw).strip().lower()
    if text.startswith("0o"):
        text = text[2:]
    if not text or not re.fullmatch(r"[0-7]{3,4}", text):
        raise ValueError(
            f"posix_mode không hợp lệ: '{raw}'. Cần 3 hoặc 4 chữ số bát phân, ví dụ 755 hoặc 0644."
        )
    value = int(text, 8)
    if not 0 <= value <= 0o7777:
        raise ValueError(f"posix_mode ngoài khoảng cho phép: '{raw}'.")
    return value


def _enumerate_tree(root: str, cap: int) -> Tuple[List[Tuple[str, bool]], List[Dict[str, str]], bool]:
    """Every item under `root`, deepest first, plus walk errors.

    Returns (items, walk_errors, truncated). Links are never followed and never
    returned as targets: on Windows the links under a data tree are junctions,
    which report islink()=False and which os.walk descends into regardless of
    followlinks — chmod or icacls through one would modify a completely
    different tree.
    """
    items: List[Tuple[str, bool]] = []
    walk_errors: List[Dict[str, str]] = []
    truncated = False

    def on_error(exc: OSError) -> None:
        # os.walk's default onerror=None DISCARDS these — an unreadable subtree
        # vanishes from the walk with no exception, and the caller is told the
        # whole tree succeeded.
        walk_errors.append({
            "path": getattr(exc, "filename", None) or root,
            "error": f"Không duyệt được: {exc}",
            "source": "walk",
        })

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=on_error, followlinks=False):
        kept = []
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if _is_link(full):
                walk_errors.append({
                    "path": full,
                    "error": "Bỏ qua vì là liên kết (symlink/junction); đổi quyền qua liên kết sẽ tác động lên đích ngoài phạm vi yêu cầu.",
                    "source": "walk",
                })
                continue
            kept.append(name)
            items.append((full, True))
        dirnames[:] = kept
        for name in filenames:
            full = os.path.join(dirpath, name)
            if _is_link(full):
                walk_errors.append({
                    "path": full,
                    "error": "Bỏ qua vì là liên kết (symlink); đổi quyền qua liên kết sẽ tác động lên đích.",
                    "source": "walk",
                })
                continue
            items.append((full, False))
        if len(items) > cap:
            truncated = True
            break

    items.sort(key=lambda pair: pair[0].count(os.sep), reverse=True)
    items.append((root, True))
    return items, walk_errors, truncated


# ─────────────────────────────────────────────────────────────────────────────
# Write: POSIX
# ─────────────────────────────────────────────────────────────────────────────

def _chmod_one(target: str, is_dir: bool, file_mode: int, dir_mode: int) -> Optional[str]:
    """chmod + verify. Returns an error string, or None on success."""
    want = dir_mode if is_dir else file_mode
    try:
        os.chmod(target, want)
    except OSError as exc:
        return f"chmod thất bại: {exc}"
    try:
        got = stat.S_IMODE(os.lstat(target).st_mode)
    except OSError as exc:
        return f"Đã gọi chmod nhưng không đọc lại được để xác nhận: {exc}"
    if got != want:
        # Catches filesystems that accept chmod and ignore it — vfat, exfat, an
        # NTFS volume mounted on Linux. Without this check the call "succeeds"
        # while nothing changed.
        return (f"Hệ thống tập tin không lưu được chế độ này: yêu cầu {want:04o} "
                f"nhưng đọc lại thấy {got:04o}.")
    return None


def _apply_posix(safe_path: str, raw_mode: str, recursive: bool) -> Dict[str, Any]:
    try:
        file_mode = _parse_posix_mode(raw_mode)
    except ValueError as exc:
        return _error(str(exc))

    if _is_link(safe_path):
        try:
            target = os.path.realpath(safe_path)
        except OSError:
            target = "(không xác định)"
        return _error(
            f"'{safe_path}' là liên kết. os.chmod sẽ đổi quyền của đích ({target}) chứ không phải của liên kết, "
            "nên yêu cầu bị từ chối để không sửa nhầm tập tin khác. Hãy gọi lại với đúng đường dẫn đích."
        )

    is_dir = os.path.isdir(safe_path)
    # Directories need the traverse bit wherever read is allowed. Applying a
    # flat 0644 to a tree strips x from every directory and makes the whole
    # subtree unenterable — including for the code that would undo it.
    dir_mode = file_mode | ((file_mode & 0o444) >> 2)

    if recursive and is_dir and not dir_mode & stat.S_IXUSR:
        return _error(
            f"Từ chối áp dụng đệ quy chế độ {file_mode:04o}: chế độ này không cho chủ sở hữu quyền đọc, "
            f"nên thư mục sẽ nhận {dir_mode:04o} và không ai vào được cây thư mục nữa (kể cả để hoàn tác). "
            "Hãy dùng chế độ có bit đọc cho chủ sở hữu, ví dụ 0700 hoặc 0755."
        )

    warnings: List[str] = []
    if not recursive or not is_dir:
        err = _chmod_one(safe_path, is_dir, file_mode, dir_mode)
        applied = f"{(dir_mode if is_dir else file_mode):04o}"
        if err:
            return _error(
                f"Không đổi được quyền cho {safe_path}: {err}",
                failed=[{"path": safe_path, "error": err, "source": "apply"}],
                total_count=1,
            )
        if recursive and not is_dir:
            warnings.append("Đường dẫn là tập tin nên tuỳ chọn đệ quy không có tác dụng.")
        return {
            "status": "ok",
            "applied": applied,
            "message": f"Đã đặt quyền {applied} cho {safe_path}.",
            "failed": [],
            "warnings": warnings,
            "applied_count": 1,
            "total_count": 1,
        }

    items, walk_errors, truncated = _enumerate_tree(safe_path, MAX_RECURSIVE_ITEMS)
    if truncated:
        return _error(
            f"Từ chối áp dụng đệ quy: cây thư mục có hơn {MAX_RECURSIVE_ITEMS} mục. "
            "Chưa có mục nào bị thay đổi. Hãy chọn thư mục con nhỏ hơn hoặc dùng chmod trực tiếp trên máy chủ."
        )

    failed: List[Dict[str, str]] = list(walk_errors)
    applied_count = 0
    # Deepest first: a parent whose mode changes first could take away the
    # traverse bit needed to reach its own children.
    for target, item_is_dir in items:
        err = _chmod_one(target, item_is_dir, file_mode, dir_mode)
        if err:
            failed.append({"path": target, "error": err, "source": "apply"})
        else:
            applied_count += 1

    total = len(items)
    applied_str = f"{file_mode:04o} (thư mục: {dir_mode:04o})"
    if dir_mode != file_mode:
        warnings.append(
            f"Thư mục nhận {dir_mode:04o} thay vì {file_mode:04o}: bit thực thi được giữ lại "
            "để còn vào được thư mục."
        )
    if failed:
        return {
            "status": "error",
            "applied": applied_str,
            "message": (f"Không hoàn thành yêu cầu: {applied_count}/{total} mục đổi được quyền, "
                        f"{len(failed)} mục thất bại. Danh sách lỗi nằm trong trường 'failed'."),
            "failed": failed,
            "warnings": warnings,
            "applied_count": applied_count,
            "total_count": total,
            # "partial" means some work landed. Zero applied is a total failure,
            # and labelling it partial would overstate what happened.
            "partial": applied_count > 0,
        }
    return {
        "status": "ok",
        "applied": applied_str,
        "message": f"Đã đặt quyền cho toàn bộ {total} mục trong {safe_path}.",
        "failed": [],
        "warnings": warnings,
        "applied_count": applied_count,
        "total_count": total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Write: Windows
# ─────────────────────────────────────────────────────────────────────────────

# Only simple, non-destructive rights. Anything outside this table is refused
# with the list of accepted values rather than passed through to icacls.
_RIGHTS_ALIASES: Dict[str, str] = {
    "R": "R", "READ": "R",
    "W": "W", "WRITE": "W",
    "RX": "RX", "READANDEXECUTE": "RX", "READEXECUTE": "RX",
    "M": "M", "MODIFY": "M",
    "F": "F", "FULL": "F", "FULLCONTROL": "F",
}
_RIGHTS_LABELS = {"R": "đọc", "W": "ghi", "RX": "đọc và thực thi", "M": "sửa đổi", "F": "toàn quyền"}

_IDENTITY_RE = re.compile(r'^[^:"/*?<>|\r\n\t]+$')


def _normalize_rights(raw: str) -> str:
    key = re.sub(r"[\s_()]", "", str(raw or "")).upper()
    if key not in _RIGHTS_ALIASES:
        raise ValueError(
            f"Quyền '{raw}' không được hỗ trợ. Giá trị hợp lệ: R (đọc), W (ghi), RX (đọc và thực thi), "
            "M (sửa đổi), F (toàn quyền)."
        )
    return _RIGHTS_ALIASES[key]


def _validate_identity(raw: str) -> str:
    identity = str(raw or "").strip()
    if not identity:
        raise ValueError("Thiếu 'identity': cần tên tài khoản hoặc nhóm, ví dụ 'MAYTINH\\ten_nguoi_dung'.")
    if len(identity) > 256:
        raise ValueError("'identity' quá dài (tối đa 256 ký tự).")
    if identity.startswith("*"):
        # icacls accepts *S-1-5-32-545 for a raw SID; nothing else may start
        # with '*', which would otherwise read as a wildcard.
        if not re.fullmatch(r"\*S-1-[0-9\-]+", identity):
            raise ValueError("'identity' bắt đầu bằng '*' chỉ hợp lệ với dạng SID, ví dụ *S-1-5-32-545.")
        return identity
    if not _IDENTITY_RE.fullmatch(identity):
        raise ValueError(
            "'identity' chứa ký tự không hợp lệ. Không dùng : \" / * ? < > | hay ký tự xuống dòng. "
            "Dạng đúng: 'ten_nguoi_dung' hoặc 'MIEN\\ten_nguoi_dung'."
        )
    return identity


def _run_icacls(args: List[str]) -> Tuple[bool, str]:
    """One icacls call on one item. Returns (ok, detail).

    Success is judged by exit code + stderr, never by matching the echoed path:
    icacls destroys non-ASCII characters in its own output before writing them
    to a pipe, so a Vietnamese filename or account name comes back with literal
    '?' in place of the accented letters and cannot be matched against anything.
    """
    icacls = CAPABILITIES["icacls"]
    if not icacls:
        return False, "Không tìm thấy icacls.exe."
    try:
        proc = subprocess.run([icacls] + args, **_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        return False, f"icacls không phản hồi sau {SUBPROCESS_TIMEOUT_SEC}s."
    except OSError as exc:
        return False, f"Không chạy được icacls: {exc}"
    stderr = _decode_process_output(proc.stderr).strip()
    if proc.returncode != 0:
        return False, stderr or f"icacls trả về mã thoát {proc.returncode}."
    if stderr:
        return False, stderr
    return True, ""


def _icacls_target(path: str) -> str:
    """A trailing separator makes icacls treat the argument as a search pattern."""
    if len(path) > 3 and path.endswith(("\\", "/")):
        return path.rstrip("\\/")
    return path


def _apply_windows(safe_path: str, spec: Dict[str, Any], recursive: bool) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        return _error("Tham số 'windows' phải là một object có các khoá identity, rights, action.")

    action = str(spec.get("action") or "").strip().lower()
    if action == "deny":
        return _error(
            "Không hỗ trợ tạo ACE từ chối (deny). Một ACE deny có thể khoá vĩnh viễn thư mục: "
            "sau khi deny toàn quyền, ngay cả chủ sở hữu cũng không chạy được takeown, icacls /reset "
            "hay xoá thư mục nếu không có quyền quản trị. Hãy dùng action='revoke' để gỡ quyền đã cấp."
        )
    if action not in ("grant", "revoke"):
        return _error("'action' phải là 'grant' hoặc 'revoke'.")

    try:
        identity = _validate_identity(spec.get("identity"))
    except ValueError as exc:
        return _error(str(exc))

    rights = ""
    if action == "grant":
        try:
            rights = _normalize_rights(spec.get("rights"))
        except ValueError as exc:
            return _error(str(exc))

    if not CAPABILITIES["icacls"]:
        return _error(
            "Không tìm thấy icacls.exe nên không thể đổi quyền trên Windows. "
            "Kiểm tra %SystemRoot%\\System32\\icacls.exe, hoặc đổi quyền thủ công bằng "
            "Explorer > chuột phải > Properties > Security."
        )

    warnings: List[str] = []
    inherit = bool(spec.get("inherit"))

    if action == "revoke":
        # /remove:g drops every granted ACE for the account, not just some
        # rights — icacls cannot subtract an individual right.
        warnings.append(
            f"Thao tác gỡ bỏ TẤT CẢ các ACE cấp quyền cho '{identity}', không chỉ một phần quyền. "
            "ACE từ chối (deny) không bị đụng tới."
        )
        current_user = _current_windows_identity()
        if current_user and _identity_matches(current_user, identity):
            owner = None
            try:
                owner = _read_windows_security(safe_path).get("owner")
            except Exception:
                owner = None
            if owner is None:
                return _error(
                    f"Từ chối gỡ quyền của chính tài khoản đang chạy ('{current_user}') vì không xác định được "
                    "chủ sở hữu của đối tượng. Nếu không phải chủ sở hữu, bạn sẽ mất quyền truy cập và chỉ "
                    "quản trị viên mới khôi phục được."
                )
            if not _identity_matches(owner, current_user):
                return _error(
                    f"Từ chối gỡ quyền của chính tài khoản đang chạy ('{current_user}') vì chủ sở hữu đối tượng là "
                    f"'{owner}'. Sau thao tác này bạn sẽ không còn cách nào tự cấp lại quyền."
                )
            warnings.append(
                f"Bạn đang gỡ quyền của chính mình. Vẫn khôi phục được vì '{current_user}' là chủ sở hữu."
            )

    def icacls_args(target: str, target_is_dir: bool) -> List[str]:
        if action == "grant":
            prefix = "(OI)(CI)" if (inherit and target_is_dir) else ""
            return [_icacls_target(target), "/grant", f"{identity}:{prefix}({rights})"]
        return [_icacls_target(target), "/remove:g", identity]

    applied_str = (f"grant {identity}:({rights})" if action == "grant" else f"remove-grant {identity}")
    is_dir = os.path.isdir(safe_path)

    def finish(applied_count: int, total: int, failed: List[Dict[str, str]]) -> Dict[str, Any]:
        """Merge the post-change verification into the result.

        icacls exits 0 for a /remove:g that removed nothing, because an
        INHERITED ACE cannot be removed from the child that inherits it. Taking
        that exit code at face value is how a green checkmark gets shown for
        work that did not happen, so the re-read decides the status.
        """
        verify_warnings, effective = _verify_windows_change(safe_path, identity, action)
        warnings.extend(verify_warnings)
        if total > 1:
            warnings.append(
                f"Chỉ xác minh lại quyền của mục gốc ({safe_path}); "
                f"{total - 1} mục còn lại chỉ được đánh giá qua mã thoát của icacls."
            )
        if effective is False:
            failed = failed + [{
                "path": safe_path,
                "error": "icacls chạy xong nhưng đọc lại thấy quyền không thay đổi như yêu cầu.",
                "source": "verify",
            }]
            applied_count = max(0, applied_count - 1)
        if failed:
            return {
                "status": "error",
                "applied": applied_str,
                "message": (
                    f"Không hoàn thành yêu cầu: {applied_count}/{total} mục thay đổi được, "
                    f"{len(failed)} mục thất bại. Chi tiết trong 'failed' và 'warnings'."
                ),
                "failed": failed,
                "warnings": warnings,
                "applied_count": applied_count,
                "total_count": total,
                "partial": applied_count > 0,
            }
        return {
            "status": "ok",
            "applied": applied_str,
            "message": _windows_success_message(action, identity, rights, safe_path, total),
            "failed": [],
            "warnings": warnings,
            "applied_count": applied_count,
            "total_count": total,
        }

    if not recursive or not is_dir:
        ok, detail = _run_icacls(icacls_args(safe_path, is_dir))
        if recursive and not is_dir:
            warnings.append("Đường dẫn là tập tin nên tuỳ chọn đệ quy không có tác dụng.")
        if not ok:
            return _error(
                f"icacls không thực hiện được thao tác trên {safe_path}: {detail}",
                applied="",
                failed=[{"path": safe_path, "error": detail, "source": "apply"}],
                total_count=1,
                warnings=warnings,
            )
        return finish(1, 1, [])

    items, walk_errors, truncated = _enumerate_tree(safe_path, MAX_RECURSIVE_ITEMS)
    if truncated:
        return _error(
            f"Từ chối áp dụng đệ quy: cây thư mục có hơn {MAX_RECURSIVE_ITEMS} mục. "
            "Chưa có mục nào bị thay đổi. Hãy chọn thư mục con nhỏ hơn.",
            warnings=warnings,
        )

    failed: List[Dict[str, str]] = list(walk_errors)
    applied_count = 0
    # One icacls call per item. `icacls /T /C` exits 0 while reporting its own
    # failures only on stderr, which is precisely how a green checkmark gets
    # shown for work that did not happen; and without /C it stops at the first
    # error having processed part of the tree.
    for target, target_is_dir in items:
        ok, detail = _run_icacls(icacls_args(target, target_is_dir))
        if ok:
            applied_count += 1
        else:
            failed.append({"path": target, "error": detail, "source": "apply"})

    return finish(applied_count, len(items), failed)


def _windows_success_message(action: str, identity: str, rights: str, path: str, count: int) -> str:
    scope = f"{count} mục trong {path}" if count > 1 else path
    if action == "grant":
        return f"Đã cấp quyền {_RIGHTS_LABELS.get(rights, rights)} ({rights}) cho '{identity}' trên {scope}."
    return f"Đã gỡ các quyền đã cấp cho '{identity}' trên {scope}."


def _verify_windows_change(path: str, identity: str, action: str) -> Tuple[List[str], Optional[bool]]:
    """Re-read the DACL of `path`. Returns (warnings, effective).

    `effective` is True when the DACL now reflects the request, False when it
    demonstrably does not, and None when the check itself could not run — an
    unverifiable result must not be reported as either success or failure.
    """
    warnings: List[str] = []
    try:
        security = _read_windows_security(path)
    except Exception as exc:
        warnings.append(
            f"Không xác minh lại được quyền sau khi thay đổi: {exc}. "
            "Kết quả dưới đây chỉ dựa trên mã thoát của icacls."
        )
        return warnings, None

    matching = [e for e in security.get("entries", [])
                if e.get("type") == "allow" and _identity_matches(e.get("identity") or "", identity)]
    if action == "revoke":
        inherited = [e for e in matching if e.get("inherited")]
        if inherited:
            warnings.append(
                f"'{identity}' VẪN còn quyền trên {path} do thừa kế từ thư mục cha "
                "(ACE thừa kế không thể gỡ tại đây, icacls vẫn báo thành công). "
                "Hãy sửa quyền ở thư mục cha, hoặc tắt thừa kế cho đối tượng này rồi thử lại."
            )
            return warnings, False
        if matching:
            warnings.append(
                f"'{identity}' vẫn còn ACE cấp quyền trực tiếp trên {path} sau khi gỡ."
            )
            return warnings, False
        return warnings, True
    if action == "grant" and not matching:
        warnings.append(
            f"icacls báo thành công nhưng đọc lại không thấy ACE cấp quyền nào cho '{identity}' trên {path}. "
            "Hãy kiểm tra lại tên tài khoản."
        )
        return warnings, False
    return warnings, True


# ─────────────────────────────────────────────────────────────────────────────
# Public: write
# ─────────────────────────────────────────────────────────────────────────────

def set_permissions(path: str, *, recursive: bool = False, posix_mode: Optional[str] = None,
                    windows: Optional[Dict[str, Any]] = None, service=None) -> Dict[str, Any]:
    """Change permissions on `path`.

    Refuses with status="error" rather than applying half a change. A recursive
    apply that hits problems returns status="error" with every failure listed in
    `failed` and the real counts in applied_count/total_count — it never reports
    success for work that did not happen.

    Raises ValueError (outside sandbox) or FileNotFoundError (missing path).
    Never raises because of the platform.
    """
    safe_path = _validated(path, service)
    platform_name = _platform_name()
    recursive = bool(recursive)

    def finish(result: Dict[str, Any]) -> Dict[str, Any]:
        result.setdefault("warnings", [])
        result.setdefault("failed", [])
        result.setdefault("applied_count", 0)
        result.setdefault("total_count", 0)
        result["path"] = safe_path
        result["platform"] = platform_name
        result["recursive"] = recursive
        return result

    if posix_mode is None and windows is None:
        return finish(_error(
            "Không có gì để áp dụng: cần 'posix_mode' (Linux/macOS) hoặc 'windows' (Windows)."
        ))
    if posix_mode is not None and windows is not None:
        return finish(_error(
            "Chỉ được gửi một trong hai: 'posix_mode' hoặc 'windows'. "
            "Gửi cả hai là dấu hiệu gọi sai API, nên yêu cầu bị từ chối thay vì áp dụng một nửa."
        ))

    if IS_WINDOWS:
        if posix_mode is not None:
            return finish(_error(
                "Windows không lưu chế độ quyền kiểu POSIX. os.chmod trên Windows chỉ bật/tắt thuộc tính "
                "chỉ-đọc — mọi giá trị chỉ cho ra 0666 (ghi được) hoặc 0444 (chỉ đọc), nên hiển thị hay nhận "
                "'0755' ở đây là bịa. Hãy dùng trường 'windows' với identity/rights/action (thực hiện bằng icacls)."
            ))
        return finish(_apply_windows(safe_path, windows or {}, recursive))

    if IS_POSIX:
        if windows is not None:
            return finish(_error(
                f"Tham số 'windows' chỉ dùng được trên Windows; hệ thống hiện tại là {platform_name}. "
                "Hãy dùng 'posix_mode', ví dụ '0755'."
            ))
        return finish(_apply_posix(safe_path, posix_mode or "", recursive))

    return finish(_error(
        f"Nền tảng '{sys.platform}' không được hỗ trợ đổi quyền. "
        "Chỉ hỗ trợ Windows (ACL qua icacls), Linux và macOS (chmod)."
    ))
