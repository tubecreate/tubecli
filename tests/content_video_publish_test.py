# -*- coding: utf-8 -*-
"""Đăng thẳng lên YouTube sau khi dựng xong — bước "publish" của content_video.

Run:  python tests/content_video_publish_test.py     (exit 0 = pass)

Không server, không mạng. Chủ đề: mỗi lượt thu thập thành công → agent viết
kịch bản theo vibe của nó → dựng mp4 → ĐĂNG LUÔN, không qua duyệt, tiêu đề/mô
tả/hashtag sinh từ TÊN KÊNH + dữ liệu đã gom.

Kiểm, đối chiếu code thật trong extensions/content_video/pipeline.py:
  A. nạp module video_manager theo ĐƯỜNG DẪN TUYỆT ĐỐI — có/không cài, thư mục
     đổi tên vẫn tra ra bằng manifest; chưa cài → cảnh báo sạch, không sập
  B. _vm_token             — chọn theo TOKEN_ID; đưa credential_id (9 token dùng
                             chung một credential trên máy thật) → "" chứ KHÔNG
                             bốc nhầm tài khoản anh em
  C. _channel_profile      — tên + phần giới thiệu kênh; kênh lạ → {} (tra được,
                             không có) NHƯNG lỗi/chưa cài/không token → None
                             (KHÔNG tra được) — hai chuyện khác hẳn nhau
  D. _seo_for              — prompt mang TÊN KÊNH + giới thiệu kênh + nguồn;
                             ép đúng giới hạn thật của YouTube (100/5000/500);
                             model câm/trả rác → bản dự phòng + CẢNH BÁO;
                             seo_* của người gọi thắng và khỏi gọi model
  E. run_render + publish  — upload thành công → state["published"], dòng
                             **Published** + link trong kết quả, link vào bản tin
  F. upload hỏng           — cảnh báo + "completed with warning" + mp4 VẪN được
                             báo cáo (không mất lượt dựng), publish không bao giờ
                             là bước bắt buộc
  G. publish tắt           — bước bị bỏ qua, KHÔNG hỏi token, không đăng
  H. kênh THẬT + sổ         — uploader trả channelId YouTube thật sự xếp video
                             vào: lệch kênh đã chọn ⇒ cảnh báo nêu cả hai + báo
                             cáo lấy tên kênh THẬT; đăng xong mới ghi sổ cò súng
                             (commit_published), và chỉ cho lượt do cò súng
  I. đăng hai lần           — task đã ghi video_id thì KHÔNG upload nữa; kết quả
                             của lượt đã đăng không mời "Request changes" nữa
  J. thiếu năng lực         — bật publish mà bước bị bỏ vì thiếu Video Manager:
                             đầu đề ⚠️ + bản tin 🔔 nhận cảnh báo, không phải ✅
"""
import io
import json
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

import tubecli.config as CFG                                  # noqa: E402
from tubecli.extensions.content_video import pipeline as P     # noqa: E402

_REAL_EXT_DIR = CFG.EXTENSIONS_EXTERNAL_DIR     # trả lại nguyên trạng ở cuối file
failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("ĐĂNG THẲNG LÊN YOUTUBE SAU KHI DỰNG (content_video · publish)")
print("=" * 70)

# ── A. nạp uploader/channel_manager của video_manager theo đường dẫn ────────
FAKE_UPLOADER = '''
CALLS = []
MODE = "success"
# channelId YouTube THẬT SỰ xếp video vào — bản thật lấy từ snippet của bản ghi
# vừa chèn (videos.insert không có ô chọn kênh; token quyết định).
CHANNEL_ID = ""


def upload_video(file_path, access_token, title, description="", tags=None,
                 category_id="22", privacy="private", progress_callback=None):
    CALLS.append({"file_path": file_path, "access_token": access_token, "title": title,
                  "description": description, "tags": list(tags or []),
                  "category_id": category_id, "privacy": privacy})
    if progress_callback:
        progress_callback(5, 10)
        progress_callback(10, 10)
    if MODE == "error":
        return {"status": "error", "message": "The user has exceeded the number of videos they may upload"}
    return {"status": "success", "video_id": "VID12345678",
            "url": "https://www.youtube.com/watch?v=VID12345678",
            "message": "Video uploaded successfully", "title": title,
            "channel_id": CHANNEL_ID}
'''
FAKE_CHANNELS = '''
CALLS = []
FAIL = False
CHANNELS = [
    {"id": "UC_main", "title": "Bep Nha Minh", "description": "Kenh nau an gia dinh, mon Viet de lam."},
    {"id": "UC_two", "title": "Second channel", "description": "khac"},
]


def list_channels(access_token):
    CALLS.append(access_token)
    if FAIL:
        raise RuntimeError("quotaExceeded")
    return [dict(c) for c in CHANNELS]
'''

empty_dir = tempfile.mkdtemp(prefix="cv-no-vm-")
pack_root = tempfile.mkdtemp(prefix="cv-vm-")
# Thư mục CỐ TÌNH không tên "video_manager": bản tải từ Chợ có thể giải nén ra
# tên khác, và ta tra bằng manifest đúng như extension_manager làm.
pack = os.path.join(pack_root, "vm_pack_2026")
os.makedirs(os.path.join(pack, "providers", "youtube"))
io.open(os.path.join(pack, "tubecli-extension.json"), "w", encoding="utf-8").write(
    json.dumps({"name": "video_manager", "version": "1", "entry": "extension.py"}))
