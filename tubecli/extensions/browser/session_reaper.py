"""Dọn phiên trình duyệt treo / quá giờ + đếm chỗ cho bộ lập lịch (10/11/2026).

Sự cố thật (contabo 6G, 9–10/11/2026): 7 phiên Muse ẨN (muse-vinh-20…34, `--manual --url https://muse.ai/ --headless`)
mở để vẽ ảnh cho task video. Bộ lập lịch đếm MỌI phiên process_manager vào trần `max_scheduled_browsers` (5) nên ba
agent «Momento bíblico» bị bỏ lượt «busy» hàng chục lần mỗi ngày, mà dòng bỏ qua chỉ nói «7 browser session(s) already
running» — không ai biết ai đang giữ chỗ.

Ba việc ở đây, đều THUẦN phần quyết định (plan_* nhận dữ liệu qua tham số) để kiểm được mà không cần tiến trình thật:

1. describe_holders — ai đang giữ chỗ: hồ sơ, loại phiên, tuổi. Đi vào dòng «busy» của run_log.
2. counted_for_cap — phiên Muse ẩn đếm vào trần bao nhiêu. CHỌN: Muse ẩn chiếm TỐI ĐA (trần − 1) chỗ trong phép đếm.
   Vì sao không bỏ hẳn Muse khỏi phép đếm: trần này là cái phanh RAM của máy (VPS 6–8 GB), mỗi Chromium ẩn ~300–500 MB;
   bỏ hẳn thì một lô ảnh 7 tài khoản + 5 lượt nghiên cứu = 12 trình duyệt. Vì sao không đếm đủ như cũ: bể Muse có trần
   riêng (số tài khoản × muse_lanes) và có thể chiếm trọn trần trong nhiều giờ ⇒ lượt nghiên cứu theo lịch chết đói.
   Giữ lại MỘT chỗ cho lượt theo lịch: tối đa thêm đúng một trình duyệt (lượt lịch mở từng cái một mỗi nhịp, nhịp sau
   đã đếm đủ trần), đổi lại chuỗi thu thập → video không đứng cả ngày.
3. plan_sweep / sweep — dọn phiên quá giờ: (a) phiên có max_duration mà quá hạn + 3 phút (vòng theo dõi lẽ ra đã giết —
   giết hỏng / luồng chết), (b) phiên Muse ẩn KHÔNG có lượt Muse nào đang chạy và rảnh ≥ MUSE_IDLE_MAX, (c) phiên mở tay
   không hạn giờ quá MANUAL_SESSION_MAX. KHÔNG BAO GIỜ giết phiên đang có người xem live, phiên Muse đang có lượt chạy,
   hay lượt theo lịch còn trong hạn. Mỗi lần giết ghi log máy chủ + run_log / bảng nhóm khi phiên thuộc một agent.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger("tubecli.browser.reaper")

# Phiên có hạn giờ mà sống quá hạn + chừng này giây ⇒ vòng theo dõi đã không giết được → dọn.
OVERRUN_GRACE_SEC = 180
# Phiên Muse ẩn rảnh (không lượt nào đang chạy) chừng này giây ⇒ đóng để trả RAM + chỗ; lượt Muse sau tự mở lại
# (core/muse.ensure_browser, ~10–20 s). 30 phút: một lô ảnh Studio gửi liên tục nên khoảng rảnh giữa hai ảnh chỉ vài
# giây; 30 phút rảnh là lô đã xong.
MUSE_IDLE_MAX = 30 * 60
# Phiên mở tay / hệ thống KHÔNG có hạn giờ (dashboard «Mở», node Browser, đăng nhập…) sống quá chừng này ⇒ dọn, trừ khi
# đang có người xem live. Đổi được bằng global setting `browser_manual_max_hours` (0 = không bao giờ dọn).
MANUAL_SESSION_MAX = 4 * 3600
MANUAL_MAX_SETTING = "browser_manual_max_hours"
# Chạy nhiều nhất mỗi chừng này giây (bộ lập lịch gọi mỗi nhịp).
SWEEP_EVERY = 60

KIND_MUSE = "muse-hidden"
KIND_SCHEDULED = "scheduled"
KIND_COOKIES = "cookie-refresh"
KIND_MANUAL = "manual"
KIND_LABEL = {KIND_MUSE: "Muse, hidden", KIND_SCHEDULED: "scheduled run", KIND_COOKIES: "cookie refresh",
              KIND_MANUAL: "opened by hand / system"}

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"last": 0.0}
_RECENT: List[Dict[str, Any]] = []      # 50 lần dọn gần nhất (đọc trong test / gỡ lỗi)


# ── phân loại ─────────────────────────────────────────────────────────────────
def session_kind(inst: Dict[str, Any]) -> str:
    url = str(inst.get("_url") or "")
    cmd = str(inst.get("command") or "")
    if inst.get("_run_id") or inst.get("_agent_id"):
        return KIND_SCHEDULED
    if "muse.ai" in url or "--url https://muse.ai" in cmd:
        return KIND_MUSE
    if inst.get("_max_duration") and ("youtube.com" in url or "--url https://www.youtube.com" in cmd):
        return KIND_COOKIES
    return KIND_MANUAL


def _age_sec(inst: Dict[str, Any], now: float) -> float:
    try:
        return max(0.0, now - datetime.fromisoformat(str(inst.get("started_at"))).timestamp())
    except Exception:       # noqa: BLE001
        return 0.0


def fmt_age(sec: float) -> str:
    sec = int(max(0, sec))
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def holders(instances: Iterable[Dict[str, Any]], now: Optional[float] = None) -> List[Dict[str, Any]]:
    """[{instance_id, profile, kind, age_sec}] của các phiên đang chạy, cũ nhất trước."""
    now = time.time() if now is None else now
    out = []
    for inst in instances or []:
        if str(inst.get("status") or "") != "running":
            continue
        out.append({"instance_id": inst.get("instance_id"), "profile": str(inst.get("profile") or "?"),
                    "kind": session_kind(inst), "age_sec": _age_sec(inst, now)})
    out.sort(key=lambda h: -h["age_sec"])
    return out


def describe_holders(hs: List[Dict[str, Any]], limit: int = 8) -> str:
    parts = [f"{h['profile']} ({KIND_LABEL.get(h['kind'], h['kind'])}, {fmt_age(h['age_sec'])})" for h in hs[:limit]]
    if len(hs) > limit:
        parts.append(f"+{len(hs) - limit} more")
    return "; ".join(parts)


def counted_for_cap(hs: List[Dict[str, Any]], cap: int) -> int:
    """Số chỗ tính vào trần lượt theo lịch: phiên khác Muse đủ, phiên Muse ẩn tối đa (cap − 1). Xem đầu file."""
    muse = sum(1 for h in hs if h["kind"] == KIND_MUSE)
    other = len(hs) - muse
    return other + min(muse, max(0, int(cap) - 1))


# ── kế hoạch dọn (thuần) ──────────────────────────────────────────────────────
def plan_sweep(instances: Iterable[Dict[str, Any]], now: float, live_profiles: Iterable[str] = (),
               muse_busy: Optional[Dict[str, int]] = None, muse_last_active: Optional[Dict[str, float]] = None,
               manual_max: int = MANUAL_SESSION_MAX, muse_idle_max: int = MUSE_IDLE_MAX) -> List[Dict[str, Any]]:
    """[{instance_id, profile, kind, age_sec, limit_sec, reason}] — các phiên NÊN đóng. Không giết gì."""
    live = set(str(p) for p in (live_profiles or ()))
    busy = dict(muse_busy or {})
    last = dict(muse_last_active or {})
    out: List[Dict[str, Any]] = []
    for inst in instances or []:
        if str(inst.get("status") or "") != "running":
            continue
        prof = str(inst.get("profile") or "")
        kind = session_kind(inst)
        age = _age_sec(inst, now)
        if prof in live:
            continue                                     # có người đang xem — không bao giờ đụng
        if kind == KIND_MUSE and busy.get(prof):
            continue                                     # đang vẽ / đọc / quay dở
        row = {"instance_id": inst.get("instance_id"), "profile": prof, "kind": kind, "age_sec": age}
        maxd = inst.get("_max_duration")
        try:
            maxd = int(maxd) if maxd else 0
        except (TypeError, ValueError):
            maxd = 0
        if maxd > 0 and age > maxd + OVERRUN_GRACE_SEC:
            out.append({**row, "limit_sec": maxd,
                        "reason": f"ran {fmt_age(age)}, past its {fmt_age(maxd)} limit (the watchdog did not stop it)"})
            continue
        if kind == KIND_MUSE:
            since = max(float(last.get(prof) or 0.0), now - age)    # chưa từng nhận lượt ⇒ tính từ lúc mở
            idle = now - since
            if muse_idle_max > 0 and idle >= muse_idle_max:
                out.append({**row, "limit_sec": muse_idle_max,
                            "reason": f"Muse session idle for {fmt_age(idle)} (no Muse job running)"})
            continue
        if kind == KIND_MANUAL and not maxd and manual_max > 0 and age > manual_max:
            out.append({**row, "limit_sec": manual_max,
                        "reason": f"open for {fmt_age(age)} with no time limit and nobody watching it live "
                                  f"(limit {fmt_age(manual_max)})"})
    return out


# ── nguồn dữ liệu thật ────────────────────────────────────────────────────────
def _manual_max() -> int:
    try:
        from tubecli.config import get_global_setting
        v = get_global_setting(MANUAL_MAX_SETTING, None)
        if v is not None and str(v).strip() != "":
            return max(0, int(float(v) * 3600))
    except Exception:       # noqa: BLE001
        pass
    return MANUAL_SESSION_MAX


def _live_profiles() -> List[str]:
    try:
        from tubecli.extensions.browser import routes as R
        out = []
        for _sid, info in list(getattr(R, "_preview_processes", {}).items()):
            proc = info.get("proc")
            if proc is not None and proc.poll() is not None:
                continue
            if info.get("profile"):
                out.append(str(info["profile"]))
        return out
    except Exception:       # noqa: BLE001
        return []


def _muse_state():
    try:
        from tubecli.core import muse as M
        return M._busy_by_profile(), M.last_active_by_profile()
    except Exception:       # noqa: BLE001
        return None, None


def _raw_instances() -> List[Dict[str, Any]]:
    from .process_manager import browser_process_manager as pm
    with pm._instances_lock:
        rows = []
        for inst in pm._instances.values():
            pm._refresh_exit_status(inst)
            rows.append(dict(inst))
    return rows


def running_holders(now: Optional[float] = None) -> List[Dict[str, Any]]:
    try:
        return holders(_raw_instances(), now)
    except Exception:       # noqa: BLE001
        return []


def _log_kill(row: Dict[str, Any], inst: Dict[str, Any], stopped: bool) -> None:
    msg = (f"[Browser] reaper {'stopped' if stopped else 'could NOT stop'} {row['profile']} "
           f"({KIND_LABEL.get(row['kind'], row['kind'])}, {fmt_age(row['age_sec'])}): {row['reason']}")
    logger.warning(msg)
    print(msg)
    agent_id = str(inst.get("_agent_id") or "")
    run_id = str(inst.get("_run_id") or "")
    if not agent_id:
        return
    try:
        from tubecli.core import run_log
        note = getattr(run_log, "note", None)
        if note and run_id:
            note(run_id, agent_id, msg.replace("[Browser] ", ""), kind="reaper")
    except Exception:       # noqa: BLE001
        pass
    try:
        from tubecli.core import group_context, group_log
        from tubecli.core.agent import agent_manager
        ag = agent_manager.get(agent_id)
        name = getattr(ag, "name", "") if ag else ""
        for g in group_context.effective_groups(agent_id) or []:
            gid = (g or {}).get("group_id") if isinstance(g, dict) else ""
            if gid:
                group_log.append(gid, agent_id, name, kind="schedule",
                                 title=f"Browser {row['profile']} closed by the cleanup", detail=row["reason"],
                                 ok=False)
    except Exception:       # noqa: BLE001
        pass


def sweep(now: Optional[float] = None, force: bool = False,
          terminate: Optional[Callable[[str], bool]] = None) -> List[Dict[str, Any]]:
    """Một vòng dọn (tối đa mỗi SWEEP_EVERY giây trừ khi force). Trả các phiên đã xử lý. Không bao giờ ném."""
    now = time.time() if now is None else now
    with _LOCK:
        if not force and now - _STATE["last"] < SWEEP_EVERY:
            return []
        _STATE["last"] = now
    try:
        from .process_manager import browser_process_manager as pm
        rows = _raw_instances()
        busy, last = _muse_state()
        if busy is None:
            # Không đọc được sổ Muse ⇒ không biết phiên Muse nào đang chạy ⇒ không đụng phiên Muse nào.
            rows = [r for r in rows if session_kind(r) != KIND_MUSE]
        plan = plan_sweep(rows, now, _live_profiles(), busy or {}, last or {}, _manual_max())
        by_id = {r.get("instance_id"): r for r in rows}
        kill = terminate or pm.terminate
        done = []
        for row in plan:
            try:
                ok = bool(kill(str(row["instance_id"])))
            except Exception as e:      # noqa: BLE001
                logger.warning(f"[Browser] reaper could not stop {row['instance_id']}: {e}")
                ok = False
            _log_kill(row, by_id.get(row["instance_id"]) or {}, ok)
            done.append({**row, "stopped": ok})
        if done:
            with _LOCK:
                _RECENT.extend(done)
                del _RECENT[:-50]
        return done
    except Exception as e:      # noqa: BLE001
        logger.warning(f"[Browser] session sweep failed: {e}")
        return []
