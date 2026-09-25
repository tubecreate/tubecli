# -*- coding: utf-8 -*-
"""Retry bám lượt dựng CŨ nhưng lượt này vừa vẽ bù ảnh → phải dựng lại (25/9/2026).

Bệnh: task hỏng 4 ảnh (401 Codex), user Cancel → Retry. Bước vẽ bù 4/4, rồi bước dựng thấy export cũ «still
running» và bám vào nó — lượt ấy khởi động TRƯỚC khi có 4 ảnh mới ⇒ video ra vẫn thiếu. Kèm lỗi ngầm: phép so
«tài sản mới hơn video» chỉ xét image_url (Studio để ảnh ở composed_image) và đường dẫn thô (giọng ghi dạng
/api/v1/tts/audio/<tên>) nên chưa từng thấy gì. Cam kết:
  1. Bám lượt cũ + có ảnh/giọng mới hơn lúc lượt cũ BẮT ĐẦU → chờ nó xong rồi dựng lại MỘT lần.
  2. Checkpoint cũ không có giờ bắt đầu → lấy giờ lượt Retry bắt đầu làm mốc.
  3. Không có gì mới → dùng kết quả lượt cũ, không dựng thêm.
  4. Không bám lượt cũ (tự bắt đầu) → không dựng hai lần.
  5. Ảnh ở composed_image và giọng /api/v1/tts/audio/<tên> đều được tính.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


TMP = tempfile.mkdtemp()


def touch(name, mtime):
    p = os.path.join(TMP, name)
    with open(p, "wb") as f:
        f.write(b"x")
    os.utime(p, (mtime, mtime))
    return p


NOW = time.time()
OLD_IMG = touch("old.jpg", NOW - 3600)
NEW_IMG = touch("new.jpg", NOW - 60)          # vẽ bù ở lượt Retry
VIDEO = touch("ep_pipeline_export.mp4", NOW)  # lượt cũ xong SAU khi ảnh vẽ bù
SHOTS = []

# Mọi đường ra mạng đều giả — test không được chạm máy chủ đang chạy.
POSTS, POLLS, CK = [], [], {}
P._finished_video = lambda state, ep_id: ""
P._post = lambda path, payload=None, timeout=60, **k: POSTS.append(path) or {"task_id": f"new{len(POSTS)}"}
P._get = lambda path, timeout=60, **k: {"video_url": VIDEO}
P._put = lambda path, payload=None, timeout=60, **k: {}
P._poll_studio = lambda url, *a, **k: POLLS.append(url) or {"status": "completed"}
P._storyboards = lambda ep_id: SHOTS
P._checkpoint_merge = lambda state, data: CK.update(data)
P.media_seconds = lambda path: 60.0
P.planned_seconds = lambda state: 0
P.share_links = lambda state: {}


def render(checkpoint, running="running", attempt_started=NOW - 120):
    POSTS.clear()
    POLLS.clear()
    CK.clear()
    P._running_export = lambda task_id: running if task_id else ""
    st = {"episode_id": 7, "checkpoint": checkpoint, "_say": lambda *a: None, "warnings": [],
          "_attempt_started": attempt_started}
    P._step_render(st, {})
    return st


# 1 + 5: lượt cũ bắt đầu 2 giờ trước, lượt Retry vẽ bù một ảnh (composed_image) → dựng lại đúng một lần.
SHOTS[:] = [{"composed_image": OLD_IMG}, {"composed_image": NEW_IMG, "image_url": ""}]
render({"export_task_id": "old1", "export_started_at": NOW - 7200})
ok(len(POSTS) == 1 and POLLS[0].endswith("/old1") and POLLS[1].endswith("/new1"),
   "bám lượt cũ + ảnh vẽ bù mới hơn giờ lượt cũ bắt đầu → chờ lượt cũ rồi dựng lại MỘT lần", (POSTS, POLLS))
ok(CK.get("export_task_id") == "new1" and CK.get("export_started_at"),
   "lượt mới ghi id + giờ bắt đầu vào checkpoint (Retry sau so được)", CK)

# 2: checkpoint của lõi cũ không có giờ bắt đầu → mốc = giờ lượt Retry bắt đầu.
render({"export_task_id": "old1"}, attempt_started=NOW - 120)
ok(len(POSTS) == 1, "checkpoint cũ thiếu giờ bắt đầu → so với giờ lượt Retry bắt đầu, vẫn dựng lại", POSTS)

# 3: không có gì mới hơn lượt cũ → không dựng thêm.
SHOTS[:] = [{"composed_image": OLD_IMG}]
render({"export_task_id": "old1", "export_started_at": NOW - 600})
ok(POSTS == [] and len(POLLS) == 1, "không ảnh/giọng nào mới hơn → dùng kết quả lượt cũ", (POSTS, POLLS))

# 4: không có lượt cũ đang chạy → tự bắt đầu, không dựng hai lần dù ảnh mới.
SHOTS[:] = [{"composed_image": NEW_IMG}]
render({}, running="")
ok(len(POSTS) == 1 and len(POLLS) == 1, "tự bắt đầu lượt dựng → chỉ một lượt", (POSTS, POLLS))

# 5: giọng /api/v1/tts/audio/<tên> được quy ra file thật.
_real_audio = P._shot_audio_file
NEW_MP3 = touch("tts_abc.mp3", NOW - 30)
P._shot_audio_file = lambda u: NEW_MP3 if str(u or "").startswith("/api/v1/tts/audio/") else _real_audio(u)
SHOTS[:] = [{"composed_image": OLD_IMG, "tts_audio_url": "/api/v1/tts/audio/tts_abc.mp3"}]
ok(P._assets_newer_than(7, VIDEO, since=NOW - 600), "giọng lưu dạng /api/v1/tts/audio/<tên> được tính", SHOTS)
P._shot_audio_file = _real_audio
ok(not P._assets_newer_than(7, VIDEO, since=0) is None, "không mốc → so với mp4 như cũ")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