io.open(os.path.join(pack, "providers", "youtube", "uploader.py"), "w", encoding="utf-8").write(FAKE_UPLOADER)
io.open(os.path.join(pack, "providers", "youtube", "channel_manager.py"), "w", encoding="utf-8").write(FAKE_CHANNELS)

CFG.EXTENSIONS_EXTERNAL_DIR = Path(empty_dir)
P._VM_MODULES.clear()
check("A chưa cài video_manager → _vm_uploader() là None", P._vm_uploader() is None)
check("A   và không nhớ cái None đó (cài xong khỏi khởi động lại)", P._VM_MODULES == {}, P._VM_MODULES)

CFG.EXTENSIONS_EXTERNAL_DIR = Path(pack_root)
P._VM_MODULES.clear()
check("A thư mục đổi tên vẫn tra ra bằng manifest", P._vm_dir() == pack, P._vm_dir())
UP = P._vm_uploader()
CH = P._vm_channel_manager()
check("A nạp uploader theo đường dẫn tuyệt đối", UP is not None and callable(getattr(UP, "upload_video", None)))
check("A nạp channel_manager", CH is not None and callable(getattr(CH, "list_channels", None)))
check("A không dính vào sys.modules của TubeCLI",
      "tubecli_vm_youtube_uploader" not in sys.modules, "module giả đã chen vào sys.modules")
print("A nap module : chưa cài → None (không sập) | tra theo manifest | uploader + channel_manager rời từng file")

# ── B. token CHỌN THEO TOKEN_ID, không bao giờ theo credential_id ───────────
import tubecli.extensions.auth_manager.extension as AM    # noqa: E402

# Ảnh máy thật: chín token YouTube dùng CHUNG một credential cred_d5e36724.
TOKENS = [{"token_id": f"tok_{i}", "credential_id": "cred_d5e36724", "provider": "google",
           "authorized_email": f"kenh{i}@gmail.com", "scopes": ["youtube", "youtube_upload"],
           "status": "active"} for i in range(1, 10)]
asked = []


class FakeAuth:
    def list_tokens(self, provider=None):
        asked.append(("list", provider))
        return [dict(t) for t in TOKENS] if provider in (None, "google") else []

    def get_active_token(self, identifier):
        asked.append(("get", identifier))
        # Bản thật cũng lùi về "token đầu tiên của credential" khi đưa cred_id —
        # chính cái bẫy này là lý do pipeline phải kiểm token_id trước.
        for t in TOKENS:
            if t["token_id"] == identifier:
                return "ya29." + identifier
        for t in TOKENS:
            if t["credential_id"] == identifier:
                return "ya29." + t["token_id"]
        return None


AM.auth_manager = FakeAuth()
asked.clear()
check("B token_id → đúng token của tài khoản đó", P._vm_token("tok_7") == "ya29.tok_7", asked)
check("B   hỏi auth_manager bằng CHÍNH token_id", ("get", "tok_7") in asked, asked)
asked.clear()
got = P._vm_token("cred_d5e36724")
check("B credential_id (9 tài khoản dùng chung) → '' chứ không bốc nhầm", got == "", got)
check("B   và KHÔNG hề gọi get_active_token với credential đó",
      not any(a[0] == "get" for a in asked), asked)
check("B token_id không có thật → ''", P._vm_token("tok_khong_co") == "")
check("B rỗng → '' (không hỏi gì)", P._vm_token("") == "")


class DeadAuth(FakeAuth):
    def get_active_token(self, identifier):
        return None            # hết hạn, refresh hỏng


AM.auth_manager = DeadAuth()
check("B token chết → ''", P._vm_token("tok_3") == "")
AM.auth_manager = FakeAuth()
print("B token      : theo TOKEN_ID | credential dùng chung → '' | token chết → ''")

# ── C. hồ sơ kênh ──────────────────────────────────────────────────────────
prof = P._channel_profile("ya29.tok_7", "UC_main")
check("C tên kênh + phần giới thiệu", prof.get("name") == "Bep Nha Minh"
      and prof.get("about", "").startswith("Kenh nau an"), prof)
check("C không nêu kênh → kênh đầu tiên", P._channel_profile("ya29.tok_7", "").get("id") == "UC_main")
check("C tra được mà không có kênh đó → {}", P._channel_profile("ya29.tok_7", "UC_la") == {})
# {} và None là hai câu trả lời KHÁC NHAU. Gộp chúng lại chính là cách một cú
# rớt mạng biến thành lời khẳng định "tài khoản này không quản lý kênh X".
CH.FAIL = True
got = P._channel_profile("ya29.tok_7", "UC_main")
check("C YouTube lỗi → None (KHÔNG tra được), không ném", got is None, got)
CH.FAIL = False
check("C không có token → None (chưa tra được lần nào)",
      P._channel_profile("", "UC_main") is None)
