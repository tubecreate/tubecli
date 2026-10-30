"""Nhân bản extension + template sang máy khác (core/clone_kit.py, api/clone_routes.py, công cụ MCP) — 30/10/2026.

Chạy:  python tests/clone_kit_test.py      (mã thoát 0 = đạt)

User: «clone tubecli từ vps này qua vps khác thông qua mcp, copy tất cả qua vps mới chỉ copy các extension, template
không copy data, agent và để mở phần copy data nếu cần phát triển thêm». Khoá: không chép data/node_modules/.git/tệp bí
mật; chống zip-slip; chế độ newer/missing/all; dữ liệu máy đích không bị đụng; mã tải hạn + lượt; chỉ nhận URL bundle
https đúng dạng; gói dùng lại; template qua Content Studio (cả lúc chưa nạp → chờ khởi động lại); mục data/agents TẮT;
route + cổng đăng nhập + công cụ MCP (clone_import luôn hỏi chủ). Hai máy là hai DATA_DIR tạm, Content Studio là bản giả.
"""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tubecli.config as CFG  # noqa: E402
from tubecli.core import clone_kit as CK  # noqa: E402

REAL = CFG.DATA_DIR
checks = fails = 0


def check(name, ok, detail=""):
    global checks, fails
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails += 1


def mk(base: Path, rel: str, data=b"x"):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


SRC = Path(tempfile.mkdtemp(prefix="clone_src_"))
DST = Path(tempfile.mkdtemp(prefix="clone_dst_"))
E = "extensions_external"
mk(SRC, f"{E}/ext_a/tubecli-extension.json", json.dumps({"name": "ext_a", "version": "1.2.0", "package_keep_dirs": ["assets/data"]}))
mk(SRC, f"{E}/ext_a/main.py", "print('a')")
mk(SRC, f"{E}/ext_a/static/logo.png", b"\x89PNG....")
mk(SRC, f"{E}/ext_a/assets/data/table.json", "{}")          # package_keep_dirs đưa lại
mk(SRC, f"{E}/ext_a/data/user.json", "{\"secret\":1}")       # dữ liệu → KHÔNG chép
mk(SRC, f"{E}/ext_a/node_modules/x/index.js", "x")
mk(SRC, f"{E}/ext_a/__pycache__/m.cpython-312.pyc", b"\0")
mk(SRC, f"{E}/ext_a/.env", "KEY=1")
mk(SRC, f"{E}/ext_a/cookies.json", "[]")
mk(SRC, f"{E}/ext_a/client_secret_abc.json", "{}")
mk(SRC, f"{E}/ext_b/tubecli-extension.json", json.dumps({"name": "ext_b", "version": "2.0.0"}))
mk(SRC, f"{E}/ext_b/b.py", "B2")
mk(SRC, f"{E}/shared/util.py", "u")                          # thư mục hỗ trợ không manifest

mk(DST, f"{E}/ext_b/tubecli-extension.json", json.dumps({"name": "ext_b", "version": "1.5.0"}))
mk(DST, f"{E}/ext_b/b.py", "B1")
mk(DST, f"{E}/ext_b/data/keep.json", "MINE")                 # dữ liệu máy đích — phải còn nguyên
mk(DST, f"{E}/ext_c/tubecli-extension.json", json.dumps({"name": "ext_c", "version": "1.0.0"}))

