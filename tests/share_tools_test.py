"""Link công khai do Claude tạo qua trình kết nối claude.ai (codex_gpt/tools.py share_* + core/public_share.py).

Chạy:  python tests/share_tools_test.py      (mã thoát 0 = đạt)

4/11/2026: share_* ra đời, share_file LUÔN hỏi chủ. 5/11/2026 user: bật «Allow public share links» = đồng ý TRƯỚC cho mọi
link của kết nối đó — share_file trả URL NGAY (không link duyệt), hạn mặc định 30 phút (1–1440), tải thẳng bằng GET không
cần đăng nhập (đúng Content-Type/Length, có Range), kho media cũng chia sẻ được, share_files tới 100 file, CHỈ ảnh/video
(đuôi + magic bytes), chặn ../, symlink ra ngoài và đường nhạy cảm, 200 link/giờ/kết nối, nhật ký tạo/tải, tắt ô = link
đang sống trả 410. Chạy route File Manager THẬT trên DATA_DIR tạm.
"""
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tubecli.config as CFG  # noqa: E402

# Windows: File Manager chặn ~/AppData/Local (thư mục tạm mặc định nằm trong đó) — dựng DATA_DIR tạm cạnh repo.
D = Path(tempfile.mkdtemp(prefix="share_tools_", dir=str(ROOT.parent) if os.name == "nt" else None))
OUTSIDE = Path(tempfile.mkdtemp(prefix="share_out_", dir=str(ROOT.parent) if os.name == "nt" else None))
CFG.DATA_DIR = D
CFG.EXTENSIONS_DATA_DIR = D / "extensions_data"
os.environ["TUBECLI_PUBLIC_URL"] = "https://box.example.com"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.core import claude_connector as CC  # noqa: E402
from tubecli.core import public_share as PS  # noqa: E402
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402
from tubecli.extensions.file_manager import routes as FM  # noqa: E402

PS.fm_enabled = lambda: True          # test không nạp extension_manager
checks = fails = 0


def check(name, ok, detail=""):
    global checks, fails
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {str(detail)[:400]}"))
    if not ok:
        fails += 1


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + os.urandom(3000)
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + os.urandom(5000)
M4A = b"\x00\x00\x00\x18ftypM4A \x00\x00\x02\x00isomiso2" + os.urandom(500)


def mk(rel, data=PNG, base=None):
    p = (base or D) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


VIDEO = mk("content_studio/outputs/exports/toan1_bai1_minhhoa.mp4", MP4)
time.sleep(0.02)
IMG = mk("content_studio/api_images/scene_03.png")
MAM = mk("extensions_data/media_library/t2_greenguide/mam_suy_nghi.png")
SHEET = mk("extensions_data/media_library/t2_greenguide/meo_chay_a24x6f12.png")
BIG = mk("extensions_data/media_library/t2_greenguide/meo_chay_a24x6f12_src.mp4",
         b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + os.urandom(4 * 1048576))
SECRET = mk("cloud_api_keys.json", b'{"k":"secret"}')
FAKE_PNG = mk("content_studio/outputs/exports/fake.png", b"<html><script>alert(1)</script></html>")
HTML_MP4 = mk("content_studio/outputs/exports/page.mp4", b"<!doctype html><script>x</script>")
SVG = mk("content_studio/outputs/exports/logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>")
MP3 = mk("content_studio/outputs/exports/voice.mp3", b"ID3\x03\x00" + os.urandom(500))
AUDIO_MP4 = mk("content_studio/outputs/exports/voice_as.mp4", M4A)
JSONF = mk("content_studio/outputs/exports/settings.json", b"{}")
PROFILE_IMG = mk("browser_profiles/p1/Default/screenshot.png")
SESSION_IMG = mk("content_studio/sessions/s1.png")
COOKIE_IMG = mk("content_studio/outputs/cookie_dump.png")
ENV_IMG = mk("content_studio/outputs/.env.png")
FAR = mk("far.png", base=OUTSIDE)
mk("content_studio/outputs/.hidden/x.mp4", MP4)
os.makedirs(D / "content_studio/outputs/folder.mp4", exist_ok=True)
LINK = str(D / "content_studio/outputs/exports/link_to_far.png")
try:
    os.symlink(FAR, LINK)
    HAVE_LINK = True
except (OSError, NotImplementedError):
    HAVE_LINK = False

app = FastAPI()
for r in FM.router:
    app.include_router(r)
