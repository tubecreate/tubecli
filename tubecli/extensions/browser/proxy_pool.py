"""Kho proxy — nhiều proxy gom thành nhóm, phát ra theo chính sách thay vì gõ tay từng cái.

Vì sao có tệp này. Hồ sơ trình duyệt chỉ giữ MỘT chuỗi proxy cố định
(profile_manager.create_profile), và `bulk_set_proxy` đặt CÙNG một proxy cho
nhiều hồ sơ — ngược hẳn với xoay vòng. Chế độ "Dynamic API" trên giao diện agent
thì gọi cứng tmproxy.com và hỏi `get-current-proxy`, tức lấy lại đúng IP đang
dùng; ô "Provider API URL" người dùng gõ vào không nơi nào đọc. Nên trước tệp này,
TubeCLI không có cách nào phát IP khác nhau cho các hồ sơ.

Ba việc tệp này làm mà chuỗi proxy đơn lẻ không làm được:

  1. GOM NHÓM. Mỗi kho là một nguồn (nhà cung cấp, quốc gia, gói thuê). Hồ sơ xin
     "một proxy từ Kho VN" chứ không xin một địa chỉ cụ thể, nên đổi nhà cung cấp
     là đổi nội dung kho, không phải sửa 100 hồ sơ.

  2. PHÁT ĐỀU. `distribute()` luôn chọn proxy đang có ÍT hồ sơ dùng nhất, đếm cả
     hồ sơ CŨ trên đĩa. Phát ngẫu nhiên thuần sẽ dồn nhiều hồ sơ vào một IP đúng
     lúc ta đang cố tránh điều đó.

  3. CHUẨN HOÁ DẠNG. Nhà cung cấp Việt Nam hay phát dạng
     `scheme://host:port:user:pass`. Engine ShardX từ chối thẳng dạng này
     (`PROXY_FORMAT_UNSUPPORTED` — routes.proxy_blocker), và mã cũ chỉ ném lỗi bảo
     người dùng tự viết lại. Nó viết lại được bằng máy: 3 trong 14 proxy đang có
     trên đĩa thuộc dạng đó. Kho chuẩn hoá ngay lúc nhập.

Cố ý KHÔNG làm ở đây: gọi mạng lúc phát proxy. `pick()`/`distribute()` nằm trên
đường mở trình duyệt, nên chúng chỉ đọc tệp. Việc đo thật nằm ở `test_proxy()`,
chỉ chạy khi người dùng bấm.
"""
import json
import os
import random
import re
import threading
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from tubecli.config import EXTENSIONS_DATA_DIR

# TUBECLI_PROXY_STORE trỏ kho sang tệp khác. Có biến này vì một lượt kiểm định
# tự động đã ghi 419 proxy giả vào kho thật của người dùng và gán chúng cho 9 hồ
# sơ: dặn kịch bản "nhớ dọn" không phải là hàng rào, chuyển hướng được mới là.
STORE = os.environ.get("TUBECLI_PROXY_STORE") or os.path.join(
    EXTENSIONS_DATA_DIR, "browser", "proxy_center.json")
DEFAULT_KHO = "Kho 1"

# Ghi tệp dưới khoá: hai hồ sơ khởi động cùng lúc đều gọi distribute(), và một
# lần ghi chồng lên nhau sẽ nuốt mất proxy vừa thêm.
_LOCK = threading.RLock()

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y")


# ── đọc / ghi ───────────────────────────────────────────────────────────────
def _empty() -> Dict:
    return {"khos": [{"name": DEFAULT_KHO, "note": ""}], "proxies": []}


def _load() -> Dict:
    """Đọc kho. Tệp hỏng KHÔNG được làm sập đường mở trình duyệt — trả kho rỗng,
    và giữ nguyên tệp cũ để người dùng còn cứu được."""
    try:
        with open(STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    khos = data.get("khos")
    if not isinstance(khos, list) or not khos:
        khos = [{"name": DEFAULT_KHO, "note": ""}]
    proxies = data.get("proxies")
    if not isinstance(proxies, list):
        proxies = []
    return {"khos": khos, "proxies": proxies}


def _save(data: Dict) -> None:
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE)


# ── chuỗi proxy ─────────────────────────────────────────────────────────────
def _parse(raw: str) -> Optional[dict]:
    """Mượn routes.parse_proxy — nó là nơi duy nhất trong repo đọc ĐÚNG thứ tự
    [host, port, user, pass] của dạng nhà cung cấp. Nhập muộn vì routes nhập
    module này."""
    from .routes import parse_proxy
    return parse_proxy(raw)


