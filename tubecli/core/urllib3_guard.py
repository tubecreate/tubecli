"""Gỡ lớp bọc chồng của yt-dlp trên urllib3 (24/11/2026 — contabo: «Download failed: download failed after 4 attempts:
'Urllib3PercentREOverride' object has no attribute 'sub'»).

yt-dlp (yt_dlp/networking/_requests.py) bọc urllib3.util.url._PERCENT_RE bằng Urllib3PercentREOverride khi được import.
ytdlp_manager tự cập nhật yt-dlp rồi xoá yt_dlp khỏi sys.modules để lần import sau nạp mã mới — nhưng urllib3 KHÔNG nạp
lại, nên mỗi lần như vậy lại bọc thêm một lớp lên chính lớp cũ. Lớp ngoài chuyển tiếp thuộc tính bằng
`self.re.__getattribute__(item)`, mà gọi thẳng __getattribute__ thì bỏ qua __getattr__ của lớp trong: từ lớp thứ hai trở
đi chỉ còn `subn` dùng được. urllib3 ≥ 2.8 gọi thêm `_PERCENT_RE.sub(...)` khi chuẩn hoá địa chỉ ⇒ MỌI requests.get trong
tiến trình TubeCLI hỏng: tải nhân ShardX, đọc manifest (máy kẹt ở bản cũ đã lưu), API riêng…

  unwrap()  trả _PERCENT_RE về regex gốc (gọi TRƯỚC khi xoá yt_dlp khỏi sys.modules: lần import sau bọc đúng một lớp)
  heal()    gộp nhiều lớp còn MỘT (lớp ngoài cùng — của bản yt-dlp mới nhất) — gọi trước việc mạng quan trọng
"""
import logging

logger = logging.getLogger("Urllib3Guard")
_NAME = "Urllib3PercentREOverride"


def _layers():
    try:
        import urllib3.util.url as U
    except Exception:          # noqa: BLE001 — không có urllib3: không có gì để sửa
        return None, None, []
    attr = "_PERCENT_RE" if hasattr(U, "_PERCENT_RE") else ("PERCENT_RE" if hasattr(U, "PERCENT_RE") else None)
    if not attr:
        return U, None, []
    chain, cur = [], getattr(U, attr)
    while type(cur).__name__ == _NAME and "re" in getattr(cur, "__dict__", {}) and len(chain) < 64:
        chain.append(cur)
        cur = cur.__dict__["re"]
    return U, attr, chain + [cur]


def depth() -> int:
    """Số lớp bọc hiện tại (0 = regex gốc)."""
    _, _, chain = _layers()
    return max(0, len(chain) - 1)


def unwrap() -> int:
    """Trả về regex gốc. Trả số lớp đã gỡ."""
    U, attr, chain = _layers()
    if not attr or len(chain) < 2:
        return 0
    setattr(U, attr, chain[-1])
    return len(chain) - 1


def heal() -> int:
    """Còn đúng một lớp bọc (giữ lớp ngoài cùng, trỏ thẳng vào regex gốc). Trả số lớp đã gộp bớt."""
    U, attr, chain = _layers()
    if not attr or len(chain) <= 2:
        return 0
    outer, raw = chain[0], chain[-1]
    outer.__dict__["re"] = raw
    removed = len(chain) - 2
    logger.warning("urllib3: collapsed %d stacked yt-dlp wrapper(s) on %s", removed, attr)
    return removed
