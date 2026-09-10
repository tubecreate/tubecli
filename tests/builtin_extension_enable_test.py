# Extension CÀI SẴN phải sống trên máy đã cài từ trước, và bật là route sống ngay.
#
# Chạy:  python tests/builtin_extension_enable_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   11/9/2026: người dùng kéo file từ máy vào canvas, node hiện lỗi "Not Found".
#   Không phải lỗi kéo-thả, không phải CORS, không phải tunnel: extension Kho
#   nguyên liệu (media_library) — extension CÀI SẴN — chưa bao giờ được bật trên
#   máy đó, nên toàn bộ /api/v1/media/* trả 404.
#
#   Hai lỗ chồng nhau:
#     1. chỉ `tubecli init` bật extension hệ thống; register() coi "không có trong
#        extensions.json" là tắt. Nên MỌI extension cài sẵn ra sau ngày người dùng
#        init đều nằm im — vẫn hiện trong sidebar (đối tượng đã nạp) nhưng
#        register_api_routes() bỏ qua vì chưa bật. Không ai đoán ra phải init lại.
#     2. route chỉ được gắn một lần lúc khởi động, nên cả đường sửa tay "vào bảng
#        điều khiển bật lên" cũng vẫn 404 tới lần restart, mà không ai nói ra.
#
#   Test này giữ cả hai, và giữ luôn hai điều kiện mà đường kéo-thả dựa vào:
#   media_library phải là extension_type "system", và router của nó phải giữ tiền
#   tố /api/v1/media (cloud gọi thẳng đường đó).
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


import tubecli.config as cfg   # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tubecli_extmgr_test_")
cfg.DATA_DIR = _TMP
cfg.EXTENSIONS_DATA_DIR = os.path.join(_TMP, "extensions_data")

from tubecli.core import extension_manager as EM   # noqa: E402

# Hằng đường dẫn được tính lúc import, nên phải ép sang temp — nếu không test ghi
# thẳng vào extensions.json THẬT và tắt/bật extension của người dùng.
EM.EXTENSIONS_CONFIG_FILE = os.path.join(_TMP, "extensions.json")


class FakeExt(EM.Extension):
    """Extension giả: đếm số lần on_enable và trả router giả."""

    def __init__(self, name, ext_type="system", routers=None):
        super().__init__()
        self.name = name
        self.extension_type = ext_type
        self.enable_calls = 0
        self._routers = routers
        self.route_error = None

    def on_enable(self):
        self.enable_calls += 1

    def on_disable(self):
        pass

    def get_routes(self):
        return self._routers


class FakeApp:
    def __init__(self):
        self.included = []
        self.openapi_schema = {"stale": True}

    def include_router(self, r):
        self.included.append(r)


def fresh(config=None):
    """Manager mới với extensions.json do test quyết định."""
    with io.open(EM.EXTENSIONS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config if config is not None else {}, f)
    return EM.ExtensionManager()


