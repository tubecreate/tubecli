"""
ffmpeg/ffprobe helpers for video_studio.

Kept separate so the engines never shell out ad hoc, and so a missing ffmpeg
produces one clear message instead of a raw OSError deep in a filter chain.
"""
import glob
import logging
import os
import re
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
        managed = managed_dir()
        if managed:
            dirs.append(managed)             # bộ cài Windows + tự tải (ensure_installed) đặt ở đây
        dirs += [
            r"C:\ffmpeg\bin",
            os.path.join(program_files, "ffmpeg", "bin"),
            os.path.join(local, "Microsoft", "WinGet", "Links"),
        ]
        # winget cài gói "portable" (Gyan.FFmpeg) vào Packages\<gói>\<bản>\bin, và
        # chỉ tạo lối tắt ở Links khi được phép tạo symlink — không thì nó thêm
        # thẳng thư mục bin vào PATH NGƯỜI DÙNG, mà máy chủ bật từ Connect không
        # thấy PATH mới đó (máy PC của user 11/9/2026: `where ffmpeg` →
        # …\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-9.0.1-full_build\bin).
        if local:
            pk = os.path.join(local, "Microsoft", "WinGet", "Packages")
            dirs += sorted(glob.glob(os.path.join(pk, "*FFmpeg*", "*", "bin")), reverse=True)
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


# name -> resolved path. Chỉ nhớ khi THẤY: nhớ cả "không có" thì cài ffmpeg xong
# vẫn phải khởi động lại TubeCLI mới hết báo thiếu — bấm Retry không ăn thua (máy
# PC của user, 11/9/2026). Chưa thấy thì dò lại: vài phép isfile, rẻ.
_RESOLVED: dict = {}


def _which(name: str) -> Optional[str]:
    if _RESOLVED.get(name):
        return _RESOLVED[name]
    result = _which_uncached(name)
    if result:
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


# ── Tự tải ffmpeg + ffprobe khi máy thiếu (Windows) ──────────────────────────
# install.ps1 cũ không hề cài ffmpeg; VPS Windows mới chạy TTS / video là «[WinError 2] The system cannot find the
# file specified» (19/11/2026). Lõi tự vá: lúc khởi động (video_studio.on_enable) mà thiếu ffmpeg HOẶC ffprobe ⇒
# tải bản essentials (~90 MB, một lần) về CÙNG thư mục bộ cài dùng — %LOCALAPPDATA%\Programs\ffmpeg\bin — chỉ
# giữ ffmpeg.exe + ffprobe.exe, kiểm chạy được rồi đưa lên PATH của tiến trình. Hỏng thì 6 giờ sau mới thử lại.
FFMPEG_DOWNLOADS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
)
RETRY_AFTER_SEC = 6 * 3600
INSTALL_STATE = {"status": "idle", "error": "", "dir": "", "at": 0.0}
_INSTALL_LOCK = __import__("threading").Lock()


def managed_dir() -> Optional[str]:
    if os.name != "nt":
        return None
    local = os.environ.get("LOCALAPPDATA") or ""
    return os.path.join(local, "Programs", "ffmpeg", "bin") if local else None


def _marker_file() -> Optional[str]:
    d = managed_dir()
    return os.path.join(os.path.dirname(d), ".tubecli-download.json") if d else None


def needs_install() -> bool:
    """Thiếu ffmpeg hoặc ffprobe (bản ffmpeg của imageio-ffmpeg KHÔNG kèm ffprobe ⇒ vẫn tính là thiếu)."""
    return not (find_ffmpeg() and find_ffprobe())


def _download(url: str, dest: str, timeout: float = 60) -> None:
    import shutil
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "TubeCLI-ffmpeg-setup"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)


