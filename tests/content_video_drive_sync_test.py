# -*- coding: utf-8 -*-
"""Đồng bộ một task video ĐÃ XONG lên Google Drive — nút trên thẻ Codex (16/9/2026).

User: "các task chưa up drive nếu muốn upload lên drive, bên cạnh button delete thêm button sync lên drive, bấm vào
chọn drive để đồng bộ project lên / ở button delete thêm delete + đồng bộ lên drive (hoặc chỉ delete, delete file là
xoá luôn project trong content studio)".

Kiểm:
  A. drive_sync_info: không có task / task chỉ viết kịch bản / không phải video / đang chạy / mất video / được
  B. create_drive_sync_task: task «Drive: …» không cần duyệt, payload kind content_video.drive trỏ về task gốc
  C. run_kind chuyển đúng sang run_drive_sync
  D. run_drive_sync: tải project lên, checkpoint (thư mục, Sheet) ghi vào TASK GỐC, kết quả có dòng Google Drive
  E. đồng bộ lại: dùng lại thư mục, không tải lại
  F. đồng bộ rồi xoá: xoá task gốc (purge) SAU khi tải xong, kết quả nói số file + project Studio đã xoá
  G. tải hỏng: ném lỗi, KHÔNG xoá task gốc
  H. video gốc đã mất: báo rõ
  I. route: hỏi trước, kiểm tài khoản ngay, chặn khách của không gian chia sẻ
  J. (16/9/2026) "những task đã upload driver thì đánh dấu đã upload drive màu xanh": tải xong → dấu trên TASK GỐC;
     lượt quét task cũ đọc checkpoint một lần (dấu rỗng = đã kiểm)
  K. CodexManager.set_drive thật: ghi ở mọi trạng thái, chỉ giữ link/tài khoản/số file, không đổi updated_at

Run:  python tests/content_video_drive_sync_test.py     (exit 0 = pass)
"""
import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cv_dsync_"))
CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_EXTERNAL_DIR = CFG.DATA_DIR / "extensions_external"
# PHẢI đổi cả EXTENSIONS_DATA_DIR: import tubecli.core.agent tạo junction DATA_DIR → EXTENSIONS_DATA_DIR
# (xem tests/content_video_drive_test.py — đã từng ghi file giả vào kho thật).
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
_TMP_REAL = os.path.realpath(str(TMP))


def _inside_tmp(p) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(str(p)), _TMP_REAL]) == _TMP_REAL
    except ValueError:
        return False


from fastapi import HTTPException  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.extensions.content_video import drive_export as DX  # noqa: E402
from tubecli.extensions.content_video import routes as R  # noqa: E402
import tubecli.core.agent as AG  # noqa: E402
import tubecli.extensions.codex.manager as CM  # noqa: E402

P._put = lambda *a, **k: {}

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:400])


DD = CFG.DATA_DIR
if DD.exists():
    _escaped = [str(c) for c in DD.iterdir() if not _inside_tmp(c)]
    if _escaped:
        print("ABORT — DATA_DIR tạm có link trỏ ra ngoài thư mục tạm:", _escaped[:5])
        sys.exit(2)


def mk(rel, size):
    p = DD / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if not _inside_tmp(p.parent):
        print("ABORT — sắp ghi ra ngoài thư mục tạm:", p)
        sys.exit(2)
    p.write_bytes(b"x" * size)
    return str(p)


MP4 = mk("content_studio/outputs/exports/episode_21_pipeline_export.mp4", 3000)
mk("content_studio/outputs/exports/episode_21_pipeline_main.mp4", 2000)
IMG = mk("content_studio/grok_images/ep21_1.png", 50)
AUD = mk("content_video/audio/ep21/shot001.mp3", 70)
MP4B = mk("content_studio/outputs/exports/episode_22_pipeline_export.mp4", 1000)
SHOTS = [{"id": 1, "storyboard_number": 1, "image_prompt": "zen garden", "video_prompt": "slow pan",
          "narration_text": "Hola", "composed_image": IMG, "tts_audio_url": AUD, "duration": 5}]