pub = TestClient(app)
LOOP = asyncio.new_event_loop()
txt = lambda res: "\n".join(c.get("text", "") for c in (res.get("content") or []))   # noqa: E731
run = LOOP.run_until_complete
CC.enabled = lambda: True


def handle(name, args, perms=("share",), grant=17, level="write"):
    return run(CC.handle({"rpc": {"method": "tools/call", "params": {"name": name, "arguments": args}},
                          "level": level, "perms": list(perms), "grant": grant}, app))


def js_of(res):
    t = txt(res)
    return json.loads(t[t.index("{"):]) if "{" in t else {}


def tok_of(url):
    return url.rsplit("/s/", 1)[1].split("/")[0]


def share(args, grant=17):
    st, body = handle("share_file", args, grant=grant)
    return tok_of(js_of(body["result"])["url"])


# ── A. đăng ký + quyền ────────────────────────────────────────────────────────
names = ["share_find", "share_file", "share_files", "share_list", "share_revoke"]
check("A1 năm công cụ share_* có, đều cần quyền «share»", all(T.TOOLS[n].perm == "share" for n in names))
check("A2 share_file: lệnh ghi nhưng KHÔNG hỏi chủ, không thẻ duyệt",
      T.TOOLS["share_file"].is_write({}) and not T.TOOLS["share_file"].asks_always({}) and T.TOOLS["share_file"].plan is None
      and not CC.is_dangerous(T.TOOLS["share_file"], {}))
check("A3 Codex trên máy không thấy share_*", not any(t["name"] in names for t in T.list_tools()))
check("A4 trình kết nối liệt kê share_* (mức ghi)", all(n in {t["name"] for t in CC.list_tools("write")} for n in names))
check("A5 File Manager vẫn bị chặn với tubecli_api",
      T.api_blocked("POST", "/api/v1/file-manager/share") and T.api_blocked("GET", "/api/v1/file-manager/shares"))
st, body = handle("share_file", {"path": VIDEO}, perms=())
check("A6 không có quyền → từ chối rõ ràng, chỉ đường bật trong Connectors, không thẻ duyệt",
      "needs_approval" not in body and body["result"]["isError"] and "Allow public share links" in txt(body["result"]))
st, body = handle("share_file", {"path": VIDEO}, level="read")
check("A7 kết nối chỉ-đọc có quyền share vẫn không tạo link", body["result"]["isError"] and "read-only" in txt(body["result"]))

# ── B. tìm file ───────────────────────────────────────────────────────────────
st, body = handle("share_find", {"limit": 100})
t = txt(body["result"])
rows = json.loads(t[t.index("["):])
paths = {os.path.normcase(x["path"]) for x in rows}
want = {os.path.normcase(os.path.realpath(p)) for p in (VIDEO, IMG, MAM, SHEET, BIG)}
check("B1 liệt kê ảnh/video thật (kết quả + kho media)", want <= paths, sorted(paths))
bad = (FAKE_PNG, HTML_MP4, SVG, MP3, AUDIO_MP4, JSONF, PROFILE_IMG, SESSION_IMG, COOKIE_IMG, ENV_IMG, SECRET)
check("B2 không lộ: ảnh giả, svg, âm thanh, json, hồ sơ trình duyệt, session, cookie, .env, thư mục ẩn",
      not any(os.path.normcase(os.path.realpath(p)) in paths for p in bad) and not any(".hidden" in p for p in paths),
      sorted(paths))
mrow = next((x for x in rows if x["name"] == "mam_suy_nghi.png"), {})
check("B3 file kho media kèm collection + filename", mrow.get("collection") == "t2_greenguide"
      and mrow.get("filename") == "mam_suy_nghi.png", mrow)
st, body = handle("share_find", {"collection": "t2_greenguide", "kind": "video"})
t = txt(body["result"])
check("B4 lọc theo kho + loại", "meo_chay_a24x6f12_src.mp4" in t and "mam_suy_nghi" not in t and "toan1" not in t, t)

