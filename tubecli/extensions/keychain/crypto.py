"""Mã hoá at-rest cho Keychain.

Két này giữ mật khẩu THẬT của người dùng cho các mạng xã hội. auth_manager
(anh em của nó) lưu token dạng trần — Keychain cố ý không đi theo: một file đĩa
lộ ra là mất tài khoản chính, không phải nick rác.

Khoá Fernet nằm ở một file riêng (chmod 600), sinh ngẫu nhiên lần đầu. Mất khoá
= mất khả năng giải mã (đúng như mọi két): đó là cái giá của "không giữ khoá
cạnh mật khẩu dạng trần". Chỉ ba trường nhạy cảm được mã hoá (mật khẩu, khôi
phục, 2FA); username thì không — giao diện và agent cần thấy "có tài khoản X"
mà không phải giải mã, và username vốn không phải bí mật cao.
"""
import os
import base64
import logging
from typing import Optional

logger = logging.getLogger("KeychainCrypto")

_KEY_FILE_NAME = "master.key"
_fernet = None
_key_dir = None


def init(key_dir: str) -> None:
    """Nạp (hoặc sinh) khoá. Gọi một lần khi extension bật."""
    global _key_dir
    _key_dir = key_dir
    _load()


def _key_path() -> str:
    return os.path.join(_key_dir or ".", _KEY_FILE_NAME)


def _load():
    global _fernet
    from cryptography.fernet import Fernet
    path = _key_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        # Ghi khoá TRƯỚC khi đóng, rồi siết quyền. 0o600: chỉ chủ tiến trình
        # đọc — trên POSIX là hàng rào thật, trên Windows chmod là no-op nên
        # ở đó két chỉ an toàn ngang quyền thư mục data (đã nằm sau login).
        with open(path, "wb") as f:
            f.write(key)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        logger.info("Keychain: sinh khoá mã hoá mới tại %s", path)
    _fernet = Fernet(key)


def _cipher():
    if _fernet is None:
        raise RuntimeError("Keychain crypto chưa init()")
    return _fernet


def encrypt(plain: Optional[str]) -> str:
    """Chuỗi thường -> chuỗi mã hoá (an toàn để ghi đĩa). '' và None -> ''."""
    if not plain:
        return ""
    token = _cipher().encrypt(plain.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: Optional[str]) -> str:
    """Ngược lại. Token hỏng/khoá sai -> '' (không làm sập lời gọi)."""
    if not token:
        return ""
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.warning("Keychain: giải mã thất bại (%s)", e)
        return ""


def is_ready() -> bool:
    return _fernet is not None