P._storyboards = lambda ep: [dict(s) for s in SHOTS]
P.media_seconds = lambda p: 3.0
P._agent_scope = lambda agent: ["p1"]
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}


def fake_get(path, timeout=60):
    if path.startswith("/api/v1/studio/dramas/5/"):
        return {"items": []}
    raise AssertionError(f"test chặn HTTP thật: {path}")


P._get = fake_get

TOKENS = [
    {"token_id": "tok_a", "credential_id": "cred_a", "authorized_email": "a@x.com", "scopes": ["drive"], "status": "active"},
    {"token_id": "tok_ro", "credential_id": "cred_r", "authorized_email": "ro@x.com", "scopes": ["drive_readonly"], "status": "active"},
]


class FakeDrive:
    def __init__(self):
        self.files, self.n, self.calls = {}, 0, []

    def add(self, name, parent, mime="", size=None):
        self.n += 1
        fid = f"f{self.n}"
        self.files[fid] = {"id": fid, "name": name, "parent": parent, "mimeType": mime,
                           "size": None if size is None else str(size),
                           "webViewLink": f"https://drive.google.com/{fid}", "trashed": False}
        return dict(self.files[fid])

    def children(self, parent):
        out = {}
        for f in self.files.values():
            if f["parent"] == parent and not f["trashed"]:
                out.setdefault(f["name"], dict(f))
        return out


FD = FakeDrive()
FAIL_UPLOAD = {"on": False}


def fake_upload(drive, path, name, parent, on_progress=None, cancelled=None, cancel_exc=None):
    FD.calls.append(("upload", name))
    if FAIL_UPLOAD["on"]:
        raise RuntimeError("<HttpError 403 storageQuotaExceeded>")
    size = os.path.getsize(path)
    if on_progress:
        on_progress(size)
    return FD.add(name, parent, "", size)


DX.google_tokens = lambda: [dict(t) for t in TOKENS]
DX.services = lambda tid: ("drive", "sheets")
DX.file_alive = lambda drive, fid: (dict(FD.files[fid], parents=[FD.files[fid]["parent"]])
                                    if fid in FD.files and not FD.files[fid]["trashed"] else None)


def fake_find_or_create(drive, parent, name):
    hit = [f for f in FD.files.values() if f["name"] == name and f["parent"] == parent and not f["trashed"]
           and f["mimeType"] == DX.FOLDER_MIME]
    return dict(hit[0]) if hit else (FD.calls.append(("folder", name)) or FD.add(name, parent, DX.FOLDER_MIME))


DX.find_or_create_folder = fake_find_or_create
DX.my_drive_root_id = lambda drive: "root"
DX.move_folder = lambda drive, fid, new_parent, old: FD.calls.append(("move", fid)) or FD.files[fid].update(parent=new_parent)
P._drive_root_name = lambda: "tuan89tk-vps-k7m2qx"
DX.unique_name = lambda drive, parent, name: name
DX.create_folder = lambda drive, name, parent="root": FD.calls.append(("folder", name)) or FD.add(name, parent, DX.FOLDER_MIME)
DX.list_children = lambda drive, fid: FD.children(fid)
DX.upload_file = fake_upload
DX.trash_file = lambda drive, fid: FD.files[fid].update(trashed=True)
DX.create_sheet = lambda drive, name, parent: FD.calls.append(("sheet", name)) or FD.add(name, parent, DX.SHEET_MIME)
DX.write_sheet = lambda sheets, sid, tabs, widths=None: FD.calls.append(("write_sheet", sid))
DX.share_public = lambda drive, fid: FD.calls.append(("share", fid))


class Agent:
    id, name, system_prompt = "a1", "Orchestrator", ""


AG.agent_manager.get = lambda aid: Agent() if aid == "a1" else None

