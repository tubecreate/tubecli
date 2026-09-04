"""Auto-publish trigger — a browsing run ends, a video goes up.

The chain the founder asked for: "mỗi lần thu thập thành công thì … viết nội
dung mới, đăng lên kênh youtube đã được cấp api", with no review step in the
middle ("đăng luôn khỏi duyệt"). This module is the *trigger* half — it decides
whether a finished run has earned a video and queues ONE codex task. Writing the
script, rendering, the SEO and the upload all live in pipeline.py.

Where it is called from: the very end of
browser/process_manager.py::_record_run_end, the single place every scheduled
agent run ends. That is a watcher thread with no error handling of its own, so
**nothing here may raise**: every public function catches its own exceptions and
returns a reason string instead.

Why a high-water mark and not "did this run scrape something":

  * `work` (the actions/steps summary) is empty on scheduled runs — they set
    scripted_only, so open.js prints neither "Step:" lines nor "Actions: N" and
    run_log stores no work at all. Gating on it would mean never firing.
  * Counting log lines is worse: extract_content.js prints its COMPLETE banner
    even for a URL it skipped as a duplicate.

So "is there anything new?" is asked of the corpus itself: rows in scraped_store
with real body text whose scraped_at is newer than the last mark we published
from. That mark is per agent and lives in this module's little JSON store,
because pipeline.py already knows how to *use* a high_water_prev (it filters the
corpus and stamps a new one) but nothing has ever *persisted* one — a repo-wide
grep for high_water outside pipeline.py returns zero hits.

Cái mốc ấy chỉ nhúc nhích khi một video ĐÃ THẬT SỰ lên kênh. Lúc xếp việc chỉ
có `high_water_pending` được ghi (cửa chống dội đọc nó); `high_water` và bộ đếm
ngày đợi pipeline gọi commit_published() ngược về. Dời mốc ngay lúc xếp thì mọi
hỏng hóc phía sau — task lỗi, dựng chết, upload trượt, server khởi động lại —
đều âm thầm phá huỷ đúng cửa sổ corpus đó: những bài ấy không bao giờ được đăng
mà cũng không bao giờ được đếm lại. Bên thua thiệt phải là "làm lại", không
phải "mất hẳn".

Chuỗi này chỉ dành cho lượt chạy THEO LỊCH: nút "Chạy thử" cũng đi qua đúng lối
này (nó mint một run_id thật), nên process_manager gửi kèm `trigger` và lượt tay
bị chặn ngay ở cửa đầu tiên.

No review gate, because there is nothing to review. The normal two-stage
pipeline (plan → a human reads the script → render) exists so somebody can stop
a bad script before it becomes a video. Nobody reads this one, so the stages are
not split at all: create_auto_task() queues ONE task of kind content_video.auto
that runs the whole chain — corpus, script, images, voice, mp4, upload — and by
the time codex parks it in REVIEW the video is already up. The review box is a
record of what went out, not a gate somebody has to open.

The rejected alternative was a daemon thread that watched the plan task and
pressed Accept for it. It worked, but it faked a human decision to get past a
gate; removing the gate is the honest version of the same intent, and it costs
one fewer thread, no restart recovery and no 90-minute watchdog.
"""
import datetime
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Tuple

logger = logging.getLogger("ContentVideo")

STORE_FILE = "autopublish.json"

# Kết cục được coi là "lượt chạy có thu hoạch". timeout_killed nằm trong này vì
# phiên hẹn giờ CỐ Ý chạy tới hết giờ rồi bị dừng — đó là cái kết bình thường
# chứ không phải hỏng. timeout_kill_failed thì không: tiến trình còn sống, chưa
# ai biết nó đang làm gì. Dù sao ngưỡng thật vẫn là số bài mới, không phải cái
# danh sách này.
OK_OUTCOMES = ("completed", "partial", "timeout_killed")

# Hai lượt kết thúc sát nhau (agent chạy nhiều hồ sơ) không được thành hai video.
DEBOUNCE_SEC = 10 * 60
# Trạng thái codex nghĩa là "việc trước còn dở" — còn dở thì đừng xếp thêm.
UNFINISHED = ("pending_approval", "queued", "running", "review")
JOB_LABEL = "Auto publish"
ACTOR = "autopublish"

# Chuỗi này là "mỗi lần thu thập THEO LỊCH", không phải "mỗi lần ai đó bấm Chạy
# thử". Từ vựng thật trong repo chỉ có hai giá trị: scheduler + mặc định của
# run_agent_routine gửi "schedule", nút Run now gửi "manual"; các tên còn lại
# nhận cho rộng phòng khi có nguồn lịch mới.
SCHEDULED_TRIGGERS = ("schedule", "scheduled", "routine", "cron", "timer")

