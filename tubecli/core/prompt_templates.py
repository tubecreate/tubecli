"""Prompt gửi model đặt trong FILE mẫu (tubecli/prompts/<tên>.txt), không viết rải rác trong mã (4/11/2026).

Chỗ trống viết `{{tên}}` — thay bằng str.replace, nên dấu ngoặc nhọn của JSON mẫu trong prompt không cần thoát.
"""
import os
from functools import lru_cache
from typing import Any

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")


@lru_cache(maxsize=32)
def _read(name: str) -> str:
    with open(os.path.join(_DIR, name + ".txt"), encoding="utf-8") as f:
        return f.read()


def render(name: str, **values: Any) -> str:
    """Nội dung mẫu `name` với mọi `{{khoá}}` đã thay. Khoá không truyền thì để trống."""
    text = _read(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value if value is not None else ""))
    return text