TASKS = {
    "src": {"id": "src", "seq": 21, "status": "done", "assignee_id": "a1", "assignee_name": "Orchestrator",
            "created_by": "user", "origin": {"chat_id": "9"}, "title": "Video from content: Orchestrator"},
    "src2": {"id": "src2", "seq": 22, "status": "review", "assignee_id": "a1", "assignee_name": "Orchestrator",
             "created_by": "autopublish", "origin": {}, "title": "Video from content: Orchestrator"},
    "plan": {"id": "plan", "seq": 20, "status": "review", "assignee_id": "a1"},
    "busy": {"id": "busy", "seq": 23, "status": "running", "assignee_id": "a1"},
    "novid": {"id": "novid", "seq": 24, "status": "done", "assignee_id": "a1"},
    "other": {"id": "other", "seq": 25, "status": "done", "assignee_id": "a1"},
}
KINDS = {"src": P.KIND_AUTO, "src2": P.KIND_RENDER, "plan": P.KIND_PLAN, "busy": P.KIND_RENDER,
         "novid": P.KIND_RENDER, "other": "video_studio.reup"}
CK = {"src": {"video_path": MP4, "title": "10 Claves Zen", "episode_id": 21, "drama_id": 5, "script": "Hola",
              "language": "es", "seo_sources": [{"title": "src", "url": "https://youtu.be/abc"}]},
      "src2": {"video_path": MP4B, "title": "Siete Cambios", "episode_id": 21, "drama_id": 5},
      "busy": {"video_path": MP4}, "novid": {"video_path": str(DD / "gone.mp4")}}
P._read_checkpoint = lambda tid: dict(CK.get(tid) or {})
P._write_checkpoint = lambda tid, d: CK.__setitem__(tid, dict(d))
created, events, deleted = [], [], []


def fake_create_task(**k):
    tid = f"sync{len(created) + 1}"
    created.append(k)
    TASKS[tid] = {"id": tid, "seq": 30 + len(created), "status": "queued", **k}
    return dict(TASKS[tid])


def fake_delete(tid, purge=False, actor="user"):
    deleted.append((tid, purge, len([c for c in FD.calls if c[0] == "upload"])))
    return {"task": TASKS.get(tid), "purge": {"files": 12, "bytes": 5 * 1048576, "drama_hidden": True, "errors": []}}


CM.codex_manager.get_task = lambda tid: TASKS.get(tid)
CM.codex_manager.kind_of = lambda tid: KINDS.get(tid)
CM.codex_manager.create_task = fake_create_task
CM.codex_manager.append_event = lambda tid, kind, text, actor=None, data=None: events.append((tid, data or {}))
CM.codex_manager.delete = fake_delete
MARKS = {}
CM.codex_manager.set_drive = lambda tid, d: MARKS.__setitem__(tid, dict(d or {})) or {"id": tid}

print("── A. drive_sync_info ──────────────────────────────────────")
ok(P.drive_sync_info("nope")["reason"] == "not_found", "không có task")
ok(P.drive_sync_info("plan")["reason"] == "script_only" and not P.drive_sync_info("plan")["ok"],
   "task kế hoạch chỉ viết kịch bản → nói video nằm ở task dựng")
ok(P.drive_sync_info("other")["reason"] == "not_video", "không phải task video")
ok(P.drive_sync_info("busy")["reason"] == "busy", "task còn đang chạy → chờ xong")
ok(P.drive_sync_info("novid")["reason"] == "no_video", "file video đã mất → nói rõ")
info = P.drive_sync_info("src")
ok(info["ok"] and info["seq"] == 21 and info["title"] == "10 Claves Zen" and info["drive"] == {} and info["agent_id"] == "a1",
   "task tự động đã xong + còn video → được, có tiêu đề", info)
ok(P.drive_sync_info("src2")["ok"], "task DỰNG đang ở Review cũng đồng bộ được")