# Ghi/đọc sổ dưới một khoá: nhiều watcher browser cùng kết thúc một lúc là
# chuyện thường.
_LOCK = threading.RLock()


# ── The little store ─────────────────────────────────────────────────
#
# Shape, per agent id:
#     {"high_water": ISO, "high_water_pending": ISO, "published_today": int,
#      "day": "YYYY-MM-DD", "last_task_id": str, "last_fired_at": epoch,
#      "last_commit_key": str, "last_video_url": str}
#
# HAI cái mốc, và đó là chủ ý. `high_water_pending` được ghi lúc XẾP VIỆC và
# chỉ cửa chống dội đọc nó; `high_water` chỉ nhúc nhích khi một video ĐÃ THẬT
# SỰ lên kênh (commit_published). Gộp chúng làm một — dời mốc ngay lúc xếp —
# nghĩa là mọi hỏng hóc phía sau (task lỗi, dựng chết, upload trượt, server
# khởi động lại) đều âm thầm phá huỷ đúng cửa sổ corpus đó: những bài ấy không
# bao giờ được đăng, mà cũng không bao giờ được đếm lại.
#
# Best-effort like run_log: a store that can break a browsing run is worse than
# no store. A read that fails returns {}, a write that fails is logged and
# dropped — the next run simply re-counts and may re-publish, which is the safe
# direction for a mark whose only job is to stop duplicates.

def _store_path():
    from tubecli.config import ext_data_path

    return ext_data_path("content_video", STORE_FILE)


