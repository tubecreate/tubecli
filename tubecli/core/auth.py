"""Dashboard authentication.

WHY THIS EXISTS
    The API has no authentication and never had any. That was survivable while
    the server only ever listened on 127.0.0.1 — the operating system was the
    boundary. It stops being survivable the moment anybody serves it on a public
    address, because the surface behind it is not a toy:

        GET  /api/v1/files/read?path=<data>/cloud_api_keys.json
             returns every stored provider key in plaintext
        POST /api/v1/extensions/install
             runs git clone + pip install, i.e. arbitrary code execution
        data/browser_profiles
             holds logged-in Google/YouTube sessions

    origin_guard.py held the line by refusing browser requests from any origin
    that is not loopback. That works, but it makes remote use impossible: the
    only way to reach the dashboard from a laptop was to set
    TUBECLI_ALLOWED_ORIGIN_HOSTS, which removes the sole protection rather than
    replacing it. This module is the replacement.

THE SHAPE
    Loopback stays open. A user on their own desktop sees no login screen, which
    is the experience the product has today and the one most installs want.

    A request arriving from anywhere else needs a session. The session is a
    cookie, not a bearer header, for two measured reasons:
      * The dashboard's one SSE consumer uses EventSource
        (website_manager/static/index.html:1502), and EventSource cannot set
        request headers. It does send cookies.
      * fetch() is called from ~100 places across the dashboard and the
        marketplace extensions, with no shared wrapper. Cookies ride along
        automatically; a header would have to be threaded through every one,
        including extension repos this project does not control.

    Cookies bring CSRF exposure, which origin_guard already answers: it refuses
    cross-origin browser requests outright. The two compose — the guard decides
    "may this page talk to us at all", auth decides "is this someone we know".

THE DEFAULT PASSWORD
    Ships as "123456" so the installer can print something the user can act on;
    a random string scrolls past in a `curl | bash` and is then unrecoverable.
    It is deliberately not enough on its own:

      * While the password is still the default, remote requests are REFUSED —
        not merely warned about. Otherwise every fresh install would sit on the
        public internet with a known password during the window between install
        and first login, which is exactly when a scanner finds it.
      * The change is forced at first login and cannot be skipped.

    So the default is a bootstrap credential usable from the machine itself, not
    a way in from outside.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional, Tuple

DEFAULT_PASSWORD = "123456"

# scrypt, from the standard library — no new dependency. These are the
# interactive-login parameters from RFC 7914; they cost ~100 ms and ~16 MB per
# verification, which is nothing for a human login and a great deal for someone
# working through a wordlist.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 32

SESSION_COOKIE = "tubecli_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600      # 30 days; this is a personal tool

# Login throttling. "123456" is the single most-guessed password in existence,
# so the default install must not be brute-forceable in the window before the
# user changes it.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300

_failures: dict = {}      # client key -> (count, first_failure_ts)
_sessions: dict = {}      # token -> expiry timestamp


def _auth_file():
    from tubecli.config import DATA_DIR

    return DATA_DIR / "auth.json"


def _write_private(path, payload: dict) -> None:
    """Write JSON that only the owner can read.

    The file holds a password hash and the session-signing secret. Creating it
    with the default umask would leave it world-readable on a multi-user box,
    and chmod after the fact leaves a window where it is not. Open with 0600
    from the start, and write through a temp file so a crash cannot leave a
    half-written file that reads as "no password configured".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
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


def _load() -> dict:
    path = _auth_file()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        # A corrupt file must not read as "no password set" — that would be an
        # open door. Callers treat an empty dict as "not configured yet", and
        # is_configured() below is what decides, so return empty and let the
        # caller re-seed from the default.
        return {}


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN,
    )


def ensure_initialised() -> None:
    """Create auth.json with the default password if it does not exist yet."""
    if _load().get("password_hash"):
        return
    set_password(DEFAULT_PASSWORD, _is_default=True)


def set_password(password: str, _is_default: bool = False) -> None:
    """Store a new password, and invalidate every existing session.

    Changing the password logs other browsers out; that is the point of changing
    it. The signing secret is rotated at the same time so a stolen cookie cannot
    outlive the change.
    """
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
    salt = secrets.token_bytes(16)
    payload = {
        "version": 1,
        "salt": salt.hex(),
        "password_hash": _hash(password, salt).hex(),
        "is_default": bool(_is_default),
        "secret": secrets.token_hex(32),
        "updated_at": int(time.time()),
    }
    _write_private(_auth_file(), payload)
    _sessions.clear()


