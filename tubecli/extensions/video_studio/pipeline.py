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
import re
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

        # A step is only "optional" in a full reup, where partial output is
        # still useful. When the caller asked for exactly this job, its failure
        # IS the outcome — reporting "✅ finished" over it is a lie.
        required = sid in (options.get("required_steps") or ())

        say(sid, "running", label)
        try:
            handler = globals()[f"_step_{sid}"]
            handler(state, options)
        except Exception as e:
            say(sid, "error", str(e)[:300])
            if optional and not required:
                notes.append(f"- **{label}** failed: {e}")
                continue
            raise
        say(sid, "success", "")

    # Someone who asked for subtitles wants the SUBTITLES, not a line count.
    # Write them to an .srt they can open, and put the text in the answer.
    subs = state.get("subtitles") or []
    if subs and not state.get("srt_path"):
        try:
            stem = os.path.splitext(state.get("video_path") or "")[0]
            if not stem:
                from tubecli.config import EXTENSIONS_DATA_DIR

                outdir = os.path.join(str(EXTENSIONS_DATA_DIR), "video_studio", "subtitles")
                os.makedirs(outdir, exist_ok=True)
                stem = os.path.join(outdir, _safe_stem(state))
            # Tag the language so a translation never lands on top of the
            # original it came from.
            lang = state.get("subtitle_language") or ""
            if lang and not stem.endswith(f".{lang}"):
                stem = f"{stem}.{lang}"
            state["srt_path"] = _export_srt(subs, f"{stem}.srt")
        except Exception as e:
            logger.warning(f"[VideoStudio] could not write the SRT: {e}")

    # "…and save it as txt": the timestamps go, the words stay.
    if subs and options.get("export_txt"):
        try:
            base = os.path.splitext(state.get("srt_path")
                                    or state.get("video_path") or "subtitles")[0]
            txt_path = f"{base}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(str(s.get("text", "")).strip()
                                  for s in subs if str(s.get("text", "")).strip()))
            state["txt_path"] = txt_path
        except Exception as e:
            logger.warning(f"[VideoStudio] could not write the TXT: {e}")

    lines = [f"## ✅ {options.get('job_label') or 'Reup pipeline'} finished", ""]
    for key, label in (("video_path", "Downloaded"), ("clean_path", "Original subs covered"),
                       ("dubbed_path", "Dubbed"), ("final_path", "Final video"),
                       ("srt_path", "Subtitle file"), ("txt_path", "Plain text")):
        if state.get(key):
            lines.append(f"- **{label}**: `{state[key]}`")
    if subs:
        origin = state.get("subtitle_source") or ""
        detail = f"{len(subs)} lines"
        if state.get("subtitle_language"):
            detail += f" · {state['subtitle_language']}"
        if origin:
            detail += f" · {origin}"
            if state.get("subtitle_auto"):
                detail += " (auto-generated)"
        lines.append(f"- **Subtitles**: {detail}")
        lines += ["", _subtitle_preview(subs)]
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


PREVIEW_LINES = 40
PREVIEW_CHARS = 3000


def _safe_stem(state: Dict) -> str:
    """A filename for subtitles pulled without ever downloading the video."""
    source = state.get("url") or ""
    # A local source is already a real filename — sanitising the whole PATH
    # turned "…\Vật Lý Sau 2,500 Năm.srt" into
    # "C_tubecreate-vue_tubecli_data_extensions_data_video_studio_s".
    if source and os.path.isfile(source):
        return os.path.splitext(os.path.basename(source))[0][:60]

    base = state.get("title") or source or "subtitles"
    base = re.sub(r"^https?://", "", str(base))
    base = re.sub(r'[\\/:*?"<>|]+', "_", base).strip("_. ")
    return (base or "subtitles")[:60]


def _ts(seconds) -> str:
    try:
        s = float(seconds or 0)
    except (TypeError, ValueError):
        s = 0.0
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def _subtitle_preview(subs: List[Dict]) -> str:
    """The actual transcript, timestamped and trimmed to a readable size.

    Reporting only "176 lines" told the user nothing about what was in the
    video — the point of extracting subtitles is to read them.
    """
    out, total = [], 0
    for s in subs[:PREVIEW_LINES]:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        line = f"`{_ts(s.get('start'))}`  {text}"
        total += len(line)
        if total > PREVIEW_CHARS:
            break
        out.append(line)
    shown = len(out)
    body = "\n".join(out)
    if shown < len(subs):
        body += f"\n\n_…{len(subs) - shown} more lines — the full text is in the .srt above._"
    return body


def _try_caption_track(state: Dict, options: Dict) -> bool:
    """Fetch the platform's own caption track. True when it produced lines.

    YouTube (and most sites yt-dlp knows) publish subtitles that can be pulled
    straight from the page — downloading the video and running Whisper over it,
    as this pipeline used to do unconditionally, is minutes of CPU and an API
    bill for something already available as text.
    """
    langs = options.get("caption_languages")
    if isinstance(langs, str):
        langs = [langs]
    if not langs and options.get("source_language") not in (None, "", "auto"):
        langs = [options["source_language"]]
    try:
        data = _post("/api/v1/subtitle/extract/youtube",
                     {"url": state["url"], "languages": langs}, timeout=180)
    except Exception as e:
        logger.info(f"[VideoStudio] no caption track for {state['url']}: {e}")
        return False

    subs = data.get("subtitles") or []
    if not subs:
        return False
    state["subtitles"] = subs
    state["subtitle_count"] = len(subs)
    state["subtitle_source"] = data.get("engine") or "captions"
    state["subtitle_language"] = data.get("language") or ""
    state["subtitle_auto"] = bool(data.get("is_auto_generated"))
    if data.get("title"):
        state.setdefault("title", data["title"])
    return True


