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
UNFINISHED = ("pending_approval", "backlog", "queued", "running", "review")
JOB_LABEL = "Auto publish"
JOB_LABEL_VIDEO = "Auto video"          # lượt chỉ dựng (agent.auto_video, chưa đăng)
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
        "paused": dict(row.get("paused") or {}) if isinstance(row.get("paused"), dict) else {},
        # Chủ / connector bấm «tạm dừng agent» (pause_agent) — khác `paused` ở trên (tự dừng vì video dài).
        "agent_paused": dict(row.get("agent_paused") or {}) if isinstance(row.get("agent_paused"), dict) else {},
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


# ── Tạm dừng vì kênh chưa xác minh (19/10/2026) ─────────────────────
#
# YouTube không nhận video quá 15 phút từ kênh chưa xác minh số điện thoại. Đăng hỏng thì mốc corpus đứng yên (cố ý,
# để «làm lại» chứ không «mất hẳn») và trần ngày chỉ đếm video ĐÃ lên — nên lượt thu thập nào đủ bài cũng dựng lại
# nguyên một video dài rồi lại đăng hỏng: vòng lặp tốn cả giờ máy mỗi vòng. Pipeline gọi pause_for_length() khi bỏ
# đăng (hay đăng hỏng) một video dài trên kênh chưa xác minh; cò súng đứng yên tới khi người dùng xác minh kênh (bỏ
# cờ publish_unverified), đổi mẫu, hay sửa mẫu (mốc updated_at của mẫu đổi — vd rút ngắn Video length).
PAUSE_LONG_UNVERIFIED = "long_unverified"


def _preset_sig(name: str) -> str:
    """Mốc sửa gần nhất của mẫu (kho mẫu chung của lõi) — đổi khi người dùng lưu lại mẫu. "" khi không đọc được."""
    if not name:
        return ""
    try:
        from tubecli.core import templates as _T

        return str((_T.get_template(name) or {}).get("updated_at") or "")
    except Exception as e:      # noqa: BLE001
        logger.debug("[AutoPublish] could not read template %s (%s)", name, e)
        return ""


def pause_for_length(agent_id: str, seconds: float, preset: str = "", capped: bool = False) -> bool:
    """Dừng tự đăng của agent: video vừa dựng dài hơn mức kênh chưa xác minh nhận. Không bao giờ ném.

    capped: kịch bản của lượt ấy ĐÃ bị giới hạn vừa 15 phút (pipeline UNVERIFIED_SAFE_WORDS) mà video vẫn dài — vòng lặp
    thật, dừng giữ hiệu lực. Không giới hạn (lượt cũ, Retry kịch bản cũ) ⇒ ghi sổ nhưng KHÔNG giữ: lượt sau viết vừa khung."""
    aid = str(agent_id or "")
    if not aid:
        return False
    try:
        return save_mark(aid, paused={"reason": PAUSE_LONG_UNVERIFIED, "at": time.time(),
                                      "seconds": int(seconds or 0), "preset": str(preset or ""),
                                      "capped": bool(capped), "cap_words": _safe_words(),
                                      "preset_sig": _preset_sig(str(preset or ""))})
    except Exception as e:      # noqa: BLE001
        logger.error("[AutoPublish] could not pause %s (%s)", aid, e)
        return False


def _pause_holds(agent, paused: Dict[str, Any]) -> bool:
    """Lần tạm dừng vì video dài còn hiệu lực? Hết khi kênh đã xác minh, hay mẫu đổi / được sửa."""
    if paused.get("reason") != PAUSE_LONG_UNVERIFIED:
        return False
    if not bool(getattr(agent, "publish_unverified", False)):
        return False
    # Từ .213 kịch bản tự đăng của kênh chưa xác minh được viết vừa 15 phút: dừng vì một video dài KHÔNG giới hạn (sổ cũ,
    # Retry kịch bản cũ) không còn lý do giữ — lượt sau tự ngắn. Chỉ giữ khi chính kịch bản đã giới hạn vẫn ra video dài.
    if not paused.get("capped"):
        return False
    # 14/11/2026 (contabo, 78 video dựng xong không đăng): mức giới hạn cũ 2000 chữ vẫn ra video 18 phút (model viết lố
    # ~20%, giọng đọc ~130 chữ/phút) ⇒ «đã giới hạn mà vẫn dài» ⇒ dừng VĨNH VIỄN, mỗi ngày vẫn dựng một video không đăng
    # được. Lần dừng ghi theo mức giới hạn CŨ không còn giá trị khi mức giới hạn đã đổi: lượt sau viết theo mức mới.
    if int(paused.get("cap_words") or 0) != _safe_words():
        return False
    preset = str(getattr(agent, "content_video_preset", "") or "")
    return preset == str(paused.get("preset") or "") and _preset_sig(preset) == str(paused.get("preset_sig") or "")


