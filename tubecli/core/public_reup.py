"""Skill công khai «Reup Douyin» (user 28/9/2026): tải video Douyin → tách phụ đề
(Gemini, dịch 1 bước) → lồng tiếng Edge-TTS theo logic ReupDouyin (core/reup_dub.py)
→ tuỳ chọn ghi phụ đề → giao file qua link /s/ trên chính máy chủ agent.

Cả chuỗi chạy 1–3 phút, vượt xa trần 40 s/lượt invoke → kiểu JOB hai pha:
  · input là LINK Douyin  → mở job chạy NỀN, trả ngay thẻ tiến độ {kind: "reupjob"};
  · input là JSON {"job"} → trả trạng thái; xong thì {kind: "reupfile", share, ...}.
Mỗi lượt hỏi trạng thái là một lượt quota như mọi lượt chat — client chỉ hỏi khi người
xem bấm «Kiểm tra», không bao giờ tự hỏi ngầm.

Neo an toàn quen thuộc: link Douyin đi qua đúng pick_link của douyin_downloader; file
trả về là đường dẫn /s/ TƯƠNG ĐỐI để cloud tự ghép tunnel; giọng/ngôn ngữ/chế độ đều
whitelist hai tầng. Job của ai người nấy hỏi: id job ngẫu nhiên 16 hex, chỉ đi qua
phiên chat đã lưu của chính người mở.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from tubecli.core.public_agents import PublicSkillError

logger = logging.getLogger("public_reup")

JOB_TTL_SEC = 6 * 3600
MAX_VIDEO_BYTES = 300 * 1024 * 1024
MAX_PARALLEL_JOBS = 2
EXTRACT_TIMEOUT_SEC = 10 * 60
LANGS = {"", "vi", "en", "ja", "zh"}
MODES = {"replace", "mix"}
COVER_CHOICES = {"delogo", "blur", "pixel", "fill", "none"}   # none = giữ phụ đề gốc
LANG_NAMES = {"vi": "Vietnamese", "en": "English", "ja": "Japanese", "zh": "Simplified Chinese"}
TRANSLATE_BATCH = 40
_JOB_RE = re.compile(r"^[a-f0-9]{16}$")

_jobs: Dict[str, Dict[str, Any]] = {}   # id -> {status, step, done, total, code, result, created, task}


def _root() -> Path:
    from tubecli.config import DATA_DIR

    d = Path(str(DATA_DIR)) / "reup_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _base() -> str:
    from tubecli.config import get_api_port

    return f"http://127.0.0.1:{get_api_port()}"


def _sweep() -> None:
    now = time.time()
    for jid in [j for j, v in _jobs.items() if now - v.get("created", 0) > JOB_TTL_SEC]:
        _jobs.pop(jid, None)
    try:
        for p in _root().iterdir():
            if p.is_dir() and now - p.stat().st_mtime > JOB_TTL_SEC:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _set(jid: str, **kw) -> None:
    if jid in _jobs:
        _jobs[jid].update(kw)


def _download_blocking(url: str, dest: Path) -> None:
    import requests

    with requests.get(url, stream=True, timeout=120,
                      headers={"User-Agent": "Mozilla/5.0 (TubeCLI Reup)"}) as r:
        if r.status_code != 200:
            raise PublicSkillError("download_failed", status=502)
        written = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise PublicSkillError("video_too_big")
                f.write(chunk)
    if written < 10_000:
        raise PublicSkillError("download_failed", status=502)


async def _extract(file_path: str, translate_to: str, jid: str) -> list:
    """Tách phụ đề qua route job async của subtitle_extractor, dịch 1 bước bằng Gemini."""
    import requests

    def _post():
        return requests.post(_base() + "/api/v1/subtitle/extract", json={
            "file_path": file_path, "engine": "gemini",
            # TÊN ngôn ngữ, không phải mã: prompt của extension ghép thẳng «Translate every
            # sentence into {translate_to}» — «into vi» từng bị Gemini bỏ qua (28/9).
            "translate_to": LANG_NAMES.get(translate_to, translate_to) or None,
        }, timeout=30)

    r = await asyncio.to_thread(_post)
    if r.status_code == 404:
        raise PublicSkillError("skill_unavailable", status=503)
    if r.status_code >= 400:
        raise PublicSkillError("subtitle_failed", status=502)
    tid = (r.json() or {}).get("task_id")
    if not tid:
        raise PublicSkillError("subtitle_failed", status=502)

    deadline = time.monotonic() + EXTRACT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        await asyncio.sleep(2)

        def _poll():
            return requests.get(_base() + f"/api/v1/subtitle/status/{tid}", timeout=15)

        try:
            s = (await asyncio.to_thread(_poll)).json() or {}
        except Exception:      # noqa: BLE001 — một cú poll hỏng không giết job
            continue
        _set(jid, done=int(s.get("progress") or 0), total=int(s.get("total") or 0))
        st = s.get("status")
        if st == "success":
            subs = ((s.get("result") or {}).get("subtitles")) or []
            if not subs:
                raise PublicSkillError("no_speech", status=422)
            return subs
        if st == "error":
            msg = str((s.get("result") or {}).get("message") or "")
            logger.warning("[reup %s] extract lỗi: %s", jid, msg[:200])
            raise PublicSkillError("subtitle_failed", status=502)
    raise PublicSkillError("timeout", status=504)


def untranslated(subs: list, lang: str) -> list:
    """Chỉ số các câu KHÔNG ở tiếng đích (đoán theo chữ). Câu không đoán được thì bỏ qua."""
    from tubecli.core.agent_media import guess_lang

    return [i for i, s in enumerate(subs) if guess_lang([s.get("text")]) not in ("", lang)]


async def _ensure_translated(subs: list, lang: str) -> list:
    """Gemini tách + dịch một bước đôi khi TRẢ NGUYÊN TIẾNG GỐC (28/9: link EP5zRRErMAM ra
    15 câu chữ Trung phồn thể dù yêu cầu dịch sang Việt → giọng Việt đọc chữ Trung, 4/15
    câu có tiếng). Quá 20 % câu sai tiếng → dịch bù đúng các câu đó bằng route dịch chữ
    của subtitle_extractor. Dịch bù hỏng thì giữ nguyên — pick_voice chọn giọng theo tiếng
    THẬT của phụ đề nên video vẫn có tiếng."""
    import requests

    if not lang or lang not in LANG_NAMES or not subs:
        return subs
    bad = untranslated(subs, lang)
    if len(bad) <= len(subs) * 0.2:
        return subs
    out = [dict(s) for s in subs]
    for k in range(0, len(bad), TRANSLATE_BATCH):
        part = bad[k:k + TRANSLATE_BATCH]

        def _post(part=part):
            return requests.post(_base() + "/api/v1/subtitle/translate", json={
                "subtitles": [{"text": out[i]["text"]} for i in part],
                "target_language": LANG_NAMES[lang]}, timeout=120)
        try:
            r = await asyncio.to_thread(_post)
            got = (r.json() or {}).get("subtitles") or [] if r.status_code == 200 else []
        except Exception as e:      # noqa: BLE001
            logger.warning("dịch bù hỏng: %s", e)
            got = []
        for i, g in zip(part, got):
            t = str((g or {}).get("text") or "").strip()
            if t:
                out[i]["text"] = t
    logger.info("dịch bù %d/%d câu sai tiếng → còn %d", len(bad), len(subs), len(untranslated(out, lang)))
    return out


def pick_voice(opts: Dict[str, Any], texts: list) -> tuple:
    """(engine, voice, fallback_edge_voice) cho một job.

    Người xem chọn giọng Edge trên Town → dùng đúng giọng đó. Không chọn → giọng MẶC ĐỊNH
    của agent (Flow › agent › Cơ bản), trừ khi giọng đó rõ ràng khác tiếng của phụ đề
    (giọng Việt đọc phụ đề đã dịch sang Anh nghe rất lạ) → Edge đúng tiếng. Agent chưa
    đặt → Edge theo tiếng của phụ đề."""
    from tubecli.core import agent_media as am

    # Tiếng THẬT của phụ đề trước (dịch có thể đã hỏng), rồi mới tới tiếng người xem chọn
    lang = am.guess_lang(texts) or str(opts.get("lang") or "") or "vi"
    fallback = am.EDGE_BY_LANG.get(lang, "vi-VN-HoaiMyNeural")
    chosen = str(opts.get("voice") or "")
    if chosen:
        return "edge", chosen, fallback
    engine, voice = am.agent_voice(str(opts.get("_agent_id") or ""))
    vl = am.voice_lang(engine, voice)
    if engine == "capcut" and (not vl or vl == lang):
        return "capcut", voice, fallback
    if engine == "edge" and voice and (not vl or vl == lang):
        from tubecli.core.reup_dub import EDGE_VOICES
        if voice in EDGE_VOICES:
            return "edge", voice, fallback
    return "edge", fallback, fallback


_COLLAPSED = 0.05    # cue ngắn hơn chừng này = bị kẹp về cuối đoạn, không phải câu thật


def collapsed_count(subs: list) -> int:
    return sum(1 for s in subs if float(s["end"]) - float(s["start"]) < _COLLAPSED)


def rescue_collapsed(subs: list, video_dur: float) -> list:
    """Còn cue dồn cục ở ĐUÔI sau khi đã tách lại: coi mốc bị giãn đều (trôi tuyến tính),
    co các cue tốt lại rồi xếp các cue dồn cục nối sau theo tốc độ đọc của chính video
    (ký tự/giây trung vị). Dồn cục ở GIỮA (ranh giới đoạn 175 s) thì để nguyên — không
    đoán được thời gian thật, lồng tiếng tự bỏ các cue đó như trước."""
    subs = sorted(subs, key=lambda s: float(s["start"]))
    good = [s for s in subs if float(s["end"]) - float(s["start"]) >= _COLLAPSED]
    tail = subs[len(good):] if subs[:len(good)] == good else []
    if not good or not tail or video_dur <= 0:
        return subs
    rates = sorted(len(str(s["text"])) / (float(s["end"]) - float(s["start"])) for s in good)
    cps = rates[len(rates) // 2] or 15.0
    need = sum(len(str(s["text"])) for s in tail) / cps
    last = float(good[-1]["end"])
    f = max(0.6, min(1.0, (video_dur - need) / last)) if last > 0 else 1.0
    out = [{**s, "start": round(float(s["start"]) * f, 3), "end": round(float(s["end"]) * f, 3)}
           for s in good]
    t = last * f
    room = max(0.0, video_dur - t)
    k = room / need if need > 0 else 1.0
    for s in tail:
        d = len(str(s["text"])) / cps * min(1.0, k)
        out.append({**s, "start": round(t, 3), "end": round(min(video_dur, t + d), 3)})
        t += d
    return out


async def _run_job(jid: str, link: str, opts: Dict[str, Any]) -> None:
    from tubecli.core import public_share as ps
    from tubecli.core import reup_dub

    from tubecli.core import reup_cover

    jdir = _root() / jid
    jdir.mkdir(parents=True, exist_ok=True)
    det_task = None
    try:
        # 1. Link → media gốc, đúng đường skill Douyin công khai (không cookie chủ)
        _set(jid, step="download")
        from tubecli.extensions.douyin_downloader.public_skill import resolve as dy_resolve

        res = await dy_resolve(link)
        if res.get("kind") not in ("video",):
            raise PublicSkillError("not_video", status=422)
        media = (res.get("media") or [{}])[0]
        url = media.get("direct") or media.get("url")
        if not url:
            raise PublicSkillError("download_failed", status=502)
        src = jdir / "src.mp4"
        await asyncio.to_thread(_download_blocking, url, src)

        # 1.5 Dò ô phụ đề GỐC cháy sẵn (Gemini vision) — chạy SONG SONG với bước tách phụ
        # đề, vì hai việc không phụ thuộc nhau; che thật thì gộp vào lần encode cuối.
        cover_mode = str(opts.get("cover") or "none")
        want_logo = str(opts.get("logo") or "0") == "1"
        ff = reup_dub.find_ffmpeg()
        if (cover_mode in reup_cover.COVER_MODES or want_logo) and ff:
            det_task = asyncio.create_task(reup_cover.detect_subtitle_box(str(src), ff, jdir))

        # 2. Tách phụ đề (+ dịch nếu chọn)
        _set(jid, step="subtitle", done=0, total=0)
        subs = await _extract(str(src), str(opts.get("lang") or ""), jid)
        # Gemini đôi khi cho mốc TRÔI dài hơn đoạn audio; subtitle_extractor kẹp về cuối
        # đoạn nên các câu cuối dồn cục, dài 0 s, và bị bỏ khi lồng (demo 28/9: 6 câu
        # cuối video 2:28). Mô hình không tất định — tách lại một lần thường là khỏi.
        if collapsed_count(subs) >= 2:
            _set(jid, step="subtitle", done=0, total=0)
            again = await _extract(str(src), str(opts.get("lang") or ""), jid)
            if collapsed_count(again) < collapsed_count(subs):
                subs = again
        if collapsed_count(subs):
            subs = rescue_collapsed(subs, await reup_dub.media_duration(str(src)))
        subs = await _ensure_translated(subs, str(opts.get("lang") or ""))
        # Bước 3.5 của ReupDouyin: cắt dòng dài trước khi lồng — phụ đề giao ra (.srt)
        # cũng là bản đã cắt, đúng như bản gốc cho người dùng duyệt.
        subs = reup_dub.split_long_subtitles(subs)

        cover_box, logo_boxes = None, []
        if det_task is not None:
            if not det_task.done():
                _set(jid, step="clean", done=0, total=0)
            det = await det_task
            det_task = None
            cover_on = det.get("found") and cover_mode in reup_cover.COVER_MODES
            cover_box = det.get("box") if cover_on else None
            # Che theo ĐOẠN có chữ, ô khít riêng (quét pixel — user 19/10/2026); rỗng = dải cố định
            cover_segments = (det.get("segments") or None) if cover_on else None
            logo_boxes = [o["box"] for o in (det.get("overlays") or [])] if want_logo else []
            logger.info("[reup %s] phụ đề gốc: %s", jid,
                        (f"{len(cover_segments)} đoạn, ô neo {cover_box} ({det.get('hits')}/{det.get('scanned')} khung có chữ)"
                         if cover_segments else
                         f"dải cố định {cover_box} ({det.get('frames_with_text')}/{det.get('total')} khung)")
                        if cover_box else f"không che ({det.get('reason') or 'không thấy'})")
            if want_logo:
                logger.info("[reup %s] logo: %s", jid,
                            [(o.get("kind"), o.get("text"), o["box"]) for o in det.get("overlays") or []])

        out = jdir / "reup.mp4"

        def _prog(phase: str, done: int, total: int) -> None:
            _set(jid, step="dub" if phase in ("tts",) else phase, done=done, total=total)

        if str(opts.get("voice") or "") == "none":
            # 3'. CHỈ PHỤ ĐỀ, không lồng tiếng (user 19/10/2026): âm gốc giữ nguyên, che phụ đề
            # gốc / logo + ghi phụ đề mới. Không có bước dub → thẻ tiến độ nhảy thẳng sang dựng.
            _set(jid, step="burn", done=0, total=1)
            r = await reup_dub.render_only(
                str(src), subs, str(out), burn=str(opts.get("burn") or "0") == "1", progress=_prog,
                cover_box=cover_box, cover_mode=cover_mode, cover_segments=cover_segments,
                logo_boxes=logo_boxes)
        else:
            # 3. Lồng tiếng theo logic ReupDouyin
            _set(jid, step="dub", done=0, total=len(subs))
            engine, voice, fallback = pick_voice(opts, [s.get("text") for s in subs])
            r = await reup_dub.dub_video(
                str(src), subs, voice, str(out),
                mode=str(opts.get("mode") or "replace"), bg_volume=0.15,
                burn=str(opts.get("burn") or "0") == "1", progress=_prog,
                engine=engine, fallback_voice=fallback,
                cover_box=cover_box, cover_mode=cover_mode, logo_boxes=logo_boxes,
                cover_segments=cover_segments)
        if r.get("status") != "success":
            code = str(r.get("message") or "reup_failed")
            raise PublicSkillError(code if re.match(r"^[a-z_]{3,32}$", code) else "reup_failed",
                                   status=502)

        # 4. Giao hàng: file mp4 + phụ đề .srt qua kho share (chủ máy thấy, thu hồi được)
        _set(jid, step="share")
        srt = jdir / "reup.srt"
        reup_dub.write_srt(subs, srt)
        share = ps.share_path(str(out), f"reup_{jid}.mp4", JOB_TTL_SEC)
        srt_share = ps.share_path(str(srt), f"reup_{jid}.srt", JOB_TTL_SEC)
        dur = await reup_dub.media_duration(str(out))
        _set(jid, status="done", result={
            "share": share + "/download",
            "page": share,
            "srt": srt_share + "/download",
            "size": out.stat().st_size,
            "duration": f"{int(dur // 60)}:{int(dur % 60):02d}",
            "segments": int(r.get("segments") or 0),
            "engine": str(r.get("engine") or "edge"),
            "covered": bool(r.get("covered")),
            "logos": int(r.get("logos") or 0),
        })
        try:
            src.unlink()               # video gốc không giao ra ngoài — dọn luôn
        except OSError:
            pass
    except PublicSkillError as e:
        _set(jid, status="error", code=e.code)
    except Exception as e:      # noqa: BLE001
        logger.warning("[reup %s] hỏng: %s", jid, e, exc_info=True)
        _set(jid, status="error", code="reup_failed")
    finally:
        if det_task is not None and not det_task.done():
            det_task.cancel()


def _snapshot(jid: str) -> Dict[str, Any]:
    j = _jobs.get(jid)
    if not j:
        raise PublicSkillError("job_not_found", status=404)
    if j.get("status") == "done":
        return {"kind": "reupfile", "job": jid, **j["result"], "expires_h": JOB_TTL_SEC // 3600}
    return {
        "kind": "reupjob", "job": jid,
        "status": "error" if j.get("status") == "error" else "running",
        "step": str(j.get("step") or "download"),
        "done": int(j.get("done") or 0), "total": int(j.get("total") or 0),
        **({"code": j["code"]} if j.get("code") else {}),
    }


async def resolve(text: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _sweep()
    t = str(text or "").strip()

    # Pha 2: hỏi trạng thái job
    if t.startswith("{"):
        try:
            jid = str((json.loads(t) or {}).get("job") or "")
        except ValueError:
            raise PublicSkillError("bad_input")
        if not _JOB_RE.match(jid):
            raise PublicSkillError("bad_input")
        return _snapshot(jid)

    # Pha 1: link Douyin → mở job nền
    from tubecli.extensions.douyin_downloader.public_skill import pick_link

    link = pick_link(t)
    if not link:
        raise PublicSkillError("need_douyin_link")
    if sum(1 for j in _jobs.values() if j.get("status") == "running") >= MAX_PARALLEL_JOBS:
        raise PublicSkillError("busy", status=429)

    o = opts or {}
    from tubecli.core.reup_dub import EDGE_VOICES

    cover = str(o.get("cover") or "delogo")
    job_opts = {
        # "" = người xem không chọn → giọng MẶC ĐỊNH của agent (pick_voice, lúc lồng);
        # "none" = KHÔNG lồng tiếng, chỉ phụ đề, giữ âm gốc (user 19/10/2026)
        "voice": "none" if str(o.get("voice") or "") == "none"
        else (o.get("voice") if o.get("voice") in EDGE_VOICES else ""),
        "_agent_id": str(o.get("_agent_id") or ""),
        # Che phụ đề gốc: nội suy (delogo) mặc định — đúng logic user 28/9 hỏi
        "cover": cover if cover in COVER_CHOICES else "delogo",
        # Xoá logo/watermark cố định (qua 3 cửa lọc) — TẮT mặc định như ReupDouyin
        "logo": "1" if str(o.get("logo") or "") == "1" else "0",
        "lang": o.get("lang") if o.get("lang") in LANGS else "",
        "burn": "1" if str(o.get("burn") or "") == "1" else "0",
        "mode": o.get("mode") if o.get("mode") in MODES else "replace",
    }
    jid = uuid.uuid4().hex[:16]
    _jobs[jid] = {"status": "running", "step": "download", "done": 0, "total": 0,
                  "created": time.time()}
    # Giữ tham chiếu task trong job — không thì garbage collector nhặt mất giữa chừng.
    _jobs[jid]["task"] = asyncio.create_task(_run_job(jid, link, job_opts))
    return _snapshot(jid)
