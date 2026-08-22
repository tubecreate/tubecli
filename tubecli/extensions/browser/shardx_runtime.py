"""Platform-aware resolution, download and extraction of the ShardX engine.

Why this module exists
----------------------
The browser extension was built around BAS (`FastExecuteScript.x64.zip` from
bablosoft), which ships Windows PE binaries and nothing else. On Linux the engine
list still offered those builds, the ShardX download URL was hardcoded to
`ShardX-Windows.zip`, and the install directory was derived from %APPDATA% — so a
Linux user could pick an engine, watch it download, and end up with nothing that
runs and no message explaining why.

ShardX does publish a Linux build. The logic here is ported from ShardX's own SDK
(`sdks/python/shardx/runtime.py`), keeping the two details that are easy to get
wrong and expensive to debug:

1. On POSIX we shell out to the system `unzip` rather than using Python's
   `zipfile`. zipfile cannot restore symlinks and silently drops permission bits,
   which produces a tree that extracts cleanly and then fails to launch.
2. Archives produced on Windows carry no Unix exec bits at all, so after
   extraction every native binary under the engine root needs +x restored — not
   just `chrome`, because it spawns `chrome_crashpad_handler`, `chrome_sandbox`
   and friends.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Same CDN and manifest the ShardX launcher and SDK use.
PUB_BASE = "https://pub-e57a7c60f6934eb09a6600bf2fc59cdc.r2.dev"
WORKER_BASE = "https://cf-r2-worker.tubecli.workers.dev"
MANIFEST_URL = "https://raw.githubusercontent.com/ProxyShard/ShardBrowser/main/runtime.json"

# Phiên bản dùng khi KHÔNG đọc được manifest (mất mạng, GitHub chặn). Đây chỉ là
# lưới an toàn — phiên bản thật luôn lấy từ manifest qua current_version(), nên khi
# ShardX phát hành nhân mới (150, 151...) extension tự nhận mà không phải sửa code.
FALLBACK_VERSION = "149.0.7827.103"
PINNED_VERSION = FALLBACK_VERSION          # tên cũ, giữ cho code ngoài còn import

# Ép một phiên bản cụ thể (thử nhân mới trước khi manifest kịp cập nhật):
#   SHARDX_ENGINE_VERSION=151.0.7900.10
ENV_VERSION_OVERRIDE = "SHARDX_ENGINE_VERSION"

_MANIFEST_TTL = 1800          # 30 phút: đủ bắt bản mới trong ngày, không spam GitHub
_manifest_cache = {"at": 0.0, "data": {}}

_NATIVE_MAGIC = (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")

ProgressCb = Callable[[str, int, int], None]   # (label, received, total)


@dataclass(frozen=True)
class HostSpec:
    """What this machine needs in order to run ShardX."""
    plat: str                          # "Windows" | "Linux" | "Mac-arm64"
    archive: str                       # base archive name in the bucket
    binary_subpath: tuple[str, ...]    # path under the version dir to the executable
    supported: bool = True
    reason: str = ""                   # why not, when unsupported


def host_spec() -> HostSpec:
    """Describe the current host, or say plainly that it is not supported.

    Never raises: the caller is usually rendering an engine list or a progress
    file, and an exception there is what produced the original silent failure.
    """
    sysname = sys.platform
    arch = platform.machine().lower()

    if sysname == "win32" and arch in ("amd64", "x86_64"):
        return HostSpec("Windows", "ShardX-Windows.zip", ("ShardX-Windows", "chrome.exe"))
    if sysname.startswith("linux") and arch in ("x86_64", "amd64"):
        return HostSpec("Linux", "ShardX-Linux.zip", ("ShardX-Linux", "chrome"))
    if sysname == "darwin" and arch in ("arm64", "aarch64"):
        return HostSpec(
            "Mac-arm64", "ShardX-Mac-arm64.zip",
            ("ShardX-Mac-arm64", "ShardX.app", "Contents", "MacOS", "ShardX"),
        )

    return HostSpec(
        "", "", (), supported=False,
        reason=(f"ShardX has no build for {sysname}/{arch}. "
                f"Supported: Windows x64, Linux x64, macOS arm64."),
    )


def supports_bas() -> bool:
    """BAS ships Windows PE binaries only, so offering it anywhere else means
    offering a download that cannot possibly run."""
    return sys.platform == "win32"


def launcher_root() -> Path:
    """Where the ShardX Launcher keeps its runtime, per OS.

    Sharing this directory means a user who already installed the launcher does
    not download the engine a second time.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "shardx-launcher"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "shardx-launcher"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "shardx-launcher"