def _mmss(seconds: Any) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        s = 0
    return "%d:%02d" % (s // 60, s % 60)


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
    # Hai công tắc (10/10/2026): auto_publish = dựng + ĐĂNG lên kênh đã chọn; auto_video = dựng video dù chưa chọn
    # kênh (không đăng gì, video chờ duyệt trên Codex). Bật cái nào cũng đủ để lượt thu thập châm ngòi.
    if get_mark(agent_id).get("agent_paused"):
        return "skip: this agent is paused — resume it to make videos again"
    publish_on = bool(getattr(agent, "auto_publish", False))
    video_on = bool(getattr(agent, "auto_video", False))
    if not publish_on and not video_on:
        return "skip: auto video and auto-publish off"

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
    method = str(getattr(agent, "publish_method", "script") or "script")
    # Đường API cần token + kênh (videos.insert đăng vào kênh của token). Đường TRÌNH DUYỆT (10/10/2026) thì không:
    # hồ sơ đã đăng nhập YouTube là đủ, kênh bỏ trống = kênh mặc định của tài khoản trong hồ sơ.
    publish = publish_on and (method != "api" or (bool(token_id) and bool(channel_id)))
    # Vì sao lượt này CHỈ DỰNG (15/11/2026): trước đây ghi chú chỉ nói «render only, waiting for review» — chủ thấy
    # auto_publish vẫn bật mà không hiểu vì sao 76 video nằm ở review.
    why_render_only = "" if publish_on else "auto-publish is off for this agent"
    if publish_on and not publish:
        why_render_only = "auto-publish uses the API but no YouTube %s is chosen" % ("token" if not token_id else "channel")
    if publish_on and not publish:
        # Công tắc đăng bật mà chưa chọn kênh là LỖI CẤU HÌNH, không phải "chưa tới
        # lượt": người dùng đang tin rằng video vẫn được đăng. Kêu to. Có bật «tự dựng
        # video» thì vẫn dựng (chỉ không đăng); không thì dừng như cũ.
        missing = "token" if not token_id else "channel"
        logger.warning("[AutoPublish] agent %s has auto-publish ON but no YouTube %s "
                       "— pick a channel in the agent's Data collection tab",
                       getattr(agent, "name", "") or agent_id, missing)
        if not video_on:
            return "skip: auto-publish armed but no YouTube %s chosen" % missing

    # Kênh chưa xác minh + video lần trước quá 15 phút ⇒ đứng yên (xem pause_for_length). Bật «tự dựng video» thì
    # vẫn dựng nhưng không đăng — đúng nghĩa công tắc ấy; không thì thôi hẳn, khỏi dựng một video không đăng được.
    paused = get_mark(agent_id).get("paused") or {}
    if publish and paused:
        if _pause_holds(agent, paused):
            if not video_on:
                return ("skip: auto-publish paused — the last video was %s long and the channel is not verified "
                        "(YouTube takes at most 15 min); verify the channel and untick «Channel not verified», "
                        "or shorten the template" % _mmss(paused.get("seconds")))
            publish = False
            why_render_only = ("publishing paused itself: the last video was %s long and this agent's channel is marked "
                               "«not verified» (YouTube takes at most 15 min) — verify the channel and untick «Channel "
                               "not verified», or PATCH /api/v1/codex/autopublish/%s {\"publish\": true}"
                               % (_mmss(paused.get("seconds")), agent_id))
        else:
            save_mark(agent_id, paused={})

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

        # Chống trùng (14/11/2026 — «Seek First: What Matthew 6:33 Really Means» dựng 5 lần, mỗi lần ~3 giờ): lượt thu
        # thập vừa xong tìm đúng chủ đề của một video ĐÃ CÓ ⇒ không xếp việc, và gác cửa sổ bài này lại để lượt sau
        # không gom chúng vào một video khác.
        topic_query = _run_query(agent_id, run_id)
        dup = duplicate_task(agent_id, [topic_query]) if topic_query else None
        if dup:
            skip_window(agent_id, newest)
            return "skip: duplicate topic — «%s» was already made as task #%s («%s»); the new pages were set aside" % (
                topic_query[:100], dup.get("seq", "?"), str(dup.get("title") or "")[:80])

        options: Dict[str, Any] = {
            # "publish" cũng là id của bước upload trong RENDER_STEPS, và _run_steps
            # đọc options[<step id>] làm công tắc bật/tắt bước — nên một khoá này
            # vừa nói "lượt này có đăng" vừa bật đúng bước đó. False = lượt CHỈ DỰNG.
            "publish": publish,
            "high_water_prev": mark["high_water"],
            # Chặn TRÊN của cửa sổ corpus: đúng cái mốc vừa đếm ở trên. Thiếu nó,
            # bài thu thập được trong lúc task chạy vừa vào video này vừa được
            # lượt sau đếm lại — một corpus, hai video.
            "high_water": newest,
            # Cờ này nói với pipeline: lượt đăng thành công thì gọi
            # commit_published() ngược về đây. Một lượt dựng thủ công cũng có
            # thể bật publish, và nó KHÔNG được tiêu một suất của trần ngày.
            "autopublish": True,
            # Ảnh đại diện vẽ bằng model ảnh từ ảnh hook (15/10/2026 — trước đây layout Thumbnail Studio, lạc kiểu
            # video; xem pipeline.thumb_config); là bước mềm — vẽ hỏng chỉ cảnh báo. Agent tắt được (publish_thumbnail,
            # 15/10/2026): kênh chưa xác minh không nhận thumbnail tuỳ chỉnh — không vẽ, không gắn; prompt vẫn viết.
            "thumbnail": bool(getattr(agent, "publish_thumbnail", True))
                         and not bool(getattr(agent, "publish_unverified", False)),
        }
        if publish:
            options.update({
                # Kênh chưa xác minh (19/10/2026): pipeline không đăng video quá 15 phút, không gắn thumbnail.
                "publish_unverified": bool(getattr(agent, "publish_unverified", False)),
                "publish_token_id": token_id,
                "publish_channel_id": channel_id,
                "publish_channel_name": str(getattr(agent, "publish_channel_name", "") or ""),
                "publish_privacy": str(getattr(agent, "publish_privacy", "public") or "public"),
                "publish_method": method,
                "publish_monetize": bool(getattr(agent, "publish_monetize", False)),
                # Hồ sơ trình duyệt đăng bài ("" = tự chọn hồ sơ đã đăng nhập YouTube) + hẹn giờ theo khung hằng
                # ngày của agent (10/10/2026).
                "publish_profile": str(getattr(agent, "publish_profile", "") or ""),
                "publish_when": str(getattr(agent, "publish_when", "now") or "now"),
                "publish_slots": str(getattr(agent, "publish_slots", "") or ""),
                "publish_tz": str(getattr(agent, "publish_tz", "") or ""),
                "publish_tz_offset": getattr(agent, "publish_tz_offset", ""),
            })
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
                job_label=JOB_LABEL if publish else JOB_LABEL_VIDEO,
                high_water_prev=mark["high_water"],
                high_water=newest,
            )
        except Exception as e:
            # KHÔNG đụng vào sổ: lượt sau đếm lại đúng chỗ này và thử lại.
            logger.error("[AutoPublish] could not queue the video for %s (%s)", agent_id, e,
                         exc_info=True)
            return "error: could not queue (%s)" % e

        task_id = str((task or {}).get("id") or "")
        if topic_query and task_id:
            try:        # để lượt sau so chủ đề với cả task chưa có tiêu đề (đang viết kịch bản)
                _codex().set_meta(task_id, {"topic_query": topic_query[:200]})
            except Exception as e:      # noqa: BLE001
                logger.debug("[AutoPublish] could not note the topic on %s (%s)", task_id, e)
        # Chỉ ghi phần dành cho CỬA CHỐNG DỘI. `high_water` thật và bộ đếm ngày
        # nằm yên cho tới khi commit_published() báo là video đã lên kênh: cái
        # task này còn có thể chết ở bước dựng, ở lúc upload, hay theo server
        # khi nó khởi động lại, và cửa sổ corpus phải sống sót qua tất cả.
        save_mark(agent_id,
                  high_water_pending=newest,
                  last_task_id=task_id,
                  last_fired_at=time.time())
    if not publish:
        return "queued: task #%s from %d new page(s) — render only, waiting for review%s" % (
            (task or {}).get("seq", "?"), count, (" (%s)" % why_render_only) if why_render_only else "")
    return "queued: task #%s from %d new page(s) to %s" % (
        (task or {}).get("seq", "?"), count,
        options["publish_channel_name"] or channel_id or "the profile's default channel")