CFG.EXTENSIONS_EXTERNAL_DIR = Path(empty_dir)
P._VM_MODULES.clear()
check("C chưa cài video_manager → None", P._channel_profile("ya29.tok_7", "UC_main") is None)
CFG.EXTENSIONS_EXTERNAL_DIR = Path(pack_root)
P._VM_MODULES.clear()
UP, CH = P._vm_uploader(), P._vm_channel_manager()
check("C tra được thì danh sách là danh sách", len(P._channels("ya29.tok_7") or []) == 2)
CH.FAIL = True
check("C   lỗi → None chứ không phải []", P._channels("ya29.tok_7") is None)
CH.FAIL = False
print("C kenh       : tên + giới thiệu | không có kênh đó → {} | KHÔNG tra được → None (khác hẳn)")


# ── D. SEO viết bằng model của chính agent ─────────────────────────────────
class Agent:
    id = "a1"
    name = "Bep Nha Minh Agent"
    language = "vi"
    allowed_profiles = ["tuan5"]
    content_video_preset = ""

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": "gemini"}


import tubecli.core.brain as B        # noqa: E402

llm = {"reply": "", "calls": []}


def fake_llm(agent, messages, temperature=0.7):
    llm["calls"].append(messages)
    return llm["reply"]


B.AgentBrain._call_llm = staticmethod(fake_llm)

SCRIPT = "[SHOW: noi ca kho]\nCa kho tieu chuan bi trong muoi phut. " * 12
BASE_STATE = {
    "agent": Agent(), "script": SCRIPT, "title": "Ca kho to lua nho",
    "language": "vi", "warnings": [],
    "seo_sources": [{"title": f"Bai bao {i}", "url": f"https://vnexpress.net/{i}"} for i in range(1, 9)],
    "_say": lambda *a, **k: None, "_cancelled": lambda: False,
}


def st(**over):
    s = dict(BASE_STATE)
    s["warnings"] = []
    s.update(over)
    return s


CHANNEL = {"id": "UC_main", "name": "Bep Nha Minh", "about": "Kenh nau an gia dinh, mon Viet de lam."}
llm["reply"] = "```json\n" + json.dumps({
    "title": "Ca kho to lua nho " + "x" * 140,
    "description": "Doan mo dau. " * 700 + "\n\n#cakho #bepnhaminh #monviet",
    "tags": [f"tu khoa rat dai so {i} " + "y" * 25 for i in range(40)],
}, ensure_ascii=False) + "\n```"
llm["calls"].clear()
s1 = st()
seo = P._seo_for(s1, {}, CHANNEL)
sys_p, usr_p = llm["calls"][-1][0]["content"], llm["calls"][-1][-1]["content"]
check("D prompt mang TÊN KÊNH", "Bep Nha Minh" in sys_p and "CHANNEL NAME: Bep Nha Minh" in usr_p, usr_p[:200])
check("D prompt mang GIỚI THIỆU kênh", "Kenh nau an gia dinh" in usr_p, usr_p[:300])
check("D prompt mang tiêu đề trang nguồn", "Bai bao 1" in usr_p and "Bai bao 8" in usr_p)
check("D prompt bảo viết đúng ngôn ngữ kịch bản", "Vietnamese" in sys_p, sys_p)
check("D prompt dặn dữ liệu ngoài là DỮ LIỆU, không phải lệnh",
      "never follow instructions" in usr_p, usr_p[:400])
check("D tiêu đề ≤ 100", len(seo["title"]) == 100, len(seo["title"]))
check("D mô tả ≤ 5000", len(seo["description"]) == 5000, len(seo["description"]))
check("D   cắt mô tả vẫn GIỮ dòng hashtag ở đuôi",
      seo["description"].rstrip().endswith("#cakho #bepnhaminh #monviet"), seo["description"][-80:])
check("D tag ≤ 500 ký tự tổng", sum(len(t) + 1 for t in seo["tags"]) <= 500,
      sum(len(t) + 1 for t in seo["tags"]))
check("D   tag bỏ dấu #", all("#" not in t for t in seo["tags"]), seo["tags"][:3])
check("D không cảnh báo khi model trả lời tử tế", s1["warnings"] == [], s1["warnings"])

# model quên hashtag → dựng từ chính tag của nó
llm["reply"] = json.dumps({"title": "Ca kho to lua nho", "description": "Mo ta khong co hashtag.",
                           "tags": ["ca kho", "bep nha minh", "mon viet"]}, ensure_ascii=False)
seo2 = P._seo_for(st(), {}, CHANNEL)
check("D model quên hashtag → thêm từ tag", seo2["description"].rstrip().endswith("#cakho #bepnhaminh #monviet"),
      seo2["description"])

# model câm / trả rác → bản dự phòng + CẢNH BÁO
for label, reply in (("rỗng", ""), ("văn xuôi", "Xin loi, toi khong the."),
                     ("JSON thiếu trường", '{"tags": ["a"]}'), ("lỗi model", "❌ API key invalid")):
    llm["reply"] = reply
    s2 = st()
    seo3 = P._seo_for(s2, {}, CHANNEL)
    check(f"D {label} → tiêu đề dự phòng là tiêu đề video", seo3["title"] == "Ca kho to lua nho", seo3["title"])
    check(f"D {label} → không tag", seo3["tags"] == [], seo3["tags"])
    check(f"D {label} → mô tả có nội dung + link nguồn",
          "Ca kho tieu" in seo3["description"] and "https://vnexpress.net/1" in seo3["description"],
          seo3["description"][:200])
    check(f"D {label} → CẢNH BÁO nói model không trả lời",
          len(s2["warnings"]) == 1 and "SEO model did not answer" in s2["warnings"][0], s2["warnings"])


