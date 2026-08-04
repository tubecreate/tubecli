"""
Long-running video jobs, run in the background with real progress.

Downloading and encoding take minutes, not seconds. The old "Universal Video
Downloader" skill was a workflow whose api_request node POSTs the SYNCHRONOUS
/api/v1/ytdl/download with a 30-second timeout, so every real download died with
"Read timed out (read timeout=30)" and dumped the raw error dict into the chat.

Here the async endpoint is used instead: start the job, then poll its status and
publish the percentage into the codex step, so the board shows a moving bar.
"""
import logging
import re
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("VideoStudio")

# Terminal colour codes from the tools we shell out to. Left in, they reach the
# chat bubble as literal "[0;31mERROR:[0m".
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_error(text: Any) -> str:
    return _ANSI.sub("", str(text or "")).strip()


def _humanise(error: str) -> str:
    """Turn a known, fixable tool failure into something the user can act on."""
    low = error.lower()
    if "ffmpeg" in low and ("not installed" in low or "not found" in low):
        from tubecli.core.bot_i18n import t

        return t("vs.err_ffmpeg_missing")
    return error

POLL_SECONDS = 2.0
DEFAULT_TIMEOUT = 3600      # an hour is plenty for a long video
STALL_TIMEOUT = 300         # give up if the percentage has not moved in 5 minutes


def _base_url() -> str:
    from tubecli.config import get_api_port

    return f"http://127.0.0.1:{get_api_port()}"


def _fmt_size(n) -> str:
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _fmt_speed(n) -> str:
    s = _fmt_size(n)
    return f"{s}/s" if s else ""


def _resolve_download_path(name: str) -> str:
    """Turn the downloader's bare filename into a full path.

    /api/v1/ytdl/status returns only `filename`, so every later step
    (os.path.exists, ffmpeg) would fail on it. The extension writes into
    <TUBECLI_DATA_DIR or ./data>/ytdl_downloads.
    """
    import os

    if not name:
        return ""
    if os.path.isabs(name) and os.path.exists(name):
        return name

    base = os.path.basename(name.replace("\\", "/"))
    # Canonical location first. The three data/ytdl_downloads spellings below
    # only ever resolved through the junction the boot migration leaves behind;
    # they stay as a fallback for an install whose migration has not run yet,
    # and go away with the shim.
    candidates = []
    try:
        from tubecli.config import ext_data_path

        candidates.append(str(ext_data_path("video_downloader", "ytdl_downloads")))
    except Exception:
        pass
    env_dir = os.environ.get("TUBECLI_DATA_DIR")
    if env_dir:
        candidates.append(os.path.join(env_dir, "extensions_data", "video_downloader", "ytdl_downloads"))
        candidates.append(os.path.join(env_dir, "ytdl_downloads"))
    try:
        from tubecli.config import DATA_DIR

        candidates.append(os.path.join(str(DATA_DIR), "ytdl_downloads"))
    except Exception:
        pass
    candidates.append(os.path.join("data", "ytdl_downloads"))

    for d in candidates:
        full = os.path.join(d, base)
        if os.path.exists(full):
            return os.path.abspath(full)
    logger.warning(f"[VideoStudio] could not locate {base!r} in {candidates}")
    return name


