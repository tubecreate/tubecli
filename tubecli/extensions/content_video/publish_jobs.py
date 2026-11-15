"""Đăng video ĐÃ DỰNG của một task + sửa SEO video đã đăng — qua MỘT hàng đợi trình duyệt an toàn RAM (14/11/2026).

Vì sao (contabo 6G, server t3rwap): 74 task «Auto video» nằm ở Review với bước «Publish to YouTube — turned off»; bấm
Accept chỉ đóng task, không đăng; máy không có token YouTube nên đường duy nhất là YouTube Studio trong hồ sơ trình
duyệt; và VPS 6 GB RAM đã sập khi nhiều trình duyệt mở cùng lúc. Chủ muốn Claude (connector) tự đăng từng video.

Ba việc, một hàng đợi:
  * publish   — POST /api/v1/codex/tasks/{id}/publish: đăng file mp4 SẴN CÓ của task (không dựng lại, không viết lại
                kịch bản) bằng chính đường đăng của pipeline (_publish_now → script YouTube Studio), ghi link thật vào
                kết quả + checkpoint.published rồi đưa task sang DONE mà KHÔNG gọi hook on_accept.
  * seo_edit  — PUT /api/v1/youtube/videos/{video_id}: sửa tiêu đề / mô tả / tag của video đã đăng qua Studio.
  * hàng đợi  — MỘT luồng thợ ⇒ mỗi lúc tối đa MỘT hồ sơ trình duyệt mở cho việc đăng / sửa; việc sau chờ việc trước
                đóng trình duyệt. Không mở trình duyệt khi RAM trống dưới ngưỡng hoặc khi đang dựng video (ffmpeg / bước
                render của một task đang chạy) — việc ở trạng thái «waiting» và được xét lại, không hỏng. Xong / lỗi /
                quá giờ đều ĐÓNG hồ sơ.

Sổ việc ghi ra đĩa (publish_jobs.json): việc ĐANG CHỜ sống qua lần khởi động lại và chạy tiếp. Việc ĐANG CHẠY lúc
máy chủ tắt thì KHÔNG tự chạy lại — video có thể đã lên kênh, chạy lại là đăng lần hai — nó thành «interrupted» và
nói rõ phải mở kênh kiểm tra.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ContentVideo")

STORE_FILE = "publish_jobs.json"
ACTOR = "publish_queue"
KEEP_FINISHED = 200                       # việc đã xong giữ lại để tra (cũ hơn thì bỏ)
PUBLISH_KINDS = ("content_video.auto", "content_video.render")
EDIT_SCRIPT = "youtube_edit_video"
YT_TITLE_MAX, YT_DESC_MAX, YT_TAGS_MAX = 100, 5000, 500

# Cài đặt (global settings) — tên khoá + mặc định. Đổi bằng PUT /api/v1/settings như mọi cài đặt khác.
SETTINGS = {
    "publish_min_free_ram_mb": 1536,      # dưới chừng này RAM trống thì KHÔNG mở trình duyệt, việc chờ
    "publish_wait_for_render": True,      # đang dựng video (ffmpeg / bước render) thì chờ
    "publish_job_timeout_min": 60,        # một việc chạy quá chừng này phút ⇒ quá giờ, đóng hồ sơ
    "publish_recheck_sec": 30,            # nhịp xét lại khi đang chờ RAM / render
    "publish_max_wait_hours": 24,         # chờ quá chừng này giờ ⇒ hỏng với lý do rõ ràng
}

QUEUED, WAITING, RUNNING = "queued", "waiting", "running"
DONE, FAILED, UNVERIFIED, INTERRUPTED = "done", "failed", "unverified", "interrupted"
ACTIVE = (QUEUED, WAITING, RUNNING)

_LOCK = threading.RLock()
_WAKE = threading.Event()
_worker: Optional[threading.Thread] = None
_loaded = False
_jobs: Dict[str, Dict[str, Any]] = {}


class JobError(Exception):
    """Lời từ chối có mã HTTP — route trả nguyên cho người gọi."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


# ── cài đặt ───────────────────────────────────────────────────────────────────
def setting(name: str) -> Any:
    default = SETTINGS[name]
    try:
        from tubecli import config
        raw = (config.read_global_settings() or {}).get(name)
    except Exception:       # noqa: BLE001
        raw = None
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return str(raw).strip().lower() not in ("false", "0", "off", "no")
    try:
        return type(default)(float(raw))
    except (TypeError, ValueError):
        return default


# ── sổ việc ───────────────────────────────────────────────────────────────────
def _store_path():
    from tubecli.config import ext_data_path

    return ext_data_path("content_video", STORE_FILE)


def _now() -> float:
    return time.time()


def _save() -> None:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(_jobs.values(), key=lambda j: j.get("created_at") or 0)
        done = [j for j in rows if j.get("status") not in ACTIVE]
        for j in done[:-KEEP_FINISHED] if len(done) > KEEP_FINISHED else []:
            _jobs.pop(j["id"], None)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"jobs": list(_jobs.values())}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, str(path))
    except Exception as e:      # noqa: BLE001
        logger.warning("[PublishQueue] could not save the queue (%s)", e)


