"""Bảng XEM TRƯỚC của form «Tạo video từ nội dung» (Codex, 14/11/2026).

User: «thêm button xem trước khi người dùng bấm button thì hiện lên một cái bảng review để họ xem các thông số gồm template,
AI tạo content, AI tạo ảnh, AI tạo voice, thêm load 1 lần check AI có hoạt động hay không, rồi phương thức tạo, dạng ảnh
video, kiểu dùng voice gốc như đang làm này, có tạo thumbnail hay không… nếu người dùng muốn đổi ý thì có nút back».

Hai lời gọi, cùng thân như /run (KHÔNG tạo task, KHÔNG ghi gì):
- build_preview: bảng thông số — nhanh, không gọi AI (mẫu đọc từ Studio, model / giọng / ảnh tính đúng như lúc chạy).
- run_checks: kiểm SỐNG một lần — AI viết gọi thật 1 từ (như nút «Thử gọi» của Flow, /api/v1/ai/test), Muse / bộ vẽ ảnh,
  giọng đọc, Content Studio. Ảnh KHÔNG vẽ thử (tốn lượt) — chỉ kiểm cấu hình + tài khoản.
Chữ trả về là tiếng Anh (chữ sản phẩm); nhãn từng dòng do giao diện dịch theo `key`.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_S = 120          # gọi thử model có thể backoff ~100 s (đo 26/9/2026: gemini-3.8-flash 103,7 s)
ENGINE_NAMES = {"edge": "Edge", "capcut": "CapCut", "omnivoice": "OmniVoice", "everai": "EverAI",
                "vibevoice": "VibeVoice", "elevenlabs": "ElevenLabs", "11labs": "ElevenLabs", "muse": "Muse",
                "auto": "Automatic"}
LENGTH_NAMES = {"short_1m": "~1 min", "short_3m": "~3 min", "medium_5m": "~5 min", "long_10m": "~10 min",
                "long_20m": "~20 min", "long_30m": "~30 min"}


def _row(key: str, value: str, detail: str = "", tone: str = "") -> Dict[str, str]:
    return {"key": key, "value": str(value or ""), "detail": str(detail or ""), "tone": tone}


def _agent(agent_id: str):
    from tubecli.core.agent import agent_manager
    return agent_manager.get(str(agent_id or "")) if agent_id else None


def _model_of(agent) -> Tuple[str, str]:
    d = agent.to_dict() if hasattr(agent, "to_dict") else {}
    return str(d.get("model") or getattr(agent, "model", "") or ""), str(d.get("provider") or "")


def normalize(content: str, options: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Any]]:
    """Options y như /run sẽ tạo (bài dán phụ đề → lời, file giọng → nguyên văn) + mốc phụ đề. Không ghi file mốc."""
    from tubecli.extensions.content_video import pipeline as P
    o = {**P.DEFAULTS, **dict(options or {})}
    cues: List[Any] = []
    if content:
        cues = P.subtitle_cues(content)
        o["source_text"] = P.subtitle_to_text(content)
    if str(o.get("voice_file") or "").strip():
        P.apply_voice_file(o)
    return o, cues


def _preset_fields(name: str) -> Tuple[Dict[str, Any], str]:
    from tubecli.extensions.content_video import pipeline as P
    if not name:
        return {}, "No template chosen."
    try:
        return dict(P._load_preset(name) or {}), ""
    except Exception as e:      # noqa: BLE001 — sai tên mẫu / Studio tắt: bảng vẫn hiện, dòng mẫu báo lỗi
        return {}, str(e)[:300]


def _image_line(meta: Dict[str, Any], agent) -> Tuple[str, str, str]:
    """(giá trị, chi tiết, nhà vẽ 'muse'|<provider>)."""
    from tubecli.extensions.content_video import pipeline as P
    roles = meta.get("image_models") if isinstance(meta.get("image_models"), dict) else {}
    role_note = ", ".join(f"{k}: {v}" for k, v in roles.items() if v)
    if meta.get("muse_only"):
        return "Muse", "This template draws every picture with Muse" + (f" ({role_note})" if role_note else ""), "muse"
    try:
        from tubecli.core import image_gen as IG
        ap, am = P._agent_image_default({"agent": agent})
        r = IG.resolve_provider(ap or None, am or None)
        prov, model = str(r.get("provider") or ""), str(r.get("model") or "")
        value = " · ".join(x for x in (prov, model) if x) or "Not set"
        detail = ("the agent's own image model" if ap else "the machine's image settings")
        if role_note:
            detail += f"; per picture type: {role_note}"
        return value, detail, prov
    except Exception as e:      # noqa: BLE001
        return "Unknown", str(e)[:200], ""


def _media_line(options: Dict[str, Any], meta: Dict[str, Any]) -> Tuple[str, str]:
    if str(options.get("scene_media") or "").strip().lower() == "stills":
        return "Still images only", "no video clips, not even the opening one (chosen in this form)"
    mode = str(meta.get("clip_mode") or "").strip().lower()
    try:
        mx = max(0, int(meta.get("clip_max") or 0))
    except (TypeError, ValueError):
        mx = 0
    cap = f", at most {mx}" if mx else ""
    if mode == "hook":
        value = "Moving still images"
        detail = "only the opening scene may get a video clip"
    elif mode == "important":
        value = "Moving stills + clips for key scenes"
        detail = f"the AI picks the turning points and peaks{cap}, as far as the template's style allows"
    else:
        value = "Images + video clips"
        detail = f"clips spread through the video{cap}, as far as the template's style allows (a style without clips stays still)"
    if str(meta.get("hook_video") or "").strip():
        detail += f"; a 10-second opening clip ({meta.get('hook_video')})"
    aspect = str(meta.get("aspect_ratio") or options.get("aspect_ratio") or "")
    if aspect:
        detail += f"; frame {aspect}"
    return value, detail


def _voice_line(options: Dict[str, Any], meta: Dict[str, Any], agent, cues: List[Any],
                voice_name: str) -> Tuple[Dict[str, str], List[str]]:
    from tubecli.extensions.content_video import pipeline as P
    from tubecli.extensions.content_video import narration_dub as ND
    warns: List[str] = []
    path = P.voice_file_path(options)
    if options.get("voice_file") and path:
        secs = P.media_seconds(path) if os.path.isfile(path) else 0.0
        name = voice_name or os.path.basename(path)
        value = f"Your voice file · {name}" + (f" ({P.clock(secs)})" if secs else "")
        if cues:
            last = max(float(c[1]) for c in cues)
            if secs and last > secs + 5:
                warns.append(f"Your subtitles run to {P.clock(last)} but the voice file is {P.clock(secs)} long — they "
                             "may not belong together; Whisper will listen to the file instead.")
                how = "Whisper listens to it to find each scene (the subtitles do not fit the file)"
            else:
                how = f"cut scene by scene by the times in your subtitles ({len(cues)} lines) — no listening needed"
        elif ND.whisper_installed():
            how = "Whisper listens to it to find where each scene starts"
        else:
            how = ("Whisper listens to it to find each scene — Whisper is not on this machine yet and installs itself "
                   "the first time (about 100 MB)")
        detail = f"{how}; a temporary CapCut (or Edge) voice reads first for timing, then your file replaces it"
        return _row("voice", value, detail), warns
    if options.get("_voice_file_dropped"):
        warns.append("The uploaded voice file is gone from this machine — upload it again.")
    v = P._retry_voice_now(options, meta, agent)
    eng = str(v.get("engine") or "auto")
    value = " · ".join(x for x in (ENGINE_NAMES.get(eng, eng.title()), str(v.get("id") or "")) if x)
    detail = {"task": "chosen for this task", "agent": "the agent's default voice",
              "template": "the template's voice"}.get(str(v.get("source") or ""), "")
    if options.get("dub"):
        dv = " ".join(str(options.get("dub_voice") or "").split())
        detail += "; then Muse re-reads the whole script in one take" + (f" ({dv[:80]})" if dv else "")
    return _row("voice", value, detail), warns


def _script_line(options: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, str]:
    from tubecli.extensions.content_video import pipeline as P
    mode = str(options.get("script_mode") or "rewrite").lower()
    words = P.content_words(str(options.get("source_text") or "")) if options.get("source_text") else 0
    if mode == "verbatim":
        value = "Word for word"
        detail = "your text is read as it is; the AI only describes the pictures"
        vpath = P.voice_file_path(options) if options.get("voice_file") else ""
        secs = P.media_seconds(vpath) if vpath and os.path.isfile(vpath) else 0.0
        if secs:
            detail += f"; the video runs as long as your voice file ({P.clock(secs)})"
        elif words:
            detail += f"; ~{P.minutes_of(words):g} min read aloud"
    elif mode == "reference":
        value = "New script on the source's structure"
        detail = "no sentence, story or metaphor of the source is reused"
    else:
        value = "Rewritten by the AI"
        detail = "the AI writes a new script from your content"
    if mode != "verbatim":
        try:
            tw = int(options.get("target_words") or 0)
        except (TypeError, ValueError):
            tw = 0
        if str(options.get("length_mode") or "") == "minutes" and tw:
            detail += f"; ~{P.minutes_of(tw):g} min"
        else:
            vl = str(meta.get("video_length") or "")
            detail += "; as long as the content needs" + (f" (template: {LENGTH_NAMES.get(vl, vl)})" if vl else "")
        dna = str(options.get("content_dna") or meta.get("content_dna") or "")
        if dna and dna != "none":
            detail += f"; writing style (content DNA): {dna}"
        note = " ".join(str(options.get("instructions") or "").split())
        if note:
            detail += f"; your instructions: {note[:120]}{'…' if len(note) > 120 else ''}"
    return _row("script", value, detail)


def _source_line(options: Dict[str, Any], cues: List[Any]) -> Dict[str, str]:
    from tubecli.extensions.content_video import pipeline as P
    text = str(options.get("source_text") or "")
    yt = P.youtube_link_only(text) if text else []
    if yt:
        return _row("source", f"YouTube subtitles · {len(yt)} link(s)", "read when the task runs")
    words = P.content_words(text) if text else 0
    if cues:
        return _row("source", f"Subtitles (.srt / .vtt) · {len(cues)} lines", f"~{words:,} words")
    return _row("source", "Pasted text", f"~{words:,} words")


def _publish_line(options: Dict[str, Any]) -> Dict[str, str]:
    if not options.get("publish"):
        return _row("publish", "Off")
    method = str(options.get("publish_method") or "")
    chan = str(options.get("publish_channel_name") or options.get("publish_profile") or "")
    when = str(options.get("publish_when") or "now")
    detail = " · ".join(x for x in (
        {"api": "YouTube API", "browser": "browser upload"}.get(method, method),
        chan, str(options.get("publish_privacy") or ""),
        {"now": "when the video is ready", "slots": f"daily slots {options.get('publish_slots') or ''}".strip(),
         "at": "at the time you chose"}.get(when, when)) if x)
    return _row("publish", "YouTube", detail)


def build_preview(agent_id: str, content: str, options: Dict[str, Any], review: bool = True,
                  voice_name: str = "") -> Dict[str, Any]:
    """Bảng thông số (không gọi AI). {"ok", "rows": [{key, value, detail, tone}], "steps": [...], "warnings": [...]}."""
    from tubecli.extensions.content_video import pipeline as P
    o, cues = normalize(content, options)
    agent = _agent(agent_id)
    warns: List[str] = []
    rows: List[Dict[str, str]] = []
    preset = str(o.get("preset") or getattr(agent, "content_video_preset", "") or "").strip()
    fields, perr = _preset_fields(preset)
    meta = fields.get("metadata") if isinstance(fields.get("metadata"), dict) else {}
    lang = str(o.get("language") or fields.get("language") or "")
    tpl_detail = " · ".join(x for x in (P.language_name(lang) if lang and lang != "auto" else "",
                                        str(meta.get("aspect_ratio") or ""),
                                        LENGTH_NAMES.get(str(meta.get("video_length") or ""),
                                                         str(meta.get("video_length") or ""))) if x)
    rows.append(_row("template", preset or "—", perr or tpl_detail, "bad" if perr else ""))
    if agent is None:
        rows.append(_row("content_ai", "—", "The agent was not found.", "bad"))
    else:
        model, prov = _model_of(agent)
        what = ("describes every scene and draws up the storyboard" if str(o.get("script_mode")) == "verbatim"
                else "writes the script and the storyboard")
        rows.append(_row("content_ai", model or "Not set",
                         f"agent «{getattr(agent, 'name', '')}»" + (f" · {prov}" if prov else "") + f" — {what}",
                         "" if model else "bad"))
    img_value, img_detail, _ = _image_line(meta, agent)
    if str(meta.get("cast_library") or "") == "auto":
        img_detail += "; recurring people get a reference sheet first (shared character library)"
    rows.append(_row("image_ai", img_value, img_detail))
    vrow, vwarn = _voice_line(o, meta, agent, cues, voice_name)
    rows.append(vrow)
    warns += vwarn
    rows.append(_source_line(o, cues))
    rows.append(_script_line(o, meta))
    mv, md = _media_line(o, meta)
    rows.append(_row("media", mv, md))
    sub = str(meta.get("subtitle_style") or "")
    if sub:
        rows.append(_row("subtitles", sub.replace("_", " ").title(), str(meta.get("subtitle_size") or "")))
    cast = P.task_cast(o)
    tcast = meta.get("cast") if isinstance(meta.get("cast"), list) else []
    if cast is not None or tcast:
        rows.append(_row("cast", ", ".join(cast if cast is not None else tcast) or "None",
                         "chosen in this form" if cast is not None else "from the template"))
    if o.get("thumbnail"):
        style = " ".join(str(o.get("thumbnail_style") or "").split())
        rows.append(_row("thumbnail", "Drawn with the image AI", style[:120]))
    else:
        rows.append(_row("thumbnail", "Prompt only", "the thumbnail prompt is written; no image is drawn"))
    rows.append(_row("review", "Stop at the script for your review" if review else "Runs straight to the video",
                     "you accept the script before any picture is drawn" if review else "no stop before the video"))
    rows.append(_publish_line(o))
    rows.append(_row("drive", "On" if o.get("drive") else "Off", P._drive_plan_note(o) if o.get("drive") else ""))
    wm = " ".join(str(o.get("watermark") or meta.get("watermark") or "").split())
    if wm:
        rows.append(_row("watermark", wm, "chosen in this form" if o.get("watermark") else "from the template"))
    steps = []
    try:
        for r in P.plan(o):
            steps.append({"step": r["step"], "label": r["label"], "will_run": bool(r["will_run"]),
                          "enabled": bool(r["enabled"]), "blocked_by": list(r.get("blocked_by") or [])})
            if r["enabled"] and not r["available"]:
                warns.append(f"{r['label']} needs {', '.join(r['blocked_by'])}.")
    except Exception as e:      # noqa: BLE001
        logger.info(f"[ContentVideo] preview plan unavailable: {e}")
    return {"ok": not perr and agent is not None, "rows": rows, "steps": steps, "warnings": warns}


# ── Kiểm sống ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _check(key: str, ok: Optional[bool], detail: str, value: str = "") -> Dict[str, Any]:
    """status: ok | fail | warn (ok=None = không chắc)."""
    return {"key": key, "status": "ok" if ok else ("warn" if ok is None else "fail"), "detail": str(detail or "")[:400],
            "value": value}


def check_text_ai(agent) -> Dict[str, Any]:
    if agent is None:
        return _check("content_ai", False, "The agent was not found.")
    model, prov = _model_of(agent)
    if not model:
        return _check("content_ai", False, "The agent has no AI model — pick one in the agent's settings.")
    from tubecli.api.ai_routes import run_probe
    r = run_probe(model, prov)
    if r.get("ok"):
        return _check("content_ai", True, f"answered in {r.get('seconds', 0)} s", model)
    return _check("content_ai", False, str(r.get("message") or "no answer"), model)


def check_image_ai(meta: Dict[str, Any], agent) -> Dict[str, Any]:
    _, _, prov = _image_line(meta, agent)
    if prov == "muse" or meta.get("muse_only"):
        from tubecli.core import muse
        st = muse.status(quick=True)
        if not st.get("configured"):
            return _check("image_ai", False, str(st.get("message") or "Muse is not set up on this machine."), "Muse")
        pool = st.get("pool") or []
        good = [p for p in pool if not p.get("down") and not p.get("signed_out")]
        remote = int(st.get("remote_seats") or 0)
        if not good and not remote:
            bad = "; ".join(f"{p.get('profile', '?')}: {'signed out' if p.get('signed_out') else 'down'}" for p in pool)
            return _check("image_ai", False, f"no Muse account is usable right now ({bad})", "Muse")
        busy = " — all seats busy, pictures wait their turn" if st.get("busy") else ""
        return _check("image_ai", True, f"{len(good)} account(s)" + (f" + {remote} remote seat(s)" if remote else "")
                      + f" ready (not test-drawn){busy}", "Muse")
    try:
        from tubecli.core import image_gen as IG
        from tubecli.extensions.content_video import pipeline as P
        ap, am = P._agent_image_default({"agent": agent})
        r = IG.resolve_provider(ap or None, am or None)
        label = " · ".join(x for x in (str(r.get("provider") or ""), str(r.get("model") or "")) if x)
        if r.get("ok"):
            return _check("image_ai", True, "key / account found (not test-drawn)", label)
        return _check("image_ai", False, str(r.get("reason") or "not usable"), label)
    except Exception as e:      # noqa: BLE001
        return _check("image_ai", None, f"could not check: {str(e)[:200]}")


def check_voice(options: Dict[str, Any], fields: Dict[str, Any], agent, cues: List[Any]) -> Dict[str, Any]:
    from tubecli.extensions.content_video import pipeline as P
    from tubecli.extensions.content_video import narration_dub as ND
    state: Dict[str, Any] = {"preset": {"fields": fields}, "agent": agent}
    try:
        eng = P._tts_engine(state, options)
    except Exception as e:      # noqa: BLE001 — chính câu lỗi bước giọng sẽ báo
        return _check("voice", False, str(e)[:300])
    if not eng:
        return _check("voice", False, "No voice engine on this machine — install TTS VibeVoice (Edge) or CapCut TTS.")
    name = ENGINE_NAMES.get(eng, eng)
    if options.get("voice_file"):
        if not P.voice_file_path(options):
            return _check("voice", False, "The uploaded voice file is gone — upload it again.")
        temp = f"temporary voice: {name}" + (f" ({state.get('capcut_email')})" if state.get("capcut_email") else "")
        if cues:
            return _check("voice", True, f"{temp}; your file is cut by your subtitles' times", name)
        if ND.whisper_installed():
            return _check("voice", True, f"{temp}; Whisper is installed", name)
        return _check("voice", None, f"{temp}; Whisper is not installed yet — it installs itself when the voice "
                                     "file is swapped in (needs internet, about 100 MB)", name)
    if options.get("dub"):
        from tubecli.core import muse
        if not muse.status(quick=True).get("configured"):
            return _check("voice", False, "Re-dub with Muse is on, but Muse is not set up on this machine.", name)
    return _check("voice", True, f"{name} is ready" + (f" ({state.get('capcut_email')})" if state.get("capcut_email")
                                                      else ""), name)


def check_studio() -> Dict[str, Any]:
    from tubecli.extensions.content_video.capabilities import studio_capabilities
    try:
        caps = studio_capabilities(timeout=20)
    except Exception as e:      # noqa: BLE001
        return _check("studio", False, f"Content Studio does not answer: {str(e)[:200]}")
    bad = [k for k in ("assembly",) if not (caps.get(k) or {}).get("ok")]
    if bad:
        c = caps.get(bad[0]) or {}
        return _check("studio", False, f"{c.get('label', bad[0])}: {c.get('detail', '')} {c.get('fix', '')}".strip())
    return _check("studio", True, "Content Studio is running; video assembly (ffmpeg) is ready")


def run_checks(agent_id: str, content: str, options: Dict[str, Any],
               timeout: float = CHECK_TIMEOUT_S) -> Dict[str, Any]:
    """Kiểm sống song song; quá `timeout` thì mục chưa xong báo «still waiting» (không treo bảng)."""
    o, cues = normalize(content, options)
    agent = _agent(agent_id)
    preset = str(o.get("preset") or getattr(agent, "content_video_preset", "") or "").strip()
    fields, _ = _preset_fields(preset)
    meta = fields.get("metadata") if isinstance(fields.get("metadata"), dict) else {}
    jobs: Dict[str, Callable[[], Dict[str, Any]]] = {
        "content_ai": lambda: check_text_ai(agent),
        "image_ai": lambda: check_image_ai(meta, agent),
        "voice": lambda: check_voice(o, fields, agent, cues),
        "studio": check_studio,
    }
    out: Dict[str, Dict[str, Any]] = {}
    pool = ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="cv-preview")
    futs = {pool.submit(fn): key for key, fn in jobs.items()}
    done, _ = wait(futs, timeout=timeout)
    for f, key in futs.items():
        if f in done:
            try:
                out[key] = f.result()
            except Exception as e:      # noqa: BLE001
                out[key] = _check(key, None, f"could not check: {str(e)[:200]}")
        else:
            out[key] = _check(key, None, f"no answer within {int(timeout)} s")
    pool.shutdown(wait=False)
    order = ["content_ai", "image_ai", "voice", "studio"]
    checks = [out[k] for k in order]
    return {"ok": all(c["status"] != "fail" for c in checks), "checks": checks}
