# -*- coding: utf-8 -*-
"""Tên thật + thông số của task video lên thẻ Codex (bảng việc, 25/9/2026).

Cam kết:
  1. Tạo task (kế hoạch / tự động): meta stage, language, text_model (model agent), preset, source (pasted/youtube).
  2. Task dựng tạo từ kế hoạch: tên = tên THẬT của video (không «· render:»), meta stage=render + task cha.
  3. Bước viết kịch bản: set_title với tiêu đề AI đặt — nhưng người dùng đã gõ tiêu đề thì giữ của họ.
  4. Bước giọng: meta.voice = giọng thật sự dùng.
  5. backfill_task_meta: task cũ tên chung chung + có checkpoint → đổi tên, ghi meta; task đã có meta thì bỏ qua.
Mọi codex_manager / agent đều giả.
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
import tubecli.extensions.codex.manager as CM  # noqa: E402
import tubecli.core.agent as AG  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


class _Agent:
    id, name, model, language, content_video_preset = "ag1", "Doctor", "ag/gemini-3.8-flash", "auto", "Chalk VI"


TASKS, META, TITLES, EVENTS = {}, {}, {}, {}
SEQ = [100]


def _create(**k):
    SEQ[0] += 1
    t = {"id": f"t{SEQ[0]}", "seq": SEQ[0], "status": "backlog", **k}
    TASKS[t["id"]] = t
    return t


CM.codex_manager.create_task = _create
CM.codex_manager.append_event = lambda tid, kind, text, actor=None, data=None: EVENTS.setdefault(tid, []).append({"data": data or {}})
CM.codex_manager.get_events = lambda tid, limit=1000: list(EVENTS.get(tid, []))
CM.codex_manager.set_meta = lambda tid, patch: META.setdefault(tid, {}).update({k: v for k, v in (patch or {}).items() if v not in (None, "")})
CM.codex_manager.set_title = lambda tid, title, actor="pipeline": TITLES.__setitem__(tid, title)
CM.codex_manager.get_task = lambda tid: TASKS.get(tid)
CM.codex_manager.kind_of = lambda tid: next((e["data"].get("kind") for e in reversed(EVENTS.get(tid, [])) if e["data"].get("kind")), None)
AG.agent_manager.get = lambda aid: _Agent()

# ── 1. tạo task ──────────────────────────────────────────────────────────────
t = P.create_plan_task("ag1", {"preset": "Chalk VI", "source_text": "Bài dán tay dài", "language": "auto"}, created_by="user")
m = META[t["id"]]
ok(m["stage"] == "plan" and m["text_model"] == "ag/gemini-3.8-flash" and m["preset"] == "Chalk VI" and m["source"] == "pasted"
   and "language" not in m, "task kế hoạch: stage, model agent, mẫu, nguồn dán; ngôn ngữ auto thì để trống", m)
t2 = P.create_auto_task("ag1", {"source_text": "https://www.youtube.com/watch?v=abc12345678", "language": "vi"}, created_by="user")
ok(META[t2["id"]]["source"] == "youtube" and META[t2["id"]]["language"] == "vi" and META[t2["id"]]["stage"] == "auto",
   "task tự động: nguồn YouTube, ngôn ngữ đã chọn", META[t2["id"]])

# ── 2. task dựng từ kế hoạch ─────────────────────────────────────────────────
P._read_checkpoint = lambda tid: {"script": "x", "title": "Sau 60 tuổi, 6 thói quen buổi tối", "language": "vi",
                                  "preset": "Chalk VI"} if tid == t["id"] else {}
META[t["id"]]["voice"] = {"engine": "everai", "id": "vi_female_huyenanh_mb"}
plan_task = {**t, "assignee_id": "ag1", "assignee_name": "Doctor", "priority": 0, "origin": {}, "meta": META[t["id"]]}
r = P.create_render_task(plan_task)
ok(r["title"] == "Sau 60 tuổi, 6 thói quen buổi tối" and META[r["id"]]["stage"] == "render"
   and META[r["id"]]["parent_id"] == t["id"] and META[r["id"]]["parent_seq"] == t["seq"]
   and META[r["id"]]["voice"]["id"] == "vi_female_huyenanh_mb" and META[r["id"]]["text_model"] == "ag/gemini-3.8-flash",
   "task dựng: tên thật, stage render, task cha, kế thừa giọng/model của kế hoạch", (r["title"], META[r["id"]]))

# ── 3. tên thật ở bước kịch bản ──────────────────────────────────────────────
TITLES.clear()
P._task_title("t9", "  Tên   AI đặt ", {"title": ""})
P._task_title("t8", "Tên AI đặt", {"title": "Tên tôi gõ"})
P._task_title("t7", "   ", {})
ok(TITLES == {"t9": "Tên AI đặt"}, "set_title gọn khoảng trắng; người dùng gõ tiêu đề thì giữ; rỗng thì bỏ", TITLES)
src = Path(P.__file__).read_text(encoding="utf-8")
ok(src.count("_task_title(state.get(\"task_id\"), state[\"title\"], options)") >= 3,
   "bước kịch bản (viết mới + dùng lại) và lượt dựng đều ghi tên thật")
ok('_task_title(state.get("task_id"), title)' in src, "bản clone ghi tên đã dịch")

# ── 4. giọng thật sự dùng ────────────────────────────────────────────────────
v = P._voice_meta("capcut", {"capcut_speaker": "ICL_jp_female_tt_you", "tts_voice_used": "CapCut · Yukiko · Japanese"}, {})
ok(v == {"engine": "capcut", "id": "ICL_jp_female_tt_you", "name": "Yukiko"}, "CapCut: id + tên giọng", v)
v2 = P._voice_meta("edge", {"tts_batch_engine": "everai", "tts_voice_pref": "vi_female_huyenanh_mb", "language": "vi"}, {})
ok(v2 == {"engine": "everai", "id": "vi_female_huyenanh_mb"}, "EverAI qua batch: engine thật + id", v2)
ok(P._voice_meta("edge", {"language": "ja"}, {}) == {"engine": "edge", "id": "ja-JP-NanamiNeural"}, "edge mặc định theo ngôn ngữ")
ok('_task_meta(state.get("task_id"), voice=_voice_meta(engine, state, options))' in src, "bước giọng ghi meta.voice")

# ── 5. backfill ──────────────────────────────────────────────────────────────
OLD = [{"id": "o1", "seq": 50, "lane": "video", "status": "review", "title": "Video from content: chuyên gia it"},
       {"id": "o2", "seq": 51, "lane": "video", "status": "done", "title": "Tên tôi tự đặt"},
       {"id": "o3", "seq": 52, "lane": "video", "status": "review", "title": "Drive: Sau 60 tuổi"},
       {"id": "o4", "seq": 53, "lane": "video", "status": "done", "title": "Đã có meta", "meta": {"stage": "auto"}},
       {"id": "o5", "seq": 54, "lane": "", "status": "done", "title": "Việc chung"}]
CM.codex_manager.list_tasks = lambda limit=0, **k: [dict(x) for x in OLD]
EVENTS.clear()
EVENTS["o1"] = [{"data": {"kind": P.KIND_AUTO, "options": {"source_text": "bài", "preset": "Chalk VI", "tts_engine": "everai", "tts_voice": "vi_x"}}}]
EVENTS["o2"] = [{"data": {"kind": P.KIND_PLAN, "options": {"title": "Tên tôi tự đặt"}}}]
EVENTS["o3"] = [{"data": {"kind": P.KIND_DRIVE, "source_task_id": "o1", "source_seq": 50, "options": {"drive": True}}}]
CK = {"o1": {"title": "Sau 60 tuổi, 6 thói quen", "language": "vi", "preset": "Chalk VI"}, "o2": {"title": "Tên AI đặt", "language": "vi"}}
P._read_checkpoint = lambda tid: dict(CK.get(tid, {}))
META.clear()
TITLES.clear()
n = P.backfill_task_meta()
ok(n == 3 and set(META) == {"o1", "o2", "o3"}, "quét đúng task video chưa có meta (bỏ task đã có meta và việc chung)", (n, sorted(META)))
ok(TITLES.get("o1") == "Sau 60 tuổi, 6 thói quen" and "o2" not in TITLES and TITLES.get("o3") == "Sau 60 tuổi, 6 thói quen",
   "đổi tên chung chung theo checkpoint (Drive lấy tên task nguồn); tên tự đặt giữ nguyên", TITLES)
ok(META["o1"]["stage"] == "auto" and META["o1"]["language"] == "vi" and META["o1"]["voice"] == {"engine": "everai", "id": "vi_x"}
   and META["o1"]["source"] == "pasted" and META["o3"]["stage"] == "drive" and META["o3"]["parent_id"] == "o1"
   and META["o3"]["parent_seq"] == 50, "meta điền từ payload + checkpoint", (META["o1"], META["o3"]))

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