# ── C. từ chối ────────────────────────────────────────────────────────────────
refuse = [("../ thoát ra ngoài", {"path": str(D / "content_studio/outputs/../../cloud_api_keys.json")}),
          ("file ngoài data/", {"path": FAR}),
          ("tệp khoá (json)", {"path": SECRET}),
          ("ảnh giả (html đuôi .png)", {"path": FAKE_PNG}),
          ("html đuôi .mp4", {"path": HTML_MP4}),
          ("svg", {"path": SVG}),
          ("âm thanh mp3", {"path": MP3}),
          ("âm thanh m4a đuôi .mp4", {"path": AUDIO_MP4}),
          ("hồ sơ trình duyệt", {"path": PROFILE_IMG}),
          ("thư mục sessions", {"path": SESSION_IMG}),
          ("tên tệp cookie", {"path": COOKIE_IMG}),
          (".env", {"path": ENV_IMG}),
          ("thư mục", {"path": str(D / "content_studio/outputs/folder.mp4")}),
          ("không tồn tại", {"path": str(D / "content_studio/outputs/nope.mp4")}),
          ("kho media: tên có ../", {"collection": "t2_greenguide", "filename": "../../../cloud_api_keys.json"}),
          ("kho media: không có file", {"collection": "t2_greenguide", "filename": "nope.png"})]
if HAVE_LINK:
    refuse.append(("symlink trỏ ra ngoài data/", {"path": LINK}))
else:
    print("[SKIP] máy này không tạo được symlink")
for label, args in refuse:
    st, body = handle("share_file", args)
    check(f"C {label} → từ chối", body["result"]["isError"] and "needs_approval" not in body, txt(body["result"]))
st, body = handle("share_file", {"path": SVG})
check("C câu báo loại file đúng chữ", "Only image and video files can be shared" in txt(body["result"]), txt(body["result"]))
check("C chưa tạo link nào", not [x for x in FM._load_shares() if PS.is_claude(x)])

# ── D. tạo link ngay + tải về ─────────────────────────────────────────────────
st, body = handle("share_file", {"path": IMG})
res = body["result"]
row = js_of(res)
check("D1 có quyền → URL ngay trong kết quả, không link duyệt", not res.get("isError") and "needs_approval" not in body
      and row.get("url", "").startswith("https://box.example.com/s/") and row.get("raw_url", "").endswith("/raw")
      and row.get("download_url", "").endswith("/download"), txt(res))
tok_img = tok_of(row["url"])
rec = next(x for x in FM._load_shares() if x["token"] == tok_img)
check("D2 bản ghi: via=claude, grant=17, hạn ≈ 30 phút, token ≥ 128 bit",
      rec["via"] == "claude" and rec["grant"] == 17 and 1790 < rec["expires"] - time.time() <= 1800
      and len(tok_img) >= 32, rec)
r = pub.get(f"/s/{tok_img}/download")
check("D3 /download: 200, đủ byte + sha256 khớp, image/png, attachment, nosniff, Content-Length",
      r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == hashlib.sha256(PNG).hexdigest()
      and r.headers.get("content-type", "").startswith("image/png") and "attachment" in r.headers.get("content-disposition", "")
      and r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("content-length") == str(len(PNG)),
      (r.status_code, dict(r.headers)))
r = pub.get(f"/s/{tok_img}/raw")
check("D4 /raw: inline, đúng loại", r.status_code == 200 and r.headers.get("content-type", "").startswith("image/png")
      and "inline" in r.headers.get("content-disposition", ""), dict(r.headers))
r = pub.get(f"/s/{tok_img}")
check("D5 trang /s/<mã> mở được, không lộ đường dẫn máy chủ", r.status_code == 200 and str(D) not in r.text)
for v, ok in ((0, False), (1441, False), ("x", False), (5, True), (1440, True)):
    st, body = handle("share_file", {"path": IMG, "expires_minutes": v})
    good = not body["result"].get("isError")
    check(f"D6 expires_minutes={v!r} → {'nhận' if ok else 'từ chối'}", good == ok, txt(body["result"]))
t5 = share({"path": IMG, "expires_minutes": 5})
check("D7 hạn 5 phút", 290 < next(x for x in FM._load_shares() if x["token"] == t5)["expires"] - time.time() <= 300)

# ── E. kho media + video lớn có Range ─────────────────────────────────────────
st, body = handle("share_file", {"collection": "t2_greenguide", "filename": "mam_suy_nghi.png"})
check("E1 kho media t2_greenguide/mam_suy_nghi.png → link", not body["result"].get("isError"), txt(body["result"]))
tok_big = share({"path": BIG, "expires_minutes": 1440})
full = open(BIG, "rb").read()
r = pub.get(f"/s/{tok_big}/download")
check("E2 video 4 MB tải đủ, sha256 khớp, video/mp4", r.status_code == 200 and len(r.content) == len(full)
      and hashlib.sha256(r.content).digest() == hashlib.sha256(full).digest()
      and r.headers.get("content-type", "").startswith("video/mp4"), (r.status_code, len(r.content)))
