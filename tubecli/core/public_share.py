"""Link công khai /s/<token> — kho file tạm cho skill công khai + link do Claude tạo qua trình kết nối.

1) Skill công khai (youtube.download / capcut.tts / reup): `share_path` + `sweep` như trước — file nằm trên máy chủ agent,
   phát cho người lạ qua link chia sẻ của File Manager, chủ máy THẤY và THU HỒI được. Đường dẫn trả về luôn TƯƠNG ĐỐI.

2) Link do Claude tạo (user 5/11/2026): bật «Allow public share links» trên TubeCLI Cloud › Connectors = đồng ý TRƯỚC cho
   mọi link của kết nối đó — `share_file` tạo link và trả URL ngay, không link duyệt. Rào:
   * chỉ file trong DATA_DIR (đường THẬT sau symlink), không đoạn «..», không thư mục/tệp nhạy cảm (BLOCKED_*);
   * chỉ ẢNH và VIDEO (SHAREABLE_TYPES): đuôi VÀ magic bytes của nội dung cùng nhóm image/* hoặc video/* — route /s/
     kiểm lại trước mỗi lần phục vụ (phòng file bị thay sau khi tạo link);
   * hạn mặc định 30 phút (1–1440 phút), hết hạn / thu hồi / tắt quyền → 410 Gone (bia mộ giữ 7 ngày);
   * mỗi kết nối tối đa RATE_PER_HOUR link/giờ; mọi lần tạo/tải ghi nhật ký (giờ, kết nối, file, IP);
   * tắt ô trên Connectors → cloud gọi `shares/revoke` → revoke_grant() giết mọi link đang sống của kết nối đó.
   Bản ghi nằm chung shares.json của File Manager (via="claude", grant=<mã kết nối>) nên tab chia sẻ của File Manager
   vẫn thấy và nút thu hồi vẫn chạy.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── danh sách cho phép: SỬA MỘT CHỖ NÀY ──────────────────────────────────────
# Đuôi → MIME. SVG KHÔNG có: SVG chứa được script. Âm thanh, tài liệu, json/txt/zip/html, file thực thi: từ chối.
SHAREABLE_TYPES: Dict[str, Dict[str, str]] = {
    "image": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".gif": "image/gif"},
    "video": {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"},
}
SHAREABLE_EXTS: Dict[str, Tuple[str, str]] = {ext: (kind, mime) for kind, m in SHAREABLE_TYPES.items()
                                              for ext, mime in m.items()}
REFUSE_TYPE = "Only image and video files can be shared"

DEFAULT_MINUTES, MIN_MINUTES, MAX_MINUTES = 30, 1, 1440
RATE_PER_HOUR = 200
MAX_BATCH = 100
VIA_CLAUDE = "claude"
GONE_KEEP_SEC = 7 * 86400
GONE_MAX = 5000
LOG_MAX_BYTES = 5 * 1048576

# Thư mục/tệp nhạy cảm — so theo TỪNG đoạn đường (chữ thường) bên dưới DATA_DIR.
BLOCKED_SEGMENTS = {
    "browser_profiles", "profiles", "profile", "sessions", "session", "cookies", "cookie", "keychain", "credentials",
    "credential", "secrets", "secret", "tokens", "token", "auth", "oauth", "2fa", "totp", "passwords", "password",
    ".ssh", ".gnupg", ".git", "codex_gpt", "codex_home", ".codex", "auth_manager", "api_keys", "api-keys", "accounts",
}
# Phần tên tệp (chữ thường) — .env*, auth_manager*, cookie*, token*… bị chặn dù nằm ở đâu.
BLOCKED_NAME_PARTS = ("cookie", "token", "secret", "credential", "password", "keychain", "auth_manager", "session",
                      "oauth", "apikey", "api_key")

_LOCK = threading.RLock()


class ShareRefused(Exception):
    """Không chia sẻ được — câu báo trả thẳng cho Claude."""


# ── kho file tạm cho skill công khai (giữ nguyên) ────────────────────────────

def sweep(d: str, ttl: int) -> None:
    """Xoá file cũ quá ttl trong thư mục d — hỏng thì thôi, không chặn lượt gọi."""
    now = time.time()
    try:
        for name in os.listdir(d):
            fp = os.path.join(d, name)
            try:
                if os.path.isfile(fp) and now - os.path.getmtime(fp) > ttl:
                    os.remove(fp)
            except OSError:
                pass
    except OSError:
        pass


def fm_enabled() -> bool:
    try:
        from tubecli.core.extension_manager import extension_manager

        return any(e.name == "file_manager" for e in extension_manager.get_enabled())
    except Exception:      # noqa: BLE001 — không hỏi được thì cứ thử, share hỏng sẽ tự lộ
        return True


def share_path(path: str, name: str, ttl: int) -> str:
    """"/s/<token>" cho file này — tái dùng link còn sống, hết hạn thì phát link mới. Không đụng link do Claude tạo."""
    import secrets

    from tubecli.extensions.file_manager import routes as fmr

    with _LOCK:
        items = fmr._load_shares()
        key = os.path.normcase(os.path.normpath(path))
        now = time.time()
        for it in items:
            if not is_claude(it) and os.path.normcase(os.path.normpath(str(it.get("path") or ""))) == key:
                exp = it.get("expires")
                if not exp or float(exp) > now + 60:
                    return "/s/" + it["token"]
        items = [it for it in items if is_claude(it)
                 or os.path.normcase(os.path.normpath(str(it.get("path") or ""))) != key]
        it = {"token": secrets.token_urlsafe(18), "path": os.path.normpath(path), "name": (name or "")[:120],
              "created": now, "expires": now + ttl, "downloads": 0}
        items.append(it)
        fmr._save_shares(items)
    return "/s/" + it["token"]


# ── loại file: đuôi + magic bytes ────────────────────────────────────────────
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"}
_AUDIO_BRANDS = {b"M4A ", b"M4B ", b"M4P ", b"F4A ", b"F4B "}
_QT_ATOMS = {b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}


def sniff(path: str) -> str:
    """MIME theo NỘI DUNG (vài chục byte đầu) cho các loại được phép, "" khi không nhận ra / không được phép."""
    try:
        with open(path, "rb") as f:
            h = f.read(64)
    except OSError:
        return ""
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "image/webp"
    if h.startswith(b"\x1a\x45\xdf\xa3"):              # EBML — chỉ nhận khi doctype là webm (mkv không nằm trong danh sách)
        return "video/webm" if b"webm" in h else ""
    if len(h) >= 12 and h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in _HEIF_BRANDS or brand in _AUDIO_BRANDS:
            return ""                                   # ảnh HEIF/AVIF, âm thanh m4a — không phải video, không cho
        return "video/quicktime" if brand == b"qt  " else "video/mp4"
    if len(h) >= 8 and h[4:8] in _QT_ATOMS:
        return "video/quicktime"
    return ""


def type_of(path: str) -> Tuple[str, str]:
    """(nhóm, MIME thật) khi đuôi VÀ nội dung cùng là ảnh hoặc cùng là video; không thì ShareRefused."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in SHAREABLE_EXTS:
        raise ShareRefused(f"{REFUSE_TYPE} ({' '.join(SHAREABLE_EXTS)})")
    kind = SHAREABLE_EXTS[ext][0]
    mime = sniff(path)
    if not mime or mime.split("/", 1)[0] != kind:
        raise ShareRefused(f"{REFUSE_TYPE} — the content of this file is not a real {kind}")
    return kind, mime