def _load() -> None:
    """Nạp sổ một lần mỗi tiến trình. Việc đang CHẠY lúc tắt máy ⇒ interrupted (không tự chạy lại)."""
    global _loaded
    with _LOCK:
        if _loaded:
            return
        _loaded = True
        try:
            path = str(_store_path())
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    for j in (json.load(fh) or {}).get("jobs") or []:
                        if isinstance(j, dict) and j.get("id"):
                            _jobs[str(j["id"])] = j
        except Exception as e:      # noqa: BLE001
            logger.warning("[PublishQueue] queue file unreadable (%s) — starting empty", e)
        changed = False
        for j in _jobs.values():
            if j.get("status") == RUNNING:
                j.update(status=INTERRUPTED, finished_at=_now(),
                         error="The server restarted while this job was running. The video may or may not have "
                               "reached YouTube — check the channel before publishing this task again.")
                changed = True
            elif j.get("status") == WAITING:
                j.update(status=QUEUED, wait_reason="")
                changed = True
        if changed:
            _save()


def public(job: Dict[str, Any]) -> Dict[str, Any]:
    """Bản của việc trả cho người gọi (không lộ gì ngoài những gì chính họ gửi)."""
    out = {k: job.get(k) for k in ("id", "kind", "status", "task_id", "task_seq", "video_id", "profile", "channel",
                                   "wait_reason", "progress", "error", "result", "created_at", "started_at",
                                   "finished_at", "requested")}
    with _LOCK:
        ahead = [j for j in _jobs.values() if j.get("status") in ACTIVE and j["id"] != job["id"]
                 and (j.get("created_at") or 0) <= (job.get("created_at") or 0)]
    out["position"] = len(ahead) if job.get("status") in (QUEUED, WAITING) else 0
    return out


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    _load()
    with _LOCK:
        j = _jobs.get(str(job_id))
        return dict(j) if j else None


