"""Đăng video đã dựng của task Review + sửa SEO video đã đăng, qua hàng đợi trình duyệt an toàn RAM (14/11/2026).

Chạy:  PYTHONIOENCODING=utf-8 python tests/publish_jobs_test.py      (mã thoát 0 = đạt)

Vì sao (contabo 6G): 74 task «Auto video» nằm Review với bước Publish tắt, Accept chỉ đóng task; không có token YouTube
⇒ chỉ đăng được qua YouTube Studio trong hồ sơ trình duyệt; VPS 6 GB từng sập vì mở nhiều trình duyệt.

  A. request_publish — từ chối đúng lý do (không phải video đã dựng, không ở review, đã đăng, thiếu file, kênh chưa
     xác minh + video > 15 phút, kênh không khớp hồ sơ nào, đang có việc); nhận thì xếp hàng và trả ngay
  B. chạy việc đăng — dùng file SẴN CÓ, tiêu đề / mô tả / tag của người gọi thắng, link thật vào kết quả + checkpoint,
     REVIEW → DONE mà KHÔNG gọi hook on_accept; không id ⇒ UNVERIFIED, task ở lại Review, lần sau phải force
  C. hàng đợi — một việc một lúc; RAM thấp / đang render ⇒ chờ rồi xét lại; luôn đóng hồ sơ (xong, lỗi, quá giờ);
     việc đang chạy lúc khởi động lại ⇒ interrupted (không tự đăng lại), việc đang chờ thì còn
  D. sửa SEO — chọn hồ sơ (profile > channel > task đã đăng video), biến của script, đọc báo cáo của script
  E. tĩnh — script sửa không đụng chế độ hiển thị; route có mặt

Cách ly: kho Codex + sổ việc trong thư mục tạm; _publish_now / script / hồ sơ trình duyệt / RAM / agent đều GIẢ —
không mở trình duyệt, không HTTP, không đụng dữ liệu thật.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
ROOT = Path(__file__).resolve().parent.parent

import tubecli.extensions.codex.manager as CMod  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f" — {str(detail)[:400]}"))
    if not ok:
        failures.append(label)


TMP = tempfile.mkdtemp(prefix="publish-jobs-")
CMod.CODEX_DATA_DIR = TMP
CMod.TASKS_FILE = os.path.join(TMP, "tasks.json")
CMod.EVENTS_DIR = os.path.join(TMP, "events")
cm = CMod.CodexManager()
cm.notifications_enabled = False
cm.post_to_chat = lambda *a, **k: None
CMod.codex_manager = cm

from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.extensions.content_video import publish_jobs as PJ  # noqa: E402

REAL_PUBLISH_NOW = P._publish_now                 # phần F chạy đường đăng THẬT của pipeline (chỉ script là giả)
import tubecli.extensions.content_video.publish_schedule as PS  # noqa: E402
PS._store_path = lambda: Path(TMP) / "publish_slots.json"       # sổ khung giờ cũng vào thư mục tạm
PJ._store_path = lambda: Path(TMP) / "publish_jobs.json"
import tubecli.extensions.content_video.autopublish as AP  # noqa: E402
AP._store_path = lambda: Path(TMP) / "autopublish.json"        # sổ trần ngày cũng vào thư mục tạm
PJ.start_worker = lambda: None                    # test tự gọi tick() — không có luồng nền nào
STOPS, RAM, RENDER = [], [4000.0], [""]
P._post = lambda path, payload, timeout=300: STOPS.append((path, payload.get("profile"))) or {}
PJ.free_ram_mb = lambda: RAM[0]
PJ.render_running = lambda: RENDER[0]
SECS = [600.0]
P.media_seconds = lambda path: SECS[0]


class Agent:
    def __init__(self, **kw):
        self.id = kw.get("id", "ag1")
        self.name = "Deep Biblical Echoes Niche Researcher"
        self.publish_profile = kw.get("publish_profile", "gmail_pk0789743")
        self.publish_channel_name = kw.get("publish_channel_name", "Pawan Kumar")
        self.publish_channel_id = kw.get("publish_channel_id", "")
        self.publish_privacy = "public"
        self.publish_unverified = kw.get("publish_unverified", False)
        self.publish_thumbnail = False
        self.publish_monetize = False
        self.publish_slots, self.publish_tz, self.publish_tz_offset = "12:00, 19:00", "Asia/Ho_Chi_Minh", 420
        self.allowed_profiles = [self.publish_profile]
        # 0 = không trần: các phần A–F xếp nhiều việc cho cùng một agent; trần ngày kiểm riêng ở phần G.
        self.publish_max_per_day = kw.get("publish_max_per_day", 0)


AGENTS = {"ag1": Agent(), "agU": Agent(id="agU", publish_unverified=True)}
import tubecli.core.agent as AgentMod  # noqa: E402


class FakeAgents:
    def get(self, aid):
        return AGENTS.get(aid)


AgentMod.agent_manager = FakeAgents()

PROFILES = [
    {"name": "gmail_singhradhika3976", "notes": ""},
    {"name": "gmail_pk0789743", "notes": "", "google_account": {"email": "pk0789743@gmail.com"}},
    {"name": "gmail_shivani123rb", "notes": ""},
    {"name": "stoic_shivani123rb", "notes": ""},
    {"name": "gmail_jayarajapatela", "notes": "kênh Jay"},
]
import tubecli.extensions.browser.profile_manager as PM  # noqa: E402
PM.list_profiles = lambda: [dict(p) for p in PROFILES]
PM.get_profile = lambda name: next((dict(p) for p in PROFILES if p["name"] == name), None)

HOOKS = []
for k in ("content_video.plan", "content_video.auto", "content_video.render"):
    cm.on_accept(k, lambda task, actor, _k=k: HOOKS.append((_k, task["id"])))
MP4 = os.path.join(TMP, "episode_173_pipeline_export.mp4")
open(MP4, "wb").write(b"\0" * 64)


def to_review(kind="content_video.auto", agent="ag1", ck=None, title="Seek First: What Matthew 6:33 Really Means",
              result=None):
    t = cm.create_task(goal=title, title=title, created_by="autopublish", approval_required=False,
                       assignee_type="agent", assignee_id=agent, assignee_name="x")
    cm.append_event(t["id"], "log", "kind", data={"kind": kind, "task_id": t["id"]})
    cm.append_event(t["id"], "log", "checkpoint", data={"checkpoint": {
        "script": "TITLE: x\n\n[SHOW: a]\nNarration.", "title": title, "episode_id": 173, "language": "en",
        **({"video_path": MP4} if ck is None else ck)}})
    got = cm.claim_next()
    assert got and got["id"] == t["id"], got
    cm.report_result(t["id"], result or f"## ⚠️ Auto video rendered — 77 shots · video 10:00\n\n- **Video**: `{MP4}`\n- **Title**: {title}")
    return cm.get_task(t["id"])


def refusal(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except PJ.JobError as e:
        return e


VID = "dQw4w9WgXcQ"
PUBLISHED = []


def fake_publish(vid=VID, exc=None, unverified=False):
    def run(state, options):
        PUBLISHED.append({"video": state["video_path"], "title": state["title"], "options": dict(options),
                          "resolved": state.get("channel_resolved")})
        state["_say"]("publish", "running", "opening YouTube Studio")
        if exc:
            raise RuntimeError(exc)
        if unverified:
            state["publish_unverified_url"] = True
            state["published"] = {"video_id": "", "url": "", "title": options.get("seo_title") or state["title"],
                                  "privacy": options["publish_privacy"], "channel_name": options["publish_channel_name"]}
            return
        state["published"] = {"video_id": vid, "url": f"https://youtu.be/{vid}", "title": options.get("seo_title") or state["title"],
                              "privacy": options["publish_privacy"], "channel_name": options["publish_channel_name"],
                              "via": "script"}
    return run


print("── A. request_publish ─────────────────────────────────────")
plan = to_review("content_video.plan")
e = refusal(PJ.request_publish, plan["id"], {})
check("A1 task kế hoạch (chưa có video) → 400 not_a_rendered_video", e and e.status == 400 and e.code == "not_a_rendered_video", e)
t_done = to_review()
cm.complete_review(t_done["id"], True, actor="t")
e = refusal(PJ.request_publish, t_done["id"], {})
check("A2 task không ở review → 409 not_in_review", e and e.code == "not_in_review", e)
t_pub = to_review(ck={"video_path": MP4, "published": {"video_id": VID, "url": f"https://youtu.be/{VID}"}})
e = refusal(PJ.request_publish, t_pub["id"], {})
check("A3 đã đăng rồi → 409 already_published kèm link", e and e.code == "already_published" and VID in e.extra.get("url", ""), e)
t_nofile = to_review(ck={"video_path": os.path.join(TMP, "khong_co.mp4")}, result="## done\n\n- **Title**: x")
e = refusal(PJ.request_publish, t_nofile["id"], {})
check("A4 file mp4 không còn → 409 no_video_file", e and e.code == "no_video_file", e)
t_res = to_review(ck={})          # checkpoint không có video_path → đọc từ dòng «Video» của kết quả
SECS[0] = 1100.0
t_long = to_review(agent="agU")
e = refusal(PJ.request_publish, t_long["id"], {})
check("A5 kênh chưa xác minh + video 18:20 → 422, KHÔNG xếp hàng", e and e.status == 422
      and e.code == "too_long_for_unverified_channel" and not PJ.job_for_task(t_long["id"]), e)
SECS[0] = 600.0
t1 = to_review()
e = refusal(PJ.request_publish, t1["id"], {"channel": "Kenh Khong Ton Tai"})
check("A6 channel không khớp hồ sơ nào → 400 channel_not_matched, nói cách sửa", e and e.code == "channel_not_matched"
      and "notes" in e.message, e)
e = refusal(PJ.request_publish, t1["id"], {"channel": "Shivani"})
check("A7 channel khớp HAI hồ sơ → từ chối, kể tên cả hai", e and "gmail_shivani123rb" in e.message
      and "stoic_shivani123rb" in e.message, e)
e = refusal(PJ.request_publish, t1["id"], {"privacy": "everyone"})
check("A8 privacy lạ → 400", e and e.code == "bad_privacy", e)
check("A9 find_profile: Radhika → gmail_singhradhika3976 (tên chứa nhau); Jay → nhờ ghi chú hồ sơ; Pawan → không có",
      PJ.find_profile("Radhika") == ("gmail_singhradhika3976", []) and PJ.find_profile("Jay")[0] == ""
      and PJ.find_profile("kênh Jay") == ("gmail_jayarajapatela", []) and PJ.find_profile("Pawan") == ("", []),
      (PJ.find_profile("Radhika"), PJ.find_profile("Jay"), PJ.find_profile("kênh Jay"), PJ.find_profile("Pawan")))
job = PJ.request_publish(t1["id"], {"title": "  Seek First   — Matthew 6:33 Explained ", "description": "Mô tả do Claude viết.",
                                    "tags": ["matthew 6:33", "#bible study", "matthew 6:33"], "category_id": 27,
                                    "profile": "gmail_pk0789743"}, actor="claude_connector")
check("A10 nhận → trả ngay việc «queued», chưa đụng trình duyệt", job["status"] == "queued" and job["task_seq"] == t1["seq"]
      and not PUBLISHED and not STOPS, job)
check("A11 category_id được báo là CHƯA áp dụng (không lặng lẽ bỏ)", job["requested"].get("ignored") == ["category_id"], job["requested"])
e = refusal(PJ.request_publish, t1["id"], {})
check("A12 gọi lần hai khi đang có việc → 409 publish_in_progress", e and e.code == "publish_in_progress", e)

print("── B. chạy việc đăng ──────────────────────────────────────")
P._publish_now = fake_publish()
check("B1 tick chạy việc", PJ.tick() == "ran")
done = PJ.get_job(job["id"])
call = PUBLISHED[-1]
check("B2 đăng đúng FILE SẴN CÓ của task (không dựng lại)", call["video"] == MP4, call["video"])
check("B3 tiêu đề / mô tả / tag của người gọi được đưa vào (tag sạch, bỏ trùng, bỏ #)",
      call["options"]["seo_title"] == "Seek First — Matthew 6:33 Explained" and call["options"]["seo_description"] == "Mô tả do Claude viết."
      and call["options"]["seo_tags"] == ["matthew 6:33", "bible study"], call["options"])
check("B4 hồ sơ chỉ đích danh → bỏ qua phép so tên kênh (channel_resolved đặt sẵn), đường script, đăng ngay",
      call["resolved"] and call["options"]["publish_profile"] == "gmail_pk0789743"
      and call["options"]["publish_method"] == "script" and call["options"]["publish_when"] == "now", call)
check("B5 việc xong: done + video id + link", done["status"] == "done" and done["result"]["video_id"] == VID
      and done["result"]["url"] == f"https://youtu.be/{VID}", done)
tk = cm.get_task(t1["id"])
check("B6 task REVIEW → DONE, kết quả có dòng Published với link thật, giữ các dòng cũ", tk["status"] == "done"
      and f"- **Published**: https://youtu.be/{VID}" in tk["result"] and "- **Video**:" in tk["result"], tk["result"])
check("B7 checkpoint.published có id thật (bulk accept / lần đăng sau đều thấy)", cm.published_video(t1["id"]).get("video_id") == VID)
check("B8 KHÔNG hook on_accept nào chạy", HOOKS == [("content_video.auto", t_done["id"])], HOOKS)
check("B9 hồ sơ được ĐÓNG sau khi đăng xong", STOPS and STOPS[-1] == ("/api/v1/browser/stop", "gmail_pk0789743"), STOPS)
step = next((s for s in tk.get("steps") or [] if s.get("name") == "publish"), {})
check("B10 bước Publish trên thẻ thành success kèm link", step.get("status") == "success" and VID in str(step.get("message")), step)
e = refusal(PJ.request_publish, t1["id"], {})
check("B11 đăng lại task đã đăng → từ chối", e and e.code in ("not_in_review", "already_published"), e)

# không có id → UNVERIFIED, task ở lại review
t2 = to_review(title="She Stopped Carrying Every Worry")
j2 = PJ.request_publish(t2["id"], {"profile": "gmail_singhradhika3976"})
P._publish_now = fake_publish(unverified=True)
STOPS.clear()
PJ.tick()
d2 = PJ.get_job(j2["id"])
check("B12 Studio không trả link → việc «unverified», task Ở LẠI review, không ghi published", d2["status"] == "unverified"
      and cm.get_task(t2["id"])["status"] == "review" and cm.published_video(t2["id"]) == {}, d2)
check("B13 …hồ sơ vẫn được đóng", STOPS == [("/api/v1/browser/stop", "gmail_singhradhika3976")], STOPS)
e = refusal(PJ.request_publish, t2["id"], {"profile": "gmail_singhradhika3976"})
check("B14 lần đăng sau bị chặn (có thể đã lên kênh) — phải force=true", e and e.code == "unverified_attempt", e)
j2b = PJ.request_publish(t2["id"], {"profile": "gmail_singhradhika3976", "force": True})
check("B15 force=true → nhận", j2b["status"] == "queued")

# lỗi khi đăng → failed, task còn review, hồ sơ đóng
P._publish_now = fake_publish(exc="The upload script did not finish — login required")
STOPS.clear()
PJ.tick()
d2b = PJ.get_job(j2b["id"])
check("B16 đăng lỗi → việc failed kèm lý do, task còn review, hồ sơ đóng", d2b["status"] == "failed"
      and "login required" in d2b["error"] and cm.get_task(t2["id"])["status"] == "review" and len(STOPS) == 1, (d2b, STOPS))

# không chỉ hồ sơ: dùng hồ sơ + kênh của agent, phép so tên kênh của pipeline vẫn chạy (không đặt channel_resolved)
t3 = to_review(title="auto default")
j3 = PJ.request_publish(t3["id"], {"when": "slots"})
P._publish_now = fake_publish(vid="AbCdEfGhIj0")
PJ.tick()
call = PUBLISHED[-1]
check("B17 mặc định: hồ sơ + kênh của agent, KHÔNG bỏ qua phép so kênh; when=slots theo khung giờ của agent",
      call["resolved"] is None and call["options"]["publish_profile"] == "gmail_pk0789743"
      and call["options"]["publish_channel_name"] == "Pawan Kumar" and call["options"]["publish_when"] == "slots"
      and call["options"]["publish_slots"] == "12:00, 19:00", call)
check("B18 video path lấy từ dòng «Video» của kết quả khi checkpoint không ghi", PJ.task_video_path(t_res, cm.checkpoint_of(t_res["id"])) == MP4)

print("── C. hàng đợi ────────────────────────────────────────────")
ta, tb = to_review(title="A"), to_review(title="B")
ja = PJ.request_publish(ta["id"], {"profile": "gmail_pk0789743"})
time.sleep(0.01)
jb = PJ.request_publish(tb["id"], {"profile": "gmail_singhradhika3976"})
check("C1 việc thứ hai đứng sau (position 1)", PJ.public(PJ.get_job(jb["id"]))["position"] == 1 and PJ.public(PJ.get_job(ja["id"]))["position"] == 0)
RAM[0] = 900.0
n = len(PUBLISHED)
check("C2 RAM trống 900 MB (< 1536) → KHÔNG mở trình duyệt, việc «waiting» kèm lý do", PJ.tick() == "waiting"
      and PJ.get_job(ja["id"])["status"] == "waiting" and "900 MB" in PJ.get_job(ja["id"])["wait_reason"]
      and len(PUBLISHED) == n, PJ.get_job(ja["id"]))
RAM[0], RENDER[0] = 4000.0, "task #7 is assembling its video"
check("C3 đang dựng video → vẫn chờ, lý do đổi", PJ.tick() == "waiting" and "assembling" in PJ.get_job(ja["id"])["wait_reason"]
      and len(PUBLISHED) == n)
RAM[0] = -1.0
RENDER[0] = ""
check("C4 không đo được RAM → cửa ĐÓNG (không mở mù)", PJ.tick() == "waiting" and "cannot be measured" in PJ.get_job(ja["id"])["wait_reason"])
RAM[0] = 4000.0
ORDER = []
P._publish_now = lambda state, options: (ORDER.append(state["task_id"]), fake_publish(vid="ZzZzZzZzZz1")(state, options))[1]
check("C5 máy rảnh → chạy theo thứ tự xếp hàng, mỗi nhịp MỘT việc", PJ.tick() == "ran" and ORDER == [ta["id"]]
      and PJ.get_job(jb["id"])["status"] == "queued", ORDER)
PJ.tick()
check("C6 việc sau chạy sau khi việc trước xong", ORDER == [ta["id"], tb["id"]] and PJ.tick() == "idle")
real_gate = PJ.gate_reason
check("C7 cài đặt mặc định: 1536 MB, chờ render, 60 phút, 30 giây", PJ.setting("publish_min_free_ram_mb") == 1536
      and PJ.setting("publish_wait_for_render") is True and PJ.setting("publish_job_timeout_min") == 60
      and PJ.setting("publish_recheck_sec") == 30)

# chờ quá hạn → bỏ, nói rõ chưa mở gì
tc = to_review(title="C")
jc = PJ.request_publish(tc["id"], {"profile": "gmail_pk0789743"})
PJ._jobs[jc["id"]]["created_at"] = time.time() - 30 * 3600
RAM[0] = 100.0
check("C8 chờ quá 24 giờ → failed «gave up», không mở trình duyệt", PJ.tick() == "gave_up"
      and "Nothing was opened" in PJ.get_job(jc["id"])["error"])
RAM[0] = 4000.0

# quá giờ → đóng hồ sơ, ghi dấu chưa xác minh
td = to_review(title="D")
jd = PJ.request_publish(td["id"], {"profile": "gmail_pk0789743"})
_real_setting = PJ.setting
PJ.setting = lambda name: 0 if name == "publish_job_timeout_min" else _real_setting(name)
_real_join = PJ.threading.Thread.join
PJ.threading.Thread.join = lambda self, timeout=None: _real_join(self, 0.2)
P._publish_now = lambda state, options: time.sleep(1.5)
STOPS.clear()
PJ.tick()
PJ.threading.Thread.join = _real_join
PJ.setting = _real_setting
dd = PJ.get_job(jd["id"])
check("C9 quá giờ → failed «Timed out», hồ sơ ĐÓNG, task còn review", dd["status"] == "failed" and "Timed out" in dd["error"]
      and STOPS == [("/api/v1/browser/stop", "gmail_pk0789743")] and cm.get_task(td["id"])["status"] == "review", (dd, STOPS))
e = refusal(PJ.request_publish, td["id"], {"profile": "gmail_pk0789743"})
check("C10 sau lần quá giờ: đăng lại phải force (video có thể đã lên)", e and e.code == "unverified_attempt", e)
time.sleep(1.6)

# khởi động lại: việc đang chạy → interrupted; việc đang chờ còn nguyên
te, tf = to_review(title="E"), to_review(title="F")
je = PJ.request_publish(te["id"], {"profile": "gmail_pk0789743"})
jf = PJ.request_publish(tf["id"], {"profile": "gmail_pk0789743"})
PJ._patch(je["id"], status="running", started_at=time.time())
PJ._patch(jf["id"], status="waiting", wait_reason="x")
saved = json.load(open(Path(TMP) / "publish_jobs.json", encoding="utf-8"))
check("C11 sổ việc ghi ra đĩa", {j["id"] for j in saved["jobs"]} >= {je["id"], jf["id"]})
PJ._jobs.clear()
PJ._loaded = False
PJ._load()
check("C12 khởi động lại: việc ĐANG CHẠY → interrupted (không tự đăng lại), nói phải kiểm kênh",
      PJ.get_job(je["id"])["status"] == "interrupted" and "check the channel" in PJ.get_job(je["id"])["error"])
check("C13 …việc ĐANG CHỜ còn trong hàng (queued)", PJ.get_job(jf["id"])["status"] == "queued")
P._publish_now = fake_publish(vid="QqQqQqQqQq2")
PJ.tick()
check("C14 …và chạy tiếp được", PJ.get_job(jf["id"])["status"] == "done")

# gate thật: render_running đọc bước render của task đang chạy
src = (ROOT / "tubecli" / "extensions" / "content_video" / "publish_jobs.py").read_text(encoding="utf-8")
ns = {}
exec(compile(src[src.index("def render_running"):src.index("def gate_reason")], "rr", "exec"), {"logger": PJ.logger}, ns)
tr = cm.create_task(goal="r", title="r", created_by="user", approval_required=False)
cm.claim_next()
cm.report_step(tr["id"], "render", "running", "12/100", "Assemble the video")
import psutil as _ps  # noqa: E402
_real_iter = _ps.process_iter
_ps.process_iter = lambda attrs=None: iter(())
check("C15 render_running: task đang chạy có bước render running → có câu", "assembling" in ns["render_running"](), ns["render_running"]())
cm.report_step(tr["id"], "render", "success", "", "Assemble the video")
check("C16 …bước render xong → hết", ns["render_running"]() == "")


class _Proc:
    info = {"name": "ffmpeg.exe"}


_ps.process_iter = lambda attrs=None: iter([_Proc()])
check("C17 …tiến trình ffmpeg đang sống → có câu", "ffmpeg" in ns["render_running"]())
_ps.process_iter = _real_iter
PJ.render_running = lambda: RENDER[0]

print("── D. sửa SEO video đã đăng ───────────────────────────────")
e = refusal(PJ.request_seo_edit, "abc", {"title": "x"})
check("D1 video id sai dạng → 400", e and e.code == "bad_video_id", e)
e = refusal(PJ.request_seo_edit, VID, {"category_id": 27, "default_audio_language": "en"})
check("D2 chỉ gửi trường chưa tự động hoá → 400 nothing_to_change, nói rõ trường nào chưa làm được",
      e and e.code == "nothing_to_change" and e.extra.get("not_applied") == ["category_id", "default_audio_language"], e)
e = refusal(PJ.request_seo_edit, "NoTaskVid01", {"title": "x"})
check("D3 video không do task nào ở đây đăng + không chỉ hồ sơ → 400 profile_required", e and e.code == "profile_required", e)
je1 = PJ.request_seo_edit(VID, {"title": "New Title", "tags": "a, b ,a", "category_id": 27})
check("D4 video của task #… → tự lấy hồ sơ đăng của agent; trường chưa áp dụng được báo lại",
      je1["status"] == "queued" and je1["profile"] == "gmail_pk0789743" and je1["task_seq"] == t1["seq"]
      and "category_id" in je1.get("not_applied", {}), je1)
e = refusal(PJ.request_seo_edit, VID, {"title": "again"})
check("D5 đang có việc sửa video này → 409", e and e.code == "edit_in_progress", e)
v = PJ.edit_variables(VID, {"title": "New Title", "tags": ["a", "b"]})
check("D6 biến script: chỉ bật cờ trường được gửi, mở đúng trang chi tiết của video",
      v["set_title"] == "1" and v["set_description"] == "0" and v["set_tags"] == "1" and v["tags_csv"] == "a,b"
      and v["edit_url"] == f"https://studio.youtube.com/video/{VID}/edit", v)


class Res(dict):
    success = True
    log = ""


RUNS = []


def fake_script(report, ok=True):
    def run(state, options, slug, variables, profile):
        RUNS.append((slug, profile, dict(variables)))
        r = Res({"t2_edit": report})
        r.success = ok
        r.log = "locator timeout at step 4"
        return r
    return run


P.ensure_upload_script = lambda slug: False
P._run_upload_script = fake_script({"video_ok": True, "saved": True, "applied": ["title", "tags"], "skipped": [], "title": "New Title"})
STOPS.clear()
PJ.tick()
r1 = PJ.get_job(je1["id"])
check("D7 script báo đã lưu → done, kể đúng trường đã sửa, hồ sơ đóng", r1["status"] == "done" and r1["result"]["applied"] == ["title", "tags"]
      and RUNS[-1][0] == "youtube_edit_video" and RUNS[-1][1] == "gmail_pk0789743" and len(STOPS) == 1, (r1, STOPS))
je2 = PJ.request_seo_edit(VID, {"description": "d"}, )
P._run_upload_script = fake_script({"video_ok": False, "saved": False, "applied": [], "note": "not on this video"})
PJ.tick()
check("D8 trang không phải video này → failed, nói KHÔNG gõ gì", PJ.get_job(je2["id"])["status"] == "failed"
      and "nothing was typed" in PJ.get_job(je2["id"])["error"])
je3 = PJ.request_seo_edit(VID, {"description": "d"}, )
P._run_upload_script = fake_script(json.dumps({"video_ok": True, "saved": False, "applied": ["description"], "note": "save button is disabled"}))
PJ.tick()
check("D9 Studio không xác nhận lưu → unverified (không báo thành công)", PJ.get_job(je3["id"])["status"] == "unverified", PJ.get_job(je3["id"]))
je4 = PJ.request_seo_edit(VID, {"title": "t"}, )
P._run_upload_script = fake_script({}, ok=False)
PJ.tick()
check("D10 script không chạy xong → failed kèm đuôi log", PJ.get_job(je4["id"])["status"] == "failed"
      and "locator timeout" in PJ.get_job(je4["id"])["error"])
je5 = PJ.request_seo_edit("OtherVid001", {"title": "t", "channel": "Radhika"})
check("D11 channel → hồ sơ (tra trong mọi hồ sơ)", je5["profile"] == "gmail_singhradhika3976")

while PJ.tick() == "ran":        # chạy nốt việc còn trong hàng (je5) để phần F bắt đầu với hàng rỗng
    pass

print("── F. đường đăng THẬT của pipeline với state dựng lại ─────")
# _publish_now → _resolve_channel → _publish_via_script chạy thật; chỉ bước chạy script trình duyệt là giả. Bắt lỗi
# «state thiếu khoá» mà các bài trên (thay cả _publish_now) không thấy được.
P._publish_now = REAL_PUBLISH_NOW
P.ensure_upload_script = lambda slug: False
P.ensure_thumbnail_branch = lambda slug: False
P._script_schedules = lambda slug: True
SCRIPT_VARS = []


def real_script(state, options, slug, variables, profile):
    SCRIPT_VARS.append((slug, profile, dict(variables)))
    r = Res({"t2_publish": {"state": "published", "url": "https://youtu.be/RealVid0001", "note": ""}, "thumbnail_done": ""})
    r.success = True
    return r


P._run_upload_script = real_script
tr1 = to_review(title="Real path")
jr1 = PJ.request_publish(tr1["id"], {"title": "Real Path Title", "description": "Real description.", "tags": ["one", "two"],
                                     "profile": "gmail_pk0789743", "privacy": "unlisted"})
PJ.tick()
dr1 = PJ.get_job(jr1["id"])
check("F1 đường thật chạy trọn với state dựng lại → done + id thật", dr1["status"] == "done"
      and dr1["result"]["video_id"] == "RealVid0001", dr1)
sv = SCRIPT_VARS[-1] if SCRIPT_VARS else ("", "", {})
check("F2 script nhận đúng file, tiêu đề của người gọi, mô tả kèm tag, chế độ unlisted, không hẹn giờ",
      sv[0] == "youtube_upload" and sv[1] == "gmail_pk0789743" and sv[2].get("video_path") == MP4
      and sv[2].get("title") == "Real Path Title" and "Real description." in sv[2].get("description", "")
      and sv[2].get("visibility_radio") == "UNLISTED" and sv[2].get("schedule") == "0", sv)
check("F3 task sang done với link thật", cm.get_task(tr1["id"])["status"] == "done"
      and "https://youtu.be/RealVid0001" in cm.get_task(tr1["id"])["result"])

# không chỉ hồ sơ + tên kênh của agent KHÔNG khớp hồ sơ ⇒ pipeline dừng (luật .233), việc failed, không gọi script
tr2 = to_review(title="Real mismatch")
jr2 = PJ.request_publish(tr2["id"], {"title": "T", "description": "D"})
P._find_channel = lambda **kw: {}
n_scripts = len(SCRIPT_VARS)
PJ.tick()
dr2 = PJ.get_job(jr2["id"])
check("F4 kênh của agent không khớp hồ sơ → failed «Publishing stopped», KHÔNG mở script, task còn review",
      dr2["status"] == "failed" and "Publishing stopped" in dr2["error"] and len(SCRIPT_VARS) == n_scripts
      and cm.get_task(tr2["id"])["status"] == "review", dr2)

# script trả link trợ giúp (không phải video) ⇒ unverified
P._run_upload_script = lambda state, options, slug, variables, profile: (lambda r: (setattr(r, "success", True), r)[1])(
    Res({"t2_publish": {"state": "published", "url": "https://support.google.com/youtube?p=upload_videos"}}))
tr3 = to_review(title="Real unverified")
jr3 = PJ.request_publish(tr3["id"], {"title": "T", "description": "D", "profile": "gmail_pk0789743"})
PJ.tick()
check("F5 script trả link trợ giúp → unverified, task ở lại review, không ghi published",
      PJ.get_job(jr3["id"])["status"] == "unverified" and cm.get_task(tr3["id"])["status"] == "review"
      and cm.published_video(tr3["id"]) == {}, PJ.get_job(jr3["id"]))

print("── G. route ───────────────────────────────────────────────")
import asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from tubecli.extensions.codex import routes as CR  # noqa: E402
from tubecli.extensions.content_video import routes as VR  # noqa: E402
P._run_upload_script = real_script
tg = to_review(title="Route")
resp = asyncio.run(CR.publish_task(str(tg["seq"]), {"title": "Via Route", "description": "D", "profile": "gmail_pk0789743"}))
body = json.loads(resp.body)
check("G1 POST /codex/tasks/{số task}/publish → 202 + việc queued", resp.status_code == 202 and body["status"] == "queued"
      and body["job"]["task_id"] == tg["id"], body)
st = asyncio.run(CR.publish_task_status(tg["id"]))
check("G2 GET …/publish → việc mới nhất, chưa có published", st["job"]["status"] == "queued" and st["published"] is None, st)
try:
    asyncio.run(CR.publish_task(tg["id"], {}))
    err = None
except HTTPException as ex:
    err = ex
check("G3 gọi lại → HTTP 409 kèm code", err is not None and err.status_code == 409 and err.detail.get("code") == "publish_in_progress", err and err.detail)
PJ.tick()
st = asyncio.run(CR.publish_task_status(tg["id"]))
check("G4 sau khi chạy: published có id, task done", st["published"] and st["published"]["video_id"] == "RealVid0001"
      and st["task"]["status"] == "done", st)


class Rq:
    class state:
        guest_scope = None


resp = asyncio.run(VR.youtube_video_edit("RealVid0001", Rq(), {"title": "Edited"}))
body = json.loads(resp.body)
check("G5 PUT /youtube/videos/{id} → 202, tự tìm hồ sơ từ task đã đăng video đó", resp.status_code == 202
      and body["job"]["kind"] == "seo_edit" and body["job"]["profile"] == "gmail_pk0789743", body)
lst = asyncio.run(VR.publish_jobs_list(Rq(), True, 50))
check("G6 GET /content-video/publish-jobs → hàng đợi + cổng + cài đặt", len(lst["jobs"]) >= 1 and "gate" in lst
      and lst["settings"]["publish_min_free_ram_mb"] == 1536, lst)


class Guest:
    class state:
        guest_scope = {"w": 1}


try:
    asyncio.run(VR.youtube_video_edit("RealVid0001", Guest(), {"title": "x"}))
    gerr = None
except HTTPException as ex:
    gerr = ex
check("G7 khách của workspace chia sẻ không sửa được video", gerr is not None and gerr.status_code == 403)

print("── E. tĩnh ────────────────────────────────────────────────")
seed = json.load(open(ROOT / "tubecli" / "extensions" / "content_video" / "assets" / "youtube_edit_video.json", encoding="utf-8"))
blob = json.dumps(seed, ensure_ascii=False)
check("E1 script sửa: không bấm Publish / chế độ hiển thị / xoá video", not any(x in blob for x in (
    "#done-button", "name='PUBLIC'", "name='PRIVATE'", "name='UNLISTED'", "delete", "visibility")), "")
check("E2 script sửa: kiểm đúng video trước khi gõ, mọi bước gõ nằm sau cổng video_ok",
      "/video/{{video_id}}/" in blob and blob.count("window.__t2edit && window.__t2edit.video_ok") >= 3)
croutes = (ROOT / "tubecli" / "extensions" / "codex" / "routes.py").read_text(encoding="utf-8")
vroutes = (ROOT / "tubecli" / "extensions" / "content_video" / "routes.py").read_text(encoding="utf-8")
check("E3 route có mặt: POST + GET /tasks/{id}/publish, PUT /youtube/videos/{id}, GET /publish-jobs",
      '@router.post("/tasks/{task_id}/publish")' in croutes and '@router.get("/tasks/{task_id}/publish")' in croutes
      and '@youtube_router.put("/videos/{video_id}")' in vroutes and '@router.get("/publish-jobs")' in vroutes)
check("E4 đăng xong dùng _settle (không complete_review ⇒ không hook)", "cm._settle(tid, \"done\"" in src and "complete_review" not in src)

print("── G. trần mỗi ngày của agent ─────────────────────────────")
AGENTS["agL"] = Agent(id="agL", publish_max_per_day=2)
RAM[0], RENDER[0] = 4000.0, ""
g1, g2, g3 = (to_review(agent="agL", title=f"G video {i}") for i in (1, 2, 3))
jg1 = PJ.request_publish(g1["id"], {"profile": "gmail_pk0789743"})
jg2 = PJ.request_publish(g2["id"], {"profile": "gmail_pk0789743"})
err = refusal(PJ.request_publish, g3["id"], {"profile": "gmail_pk0789743"})
check("G1 trần 2/ngày: việc thứ ba cùng agent bị từ chối (đếm cả việc còn trong hàng đợi)",
      err is not None and err.code == "daily_limit_reached" and err.status == 409, err and (err.status, err.code))
check("G2 when=slots (YouTube tự rải ngày) không bị trần chặn",
      refusal(PJ.request_publish, g3["id"], {"profile": "gmail_pk0789743", "when": "slots"}) is None)
g4 = to_review(agent="agL", title="G video 4")
check("G3 ignore_daily_limit=true: chủ nói cứ đăng", refusal(PJ.request_publish, g4["id"],
      {"profile": "gmail_pk0789743", "ignore_daily_limit": True}) is None)
g5 = to_review(agent="ag1", title="G video khác agent")
check("G4 agent KHÁC (không trần) không bị ảnh hưởng", refusal(PJ.request_publish, g5["id"], {"profile": "gmail_pk0789743"}) is None)
check("G5 count_published: tính một lần cho mỗi task, không dời mốc kho",
      AP.count_published("agC", "https://youtu.be/abcdefghijk", "tX").startswith("counted 1")
      and AP.count_published("agC", "https://youtu.be/abcdefghijk", "tX") == "already counted"
      and AP.get_mark("agC")["published_today"] == 1 and AP.get_mark("agC")["high_water"] == "")
check("G6 đăng xong gọi count_published (tính vào trần ngày)", "autopublish.count_published(" in src)

print("── H. đánh dấu ĐÃ ĐĂNG TAY (15/11/2026) ─────────────────────")
AGENTS["agH"] = Agent(id="agH", publish_max_per_day=2)
h1 = to_review(agent="agH", title="The Cup That Was Already Full")
HOOKS.clear()
n_stops = len(STOPS)
err = refusal(PJ.mark_published, h1["id"], {"url": "https://support.google.com/youtube?p=upload_videos"})
check("H1 link trợ giúp (không phải link video) → từ chối, task vẫn ở review",
      err is not None and err.code == "video_link_required" and cm.get_task(h1["id"])["status"] == "review", err and err.code)
out = PJ.mark_published(h1["id"], {"url": "https://studio.youtube.com/video/AbCdEfGhIjK/edit", "channel": "Radhika Singh"}, "claude_connector")
t = cm.get_task(h1["id"])
check("H2 link Studio → ghi youtu.be/<id>, task sang done, dòng Published trong kết quả",
      out["url"] == "https://youtu.be/AbCdEfGhIjK" and t["status"] == "done"
      and "**Published** (by hand, outside TubeCLI): https://youtu.be/AbCdEfGhIjK → Radhika Singh" in (t.get("result") or ""), (out, t.get("status")))
check("H3 không mở trình duyệt, không gọi hook nhận task (không dựng / đăng lại)", len(STOPS) == n_stops and HOOKS == [])
check("H4 tính vào trần ngày của agent", AP.get_mark("agH")["published_today"] == 1, AP.get_mark("agH"))
check("H5 task biết mình đã đăng → đánh dấu lại bị chặn", cm.published_video(h1["id"]).get("video_id") == "AbCdEfGhIjK"
      and getattr(refusal(PJ.mark_published, h1["id"], {"video_id": "AbCdEfGhIjK"}), "code", "") == "already_published")
h2 = to_review(agent="agH", title="Another story")
err = refusal(PJ.mark_published, h2["id"], {"video_id": "AbCdEfGhIjK"})
check("H6 cùng một video không ghi cho hai task", err is not None and err.code == "video_belongs_to_another_task", err and err.code)
out = PJ.mark_published(h2["id"], {"video_id": "ZyXwVuTsRqP"})
h3 = to_review(agent="agH", title="Third story")
err = refusal(PJ.request_publish, h3["id"], {"profile": "gmail_pk0789743"})
check("H7 hai video đánh dấu tay đã đủ trần 2/ngày → lượt đăng thứ ba hôm nay bị từ chối",
      out["status"] == "done" and err is not None and err.code == "daily_limit_reached", err and err.code)
check("H8 route POST /tasks/{id}/published có mặt", '@router.post("/tasks/{task_id}/published")' in croutes)

print(f"\n{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
