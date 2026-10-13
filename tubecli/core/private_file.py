"""Write JSON that holds secrets so that only the owner can read it.

Used for files such as data/cloud_api_keys.json (provider API keys) and
data/auth_manager.json (OAuth client secrets, access and refresh tokens).
Security review 13/10/2026: those were written with plain open("w"), i.e. with
the process umask — world-readable on a typical Linux box, and a crash mid-write
could leave a truncated file that loads as "no keys".

What this does, and what it does not:
  * The temp file is created 0600 from the start (no chmod-after window), written,
    fsync'd and atomically renamed over the target, so a reader never sees half a file.
  * On Windows, POSIX modes do not apply; the file inherits the ACL of the user's
    data directory (under the user profile), which is the same protection the rest
    of data/ has.
  * It is NOT encryption. Anyone running as the same OS user can read the file.
    Social-account passwords live in the Keychain extension (Fernet) instead.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def write_json_private(path, payload, *, indent: int = 2, ensure_ascii: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=indent, ensure_ascii=ensure_ascii)
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
        pass  # Windows: ACLs, not mode bits — see module docstring
