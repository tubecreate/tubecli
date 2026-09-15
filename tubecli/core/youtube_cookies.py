"""Cookie YouTube lấy TỰ ĐỘNG từ hồ sơ browser TubeCLI đang mở (15/9/2026).

User: "thêm option tự động lấy cookies từ browser". Thử thật trên máy dev trước khi làm:
  * YouTube trả "Sign in to confirm you're not a bot" sau vài lần tải liên tiếp (tự hết sau ~30 phút).
  * Hồ sơ có logo YouTube trên thẻ = `profile_manager.detect_logins` thấy TÊN cookie đăng nhập trong SQLite.
    yt-dlp giải mã được cookie của hồ sơ ĐANG TẮT, nhưng Google đã xoay chúng: testlive → "cookies are no
    longer valid", testshardx → "The page needs to be reloaded" (cookie cũ còn làm HỎNG lượt tải vốn chạy được).
  ⇒ chỉ dùng cookie SAU khi bị chặn, chỉ lấy từ hồ sơ ĐANG MỞ (đọc qua CDP — `browser/routes._read_live_cookies`,
    luôn là cookie mới nhất), chỉ giữ cookie youtube.com/google.com, ghi file tạm rồi XOÁ ngay sau lượt tải,
    hồ sơ có proxy thì yt-dlp đi qua đúng proxy đó (một phiên thấy từ hai IP dễ bị Google đăng xuất).

Cài đặt dùng chung với Video Downloader (data/downloader_settings.json):
  cookie_auto_browser  bật/tắt (mặc định bật)
  cookie_profile       "" = tự chọn hồ sơ đang mở đã đăng nhập YouTube; tên hồ sơ = chỉ dùng hồ sơ đó
"""
from __future__ import annotations

import logging
import os
import socket
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("tubecli.youtube_cookies")

MAX_PROFILES = 2                                   # mỗi lượt thử tối đa ngần này hồ sơ đang mở
_KEEP_DOMAINS = ("youtube.com", "google.com")      # cookie đăng nhập YouTube nằm ở hai miền này
_SESSION_NAMES = ("LOGIN_INFO", "__Secure-3PSID", "SID")
_BLOCK_MARKERS = ("sign in to confirm", "not a bot", "confirm your age", "age-restricted", "age restricted",
                  "inappropriate for some users", "login required", "use --cookies", "--cookies-from-browser")


# ── nhận ra lỗi "YouTube đòi đăng nhập" ──────────────────────────────────────

def is_blocked(message: str) -> bool:
    """Lỗi yt-dlp này có phải YouTube đòi đăng nhập (bot-check / giới hạn tuổi) — thứ cookie gỡ được."""
    low = str(message or "").lower()
    return any(m in low for m in _BLOCK_MARKERS)


# ── cài đặt ─────────────────────────────────────────────────────────────────