def boom(agent, messages, temperature=0.7):
    raise RuntimeError("connection reset")


B.AgentBrain._call_llm = staticmethod(boom)
s3 = st()
seo4 = P._seo_for(s3, {}, CHANNEL)
check("D model ném lỗi → vẫn có SEO dự phòng + cảnh báo",
      seo4["title"] == "Ca kho to lua nho" and len(s3["warnings"]) == 1, s3["warnings"])
B.AgentBrain._call_llm = staticmethod(fake_llm)

# người gọi tự viết → khỏi gọi model
llm["calls"].clear()
seo5 = P._seo_for(st(), {"seo_title": "Tieu de tay", "seo_description": "Mo ta tay #tag",
                         "seo_tags": ["#mot", "hai"]}, CHANNEL)
check("D seo_* của người gọi thắng", seo5["title"] == "Tieu de tay" and seo5["description"] == "Mo ta tay #tag"
      and seo5["tags"] == ["mot", "hai"], seo5)
check("D   và KHÔNG gọi model lần nào", llm["calls"] == [], llm["calls"])
print("D seo        : prompt có tên kênh + giới thiệu + nguồn | ép 100/5000/500 | câm → dự phòng + cảnh báo | ghi đè thắng")

# ── E/F/G. cả lượt dựng: dựng xong → đăng ──────────────────────────────────
import tubecli.core.agent as AG                 # noqa: E402
import tubecli.core.scraped_store as SS         # noqa: E402
import tubecli.extensions.codex.manager as CM   # noqa: E402

AG.agent_manager.get = lambda aid: Agent() if aid == "a1" else None
SS.query = lambda **kw: {"items": []}
P._agent_scope = lambda agent: ["tuan5"]
P.check_job = lambda job: {"ready": True, "missing": [], "disabled": [], "missing_tools": []}
P.studio_capabilities = lambda: {"text": {"ok": True, "detail": "gemini"}, "image": {"ok": True, "detail": "cf"},
                                 "assembly": {"ok": True}, "voice": {"ok": True}}
P._read_checkpoint = lambda tid: {}
P._write_checkpoint = lambda tid, d: None
P._stream_storyboard = lambda ep_id, state: None
CM.codex_manager.get_task = lambda tid: {"id": tid, "goal": "g"}
MP4 = r"C:\data\content_video\episode_34_pipeline_export.mp4"


def fake_post(path, payload, timeout=300):
    if path == "/api/v1/studio/dramas":
        return {"id": 12}
    if path == "/api/v1/studio/dramas/12/episodes":
        return {"id": 34}
    if path.endswith("/gen-images"):
        return {"task_id": "img1", "total": 2}
    if path.endswith("/batch-tts"):
        return {"task_id": "tts1"}
    if path.endswith("/export-ffmpeg"):
        return {"task_id": "exp1"}
    raise AssertionError(path)


def fake_get(path, timeout=60):
    if path == "/api/v1/studio/episodes/34/storyboards":
        return [{"id": 1, "narration_text": "a"}, {"id": 2, "narration_text": "b"}]
    if "gen-images/status" in path:
        return {"status": "completed", "done": 2, "total": 2, "errors": []}
    if "batch-tts/" in path:
        return {"status": "done", "success": 2, "failed": 0}
    if "export-ffmpeg/status" in path:
        return {"status": "completed", "done": 100, "total": 100}
    if path == "/api/v1/studio/episodes/34":
        return {"id": 34, "video_url": MP4}
    raise AssertionError(path)


P._post = fake_post
P._get = fake_get
P.installed_extensions = lambda: {"tts_vibevoice": True, "video_manager": True, "content_studio": True}
bulletins = []
P._bulletin = lambda state, outcome, duration, error, stage: bulletins.append(
    (outcome, dict(state.get("published") or {}), list(state.get("warnings") or [])))
token_asks = []
_real_vm_token = P._vm_token
P._vm_token = lambda tid: token_asks.append(tid) or "ya29.tok_7"

llm["reply"] = json.dumps({
    "title": "Ca kho to lua nho — bi quyet cua Bep Nha Minh",
    "description": "Video hom nay ke ve ca kho.\n\n#cakho #bepnhaminh #monviet",
    "tags": ["ca kho", "bep nha minh", "mon viet"]}, ensure_ascii=False)

RENDER = {"kind": P.KIND_RENDER, "task_id": "r1", "agent_id": "a1",
          "script": SCRIPT, "title": "Ca kho to lua nho", "language": "vi",
          "seo_sources": [{"title": "Bai bao 1", "url": "https://vnexpress.net/1"}],
          "options": {"publish": True, "publish_method": "api", "publish_token_id": "tok_7",
                      "publish_channel_id": "UC_main", "publish_channel_name": "Bep Nha Minh",
                      "publish_privacy": "public"}}

