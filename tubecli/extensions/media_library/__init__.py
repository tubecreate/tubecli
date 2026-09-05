"""Kho nguyên liệu — API Python cho các extension khác dùng.

Đây là mặt tiền mà extension khác gọi vào. Nhập thẳng `library` cũng chạy,
nhưng nhập qua đây thì bề mặt hẹp và ổn định hơn:

    from tubecli.extensions.media_library import collections, pick_media

    for c in collections():
        print(c["id"], c["name"], c["count"])

    path, why = pick_media("kho_avatar", mode="cycle")
    if path:
        ...
"""
from .library import (KIND_GIF, KIND_IMAGE, KIND_VIDEO, get, list_all,
                      list_files, peek_cycle, pick, stats)
# Bộ dò extension nội bộ tìm `extension_instance` ở ngay package, không phải
# ở module con. Dùng lại đúng một instance để không có hai bản sống song song.
from .extension import extension_instance  # noqa: E402


def collections():
    """Mọi kho, kèm số file và ảnh bìa."""
    return list_all()


def collection(cid: str):
    """Một kho, hoặc None."""
    return get(cid)


def files(cid: str):
    """File trong một kho, thứ tự ổn định."""
    return list_files(cid)


def pick_media(cid: str, *, mode: str = "random", commit: bool = True,
               chosen: str = "", kind: str = ""):
    """Bốc một file. Trả (đường dẫn tuyệt đối, lý do); kho rỗng trả ("", lý do).

    `mode`: "random" | "cycle" | "ai". `kind`: "" | "image" | "gif" | "video".
    `commit=False` để xem trước mà không dời con trỏ xoay vòng.
    """
    return pick(cid, mode, commit=commit, chosen=chosen, kind=kind)


def exists(cid: str) -> bool:
    return get(cid) is not None


__all__ = ["extension_instance", "collections", "collection", "files", "pick_media", "exists",
           "peek_cycle", "stats", "KIND_IMAGE", "KIND_GIF", "KIND_VIDEO"]
