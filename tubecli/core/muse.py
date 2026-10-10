"""Muse (muse.ai — agent AI của Meta) làm một nhà cung cấp AI như 9Router: viết chữ + vẽ ảnh.

User 2/10/2026: «máy dev browser chayagent có phiên đăng nhập muse.ai — tích hợp vào để có thể tạo ảnh,
tạo kịch bản bằng cách chọn model trong cloud api giống 9router».

Muse KHÔNG có API: chat đi qua WebSocket mã hoá (Noise), nên ta lái chính ứng dụng web của nó trong
một hồ sơ trình duyệt TubeCLI đã đăng nhập (extensions/browser/muse_tool.cjs, nối CDP vào phiên đang
chạy — cách làm của github.com/duclm1x1/Muse-Chat-MCP). Mô-đun này là MỘT chỗ biết:

  * hồ sơ nào giữ phiên Muse (cài đặt `muse_profile` trong global_settings.json, chọn ở Cloud API Keys)
    + các hồ sơ PHỤ `muse_extra_profiles` — mỗi hồ sơ một tài khoản Muse khác (5/10/2026)
  * mở hồ sơ ấy ẨN khi nó đang tắt (như youtube_cookies), rồi để nó sống tối đa HIDDEN_SESSION_MAX
  * mỗi tài khoản mỗi lúc `muse_lanes` lượt (mặc định MỘT — một tài khoản Muse = một người gõ); nhiều tài
    khoản thì nhiều lượt chạy cùng lúc — xem _acquire
  * gõ vào chat phụ nào: dùng lại một chat phụ cho `muse_turns_per_chat` lượt rồi mở chat phụ mới
    (mỗi lượt một chat phụ thì danh sách chat của người dùng ngập rác; dồn hết vào một chat thì ngữ
    cảnh cũ lẫn vào câu trả lời và trang nặng dần)
  * dựng prompt từ messages kiểu OpenAI, và dựng lời xin ảnh theo khung hình

Đo thật 2/10/2026 (hồ sơ chayagent): câu ngắn ~8 s cả mở tab; kịch bản JSON 3 cảnh ~10 s; ảnh 16:9 ra
2048×1152, 9:16 ra 1152×2048 (webp) trong ~25–30 s.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tubecli.muse")

PROVIDER = "muse"
CHAT_MODEL = "muse-spark"
IMAGE_MODEL = "muse-image"
CHAT_MODELS = [CHAT_MODEL]
IMAGE_MODELS = [IMAGE_MODEL]
DEFAULT_TURNS_PER_CHAT = 10
MAX_TURNS_PER_CHAT = 100
CHAT_TIMEOUT = 300
IMAGE_TIMEOUT = 300
# Chờ tới lượt (lượt khác đang chạy). Lô ảnh của Studio gửi song song: phải XẾP HÀNG, không được hỏng.
QUEUE_WAIT = 1800
LAUNCH_WAIT = 120
LAUNCH_SETTLE = 4
# Hồ sơ tự mở ẩn để phục vụ Muse sống tối đa chừng này (monitor của process_manager tự giết), lượt sau
# thấy nó tắt thì mở lại.
# Phiên ẩn sống tối đa chừng này giây. Từng là 1800 (30 phút): bộ quản lý trình duyệt GIẾT phiên đúng giờ dù đang quay
# clip dở («exceeded max duration (1800s). Force killing» → page closed → ECONNREFUSED → tài khoản bị bỏ qua 10 phút) —
# nguyên nhân gốc của chuỗi «trình duyệt Muse treo» 8–9/10/2026. Lô 30 clip × 3 tài khoản kéo dài hàng giờ ⇒ 6 giờ;
# phiên hỏng đã có reset_browser dọn.
HIDDEN_SESSION_MAX = 6 * 3600
ASPECTS = {"16:9": "landscape", "9:16": "vertical portrait", "1:1": "square",
           "4:3": "landscape", "3:4": "portrait"}

# Một tài khoản chạy song song tối đa chừng này lượt (mỗi lượt một chat phụ riêng). Mặc định 1: chưa đo Muse có
# chịu nhiều lượt cùng tài khoản không — muốn nhanh thì thêm TÀI KHOẢN (hồ sơ phụ), không thêm lượt.
MAX_LANES = 3
# Hồ sơ hỏng (trình duyệt không mở / chưa đăng nhập) bị bỏ qua chừng này giây, lượt đi sang tài khoản khác.
DOWN_SECONDS = 600
# Thử lại + dọn phiên (user 8/10/2026: «thêm cơ chế thử lại muse, clear phiên (giải phóng ram) xong mở lại, nếu 3 lần
# lỗi báo cho telegram»): trình duyệt treo/đóng (kind "browser") → giết cả cây tiến trình của hồ sơ, nghỉ RESET_WAIT, mở
# lại, thử lại — tối đa MUSE_ATTEMPTS lượt cho một yêu cầu; hết lượt (hay tài khoản chưa đăng nhập) → một dòng Telegram,
# tối đa mỗi ALERT_EVERY giây cho cùng lý do.
MUSE_ATTEMPTS = 3
RESET_WAIT = 6.0
ALERT_EVERY = 900
_ALERTED: Dict[str, float] = {}

# Chỗ ngồi: mỗi (hồ sơ, lượt) một khoá. User 5/10/2026: «có 3 tài khoản có thể tạo cùng lúc 3 ảnh cho nhanh hơn
# không?» — Studio vốn gửi 3 ảnh song song (DRAW_LANES) mà trước đây cả 3 xếp hàng sau MỘT _LOCK.
_POOL = threading.Condition()
_BUSY: Dict[str, str] = {}          # khoá chỗ ngồi → hồ sơ đang chạy ở đó
_LAST_USED: Dict[str, float] = {}
# NGƯỜI GÁC TREO (user 10/10/2026: «cơ chế xem lần tạo thành công gần nhất của profile, nếu lâu hơn 15 phút có nghĩa là
# trình duyệt đó bị treo và tự xoá phiên khởi động lại»): mỗi WATCH_EVERY giây, hồ sơ CỤC BỘ đang bận mà đã HANG_SECONDS
# không có lần thành công nào (tính từ lúc nhận lượt hoặc lần thành công gần nhất, cái nào muộn hơn) → đóng hẳn phiên
# (reset_browser); lượt đang dở nhận lỗi «browser» và ask() tự mở lại + thử lại như thường. Nút từ xa có người gác riêng.
HANG_SECONDS = 900
WATCH_EVERY = 60
_BUSY_SINCE: Dict[str, float] = {}  # khoá chỗ ngồi → lúc nhận lượt
_LAST_OK: Dict[str, float] = {}     # hồ sơ → lần tạo thành công gần nhất
_HUNG_RESET: Dict[str, float] = {}  # khoá chỗ ngồi → lúc người gác đã đóng phiên (một lần mỗi lượt)
_WATCHDOG: Dict[str, Any] = {"thread": None}
_DOWN: Dict[str, float] = {}        # hồ sơ → hết hạn bỏ qua
_THREAD_OWNER: Dict[str, str] = {}  # chat phụ → hồ sơ (chat của tài khoản A không mở được ở tài khoản B)
_STATE_LOCK = threading.Lock()


class MuseError(Exception):
    """kind: config | browser | auth | timeout | approval | refused | busy | error."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def is_muse_model(model) -> bool:
    """Model này của Muse? Nhận theo TÊN (như 9Router) — model mặc định của máy không mang provider."""
    return str(model or "").strip().lower().startswith("muse")


# ── cài đặt ───────────────────────────────────────────────────────────────────

def _clamp_turns(v) -> int:
    try:
        n = int(str(v if v is not None else "").strip() or DEFAULT_TURNS_PER_CHAT)
    except (TypeError, ValueError):
        return DEFAULT_TURNS_PER_CHAT
    return max(1, min(MAX_TURNS_PER_CHAT, n))


def _clamp_lanes(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_LANES, n))