DEFAULT_SCHEME = "http"


def _add_scheme(raw: str) -> tuple:
    """(chuỗi có scheme, đã phải đoán scheme hay chưa).

    Nhà cung cấp thường phát `ip:port:user:pass` trần. Từ chối nó là từ chối
    đúng thứ người dùng dán vào. Mặc định http vì đó là dạng duy nhất chạy được
    mà KHÔNG cần relay — đoán sai thì `test_proxy` sửa lại."""
    v = (raw or "").strip()
    if not v or "://" in v:
        return v, False
    return f"{DEFAULT_SCHEME}://{v}", True


def scheme_was_guessed(raw: str) -> bool:
    return _add_scheme(raw)[1]


def normalise(raw: str) -> Optional[str]:
    """Chuỗi proxy về dạng engine chạy được, hoặc None nếu không đọc nổi.

    Dạng nhà cung cấp `scheme://host:port:user:pass` được viết lại thành
    `scheme://user:pass@host:port`. Đây là toàn bộ lý do dạng đó bị từ chối:
    Chromium không hiểu bốn phần ngăn bằng dấu hai chấm, chứ proxy thì vẫn tốt.

    Chuỗi trần không có `://` được gắn scheme mặc định — xem _add_scheme.
    """
    info = _parse(_add_scheme(raw)[0])
    if not info:
        return None
    if not info["scheme_known"]:
        # Một hồ sơ trên đĩa ghi "sock5s://" (gõ nhầm socks5). Chromium trả
        # ERR_NO_SUPPORTED_PROXIES cho scheme lạ, nên nhận vào kho chỉ để hỏng
        # lúc mở trình duyệt là vô ích — trả None để nó nằm ở danh sách "không
        # đọc được" ngay lúc nhập, kèm nguyên văn dòng đó.
        return None
    if info["has_credentials"]:
        return f"{info['scheme']}://{info['user']}:{info['password']}@{info['host']}:{info['port']}"
    return f"{info['scheme']}://{info['host']}:{info['port']}"


def key_of(raw: str) -> str:
    """Khoá so trùng: host:port:user, bỏ scheme và mật khẩu.

    Cùng một điểm cuối ghi http hay socks5 vẫn là MỘT proxy — nếu không, đếm số
    hồ sơ đang dùng sẽ sai và `distribute()` tưởng còn chỗ trống."""
    info = _parse(_add_scheme(raw)[0])
    if not info:
        return ""
    return f"{info['host']}:{info['port']}:{info['user']}".lower()


def is_expired(p: Dict) -> bool:
    """Hết hạn khi expiry_date đã QUA. Không ghi hạn nghĩa là không hết hạn —
    người dùng bỏ trống thì đừng tự suy diễn rồi giấu proxy của họ đi."""
    s = str(p.get("expiry_date") or "").strip()
    if not s:
        return False
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date() < date.today()
        except ValueError:
            continue
    return False  # ghi sai định dạng thì coi như còn hạn, đừng vứt proxy đi


def engine_blocker(raw: str, version: str = "ShardX 149.0.7827.103") -> Optional[str]:
    """Engine đã ghim có chạy được proxy này không — mã lý do, hoặc None nếu được.

    Dùng chung luật với routes.proxy_blocker để kho không bao giờ phát ra một
    dạng mà launcher sẽ từ chối vài giây sau đó.

    `version` phải là chuỗi ghim ShardX thật ("ShardX <ver>"): proxy_blocker mở
    đầu bằng `if not shardx_pin(version): return None`, nên truyền "shardx" làm
    nó bỏ qua mọi kiểm tra và luôn nói "được".
    """
    try:
        from .routes import proxy_blocker
        return proxy_blocker(version, raw)
    except Exception:
        return None


# ── kho ─────────────────────────────────────────────────────────────────────
def list_khos() -> List[Dict]:
    data = _load()
    counts: Dict[str, int] = {}
    live: Dict[str, int] = {}
    for p in data["proxies"]:
        k = p.get("kho") or DEFAULT_KHO
        counts[k] = counts.get(k, 0) + 1
        if not is_expired(p):
            live[k] = live.get(k, 0) + 1
    return [{"name": k.get("name", ""), "note": k.get("note", ""),
             "total": counts.get(k.get("name", ""), 0),
             "live": live.get(k.get("name", ""), 0)} for k in data["khos"]]


