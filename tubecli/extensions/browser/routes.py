"""
Browser Extension — API routes.
"""
from fastapi import APIRouter, HTTPException, Request, File, UploadFile, Form
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
import os
import re
import sys
import platform
import json
import subprocess
import threading
import asyncio
from pathlib import Path

# Note: psutil and requests are imported lazily inside handlers to avoid
# preventing route registration when these packages aren't installed.

from .profile_manager import list_profiles, create_profile, get_profile, update_profile, delete_profile, get_fingerprint, reset_fingerprint, refresh_fingerprint

router = APIRouter(prefix="/api/v1/browser", tags=["browser"])

# Track download processes
download_processes = {}
# Versions the user asked to cancel. Downloads run in a thread, not a subprocess,
# so there is nothing to terminate — the transfer loop checks this instead.
download_cancelled = set()


class ProfileCreateRequest(BaseModel):
    name: str
    proxy: str = ""
    browser_version: str = "latest"
    version: Optional[str] = None  # Compatibility with UI sending 'version'
    tags: List[str] = ["Windows", "Chrome"]
    window_size: Optional[dict] = None   # {"width": 1920, "height": 1080}
    chrome_version: Optional[str] = ""

class ProfileUpdateRequest(BaseModel):
    proxy: Optional[str] = None
    browser_version: Optional[str] = None
    version: Optional[str] = None # Compatibility with UI
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    google_account: Optional[Any] = None  # Can be raw string or dict
    facebook_account: Optional[Any] = None
    tiktok_account: Optional[Any] = None
    x_account: Optional[Any] = None
    discord_account: Optional[Any] = None
    telegram_account: Optional[Any] = None
    window_size: Optional[dict] = None   # {"width": int, "height": int}
    chrome_version: Optional[str] = None

class LaunchRequest(BaseModel):
    profile: str
    prompt: str = ""
    # No start page by default. Opening a profile by hand always forced a
    # navigation to google.com, and on the ShardX engine that navigation cannot
    # be driven over the automation channel at all: it timed out and left the
    # first tab spinning. The profile opens its own start pages anyway, and a
    # caller that genuinely needs a page (an OAuth callback) still passes one.
    url: str = ""
    headless: bool = False
    manual: bool = True
    # Empty = "caller has no opinion"; spawn() resolves it against the
    # default browser AI and then the user's default AI.
    ai_model: str = ""
    context: Optional[dict] = None

class StopRequest(BaseModel):
    profile: str
    # Mặc định dọn triệt để: tìm theo thư mục profile nên bắt được cả tiến trình mồ
    # côi còn sót sau khi TubeCLI restart. force=False giữ hành vi cũ (chỉ dừng cái
    # đang theo dõi trong RAM).
    force: bool = True


@router.get("/profiles")
async def api_list_profiles():
    from .profile_manager import list_profiles
    from . import shardx_runtime as sx
    profiles = await asyncio.to_thread(list_profiles)
    # The page needs to know the host to decide what to show. A BAS key is
    # meaningless where BAS cannot run, and launching a window on the machine only
    # makes sense where there is a display — on a headless server or in a container
    # that button could never do anything.
    return {
        "profiles": profiles,
        "platform": {
            "os": sys.platform,
            "bas_available": sx.supports_bas(),
            "can_open_window": _has_display(),
        },
    }