MAX_REMOTE_SEATS = 6
REMOTE_PREFIX = "remote"
NODE_KEY_MIN = 16
REMOTE_POST_WAIT = 90      # giây chờ lượt POST video tới nút (dưới ngưỡng ~100 s của tunnel Cloudflare)
REMOTE_POLL = 5.0          # giây giữa hai lần hỏi GET /v1/videos/jobs/{id}


NODE_PATH = "/api/v1/muse"


def _node_url(raw: str) -> str:
    """Địa chỉ nút từ xa người dùng dán → URL đầy đủ tới /api/v1/muse, hoặc "" nếu không dùng được.

    9/10/2026 user dán `https://tungho2-23.tubecreate.com` (tên miền trần) — trước đây lõi gọi thẳng
    `<trần>/v1/chat/completions` → 404. Giờ: thiếu scheme → https (IP/localhost → http); không có đường dẫn
    (hoặc chỉ "/") → nối /api/v1/muse; đã có đường dẫn khác thì giữ nguyên (ví dụ reverse-proxy đổi tiền tố).
    """
    url = str(raw or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        host = url.split("/", 1)[0].split(":", 1)[0]
        local = host in ("localhost", "127.0.0.1") or re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host) is not None
        url = ("http://" if local else "https://") + url
    if not url.startswith(("http://", "https://")):
        return ""
    rest = url.split("://", 1)[1]
    if "/" not in rest:
        url = url + NODE_PATH
    return url


def _clean_remotes(raw) -> List[dict]:
    """[{base_url, key, seats}] — nút Muse từ xa (TubeCLI khác, như 9Router): base_url http(s) tới /api/v1/muse."""
    out: List[dict] = []
    for r in (raw if isinstance(raw, list) else []):
        if not isinstance(r, dict):
            continue
        url = _node_url(str(r.get("base_url") or r.get("url") or ""))
        if not url:
            continue
        try:
            seats = int(r.get("seats") or 1)
        except (TypeError, ValueError):
            seats = 1
        out.append({"base_url": url, "key": str(r.get("key") or "").strip(), "seats": max(1, min(MAX_REMOTE_SEATS, seats))})
    return out


def settings() -> dict:
    """{profile, extra_profiles, pool, lanes, turns_per_chat, remotes, node_key}. profile "" = chưa chọn hồ sơ nào.

    pool = hồ sơ chính + hồ sơ phụ (không trùng), theo thứ tự; chưa có hồ sơ chính thì pool rỗng.
    remotes = nút Muse từ xa (9/10/2026, «giống 9Router»): mỗi nút thêm `seats` chỗ ngồi vào bể."""
    try:
        from tubecli.config import read_global_settings
        g = read_global_settings()
    except Exception:      # noqa: BLE001
        g = {}
    profile = str(g.get("muse_profile") or "").strip()
    extra = g.get("muse_extra_profiles")
    pool = [profile] if profile else []
    for p in (extra if isinstance(extra, list) else []):
        p = str(p or "").strip()
        if profile and p and p not in pool:
            pool.append(p)
    return {"profile": profile, "extra_profiles": pool[1:], "pool": pool,
            "lanes": _clamp_lanes(g.get("muse_lanes")),
            "turns_per_chat": _clamp_turns(g.get("muse_turns_per_chat")),
            "remotes": _clean_remotes(g.get("muse_remotes")),
            "node_key": str(g.get("muse_node_key") or "").strip()}


