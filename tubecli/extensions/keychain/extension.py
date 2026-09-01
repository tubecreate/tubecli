"""Keychain — két tài khoản mạng xã hội của người dùng.

Giữ credential (Facebook, TikTok, X, Discord, Telegram, Google, generic) đã mã
hoá, và gán vào profile trình duyệt để agent DÙNG được mà không thấy mật khẩu.
Cố ý mỏng: két chỉ lưu + gán; đăng nhập là việc của trình duyệt (cookie-first),
agent chỉ biết "profile này có tài khoản gì" qua chip đăng nhập đã có sẵn.
"""
import os
import logging

from tubecli.core.extension_manager import Extension
from tubecli.config import EXTENSIONS_DATA_DIR

logger = logging.getLogger("KeychainExtension")

_DATA_DIR = os.path.join(EXTENSIONS_DATA_DIR, "keychain")
_DATA_FILE = os.path.join(_DATA_DIR, "accounts.json")


class KeychainExtension(Extension):
    name = "keychain"
    version = "0.1.0"
    description = "Két tài khoản mạng xã hội đã mã hoá; gán vào profile cho agent dùng"
    author = "TubeCreate"
    extension_type = "system"

    def on_enable(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        from . import crypto, store as store_mod
        from .routes import set_store
        crypto.init(_DATA_DIR)
        self._store = store_mod.KeychainStore(_DATA_FILE)
        set_store(self._store)
        logger.info("Keychain enabled (crypto ready=%s)", crypto.is_ready())

    def get_routes(self):
        from .routes import router
        return router


extension_instance = KeychainExtension()