def download_with_progress(
    url: str,
    report: Optional[Callable[..., None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    step: str = "download",
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Start an async download and follow it to completion.

    Returns {ok, path, filename, error}. `report(step, status, message,
    progress=pct)` is called as the percentage moves.
    """
    import requests

    def say(status: str, message: str = "", progress=None):
        if report:
            try:
                report(step, status, message, "Download", progress)
            except TypeError:
                # A caller with the older 4-argument signature.
                try:
                    report(step, status, message, "Download")
                except Exception:
                    pass
            except Exception:
                pass

    say("running", "starting…", 0)

    try:
        r = requests.post(f"{_base_url()}/api/v1/ytdl/download_async",
                          json={"url": url}, timeout=60)
    except Exception as e:
        return {"ok": False, "error": f"Could not start the download: {e}"}
    if r.status_code >= 400:
        return {"ok": False,
                "error": f"Downloader returned HTTP {r.status_code}: {r.text[:300]}"}

    try:
        payload = r.json()
    except Exception:
        return {"ok": False, "error": f"Downloader returned non-JSON: {r.text[:200]}"}

    task_id = (payload.get("task_id") or payload.get("id")
               or (payload.get("data") or {}).get("task_id"))
    if not task_id:
        # Some builds answer synchronously — accept that too.
        path = payload.get("path") or payload.get("filename")
        if path:
            say("success", "done", 100)
            return {"ok": True, "path": path, "filename": path}
        return {"ok": False, "error": f"No task_id in the response: {payload}"}

    started = time.time()
    last_pct, last_move = -1.0, time.time()

    while True:
        if is_cancelled and is_cancelled():
            return {"ok": False, "error": "Cancelled by the user."}
        if time.time() - started > timeout:
            return {"ok": False, "error": f"Download timed out after {timeout}s."}

        time.sleep(POLL_SECONDS)
        try:
            s = requests.get(f"{_base_url()}/api/v1/ytdl/status/{task_id}", timeout=30)
            data = (s.json() or {}).get("data") or {}
        except Exception as e:
            logger.debug(f"[VideoStudio] status poll failed: {e}")
            continue

        status = (data.get("status") or "").lower()
        pct = data.get("progress")
        try:
            pct = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct = None

        if pct is not None and pct != last_pct:
            last_pct, last_move = pct, time.time()
            bits = [f"{pct:.0f}%"]
            if data.get("total_size"):
                bits.append(f"{_fmt_size(data.get('downloaded'))} / "
                            f"{_fmt_size(data.get('total_size'))}")
            if data.get("speed"):
                bits.append(_fmt_speed(data.get("speed")))
            say("running", " · ".join(b for b in bits if b), pct)
        elif time.time() - last_move > STALL_TIMEOUT:
            return {"ok": False,
                    "error": f"The download stalled for {STALL_TIMEOUT}s with no progress."}

        if status in ("done", "finished", "completed", "success"):
            raw = data.get("filename") or data.get("path") or ""
            path = _resolve_download_path(raw)
            name = raw.replace("\\", "/").split("/")[-1]
            say("success", name or "done", 100)
            return {"ok": True, "path": path, "filename": name}
        if status in ("error", "failed"):
            err = _humanise(_clean_error(data.get("error"))
                            or "the downloader reported a failure")
            say("error", err[:200])
            return {"ok": False, "error": err}


def run_download_task(url: str, options: Optional[Dict] = None,
                      report: Optional[Callable[..., None]] = None,
                      is_cancelled: Optional[Callable[[], bool]] = None) -> str:
    """Codex entry point for a standalone download."""
    from tubecli.extensions.video_studio.capabilities import guidance_for

    gap = guidance_for(["download"])
    if gap:
        raise RuntimeError(gap)

    result = download_with_progress(url, report, is_cancelled)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "The download failed.")
    path = result.get("path") or ""
    name = path.replace("\\", "/").split("/")[-1]
    from tubecli.core.bot_i18n import t

    return (f"{t('vs.download_finished')}\n\n"
            f"- **{t('vs.label_file')}**: `{name}`\n"
            f"- **{t('vs.label_path')}**: `{path}`\n\n"
            f"{t('vs.label_source')}: {url}")


def create_download_task(url: str, created_by: str = "user",
                         origin: Optional[Dict] = None) -> Dict:
    """Queue a download as a codex task so it runs in the background."""
    from tubecli.extensions.codex.manager import codex_manager

    task = codex_manager.create_task(
        goal=f"Download the video: {url}",
        title=f"Download: {url[:48]}",
        created_by=created_by,
        origin=origin or {},
        assignee_type="agent",
        assignee_name="Video Agent",
    )
    codex_manager.append_event(
        task["id"], "log", "Download queued", actor="video_studio",
        data={"url": url, "kind": "video_studio.download"},
    )
    return task