def saved():
    with io.open(EM.EXTENSIONS_CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


# ── A. extension cài sẵn MỚI: chưa có ý kiến ⇒ bật ───────────────────────
m = fresh({"browser": {"enabled": True}})
new_ext = FakeExt("media_library")
m.register(new_ext)
check("A1 cài sẵn mới thì bật", new_ext.enabled is True, "vẫn tắt ⇒ mọi URL của nó 404")
check("A2 on_enable chạy đúng một lần", new_ext.enable_calls == 1, f"{new_ext.enable_calls} lần")
check("A3 ghi lại lựa chọn vào extensions.json",
      saved().get("media_library", {}).get("enabled") is True, saved())
check("A4 nằm trong get_enabled (register_api_routes duyệt danh sách này)",
      new_ext in m.get_enabled())

# ── B. người dùng TỰ TAY tắt thì phải tôn trọng ──────────────────────────
m = fresh({"media_library": {"enabled": False}})
off = FakeExt("media_library")
m.register(off)
check("B1 enabled:false vẫn tắt", off.enabled is False, "tự bật lại = ghi đè ý người dùng")
check("B2 không gọi on_enable", off.enable_calls == 0, f"{off.enable_calls} lần")
check("B3 không sửa file config", saved()["media_library"]["enabled"] is False, saved())

# ── C. extension ngoài (Chợ) KHÔNG tự bật ────────────────────────────────
m = fresh({})
ext = FakeExt("capcut_tts", ext_type="external")
m.register(ext)
check("C1 extension ngoài vẫn phải tự bật", ext.enabled is False,
      "tự bật extension tải từ Chợ = chạy code lạ mà chưa ai đồng ý")
check("C2 không ghi gì cho extension ngoài", "capcut_tts" not in saved(), saved())

# ── D. cấu hình có sẵn enabled:true vẫn chạy như cũ ──────────────────────
m = fresh({"media_library": {"enabled": True}})
on = FakeExt("media_library")
m.register(on)
check("D1 enabled:true thì bật", on.enabled is True)
check("D2 on_enable một lần (không nhân đôi)", on.enable_calls == 1, f"{on.enable_calls} lần")

# ── E. gắn route: một lần, và biết mình đã gắn ───────────────────────────
m = fresh({})
r1, r2 = object(), object()
two = FakeExt("media_library", routers=[r1, r2])
m.register(two)
app = FakeApp()
m.register_api_routes(app)
check("E1 gắn đủ router", app.included == [r1, r2], app.included)
check("E2 routes_live nói thật", m.routes_live("media_library") is True)
check("E3 giữ app lại để bật lúc đang chạy", m._app is app)
m.register_api_routes(app)
check("E4 gọi lại KHÔNG gắn hai lần", app.included == [r1, r2],
      f"{len(app.included)} router ⇒ route trùng")

# ── F. bật LÚC ĐANG CHẠY thì route sống ngay ─────────────────────────────
m = fresh({})
late = FakeExt("media_library", routers=[r1])
m.register(late)                       # chưa có config → bật theo mặc định
m.disable("media_library")             # người dùng tắt
app = FakeApp()
m.register_api_routes(app)             # khởi động: không gắn gì
check("F1 đang tắt thì không gắn route", app.included == [], app.included)
check("F2 routes_live=False khi chưa gắn", m.routes_live("media_library") is False)
m.enable("media_library")
check("F3 bật lúc đang chạy là gắn route ngay", app.included == [r1],
      "route chỉ gắn lúc khởi động ⇒ bật xong vẫn 404 tới lần restart")
check("F4 routes_live=True sau khi bật", m.routes_live("media_library") is True)
check("F5 xoá cache openapi", app.openapi_schema is None, app.openapi_schema)
check("F6 bật lại lần nữa không gắn trùng", (m.enable("media_library"), app.included)[1] == [r1],
      app.included)

# ── G. gắn route mà get_routes() nổ thì ghi lý do, không nuốt ────────────
class Boom(FakeExt):
    def get_routes(self):
        raise RuntimeError("thiếu PIL")


m = fresh({})
boom = Boom("thumbnail_studio")
m.register(boom)
app = FakeApp()
ok = m._mount_routes(boom, app)
check("G1 trả False khi gắn hỏng", ok is False)
check("G2 ghi lý do lên chính extension", "thiếu PIL" in (boom.route_error or ""), boom.route_error)
check("G3 routes_live=False khi gắn hỏng", m.routes_live("thumbnail_studio") is False)

# ── H. chưa có app thì không được nói dối là đã gắn ──────────────────────
m = fresh({})
noapp = FakeExt("media_library", routers=[r1])
m.register(noapp)
check("H1 không có app ⇒ False", m._mount_routes(noapp) is False)
check("H2 và routes_live vẫn False", m.routes_live("media_library") is False)

# ── I. hai điều kiện mà đường kéo-thả từ canvas dựa vào ──────────────────
ml = ROOT / "tubecli" / "extensions" / "media_library"
ext_src = io.open(ml / "extension.py", encoding="utf-8").read()
check("I1 media_library là extension hệ thống",
      re.search(r'extension_type\s*=\s*"system"', ext_src) is not None,
      "không phải 'system' ⇒ phép bật-theo-mặc-định không áp dụng, lại 404 như cũ")
routes_src = io.open(ml / "routes.py", encoding="utf-8").read()
check("I2 router giữ tiền tố /api/v1/media",
      re.search(r'APIRouter\(prefix="/api/v1/media"[,)]', routes_src) is not None,
      "cloud gọi thẳng /api/v1/media/... — đổi tiền tố là gãy đường kéo-thả")
check("I3 còn route /defaults (client hỏi kho mặc định)",
      '@router.get("/defaults")' in routes_src)
check("I4 route tải lên nhận field 'file'",
      re.search(r'@router\.post\("/collections/\{cid\}/files"\)\s*\n\s*async def upload_file\('
                r'cid: str, file: UploadFile', routes_src) is not None,
      "cloud gửi FormData field 'file' — lệch tên là 422")

# ── J. đường bật hộ từ cloud phải còn và phải nói route sống chưa ────────
srv = io.open(ROOT / "tubecli" / "api" / "server.py", encoding="utf-8").read()
check("J1 còn endpoint bật extension",
      '@app.post("/api/v1/extensions/{name}/enable")' in srv)
check("J2 endpoint trả routes_live", "routes_live" in srv.split(
    '@app.post("/api/v1/extensions/{name}/enable")')[1][:600],
      "không nói route đã sống chưa ⇒ client thử lại vô ích rồi báo lỗi vô nghĩa")

print(f"\n{checks - len(failures)}/{checks} kiểm tra đạt")
if failures:
    print("\nTRƯỢT:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("Tất cả đạt.")