# ── đường dẫn ────────────────────────────────────────────────────────────────

def data_root() -> str:
    from tubecli import config

    return os.path.realpath(str(config.DATA_DIR))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:          # ổ đĩa khác nhau (Windows)
        return False


def blocked_reason(real: str, root: Optional[str] = None) -> str:
    """"" khi được phép; không thì lý do (thư mục / tên tệp nhạy cảm)."""
    root = root or data_root()
    rel = os.path.relpath(real, root)
    parts = [p.lower() for p in rel.replace("\\", "/").split("/") if p]
    for seg in parts[:-1]:
        if seg in BLOCKED_SEGMENTS or seg.startswith(".env"):
            return f"files under '{seg}' are private and cannot be shared"
    name = parts[-1] if parts else ""
    if name.startswith(".env") or any(x in name for x in BLOCKED_NAME_PARTS):
        return "this file name looks private (session, cookie, token, key…) and cannot be shared"
    return ""


def media_path(collection: Any, filename: Any) -> str:
    """Đường của một file trong kho media (/api/v1/media/collections/<cid>/files/<name>)."""
    cid, fn = str(collection or "").strip(), str(filename or "").strip()
    if not cid or not fn:
        raise ShareRefused("'collection' and 'filename' are both required for a media library file")
    if fn != os.path.basename(fn) or fn in (".", "..") or "/" in fn or "\\" in fn:
        raise ShareRefused("'filename' must be a plain file name inside the collection")
    from tubecli.extensions.media_library import library as ML

    try:
        d = ML.collection_dir(cid)
    except ValueError as e:
        raise ShareRefused(f"Bad collection: {e}") from None
    p = os.path.join(d, fn)
    if not os.path.isfile(p):
        raise ShareRefused(f"No file '{fn}' in media collection '{cid}'")
    return p