def verify_password(password: str) -> bool:
    data = _load()
    stored = data.get("password_hash")
    salt = data.get("salt")
    if not stored or not salt:
        return False
    try:
        candidate = _hash(password, bytes.fromhex(salt))
    except Exception:
        return False
    # compare_digest, not ==, so the answer takes the same time either way.
    return hmac.compare_digest(candidate.hex(), stored)


def is_default_password() -> bool:
    """True while the shipped password has not been replaced.

    Remote access is refused in this state. Read from the stored flag rather
    than by hashing "123456" again, so a user who deliberately re-chooses the
    default is still treated as having chosen it.
    """
    return bool(_load().get("is_default", True))


def is_configured() -> bool:
    return bool(_load().get("password_hash"))


# ── Sessions ─────────────────────────────────────────────────────────

def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def session_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None:
        return False
    if expiry < time.time():
        _sessions.pop(token, None)
        return False
    return True


def destroy_session(token: Optional[str]) -> None:
    if token:
        _sessions.pop(token, None)


# ── Throttling ───────────────────────────────────────────────────────

def _prune(key: str) -> None:
    entry = _failures.get(key)
    if entry and time.time() - entry[1] > _LOCKOUT_SECONDS:
        _failures.pop(key, None)


def throttle_status(key: str) -> Tuple[bool, int]:
    """(locked_out, seconds_remaining) for this client."""
    _prune(key)
    entry = _failures.get(key)
    if not entry or entry[0] < _MAX_ATTEMPTS:
        return False, 0
    remaining = int(_LOCKOUT_SECONDS - (time.time() - entry[1]))
    return True, max(remaining, 1)


def record_failure(key: str) -> None:
    _prune(key)
    count, first = _failures.get(key, (0, time.time()))
    _failures[key] = (count + 1, first)


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


# ── The decision ─────────────────────────────────────────────────────

def is_loopback(host: str) -> bool:
    """Did this request arrive over the loopback interface?

    Judged on the CLIENT address, never on the Host header — Host is supplied by
    the caller and a remote client can send anything it likes. This is the same
    reasoning origin_guard.py documents for its own allowlist.
    """
    if not host:
        return False
    h = host.strip().lower()
    if h.startswith("::ffff:"):          # IPv4 mapped into IPv6
        h = h[7:]
    return h in ("127.0.0.1", "::1", "localhost") or h.startswith("127.")


# Headers that only ever appear when something forwarded the request.
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded",
                  "x-forwarded-host", "cf-connecting-ip")


def behind_proxy(headers) -> bool:
    """Was this request relayed by something else?

    This is what stops the loopback exemption from becoming a bypass. A reverse
    proxy on the same host — nginx, Caddy, or `cloudflared tunnel --url
    http://127.0.0.1:5295` — connects over loopback, so EVERY request it relays
    arrives with client.host == "127.0.0.1". Trusting that address alone would
    mean an internet-facing tunnel silently turned authentication off for the
    whole API, which is the exact opposite of what someone putting a proxy in
    front intends.

    So: a request carrying forwarding headers is never treated as local, no
    matter what address it came from. The proxy operator is expected to
    authenticate at the proxy, or the user logs in normally.

    `headers` is anything with a case-insensitive .get — Starlette's Headers,
    or a plain dict in tests.
    """
    try:
        return any(headers.get(h) for h in _PROXY_HEADERS)
    except Exception:
        return False


