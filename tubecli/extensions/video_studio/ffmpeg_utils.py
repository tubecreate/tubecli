"""
ffmpeg/ffprobe helpers for video_studio.

Kept separate so the engines never shell out ad hoc, and so a missing ffmpeg
produces one clear message instead of a raw OSError deep in a filter chain.
"""
import logging
import os
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger("VideoStudio")

# Windows: never flash a console window for a background ffmpeg call.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _configured_dir() -> Optional[str]:
    """The `ffmpeg_path` a user can set in global settings."""
    try:
        import json

        from tubecli.config import DATA_DIR

        settings_file = os.path.join(str(DATA_DIR), "global_settings.json")
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            configured = data.get("ffmpeg_path") or ""
            if configured:
                return os.path.dirname(configured) if os.path.isfile(configured) else configured
    except Exception:
        pass
    return None


# Places a Windows/macOS/Linux user actually ends up with ffmpeg. Searched only
# when PATH comes up empty, which is the normal case for a server started from
# a desktop launcher or a service: those inherit a much smaller PATH than a
# developer shell, and the whole video chain then silently loses ffmpeg.
def _known_dirs() -> List[str]:
    dirs: List[str] = []
    configured = _configured_dir()
    if configured:
        dirs.append(configured)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or ""
        program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
        dirs += [
            r"C:\ffmpeg\bin",
            os.path.join(program_files, "ffmpeg", "bin"),
            os.path.join(local, "Microsoft", "WinGet", "Links"),
        ]
        # Versioned unzip-anywhere builds: C:\ffmpeg-7.1.1-essentials_build\bin
        try:
            for entry in os.listdir("C:\\"):
                if entry.lower().startswith("ffmpeg"):
                    dirs.append(os.path.join("C:\\", entry, "bin"))
        except Exception:
            pass
    else:
        dirs += ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/snap/bin"]
    return dirs


def _runs(exe: str) -> bool:
    """Does this binary actually start?

    Existing on disk is not the same as working. A conda install ships
    Library/bin/ffprobe.exe that dies at load with 0xC0000139
    STATUS_ENTRYPOINT_NOT_FOUND because a sibling DLL does not export what it
    links against — and shutil.which() finds it first, because the server runs
    on that same conda Python. The old code accepted it and never reached the
    working copy further down the list, so every probe failed with a raw
    "non-zero exit status 3221225785" and the UI told the user to install
    FFmpeg, which was already installed.

    One extra subprocess per binary per process; the result is cached below.
    """
    try:
        r = subprocess.run(
            [exe, "-version"], capture_output=True, timeout=15,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and b"version" in (r.stdout or b"").lower()


# name -> resolved path, or None once every candidate has been rejected.
_RESOLVED: dict = {}


def _which(name: str) -> Optional[str]:
    if name in _RESOLVED:
        return _RESOLVED[name]
    result = _which_uncached(name)
    _RESOLVED[name] = result
    return result


def _path_candidates(name: str) -> List[str]:
    """Every match on PATH, in order — not just the first.

    shutil.which() stops at the first hit, which is the wrong shape once a hit
    can be rejected: on this machine entry one is conda's broken copy and the
    working one is further down the same PATH, so stopping early loses it.
    """
    out: List[str] = []
    exe = _exe(name)
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        d = d.strip().strip('"')
        if not d:
            continue
        candidate = os.path.join(d, exe)
        if os.path.isfile(candidate) and candidate not in out:
            out.append(candidate)
    return out


def _which_uncached(name: str) -> Optional[str]:
    # Every candidate is probed and a broken one is skipped rather than
    # returned. Order is unchanged in spirit: PATH first, then known installs.
    rejected: List[str] = []
    seen = set()
    candidates = _path_candidates(name)
    candidates += [os.path.join(d, _exe(name)) for d in _known_dirs()]
    for candidate in candidates:
        key = os.path.normcase(os.path.normpath(candidate))
        if key in seen or not os.path.isfile(candidate):
            continue
        seen.add(key)
        if _runs(candidate):
            if rejected:
                logger.warning(
                    "[VideoStudio] %s at %s does not run (skipped); using %s",
                    name, rejected[0], candidate,
                )
            return candidate
        rejected.append(candidate)
    if rejected:
        logger.warning(
            "[VideoStudio] found %d copies of %s, none of which run: %s",
            len(rejected), name, ", ".join(rejected[:3]),
        )
    # Last resort: the copy pip pulls in with imageio-ffmpeg. Its file is named
    # ffmpeg-win-x86_64-v7.1.exe, NOT ffmpeg.exe — so it is only ever usable as
    # a full path. Never hand its DIRECTORY to a tool that looks for
    # "ffmpeg.exe" inside (that is exactly how yt-dlp came to report
    # "ffmpeg is not installed" while ffmpeg was sitting right there).
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.isfile(exe):
                return exe
        except Exception:
            pass
    return None


def ensure_on_path() -> Optional[str]:
    """Make ffmpeg discoverable to every child process and library in-process.

    Anything that shells out to a bare "ffmpeg" — the burn-subtitles route, the
    TTS stitcher, yt-dlp's own PATH lookup — depends on the process PATH, which
    a launcher-started server often lacks. Prepending the directory once at
    startup fixes all of them together. Returns the directory added, or None.
    """
    exe = find_ffmpeg()
    if not exe:
        return None
    directory = os.path.dirname(exe)
    # Only useful if the directory really holds a normally-named binary;
    # imageio's oddly-named copy would not satisfy a bare "ffmpeg" lookup.
    if not os.path.isfile(os.path.join(directory, _exe("ffmpeg"))):
        return None
    current = os.environ.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    if any(os.path.normcase(os.path.normpath(p)) == os.path.normcase(os.path.normpath(directory))
           for p in parts):
        return directory
    os.environ["PATH"] = directory + os.pathsep + current
    logger.info(f"[VideoStudio] added {directory} to PATH so ffmpeg is discoverable")
    return directory


def find_ffmpeg() -> Optional[str]:
    return _which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    found = _which("ffprobe")
    if found:
        return found
    # imageio-ffmpeg ships ffmpeg but NO ffprobe, so a box that only has that
    # copy loses probing entirely — and callers degrade quietly (subtitle
    # region detection falls back to sampling under a second of video). Look
    # beside whatever ffmpeg we did find before giving up.
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        beside = os.path.join(os.path.dirname(ffmpeg), _exe("ffprobe"))
        if os.path.isfile(beside):
            return beside
    return None


def require_ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError(
            "ffmpeg not found. Install it from https://ffmpeg.org and put its 'bin' "
            "folder on PATH, then restart TubeCLI — or add 'ffmpeg_path' to "
            "data/global_settings.json."
        )
    return exe


def run(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_NO_WINDOW,
    )


def probe_size(video_path: str) -> Tuple[int, int]:
    """(width, height), or (0, 0) when it cannot be read."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return (0, 0)
    try:
        r = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=s=x:p=0", video_path], timeout=30)
        w, h = r.stdout.strip().split("x")[:2]
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def media_duration(path: str) -> float:
    """Duration in seconds, 0.0 when unknown."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return 0.0
    try:
        r = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path], timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0