def engine_dir(version: str) -> Path:
    """Directory holding one installed engine version."""
    return launcher_root() / "runtime" / "engines" / version


def binary_path(version: str) -> Optional[Path]:
    """Full path to the ShardX executable for `version`, or None when unsupported.

    Tries the layouts the launcher and the CDN archives have used, so an engine
    installed by either route is found.
    """
    spec = host_spec()
    if not spec.supported:
        return None
    root = engine_dir(version)
    exe = spec.binary_subpath[-1]
    candidates = [
        root.joinpath(*spec.binary_subpath),                                   # ShardX-Linux/chrome
        root / f"ShardX-{spec.plat}-{version}" / exe,                          # versioned wrapper dir
        root / exe,                                                            # flattened
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def is_installed(version: str) -> bool:
    p = binary_path(version)
    return bool(p and p.exists())


def archive_url(version: str) -> str:
    """CDN URL của gói engine cho host này + phiên bản này.

    Bản MỚI NHẤT nằm ở PUB_BASE dưới tên không có số phiên bản (ShardX-Windows.zip) —
    ShardX ghi đè chính file đó mỗi lần lên nhân mới. Bản cũ hơn nằm sau worker theo
    route có số phiên bản.

    Trước đây chỗ này so với hằng số PINNED_VERSION cứng trong code: ngay khi ShardX
    bump manifest (149 -> 150/151), bản mới nhất bị coi là "bản cũ" và tải qua route
    worker — nơi chưa bao giờ có file đó -> 404. Nay so với manifest.
    """
    spec = host_spec()
    if version == current_version():
        return f"{PUB_BASE}/{spec.archive}"
    return f"{WORKER_BASE}/ShardX-{spec.plat}-{version}.zip"


def download_candidates(version: str) -> list:
    """Các URL để thử lần lượt.

    Manifest và bucket không đổi cùng lúc (bucket thường lên trước). Thử cả hai đường
    thay vì tin tuyệt đối một cái: hỏng đường này còn đường kia, thay vì ném 404 cho
    người dùng.
    """
    spec = host_spec()
    if not spec.supported:
        return []
    pub = f"{PUB_BASE}/{spec.archive}"
    worker = f"{WORKER_BASE}/ShardX-{spec.plat}-{version}.zip"
    urls = [pub, worker] if version == current_version() else [worker, pub]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def url_exists(url: str, timeout: float = 12.0) -> bool:
    """HEAD kiểm tra file có thật — để không mời người dùng bấm Tải một URL 404."""
    try:
        import requests
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


FINGERPRINTS_ARCHIVE = "ShardX-Fingerprints.zip"


def fingerprints_dir() -> Path:
    """Where the engine looks for the ShardX fingerprint library."""
    return launcher_root() / "runtime" / "fingerprints"


def fingerprints_installed() -> bool:
    d = fingerprints_dir()
    return d.is_dir() and any(d.glob("*.json"))


def install_fingerprints(on_progress=None) -> bool:
    """Fetch the ShardX fingerprint library.

    Without it a profile launches with no --fingerprint-profile at all, which
    silently defeats the entire point of a browser profile. The engine download
    never fetched it, and on Windows it was only ever present because the ShardX
    Launcher had been installed separately.
    """
    dest = fingerprints_dir()
    if fingerprints_installed():
        return True
    tmp = dest.parent / f".{FINGERPRINTS_ARCHIVE}.tmp"
    try:
        download(f"{PUB_BASE}/{FINGERPRINTS_ARCHIVE}", tmp, on_progress=on_progress)
        extract(tmp, dest)
        # The archive carries its own top-level folder; flatten so the engine's
        # lookup finds *.json directly in the fingerprints directory.
        if not any(dest.glob("*.json")):
            for sub in dest.iterdir():
                if sub.is_dir() and any(sub.glob("*.json")):
                    for f in sub.glob("*.json"):
                        f.replace(dest / f.name)
                    break
        return fingerprints_installed()
    except Exception:
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def missing_linux_libraries() -> list:
    """Shared libraries Chromium needs that this machine does not have.

    Only meaningful on Linux. A container image typically has none of them, and
    the failure mode without this check is chrome exiting immediately with a
    loader error that never reaches the user.
    """
    if not sys.platform.startswith("linux"):
        return []
    needed = [
        "libnss3.so", "libnspr4.so", "libatk-1.0.so.0", "libatk-bridge-2.0.so.0",
        "libcups.so.2", "libxkbcommon.so.0", "libXcomposite.so.1", "libXdamage.so.1",
        "libXfixes.so.3", "libXrandr.so.2", "libgbm.so.1", "libpango-1.0.so.0",
        "libcairo.so.2", "libasound.so.2",
    ]
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []          # cannot tell; do not invent a warning
    return [lib for lib in needed if lib not in out]


# Packages, with the alternatives each one goes by.
#
# Ubuntu 24.04 ("noble") renamed several of these in the 64-bit time_t
# transition: libatk1.0-0 -> libatk1.0-0t64, libcups2 -> libcups2t64 and so on.
# apt resolves most of those itself through Provides, but NOT libasound2, which
# became a virtual package with two providers — apt then refuses to guess and
# fails the ENTIRE transaction with "Package 'libasound2' has no installation
# candidate", so one renamed package took every other library down with it.
#
# Listing alternatives and installing them one at a time means a name that does
# not exist on this release costs only itself. The libraries actually present
# are re-checked afterwards by missing_linux_libraries(), which is the answer that
# matters — package names are a means, not the goal.
_APT_ALTERNATIVES = (
    ("unzip",),
    ("ca-certificates",),
    ("fonts-liberation",),
    ("libnss3",),
    ("libnspr4",),
    ("libatk1.0-0t64", "libatk1.0-0"),
    ("libatk-bridge2.0-0t64", "libatk-bridge2.0-0"),
    ("libcups2t64", "libcups2"),
    ("libxkbcommon0",),
    ("libxcomposite1",),
    ("libxdamage1",),
    ("libxfixes3",),
    ("libxrandr2",),
    ("libgbm1",),
    ("libpango-1.0-0",),
    ("libcairo2",),
    ("libasound2t64", "libasound2"),
    ("libxshmfence1",),
)

# Kept as a plain string: it is what gets shown to a user who has to run the
# command by hand, and several call sites already .split() it. The t64 names go
# first so a copy-paste works on current Ubuntu; on older releases apt resolves
# them back through Provides.
LINUX_APT_PACKAGES = " ".join(alts[0] for alts in _APT_ALTERNATIVES)


def download(url: str, dest: Path, on_progress=None, attempts: int = 4) -> None:
    """Fetch `url` to `dest`, resuming across dropped connections.

    The engine archive is >200 MB, and the previous implementation was a single
    `requests.get(..., timeout=300)` with no retry. Two consequences, both of which
    look identical to a frozen program:

    * `timeout` in requests is per socket read, not for the transfer, so a
      connection that dies without closing blocks for the full 300 s on every
      chunk. A short read timeout turns that into a fast, retryable error.
    * A failure at 97% discarded 200 MB and started again. Range requests resume
      from whatever is already on disk instead.

    `on_progress(received, total, speed_bps)` is called as bytes arrive.
    """
    import time
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = None

    for attempt in range(1, attempts + 1):
        have = dest.stat().st_size if dest.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            # (connect timeout, read timeout). 30 s without a single byte means the
            # transfer is dead, not slow — a healthy CDN sends something long before.
            with requests.get(url, stream=True, timeout=(15, 30), headers=headers) as r:
                if have and r.status_code == 200:
                    # Server ignored the Range header; start over rather than
                    # appending a second full copy onto the first partial one.
                    have = 0
                    dest.unlink(missing_ok=True)
                elif have and r.status_code != 206:
                    r.raise_for_status()
                else:
                    r.raise_for_status()

                total = int(r.headers.get("content-length", 0)) + have
                received = have
                started = time.monotonic()
                mode = "ab" if have else "wb"
                with dest.open(mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 18):
                        if not chunk:
                            continue
                        f.write(chunk)
                        received += len(chunk)
                        if on_progress:
                            elapsed = max(time.monotonic() - started, 0.001)
                            speed = (received - have) / elapsed
                            on_progress(received, total, speed)
            return
        except Exception as e:            # noqa: BLE001 - reported to the user below
            last_err = e
            if attempt < attempts:
                if on_progress:
                    on_progress(-1, 0, 0.0)   # signals "retrying" to the caller
                time.sleep(min(2 ** attempt, 10))

    raise RuntimeError(f"download failed after {attempts} attempts: {last_err}")


def extract(archive: Path, dest: Path) -> None:
    """Extract an engine archive, preserving what the engine needs to run.

    On POSIX this shells out to `unzip`. Python's zipfile writes every symlink as
    a short text file and drops permission bits, which yields a tree that looks
    extracted and then fails on first launch.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        return

    try:
        proc = subprocess.run(
            ["unzip", "-q", "-o", str(archive), "-d", str(dest)],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "The system `unzip` command is required to install the engine. "
            "Install it with `apt install unzip` (Debian/Ubuntu), "
            "`dnf install unzip` (Fedora) or `brew install unzip` (macOS)."
        ) from e
    # unzip(1) uses exit 1 for warnings — typically backslashes in paths for
    # archives zipped on Windows — and extraction still completes. Only 2+ is fatal.
    if proc.returncode > 1:
        raise RuntimeError(
            f"unzip failed for {archive.name} (exit {proc.returncode}): "
            f"{proc.stderr.decode(errors='replace')[:300]}"
        )
    fix_exec_bits(dest)


def fix_exec_bits(root: Path) -> int:
    """Restore +x on every native binary under `root`; returns how many changed.

    Windows zip producers store no Unix permission bits, so chrome and every
    helper it spawns arrive non-executable.
    """
    if sys.platform == "win32":
        return 0
    fixed = 0
    for p in root.rglob("*"):
        try:
            if not p.is_file() or p.is_symlink():
                continue
            with p.open("rb") as f:
                head = f.read(4)
            if any(head.startswith(m) for m in _NATIVE_MAGIC):
                mode = p.stat().st_mode
                if not mode & 0o111:
                    p.chmod(mode | 0o111)
                    fixed += 1
        except OSError:
            pass
    return fixed


def _manifest_cache_file() -> Path:
    return launcher_root() / "runtime" / "manifest-cache.json"


def fetch_manifest(timeout: float = 8.0, force: bool = False) -> dict:
    """Manifest ShardX (chromium_version, etag từng gói, grease...).

    Cache 30 phút trong RAM + một bản trên đĩa. Danh sách engine được gọi mỗi lần mở
    trang; không cache thì mỗi lần mở là một lượt gọi GitHub — chậm và dễ bị giới hạn
    tần suất. Bản trên đĩa giúp máy mất mạng vẫn biết phiên bản mới nhất đã thấy lần
    cuối, thay vì tụt về hằng số dự phòng.
    """
    import json
    import time
    now = time.time()
    if not force and _manifest_cache["data"] and now - _manifest_cache["at"] < _MANIFEST_TTL:
        return _manifest_cache["data"]

    data = {}
    try:
        import requests
        r = requests.get(MANIFEST_URL, timeout=timeout)
        if r.status_code == 200:
            parsed = r.json()
            if isinstance(parsed, dict):
                data = parsed
    except Exception:
        data = {}

    if data:
        _manifest_cache.update(at=now, data=data)
        try:
            f = _manifest_cache_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
        return data

    if _manifest_cache["data"]:
        return _manifest_cache["data"]
    try:
        cached = json.loads(_manifest_cache_file().read_text(encoding="utf-8"))
        if isinstance(cached, dict):
            _manifest_cache.update(at=now, data=cached)
            return cached
    except Exception:
        pass
    return {}


def current_version() -> str:
    """Phiên bản nhân MỚI NHẤT mà ShardX đang phát hành cho host này."""
    forced = (os.environ.get(ENV_VERSION_OVERRIDE) or "").strip()
    if forced:
        return forced
    return fetch_manifest().get("chromium_version") or FALLBACK_VERSION


def _version_key(v: str) -> tuple:
    """So sánh phiên bản theo SỐ, không theo chuỗi — nếu không thì '9' > '151'."""
    parts = []
    for chunk in str(v).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def installed_versions() -> list:
    """Các phiên bản engine đã cài trên máy (mới nhất trước)."""
    root = launcher_root() / "runtime" / "engines"
    if not root.is_dir():
        return []
    out = [d.name for d in root.iterdir() if d.is_dir() and is_installed(d.name)]
    return sorted(out, key=_version_key, reverse=True)


def check_update() -> dict:
    """So phiên bản đã cài với phiên bản ShardX đang phát hành.

    Trả đủ để UI nói một câu rõ ràng: đang cài gì, mới nhất là gì, có nên cập nhật
    không; và nếu manifest không đọc được thì nói thẳng là đang dùng bản dự phòng.
    """
    man = fetch_manifest()
    latest = current_version()
    installed = installed_versions()
    newest = installed[0] if installed else None
    return {
        "latest": latest,
        "installed": installed,
        "newest_installed": newest,
        "update_available": bool(newest and _version_key(latest) > _version_key(newest)),
        "up_to_date": bool(newest and _version_key(latest) <= _version_key(newest)),
        "manifest_ok": bool(man),
        "manifest_revision": man.get("revision"),
        "grease_brand": man.get("grease_brand"),
        "grease_version": man.get("grease_version"),
        "forced_by_env": bool((os.environ.get(ENV_VERSION_OVERRIDE) or "").strip()),
        "source": "manifest" if man else "fallback",
    }


def available_versions() -> list:
    """ShardX engine versions that can actually be downloaded on this host.

    ShardBrowser's manifest publishes one archive per platform, unversioned, for
    the current chromium version — that is what PUB_BASE serves. The versioned
    archives behind the worker are extra uploads, and only the Windows ones exist:
    ShardX-Windows-148.*.zip answers 200 while ShardX-Linux-148.*.zip answers 404.
    Offering those on Linux meant offering a download that always fails, so list
    them only where they exist.
    """
    pinned = current_version()
    if sys.platform == "win32":
        extra = ["148.0.7778.216", "148.0.7778.97"]
        return [pinned] + [v for v in extra if v != pinned]
    return [pinned]


def _package_manager() -> Optional[list]:
    """Install-command prefix for this distro's package manager, or None."""
    for exe, cmd in (
        ("apt-get", ["apt-get", "install", "-y", "-q"]),
        ("dnf",     ["dnf", "install", "-y", "-q"]),
        ("yum",     ["yum", "install", "-y", "-q"]),
        ("pacman",  ["pacman", "-Sy", "--noconfirm"]),
        ("zypper",  ["zypper", "--non-interactive", "install"]),
        ("apk",     ["apk", "add", "--quiet"]),
    ):
        if shutil.which(exe):
            return cmd
    return None


def _can_install_packages() -> Optional[list]:
    """Command prefix that can install packages without prompting, or None.

    Root needs no prefix. A non-root user only qualifies with passwordless sudo —
    we must never leave a server process blocked on a password prompt nobody can
    see.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        try:
            r = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return ["sudo", "-n"]
        except Exception:
            pass
    return None


def install_packages(names: list, timeout: int = 600) -> bool:
    """Install system packages when this process can do so without prompting.

    Returns False rather than raising, and never blocks on a password prompt: a
    server process waiting on sudo would hang with nothing on screen to explain it.
    """
    cmd = _package_manager()
    prefix = _can_install_packages()
    if not cmd or prefix is None or not names:
        return False
    try:
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
        if cmd[0] == "apt-get":
            subprocess.run(prefix + ["apt-get", "update", "-qq"],
                           capture_output=True, timeout=timeout, env=env)
        r = subprocess.run(prefix + cmd + list(names),
                           capture_output=True, timeout=timeout, env=env)
        return r.returncode == 0
    except Exception:
        return False


def manual_install_hint(names: list) -> str:
    """The exact command to run by hand, with sudo only when it is needed."""
    cmd = _package_manager()
    need_sudo = _can_install_packages() is None
    base = " ".join(cmd) if cmd else "your package manager install"
    return f"{'sudo ' if need_sudo else ''}{base} {' '.join(names)}"


def install_chromium_libs(timeout: int = 900) -> bool:
    """Install the Chromium runtime libraries, tolerating renamed packages.

    One apt invocation per package, not one for the whole list. `apt-get install
    a b c` is all-or-nothing: on Ubuntu 24.04 the single unresolvable name
    libasound2 aborted the transaction and none of the other thirteen libraries
    were installed either. Installing them separately means a name that does not
    exist on this release costs only itself, and the alternatives cover the
    releases where it goes by another name.

    Returns whether anything was installed at all; the caller re-checks
    missing_linux_libraries() for the answer that actually matters.
    """
    cmd = _package_manager()
    prefix = _can_install_packages()
    if not cmd or prefix is None:
        return False

    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    if cmd[0] == "apt-get":
        try:
            subprocess.run(prefix + ["apt-get", "update", "-qq"],
                           capture_output=True, timeout=180, env=env)
        except Exception:
            pass

    installed_any = False
    for alternatives in _APT_ALTERNATIVES:
        for name in alternatives:
            try:
                r = subprocess.run(prefix + cmd + [name],
                                   capture_output=True, timeout=timeout, env=env)
            except Exception:
                continue
            if r.returncode == 0:
                installed_any = True
                break          # this package is handled; skip its other names
    return installed_any


def preflight() -> Optional[str]:
    """Anything that would make an install fail, checked before downloading.

    The engine archive is over 200 MB. Discovering afterwards that `unzip` is
    missing means the user waited through the whole transfer to be told the
    install could not have worked in the first place — and the same was true of
    the Chromium runtime libraries, except worse: the install reported success
    and the failure only surfaced later as
    "The engine is missing libatk-1.0.so.0" on the first launch attempt, long
    after anything connected it to the install.
    """
    spec = host_spec()
    if not spec.supported:
        return spec.reason

    if sys.platform != "win32" and not shutil.which("unzip"):
        # Install it rather than handing back a command to type. The user asked
        # for the engine, and this process can usually do it — the same reasoning
        # the installer applies to pip and venv.
        install_packages(["unzip"])
        if shutil.which("unzip"):
            return None
        blocked = _can_install_packages() is None
        return (f"`unzip` is required to install the engine and could not be "
                f"installed automatically"
                f"{' — this process is not root and sudo would prompt for a password' if blocked else ''}. "
                f"Run: {manual_install_hint(['unzip'])}")

    # The Chromium runtime libraries, checked HERE rather than discovered at
    # launch. install_packages() is deliberately silent when it cannot act —
    # it returns False rather than blocking on a sudo password no server
    # process could answer — so without this the whole install completed,
    # reported success, and the engine then refused to start with a message
    # nothing tied back to the install.
    missing = missing_linux_libraries()
    if missing:
        install_chromium_libs()
        missing = missing_linux_libraries()
    if missing:
        blocked = _can_install_packages() is None
        return (
            "The engine needs the Chromium runtime libraries, and "
            + (str(len(missing)) + " are missing: " + ", ".join(missing[:4])
               + ("…" if len(missing) > 4 else ""))
            + ". They could not be installed automatically"
            + (" — this process is not root and sudo would prompt for a password"
               if blocked else "")
            + f".\nRun: {manual_install_hint(LINUX_APT_PACKAGES.split())}"
        )
    return None
