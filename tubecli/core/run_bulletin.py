"""Bản tin MỘT DÒNG sau mỗi lượt chạy hẹn giờ — vào chat, và Telegram nếu có.

Lượt hẹn giờ chạy xong chỉ nằm trong tab Hoạt động; người dùng phải tự mở ra
xem. Ở đây, khi một lượt KẾT THÚC (không phải skip — skip mỗi tick một dòng là
spam), agent tự ghi một dòng tóm tắt vào phiên chat của nó, và bắn đúng dòng đó
sang Telegram nếu agent có kết nối.

Bản tin CỐ Ý gần như không có văn xuôi: icon kết quả + hành vi + hồ sơ + truy
vấn + thời lượng. Không văn xuôi thì không phải chọn ngôn ngữ — sản phẩm chạy
9 thứ tiếng, còn nhãn "Xem chi tiết" là việc của giao diện (đọc meta, tự dịch).

Best-effort tuyệt đối: mọi lỗi ở đây chỉ được log, không bao giờ được phép làm
hỏng vòng theo dõi tiến trình đã gọi nó.
"""
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("RunBulletin")

_ICON = {
    "completed": "✅",
    "partial": "◑",          # làm được một phần rồi vấp — không đỏ như hỏng sạch
    "timeout_killed": "⏱",
    "timeout_kill_failed": "⏱",
    "error": "❌",
    "failed": "❌",
    "refused": "🚫",
}

_QUERY_MAX = 60


def _fmt_duration(sec: Optional[float]) -> str:
    try:
        s = int(float(sec or 0))
    except Exception:
        return ""
    if s <= 0:
        return ""
    return "%dm%02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


def _run_row(agent_id: str, run_id: str) -> Dict[str, Any]:
    """Dòng launch của đúng lượt này (behavior/profile/query) từ run_log."""
    try:
        from tubecli.core import run_log
        for r in run_log.list_for_agent(agent_id, days=2, limit=60) or []:
            if str(r.get("run_id") or "") == str(run_id):
                return r
    except Exception:
        pass
    return {}


def build_text(agent_name: str, outcome: str, launch: Dict[str, Any],
               duration_sec: Optional[float], warned: bool) -> str:
    icon = "⚠️" if (outcome == "completed" and warned) else _ICON.get(outcome, "•")
    parts = [icon]
    b = str(launch.get("behavior") or "").strip()
    p = str(launch.get("profile") or "").strip()
    q = str(launch.get("query") or "").strip()
    if b:
        parts.append(b)
    if p:
        parts.append(p)
    if q:
        if len(q) > _QUERY_MAX:
            q = q[:_QUERY_MAX - 1] + "…"
        parts.append("“%s”" % q)
    d = _fmt_duration(duration_sec)
    if d:
        parts.append(d)
    if len(parts) == 1:          # không có gì để kể ngoài icon → thêm outcome thô
        parts.append(outcome)
    line = " · ".join(parts)
    # Phần lỗi tách riêng, sau dấu — : bản tin vẫn khoe việc đã làm ở đầu dòng,
    # lý do vấp nằm ở đuôi cho ai cần. Chỉ khi thật sự có lỗi.
    err = str((launch or {}).get("error") or "").strip()
    if err and outcome in ("partial", "error", "failed"):
        if len(err) > 70:
            err = err[:69] + "…"
        line += "  — " + err
    return line


def _post_chat(agent, text: str, run_id: str, outcome: str) -> None:
    """Ghi vào MỘT phiên cố định "🔔 <tên agent>" (kind=run_bulletin) của agent.

    Bản cũ ghi vào sessions[0] — "phiên mới nhất" đổi theo từng lượt (mỗi lượt
    routine chạm phiên riêng của nó, đẩy nó lên đầu) nên bản tin rơi lung tung
    khắp các phiên; người dùng mở phiên của mình thì chẳng thấy gì. Phiên cố
    định thì gọn (chat chính không bị dội tin) và tìm là thấy."""
    from tubecli.extensions.chat.store import conversation_store as chat_store
    sessions = [s for s in (chat_store.list_sessions(limit=500) or [])
                if str(s.get("agent_id") or "") == str(agent.id)
                and not s.get("guest_ws")
                and str(s.get("kind") or "") == "run_bulletin"]
    if sessions:
        sid = sessions[0]["id"]
    else:
        sid = chat_store.create_session(
            title="🔔 " + str(getattr(agent, "name", "") or "Agent"),
            agent_id=str(agent.id), agent_name=str(getattr(agent, "name", "")),
            kind="run_bulletin",
        )["id"]
    # meta.kind là thứ giao diện dựa vào để vẽ nút "Xem chi tiết" (mở tab
    # Hoạt động đúng lượt) — nội dung text giữ nguyên là một dòng dữ liệu.
    chat_store.append_message(sid, "assistant", text, meta={
        "kind": "run_bulletin", "run_id": str(run_id or ""), "outcome": outcome,
    })


def _post_telegram(agent, text: str) -> None:
    token = str(getattr(agent, "telegram_token", "") or "").strip()
    chat_id = str(getattr(agent, "telegram_chat_id", "") or "").strip()
    if not token or not chat_id:
        return
    import requests
    name = str(getattr(agent, "name", "") or "").strip()
    body = ("%s — %s" % (name, text)) if name else text
    requests.post(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        json={"chat_id": chat_id, "text": body},
        timeout=8,
    )


def post_end(agent_id: str, run_id: str, outcome: str,
             duration_sec: Optional[float] = None,
             warnings: Optional[list] = None,
             work: Optional[Dict[str, Any]] = None) -> None:
    """Gọi ngay sau run_log.end(). Không bao giờ ném lỗi ra ngoài."""
    try:
        if not agent_id or outcome in ("skipped", None, ""):
            return
        from tubecli.core.agent import agent_manager
        agent = agent_manager.get(str(agent_id))
        if not agent:
            return
        # Một công tắc cho cả cụm "chat biết lịch": tắt routine_in_chat (tab
        # Schedule) là tắt luôn bản tin — người đã không muốn lịch dây vào chat
        # thì cũng không muốn chat bị dội tin mỗi lượt chạy.
        if getattr(agent, "routine_in_chat", True) is False:
            return
        launch = dict(_run_row(str(agent_id), str(run_id or "")).get("launch") or {})
        # error nằm ở work (log của tiến trình), gộp vào để build_text kể phần
        # lỗi riêng — không đọc lại run_log lần nữa.
        if isinstance(work, dict) and work.get("error"):
            launch["error"] = work["error"]
        text = build_text(str(getattr(agent, "name", "")), str(outcome), launch,
                          duration_sec, bool(warnings))

        def work():
            try:
                _post_chat(agent, text, run_id, str(outcome))
            except Exception as e:
                logger.warning("bulletin -> chat failed: %s" % e)
            try:
                _post_telegram(agent, text)
            except Exception as e:
                logger.warning("bulletin -> telegram failed: %s" % e)

        # Thread riêng: Telegram là lời gọi mạng, còn người gọi ta đang đứng
        # trong vòng theo dõi tiến trình — không được bắt nó chờ.
        threading.Thread(target=work, daemon=True, name="run-bulletin").start()
    except Exception as e:
        logger.warning("bulletin skipped: %s" % e)