r = pub.get(f"/s/{tok_big}/download", headers={"Range": "bytes=1000-1999"})
check("E3 Range trên /download → 206, đúng 1000 byte", r.status_code == 206 and r.content == full[1000:2000]
      and r.headers.get("content-range", "").startswith("bytes 1000-1999/"), (r.status_code, dict(r.headers)))
r = pub.get(f"/s/{tok_big}/raw", headers={"Range": "bytes=0-99"})
check("E4 Range trên /raw → 206", r.status_code == 206 and r.content == full[:100], r.status_code)
r = pub.head(f"/s/{tok_big}/download")
check("E5 HEAD /download → 200 + Content-Length", r.status_code == 200 and r.headers.get("content-length") == str(len(full)),
      (r.status_code, dict(r.headers)))

# ── F. share_files ────────────────────────────────────────────────────────────
st, body = handle("share_files", {"files": [VIDEO, {"path": IMG}, {"collection": "t2_greenguide", "filename": "mam_suy_nghi.png"},
                                            SVG, {"path": SECRET}], "expires_minutes": 10})
out = js_of(body["result"])
check("F1 3 link + 2 từ chối, mỗi link {file, url, raw_url, download_url, expires_at}",
      len(out.get("links", [])) == 3 and len(out.get("refused", [])) == 2
      and all({"file", "url", "raw_url", "download_url", "expires_at"} <= set(x) for x in out["links"]), out)
st, body = handle("share_files", {"files": [IMG] * 101})
check("F2 quá 100 file → từ chối", body["result"]["isError"] and "100" in txt(body["result"]))

# ── G. hết hạn → 410, sweep dọn bản ghi ───────────────────────────────────────
_real_time = time.time
time.time = lambda: _real_time() + 1801
try:
    codes = [pub.get(f"/s/{tok_img}{sfx}").status_code for sfx in ("", "/raw", "/download")]
    check("G1 sau 30 phút: trang, /raw, /download đều 410", codes == [410, 410, 410], codes)
    n = PS.sweep_links()
    check("G2 sweep dọn bản ghi hết hạn", n >= 1 and not any(x["token"] == tok_img for x in FM._load_shares()), n)
    check("G3 dọn xong vẫn 410 (bia mộ)", pub.get(f"/s/{tok_img}/download").status_code == 410)
    check("G4 link 1440 phút vẫn sống", pub.get(f"/s/{tok_big}/download", headers={"Range": "bytes=0-0"}).status_code == 206)
finally:
    time.time = _real_time
check("G5 token lạ → 404", pub.get("/s/khongcoma/download").status_code == 404)

# ── H. file bị thay sau khi tạo link → 410 ────────────────────────────────────
swap = mk("content_studio/outputs/exports/swap.png")
tok_sw = share({"path": swap})
check("H1 trước khi thay: 200", pub.get(f"/s/{tok_sw}/download").status_code == 200)
Path(swap).write_bytes(b"<html><script>evil()</script></html>")
check("H2 nội dung đổi thành html → 410, không phục vụ", pub.get(f"/s/{tok_sw}/raw").status_code == 410)

# ── I. tắt ô «Allow public share links» → link đang sống 410 ─────────────────
tok17 = share({"path": VIDEO}, grant=17)
tok18 = share({"path": VIDEO}, grant=18)
st, out = run(CC.handle({"rpc": {"method": "shares/revoke", "params": {}}, "level": "write", "grant": 17}, app))
check("I1 cloud gọi shares/revoke cho kết nối 17 → thu hồi", st == 200 and out["result"]["revoked"] >= 1, out)
check("I2 link của 17 → 410, link của 18 còn sống", pub.get(f"/s/{tok17}/download").status_code == 410
      and pub.get(f"/s/{tok18}/download").status_code == 200)
st, body = handle("share_list", {}, perms=(), grant=18)
check("I3 lời gọi của 18 không còn quyền → share_* báo lỗi rõ + link của 18 chết ngay (lưới an toàn)",
      body["result"]["isError"] and "Allow public share links" in txt(body["result"])
      and pub.get(f"/s/{tok18}/download").status_code == 410)
st, out = run(CC.handle({"rpc": {"method": "shares/revoke", "params": {}}, "level": "write"}, app))
check("I4 shares/revoke thiếu grant → 400", st == 400)