def _truthy(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")
    return bool(value)


def settings() -> Dict[str, Any]:
    """{"auto", "profile", "pasted", "browser"} — đọc cài đặt của Video Downloader (mặc định: tự động bật)."""
    try:
        from tubecli.extensions.video_downloader.routes import _get_settings
        s = dict(_get_settings() or {})
    except Exception as e:      # noqa: BLE001
        logger.debug("downloader settings unavailable: %s", e)
        s = {}
    return {"auto": _truthy(s.get("cookie_auto_browser"), True),
            "profile": str(s.get("cookie_profile") or "").strip(),
            "pasted": bool(str(s.get("cookie_youtube") or "").strip()),
            "browser": str(s.get("cookies_from_browser") or "").strip()}


# ── hồ sơ browser ───────────────────────────────────────────────────────────

def _pm():
    from tubecli.extensions.browser import profile_manager
    return profile_manager


def _port_open(port, timeout: float = 0.25) -> bool:
    """Có tiến trình nghe ở 127.0.0.1:port không — trả lời trong ~timeout.

    Đo 15/9/2026 trên Windows: hồ sơ đã tắt còn sót file DevToolsActivePort, và phép thử HTTP của browser/routes
    chờ đủ 1,5 s cho mỗi cổng chết (24 hồ sơ = 35 s). Chromium sống nhận kết nối trong vài ms. Dùng 127.0.0.1,
    không "localhost" (bẫy IPv6 trên Windows)."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError, TypeError):
        return False


def _is_live(name: str) -> bool:
    """Hồ sơ có phiên Chromium THẬT đang chạy (cổng CDP sống) — cùng nguồn với browser/routes._live_cdp_port."""
    try:
        from tubecli.extensions.browser_scripts.group_scripts import cdp_port_of
        if cdp_port_of(name):
            return True
    except Exception:      # noqa: BLE001
        pass
    try:
        from tubecli.extensions.browser.routes import _cdp_alive, _devtools_active_port
        port, _mtime = _devtools_active_port(name)
    except Exception:      # noqa: BLE001
        return False
    return bool(port) and _port_open(port) and bool(_cdp_alive(port))


def _youtube_session(db_path: str) -> bool:
    """Kho cookie có cookie phiên của CHÍNH youtube.com (chỉ đọc TÊN, không đọc giá trị)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=0.2)
        try:
            marks = ",".join("?" * len(_SESSION_NAMES))
            row = conn.execute(
                f"SELECT count(*) FROM cookies WHERE name IN ({marks}) "
                "AND (host_key = 'youtube.com' OR host_key LIKE '%.youtube.com')", _SESSION_NAMES).fetchone()
        finally:
            conn.close()
        return bool(row and row[0])
    except Exception:      # noqa: BLE001
        return False


def _profile_proxy_raw(name: str) -> str:
    try:
        return str((_pm()._load_config(name) or {}).get("proxy") or "").strip()
    except Exception:      # noqa: BLE001
        return ""


def candidates(preferred: str = "") -> List[Dict[str, Any]]:
    """Hồ sơ đã đăng nhập YouTube: [{"name", "live", "youtube_session", "proxy"}], đang mở trước.

    Không có giá trị cookie nào ở đây — an toàn để trả cho ô chọn ở Settings.
    """
    pm = _pm()
    base = pm.PROFILES_DIR
    try:
        names = [preferred] if preferred else sorted(os.listdir(base))
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for name in names:
        root = os.path.join(base, name)
        if not name or name.endswith("_bas") or not os.path.isdir(root):
            continue
        try:
            logins = pm.detect_logins(name)
        except Exception:      # noqa: BLE001
            logins = []
        if "youtube" not in logins:
            continue
        db = pm._find_cookie_db(root)
        out.append({"name": name, "live": False, "youtube_session": bool(db and _youtube_session(db)),
                    "proxy": bool(_profile_proxy_raw(name))})
    if out:
        # Dò phiên song song — mỗi hồ sơ tốn tới ~0,25 s khi cổng đã chết.
        with ThreadPoolExecutor(max_workers=min(8, len(out))) as pool:
            for item, live in zip(out, pool.map(lambda c: _is_live(c["name"]), out)):
                item["live"] = bool(live)
    out.sort(key=lambda c: (not c["live"], not c["youtube_session"], c["proxy"], c["name"].lower()))
    return out


def plan(preferred: str = "") -> Dict[str, List[str]]:
    """{"live": hồ sơ đang mở dùng được, "closed": hồ sơ đã đăng nhập nhưng đang tắt}."""
    items = candidates(preferred)
    return {"live": [c["name"] for c in items if c["live"]], "closed": [c["name"] for c in items if not c["live"]]}


def proxy_for(name: str) -> Tuple[Optional[str], str]:
    """(URL proxy cho yt-dlp, lỗi). (None, "") = hồ sơ đi thẳng; (None, lý do) = có proxy mà không đọc được."""
    raw = _profile_proxy_raw(name)
    if not raw:
        return None, ""
    val = raw
    try:
        from tubecli.extensions.browser.proxy_pool import _add_scheme
        got = _add_scheme(raw)
        val = got[0] if isinstance(got, (tuple, list)) else str(got)
    except Exception:      # noqa: BLE001
        val = raw if "://" in raw else "http://" + raw
    try:
        from tubecli.extensions.browser.routes import parse_proxy
        p = parse_proxy(val)
    except Exception:      # noqa: BLE001
        p = None
    if not p or not p.get("scheme_known"):
        return None, "the profile's proxy could not be read"
    auth = (f"{quote(p['user'], safe='')}:{quote(p['password'], safe='')}@" if p.get("user") else "")
    return f"{p['scheme']}://{auth}{p['host']}:{p['port']}", ""