# ── 14/11/2026: gác cửa sổ, chống trùng chủ đề, bật / tắt Publish, tạm dừng agent ─────────────
def _safe_words() -> int:
    try:
        from tubecli.extensions.content_video.pipeline import UNVERIFIED_SAFE_WORDS
        return int(UNVERIFIED_SAFE_WORDS)
    except Exception:       # noqa: BLE001
        return 0


def skip_window(agent_id: str, high_water: str = "") -> bool:
    """Dời mốc kho qua một cửa sổ bài KHÔNG làm video (nguồn lạc ngách, chủ đề trùng) để lượt thu thập sau không châm
    ngòi lại đúng mớ bài ấy. pipeline._skip_window_after_hold gọi hàm này từ 4/11 nhưng nó chưa từng tồn tại — lệnh
    gọi nằm trong try/except nên cửa sổ không bao giờ được gác. Chỉ tiến, không lùi."""
    aid, hw = str(agent_id or ""), str(high_water or "")
    if not aid or not hw:
        return False
    with _LOCK:
        if hw <= get_mark(aid)["high_water"]:
            return False
        return save_mark(aid, high_water=hw)


# Chữ không mang chủ đề (en / es / vi) + chữ vỏ mà bộ dựng câu tìm kiếm quấn quanh từ khoá.
_TOPIC_STOP = frozenset("""
a an the of in on at to for and or is are was were be what whats does do did mean means meaning really actually
explained explain why how who when where this that it its his her their your our with from by as about into
latest news today best practices guide tutorial top new vs
que qué el la los las de del en y o es son un una lo como cómo sobre por para con su sus al mejores prácticas guía
la lá của và là những các một cho về trong khi với có không gì nào thế
""".split())
DUP_DAYS = 21
DUP_STATUSES = ("pending_approval", "backlog", "queued", "running", "review", "done")
_GENERIC_TITLE = ("auto publish:", "auto video:", "auto publish ·", "auto video ·")