def list_jobs(active_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
    _load()
    with _LOCK:
        rows = sorted(_jobs.values(), key=lambda j: j.get("created_at") or 0, reverse=True)
    if active_only:
        rows = [j for j in rows if j.get("status") in ACTIVE]
    return [public(j) for j in rows[:max(1, min(200, int(limit or 50)))]]


def job_for_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Việc đăng MỚI NHẤT của task (đang chờ, đang chạy hay đã xong)."""
    _load()
    with _LOCK:
        rows = [j for j in _jobs.values() if j.get("kind") == "publish" and j.get("task_id") == str(task_id)]
    rows.sort(key=lambda j: j.get("created_at") or 0)
    return dict(rows[-1]) if rows else None


def _enqueue(job: Dict[str, Any]) -> Dict[str, Any]:
    _load()
    job.update(id=uuid.uuid4().hex[:16], status=QUEUED, created_at=_now(), started_at=None, finished_at=None,
               wait_reason="", progress="", error="", result={})
    with _LOCK:
        _jobs[job["id"]] = job
        _save()
    start_worker()
    _WAKE.set()
    return job


def _patch(job_id: str, **fields: Any) -> None:
    with _LOCK:
        j = _jobs.get(job_id)
        if j is not None:
            j.update(fields)
            _save()


# ── cổng RAM / render ─────────────────────────────────────────────────────────
def free_ram_mb() -> float:
    """RAM còn dùng được (MB). Không đo được → -1 (cổng coi là «không biết», xem gate_reason)."""
    try:
        import psutil
        return float(psutil.virtual_memory().available) / (1024 * 1024)
    except Exception:       # noqa: BLE001
        return -1.0


def render_running() -> str:
    """Câu mô tả việc dựng video đang chạy, hay "" khi không có. Hai dấu hiệu: một task Codex đang chạy có bước
    «render» ở trạng thái running; hoặc một tiến trình ffmpeg đang sống (Content Studio xuất video bằng ffmpeg)."""
    try:
        from tubecli.extensions.codex.manager import codex_manager
        for t in codex_manager.list_tasks(status="running", limit=50) or []:
            for s in t.get("steps") or []:
                if s.get("name") == "render" and s.get("status") == "running":
                    return f"task #{t.get('seq')} is assembling its video"
    except Exception as e:      # noqa: BLE001
        logger.debug("[PublishQueue] cannot read running tasks: %s", e)
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            if "ffmpeg" in str((p.info or {}).get("name") or "").lower():
                return "ffmpeg is running (a video is being rendered)"
    except Exception as e:      # noqa: BLE001
        logger.debug("[PublishQueue] cannot list processes: %s", e)
    return ""


def gate_reason() -> str:
    """Vì sao CHƯA được mở trình duyệt ("" = được). RAM không đo được thì KHÔNG mở (cửa đóng): máy này đã sập vì
    thiếu RAM, mở mù là lặp lại đúng sự cố đó."""
    need = int(setting("publish_min_free_ram_mb"))
    if need > 0:
        free = free_ram_mb()
        if free < 0:
            return "free RAM cannot be measured on this machine (psutil missing)"
        if free < need:
            return f"only {int(free)} MB of RAM is free (needs {need} MB)"
    if setting("publish_wait_for_render"):
        why = render_running()
        if why:
            return why
    return ""


# ── luồng thợ ─────────────────────────────────────────────────────────────────
def start_worker() -> None:
    global _worker
    with _LOCK:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_loop, name="publish-queue", daemon=True)
        _worker.start()


def _next_job() -> Optional[Dict[str, Any]]:
    with _LOCK:
        rows = sorted((j for j in _jobs.values() if j.get("status") in (QUEUED, WAITING)),
                      key=lambda j: j.get("created_at") or 0)
        return rows[0] if rows else None


def tick() -> str:
    """MỘT nhịp của thợ: "idle" (không có việc) · "waiting" (cổng RAM / render đang đóng) · "gave_up" · "ran".
    Việc được lấy theo thứ tự xếp hàng và chạy TRỌN trong nhịp này — nên không bao giờ có hai trình duyệt cùng mở."""
    job = _next_job()
    if job is None:
        return "idle"
    try:
        why = gate_reason()
        if why:
            waited_h = (_now() - float(job.get("created_at") or _now())) / 3600.0
            if waited_h > float(setting("publish_max_wait_hours")):
                _finish(job, FAILED, error=f"Waited {int(waited_h)} h for the machine to be free and gave up — "
                                           f"last reason: {why}. Nothing was opened or published.")
                return "gave_up"
            if job.get("status") != WAITING or job.get("wait_reason") != why:
                _patch(job["id"], status=WAITING, wait_reason=why)
            return "waiting"
        _run(job)
        return "ran"
    except Exception as e:      # noqa: BLE001 — luồng thợ không được chết
        logger.error("[PublishQueue] job %s crashed: %s", job.get("id"), e, exc_info=True)
        _finish(job, FAILED, error=f"Internal error: {e}")
        return "ran"


def _loop() -> None:
    _load()
    while True:
        what = tick()
        if what == "idle":
            _WAKE.clear()
            _WAKE.wait(60)
        elif what == "waiting":
            _WAKE.clear()
            _WAKE.wait(max(5, int(setting("publish_recheck_sec"))))


def _finish(job: Dict[str, Any], status: str, error: str = "", result: Optional[Dict] = None) -> None:
    _patch(job["id"], status=status, error=str(error or "")[:600], result=result or job.get("result") or {},
           finished_at=_now(), wait_reason="")


def _run(job: Dict[str, Any]) -> None:
    """Chạy MỘT việc có trần thời gian; dù kết cục nào cũng đóng hồ sơ trình duyệt."""
    _patch(job["id"], status=RUNNING, started_at=_now(), wait_reason="", progress="starting")
    handler = _run_publish if job.get("kind") == "publish" else _run_seo_edit
    box: Dict[str, Any] = {}

    def body():
        try:
            box["out"] = handler(job)
        except BaseException as e:      # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=body, name=f"publish-job-{job['id']}", daemon=True)
    t.start()
    t.join(max(60, int(setting("publish_job_timeout_min")) * 60))
    timed_out = t.is_alive()
    # ĐÓNG hồ sơ trong mọi trường hợp: xong, lỗi (đường đăng để cửa sổ mở cho chủ xem — máy 6 GB không chịu nổi), quá giờ.
    _close_profile(str((get_job(job["id"]) or job).get("profile") or ""))
    if timed_out:
        _after_failure(job, f"Timed out after {int(setting('publish_job_timeout_min'))} minutes — the browser was closed. "
                            "The video may or may not have reached YouTube: check the channel before trying again.",
                       unsure=True)
        return
    if "err" in box:
        _after_failure(job, " ".join(str(box["err"]).split())[:500])
        return
    status, result, error = box.get("out") or (FAILED, {}, "no result")
    _finish(job, status, error=error, result=result)


def _after_failure(job: Dict[str, Any], message: str, unsure: bool = False) -> None:
    if job.get("kind") == "publish":
        _task_step(job, "error", message)
        _task_log(job, f"❌ Publish failed: {message}")
        if unsure:
            _write_attempt(str(job.get("task_id") or ""), {"at": _now(), "unverified": True, "job": job["id"]})
    _finish(job, FAILED, error=message)


def _close_profile(profile: str) -> None:
    if not profile:
        return
    try:
        from tubecli.extensions.content_video import pipeline as P
        P._post("/api/v1/browser/stop", {"profile": profile, "force": False}, timeout=60)
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] could not close the browser of %s: %s", profile, e)


# ── tra hồ sơ / kênh ──────────────────────────────────────────────────────────
def _profile_labels(name: str, row: Optional[Dict] = None) -> List[str]:
    p = row
    if p is None:
        try:
            from tubecli.extensions.browser.profile_manager import get_profile
            p = get_profile(name) or {}
        except Exception:       # noqa: BLE001
            p = {}
    labels = [name]
    ga = p.get("google_account") or {}
    if isinstance(ga, dict):
        email = str(ga.get("email") or "")
        labels += [email, email.split("@")[0] if "@" in email else "", str(ga.get("label") or ""),
                   str(ga.get("name") or ""), str(ga.get("display_name") or "")]
    labels.append(str(p.get("notes") or ""))
    return [x for x in labels if x]


def find_profile(channel: str) -> Tuple[str, List[str]]:
    """Hồ sơ trình duyệt mang tên / bí danh `channel` trong TẤT CẢ hồ sơ của máy: (hồ sơ, []) khi có đúng một hồ sơ
    khớp nhất; ("", [các hồ sơ ngang điểm]) khi mơ hồ; ("", []) khi không có. Cùng luật so với pipeline
    (_ident_key: khớp nguyên, hoặc chứa nhau với ít nhất 4 ký tự) — «Radhika» khớp gmail_singhradhika3976, còn
    «Pawan» / «Jay» thì phải có trong ghi chú hay tài khoản Google của hồ sơ."""
    from tubecli.extensions.content_video import pipeline as P
    want = P._ident_key(channel)
    if not want:
        return "", []
    try:
        from tubecli.extensions.browser.profile_manager import list_profiles
        rows = [r for r in (list_profiles() or []) if isinstance(r, dict) and r.get("name")]
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] cannot list browser profiles: %s", e)
        rows = []
    scored: List[Tuple[int, str]] = []
    for r in rows:
        best = 0
        for lab in _profile_labels(str(r["name"]), r):
            k = P._ident_key(lab)
            if not k:
                continue
            if k == want:
                best = max(best, 3)
            elif (want in k or k in want) and min(len(k), len(want)) >= 4:
                best = max(best, 2)
        if best:
            scored.append((best, str(r["name"])))
    if not scored:
        return "", []
    top = max(s for s, _n in scored)
    names = sorted(n for s, n in scored if s == top)
    return (names[0], []) if len(names) == 1 else ("", names)


def _profile_exists(name: str) -> bool:
    try:
        from tubecli.extensions.browser.profile_manager import get_profile
        return bool(get_profile(name))
    except Exception:       # noqa: BLE001
        return False


# ── văn bản SEO do người gọi đưa ──────────────────────────────────────────────
def clean_tags(tags: Any) -> List[str]:
    if isinstance(tags, str):
        tags = re.split(r"[,\n]", tags)
    out: List[str] = []
    total = 0
    for t in tags or []:
        s = " ".join(str(t or "").replace("#", " ").split())[:60]
        if not s or s.lower() in (o.lower() for o in out):
            continue
        if total + len(s) + 1 > YT_TAGS_MAX:
            break
        out.append(s)
        total += len(s) + 1
    return out


def seo_fields(body: Dict[str, Any]) -> Dict[str, Any]:
    """{title, description, tags} sạch từ thân request — chỉ những trường người gọi THỰC SỰ gửi."""
    out: Dict[str, Any] = {}
    if isinstance(body.get("title"), str) and body["title"].strip():
        out["title"] = " ".join(body["title"].split())[:YT_TITLE_MAX]
    if isinstance(body.get("description"), str) and body["description"].strip():
        out["description"] = body["description"].strip()[:YT_DESC_MAX]
    if body.get("tags"):
        tags = clean_tags(body["tags"])
        if tags:
            out["tags"] = tags
    return out


# ── 1. đăng video của task ────────────────────────────────────────────────────
_VIDEO_LINE_RE = re.compile(r"\*\*Video\*\*:\s*`([^`]+)`")


def _codex():
    from tubecli.extensions.codex.manager import codex_manager

    return codex_manager


def task_video_path(task: Dict[str, Any], ck: Dict[str, Any]) -> str:
    path = str(ck.get("video_path") or "").strip()
    if not path:
        m = _VIDEO_LINE_RE.search(str(task.get("result") or ""))
        path = m.group(1).strip() if m else ""
    return path


def request_publish(task_id: str, body: Optional[Dict[str, Any]] = None, actor: str = "user") -> Dict[str, Any]:
    """Kiểm điều kiện rồi xếp việc đăng. Trả bản public của việc; ném JobError khi từ chối."""
    from tubecli.extensions.content_video import pipeline as P

    body = dict(body or {})
    cm = _codex()
    task = cm.get_task(str(task_id))
    if not task:
        raise JobError(404, "task_not_found", f"Task not found: {task_id}")
    tid = str(task["id"])
    kind = cm.kind_of(tid) or ""
    if kind not in PUBLISH_KINDS:
        raise JobError(400, "not_a_rendered_video", "Only a rendered video task (Auto video / render) can be published "
                                                    f"— this task is “{kind or 'a general task'}”.")
    if task.get("status") != "review":
        raise JobError(409, "not_in_review", f"The task is “{task.get('status')}”, not in review — only a rendered "
                                             "video waiting in review can be published this way.")
    pub = cm.published_video(tid)
    if pub:
        raise JobError(409, "already_published", f"This task already published {pub['url']}.", url=pub["url"],
                       video_id=pub["video_id"])
    active = job_for_task(tid)
    if active and active.get("status") in ACTIVE:
        raise JobError(409, "publish_in_progress", "A publish job for this task is already queued or running.",
                       job=public(active))
    ck = cm.checkpoint_of(tid)
    attempt = ck.get("publish_attempt") if isinstance(ck.get("publish_attempt"), dict) else {}
    if attempt.get("unverified") and not body.get("force"):
        raise JobError(409, "unverified_attempt",
                       "An earlier publish of this task finished without a video link, so it may already be on the "
                       "channel. Check the channel first; send force=true to upload it again.")
    video = task_video_path(task, ck)
    if not video or not os.path.isfile(video):
        raise JobError(409, "no_video_file", "The rendered video file of this task is not on this machine"
                                             + (f" ({video})" if video else "") + " — it cannot be published.")
    from tubecli.core.agent import agent_manager
    agent = agent_manager.get(str(task.get("assignee_id") or "")) if task.get("assignee_id") else None
    if not agent:
        raise JobError(409, "no_agent", "The task has no owning agent, so there is no channel / profile to publish with.")

    privacy = str(body.get("privacy") or getattr(agent, "publish_privacy", "") or "public").strip().lower()
    if privacy not in ("public", "unlisted", "private"):
        raise JobError(400, "bad_privacy", "privacy must be public, unlisted or private.")

    # Kênh / hồ sơ: profile ghi rõ > channel (tên / bí danh, tra trong mọi hồ sơ của máy) > cấu hình của agent.
    profile = str(body.get("profile") or "").strip()
    channel = " ".join(str(body.get("channel") or "").split())
    explicit = False
    if profile:
        if not _profile_exists(profile):
            raise JobError(400, "profile_not_found", f"No browser profile is named “{profile}”.")
        explicit = True
    elif channel:
        if _profile_exists(channel):
            profile, explicit = channel, True
            channel = ""
        else:
            profile, ties = find_profile(channel)
            if not profile:
                raise JobError(400, "channel_not_matched",
                               (f"“{channel}” matches several browser profiles ({', '.join(ties)}) — pass profile=<name>."
                                if ties else
                                f"No browser profile is named, aliased or logged in as “{channel}”. Write the channel "
                                f"name in that profile's notes, or pass profile=<profile name>."))
            explicit = True
    else:
        profile = str(getattr(agent, "publish_profile", "") or "").strip()

    secs = float(P.media_seconds(video) or 0)
    if bool(getattr(agent, "publish_unverified", False)) and secs > P.UNVERIFIED_MAX_SEC:
        raise JobError(422, "too_long_for_unverified_channel",
                       f"The video is {P._mmss(secs)} long and this agent's channel is marked “not verified” — YouTube "
                       f"rejects videos over 15 minutes from such channels. Verify the channel ({P.VERIFY_URL}) and "
                       "untick “Channel not verified”, or shorten the video.", seconds=round(secs))

    # Trần mỗi ngày của agent (publish_max_per_day) áp cả cho lượt đăng TAY: 74 video tồn ở review mà đăng dồn một ngày
    # là thứ làm kênh bị đánh dấu spam. Tính video đã lên hôm nay + việc đăng còn trong hàng đợi của cùng agent. Hẹn theo
    # khung giờ (when=slots) thì YouTube tự rải ngày nên không chặn; ignore_daily_limit=true là lời chủ nói «cứ đăng».
    when_slots = str(body.get("when") or "").strip().lower() == "slots"
    limit = int(getattr(agent, "publish_max_per_day", 2) or 0)
    if limit and not when_slots and not body.get("ignore_daily_limit"):
        try:
            from . import autopublish
            today = int(autopublish.get_mark(str(agent.id)).get("published_today") or 0)
        except Exception:       # noqa: BLE001
            today = 0
        with _LOCK:
            waiting = sum(1 for j in _jobs.values() if j.get("kind") == "publish" and j.get("agent_id") == str(agent.id)
                          and j.get("status") in ACTIVE)
        if today + waiting >= limit:
            raise JobError(409, "daily_limit_reached",
                           f"This agent's channel already has {today} video(s) published today and {waiting} waiting to "
                           f"publish — its limit is {limit} a day. Try tomorrow, pass when=\"slots\" to schedule it, raise "
                           "the limit (PATCH /api/v1/codex/autopublish/{agent_id} daily_limit), or pass "
                           "ignore_daily_limit=true.", published_today=today, queued=waiting, daily_limit=limit)

    ignored = [k for k in ("category_id",) if body.get(k) not in (None, "")]
    job = _enqueue({
        "kind": "publish", "task_id": tid, "task_seq": task.get("seq"), "actor": str(actor or "user")[:40],
        "agent_id": str(agent.id),
        "profile": profile, "channel": channel, "explicit_profile": explicit, "privacy": privacy,
        "when": "slots" if str(body.get("when") or "").strip().lower() == "slots" else "now",
        "seo": seo_fields(body), "video_path": video, "seconds": round(secs),
        "requested": {"ignored": ignored, **{k: body[k] for k in ("title", "channel", "profile", "privacy") if body.get(k)}},
    })
    cm.append_event(tid, "log", f"📤 Publish requested by {actor} — queued (one browser at a time)", actor=ACTOR)
    return public(job)


_STUDIO_VIDEO_RE = re.compile(r"^https?://studio\.youtube\.com/video/([A-Za-z0-9_-]{6,20})(?![A-Za-z0-9_-])")


def mark_published(task_id: str, body: Optional[Dict[str, Any]] = None, actor: str = "user") -> Dict[str, Any]:
    """Video của task ĐÃ được đăng tay ngoài TubeCLI (15/11/2026 — #206, #207 trên contabo đăng bằng script
    youtube_upload chạy tay): ghi link vào task, REVIEW → DONE, tính vào trần ngày của agent. KHÔNG mở trình duyệt, KHÔNG
    tải gì lên. Bắt buộc có link video thật (youtu.be/<id>, watch?v=<id>, studio.youtube.com/video/<id>) hoặc video_id —
    không có link thì không ai kiểm được, và các lưới chống đăng trùng phía sau dựa vào chính id này."""
    from tubecli.extensions.content_video import pipeline as P

    body = dict(body or {})
    cm = _codex()
    task = cm.get_task(str(task_id))
    if not task:
        raise JobError(404, "task_not_found", f"Task not found: {task_id}")
    tid = str(task["id"])
    kind = cm.kind_of(tid) or ""
    if kind not in PUBLISH_KINDS:
        raise JobError(400, "not_a_rendered_video", "Only a rendered video task (Auto video / render) can be marked "
                                                    f"as published — this task is “{kind or 'a general task'}”.")
    pub = cm.published_video(tid)
    if pub:
        raise JobError(409, "already_published", f"This task already published {pub['url']}.", url=pub["url"],
                       video_id=pub["video_id"])
    if task.get("status") != "review":
        raise JobError(409, "not_in_review", f"The task is “{task.get('status')}”, not in review.")
    active = job_for_task(tid)
    if active and active.get("status") in ACTIVE:
        raise JobError(409, "publish_in_progress", "A publish job for this task is queued or running — wait for it.",
                       job=public(active))
    raw = str(body.get("url") or "").strip()
    vid = P.youtube_video_id(raw)
    if not vid and raw:
        m = _STUDIO_VIDEO_RE.match(raw)
        vid = m.group(1) if m else ""
    if not vid:
        cand = str(body.get("video_id") or "").strip()
        vid = cand if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", cand) else ""
    if not vid:
        raise JobError(400, "video_link_required",
                       "Send the link of the video on YouTube (url: https://youtu.be/<id>, a watch?v= link, or "
                       "https://studio.youtube.com/video/<id>) or its video_id. A help link such as "
                       "support.google.com/youtube?p=upload_videos is not a video link — open YouTube Studio › Content "
                       "and copy the video's link.")
    url = f"https://youtu.be/{vid}"
    other = task_of_video(vid)
    if other and str(other.get("id")) != tid:
        raise JobError(409, "video_belongs_to_another_task",
                       f"Video {vid} is already recorded on task #{other.get('seq', '?')}.", task=other.get("seq"))
    channel = str(body.get("channel") or "").strip()[:120]
    scheduled = str(body.get("scheduled") or "").strip()[:60]
    published = {"video_id": vid, "url": url, "title": str(body.get("title") or task.get("title") or "")[:200],
                 "channel_name": channel, "by_hand": True, "at": _now()}
    cm.append_event(tid, "log", "checkpoint", actor=str(actor or ACTOR), data={"checkpoint": {"published": published}})
    try:
        from . import autopublish
        counted = autopublish.count_published(str(task.get("assignee_id") or ""), url, tid)
    except Exception as e:      # noqa: BLE001
        counted = f"not counted: {e}"
    line = (f"- **Published** (by hand, outside TubeCLI): {url}"
            + (f" (scheduled {scheduled})" if scheduled else "") + (f" → {channel}" if channel else ""))
    cm._settle(tid, "done", str(actor or ACTOR), message=f"Marked as published: {url}",
               updates={"result": result_with_link(str(task.get("result") or ""), line), "finished_at": cm_now()})
    return {"task": task.get("seq"), "status": "done", "video_id": vid, "url": url, "daily_limit": counted}


def _task_log(job: Dict[str, Any], message: str) -> None:
    try:
        _codex().append_event(str(job.get("task_id") or ""), "log", message[:1000], actor=ACTOR)
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] cannot log to the task: %s", e)


def _task_step(job: Dict[str, Any], status: str, message: str) -> None:
    try:
        _codex().report_step(str(job.get("task_id") or ""), "publish", status, message[:300], "Publish to YouTube")
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] cannot update the publish step: %s", e)


def _write_attempt(task_id: str, attempt: Dict[str, Any]) -> None:
    """Ghi dấu «đã thử đăng mà chưa xác minh được» vào checkpoint — lần đăng sau phải force=true."""
    if not task_id:
        return
    try:
        _codex().append_event(task_id, "log", "checkpoint", actor=ACTOR,
                              data={"checkpoint": {"publish_attempt": attempt}})
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] cannot checkpoint the attempt: %s", e)


def result_with_link(result: str, line: str) -> str:
    """Chèn dòng «Published» ngay dưới tiêu đề kết quả (thay dòng Published cũ nếu có)."""
    rows = [ln for ln in str(result or "").split("\n") if not ln.startswith("- **Published**")]
    at = next((i + 1 for i, ln in enumerate(rows) if ln.startswith("- ")), None)
    if at is None:
        return (str(result or "").rstrip() + "\n\n" + line).strip()
    rows.insert(at - 1, line)
    return "\n".join(rows)


def _run_publish(job: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str]:
    from tubecli.core.agent import agent_manager
    from tubecli.extensions.content_video import pipeline as P

    cm = _codex()
    tid = str(job["task_id"])
    task = cm.get_task(tid)
    if not task or task.get("status") != "review":
        raise RuntimeError("The task left review while the job was waiting — nothing was published.")
    if cm.published_video(tid):
        raise RuntimeError("The task was published meanwhile — nothing was uploaded.")
    agent = agent_manager.get(str(task.get("assignee_id") or ""))
    if not agent:
        raise RuntimeError("The owning agent no longer exists.")
    ck = cm.checkpoint_of(tid)
    video = str(job.get("video_path") or "")
    if not os.path.isfile(video):
        raise RuntimeError(f"The video file is gone ({video}).")

    def say(step: str, status: str, message: str = "", progress: Any = None) -> None:
        if message:
            _patch(job["id"], progress=message[:200])
            _task_step(job, "running", message)

    meta = task.get("meta") or {}
    seo = job.get("seo") or {}
    thumb = str(ck.get("thumbnail_path") or "")
    state: Dict[str, Any] = {
        "agent": agent, "task_id": tid, "checkpoint": ck, "corpus": [], "videos": [], "warnings": [],
        "_say": say, "_cancelled": lambda: False,
        "video_path": video, "title": seo.get("title") or str(ck.get("title") or task.get("title") or ""),
        "script": str(ck.get("script") or ""), "language": str(ck.get("language") or meta.get("language") or ""),
        "episode_id": ck.get("episode_id") or meta.get("episode_id"), "drama_id": ck.get("drama_id") or meta.get("drama_id"),
        "seo_sources": [r for r in (ck.get("seo_sources") or []) if isinstance(r, dict)],
        "thumbnail_path": thumb if (thumb and os.path.isfile(thumb)
                                    and bool(getattr(agent, "publish_thumbnail", True))) else "",
    }
    options: Dict[str, Any] = {
        "publish": True, "publish_method": "script", "publish_privacy": job.get("privacy") or "public",
        "publish_profile": str(job.get("profile") or ""),
        "publish_channel_id": "" if job.get("channel") else str(getattr(agent, "publish_channel_id", "") or ""),
        "publish_channel_name": str(job.get("channel") or getattr(agent, "publish_channel_name", "") or ""),
        "publish_token_id": "", "publish_monetize": bool(getattr(agent, "publish_monetize", False)),
        "publish_unverified": bool(getattr(agent, "publish_unverified", False)),
        "publish_when": job.get("when") or "now",
        "publish_slots": str(getattr(agent, "publish_slots", "") or ""),
        "publish_tz": str(getattr(agent, "publish_tz", "") or ""),
        "publish_tz_offset": getattr(agent, "publish_tz_offset", ""),
        "seo_title": seo.get("title") or "", "seo_description": seo.get("description") or "",
        "seo_tags": seo.get("tags") or [],
    }
    if job.get("explicit_profile"):
        # Người gọi CHỈ ĐÍCH DANH hồ sơ (profile=…, hay channel đã tra ra đúng một hồ sơ): đó là lựa chọn có chủ ý —
        # không để phép so «tên kênh ↔ hồ sơ» của _resolve_channel chặn lại lần nữa.
        state["channel_resolved"] = {"id": options["publish_channel_id"], "name": options["publish_channel_name"],
                                     "token_id": "", "about": ""}
    profile = P._login_profile(agent, options)
    _patch(job["id"], profile=profile)          # _run đóng đúng hồ sơ này khi xong / lỗi / quá giờ
    _task_step(job, "running", f"publishing as “{profile}”")
    P._publish_now(state, options)

    pub = dict(state.get("published") or {})
    vid = str(pub.get("video_id") or "").strip()
    warnings = [str(w) for w in state.get("warnings") or []]
    result = {"video_id": vid, "url": str(pub.get("url") or ""), "title": str(pub.get("title") or state["title"]),
              "privacy": pub.get("privacy"), "channel": pub.get("channel_name") or "", "profile": profile,
              "scheduled": pub.get("scheduled_label") or "", "warnings": warnings[:10]}
    if state.get("publish_unverified_url") or not vid or not P.youtube_video_id(result["url"]):
        # Không cầm được link video: KHÔNG ghi là đã đăng, task ở lại Review.
        _write_attempt(tid, {"at": _now(), "unverified": True, "job": job["id"], "title": result["title"]})
        note = ("UNVERIFIED — YouTube Studio finished but no video link (youtu.be/<id>) was returned. Check the channel "
                "before publishing this task again.")
        _task_step(job, "warning", note)
        _task_log(job, f"⚠️ Publish {note}")
        return UNVERIFIED, result, note
    P._remember_published(state)
    try:        # tính vào trần ngày của agent (không dời mốc kho — video này dựng từ cửa sổ bài đã cũ)
        from . import autopublish
        autopublish.count_published(str(job.get("agent_id") or task.get("assignee_id") or ""), result["url"], tid)
    except Exception as e:      # noqa: BLE001
        logger.info("[PublishQueue] could not count the publish toward the daily limit: %s", e)
    line = (f"- **Published**: {result['url']} "
            f"({'scheduled — private until then' if result['scheduled'] else result['privacy'] or ''})"
            + (f" → {result['channel']}" if result["channel"] else ""))
    new_result = result_with_link(str(task.get("result") or ""), line)
    _task_step(job, "success", result["url"])
    try:
        # REVIEW → DONE bằng _settle: KHÔNG gọi hook on_accept (hook của task kế hoạch xếp một lượt dựng + đăng nữa).
        cm._settle(tid, "done", str(job.get("actor") or ACTOR), message=f"Published: {result['url']}",
                   updates={"result": new_result, "finished_at": cm_now()})
    except Exception as e:      # noqa: BLE001 — video ĐÃ lên kênh: không biến thành «hỏng» vì cái sổ
        logger.warning("[PublishQueue] published but could not close task %s: %s", tid, e)
        result["warnings"].append(f"Published, but the task could not be moved to done: {e}")
    return DONE, result, ""


def cm_now() -> str:
    import datetime
    return datetime.datetime.now().astimezone().isoformat()


# ── 3. sửa SEO video đã đăng ──────────────────────────────────────────────────
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
NOT_APPLIED_REASON = ("not set by the YouTube Studio script yet (the category / audio-language dropdowns are not "
                      "automated) — change it by hand in Studio")


def task_of_video(video_id: str) -> Optional[Dict[str, Any]]:
    """Task content_video đã đăng video này (theo checkpoint.published.video_id), hay None."""
    cm = _codex()
    try:
        rows = (cm.list_tasks(status="done", limit=500) or []) + (cm.list_tasks(status="review", limit=500) or [])
    except Exception:       # noqa: BLE001
        rows = []
    for t in rows:
        try:
            if (cm.published_video(str(t.get("id") or "")) or {}).get("video_id") == video_id:
                return t
        except Exception:       # noqa: BLE001
            continue
    return None


def request_seo_edit(video_id: str, body: Optional[Dict[str, Any]] = None, actor: str = "user") -> Dict[str, Any]:
    body = dict(body or {})
    video_id = str(video_id or "").strip()
    if not _ID_RE.match(video_id):
        raise JobError(400, "bad_video_id", "video_id must be the 11-character YouTube video id.")
    fields = seo_fields(body)
    not_applied = [k for k in ("category_id", "default_audio_language") if body.get(k) not in (None, "")]
    if not fields:
        raise JobError(400, "nothing_to_change",
                       "Send at least one of title, description, tags."
                       + (f" ({', '.join(not_applied)}: {NOT_APPLIED_REASON}.)" if not_applied else ""),
                       not_applied=not_applied)
    profile = str(body.get("profile") or "").strip()
    channel = " ".join(str(body.get("channel") or "").split())
    task = None
    if profile:
        if not _profile_exists(profile):
            raise JobError(400, "profile_not_found", f"No browser profile is named “{profile}”.")
    elif channel:
        if _profile_exists(channel):
            profile = channel
        else:
            profile, ties = find_profile(channel)
            if not profile:
                raise JobError(400, "channel_not_matched",
                               f"“{channel}” matches several browser profiles ({', '.join(ties)}) — pass profile=<name>."
                               if ties else f"No browser profile is named, aliased or logged in as “{channel}”.")
    else:
        task = task_of_video(video_id)
        if task:
            from tubecli.core.agent import agent_manager
            agent = agent_manager.get(str(task.get("assignee_id") or ""))
            profile = str(getattr(agent, "publish_profile", "") or "").strip() if agent else ""
        if not profile:
            raise JobError(400, "profile_required",
                           "This video was not published by a task on this machine (or its agent has no publish "
                           "profile) — pass profile=<browser profile> or channel=<channel name>.")
    with _LOCK:
        _load()
        dup = next((j for j in _jobs.values() if j.get("kind") == "seo_edit" and j.get("video_id") == video_id
                    and j.get("status") in ACTIVE), None)
    if dup:
        raise JobError(409, "edit_in_progress", "An edit of this video is already queued or running.", job=public(dup))
    job = _enqueue({"kind": "seo_edit", "video_id": video_id, "profile": profile, "channel": channel,
                    "actor": str(actor or "user")[:40], "seo": fields, "task_id": str((task or {}).get("id") or ""),
                    "task_seq": (task or {}).get("seq"),
                    "requested": {"fields": sorted(fields), "not_applied": not_applied}})
    out = public(job)
    if not_applied:
        out["not_applied"] = {k: NOT_APPLIED_REASON for k in not_applied}
    return out


def edit_variables(video_id: str, fields: Dict[str, Any]) -> Dict[str, str]:
    """Biến cho script youtube_edit_video — cờ set_* = '1' chỉ cho trường người gọi gửi."""
    tags = fields.get("tags") or []
    return {
        "video_id": video_id,
        "edit_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "upload_url": f"https://studio.youtube.com/video/{video_id}/edit",     # khung live mở thẳng trang này
        "set_title": "1" if fields.get("title") else "0", "title": str(fields.get("title") or ""),
        "set_description": "1" if fields.get("description") else "0", "description": str(fields.get("description") or ""),
        "set_tags": "1" if tags else "0", "tags_csv": ",".join(tags),
    }


def read_edit_report(res: Any) -> Dict[str, Any]:
    """Báo cáo của bước cuối script (biến t2_edit): {video_ok, saved, applied:[…], skipped:[…], title, note}."""
    raw = res.get("t2_edit") if hasattr(res, "get") else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:       # noqa: BLE001
            raw = {"note": raw}
    return raw if isinstance(raw, dict) else {}


def _run_seo_edit(job: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str]:
    from tubecli.extensions.content_video import pipeline as P

    profile = str(job.get("profile") or "")
    fields = job.get("seo") or {}
    if P.ensure_upload_script(EDIT_SCRIPT):
        logger.info("[PublishQueue] installed the browser script %s", EDIT_SCRIPT)
    state = {"_say": lambda step, status, message="", progress=None: _patch(job["id"], progress=str(message)[:200]),
             "_cancelled": lambda: False}
    res = P._run_upload_script(state, {}, EDIT_SCRIPT, edit_variables(str(job["video_id"]), fields), profile)
    if not getattr(res, "success", False):
        tail = " ".join(str(getattr(res, "log", "") or "").split())[-300:]
        raise RuntimeError("The YouTube Studio edit script did not finish" + (f" — {tail}" if tail else "")
                           + ". Nothing is known to have been saved.")
    rep = read_edit_report(res)
    applied = [str(x) for x in (rep.get("applied") or [])]
    result = {"video_id": job["video_id"], "url": f"https://youtu.be/{job['video_id']}", "profile": profile,
              "applied": applied, "skipped": rep.get("skipped") or [], "saved": bool(rep.get("saved")),
              "title_now": str(rep.get("title") or ""), "note": str(rep.get("note") or "")[:300]}
    if not rep or not rep.get("video_ok"):
        return FAILED, result, ("The Studio page did not show this video in this profile (wrong channel, signed out, "
                                "or the page changed) — nothing was typed.")
    if not rep.get("saved") or not applied:
        return UNVERIFIED, result, ("The script ran but YouTube Studio did not confirm a save"
                                    + (f" ({result['note']})" if result["note"] else "") + " — open the video and check.")
    return DONE, result, ""