def check_request(client_host: str, cookie_token: Optional[str],
                  headers=None) -> Optional[dict]:
    """None when the request may proceed, otherwise the refusal to send back.

    The refusal carries a machine-readable `reason` so the dashboard can show a
    login form, a "set your password first" notice, or a plain error, rather
    than the single opaque "Failed." the product shows today.
    """
    # Local ONLY when nothing relayed it. See behind_proxy() — a same-host
    # reverse proxy or tunnel makes every remote request look like 127.0.0.1.
    if is_loopback(client_host) and not (headers is not None and behind_proxy(headers)):
        return None                       # the machine itself; unchanged behaviour

    if not is_configured():
        # Nothing to check against. Refuse rather than fall open.
        return {"reason": "not_configured",
                "detail": "TubeCLI chưa được thiết lập. Hãy đăng nhập từ chính máy chủ để đặt mật khẩu."}

    # The default password is WARNED ABOUT, not refused.
    #
    # An earlier version blocked every remote request until the password was
    # changed, which closed the window between install and first login. The
    # product owner chose otherwise: a user who does not want to change it
    # should still be able to work, and be told what they are accepting. That
    # is a real trade — anyone who reaches the port and guesses the shipped
    # password gets the same access the owner has, on an API that returns
    # data/cloud_api_keys.json and installs code — so the warning is surfaced
    # everywhere it can be: /api/v1/auth/status, the login screen, a banner in
    # the dashboard, and the console at startup.
    if session_valid(cookie_token):
        return None

    return {"reason": "login_required", "detail": "Cần đăng nhập."}


# ── Read-only key for the scraped corpus ─────────────────────────────
#
# Why this exists at all. The session cookie needs three stateful steps: POST
# the password, keep the Set-Cookie, send it back. Most cloud AI tools cannot
# do that — they perform ONE fetch, some of them GET-only with no way to set a
# header. A cookie-based brief is unusable there, which is what the corpus
# owner ran into.
#
# So: a bearer key that works in a single request, and is deliberately much
# weaker than the password. It is read-only, GET-only, and the gate in
# server.py accepts it on the scraped data paths and nowhere else. The password
# reaches /read, cloud_api_keys.json and code installation; this reaches
# scraped articles. Those are not the same thing to lose, and the whole point
# of handing a brief to a third-party AI is that it WILL be seen by something
# the owner does not control.
#
# Kept in its own file, not in auth.json, because set_password() replaces that
# payload wholesale on purpose — parking a key inside it would have quietly
# revoked the key every time the password changed.
READ_TOKEN_PREFIX = "tcs_"


def _read_token_file():
    from tubecli.config import DATA_DIR

    return DATA_DIR / "scraped_read_key.json"


def _load_read_tokens() -> dict:
    path = _read_token_file()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def scraped_read_token(create: bool = True) -> Optional[str]:
    """The current read key, minting one on first use.

    Stored in plaintext rather than hashed, which is the deliberate trade: the
    brief embeds the key every time it is opened, and a hash would mean showing
    it once and forcing a rotation to ever see it again. The file is written
    0600 alongside the password hash, and the key is narrow enough that its
    disclosure is a different order of problem.
    """
    data = _load_read_tokens()
    token = data.get("token")
    if token:
        return token
    if not create:
        return None
    return rotate_scraped_read_token()


def rotate_scraped_read_token() -> str:
    """Mint a new key. The previous one stops working immediately."""
    token = READ_TOKEN_PREFIX + secrets.token_urlsafe(24)
    _write_private(_read_token_file(), {
        "version": 1,
        "token": token,
        "updated_at": int(time.time()),
    })
    return token


def scraped_read_token_valid(candidate: Optional[str]) -> bool:
    if not candidate or not isinstance(candidate, str):
        return False
    current = scraped_read_token(create=False)
    if not current:
        return False
    # compare_digest so a wrong key takes the same time as a right one.
    return hmac.compare_digest(candidate.strip(), current)


# ── Guest tokens (workspace chia sẻ có phạm vi) ──────────────────────────
# Chủ mint một guest token gắn SCOPE (workspace + profiles/agent_ids/extension
# routes) cho người được chia sẻ. Sharee đăng nhập guest → cookie tubecli_guest
# (KHÁC tubecli_session của chủ). Middleware enforce scope, DENY mặc định.
# Lưu riêng guest_tokens.json (0600) — KHÔNG để trong auth.json vì set_password
# ghi đè wholesale. Ngắn hạn; mất khi restart là chấp nhận (sharee login lại).
GUEST_COOKIE = "tubecli_guest"
GUEST_TOKEN_PREFIX = "gt_"
GUEST_TTL_SECONDS = 6 * 3600
_guest_cache: dict = {}      # token -> {"scope":..., "exp":...} (cache của file)


def _guest_file():
    from tubecli.config import DATA_DIR

    return DATA_DIR / "guest_tokens.json"