def install_ffmpeg(urls=FFMPEG_DOWNLOADS, force: bool = False) -> dict:
    """ĐỒNG BỘ (chạy ở luồng nền). Trả INSTALL_STATE. Không làm gì nếu đã đủ ffmpeg + ffprobe."""
    import json
    import tempfile
    import time
    import zipfile

    target = managed_dir()
    if not target:
        INSTALL_STATE.update(status="unsupported", error="automatic download is Windows-only")
        return INSTALL_STATE
    with _INSTALL_LOCK:
        if not needs_install():
            INSTALL_STATE.update(status="ok", error="")
            return INSTALL_STATE
        marker = _marker_file()
        if not force and marker and os.path.isfile(marker):
            try:
                last = json.load(open(marker, encoding="utf-8"))
                if last.get("ok") is False and time.time() - float(last.get("at") or 0) < RETRY_AFTER_SEC:
                    INSTALL_STATE.update(status="failed", error=last.get("error", ""))
                    return INSTALL_STATE
            except Exception:
                pass
        INSTALL_STATE.update(status="downloading", error="", at=time.time())
        errors = []
        for url in urls:
            tmp = tempfile.mkdtemp(prefix="tubecli-ffmpeg-")
            zpath = os.path.join(tmp, "ffmpeg.zip")
            try:
                logger.info("[VideoStudio] ffmpeg/ffprobe missing — downloading %s", url)
                _download(url, zpath)
                staged = os.path.join(tmp, "bin")
                os.makedirs(staged, exist_ok=True)
                got = set()
                with zipfile.ZipFile(zpath) as z:
                    for member in z.namelist():
                        base = member.replace("\\", "/").rsplit("/", 1)[-1].lower()
                        if base in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in "/" + member.replace("\\", "/"):
                            with z.open(member) as src, open(os.path.join(staged, base), "wb") as out:
                                out.write(src.read())
                            got.add(base)
                if got != {"ffmpeg.exe", "ffprobe.exe"}:
                    raise RuntimeError(f"the zip has no bin/ffmpeg.exe + bin/ffprobe.exe ({sorted(got)})")
                for name in ("ffmpeg.exe", "ffprobe.exe"):
                    if not _runs(os.path.join(staged, name)):
                        raise RuntimeError(f"downloaded {name} does not run")
                os.makedirs(target, exist_ok=True)
                for name in ("ffmpeg.exe", "ffprobe.exe"):
                    os.replace(os.path.join(staged, name), os.path.join(target, name))
                _RESOLVED.clear()
                ensure_on_path()
                INSTALL_STATE.update(status="ok", error="", dir=target)
                logger.info("[VideoStudio] ffmpeg + ffprobe installed to %s", target)
                if marker:
                    json.dump({"ok": True, "at": time.time(), "url": url}, open(marker, "w", encoding="utf-8"))
                return INSTALL_STATE
            except Exception as e:  # noqa: BLE001
                errors.append(f"{url}: {e}")
                logger.warning("[VideoStudio] ffmpeg download from %s failed: %s", url, e)
            finally:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
        INSTALL_STATE.update(status="failed", error="; ".join(errors)[:500])
        if marker:
            try:
                os.makedirs(os.path.dirname(marker), exist_ok=True)
                json.dump({"ok": False, "at": time.time(), "error": INSTALL_STATE["error"]},
                          open(marker, "w", encoding="utf-8"))
            except Exception:
                pass
        return INSTALL_STATE


def ensure_installed(background: bool = True) -> dict:
    """Gọi lúc khởi động: thiếu ffmpeg / ffprobe trên Windows ⇒ tải ở luồng nền (không chặn server)."""
    if os.name != "nt" or not needs_install():
        return INSTALL_STATE
    if not background:
        return install_ffmpeg()
    if INSTALL_STATE["status"] != "downloading":
        import threading
        threading.Thread(target=install_ffmpeg, name="ffmpeg-setup", daemon=True).start()
    return INSTALL_STATE


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

    def same(p: str) -> bool:
        return (os.path.normcase(os.path.normpath(p.strip().strip('"')))
                == os.path.normcase(os.path.normpath(directory)))

    # "Đã có trên PATH" CHƯA đủ — phải là bản ĐẦU TIÊN mà một lời gọi "ffmpeg"
    # trần gặp. Đo thật 11/9/2026: máy chủ chạy bằng Python miniconda có
    # miniconda3\Library\bin (ffmpeg chết lúc nạp, 0xC0000139) đứng TRƯỚC thư mục
    # bản tốt. Bản cũ thấy thư mục tốt "đã có" nên thoát, rồi Content Studio gọi
    # tên trần và 9/9 shot hỏng với stderr rỗng. Đưa nó lên ĐẦU, bỏ chỗ cũ.
    first = _path_candidates("ffmpeg")[:1]
    if first and same(os.path.dirname(first[0])):
        return directory
    os.environ["PATH"] = os.pathsep.join([directory] + [p for p in parts if not same(p)])
    logger.info(f"[VideoStudio] put {directory} first on PATH so a bare 'ffmpeg' finds a working copy")
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


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_TIME_RE = re.compile(r"time=\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def _hms(m) -> float:
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


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
    """Duration in seconds, 0.0 when unknown.

    ffprobe trước; máy KHÔNG có ffprobe thì hỏi chính ffmpeg. Gói imageio-ffmpeg đóng gói ffmpeg mà không
    có ffprobe, nên trên những máy ấy mọi phép đo đều trả 0 — và bên gọi hiểu nhầm là «file không có
    giọng»: máy 28 (20/9/2026) dựng 59 shot đã thu tiếng thành 59 ảnh tĩnh 5 giây, phụ đề 0 shot, tiêu đề
    kết quả không có dòng thời lượng video.
    """
    if not path or not os.path.isfile(path):
        return 0.0
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            r = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path], timeout=30)
            got = float((r.stdout or "0").strip() or 0)
            if got > 0:
                return got
        except Exception:
            pass
    exe = find_ffmpeg()
    if not exe:
        return 0.0
    try:
        # `ffmpeg -i <file>` in "Duration: HH:MM:SS.xx" ra stderr rồi thoát với mã lỗi — không giải mã
        # nên nhanh như ffprobe.
        r = run([exe, "-hide_banner", "-i", path], timeout=60)
        m = _DUR_RE.search(r.stderr or "")
        if m:
            return round(_hms(m), 3)
        # Định dạng không ghi sẵn Duration: giải mã bỏ đi rồi lấy mốc cuối cùng.
        r = run([exe, "-hide_banner", "-i", path, "-f", "null", "-"], timeout=600)
        ms = _TIME_RE.findall(r.stderr or "")
        if ms:
            h, mm, ss = ms[-1]
            return round(int(h) * 3600 + int(mm) * 60 + float(ss), 3)
    except Exception as e:      # noqa: BLE001
        logger.info("media_duration %s: %s", path, e)
    return 0.0