def resolve(raw: Any = None, collection: Any = None, filename: Any = None) -> Tuple[str, str, str]:
    """(đường thật, nhóm, MIME) của một file được phép chia sẻ, hoặc ShareRefused nói rõ vì sao không."""
    if collection or filename:
        s = media_path(collection, filename)
    else:
        s = str(raw or "").strip()
        if not s:
            raise ShareRefused("Pass 'path' (from share_find) or 'collection' + 'filename'")
    if "\x00" in s:
        raise ShareRefused("Bad path")
    if ".." in s.replace("\\", "/").split("/"):
        raise ShareRefused("'..' is not allowed in the path")
    root = data_root()
    real = os.path.realpath(os.path.abspath(os.path.expanduser(s)))
    if not _inside(real, root) or real == root:
        raise ShareRefused("Only files inside the TubeCLI data folder can be shared")
    why = blocked_reason(real, root)
    if why:
        raise ShareRefused("Refused: " + why)
    if not os.path.isfile(real):
        raise ShareRefused("No such file (folders cannot be shared)")
    kind, mime = type_of(real)
    return real, kind, mime


def minutes(v: Any) -> int:
    try:
        n = int(v) if v not in (None, "") else DEFAULT_MINUTES
    except (TypeError, ValueError):
        raise ShareRefused(f"'expires_minutes' must be a whole number {MIN_MINUTES}-{MAX_MINUTES}") from None
    if n < MIN_MINUTES or n > MAX_MINUTES:
        raise ShareRefused(f"'expires_minutes' must be {MIN_MINUTES}-{MAX_MINUTES} (default {DEFAULT_MINUTES})")
    return n


# ── nhật ký + giới hạn + bia mộ (cạnh shares.json) ───────────────────────────

def _dir() -> str:
    from tubecli.extensions.file_manager import routes as fmr

    return os.path.dirname(fmr._shares_file())


