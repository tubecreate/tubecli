"""Chia sẻ file kết quả bằng link công khai qua trình kết nối claude.ai (codex_gpt/tools.py share_*) — 4/11/2026.

Chạy:  python tests/share_tools_test.py      (mã thoát 0 = đạt)

User: «trên file manager của tubecli có tính năng share file public … được làm như đề xuất đi, và cho phép cấp quyền
trong cài đặt kết nối». Khoá: File Manager vẫn bị chặn cho công cụ; chỉ chia sẻ FILE KẾT QUẢ trong vài thư mục cố định,
đuôi media/tài liệu, không thư mục, không thoát ra ngoài bằng ../ hay symlink; share_file LUÔN hỏi chủ, link có hạn; mọi
công cụ share_* chỉ chạy khi kết nối mang quyền «share» (cloud gửi kèm), Codex trên máy không thấy chúng. Chạy route File
Manager THẬT trên DATA_DIR tạm.
"""
import asyncio
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
CFG.DATA_DIR = D
os.environ["TUBECLI_PUBLIC_URL"] = "https://box.example.com"

from fastapi import FastAPI  # noqa: E402
from tubecli.core import claude_connector as CC  # noqa: E402
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402
from tubecli.extensions.file_manager import routes as FM  # noqa: E402

checks = fails = 0


def check(name, ok, detail=""):
    global checks, fails
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails += 1


def mk(rel, data=b"x" * 2048):
    p = D / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


VIDEO = mk("content_studio/outputs/exports/toan1_bai1_minhhoa.mp4")
time.sleep(0.02)
IMG = mk("content_studio/api_images/scene_03.png")
SECRET = mk("cloud_api_keys.json", b'{"k":"secret"}')
NOTMEDIA = mk("content_studio/outputs/exports/settings.json", b"{}")
mk("content_studio/outputs/.hidden/x.mp4")
os.makedirs(D / "content_studio/outputs/folder.mp4", exist_ok=True)
LINK = str(D / "content_studio/outputs/exports/link_to_keys.mp4")
try:
    os.symlink(SECRET, LINK)
    HAVE_LINK = True
except (OSError, NotImplementedError):
    HAVE_LINK = False

app = FastAPI()
for r in FM.router:
    app.include_router(r)
txt = lambda res: "\n".join(c.get("text", "") for c in (res.get("content") or []))   # noqa: E731
run = lambda coro: asyncio.get_event_loop().run_until_complete(coro)                 # noqa: E731
OK = ("share",)

# ── A. đăng ký + quyền ────────────────────────────────────────────────────────
names = ["share_find", "share_file", "share_list", "share_revoke"]
check("A1 bốn công cụ share_* có, đều cần quyền «share»", all(T.TOOLS[n].perm == "share" for n in names))
check("A2 share_file: ghi + LUÔN hỏi chủ + có kế hoạch cho thẻ duyệt",
      T.TOOLS["share_file"].is_write({}) and T.TOOLS["share_file"].asks_always({}) and T.TOOLS["share_file"].plan is not None)
check("A3 Codex trên máy không thấy share_* (không có quyền thêm)", not any(t["name"] in names for t in T.list_tools()))
check("A4 trình kết nối liệt kê share_* (mức ghi)", all(n in {t["name"] for t in CC.list_tools("write")} for n in names))
check("A5 File Manager vẫn bị chặn với tubecli_api",
      T.api_blocked("POST", "/api/v1/file-manager/share") and T.api_blocked("GET", "/api/v1/file-manager/shares"))
r = run(T.call_tool("share_find", {}, app, CC._yes, agent=CC.AGENT))
check("A6 không có quyền → từ chối, chỉ đường bật trong TubeCLI Cloud › Connectors",
      r["isError"] and "Connectors" in txt(r) and "Allow public share links" in txt(r), txt(r))
out = run(CC.call("share_file", {"path": VIDEO}, "write", False, app, perms=()))
check("A7 trình kết nối thiếu quyền → từ chối NGAY, không tạo thẻ duyệt", "needs_approval" not in out and out["result"]["isError"])
out = run(CC.call("share_file", {"path": VIDEO}, "read", False, app, perms=OK))
check("A8 kết nối chỉ-đọc có quyền share vẫn không tạo link được", "needs_approval" not in out and out["result"]["isError"]
      and "read-only" in txt(out["result"]), out)

# ── B. tìm file ───────────────────────────────────────────────────────────────
r = run(T.call_tool("share_find", {}, app, CC._yes, agent=CC.AGENT, perms=OK))
body = txt(r)
rows = json.loads(body[body.index("["):])
paths = [x["path"] for x in rows]
check("B1 liệt kê video + ảnh kết quả, mới nhất trước — symlink ra tệp khoá không hiện",
      not r["isError"] and paths == [os.path.realpath(IMG), os.path.realpath(VIDEO)], paths)
check("B2 không lộ tệp ngoài thư mục kết quả, tệp không phải media, thư mục ẩn",
      not any(p.endswith(("cloud_api_keys.json", "settings.json")) or ".hidden" in p for p in paths), paths)
r = run(T.call_tool("share_find", {"kind": "video", "query": "minhhoa"}, app, CC._yes, agent=CC.AGENT, perms=OK))
check("B3 lọc theo loại + tên", "toan1_bai1_minhhoa.mp4" in txt(r) and "scene_03" not in txt(r), txt(r))