def create_kho(name: str, note: str = "") -> Dict:
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "Tên kho không được để trống"}
    with _LOCK:
        data = _load()
        if any(k.get("name") == name for k in data["khos"]):
            return {"success": False, "error": f"Kho '{name}' đã có"}
        data["khos"].append({"name": name, "note": note or ""})
        _save(data)
    return {"success": True, "name": name}


def rename_kho(old: str, new: str) -> Dict:
    new = (new or "").strip()
    if not new:
        return {"success": False, "error": "Tên kho không được để trống"}
    with _LOCK:
        data = _load()
        if not any(k.get("name") == old for k in data["khos"]):
            return {"success": False, "error": f"Không có kho '{old}'"}
        if old != new and any(k.get("name") == new for k in data["khos"]):
            return {"success": False, "error": f"Kho '{new}' đã có"}
        for k in data["khos"]:
            if k.get("name") == old:
                k["name"] = new
        # Proxy mang tên kho chứ không mang id kho, nên đổi tên phải kéo theo.
        # Bỏ bước này là cả kho biến mất khỏi mọi màn hình.
        for p in data["proxies"]:
            if (p.get("kho") or DEFAULT_KHO) == old:
                p["kho"] = new
        _save(data)
    return {"success": True, "name": new}


def delete_kho(name: str, delete_proxies: bool = False) -> Dict:
    with _LOCK:
        data = _load()
        if len(data["khos"]) <= 1:
            return {"success": False, "error": "Phải còn ít nhất một kho"}
        if not any(k.get("name") == name for k in data["khos"]):
            return {"success": False, "error": f"Không có kho '{name}'"}
        data["khos"] = [k for k in data["khos"] if k.get("name") != name]
        fallback = data["khos"][0]["name"]
        moved = 0
        kept = []
        for p in data["proxies"]:
            if (p.get("kho") or DEFAULT_KHO) != name:
                kept.append(p)
                continue
            if delete_proxies:
                continue
            p["kho"] = fallback
            moved += 1
            kept.append(p)
        data["proxies"] = kept
        _save(data)
    return {"success": True, "moved_to": fallback if moved else None, "moved": moved}


# ── proxy ───────────────────────────────────────────────────────────────────
def list_proxies(kho: Optional[str] = None, include_expired: bool = True) -> List[Dict]:
    data = _load()
    used = usage_counts()
    out = []
    for p in data["proxies"]:
        if kho and (p.get("kho") or DEFAULT_KHO) != kho:
            continue
        expired = is_expired(p)
        if expired and not include_expired:
            continue
        item = dict(p)
        item["expired"] = expired
        item["profiles"] = used.get(key_of(p.get("proxy_str", "")), 0)
        item["blocker"] = engine_blocker(p.get("proxy_str", ""))
        item["scheme_guessed"] = bool(p.get("scheme_guessed"))
        out.append(item)
    return out