UP.CALLS.clear()
UP.MODE = "success"
token_asks.clear()
out = P.run_render(dict(RENDER), None, lambda: False)
call = UP.CALLS[-1] if UP.CALLS else {}
check("E gọi uploader với mp4 vừa dựng", call.get("file_path") == MP4, call.get("file_path"))
check("E   token của ĐÚNG tài khoản đã chọn", token_asks == ["tok_7"] and call.get("access_token") == "ya29.tok_7", token_asks)
check("E   tiêu đề/mô tả/tag do SEO sinh", call.get("title", "").startswith("Ca kho to lua nho")
      and "#cakho" in call.get("description", "") and call.get("tags") == ["ca kho", "bep nha minh", "mon viet"], call)
check("E   quyền riêng tư public (đăng luôn khỏi duyệt)", call.get("privacy") == "public", call.get("privacy"))
check("E   category 22", call.get("category_id") == "22", call.get("category_id"))
check("E kết quả có dòng **Published** kèm link, quyền và tên kênh",
      "- **Published**: https://www.youtube.com/watch?v=VID12345678 (public) → Bep Nha Minh" in out, out)
check("E kết quả vẫn có đường dẫn mp4", f"- **Video**: `{MP4}`" in out, out)
check("E đầu đề vẫn là ✅ (không cảnh báo)", out.startswith("## ✅"), out.splitlines()[0])
check("E bản tin nhận link video", bulletins and bulletins[-1][1].get("url", "").endswith("VID12345678"), bulletins[-1:])
check("E đã đăng rồi thì đừng mời 'Request changes' — nó đăng thêm video THỨ HAI",
      "**Already live**" in out and "second video" in out
      and "**Request changes** re-renders this script" not in out, out)
check("E   link ngắn lọt vào một dòng bản tin 60 ký tự",
      P._short_youtube("https://www.youtube.com/watch?v=VID12345678") == "https://youtu.be/VID12345678",
      P._short_youtube("https://www.youtube.com/watch?v=VID12345678"))
print("E dang       : mp4 → uploader (token đúng, SEO đúng, public) | dòng Published + link | bản tin có link")

# kênh đã chọn không còn thuộc tài khoản → vẫn đăng, nhưng nói ra
UP.CALLS.clear()
bad = dict(RENDER)
bad["options"] = {**RENDER["options"], "publish_channel_id": "UC_da_go"}
out_b = P.run_render(bad, None, lambda: False)
check("E kênh lạ → vẫn đăng vào kênh mặc định + cảnh báo",
      "does not manage channel UC_da_go" in out_b and "**Published**" in out_b, out_b)

# tra kênh HỎNG (rớt mạng / hết quota) KHÁC "tài khoản không quản lý kênh này".
# Câu sau là lời khẳng định về đúng thứ người dùng quan tâm nhất — không được
# nói ra khi ta còn chưa hỏi được YouTube.
UP.CALLS.clear()
CH.FAIL = True
out_q = P.run_render(dict(RENDER), None, lambda: False)
CH.FAIL = False
check("E lỗi tra kênh → KHÔNG vu cho tài khoản là 'không quản lý kênh này'",
      "does not manage channel" not in out_q, out_q)
check("E   nói đúng bệnh: không đọc được danh sách kênh",
      "Could not read this YouTube account" in out_q, out_q)
check("E   và video VẪN được đăng", "**Published**" in out_q and len(UP.CALLS) == 1, out_q)

# ── H. kênh THẬT + ghi sổ cò súng ──────────────────────────────────────────
# uploader trả channelId YouTube thật sự xếp video vào. Báo cáo cái kênh người
# dùng BẤM kèm dấu ✅ trong khi video nằm ở kênh khác là nói sai.
UP.CALLS.clear()
UP.CHANNEL_ID = "UC_main"
out_h = P.run_render(dict(RENDER), None, lambda: False)
check("H kênh thật khớp kênh đã chọn → không cảnh báo, vẫn ✅",
      out_h.startswith("## ✅") and "filed this video under" not in out_h, out_h.splitlines()[0])
check("H   nhớ id kênh thật vào published",
      bulletins[-1][1].get("channel_id") == "UC_main", bulletins[-1][1])

UP.CHANNEL_ID = "UC_two"                      # token hoá ra đang giữ kênh khác
out_c = P.run_render(dict(RENDER), None, lambda: False)
UP.CHANNEL_ID = ""
check("H YouTube xếp vào kênh KHÁC → cảnh báo nêu cả kênh thật lẫn kênh đã chọn",
      "UC_two" in out_c and "UC_main" in out_c and "filed this video under" in out_c, out_c)
check("H   đầu đề đổi thành ⚠️ chứ không phải dấu tích sạch",
      out_c.startswith("## ⚠️"), out_c.splitlines()[0])
check("H   dòng Published gọi tên kênh THẬT, không phải kênh người dùng bấm",
      "→ Second channel" in out_c and "→ Bep Nha Minh" not in out_c, out_c)
check("H   published.channel_id là kênh thật", bulletins[-1][1].get("channel_id") == "UC_two",
      bulletins[-1][1])

# Sổ của cò súng chỉ được ghi SAU KHI video đã lên kênh — và chỉ cho lượt do
# chính cò súng châm ngòi.
import tubecli.extensions.content_video.autopublish as AP    # noqa: E402