def _read_all() -> Dict[str, Dict[str, Any]]:
    """Everything in the store, or {} when it is missing, torn or foreign."""
    try:
        path = _store_path()
        if not os.path.isfile(str(path)):
            return {}
        with open(str(path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        # Một entry hỏng không được làm mù cả sổ của những agent khác.
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:
        logger.warning("[AutoPublish] store unreadable (%s) — starting from empty", e)
        return {}


def _write_all(data: Dict[str, Dict[str, Any]]) -> bool:
    """tmp + os.replace, so a kill mid-write cannot leave half a store. Never
    raises."""
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
        return True
    except Exception as e:
        logger.warning("[AutoPublish] could not write the store (%s)", e)
        return False


def _today() -> str:
    return datetime.date.today().isoformat()


def get_mark(agent_id: str) -> Dict[str, Any]:
    """This agent's row, with every key present and typed."""
    try:
        row = _read_all().get(str(agent_id)) or {}
    except Exception:
        row = {}
    day = str(row.get("day") or "")
    try:
        published = int(row.get("published_today") or 0)
    except (TypeError, ValueError):
        published = 0
    try:
        fired = float(row.get("last_fired_at") or 0)
    except (TypeError, ValueError):
        fired = 0.0
    # Bộ đếm là "của ngày `day`". Sang ngày khác nó vô nghĩa, nên quy về 0 ngay
    # tại chỗ ĐỌC — không nơi gọi nào phải nhớ tự reset.
    if day != _today():
        published, day = 0, _today()
    return {
        "high_water": str(row.get("high_water") or ""),
        "high_water_pending": str(row.get("high_water_pending") or ""),
        "published_today": published,
        "day": day,
        "last_task_id": str(row.get("last_task_id") or ""),
        "last_fired_at": fired,
        "last_commit_key": str(row.get("last_commit_key") or ""),
        "last_video_url": str(row.get("last_video_url") or ""),
    }


def save_mark(agent_id: str, **fields: Any) -> bool:
    """Merge `fields` into this agent's row. Never raises."""
    aid = str(agent_id or "")
    if not aid:
        return False
    with _LOCK:
        data = _read_all()
        row = dict(data.get(aid) or {})
        row.update(fields)
        data[aid] = row
        return _write_all(data)


def commit_published(agent_id: str, high_water: str = "", video_url: str = "",
                     task_id: str = "") -> str:
    """MỘT video vừa thật sự lên kênh → bây giờ mới dời mốc và tính vào trần ngày.

    pipeline.py gọi hàm này ngay sau khi uploader trả về success. Cho tới lúc
    đó, cửa sổ corpus vẫn còn nguyên: task hỏng ở bất cứ đâu thì lượt chạy sau
    đếm lại đúng những bài ấy và thử lại.

    Vô hại khi gọi lại: cùng một task (hay cùng một link video) commit lần thứ
    hai chỉ được tính một lần — một lượt chạy lại sau khi khởi động không được
    ăn thêm một suất trong trần ngày. Không bao giờ ném: nó chạy trong luồng
    thợ của codex, ngay sau một lượt đăng ĐÃ THÀNH CÔNG.
    """
    aid = str(agent_id or "")
    if not aid:
        return "no agent id"
    try:
        with _LOCK:
            row = get_mark(aid)
            key = str(task_id or "") or str(video_url or "")
            if key and row["last_commit_key"] == key:
                return "already counted"
            hw = str(high_water or "") or row["high_water_pending"]
            fields: Dict[str, Any] = {
                "published_today": row["published_today"] + 1,
                "day": _today(),
                "last_video_url": str(video_url or ""),
            }
            if key:
                fields["last_commit_key"] = key
            # Mốc chỉ đi tới, không đi lui: hai task chạy song song về đích lệch
            # thứ tự cũng không được kéo mốc về quá khứ và làm cả kho mới hiện lại.
            if hw and hw > row["high_water"]:
                fields["high_water"] = hw
            save_mark(aid, **fields)
            return "counted %d (high_water=%s)" % (fields["published_today"],
                                                   fields.get("high_water", row["high_water"]))
    except Exception as e:
        logger.error("[AutoPublish] could not commit the mark for %s (%s)", aid, e, exc_info=True)
        return "error: %s" % e


# ── Counting what is new ─────────────────────────────────────────────

def _scope(agent) -> list:
    """Profiles this agent may read.

    Delegated to pipeline._agent_scope on purpose: the trigger has to count over
    EXACTLY the profiles the pipeline will later gather from, or the threshold
    means nothing. One import beats a second copy that drifts.
    """
    try:
        from tubecli.extensions.content_video.pipeline import _agent_scope

        return _agent_scope(agent)
    except Exception as e:
        logger.debug("[AutoPublish] falling back to allowed_profiles (%s)", e)
        return [str(p) for p in (getattr(agent, "allowed_profiles", None) or []) if p]


def scan_new(agent, high_water: str = "") -> Tuple[int, str]:
    """(how many harvested pages are newer than `high_water`, the newest stamp).

    only_with_content=True on purpose: scraped_store holds a row for every page
    the browser VISITED, and most visits are search-result pages the scraper
    skipped. "Đủ bài để làm video" means text on disk, not URLs walked past.

    With no mark yet (the toggle was only just switched on) ONLY TODAY counts.
    Otherwise the first run after arming would sweep up the whole backlog and
    publish a video about news from last March.

    Quét qua pipeline.scan_window, tức LẬT TRANG THEO CHIỀU GIẢM. Cách cũ —
    một lần hỏi order="asc", limit=500 — nhận về 500 dòng CŨ NHẤT, nên một hồ
    sơ quá 500 dòng là cái mốc không bao giờ thấy bài mới nữa.
    """
    try:
        from tubecli.core import scraped_store
        from tubecli.extensions.content_video.pipeline import scan_window

        hw = str(high_water or "")
        rows = scan_window(
            agent_id=str(getattr(agent, "id", "") or ""),
            allowed_profiles=_scope(agent),
            hw_prev=hw,
            day=None if hw else "today",
            only_with_content=True,
        )
        newest, count = "", 0
        for item in rows:
            stamp = str(item.get("scraped_at") or "")
            # Dòng không có mốc đọc được thì KHÔNG được tính: đếm nó vào mà
            # `newest` vẫn rỗng nghĩa là mốc đứng yên, và đúng cái corpus ấy
            # châm ngòi lại ở mọi lượt chạy sau cho tới khi cạn trần ngày.
            if scraped_store._parse_utc(stamp) is None:
                continue
            count += 1
            if stamp > newest:
                newest = stamp
        return count, newest
    except Exception as e:
        logger.warning("[AutoPublish] could not read the corpus (%s)", e)
        return 0, ""


def new_pages(agent, high_water: str = "") -> int:
    """How many harvested pages are newer than `high_water`."""
    return scan_new(agent, high_water)[0]


# ── The approval bridge ──────────────────────────────────────────────

def _codex():
    from tubecli.extensions.codex.manager import codex_manager

    return codex_manager


def _task_status(task_id: str) -> str:
    """Trạng thái codex của một task, thường hoá; "" khi không tra được.

    Cửa chống dội hỏi hàm này: việc lần trước còn dang dở thì đừng xếp thêm.
    Không tra được (task bị xoá, codex chưa sẵn sàng) trả "" — coi như đã xong,
    vì chặn mãi vì một câu hỏi không có đáp án thì tệ hơn là thử lại.
    """
    try:
        task = _codex().get_task(str(task_id or ""))
        return str((task or {}).get("status") or "").strip().lower()
    except Exception as e:
        logger.debug("[AutoPublish] could not read task %s (%s)", task_id, e)
        return ""

# ── The trigger ──────────────────────────────────────────────────────

def maybe_publish_after_run(agent_id: str, run_id: str = "", outcome: str = "",
                            trigger: str = "") -> str:
    """A scheduled run just ended — publish a video if it earned one.

    `trigger` là chữ mà run_log ghi cho lượt chạy: "schedule" (bộ hẹn giờ) hay
    "manual" (nút Chạy thử). Chuỗi này chỉ dành cho lượt THEO LỊCH.

    Returns a short, greppable reason for the caller's log. NEVER raises: the
    caller is a browser watcher thread whose real job is closing out a run.
    """
    try:
        return _maybe_publish(str(agent_id or ""), str(run_id or ""), str(outcome or ""),
                              str(trigger or ""))
    except Exception as e:
        logger.error("[AutoPublish] trigger blew up (%s)", e, exc_info=True)
        return "error: %s" % e


def _maybe_publish(agent_id: str, run_id: str, outcome: str, trigger: str = "") -> str:
    # Rẻ trước, đắt sau: chỉ khi mọi cánh cửa cấu hình đã mở mới đi đọc kho.
    if outcome not in OK_OUTCOMES:
        return "skip: outcome=%s" % (outcome or "?")
    # trigger rỗng = NGƯỜI GỌI CHƯA NÓI, không phải "lượt thủ công": phía gọi
    # (process_manager) mới đang được nối dây. Chọn hướng dễ dãi có chủ ý, vì
    # mặc định chặn sẽ TẮT âm thầm cả chuỗi tự đăng nếu nửa kia lên chậm hơn —
    # còn nhận nhầm một lượt bấm tay thì chỉ là một video thừa, vẫn bị trần
    # ngày và cửa chống dội chặn lại.
    if trigger and trigger.strip().lower() not in SCHEDULED_TRIGGERS:
        return "skip: manual run (trigger=%s)" % trigger.strip().lower()
    if not agent_id:
        return "skip: no agent id"

    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(agent_id)
    if not agent:
        return "skip: agent %s not found" % agent_id
    if not getattr(agent, "auto_publish", False):
        return "skip: auto-publish off"

    # Công tắc bật mà chính extension bị tắt/gỡ thì không có gì chạy được cả:
    # create_auto_task sẽ xếp một task mà executor không có nhánh nào nhận.
    # {} = không hỏi được danh sách extension → đừng chặn vì một câu không có
    # đáp án.
    try:
        from tubecli.extensions.content_video.capabilities import installed_extensions

        installed = installed_extensions() or {}
    except Exception as e:
        logger.debug("[AutoPublish] could not list extensions (%s)", e)
        installed = {}
    if installed and not installed.get("content_video"):
        return "skip: the Content Video extension is %s" % (
            "disabled" if "content_video" in installed else "not installed")

    token_id = str(getattr(agent, "publish_token_id", "") or "")
    channel_id = str(getattr(agent, "publish_channel_id", "") or "")
    if not token_id or not channel_id:
        # Công tắc bật mà chưa chọn kênh là LỖI CẤU HÌNH, không phải "chưa tới
        # lượt": người dùng đang tin rằng video vẫn được đăng. Kêu to.
        missing = "token" if not token_id else "channel"
        logger.warning("[AutoPublish] agent %s has auto-publish ON but no YouTube %s "
                       "— pick a channel in the agent's Data collection tab",
                       getattr(agent, "name", "") or agent_id, missing)
        return "skip: auto-publish armed but no YouTube %s chosen" % missing

    # Từ đây tới lúc ghi sổ là MỘT quyết định, và nó phải nguyên khối. Trước đây
    # khoá chỉ được giữ bên trong save_mark, nên hai lượt chạy của cùng một agent
    # kết thúc sát nhau (agent nhiều hồ sơ — đúng cái tình huống cửa chống dội
    # sinh ra để chặn) cùng đọc một cái sổ cũ, cùng qua trần ngày, cùng qua cửa
    # chống dội, và xếp hai task. Giữ khoá trọn cả đoạn thì lượt thứ hai đọc sổ
    # sau khi lượt thứ nhất đã ghi xong.
    with _LOCK:
        mark = get_mark(agent_id)
        cap = int(getattr(agent, "publish_max_per_day", 2) or 0)
        if mark["published_today"] >= cap:
            return "skip: daily cap reached (%d/%d)" % (mark["published_today"], cap)

        if mark["last_fired_at"] and (time.time() - mark["last_fired_at"]) < DEBOUNCE_SEC:
            # Chỉ chặn khi việc lần trước CHƯA xong. Hai phiên browser của cùng một
            # agent kết thúc cách nhau vài giây là bình thường; hai video thì không.
            # Còn nếu task trước đã done/failed thì chẳng có gì để trùng.
            if _task_status(mark["last_task_id"]) in UNFINISHED:
                return "skip: debounced (task %s still running)" % mark["last_task_id"][:8]

        count, newest = scan_new(agent, mark["high_water"])
        need = int(getattr(agent, "publish_min_pages", 3) or 1)
        if count < need:
            return "skip: only %d new page(s), needs %d" % (count, need)
        if not newest:
            # Có bài mà không đọc được mốc nào ⇒ không có gì để dời mốc tới.
            # Bắn lúc này là tự chuốc lấy vòng lặp: đúng corpus ấy châm ngòi lại
            # ở mọi lượt sau cho tới khi cạn trần ngày.
            return "skip: %d new page(s) but none has a usable timestamp" % count

        options: Dict[str, Any] = {
            # "publish" cũng là id của bước upload trong RENDER_STEPS, và _run_steps
            # đọc options[<step id>] làm công tắc bật/tắt bước — nên một khoá này
            # vừa nói "lượt này có đăng" vừa bật đúng bước đó.
            "publish": True,
            "publish_token_id": token_id,
            "publish_channel_id": channel_id,
            "publish_channel_name": str(getattr(agent, "publish_channel_name", "") or ""),
            "publish_privacy": str(getattr(agent, "publish_privacy", "public") or "public"),
        "publish_method": str(getattr(agent, "publish_method", "script") or "script"),
        "publish_monetize": bool(getattr(agent, "publish_monetize", False)),
            "high_water_prev": mark["high_water"],
            # Chặn TRÊN của cửa sổ corpus: đúng cái mốc vừa đếm ở trên. Thiếu nó,
            # bài thu thập được trong lúc task chạy vừa vào video này vừa được
            # lượt sau đếm lại — một corpus, hai video.
            "high_water": newest,
            # Cờ này nói với pipeline: lượt đăng thành công thì gọi
            # commit_published() ngược về đây. Một lượt dựng thủ công cũng có
            # thể bật publish, và nó KHÔNG được tiêu một suất của trần ngày.
            "autopublish": True,
        }
        preset = str(getattr(agent, "content_video_preset", "") or "")
        if preset:
            options["preset"] = preset

        from tubecli.extensions.content_video.pipeline import create_auto_task

        try:
            # MỘT task chạy trọn: corpus → kịch bản → mp4 → YouTube. Không có ô duyệt
            # nào ở giữa để phải mở, nên cũng không cần ai đi mở hộ.
            task = create_auto_task(
                agent_id, options,
                created_by=ACTOR,
                origin={"agent_id": agent_id, "run_id": run_id, "trigger": "scraped_run"},
                job_label=JOB_LABEL,
                high_water_prev=mark["high_water"],
                high_water=newest,
            )
        except Exception as e:
            # KHÔNG đụng vào sổ: lượt sau đếm lại đúng chỗ này và thử lại.
            logger.error("[AutoPublish] could not queue the video for %s (%s)", agent_id, e,
                         exc_info=True)
            return "error: could not queue (%s)" % e

        task_id = str((task or {}).get("id") or "")
        # Chỉ ghi phần dành cho CỬA CHỐNG DỘI. `high_water` thật và bộ đếm ngày
        # nằm yên cho tới khi commit_published() báo là video đã lên kênh: cái
        # task này còn có thể chết ở bước dựng, ở lúc upload, hay theo server
        # khi nó khởi động lại, và cửa sổ corpus phải sống sót qua tất cả.
        save_mark(agent_id,
                  high_water_pending=newest,
                  last_task_id=task_id,
                  last_fired_at=time.time())
    return "queued: task #%s from %d new page(s) to %s" % (
        (task or {}).get("seq", "?"), count,
        options["publish_channel_name"] or channel_id)