def _has_display() -> bool:
    """Whether a browser window could appear on this machine at all."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

@router.post("/profiles")
async def api_create_profile(req: ProfileCreateRequest):
    from .profile_manager import create_profile
    try:
        # Map 'version' to 'browser_version' if needed
        version = req.version or req.browser_version
        profile = await asyncio.to_thread(
            create_profile,
            req.name,
            proxy=req.proxy,
            browser_version=version,
            tags=req.tags,
            window_size=req.window_size,
            chrome_version=req.chrome_version or "",
        )
        return {"status": "created", "profile": profile}
    except ValueError as e:
        raise HTTPException(409, str(e))

@router.get("/profiles/{name}")
async def api_get_profile(name: str):
    from .profile_manager import get_profile
    profile = await asyncio.to_thread(get_profile, name)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return profile

@router.put("/profiles/{name}")
async def api_update_profile(name: str, req: ProfileUpdateRequest):
    from .profile_manager import update_profile
    data = req.model_dump(exclude_none=True)
    if "version" in data and "browser_version" not in data:
        data["browser_version"] = data.pop("version")
    
    # Parse account strings -> JSON if needed
    for act_key in ("google_account", "facebook_account", "tiktok_account", "x_account", "discord_account", "telegram_account"):
        if act_key in data and isinstance(data[act_key], str):
            raw = data[act_key].strip()
            if raw:
                # Split by pipe or tab
                parts = raw.split("|") if "|" in raw else raw.split("\t")
                parts = [p.strip() for p in parts if p.strip()]
                data[act_key] = {
                    "email": parts[0] if len(parts) > 0 else "",
                    "password": parts[1] if len(parts) > 1 else "",
                    "recoveryEmail": parts[2] if len(parts) > 2 else "",
                    "twoFactorCodes": parts[3] if len(parts) > 3 else "",
                }
            else:
                data[act_key] = None
    
    profile = await asyncio.to_thread(update_profile, name, **data)
    if not profile:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "updated", "profile": profile}

@router.delete("/profiles/{name}")
async def api_delete_profile(name: str):
    from .profile_manager import delete_profile
    success = await asyncio.to_thread(delete_profile, name)
    if not success:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "deleted"}

@router.get("/profiles/{name}/fingerprint")
async def api_get_fingerprint(name: str):
    import asyncio
    from .profile_manager import get_fingerprint
    fp = await asyncio.to_thread(get_fingerprint, name)
    if not fp:
        raise HTTPException(404, f"Fingerprint not found or failed to fetch for profile '{name}'")
    return fp

@router.post("/profiles/{name}/fingerprint/reset")
async def api_reset_fingerprint(name: str):
    from .profile_manager import reset_fingerprint
    success = await asyncio.to_thread(reset_fingerprint, name)
    if success:
        return {"status": "reset", "profile": name}
    raise HTTPException(404, f"Fingerprint not found for profile '{name}'")


@router.post("/profiles/{name}/fingerprint/refresh")
async def api_refresh_fingerprint(name: str):
    """Force-fetch a brand new fingerprint from the remote API, replacing any existing one."""
    import asyncio
    from .profile_manager import refresh_fingerprint
    try:
        # Run in thread pool — refresh_fingerprint uses blocking requests.get() with 8MB+ responses
        fp = await asyncio.to_thread(refresh_fingerprint, name)
        if fp:
            return {"status": "refreshed", "profile": name, "fingerprint_keys": list(fp.keys())[:5]}
        raise HTTPException(500, f"Failed to refresh fingerprint for profile '{name}'. API may be unavailable.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[refresh_fingerprint] Error: {e}")
        raise HTTPException(500, f"Failed to refresh fingerprint for profile '{name}': {str(e)}")


@router.get("/profiles/{name}/cookies")
async def api_get_cookies(name: str):
    """Get cookies.json content for a profile."""
    import os, json
    from .profile_manager import PROFILES_DIR
    cookie_path = os.path.join(PROFILES_DIR, name, "cookies.json")
    if not os.path.exists(cookie_path):
        return {"cookies": [], "count": 0}
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        return {"cookies": cookies, "count": len(cookies) if isinstance(cookies, list) else 0}
    except Exception as e:
        raise HTTPException(500, f"Failed to read cookies: {e}")

@router.post("/profiles/{name}/cookies")
async def api_import_cookies(name: str, request: Request):
    """Import cookies.json for a profile."""
    import os, json
    from .profile_manager import PROFILES_DIR
    profile_path = os.path.join(PROFILES_DIR, name)
    if not os.path.isdir(profile_path):
        raise HTTPException(404, f"Profile '{name}' not found")
    try:
        body = await request.json()
        cookies = body.get("cookies", body) if isinstance(body, dict) else body
        if not isinstance(cookies, list):
            cookies = [cookies]
        cookie_path = os.path.join(profile_path, "cookies.json")
        with open(cookie_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        return {"status": "imported", "count": len(cookies)}
    except Exception as e:
        raise HTTPException(500, f"Failed to import cookies: {e}")

@router.delete("/profiles/{name}/cookies")
async def api_delete_cookies(name: str):
    """Delete cookies.json for a profile."""
    import os
    from .profile_manager import PROFILES_DIR
    cookie_path = os.path.join(PROFILES_DIR, name, "cookies.json")
    if os.path.exists(cookie_path):
        os.remove(cookie_path)
        return {"status": "deleted"}
    return {"status": "not_found"}


# profile -> when its launch started. A launch that never reports back must not
# lock the profile out for the rest of the process's life: before this was
# time-bounded, one crashed attempt meant "already running or opening" on every
# later click, and only a server restart cleared it.
_launching_profiles: Dict[str, float] = {}
_launching_lock = asyncio.Lock()
LAUNCH_GUARD_SEC = 90


def _pid_alive(pid) -> bool:
    """Is this PID still around? Unknown counts as alive, so a probe failure
    never lets two launchers run against the same profile directory."""
    try:
        import psutil

        return psutil.pid_exists(int(pid))
    except ImportError:
        pass
    except Exception:
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def _is_launching(profile_name: str) -> bool:
    import time

    started = _launching_profiles.get(profile_name)
    if started is None:
        return False
    if time.time() - started > LAUNCH_GUARD_SEC:
        _launching_profiles.pop(profile_name, None)   # stale — let it retry
        return False
    return True


def is_profile_running(profile_name: str) -> bool:
    from .process_manager import browser_process_manager
    # Check normal running profiles. A recorded status of "running" is not
    # proof: if the launcher was killed the record survives, and the profile
    # would be unopenable until restart. Verify the process is really there.
    for inst in browser_process_manager.list_all():
        if inst.get("profile") == profile_name and inst.get("status") == "running":
            pid = inst.get("pid")
            if pid and not _pid_alive(pid):
                continue
            return True
            
    # Check preview running profiles
    dead_sessions = []
    is_running = False
    for session_id, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc and proc.poll() is not None:
            dead_sessions.append(session_id)
        elif info.get("profile") == profile_name:
            is_running = True
            
    for session_id in dead_sessions:
        _preview_processes.pop(session_id, None)
        
    return is_running

def shardx_pin(version: str) -> Optional[str]:
    """Số phiên bản trong một chuỗi ghim ShardX, hay None nếu không phải ghim ShardX.

    Phải tách CHÍNH XÁC như browser_manager.js:1153
    (bỏ 'ShardX', bỏ tiếp dấu '-' và khoảng trắng đầu), vì UI ghi hai dạng:
    routes.py:622 phát ra "ShardX <ver>" (dấu cách) cho browser_version và
    "ShardX-<ver>" (gạch nối) cho bas_version. Lệch một ký tự là preflight đi tìm
    thư mục engine khác với thư mục launcher thật sự mở.
    """
    v = str(version or "")
    if "ShardX" not in v:
        return None
    return v.replace("ShardX", "", 1).lstrip().lstrip("-").strip()


# Mỗi mã là MỘT câu người dùng làm được việc với nó. Thứ tự ở check_launch_blockers
# đi từ "không đời nào chạy được" xuống "thiếu giấy phép".
LAUNCH_BLOCKER_MESSAGES = {
    "ENGINE_WINDOWS_ONLY": (
        "This profile is pinned to a BAS (Security Browser) engine, and BAS ships "
        "Windows binaries only — it cannot run on this system at all. There is no "
        "ShardX engine installed here to run it on instead, so nothing can open "
        "this profile yet. Download a ShardX engine from the Browser page (Engine "
        "versions) — ShardX has a native build for this platform and needs no key "
        "— and this profile will run on it."
    ),
    "SHARDX_ENGINE_MISSING": (
        "This profile is pinned to a ShardX engine that is not downloaded on this "
        "machine. Install it from the Browser page (Engine versions), then launch "
        "again."
    ),
    "BAS_KEY_REQUIRED": (
        "This profile uses a BAS engine, which needs a BAS Fingerprint "
        "API key. Enter one in Settings, or create the profile with a "
        "ShardX engine instead — ShardX is free and needs no key."
    ),
    "BAS_KEY_EXPIRED": (
        "This profile's BAS engine has a fingerprint key that was REJECTED the "
        "last time a browser actually tried to open (expired or invalid). Enter a "
        "valid BAS key in Settings, or repin this profile to a ShardX engine — "
        "ShardX needs no key. A single successful BAS launch clears this by itself."
    ),
    "PROXY_SOCKS5_AUTH_UNSUPPORTED": (
        "This profile uses a SOCKS5 proxy with a username and password, and the "
        "ShardX engine cannot authenticate to one: Chromium has no SOCKS5 login "
        "support, so the credentials are dropped and every page fails with "
        "ERR_PROXY_CONNECTION_FAILED. Use an HTTP/HTTPS proxy from the same "
        "provider (same credentials usually work), or point this profile at an "
        "unauthenticated SOCKS5 endpoint."
    ),
    "PROXY_FORMAT_UNSUPPORTED": (
        "This profile's proxy is not in a form any engine can read. Use "
        "scheme://user:password@host:port (or scheme://host:port with no login) "
        "and one of http, https, socks5, socks4. The provider style "
        "scheme://host:port:user:password is NOT understood — rewrite it with the "
        "'@' form. Left as is, ShardX starts and every page fails with "
        "ERR_NO_SUPPORTED_PROXIES."
    ),
}


# Dạng proxy nào thật sự tồn tại trong hồ sơ, đo trên 102 thư mục
# data/extensions_data/browser/browser_profiles: 76 có config.json, 14 có proxy —
# 9 dạng "socks5://user:pass@host:port", 3 dạng nhà cung cấp
# "socks5://host:port:user:pass" (một cái còn gõ nhầm scheme "sock5s"),
# 1 http có mật khẩu, 1 socks5 trần. Tức 12/14 là SOCKS5 CÓ MẬT KHẨU.
_PROXY_SCHEMES = ("http", "https", "socks5", "socks4")

# scheme://user:pass@host:port — dạng chuẩn, dạng duy nhất normalizeProxy() để yên
# mà vẫn đúng.
_RE_PROXY_AT = re.compile(
    r"^(?P<scheme>[a-z0-9]+)://(?P<user>[^:/@]+):(?P<password>[^:/@]*)@"
    r"(?P<host>[^:/@]+):(?P<port>\d+)/?$", re.I)
# scheme://host:port — không đăng nhập.
_RE_PROXY_BARE = re.compile(
    r"^(?P<scheme>[a-z0-9]+)://(?P<host>[^:/@]+):(?P<port>\d+)/?$", re.I)
# scheme://host:port:user:pass — dạng nhà cung cấp Việt Nam hay phát.
_RE_PROXY_COLON = re.compile(
    r"^(?P<scheme>[a-z0-9]+)://(?P<host>[^:/@]+):(?P<port>\d+):"
    r"(?P<user>[^:/@]+):(?P<password>[^:/@]+)/?$", re.I)


def parse_proxy(raw: str) -> Optional[dict]:
    r"""Đọc chuỗi proxy thành các phần, hoặc None khi không đọc nổi.

    CỐ Ý không dùng lại browser_manager.normalizeProxy(): hàm đó đọc SAI thứ tự.
    Regex của nó (browser_manager.js:1790) bắt bốn nhóm rồi gán
    [user, pass, host, port], trong khi chuỗi nhà cung cấp thật sự là
    [host, port, user, pass]. Nó không gây hại chỉ vì nhóm cuối bị ép phải là
    chữ số, nên "…:24146:sObgXjw1:rC5CCCO5mIMz" không khớp và đi qua nguyên vẹn —
    một lỗi được che bởi một lỗi khác. Sửa mỗi phần \d+ mà không đảo thứ tự sẽ
    biến host thành user và đẩy hồ sơ ra một proxy không tồn tại.
    """
    v = str(raw or "").strip()
    if not v:
        return None
    for form, rx in (("creds_at", _RE_PROXY_AT),
                     ("bare", _RE_PROXY_BARE),
                     ("colon", _RE_PROXY_COLON)):
        m = rx.match(v)
        if not m:
            continue
        g = m.groupdict()
        scheme = g["scheme"].lower()
        return {
            "form": form,
            "scheme": scheme,
            "scheme_known": scheme in _PROXY_SCHEMES,
            "host": g["host"],
            "port": int(g["port"]),
            "user": g.get("user") or "",
            "password": g.get("password") or "",
            "has_credentials": bool(g.get("user")),
        }
    return None


def proxy_blocker(version: str, raw_proxy: str) -> Optional[str]:
    """Proxy này có chạy được trên nhân đã ghim không — chỉ xét nhánh ShardX.

    Đo thật bằng chính engine đã cài (149.0.7827.103, chrome.exe --headless
    --dump-dom https://api.ipify.org):

      • socks5://host:port:user:pass  → ERR_NO_SUPPORTED_PROXIES
      • sock5s://…  (gõ nhầm scheme)  → ERR_NO_SUPPORTED_PROXIES
      • socks5://host:port  (đã rụng mật khẩu, proxy đòi đăng nhập)
                                      → ERR_PROXY_CONNECTION_FAILED
      • http://host:port    (đã rụng mật khẩu, proxy đòi đăng nhập)
                                      → ERR_PROXY_CONNECTION_FAILED
      • không proxy                   → mở được, trả IP thật

    Tin TỐT: KHÔNG có rò IP. Chromium từ chối hẳn chứ không âm thầm đi thẳng, nên
    nỗi lo "chạy trần mà tưởng có proxy" là không đúng với nhân này. Tin xấu: cả
    bốn ca hỏng đều mở trình duyệt thành công rồi mọi trang mới lỗi — nên lượt chạy
    vẫn vào sổ là "running" và báo cáo vẫn nói thành công.

    Vì sao chỉ chặn nhánh ShardX: đây là những gì ĐO ĐƯỢC. Nhánh BAS đưa nguyên
    chuỗi cho plugin native (browser-with-fingerprints không hề kiểm định dạng —
    src/plugin/utils.js:51 chỉ xem có phải string không), và BAS tự cắm proxy chứ
    không qua --proxy-server, nên nó CÓ THỂ đăng nhập SOCKS5. Không kiểm chứng
    được trên máy này vì khoá BAS đã hết hạn, và đoán bừa rồi chặn nhầm thì tệ hơn
    là để launcher tự nói.

    Vì sao http/https CÓ mật khẩu KHÔNG bị chặn ở đây: nó sửa được thật, bằng cách
    chuyển sang tuỳ chọn `proxy` của Playwright (xem bản vá gửi Builder B). Chặn
    một thứ sắp chạy được chỉ tổ phải gỡ ra ngay sau đó.
    """
    if not shardx_pin(version):
        return None
    info = parse_proxy(raw_proxy)
    if raw_proxy and not info:
        return "PROXY_FORMAT_UNSUPPORTED"
    if not info:
        return None
    if not info["scheme_known"] or info["form"] == "colon":
        return "PROXY_FORMAT_UNSUPPORTED"
    if info["has_credentials"] and info["scheme"].startswith("socks"):
        # Chromium không biết đăng nhập SOCKS5, và Playwright chặn thẳng ở
        # node_modules/playwright-core/lib/server/browserContext.js:665
        # ("Browser does not support socks5 proxy authentication"). Không có
        # đường nào qua nếu không dựng một relay cục bộ.
        return "PROXY_SOCKS5_AUTH_UNSUPPORTED"
    return None


def check_launch_blockers(profile_name: str) -> Optional[str]:
    """Why this profile cannot start, in words the user can act on.

    Ba lý do, chỉ dùng thông tin có sẵn trên đĩa (không gọi mạng — hàm này nằm
    trên đường mở trình duyệt và trên preview_preflight):

    1. ENGINE_WINDOWS_ONLY — hồ sơ ghim nhân BAS trên máy không chạy được BAS
       VÀ máy đó cũng không có engine ShardX nào để mượn. BAS là nhị phân PE;
       ngoài Windows không có cách nào chạy. Hỏi khoá vân tay ở đây là hỏi sai
       câu: có khoá cũng vẫn không chạy. Nếu CÓ ShardX đã cài thì hàm này KHÔNG
       từ chối — launcher mượn nhân ShardX và in ENGINE_SUBSTITUTED (xem chỗ gọi
       supports_bas() bên dưới).

    2. SHARDX_ENGINE_MISSING — ghim ShardX nhưng engine chưa tải. Không chặn thì
       browser_manager.js:1200 ném lỗi BÊN TRONG try mà catch duy nhất (:1310)
       chỉ console.warn, nên shardxExePath vẫn null, guard :1321 trượt, và hồ sơ
       tụt âm thầm sang nhánh BAS — người dùng nhận "BAS engine, Windows only"
       trong khi sự thật là "engine ShardX chưa tải".

    3. BAS_KEY_REQUIRED — hồ sơ BAS trên Windows, không vân tay cục bộ, không
       khoá. Cuộc gọi API vân tay trả "Query limit reached" và launcher chết sau
       chừng mười giây, màn hình trống, lý do chỉ nằm trong log.

    Ngoại lệ has_local_fp ở nhánh 3 CỐ Ý giữ nguyên: _get_bas_key() chỉ đọc
    data/global_settings.json, còn browser_manager.fetchServiceKey() (:531) khi
    file đó trống thì còn hỏi khoá dùng chung ở api.tubecreate.com. Python không
    thấy khoá đó, nên siết nhánh này sẽ chặn nhầm những máy đang chạy được bằng
    khoá chung. Khoá chung HẾT HẠN chỉ lộ ra lúc launch, và đó là chuyện của
    run_log/log_tail, không phải của preflight.
    """
    from .profile_manager import PROFILES_DIR, get_profile
    from . import shardx_runtime as sx

    config = get_profile(profile_name) or {}
    version = str(config.get("browser_version") or "")

    shardx_ver = shardx_pin(version)
    if shardx_ver:
        try:
            if not sx.is_installed(shardx_ver):
                return "SHARDX_ENGINE_MISSING"
        except Exception:
            pass          # không chắc thì cho qua; launcher sẽ nói lý do thật
        # Engine có rồi thì tới lượt proxy: ShardX mở được với proxy hỏng, và
        # mở được là đủ để lượt chạy vào sổ "running" dù không trang nào tải nổi.
        return proxy_blocker(version, config.get("proxy") or "")

    # Không có "ShardX" trong chuỗi = ghim BAS, kể cả "" / "default" / số trần.
    #
    # Host không chạy được BAS thì CHƯA chắc là từ chối. browser_manager.js có sẵn
    # nhánh mượn nhân: ghim BAS mà họ BAS không dùng được ở đây, nhưng máy CÓ engine
    # ShardX, thì nó mở bằng ShardX và in ENGINE_SUBSTITUTED. Preflight chạy TRƯỚC,
    # nên nếu ở đây cứ chặn thẳng thì nhánh kia thành mã chết và 63 hồ sơ ghim BAS
    # cũ trên một VPS Linux có ShardX bị từ chối dù mở được. Hai tầng phải nói cùng
    # một câu: chỉ từ chối khi KHÔNG có nhân nào mở nổi hồ sơ này.
    try:
        host_runs_bas = sx.supports_bas()
    except Exception:
        host_runs_bas = True      # không chắc thì cho qua; launcher sẽ nói lý do thật
    if not host_runs_bas:
        try:
            borrowed = (sx.installed_versions() or [None])[0]
        except Exception:
            borrowed = None
        if not borrowed:
            return "ENGINE_WINDOWS_ONLY"
        # Sẽ chạy bằng ShardX, nên phải xét proxy theo luật của ShardX — đúng nhân
        # mà nó thật sự dùng, không phải nhân được ghim trên giấy.
        return proxy_blocker(sx.shardx_pin(borrowed), config.get("proxy") or "")

    profile_dir = os.path.join(PROFILES_DIR, profile_name)
    has_local_fp = any(
        os.path.isfile(os.path.join(profile_dir, n))
        for n in ("fingerprint_saved.json", "fingerprint.json", "shardx_fingerprint.json")
    )
    # Bằng chứng thắng suy đoán. Ngoại lệ has_local_fp bên dưới vẫn giữ (lý do ở
    # docstring: _get_bas_key() mù với khoá dùng chung), nhưng nó KHÔNG được phép
    # thắng một lượt mở thật đã chết vì khoá. Đo trên máy này: cả ba hồ sơ chạy
    # theo lịch hôm nay (truyenhangdoc, chanquasdi, basmoi) đều CÓ
    # fingerprint_saved.json, đều lọt preflight nhờ đúng ngoại lệ đó, và đều chết
    # 23/23 lượt vì khoá BAS. Vân tay cục bộ tránh được cuộc gọi LẤY vân tay mới,
    # nhưng engine vẫn kiểm khoá lúc mở — nên "có vân tay" chưa bao giờ là lý do
    # để tin rằng khoá còn sống.
    #
    # Chỉ chặn khi verdict == "bad", tức một lượt mở THẬT đã hỏng vì khoá trong
    # BAS_KEY_BAD_TTL gần đây, và đúng key_id đang dùng. Không suy ra từ việc
    # "không thấy khoá trong global_settings.json" — đó mới là phép siết đã bị
    # cảnh báo, vì browser_manager.fetchServiceKey() (:740) còn tải khoá dùng
    # chung ở api.tubecreate.com mà Python không nhìn thấy.
    try:
        if (sx.bas_key_state() or {}).get("verdict") == "bad":
            return "BAS_KEY_EXPIRED"
    except Exception:
        pass

    if has_local_fp or _get_bas_key():
        return None
    return "BAS_KEY_REQUIRED"


# Câu chữ engine BAS ném ra khi khoá vân tay không dùng được. Lấy từ chính các
# nhánh browser_manager.js:1597 đang bắt, cộng ca "key is missing" mà chưa test nào
# phủ.
_BAS_KEY_ERROR_MARKERS = (
    "key expired",
    "invalid key",
    "fingerprintswitcher key is missing",
    "query limit reached",
)


def note_launch_output(text: str) -> Optional[str]:
    """Đọc log một lượt mở và ghi lại phán quyết về khoá BAS nếu thấy.

    shardx_runtime.mark_bas_key_bad() là thứ DUY NHẤT biến bas_key_state() từ
    "unknown" thành "bad", và cho tới giờ KHÔNG AI gọi nó — nên kiểm kê mãi mãi nói
    "chưa biết" dù máy này đã hỏng 23/23 lượt. Đây là một chỗ gọi, không phải chỗ
    tốt nhất: /log/{profile} chỉ chạy khi có người mở log. Chỗ đúng là monitor nền
    trong process_manager.py, nơi luôn thấy tiến trình chết và đọc được log — nằm
    ngoài phạm vi lần sửa này (xem tóm tắt).

    Trả về mã đã ghi, hay None khi log không nói gì về khoá.
    """
    low = str(text or "").lower()
    if not low:
        return None
    try:
        from . import shardx_runtime as sx
        if any(m in low for m in _BAS_KEY_ERROR_MARKERS):
            # Cắt lấy đúng dòng chứa lỗi để reason đọc được, thay vì 5KB log.
            reason = next((ln.strip() for ln in str(text).splitlines()
                           if any(m in ln.lower() for m in _BAS_KEY_ERROR_MARKERS)), "")
            sx.mark_bas_key_bad(reason)
            return "bad"
    except Exception:
        pass
    return None


def launch_refusal(profile_name: str) -> Optional[dict]:
    """Cùng một lời từ chối cho MỌI đường mở: /launch, live view, và lịch chạy.

    Trước đây chỉ /launch biết diễn giải mã chặn, nên lượt theo lịch cứ spawn rồi
    ghi "running" cho một tiến trình chết sau một giây.
    """
    code = check_launch_blockers(profile_name)
    if not code:
        return None
    return {
        "code": code,
        "profile": str(profile_name),
        "message": LAUNCH_BLOCKER_MESSAGES.get(
            code, f"This profile cannot launch on this system ({code})."),
    }


@router.post("/launch")
async def api_launch_browser(req: LaunchRequest):
    refusal = launch_refusal(req.profile)
    if refusal:
        raise HTTPException(400, refusal)

    async with _launching_lock:
        if _is_launching(req.profile) or is_profile_running(req.profile):
            raise HTTPException(400, f"Profile '{req.profile}' is already running or opening.")
        import time as _time

        _launching_profiles[req.profile] = _time.time()
        
    try:
        from .process_manager import browser_process_manager
        result = browser_process_manager.spawn(
            profile=req.profile, prompt=req.prompt, url=req.url, headless=req.headless, manual=req.manual, ai_model=req.ai_model, context=req.context
        )
        return result
    finally:
        async with _launching_lock:
            _launching_profiles.pop(req.profile, None)

@router.post("/stop")
async def api_stop_browser(req: StopRequest):
    from .process_manager import browser_process_manager, force_kill_profile
    stopped = False
    
    # 1. Stop normal browser process
    if browser_process_manager.stop_by_profile(req.profile):
        stopped = True
        
    # 2. Stop preview browser process
    dead_sessions = []
    for session_id, info in list(_preview_processes.items()):
        if info.get("profile") == req.profile:
            proc = info.get("proc")
            if proc:
                try:
                    import platform
                    import subprocess
                    if platform.system() == "Windows":
                        subprocess.run(
                            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                            capture_output=True, timeout=5
                        )
                    else:
                        proc.terminate()
                except Exception:
                    pass
            _preview_processes.pop(session_id, None)
            stopped = True
            
    # Dọn phần hệ điều hành còn giữ: chrome mồ côi từ phiên trước, node preview
    # server không còn trong dict, và khoá Singleton chrome để lại khi bị giết cứng.
    report = {}
    if req.force:
        report = await asyncio.to_thread(force_kill_profile, req.profile)
        if report.get("killed") or report.get("locks_removed"):
            stopped = True

    # "Không có gì để dừng" là kết quả hợp lệ của lệnh dọn, không phải lỗi 404 —
    # trước đây client phải nuốt lỗi rồi mở tiếp vào một profile vẫn đang bị khoá.
    return {
        "status": "stopped" if stopped else "idle",
        "profile": req.profile,
        "killed": report.get("killed", []),
        "locks_removed": report.get("locks_removed", []),
        "errors": report.get("errors", []),
    }

@router.get("/status")
async def api_browser_status():
    from .process_manager import browser_process_manager
    instances = browser_process_manager.list_all()
    
    # Add preview processes to the instances list so the frontend knows they are running
    dead_sessions = []
    for session_id, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc and proc.poll() is not None:
            dead_sessions.append(session_id)
        else:
            exists = False
            for inst in instances:
                if inst.get("profile") == info.get("profile") and inst.get("status") == "running":
                    exists = True
                    break
            if not exists:
                instances.append({
                    "instance_id": session_id,
                    "profile": info.get("profile"),
                    "status": "running",
                    "manual": True,
                    "is_preview": True,
                    # Cổng của phiên preview: khung Browser trên canvas cần nó để TỰ
                    # nối vào phiên do agent mở. Không có, khung đứng im ở nút "Mở
                    # live view" trong khi browser đã chạy — người dùng thấy agent
                    # bảo "đã mở" mà màn hình trống.
                    "port": info.get("port")
                })
                
    for session_id in dead_sessions:
        _preview_processes.pop(session_id, None)
        
    return {"instances": instances}

@router.get("/log/{profile}")
async def api_browser_log(profile: str):
    """Read latest log file for a browser profile instance."""
    from .process_manager import browser_process_manager
    # Find latest instance for this profile
    all_instances = browser_process_manager.list_all()
    instance = None
    for inst in reversed(all_instances):
        if inst.get("profile") == profile:
            instance = inst
            break
    
    if not instance:
        return {"error": "No instance found for this profile", "log": ""}
    
    log_file = instance.get("log_file", "")
    log_content = ""
    if log_file and os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_content = f.read(5000)  # Last 5KB
        except Exception as e:
            log_content = f"Error reading log: {e}"
    else:
        log_content = f"Log file not found: {log_file}"
    
    # Log đã đọc rồi thì đọc nốt xem nó có nói khoá BAS hỏng không — rẻ, và là
    # cách duy nhất hiện có để kiểm kê biết khoá đã chết.
    #
    # CHỈ đọc log còn MỚI. Route này chạy mỗi lần có người bấm xem log, và nó lấy
    # instance gần nhất của hồ sơ — không chặn thì một file log từ tuần trước cứ
    # mỗi lần mở lại đóng dấu "khoá hỏng" một lần nữa, gia hạn lệnh chặn vô hạn
    # dù khoá đã được thay. Quá BAS_KEY_BAD_TTL thì log đó hết là bằng chứng.
    try:
        import time as _t
        from . import shardx_runtime as _sx
        if log_file and os.path.exists(log_file):
            if (_t.time() - os.path.getmtime(log_file)) < _sx.BAS_KEY_BAD_TTL:
                note_launch_output(log_content)
    except Exception:
        pass

    return {
        "instance_id": instance.get("instance_id"),
        "status": instance.get("status"),
        "command": instance.get("command"),
        "log_file": log_file,
        "log": log_content,
        "debug": instance.get("debug", {}),
    }

def _get_bas_key() -> str:
    """The BAS fingerprint licence key, or "" when the user has none.

    ShardX needs nothing; BAS fetches its fingerprints from an API that meters
    by key, so a BAS profile without one cannot launch at all.
    """
    import json as _json

    try:
        from tubecli.config import DATA_DIR

        path = os.path.join(str(DATA_DIR), "global_settings.json")
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            settings = _json.load(f)
        key = (settings.get("bas_fingerprint_key")
               or (settings.get("browser_service_keys") or {}).get("bas") or "")
        return str(key).strip()
    except Exception:
        return ""


@router.get("/engine/versions")
async def api_get_engine_versions():
    def _fetch():
        import json
        import os
        
        try:
            ext_dir = os.path.dirname(__file__)
            versions = []
            api_error = None
            
            # 1. Fetch versions from private API server (fast, no HEAD requests)
            private_api_url = "https://api.tubecreate.com/api/fingerprints/check_versions.php"
            try:
                import requests
                from tubecli.config import get_language
                lang = get_language()
                resp = requests.post(private_api_url, json={"lang": lang}, timeout=15)
                if resp.status_code == 200:
                    private_data = resp.json()
                    if private_data.get("success"):
                        for pv in private_data.get("versions", []):
                            pv_name = pv.get("browser_version")
                            if not pv_name or pv_name == "Unknown":
                                pv_name = pv.get("bas_version")
                            if not pv_name:
                                pv_name = "Unknown"
                                
                            display_name = pv_name
                            if not display_name.startswith("ShardX") and not display_name.startswith("BAS"):
                                display_name = f"BAS {display_name}"
                            versions.append({
                                "name": display_name,
                                "browser_version": pv.get("browser_version", pv_name),
                                "bas_version": pv.get("bas_version", ""),
                                "downloaded": False,
                                "download_url": pv.get("download_url"),
                                "local_url": pv.get("local_url"),
                                "bablosoft_url": pv.get("bablosoft_url"),
                                "is_private": True,
                                "path": "-"
                            })
                    else:
                        api_error = private_data.get("message", "API returned success=false")
                else:
                    api_error = f"API returned status {resp.status_code}"
            except ImportError:
                api_error = "Python 'requests' module not installed. Run: pip install requests"
                print(f"[PrivateAPI] {api_error}")
            except Exception as e:
                api_error = f"API connection error: {str(e)}"
                print(f"[PrivateAPI] Error: {e}")

            # 2. Add local fallback versions if they are not in the list
            fallback_versions = [
                {"bas_version": "30.2.0", "browser_version": "149.0.7827.54",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/30.2.0/FastExecuteScript.x64.zip"},
                {"bas_version": "30.1.0", "browser_version": "148.0.7778.97",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/30.1.0/FastExecuteScript.x64.zip"},
                {"bas_version": "30.0.0", "browser_version": "147.0.7727.56",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/30.0.0/FastExecuteScript.x64.zip"},
                {"bas_version": "29.9.2", "browser_version": "146.0.7680.80",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.9.2/FastExecuteScript.x64.zip"},
                {"bas_version": "29.8.1", "browser_version": "145.0.7632.46",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.8.1/FastExecuteScript.x64.zip"},
                {"bas_version": "29.7.0", "browser_version": "144.0.7559.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.7.0/FastExecuteScript.x64.zip"},
                {"bas_version": "29.5.0", "browser_version": "142.0.7444.60",
                 "download_url": "http://downloads.bablosoft.com/distr/FastExecuteScript64/29.5.0/FastExecuteScript.x64.zip"},
            ]
            
            # BAS ships Windows PE binaries only. Listing it on Linux or macOS
            # offered a download that could never run — and the failure was silent,
            # because nothing downstream checked the platform either.
            from . import shardx_runtime as sx
            if not sx.supports_bas():
                versions = [v for v in versions
                            if str(v.get("name", "")).startswith("ShardX")]
                fallback_versions = []

            existing_bas_versions = set(v.get("bas_version") for v in versions)
            for fv in fallback_versions:
                if fv["bas_version"] not in existing_bas_versions:
                    display_name = fv["browser_version"]
                    if not display_name.startswith("ShardX") and not display_name.startswith("BAS"):
                        display_name = f"BAS {display_name}"
                    versions.append({
                        "name": display_name,
                        "browser_version": fv["browser_version"],
                        "bas_version": fv["bas_version"],
                        "downloaded": False,
                        "download_url": fv["download_url"],
                        "is_private": False,
                        "is_fallback": True,
                        "path": "-"
                    })

            # 2b. ShardX versions this host can actually download. The list used to
            # be hardcoded, so Linux was offered 148.0.7778.97 and 148.0.7778.216 —
            # verified to answer 404, because only the Windows archives for those
            # versions were ever uploaded. Offering an Install button for a
            # guaranteed failure is worse than not listing it.
            shardx_versions = [
                {"bas_version": f"ShardX-{v}", "browser_version": f"ShardX {v}", "download_url": ""}
                for v in sx.available_versions()
            ]
            for sv in shardx_versions:
                versions.append({
                    "name": sv["browser_version"],
                    "browser_version": sv["browser_version"],
                    "bas_version": sv["bas_version"],
                    "downloaded": False,
                    "download_url": sv["download_url"],
                    "is_private": False,
                    "is_fallback": True,
                    "is_shardx": True,
                    "path": "-"
                })

            # 3. Check local install status — data/script/{bas_version}/
            # plugin.setWorkingFolder(__dirname) in open.js makes plugin look here
            _sx_latest = sx.current_version()
            for v in versions:
                bas_ver = v.get("bas_version", "")
                if not bas_ver:
                    continue
                
                if v.get("is_shardx"):
                    # Resolved per OS now. This used to read %APPDATA% and look for
                    # chrome.exe, so on Linux and macOS an installed engine was
                    # always reported as missing.
                    version_num = bas_ver.replace("ShardX-", "")
                    chrome = sx.binary_path(version_num)
                    installed = bool(chrome and chrome.exists())
                    v["downloaded"] = installed
                    v["path"] = str(chrome.parent) if installed else "-"
                    # Bản ShardX đang phát hành: UI cần phân biệt "mới nhất" với
                    # "bản cũ còn giữ lại", nếu không người dùng không biết nên cài cái nào.
                    v["is_current"] = (version_num == _sx_latest)
                    v["chromium_version"] = version_num
                    # KHÔNG gắn chữ "mới nhất" vào name: name đi thẳng ra UI, mà UI có
                    # 9 ngôn ngữ — chữ cứng tiếng Việt sẽ chen vào giao diện tiếng Anh.
                    # Badge LATEST (dịch theo ngôn ngữ) đã nói đủ.
                else:
                    script_dir = os.path.join(ext_dir, "data", "script", bas_ver)
                    is_installed = os.path.isdir(script_dir) and os.path.isfile(
                        os.path.join(script_dir, "FastExecuteScript.exe")
                    )
                    
                    v["downloaded"] = is_installed
                    v["path"] = script_dir if is_installed else "-"
            
            # ShardX is the free engine; BAS pulls its fingerprints from an
            # API that needs a licence key, and without one a profile dies at
            # launch with nothing but a line in a log file. Say so up front.
            for v in versions:
                v["requires_key"] = not bool(v.get("is_shardx"))

            # Sort: newest first
            versions.sort(key=lambda x: x.get("bas_version", ""), reverse=True)

            spec = sx.host_spec()
            result = {
                "success": True,
                "versions": versions,
                "bas_key_configured": bool(_get_bas_key()),
                # Platform facts the UI needs in order to explain itself. Without
                # these it had no way to say why a list was empty or why a download
                # would not run, so it said nothing at all.
                "platform": {
                    "os": sys.platform,
                    "arch": platform.machine(),
                    "engine": spec.plat,
                    "supported": spec.supported,
                    "bas_available": sx.supports_bas(),
                },
                # Phiên bản nhân ShardX đang phát hành + đã cài, để UI nói được
                # "có bản mới" thay vì bắt người dùng tự đối chiếu số.
                "engine_update": sx.check_update(),
            }
            if not spec.supported:
                result["platform_error"] = spec.reason
            elif not sx.supports_bas():
                result["platform_note"] = (
                    "BAS engines are Windows-only, so only ShardX is listed here."
                )
            missing_libs = sx.missing_linux_libraries()
            if missing_libs:
                result["missing_libraries"] = missing_libs
                result["missing_libraries_hint"] = (
                    f"ShardX needs shared libraries this system does not have "
                    f"({', '.join(missing_libs[:4])}"
                    f"{'...' if len(missing_libs) > 4 else ''}). "
                    f"On Debian/Ubuntu: sudo apt install -y {sx.LINUX_APT_PACKAGES}"
                )
            if api_error and not any(v.get("is_private") for v in versions):
                result["warning"] = api_error
            return result
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "status": "error", "message": str(e), "error": str(e)}

    return await asyncio.to_thread(_fetch)

@router.get("/engine/check-update")
async def api_engine_check_update(force: bool = True):
    """Phiên bản nhân ShardX mới nhất so với bản đã cài.

    force=true bỏ qua cache 30 phút — dùng khi người dùng bấm "Kiểm tra bản mới" và
    muốn biết ngay, thay vì chờ cache hết hạn.
    """
    from . import shardx_runtime as sx

    def _check():
        if force:
            sx.fetch_manifest(force=True)
        info = sx.check_update()
        info["success"] = True
        if info["update_available"]:
            info["message"] = (f"Có nhân mới {info['latest']} "
                               f"(đang cài {info['newest_installed']}).")
        elif not info["installed"]:
            info["message"] = f"Chưa cài nhân nào. Bản mới nhất: {info['latest']}."
        else:
            info["message"] = f"Đang dùng nhân mới nhất ({info['latest']})."
        if not info["manifest_ok"]:
            info["message"] += " (Không đọc được manifest ShardX — đang dùng bản dự phòng.)"
        return info

    return await asyncio.to_thread(_check)


@router.get("/engine/inventory")
async def api_engine_inventory():
    """Nhân nào CÓ trên máy, nhân nào DÙNG ĐƯỢC, và profile mới sẽ ghim vào đâu.

    Chỉ đọc, không chạm mạng, không sửa gì. Có route này để bảng điều khiển nói
    được đúng một câu mà trước đây không ai nói: "BAS đã cài nhưng khoá hết hạn —
    đang dùng ShardX". Trước đó UI chỉ có danh sách phiên bản, nên một nhân đã cài
    mà không mở nổi trông y hệt một nhân lành, và người dùng cứ tạo tiếp profile
    ghim vào nó.

    Dùng lại nguyên shardx_runtime.engine_inventory() chứ không tự tính lại: điểm
    của cả đợt sửa này là chỉ có MỘT chỗ định nghĩa "dùng được". summary chỉ là
    cùng câu trả lời đó viết bằng tiếng Anh cho UI in thẳng.
    """
    from . import shardx_runtime as sx

    def _read():
        inv = sx.engine_inventory()
        engines = inv.get("engines") or []
        usable = [e for e in engines if e.get("usable")]
        bas_all = [e for e in engines if e.get("family") == "bas"]
        bas_usable = [e for e in bas_all if e.get("usable")]

        # why_not của shardx_runtime viết bằng tiếng Việt; summary này là chuỗi
        # tiếng Anh UI in thẳng, nên dựng lại lý do từ các trường có cấu trúc thay
        # vì nhét why_not vào giữa một câu tiếng Anh. Lý do gốc vẫn còn nguyên
        # trong từng mục engines[] cho ai muốn đọc.
        bas_info = inv.get("bas") or {}
        key_info = bas_info.get("key") or {}
        if not bas_info.get("host_supported"):
            bas_reason = "BAS ships Windows binaries only and cannot run on this system"
        elif key_info.get("verdict") == "bad":
            bas_reason = "its fingerprint key was rejected at the last launch (expired or invalid)"
        elif not key_info.get("available"):
            bas_reason = ("no BAS fingerprint key has proven to work here (none is "
                          "configured locally, and the shared key has never opened a "
                          "browser on this machine)")
        else:
            bas_reason = "no usable BAS engine"

        if not engines:
            summary = ("No browser engine is installed on this machine. Download a "
                       "ShardX engine from the Browser page — it is free and needs no key.")
        elif not usable:
            summary = (f"Engines are installed but none can launch right now: {bas_reason}. "
                       f"New profiles will be pinned to {inv.get('default_pin')}, which you "
                       f"can install from the Browser page.")
        elif bas_all and not bas_usable:
            # Chính là ca trên máy này: BAS có 6 bản, không bản nào mở được.
            summary = (f"BAS is installed ({len(bas_all)} version(s)) but not usable — "
                       f"{bas_reason}. ShardX is being used instead; new profiles pin to "
                       f"{inv.get('default_pin')}.")
        else:
            summary = (f"{len(usable)} of {len(engines)} installed engine(s) are usable. "
                       f"New profiles pin to {inv.get('default_pin')}.")

        inv["summary"] = summary
        inv["success"] = True
        return inv

    # engine_inventory() chạm đĩa (quét thư mục engine, đọc engine_state) nên đẩy
    # sang thread — event loop của FastAPI không nên chờ I/O đồng bộ.
    return await asyncio.to_thread(_read)


@router.post("/engine/download/{version}")
async def api_download_engine(version: str, request: Request):
    # Bound for the whole endpoint: both the ShardX and the BAS branch need it,
    # and importing it inside the ShardX branch alone left the BAS branch with an
    # unbound name.
    from . import shardx_runtime as sx

    ext_dir = os.path.dirname(__file__)
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    # Check if already downloading this version
    if version in download_processes:
        return {"status": "already_downloading", "version": version}
    
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    os.makedirs(os.path.dirname(progress_file), exist_ok=True)
    
    def write_progress(status, percent=0, message=""):
        import json as _json
        data = {"version": version, "status": status, "percent": percent}
        if message:
            # Informational text goes in `message`; `error` is set only when the
            # status really is an error. Everything used to land in `error`, and
            # the UI's poll loop skips any response carrying that field — so the
            # moment the backend reported "Extracting...", the progress bar stopped
            # updating and stopped noticing completion. A long extraction then
            # looked exactly like a frozen download.
            data["message"] = message
            if status == "error":
                data["error"] = message
        try:
            tmp_progress = progress_file + ".tmp"
            with open(tmp_progress, "w") as f:
                _json.dump(data, f, indent=2)
            os.replace(tmp_progress, progress_file)
        except:
            pass
    
    # Write initial progress immediately to prevent startup flicker
    write_progress("downloading", 0, "Initializing download...")
    
    if version.startswith("ShardX-"):
        version_num = version.replace("ShardX-", "").replace("ShardX ", "").strip()
        spec = sx.host_spec()

        # Refuse loudly rather than downloading something that cannot run. This
        # path used to build a Windows URL and an %APPDATA% directory regardless
        # of the OS, which is why a Linux user saw nothing happen at all.
        # preflight also catches a missing `unzip` now — better to say so before
        # the 200 MB transfer than after it.
        blocker = sx.preflight()
        if blocker:
            write_progress("error", 0, blocker)
            return {"success": False, "message": blocker}

        target_dir = sx.engine_dir(version_num)
        os.makedirs(target_dir, exist_ok=True)

        def download_and_extract_shardx():
            import requests

            # Manifest và bucket không đổi cùng lúc, nên thử lần lượt: bản mới nhất
            # nằm ở CDN dưới tên không số, bản cũ nằm sau worker theo số phiên bản.
            candidates = sx.download_candidates(version_num) or [sx.archive_url(version_num)]
            url = candidates[0]
            try:
                write_progress(
                    "downloading", 3,
                    f"Connecting to {'Cloudflare R2 worker' if 'cf-r2' in url else 'ProxyShard CDN'} "
                    f"for {spec.plat}...",
                )

                write_progress("downloading", 5, f"Downloading ShardX engine ({spec.plat})...")

                engine_tmp = os.path.join(ext_dir, "data", "engine")
                os.makedirs(engine_tmp, exist_ok=True)
                tmp_zip = os.path.join(engine_tmp, f"{version}.zip")

                def on_progress(received, total, speed):
                    # Cancelling is a flag, not a signal to a process — raising here
                    # is what actually stops the transfer.
                    if version in download_cancelled:
                        raise RuntimeError("cancelled by user")
                    # received < 0 is the retry signal from the downloader.
                    if received < 0:
                        write_progress("downloading", 5, "Connection dropped — retrying...")
                        return
                    if total <= 0:
                        return
                    pct = min(int((received / total) * 80) + 5, 85)
                    # Show the actual megabytes and speed. A bare percentage that
                    # stops moving is indistinguishable from a frozen program, which
                    # is exactly how a slow 200 MB transfer read to users.
                    write_progress(
                        "downloading", pct,
                        f"{received / 1048576:.0f} / {total / 1048576:.0f} MB "
                        f"({speed / 1048576:.1f} MB/s)",
                    )

                # Resumes across dropped connections instead of restarting the
                # whole 200 MB transfer, and fails fast on a dead socket rather
                # than blocking for the full timeout on every chunk.
                last_err = None
                for i, cand in enumerate(candidates):
                    if version in download_cancelled:
                        raise RuntimeError("cancelled by user")
                    try:
                        if i:
                            # Đường đầu hỏng (404 vì manifest lệch bucket, CDN chặn…)
                            # → nói rõ đang đổi nguồn thay vì báo lỗi rồi dừng.
                            write_progress("downloading", 5,
                                           f"Nguồn {i} không tải được, thử nguồn dự phòng...")
                            try:
                                os.remove(tmp_zip)
                            except OSError:
                                pass
                        sx.download(cand, Path(tmp_zip), on_progress=on_progress)
                        url = cand
                        last_err = None
                        break
                    except RuntimeError:
                        raise                      # người dùng bấm huỷ
                    except Exception as e:
                        last_err = e
                if last_err is not None:
                    raise last_err

                write_progress("extracting", 90, "Extracting ShardX engine...")
                try:
                    # Goes through shardx_runtime: on POSIX it uses the system
                    # unzip and then restores exec bits, because zipfile drops
                    # symlinks and permissions and the engine will not launch.
                    sx.extract(Path(tmp_zip), Path(target_dir))
                except Exception as e:
                    try:
                        os.remove(tmp_zip)
                    except OSError:
                        pass
                    write_progress("error", 0, str(e)[:300])
                    return

                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass

                # Confirm the thing we just installed is actually runnable, rather
                # than reporting success because the extract did not raise.
                chrome = sx.binary_path(version_num)
                if not (chrome and chrome.exists()):
                    write_progress(
                        "error", 0,
                        f"Extracted, but no ShardX executable was found at "
                        f"{chrome}. The archive layout may have changed.",
                    )
                    return

                # The fingerprint library ships separately from the engine and was
                # never fetched. Without it the launcher finds no fingerprint file,
                # skips --fingerprint-profile entirely, and the profile runs with
                # the engine's real fingerprint — the one thing a profile exists to
                # prevent.
                if not sx.fingerprints_installed():
                    write_progress("extracting", 93, "Installing ShardX fingerprint library...")
                    if not sx.install_fingerprints():
                        write_progress("extracting", 94,
                                       "Warning: fingerprint library could not be installed; "
                                       "profiles would use the engine's own fingerprint.")

                missing = sx.missing_linux_libraries()
                if missing:
                    # Chromium will not start without these, so install them the
                    # same way as unzip rather than ending on a green "completed"
                    # for an engine that cannot run.
                    write_progress("extracting", 95,
                                   f"Installing {len(missing)} required system libraries...")
                    # Per-package, not one apt call for the whole list:
                    # on Ubuntu 24.04 the single unresolvable name
                    # libasound2 aborted the transaction and took the
                    # other thirteen libraries down with it.
                    sx.install_chromium_libs()
                    missing = sx.missing_linux_libraries()
                if missing:
                    write_progress(
                        "completed", 100,
                        f"Installed, but {len(missing)} system libraries are still "
                        f"missing so the engine will not start yet. Run: "
                        f"{sx.manual_install_hint(sx.LINUX_APT_PACKAGES.split())}",
                    )
                    return

                write_progress("completed", 100)
                return

            except Exception as e:
                write_progress("error", 0, f"Download failed: {str(e)[:300]}")
                return
        
        def run_bg_shardx():
            # Clear any stale cancel from a previous attempt, or this download would
            # abort immediately on its first progress callback.
            download_cancelled.discard(version)
            download_processes[version] = True
            try:
                download_and_extract_shardx()
            finally:
                download_processes.pop(version, None)
                download_cancelled.discard(version)
        
        threading.Thread(target=run_bg_shardx, daemon=True).start()
        return {"status": "started", "version": version}

    download_url = body.get("download_url", "")
    bas_version = body.get("bas_version") or version

    # BAS ships Windows PE binaries. The engine list no longer offers it elsewhere,
    # but this endpoint is reachable directly, and downloading 150 MB of Windows
    # executables onto a Linux box only to have nothing happen is exactly the
    # silent failure this whole change exists to remove.
    if not sx.supports_bas():
        msg = (f"BAS engines only run on Windows; this machine is {sys.platform}. "
               f"Use a ShardX engine instead — it has a native build for this platform.")
        write_progress("error", 0, msg)
        return {"success": False, "message": msg}

    # If no download_url provided, construct Security Browser URL
    if not download_url:
        download_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    # Extract to data/script/ — plugin.setWorkingFolder(__dirname) in open.js
    # makes the plugin look here for engines
    target_dir = os.path.join(ext_dir, "data", "script", bas_version)
    
    # Ensure directories exist
    # CRITICAL: We MUST create the data/engine/{bas_version} directory
    # The plugin checks for its existence to skip downloading
    engine_dir = os.path.join(ext_dir, "data", "engine", bas_version)
    os.makedirs(engine_dir, exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)
    
    # Build fallback Security Browser URL
    fallback_url = f"http://downloads.bablosoft.com/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
    
    def download_and_extract():
        import zipfile
        import requests
        
        # Try local_url first, then Cloudflare R2 proxy, then fallback to Bablosoft
        urls_to_try = []
        if download_url and download_url != fallback_url:
            urls_to_try.append(("local", download_url))
            
        # Cloudflare R2 proxy worker domain (uses user's workers.dev subdomain)
        cf_subdomain = "tubecli"
        cf_proxy_url = f"https://cf-r2-worker.{cf_subdomain}.workers.dev/distr/FastExecuteScript64/{bas_version}/FastExecuteScript.x64.zip"
        urls_to_try.append(("cloudflare_r2", cf_proxy_url))
        
        urls_to_try.append(("security_browser", fallback_url))
        
        for url_label, url in urls_to_try:
            try:
                write_progress("downloading", 3, f"Trying {url_label} server...")
                
                # verify defaults to True. It was disabled here, on a download whose
                # contents are then executed — anyone able to intercept the
                # connection could have swapped the engine for their own binary.
                resp = requests.get(url, stream=True, timeout=300)
                if resp.status_code != 200:
                    if url_label == "local":
                        write_progress("downloading", 3, f"Local server returned {resp.status_code}, switching to Cloudflare R2 proxy...")
                        continue
                    elif url_label == "cloudflare_r2":
                        write_progress("downloading", 3, f"Cloudflare R2 proxy returned {resp.status_code}, switching to Security Browser CDN...")
                        continue
                    write_progress("error", 0, f"HTTP {resp.status_code} from {url}")
                    return
                
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                
                write_progress("downloading", 5, f"Downloading from {url_label} server...")
                
                tmp_zip = os.path.join(ext_dir, "data", "engine", f"{bas_version}.zip")
                with open(tmp_zip, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int((downloaded / total_size) * 80) + 5
                                write_progress("downloading", min(pct, 85))
                
                write_progress("extracting", 90)
                
                try:
                    with zipfile.ZipFile(tmp_zip, "r") as zf:
                        zf.extractall(target_dir)
                except zipfile.BadZipFile:
                    try:
                        os.remove(tmp_zip)
                    except:
                        pass
                    if url_label == "local":
                        write_progress("downloading", 3, "Local file corrupt, switching to Cloudflare R2 proxy...")
                        continue
                    elif url_label == "cloudflare_r2":
                        write_progress("downloading", 3, "Cloudflare R2 file corrupt, switching to Security Browser CDN...")
                        continue
                    write_progress("error", 0, "Downloaded file is not a valid ZIP archive")
                    return
                
                try:
                    os.remove(tmp_zip)
                except:
                    pass
                
                write_progress("completed", 100)
                return
                
            except Exception as e:
                if url_label == "local":
                    write_progress("downloading", 3, f"Local server failed, switching to Cloudflare R2 proxy...")
                    continue
                elif url_label == "cloudflare_r2":
                    write_progress("downloading", 3, f"Cloudflare R2 proxy failed, switching to Security Browser CDN...")
                    continue
                write_progress("error", 0, str(e)[:300])
                return
        
        write_progress("error", 0, "All download servers failed")
    
    # Run download in background thread
    def run_bg():
        download_cancelled.discard(version)
        download_processes[version] = True
        try:
            download_and_extract()
        finally:
            download_processes.pop(version, None)
            download_cancelled.discard(version)
    
    threading.Thread(target=run_bg, daemon=True).start()
    return {"status": "started", "version": version}

@router.post("/engine/cancel/{version}")
async def api_cancel_engine(version: str):
    """Ask an in-flight engine download to stop.

    This used to treat download_processes[version] as a subprocess and call
    proc.pid — but both download paths store the literal True and run in a thread,
    so cancelling answered 500 with "'bool' object has no attribute 'pid'". There
    is no process to kill; the download loop watches this flag instead.
    """
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
    if version in download_processes:
        download_cancelled.add(version)
        download_processes.pop(version, None)
        return {"status": "cancelled"}
    return {"status": "not_running"}

@router.get("/engine/status/{version}")
async def api_engine_status(version: str):
    import os
    import json
    
    ext_dir = os.path.dirname(__file__)
    version = version.replace("BAS ", "").replace("BAS-", "").strip()
    # Find bas_version from the name if needed, but UI sends the same name
    # We check if a .progress.json exists in data/engine/BAS_VERSION or just data/engine/
    # But bas_version is unknown here unless we fetch from engine/versions again.
    # For now, let's assume open.js writes to data/engine/{version}.progress.json
    
    progress_file = os.path.join(ext_dir, "data", "engine", f"{version}.progress.json")
    is_running = version in download_processes
    
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r") as f:
                data = json.load(f)
                data["is_running"] = is_running
                return data
        except:
            return {"status": "downloading", "percent": 0, "is_running": is_running}
    
    return {"status": "unknown", "percent": 0, "is_running": is_running}


@router.get("/2fa")
async def api_get_2fa(secret: str = ""):
    """Generate a live 6-digit TOTP code from a base32 secret."""
    if not secret:
        raise HTTPException(400, "Missing 'secret' query parameter")
    try:
        import pyotp
        import time
        # Clean up the secret: remove spaces, uppercase
        clean_secret = secret.replace(" ", "").upper()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)
        return {"code": code, "time": int(time.time()), "remaining": remaining}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate TOTP: {str(e)}")

# ── Chrome Extension Communication ──

import time

# Store connected extensions: token -> {"last_seen": float, "queue": list, "results": dict}
browser_extensions = {}

class BrowserCommandResult(BaseModel):
    token: str
    commandId: str
    action: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

class RegisterRequest(BaseModel):
    token: str
    userAgent: str
    timestamp: int

@router.post("/register")
async def api_register_browser(req: RegisterRequest):
    browser_extensions[req.token] = {"last_seen": time.time(), "queue": [], "results": {}}
    return {"success": True}

@router.delete("/extensions/{token}")
async def api_disconnect_browser(token: str):
    if token in browser_extensions:
        del browser_extensions[token]
    return {"success": True}

@router.get("/extensions")
async def api_get_browser_extensions():
    now = time.time()
    active = []
    # Clean up dead extensions (inactive > 60s)
    for token, data in list(browser_extensions.items()):
        if now - data["last_seen"] < 60:
            active.append({"token": token, "last_seen": data["last_seen"]})
        else:
            del browser_extensions[token]
    return {"extensions": active}

@router.get("/commands/{token}")
async def api_get_commands(token: str):
    if token not in browser_extensions:
        browser_extensions[token] = {"last_seen": time.time(), "queue": [], "results": {}}
    else:
        browser_extensions[token]["last_seen"] = time.time()
        
    if browser_extensions[token]["queue"]:
        cmd = browser_extensions[token]["queue"].pop(0)
        return {"command": cmd}
    return {"command": None}

@router.post("/commands/{token}")
async def api_post_command(token: str, command: dict):
    if token not in browser_extensions:
        browser_extensions[token] = {"last_seen": time.time(), "queue": [], "results": {}}
    
    if "id" not in command:
        import uuid
        command["id"] = str(uuid.uuid4())[:8]
        
    browser_extensions[token]["queue"].append(command)
    return {"success": True, "command_id": command["id"]}

@router.post("/result")
async def api_post_result(result: BrowserCommandResult):
    token = result.token
    if token in browser_extensions:
        browser_extensions[token]["last_seen"] = time.time()
        browser_extensions[token]["results"][result.commandId] = result.model_dump()
        return {"success": True}
    return {"success": False, "error": "Token not found"}

@router.get("/result/{token}/{command_id}")
async def api_get_result(token: str, command_id: str):
    if token in browser_extensions:
        if command_id in browser_extensions[token]["results"]:
            res = browser_extensions[token]["results"].pop(command_id) # Consume result
            return {"ready": True, **res}
    return {"ready": False}


# ── Browser Preview (WebSocket & Canvas proxy) ──

import logging
_preview_processes = {}


def _resolve_profile_for_port(port):
    """Profile của preview đang chạy ở PORT này (None nếu không có / proc đã chết).

    Dùng cho GUEST scope (workspace chia sẻ): endpoint địa chỉ theo port (screenshot/
    ws) không mang profile, nên map port→profile qua đây để chặn port ngoài phạm vi.
    Reap luôn proc chết như is_profile_running.
    """
    try:
        port = int(port)
    except Exception:
        return None
    dead, prof = [], None
    for sid, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc is not None and proc.poll() is not None:
            dead.append(sid)
            continue
        if info.get("port") == port:
            prof = info.get("profile")
    for sid in dead:
        _preview_processes.pop(sid, None)
    return prof


def _resolve_port_for_profile(profile):
    """Port của preview đang chạy cho PROFILE này (None nếu không có / proc đã chết).

    Ngược với _resolve_profile_for_port: dùng cho attach-file (guest kéo file trong Nhóm
    lên browser) khi client chỉ biết profile (node.data.profile) — server tự tìm port
    đang chạy, client KHÔNG được chỉ định port (chống SSRF tới port tuỳ ý).
    """
    if not profile:
        return None
    profile = str(profile)
    dead, port = [], None
    for sid, info in list(_preview_processes.items()):
        proc = info.get("proc")
        if proc is not None and proc.poll() is not None:
            dead.append(sid)
            continue
        if str(info.get("profile")) == profile:
            port = info.get("port")
    for sid in dead:
        _preview_processes.pop(sid, None)
    return port


def _preview_tail_for_profile(profile, n=15):
    """Vài dòng stdout CUỐI của tiến trình node preview cho PROFILE này (nếu còn sổ).

    launch_preview cất deque early_output vào _preview_processes[...] để đường
    /preview/last-error gom được nhật ký THẬT vào `detail` (không rỗng). Đọc thôi,
    không reap — proc có thể đã chết nhưng deque vẫn còn nội dung thread reader đổ vào.
    """
    prof = str(profile or "")
    if not prof:
        return ""
    try:
        for info in list(_preview_processes.values()):
            if str(info.get("profile")) == prof:
                buf = info.get("early_output")
                if buf:
                    return "\n".join(list(buf)[-n:])
    except Exception:
        pass
    return ""

# ── Node dependency bootstrap ────────────────────────────────────────────────
# The extension installs its npm packages in on_enable(), which runs once. A host
# that had no Node at that moment — the normal case on Linux, where the installer
# adds Node in the same run — therefore never got them, and nothing ever retried.
# Install them on demand instead, in the background, because the playwright
# postinstall pulls browser binaries and takes minutes.
_deps_state = {"running": False, "done": False, "error": None, "log": []}


def browser_deps_installed() -> bool:
    return os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_modules"))


def start_browser_deps_install() -> dict:
    """Kick off `npm install` for this extension unless it is already running."""
    import shutil as _shutil
    import threading

    if browser_deps_installed():
        return {"status": "installed"}
    if _deps_state["running"]:
        return {"status": "installing"}

    npm = _shutil.which("npm")
    if not npm:
        return {"status": "error",
                "message": "Node.js (npm) is not installed, so browser automation "
                           "cannot be set up. Install Node.js from https://nodejs.org "
                           "or your package manager, then try again."}

    ext_dir = os.path.dirname(os.path.abspath(__file__))
    _deps_state.update({"running": True, "done": False, "error": None, "log": []})

    def run():
        try:
            proc = subprocess.Popen(
                [npm, "install", "--no-audit", "--no-fund"],
                cwd=ext_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    _deps_state["log"] = (_deps_state["log"] + [line])[-40:]
            proc.wait()
            if proc.returncode != 0 or not browser_deps_installed():
                tail = "\n".join(_deps_state["log"][-8:]) or "(no output)"
                _deps_state["error"] = f"npm install failed (exit {proc.returncode}).\n{tail}"
            else:
                _deps_state["done"] = True
        except Exception as e:
            _deps_state["error"] = str(e)
        finally:
            _deps_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return {"status": "installing"}


@router.get("/deps/status")
async def api_browser_deps_status():
    """Whether browser automation dependencies are present or being installed."""
    return {
        "installed": browser_deps_installed(),
        "installing": _deps_state["running"],
        "error": _deps_state["error"],
        "log": _deps_state["log"][-8:],
    }


@router.post("/deps/install")
async def api_browser_deps_install():
    return start_browser_deps_install()
preview_logger = logging.getLogger("Browser.Preview")


# ── Preflight cho /preview/launch ────────────────────────────────────────────
# Kiểm TRƯỚC khi tốn công spawn node + Chromium. Chắc chắn hỏng thì trả lý do CỤ
# THỂ để cloud hiện thẳng (không mở WebSocket rồi đóng câm như trước). Mọi nhánh
# trả dict {reason, message_vi, detail, ...} HOẶC None (mở được). KHÔNG BAO GIỜ
# ném — đo sai / không đo được thì cho qua, thà không báo còn hơn đoán bừa.
#
# Đặt ngay trong routes.py (không tách module riêng) vì bản vá nóng chỉ đẩy
# routes.py→browser_routes.py sang VPS; một module mới sẽ không được ship và
# preflight sẽ câm trên đúng cái máy cần nó nhất.

# RAM ước lượng cho MỘT phiên preview: cây ShardX Chromium (browser+zygote+gpu+
# renderer) ~350–500MB + node/Playwright ~80–120MB. CHƯA đo trên Linux thật (máy
# build là Windows, không chạy được nhân ShardX Linux) — đây là ước lượng kiến
# trúc, PHẢI đo lại trên VPS: `ps -o rss --ppid <node_pid>` cộng lại + RSS node
# cha, rồi đặt env TUBECLI_PREVIEW_SESSION_MB=<số đo được>.
PREVIEW_SESSION_MB_DEFAULT = 450


def _preview_session_mb() -> int:
    try:
        v = int(os.environ.get("TUBECLI_PREVIEW_SESSION_MB", "") or 0)
        return v if v > 0 else PREVIEW_SESSION_MB_DEFAULT
    except Exception:
        return PREVIEW_SESSION_MB_DEFAULT


def _available_ram_mb() -> Optional[int]:
    """RAM khả dụng (MB) hay None nếu không đọc được. Trên Linux
    psutil.virtual_memory().available đọc /proc/meminfo MemAvailable — <1ms, không
    chặn. Không có psutil thì trả None (bỏ qua, không đoán)."""
    try:
        import psutil
        return int(psutil.virtual_memory().available // (1024 * 1024))
    except Exception:
        return None


def _minutes_since(value) -> Optional[int]:
    """Số phút từ mốc bắt đầu tới giờ. Nhận epoch float/int (bản ghi preview) hoặc
    chuỗi ISO (started_at của agent). None nếu không parse được."""
    try:
        import time as _t
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return max(0, int((_t.time() - float(value)) / 60))
        from datetime import datetime
        started = datetime.fromisoformat(str(value))
        return max(0, int((datetime.now() - started).total_seconds() / 60))
    except Exception:
        return None


def _low_memory_reason(avail_mb, session_mb, in_flight_others: int = 0):
    """Không đủ RAM cho một phiên mới (cộng phần các phiên đang mở song song sẽ
    chiếm). Đây chính là "từ chối mở browser thứ ba khi RAM đã cạn" thay vì mở rồi
    cả mấy cái cùng chết câm."""
    if avail_mb is None:
        return None
    need = int(session_mb) * (1 + max(0, int(in_flight_others)))
    if avail_mb < need:
        return {
            "reason": "low_memory",
            "free": int(avail_mb),
            "need": int(need),
            "session_mb": int(session_mb),
            "message_vi": (
                f"Máy còn {int(avail_mb)} MB RAM, mở một trình duyệt cần khoảng "
                f"{int(need)} MB. Đóng bớt trình duyệt/việc đang chạy hoặc nâng RAM "
                f"rồi thử lại."
            ),
            "detail": (
                f"MemAvailable={int(avail_mb)}MB need={int(need)}MB "
                f"session={int(session_mb)}MB inflight_others={int(in_flight_others)}"
            ),
        }
    return None


def _preview_busy_reason(profile, preview_sessions, instances):
    """Profile có phiên SỐNG không (agent điều khiển / khung khác trên canvas)?

    Đây là ranh giới "không được giết phiên của người khác": phải BÁO, không
    force-kill. `instances` là các bản ghi của browser_process_manager (kèm
    _process, _agent_id, started_at). `preview_sessions` là _preview_processes
    (session_id -> {proc, profile, started_at, ...}). Trả dict lý do hoặc None.
    """
    profile = str(profile)
    # 1) Agent (hoặc lần mở tay từ dashboard) đang chạy browser trên profile này.
    for inst in (instances or []):
        try:
            if str(inst.get("profile")) != profile:
                continue
            proc = inst.get("_process")
            if proc is None or proc.poll() is not None:
                continue                      # đã chết — không tính là bận
            agent_id = inst.get("_agent_id")
            mins = _minutes_since(inst.get("started_at"))
            when = f" (mở {mins} phút trước)" if mins is not None else ""
            if agent_id:
                return {
                    "reason": "profile_busy", "by": "agent",
                    "who": str(agent_id), "mins": mins, "profile": profile,
                    "message_vi": (
                        f"Profile «{profile}» đang được agent «{agent_id}» điều "
                        f"khiển{when}. Chờ nó xong hoặc dừng phiên đó rồi thử lại."
                    ),
                    "detail": (
                        f"agent_id={agent_id} pid={inst.get('pid')} "
                        f"started_at={inst.get('started_at')}"
                    ),
                }
            return {
                "reason": "profile_busy", "by": "manual",
                "who": None, "mins": mins, "profile": profile,
                "message_vi": (
                    f"Profile «{profile}» đang được mở ở nơi khác trên máy này"
                    f"{when}. Đóng phiên đó rồi thử lại."
                ),
                "detail": f"manual pid={inst.get('pid')} started_at={inst.get('started_at')}",
            }
        except Exception:
            continue
    # 2) Một khung preview khác trên canvas đang mở đúng profile này.
    for sid, info in list((preview_sessions or {}).items()):
        try:
            proc = info.get("proc")
            if proc is not None and proc.poll() is not None:
                continue                      # phiên chết — reap ở nơi khác, bỏ qua
            if str(info.get("profile")) != profile:
                continue
            mins = _minutes_since(info.get("started_at"))
            when = f" (mở {mins} phút trước)" if mins is not None else ""
            return {
                "reason": "profile_busy", "by": "frame",
                "who": None, "mins": mins, "profile": profile,
                "message_vi": (
                    f"Profile «{profile}» đang mở ở một khung khác trên canvas"
                    f"{when}. Đóng khung kia trước rồi thử lại."
                ),
                "detail": f"preview_session={sid} port={info.get('port')}",
            }
        except Exception:
            continue
    return None


# ── XEM GHÉP một phiên đang chạy (không giết ai) ───────────────────────
# _preview_busy_reason ở trên cố ý CHỈ BÁO. Nhưng "báo" không được là ngõ cụt: lượt
# chạy theo lịch mở Chromium qua open.js với --remote-debugging-port=0 (open.js:1075),
# nên CHÍNH Chromium ghi cổng CDP của nó vào <profile>/DevToolsActivePort. Không ai
# đọc file đó cho phiên theo lịch — nó là thứ duy nhất cho phép NHÌN phiên agent thay
# vì phải dừng nó. Nối vào KHÔNG giết gì cả, nên ranh giới "không giết phiên của
# người khác" (docstring _preview_busy_reason) vẫn nguyên vẹn: dừng vẫn là một quyết
# định TÁCH BIỆT do người bấm.


def _profile_storage_dir(profile):
    from .profile_manager import PROFILES_DIR
    return os.path.join(PROFILES_DIR, str(profile))


def _epoch_of(value):
    """started_at → epoch giây. Nhận float (bản ghi preview) hoặc ISO (instance)."""
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        from datetime import datetime
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return None


def _devtools_active_port(profile):
    """(cổng, mtime) mà Chromium TỰ ghi ở <profile>/DevToolsActivePort.

    Dòng đầu là cổng, dòng sau là đường dẫn WebSocket — đọc đúng dòng đầu, y như
    boundCdpPort() trong preview_server.cjs. (0, None) khi không có file.
    """
    try:
        path = os.path.join(_profile_storage_dir(profile), "DevToolsActivePort")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
        return int(first), os.path.getmtime(path)
    except Exception:
        return 0, None


def _cdp_alive(port, timeout=1.5):
    """Cổng CDP này có Chromium THẬT đang nghe không.

    ĐÚNG một phép thử, và là phép thử đã có sẵn: cdpAlive() của preview_server.cjs —
    GET /json/version trên 127.0.0.1, chỉ 200 mới tính là sống. Lý do nằm ngay ở comment
    của nó (khối dọn file cổng lúc khởi động): cổng ephemeral được hệ điều hành CẤP
    LẠI, nên một file cổng còn sót trỏ vào browser của NGƯỜI KHÁC. Tin file mà không
    thử = mời người dùng xem nhầm profile.
    """
    try:
        port = int(port)
    except Exception:
        return False
    if port <= 0:
        return False
    try:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("GET", "/json/version")
            return conn.getresponse().status == 200
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return False


def _cdp_port_pid(port):
    """PID đang NGHE ở cổng này, hay None khi không tra được (thiếu psutil/quyền).

    None nghĩa là "không biết", KHÔNG phải "sai" — người gọi phải coi đó là thiếu
    bằng chứng chứ không phải bằng chứng ngược, kẻo trên máy không tra được cổng thì
    không bao giờ xem ghép được.
    """
    try:
        import psutil
        listen = getattr(psutil, "CONN_LISTEN", "LISTEN")
        for c in psutil.net_connections(kind="inet"):
            try:
                if c.status == listen and c.laddr and int(c.laddr.port) == int(port):
                    return c.pid
            except Exception:
                continue
    except Exception:
        return None
    return None


def _pid_in_tree(pid, root_pid):
    """pid có nằm trong cây tiến trình của root_pid không (chính nó hoặc con cháu).

    Bản ghi instance giữ pid của TIẾN TRÌNH NODE (open.js); Chromium là con của nó,
    nên pid nghe cổng CDP gần như không bao giờ bằng pid trong bản ghi.
    """
    try:
        import psutil
        if int(pid) == int(root_pid):
            return True
        for anc in psutil.Process(int(pid)).parents():
            if anc.pid == int(root_pid):
                return True
    except Exception:
        return False
    return False


def _attach_probe(profile, instances):
    """Phiên SỐNG của profile này có nối CDP vào được không → (cổng, lý_do).

    lý_do: 'ok' | 'no_session' | 'no_port_file' | 'stale_port_file' | 'port_dead'
           | 'port_foreign'. Ba bằng chứng, thiếu một là KHÔNG mời:
      1. còn một instance SỐNG đúng profile này (_process.poll() is None) — file của
         một lượt đã chết không bao giờ được dùng;
      2. DevToolsActivePort được ghi SAU khi phiên đó bắt đầu. force_kill_profile dọn
         file này (_STALE_CDP_FILES trong process_manager.py) nhưng một lần sập cứng
         thì không ai dọn hộ, và file cũ trỏ vào cổng ephemeral đã được cấp lại;
      3. cổng trả lời /json/version NGAY BÂY GIỜ, và — nếu tra được — tiến trình nghe
         cổng đó nằm trong cây tiến trình của chính phiên (chặn nốt ca cổng đã bị cấp
         lại cho browser của profile KHÁC).
    """
    profile = str(profile)
    inst = None
    for i in (instances or []):
        try:
            if str(i.get("profile")) != profile:
                continue
            proc = i.get("_process")
            if proc is not None and proc.poll() is not None:
                continue
            inst = i
            break
        except Exception:
            continue
    if inst is None:
        return 0, "no_session"

    port, mtime = _devtools_active_port(profile)
    if not port:
        return 0, "no_port_file"

    started = _epoch_of(inst.get("started_at"))
    # 60s dung sai: bản ghi được tạo ngay trước khi node chạy, và đồng hồ file có thể
    # lệch chút. Chromium ghi file này SAU đó vài giây nên bình thường mtime > started.
    if mtime is not None and started is not None and mtime < started - 60:
        return 0, "stale_port_file"

    if not _cdp_alive(port):
        return 0, "port_dead"

    owner = _cdp_port_pid(port)
    if owner is not None and inst.get("pid") and not _pid_in_tree(owner, inst.get("pid")):
        return 0, "port_foreign"
    return int(port), "ok"


_ATTACH_WHY_VI = {
    "no_session": "phiên đó vừa kết thúc",
    "no_port_file": "phiên đó không mở cổng gỡ lỗi nên không xem ghép được",
    "stale_port_file": "dấu vết cổng còn lại là của lượt chạy trước (không tin được)",
    "port_dead": "cổng gỡ lỗi của phiên đó không còn trả lời",
    "port_foreign": "cổng đó giờ thuộc về một tiến trình khác — không dám nối",
    "probe_failed": "không dò được phiên đó",
}


def _attach_offer(profile, busy, instances, preview_sessions=None):
    """"Bận" thì XEM phiên đó bằng cách nào — luôn trả dict, không bao giờ ném.

    Hai kiểu nối, cùng một câu trả lời cho người gọi:
      • by='frame'  → đã có preview_server chạy sẵn cho profile này; cứ mở WebSocket
        vào đúng cổng đó là hai khung cùng xem (clients là Set, broadcast tới tất cả)
        — không cần đóng khung kia nữa.
      • by='agent'/'manual' → chạy MỘT preview_server ở chế độ --attach-cdp qua
        POST /api/v1/browser/preview/attach. CHỈ XEM (preview_server.cjs từ chối mọi
        lệnh chuột/phím ở chế độ này).
    """
    by = (busy or {}).get("by")
    if by == "frame":
        port = _resolve_port_for_profile(profile)
        if port:
            return {
                "available": True, "mode": "preview_session", "control": "full",
                "preview_port": port, "ws": "/api/v1/browser/preview/ws/%d" % int(port),
                "message_vi": "Khung kia vẫn đang chiếu — có thể xem chung, không cần đóng nó.",
            }
        return {"available": False, "why": "no_session",
                "message_vi": "Không xem ghép được phiên này (" + _ATTACH_WHY_VI["no_session"] + ")."}

    port, why = _attach_probe(profile, instances)
    if not port:
        return {"available": False, "why": why,
                "message_vi": "Không xem ghép được phiên này ("
                              + _ATTACH_WHY_VI.get(why, why) + ")."}
    return {
        "available": True, "mode": "cdp", "control": "view_only",
        "cdp_port": int(port),
        "endpoint": "/api/v1/browser/preview/attach",
        "method": "POST",
        "body": {"profile": str(profile)},
        "message_vi": "Bạn có thể XEM phiên đang chạy ngay tại đây (chỉ xem, không điều khiển).",
    }


def _engine_key_reason(profile):
    """Profile dùng nhân BAS mà chưa có khoá vân tay → không mở được, cần khoá hoặc
    đổi sang ShardX. (Key HẾT HẠN — có key nhưng expired — chỉ lộ lúc launch, do
    preview_server.cjs báo qua message WS 'fatal' reason=engine_expired.)"""
    try:
        if check_launch_blockers(profile) == "BAS_KEY_REQUIRED":
            return {
                "reason": "engine_key", "profile": str(profile),
                "message_vi": (
                    f"Profile «{profile}» dùng nhân Security Browser (BAS) cần khoá "
                    f"vân tay. Nhập khoá trong Cài đặt, hoặc đổi profile sang nhân "
                    f"ShardX (miễn phí, không cần khoá)."
                ),
                "detail": "BAS_KEY_REQUIRED",
            }
    except Exception:
        pass
    return None


def preview_preflight(profile, preview_sessions, instances, in_flight_others: int = 0):
    """Lý do KHÔNG mở được (dict) hay None (mở được). Thứ tự: cụ thể nhất trước —
    profile đang bận → thiếu khoá engine → hết RAM. Không nhánh nào được ném."""
    try:
        busy = _preview_busy_reason(profile, preview_sessions, instances)
        if busy:
            # "Bận" không còn là ngõ cụt: kèm luôn CÁCH XEM phiên đó nếu nối được, để
            # một lần gọi trả đủ hai việc: vì sao không mở được, và bấm gì để xem. Mọi
            # trường cũ (reason/by/who/mins/profile/message_vi/detail) giữ nguyên —
            # nodes.js reasonText() và WorkspaceViewer.js đang đọc chúng.
            try:
                busy["attach"] = _attach_offer(profile, busy, instances, preview_sessions)
            except Exception:
                busy["attach"] = {"available": False, "why": "probe_failed",
                                  "message_vi": _ATTACH_WHY_VI["probe_failed"]}
            if busy["attach"].get("available") and busy.get("message_vi"):
                busy["message_vi"] = (busy["message_vi"] + " "
                                      + busy["attach"].get("message_vi", "")).strip()
            return busy
    except Exception:
        pass
    try:
        eng = _engine_key_reason(profile)
        if eng:
            return eng
    except Exception:
        pass
    try:
        low = _low_memory_reason(_available_ram_mb(), _preview_session_mb(), in_flight_others)
        if low:
            return low
    except Exception:
        pass
    return None


async def _spawn_preview_server(profile, url, extra_args=()):
    """Chạy preview_server.cjs và CHỜ nó thực sự listen — (proc, port, early_output).

    Tách khỏi launch_preview vì nay có HAI lối vào cần đúng bộ kiểm tra này: mở browser
    mới, và XEM GHÉP một phiên đang chạy (--attach-cdp). Ném HTTPException với lý do
    đọc được; không bao giờ trả về một tiến trình đã chết hoặc chưa nghe cổng.
    """
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(ext_dir, "preview_server.cjs")

    # Fail with a reason rather than letting Popen raise a bare FileNotFoundError.
    import shutil as _shutil
    if not _shutil.which("node"):
        raise HTTPException(500, "Node.js is required for browser preview but `node` "
                                 "is not installed. Install Node.js, then try again.")

    # Playwright needs Node 20+. Debian 12 and Ubuntu 22.04 package Node 18, so
    # this passes a plain presence check and then fails inside the preview
    # server with "Playwright requires Node.js 20 or higher" — visible only in
    # its own log, while the page showed a spinner. Say it here instead.
    try:
        _nv = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=10).stdout
        _major = int(_nv.strip().lstrip("v").split(".")[0])
    except Exception:
        _major = 0
    if 0 < _major < 20:
        raise HTTPException(
            500,
            f"Browser automation needs Node.js 20 or newer; this system has "
            f"v{_major}. On Debian/Ubuntu the distribution package is Node 18, "
            f"so install from NodeSource:\n"
            f"  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -\n"
            f"  apt-get install -y nodejs",
        )

    browser_ext_nm = os.path.join(ext_dir, "node_modules")
    if not os.path.isdir(browser_ext_nm):
        # Install them rather than handing the user a command. 503 with a
        # retry-after tells the page this is a wait, not a dead end.
        started = start_browser_deps_install()
        if started.get("status") == "error":
            raise HTTPException(500, started["message"])
        raise HTTPException(
            503,
            "Installing browser automation dependencies (a few minutes — it also "
            "downloads browser binaries). This page will keep retrying.",
            headers={"Retry-After": "20", "X-TubeCLI-Installing": "deps"},
        )

    # Find available port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    # Build environment and NODE_PATH
    env = os.environ.copy()
    existing = env.get("NODE_PATH", "")
    # os.pathsep, not ";". On Linux a semicolon is an ordinary character, so
    # "a;b" was read as one directory named "a;b", NODE_PATH resolved to
    # nothing, and preview_server.cjs died on require('minimist') before it
    # ever listened — which is why the preview WebSocket had nothing to
    # connect to and the page sat on "Initializing browser...".
    env["NODE_PATH"] = browser_ext_nm + (os.pathsep + existing if existing else "")

    from .profile_manager import PROFILES_DIR
    cmd = ["node", preview_path, "--profile", profile or "default",
           "--url", url, "--port", str(port),
           "--profiles-dir", PROFILES_DIR]
    cmd.extend(str(a) for a in (extra_args or ()))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ext_dir, encoding="utf-8", errors="replace",
        env=env,
    )
    
    import threading
    from collections import deque
    # Keep the first lines around. When node dies on startup its reason is the
    # only useful thing on screen, and it used to scroll past into the server
    # log while the API cheerfully reported success.
    early_output = deque(maxlen=40)

    def log_proc_output(p, name):
        try:
            for line in p.stdout:
                early_output.append(line.rstrip())
                print(f"[PreviewServer][{name}] {line.rstrip()}", flush=True)
        except Exception as e:
            print(f"[PreviewServer][{name}] Error reading stdout: {e}", flush=True)
        finally:
            try: p.stdout.close()
            except: pass

    t = threading.Thread(target=log_proc_output, args=(proc, profile), daemon=True)
    t.start()

    # Do not claim "launched" until the preview server is actually listening.
    # Returning immediately meant a node process that died on startup still
    # produced a success response, and the page then opened a WebSocket to a
    # port with nothing behind it and waited on "Initializing browser..."
    # forever with no error anywhere.
    import socket as _socket
    deadline = time.time() + 25
    listening = False
    while time.time() < deadline:
        if proc.poll() is not None:
            await asyncio.sleep(0.2)      # let the reader thread drain
            detail = "\n".join(list(early_output)[-15:]) or "(no output)"
            raise HTTPException(
                500,
                f"Browser preview failed to start (node exited with code "
                f"{proc.returncode}).\n{detail}",
            )
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                listening = True
                break
        await asyncio.sleep(0.4)

    if not listening:
        try:
            proc.terminate()
        except Exception:
            pass
        detail = "\n".join(list(early_output)[-15:]) or "(no output)"
        raise HTTPException(
            500,
            f"Browser preview did not start listening on port {port} within 25s.\n{detail}",
        )
    return proc, port, early_output


@router.post("/preview/launch")
async def launch_preview(request: Request):
    """Launch a browser for preview/element picking."""
    body = await request.json()
    profile = body.get("profile", "")
    url = body.get("url", "https://google.com")
    if not url or url == "about:blank":
        url = "https://google.com"

    # force (mặc định): mở lại luôn được — dọn sạch phiên cũ của CHÍNH profile này
    # rồi chạy. Trước đây gặp phiên cũ là ném 400 "already running", trong khi phiên
    # đó thường đã chết từ lần restart trước và chỉ còn lại khoá.
    force = bool(body.get("force", True))
    async with _launching_lock:
        # PREFLIGHT — chạy TRƯỚC force-kill: nếu profile đang có phiên SỐNG (agent
        # hoặc khung khác trên canvas) thì BÁO chứ không giết; nếu RAM/engine chặn
        # thì từ chối luôn, khỏi spawn node rồi đóng câm. Force-kill bên dưới chỉ để
        # dọn phiên ĐÃ CHẾT / khoá mồ côi của chính profile này.
        from .process_manager import browser_process_manager as _bpm
        try:
            # Đọc thẳng _instances (kèm _agent_id/_process) thay vì thêm method mới
            # ở process_manager.py: bản vá nóng chỉ ship routes.py, method mới sẽ
            # KHÔNG có trên VPS → AttributeError. Cùng tiến trình nên đọc trực tiếp
            # dưới lock của nó là an toàn.
            with _bpm._instances_lock:
                _instances_snapshot = list(_bpm._instances.values())
        except Exception:
            _instances_snapshot = []
        # RAM mà các launch khác đang bay sẽ sớm chiếm — để browser thứ 2/3 bị từ
        # chối có lý do thay vì cùng OOM (hàng đợi đầy đủ là việc của G1).
        _in_flight = sum(1 for p in _launching_profiles if p != profile)
        _pf = preview_preflight(profile, _preview_processes, _instances_snapshot,
                                in_flight_others=_in_flight)
        if _pf is not None:
            # HTTP 200 + {ok:false,...}: cloud hiện message_vi NGAY, không mở WebSocket.
            preview_logger.info("preflight từ chối %s: %s", profile, _pf.get("reason"))
            return {"ok": False, **_pf}

        if _is_launching(profile) or is_profile_running(profile):
            if not force:
                raise HTTPException(400, f"Profile '{profile}' is already running or opening.")
            from .process_manager import force_kill_profile, browser_process_manager
            try:
                browser_process_manager.stop_by_profile(profile)
            except Exception:
                pass
            for sid, info in list(_preview_processes.items()):
                if info.get("profile") == profile:
                    _preview_processes.pop(sid, None)
            await asyncio.to_thread(force_kill_profile, profile)
            _launching_profiles.pop(profile, None)
        import time as _time

        _launching_profiles[profile] = _time.time()

    try:
        proc, port, early_output = await _spawn_preview_server(profile, url)

        session_id = f"preview_{int(time.time())}"
        # started_at + opened_by: để preflight của LẦN mở sau biết profile này đang
        # mở ở "một khung khác trên canvas (mở N phút trước)" thay vì báo chung chung.
        _preview_processes[session_id] = {
            "proc": proc, "port": port, "profile": profile,
            "started_at": time.time(),
            "opened_by": (body.get("opened_by") or "canvas"),
            # Giữ deque stdout để /preview/last-error gom nhật ký THẬT vào detail nếu
            # browser chết SAU khi đã listen (crash sau launch-success là ca hay gặp).
            "early_output": early_output,
        }
        return {"status": "launched", "session_id": session_id, "port": port}
    finally:
        async with _launching_lock:
            _launching_profiles.pop(profile, None)

@router.post("/preview/stop")
async def stop_preview(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    info = _preview_processes.pop(session_id, None)
    if info:
        try:
            # Kill process tree on Windows/Linux
            import platform
            proc = info["proc"]
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=5
                )
            else:
                # SIGTERM rồi phải KIỂM lại. Ta vừa xoá phiên khỏi _preview_processes,
                # nên nếu node không chết thì không còn ai theo dõi nó nữa, mà Chromium
                # con của nó vẫn giữ user-data-dir của profile — lần mở sau chết vì
                # SingletonLock và cổng preview thì bị chiếm tới lúc restart. Một
                # preview_server cũ (máy vá nóng lệch phiên bản) bắt SIGTERM mà không
                # thoát là đúng cảnh đó. Xin không được thì lấy bằng vũ lực.
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        return {"status": "stopped"}
    return {"status": "not_found"}

from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/preview/ws/{port}")
async def ws_preview_proxy(websocket: WebSocket, port: int):
    """Proxy WebSocket connection to the local preview server.

    Checked here because HTTP middleware never runs for a WebSocket: Starlette
    dispatches the "websocket" scope past every @app.middleware("http"),
    including the login gate. Without this, the route proxies raw traffic to any
    localhost port a caller names, with no credential at all.
    """
    from tubecli.core.ws_auth import reject_unless_allowed

    # GUEST (workspace chia sẻ): opt-in per-endpoint. Cho qua NẾU cookie guest hợp lệ
    # VÀ port này thuộc profile ∈ scope. Không phải guest → owner check như thường.
    # FAIL-CLOSED: lỗi → coi như không phải guest. (browser_scripts WS KHÔNG có nhánh
    # này nên guest luôn bị từ chối ở đó — đúng ý G1 chỉ browser.)
    guest_ok = False
    try:
        from tubecli.core import auth
        _gscope = auth.guest_scope_for(websocket.cookies.get(auth.GUEST_COOKIE))
        if _gscope:
            _prof = _resolve_profile_for_port(port)
            guest_ok = bool(_prof) and _prof in set(str(x) for x in (_gscope.get("profiles") or []))
    except Exception:
        guest_ok = False

    if not guest_ok and not await reject_unless_allowed(websocket):
        return
    await websocket.accept()
    preview_logger.info(f"[WS Proxy] Client connected, proxying to localhost:{port}")
    
    local_ws = None
    try:
        import aiohttp
        session = aiohttp.ClientSession()
        
        # Retry connection to local preview server up to 20 times (10 seconds)
        retries = 20
        for attempt in range(retries):
            try:
                # 127.0.0.1 rather than "localhost", to match the address the
                # preview server is checked on and to avoid an IPv6-first lookup
                # against an IPv4-only listener.
                local_ws = await session.ws_connect(f"http://127.0.0.1:{port}", timeout=5)
                break
            except (aiohttp.ClientConnectorError, aiohttp.WSServerHandshakeError) as e:
                if attempt == retries - 1:
                    preview_logger.error(
                        f"[WS Proxy] Failed to connect to 127.0.0.1:{port} after "
                        f"{retries} attempts: {type(e).__name__}: {e}")
                    try:
                        await websocket.close(code=1011, reason=str(e)[:120])
                    except Exception:
                        pass
                    raise e
                await asyncio.sleep(0.5)
                
        preview_logger.info(f"[WS Proxy] Connected to local preview server on port {port}")
        
        async def forward_to_local():
            """Client → Local preview server"""
            try:
                while True:
                    # receive() rather than receive_text(): the client may send
                    # binary one day, and receive_text() raises on anything else.
                    event = await websocket.receive()
                    if event.get("type") == "websocket.disconnect":
                        break
                    if event.get("text") is not None:
                        await local_ws.send_str(event["text"])
                    elif event.get("bytes") is not None:
                        await local_ws.send_bytes(event["bytes"])
            except (WebSocketDisconnect, Exception):
                pass

        async def forward_to_client():
            """Local preview server → Client"""
            try:
                async for msg in local_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        # Screen frames travel as raw bytes. This branch did not
                        # exist, so binary frames matched nothing and were
                        # dropped in silence: the socket stayed up, JSON status
                        # messages still arrived, and the canvas stayed black.
                        # A relay has to carry every frame type its endpoints
                        # use, not just the one it was written for.
                        await websocket.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
            except Exception:
                pass
        
        async def heartbeat():
            """Keep connection alive through reverse proxies"""
            try:
                while True:
                    await asyncio.sleep(15)
                    try:
                        await local_ws.ping()
                    except Exception:
                        break
            except asyncio.CancelledError:
                pass
        
        done, pending = await asyncio.wait(
            [asyncio.create_task(forward_to_local()),
             asyncio.create_task(forward_to_client()),
             asyncio.create_task(heartbeat())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except ImportError:
        preview_logger.error("[WS Proxy] aiohttp not installed.")
        try:
            await websocket.close(code=1011, reason="aiohttp not installed on server")
        except Exception:
            pass
    except Exception as e:
        preview_logger.error(f"[WS Proxy] Error: {e}")
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass
    finally:
        if local_ws:
            await local_ws.close()
            await session.close()

@router.get("/preview/screenshot/{port}")
async def proxy_screenshot(port: int):
    """Proxy screenshot from local preview server for remote access."""
    import asyncio
    detail = "Preview server unavailable"
    try:
        import requests as _requests
        # 127.0.0.1, not "localhost": in a container localhost can resolve to ::1
        # first while the node server listens on IPv4 only, and the connection is
        # then refused for a server that is running perfectly well.
        resp = await asyncio.to_thread(
            _requests.get, f"http://127.0.0.1:{port}/screenshot", timeout=10
        )
        if resp.status_code == 200:
            from fastapi.responses import Response
            return Response(content=resp.content, media_type="image/jpeg")
        # Pass the preview server's own words through. A bare "unavailable" said
        # nothing about a browser that failed to start inside it.
        body = (resp.text or "")[:300]
        detail = f"Preview server returned {resp.status_code}: {body}" if body else \
                 f"Preview server returned {resp.status_code}"
        preview_logger.error(f"[Screenshot Proxy] {detail}")
    except Exception as e:
        detail = f"Could not reach preview server on port {port}: {e}"
        preview_logger.error(f"[Screenshot Proxy] {detail}")
    raise HTTPException(502, detail)


@router.get("/preview/last-error")
async def api_preview_last_error(profile: str = "", request: Request = None):
    """Lý do THẬT khiến preview của <profile> chết TRƯỚC khi hiện được hình.

    preview_server.cjs ghi <profile>/preview_last_error.json {reason,message,detail,at}
    ngay trước khi thoát khi CHƯA everReady (và xoá khi một phiên đã xem được hình). Cloud
    gọi đường này khi WebSocket đóng CÂM — khung 'fatal' qua WS có thể mất do timing (WS
    chưa connect lúc server phát) — để nói ĐÚNG lý do thay vì đoán "hết RAM".

    Trả {reason, message_vi, detail, at} nếu file MỚI (~2 phút), ngược lại {} (không có
    lỗi gần đây / file cũ không liên quan lần đóng này).

    Owner-only: KHÁCH (workspace chia sẻ) KHÔNG được đọc nhật ký lỗi máy chủ.
    """
    # Khách (request.state.guest_scope != None) không được xem log lỗi máy chủ.
    if request is not None and getattr(getattr(request, "state", None), "guest_scope", None) is not None:
        raise HTTPException(403, "Chỉ chủ máy mới xem được nhật ký lỗi preview")

    prof = str(profile or "").strip()
    if not prof:
        return {}

    from .profile_manager import PROFILES_DIR
    err_path = os.path.join(PROFILES_DIR, prof, "preview_last_error.json")
    # Chống path traversal: realpath của file PHẢI nằm trong PROFILES_DIR (chặn "../").
    try:
        base = os.path.realpath(PROFILES_DIR)
        real = os.path.realpath(err_path)
        if os.path.commonpath([base, real]) != base:
            return {}
    except Exception:
        return {}
    if not os.path.isfile(err_path):
        return {}

    # Chỉ trả nếu file MỚI. Cửa sổ ~2 phút (nới hơn con số 60s trong spec) để bù độ trễ
    # launch (tới 25s) + thời điểm cloud gọi sau khi WS đóng; file cũ hơn là của lần
    # hỏng xa trước, KHÔNG liên quan lần đóng này nên coi như không có.
    try:
        if (time.time() - os.path.getmtime(err_path)) > 120:
            return {}
    except Exception:
        return {}
    try:
        with open(err_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    reason = data.get("reason") or "browser_crashed"
    message = data.get("message") or ""
    detail = data.get("detail") or ""
    at = data.get("at") or ""

    # Gom vài dòng stdout CUỐI của tiến trình node preview (nếu phiên còn trong sổ) để
    # "xem nhật ký" có nội dung thật chứ không rỗng.
    tail = _preview_tail_for_profile(prof)
    if tail:
        detail = (detail + "\n\n--- nhật ký preview (mới nhất) ---\n" + tail) if detail else tail

    return {"reason": reason, "message_vi": message, "detail": detail, "at": at}


@router.post("/preview/control/{port}/{action:path}")
async def proxy_preview_control(port: int, action: str, request: Request):
    """Forward a control command to the preview server running on this machine.

    The viewer used to POST to http://localhost:<port>/navigate straight from the
    page. That only works when the browser and the preview server are the same
    machine — from any remote dashboard, and from a container where only 5295 is
    published, it is ERR_CONNECTION_REFUSED. Everything goes through the API now,
    which is on the machine that owns the port.
    """
    import asyncio
    # "read": trả CHỮ của trang đang mở (browser_read của agent trong Nhóm). Đây là
    # đường DUY NHẤT ra khỏi preview server cho nội dung trang, và nó nằm sau cùng một
    # cửa như mọi control khác: server.py::_guest_allowed KHÔNG mở /preview/control/*
    # cho guest (deny mặc định), nên chỉ CHỦ (admin token) — và group_actions gọi
    # in-process — mới tới được đây. Người gọi không tự chọn được cổng nào khác:
    # browser_read lấy port từ sổ tiến trình của chính server (_resolve_port_for_profile).
    allowed = {"navigate", "pick/start", "pick/stop", "back", "forward", "reload",
               "click", "type", "scroll", "read"}
    if action not in allowed:
        raise HTTPException(400, f"Unknown preview action '{action}'")
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        import requests as _requests
        resp = await asyncio.to_thread(
            _requests.post, f"http://127.0.0.1:{port}/{action}", json=body, timeout=30
        )
        try:
            return resp.json()
        except Exception:
            return {"status": "ok" if resp.status_code < 400 else "error",
                    "code": resp.status_code, "body": (resp.text or "")[:300]}
    except Exception as e:
        preview_logger.error(f"[Preview Control] {action} -> {e}")
        raise HTTPException(502, f"Preview server did not accept '{action}': {e}")


@router.post("/preview/upload/{port}")
async def api_preview_upload_files(port: int, files: List[UploadFile] = File(...)):
    """Upload files for the file chooser dialog of browser at port."""
    import uuid
    import shutil
    import requests
    
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(ext_dir, "data", "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Create unique directory for this upload batch
    upload_id = str(uuid.uuid4())
    batch_dir = os.path.join(temp_dir, upload_id)
    os.makedirs(batch_dir, exist_ok=True)
    
    file_paths = []
    try:
        for file in files:
            safe_filename = os.path.basename(file.filename)
            dest_path = os.path.join(batch_dir, safe_filename)
            
            with open(dest_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)
            file_paths.append(dest_path)
            
        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(
            requests.post,
            node_url,
            json={"filePaths": file_paths},
            timeout=300
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text}")
    except Exception as e:
        if os.path.exists(batch_dir):
            try:
                shutil.rmtree(batch_dir)
            except Exception:
                pass
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"File upload failed: {str(e)}")


# ── Chunked upload (file lớn) ────────────────────────────────────────────────
# Domain tunnel đi qua Cloudflare edge giới hạn 100MB/request. Video dài vượt mức
# này → 413 ở edge (client thấy CORS/ERR_FAILED). Chia file thành chunk < 100MB,
# gửi từng phần rồi ghép lại ở server. Mỗi request nhỏ nên lọt edge.
def _upload_temp_dir():
    ext_dir = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(ext_dir, "data", "temp_uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_upload_id(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "", str(s or ""))[:64]


@router.post("/preview/upload-chunk/{port}")
async def api_preview_upload_chunk(
    port: int,
    upload_id: str = Form(...),
    file_name: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
):
    """Nhận một mảnh của file lớn. Lưu thành <upload_id>/<file>.partNNNNNN."""
    uid = _safe_upload_id(upload_id)
    if not uid:
        raise HTTPException(400, "upload_id không hợp lệ")
    batch_dir = os.path.join(_upload_temp_dir(), uid)
    os.makedirs(batch_dir, exist_ok=True)
    safe_name = os.path.basename(file_name)
    part_path = os.path.join(batch_dir, f"{safe_name}.part{int(chunk_index):06d}")
    try:
        with open(part_path, "wb") as buffer:
            while data := await chunk.read(1024 * 1024):
                buffer.write(data)
    except Exception as e:
        raise HTTPException(500, f"Lưu chunk lỗi: {e}")
    return {"ok": True, "chunk": int(chunk_index)}


class UploadFinalizeRequest(BaseModel):
    upload_id: str
    files: List[Dict[str, Any]]   # [{name, total_chunks}]


@router.post("/preview/upload-finalize/{port}")
async def api_preview_upload_finalize(port: int, req: UploadFinalizeRequest):
    """Ghép các chunk thành file hoàn chỉnh rồi gắn vào filechooser đang chờ."""
    import shutil
    import requests

    uid = _safe_upload_id(req.upload_id)
    batch_dir = os.path.join(_upload_temp_dir(), uid)
    if not uid or not os.path.isdir(batch_dir):
        raise HTTPException(400, "Phiên upload không tồn tại")

    file_paths = []
    try:
        for f in req.files:
            safe_name = os.path.basename(str(f.get("name", "")))
            total = int(f.get("total_chunks", 0))
            if not safe_name or total <= 0:
                raise HTTPException(400, "Thông tin file không hợp lệ")
            final_path = os.path.join(batch_dir, safe_name)
            with open(final_path, "wb") as out:
                for i in range(total):
                    part_path = os.path.join(batch_dir, f"{safe_name}.part{i:06d}")
                    if not os.path.exists(part_path):
                        raise HTTPException(400, f"Thiếu mảnh {i} của {safe_name}")
                    with open(part_path, "rb") as p:
                        while data := p.read(1024 * 1024):
                            out.write(data)
                    try:
                        os.remove(part_path)
                    except Exception:
                        pass
            file_paths.append(final_path)

        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(
            requests.post, node_url, json={"filePaths": file_paths}, timeout=600
        )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text}")
    except Exception as e:
        try:
            shutil.rmtree(batch_dir)
        except Exception:
            pass
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"Finalize upload lỗi: {e}")


class UploadLocalRequest(BaseModel):
    paths: List[str]


@router.post("/preview/upload-local/{port}")
async def api_preview_upload_local(port: int, req: UploadLocalRequest):
    """Gắn file CÓ SẴN trên VPS vào filechooser đang chờ — KHÔNG upload lại.

    Dùng cho: chọn file từ File Manager (file sẵn trên máy chủ), hoặc file vừa tải
    từ Google Drive về VPS. Nhanh vì bỏ qua bước tải file từ máy người dùng lên."""
    import requests
    paths = []
    for p in (req.paths or []):
        ap = os.path.abspath(os.path.expanduser(str(p)))
        if not os.path.isfile(ap):
            raise HTTPException(400, f"File không tồn tại trên VPS: {p}")
        paths.append(ap)
    if not paths:
        raise HTTPException(400, "Chưa chọn file")
    try:
        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(
            requests.post, node_url, json={"filePaths": paths}, timeout=600
        )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Gắn file từ VPS lỗi: {e}")


class SetInputRequest(BaseModel):
    paths: List[str]
    selector: Optional[str] = None


@router.post("/preview/set-input/{port}")
async def api_preview_set_input(port: int, req: SetInputRequest):
    """Gắn file VPS thẳng vào ô <input type=file> của trang đang mở.

    Khác /preview/upload-local: đường kia đòi filechooser đang chờ, tức là đòi một
    người vừa bấm nút tải lên. Agent chạy theo lịch không có ai bấm hộ. KHÔNG mở cho
    guest (không nằm trong allowlist ở server.py, deny mặc định) — path tuỳ ý ở đây
    cũng là exfil như upload-local.
    """
    import requests
    paths = []
    for p in (req.paths or []):
        ap = os.path.abspath(os.path.expanduser(str(p)))
        if not os.path.isfile(ap):
            raise HTTPException(400, f"File không tồn tại trên VPS: {p}")
        paths.append(ap)
    if not paths:
        raise HTTPException(400, "Chưa chọn file")
    payload = {"filePaths": paths}
    if req.selector:
        payload["selector"] = str(req.selector)[:200]
    try:
        response = await asyncio.to_thread(
            requests.post, f"http://localhost:{port}/set-input-files", json=payload, timeout=300
        )
    except Exception as e:
        raise HTTPException(500, f"Gắn file vào input lỗi: {e}")
    if response.status_code == 200:
        return response.json()
    if response.status_code == 404:
        raise HTTPException(404, "Trang đang mở không có ô chọn file nào khớp")
    raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text}")


class AttachFileRequest(BaseModel):
    profile: str
    path: str


@router.post("/preview/attach-file")
async def api_preview_attach_file(req: AttachFileRequest, request: Request):
    """Gắn MỘT file VPS (∈ folder/file được chia sẻ) vào filechooser browser của PROFILE.

    GUEST kéo file trong Nhóm lên browser để DÙNG. Client chỉ gửi {profile, path}; server
    tự tìm port đang chạy của profile (client KHÔNG chỉ định port) + canonical hoá path
    GIỐNG file-manager route rồi feed realpath cho Playwright. Enforce chính ở _guest_allowed
    (profile∈scope + path∈folders/files); đây là lớp 2 defense-in-depth. File đã trên VPS →
    không staging, không exfil (file sharee vốn được phép đọc, nay đưa vào chính browser họ).
    """
    import requests as _rq
    from tubecli.core import auth

    prof = str(req.profile or "")
    raw = req.path or ""
    safe = auth._canon_fs(raw)

    gscope = getattr(getattr(request, "state", None), "guest_scope", None)
    if gscope is not None:
        if prof not in set(str(x) for x in (gscope.get("profiles") or [])):
            raise HTTPException(403, "Profile ngoài phạm vi được chia sẻ")
        folders = gscope.get("folders") or []
        files = gscope.get("files") or []
        if not (auth.path_in_folders(raw, folders) or auth.path_is_shared_file(raw, files)):
            raise HTTPException(403, "File ngoài phạm vi được chia sẻ")

    if not os.path.isfile(safe):
        raise HTTPException(404, "File không tồn tại")
    port = _resolve_port_for_profile(prof)
    if not port:
        raise HTTPException(409, "Browser của profile này chưa mở")

    try:
        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(_rq.post, node_url, json={"filePaths": [safe]}, timeout=600)
        if response.status_code != 200:
            raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text[:200]}")
        return {"status": "attached", "name": os.path.basename(safe)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Gắn file vào browser lỗi: {e}")


class DriveAttachRequest(BaseModel):
    file_id: str
    cred_id: Optional[str] = None


@router.post("/preview/drive-attach/{port}")
async def api_preview_drive_attach(port: int, req: DriveAttachRequest, request: Request):
    """Tải MỘT file Google Drive rồi GẮN thẳng vào filechooser của browser ở {port}.

    Đường AN TOÀN cho GUEST (workspace chia sẻ): guest CHỈ gửi file_id + cred_id, KHÔNG
    gửi path nào — server tự đặt thư mục staging CỐ ĐỊNH. Thay cho luồng download+upload-
    local (upload-local nhận abs path tuỳ ý = exfil, KHÔNG mở cho guest). Enforce chính ở
    _guest_allowed; đây là lớp 2 (defense-in-depth) + dùng được cho cả chủ.
    """
    import requests as _rq
    import uuid as _uuid
    from tubecli.config import DATA_DIR
    from tubecli.extensions.file_manager.drive import _svc, _download_to_spool

    gscope = getattr(getattr(request, "state", None), "guest_scope", None)
    if gscope is not None:
        prof = _resolve_profile_for_port(port)
        if not prof or prof not in set(str(x) for x in (gscope.get("profiles") or [])):
            raise HTTPException(403, "Port ngoài phạm vi được chia sẻ")
        fm = gscope.get("file_manager") or {}
        allowed = set(str(x) for x in (fm.get("drive_cred_ids") or []))
        if not fm.get("drive") or (req.cred_id is not None and str(req.cred_id) not in allowed):
            raise HTTPException(403, "Drive account ngoài phạm vi được chia sẻ")

    def work():
        svc, _email = _svc(req.cred_id)
        spool, name, _mime = _download_to_spool(svc, req.file_id)
        ws = str((gscope or {}).get("workspace") or "direct")
        stage = os.path.join(str(DATA_DIR), "guest_drive", ws, _uuid.uuid4().hex)
        os.makedirs(stage, exist_ok=True)
        dest = os.path.join(stage, os.path.basename(name) or "file")
        try:
            with open(dest, "wb") as f:
                while True:
                    chunk = spool.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        finally:
            spool.close()
        return dest, name

    try:
        dest, name = await asyncio.to_thread(work)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Tải file từ Drive lỗi: {e}")

    # KHÔNG xoá staging ngay: Playwright setFiles đọc file lúc trang SUBMIT (sau này),
    # xoá sớm sẽ hỏng upload. Dọn theo workspace khi revoke/hết hạn (auth.revoke...).
    try:
        node_url = f"http://localhost:{port}/upload-files"
        response = await asyncio.to_thread(_rq.post, node_url, json={"filePaths": [dest]}, timeout=600)
        if response.status_code != 200:
            raise HTTPException(502, f"Node preview server returned {response.status_code}: {response.text[:200]}")
        return {"status": "attached", "name": os.path.basename(dest)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Gắn file Drive vào browser lỗi: {e}")


# ── Kho proxy ───────────────────────────────────────────────────────────────
# Vì sao có nhóm route này: hồ sơ chỉ giữ MỘT chuỗi proxy, và bulk_set_proxy đặt
# CÙNG một proxy cho nhiều hồ sơ. Kho cho phép gán theo nguồn ("một proxy từ Kho
# VN") và phát đều, thay vì gõ tay từng địa chỉ.
#
# Mọi route ghi đều là POST: route GET không mang Origin nên origin_guard cho qua,
# và một trang bất kỳ có thể gọi được — cùng luật với các extension khác trong repo.

class KhoRequest(BaseModel):
    name: str = ""
    new_name: str = ""
    note: str = ""
    delete_proxies: bool = False


class ProxyImportRequest(BaseModel):
    kho: str = ""
    text: str = ""
    expiry_date: str = ""
    note: str = ""


class ProxyEditRequest(BaseModel):
    id: str = ""
    ids: List[str] = []
    kho: Optional[str] = None
    expiry_date: Optional[str] = None
    note: Optional[str] = None
    proxy_str: Optional[str] = None


class ProxyTestRequest(BaseModel):
    id: str = ""
    proxy_str: str = ""


class ProxyAssignRequest(BaseModel):
    profiles: List[str] = []
    kho: str = ""
    rotate_minutes: int = 0


@router.get("/proxy-pool")
async def api_proxy_pool(kho: str = "", include_expired: bool = True):
    """Kho và proxy trong kho. Kèm `blocker` cho từng proxy: engine hiện tại có
    chạy được nó không, và nếu không thì vì sao — biết trước còn hơn mở trình
    duyệt xong mới thấy mọi trang chết."""
    from . import proxy_pool as pool
    return {
        "success": True,
        "khos": pool.list_khos(),
        "proxies": pool.list_proxies(kho or None, include_expired),
        "relay_note": "PROXY_SOCKS5_AUTH_UNSUPPORTED chỉ chặn khi KHÔNG qua relay",
    }


@router.post("/proxy-pool/kho/create")
async def api_kho_create(req: KhoRequest):
    from . import proxy_pool as pool
    return pool.create_kho(req.name, req.note)


@router.post("/proxy-pool/kho/rename")
async def api_kho_rename(req: KhoRequest):
    from . import proxy_pool as pool
    return pool.rename_kho(req.name, req.new_name)


@router.post("/proxy-pool/kho/delete")
async def api_kho_delete(req: KhoRequest):
    from . import proxy_pool as pool
    return pool.delete_kho(req.name, req.delete_proxies)


@router.post("/proxy-pool/import")
async def api_proxy_import(req: ProxyImportRequest):
    """Dán nhiều dòng, mỗi dòng một proxy. Trả về NGUYÊN VĂN các dòng không đọc
    được: báo "3 dòng lỗi" mà không nói dòng nào thì người dùng phải tự dò."""
    from . import proxy_pool as pool
    return pool.add_proxies(req.kho, req.text, req.expiry_date, req.note)


@router.post("/proxy-pool/update")
async def api_proxy_update(req: ProxyEditRequest):
    from . import proxy_pool as pool
    fields = {k: v for k, v in
              (("kho", req.kho), ("expiry_date", req.expiry_date),
               ("note", req.note), ("proxy_str", req.proxy_str))
              if v is not None}
    return pool.update_proxy(req.id, **fields)


@router.post("/proxy-pool/delete")
async def api_proxy_delete(req: ProxyEditRequest):
    from . import proxy_pool as pool
    ids = req.ids or ([req.id] if req.id else [])
    return pool.remove_proxies(ids)


@router.post("/proxy-pool/test")
async def api_proxy_test(req: ProxyTestRequest):
    """Đi thật qua proxy để lấy IP công khai. Chạy trong luồng riêng: requests là
    đồng bộ và một proxy chết ngốn trọn 15 giây timeout của event loop."""
    from . import proxy_pool as pool
    raw = req.proxy_str
    if not raw and req.id:
        for p in pool.list_proxies():
            if p.get("id") == req.id:
                raw = p.get("proxy_str", "")
                break
    if not raw:
        raise HTTPException(400, "Thiếu proxy để kiểm tra")
    result = await asyncio.to_thread(pool.test_proxy, raw)
    if req.id:
        pool.record_test(req.id, result)
    return result


@router.post("/proxy-pool/assign")
async def api_proxy_assign(req: ProxyAssignRequest):
    """Phát proxy từ kho cho các hồ sơ, chia ĐỀU.

    Ghi thêm proxy_kho và proxy_rotate_minutes lên hồ sơ để lần mở sau còn biết
    proxy này đến từ kho nào — không có nó thì không xoay vòng được, vì xoay cần
    biết lấy cái kế tiếp ở đâu."""
    from . import proxy_pool as pool
    names = [n for n in (req.profiles or []) if n]
    if not names:
        raise HTTPException(400, "Chưa chọn hồ sơ nào")
    picks = pool.distribute(req.kho or None, len(names))
    if not any(picks):
        return {"success": False, "error": f"Kho '{req.kho}' không có proxy dùng được"}
    assigned = []
    for name, proxy in zip(names, picks):
        if not proxy:
            continue
        update_profile(name, proxy=proxy, proxy_kho=req.kho,
                       proxy_rotate_minutes=int(req.rotate_minutes or 0))
        assigned.append({"profile": name, "proxy": proxy})
    return {"success": True, "assigned": assigned, "count": len(assigned)}


@router.get("/proxy-pool/relays")
async def api_proxy_relays():
    """Relay nào đang chạy, đang dùng upstream nào, đã xoay mấy lần.

    Mật khẩu bị che ở tầng dưới (proxy_relay._mask) chứ không ở đây — che tại
    nơi phát sinh thì mọi đường ra đều an toàn."""
    from .proxy_relay import manager
    return {"success": True, "relays": manager.status()}