def node_key_ok(authorization: Optional[str]) -> bool:
    """Máy khác gọi /api/v1/muse/v1/* với `Authorization: Bearer <muse_node_key>` của máy này (≥ NODE_KEY_MIN ký tự)."""
    import hmac
    key = settings().get("node_key") or ""
    tok = str(authorization or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    return bool(key) and len(key) >= NODE_KEY_MIN and bool(tok) and hmac.compare_digest(key, tok)


def _profiles_dir() -> str:
    from tubecli.extensions.browser.profile_manager import PROFILES_DIR
    return str(PROFILES_DIR)


def _check_profile(p: str) -> str:
    p = str(p or "").strip()
    if p and (p in (".", "..") or "/" in p or "\\" in p or not os.path.isdir(os.path.join(_profiles_dir(), p))):
        raise ValueError(f"Browser profile '{p}' does not exist on this machine.")
    return p


def set_settings(profile: Optional[str] = None, turns_per_chat: Optional[int] = None,
                 extra_profiles: Optional[List[str]] = None, lanes: Optional[int] = None,
                 remotes: Optional[List[dict]] = None, node_key: Optional[str] = None) -> dict:
    """Chỉ ghi khoá được truyền. Hồ sơ phải có thật (tên gõ sai = mọi lượt hỏng mà trông như đã cấu hình)."""
    from tubecli.config import set_global_setting
    if remotes is not None:
        set_global_setting("muse_remotes", _clean_remotes(remotes))
    if node_key is not None:
        nk = str(node_key).strip()
        if nk and len(nk) < NODE_KEY_MIN:
            raise ValueError(f"The node key must be at least {NODE_KEY_MIN} characters.")
        set_global_setting("muse_node_key", nk)
    if profile is not None:
        # Đổi hồ sơ = đổi tài khoản: pick_thread thấy state["profile"] khác nên tự mở chat phụ mới.
        set_global_setting("muse_profile", _check_profile(profile))
    if extra_profiles is not None:
        names: List[str] = []
        for p in extra_profiles:
            p = _check_profile(p)
            if p and p not in names:
                names.append(p)
        set_global_setting("muse_extra_profiles", names)
    if lanes is not None:
        set_global_setting("muse_lanes", _clamp_lanes(lanes))
    if turns_per_chat is not None:
        set_global_setting("muse_turns_per_chat", _clamp_turns(turns_per_chat))
    return settings()


def local_base_url() -> str:
    """Cổng chuẩn OpenAI do CHÍNH TubeCLI phục vụ (api/muse_routes.py) — cho chỗ nào chỉ biết nói kiểu
    OpenAI qua HTTP (Content Studio đọc PROVIDERS[...]["base_url"])."""
    try:
        from tubecli.config import get_api_port
        port = int(get_api_port())
    except Exception:      # noqa: BLE001
        port = 5295
    return f"http://127.0.0.1:{port}/api/v1/muse/v1"


# ── trạng thái chat phụ đang dùng ─────────────────────────────────────────────

def _state_file() -> str:
    from tubecli.config import DATA_DIR
    return os.path.join(str(DATA_DIR), "muse_state.json")


def _load_state() -> dict:
    try:
        with open(_state_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:      # noqa: BLE001
        return {}


def _save_state(d: dict) -> None:
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:      # noqa: BLE001
        logger.warning("muse: could not save chat state: %s", e)


def _slot_state(all_state: dict, key: str) -> dict:
    """Trạng thái chat phụ của MỘT chỗ ngồi. File cũ (một hồ sơ, dạng phẳng) vẫn đọc được: nó là chỗ của hồ sơ ấy."""
    slots = all_state.get("slots")
    if isinstance(slots, dict):
        s = slots.get(key)
        return s if isinstance(s, dict) else {}
    return all_state if all_state.get("profile") == key else {}


def _save_slot(key: str, slot: dict) -> None:
    with _STATE_LOCK:
        d = _load_state()
        slots = d.get("slots") if isinstance(d.get("slots"), dict) else (
            {d["profile"]: d} if d.get("profile") else {})
        slots[key] = slot
        _save_state({"slots": slots})


def pick_thread(state: dict, profile: str, turns_per_chat: int, fresh: bool = False) -> str:
    """"new" hay id chat phụ để gõ tiếp."""
    tid = str(state.get("thread") or "")
    if fresh or not tid or state.get("profile") != profile:
        return "new"
    if int(state.get("turns") or 0) >= turns_per_chat:
        return "new"
    return tid


def next_state(state: dict, profile: str, thread: str, result: dict) -> dict:
    """Trạng thái sau một lượt: chat phụ mới thì đếm lại từ 1."""
    tid = str(result.get("thread_id") or "")
    if not tid:
        return state
    if thread == "new" or tid != state.get("thread"):
        return {"profile": profile, "thread": tid, "turns": 1, "updated_at": int(time.time())}
    return {**state, "turns": int(state.get("turns") or 0) + 1, "updated_at": int(time.time())}


# ── trình duyệt ───────────────────────────────────────────────────────────────

def _tool_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "extensions", "browser", "muse_tool.cjs")


def _port_alive(port: int) -> bool:
    """Cổng này có Chromium thật đang nghe (GET /json/version) — cùng phép thử với browser/routes."""
    try:
        from tubecli.extensions.browser.routes import _cdp_alive
        return bool(_cdp_alive(int(port)))
    except Exception:      # noqa: BLE001
        return False


def _cdp_port_from_processes(profile: str) -> int:
    """Cổng CDP đọc từ CHÍNH dòng lệnh Chromium của hồ sơ này: tiến trình chính có `--user-data-dir=<hồ sơ>`
    và `--remote-debugging-port=N` (N = 0 là cổng ngẫu nhiên → xem cổng tiến trình ấy đang nghe), rồi gõ cửa
    /json/version.

    Vì sao cần: preview_cdp.json chỉ được tin khi pid khớp bản ghi trong RAM của server — server khởi động lại là
    mất dấu, lượt mở ẩn kế tiếp xoá luôn file ấy (_STALE_CDP_FILES) rồi mở TRÙNG hồ sơ đang chạy → «Failed to
    launch the browser process» và nút Thử vẽ báo hỏng trong khi trình duyệt vẫn sống (2/10/2026). Đường dẫn hồ
    sơ trong dòng lệnh là bằng chứng cổng thuộc đúng hồ sơ — không cần file nào.
    """
    try:
        import psutil
    except Exception:      # noqa: BLE001
        return 0
    target = os.path.normcase(os.path.realpath(os.path.join(_profiles_dir(), profile)))
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = list(p.info.get("cmdline") or [])
        except Exception:      # noqa: BLE001
            continue
        if not cmd or any(a.startswith("--type=") for a in cmd):
            continue        # renderer / gpu… — chỉ tiến trình chính mang cổng
        udd = next((a[len("--user-data-dir="):] for a in cmd if a.startswith("--user-data-dir=")), "")
        if not udd or os.path.normcase(os.path.realpath(udd.strip('"'))) != target:
            continue
        flag = next((a for a in cmd if a.startswith("--remote-debugging-port=")), "")
        try:
            port = int(flag.split("=", 1)[1]) if flag else 0
        except ValueError:
            port = 0
        if port and _port_alive(port):
            return port
        try:
            ports = sorted({c.laddr.port for c in p.net_connections(kind="tcp")
                            if c.status == "LISTEN" and c.laddr and c.laddr.port})
        except Exception:      # noqa: BLE001
            ports = []
        for cand in ports:
            if _port_alive(cand):
                return cand
    return 0


def _profile_processes(profile: str) -> list:
    """Mọi tiến trình Chromium (chính + renderer/gpu…) mang --user-data-dir của hồ sơ này."""
    try:
        import psutil
    except Exception:      # noqa: BLE001
        return []
    target = os.path.normcase(os.path.realpath(os.path.join(_profiles_dir(), profile)))
    out = []
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = list(p.info.get("cmdline") or [])
        except Exception:      # noqa: BLE001
            continue
        udd = next((a[len("--user-data-dir="):] for a in cmd if a.startswith("--user-data-dir=")), "")
        if udd and os.path.normcase(os.path.realpath(udd.strip('"'))) == target:
            out.append(p)
    return out


def reset_browser(profile: str) -> bool:
    """ĐÓNG HẲN phiên trình duyệt của hồ sơ — giết cả cây tiến trình (giải phóng RAM) để lượt sau mở lại sạch (user
    8/10/2026: «clear phiên (giải phóng ram) xong mở lại»). Qua sổ phiên của browser extension trước; phiên không có
    trong sổ (server đã khởi động lại, công cụ khác mở) thì giết theo --user-data-dir. True khi hồ sơ không còn tiến
    trình nào."""
    try:
        from tubecli.extensions.browser.process_manager import browser_process_manager
        browser_process_manager.stop_by_profile(profile)
    except Exception as e:      # noqa: BLE001
        logger.info("muse: process manager could not stop %s: %s", profile, e)
    procs = _profile_processes(profile)
    for p in procs:
        try:
            p.kill()
        except Exception:      # noqa: BLE001
            pass
    if procs:
        try:
            import psutil
            psutil.wait_procs(procs, timeout=5)
        except Exception:      # noqa: BLE001
            pass
    left = _profile_processes(profile)
    logger.warning("muse: browser session of %s closed — %d process(es) killed%s", profile, len(procs),
                   "" if not left else f", {len(left)} still alive")
    return not left


def _ask_remote(node: dict, prof: str, prompt: str, *, files=None, want_images=False, image_dir="", max_images=1,
                want_videos=False, video_dir="", max_videos=1, thread_id="", timeout=CHAT_TIMEOUT) -> dict:
    """Một lượt ở NÚT TỪ XA (TubeCLI khác, như 9Router): clip → POST /v1/videos/generations, ảnh → /v1/images/generations,
    chữ → /v1/chat/completions. File đính kèm gửi base64; clip/ảnh nhận về ghi ra video_dir/image_dir. Trả dict cùng
    dạng với muse_tool ({ok, text, images, videos, thread_id, profile}). Lỗi của nút ({error: {code}}) → MuseError cùng
    kind; không nối được → MuseError("browser") để lớp trên bỏ qua nút 10 phút rồi thử nút/tài khoản khác."""
    import urllib.request
    import urllib.error
    base = str(node.get("base_url") or "").rstrip("/")
    headers = {"Content-Type": "application/json", "User-Agent": "TubeCLI-muse-node/1",
               "Accept": "application/json"}
    if node.get("key"):
        headers["Authorization"] = f"Bearer {node['key']}"
    refs = []
    for p in list(files or [])[:3]:
        try:
            with open(str(p), "rb") as f:
                raw = f.read()
            mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
            refs.append(f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"))
        except OSError:
            continue
    # chat phụ của nút: id lưu ở đây là "<prof>:<id trên nút>"
    tid = str(thread_id or "")
    if tid.startswith(prof + ":"):
        tid = tid[len(prof) + 1:]
    if want_videos:
        # wait=false: nút trả {id} ngay rồi quay nền — tunnel Cloudflare cắt HTTP > ~100 s (524) mà clip mất 75–200 s.
        path, body = "/v1/videos/generations", {"prompt": prompt, "reference_images": refs, "thread_id": tid,
                                                 "timeout": int(timeout), "wait": False}
    elif want_images:
        path, body = "/v1/images/generations", {"prompt": prompt, "reference_images": refs, "thread_id": tid, "n": 1}
    else:
        path, body = "/v1/chat/completions", {"model": CHAT_MODEL, "messages": [{"role": "user", "content": prompt}]}

    def _http(method: str, url: str, payload=None, wait: int = 60) -> dict:
        req = urllib.request.Request(url, data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode("utf-8")).get("error") or {}
            except Exception:      # noqa: BLE001
                err = {}
            kind = str(err.get("code") or "")
            kind = kind if kind in ("config", "refused", "auth", "approval", "busy", "browser", "timeout", "error") else \
                ("auth" if e.code in (401, 403) else "browser")
            raise MuseError(kind, f"remote Muse node {base}: {err.get('message') or e}")
        except MuseError:
            raise
        except Exception as e:      # noqa: BLE001 — không nối được / hết giờ
            raise MuseError("browser", f"remote Muse node {base} unreachable: {str(e)[:160]}")

    # Lượt đầu: chat/ảnh chờ trọn; video chỉ chờ 90 s (nút mới trả id ngay; nút cũ trả clip luôn nếu kịp dưới 100 s).
    data = _http("POST", base + path, body, wait=REMOTE_POST_WAIT if want_videos else int(timeout) + 60)
    if want_videos and not data.get("data") and data.get("id"):
        job, deadline = str(data["id"]), time.time() + int(timeout) + 60
        while True:
            if time.time() > deadline:
                raise MuseError("timeout", f"remote Muse node {base}: video job {job} did not finish within {int(timeout) + 60} s")
            time.sleep(REMOTE_POLL)
            data = _http("GET", f"{base}/v1/videos/jobs/{job}", None, wait=60)
            if data.get("status") != "running":
                break
    out = {"ok": True, "text": "", "images": [], "videos": [], "profile": prof}
    rows = data.get("data") or []
    if want_videos:
        os.makedirs(video_dir or ".", exist_ok=True)
        for i, row in enumerate(rows[:max(1, max_videos)]):
            b64 = row.get("b64_json")
            if not b64:
                continue
            p = os.path.join(video_dir or ".", f"muse_remote_{int(time.time())}_{i}.mp4")
            with open(p, "wb") as f:
                f.write(base64.b64decode(b64))
            out["videos"].append({"path": p, "poster": "", "width": row.get("width"), "height": row.get("height"),
                                  "duration": row.get("duration")})
            if row.get("thread_id"):
                out["thread_id"] = f"{prof}:{row['thread_id']}"
    elif want_images:
        os.makedirs(image_dir or ".", exist_ok=True)
        for i, row in enumerate(rows[:max(1, max_images)]):
            b64 = row.get("b64_json")
            if not b64:
                continue
            p = os.path.join(image_dir or ".", f"muse_remote_{int(time.time())}_{i}.jpg")
            with open(p, "wb") as f:
                f.write(base64.b64decode(b64))
            out["images"].append({"path": p})
    else:
        ch = (data.get("choices") or [{}])[0]
        out["text"] = str(((ch.get("message") or {}).get("content")) or "")
    return out


def _telegram_target() -> tuple:
    """(bot token, chat id) từ cài đặt chung — cùng nguồn Codex dùng để báo task xong."""
    try:
        from tubecli.config import read_global_settings
        data = read_global_settings() or {}
        return str(data.get("telegram_bot_token") or ""), str(data.get("telegram_chat_id") or "")
    except Exception:      # noqa: BLE001
        return "", ""


def _alert(reason: str, text: str) -> bool:
    """Một dòng Telegram cho người vận hành — tối đa mỗi ALERT_EVERY giây cho cùng `reason`. True khi đã gửi."""
    now = time.time()
    if now - _ALERTED.get(reason, 0) < ALERT_EVERY:
        return False
    token, chat_id = _telegram_target()
    if not token or not chat_id:
        logger.warning("muse: no Telegram bot/chat configured — alert not sent: %s", text)
        return False
    _ALERTED[reason] = now
    try:
        from tubecli.extensions.codex.telegram import notify_fire_and_forget
        notify_fire_and_forget(token, chat_id, text)
        return True
    except Exception as e:      # noqa: BLE001
        logger.warning("muse: Telegram alert failed: %s", e)
        return False


def _alert_text(err: "MuseError", profile: str, attempts: int) -> str:
    if err.kind == "browser":
        return (f"⚠️ Muse: the browser of account «{profile}» failed {attempts} times in a row — its session was closed "
                f"and reopened each time ({str(err)[:160]}). Image and video requests will keep failing until it is "
                f"fixed: open Settings → Muse → Test.")
    if err.kind == "auth":
        return (f"⚠️ Muse: account «{profile}» is not signed in to muse.ai ({str(err)[:160]}). Sign in again in that "
                f"browser profile.")
    return f"⚠️ Muse: {err.kind} — {str(err)[:200]}"


def _cdp_port(profile: str) -> int:
    try:
        from tubecli.extensions.browser.routes import _live_cdp_port
        port = int(_live_cdp_port(profile) or 0)
        if port:
            return port
    except Exception as e:      # noqa: BLE001
        logger.info("muse: cannot read the CDP port of %s: %s", profile, e)
    return _cdp_port_from_processes(profile)


def _launch_hidden(profile: str) -> None:
    """Mở hồ sơ ẨN ở muse.ai (cùng lối với youtube_cookies.refresh_attempt) — ném MuseError nếu không được."""
    try:
        from tubecli.extensions.browser.routes import _is_launching, is_profile_running, launch_refusal
        from tubecli.extensions.browser.process_manager import browser_process_manager
    except Exception as e:      # noqa: BLE001
        raise MuseError("browser", f"The browser extension is unavailable ({e}).")
    ref = launch_refusal(profile)
    if ref:
        raise MuseError("browser", f"Cannot open browser profile '{profile}': "
                                   f"{ref.get('message') or ref.get('code') or 'blocked'}")
    if _is_launching(profile) or is_profile_running(profile):
        return ""                       # đang mở dở — chỉ việc chờ cổng CDP
    logger.info("muse: opening browser profile %s in the background", profile)
    res = browser_process_manager.spawn(profile=profile, url="https://muse.ai/", headless=True, manual=True,
                                        max_duration=HIDDEN_SESSION_MAX)
    if not isinstance(res, dict) or res.get("status") == "error":
        raise MuseError("browser", f"Could not open browser profile '{profile}' "
                                   f"({(res or {}).get('error') or 'launch failed'}).")
    return str(res.get("instance_id") or "")


def _instance_status(instance_id: str) -> Optional[dict]:
    try:
        from tubecli.extensions.browser.process_manager import browser_process_manager
        return browser_process_manager.get_status(instance_id)
    except Exception:      # noqa: BLE001
        return None


def ensure_browser(profile: str, launch: bool = True, sleep=time.sleep) -> int:
    """Cổng CDP của phiên đang chạy; tắt thì mở ẩn rồi chờ (launch=True). Tiến trình mở ẩn chết sớm (hồ sơ đang
    bị một Chromium khác giữ, thiếu RAM…) → báo ngay lý do, không ngồi đợi hết LAUNCH_WAIT."""
    port = _cdp_port(profile)
    if port or not launch:
        if not port:
            raise MuseError("browser", f"Browser profile '{profile}' is not running.")
        return port
    inst = _launch_hidden(profile)
    deadline = time.time() + LAUNCH_WAIT
    while time.time() < deadline:
        port = _cdp_port(profile)
        if port:
            sleep(LAUNCH_SETTLE)        # muse.ai đang nạp trong tab đầu — cho nó chạy xong
            return port
        if inst:
            cur = _instance_status(inst)
            if cur and cur.get("status") not in (None, "running", "starting"):
                why = cur.get("error") or cur.get("message") or cur.get("status")
                raise MuseError("browser", f"Browser profile '{profile}' closed before it was ready ({why}).")
        sleep(1.5)
    raise MuseError("browser", f"Browser profile '{profile}' did not become ready within {LAUNCH_WAIT} s.")


def run_tool(port: int, action: str, req: Optional[dict] = None, timeout: int = 60) -> dict:
    """Chạy muse_tool.cjs, trả JSON nó in giữa hai dấu. Không bao giờ trả None."""
    from tubecli.core import proc as _proc
    args = ["node", _tool_path(), "--cdp", str(int(port)), "--action", action]
    tmp = None
    if req is not None:
        fd, tmp = tempfile.mkstemp(prefix="muse_req_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False)
        args += ["--in", tmp]
    # Đầu ra vào FILE tạm, không qua ống: subprocess.run(capture_output, timeout) trên Windows, khi quá hạn, giết node
    # rồi communicate() KHÔNG hạn để gom ống — có tiến trình nào giữ đầu ống là chờ mãi (Pod Studio #160 đêm 2/10/2026:
    # clip 3 treo 7,5 giờ dù hạn 645 s). File thì không có gì để chờ; quá hạn → giết cả cây tiến trình.
    out_fd, out_path = tempfile.mkstemp(prefix="muse_out_", suffix=".txt")
    err_fd, err_path = tempfile.mkstemp(prefix="muse_err_", suffix=".txt")
    p = None
    try:
        with os.fdopen(out_fd, "wb") as out_f, os.fdopen(err_fd, "wb") as err_f:
            try:
                p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f, **_proc.hidden_kwargs())
            except FileNotFoundError:
                return {"ok": False, "kind": "browser", "error": "Node.js is not installed — the Muse driver needs it."}
            try:
                p.wait(timeout=timeout + 45)
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                return {"ok": False, "kind": "timeout", "error": f"Muse did not answer within {timeout} s."}
        return parse_tool_output(_read_text(out_path), _read_text(err_path))
    finally:
        for f in (tmp, out_path, err_path):
            if f:
                try:
                    os.remove(f)
                except OSError:
                    pass


def _read_text(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _kill_tree(p: "subprocess.Popen") -> None:
    """Giết tiến trình driver và mọi tiến trình con của nó, chờ tối đa 10 s — không bao giờ treo ở đây."""
    try:
        import psutil
        for c in psutil.Process(p.pid).children(recursive=True):
            try:
                c.kill()
            except Exception:      # noqa: BLE001
                pass
    except Exception:      # noqa: BLE001
        pass
    try:
        p.kill()
        p.wait(timeout=10)
    except Exception:      # noqa: BLE001
        pass


def parse_tool_output(stdout: str, stderr: str = "") -> dict:
    m = re.search(r"__MUSE_RESULT__(.*?)__MUSE_END__", stdout or "", re.S)
    if not m:
        why = (stderr or stdout or "").strip().splitlines()
        return {"ok": False, "kind": "error", "error": "Muse driver failed: " + (why[-1] if why else "no output")[:300]}
    try:
        d = json.loads(m.group(1))
    except ValueError as e:
        return {"ok": False, "kind": "error", "error": f"Muse driver returned bad JSON: {e}"}
    return d if isinstance(d, dict) else {"ok": False, "kind": "error", "error": "Muse driver returned no object"}


# ── trạng thái + một lượt hỏi ─────────────────────────────────────────────────

def _profile_status(profile: str, busy: bool) -> dict:
    """Trạng thái MỘT hồ sơ: {profile, running, logged_in, verified, busy, message}. Không mở trình duyệt."""
    out = {"profile": profile, "running": False, "logged_in": None, "verified": False, "busy": busy, "message": ""}
    port = _cdp_port(profile)
    if not port:
        # Tắt KHÔNG phải hỏng: lượt hỏi đầu tiên tự mở nó ẩn.
        out["message"] = f"Browser profile '{profile}' is closed — it opens in the background on the first request."
        return out
    out["running"] = True
    if busy:
        out["message"] = "Muse is answering another request."
        return out
    res = run_tool(port, "status", timeout=20)
    if res.get("ok"):
        out["logged_in"] = bool(res.get("logged_in"))
        out["verified"] = bool(res.get("verified"))
        if not out["logged_in"]:
            out["message"] = f"Browser profile '{profile}' is not signed in to muse.ai — open it and sign in."
    else:
        out["message"] = str(res.get("error") or "status check failed")
    return out


def _busy_by_profile() -> Dict[str, int]:
    with _POOL:
        out: Dict[str, int] = {}
        for p in _BUSY.values():
            out[p] = out.get(p, 0) + 1
        return out


def status() -> dict:
    """Không mở trình duyệt, không gõ gì: {configured, profile, running, logged_in, verified, message, pool[…]}.

    Các trường cấp ngoài là của hồ sơ CHÍNH (như trước); `pool` có một dòng cho mỗi tài khoản."""
    st = settings()
    profile = st["profile"]
    remotes = st.get("remotes") or []
    busy_by = _busy_by_profile()
    remote_seats = sum(int(r.get("seats") or 1) for r in remotes)
    seats = len(st["pool"]) * st["lanes"] + remote_seats
    # configured = có hồ sơ ở máy này HOẶC có nút từ xa (chỉ-remote vẫn là đã cấu hình, 9/10/2026)
    out = {"provider": PROVIDER, "configured": bool(profile) or bool(remotes), "profile": profile,
           "extra_profiles": st["extra_profiles"], "lanes": st["lanes"],
           "turns_per_chat": st["turns_per_chat"], "running": False, "logged_in": None, "verified": False,
           "models": CHAT_MODELS, "image_models": IMAGE_MODELS,
           "remote_nodes": len(remotes), "remote_seats": remote_seats, "remote_only": bool(remotes) and not profile,
           "busy": bool(seats) and sum(busy_by.values()) >= seats, "message": "", "pool": []}
    slot = _slot_state(_load_state(), profile) if profile else {}
    if slot.get("thread"):
        out["thread"] = slot.get("thread")
        out["thread_turns"] = int(slot.get("turns") or 0)
    if not profile:
        out["message"] = (f"No browser profile on this machine — using {len(remotes)} remote Muse node(s), {remote_seats} seat(s)."
                          if remotes else "Pick the browser profile that is signed in to muse.ai, or add a remote Muse node.")
        return out
    now = time.time()
    for p in st["pool"]:
        row = _profile_status(p, busy_by.get(p, 0) >= st["lanes"])
        row["down"] = _DOWN.get(p, 0) > now
        row["last_used"] = _LAST_USED.get(p) or None      # epoch giây — hộp cài đặt hiện «used 2 min ago»
        row["last_ok"] = _LAST_OK.get(p) or None          # lần tạo thành công gần nhất (người gác treo dựa vào nó)
        with _POOL:
            since = [_BUSY_SINCE.get(k, now) for k, q in _BUSY.items() if q == p]
        row["busy_for"] = int(now - min(since)) if since else 0
        out["pool"].append(row)
    first = out["pool"][0]
    out.update(running=first["running"], logged_in=first["logged_in"], verified=first["verified"],
               message=first["message"])
    return out


def _acquire(pool: List[str], lanes: int, want: str = "", timeout: float = QUEUE_WAIT,
             remotes: Optional[List[dict]] = None):
    """Giữ MỘT chỗ ngồi → (hồ sơ, khoá chỗ). Chọn tài khoản ít lượt đang chạy nhất, rồi lâu chưa dùng nhất — các
    lượt xoay vòng qua mọi tài khoản. Tài khoản đang hỏng (_DOWN) bị bỏ qua, trừ khi tài khoản nào cũng hỏng.
    want: chat phụ của tài khoản nào thì PHẢI chạy ở tài khoản đó.
    remotes: nút Muse từ xa — mỗi nút là một «tài khoản» tên remote<i> với `seats` chỗ ngồi (9/10/2026)."""
    seats: Dict[str, int] = {p: max(1, lanes) for p in pool}
    names = list(pool)
    for i, r in enumerate(remotes or []):
        nm = f"{REMOTE_PREFIX}{i}"
        names.append(nm)
        seats[nm] = max(1, int(r.get("seats") or 1))
    deadline = time.time() + timeout
    with _POOL:
        while True:
            now = time.time()
            live = [want] if want else ([p for p in names if _DOWN.get(p, 0) <= now] or list(names))
            load: Dict[str, int] = {}
            for p in _BUSY.values():
                load[p] = load.get(p, 0) + 1
            free = []
            for p in live:
                for i in range(seats.get(p, max(1, lanes))):
                    k = p if i == 0 else f"{p}#{i + 1}"
                    if k not in _BUSY:
                        free.append((load.get(p, 0), _LAST_USED.get(p, 0.0), k, p))
            if free:
                free.sort()
                _, _, k, p = free[0]
                _BUSY[k] = p
                _BUSY_SINCE[k] = now
                _LAST_USED[p] = now
                _start_watchdog()
                return p, k
            left = deadline - now
            if left <= 0:
                raise MuseError("busy", "Muse has been busy with other requests for too long.")
            _POOL.wait(min(left, 5))


def _release(key: str) -> None:
    with _POOL:
        _BUSY.pop(key, None)
        _BUSY_SINCE.pop(key, None)
        _HUNG_RESET.pop(key, None)
        _POOL.notify_all()


def _watch_once(now: Optional[float] = None) -> List[str]:
    """Một vòng người gác: trả các hồ sơ vừa bị đóng phiên vì treo. Gọi được trong test."""
    now = time.time() if now is None else now
    with _POOL:
        busy = [(k, p, _BUSY_SINCE.get(k, now)) for k, p in _BUSY.items()]
    hung: List[str] = []
    for k, p, since in busy:
        if p.startswith(REMOTE_PREFIX) or k in _HUNG_RESET:
            continue
        ref = max(since, _LAST_OK.get(p, 0.0))
        if now - ref <= HANG_SECONDS:
            continue
        with _POOL:
            if _BUSY.get(k) != p or k in _HUNG_RESET:      # lượt vừa xong / người gác khác đã xử lý
                continue
            _HUNG_RESET[k] = now
        mins = int((now - ref) // 60)
        logger.warning("muse watchdog: %s busy %d min with no successful generation — closing its browser session", p, mins)
        try:
            reset_browser(p)
        except Exception as e:      # noqa: BLE001
            logger.warning("muse watchdog: reset of %s failed: %s", p, e)
        _alert(f"hang:{p}", f"⚠️ Muse: browser profile «{p}» was stuck {mins} min with no successful generation — "
                            f"its session was closed and the request is being retried.")
        if p not in hung:
            hung.append(p)
    return hung


def _watch_loop() -> None:
    while True:
        time.sleep(WATCH_EVERY)
        try:
            _watch_once()
        except Exception as e:      # noqa: BLE001
            logger.warning("muse watchdog: %s", e)


def _start_watchdog() -> None:
    """Bật người gác MỘT lần (gọi trong _acquire, đang giữ _POOL)."""
    t = _WATCHDOG.get("thread")
    if t is not None and t.is_alive():
        return
    t = threading.Thread(target=_watch_loop, name="muse-watchdog", daemon=True)
    _WATCHDOG["thread"] = t
    t.start()


def ask(prompt: str, *, want_images: bool = False, files: Optional[List[str]] = None,
        image_dir: str = "", max_images: int = 1, timeout: int = CHAT_TIMEOUT, fresh: bool = False,
        launch: bool = True, want_videos: bool = False, video_dir: str = "", max_videos: int = 1,
        thread_id: str = "", _failover: bool = True, _attempt: int = 1) -> dict:
    """Một lượt hỏi Muse → kết quả của muse_tool (text, images, videos, thread_id, profile…). Ném MuseError.

    thread_id: gõ vào ĐÚNG chat phụ này (chuỗi clip nối tiếp phải ở cùng một chat để Muse giữ mạch), bỏ qua
    chat phụ dùng chung; "" = chat phụ dùng chung như thường. Chat phụ thuộc về tài khoản đã mở nó.
    Trình duyệt treo/đóng: ĐÓNG HẲN phiên (giải phóng RAM), nghỉ, mở lại, thử lại — tối đa MUSE_ATTEMPTS lượt, tài khoản
    vừa hỏng bị bỏ qua DOWN_SECONDS nên lượt sau thường rơi vào tài khoản khác; hết lượt → Telegram + MuseError.
    Lượt quá hạn (timeout) không ra gì: cũng đóng hẳn phiên rồi thử lại (chat mới), tối đa MUSE_ATTEMPTS lượt.
    Chưa đăng nhập: bỏ qua tài khoản ấy và thử lại MỘT lần ở tài khoản khác; hết → Telegram + MuseError."""
    st = settings()
    profile = st["profile"]
    pool = st["pool"]
    remotes = st.get("remotes") or []
    # CHỈ nút từ xa, không hồ sơ nào ở máy này (9/10/2026 user: «người dùng chỉ remote mà không dùng browser local»)
    # → vẫn chạy: bể cục bộ rỗng, mọi chỗ ngồi là remote<i>.
    if not profile and not remotes:
        raise MuseError("config", "Muse is not set up: pick the browser profile that is signed in to muse.ai "
                                  "in Cloud API Keys → Muse, or add a remote Muse node.")
    own = bool(thread_id)
    pinned = own and thread_id != "new"
    want = (_THREAD_OWNER.get(thread_id) or profile) if pinned else ""
    if want and want not in pool and not (want.startswith(REMOTE_PREFIX) and want in {f"{REMOTE_PREFIX}{i}" for i in range(len(remotes))}):
        want = ""
    prof, key = _acquire(pool, st["lanes"], want, remotes=remotes) if remotes else _acquire(pool, st["lanes"], want)
    failed: Optional[MuseError] = None
    if prof.startswith(REMOTE_PREFIX):
        # Chỗ ngồi TỪ XA (9/10/2026 «giống 9Router»): gọi HTTP tới nút, không có trình duyệt ở đây
        try:
            node = remotes[int(prof[len(REMOTE_PREFIX):])]
            res = _ask_remote(node, prof, prompt, files=files, want_images=want_images, image_dir=image_dir,
                              max_images=max_images, want_videos=want_videos, video_dir=video_dir,
                              max_videos=max_videos, thread_id=thread_id, timeout=timeout)
            if res.get("thread_id"):
                _THREAD_OWNER[str(res["thread_id"])] = prof
            _DOWN.pop(prof, None)
            _LAST_OK[prof] = time.time()
            _release(key)
            return res
        except MuseError as e:
            failed = e
            _release(key)
    else:
      try:
        port = ensure_browser(prof, launch=launch)
        slot = _slot_state(_load_state(), key)
        thread = thread_id if own else pick_thread(slot, prof, st["turns_per_chat"], fresh)
        req = {"prompt": prompt, "thread": thread, "timeout_ms": int(timeout * 1000),
               "want_images": bool(want_images), "max_images": int(max_images or 1),
               "image_dir": image_dir or "", "files": list(files or []),
               "want_videos": bool(want_videos), "max_videos": int(max_videos or 1), "video_dir": video_dir or ""}
        res = run_tool(port, "ask", req, timeout=timeout)
        if res.get("tabs_closed"):
            logger.info("muse: closed %s leftover tab(s) of %s before this request", res.get("tabs_closed"), prof)
        if not res.get("ok") and thread != "new" and not own and res.get("kind") == "error" and not res.get("thread_id"):
            # Chat phụ đã bị xoá / không mở được → mở chat phụ mới, MỘT lần.
            logger.warning("muse: chat %s unusable (%s) — starting a new one", thread, res.get("error"))
            thread, req["thread"] = "new", "new"
            res = run_tool(port, "ask", req, timeout=timeout)
        if not own:
            _save_slot(key, next_state(slot if thread != "new" else {}, prof, thread, res))
        if res.get("thread_id"):
            _THREAD_OWNER[str(res["thread_id"])] = prof
        if not res.get("ok"):
            raise MuseError(str(res.get("kind") or "error"), str(res.get("error") or "Muse request failed."))
        _DOWN.pop(prof, None)
        _LAST_OK[prof] = time.time()
        res["profile"] = prof
        return res
      except MuseError as e:
        failed = e
      finally:
        _release(key)
    if failed.kind in ("browser", "auth") and (len(pool) + len(remotes)) > 1:
        _DOWN[prof] = time.time() + DOWN_SECONDS
    if failed.kind == "browser" and launch and _attempt < MUSE_ATTEMPTS:
        # Trình duyệt treo/đóng («cannot attach to the browser on CDP port…» — 8/10/2026 làm #302/#306 mất clip): ĐÓNG
        # HẲN phiên của hồ sơ (giải phóng RAM), nghỉ, rồi thử lại — ensure_browser mở lại; tài khoản vừa hỏng bị bỏ qua
        # nên lượt sau ưu tiên tài khoản khác (chat riêng ghim tài khoản thì vẫn tài khoản ấy).
        logger.warning("muse: browser of %s unusable (%s) — closing its session and retrying (%d/%d)",
                       prof, failed, _attempt, MUSE_ATTEMPTS)
        reset_browser(prof)
        time.sleep(RESET_WAIT)
        return ask(prompt, want_images=want_images, files=files, image_dir=image_dir, max_images=max_images,
                   timeout=timeout, fresh=fresh, launch=launch, want_videos=want_videos, video_dir=video_dir,
                   max_videos=max_videos, thread_id=thread_id, _failover=_failover, _attempt=_attempt + 1)
    if failed.kind == "auth" and len(pool) > 1 and _failover and not pinned:
        logger.warning("muse: account %s unusable (%s) — trying another account", prof, failed)
        return ask(prompt, want_images=want_images, files=files, image_dir=image_dir, max_images=max_images,
                   timeout=timeout, fresh=fresh, launch=launch, want_videos=want_videos, video_dir=video_dir,
                   max_videos=max_videos, thread_id=thread_id, _failover=False, _attempt=_attempt)
    if failed.kind == "timeout" and launch and _attempt < MUSE_ATTEMPTS:
        # Lượt treo quá hạn (video 15 phút, chữ/ảnh 5 phút) mà không ra gì: phiên có thể kẹt → ĐÓNG HẲN phiên (dọn RAM),
        # mở lại, thử lại trong chat MỚI (chat riêng ghim tài khoản thì giữ chat) — user 9/10/2026: «sau 15 phút thử không
        # thành công thì reset phiên chứ» (thay cho giết phiên theo đồng hồ 30 phút). Tài khoản vừa treo không bị bỏ qua.
        logger.warning("muse: %s did not finish within %s s — resetting its session and retrying (%d/%d)",
                       prof, timeout, _attempt, MUSE_ATTEMPTS)
        reset_browser(prof)
        time.sleep(RESET_WAIT)
        return ask(prompt, want_images=want_images, files=files, image_dir=image_dir, max_images=max_images,
                   timeout=timeout, fresh=(fresh or not own), launch=launch, want_videos=want_videos, video_dir=video_dir,
                   max_videos=max_videos, thread_id=thread_id, _failover=_failover, _attempt=_attempt + 1)
    if (failed.kind == "browser" and launch) or failed.kind == "auth":
        # hết đường thử lại — báo người vận hành (user 8/10/2026: «nếu 3 lần lỗi báo cho telegram»)
        _alert(f"{failed.kind}:{prof}", _alert_text(failed, prof, _attempt))
    raise failed


# ── chat kiểu OpenAI ──────────────────────────────────────────────────────────

def text_of(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for p in content:
            if isinstance(p, str):
                bits.append(p)
            elif isinstance(p, dict) and p.get("type") in (None, "text", "input_text"):
                bits.append(str(p.get("text") or p.get("content") or ""))
        return "\n".join(b for b in bits if b)
    return str(content)


def images_of(messages: List[Dict], folder: str) -> List[str]:
    """Ảnh data: URI trong content kiểu OpenAI (image_url) → file tạm để đính vào ô soạn của Muse."""
    out = []
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for p in content:
            if not isinstance(p, dict) or p.get("type") not in ("image_url", "input_image"):
                continue
            url = p.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            mm = re.match(r"^data:image/(\w+);base64,(.+)$", str(url or ""), re.S)
            if not mm:
                continue
            ext = {"jpeg": "jpg"}.get(mm.group(1).lower(), mm.group(1).lower())
            path = os.path.join(folder, f"ref_{len(out)}.{ext}")
            with open(path, "wb") as f:
                f.write(base64.b64decode(mm.group(2)))
            out.append(path)
    return out


def build_prompt(messages: List[Dict]) -> str:
    """messages kiểu OpenAI → MỘT tin gửi Muse.

    Muse giữ hội thoại của chính nó, và chat phụ được dùng lại nhiều lượt — nên câu mở đầu nói rõ đây
    là yêu cầu độc lập. Các lượt trước (nếu có) đi kèm như NGỮ CẢNH, không giả làm bản ghi hội thoại:
    Muse-Chat-MCP đo được nhãn kiểu "### USER / ### ASSISTANT" làm Muse gạt đi là "bản ghi giả".
    """
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    system = "\n\n".join(text_of(m.get("content")) for m in msgs if m.get("role") in ("system", "developer"))
    rest = [m for m in msgs if m.get("role") not in ("system", "developer")]
    last_i = max((i for i, m in enumerate(rest) if m.get("role") in ("user", "tool")), default=-1)
    request = text_of(rest[last_i].get("content")) if last_i >= 0 else ""
    earlier = rest[:last_i] if last_i > 0 else []
    parts = ["[New independent request — answer only this message; ignore anything earlier in this chat.]"]
    if system.strip():
        parts.append("Instructions:\n" + system.strip())
    if earlier:
        lines = []
        for m in earlier:
            t = text_of(m.get("content")).strip()
            if t:
                who = "Assistant" if m.get("role") == "assistant" else "User"
                lines.append(f"{who} said: {t}")
        if lines:
            parts.append("Earlier messages, for context only:\n" + "\n\n".join(lines))
    parts.append(("Request:\n" if len(parts) > 1 else "") + request.strip())
    return "\n\n".join(p for p in parts if p.strip())


def chat_completion(messages: List[Dict], model: str = CHAT_MODEL, timeout: int = CHAT_TIMEOUT) -> str:
    """Câu trả lời chữ của Muse. Ném MuseError."""
    with tempfile.TemporaryDirectory(prefix="muse_in_") as tmp:
        refs = images_of(messages, tmp)
        prompt = build_prompt(messages)
        if not prompt.strip() and not refs:
            raise MuseError("error", "The request has no text.")
        res = ask(prompt, files=refs, timeout=timeout)
    text = str(res.get("text") or "").strip()
    if not text:
        raise MuseError("error", "Muse returned an empty reply.")
    return text


# ── vẽ ảnh ────────────────────────────────────────────────────────────────────

def image_request(prompt: str, aspect_ratio: str = "16:9", with_refs: bool = False) -> str:
    """Lời xin MỘT ảnh: khung hình nói bằng chữ (Muse không có tham số kích thước — 16:9 ra 2048×1152)."""
    ar = aspect_ratio if aspect_ratio in ASPECTS else "16:9"
    lines = [
        "Generate exactly ONE image now. Do not ask questions, do not explain, and do not write anything "
        "in your reply — reply with the image only.",
        f"Aspect ratio: {ar} ({ASPECTS[ar]}).",
        "Do not put any words, letters, captions, logos or watermarks inside the image unless the description "
        "below explicitly asks for them.",
    ]
    if with_refs:
        lines.append("Use the attached image(s) as the visual reference for the characters and style.")
    lines.append("")
    lines.append("Image description:")
    lines.append(str(prompt or "").strip())
    return "\n".join(lines)


# Muse trả lời bằng chữ thay cho ảnh: chỉ là TỪ CHỐI khi câu chữ nói vậy (bộ vẽ không lùi sang nhà khác với lời
# từ chối nội dung). Hỏi lại / tán chuyện thì là lỗi thường — lô ảnh còn đường lùi.
_REFUSAL_RE = re.compile(r"\b(can'?t|cannot|unable to|won'?t|not able to|sorry|policy|policies|guidelines|"
                         r"not allowed|inappropriate)\b|không thể|xin lỗi|chính sách", re.I)
# Câu BÁO LỖI của chính Muse ("Xin lỗi, tôi đã gặp vấn đề khi phản hồi. Vui lòng thử lại." — Pod Studio #160, 2/10/2026;
# "the generation service is temporarily unavailable") cũng có «xin lỗi»/«sorry» → phải là lỗi THƯỜNG (gọi lại được),
# không phải từ chối nội dung.
_TRANSIENT_RE = re.compile(r"gặp vấn đề|vui lòng thử lại|đã xảy ra lỗi|try again|temporarily unavailable|"
                           r"something went wrong|an error occurred|ran into a problem|technical (?:issue|problem)", re.I)


def _no_output_kind(said: str) -> str:
    """Muse trả chữ thay cho ảnh/video → 'refused' chỉ khi là lời từ chối nội dung; lỗi hệ thống hay tán chuyện → 'error'."""
    if _TRANSIENT_RE.search(said or ""):
        return "error"
    return "refused" if _REFUSAL_RE.search(said or "") else "error"


def _to_jpeg(data: bytes) -> bytes:
    """webp của Muse → JPEG: khâu dựng video (canvas Node, ffmpeg cũ) và tên file .jpg của Studio đều
    chắc ăn với JPEG. Không có PIL thì trả nguyên."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im2 = bg
            else:
                im2 = im.convert("RGB")
            buf = io.BytesIO()
            im2.save(buf, "JPEG", quality=93)
            return buf.getvalue()
    except Exception as e:      # noqa: BLE001
        logger.info("muse: keeping the original image bytes (%s)", e)
        return data


# Băm các ảnh Muse đã gửi trong từng chat phụ (giữ THREAD_IMAGES_KEEP ảnh cuối mỗi chat).
_THREAD_IMAGES: Dict[str, List[str]] = {}
THREAD_IMAGES_KEEP = 40


def generate_image_bytes(prompt: str, aspect_ratio: str = "16:9", reference_images: Optional[list] = None,
                         timeout: int = IMAGE_TIMEOUT, thread_id: str = "") -> bytes:
    """Bytes JPEG của MỘT ảnh Muse vẽ. Ném MuseError (kind refused khi Muse trả lời bằng chữ).
    thread_id="new": vẽ trong chat MỚI — thử lại sau một lần từ chối phải đi chat mới, chat cũ nhớ lời từ chối (#164).

    Muse GỬI LẠI ảnh cũ của chat thay vì vẽ mới khi lời xin mơ hồ (5/10/2026: #275 có 11 tấm trùng từng byte, nhịp
    27 = nhịp 26, nhịp 1 vẽ lại = nhịp 149 — prompt chỉ là câu lời đọc). Ảnh trùng một ảnh chat ấy đã gửi ⇒ vẽ lại
    MỘT lần trong chat mới; vẫn trùng thì báo lỗi (thà thiếu tranh còn hơn tranh của nhịp khác)."""
    import hashlib
    refs = [p for p in (reference_images or []) if p and os.path.isfile(str(p))][:3]
    for attempt in range(2):
        with tempfile.TemporaryDirectory(prefix="muse_img_") as tmp:
            res = ask(image_request(prompt, aspect_ratio, bool(refs)), want_images=True, files=refs,
                      image_dir=tmp, max_images=1, timeout=timeout, thread_id=thread_id)
            imgs = [i for i in (res.get("images") or []) if isinstance(i, dict) and i.get("path")]
            if not imgs:
                said = " ".join(str(res.get("text") or "").split())[:240]
                raise MuseError(_no_output_kind(said), f"Muse did not draw an image{': ' + said if said else '.'}")
            with open(imgs[0]["path"], "rb") as f:
                data = f.read()
        digest = hashlib.sha1(data).hexdigest()
        tid = str(res.get("thread_id") or "")
        sent = _THREAD_IMAGES.setdefault(tid, []) if tid else []
        if digest in sent:
            if attempt == 0:
                logger.warning("muse: chat %s sent back an image it had already sent — drawing again in a new chat", tid)
                thread_id = "new"
                continue
            raise MuseError("error", "Muse sent back an earlier image instead of drawing a new one.")
        if tid:
            sent.append(digest)
            del sent[:-THREAD_IMAGES_KEEP]
        return _to_jpeg(data)
    raise MuseError("error", "Muse sent back an earlier image instead of drawing a new one.")


# ── video ─────────────────────────────────────────────────────────────────────
# Đo 2/10/2026: image→video 9:16 → 704×1104, 10 s cố định, h264 + aac, ~6 MB, ~90 s. Muse không nhận độ dài khác.
# Một lượt quay chờ tối đa 15 phút (user 9/10/2026: «sau 15 phút thử không thành công thì reset phiên») — hết hạn thì
# ask() ĐÓNG HẲN phiên rồi thử lại, xem bên dưới.
VIDEO_TIMEOUT = 900


def video_request(prompt: str, aspect_ratio: str = "9:16", continue_from: bool = False) -> str:
    """Lời xin MỘT clip 10 s. continue_from: ảnh đính kèm ĐẦU là khung cuối của clip trước → khung đầu phải trùng."""
    ar = aspect_ratio if aspect_ratio in ASPECTS else "9:16"
    lines = [
        "Create exactly ONE 10-second video now. Do not ask questions, do not explain, and do not write anything in "
        "your reply — reply with the video only.",
        f"Aspect ratio: {ar} ({ASPECTS[ar]}).",
        "No text, captions, logos or watermarks inside the video.",
    ]
    if continue_from:
        lines.append("The FIRST attached image is the final frame of the previous shot: the video must START from "
                     "exactly that frame (same person, pose, framing, lighting and background) and continue the "
                     "action seamlessly. The other attached image(s) are the character's reference portrait: the "
                     "person must stay the SAME individual as in that portrait — same face shape, eyes, hair color "
                     "and style, skin tone — throughout the whole video. Keep the outfit identical.")
    else:
        lines.append("Use the attached image(s) as the reference for the person, outfit and setting — keep the face, "
                     "hair and outfit identical.")
    lines.append("")
    lines.append("Shot description:")
    lines.append(str(prompt or "").strip())
    return "\n".join(lines)


def generate_video_clip(prompt: str, out_dir: str, reference_images: Optional[list] = None,
                        aspect_ratio: str = "9:16", continue_from: bool = False, thread_id: str = "",
                        timeout: int = VIDEO_TIMEOUT) -> dict:
    """MỘT clip Muse → {path, poster, width, height, duration, thread_id}. Ném MuseError."""
    refs = [p for p in (reference_images or []) if p and os.path.isfile(str(p))][:3]
    os.makedirs(out_dir, exist_ok=True)
    res = ask(video_request(prompt, aspect_ratio, continue_from), want_videos=True, files=refs, video_dir=out_dir,
              max_videos=1, timeout=timeout, thread_id=thread_id)
    vids = [v for v in (res.get("videos") or []) if isinstance(v, dict) and v.get("path")]
    if not vids:
        said = " ".join(str(res.get("text") or "").split())[:240]
        raise MuseError(_no_output_kind(said), f"Muse did not make a video{': ' + said if said else '.'}")
    return {**vids[0], "thread_id": res.get("thread_id", "")}


def test_remote(base_url: str, key: str, timeout: int = 60) -> dict:
    """Gọi thử MỘT câu ngắn tới một nút Muse từ xa (chưa cần lưu): {ok, seconds, reply|message, kind, base_url}.

    Hộp cài đặt bấm «Test» / «Test and add» cho từng máy (9/10/2026)."""
    url = _node_url(base_url)
    if not url:
        return {"ok": False, "seconds": 0.0, "message": "Address must be a domain or http(s) URL.", "kind": "config", "base_url": base_url}
    node = {"base_url": url, "key": str(key or "").strip(), "seats": 1}
    t0 = time.time()
    try:
        res = _ask_remote(node, "remote?", "Reply with the single word OK.", timeout=timeout)
        return {"ok": True, "seconds": round(time.time() - t0, 1), "reply": str(res.get("text") or "")[:80], "base_url": url}
    except MuseError as e:
        return {"ok": False, "seconds": round(time.time() - t0, 1), "message": str(e), "kind": e.kind, "base_url": url}


def test_chat(timeout: int = 90) -> dict:
    """Gọi thử MỘT câu ngắn: {ok, seconds, reply|message, kind}."""
    t0 = time.time()
    try:
        text = chat_completion([{"role": "user", "content": "Reply with the single word OK."}], timeout=timeout)
        return {"ok": True, "seconds": round(time.time() - t0, 1), "reply": text[:80]}
    except MuseError as e:
        return {"ok": False, "seconds": round(time.time() - t0, 1), "message": str(e), "kind": e.kind}
