"""Encrypted store for the user's CapCut accounts.

A CapCut account is email + password, and the password must stay RECOVERABLE —
the wrapper hands it to the Node server as an `x-capcut-password` header on every
synthesize call, so a one-way hash (like auth.py uses for the dashboard
password) is not an option here. Instead the password is encrypted with
AES-GCM under a key that lives in its own 0600 file, next to but separate from
the account list. Reading accounts.json alone yields nothing usable; the key
file is what decrypts it. This mirrors the CapCut project's own secretBox
(src/lib/admin/secretBox.ts), which stores passwords the same way.

Everything lives under ext_data_path("capcut_tts", …) so it moves with the rest
of the extension's data and is covered by the 0600 discipline below rather than
the world-readable default that cloud_api_keys.json shipped with.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tubecli.config import ext_data_path

logger = logging.getLogger("CapCutTTS.accounts")

_EXT = "capcut_tts"


def _accounts_file():
    return ext_data_path(_EXT, "accounts.json")


def _key_file():
    return ext_data_path(_EXT, ".enc_key")


def _write_private(path, data: bytes) -> None:
    """Write a file only the owner can read (0600), via a temp file + replace.

    The same technique auth.py uses for the password hash: open 0600 from the
    start so there is never a window where the secret is world-readable, and
    write through a temp file so a crash cannot leave a half-written key.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    os.replace(str(tmp), str(path))
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass  # Windows ACLs do not map onto this; the file is under the profile


def _load_key() -> bytes:
    """The 32-byte AES key, minted on first use and kept 0600."""
    kf = _key_file()
    if kf.exists():
        try:
            raw = kf.read_bytes()
            if len(raw) == 32:
                return raw
        except OSError:
            pass
    key = os.urandom(32)
    _write_private(kf, key)
    return key


def _encrypt(plaintext: str) -> str:
    """AES-GCM → base64(nonce).base64(ciphertext). Nonce is 12 fresh bytes."""
    key = _load_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce).decode() + "." + base64.b64encode(ct).decode()


def _decrypt(sealed: str) -> Optional[str]:
    """Reverse of _encrypt. Returns None on any failure (wrong key, tampered)."""
    try:
        nonce_b64, ct_b64 = sealed.split(".", 1)
        key = _load_key()
        pt = AESGCM(key).decrypt(base64.b64decode(nonce_b64), base64.b64decode(ct_b64), None)
        return pt.decode("utf-8")
    except Exception:
        return None


class AccountStore:
    """The user's CapCut accounts, keyed by lowercased email."""

    def __init__(self):
        self._accounts: Dict[str, dict] = {}
        self._load()

    def _load(self):
        p = _accounts_file()
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._accounts = data
        except (OSError, ValueError) as e:
            logger.warning("Could not read accounts file: %s", e)
            self._accounts = {}

    def _save(self):
        _write_private(_accounts_file(), json.dumps(self._accounts, ensure_ascii=False, indent=2).encode("utf-8"))

    # ── mutations ──────────────────────────────────────────────────────────
    def add(self, email: str, password: str, label: str = "") -> dict:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            return {"status": "error", "message": "Email không hợp lệ."}
        if not password:
            return {"status": "error", "message": "Chưa nhập mật khẩu CapCut."}
        self._load()
        existing = self._accounts.get(email, {})
        self._accounts[email] = {
            "email": email,
            "password_enc": _encrypt(password),
            "label": label or existing.get("label", ""),
            "enabled": existing.get("enabled", True),
            "added_at": existing.get("added_at") or int(time.time()),
            "last_used_at": existing.get("last_used_at", 0),
            "last_error": "",
        }
        self._save()
        return {"status": "success", "message": f"Đã lưu tài khoản {email}."}

    def remove(self, email: str) -> dict:
        email = (email or "").strip().lower()
        self._load()
        if email in self._accounts:
            del self._accounts[email]
            self._save()
            return {"status": "success", "message": f"Đã xoá {email}."}
        return {"status": "error", "message": f"Không tìm thấy {email}."}

    def set_enabled(self, email: str, enabled: bool) -> dict:
        email = (email or "").strip().lower()
        self._load()
        acc = self._accounts.get(email)
        if not acc:
            return {"status": "error", "message": f"Không tìm thấy {email}."}
        acc["enabled"] = bool(enabled)
        self._save()
        return {"status": "success"}

    def record_use(self, email: str, error: str = "") -> None:
        email = (email or "").strip().lower()
        self._load()
        acc = self._accounts.get(email)
        if acc:
            acc["last_used_at"] = int(time.time())
            acc["last_error"] = error or ""
            self._save()

    # ── reads ──────────────────────────────────────────────────────────────
    def list_masked(self) -> List[dict]:
        """Accounts without the password — safe to send to the dashboard."""
        self._load()
        out = []
        for acc in self._accounts.values():
            out.append({
                "email": acc.get("email", ""),
                "label": acc.get("label", ""),
                "enabled": acc.get("enabled", True),
                "added_at": acc.get("added_at", 0),
                "last_used_at": acc.get("last_used_at", 0),
                "last_error": acc.get("last_error", ""),
            })
        out.sort(key=lambda a: a.get("added_at", 0))
        return out

    def get_credentials(self, email: str) -> Optional[Dict[str, str]]:
        """Decrypt one account's password for a real CapCut call. None if the
        account is missing or the ciphertext cannot be opened."""
        email = (email or "").strip().lower()
        self._load()
        acc = self._accounts.get(email)
        if not acc:
            return None
        pw = _decrypt(acc.get("password_enc", ""))
        if pw is None:
            return None
        return {"email": acc["email"], "password": pw}

    def bootstrap_account(self) -> Optional[Dict[str, str]]:
        """The account the Node server boots with (its default/fallback).

        The server refuses to start without one valid CAPCUT_EMAIL/PASSWORD, so
        the first ENABLED account is used to seed it. Per-user requests override
        it with headers; this one only backs /v2/languages and /v2/preview,
        which the Node build always serves from the default account.
        """
        self._load()
        for acc in sorted(self._accounts.values(), key=lambda a: a.get("added_at", 0)):
            if acc.get("enabled", True):
                pw = _decrypt(acc.get("password_enc", ""))
                if pw:
                    return {"email": acc["email"], "password": pw}
        return None

    def count_enabled(self) -> int:
        self._load()
        return sum(1 for a in self._accounts.values() if a.get("enabled", True))


account_store = AccountStore()