def add_proxies(kho: str, raw_text: str, expiry_date: str = "", note: str = "") -> Dict:
    """Nhập hàng loạt: mỗi dòng một proxy.

    Trả về số thêm được, số trùng và các dòng không đọc nổi — KÈM nội dung dòng.
    Báo "3 dòng lỗi" mà không nói dòng nào thì người dùng phải tự dò trong 200
    dòng vừa dán."""
    kho = (kho or DEFAULT_KHO).strip() or DEFAULT_KHO
    added, duplicate, invalid = [], [], []
    with _LOCK:
        data = _load()
        if not any(k.get("name") == kho for k in data["khos"]):
            data["khos"].append({"name": kho, "note": ""})
        # So trùng TOÀN CỤC, không theo từng kho: cùng một điểm cuối nằm ở hai
        # kho sẽ bị đếm hai lần khi phát đều, và hồ sơ tưởng đang dùng hai IP
        # khác nhau. Nhưng phải nhớ nó đang ở kho NÀO để còn nói ra.
        seen = {key_of(p.get("proxy_str", "")): (p.get("kho") or DEFAULT_KHO)
                for p in data["proxies"]}
        for line in (raw_text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Dán từ bảng tính hay kèm dấu phẩy hoặc tab ở cuối.
            line = line.rstrip(",;").strip()
            canon = normalise(line)
            if not canon:
                invalid.append(line[:120])
                continue
            guessed = scheme_was_guessed(line)
            k = key_of(canon)
            if k in seen:
                duplicate.append({"proxy": canon, "kho": seen[k]})
                continue
            seen[k] = kho
            entry = {
                "id": uuid.uuid4().hex[:12],
                "proxy_str": canon,
                "kho": kho,
                "expiry_date": (expiry_date or "").strip(),
                "note": note or "",
                "added_at": datetime.now().isoformat(timespec="seconds"),
                "last_ip": "",
                "last_country": "",
                "last_checked": "",
                "last_ok": None,
                # Người dùng không ghi scheme nên ta đoán http. Bảng phải NÓI RA
                # điều đó: đoán sai thì trình duyệt mở lên với proxy chết.
                "scheme_guessed": guessed,
            }
            data["proxies"].append(entry)
            added.append(entry)
        if added:
            _save(data)
    # `duplicate_where`: kho nào đang giữ mỗi proxy bị bỏ qua. Nếu không có nó,
    # người dùng thấy "3 đã có trong kho" ngay trên một cái kho rỗng.
    return {"success": True, "added": len(added), "duplicate": len(duplicate),
            "duplicate_where": duplicate, "invalid": invalid, "items": added,
            "guessed": sum(1 for a in added if a.get("scheme_guessed"))}


def update_proxy(proxy_id: str, **fields) -> Dict:
    allowed = {"kho", "expiry_date", "note", "proxy_str", "last_ip", "last_country",
               "last_checked", "last_ok", "scheme_guessed"}
    with _LOCK:
        data = _load()
        for p in data["proxies"]:
            if p.get("id") != proxy_id:
                continue
            for k, v in fields.items():
                if k not in allowed:
                    continue
                if k == "proxy_str":
                    canon = normalise(v)
                    if not canon:
                        return {"success": False, "error": "Chuỗi proxy không đọc được"}
                    v = canon
                p[k] = v
            _save(data)
            return {"success": True, "proxy": p}
    return {"success": False, "error": "Không tìm thấy proxy"}


def remove_proxies(ids: List[str]) -> Dict:
    ids = set(ids or [])
    with _LOCK:
        data = _load()
        before = len(data["proxies"])
        data["proxies"] = [p for p in data["proxies"] if p.get("id") not in ids]
        removed = before - len(data["proxies"])
        if removed:
            _save(data)
    return {"success": True, "removed": removed}


# ── phát proxy ──────────────────────────────────────────────────────────────
def usage_counts() -> Dict[str, int]:
    """Mỗi proxy đang được bao nhiêu hồ sơ dùng, theo khoá host:port:user."""
    counts: Dict[str, int] = {}
    try:
        from .profile_manager import list_profiles
        for prof in list_profiles():
            k = key_of(prof.get("proxy", ""))
            if k:
                counts[k] = counts.get(k, 0) + 1
    except Exception:
        pass
    return counts


# Chỉ HAI mã là bế tắc thật. PROXY_SOCKS5_AUTH_UNSUPPORTED thì KHÔNG: relay cục
# bộ tự đăng nhập SOCKS5 rồi nói HTTP không mật khẩu với Chrome, và trên máy này
# 11 trong 14 proxy đang dùng thuộc đúng loại đó. Loại chúng khỏi kho là vứt đi
# gần như toàn bộ proxy người dùng đã mua.
FATAL_BLOCKERS = {"PROXY_FORMAT_UNSUPPORTED"}


def _usable(kho: Optional[str]) -> List[Dict]:
    """Proxy trong kho mà engine chạy được QUA RELAY, ưu tiên còn hạn.

    Nếu TOÀN BỘ kho đã hết hạn thì vẫn trả về danh sách hết hạn đó, vì trả rỗng
    khiến hồ sơ mở KHÔNG proxy — lộ IP thật, tệ hơn nhiều so với một proxy quá
    hạn mà cùng lắm là không kết nối được."""
    data = _load()
    pool = [p for p in data["proxies"]
            if (not kho or (p.get("kho") or DEFAULT_KHO) == kho)
            and engine_blocker(p.get("proxy_str", "")) not in FATAL_BLOCKERS]
    live = [p for p in pool if not is_expired(p)]
    return live or pool


def pick(kho: Optional[str] = None) -> Optional[str]:
    """Một proxy ngẫu nhiên từ kho. None khi kho rỗng — người gọi PHẢI xử lý
    None chứ đừng mở trình duyệt trần."""
    pool = _usable(kho)
    return random.choice(pool)["proxy_str"] if pool else None


def distribute(kho: Optional[str], count: int) -> List[Optional[str]]:
    """`count` proxy chia đều: mỗi lượt lấy proxy đang có ít hồ sơ dùng nhất.

    Đếm cả hồ sơ CŨ trên đĩa, nên gán cho 5 hồ sơ mới không dồn vào IP mà 30 hồ
    sơ cũ đang dùng. count > số proxy thì quay vòng."""
    pool = _usable(kho)
    if not pool or count <= 0:
        return [None] * max(count, 0)
    used = usage_counts()
    counts = [used.get(key_of(p["proxy_str"]), 0) for p in pool]
    out = []
    for _ in range(count):
        i = min(range(len(pool)), key=lambda j: counts[j])
        out.append(pool[i]["proxy_str"])
        counts[i] += 1
    return out


def next_after(kho: Optional[str], current: Optional[str]) -> Optional[str]:
    """Proxy kế tiếp trong kho, KHÁC cái đang dùng — dùng cho xoay vòng theo lịch.

    Kho chỉ có một proxy thì trả lại chính nó: đổi sang None sẽ khiến phiên đang
    chạy rơi ra IP thật giữa chừng."""
    pool = _usable(kho)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]["proxy_str"]
    ck = key_of(current or "")
    others = [p for p in pool if key_of(p["proxy_str"]) != ck]
    used = usage_counts()
    others.sort(key=lambda p: used.get(key_of(p["proxy_str"]), 0))
    # Trong nhóm ít dùng nhất thì chọn ngẫu nhiên, để nhiều phiên xoay cùng lúc
    # không cùng nhảy sang một IP.
    fewest = used.get(key_of(others[0]["proxy_str"]), 0)
    tied = [p for p in others if used.get(key_of(p["proxy_str"]), 0) == fewest]
    return random.choice(tied)["proxy_str"]


