# Cập nhật MỘT extension không được khởi động lại cả TubeCLI.
#
# Chạy:  python tests/extension_hot_reload_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026: "khi tôi update phiên bản extension thì nó reset cả hệ thống luôn".
#   Cập nhật từ Chợ luôn hẹn khởi động lại vì hai lẽ, cả hai gỡ được tại chỗ:
#     1. route bản cũ nằm TRƯỚC trong bảng định tuyến và luôn thắng route mới;
#     2. module con của extension nằm trong sys.modules nên nạp lại vẫn ra mã cũ
#        (extension import `hr_routes` như module cấp cao vì thư mục của nó nằm
#        trong sys.path).
#   Test dùng FastAPI THẬT + một extension mẫu có module con, sửa file trên đĩa
#   rồi nạp nóng, và gọi route thật qua TestClient.
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
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
    print(("  ok   " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


import tubecli.config as cfg   # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tubecli_hotreload_"))
cfg.DATA_DIR = TMP
cfg.EXTENSIONS_DATA_DIR = TMP / "extensions_data"

from tubecli.core import extension_manager as EM   # noqa: E402

EM.EXTENSIONS_CONFIG_FILE = str(TMP / "extensions.json")

from fastapi import FastAPI                          # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402

EXT = TMP / "hr_demo"
EXT.mkdir()
LOG = TMP / "lifecycle.log"


def write_ext(version: str, answer: str, routes_extra: str = "", manifest_extra: dict = None):
    manifest = {"name": "hr_demo", "version": version, "entry": "extension.py",
                "extension_class": "HrDemo", "description": "x", "author": "t"}
    manifest.update(manifest_extra or {})
    (EXT / "tubecli-extension.json").write_text(json.dumps(manifest), encoding="utf-8")
    (EXT / "extension.py").write_text(textwrap.dedent(f"""
        from tubecli.core.extension_manager import Extension

        class HrDemo(Extension):
            name = "hr_demo"
            version = "{version}"

            def on_enable(self):
                open(r"{LOG}", "a").write("enable {version}\\n")

            def on_disable(self):
                open(r"{LOG}", "a").write("disable {version}\\n")

            def get_routes(self):
                import hr_routes
                return [hr_routes.router]
    """), encoding="utf-8")
    (EXT / "hr_routes.py").write_text(textwrap.dedent(f"""
        from fastapi import APIRouter
        import hr_helper
        router = APIRouter(prefix="/api/v1/hr-demo")

        @router.get("/ping")
        def ping():
            return {{"answer": hr_helper.ANSWER, "version": "{version}"}}
        {routes_extra}
    """), encoding="utf-8")
    (EXT / "hr_helper.py").write_text(f'ANSWER = "{answer}"\n', encoding="utf-8")


write_ext("1.0.0", "old")

app = FastAPI()
m = EM.ExtensionManager()
with open(EXT / "tubecli-extension.json", encoding="utf-8") as f:
    ext = m._load_external_extension(str(EXT), json.load(f))
m.register(ext)
m.enable("hr_demo")
m.register_api_routes(app)
client = TestClient(app)


def ping():
    r = client.get("/api/v1/hr-demo/ping")
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


def ping_routes():
    return [r for r in app.router.routes if getattr(r, "path", "") == "/api/v1/hr-demo/ping"]


print("== A. trước khi cập nhật")
check("A1 route bản 1 chạy", ping() == (200, {"answer": "old", "version": "1.0.0"}), ping())
check("A2 ghi lại route của extension", len(m._route_objs.get("hr_demo", [])) == 1, m._route_objs)

print("== B. cập nhật file trên đĩa rồi nạp nóng")
write_ext("2.0.0", "new")
res = m.hot_reload("hr_demo", app)
check("B1 nạp nóng thành công", res.get("reloaded") is True, res)
check("B2 route trả MÃ MỚI — kể cả module con hr_helper", ping() == (200, {"answer": "new", "version": "2.0.0"}), ping())
check("B3 không còn route cũ nằm trước chặn đường", len(ping_routes()) == 1, len(ping_routes()))
check("B4 báo đúng phiên bản", res.get("old_version") == "1.0.0" and res.get("version") == "2.0.0", res)
check("B5 đối tượng extension trong bộ quản lý là bản mới", m.get("hr_demo").version == "2.0.0")
life = LOG.read_text().split("\n")
check("B6 dừng bản cũ rồi bật bản mới", "disable 1.0.0" in life and life.index("disable 1.0.0") < life.index("enable 2.0.0"), life)
check("B7 cờ bật đã lưu của extension không bị động tới",
      m._config.get("hr_demo", {}).get("enabled") is True, m._config.get("hr_demo"))
# Nạp nóng KHÔNG được kéo theo cả hệ node + bộ quản lý toàn cục: trong tiến trình
# chưa từng nạp registry, import nó từng bật hàng loạt extension THẬT (13/9/2026).
check("B8 không import registry node khi tiến trình chưa dùng tới",
      "tubecli.nodes.registry" not in sys.modules)

print("== C. mã mới HỎNG thì giữ bản đang chạy")
write_ext("3.0.0", "broken", routes_extra="this is not python")
res = m.hot_reload("hr_demo", app)
check("C1 báo không nạp được", res.get("reloaded") is False and res.get("reason"), res)
check("C2 route bản 2 VẪN chạy", ping() == (200, {"answer": "new", "version": "2.0.0"}), ping())
check("C3 không để lại route rác", len(ping_routes()) == 1, len(ping_routes()))
check("C4 bộ quản lý vẫn giữ bản đang chạy", m.get("hr_demo").version == "2.0.0", m.get("hr_demo").version)

print("== D. sửa lỗi xong nạp lại được tiếp")
write_ext("3.0.1", "fixed")
res = m.hot_reload("hr_demo", app)
check("D1 nạp được", res.get("reloaded") is True, res)
check("D2 chạy mã đã sửa", ping() == (200, {"answer": "fixed", "version": "3.0.1"}), ping())
check("D3 vẫn đúng một route", len(ping_routes()) == 1)

print("== E. extension tự xin khởi động lại, và extension cài sẵn")
write_ext("4.0.0", "optout", manifest_extra={"hot_reload": False})
res = m.hot_reload("hr_demo", app)
check("E1 manifest hot_reload:false thì không nạp nóng", res.get("reloaded") is False and "restart" in res.get("reason", ""), res)
check("E2 và không đụng gì bản đang chạy", ping() == (200, {"answer": "fixed", "version": "3.0.1"}), ping())
builtin = EM.Extension()
builtin.name = "sys_demo"
builtin.extension_type = "system"
m._extensions["sys_demo"] = builtin
check("E3 extension cài sẵn: không nạp nóng (đi theo bản lõi)",
      m.hot_reload("sys_demo", app).get("reloaded") is False)
check("E4 không có app đang chạy (CLI): nói rõ", EM.ExtensionManager().hot_reload("hr_demo").get("reloaded") is False)

print("== F. route gắn bằng đường khác (Chợ cài mới) vẫn được gỡ")
write_ext("5.0.0", "market")
m2_app = FastAPI()
m2 = EM.ExtensionManager()
with open(EXT / "tubecli-extension.json", encoding="utf-8") as f:
    e2 = m2._load_external_extension(str(EXT), json.load(f))
m2.register(e2)
m2.enable("hr_demo")
m2._app = m2_app
for r in e2.get_routes():            # gắn tay, KHÔNG qua _mount_routes (như Chợ hot-mount)
    m2_app.include_router(r)
write_ext("5.0.1", "market2")
res = m2.hot_reload("hr_demo", m2_app)
c2 = TestClient(m2_app)
paths = [r for r in m2_app.router.routes if getattr(r, "path", "") == "/api/v1/hr-demo/ping"]
check("F1 nạp nóng được", res.get("reloaded") is True, res)
check("F2 route cũ gắn tay cũng bị gỡ (nhận ra theo file của endpoint)", len(paths) == 1, len(paths))
check("F3 chạy mã mới", c2.get("/api/v1/hr-demo/ping").json().get("answer") == "market2")

print("== G. các đường gọi đều dùng nạp nóng")
market = io.open(ROOT / "tubecli" / "extensions" / "market" / "routes.py", encoding="utf-8").read()
check("G1 Chợ cài đè extension đang chạy → hot_reload trước",
      "if was_installed:" in market and "extension_manager.hot_reload(hr_target.name)" in market)
check("G2 update-local không restart khi đã nạp nóng", 'if result.get("reloaded"):' in market)
mgr = io.open(ROOT / "tubecli" / "core" / "extension_manager.py", encoding="utf-8").read()
check("G3 update_extension (git) dùng hot_reload", "hr = self.hot_reload(name)" in mgr)
srv = io.open(ROOT / "tubecli" / "api" / "server.py", encoding="utf-8").read()
check("G4 có route nạp lại bằng tay", '@app.post("/api/v1/extensions/{name}/reload")' in srv)
webui = io.open(ROOT / "tubecli" / "extensions" / "webui" / "static" / "app.js", encoding="utf-8").read()
check("G5 dashboard: nạp nóng thì tải lại khung, không chờ restart",
      "if (result.reloaded) {" in webui and "reloadExtensionFrames(name);" in webui)

shutil.rmtree(TMP, ignore_errors=True)
print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