# ── C. chặn đường ra ngoài ────────────────────────────────────────────────────
for label, p in [("tệp khoá ngoài thư mục kết quả", SECRET),
                 ("../ thoát ra ngoài", str(D / "content_studio/outputs/../../cloud_api_keys.json")),
                 ("tệp không phải media", NOTMEDIA),
                 ("thư mục", str(D / "content_studio/outputs/folder.mp4")),
                 ("không tồn tại", str(D / "content_studio/outputs/nope.mp4"))]:
    out = run(CC.call("share_file", {"path": p}, "write", False, app, perms=OK))
    check(f"C {label} → từ chối trước thẻ duyệt", "needs_approval" not in out and out["result"]["isError"], out)
if HAVE_LINK:
    out = run(CC.call("share_file", {"path": LINK}, "write", False, app, perms=OK))
    check("C symlink trỏ ra tệp khoá → từ chối", "needs_approval" not in out and out["result"]["isError"], out)
else:
    print("[SKIP] máy này không tạo được symlink")

# ── D. tạo link: thẻ duyệt → chủ duyệt → link công khai có hạn ─────────────────
out = run(CC.call("share_file", {"path": VIDEO, "expires_days": 99}, "write", False, app, perms=OK))
na = out.get("needs_approval") or {}
check("D1 có quyền → thẻ duyệt ghi tên, dung lượng, PUBLIC, số ngày (99 → tối đa 30)",
      na.get("tool") == "share_file" and "PUBLIC" in na.get("summary", "") and "toan1_bai1_minhhoa.mp4" in na.get("summary", "")
      and "2 KB" in na.get("summary", "") and "30 day" in na.get("summary", ""), na)
check("D2 chưa duyệt thì chưa có link nào", not (D / "file_manager" / "shares.json").exists()
      or not json.loads((D / "file_manager" / "shares.json").read_text(encoding="utf-8")).get("shares"))
out = run(CC.call("share_file", {"path": VIDEO}, "write", True, app, perms=OK))
res = out.get("result") or {}
t = txt(res)
check("D3 chủ duyệt → link https công khai đầy đủ", not res.get("isError") and "https://box.example.com/s/" in t, t)
sh = json.loads((D / "file_manager" / "shares.json").read_text(encoding="utf-8"))["shares"]
check("D4 sổ chia sẻ của File Manager: đúng file, có hạn ~7 ngày", len(sh) == 1 and sh[0]["path"] == os.path.normpath(VIDEO)
      and 6.9 * 86400 < sh[0]["expires"] - time.time() < 7.1 * 86400, sh)
from fastapi.testclient import TestClient  # noqa: E402
pub = FastAPI()
pub.include_router(FM.router_public)
tok = sh[0]["token"]
pr = TestClient(pub).get(f"/s/{tok}")
check("D5 trang /s/<mã> mở được, không lộ đường dẫn máy chủ", pr.status_code == 200 and str(D) not in pr.text, pr.status_code)
out = run(CC.call("share_file", {"path": VIDEO}, "write", True, app, perms=OK))
check("D6 chia sẻ lại cùng file → trả link cũ, nói rõ", "already had a link" in txt(out["result"]) and tok in txt(out["result"]))

# ── E. liệt kê + thu hồi ──────────────────────────────────────────────────────
other = mk("downloads/private.mp4")
lst = FM._load_shares()
lst.append({"token": "ownerLinkXYZ", "path": other, "name": "private.mp4", "created": time.time(), "expires": None, "downloads": 0})
FM._save_shares(lst)
r = run(T.call_tool("share_list", {}, app, CC._yes, agent=CC.AGENT, perms=OK))
check("E1 share_list: chỉ link của file kết quả (link chủ tự tạo cho file khác không hiện)",
      tok in txt(r) and "ownerLinkXYZ" not in txt(r) and "private.mp4" not in txt(r), txt(r))
out = run(CC.call("share_revoke", {"token": "ownerLinkXYZ"}, "write", False, app, perms=OK))
check("E2 không thu hồi được link chủ tự tạo cho file khác", out["result"]["isError"]
      and any(s["token"] == "ownerLinkXYZ" for s in FM._load_shares()))
out = run(CC.call("share_revoke", {"token": tok}, "write", False, app, perms=OK))
check("E3 thu hồi link của mình: chạy luôn, link chết", not out["result"]["isError"]
      and not any(s["token"] == tok for s in FM._load_shares()) and TestClient(pub).get(f"/s/{tok}").status_code == 404,
      out)

# ── F. cloud gửi quyền: handle() đọc «perms», bỏ quyền lạ ──────────────────────
CC.enabled = lambda: True
st, body = run(CC.handle({"rpc": {"method": "tools/call", "params": {"name": "share_list", "arguments": {}}},
                          "level": "write", "perms": ["share", "root"]}, app))
check("F1 handle: perms=[share] → chạy", st == 200 and not body["result"]["isError"], body)
st, body = run(CC.handle({"rpc": {"method": "tools/call", "params": {"name": "share_list", "arguments": {}}},
                          "level": "write", "perms": "share"}, app))
check("F2 handle: perms sai kiểu → coi như không có quyền", st == 200 and body["result"]["isError"], body)
st, body = run(CC.handle({"rpc": {"method": "tools/call", "params": {"name": "share_list", "arguments": {}}},
                          "level": "write"}, app))
check("F3 cloud cũ (không gửi perms) → từ chối", body["result"]["isError"])

shutil.rmtree(D, ignore_errors=True)
print(f"\n{checks - fails}/{checks} PASS")
sys.exit(1 if fails else 0)