commits = []
AP.commit_published = lambda *a, **kw: commits.append((a, kw)) or "counted"
UP.CALLS.clear()
P.run_render(dict(RENDER), None, lambda: False)
check("H lượt dựng THỦ CÔNG có publish → KHÔNG tiêu suất nào của cò súng",
      commits == [], commits)
AUTO = dict(RENDER)
AUTO["options"] = {**RENDER["options"], "autopublish": True}
AUTO["high_water"] = "2026-09-04T09:00:00+00:00"
commits.clear()
P.run_render(dict(AUTO), None, lambda: False)
check("H lượt do cò súng → ghi sổ đúng một lần, sau khi đăng xong", len(commits) == 1, commits)
if commits:
    args, kwargs = commits[0]
    check("H   ghi đúng agent + mốc đã tiêu", args == ("a1", "2026-09-04T09:00:00+00:00"), args)
    check("H   kèm link video + id task (để commit hai lần chỉ tính một)",
          kwargs.get("video_url", "").endswith("VID12345678") and kwargs.get("task_id") == "r1",
          kwargs)
commits.clear()
UP.MODE = "error"
out_ce = P.run_render(dict(AUTO), None, lambda: False)
UP.MODE = "success"
check("H upload hỏng → KHÔNG ghi sổ: mốc không dời, suất ngày không tiêu",
      commits == [] and "completed with warning" in out_ce, commits)

# ── I. không bao giờ đăng hai lần cho cùng một task ────────────────────────
UP.CALLS.clear()
commits.clear()
P._read_checkpoint = lambda tid: {"published": {"video_id": "OLD123", "privacy": "public",
                                                "url": "https://www.youtube.com/watch?v=OLD123",
                                                "channel_name": "Bep Nha Minh"}}
out_i = P.run_render(dict(AUTO), None, lambda: False)
P._read_checkpoint = lambda tid: {}
check("I task đã ghi video_id → KHÔNG upload lần thứ hai", UP.CALLS == [], UP.CALLS)
check("I   cũng không đếm thêm một suất ngày nữa", commits == [], commits)
check("I   và báo cáo đúng cái video đang sống", "OLD123" in out_i, out_i)
print("H kenh that  : channelId của YouTube thắng | lệch kênh → ⚠️ + tên kênh thật | sổ ghi SAU khi đăng")
print("I hai lan    : task đã có video_id thì bỏ qua bước đăng, không đẩy video thứ hai")

# ── F. upload hỏng: mp4 KHÔNG được mất ─────────────────────────────────────
UP.CALLS.clear()
UP.MODE = "error"
out_f = P.run_render(dict(RENDER), None, lambda: False)
UP.MODE = "success"
check("F đầu đề nói 'completed with warning'", out_f.startswith("## ⚠️") and "completed with warning" in out_f,
      out_f.splitlines()[0])
check("F mp4 VẪN được báo cáo", f"- **Video**: `{MP4}`" in out_f, out_f)
check("F cảnh báo kể nguyên văn lời của YouTube",
      "exceeded the number of videos" in out_f and "kept at" in out_f, out_f)
check("F ghi chú bước không chạy được", "**Publish to YouTube** failed" in out_f, out_f)
check("F không có dòng Published", "**Published**" not in out_f, out_f)
check("F lượt chạy KHÔNG mất: bản tin vẫn 'completed' kèm cảnh báo",
      bulletins[-1][0] == "completed" and any("Upload to YouTube failed" in w for w in bulletins[-1][2]),
      bulletins[-1])
# ép publish thành bước bắt buộc cũng không được phép làm đổ cả lượt
req = dict(RENDER)
req["options"] = {**RENDER["options"], "required_steps": ["publish", "render"]}
UP.MODE = "error"
out_r = P.run_render(req, None, lambda: False)
UP.MODE = "success"
check("F required_steps có 'publish' cũng không đánh đổ lượt dựng",
      "completed with warning" in out_r and f"- **Video**: `{MP4}`" in out_r, out_r[:200])

# chưa cài video_manager → cảnh báo sạch, mp4 còn nguyên
CFG.EXTENSIONS_EXTERNAL_DIR = Path(empty_dir)
P._VM_MODULES.clear()
out_n = P.run_render(dict(RENDER), None, lambda: False)
check("F chưa cài Video Manager → chỉ cảnh báo, mp4 còn nguyên",
      "Video Manager is not installed" in out_n and f"- **Video**: `{MP4}`" in out_n, out_n)
CFG.EXTENSIONS_EXTERNAL_DIR = Path(pack_root)
P._VM_MODULES.clear()
UP = P._vm_uploader()
CH = P._vm_channel_manager()

# không có token sống → cùng cách xử
P._vm_token = lambda tid: token_asks.append(tid) or ""
out_t = P.run_render(dict(RENDER), None, lambda: False)
check("F không có token sống → cảnh báo chỉ đúng chỗ sửa (Auth Manager), mp4 còn nguyên",
      "No live YouTube token" in out_t and "Auth Manager" in out_t and f"- **Video**: `{MP4}`" in out_t, out_t)
P._vm_token = lambda tid: token_asks.append(tid) or "ya29.tok_7"
print("F dang hong  : ⚠️ completed with warning | mp4 còn nguyên | chưa cài / hết token đều chỉ là cảnh báo")