def _step_subtitle(state: Dict, options: Dict):
    # Cheapest route first: most platforms already publish a caption track, so
    # asking for it costs one request — no multi-hundred-MB download, no
    # Whisper/Gemini pass, no API spend. Only fall through to transcription
    # when the video genuinely has no captions.
    if state.get("subtitles"):
        return                      # supplied by the caller (an .srt input)
    if not options.get("force_transcribe") and state.get("url"):
        if _try_caption_track(state, options):
            return

    if not state.get("video_path"):
        # Transcription needs the media. Fetch it now rather than up front, so
        # a video that already has captions never gets downloaded at all.
        if not state.get("url"):
            raise RuntimeError("Nothing to transcribe: no captions, no media file.")
        say = state.get("_report")
        if say:
            try:
                say("download", "running", "no captions — downloading to transcribe",
                    "Download", 0)
            except Exception:
                pass
        _step_download(state, options)
        if say:
            try:
                say("download", "success", "", "Download", 100)
            except Exception:
                pass

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


def _translate_via_brain(subs: List[Dict], target: str, state: Dict) -> List[Dict]:
    """Translate with whatever LLM the user has configured.

    /api/v1/subtitle/translate is hard-wired to Gemini and 400s with "No Gemini
    API key available" — even when the user has DeepSeek, OpenRouter or a local
    model set up. AgentBrain already resolves keys and fails over between
    providers, so route through it instead of demanding one vendor.
    """
    import json as _json

    from tubecli.core.brain import AgentBrain

    # Use the Translator specialist when it exists: it carries the model chosen
    # for translation work and the house style (keep line count, never
    # translate names/paths/code). Falling back to an empty agent keeps this
    # working on installs that have no specialists.
    agent: Dict[str, Any] = {"model": "", "cloud_api_keys": {}}
    house_style = ""
    try:
        from tubecli.core.specialists import get_specialist_for_intent

        spec = get_specialist_for_intent("translate")
        if spec:
            agent = spec if isinstance(spec, dict) else spec.to_dict()
            house_style = (agent.get("system_prompt") or "").strip()
    except Exception as e:
        logger.debug(f"[VideoStudio] no translator specialist: {e}")

    if not agent.get("model"):
        # A specialist with no model of its own would fall through to
        # _call_llm's "qwen:latest" default — an Ollama model most installs do
        # not have. Borrow the orchestrator's instead, which is configured.
        try:
            from tubecli.core.agent import agent_manager

            for a in agent_manager.get_all():
                if (getattr(a, "role", "") or "") == "orchestrator" and getattr(a, "model", ""):
                    agent = {**agent, "model": a.model, "provider": getattr(a, "provider", "")}
                    break
        except Exception:
            pass

    out: List[Dict] = []
    batch = 40
    total = max(1, len(subs))
    for i in range(0, len(subs), batch):
        if state.get("_is_cancelled") and state["_is_cancelled"]():
            raise RuntimeError("Cancelled by the user.")
        chunk = subs[i:i + batch]
        numbered = "\n".join(f"{n + 1}. {s.get('text', '')}" for n, s in enumerate(chunk))
        system = (house_style + "\n\n") if house_style else ""
        system += (
            "Reply with ONLY a JSON array of translated strings, exactly "
            f"{len(chunk)} of them, in the same order as the input. "
            "No prose, no numbering, no code fences."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content":
                f"Translate these {len(chunk)} subtitle lines to {target}:\n\n{numbered}"},
        ]
        raw = AgentBrain._call_llm(agent, messages, temperature=0.1) or ""
        texts = None
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                parsed = _json.loads(m.group(0))
                if isinstance(parsed, list):
                    texts = [str(x) for x in parsed]
            except Exception:
                texts = None
        for n, s in enumerate(chunk):
            new = dict(s)
            if texts and n < len(texts) and texts[n].strip():
                new["text"] = texts[n].strip()
            out.append(new)          # a failed batch keeps the original line
        if state.get("_report"):
            done = min(i + batch, len(subs))
            try:
                state["_report"]("translate", "running", f"{done}/{len(subs)}",
                                 "Translate", done * 100.0 / total)
            except Exception:
                pass
    return out


def _step_translate(state: Dict, options: Dict):
    if not state.get("subtitles"):
        raise RuntimeError("Nothing to translate — the subtitle step produced no lines.")
    target = options.get("target_language", "vi")
    subs = []
    try:
        data = _post("/api/v1/subtitle/translate", {
            "subtitles": state["subtitles"], "target_language": target,
        }, timeout=1800)
        subs = data.get("subtitles") or data.get("result") or []
    except Exception as e:
        # The extension's endpoint is Gemini-only. Rather than fail on a
        # missing key for one specific vendor, fall back to the user's own
        # configured model.
        logger.info(f"[VideoStudio] subtitle/translate unusable ({e}); using the agent's LLM")
        subs = _translate_via_brain(state["subtitles"], target, state)

    if not subs:
        raise RuntimeError("The translation produced no lines.")
    if subs == state["subtitles"]:
        raise RuntimeError(
            "Nothing was translated — no usable model answered. Add an API key "
            "in Cloud API Keys, or run a local model."
        )
    state["subtitles"] = subs
    state["subtitle_language"] = target
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