# ── J. share_list / share_revoke / nút thu hồi File Manager ──────────────────
tj = share({"path": IMG})
owner = {"token": "ownerLinkXYZ", "path": mk("downloads/private.pdf", b"%PDF-1.4"), "name": "private.pdf",
         "created": time.time(), "expires": None, "downloads": 0}
FM._save_shares(FM._load_shares() + [owner])
st, body = handle("share_list", {})
t = txt(body["result"])
check("J1 share_list: link của Claude, không có link chủ tự tạo", tj in t and "ownerLinkXYZ" not in t, t[:300])
st, body = handle("share_revoke", {"token": "ownerLinkXYZ"})
check("J2 không thu hồi được link chủ tự tạo", body["result"]["isError"] and any(x["token"] == "ownerLinkXYZ" for x in FM._load_shares()))
st, body = handle("share_revoke", {"token": tj})
check("J3 share_revoke → 410", not body["result"]["isError"] and pub.get(f"/s/{tj}").status_code == 410)
tk = share({"path": IMG})
run(FM.revoke_share(tk))
check("J4 nút thu hồi của File Manager vẫn chạy → 410", pub.get(f"/s/{tk}/download").status_code == 410)
r = pub.get("/s/ownerLinkXYZ/download")
check("J5 link chủ tự tạo (PDF) không bị luật ảnh/video chặn", r.status_code == 200, r.status_code)

# ── K. giới hạn mỗi giờ ───────────────────────────────────────────────────────
PS.RATE_PER_HOUR, _old = 3, PS.RATE_PER_HOUR
try:
    res = [handle("share_file", {"path": IMG}, grant=99)[1]["result"] for _ in range(4)]
    check("K1 kết nối 99: 3 link rồi báo quá giới hạn", [bool(x.get("isError")) for x in res] == [False, False, False, True]
          and "per hour" in txt(res[3]), [txt(x)[:80] for x in res])
    check("K2 kết nối khác không bị ảnh hưởng", not handle("share_file", {"path": IMG}, grant=98)[1]["result"].get("isError"))
finally:
    PS.RATE_PER_HOUR = _old

# ── L. nhật ký ────────────────────────────────────────────────────────────────
log = PS.read_log(1000)
check("L1 nhật ký có lần tạo (giờ, kết nối, file)", any(x["event"] == "create" and x.get("grant") == 17 and x.get("file")
                                                     and x.get("at") for x in log))
check("L2 nhật ký có lần tải kèm IP", any(x["event"] == "download" and "ip" in x and x.get("file") for x in log))
check("L3 nhật ký có thu hồi do tắt quyền", any(x["event"] == "connection_off" for x in log))

# ── N. routes.py chạy trên lõi CŨ (hot-patch của cloud, public_share bản cũ) ──
_orig_ps_new = FM._ps_new
FM._ps_new = lambda: None
try:
    old = {"token": "oldCoreTok", "path": IMG, "name": "x.png", "created": time.time(), "expires": time.time() - 5, "downloads": 0}
    old2 = dict(old, token="oldCoreTok2", expires=None)
    FM._save_shares(FM._load_shares() + [old, old2])
    check("N1 lõi cũ: link hết hạn → 410, không lỗi 500", pub.get("/s/oldCoreTok/download").status_code == 410)
    check("N2 lõi cũ: link sống → 200", pub.get("/s/oldCoreTok2/download").status_code == 200)
    r = run(FM.revoke_share("oldCoreTok2"))
    check("N3 lõi cũ: nút thu hồi vẫn chạy", r["removed"] and pub.get("/s/oldCoreTok2/download").status_code == 404)
    check("N4 lõi cũ: danh sách chia sẻ vẫn mở", run(FM.list_shares())["success"])
finally:
    FM._ps_new = _orig_ps_new

# ── M. hằng số ────────────────────────────────────────────────────────────────
check("M1 SHAREABLE_TYPES: đúng ảnh + video, không svg", set(PS.SHAREABLE_EXTS) == {".png", ".jpg", ".jpeg", ".webp", ".gif",
                                                                                ".mp4", ".webm", ".mov"})

pub.close()
shutil.rmtree(D, ignore_errors=True)
shutil.rmtree(OUTSIDE, ignore_errors=True)
print(f"\n{checks - fails}/{checks} PASS")
sys.exit(1 if fails else 0)