def topic_tokens(text: str) -> frozenset:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(text or "")).casefold()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return frozenset(t for t in re.split(r"[^0-9a-z]+", s) if t and t not in _TOPIC_STOP)


def similar_topic(a: str, b: str) -> bool:
    """Hai câu cùng MỘT chủ đề: ≥ 3 chữ mang nghĩa chung và chúng phủ ≥ 75% câu ngắn hơn.
    «latest What does "seek first the kingdom of God" mean in Matthew 6:33? news» ≈ «Seek First: What Matthew 6:33
    Really Means»; «Matthew 6:33» và «Matthew 6:34» thì KHÔNG (số câu khác nhau)."""
    ta, tb = topic_tokens(a), topic_tokens(b)
    if not ta or not tb:
        return False
    common = ta & tb
    small = min(len(ta), len(tb))
    # Số (chương, câu) lệch nhau là bài khác dù chữ giống: «Matthew 6:33» ≠ «Matthew 6:34».
    na, nb = {t for t in ta if t.isdigit()}, {t for t in tb if t.isdigit()}
    if na and nb and na != nb:
        return False
    return len(common) >= 3 and len(common) / small >= 0.75


def _run_query(agent_id: str, run_id: str) -> str:
    """Câu tìm kiếm của lượt thu thập vừa xong (run_log) — chủ đề mà video sắp dựng sẽ nói tới. "" khi không đọc được."""
    if not run_id:
        return ""
    try:
        from tubecli.core import run_log
        for r in run_log.list_for_agent(str(agent_id), days=2, limit=40):
            if r.get("run_id") == run_id:
                return " ".join(str(r.get("query") or "").split())
    except Exception as e:      # noqa: BLE001
        logger.debug("[AutoPublish] could not read the run query (%s)", e)
    return ""


def _age_days(stamp: Any) -> float:
    try:
        dt = datetime.datetime.fromisoformat(str(stamp or ""))
        now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
        return (now - dt).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return 0.0