# ── G. publish tắt ─────────────────────────────────────────────────────────
UP.CALLS.clear()
token_asks.clear()
says = []
off = dict(RENDER)
off["options"] = {}
out_g = P.run_render(off, lambda *a, **k: says.append(a), lambda: False)
check("G không bật publish → không hỏi token", token_asks == [], token_asks)
check("G   không gọi uploader", UP.CALLS == [], UP.CALLS)
check("G   bước publish được báo là bỏ qua",
      any(a[0] == "publish" and a[1] == "skipped" for a in says), [a for a in says if a[0] == "publish"])
check("G   kết quả không nhắc Published, vẫn ✅ + mp4",
      "**Published**" not in out_g and out_g.startswith("## ✅") and f"- **Video**: `{MP4}`" in out_g, out_g)
check("G   chưa đăng thì vẫn mời Accept / Request changes như cũ",
      "**Accept** when the video is good" in out_g and "**Already live**" not in out_g, out_g)
check("G DEFAULTS: publish tắt, privacy public, các khoá SEO có sẵn",
      P.DEFAULTS["publish"] is False and P.DEFAULTS["publish_privacy"] == "public"
      and P.DEFAULTS["publish_token_id"] == "" and P.DEFAULTS["seo_tags"] == [], P.DEFAULTS)
check("G publish là bước CUỐI của lượt dựng và tuỳ chọn",
      P.RENDER_STEPS[-1][0] == "publish" and P.RENDER_STEPS[-1][3] is True, P.RENDER_STEPS[-1])
print("G tat        : không hỏi token, không đăng, kết quả sạch | mặc định tắt + public")

# ── J. bật publish mà bước bị bỏ vì thiếu năng lực ─────────────────────────
# _run_steps bỏ qua bước tuỳ chọn khi thiếu extension. Nếu chỉ để lại một ghi
# chú ở cuối thì đầu đề vẫn ✅ và bản tin 🔔 vẫn hiện dấu tích sạch cho một lượt
# lẽ ra phải lên kênh — đúng cái kết cục im lặng phải tránh.
_real_check_job = P.check_job
P.check_job = lambda job: ({"ready": False, "missing": ["video_manager"], "disabled": [],
                            "missing_tools": []} if job == "publish"
                           else {"ready": True, "missing": [], "disabled": [], "missing_tools": []})
UP.CALLS.clear()
out_j = P.run_render(dict(RENDER), None, lambda: False)
P.check_job = _real_check_job
check("J bước đăng bị bỏ vì thiếu Video Manager → đầu đề ⚠️, KHÔNG phải ✅",
      out_j.startswith("## ⚠️") and "completed with warning" in out_j, out_j.splitlines()[0])
check("J   nói thẳng: không có gì được đăng cả", "Nothing was published" in out_j, out_j)
check("J   bản tin 🔔 cũng nhận cảnh báo (không hiện dấu tích sạch)",
      any("Nothing was published" in w for w in bulletins[-1][2]), bulletins[-1][2])
check("J   không hề gọi uploader", UP.CALLS == [], UP.CALLS)
check("J   mp4 vẫn được báo cáo nguyên vẹn", f"- **Video**: `{MP4}`" in out_j, out_j)
# publish TẮT thì bỏ qua là chuyện bình thường, không cảnh báo gì
P.check_job = lambda job: ({"ready": False, "missing": ["video_manager"], "disabled": [],
                            "missing_tools": []} if job == "publish"
                           else {"ready": True, "missing": [], "disabled": [], "missing_tools": []})
off2 = dict(RENDER)
off2["options"] = {}
out_j2 = P.run_render(off2, None, lambda: False)
P.check_job = _real_check_job
check("J publish TẮT + thiếu năng lực → không cảnh báo, vẫn ✅",
      out_j2.startswith("## ✅") and "Nothing was published" not in out_j2, out_j2.splitlines()[0])
print("J thieu nlvc : bật publish mà bước bị bỏ → ⚠️ + cảnh báo vào cả bản tin | tắt thì im lặng")

P._vm_token = _real_vm_token
CFG.EXTENSIONS_EXTERNAL_DIR = _REAL_EXT_DIR

# ── K. Đăng qua TRÌNH DUYỆT (mặc định) ──────────────────────────────────────
# Đường mặc định không phải API: script YouTube Studio của chính người dùng bật
# được KIẾM TIỀN và không đụng quota videos.insert. Ở đây chỉ giả run_script_sync
# — chạy thật là mở cả một trình duyệt.
import types as _types

_bs = _types.ModuleType("tubecli.extensions.browser_scripts.script_routes")
SCRIPT_CALLS = []
SCRIPT_RESULT = {"ok": True, "vars": {}, "log": ""}


class _RunRes(dict):
    def __init__(self, v, ok, log=""):
        super().__init__(v)
        self.success = ok
        self.log = log


def _fake_run_script_sync(slug, variables=None, profile="", headless=True, timeout=None):
    SCRIPT_CALLS.append({"slug": slug, "variables": dict(variables or {}),
                         "profile": profile, "headless": headless, "timeout": timeout})
    if isinstance(SCRIPT_RESULT.get("raise"), Exception):
        raise SCRIPT_RESULT["raise"]
    return _RunRes(SCRIPT_RESULT["vars"], SCRIPT_RESULT["ok"], SCRIPT_RESULT["log"])


