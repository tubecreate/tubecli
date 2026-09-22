"""core/backgrounds.py — Danh mục NỀN, tách rời khỏi phong cách hình ảnh.

Vì sao cần: trước đây nền bị khoá cứng vào `art_style` — chọn "Pastel" là phải
chịu nền pastel. Giờ người dùng chọn phong cách (font, bảng màu, hiệu ứng chữ)
rồi đổi nền riêng.

Mỗi preset gồm:
  id    — lưu trong project.json (bg = "")
  grad  — [màu_đầu, màu_cuối] gradient chéo; 1 màu lặp lại = nền trơn
  fx    — "auto" giữ hiệu ứng nền của phong cách (lưới pixel, quả cầu
          liquidglass...); "off" = nền phẳng tuyệt đối

bg = "" (rỗng) nghĩa là THEO PHONG CÁCH — renderer không nhận cờ nào, giữ
nguyên hành vi cũ. Đây là mặc định để project cũ không đổi hình.
"""

# (id, tên hiển thị, grad, fx)
BACKGROUNDS = [
    ("", "Theo phong cách (mặc định)", None, "auto"),

    # ── Tối ──────────────────────────────────────────────────────────
    ("midnight",   "🌌 Tím than gradient",   ["#0a0a1a", "#1a1030"], "auto"),
    ("deep_blue",  "🌊 Xanh đêm sâu",        ["#020617", "#0f2544"], "auto"),
    ("charcoal",   "🌑 Than chì trung tính", ["#111214", "#232529"], "auto"),
    ("black_flat", "⬛ Đen phẳng",           ["#000000", "#000000"], "off"),
    ("forest",     "🌲 Xanh rừng trầm",      ["#0b1f18", "#153a2c"], "auto"),
    ("wine",       "🍷 Đỏ rượu sâu",         ["#1a0710", "#3d0f22"], "auto"),

    # ── Sáng ─────────────────────────────────────────────────────────
    ("paper",      "📄 Giấy kem ấm",         ["#fcf8f2", "#f0e6d6"], "auto"),
    ("white_flat", "⬜ Trắng phẳng",          ["#ffffff", "#ffffff"], "off"),
    ("pastel_pink","🌸 Pastel hồng–tím",     ["#fff5f5", "#f0e6ff"], "auto"),
    ("sky",        "☁️ Trời xanh nhạt",      ["#f0f9ff", "#dbeafe"], "auto"),
    ("mint",       "🌿 Bạc hà dịu",          ["#f2fbf6", "#dcf3e6"], "auto"),

    # ── Nổi bật ──────────────────────────────────────────────────────
    ("sunset",     "🌇 Hoàng hôn cam–tím",   ["#2b1055", "#7b2e5e"], "auto"),
    ("neon_cyber", "🌃 Neon tím–hồng",       ["#05010f", "#2a0a3a"], "auto"),
    ("gold_dark",  "👑 Đen ánh vàng",        ["#0d0b06", "#2e2410"], "auto"),
]

_BY_ID = {b[0]: b for b in BACKGROUNDS}


def options() -> list[tuple[str, str]]:
    """[(id, tên)] cho ft.Dropdown."""
    return [(b[0], b[1]) for b in BACKGROUNDS]


def get(bg_id: str) -> dict | None:
    """Trả {grad, fx} hoặc None nếu 'theo phong cách' / id lạ."""
    b = _BY_ID.get((bg_id or "").strip())
    if not b or not b[2]:
        return None
    return {"grad": b[2], "fx": b[3]}


def _luma(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def is_light(bg_id: str) -> bool:
    """Nền sáng? (dùng để cảnh báo chữ của phong cách tối sẽ khó đọc)"""
    cfg = get(bg_id)
    if not cfg:
        return False
    return sum(_luma(c) for c in cfg["grad"]) / 2 > 0.55


# Phong cách có bảng màu chữ SÁNG → đặt trên nền sáng sẽ mất chữ.
DARK_STYLES = {"default", "liquidglass", "cyberpunk", "pixel"}


def contrast_warning(bg_id: str, art_style: str) -> str:
    """Cảnh báo tương phản, rỗng nếu an toàn."""
    if is_light(bg_id) and art_style in DARK_STYLES:
        return (f"⚠️ Nền sáng + phong cách '{art_style}' dùng chữ sáng → chữ sẽ "
                f"khó đọc. Đổi màu tiêu đề/chữ sang tối, hoặc chọn nền tối.")
    return ""


def render_args(bg_id: str) -> list[str]:
    """Cờ dòng lệnh cho canvas_renderer.js. Rỗng = giữ nguyên nền phong cách."""
    cfg = get(bg_id)
    if not cfg:
        return []
    args = ["--bg-grad", ",".join(cfg["grad"])]
    if cfg["fx"] == "off":
        args += ["--bg-fx", "off"]
    return args


def name_of(bg_id: str) -> str:
    b = _BY_ID.get((bg_id or "").strip())
    return b[1] if b else "Theo phong cách"
