"""core/subtitles.py — Phụ đề (subtitle) cháy chữ: NGUỒN DỮ LIỆU DUY NHẤT.

Preset phụ đề nằm ở engines/subtitle_presets.json — file DỮ LIỆU THUẦN, KHÔNG
code, được ĐỌC BỞI CẢ HAI phía:
  • JS  : engines/subtitle_engine.js (vẽ trong canvas_renderer.js)
  • PY  : module này (UI chọn preset, dựng tham số truyền cho renderer)
Sửa preset = sửa MỘT file JSON, không phải sửa hai nơi rồi lệch nhau.

Module này lo 3 việc:
  1. Đọc/cache danh sách preset      → list_presets(), get_preset(id)
  2. Chọn preset mặc định theo phong cách hình ảnh → default_for_style()
     (nền tối dùng chữ trắng viền đen; nền SÁNG phải có hộp nền, không thì
      chữ trắng chìm hẳn vào nền giấy/pastel)
  3. Dựng payload + cờ CLI cho canvas_renderer.js → subtitle_config(),
     cli_args(). Đúng MỘT chỗ dựng cờ → preview và render thật không bao giờ
     lệch nhau (bài học từ --title-color: 5 chỗ dựng lệnh, sửa sót 1 là lệch).

TƯƠNG THÍCH NGƯỢC (quan trọng — đọc kỹ):
project.json ĐƯỢC GHI TRƯỚC khi có tính năng này thì KHÔNG có khoá
"subtitle_enabled". Những project đó phải render RA Y HỆT bản cũ → phụ đề TẮT.
Nếu để nó rơi về settings/_DEFAULTS (mặc định True) thì mở lại một bài học cũ
rồi render là tự nhiên chữ cháy đè lên video vốn không hề có phụ đề.

Vì vậy khoá "subtitle_enabled" là MỐC ĐÁNH DẤU:
  • project KHÔNG có khoá  → project ĐỜI CŨ → tắt, và settings toàn cục KHÔNG
    được phép bật hộ (xem has_subtitle_key / subtitle_config).
  • project CÓ khoá        → project đời mới (project_store.create_project luôn
    ghi subtitle_enabled=True, dialog phụ đề cũng ghi) → theo đúng giá trị đó.
Các khoá còn lại (preset/cỡ chữ/vị trí) vẫn rơi về settings như thường — chúng
chỉ đổi HÌNH DÁNG phụ đề, không bật/tắt nó.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("TubeCraft.Subtitles")

from config import ENGINES_DIR

PRESETS_FILE = Path(ENGINES_DIR) / "subtitle_presets.json"

# Khoá quyết định project có "biết" tới phụ đề hay không. Có mặt trong
# project.json = project được tạo/lưu SAU khi có tính năng.
ENABLED_KEY = "subtitle_enabled"

# Mặc định khi project LẪN settings đều không nói gì.
# subtitle_preset "" = TỰ CHỌN theo art_style (xem default_for_style).
# subtitle_y_pct None = dùng yPct của preset.
# subtitle_enabled True: chỉ áp cho project ĐỜI MỚI (có ENABLED_KEY) mà giá trị
# lại là None; project đời cũ không bao giờ chạm tới mặc định này.
_DEFAULTS = {
    "subtitle_enabled": True,
    "subtitle_preset": "",
    "subtitle_font_scale": 1.0,
    "subtitle_y_pct": None,
    "subtitle_max_lines": None,
}

# Preset mặc định theo phong cách hình ảnh. Chỉ 2 nhóm thật sự khác nhau:
# nền TỐI (chữ trắng viền đen là đủ) và nền SÁNG (bắt buộc hộp nền tối/sáng
# tương phản, nếu không chữ trắng biến mất trên giấy/pastel/aurora).
_STYLE_MAP = {
    # nền SÁNG (giấy/màu nước/phác thảo) — chữ mực đậm, quầng trắng
    "aurora": "paper_ink",
    "watercolor": "paper_ink",
    "sketch": "paper_ink",
    "sketchnote": "paper_ink",
    "inkwash": "paper_ink",
    "warmpaper": "paper_ink",
    "editcream": "paper_ink",   # Editorial Cream — cream ấm, chữ đen
    # nền sáng + tông vui → bong bóng trắng, chữ tối
    "pastel": "bubble_box",
    "cartoon": "bubble_box",
    # nền tối, tông neon
    "cyberpunk": "neon_glow",
    "neonsketch": "neon_glow",
    "techdark": "tech_chip",
    # bảng đen toán — tối giản, không cướp nhìn khỏi công thức
    "mathnoir": "minimal_mono",
    # nền tối thường
    "default": "capcut_bold",
    "liquidglass": "capcut_bold",
    "pixel": "big_impact",
}

_FALLBACK_PRESET = "capcut_bold"

# cache theo mtime — preset đọc mỗi lần mở dialog/preview, đừng đọc đĩa liên tục
_cache = {"mtime": None, "data": None}


def _load() -> dict:
    """Đọc subtitle_presets.json (cache theo mtime). Lỗi → {} (phụ đề tắt êm)."""
    try:
        mtime = PRESETS_FILE.stat().st_mtime
    except OSError:
        logger.warning(f"Không thấy {PRESETS_FILE} — phụ đề sẽ không có preset.")
        return {"version": 0, "presets": []}
    if _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
            raise ValueError("thiếu mảng 'presets'")
    except Exception as e:
        logger.error(f"subtitle_presets.json hỏng: {e}")
        return {"version": 0, "presets": []}
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def list_presets() -> list:
    """Danh sách preset [{id, name, desc, ...}] — dùng cho dropdown/picker UI."""
    return [p for p in _load().get("presets", [])
            if isinstance(p, dict) and p.get("id")]


def preset_options() -> list:
    """[(id, "Tên — mô tả")] cho ft.Dropdown."""
    out = []
    for p in list_presets():
        desc = (p.get("desc") or "").strip()
        label = p.get("name") or p["id"]
        out.append((p["id"], f"{label} — {desc}" if desc else label))
    return out


def get_preset(preset_id: str):
    """Preset theo id, hoặc None nếu không có."""
    if not preset_id:
        return None
    for p in list_presets():
        if p.get("id") == preset_id:
            return p
    return None


def default_for_style(art_style: str) -> str:
    """Id preset mặc định cho một phong cách hình ảnh.

    Nếu id trong bảng không tồn tại trong file JSON (ai đó sửa preset), rơi về
    capcut_bold, rồi về preset ĐẦU TIÊN của file — luôn trả id hợp lệ nếu file
    có ít nhất 1 preset."""
    presets = list_presets()
    if not presets:
        return ""
    ids = {p["id"] for p in presets}
    for candidate in (_STYLE_MAP.get((art_style or "").strip().lower()),
                      _FALLBACK_PRESET):
        if candidate and candidate in ids:
            return candidate
    return presets[0]["id"]


# ── Dựng cấu hình truyền cho renderer ────────────────────────────────
def _settings() -> dict:
    try:
        from config import load_settings
        return load_settings()
    except Exception:
        return {}


def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "off", "no", "none")
    return bool(v)


def _as_float(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f


def has_subtitle_key(project: dict) -> bool:
    """project.json này có BIẾT tới phụ đề không?

    False = project được ghi TRƯỚC khi có tính năng (project.json không có khoá
    subtitle_enabled) → phải render y hệt bản cũ: phụ đề TẮT, bất kể settings
    toàn cục của máy đang bật.
    True  = project đời mới: project_store.create_project ghi
    subtitle_enabled=True ngay lúc tạo, dialog phụ đề cũng ghi khi bấm Lưu.
    """
    return isinstance(project, dict) and ENABLED_KEY in project


def subtitle_config(project: dict, settings: dict = None) -> dict:
    """Cấu hình phụ đề ĐÃ GIẢI QUYẾT cho một project.

    Trả đúng shape mà canvas_renderer.js chờ ở --subtitle:
        {"enabled": bool, "preset": str, "fontScale": float,
         "yPct": float|None, "maxLines": int|None}
    (None = dùng giá trị của preset.)

    Thứ tự ưu tiên mỗi khoá: project.json → settings.json → _DEFAULTS.
    NGOẠI LỆ subtitle_enabled: project KHÔNG có khoá → TẮT, không hỏi settings
    (xem has_subtitle_key và docstring đầu file).
    """
    project = project if isinstance(project, dict) else {}
    if settings is None:
        settings = _settings()
    settings = settings if isinstance(settings, dict) else {}

    def pick(key):
        for src in (project, settings):
            if src.get(key) is not None:
                return src[key]
        return _DEFAULTS[key]

    # Project đời cũ (không có khoá) → tắt hẳn. Có khoá nhưng để None (ai đó xoá
    # giá trị) → mới rơi về settings/_DEFAULTS như các khoá khác.
    enabled = _as_bool(pick("subtitle_enabled")) if has_subtitle_key(project) else False

    preset = str(pick("subtitle_preset") or "").strip()
    if preset and get_preset(preset) is None:
        logger.warning(f"Preset phụ đề '{preset}' không tồn tại → dùng mặc định.")
        preset = ""
    if not preset:
        preset = default_for_style(project.get("art_style", "default"))
    if not preset:                      # file preset rỗng/hỏng → tắt hẳn
        enabled = False

    # 0.6–2.0: dưới nữa là không đọc nổi, trên nữa là tràn khung 9:16
    scale = min(2.0, max(0.6, _as_float(pick("subtitle_font_scale"), 1.0)))

    y_raw = pick("subtitle_y_pct")
    y_pct = None
    if y_raw is not None and str(y_raw).strip() != "":
        # Trần 0.90: dưới nữa là đè lên thanh tiến trình (y≈H-56) và UI nền tảng
        y_pct = min(0.90, max(0.30, _as_float(y_raw, 0.82)))

    ml_raw = pick("subtitle_max_lines")
    max_lines = None
    if ml_raw is not None and str(ml_raw).strip() != "":
        try:
            max_lines = min(4, max(1, int(ml_raw)))
        except (TypeError, ValueError):
            max_lines = None

    # Màu nhấn theo TEMPLATE: def khai "subtitle_accent" (hex 6 ký tự) →
    # từ-đang-đọc + quầng glow ăn theo màu template (vd Neon Doodle lime)
    # thay vì màu cứng của preset. Project ghi đè được bằng cùng khoá.
    accent = project.get("subtitle_accent")
    if not accent and project.get("template"):
        try:
            from core.templates import get_template
            accent = (get_template(project["template"]) or {}).get("subtitle_accent")
        except Exception:
            accent = None
    accent = str(accent).strip() if accent else ""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        accent = ""

    return {"enabled": enabled, "preset": preset, "fontScale": round(scale, 3),
            "yPct": y_pct, "maxLines": max_lines, "accent": accent or None}


def to_json(cfg: dict) -> str:
    """Chuỗi JSON compact truyền qua CLI/env (subprocess dùng list arg nên
    không cần lo quote của shell)."""
    return json.dumps(cfg, ensure_ascii=False, separators=(",", ":"))


def cli_args(project: dict, settings: dict = None) -> list:
    """Cờ CLI cho canvas_renderer.js: ['--subtitle', '<json>'] hoặc [].

    Phụ đề TẮT → [] (renderer không thấy cờ → không vẽ gì, y hệt bản cũ)."""
    cfg = subtitle_config(project, settings)
    if not cfg.get("enabled"):
        return []
    return ["--subtitle", to_json(cfg)]


def env_vars(project: dict, settings: dict = None) -> dict:
    """{'T2_SUBTITLE': '<json>'} hoặc {}.

    Dùng cho render chunk song song: mọi tiến trình con thừa kế env nên không
    phụ thuộc vào việc nhớ sửa đủ 4 chỗ dựng lệnh (bài học T2_BG_GRAD)."""
    cfg = subtitle_config(project, settings)
    if not cfg.get("enabled"):
        return {}
    return {"T2_SUBTITLE": to_json(cfg)}