def duplicate_task(agent_id: str, texts, exclude: str = "", days: int = DUP_DAYS):
    """Task video CÒN MỞ hay ĐÃ XONG của agent này (trong `days` ngày) nói cùng chủ đề với một trong `texts` — so với
    tiêu đề và câu tìm kiếm đã ghi (meta.topic_query). None khi không có. Task bị huỷ / hỏng không tính."""
    wanted = [t for t in (texts or []) if topic_tokens(t)]
    if not wanted:
        return None
    try:
        tasks = _codex().list_tasks(limit=500) or []
    except Exception as e:      # noqa: BLE001
        logger.debug("[AutoPublish] could not list tasks (%s)", e)
        return None
    for t in tasks:
        if str(t.get("id") or "") == str(exclude or "") or str(t.get("assignee_id") or "") != str(agent_id):
            continue
        if str(t.get("status") or "").lower() not in DUP_STATUSES or _age_days(t.get("created_at")) > days:
            continue
        title = str(t.get("title") or "")
        have = [str((t.get("meta") or {}).get("topic_query") or "")]
        if not title.casefold().startswith(_GENERIC_TITLE):
            have.append(title)
        if any(similar_topic(w, h) for w in wanted for h in have if h):
            return t
    return None


def status(agent) -> Dict[str, Any]:
    """Tình trạng tự đăng của một agent — thứ GET /api/v1/codex/autopublish/{agent_id} trả về."""
    aid = str(getattr(agent, "id", "") or "")
    mark = get_mark(aid)
    paused = mark["paused"] if _pause_holds(agent, mark["paused"]) else {}
    return {
        "agent_id": aid, "agent_name": str(getattr(agent, "name", "") or ""),
        "publish": bool(getattr(agent, "auto_publish", False)),
        "auto_video": bool(getattr(agent, "auto_video", False)),
        "daily_limit": int(getattr(agent, "publish_max_per_day", 2) or 0),
        "published_today": mark["published_today"],
        "method": str(getattr(agent, "publish_method", "script") or "script"),
        "profile": str(getattr(agent, "publish_profile", "") or ""),
        "channel": str(getattr(agent, "publish_channel_name", "") or ""),
        "channel_unverified": bool(getattr(agent, "publish_unverified", False)),
        "agent_paused": bool(mark.get("agent_paused")),
        "paused_for_length": bool(paused),
        "paused_detail": ("the last video was %s long and the channel is not verified (YouTube takes at most 15 min)"
                          % _mmss(paused.get("seconds"))) if paused else "",
        # Khi nào video lên kênh: "now" = ngay sau khi dựng; "slots" = tải lên ngay sau khi dựng và HẸN GIỜ trên YouTube
        # vào khung trống kế tiếp của `slots` (không có bộ đăng riêng chạy theo giờ).
        "when": str(getattr(agent, "publish_when", "now") or "now"),
        "when_choices": list(_when_choices()),
        "slots": str(getattr(agent, "publish_slots", "") or ""),
        **_will_publish(agent, mark, bool(paused)),
    }


def _when_choices():
    from tubecli.core.agent import PUBLISH_WHEN_CHOICES
    return PUBLISH_WHEN_CHOICES


def _will_publish(agent, mark: Dict[str, Any], paused: bool) -> Dict[str, Any]:
    """{will_publish, why_not}: lượt tự động KẾ TIẾP của agent này có đăng lên kênh không — cùng luật với trigger."""
    why = ""
    if mark.get("agent_paused"):
        why = "the agent is paused (POST /api/v1/agents/{id}/resume)"
    elif not bool(getattr(agent, "auto_publish", False)):
        why = "auto-publish is off for this agent"
    elif str(getattr(agent, "publish_method", "script") or "script") == "api" and not (
            getattr(agent, "publish_token_id", "") and getattr(agent, "publish_channel_id", "")):
        why = "auto-publish uses the API but no YouTube token / channel is chosen"
    elif paused:
        why = ("publishing paused itself: the last video was over 15 minutes and the channel is marked «not verified» — "
               "send {\"publish\": true} to clear it, or {\"channel_unverified\": false} if the channel is verified")
    elif mark.get("published_today", 0) >= int(getattr(agent, "publish_max_per_day", 2) or 0):
        why = "today's limit is reached (%d of %d)" % (mark.get("published_today", 0),
                                                       int(getattr(agent, "publish_max_per_day", 2) or 0))
    return {"will_publish": not why, "why_not": why}