# ── cookie → file Netscape cho yt-dlp ───────────────────────────────────────

def netscape_text(cookies: List[Dict[str, Any]]) -> Tuple[str, int]:
    """(nội dung file cookies.txt, số cookie giữ lại) — CHỈ youtube.com / google.com.

    Cột include_subdomains PHẢI khớp dấu chấm đầu tên miền (http.cookiejar kiểm), cookie HttpOnly mang tiền tố
    "#HttpOnly_", cookie phiên ghi hạn 0 (yt-dlp nạp với ignore_expires)."""
    lines = ["# Netscape HTTP Cookie File", "# TubeCLI: YouTube/Google cookies from an open browser profile"]
    kept = 0
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        dom = str(c.get("domain") or "").strip()
        name = str(c.get("name") or "")
        value = str(c.get("value") or "")
        bare = dom.lstrip(".").lower()
        if not dom or not name or not any(bare == d or bare.endswith("." + d) for d in _KEEP_DOMAINS):
            continue
        if any(ch in name + value + dom for ch in "\t\r\n"):
            continue
        exp = c.get("expires")
        exp = int(exp) if isinstance(exp, (int, float)) and exp > 0 else 0
        lines.append("\t".join([("#HttpOnly_" if c.get("httpOnly") else "") + dom,
                                "TRUE" if dom.startswith(".") else "FALSE",
                                str(c.get("path") or "/"), "TRUE" if c.get("secure") else "FALSE",
                                str(exp), name, value]))
        kept += 1
    return "\n".join(lines) + "\n", kept


