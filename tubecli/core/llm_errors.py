"""Phân loại lỗi AI / trình duyệt + thời gian chờ theo NHÀ CUNG CẤP (4/11/2026).

Sự cố thật trên VPS: task video hỏng hẳn ở bước viết kịch bản vì «[Codex Error] usage_limit», «[OpenAI Error] 402
Insufficient Balance», «HTTP 502/503», «returned an empty response» — trong khi các lỗi ấy chỉ là TẠM THỜI. Nay lỗi được
xếp loại; loại tạm thời thì thử model khác, rồi hẹn chạy lại (không đánh hỏng), và nhà cung cấp vừa hết lượt được
«nghỉ» một khoảng — không bị gọi lại mỗi phút.
"""
import logging
import re
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger("LLMErrors")

QUOTA, BALANCE, HTTP_5XX, EMPTY, AUTH = "quota", "insufficient_balance", "http_5xx", "empty_response", "auth"
SIGNED_OUT, PAGE_LOAD, OTHER = "browser_signed_out", "page_load_failed", "other"
# Lỗi qua được nếu chờ hoặc đổi model — không phải lỗi của nội dung / cấu hình.
RETRYABLE = (QUOTA, BALANCE, HTTP_5XX, EMPTY, AUTH)
# Nhà cung cấp lỗi loại này thì nghỉ bao lâu (giây).
COOLDOWN = {QUOTA: 60 * 60, BALANCE: 6 * 60 * 60, HTTP_5XX: 10 * 60, EMPTY: 10 * 60, AUTH: 60 * 60}

_RULES = (
    (BALANCE, re.compile(r"\b402\b|insufficient[ _-]?balance|insufficient[ _-]?(?:funds|credit)|payment required"
                         r"|billing|out of credit|credit balance", re.I)),
    (QUOTA, re.compile(r"usage[ _-]?limit|\b429\b|quota|rate[ _-]?limit|too many requests|resource[ _-]?exhausted"
                       r"|exceeded your current|used up|hết quota|daily free allocation", re.I)),
    (AUTH, re.compile(r"\b401\b|unauthori[sz]ed|invalid api key|api key not valid|auth_error|must sign in again"
                      r"|token (?:expired|revoked)", re.I)),
    (HTTP_5XX, re.compile(r"\bHTTP 5\d\d\b|\b50[0-4]\b|server error|bad gateway|service unavailable"
                          r"|gateway time-?out|overloaded", re.I)),
    (EMPTY, re.compile(r"empty (?:response|reply|script|answer)|returned nothing|no content returned", re.I)),
    (SIGNED_OUT, re.compile(r"signed[ _-]?out|not signed in|not logged in|login required|đăng nhập lại", re.I)),
    (PAGE_LOAD, re.compile(r"page (?:did not|failed to) load|net::ERR_|navigation timeout|timeout \d+ms exceeded", re.I)),
)


def classify(text) -> str:
    """Một trong QUOTA / BALANCE / HTTP_5XX / EMPTY / AUTH / SIGNED_OUT / PAGE_LOAD / OTHER."""
    s = str(text or "").strip()
    if not s:
        return EMPTY
    for kind, rx in _RULES:
        if rx.search(s):
            return kind
    return OTHER


def retryable(text) -> bool:
    return classify(text) in RETRYABLE


def provider_of(model: str, provider: str = "") -> str:
    """Nhà cung cấp của một tên model — đủ để đặt thời gian nghỉ (không thay định tuyến của brain)."""
    p = str(provider or "").strip().lower()
    if p:
        return p
    m = str(model or "").strip().lower()
    if m.startswith("codex/"):
        return "codex"
    if m.startswith("muse"):
        return "muse"
    if m.startswith("@cf/"):
        return "cloudflare"
    if m.startswith(("cx/", "ag/", "kr/", "xai/")) or "9router" in m:
        return "9router"
    for key, name in (("gemini", "gemini"), ("gemma", "gemini"), ("claude", "claude"), ("deepseek", "deepseek"),
                      ("grok", "grok"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai")):
        if key in m:
            return name
    if "/" in m:
        return "openrouter"
    return m or "unknown"


# ── thời gian nghỉ theo nhà cung cấp ─────────────────────────────────────────
# CHỈ trong bộ nhớ của tiến trình: giờ chạy lại của TASK đã lưu bền trong meta.retry_at (bảng việc), còn bảng nghỉ này chỉ
# để một lượt không gọi lại nhà vừa hết lượt. Ghi ra đĩa từng làm test giả lập lỗi ghi bẩn dữ liệu thật của máy (4/11/2026).
_LOCK = threading.Lock()
_COOLING: Dict[str, Dict] = {}


def cool_down(provider: str, kind: str, reason: str = "", now: Optional[float] = None) -> float:
    """Cho nhà cung cấp nghỉ theo loại lỗi; trả mốc mở lại (epoch). Loại không có thời gian nghỉ → 0."""
    secs = COOLDOWN.get(kind, 0)
    if not provider or not secs:
        return 0.0
    now = time.time() if now is None else now
    until = now + secs
    with _LOCK:
        old = _COOLING.get(provider) or {}
        if float(old.get("until") or 0) < until:
            _COOLING[provider] = {"until": until, "kind": kind, "reason": str(reason or "")[:200], "at": now}
    return until


def cooling_until(provider: str, now: Optional[float] = None) -> float:
    """Mốc mở lại của nhà cung cấp đang nghỉ, 0 khi đang dùng được."""
    now = time.time() if now is None else now
    with _LOCK:
        until = float((_COOLING.get(str(provider or "")) or {}).get("until") or 0)
    return until if until > now else 0.0


def cooling() -> Dict[str, Dict]:
    """Bản sao bảng nghỉ (cho trang chẩn đoán / test)."""
    with _LOCK:
        return {k: dict(v) for k, v in _COOLING.items()}


def reset() -> None:
    with _LOCK:
        _COOLING.clear()