# ── đo thật ─────────────────────────────────────────────────────────────────
def test_proxy(raw: str, timeout: int = 15) -> Dict:
    """Đi thật qua proxy để lấy IP công khai. Chỉ gọi khi người dùng bấm.

    Thử đúng scheme đã ghi; chuỗi không ghi scheme thì thử http rồi socks5."""
    canon = normalise(raw)
    if not canon:
        return {"ok": False, "error": "Chuỗi proxy không đọc được"}
    try:
        import requests
    except ImportError:
        return {"ok": False, "error": "Thiếu thư viện requests"}

    info = _parse(canon)
    auth = f"{info['user']}:{info['password']}@" if info["has_credentials"] else ""
    endpoint = f"{info['host']}:{info['port']}"
    # Luôn thử NỐT scheme còn lại. Chuỗi trần được gắn http lúc nhập chỉ là phỏng
    # đoán, và một proxy socks5 bị ghi nhầm thành http sẽ mở trình duyệt xong mọi
    # trang mới chết — kiểm tra là lúc duy nhất biết được sự thật, nên đừng chỉ
    # xác nhận phỏng đoán của chính mình.
    other = f"socks5://{auth}{endpoint}" if info["scheme"] == "http" else f"http://{auth}{endpoint}"
    candidates = [canon, other]

    last = "Không rõ"
    for url in candidates:
        scheme = url.split("://", 1)[0]
        try:
            r = requests.get("http://ip-api.com/json/",
                             proxies={"http": url, "https": url}, timeout=timeout)
            if r.status_code == 200:
                d = r.json()
                return {"ok": True, "ip": d.get("query", "?"),
                        "country": d.get("countryCode", "??"),
                        "city": d.get("city", ""), "scheme": scheme,
                        "working": url}
            last = f"HTTP {r.status_code} qua {scheme}"
        except Exception as e:
            # Lỗi socket hay kèm ký tự điều khiển; cắt cho vừa một dòng giao diện.
            msg = "".join(c for c in str(e) if c.isprintable())
            last = f"{scheme}: {msg[:80]}"
    return {"ok": False, "error": last}


def record_test(proxy_id: str, result: Dict) -> None:
    """Ghi kết quả đo lên proxy, để lần sau nhìn danh sách là biết cái nào chết.

    Nếu scheme đi được KHÁC với scheme đang lưu thì ghi đè luôn: đó chính là giá
    trị của nút kiểm tra với một chuỗi trần — nó sửa phỏng đoán, chứ không chỉ
    dán nhãn xanh hay đỏ."""
    fields = {
        "last_ip": result.get("ip", "") if result.get("ok") else "",
        "last_country": result.get("country", "") if result.get("ok") else "",
        "last_checked": datetime.now().isoformat(timespec="seconds"),
        "last_ok": bool(result.get("ok")),
    }
    working = result.get("working")
    if result.get("ok") and working:
        fields["proxy_str"] = working
        fields["scheme_guessed"] = False
    update_proxy(proxy_id, **fields)