try:
    # ── mục ──────────────────────────────────────────────────────────────────
    pub = {s["name"]: s for s in CK.sections_public()}
    check("mục extensions + templates BẬT; data + agents khai sẵn nhưng TẮT (chỗ mở rộng)",
          pub["extensions"]["enabled"] and pub["templates"]["enabled"] and not pub["data"]["enabled"] and not pub["agents"]["enabled"])
    for bad in (["data"], ["agents"], ["nope"]):
        try:
            CK._pick_sections(bad)
            check(f"mục {bad} bị từ chối", False, "không ném")
        except ValueError as e:
            check(f"mục {bad} bị từ chối có lý do", "not available" in str(e) or "Unknown" in str(e), str(e))

    # ── xuất trên máy nguồn ──────────────────────────────────────────────────
    CFG.DATA_DIR = SRC
    ex = CK.export_bundle(["extensions"])
    zpath = SRC / "clone" / "out" / CK._load_tokens()[ex["token"]]["file"]
    names = zipfile.ZipFile(zpath).namelist()
    check("gói có mã, mã chép, file đúng chỗ", ex["path"] == f"/api/v1/clone/bundle/{ex['token']}" and len(ex["token"]) >= 40
          and "extensions/ext_a/main.py" in names and "extensions/ext_a/static/logo.png" in names
          and "extensions/ext_b/b.py" in names and "extensions/shared/util.py" in names and "manifest.json" in names, names)
    check("package_keep_dirs đưa lại assets/data", "extensions/ext_a/assets/data/table.json" in names)
    leaked = [n for n in names if any(x in n for x in ("/data/user.json", "node_modules", "__pycache__", ".env",
                                                       "cookies.json", "client_secret"))]
    check("KHÔNG chép dữ liệu / node_modules / __pycache__ / .env / cookies / client_secret", not leaked, leaked)
    info = {i.filename: i for i in zipfile.ZipFile(zpath).infolist()}
    check("ảnh ghi STORED (không nén lại), mã nén DEFLATED",
          info["extensions/ext_a/static/logo.png"].compress_type == zipfile.ZIP_STORED
          and info["extensions/ext_a/main.py"].compress_type == zipfile.ZIP_DEFLATED)
    man = ex["manifest"]
    rows = {r["dir"]: r for r in man["sections"]["extensions"]["items"]}
    check("manifest: phiên bản + loại (support cho thư mục không manifest) + danh sách tệp bí mật bị bỏ",
          rows["ext_a"]["version"] == "1.2.0" and rows["shared"]["kind"] == "support"
          and any(".env" in x for x in man["sections"]["extensions"]["skipped_secret_files"]), rows)
    again = CK.export_bundle(["extensions"])
    check("gọi lại trong 15 phút → DÙNG LẠI gói vừa làm (cloud quá giờ gọi lại vẫn có gói)", again["token"] == ex["token"] and again.get("reused"))
    fresh = CK.export_bundle(["extensions"], fresh=True)
    check("fresh=true → gói mới", fresh["token"] != ex["token"] and not fresh.get("reused"))

    # mã tải: không đếm khi đọc manifest, đếm khi tải, tối đa 5
    check("đọc manifest không tính lượt", CK.bundle_for(ex["token"], False) and CK._load_tokens()[ex["token"]]["downloads"] == 0)
    for _ in range(CK.BUNDLE_MAX_DOWNLOADS):
        CK.bundle_for(ex["token"], True)
    check("quá 5 lượt tải → hết", CK.bundle_for(ex["token"], True) is None)
    check("mã sai → None", CK.bundle_for("x" * 43) is None)
    t = CK._load_tokens()
    t[fresh["token"]]["expires_at"] = 1
    CK._save_tokens(t)
    check("hết hạn → None + dọn file gói", CK.bundle_for(fresh["token"]) is None)

    # ── URL ──────────────────────────────────────────────────────────────────
    good = "https://src.example.com/api/v1/clone/bundle/" + "A" * 43
    check("URL bundle https đúng dạng được nhận", CK.check_bundle_url(good) == good)
    for bad in ("http://src.example.com/api/v1/clone/bundle/" + "A" * 43, "https://src.example.com/api/v1/files/read",
                good + "?x=1", "https://src.example.com/api/v1/clone/bundle/short", "file:///etc/passwd"):
        try:
            CK.check_bundle_url(bad)
            check(f"URL lạ bị từ chối: {bad[:50]}", False, "không ném")
        except ValueError:
            check(f"URL lạ bị từ chối: {bad[:50]}", True)

    # ── nhập trên máy đích ───────────────────────────────────────────────────
    bundle_file = SRC / "clone" / "out" / CK._load_tokens()[again["token"]]["file"] if again["token"] in CK._load_tokens() else zpath
    with zipfile.ZipFile(bundle_file, "a") as zf:                # gắn file zip-slip vào gói
        zf.writestr("extensions/ext_a/../../evil.txt", "pwn")
        zf.writestr("extensions/ext_a/data/injected.json", "x")
    src_man = json.loads(zipfile.ZipFile(bundle_file).read("manifest.json"))
    CFG.DATA_DIR = DST
    plan = CK.plan_import(src_man, ["extensions"], "newer")
    acts = {p["dir"]: p["action"] for p in plan["extensions"]}
    check("kế hoạch newer: ext_a cài mới, ext_b cập nhật 1.5→2.0", acts.get("ext_a") == "install" and acts.get("ext_b") == "update", acts)
    check("kế hoạch missing: ext_b bỏ qua", {p["dir"]: p["action"] for p in CK.plan_import(src_man, ["extensions"], "missing")["extensions"]}.get("ext_b") == "skip")
    check("plan_summary nói rõ data + agents KHÔNG chép", "data and agents are NOT copied" in CK.plan_summary(plan))

    CK._download = lambda url, dest, job: shutil.copyfile(bundle_file, dest)
    r = CK.start_import(good, ["extensions"], "newer")
    import time
    for _ in range(100):
        j = CK.job_status(r["job_id"])
        if j["status"] != "running":
            break
        time.sleep(0.05)
    j = CK.job_status(r["job_id"])
    check("job xong", j["status"] == "done", j)
    d = DST / E
    check("ext_a được cài (mã + ảnh + assets/data)", (d / "ext_a/main.py").read_text() == "print('a')" and (d / "ext_a/static/logo.png").is_file()
          and (d / "ext_a/assets/data/table.json").is_file())
    check("ext_b cập nhật mã, DỮ LIỆU máy đích còn nguyên", (d / "ext_b/b.py").read_text() == "B2" and (d / "ext_b/data/keep.json").read_text() == "MINE")
    check("ext_c (chỉ có ở máy đích) không bị đụng", (d / "ext_c/tubecli-extension.json").is_file())
    check("zip-slip + file data chèn vào gói bị bỏ", not (DST / "evil.txt").exists() and not (DST / E / "evil.txt").exists()
          and not (d / "ext_a/data/injected.json").exists())
    check("cần khởi động lại (có extension mới)", j.get("restart_required") is True)
    check("báo cáo lưu ra đĩa (đọc lại được sau khi khởi động lại)", (DST / "clone" / "jobs" / f"{r['job_id']}.json").is_file())

    # ── template qua Content Studio giả ──────────────────────────────────────
    from fastapi import FastAPI, File, Request, UploadFile
    from fastapi.responses import Response
    GOT = {}
    cs = FastAPI()

    @cs.post("/api/v1/studio/preset-bundle/export-zip")
    async def _ex():
        return Response(b"PK-templates-zip", media_type="application/zip")

    @cs.post("/api/v1/studio/preset-bundle/import-zip")
    async def _imz(file: UploadFile = File(...)):
        GOT["zip"] = await file.read()
        return {"upload_id": "u1"}

    @cs.post("/api/v1/studio/preset-bundle/import")
    async def _imp(request: Request):
        GOT["import"] = await request.json()
        return {"added": 3, "skipped": 1}

    CFG.DATA_DIR = SRC
    ex2 = CK.export_bundle(["templates"], app=cs, fresh=True)
    z2 = SRC / "clone" / "out" / CK._load_tokens()[ex2["token"]]["file"]
    check("template: xuất qua Content Studio vào templates/content_studio.zip",
          zipfile.ZipFile(z2).read("templates/content_studio.zip") == b"PK-templates-zip"
          and ex2["manifest"]["sections"]["templates"]["content_studio"] == "exported")
    CFG.DATA_DIR = DST
    with zipfile.ZipFile(z2) as zf:
        res = CK._tpl_import(zf, json.loads(zf.read("manifest.json")), {"app": cs, "mode": "newer"})
    check("template: nhập qua import-zip + import apply (mặc định an toàn của Studio, không ghi đè)",
          res["content_studio"]["result"] == "imported" and GOT.get("zip") == b"PK-templates-zip"
          and GOT.get("import") == {"upload_id": "u1", "apply": True}, res)
    bare = FastAPI()                                            # Content Studio chưa nạp trên máy đích
    with zipfile.ZipFile(z2) as zf:
        res = CK._tpl_import(zf, {}, {"app": bare})
    staged = res["content_studio"].get("staged")
    check("Content Studio chưa nạp → xếp chờ, nhập sau khi khởi động lại", res["content_studio"]["result"] == "pending"
          and staged and (DST / "clone" / "pending" / staged).is_file())
    GOT.clear()
    out = CK.apply_pending(cs)
    check("apply_pending (lúc khởi động) nhập gói chờ rồi xoá", out and out[0]["result"] == "imported"
          and not (DST / "clone" / "pending" / staged).exists() and GOT.get("zip") == b"PK-templates-zip", out)
    check("export template khi máy nguồn không có Content Studio → bỏ qua, không hỏng",
          CK._tpl_export(zipfile.ZipFile(io.BytesIO(), "w"), {"app": bare})["content_studio"].startswith("skipped"))

    # ── route + cổng đăng nhập ───────────────────────────────────────────────
    from fastapi.testclient import TestClient
    from tubecli.api import clone_routes as R
    app = FastAPI()
    app.include_router(R.router)
    c = TestClient(app)
    CFG.DATA_DIR = SRC
    m = c.get("/api/v1/clone/manifest").json()
    check("GET manifest: mục + extension của máy", {s["name"] for s in m["sections_available"]} == {"extensions", "templates", "data", "agents"}
          and any(i["dir"] == "ext_a" for i in m["sections"]["extensions"]["items"]))
    r = c.post("/api/v1/clone/export", json={"sections": ["extensions"], "fresh": True}).json()
    check("POST export → mã", r.get("token") and r.get("path"))
    check("GET bundle/<mã>/manifest", c.get(r["manifest_path"]).json().get("format") == CK.FORMAT)
    zr = c.get(r["path"])
    check("GET bundle/<mã> → zip", zr.status_code == 200 and zr.content[:2] == b"PK")
    check("mã sai → 404", c.get("/api/v1/clone/bundle/" + "z" * 43).status_code == 404)
    check("export mục data → 400", c.post("/api/v1/clone/export", json={"sections": ["data"]}).status_code == 400)
    check("import URL lạ → 400", c.post("/api/v1/clone/import", json={"url": "http://x/api/v1/clone/bundle/" + "a" * 43}).status_code == 400)
    SRV = io.open(ROOT / "tubecli/api/server.py", encoding="utf-8").read()
    check("server.py: đăng ký router + CHỈ đường tải gói được miễn đăng nhập",
          "app.include_router(_clone_router)" in SRV and '"/api/v1/clone/bundle/")' in SRV
          and '"/api/v1/clone/import"' not in SRV.split("_AUTH_EXEMPT_PREFIX")[1][:300])

    # ── công cụ MCP ──────────────────────────────────────────────────────────
    from tubecli.extensions.codex_gpt import tools as T
    from tubecli.core import claude_connector as CC
    check("4 công cụ clone_* có trong bộ công cụ", all(n in T.TOOLS for n in ("clone_manifest", "clone_export", "clone_import", "clone_status")))
    check("clone_import LUÔN hỏi chủ + có kế hoạch cho thẻ duyệt", T.TOOLS["clone_import"].always_ask is True and T.TOOLS["clone_import"].plan is not None)
    check("tubecli_api POST /api/v1/clone/import cũng luôn hỏi", "/api/v1/clone/import" in T.ALWAYS_ASK_WRITE)
    check("clone_manifest / clone_status chỉ đọc; export / import là lệnh ghi",
          not T.TOOLS["clone_manifest"].is_write({}) and not T.TOOLS["clone_status"].is_write({})
          and T.TOOLS["clone_export"].is_write({}) and T.TOOLS["clone_import"].is_write({}))
finally:
    CFG.DATA_DIR = REAL
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.rmtree(DST, ignore_errors=True)

print(f"\n{checks - fails}/{checks} PASS")
sys.exit(1 if fails else 0)