def set_publish(agent_id: str, publish: bool, daily_limit=None, channel_unverified=None, when=None,
                slots=None) -> Dict[str, Any]:
    """Bật / tắt bước Publish của tự đăng cho MỘT agent (+ trần mỗi ngày). Bật lại thì gỡ luôn lần tự dừng vì video dài
    (người bật là người chịu trách nhiệm kênh). Ném ValueError khi agent không có hay trần sai."""
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(str(agent_id or ""))
    if not agent:
        raise ValueError("agent not found")
    fields: Dict[str, Any] = {"auto_publish": bool(publish)}
    if daily_limit is not None:
        try:
            n = int(daily_limit)
        except (TypeError, ValueError):
            raise ValueError("daily_limit must be a number from 1 to 20")
        if not 1 <= n <= 20:
            raise ValueError("daily_limit must be a number from 1 to 20")
        fields["publish_max_per_day"] = n
    # 15/11/2026: cờ «kênh chưa xác minh» tự bật sau MỘT lần tải lên hỏng của video > 15 phút (pipeline
    # _pause_autopublish) — kênh đã xác minh cũng dính (Radhika: 04/11 vẫn đăng video 19:52). Cho gỡ / đặt qua đây.
    if channel_unverified is not None:
        fields["publish_unverified"] = bool(channel_unverified)
    if when is not None:
        w = str(when).strip().lower()
        if w not in _when_choices():
            raise ValueError("when must be one of: " + ", ".join(_when_choices()))
        fields["publish_when"] = w
    if slots is not None:
        from tubecli.extensions.content_video.publish_schedule import parse_slots
        got = parse_slots(slots)
        if str(slots).strip() and not got:
            raise ValueError("slots must be times like \"12:00, 19:00\"")
        fields["publish_slots"] = ", ".join(got)
    if fields.get("publish_when", str(getattr(agent, "publish_when", "now") or "now")) == "slots" and not (
            fields.get("publish_slots", str(getattr(agent, "publish_slots", "") or ""))):
        raise ValueError("when = slots needs at least one time in slots, for example \"12:00, 19:00\"")
    agent = agent_manager.update(str(agent_id), **fields)
    if publish or channel_unverified is False:
        save_mark(str(agent_id), paused={})
    return status(agent)


def pause_agent(agent_id: str, by: str = "") -> Dict[str, Any]:
    """Tạm dừng một agent nghiên cứu: tắt lịch chạy và không cho lượt nào châm ngòi dựng video."""
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(str(agent_id or ""))
    if not agent:
        raise ValueError("agent not found")
    was = bool(getattr(agent, "schedule_enabled", False))
    if not (get_mark(str(agent_id)).get("agent_paused") or {}):
        save_mark(str(agent_id), agent_paused={"at": time.time(), "by": str(by or "")[:40], "schedule_was": was})
    agent_manager.update(str(agent_id), schedule_enabled=False)
    return {"agent_id": str(agent_id), "paused": True, "schedule_enabled": False}


def resume_agent(agent_id: str) -> Dict[str, Any]:
    """Tiếp tục: bật lại lịch chạy NẾU trước khi tạm dừng nó đang bật."""
    from tubecli.core.agent import agent_manager

    agent = agent_manager.get(str(agent_id or ""))
    if not agent:
        raise ValueError("agent not found")
    held = (get_mark(str(agent_id)).get("agent_paused") or {})
    turn_on = bool(held.get("schedule_was", True)) if held else bool(getattr(agent, "schedule_enabled", False))
    save_mark(str(agent_id), agent_paused={})
    agent_manager.update(str(agent_id), schedule_enabled=turn_on)
    return {"agent_id": str(agent_id), "paused": False, "schedule_enabled": turn_on}

def count_published(agent_id: str, video_url: str = "", task_id: str = "") -> str:
    """Một video được đăng TAY (POST /codex/tasks/{id}/publish) → tính vào trần ngày của agent, KHÔNG dời mốc kho.
    Cùng một task / link gọi lại chỉ tính một lần. Không bao giờ ném."""
    aid = str(agent_id or "")
    if not aid:
        return "no agent id"
    try:
        with _LOCK:
            row = get_mark(aid)
            key = str(task_id or "") or str(video_url or "")
            if key and row["last_commit_key"] == key:
                return "already counted"
            fields: Dict[str, Any] = {"published_today": row["published_today"] + 1, "day": _today(),
                                      "last_video_url": str(video_url or "")}
            if key:
                fields["last_commit_key"] = key
            save_mark(aid, **fields)
            return "counted %d" % fields["published_today"]
    except Exception as e:      # noqa: BLE001
        logger.error("[AutoPublish] could not count the publish for %s (%s)", aid, e)
        return "error: %s" % e
