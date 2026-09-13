# -*- coding: utf-8 -*-
"""Studio "quên" việc vẽ ảnh giữa chừng → bước ảnh chờ lắng rồi vẽ tiếp, không hỏng (14/9/2026).

Ca thật (VPS, 13/9/2026): đang vẽ 123 shot thì người dùng cập nhật Content Studio từ Chợ;
extension nạp nóng → sổ _image_tasks mới rỗng → hỏi trạng thái 404 → thẻ "Generate shot
images ERROR: the Studio no longer knows this task". Việc cũ vẫn vẽ tiếp trong nền.

Đối chiếu code thật (mọi HTTP giả lập):
  A. _settle_images — chờ khi số ảnh còn tăng, dừng khi đứng yên đủ lâu hoặc đủ ảnh; huỷ được
  B. _step_images   — mất việc → chờ lắng → xin vẽ tiếp MỘT lần (bỏ qua shot đã có ảnh) → xong;
                      lần hai lại mất → lỗi như thường; lỗi khác không bị nuốt

Run:  PYTHONIOENCODING=utf-8 python tests/content_video_lost_task_test.py     (exit 0 = pass)
"""
import sys
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
        print("  FAIL", label, "—", str(detail)[:300])


P.IMAGES_SETTLE_SEC = 0.05
P.IMAGES_SETTLE_POLL = 0.0
LOST = RuntimeError("/api/v1/studio/gen-images/status/1275ecae: the Studio no longer knows this task (it was probably restarted)")


def shots_with(n, total=20):
    return [{"id": i, "composed_image": f"img{i}.jpg" if i < n else ""} for i in range(total)]


# ── A. _settle_images ────────────────────────────────────────────────────────
print("── A. chờ việc cũ lắng ──────────────────────────────────────")
counts = iter([10, 12, 14, 14, 14, 14, 14, 14])
P._storyboards = lambda ep: shots_with(next(counts, 14))
said = []
st = {"_cancelled": lambda: False, "_say": lambda *a: said.append(a)}
P._settle_images(st, 9)
ok(any("14/20" in str(a) for a in said) and any("old job is still drawing" in str(a) for a in said),
   "báo tiến độ của việc cũ, dừng khi số ảnh đứng yên", said[-2:])
counts = iter([20])
P._storyboards = lambda ep: shots_with(next(counts, 20))
said.clear()
P._settle_images(st, 9)
ok(said == [] or all("20/20" in str(a) for a in said), "đủ ảnh → về ngay", said)
P._storyboards = lambda ep: shots_with(3)
try:
    P._settle_images({"_cancelled": lambda: True, "_say": lambda *a: None}, 9)
    ok(False, "huỷ phải ném")
except Exception as e:
    ok(P._is_cancel(e), "huỷ giữa lúc chờ → dừng", e)

# ── B. _step_images với việc bị mất ────────────────────────────────────────────
print("── B. bước ảnh mất việc → vẽ tiếp một lần ───────────────────")
posts, polls = [], []
P._fill_missing_prompts = lambda state: 0


def fake_post(path, payload, timeout=300):
    posts.append((path, dict(payload)))
    return {"task_id": f"job{len(posts)}", "total": 20 - 14 if len(posts) > 1 else 20, "with_prompt": 20, "no_prompt": 0}


def fake_poll(status_path, timeout_sec, state, step, done_statuses=("completed",), max_wait=None):
    polls.append(status_path)
    if "job1" in status_path:
        raise LOST
    return {"status": "completed", "errors": []}


P._post = fake_post
P._poll_studio = fake_poll
counts = iter([10, 14, 14, 14])
P._storyboards = lambda ep: shots_with(next(counts, 14))
said.clear()
st = {"episode_id": 9, "aspect_ratio": "16:9", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: said.append(a)}
P._step_images(st, {})
ok(len(posts) == 2 and posts[1][1]["overwrite"] is False and posts[1][1]["aspect_ratio"] == "16:9",
   "xin vẽ tiếp đúng một lần, cùng tham số, không đè ảnh đã có", posts)
ok(polls == ["/api/v1/studio/gen-images/status/job1", "/api/v1/studio/gen-images/status/job2"], "theo dõi việc mới", polls)
ok(any("forgot this job" in str(a) for a in said) and st.get("image_errors") == 0 and not st["warnings"], "thẻ nói Studio quên việc; bước xong sạch", (said[:2], st["warnings"]))

# việc mới cũng mất → lỗi như thường (không lặp vô tận)
posts.clear(); polls.clear()
P._poll_studio = lambda *a, **k: (_ for _ in ()).throw(LOST)
counts = iter([14, 14, 14])
P._storyboards = lambda ep: shots_with(next(counts, 14))
try:
    P._step_images(dict(st), {})
    ok(False, "mất lần hai phải ném")
except RuntimeError as e:
    ok("no longer knows this task" in str(e) and len(posts) == 2, "mất lần hai → lỗi rõ, không thử mãi", (str(e)[:80], len(posts)))

# lỗi khác không bị coi là mất việc
posts.clear()
P._poll_studio = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("No progress for 1800s waiting for x"))
try:
    P._step_images(dict(st), {})
    ok(False, "lỗi khác phải ném nguyên")
except RuntimeError as e:
    ok("No progress" in str(e) and len(posts) == 1, "lỗi khác → ném nguyên, không xin vẽ lại", str(e)[:60])

# Studio trả total=0 sau khi lắng (việc cũ đã vẽ hết) → xong luôn, không theo dõi gì
posts.clear(); polls.clear()
# Lượt đầu có việc để theo dõi (rồi mất); lượt xin vẽ tiếp trả rỗng vì việc cũ đã vẽ đủ.
P._post = lambda path, payload, timeout=300: posts.append(path) or {"task_id": f"job{len(posts)}", "total": 20 if len(posts) == 1 else 0, "with_prompt": 20, "no_prompt": 0}
calls = {"n": 0}


def poll_once(*a, **k):
    calls["n"] += 1
    if calls["n"] == 1:
        raise LOST
    raise AssertionError("không được theo dõi việc rỗng")


P._poll_studio = poll_once
P._storyboards = lambda ep: shots_with(20)
st2 = {"episode_id": 9, "aspect_ratio": "16:9", "warnings": [], "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_images(st2, {})
ok(len(posts) == 2 and st2.get("image_errors") == 0, "việc cũ đã vẽ đủ → xin vẽ tiếp trả rỗng → xong, không theo dõi", posts)

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