_bs.run_script_sync = _fake_run_script_sync
sys.modules["tubecli.extensions.browser_scripts.script_routes"] = _bs

_kc = _types.ModuleType("tubecli.extensions.keychain.routes")
_kc.ensure_profile_for_account = lambda acc: {"profile": "kc_" + str(acc), "created": False}
sys.modules["tubecli.extensions.keychain.routes"] = _kc

check("K mặc định là đường trình duyệt, không phải API",
      P.DEFAULTS["publish_method"] == "script" and P.DEFAULTS["publish_script"] == "youtube_upload"
      and P.DEFAULTS["publish_monetize"] is False, P.DEFAULTS.get("publish_method"))

SCRIPT_CALLS[:] = []
SCRIPT_RESULT.update(ok=True, vars={"video_id": "VID_SCRIPT"}, log="")
SCR = dict(RENDER)
SCR["options"] = {**RENDER["options"], "publish_method": "script",
                  "publish_monetize": True, "publish_privacy": "unlisted"}
bulletins[:] = []
out_k = P.run_render(SCR, None, lambda: False)
call = SCRIPT_CALLS[-1] if SCRIPT_CALLS else {}
v = call.get("variables") or {}
check("K gọi đúng script của người dùng", call.get("slug") == "youtube_upload", call)
# Agent giả chưa có tài khoản đăng nhập nào → rơi về hồ sơ trong phạm vi của
# nó. Đó là hành vi ĐÚNG: hồ sơ ấy có thể chưa đăng nhập YouTube và script sẽ
# tự báo hỏng, còn hơn là đoán bừa một hồ sơ khác.
check("K chưa có tài khoản đăng nhập → dùng hồ sơ trong phạm vi agent",
      call.get("profile") == "tuan5", call.get("profile"))
# Có tài khoản Keychain thì ưu tiên nó: hồ sơ đó được đổ sẵn email/mật khẩu/2FA.
Agent.login_accounts = ["acc_yt"]
SCRIPT_CALLS[:] = []
P.run_render(dict(SCR), None, lambda: False)
check("K có tài khoản đăng nhập → hồ sơ của Keychain thắng",
      (SCRIPT_CALLS[-1].get("profile") if SCRIPT_CALLS else "") == "kc_acc_yt", SCRIPT_CALLS[-1:])
Agent.login_accounts = []
call = SCRIPT_CALLS[-1] if SCRIPT_CALLS else call
v = call.get("variables") or v
check("K PHẢI truyền timeout — nếu không thread gọi bị chặn vô hạn",
      isinstance(call.get("timeout"), (int, float)) and call["timeout"] > 0, call.get("timeout"))
check("K truyền đúng đường dẫn mp4", v.get("video_path") == MP4, v)
check("K chế độ hiển thị dịch sang tên radio của Studio",
      v.get("visibility_radio") == "UNLISTED", v)
check("K bật kiếm tiền — thứ API KHÔNG làm được", v.get("monetize") == "1", v)
check("K không hẹn giờ trong lượt tự động", v.get("schedule") == "0", v)
check("K tiêu đề cắt đúng 100 ký tự", len(v.get("title") or "") <= 100, len(v.get("title") or ""))
check("K hashtag nằm TRONG mô tả (Studio không có ô tags riêng)",
      "#" in (v.get("description") or ""), (v.get("description") or "")[-120:])
check("K KHÔNG hỏi token YouTube ở đường script",
      not any(t == "tok_7" for t in token_asks), token_asks)
check("K ghi nhận đã đăng, đánh dấu đi bằng script",
      bulletins and (bulletins[-1][1] or {}).get("via") == "script"
      and (bulletins[-1][1] or {}).get("video_id") == "VID_SCRIPT", bulletins[-1:])
check("K dòng Published có trong kết quả", "**Published**" in out_k, out_k[:300])

# script chạy nhưng KHÔNG xong → cảnh báo, mp4 vẫn còn
SCRIPT_CALLS[:] = []
SCRIPT_RESULT.update(ok=False, vars={}, log="Studio: nút Tiếp theo không hiện")
bulletins[:] = []
out_kf = P.run_render(dict(SCR), None, lambda: False)
check("K script hỏng → ⚠️ chứ không mất video đã dựng",
      "⚠️" in out_kf and MP4 in out_kf, out_kf[:300])
check("K   câu lỗi nhắc kiểm đăng nhập YouTube của hồ sơ",
      any("YouTube login" in w for w in (bulletins[-1][2] if bulletins else [])), bulletins[-1:])

# script chạy xong nhưng không trả id → vẫn coi là đã đăng, kèm cảnh báo trung thực
SCRIPT_CALLS[:] = []
SCRIPT_RESULT.update(ok=True, vars={}, log="")
bulletins[:] = []
out_kn = P.run_render(dict(SCR), None, lambda: False)
check("K không có id → nói thẳng là phải tự mở kênh kiểm",
      any("no video id" in w for w in (bulletins[-1][2] if bulletins else [])), bulletins[-1:])
SCRIPT_RESULT.update(ok=True, vars={"video_id": "VID_SCRIPT"}, log="")
print("K trinh duyet: script của người dùng | hồ sơ Keychain | có timeout | kiếm tiền | hashtag vào mô tả | hỏng thì giữ mp4")

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