def _read_json(name: str, default):
    try:
        with open(os.path.join(_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:      # noqa: BLE001
        return default


def _write_json(name: str, data) -> None:
    p = os.path.join(_dir(), name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, p)


def log_event(event: str, **fields) -> None:
    """Một dòng JSON vào share_log.jsonl: giờ, sự kiện, kết nối, file, IP… Lỗi ghi không chặn việc chính."""
    try:
        p = os.path.join(_dir(), "share_log.jsonl")
        if os.path.isfile(p) and os.path.getsize(p) > LOG_MAX_BYTES:
            os.replace(p, p + ".1")
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:      # noqa: BLE001
        pass


def read_log(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(_dir(), "share_log.jsonl"), encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:      # noqa: BLE001
        return []


def _gkey(grant: Any) -> str:
    return str(grant) if grant not in (None, "") else "-"


def rate_left(grant: Any, now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    with _LOCK:
        stamps = [t for t in (_read_json("share_rate.json", {}).get(_gkey(grant)) or []) if now - float(t) < 3600]
    return max(0, RATE_PER_HOUR - len(stamps))


def _rate_take(grant: Any, n: int, now: float) -> None:
    data = _read_json("share_rate.json", {})
    data = {k: [t for t in v if now - float(t) < 3600] for k, v in data.items() if isinstance(v, list)}
    data[_gkey(grant)] = (data.get(_gkey(grant)) or []) + [now] * n
    _write_json("share_rate.json", {k: v for k, v in data.items() if v})


def gone_reason(token: str, now: Optional[float] = None) -> str:
    """Lý do link đã chết (expired / revoked / connection_off) nếu còn bia mộ, "" khi không biết token."""
    now = time.time() if now is None else now
    g = (_read_json("shares_gone.json", {}) or {}).get(str(token or ""))
    if isinstance(g, dict) and now - float(g.get("at") or 0) < GONE_KEEP_SEC:
        return str(g.get("reason") or "revoked")
    return ""


def _bury(tokens_reasons: Iterable[Tuple[str, str]], now: float) -> None:
    gone = _read_json("shares_gone.json", {}) or {}
    for tok, why in tokens_reasons:
        gone[str(tok)] = {"at": now, "reason": why}
    gone = {k: v for k, v in gone.items() if isinstance(v, dict) and now - float(v.get("at") or 0) < GONE_KEEP_SEC}
    if len(gone) > GONE_MAX:
        gone = dict(sorted(gone.items(), key=lambda kv: float(kv[1].get("at") or 0))[-GONE_MAX:])
    _write_json("shares_gone.json", gone)


def is_claude(it: Dict[str, Any]) -> bool:
    return isinstance(it, dict) and it.get("via") == VIA_CLAUDE


def sweep_links(now: Optional[float] = None) -> int:
    """Dọn bản ghi link của Claude đã hết hạn (để lại bia mộ → 410). Trả số bản ghi đã dọn."""
    from tubecli.extensions.file_manager import routes as fmr

    now = time.time() if now is None else now
    with _LOCK:
        items = fmr._load_shares()
        dead = [it for it in items if is_claude(it) and it.get("expires") and float(it["expires"]) <= now]
        if not dead:
            return 0
        _bury(((it["token"], "expired") for it in dead), now)
        dead_t = {it["token"] for it in dead}
        fmr._save_shares([it for it in items if it.get("token") not in dead_t])
    return len(dead)


def revoke(tokens: Iterable[str], reason: str = "revoked", **log) -> int:
    """Thu hồi theo token (mọi loại link). Để lại bia mộ → 410."""
    from tubecli.extensions.file_manager import routes as fmr

    want = {str(t) for t in tokens if t}
    if not want:
        return 0
    now = time.time()
    with _LOCK:
        items = fmr._load_shares()
        hit = [it for it in items if it.get("token") in want]
        if hit:
            fmr._save_shares([it for it in items if it.get("token") not in want])
            _bury(((it["token"], reason) for it in hit), now)
    for it in hit:
        log_event(reason, token=it["token"], grant=it.get("grant"), file=it.get("path"), via=it.get("via") or "", **log)
    return len(hit)


def revoke_grant(grant: Any, reason: str = "connection_off") -> int:
    """Giết mọi link Claude đang sống của MỘT kết nối (chủ tắt «Allow public share links» hay ngắt kết nối)."""
    from tubecli.extensions.file_manager import routes as fmr

    if grant in (None, ""):
        return 0
    g = str(grant)
    toks = [it["token"] for it in fmr._load_shares() if is_claude(it) and str(it.get("grant")) == g]
    return revoke(toks, reason)


def create(files: List[Dict[str, Any]], *, mins: int, grant: Any = None, ip: str = "") -> List[Dict[str, Any]]:
    """files: [{path (đã resolve), kind, mime, name}] → bản ghi mới (một token cho mỗi file). Kiểm giới hạn giờ."""
    import secrets

    from tubecli.extensions.file_manager import routes as fmr

    now = time.time()
    with _LOCK:
        sweep_links(now)
        left = rate_left(grant, now)
        if len(files) > left:
            raise ShareRefused(f"Too many links: at most {RATE_PER_HOUR} per hour for this connection "
                               f"({left} left now). Wait, or share fewer files.")
        items = fmr._load_shares()
        out = []
        for f in files:
            it = {"token": secrets.token_urlsafe(24), "path": os.path.normpath(f["path"]),
                  "name": str(f.get("name") or os.path.basename(f["path"]))[:120], "created": now,
                  "expires": now + mins * 60, "downloads": 0, "via": VIA_CLAUDE,
                  "grant": None if grant in (None, "") else grant, "kind": f["kind"], "mime": f["mime"]}
            items.append(it)
            out.append(it)
        fmr._save_shares(items)
        _rate_take(grant, len(out), now)
    for it in out:
        log_event("create", token=it["token"], grant=it["grant"], file=it["path"], minutes=mins, ip=ip)
    return out


def claude_links(now: Optional[float] = None) -> List[Dict[str, Any]]:
    from tubecli.extensions.file_manager import routes as fmr

    sweep_links(now)
    return [it for it in fmr._load_shares() if is_claude(it)]


def serve_check(it: Dict[str, Any]) -> str:
    """Trước khi phục vụ một link Claude: "" = được; không thì lý do 410 (loại file đổi, đường bị chặn…)."""
    if not is_claude(it):
        return ""
    try:
        _real, kind, _mime = resolve(it.get("path"))
    except ShareRefused as e:
        return str(e)
    if kind != it.get("kind"):
        return "the file changed type after the link was made"
    return ""


def client_ip(request) -> str:
    h = getattr(request, "headers", {}) or {}
    for k in ("cf-connecting-ip", "x-real-ip"):
        v = h.get(k)
        if v:
            return str(v)[:64]
    xf = h.get("x-forwarded-for")
    if xf:
        return str(xf).split(",")[0].strip()[:64]
    c = getattr(request, "client", None)
    return str(getattr(c, "host", "") or "")[:64]
