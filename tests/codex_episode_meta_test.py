# -*- coding: utf-8 -*-
"""Bảng việc realtime (11/10/2026): thẻ task video phải biết TẬP Content Studio của nó (meta.episode_id) để hỏi
/api/v1/studio/episodes/{id}/live vẽ lưới ảnh / clip từng cảnh.

  A. META_KEYS nhận episode_id / drama_id; set_meta ghi và trả về
  B. backfill_episode_meta: task cũ có meta nhưng chưa có episode_id → đọc checkpoint một lần; không có tập → 0 (không
     đọc lại lần sau); task plan (chưa vào Studio) bỏ qua
  C. _step_studio ghi meta ngay khi có tập (kiểm theo mã nguồn: gọi _task_meta(... episode_id=ep_id ...))

Run:  python tests/codex_episode_meta_test.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.codex import manager as M  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def task(seq, status="running", **kw):
    return {"id": f"t{seq}", "seq": seq, "title": f"Task {seq}", "status": status, "lane": "video", "steps": [],
            "created_at": "2026-10-11T15:00:00", "updated_at": "2026-10-11T15:00:00", **kw}


print("A. META_KEYS + set_meta")
ok("episode_id" in M.META_KEYS and "drama_id" in M.META_KEYS, "META_KEYS có episode_id, drama_id")
mgr = M.CodexManager()
mgr._loaded = True
mgr._save = lambda: None
mgr.append_event = lambda *a, **k: None
mgr._tasks = {t["id"]: t for t in [
    task(1, meta={"stage": "auto", "language": "vi"}),
    task(2, meta={"stage": "plan"}),
    task(3, meta={"stage": "render", "episode_id": 700}),
    task(4, status="done", meta={"stage": "clone"}),
    task(5, lane="", meta={"stage": "auto"}),
]}
got = mgr.set_meta("t1", {"episode_id": 731, "drama_id": 12, "bogus": 1})
ok(got and got["meta"]["episode_id"] == 731 and got["meta"]["drama_id"] == 12 and "bogus" not in got["meta"],
   "set_meta ghi episode_id / drama_id, bỏ khoá lạ", got and got.get("meta"))
ok(M.board_row(mgr._tasks["t1"])["meta"]["episode_id"] == 731, "dòng bảng mang meta.episode_id (codex.js đọc từ đây)")

print("B. backfill_episode_meta")
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
M.codex_manager = mgr
CK = {"t5": {"episode_id": 55, "drama_id": 5}, "t4": {"episode_id": 44}}
reads = []


def _fake_ck(tid):
    reads.append(tid)
    return CK.get(tid)


P._read_checkpoint = _fake_ck
mgr.set_meta("t1", {"episode_id": None})           # t1 lại chưa có tập
n = P.backfill_episode_meta()
m = {k: v.get("meta") for k, v in mgr._tasks.items()}
ok(n == 3 and sorted(reads) == ["t1", "t4", "t5"], "chỉ đọc checkpoint task auto/render/clone/drive chưa có episode_id", (n, reads))
ok(m["t5"]["episode_id"] == 55 and m["t5"]["drama_id"] == 5 and m["t4"]["episode_id"] == 44, "ghi tập từ checkpoint", m)
ok(m["t1"]["episode_id"] == 0 and m["t2"].get("episode_id") is None and m["t3"]["episode_id"] == 700,
   "không có tập → 0 (lần sau không đọc lại); task plan bỏ qua; task đã có giữ nguyên", m)
reads.clear()
ok(P.backfill_episode_meta() == 0 and reads == [], "lần hai không còn gì để đọc")

print("C. _step_studio ghi meta ngay khi có tập")
src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
i = src.find("def _step_studio(")
j = src.find("\ndef ", i + 10)
body = src[i:j]
ok('_task_meta(state.get("task_id"), episode_id=ep_id, drama_id=drama_id)' in body
   and body.find('state["drama_id"], state["episode_id"], state["title"] = drama_id, ep_id, title')
   < body.find("_task_meta(state.get(\"task_id\"), episode_id=ep_id"),
   "_step_studio: sau khi có drama/episode thì ghi meta (cả lượt chạy lại dùng checkpoint)")
ok('"episode_id": ck.get("episode_id") or None' in src[src.find("def backfill_task_meta("):src.find("def backfill_episode_meta(")],
   "backfill_task_meta (task chưa có meta) cũng ghi episode_id")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
