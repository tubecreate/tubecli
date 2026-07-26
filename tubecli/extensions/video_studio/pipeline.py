"""
Reup pipeline — download → subtitles → translate → cover original subs → dub → burn.

Modelled on ReupDouyin's core/pipeline.py, but each run is a CODEX TASK rather
than an inline call:

  * it survives a server restart, with a per-step timeline on the board
  * it waits for human approval before spending API credits and disk
  * it can be cancelled between steps, and retried

Steps that need an extension which is not installed are skipped with a clear
note rather than failing the whole run, and the task result tells the user what
to install to get them.
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from tubecli.extensions.video_studio.capabilities import check_job, guidance_for

logger = logging.getLogger("VideoStudio")

# step id, label, the capability job it needs, whether it can be skipped
STEPS = [
    ("download", "Download the video", "download", False),
    ("subtitle", "Extract subtitles", "extract_subtitle", True),
    ("translate", "Translate subtitles", "translate_subtitle", True),
    ("clean", "Cover the original burned-in subtitles", "remove_hardsub", True),
    ("dub", "Dub with text-to-speech", "tts", True),
    ("burn", "Burn the new subtitles in", "burn_subtitle", True),
]


def _base_url() -> str:
    from tubecli.config import get_api_port

    return f"http://127.0.0.1:{get_api_port()}"


def _post(path: str, payload: Dict, timeout: int = 900) -> Dict:
    import requests

    r = requests.post(_base_url() + path, json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"{path} → HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:2000]}


def _poll_task(status_path: str, task_id: str, timeout_sec: int,
               state: Optional[Dict] = None, step: str = "") -> Dict:
    """Wait for a background task (subtitle extract/burn, TTS) to finish.

    Those endpoints return {"task_id": …} immediately and stash the real result
    behind a status route — calling them like synchronous APIs, as this file
    once did, only ever yields the launch message. Polls once a second, mirrors
    percentage into the codex step when the task reports progress, and returns
    the task's `result` dict on success.
    """
    import time

    import requests

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if state and state.get("_is_cancelled") and state["_is_cancelled"]():
            raise RuntimeError("Cancelled by the user.")
        r = requests.get(f"{_base_url()}{status_path}/{task_id}", timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"{status_path}/{task_id} → HTTP {r.status_code}")
        data = r.json()
        status = data.get("status", "")
        if state and state.get("_report") and step:
            total = data.get("total") or data.get("total_segments") or 0
            done = data.get("progress") or data.get("current_segment") or 0
            if total:
                try:
                    state["_report"](step, "running", f"{done}/{total}",
                                     progress=min(99.0, done * 100.0 / total))
                except TypeError:
                    pass  # report() without progress support
                except Exception:
                    pass
        if status in ("success", "completed"):
            return data.get("result") or data
        if status == "error":
            msg = (data.get("result") or {}).get("message") or "background task failed"
            raise RuntimeError(msg)
        time.sleep(1)
    raise RuntimeError(f"Timed out after {timeout_sec}s waiting for {status_path}/{task_id}")


_SRT_TIME = None  # compiled lazily


def _parse_srt_file(path: str) -> List[Dict]:
    """Read an SRT/VTT file into the {'start': s, 'end': s, 'text': …} dicts
    the extractor's own endpoints use (see subtitle_routes._to_srt)."""
    import re as _re

    global _SRT_TIME
    if _SRT_TIME is None:
        _SRT_TIME = _re.compile(
            r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
            r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")

    def _sec(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0

    subs: List[Dict] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()
    for block in _re.split(r"\n\s*\n", content):
        m = _SRT_TIME.search(block)
        if not m:
            continue
        text_lines = []
        for line in block.splitlines():
            line = line.strip()
            if not line or line.isdigit() or "-->" in line or line.upper() == "WEBVTT":
                continue
            text_lines.append(line)
        if text_lines:
            subs.append({
                "start": _sec(m.group(1), m.group(2), m.group(3), m.group(4)),
                "end": _sec(m.group(5), m.group(6), m.group(7), m.group(8)),
                "text": " ".join(text_lines),
            })
    if not subs:
        raise RuntimeError(f"No subtitle lines could be read from {path}")
    return subs


def _export_srt(subtitles: List[Dict], output_path: str) -> str:
    """Write subtitle dicts to an SRT file via the extractor's own exporter,
    so the timestamp format always matches what the extractor produced."""
    data = _post("/api/v1/subtitle/export", {
        "subtitles": subtitles, "format": "srt", "output_path": output_path,
    }, timeout=120)
    path = data.get("path") or output_path
    if not os.path.isfile(path):
        raise RuntimeError("SRT export produced no file.")
    return path


def _mux_audio(video_path: str, audio_path: str, mix_original: bool) -> str:
    """Put the generated voice track into the video (replace or mix)."""
    from tubecli.extensions.video_studio.ffmpeg_utils import require_ffmpeg, run

    ffmpeg = require_ffmpeg()
    base, _ = os.path.splitext(video_path)
    out = f"{base}_dubbed.mp4"
    if mix_original:
        cmd = [ffmpeg, "-y", "-i", video_path, "-i", audio_path,
               "-filter_complex",
               "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[aout]",
               "-map", "0:v", "-map", "[aout]", "-c:v", "copy", out]
    else:
        cmd = [ffmpeg, "-y", "-i", video_path, "-i", audio_path,
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-shortest", out]
    proc = run(cmd, timeout=1800)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(f"ffmpeg mux failed: {(proc.stderr or b'')[-300:]}")
    return out


def plan(options: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Which steps will actually run, given the options and what is installed."""
    out = []
    for sid, label, job, optional in STEPS:
        wanted = bool(options.get(sid, True))
        cap = check_job(job)
        out.append({
            "step": sid,
            "label": label,
            "job": job,
            "enabled": wanted,
            "available": cap["ready"],
            "will_run": wanted and cap["ready"],
            "blocked_by": cap["missing"] + cap["disabled"],
            "optional": optional,
        })
    return out


def describe_plan(options: Dict[str, Any]) -> str:
    rows = plan(options)
    lines = ["**Reup pipeline plan**", ""]
    for r in rows:
        if r["will_run"]:
            mark = "✅"
            note = ""
        elif not r["enabled"]:
            mark = "⏭"
            note = " — turned off"
        else:
            mark = "⚠️"
            note = f" — needs {', '.join(r['blocked_by'])}"
        lines.append(f"{mark} {r['label']}{note}")
    blocked = [r for r in rows if r["enabled"] and not r["available"]]
    if blocked:
        lines += ["", guidance_for([r["job"] for r in blocked]) or ""]
    return "\n".join(lines)


def run_reup(url: str, options: Optional[Dict[str, Any]] = None,
             report: Optional[Callable[..., None]] = None,
             is_cancelled: Optional[Callable[[], bool]] = None) -> str:
    """Execute the pipeline. Blocking — the codex worker calls this on a thread.

    `report(step, status, message)` mirrors the codex step vocabulary
    (running | success | error | skipped).
    """
    options = options or {}

    def say(step: str, status: str, message: str = ""):
        if report:
            try:
                report(step, status, message)
            except Exception:
                pass

    def cancelled() -> bool:
        return bool(is_cancelled and is_cancelled())

    # Steps that stream progress (download, encode) need the callbacks; carry
    # them on the state so each step keeps a uniform (state, options) signature.
    state: Dict[str, Any] = {"url": url, "_report": report, "_is_cancelled": is_cancelled}
    notes: List[str] = []
    skipped_jobs: List[str] = []

    # The single-job wrappers reuse this engine for LOCAL sources too:
    # a video file already on disk skips the download, and an .srt file
    # replaces the extraction step with its own lines.
    if os.path.isfile(url):
        if url.lower().endswith((".srt", ".vtt")):
            state["subtitles"] = _parse_srt_file(url)
            state["srt_path"] = url
            state["subtitle_count"] = len(state["subtitles"])
            options = {**options, "download": False, "subtitle": False}
        else:
            state["video_path"] = url
            options = {**options, "download": False}

    for sid, label, job, optional in STEPS:
        if cancelled():
            raise RuntimeError("Cancelled by the user.")
        if not options.get(sid, True):
            say(sid, "skipped", "turned off")
            continue

        cap = check_job(job)
        if not cap["ready"]:
            gaps = ", ".join(cap["missing"] + cap["disabled"])
            if optional:
                say(sid, "skipped", f"needs {gaps}")
                notes.append(f"- **{label}** skipped — needs `{gaps}`")
                skipped_jobs.append(job)
                continue
            say(sid, "error", f"needs {gaps}")
            raise RuntimeError(
                (guidance_for([job]) or f"{label} needs {gaps}.")
            )

        say(sid, "running", label)
        try:
            handler = globals()[f"_step_{sid}"]
            handler(state, options)
        except Exception as e:
            say(sid, "error", str(e)[:300])
            if optional:
                notes.append(f"- **{label}** failed: {e}")
                continue
            raise
        say(sid, "success", "")

    lines = ["## ✅ Reup pipeline finished", ""]
    for key, label in (("video_path", "Downloaded"), ("clean_path", "Original subs covered"),
                       ("dubbed_path", "Dubbed"), ("final_path", "Final video"),
                       ("srt_path", "Subtitles")):
        if state.get(key):
            lines.append(f"- **{label}**: `{state[key]}`")
    if state.get("subtitle_count"):
        lines.append(f"- **Subtitle lines**: {state['subtitle_count']}")
    if notes:
        lines += ["", "### Steps that did not run", ""] + notes
        extra = guidance_for(skipped_jobs)
        if extra:
            lines += ["", extra]
    return "\n".join(lines)


# ── Individual steps ─────────────────────────────────────────────────

def _step_download(state: Dict, options: Dict):
    # Async + polling, never the synchronous endpoint: that one blocks for the
    # whole download and every caller times out long before it returns.
    from tubecli.extensions.video_studio.jobs import download_with_progress

    result = download_with_progress(
        state["url"], state.get("_report"), state.get("_is_cancelled"), step="download"
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "The download failed.")
    path = result.get("path") or ""
    if not path or not os.path.exists(str(path)):
        raise RuntimeError(f"The downloader returned an unusable path: {path!r}")
    state["video_path"] = str(path)


def _step_subtitle(state: Dict, options: Dict):
    # The extractor wants `file_path` (not video_path) and runs in the
    # BACKGROUND: the POST returns {"task_id"} immediately and the subtitles
    # only exist behind /subtitle/status/{id}. The old synchronous call with
    # the wrong key 422'd on every single run.
    lang = options.get("source_language") or None
    if isinstance(lang, str) and lang.strip().lower() in ("", "auto"):
        lang = None
    launch = _post("/api/v1/subtitle/extract", {
        "file_path": state["video_path"],
        "engine": options.get("subtitle_engine", "gemini"),
        "language": lang,
    }, timeout=120)
    task_id = launch.get("task_id")
    if not task_id:
        raise RuntimeError(f"Extractor did not return a task id: {str(launch)[:200]}")
    result = _poll_task("/api/v1/subtitle/status", task_id, 1800,
                        state=state, step="subtitle")
    subs = result.get("subtitles") or result.get("segments") or []
    if not subs:
        raise RuntimeError(result.get("message") or "No subtitles were extracted.")
    state["subtitles"] = subs
    state["subtitle_count"] = len(subs)
    if result.get("srt_path"):
        state["srt_path"] = result["srt_path"]


def _step_translate(state: Dict, options: Dict):
    if not state.get("subtitles"):
        raise RuntimeError("Nothing to translate — the subtitle step produced no lines.")
    data = _post("/api/v1/subtitle/translate", {
        "subtitles": state["subtitles"],
        "target_language": options.get("target_language", "vi"),
    }, timeout=1800)
    subs = data.get("subtitles") or data.get("result") or []
    if subs:
        state["subtitles"] = subs
        # Any SRT written before this point holds the ORIGINAL language —
        # drop the pointer so dub/burn re-export from the translated lines.
        state.pop("srt_path", None)


def _step_clean(state: Dict, options: Dict):
    data = _post("/api/v1/video-studio/hardsub/remove", {
        "video_path": state["video_path"],
        "mode": options.get("cover_mode", "delogo"),
        "sample": int(options.get("sample_frames", 6)),
    }, timeout=2400)
    if data.get("found") and data.get("output_path"):
        state["clean_path"] = data["output_path"]
        state["video_path"] = data["output_path"]
    else:
        raise RuntimeError(data.get("message") or "No burned-in subtitles were found.")


def _step_dub(state: Dict, options: Dict):
    if not state.get("subtitles"):
        raise RuntimeError("Nothing to dub — no subtitle lines.")
    # synthesize-srt takes SRT TEXT (srt_content), runs in the background, and
    # produces a bare voice track — it never touches the video. So: export the
    # (translated) lines to SRT, feed the text in, poll for the mp3, then mux
    # it into the video ourselves.
    base, _ = os.path.splitext(state["video_path"])
    srt_path = _export_srt(state["subtitles"], f"{base}_dub.srt")
    state["srt_path"] = srt_path  # current-language SRT; burn reuses it
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read()
    payload = {"srt_content": srt_content}
    if options.get("voice"):
        payload["voice"] = options["voice"]
    launch = _post("/api/v1/tts/synthesize-srt", payload, timeout=120)
    task_id = launch.get("task_id")
    if not task_id:
        raise RuntimeError(f"TTS did not return a task id: {str(launch)[:200]}")
    result = _poll_task("/api/v1/tts/status", task_id, 2400, state=state, step="dub")
    audio = result.get("output") or result.get("output_path") or result.get("path")
    if not audio or not os.path.isfile(audio):
        raise RuntimeError(result.get("message") or "TTS produced no audio file.")
    out = _mux_audio(state["video_path"], audio,
                     bool(options.get("mix_original", False)))
    if out:
        state["dubbed_path"] = out
        state["video_path"] = out


def _step_burn(state: Dict, options: Dict):
    # BurnRequest wants two FILES on disk (video_path + srt_path) plus flat
    # style fields, and it also runs in the background. The old call sent an
    # inline `subtitles` list and a `style` dict — neither exists in the
    # schema — so it 422'd before ffmpeg ever started.
    subs = state.get("subtitles") or []
    if not subs:
        raise RuntimeError("Nothing to burn — no subtitle lines.")
    base, _ = os.path.splitext(state["video_path"])
    srt_path = state.get("srt_path")
    if not srt_path or not os.path.isfile(srt_path):
        srt_path = _export_srt(subs, f"{base}_burn.srt")
        state["srt_path"] = srt_path
    style = options.get("subtitle_style") or {}
    payload = {"video_path": state["video_path"], "srt_path": srt_path}
    for key in ("font_size", "font_color", "position"):
        if style.get(key):
            payload[key] = style[key]
    launch = _post("/api/v1/subtitle/burn", payload, timeout=120)
    task_id = launch.get("task_id")
    if not task_id:
        raise RuntimeError(f"Burner did not return a task id: {str(launch)[:200]}")
    result = _poll_task("/api/v1/subtitle/status", task_id, 2400,
                        state=state, step="burn")
    out = result.get("output") or result.get("output_path") or result.get("path")
    if not out or not os.path.isfile(out):
        raise RuntimeError(result.get("message") or "Burning produced no file.")
    state["final_path"] = out
    state["video_path"] = out


# ── Codex integration ────────────────────────────────────────────────

def create_codex_task(url: str, options: Optional[Dict] = None,
                      created_by: str = "user", origin: Optional[Dict] = None,
                      job_label: str = "Reup") -> Dict:
    """Queue a reup (or a single-job subset of it) as an approval-gated codex
    task. `job_label` names the board card ("Reup", "Extract subtitles"…)."""
    from tubecli.extensions.codex.manager import codex_manager

    options = options or {}
    goal = (
        f"{job_label} pipeline for {url}\n\n{describe_plan(options)}\n\n"
        f"OPTIONS: {options}"
    )
    task = codex_manager.create_task(
        goal=goal,
        title=f"{job_label}: {os.path.basename(url)[:48] if os.path.isfile(url) else url[:48]}",
        created_by=created_by,
        origin=origin or {},
        assignee_type="agent",
        assignee_name="Video Agent",
    )
    # Remember the machine-readable side so the executor does not re-parse the goal.
    codex_manager.update_task(task["id"])
    codex_manager.append_event(
        task["id"], "log", "Reup pipeline queued",
        actor="video_studio", data={"url": url, "options": options,
                                    "kind": "video_studio.reup"},
    )
    return task
