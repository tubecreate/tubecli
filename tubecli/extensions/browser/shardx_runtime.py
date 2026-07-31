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

# The version whose archive lives at PUB_BASE under its plain name; every other
# version is served by the versioned worker route.
PINNED_VERSION = "149.0.7827.103"

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
    """CDN URL of the engine archive for this host and version."""
    spec = host_spec()
    if version == PINNED_VERSION:
        return f"{PUB_BASE}/{spec.archive}"
    return f"{WORKER_BASE}/ShardX-{spec.plat}-{version}.zip"


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


LINUX_APT_PACKAGES = (
    "unzip ca-certificates fonts-liberation libnss3 libnspr4 libatk1.0-0 "
    "libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 "
    "libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1"
)


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


def fetch_manifest(timeout: float = 8.0) -> dict:
    """Current archive etags and chromium version. Returns {} when unreachable."""
    try:
        import requests
        r = requests.get(MANIFEST_URL, timeout=timeout)
        if r.status_code != 200:
            return {}
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def available_versions() -> list:
    """Engine versions offerable on this host.

    On Windows this is ShardX plus BAS. Everywhere else it is ShardX only —
    listing BAS elsewhere offered a download of Windows executables.
    """
    shardx = ["149.0.7827.103", "148.0.7778.216", "148.0.7778.97"]
    manifest_version = fetch_manifest().get("chromium_version")
    if manifest_version and manifest_version not in shardx:
        shardx.insert(0, manifest_version)
    return shardx
