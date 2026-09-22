"""config.py — Đường dẫn, phiên bản và cấu hình chung của TubeCraft.

Mô hình giống t2login: BASE_DIR trỏ về nơi đặt .exe khi đóng gói (PyInstaller),
data/ nằm cạnh executable để dễ backup và không đụng Program Files.
"""
import os
import sys
import json
from pathlib import Path

APP_NAME = "TubeCraft"
APP_VERSION = "0.1.70"

# Root path — khi frozen bởi PyInstaller thì data/ nằm cạnh .exe
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# ── Thư mục dữ liệu ──────────────────────────────────────────────────
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
OUTPUTS_DIR = DATA_DIR / "outputs"
JOBS_DIR = DATA_DIR / "jobs"
GALLERY_DIR = DATA_DIR / "gallery"
LOGS_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
KEYS_FILE = DATA_DIR / "keys.enc.json"        # key AI cloud — mã hoá at-rest
LICENSE_FILE = DATA_DIR / "license.json"
# Tài khoản Google (Cách B — Bearer token theo account). KHÁC license.json:
# license.json = license-key theo MÁY; account.json = đăng nhập Google theo
# TÀI KHOẢN. Hai hệ chạy song song (xem core/account_client.py).
ACCOUNT_FILE = DATA_DIR / "account.json"

# Node engines (canvas renderer) — bundle cùng app
ENGINES_DIR = BASE_DIR / "engines"

# Server quản lý key/license (Cloudflare Worker) — đổi sau khi deploy
LICENSE_API_BASE = os.environ.get(
    "TUBECRAFT_LICENSE_API",
    "https://tubecraft-license.tubecli.workers.dev/api",
)

# ── Đăng nhập Google (Desktop OAuth client + loopback PKCE) ──────────
# CẦN ĐIỀN: tạo "Desktop app" OAuth client ở Google Cloud Console
#   (APIs & Services → Credentials → Create credentials → OAuth client ID →
#    Application type = Desktop app), rồi dán Client ID / Client secret vào đây.
# Lưu ý: client secret của Desktop app KHÔNG phải bí mật thật (nó đóng gói
# trong mọi bản cài desktop) — Google vẫn yêu cầu gửi kèm khi đổi mã, nên để
# ở đây là đúng chuẩn. Bảo mật thật nằm ở PKCE + xác minh id_token phía worker.
# Có thể ghi đè qua biến môi trường khi test.
# Đọc Desktop OAuth client từ file JSON Google tải về, đặt ở data/ (đã gitignore
# — secret KHÔNG vào git). Định dạng "installed": {"installed":{client_id,
# client_secret,...}}. Fallback biến môi trường khi test. Secret Desktop app
# không phải bí mật thật (đóng gói trong bản cài) — để ngoài git chỉ để tránh
# secret-scanner của GitHub.
_GOOGLE_CLIENT_FILE = DATA_DIR / "google_desktop_client.json"


def _doc_desktop_google():
    try:
        if _GOOGLE_CLIENT_FILE.exists():
            d = json.loads(_GOOGLE_CLIENT_FILE.read_text("utf-8")).get("installed", {})
            cid, sec = d.get("client_id", ""), d.get("client_secret", "")
            if cid and sec:
                return cid, sec
    except Exception:
        pass
    return (os.environ.get("TUBECRAFT_GOOGLE_CLIENT_ID", ""),
            os.environ.get("TUBECRAFT_GOOGLE_CLIENT_SECRET", ""))


DESKTOP_CLIENT_ID, DESKTOP_CLIENT_SECRET = _doc_desktop_google()

# Hệ TÀI KHOẢN (Google login desktop, /api/auth/*) của bản VN nằm trên worker
# VN (tubecraft-license) — RIÊNG, database khác, KHÔNG dùng chung với hệ tài
# khoản Global (tubecraft-intl-license) của bản intl. Vì tài khoản và license
# VN cùng một worker nên ACCOUNT_API_BASE dùng thẳng LICENSE_API_BASE. Override
# qua biến môi trường nếu backend tài khoản dời chỗ.
ACCOUNT_API_BASE = os.environ.get("TUBECRAFT_ACCOUNT_API", LICENSE_API_BASE)

# Kho nội dung (content bank) — nằm trên worker INTL (hyperframes), dùng CHUNG
# cho cả 2 bản: taxonomy thể loại + gợi ý đề tài theo template (chip 💡 trong
# dialog Tạo tự động). Chỉ đọc public, không cần đăng nhập.
CONTENT_BANK_API = os.environ.get(
    "TUBECRAFT_CONTENT_API", "https://hyperframes.tubecreate.com/api")

# ── Tự cập nhật (mô hình t2login, nhưng qua HTTPS thường) ────────────
# UPDATE_BASE/latest.json  = manifest {version, key, sha256, size, notes}
# UPDATE_BASE/<key>        = zip bản build (publish_update.py đẩy lên R2,
# Worker license expose lại tại /api/updates/*). Đổi qua env khi cần test.
UPDATE_BASE = os.environ.get(
    "TUBECRAFT_UPDATE_BASE",
    LICENSE_API_BASE.rstrip("/") + "/updates",
)

# Kho template online (Worker /api/templates/*): index.json + <pack>/pack.json
# + <pack>/<id>.png. App tự tải gói mẫu về cache → thêm mẫu KHÔNG cần bump app.
TEMPLATES_BASE = os.environ.get(
    "TUBECRAFT_TEMPLATES_BASE",
    LICENSE_API_BASE.rstrip("/") + "/templates",
)
TEMPLATE_CACHE_DIR = DATA_DIR / "template_packs"


def ensure_directories():
    for d in (PROJECTS_DIR, OUTPUTS_DIR, JOBS_DIR, GALLERY_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


ensure_directories()


# ── Settings (JSON phẳng, đọc/ghi nguyên tử) ─────────────────────────
_DEFAULT_SETTINGS = {
    "lang": "vi",
    "theme": "dark",
    "tts_engine": "edge",
    "tts_voice": "vi-VN-HoaiMyNeural",
    "aspect_ratio": "9:16",
    "render_fps": 30,
    # 0 = tự động theo số lõi CPU và RAM trống (engines/video_encoder._pick_workers).
    # Đặt số > 0 để ép cứng khi máy yếu hoặc muốn nhường tài nguyên cho việc khác.
    "render_workers": 0,
    "gpu_encoder": "auto",          # auto | nvenc | cpu
    "ai_provider": "tubecraft",        # provider mặc định khi sinh kịch bản
    "ai_model": "",                 # rỗng = model mặc định của provider
    # ── Phụ đề cháy chữ (core/subtitles.py + engines/subtitle_presets.json) ──
    # Đây là MẶC ĐỊNH TOÀN CỤC; project.json ghi đè từng khoá một.
    "subtitle_enabled": True,
    "subtitle_preset": "",          # rỗng = tự chọn theo art_style
    "subtitle_font_scale": 1.0,     # 0.6–2.0, nhân với size của preset
    "subtitle_y_pct": None,         # None = dùng yPct của preset
}


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    merged = dict(_DEFAULT_SETTINGS)
    merged.update(data if isinstance(data, dict) else {})
    return merged


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = str(SETTINGS_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)
