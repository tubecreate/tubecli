"""9Router — MỘT chỗ biết nó ở đâu.

Trước 13/9/2026 hơn ba chục chỗ viết cứng http://localhost:20128/v1, nên TubeCLI chỉ dùng
được 9Router chạy trên CHÍNH máy mình. Người dùng muốn trỏ sang 9Router của máy khác qua tên
miền tunnel (vd <máy>-9router.tubecreate.com) — 9Router đó đòi key ("API key required for
remote API access"). Endpoint lưu trong Cloud API Keys (key_manager.set_base_url, nằm cạnh
danh sách model của provider); mọi chỗ gọi 9Router hỏi qua đây.
"""
from typing import Optional

DEFAULT_BASE = "http://localhost:20128/v1"


def user_agent() -> str:
    """User-Agent cho mọi lượt gọi 9Router.

    Tunnel Cloudflare trước 9Router ở máy khác CHẶN User-Agent mặc định của urllib ("error
    code: 1010") và của OpenAI SDK ("Your request was blocked.") — đo 13/9/2026 — nhưng cho
    qua User-Agent riêng. Không có nó thì key đúng vẫn nhận 403.
    """
    try:
        from tubecli import __version__
        return f"TubeCLI/{__version__}"
    except Exception:      # noqa: BLE001
        return "TubeCLI"


def base_url() -> str:
    """Endpoint chuẩn OpenAI của 9Router đang dùng, không có "/" cuối."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        return (key_manager.get_base_url("9router") or DEFAULT_BASE).rstrip("/")
    except Exception:      # noqa: BLE001 — cloud_api chưa nạp được thì vẫn là máy này
        return DEFAULT_BASE


def models_url() -> str:
    return base_url() + "/models"


def chat_url() -> str:
    return base_url() + "/chat/completions"


def api_key() -> str:
    """Key đang bật của 9Router, "" nếu chưa có."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        return key_manager.get_active_key("9router") or ""
    except Exception:      # noqa: BLE001
        return ""


def auth_headers(key: Optional[str] = None) -> dict:
    """User-Agent của TubeCLI + "Authorization: Bearer …" khi có key (9Router ở máy khác bắt
    buộc có key; tunnel Cloudflare của nó chặn User-Agent mặc định — xem user_agent())."""
    k = api_key() if key is None else key
    headers = {"User-Agent": user_agent()}
    if k:
        headers["Authorization"] = f"Bearer {k}"
    return headers


def is_local() -> bool:
    """Endpoint trỏ về chính máy này (localhost / 127.x): tắt thì bị từ chối tức thì, nên
    chỗ dò nhanh được phép chờ ngắn; endpoint ở máy khác thì phải chờ lâu hơn."""
    try:
        from tubecli.extensions.cloud_api.extension import is_local_url
        return is_local_url(base_url())
    except Exception:      # noqa: BLE001
        return True
