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
    data = _post("/api/v1/subtitle/extract", {
        "video_path": state["video_path"],
        "engine": options.get("subtitle_engine", "gemini"),
        "language": options.get("source_language", "auto"),
    }, timeout=1800)
    subs = data.get("subtitles") or data.get("segments") or []
    if not subs:
        raise RuntimeError("No subtitles were extracted.")
    state["subtitles"] = subs
    state["subtitle_count"] = len(subs)
    if data.get("srt_path"):
        state["srt_path"] = data["srt_path"]


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
    data = _post("/api/v1/tts/synthesize-srt", {
        "video_path": state["video_path"],
        "subtitles": state["subtitles"],
        "voice": options.get("voice", ""),
        "mix_original": bool(options.get("mix_original", False)),
    }, timeout=2400)
    out = data.get("output_path") or data.get("path")
    if out:
        state["dubbed_path"] = out
        state["video_path"] = out


def _step_burn(state: Dict, options: Dict):
    data = _post("/api/v1/subtitle/burn", {
        "video_path": state["video_path"],
        "subtitles": state.get("subtitles") or [],
        "style": options.get("subtitle_style", {}),
    }, timeout=2400)
    out = data.get("output_path") or data.get("path")
    if out:
        state["final_path"] = out
        state["video_path"] = out


# ── Codex integration ────────────────────────────────────────────────

def create_codex_task(url: str, options: Optional[Dict] = None,
                      created_by: str = "user", origin: Optional[Dict] = None) -> Dict:
    """Queue a reup as an approval-gated codex task."""
    from tubecli.extensions.codex.manager import codex_manager

    options = options or {}
    goal = (
        f"Reup pipeline for {url}\n\n{describe_plan(options)}\n\n"
        f"OPTIONS: {options}"
    )
    task = codex_manager.create_task(
        goal=goal,
        title=f"Reup: {url[:48]}",
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
