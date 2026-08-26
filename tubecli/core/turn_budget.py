"""Hạn mức cho MỘT lượt của người dùng — dùng chung cho mọi đường vào agent.

VÌ SAO LÀ MỘT MODULE RIÊNG
    Trần này ra đời trong `extensions/chat/pipeline.py`, và `run_turn` — hàm
    duy nhất mở ngân sách — chỉ có đúng MỘT caller: `extensions/chat/routes.py`.
    Hai đường vào khác gọi thẳng `AgentBrain` và không bao giờ mở ngân sách:

        core/telegram_listener.py   — mỗi tin nhắn Telegram là một lượt
        extensions/codex/executor.py — mỗi task trong hàng đợi là một lượt

    Trần chỉ che chat web thì agent chạy qua Telegram vẫn làm bao nhiêu việc
    cũng được, và skill-gọi-skill vẫn không có trần độ sâu. Nên luật nằm ở
    `core/`, nơi cả ba đường vào đều với tới được mà không phải import ngược
    từ extension.

CÁCH DÙNG
    Mở ngân sách ở ĐẦU một lượt (một tin nhắn, một task):

        with turn_budget() as budget:
            refusal = depth_refusal(budget)
            if refusal:
                return refusal
            ...

    Tiêu một suất ngay TRƯỚC khi chạy một việc:

        capped = spend_action("download_video")
        if capped:
            return capped        # câu trả lời đã soạn sẵn cho người dùng

    Chỗ tiêu chính là `telegram_actions._run_action` — dispatcher duy nhất mọi
    action đi qua. Caller nào chạy việc mà KHÔNG qua dispatcher (fast-path tải
    video, chạy skill) thì tự tiêu lấy một suất.
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Dict, Optional

# Đây là trần tối thiểu: đếm việc THẬT SỰ chạy, chạm trần thì dừng và trả lời.
MAX_ACTIONS_PER_TURN = 12
# Agent tự kích hoạt agent/skill lồng nhau (skill gọi skill gọi skill).
MAX_TURN_DEPTH = 3

# Ngân sách là một dict DÙNG CHUNG chứ không phải con số trong ContextVar: một
# lượt lồng nhau có thể chạy trong context đã được copy (asyncio.to_thread,
# Task mới) — copy thì `set()` không dội ngược ra ngoài, còn sửa tại chỗ một
# dict thì mọi tầng vẫn nhìn thấy. Trần mà nhánh con tự làm mới là trần rỗng.
_TURN_BUDGET: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar(
    "tubecli_chat_turn_budget", default=None)


@contextlib.contextmanager
def turn_budget():
    """Ngân sách của lượt hiện tại; lượt lồng bên trong DÙNG CHUNG ngân sách đó."""
    budget = _TURN_BUDGET.get()
    token = None
    if budget is None:
        budget = {"actions": 0, "depth": 0}
        token = _TURN_BUDGET.set(budget)
    budget["depth"] += 1
    try:
        yield budget
    finally:
        budget["depth"] -= 1
        if token is not None:
            _TURN_BUDGET.reset(token)


def spend_action(what: str) -> Optional[str]:
    """Ghi nhận MỘT hành động sắp chạy trong lượt này.

    None = còn hạn mức. Một chuỗi = đã chạm trần, hãy trả chuỗi đó cho người
    dùng thay vì chạy tiếp. Không có ngân sách nào đang mở (caller chưa mở
    turn_budget) thì không chặn — trần này thuộc về một lượt, không phải một
    lời gọi hàm lẻ.
    """
    budget = _TURN_BUDGET.get()
    if budget is None:
        return None
    budget["actions"] += 1
    if budget["actions"] <= MAX_ACTIONS_PER_TURN:
        return None
    return (f"🛑 Mình đã làm {MAX_ACTIONS_PER_TURN} việc trong một lượt rồi, dừng lại "
            f"để bạn xem qua trước.\n\nViệc tiếp theo ({what}) CHƯA chạy — nhắn "
            f"\"làm tiếp\" nếu bạn muốn mình chạy nốt.")


def depth_refusal(budget: Dict[str, Any]) -> Optional[str]:
    """Câu từ chối khi agent tự kích hoạt chính nó quá sâu, hoặc None."""
    if budget.get("depth", 1) <= MAX_TURN_DEPTH:
        return None
    return (f"🛑 Chuỗi tự kích hoạt đã đi {MAX_TURN_DEPTH} tầng (skill gọi skill) và "
            f"mình dừng ở đây.\n\nHãy nói rõ việc bạn cần để mình làm thẳng một lượt.")