def write_cookie_file(cookies: List[Dict[str, Any]]) -> Tuple[Optional[str], int]:
    """Ghi file tạm (mkstemp: chỉ chủ tiến trình đọc được). (None, 0) khi không còn cookie nào sau khi lọc."""
    text, kept = netscape_text(cookies)
    if not kept:
        return None, 0
    fd, path = tempfile.mkstemp(prefix="tubecli_ytc_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path, kept


def remove_file(path: Optional[str]) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def read_live_cookies(name: str):
    """(cookies, lỗi) của phiên đang chạy — qua cookie_tool.cjs (connectOverCDP, không đóng phiên)."""
    from tubecli.extensions.browser.routes import _read_live_cookies
    return _read_live_cookies(name)


def export_attempt(name: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Một lượt thử bằng hồ sơ `name`: ({"profile", "cookiefile", "proxy", "count"}, "") hoặc (None, lý do).

    Người gọi PHẢI remove_file(att["cookiefile"]) sau khi dùng."""
    try:
        cookies, err = read_live_cookies(name)
    except Exception as e:      # noqa: BLE001
        cookies, err = None, str(e)
    if cookies is None:
        return None, ("the browser is not open" if err == "no_session" else f"could not read its cookies ({err})")
    proxy, perr = proxy_for(name)
    if perr:
        return None, perr
    path, kept = write_cookie_file(cookies)
    if not path:
        return None, "its session has no YouTube/Google cookies (log into YouTube in that profile)"
    return {"profile": name, "cookiefile": path, "proxy": proxy, "count": kept}, ""


# ── cookie ĐÃ LƯU trong kho của hồ sơ đang tắt (không mở browser) ──────────
# User 15/9/2026: "vì sao phải mở mới lấy được cookies, không lấy được cookies đã lưu sẵn sao?". Thử lại khi đã có
# node + yt-dlp-ejs: cookie lưu của testshardx tải được, của testlive YouTube báo "no longer valid" (Google đã xoay,
# yt-dlp tải như khách). Lỗi "The page needs to be reloaded" lúc đầu là do THIẾU JS runtime, không phải cookie cũ.
# ⇒ thử cookie đã lưu trước (1–2 s); chỉ khi YouTube vẫn từ chối mới mở ẩn hồ sơ để làm mới.

def _stored_profile_dir(name: str) -> Optional[str]:
    """Thư mục "Default" chứa kho cookie đã lưu (hồ sơ hoặc bản anh em _bas). yt-dlp tìm Local State (khoá giải mã)
    ở thư mục CHA của thư mục được đưa — đưa thẳng thư mục hồ sơ thì nó dò khắp PROFILES_DIR, có thể lấy nhầm khoá."""
    pm = _pm()
    for sub in ("", "_bas"):
        root = os.path.join(pm.PROFILES_DIR, name + sub)
        if not name or not os.path.isdir(root):
            continue
        default = os.path.join(root, "Default")
        db = pm._find_cookie_db(root)
        if db and os.path.isdir(default) and os.path.abspath(db).startswith(os.path.abspath(default) + os.sep):
            return default
    return None


def read_stored_cookies(profile_dir: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(cookie, cảnh báo của yt-dlp) từ kho SQLite — yt-dlp giải mã (DPAPI trên Windows, khoá mặc định/keyring trên
    Linux). Ném lỗi khi kho bị khoá (browser đang chạy trên Windows) hay không đọc được."""
    from yt_dlp.cookies import YDLLogger, extract_cookies_from_browser

    notes: List[str] = []

    class _Collect(YDLLogger):
        def warning(self, message, only_once=False):
            notes.append(str(message))

        def error(self, message, *args, **kwargs):
            notes.append(str(message))

    jar = extract_cookies_from_browser("chromium", profile_dir, _Collect())
    out: List[Dict[str, Any]] = []
    for c in jar:
        if c.value is None:
            continue
        out.append({"domain": c.domain, "name": c.name, "value": c.value, "path": c.path or "/",
                    "expires": c.expires or 0, "secure": bool(c.secure), "httpOnly": False})
    return out, notes


def stored_attempt(name: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Một lượt thử bằng cookie ĐÃ LƯU của hồ sơ: ({"profile", "cookiefile", "proxy", "count", "stored"}, "") hoặc
    (None, lý do). Không mở browser. Người gọi PHẢI remove_file(att["cookiefile"])."""
    prof = _stored_profile_dir(name)
    if not prof:
        return None, "no saved cookie store in the profile"
    proxy, perr = proxy_for(name)
    if perr:
        return None, perr
    try:
        cookies, notes = read_stored_cookies(prof)
    except Exception as e:      # noqa: BLE001
        first = str(e).strip().splitlines()[0][:160] if str(e).strip() else type(e).__name__
        return None, f"could not read its saved cookies ({first})"
    path, kept = write_cookie_file(cookies)
    if not path:
        why = next((n for n in notes if "decrypt" in n.lower()), "")
        return None, "its saved cookies have no YouTube/Google login" + (f" ({why[:120]})" if why else "")
    return {"profile": name, "cookiefile": path, "proxy": proxy, "count": kept, "stored": True}, ""


# ── mở ẨN hồ sơ đang tắt để Google làm mới cookie ───────────────────────────
# User 15/9/2026: "hiện báo lỗi nhưng không có cách giải quyết ngay" — lượt Codex dừng ở "Open a browser profile
# that is logged into YouTube: testkenh, tung1". Cookie trong kho của hồ sơ đang tắt đã bị Google xoay (dùng thẳng
# bị từ chối), nhưng khi Chromium mở hồ sơ và vào youtube.com, trang tự gọi xoay cookie → phiên có cookie mới.

REFRESH_URL = "https://www.youtube.com/"
REFRESH_WAIT = 45        # giây chờ phiên Chromium sống
REFRESH_SETTLE = 8       # giây cho trang YouTube chạy xong việc xoay cookie
REFRESH_MAX_RUN = 150    # trần sống của phiên mở ẩn (monitor của process_manager tự giết)
_REFRESH_LOCK = threading.Lock()


def _pmgr():
    from tubecli.extensions.browser.process_manager import browser_process_manager
    return browser_process_manager


def _launch_block(name: str) -> str:
    """Lý do không mở được hồ sơ này lúc này ("" = mở được) — cùng lời từ chối với /launch."""
    try:
        from tubecli.extensions.browser.routes import _is_launching, is_profile_running, launch_refusal
    except Exception as e:      # noqa: BLE001
        return f"the browser extension is unavailable ({e})"
    ref = launch_refusal(name)
    if ref:
        return str(ref.get("message") or ref.get("code") or "the profile cannot launch on this system")
    if _is_launching(name) or is_profile_running(name):
        return "the profile is already opening or in use"
    return ""


def refresh_attempt(name: str, progress=None, sleep=time.sleep) -> Tuple[Optional[Dict[str, Any]], str]:
    """Mở ẨN hồ sơ đang tắt ở youtube.com, chờ phiên sẵn sàng, xuất cookie (như export_attempt), rồi LUÔN đóng hồ sơ.

    Mỗi lúc chỉ một hồ sơ (RAM: một phiên Chromium ~450–800 MB). Người gọi PHẢI remove_file(att["cookiefile"])."""
    say = progress or (lambda msg: None)
    if not _REFRESH_LOCK.acquire(timeout=REFRESH_MAX_RUN):
        return None, "another browser profile is being refreshed"
    inst_id = ""
    try:
        why = _launch_block(name)
        if why:
            return None, why
        say(f"opening browser profile {name} in the background to refresh its YouTube cookies")
        try:
            res = _pmgr().spawn(profile=name, url=REFRESH_URL, headless=True, manual=True, max_duration=REFRESH_MAX_RUN)
        except Exception as e:      # noqa: BLE001
            return None, f"could not open it ({e})"
        if not isinstance(res, dict) or res.get("status") == "error":
            return None, f"could not open it ({(res or {}).get('error') or 'launch failed'})"
        inst_id = str(res.get("instance_id") or "")
        deadline = time.time() + REFRESH_WAIT
        ready = False
        while time.time() < deadline:
            cur = _pmgr().get_status(inst_id) if inst_id else None
            if cur and cur.get("status") not in ("running", "starting"):
                return None, f"the browser closed before it was ready ({cur.get('status')})"
            if _is_live(name):
                ready = True
                break
            sleep(1.5)
        if not ready:
            return None, f"the browser did not become ready within {REFRESH_WAIT} s"
        sleep(REFRESH_SETTLE)
        att, why = export_attempt(name)
        if att:
            att["refreshed"] = True
        return att, why
    finally:
        if inst_id:
            try:
                _pmgr().terminate(inst_id)
            except Exception as e:      # noqa: BLE001
                logger.warning("could not close the refreshed profile %s: %s", name, e)
        _REFRESH_LOCK.release()


# ── câu chỉ đường khi vẫn bị chặn ───────────────────────────────────────────

def blocked_hint(st: Dict[str, Any], pl: Optional[Dict[str, List[str]]], tried: List[str],
                 opened: Optional[List[str]] = None) -> str:
    """Việc người dùng làm tiếp, theo đúng tình huống (không lời khuyên chung chung)."""
    if not st.get("auto"):
        return ("Turn on «Auto cookies from TubeCLI browser profiles» or paste YouTube cookies in "
                "Video Downloader → Settings.")
    pl = pl or {"live": [], "closed": []}
    if tried:
        return (f"YouTube also refused the cookies of {', '.join(tried)} — sign in to YouTube again in that profile "
                "(open youtube.com), or paste fresh cookies in Video Downloader → Settings.")
    if pl["live"]:
        shown = ", ".join(pl["live"][:5])
        return (f"Could not read YouTube cookies from the open browser profile(s) {shown} — make sure YouTube is "
                "logged in there, or paste cookies in Video Downloader → Settings.")
    if st.get("profile") and not pl["closed"]:
        return (f"The browser profile «{st['profile']}» chosen in Video Downloader → Settings is not logged into "
                "YouTube — log in there or pick another profile.")
    if pl["closed"]:
        more = len(pl["closed"]) - 5
        shown = ", ".join(pl["closed"][:5]) + (f" and {more} more" if more > 0 else "")
        tried_open = f" Opening {'; '.join(opened)} in the background did not work." if opened else ""
        return (f"Open a browser profile that is logged into YouTube, then try again: {shown}.{tried_open} "
                "Or paste cookies in Video Downloader → Settings.")
    return ("No browser profile is logged into YouTube — log into YouTube in a browser profile and keep it open, "
            "or paste cookies in Video Downloader → Settings.")
