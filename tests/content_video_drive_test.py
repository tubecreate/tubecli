# -*- coding: utf-8 -*-
"""Lưu thành phẩm lên Google Drive — bước "drive" của content_video (15/9/2026).

User: "lưu nội dung đã tạo vào driver, ví dụ nội dung sẽ lưu vào sheet, file audio image và video sẽ upload lên
drive trong 1 file project, folder đặt tên theo tiêu đề / sẽ chọn auth trong tạo task như đã chọn trong auth của agent".

Không mạng, không Google thật: các hàm của drive_export được thay bằng một Drive giả trong bộ nhớ.

Kiểm:
  A. granted_auth_creds đọc khối [[AUTH-ACCESS-GUIDE]] y như splitAuthBlock của tab Auth
  B. resolve_token: token chọn tay thắng (ĐÚNG token_id, không nhận credential_id); không chọn → tài khoản đã cấp
     cho agent (đang sống trước); việc do AI/lịch dùng tài khoản chưa cấp → từ chối; chỉ đọc/thu hồi/mất → lỗi rõ
  C. _step_drive: thư mục tên tiêu đề, Sheet 3 tab, video + ảnh đại diện + ảnh/giọng từng cảnh vào images/ audio/,
     tiến độ theo byte, link trong Sheet, checkpoint giữ thư mục, dòng kết quả
  D. chạy lại: dùng lại thư mục + Sheet, file cùng tên cùng cỡ không tải lại; video dựng lại → tải bản mới, bản cũ
     vào thùng rác; đổi tài khoản / thư mục bị xoá → thư mục mới
  E. file ngoài DATA_DIR (shot trỏ ra ngoài) không bao giờ được đưa lên
  F. hỏng: cảnh báo + ném; người dùng tick → task hỏng để Retry, lịch → ghi chú; tắt → bỏ qua; thiếu năng lực → cảnh báo; huỷ
  G. kế hoạch: bước cuối, mặc định tắt, dòng kế hoạch nói thư mục + tài khoản, câu mô tả task auto
  H. drive_export thật với dịch vụ giả: upload theo khúc + huỷ, write_sheet đổi tên tab mặc định + RAW, unique_name,
     list_children nhiều trang, file_alive
  I. /assignees trả auth_creds

Run:  python tests/content_video_drive_test.py     (exit 0 = pass)
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cv_drive_"))
_REAL_DATA_DIR, _REAL_EXT_DIR = CFG.DATA_DIR, CFG.EXTENSIONS_EXTERNAL_DIR
CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_EXTERNAL_DIR = CFG.DATA_DIR / "extensions_external"
# PHẢI đổi cả EXTENSIONS_DATA_DIR: import tubecli.core.agent gọi ensure_data_dirs() → migrate_and_link_extensions_data()
# tạo junction DATA_DIR/content_studio → EXTENSIONS_DATA_DIR/content_studio. Lần đầu viết test này quên dòng đó
# và file giả đã rơi vào kho Content Studio THẬT (15/9/2026, đã dọn).
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
_TMP_REAL = os.path.realpath(str(TMP))


def _inside_tmp(p) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(str(p)), _TMP_REAL]) == _TMP_REAL
    except ValueError:
        return False

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.extensions.content_video import drive_export as DX  # noqa: E402
from tubecli.extensions.content_video import capabilities as CAP  # noqa: E402
from tubecli.core.agent import granted_auth_creds  # noqa: E402
import tubecli.core.agent as AG  # noqa: E402
import tubecli.extensions.codex.manager as CM  # noqa: E402

# Bước dựng có gọi _put — KHÔNG giả lập là test gửi PUT thật tới máy chủ đang chạy (11/9/2026).
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


REAL = {n: getattr(DX, n) for n in ("google_tokens", "services", "file_alive", "unique_name", "create_folder",
                                    "find_or_create_folder", "my_drive_root_id", "move_folder",
                                    "list_children", "upload_file", "trash_file", "create_sheet", "write_sheet",
                                    "share_public", "download_url", "_gapi")}

# ── dữ liệu ──────────────────────────────────────────────────────────
DD = CFG.DATA_DIR
# Chốt chặn trước khi ghi bất cứ gì: không mục nào của DATA_DIR tạm được trỏ (junction/hardlink) ra ngoài TMP.
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


MP4 = mk("content_studio/outputs/exports/episode_34_pipeline_export.mp4", 3000)
MAIN = mk("content_studio/outputs/exports/episode_34_pipeline_main.mp4", 2000)
THUMB = mk("content_video/thumbs/ep34/thumb.jpg", 100)
IMG1 = mk("content_studio/grok_images/ep34_1.png", 50)
IMG2 = mk("content_studio/grok_images/ep34_2.JPG", 60)
AUD1 = mk("content_video/audio/ep34/shot001.mp3", 70)
mk("tts_vibevoice/outputs/edge_abc.mp3", 80)
OUTSIDE = TMP / "secret.txt"
OUTSIDE.write_bytes(b"do not upload")
SHOTS = [
    {"id": 2, "storyboard_number": 2, "image_prompt": "a quiet lake", "narration_text": "=SUM(1) calm",
     "composed_image": IMG2, "tts_audio_url": "/api/v1/tts/audio/edge_abc.mp3", "duration": 6},
    {"id": 1, "storyboard_number": 1, "image_prompt": "sunrise", "video_prompt": "pan slowly.",
     "shot_type": "medium", "angle": "eye-level", "movement": "static", "location": "Alcoba imperial",
     "time": "Amanecer, luz fría", "action": "The person sits still", "atmosphere": "Silencio denso, tono melancólico.",
     "bgm_prompt": "Cítara guqin lenta", "sound_effect": "Brisa leve, madera crujiente",
     "character_ids": [7], "scene_id": 3,
     "narration_text": "Hello", "composed_image": IMG1, "tts_audio_url": AUD1, "duration": 11},
    {"id": 3, "storyboard_number": 3, "image_prompt": "outside", "narration_text": "Bye",
     "composed_image": str(OUTSIDE), "image_url": "https://evil.example/x.png", "tts_audio_url": str(OUTSIDE)},
]
P._storyboards = lambda ep: [dict(s) for s in SHOTS]
P.media_seconds = lambda p: 4.2
CAST = [{"id": 7, "name": "Mei", "role": "Protagonist", "description": "A weary scholar",
         "appearance": "East Asian woman in plain hanfu, hair in a low bun"},
        {"id": 8, "name": "Master", "role": "", "description": "Old monk.", "appearance": ""}]
PLACES = [{"id": 3, "location": "Alcoba imperial", "time": "Amanecer",
           "description": "Red lacquer pillars and carved lattice windows"}]
STUDIO_GETS = []


def fake_get(path, timeout=60):
    """Mọi HTTP tới Studio đều giả — thiếu cái này là test gọi máy chủ thật (xem feedback-tests-mock-all-http)."""
    STUDIO_GETS.append(path)
    if path == "/api/v1/studio/dramas/12/characters":
        return {"items": CAST}
    if path == "/api/v1/studio/dramas/12/scenes":
        return {"items": PLACES}
    raise AssertionError(f"test chặn HTTP thật: {path}")


P._get = fake_get

TOKENS = [
    {"token_id": "cred_a_1", "credential_id": "cred_a", "authorized_email": "a@x.com", "scopes": ["drive", "sheets"], "status": "active"},
    {"token_id": "cred_a_2", "credential_id": "cred_a", "authorized_email": "a2@x.com", "scopes": ["drive_readonly"], "status": "active"},
    {"token_id": "cred_b_1", "credential_id": "cred_b", "authorized_email": "b@x.com", "scopes": ["drive"], "status": "expired"},
    {"token_id": "cred_c_1", "credential_id": "cred_c", "authorized_email": "c@x.com", "scopes": ["youtube_upload"], "status": "active"},
    {"token_id": "cred_r_1", "credential_id": "cred_r", "authorized_email": "r@x.com", "scopes": ["drive"], "status": "revoked"},
    {"token_id": "cred_d_1", "credential_id": "cred_d", "authorized_email": "d@x.com", "scopes": ["drive_readonly"], "status": "active"},
]


# ── Drive giả ────────────────────────────────────────────────────────
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

    def by_name(self, name, parent=None):
        return [f for f in self.files.values() if f["name"] == name and not f["trashed"]
                and (parent is None or f["parent"] == parent)]


FD = FakeDrive()
FAIL_UPLOAD = {"name": ""}
SHEET_WRITES = []
SERVICES = []


FAIL_SHARE = {"msg": ""}


def fake_share(drive, folder_id):
    FD.calls.append(("share", folder_id))
    if FAIL_SHARE["msg"]:
        raise RuntimeError(FAIL_SHARE["msg"])


def fake_upload(drive, path, name, parent, on_progress=None, cancelled=None, cancel_exc=None):
    FD.calls.append(("upload", name, parent))
    if FAIL_UPLOAD["name"] and FAIL_UPLOAD["name"] in name:
        raise RuntimeError("<HttpError 403 storageQuotaExceeded>")
    size = os.path.getsize(path)
    if on_progress:
        on_progress(size // 2)
        on_progress(size)
    return FD.add(name, parent, "", size)


ROOT_NAME = "tuan89tk-vps-k7m2qx"


def fake_find_or_create(drive, parent, name):
    hit = [f for f in FD.by_name(name, parent) if f["mimeType"] == DX.FOLDER_MIME]
    return dict(hit[0]) if hit else (FD.calls.append(("folder", name, parent)) or FD.add(name, parent, DX.FOLDER_MIME))


def fake_move(drive, fid, new_parent, old_parents):
    FD.calls.append(("move", fid, new_parent, list(old_parents)))
    FD.files[fid]["parent"] = new_parent


def install_fakes():
    DX.google_tokens = lambda: [dict(t) for t in TOKENS]
    DX.services = lambda tid: SERVICES.append(tid) or (("drive", tid), ("sheets", tid))
    DX.file_alive = lambda drive, fid: (dict(FD.files[fid], parents=[FD.files[fid]["parent"]])
                                        if fid in FD.files and not FD.files[fid]["trashed"] else None)
    DX.find_or_create_folder = fake_find_or_create
    DX.my_drive_root_id = lambda drive: "root"
    DX.move_folder = fake_move
    DX.unique_name = lambda drive, parent, name: name if name not in FD.children(parent) else f"{name} (2)"
    DX.create_folder = lambda drive, name, parent="root": FD.calls.append(("folder", name, parent)) or FD.add(name, parent, DX.FOLDER_MIME)
    DX.list_children = lambda drive, fid: FD.children(fid)
    DX.upload_file = fake_upload
    DX.share_public = fake_share
    DX.trash_file = lambda drive, fid: FD.calls.append(("trash", fid)) or FD.files[fid].update(trashed=True)
    DX.create_sheet = lambda drive, name, parent: FD.calls.append(("sheet", name, parent)) or FD.add(name, parent, DX.SHEET_MIME)
    DX.write_sheet = lambda sheets, sid, tabs, widths=None: SHEET_WRITES.append(
        (sid, [(t, [list(r) for r in rows]) for t, rows in tabs], widths))


install_fakes()
# Danh tính cloud của máy (tài khoản + số server) — thư mục cha trên Drive (17/9/2026).
P._drive_root_name = lambda: ROOT_NAME


class Agent:
    name = "MC"
    system_prompt = "Be kind.\n\n[[AUTH-ACCESS-GUIDE]]\ncreds: cred_a\n### google · a@x.com (credential: cred_a)\n[[/AUTH-ACCESS-GUIDE]]"


TASKS = {"t1": {"id": "t1", "created_by": "user"}, "p_ai": {"id": "p_ai", "created_by": "brain"},
         "t_sched": {"id": "t_sched", "created_by": "autopublish"}}
CM.codex_manager.get_task = lambda tid: TASKS.get(tid)
CK = {}
P._read_checkpoint = lambda tid: dict(CK.get(tid) or {})
P._write_checkpoint = lambda tid, d: CK.__setitem__(tid, dict(d))
said = []


def new_state(task_id="t1", **kw):
    said.clear()
    st = {"agent": Agent(), "task_id": task_id, "checkpoint": P._read_checkpoint(task_id), "warnings": [],
          "_say": lambda *a: said.append(a), "_cancelled": lambda: False,
          "title": "Mây trắng: bay/xa", "script": "TITLE: Mây\n\n[SHOW: lake]\n=calm line\n", "language": "vi",
          "preset_name": "Tin nhanh", "episode_id": 34, "drama_id": 12, "video_path": MP4, "video_main_path": MAIN,
          "thumbnail_path": THUMB, "video_seconds": 65, "shot_count": 3,
          "seo_sources": [{"title": "Nguồn", "url": "https://youtu.be/abc"}],
          "published": {"url": "https://youtu.be/pub1", "title": "YT title"},
          "seo": {"title": "YT title", "description": "desc", "tags": ["a", "b"]}}
    st.update(kw)
    return st


def rows_of(write, tab):
    return next(rows for t, rows in write[1] if t == tab)


def field(rows, name):
    return next((r[1] for r in rows if r[0] == name), None)


OPTS = {"drive": True, "drive_token_id": "cred_a_1", "_drive_hard": True}

print("── A. granted_auth_creds ───────────────────────────────────")
SP = ("You are X.\n\n[[AUTH-ACCESS-GUIDE]]\ncreds: cred_b,  cred_a , cred_b\n### google · b@x.com (credential: cred_b)\n"
      "[[/AUTH-ACCESS-GUIDE]]\ncreds: cred_after")
ok(granted_auth_creds(SP) == ["cred_b", "cred_a"], "đọc dòng creds trong khối, bỏ trùng, giữ thứ tự", granted_auth_creds(SP))
ok(granted_auth_creds("no block\ncreds: cred_x") == [], "không có khối → không có tài khoản (dòng creds lẻ không tính)")
ok(granted_auth_creds("[[AUTH-ACCESS-GUIDE]]\nnothing") == [] and granted_auth_creds(None) == [], "khối rỗng / None")
ok(granted_auth_creds("[[AUTH-ACCESS-GUIDE]]\ncreds: cred_z") == ["cred_z"], "thiếu dấu đóng → đọc tới hết (như splitAuthBlock)")

print("── B. resolve_token / can_write ────────────────────────────")
ok([DX.can_write(s) for s in (["drive"], ["drive_file"], ["drive_readonly"], ["https://www.googleapis.com/auth/drive"],
                              ["https://www.googleapis.com/auth/drive.readonly"], ["https://www.googleapis.com/auth/drive.file"],
                              [], None)] == [True, True, False, True, False, True, False, False], "can_write: khoá ngắn + URL")


def err(fn):
    try:
        fn()
    except DX.DriveExportError as e:
        return str(e)
    return ""


ok(DX.resolve_token("cred_a_1", [], False)["authorized_email"] == "a@x.com", "chọn tay, việc do người bấm → dùng luôn")
ok("not granted to this agent" in err(lambda: DX.resolve_token("cred_a_1", ["cred_b"], True)),
   "việc do AI/lịch + tài khoản chưa cấp → từ chối")
ok(DX.resolve_token("cred_a_1", ["cred_a"], True)["token_id"] == "cred_a_1", "việc do AI + tài khoản đã cấp → được")
ok("can only read" in err(lambda: DX.resolve_token("cred_a_2", ["cred_a"], False)), "chỉ quyền đọc → lỗi rõ")
ok("revoked" in err(lambda: DX.resolve_token("cred_r_1", [], False)), "đã thu hồi → lỗi rõ")
ok("no longer in Auth Manager" in err(lambda: DX.resolve_token("gone", [], False)), "token không còn → lỗi rõ")
ok("no longer in Auth Manager" in err(lambda: DX.resolve_token("cred_a", [], False)),
   "credential_id KHÔNG được nhận thay token_id (một credential nhiều tài khoản)")
ok(DX.resolve_token("", ["cred_c", "cred_b", "cred_a"], True)["token_id"] == "cred_a_1",
   "không chọn → tài khoản đã cấp ghi được Drive, đang sống trước (b hết hạn đứng sau a)")
ok(DX.resolve_token("", ["cred_b"], True)["token_id"] == "cred_b_1", "chỉ còn tài khoản hết hạn → vẫn dùng (tự làm mới)")
ok("No Google account with Drive access is granted" in err(lambda: DX.resolve_token("", ["cred_c", "cred_r"], True)),
   "agent không có tài khoản Drive nào → nói chọn ở form hoặc cấp ở tab Auth")
ok("can only read" in err(lambda: DX.resolve_token("", ["cred_d"], True)), "tài khoản đã cấp chỉ đọc → nói rõ")

print("── C. lưu lần đầu ──────────────────────────────────────────")
st = new_state()
P._step_drive(st, dict(OPTS))
vps = FD.children("root").get(ROOT_NAME) or {}
VPS_ID = vps.get("id", "")
root = FD.children(VPS_ID)
folder = root.get("Mây trắng: bay/xa")
# User 17/9/2026: "sử dụng đường dẫn tạo folder username-vps-9/tenproject để biết được user nào đăng lên và ở server
# nào nếu tất cả đăng chung 1 drive".
ok(vps.get("mimeType") == DX.FOLDER_MIME and list(FD.children("root")) == [ROOT_NAME],
   "gốc Drive chỉ có thư mục của máy «tuan89tk-vps-k7m2qx»", list(FD.children("root")))
ok(folder and folder["mimeType"] == DX.FOLDER_MIME, "project «tuan89tk-vps-k7m2qx/tiêu đề» nằm TRONG thư mục của máy", list(root))
ok(("share", VPS_ID) not in FD.calls and any(c[0] == "share" and c[1] == (folder or {}).get("id") for c in FD.calls),
   "chỉ chia sẻ thư mục project, KHÔNG chia sẻ thư mục của máy (lộ mọi project khác)", FD.calls[:4])
ok(CK["t1"]["drive"]["root_name"] == ROOT_NAME and CK["t1"]["drive"]["root_id"] == VPS_ID,
   "sổ nhớ thư mục của máy", CK["t1"]["drive"])
ok(any(a[2] == f"project folder “{ROOT_NAME}/Mây trắng: bay/xa”" for a in said if len(a) > 2),
   "thẻ bước nói đường dẫn thư mục", [a[2] for a in said][:4])
fid = folder["id"] if folder else ""
top = FD.children(fid)
base = "Mây trắng bay xa"
ok({f"{base}.mp4", f"{base} (no layout).mp4", f"{base} (thumbnail).jpg", "images", "audio", "Mây trắng: bay/xa — content"} == set(top),
   "trong thư mục: video, bản không bố cục, ảnh đại diện, images/, audio/, Sheet nội dung", sorted(top))
imgs, auds = FD.children(top["images"]["id"]), FD.children(top["audio"]["id"])
ok(set(imgs) == {"scene_001.png", "scene_002.jpg"} and set(auds) == {"scene_001.mp3", "scene_002.mp3"},
   "ảnh + giọng theo THỨ TỰ cảnh (storyboard_number), đuôi viết thường, giọng edge /api/… tìm ra file", (sorted(imgs), sorted(auds)))
ok(imgs["scene_001.png"]["size"] == "50" and auds["scene_002.mp3"]["size"] == "80", "đúng file của từng cảnh")
ok(not FD.by_name("scene_003.png") and not FD.by_name("scene_003.txt") and all("secret" not in c[1] for c in FD.calls if c[0] == "upload"),
   "cảnh 3 trỏ ra NGOÀI DATA_DIR / URL lạ → không đưa lên")
ok(SERVICES[-1] == "cred_a_1", "dịch vụ Google của đúng token đã chọn", SERVICES)
ok(len(SHEET_WRITES) == 2 and SHEET_WRITES[0][0] == SHEET_WRITES[1][0], "Sheet ghi hai lần: nội dung trước, thêm link sau", len(SHEET_WRITES))
first, last = SHEET_WRITES
ok([t for t, _ in last[1]] == ["Overview", "Scenes", "Script"] and last[2] is P.DRIVE_WIDTHS, "ba tab + độ rộng cột")
ov1, ov = rows_of(first, "Overview"), rows_of(last, "Overview")
ok(field(ov1, "Video") is None and field(ov1, "Title") == "Mây trắng: bay/xa", "lần ghi đầu chưa có link video (chưa tải)")
ok(field(ov, "Video") == FD.by_name(f"{base}.mp4")[0]["webViewLink"] and field(ov, "Google Drive folder") == folder["webViewLink"]
   and field(ov, "YouTube") == "https://youtu.be/pub1" and field(ov, "YouTube tags") == "a, b"
   and field(ov, "Sources") == "https://youtu.be/abc" and field(ov, "Video length") == "01:05" and field(ov, "Scenes") == 3
   and field(ov, "Uploaded from") == ROOT_NAME,
   "Overview: link video, thư mục, ai đăng từ máy nào, YouTube, tag, nguồn, thời lượng, số cảnh", ov)
sc = rows_of(last, "Scenes")
ok(sc[0] == ["Scene", "Image prompt", "Video prompt", "Narration", "Seconds", "Image file", "Voice file"]
   and len(sc) == 4,
   "Scenes: prompt ảnh, prompt video đầy đủ trong MỘT ô (không tách Camera / Sound), lời, giây, link file", sc[0])
FULL = ("[VIDEO PROMPT]\n"
        "pan slowly. Camera: medium shot, eye-level angle, static camera. Action: The person sits still. "
        "Mood and light: Silencio denso, tono melancólico. "
        "Audio: music: Cítara guqin lenta; sound effects: Brisa leve, madera crujiente. Duration: about 4 s.\n\n"
        "[CHARACTERS]\n"
        "- Mei (Protagonist): A weary scholar. Appearance: East Asian woman in plain hanfu, hair in a low bun.\n\n"
        "[SCENE SETTING]\n"
        "Alcoba imperial (Amanecer): Red lacquer pillars and carved lattice windows.")
ok(sc[1][2] == FULL, "ô prompt video: [VIDEO PROMPT] + [CHARACTERS] + [SCENE SETTING] như nút Copy VID của Studio",
   sc[1][2])
ok(sorted(set(STUDIO_GETS)) == ["/api/v1/studio/dramas/12/characters", "/api/v1/studio/dramas/12/scenes"],
   "đọc nhân vật + cảnh của đúng phim (drama 12)", STUDIO_GETS)
ok(sc[1][:2] == [1, "sunrise"] and sc[1][3:5] == ["Hello", 4.2] and sc[1][5] == imgs["scene_001.png"]["webViewLink"]
   and sc[1][6] == auds["scene_001.mp3"]["webViewLink"], "cảnh 1: prompt ảnh, lời, giây thật, link ảnh + giọng", sc[1])
ok(sc[2][3] == "=SUM(1) calm" and sc[2][2] == "" and sc[3][5] == "" and sc[3][6] == "",
   "lời bắt đầu bằng '=' giữ nguyên; shot không có gì để ghép → prompt video TRỐNG (không bịa); cảnh 3 không link",
   sc[1:])

# full_video_prompt: từng mệnh đề chỉ có khi có dữ liệu, không lặp hành động đã nằm trong câu chuyển động
ok(P.full_video_prompt({"duration": 9}) == "", "chỉ có thời lượng → rỗng (không ra prompt vô nghĩa)")
ok(P.full_video_prompt({"video_prompt": "Slow push-in as the lamp flickers", "movement": "push-in", "duration": "7"})
   == "[VIDEO PROMPT]\nSlow push-in as the lamp flickers. Camera: push-in camera. Duration: about 7 s.",
   "thiếu cỡ cảnh / góc máy → chỉ ghi phần có; thời lượng dự kiến khi chưa có giọng",
   P.full_video_prompt({"video_prompt": "Slow push-in as the lamp flickers", "movement": "push-in", "duration": "7"}))
ok("Action:" not in P.full_video_prompt({"video_prompt": "The monk bows deeply at the gate", "action": "the monk bows deeply"}),
   "hành động đã có trong câu chuyển động thì không ghi lặp")
ok(P.full_video_prompt({"bgm_prompt": "  Soft   piano. ", "_seconds": 0.4})
   == "[VIDEO PROMPT]\nAudio: music: Soft piano. Duration: about 1 s.",
   "gộp khoảng trắng, bỏ dấu câu cuối, thời lượng tối thiểu 1 s",
   P.full_video_prompt({"bgm_prompt": "  Soft   piano. ", "_seconds": 0.4}))
_by_name = P.full_video_prompt({"video_prompt": "The monk rings the bell", "character_names": ["master"]}, CAST, [])
ok(_by_name == "[VIDEO PROMPT]\nThe monk rings the bell.\n\n[CHARACTERS]\n- Master: Old monk.",
   "shot không có character_ids → khớp theo tên (không phân biệt hoa thường); không vai / không ngoại hình thì bỏ",
   _by_name)
_fallback = P.full_video_prompt({"video_prompt": "Rain falls", "location": "Night market", "time": "Late night"}, CAST, PLACES)
ok(_fallback.endswith("[SCENE SETTING]\nNight market (Late night).") and "[CHARACTERS]" not in _fallback,
   "phim không có cảnh khớp → [SCENE SETTING] lấy địa điểm + thời điểm của chính shot; không nhân vật thì bỏ khối", _fallback)
ok(P.full_video_prompt({"video_prompt": "x", "location": "alcoba IMPERIAL"}, [], PLACES).endswith(
   "[SCENE SETTING]\nAlcoba imperial (Amanecer): Red lacquer pillars and carved lattice windows."),
   "không có scene_id → khớp cảnh theo địa điểm (không phân biệt hoa thường)")
ok(P.full_video_prompt({"character_ids": [99], "video_prompt": "x"}, CAST, []) == "[VIDEO PROMPT]\nx.",
   "id nhân vật không có trong phim → không bịa khối [CHARACTERS]")
_bad = {"drama_id": 12}
P._get = lambda path, timeout=60: (_ for _ in ()).throw(RuntimeError("studio down"))
ok(P._drive_studio_context(_bad) == ([], []), "Studio không trả lời → không có khối nhân vật / cảnh, không đổ lượt")
P._get = fake_get
ok(P._drive_studio_context({"drama_id": None}) == ([], []), "chưa có phim → khỏi gọi Studio")
ok(rows_of(last, "Script") == [["Script"], ["TITLE: Mây"], ["[SHOW: lake]"], ["=calm line"]], "Script: từng dòng, bỏ dòng trống")
rec = CK["t1"]["drive"]
ok(rec["folder_id"] == fid and rec["token_id"] == "cred_a_1" and rec["email"] == "a@x.com" and rec["files"] == 7
   and rec["uploaded"] == 7 and rec["sheet_id"] == top["Mây trắng: bay/xa — content"]["id"],
   "checkpoint giữ thư mục, Sheet, tài khoản, số file", rec)
ok([c for c in FD.calls if c[0] == "share"] == [("share", fid)] and rec["public"] is True,
   "chia sẻ MỘT lần cho cả thư mục (file bên trong hưởng theo)", [c for c in FD.calls if c[0] == "share"])
_vid = FD.by_name(f"{base}.mp4")[0]
ok(field(ov, "Video (download)") == f"https://drive.google.com/uc?export=download&id={_vid['id']}"
   and field(ov, "Sharing") == "anyone with the link can view and download",
   "Sheet có link TẢI thẳng + dòng Sharing", (field(ov, "Video (download)"), field(ov, "Sharing")))
prog = [a for a in said if len(a) > 3 and a[1] == "running" and a[3] is not None]
pcts = [a[3] for a in prog]
ok(prog and all(0 < p <= 100 for p in pcts) and pcts == sorted(pcts) and pcts[-1] == 100, "tiến độ theo byte, tăng dần, kết thúc 100", pcts)
ok(any("uploading image 4/7" in a[2] for a in prog) and "saved 7 file(s)" in prog[-1][2], "câu tiến độ nói loại file + thứ tự",
   [a[2] for a in prog][:3])
out = P._render_result(st, {}, [], [], 12)
ok(f"- **Google Drive**: {folder['webViewLink']} ({ROOT_NAME}/Mây trắng: bay/xa) · content sheet https://drive.google.com/" in out
   and "7 file(s) · a@x.com" in out
   and out.startswith("## ✅"), "kết quả có dòng Google Drive, vẫn ✅", out[:300])

print("── D. chạy lại ─────────────────────────────────────────────")
FD.calls.clear()
SHEET_WRITES.clear()
st2 = new_state()
P._step_drive(st2, dict(OPTS))
ok(not [c for c in FD.calls if c[0] in ("folder", "upload", "sheet")], "cùng tài khoản: không thư mục mới, không tải lại, không Sheet mới", FD.calls)
ok(not [c for c in FD.calls if c[0] == "share"], "chạy lại KHÔNG chia sẻ lại (cờ public nằm trong sổ)", FD.calls)
ok(len(SHEET_WRITES) == 2 and field(rows_of(SHEET_WRITES[-1], "Overview"), "Video") == FD.by_name(f"{base}.mp4")[0]["webViewLink"],
   "Sheet ghi lại đủ link lấy từ file đã có")
ok(CK["t1"]["drive"]["uploaded"] == 0 and CK["t1"]["drive"]["files"] == 7, "sổ ghi 0 file tải lần này")
old_id = FD.by_name(f"{base}.mp4")[0]["id"]
Path(MP4).write_bytes(b"y" * 3500)
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS))
ups = [c for c in FD.calls if c[0] == "upload"]
ok([c[1] for c in ups] == [f"{base}.mp4"] and ("trash", old_id) in FD.calls and len(FD.by_name(f"{base}.mp4", fid)) == 1,
   "video dựng lại (khác cỡ) → tải bản mới, bản cũ vào thùng rác", FD.calls)
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS, drive_token_id="cred_b_1"))
ok(("folder", "Mây trắng: bay/xa (2)", VPS_ID) in FD.calls and len([c for c in FD.calls if c[0] == "upload"]) == 7
   and CK["t1"]["drive"]["token_id"] == "cred_b_1", "đổi tài khoản → thư mục mới (tên không trùng), tải đủ", FD.calls[:2])
FD.files[CK["t1"]["drive"]["folder_id"]]["trashed"] = True
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS, drive_token_id="cred_b_1"))
ok([c for c in FD.calls if c[0] == "folder"] and [c for c in FD.calls if c[0] == "sheet"],
   "người dùng xoá thư mục trên Drive → tạo lại thư mục + Sheet", FD.calls[:3])

# Project tải TRƯỚC bản này nằm ngay gốc My Drive → lượt đồng bộ lại dời nó vào thư mục của máy.
legacy = FD.add("Dự án cũ", "root", DX.FOLDER_MIME)
CK["t1"]["drive"] = dict(CK["t1"]["drive"], folder_id=legacy["id"])
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS, drive_token_id="cred_b_1"))
ok(("move", legacy["id"], VPS_ID, ["root"]) in FD.calls and FD.files[legacy["id"]]["parent"] == VPS_ID
   and not [c for c in FD.calls if c[0] == "folder" and c[2] in (VPS_ID, "root")] and CK["t1"]["drive"]["folder_id"] == legacy["id"],
   "project cũ ở gốc My Drive → dời vào «tuan89tk-vps-k7m2qx», dùng lại chứ không tạo thư mục mới", FD.calls[:3])
elsewhere = FD.add("Kho riêng", "root", DX.FOLDER_MIME)
mine = FD.add("Tự xếp", elsewhere["id"], DX.FOLDER_MIME)
CK["t1"]["drive"] = dict(CK["t1"]["drive"], folder_id=mine["id"])
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS, drive_token_id="cred_b_1"))
ok(not [c for c in FD.calls if c[0] == "move"] and FD.files[mine["id"]]["parent"] == elsewhere["id"],
   "người dùng đã tự dời project đi chỗ khác → để yên", FD.calls[:3])

print("── E/F. an toàn, lỗi, tắt, huỷ ─────────────────────────────")
FD.calls.clear()
bad = new_state(video_path=str(OUTSIDE))
try:
    P._step_drive(bad, dict(OPTS))
    ok(False, "video ngoài DATA_DIR phải ném")
except RuntimeError as e:
    ok("Nothing to save" in str(e) and not FD.calls and bad["drive_error"], "video ngoài DATA_DIR → không đụng Drive", FD.calls)

CK.clear()
FD.calls.clear()
ai = new_state("r_ai", plan_task_id="p_ai")
ai["agent"].system_prompt = "[[AUTH-ACCESS-GUIDE]]\ncreds: cred_b\n[[/AUTH-ACCESS-GUIDE]]"
try:
    P._step_drive(ai, dict(OPTS))
    ok(False, "tài khoản chưa cấp cho việc AI tạo phải ném")
except RuntimeError as e:
    ok("not granted to this agent" in str(e) and not FD.calls and any("Saving to Google Drive failed" in w for w in ai["warnings"]),
       "kế hoạch do AI tạo + token chưa cấp cho agent → từ chối trước khi đụng Drive", str(e)[:120])
Agent.system_prompt = "[[AUTH-ACCESS-GUIDE]]\ncreds: cred_a\n[[/AUTH-ACCESS-GUIDE]]"
ok(P._drive_strict({"task_id": "t_sched"}) and P._drive_strict({"task_id": "nope"}) and not P._drive_strict({"task_id": "t1"})
   and P._drive_strict({"task_id": "t1", "plan_task_id": "p_ai"}), "nghiêm khi không phải người bấm / tra không được; lượt dựng hỏi task kế hoạch")

CK.clear()
FAIL_UPLOAD["name"] = "scene_002"
hard = new_state()
try:
    P._step_drive(hard, dict(OPTS))
    ok(False, "upload hỏng phải ném")
except RuntimeError as e:
    msg = str(e)
    ok(msg.startswith("Saving to Google Drive failed: <HttpError 403 storageQuotaExceeded>") and "what was uploaded so far is in https://drive.google.com/" in msg
       and "Retry uploads only what is missing" in msg and hard["drive_error"], "người dùng tick: lỗi nói rõ + link thư mục + Retry", msg)
FAIL_UPLOAD["name"] = ""
FD.calls.clear()
P._step_drive(new_state(), dict(OPTS))
ok([c[1] for c in FD.calls if c[0] == "upload"] == ["scene_002.jpg", "scene_002.mp3"],
   "Retry chỉ tải phần còn thiếu (hỏng ở file thứ 6 → còn 2 file)", FD.calls)

P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
STEP = [("drive", "Save to Google Drive", "drive", True)]
P._HANDLERS["drive"] = lambda s, o: (_ for _ in ()).throw(RuntimeError("boom"))
notes, skipped = [], []
try:
    P._run_steps(STEP, new_state(), {"drive": True, "_drive_hard": True}, lambda *a: None, lambda: False, notes, skipped)
    ok(False, "_drive_hard phải ném")
except RuntimeError:
    ok(notes == [], "_run_steps: _drive_hard → task hỏng (có Retry)")
P._run_steps(STEP, new_state(), {"drive": True, "_drive_hard": False}, lambda *a: None, lambda: False, notes, skipped)
ok(notes and "Save to Google Drive** failed: boom" in notes[0], "_run_steps: lịch tự đăng → chỉ ghi chú, lượt vẫn xong", notes)
P._HANDLERS["drive"] = P._step_drive
P.check_job = lambda job: {"ready": False, "missing": ["auth_manager"], "disabled": [], "missing_tools": []}
miss = new_state()
P._run_steps(STEP, miss, {"drive": True}, lambda *a: None, lambda: False, [], [])
ok(any("Nothing was saved to Google Drive" in w for w in miss["warnings"]), "bật drive mà thiếu Auth Manager → cảnh báo, không ✅", miss["warnings"])

FD.calls.clear()
off = new_state()
P._step_drive(off, {})
ok(said[-1] == ("drive", "skipped", "off") and not FD.calls, "tắt → bỏ qua, không đụng Drive")
CK.clear()
cx = new_state()
cx["_cancelled"] = lambda: True
try:
    P._step_drive(cx, dict(OPTS))
    ok(False, "huỷ phải ném")
except Exception as e:      # noqa: BLE001
    ok(P._is_cancel(e) and not cx["warnings"] and not [c for c in FD.calls if c[0] == "upload"],
       "huỷ giữa chừng → dừng trước file kế, không cảnh báo", (type(e).__name__, cx["warnings"]))

print("── G. kế hoạch ─────────────────────────────────────────────")
ok(P.RENDER_STEPS[-1] == ("drive", "Save to Google Drive", "drive", True) and "drive" in P.SOFT_FAIL_STEPS
   and P.DEFAULTS["drive"] is False and P.DEFAULTS["drive_token_id"] == "", "bước cuối, tuỳ chọn, mặc định tắt")
ok(CAP.JOBS["drive"]["requires"] == ["auth_manager"] and "auth_manager" in CAP.EXTENSIONS, "năng lực: cần Auth Manager")
d = P.describe_plan({"drive": True, "drive_token_id": "cred_a_1", "title": "Mây"})
ok("- Save to Google Drive: a folder «Mây» inside «tuan89tk-vps-k7m2qx» on a@x.com — content sheet, images, voice and video" in d,
   "dòng kế hoạch: thư mục (trong thư mục của máy) + tài khoản", d)
d2 = P.describe_plan({"drive": True})
ok("named after the video title inside «tuan89tk-vps-k7m2qx» on the Google account granted to the agent in its Auth tab" in d2,
   "không chọn → nói tài khoản đã cấp cho agent")
ok("Save to Google Drive:" not in P.describe_plan({}), "không bật → không có dòng lưu Drive")
src = Path(P.__file__).read_text(encoding="utf-8")
ok(src.count('options["_drive_hard"] = bool(options.get("drive")) and not options.get("autopublish")') == 2
   and src.count('if s not in ("publish", "drive")]') == 2, "run_render + run_auto: drive không bắt buộc, người dùng tick thì hỏng thật")
AG.agent_manager.get = lambda aid: Agent()
made = {}
CM.codex_manager.create_task = lambda **k: made.update(task=k) or {"id": "x9", "seq": 9}
CM.codex_manager.append_event = lambda *a, **k: None
P.create_auto_task("a1", {"source_text": "abc", "drive": True, "drive_token_id": "cred_a_1"}, created_by="user",
                   job_label="Video from content")
ok("→ lưu lên Google Drive" in made["task"]["goal"]
   and "- Save to Google Drive: a folder named after the video title inside «tuan89tk-vps-k7m2qx» on a@x.com" in made["task"]["goal"],
   "task auto: câu mô tả + kế hoạch nói lưu Drive", made["task"]["goal"][:200])

print("── J. quyền chia sẻ chọn lúc tạo task ──────────────────────")
CK.clear()
FD.calls.clear()
SHEET_WRITES.clear()
priv = new_state()
P._step_drive(priv, dict(OPTS, drive_public=False))
ok(not [c for c in FD.calls if c[0] == "share"] and not CK["t1"]["drive"].get("public"),
   "chọn «chỉ tài khoản Google này» → KHÔNG chia sẻ công khai", [c[0] for c in FD.calls][:4])
ok(field(rows_of(SHEET_WRITES[-1], "Overview"), "Sharing") == "private — only a@x.com",
   "Sheet nói rõ đang riêng tư của ai", field(rows_of(SHEET_WRITES[-1], "Overview"), "Sharing"))
out_priv = P._render_result(priv, {}, [], [], 5)
ok("· private to that account" in out_priv and "anyone with the link" not in out_priv, "kết quả nói riêng tư", out_priv[:400])

CK.clear()
FD.calls.clear()
FAIL_SHARE["msg"] = "<HttpError 403 sharingRateLimitExceeded>"
shaky = new_state()
P._step_drive(shaky, dict(OPTS))
FAIL_SHARE["msg"] = ""
ok(len([c for c in FD.calls if c[0] == "upload"]) == 7 and CK["t1"]["drive"]["public"] is False
   and any("could not be shared publicly" in w and "only a@x.com can open them" in w for w in shaky["warnings"]),
   "chia sẻ hỏng (tổ chức cấm link công khai) → vẫn lưu đủ file, chỉ cảnh báo", shaky["warnings"])
ok(P._render_result(shaky, {}, [], [], 5).startswith("## ⚠️"), "lượt đó hiện cảnh báo, không phải dấu tích sạch")
ok(P.DEFAULTS["drive_public"] is True,
   "mặc định ai có link xem + tải: tài khoản mở file thường khác tài khoản đã cấp quyền (16/9/2026)")
ok("(anyone with the link can view and download)" in P.describe_plan({"drive": True, "drive_token_id": "cred_a_1"}),
   "kế hoạch nói trước quyền sẽ đặt")
ok("(private to that account)" in P.describe_plan({"drive": True, "drive_token_id": "cred_a_1", "drive_public": False}),
   "kế hoạch nói riêng tư khi người dùng chọn thế")

print("── H. drive_export thật với dịch vụ giả ────────────────────")


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Status:
    def __init__(self, n):
        self.resumable_progress = n


class Req:
    def __init__(self, seq):
        self.seq = list(seq)

    def next_chunk(self):
        return self.seq.pop(0)


class FakeFiles:
    def __init__(self):
        self.created, self.lists, self.pages, self.req, self.get_result = [], [], [], None, None
        self.updated, self.perms = [], []

    def update(self, **kw):
        self.updated.append(kw)
        return _Exec({"id": kw.get("fileId")})

    def create(self, body=None, media_body=None, fields=None):
        self.created.append((body, media_body, fields))
        return self.req

    def list(self, **kw):
        self.lists.append(kw)
        return _Exec(self.pages.pop(0))

    def get(self, **kw):
        return _Exec(self.get_result)


class FakeSvc:
    def __init__(self):
        self.f = FakeFiles()

    def files(self):
        return self.f

    def permissions(self):
        files = self.f

        class Perms:
            def create(self, **kw):
                files.perms.append(kw)
                return _Exec({"id": "perm1"})
        return Perms()


class FakeMedia:
    made = []

    def __init__(self, path, chunksize=None, resumable=None):
        self.path, self.chunksize, self.resumable, self.closed = path, chunksize, resumable, False
        FakeMedia.made.append(self)

    def stream(self):
        media = self

        class S:
            def close(self):
                media.closed = True
        return S()


for n in REAL:
    setattr(DX, n, REAL[n])
DX._gapi = lambda: (None, FakeMedia, None)
svc = FakeSvc()
svc.f.req = Req([(Status(8), None), (Status(16), None), (None, {"id": "u1", "webViewLink": "L"})])
seen = []
got = DX.upload_file(svc, AUD1, "scene_001.mp3", "fold", seen.append)
ok(got == {"id": "u1", "webViewLink": "L"} and seen == [8, 16, 70], "upload_file: báo byte từng khúc rồi cỡ thật", seen)
body, media, _ = svc.f.created[-1]
ok(body == {"name": "scene_001.mp3", "parents": ["fold"]} and media.resumable and media.chunksize == DX.CHUNK_BYTES and media.closed,
   "resumable theo khúc, đúng thư mục, đóng file sau khi xong (Windows khoá file mở)")
svc.f.req = Req([(Status(8), None), (Status(16), None), (None, {"id": "u2"})])
seen2 = []


class Stop(Exception):
    pass


try:
    DX.upload_file(svc, AUD1, "x.mp3", "fold", seen2.append, lambda: bool(seen2), lambda: Stop("cancel"))
    ok(False, "huỷ phải ném")
except Stop:
    ok(seen2 == [8] and FakeMedia.made[-1].closed, "huỷ giữa hai khúc → ném lỗi huỷ, vẫn đóng file", seen2)


class FakeSheets:
    def __init__(self, titles, fail_format=False):
        self.log, self.titles, self.fail_format = [], titles, fail_format

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId=None, fields=None):
        return _Exec({"sheets": [{"properties": {"sheetId": i, "title": t}} for i, t in self.titles]})

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.log.append(("batchUpdate", body))
        if "requests" in body:
            if self.fail_format and any("repeatCell" in r for r in body["requests"]):
                return _Exec(RuntimeError("format boom"))
            replies, nid = [], 11
            for r in body["requests"]:
                if "addSheet" in r:
                    replies.append({"addSheet": {"properties": {"sheetId": nid, "title": r["addSheet"]["properties"]["title"]}}})
                    nid += 1
                else:
                    replies.append({})
            return _Exec({"replies": replies})
        return _Exec({})

    def batchClear(self, spreadsheetId=None, body=None):
        self.log.append(("batchClear", body))
        return _Exec({})


sh = FakeSheets([(0, "Trang tính1")])
long_cell = "z" * (DX.CELL_MAX + 10)
DX.write_sheet(sh, "S1", [("Overview", [["Field", "Value"], ["Title", "T"]]), ("Scenes", [["Scene"], ["=calm", long_cell]]),
                          ("Script", [["Script"]])], {"Scenes": {2: 460}})
struct = sh.log[0][1]["requests"]
ok(struct[0] == {"updateSheetProperties": {"properties": {"sheetId": 0, "title": "Overview"}, "fields": "title"}}
   and [r["addSheet"]["properties"]["title"] for r in struct[1:]] == ["Scenes", "Script"],
   "tab mặc định đổi tên thành Overview, thêm Scenes + Script", struct)
ok(sh.log[1] == ("batchClear", {"ranges": ["'Overview'", "'Scenes'", "'Script'"]}), "xoá nội dung cũ của ba tab", sh.log[1])
vals = sh.log[2][1]
scene_vals = next(x["values"] for x in vals["data"] if x["range"] == "'Scenes'!A1")
ok(vals["valueInputOption"] == "RAW" and scene_vals[1][0] == "=calm" and len(scene_vals[1][1]) == DX.CELL_MAX
   and scene_vals[1][1].endswith("…"), "RAW (không thành công thức), ô quá dài cắt đúng trần", (vals["valueInputOption"], len(scene_vals[1][1])))
fmt = sh.log[3][1]["requests"]
frozen = sorted(r["updateSheetProperties"]["properties"]["sheetId"] for r in fmt if "updateSheetProperties" in r)
ok(frozen == [0, 11, 12] and any(r.get("updateDimensionProperties", {}).get("range", {}).get("startIndex") == 2 for r in fmt),
   "định dạng: đậm + cố định dòng đầu cho cả tab mới (id từ replies), độ rộng cột", frozen)
sh2 = FakeSheets([(0, "Overview"), (5, "Scenes"), (6, "Script")], fail_format=True)
DX.write_sheet(sh2, "S2", [("Overview", [["a"]]), ("Scenes", [["b"]]), ("Script", [["c"]])])
ok(sh2.log[0][0] == "batchClear" and len(sh2.log) == 3 and "requests" in sh2.log[2][1],
   "tab đã đủ → không sửa cấu trúc; định dạng hỏng không làm hỏng lượt ghi",
   [x[0] for x in sh2.log])

svc2 = FakeSvc()
svc2.f.pages = [{"files": [{"name": "T"}, {"name": "T (2)"}]}]
ok(DX.unique_name(svc2, "root", "T") == "T (3)", "unique_name: đã có T, T (2) → T (3)")
svc2.f.pages = [{"files": []}]
ok(DX.unique_name(svc2, "root", "Bob's") == "Bob's" and "name contains 'Bob\\'s'" in svc2.f.lists[-1]["q"]
   and "mimeType = 'application/vnd.google-apps.folder'" in svc2.f.lists[-1]["q"], "tên chưa có → giữ; dấu nháy được thoát", svc2.f.lists[-1]["q"])
svc2.f.pages = [{"files": [{"name": "a", "id": "1"}], "nextPageToken": "p2"}, {"files": [{"name": "b", "id": "2"}, {"name": "a", "id": "dup"}]}]
kids = DX.list_children(svc2, "fold")
ok(set(kids) == {"a", "b"} and kids["a"]["id"] == "1" and svc2.f.lists[-1]["pageToken"] == "p2", "list_children: nhiều trang, trùng tên giữ cái đầu")
svc2.f.get_result = RuntimeError("<HttpError 404 File not found: notFound>")
ok(DX.file_alive(svc2, "x") is None, "file_alive: 404 → None")
svc2.f.get_result = {"id": "x", "trashed": True}
ok(DX.file_alive(svc2, "x") is None, "file_alive: trong thùng rác → None")
svc2.f.get_result = {"id": "x", "trashed": False, "name": "n"}
ok(DX.file_alive(svc2, "x")["name"] == "n", "file_alive: còn → trả file")
svc2.f.get_result = RuntimeError("<HttpError 500 backendError>")
try:
    DX.file_alive(svc2, "x")
    ok(False, "lỗi khác phải ném")
except RuntimeError:
    ok(True, "file_alive: lỗi mạng/máy chủ → ném (không tạo thư mục trùng)")

svc4 = FakeSvc()
svc4.f.pages = [{"files": [{"id": "r1", "name": "tuan89tk-vps-k7m2qx", "mimeType": DX.FOLDER_MIME}]}]
got = DX.find_or_create_folder(svc4, "root", "tuan89tk-vps-k7m2qx")
q4 = svc4.f.lists[-1]["q"]
ok(got["id"] == "r1" and not svc4.f.created and "'root' in parents" in q4 and "name = 'tuan89tk-vps-k7m2qx'" in q4
   and "mimeType = 'application/vnd.google-apps.folder'" in q4 and "trashed = false" in q4,
   "find_or_create_folder: hỏi đúng tên trong thư mục cha (không liệt kê cả gốc) → dùng lại", q4)
svc4.f.pages = [{"files": []}]
svc4.f.req = _Exec({"id": "new1", "name": "bob's-vps-2"})
got = DX.find_or_create_folder(svc4, "root", "bob's-vps-2")
ok(got["id"] == "new1" and svc4.f.created[-1][0] == {"name": "bob's-vps-2", "mimeType": DX.FOLDER_MIME, "parents": ["root"]}
   and "name = 'bob\\'s-vps-2'" in svc4.f.lists[-1]["q"], "chưa có → tạo ở gốc; dấu nháy được thoát", svc4.f.lists[-1]["q"])
svc4.f.get_result = {"id": "0AROOT"}
ok(DX.my_drive_root_id(svc4) == "0AROOT", "my_drive_root_id: id thật của gốc My Drive")
DX.move_folder(svc4, "p1", "r1", ["0AROOT"])
ok(svc4.f.updated[-1] == {"fileId": "p1", "addParents": "r1", "removeParents": "0AROOT", "fields": "id, parents"},
   "move_folder: thêm cha mới, bỏ cha cũ", svc4.f.updated[-1])
ok('fields="id, name, mimeType, trashed, webViewLink, parents"' in Path(DX.__file__).read_text(encoding="utf-8"),
   "file_alive lấy cả parents (biết project còn nằm ở gốc không)")

svc3 = FakeSvc()
DX.share_public(svc3, "fold1")
ok(svc3.f.perms == [{"fileId": "fold1", "body": {"type": "anyone", "role": "reader"}, "fields": "id"}],
   "share_public: quyền anyone/reader, KHÔNG bật allowFileDiscovery (không lên tìm kiếm Google)", svc3.f.perms)
ok(svc3.f.updated == [{"fileId": "fold1", "body": {"copyRequiresWriterPermission": False}, "fields": "id"}],
   "share_public: tắt cờ chặn người xem tải/copy/in", svc3.f.updated)
ok(DX.download_url("abc123") == "https://drive.google.com/uc?export=download&id=abc123", "link tải thẳng file")

print("── I. /assignees ───────────────────────────────────────────")
from tubecli.extensions.codex import routes as CR  # noqa: E402


class AgentRow:
    id, name, role, model = "a1", "MC", "writer", "m"
    system_prompt = "x\n[[AUTH-ACCESS-GUIDE]]\ncreds: cred_a, cred_b\n[[/AUTH-ACCESS-GUIDE]]"


AG.agent_manager.get_all = lambda: [AgentRow()]
res = asyncio.run(CR.list_assignees())
ok(res["agents"][0]["auth_creds"] == ["cred_a", "cred_b"] and "system_prompt" not in res["agents"][0],
   "/assignees: auth_creds, không lộ system_prompt", res["agents"][0])

CFG.DATA_DIR, CFG.EXTENSIONS_EXTERNAL_DIR = _REAL_DATA_DIR, _REAL_EXT_DIR
print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