print("── B. create_drive_sync_task ───────────────────────────────")
task = P.create_drive_sync_task("src", "tok_a", True, False)
ev = events[-1][1]
ok(created[-1]["title"] == "Drive: 10 Claves Zen" and created[-1]["approval_required"] is False
   and "lane" not in created[-1] and created[-1]["assignee_id"] == "a1" and created[-1]["origin"] == {"chat_id": "9"},
   "task «Drive: tiêu đề», không cần duyệt, không chiếm làn video, cùng agent + nơi gọi", created[-1])
ok(ev == {"kind": P.KIND_DRIVE, "task_id": task["id"], "source_task_id": "src", "source_seq": 21, "agent_id": "a1",
          "options": {"drive": True, "drive_token_id": "tok_a", "drive_public": True, "delete_after": False}},
   "payload trỏ về task gốc + tài khoản + quyền", ev)
ok("Only after a successful upload" not in created[-1]["goal"], "không xoá → mục tiêu không nhắc xoá")
P.create_drive_sync_task("src", "tok_a", False, True)
ok("Only after a successful upload: task #21 is deleted" in created[-1]["goal"] and "private" in created[-1]["goal"],
   "đồng bộ rồi xoá → mục tiêu nói rõ chỉ xoá SAU khi tải xong", created[-1]["goal"])
try:
    P.create_drive_sync_task("plan", "tok_a")
    ok(False, "task kế hoạch phải bị từ chối")
except ValueError as e:
    ok("only wrote the script" in str(e), "task kế hoạch → từ chối kèm lý do")

print("── C. run_kind ─────────────────────────────────────────────")
_real_sync = P.run_drive_sync
P.run_drive_sync = lambda payload, report=None, is_cancelled=None: "SYNCED:" + payload["source_task_id"]
ok(P.run_kind(P.KIND_DRIVE, {"source_task_id": "src"}) == "SYNCED:src", "executor chuyển content_video.drive sang run_drive_sync")
P.run_drive_sync = _real_sync

print("── D. đồng bộ ──────────────────────────────────────────────")
said = []
PAY = {"task_id": "sync1", "source_task_id": "src", "source_seq": 21, "agent_id": "a1",
       "options": {"drive": True, "drive_token_id": "tok_a", "drive_public": True, "delete_after": False}}
out = P.run_drive_sync(dict(PAY), lambda *a: said.append(a), lambda: False)
ups = [c for c in FD.calls if c[0] == "upload"]
ok(out.startswith("## ✅ Task #21 synced to Google Drive") and "- **Google Drive**: https://drive.google.com/" in out
   and "anyone with the link can view and download" in out and "- **Title**: 10 Claves Zen" in out,
   "kết quả: dòng Google Drive + quyền + tiêu đề", out)
ok({c[1] for c in ups} == {"10 Claves Zen.mp4", "10 Claves Zen (no layout).mp4", "scene_001.png", "scene_001.mp3"},
   "tải đủ video, bản không bố cục, ảnh + giọng từng cảnh", ups)
ok(CK["src"].get("drive", {}).get("folder_id") and "drive" not in CK.get("sync1", {}),
   "thư mục + Sheet ghi vào checkpoint của TASK GỐC (đồng bộ lại mới dùng lại được)", list(CK))
_vps = [f for f in FD.files.values() if f["name"] == "tuan89tk-vps-k7m2qx" and f["parent"] == "root"]
ok(len(_vps) == 1 and FD.files[CK["src"]["drive"]["folder_id"]]["parent"] == _vps[0]["id"]
   and "(tuan89tk-vps-k7m2qx/10 Claves Zen)" in out,
   "đồng bộ task cũ cũng vào «tuan89tk-vps-k7m2qx/tiêu đề», kết quả ghi đường dẫn", out[:200])
ok(any(a[0] == "drive" and a[1] == "success" for a in said), "thẻ bước drive báo xong", said[-3:])
ok(deleted == [], "không chọn xoá → không xoá gì")
m = MARKS.get("src") or {}
ok(str(m.get("folder_url") or "").startswith("https://drive.google.com/") and m.get("email") == "a@x.com"
   and m.get("files") == 4 and "sync1" not in MARKS,
   "tải xong → dấu «đã lên Drive» trên TASK GỐC (thẻ tô xanh nút Drive), không phải task đồng bộ", MARKS)