def _load_guest_tokens() -> dict:
    path = _guest_file()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def mint_guest_token(scope: dict, ttl_seconds: int = GUEST_TTL_SECONDS) -> dict:
    """Chủ mint token cho một scope. Prune token hết hạn. Trả {guest_token, exp}."""
    token = GUEST_TOKEN_PREFIX + secrets.token_urlsafe(24)
    now = int(time.time())
    exp = now + int(ttl_seconds)
    data = _load_guest_tokens()
    data = {k: v for k, v in data.items()
            if isinstance(v, dict) and int(v.get("exp", 0)) > now}
    data[token] = {"scope": scope if isinstance(scope, dict) else {}, "exp": exp}
    _write_private(_guest_file(), data)
    _guest_cache.clear()
    return {"guest_token": token, "exp": exp}


def guest_scope_for(token: Optional[str]) -> Optional[dict]:
    """Scope nếu guest token hợp lệ + chưa hết hạn; None nếu không (FAIL-CLOSED)."""
    if not token or not isinstance(token, str) or not token.startswith(GUEST_TOKEN_PREFIX):
        return None
    now = int(time.time())
    ent = _guest_cache.get(token)
    if ent is None:
        ent = _load_guest_tokens().get(token)
        if isinstance(ent, dict):
            _guest_cache[token] = ent
    if not isinstance(ent, dict) or int(ent.get("exp", 0)) <= now:
        return None
    scope = ent.get("scope")
    return scope if isinstance(scope, dict) else None


def _canon_fs(path_str: str) -> str:
    """Canonical hoá path GIỐNG HỆT thứ file-manager route THỰC SỰ chạm.

    FileService._validate_path trả normalized = normpath(abspath(expanduser(path)))
    rồi read/list mở CHÍNH chuỗi đó — mà os.open/list follow symlink → nội dung chạm
    tới là realpath(normalized). Gate phải confine ĐÚNG realpath(normalized), nếu không
    thứ tự 'gộp .. rồi mới theo symlink' sẽ LỆCH với 'theo symlink rồi mới gộp ..' của
    realpath(path) thô → symlink NGOÀI-trỏ-VÀO-trong cho phép đọc file ngoài phạm vi.
    """
    import os
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(path_str))))
    return os.path.realpath(normalized)


def path_in_folders(req_path, folders) -> bool:
    """True nếu req_path (canonical hoá như route) nằm TRONG một folder được chia sẻ.

    realpath(normpath(abspath(...))) giải hết '..' + symlink → chặn traversal, symlink
    escape, và mismatch gate↔route. Prefix GHÉP os.sep để '/a/x' KHÔNG khớp nhầm '/a/xy'.
    Từ chối folder '/' (cả máy) và path rỗng. FAIL-CLOSED: mọi lỗi → False.
    """
    import os
    if not req_path:
        return False
    try:
        rp = _canon_fs(req_path)
    except Exception:
        return False
    for f in (folders or []):
        if not f or not os.path.isabs(str(f)):
            continue   # folder PHẢI là path tuyệt đối (chặn '' → CWD, và path tương đối)
        try:
            rf = _canon_fs(f)
        except Exception:
            continue
        if not rf or rf == os.sep:
            continue   # '/' = cả máy → không bao giờ hợp lệ
        base = rf.rstrip(os.sep)
        if rp == base or rp.startswith(base + os.sep):
            return True
    return False


def revoke_guest_tokens_for_workspace(workspace: str) -> int:
    """Thu hồi mọi guest token của một workspace (khi chủ revoke). Trả số xoá."""
    if not workspace:
        return 0
    data = _load_guest_tokens()
    keep = {k: v for k, v in data.items()
            if not (isinstance(v, dict) and (v.get("scope") or {}).get("workspace") == workspace)}
    removed = len(data) - len(keep)
    if removed:
        _write_private(_guest_file(), keep)
        _guest_cache.clear()
    # Dọn thư mục staging Drive (file guest tải về để attach vào browser) của workspace.
    try:
        import shutil
        from tubecli.config import DATA_DIR
        shutil.rmtree(os.path.join(str(DATA_DIR), "guest_drive", str(workspace)), ignore_errors=True)
    except Exception:
        pass
    return removed
