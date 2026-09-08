# "Task vừa tạo mà thẻ ghi 5 tiếng trước": mốc thời gian được ghi bằng
# datetime.now().isoformat() — giờ ĐỊA PHƯƠNG của máy chủ, không kèm múi giờ. Trình
# duyệt gặp chuỗi không có múi giờ thì hiểu là giờ của CHÍNH NGƯỜI XEM, nên máy chủ
# đặt ở múi khác (VPS) lệch đúng bằng khoảng cách hai múi. Ở đây kiểm: mốc mới có
# múi giờ, mốc CŨ trong kho được hiểu theo múi máy chủ khi trả ra API, và danh sách
# task kèm đồng hồ máy chủ để giao diện khỏi phải tin đồng hồ máy khách.
import asyncio
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.codex import manager as M  # noqa: E402

TZ = re.compile(r"(Z|[+-]\d{2}:\d{2})$")
checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    if ok:
        print(f"  ok  {name}")
        return
    failures += 1
    print(f"  FAIL {name} — {detail}")


# 1. Mốc mới luôn có múi giờ, và đọc lại được thành đúng thời điểm
now = M._now()
check("mốc mới có múi giờ", bool(TZ.search(now)), now)
parsed = datetime.datetime.fromisoformat(now)
check("mốc mới là 'bây giờ' thật", parsed.tzinfo is not None
      and abs((datetime.datetime.now(datetime.timezone.utc) - parsed).total_seconds()) < 5,
      now)

# 2. Mốc CŨ (bản trước ghi, không múi giờ) được hiểu theo múi của máy chủ
off = M._local_offset()
check("múi giờ máy chủ đúng dạng +hh:mm", bool(re.fullmatch(r"[+-]\d{2}:\d{2}", off)), off)
check("mốc cũ được gắn múi máy chủ", M._aware("2026-09-05T05:43:59.107713") == "2026-09-05T05:43:59.107713" + off)
check("mốc đã có múi thì giữ nguyên", M._aware("2026-09-05T05:43:59+02:00") == "2026-09-05T05:43:59+02:00")
check("mốc kiểu Z giữ nguyên", M._aware("2026-09-05T05:43:59Z") == "2026-09-05T05:43:59Z")
check("giá trị không phải chuỗi thì không đụng", M._aware(None) is None and M._aware(12) == 12)

# 3. Sửa cả những mốc nằm sâu trong task (bước, phê duyệt) — không đụng trường khác
task = {
    "id": "x", "title": "không đụng", "created_at": "2026-01-01T00:00:00",
    "goal": "2026-01-01T00:00:00 nằm trong câu chữ",
    "approval": {"decided_at": "2026-01-01T00:01:00", "note": "ok"},
    "steps": [{"name": "s1", "started_at": "2026-01-01T00:02:00", "ended_at": None}],
}
fixed = M._with_tz(task)
check("created_at có múi", fixed["created_at"].endswith(off))
check("mốc trong approval có múi", fixed["approval"]["decided_at"].endswith(off))
check("mốc trong bước có múi", fixed["steps"][0]["started_at"].endswith(off))
check("mốc rỗng vẫn rỗng", fixed["steps"][0]["ended_at"] is None)
check("chữ nghĩa không bị đụng", fixed["title"] == "không đụng" and fixed["goal"] == task["goal"])
check("không sửa vào bản gốc", task["created_at"] == "2026-01-01T00:00:00")

# 4. Task cũ trong kho: đọc qua API là đã có múi giờ (không phải đợi ghi lại)
mgr = M.CodexManager()
mgr._loaded = True
mgr._tasks = {
    "old1": {"id": "old1", "seq": 1, "status": "done", "created_at": "2026-09-05T05:43:59.107713",
             "updated_at": "2026-09-05T05:44:00", "steps": [{"started_at": "2026-09-05T05:43:59"}]},
}
listed = mgr.list_tasks()
check("list_tasks trả mốc có múi giờ", bool(TZ.search(listed[0]["created_at"])), listed[0]["created_at"])
check("list_tasks sửa cả mốc trong bước", bool(TZ.search(listed[0]["steps"][0]["started_at"])))
got = mgr.get_task("old1")
check("get_task trả mốc có múi giờ", bool(TZ.search(got["created_at"])), got["created_at"])
check("kho KHÔNG bị sửa (chỉ sửa lúc trả ra)", mgr._tasks["old1"]["created_at"] == "2026-09-05T05:43:59.107713")
check("server_now có múi giờ", bool(TZ.search(mgr.server_now())))

# 5. Sự kiện cũng vậy — Activity in giờ theo múi người xem
ev_dir = Path(M.EVENTS_DIR)
ev_dir.mkdir(parents=True, exist_ok=True)
path = Path(mgr._events_path("evtest"))
path.write_text(json.dumps({"ts": "2026-09-05T05:43:59", "task_id": "evtest", "kind": "log",
                            "actor": "worker", "message": "xin chào"}) + "\n", encoding="utf-8")
try:
    evs = mgr.get_events("evtest")
    check("get_events trả mốc có múi giờ", len(evs) == 1 and bool(TZ.search(evs[0]["ts"])), evs)
    check("nội dung sự kiện nguyên vẹn", evs[0]["message"] == "xin chào" and evs[0]["actor"] == "worker")
finally:
    path.unlink(missing_ok=True)

# 6. API danh sách gửi kèm đồng hồ máy chủ (giao diện đếm giờ theo mốc này)
from tubecli.extensions.codex import routes as R  # noqa: E402

R.codex_manager = mgr
payload = asyncio.run(R.list_tasks())
check("/tasks có trường now", bool(TZ.search(str(payload.get("now") or ""))), payload.get("now"))
check("/tasks vẫn trả tasks + count", payload.get("count") == 1 and len(payload.get("tasks") or []) == 1)

print("=" * 62)
print(f"{failures} FAIL / {checks}" if failures else f"{checks}/{checks} PASS")
sys.exit(1 if failures else 0)