ok(P.drive_sync_info("src")["drive"].get("token_id") == "tok_a", "hộp biết tài khoản lần trước → chọn sẵn đúng nó")
ok(P.drive_sync_info("src")["drive"]["folder_url"].startswith("https://drive.google.com/"),
   "lần mở hộp sau: biết task đã từng đồng bộ (hiện câu «đồng bộ lại»)")

print("── E. đồng bộ lại ──────────────────────────────────────────")
FD.calls.clear()
P.run_drive_sync(dict(PAY), None, lambda: False)
ok(not [c for c in FD.calls if c[0] in ("folder", "upload", "sheet", "share")],
   "dùng lại thư mục + Sheet, không tải lại, không chia sẻ lại", FD.calls)

print("── F. đồng bộ rồi xoá ──────────────────────────────────────")
FD.calls.clear()
PAY2 = {"task_id": "sync2", "source_task_id": "src2", "source_seq": 22, "agent_id": "a1",
        "options": {"drive": True, "drive_token_id": "tok_a", "drive_public": False, "delete_after": True}}
out2 = P.run_drive_sync(dict(PAY2), None, lambda: False)
n_up = len([c for c in FD.calls if c[0] == "upload"])
ok(deleted == [("src2", True, n_up)] and n_up > 0, "xoá task gốc (kèm file) SAU khi tải xong", (deleted, n_up))
ok("- **Deleted** task #22 — 12 file(s), 5 MB freed · Content Studio project removed" in out2
   and "private to that account" in out2, "kết quả nói số file + project Studio đã xoá", out2)
ok(not [c for c in FD.calls if c[0] == "share"], "chọn riêng tư → không chia sẻ công khai")

print("── G/H. hỏng ───────────────────────────────────────────────")
deleted.clear()
FD.files.clear()
CK["src"].pop("drive", None)
MARKS.clear()
FAIL_UPLOAD["on"] = True
try:
    P.run_drive_sync(dict(PAY, options=dict(PAY["options"], delete_after=True)), None, lambda: False)
    ok(False, "tải hỏng phải ném")
except RuntimeError as e:
    ok("Saving to Google Drive failed" in str(e) and deleted == [], "tải hỏng → task hỏng (có Chạy lại), KHÔNG xoá task gốc",
       (str(e)[:120], deleted))
FAIL_UPLOAD["on"] = False
ok("src" not in MARKS, "tải hỏng → KHÔNG ghi dấu đã lên Drive", MARKS)
try:
    P.run_drive_sync({"task_id": "s9", "source_task_id": "novid", "source_seq": 24, "agent_id": "a1", "options": {}},
                     None, lambda: False)
    ok(False, "mất video phải ném")
except RuntimeError as e:
    ok("no rendered video on this machine" in str(e), "video gốc đã mất → báo rõ", str(e))

print("── I. route ────────────────────────────────────────────────")
REQ = types.SimpleNamespace(state=types.SimpleNamespace())
GUEST = types.SimpleNamespace(state=types.SimpleNamespace(guest_scope={"group": "g1"}))
ok(asyncio.run(R.drive_sync_probe("plan", REQ))["reason"] == "script_only", "GET: hỏi trước task có video không")
for label, call, want in (
    ("khách của không gian chia sẻ bị chặn", lambda: R.drive_sync_probe("src", GUEST), 403),
    ("task chỉ viết kịch bản → 400", lambda: R.drive_sync_start("plan", R.DriveSyncRequest(drive_token_id="tok_a"), REQ), 400),
    ("tài khoản chỉ đọc → 400 NGAY, không đợi task chạy mới hỏng",
     lambda: R.drive_sync_start("src", R.DriveSyncRequest(drive_token_id="tok_ro"), REQ), 400),
):
    try:
        asyncio.run(call())
        ok(False, label)
    except HTTPException as e:
        ok(e.status_code == want, label, (e.status_code, e.detail))
