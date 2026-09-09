"""Sinh tiến trình con mà KHÔNG bật cửa sổ console lên mặt người dùng.

VÌ SAO CÓ FILE NÀY
    Trên Windows, mỗi chương trình console (node.exe, ffmpeg, yt-dlp…) chạy bằng
    subprocess sẽ được hệ điều hành cấp một cửa sổ đen — trừ khi ta nói rõ là
    không. TubeCLI sinh khá nhiều tiến trình node (runner script, preview server,
    công cụ cookie), nên mở một phiên trình duyệt là vài khung đen nhảy lên che
    màn hình, rồi nằm đó tới hết phiên (người dùng gặp 9/9/2026).

    Cờ ấy bị bỏ sót ở từng chỗ gọi một, nên chỗ nhớ chỗ quên. Gom vào đây để chỉ
    còn MỘT nơi phải nhớ, và để test canh được.

CÁI BẪY
    CREATE_NO_WINDOW và CREATE_NEW_CONSOLE loại trừ nhau. Muốn tiến trình con nằm
    ở nhóm riêng (để Ctrl+C ở console máy chủ không giết nó) thì ghép với
    CREATE_NEW_PROCESS_GROUP — ghép được, và đó là tổ hợp trình duyệt đang dùng.
"""
from __future__ import annotations

import os
import subprocess

# Hằng số chỉ tồn tại trên Windows; giữ giá trị thật để mã đọc được ở mọi hệ.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

# Ba cờ này loại trừ nhau theo tài liệu Windows; ghép bừa là hành vi không xác định.
_CONSOLE_INTENT = CREATE_NEW_CONSOLE | DETACHED_PROCESS | CREATE_NO_WINDOW


def hidden_kwargs(extra_flags: int = 0, windows: bool | None = None) -> dict:
    """kwargs cho Popen/run để tiến trình con chạy ẩn.

    `windows` chỉ để test kiểm được cả hai nhánh trên một máy.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return {}
    return {"creationflags": CREATE_NO_WINDOW | extra_flags}


def hidden_run(cmd, **kw):
    """subprocess.run nhưng không nhá cửa sổ console.

    Kể cả `capture_output=True` cũng KHÔNG ngăn được cửa sổ hiện ra: nó chỉ chuyển
    hướng luồng, còn cửa sổ do Windows cấp lúc tạo tiến trình.
    """
    kw.setdefault("creationflags", hidden_kwargs().get("creationflags", 0))
    return subprocess.run(cmd, **kw)


def hidden_popen(cmd, **kw):
    """subprocess.Popen nhưng không nhá cửa sổ console."""
    kw.setdefault("creationflags", hidden_kwargs().get("creationflags", 0))
    return subprocess.Popen(cmd, **kw)


def no_window_flags(flags: int = 0, windows: bool | None = None) -> int:
    """Cờ tạo tiến trình sau khi thêm CREATE_NO_WINDOW — TRỪ KHI người gọi đã nói rõ
    ý muốn về console.

    Người gọi nào cố tình mở console riêng (CREATE_NEW_CONSOLE) hay tách hẳn khỏi
    console (DETACHED_PROCESS) thì phải được tôn trọng: ba cờ ấy loại trừ nhau, ghép
    thêm vào là hành vi không xác định chứ không phải "an toàn hơn".
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows or (flags & _CONSOLE_INTENT):
        return flags
    return flags | CREATE_NO_WINDOW


def install_no_window_default() -> bool:
    """Đặt CREATE_NO_WINDOW làm mặc định cho MỌI tiến trình con của tiến trình này.

    VÌ SAO VÁ TẬN Popen THAY VÌ SỬA TỪNG CHỖ GỌI
        Đếm được 111 chỗ gọi subprocess trong repo không truyền creationflags, và
        node/git/cmd đều là chương trình console — mỗi lần chạy là một khung đen
        nháy lên giữa màn hình người dùng (gặp 9/9/2026 khi mở trình duyệt). Vá
        từng chỗ thì vừa sót vừa hỏng lại ngay ở dòng code tiếp theo ai đó viết;
        subprocess.run/call/check_output đều đi qua Popen, nên một chỗ này phủ hết.

    Trả True nếu vừa cài, False nếu không cần (không phải Windows) hoặc đã cài rồi.
    """
    if os.name != "nt" or getattr(subprocess.Popen, "_tc_no_window", False):
        return False
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        kwargs["creationflags"] = no_window_flags(kwargs.get("creationflags", 0))
        return original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    subprocess.Popen._tc_no_window = True
    return True
