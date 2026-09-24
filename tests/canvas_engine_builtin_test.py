# -*- coding: utf-8 -*-
"""Canvas Engine nằm TRONG LÕI — 22/9/2026.

VÌ SAO CÓ FILE NÀY
  Bộ dựng của dây chuyền «Diễn giải» từng là extension riêng trên Chợ: cài Content Studio xong máy vẫn thiếu nó, task
  chạy 40 phút mới hỏng «renderer is not installed»; lõi và bộ dựng có hai nhịp cập nhật. User: «sao không theo đường
  builtin để nó update cùng hệ thống, vì nó hỗ trợ cho các extension khác».

  1. gói tubecli.extensions.canvas_engine nạp được, có extension_instance, nằm trong BUILTIN_EXTENSIONS, đủ file bộ dựng
  2. Chợ: extension hệ thống cùng tên → «đã cài» (không hiện nút Cài); install_from_market từ chối cài đè (409, builtin)
  3. gói trên Chợ cho lõi cũ vẫn đóng được từ đúng thư mục này (không có __init__.py trong gói ngoài)

Run:  python tests/canvas_engine_builtin_test.py     (exit 0 = pass)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── 1. gói built-in ─────────────────────────────────────────")
import tubecli.extensions.canvas_engine as CEpkg  # noqa: E402
from tubecli.core.extension_manager import ExtensionManager  # noqa: E402

ext = CEpkg.extension_instance
ok(ext.name == "canvas_engine" and ext.extension_type == "system", "extension_instance tên canvas_engine, loại system", (ext.name, ext.extension_type))
ok("tubecli.extensions.canvas_engine" in ExtensionManager.BUILTIN_EXTENSIONS, "có trong BUILTIN_EXTENSIONS → tự nạp + tự bật khi khởi động")
root = ext.renderer_dir()
need = ("config.py", os.path.join("engines", "canvas_renderer.js"), os.path.join("engines", "video_encoder.py"),
        os.path.join("core", "subtitles.py"), os.path.join("engines", "subtitle_presets.json"), "package.json")
ok(all(os.path.isfile(os.path.join(root, f)) for f in need), "renderer/ đủ file bộ dựng (đúng bộ Content Studio kiểm)", root)
ok(os.path.basename(os.path.dirname(root)) == "canvas_engine" and os.sep + "extensions" + os.sep in root, "nằm trong tubecli/extensions/", root)
import json  # noqa: E402
man = json.load(open(os.path.join(os.path.dirname(root), "tubecli-extension.json"), encoding="utf-8-sig"))
ok(man.get("name") == "canvas_engine" and man.get("display_name") == "Canvas Engine" and man.get("version"), "manifest giữ nguyên tên/version (Chợ so title↔name)", man.get("version"))

print("── 2. Chợ coi built-in là đã cài, không cài đè ─────────────")
import tubecli.extensions.market.routes as MR  # noqa: E402
from tubecli.core import extension_manager as EM  # noqa: E402


class _Sys:
    name, extension_type, extension_dir = "canvas_engine", "system", os.path.dirname(root)


class _Ext:
    name, extension_type, extension_dir = "capcut_tts", "external", "/x"


real = EM.extension_manager._extensions
EM.extension_manager._extensions = {"canvas_engine": _Sys(), "capcut_tts": _Ext()}
# Máy dev còn bản Chợ cũ trong extensions_external → trỏ Chợ vào thư mục rỗng để kiểm đúng đường built-in.
import pathlib, tempfile  # noqa: E402
import tubecli.config as CFG  # noqa: E402
real_ext_dir = CFG.EXTENSIONS_EXTERNAL_DIR
CFG.EXTENSIONS_EXTERNAL_DIR = pathlib.Path(tempfile.mkdtemp(prefix="ce-empty-ext-"))
try:
    ok(MR._builtin_extension("Canvas Engine") is not None and MR._builtin_extension("canvas_engine") is not None,
       "tra theo tên Chợ («Canvas Engine») lẫn tên manifest")
    ok(MR._builtin_extension("CapCut TTS") is None and MR._builtin_extension("Nope") is None, "extension ngoài / không có → None")
    r = MR._check_item_installed("canvas_eng", "Canvas Engine", "extension")
    ok(r["installed"] and r["path"] == os.path.dirname(root) and r["local_version"] == man["version"],
       "check-installed: đã cài, đường dẫn trong lõi, version từ manifest", r)
    req = MR.MarketInstallRequest(item_data="", item_name="Canvas Engine", category="extension", force_update=True)
    try:
        asyncio.run(MR.install_from_market("canvas_eng", req))
        ok(False, "phải từ chối cài đè")
    except Exception as e:      # noqa: BLE001 — HTTPException
        d = getattr(e, "detail", None)
        ok(getattr(e, "status_code", 0) == 409 and isinstance(d, dict) and d.get("builtin") is True and "updates together" in d.get("message", ""),
           "install (kể cả force_update) → 409, nói rõ nó cập nhật cùng TubeCLI", (getattr(e, "status_code", None), d))
    r2 = MR._check_item_installed("zzz", "CapCut TTS", "extension")
    ok(not r2["installed"] or r2["path"] != "/x", "extension ngoài không đi qua đường built-in")
finally:
    EM.extension_manager._extensions = real
    CFG.EXTENSIONS_EXTERNAL_DIR = real_ext_dir

print("── 3. gói Chợ cho lõi cũ ───────────────────────────────────")
pub = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "tubecli-cloud", "scripts", "publish_canvas_engine.py")
if os.path.isfile(pub):
    src = open(pub, encoding="utf-8").read()
    ok("extensions" + chr(92) + "canvas_engine" in src and "extensions_external" not in src.split("SRC =")[1].split("\n")[0],
       "publish_canvas_engine.py đóng gói từ tubecli/extensions/canvas_engine", src.split("SRC =")[1].split("\n")[0])
    ok('"__init__.py"' in src, "gói ngoài không mang __init__.py của loader built-in")
else:
    print("  (không có tubecli-cloud cạnh repo — bỏ qua)")

print("\n4. renderer không mờ dần phần tử của bộ cảnh Studio (24/9/2026)")
# Renderer từng mờ dần MỌI phần tử trong 25% đầu mỗi nhịp (alpha = easeOut(rawP*4)), chỉ tắt cho mathnoir.
# Bộ cảnh Studio (template `cs_*`) tự lo entrance bằng win(), nên fade ấy làm 25% đầu MỖI nhịp lộ gradient
# nền dự án dưới mặt bảng — và chính khung 0 là ảnh xem trước trên YouTube (user: «cái frame nó lạc quẻ»).
_rj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tubecli", "extensions",
                   "canvas_engine", "renderer", "engines", "canvas_renderer.js")
with open(_rj, encoding="utf-8", errors="replace") as _f:
    _rsrc = _f.read()
ok("String(el.template || '').startsWith('cs_')" in _rsrc and "const alpha = _ownEntrance" in _rsrc,
   "custom_js có template cs_* đi qua với alpha 1 — không fade engine chồng lên entrance của bộ cảnh")
ok("artStyle === 'mathnoir' ||" in _rsrc, "mathnoir vẫn được miễn fade như trước")

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