n_before = len(created)
res = asyncio.run(R.drive_sync_start("src", R.DriveSyncRequest(drive_token_id="tok_a", drive_public=False, delete_after=True), REQ))
ok(res["status"] == "queued" and len(created) == n_before + 1 and events[-1][1]["options"]["delete_after"] is True
   and events[-1][1]["options"]["drive_public"] is False, "POST: xếp task đồng bộ với đúng tuỳ chọn", res)

print("── J. quét task cũ ─────────────────────────────────────────")
BF = [
    {"id": "bf1", "lane": "video", "status": "done"},
    {"id": "bf2", "lane": "video", "status": "review"},
    {"id": "bf3", "lane": "video", "status": "running"},
    {"id": "bf4", "lane": "", "status": "done"},
    {"id": "bf5", "lane": "video", "status": "done", "drive": {}},
]
CK["bf1"] = {"drive": {"folder_url": "https://drive.google.com/old", "email": "old@x.com", "files": 9, "token_id": "tok_a"}}
CK["bf2"] = {"drive": {"folder_url": "https://drive.google.com/half", "token_id": "tok_a"}}      # tải dở: chưa có files
CM.codex_manager.list_tasks = lambda status="", limit=50, created_by="": [dict(t) for t in BF]
read = []
_rc = P._read_checkpoint
P._read_checkpoint = lambda tid: read.append(tid) or _rc(tid)
MARKS.clear()
n = P.backfill_drive_marks()
P._read_checkpoint = _rc
ok(n == 1 and MARKS.get("bf1", {}).get("folder_url") == "https://drive.google.com/old",
   "task đã tải xong TRƯỚC bản này → ghi dấu từ checkpoint", (n, MARKS))
ok(MARKS.get("bf2") == {}, "tải dở (chưa có số file) → dấu rỗng = đã kiểm, nút Drive thường", MARKS)
ok(sorted(read) == ["bf1", "bf2"] and not {"bf3", "bf4", "bf5"} & set(MARKS),
   "chỉ đọc task video đã dừng chưa có dấu (không đụng task đang chạy / việc chung / đã kiểm)", (read, MARKS))
ext_src = (ROOT / "tubecli" / "extensions" / "content_video" / "extension.py").read_text(encoding="utf-8")
ok("_DRIVE_MARKS_DONE = True" in ext_src and "backfill_drive_marks()" in ext_src,
   "on_enable (chạy lại mỗi lượt dò extension) quét task cũ MỘT lần mỗi tiến trình")

print("── K. CodexManager.set_drive ───────────────────────────────")
if not _inside_tmp(CM.TASKS_FILE):
    print("ABORT — tasks.json của Codex không nằm trong thư mục tạm:", CM.TASKS_FILE)
    sys.exit(2)
MG = CM.CodexManager()
MG._loaded = True
MG._tasks = {"t1": {"id": "t1", "status": "done", "updated_at": "2026-09-16T01:00:00+00:00"}}
r = MG.set_drive("t1", {"folder_url": "https://drive.google.com/f9", "email": "a@x.com", "files": 3,
                        "token_id": "tok_a", "folder_id": "f9", "sheet_url": ""})
ok(r["drive"] == {"folder_url": "https://drive.google.com/f9", "email": "a@x.com", "files": 3}
   and r["updated_at"] == "2026-09-16T01:00:00+00:00",
   "task ĐÃ XONG vẫn ghi được dấu; chỉ giữ link/tài khoản/số file, không đổi updated_at", r)
import json as _json  # noqa: E402
ok(_json.load(open(CM.TASKS_FILE, encoding="utf-8"))["t1"]["drive"]["files"] == 3, "ghi vào tasks.json")
ok(MG.set_drive("nope", {"folder_url": "x"}) is None, "task không có → None")
ok(MG.set_drive("t1", None)["drive"] == {}, "dấu rỗng = đã kiểm")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
