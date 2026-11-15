"""Sao lưu ảnh/video Content Studio lên Google Drive qua trình kết nối — cửa hẹp (core/drive_backup.py + công cụ drive_*).

Chạy:  python tests/drive_backup_test.py      (mã thoát 0 = đạt)

Vì sao (user 15/11/2026): giao agent MCP «sao lưu video Content Studio lên Drive» — bị chặn vì File Manager/Drive đóng
với trình kết nối. Chủ chọn: mở MỘT công cụ hẹp, chỉ ảnh/video trong thư mục Content Studio, có ô đồng ý riêng.

Cách ly: thư mục Content Studio, trạng thái và báo cáo đều ở thư mục tạm; Google Drive là đồ giả trong bộ nhớ; không mạng,
không đụng data thật.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:400]}")


from tubecli.core import drive_backup as DB  # noqa: E402
from tubecli.core import public_share as PS  # noqa: E402
from tubecli.core import claude_connector as CC  # noqa: E402
from tubecli.extensions.content_video import drive_export as DX  # noqa: E402
from tubecli.extensions.codex_gpt import tools as T  # noqa: E402

TMP = os.path.realpath(tempfile.mkdtemp(prefix="drive_bk_"))
STUDIO = os.path.join(TMP, "data", "extensions_data", "content_studio")
EXPORTS = os.path.join(STUDIO, "outputs", "exports")
os.makedirs(os.path.join(EXPORTS, "episode_1_scenes"))
os.makedirs(os.path.join(STUDIO, "hook_videos"))
os.makedirs(os.path.join(TMP, "outside"))


def put(path, size):
    with open(path, "wb") as f:
        f.write(b"\0" * size)


put(os.path.join(EXPORTS, "small.mp4"), 100)
put(os.path.join(EXPORTS, "big.mp4"), 900)
put(os.path.join(EXPORTS, "mid.mp4"), 500)
put(os.path.join(EXPORTS, "fake.mp4"), 50)                 # đuôi video nhưng không phải video thật
put(os.path.join(EXPORTS, "notes.json"), 10)
put(os.path.join(EXPORTS, "episode_1_scenes", "scene.mp4"), 70)
put(os.path.join(STUDIO, "hook_videos", "ep1_hook.mp4"), 30)
put(os.path.join(STUDIO, "hook_videos", "ep1_shot2.mp4"), 30)
put(os.path.join(TMP, "outside", "secret.mp4"), 10)


def fake_resolve(raw=None, collection=None, filename=None):
    p = os.path.realpath(str(raw))
    if os.path.basename(p) == "fake.mp4":
        raise PS.ShareRefused("not a real video")
    return p, "video", "video/mp4"


PS.resolve = fake_resolve
DB.studio_root = lambda: STUDIO
DB._state_dir = lambda: (os.makedirs(os.path.join(TMP, "state"), exist_ok=True) or os.path.join(TMP, "state"))
DB._report_dir = lambda: (os.makedirs(os.path.join(TMP, "reports"), exist_ok=True) or os.path.join(TMP, "reports"))
DB.accounts = lambda: [{"email": "owner@example.com", "token_id": "tok1", "status": "active"}]
DB.time.sleep = lambda s: None


class FakeDrive:
    """Một «Drive» trong bộ nhớ: {folder_id: {tên: {id, size}}}."""

    def __init__(self):
        self.folders = {"root": {}}
        self.created = []
        self.order = []
        self.fail = {}          # tên → số lần còn phải hỏng
        self.quota_on = ""      # tên file làm đầy Drive


G = FakeDrive()
DX.services = lambda token_id: (G, None)


def _find_or_create(drive, parent, name):
    key = f"{parent}/{name}"
    if key not in G.folders:
        G.folders[key] = {}
        G.created.append(name)
    return {"id": key, "name": name}


def _upload(drive, path, name, parent, on_progress=None, cancelled=None, cancel_exc=None):
    G.order.append(name)
    if G.quota_on == name:
        raise RuntimeError("HttpError 403 storageQuotaExceeded: The user's Drive storage quota has been exceeded")
    if G.fail.get(name, 0) > 0:
        G.fail[name] -= 1
        raise RuntimeError("HttpError 503 backendError")
    size = os.path.getsize(path)
    G.folders[parent][name] = {"id": f"id_{name}", "size": str(size), "name": name}
    return G.folders[parent][name]


DX.find_or_create_folder = _find_or_create
DX.list_children = lambda drive, folder_id: dict(G.folders.get(folder_id, {}))
DX.upload_file = _upload
DB._quota_free = lambda drive: 10 ** 12


def run(**kw):
    job = DB.start(kw.pop("account", "owner@example.com"), kw.pop("source", "outputs/exports"),
                   kw.pop("folder", "Archive/TubeCLI exports"), **kw)
    DB._THREADS[job["id"]].join(20)
    return job


def refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return ""
    except DB.BackupRefused as e:
        return str(e)


# ── A. phạm vi ────────────────────────────────────────────────────────────────
check("A1 thư mục ngoài Content Studio → từ chối", "outside" in refused(DB.resolve_source, os.path.join(TMP, "outside")))
check("A2 «..» thoát ra ngoài → từ chối", "outside" in refused(DB.resolve_source, "../../../outside"))
check("A3 đường tương đối trong Content Studio → nhận", DB.resolve_source("outputs/exports") == os.path.realpath(EXPORTS))
check("A4 đường tuyệt đối trong Content Studio → nhận", DB.resolve_source(os.path.join(STUDIO, "hook_videos")).endswith("hook_videos"))
rows, skipped = DB.scan(os.path.realpath(EXPORTS), "*.mp4")
check("A5 chỉ file nằm TRỰC TIẾP, là ảnh/video thật: không vào thư mục con, bỏ .json, bỏ video giả",
      sorted(r["name"] for r in rows) == ["big.mp4", "mid.mp4", "small.mp4"] and skipped == 1, (rows, skipped))
rows, _ = DB.scan(os.path.join(STUDIO, "hook_videos"), "EP*_hook.mp4")
check("A6 mẫu tên không phân biệt hoa thường; ep*_shot* không lọt", [r["name"] for r in rows] == ["ep1_hook.mp4"], rows)
check("A7 tài khoản lạ → từ chối, kể tên tài khoản có sẵn", "owner@example.com" in refused(DB.pick_account, "x@evil.com"))
check("A8 thư mục Drive: bắt buộc, tối đa 6 cấp", refused(DB.folder_parts, "") and refused(DB.folder_parts, "a/b/c/d/e/f/g")
      and DB.folder_parts(" A / B ") == ["A", "B"])

# ── B. một lượt sao lưu ───────────────────────────────────────────────────────
job = run(pattern="*.mp4")
check("B1 xong, đủ 3 file, không lỗi", job["status"] == "done" and job["uploaded"] == 3 and job["failed"] == 0, job)
check("B2 tải TỪNG file, file lớn trước", G.order == ["big.mp4", "mid.mp4", "small.mp4"], G.order)
check("B3 tạo đủ thư mục con trên Drive", G.created == ["Archive", "TubeCLI exports"] and job["folder_id"] == "root/Archive/TubeCLI exports")
rep = open(job["report"], encoding="utf-8").read()
check("B4 báo cáo: tên, dung lượng, Drive file ID, OK + tổng máy / Drive + «không xoá gì»",
      "OK\t900\tid_big.mp4\tbig.mp4" in rep and "3 files, 1500 bytes" in rep and "Nothing was deleted" in rep, rep)
check("B5 file trên máy còn nguyên", all(os.path.isfile(os.path.join(EXPORTS, n)) for n in ("big.mp4", "mid.mp4", "small.mp4")))

G.order.clear()
job = run(pattern="*.mp4")
check("B6 chạy lại: file cùng tên cùng dung lượng được BỎ QUA, không tải lại", job["already"] == 3 and job["uploaded"] == 0
      and G.order == [], (job["already"], G.order))

# ── C. lỗi ────────────────────────────────────────────────────────────────────
G.folders.clear()
G.folders["root"] = {}
G.order.clear()
G.fail = {"mid.mp4": 2}
job = run(pattern="*.mp4")
check("C1 hỏng 2 lần rồi được ở lần thứ 3 (thử lại tối đa 2 lần)", job["status"] == "done" and G.order.count("mid.mp4") == 3, G.order)

G.folders.clear()
G.folders["root"] = {}
G.order.clear()
G.fail = {"mid.mp4": 99}
job = run(pattern="*.mp4")
bad = [r for r in job["files"] if r["status"] == "error"]
check("C2 hỏng cả 3 lượt → ghi lỗi, VẪN làm tiếp file khác", job["status"] == "done_with_errors" and len(bad) == 1
      and bad[0]["name"] == "mid.mp4" and G.order.count("mid.mp4") == 3 and job["uploaded"] == 2, (job["status"], G.order))
check("C3 báo cáo ghi ERROR cho file đó", "ERROR\t500\t-\tmid.mp4" in open(job["report"], encoding="utf-8").read())

G.folders.clear()
G.folders["root"] = {}
G.order.clear()
G.fail = {}
G.quota_on = "mid.mp4"
job = run(pattern="*.mp4")
check("C4 Drive đầy → DỪNG ngay (không thử lại, không tải tiếp), nói rõ", job["status"] == "stopped" and "full" in job["note"]
      and G.order == ["big.mp4", "mid.mp4"] and [r["status"] for r in job["files"]] == ["ok", "error", "pending"], (job["status"], G.order))
G.quota_on = ""

check("C5 không file nào khớp → từ chối, không tạo việc", "No image or video" in refused(DB.start, "owner@example.com", "outputs/exports", "X", "*.avi"))

# ── D. mỗi lúc một việc ───────────────────────────────────────────────────────
gate = {"go": False}


def slow(job):
    job["status"] = "running"
    while not gate["go"]:
        time.sleep(0.01)
    job["status"] = "done"


time.sleep = time.sleep
first = DB.start("owner@example.com", "outputs/exports", "Y", "*.mp4", runner=slow)
check("D1 đang có việc chạy → việc thứ hai bị từ chối", "still running" in refused(DB.start, "owner@example.com", "hook_videos", "Z"))
gate["go"] = True
DB._THREADS[first["id"]].join(5)
s = DB.summary(DB.get(first["id"]), files=True)
check("D2 trạng thái gọn: có số đếm, không lộ token_id", s["total"] == 3 and "token_id" not in s and len(s["files"]) == 3, s)

# ── E. công cụ của trình kết nối ──────────────────────────────────────────────
names = ("drive_accounts", "drive_backup", "drive_backup_status", "drive_backup_cancel")
check("E1 bốn công cụ drive_* có mặt, đều đòi quyền «drive»", all(n in T.TOOLS and T.TOOLS[n].perm == "drive" for n in names))
check("E2 trình kết nối nhận quyền «drive» từ cloud", "drive" in CC.PERMS and "share" in CC.PERMS)


async def _yes(*a, **k):
    return True, "", None


r = asyncio.run(T.call_tool("drive_backup", {"account": "owner@example.com", "source": "outputs/exports", "folder": "Q"},
                            None, _yes, perms=()))
check("E3 chưa bật quyền → từ chối, chỉ chỗ bật trên Cloud › Connectors", r.get("isError") and "Allow Google Drive backup" in str(r), r)
r = asyncio.run(T.call_tool("drive_backup", {"account": "owner@example.com", "source": os.path.join(TMP, "outside"),
                                              "folder": "Q"}, None, _yes, perms=("drive",)))
check("E4 có quyền nhưng nguồn ngoài Content Studio → từ chối", r.get("isError") and "outside" in str(r), r)
r = asyncio.run(T.call_tool("drive_backup", {"account": "owner@example.com", "source": "hook_videos", "folder": "Hooks",
                                              "pattern": "ep*_hook.mp4"}, None, _yes, perms=("drive",)))
check("E5 có quyền + hợp lệ → chạy nền, trả mã việc", not r.get("isError") and "bk_" in str(r), r)
DB._THREADS[DB.get()["id"]].join(10)
r = asyncio.run(T.call_tool("drive_backup_status", {"files": True}, None, _yes, perms=("drive",)))
check("E6 drive_backup_status: 1 file ep1_hook.mp4 đã lên, kèm Drive file id", "id_ep1_hook.mp4" in str(r) and "ep1_shot2" not in str(r), r)
check("E7 File Manager và Drive VẪN bị chặn với trình kết nối", T.api_blocked("POST", "/api/v1/file-manager/drive/upload")
      and T.api_blocked("GET", "/api/v1/files/list"))

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
