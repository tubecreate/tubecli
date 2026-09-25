# -*- coding: utf-8 -*-
"""«Clone sang ngôn ngữ khác» (25/9/2026) — phần dịch (clone.py) và bước `clone` của pipeline.

User: «làm xong một bài bằng tiếng việt, muốn sử dụng lại hình ảnh và nội dung của nó nhưng dùng ngôn ngữ khác, bấm
clone và chọn ngôn ngữ». Cam kết:
  1. Mỗi nhịp dịch MỘT-MỘT: lời đọc, tiêu đề nhịp, chữ trên bảng (theo đường dẫn), nhãn sơ đồ — không gộp/tách nhịp.
  2. `hot` phải nằm trong `head` đã dịch; lệch thì bỏ tô (không tô cụm không có thật).
  3. Model bỏ sót nhịp → hỏi lại MỘT lần riêng các nhịp thiếu; vẫn thiếu → lỗi rõ, không tạo tập nửa vời.
  4. Bước clone: tạo dự án ngôn ngữ đích (giọng đã chọn, meta của dự án gốc), gọi Studio clone-shots với bản dịch,
     ghi kịch bản mới; Retry không tạo dự án thứ hai, tập đã có nhịp thì không dịch lại.
  5. CLONE_STEPS: không có «studio» và không đăng YouTube.
Mọi HTTP và model đều giả — test không chạm máy chủ đang chạy.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import clone as C  # noqa: E402
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


# ── 1–2: tách/ghép chữ trên bảng ─────────────────────────────────────────────
SC = {"type": "cluster", "head": "Ba thói quen", "hot": "thói quen", "sprite": "lib:x",
      "items": [["lib:a", "Tắm nóng"], ["@2", "Xà bông"], "Kỳ cọ"], "side": "right"}
tx = C.scene_texts(SC)
ok(tx == {"head": "Ba thói quen", "hot": "thói quen", "items.0.1": "Tắm nóng", "items.1.1": "Xà bông",
          "items.2": "Kỳ cọ"}, "chỉ lấy CHỮ (không lấy tham chiếu hình / type / side)", tx)
new = C.apply_scene_texts(SC, {"head": "Three habits", "hot": "habits", "items.0.1": "Hot baths",
                               "items.2": "Scrubbing", "sprite": "HACK", "items.9": "x"})
ok(new["items"][0] == ["lib:a", "Hot baths"] and new["items"][2] == "Scrubbing" and new["sprite"] == "lib:x",
   "ghép đúng chỗ, giữ tham chiếu hình, bỏ khoá lạ / chỉ số ngoài phạm vi", new)
ok(new["items"][1] == ["@2", "Xà bông"], "khoá thiếu bản dịch giữ chữ cũ", new["items"][1])
ok(SC["head"] == "Ba thói quen", "không sửa cảnh gốc")
ok(C.apply_scene_texts({"head": "Hot water", "hot": "x"}, {"head": "Nước nóng", "hot": "nóng quá"})["hot"] == "",
   "hot không nằm trong head đã dịch → bỏ tô")
ok(C.apply_scene_texts({"head": "a", "hot": "a"}, {"head": "Heißes Wasser", "hot": "wasser"})["hot"] == "Wasser",
   "hot khác hoa/thường → lấy đúng chữ trong head")
ok(C.diagram_labels({"type": "diagram", "subject": "cycle 'tế bào', 'bong ra'"}) == ["tế bào", "bong ra"]
   and C.diagram_labels({"type": "board", "subject": "'x'"}) == [], "nhãn sơ đồ chỉ lấy ở cảnh diagram")

# ── đọc trả lời model ────────────────────────────────────────────────────────
ok(set(C.parse_reply('```json\n{"shots":[{"id":1,"narration":"Hi."},{"id":"2","narration":""}]}\n```')) == {"1"},
   "bóc JSON trong ```json, bỏ mục lời rỗng")
ok(C.parse_reply("sorry, no") == {} and C.parse_reply('{"shots": "x"}') == {}, "trả lời hỏng → {}")

# Nhịp lời RỖNG mà bảng có chữ (lỗi chia lời .151 để lại) — vẫn phải dịch chữ, lời giữ rỗng.
EMPTY = [{"id": 5, "storyboard_number": 5, "narration_text": "", "metadata": json.dumps({"scene": {"type": "board",
          "head": "Tắm khuya", "hot": ""}})},
         {"id": 6, "storyboard_number": 6, "narration_text": "", "metadata": "{}"}]
wi = C.work_items(EMPTY)
ok([x["id"] for x in wi] == ["5"], "nhịp không có chữ nào không gửi model; lời rỗng mà bảng có chữ thì gửi", wi)
got_e = C.parse_reply('{"shots":[{"id":"5","narration":"","texts":{"head":"Late-night baths"}}]}')
ok("5" in got_e and C.missing(wi, got_e) == [] and C.missing(wi, {}) == wi,
   "trả lời chỉ có chữ bảng vẫn nhận; thiếu hẳn thì hỏi lại", got_e)
row5 = C.to_studio(wi, got_e, {"5": json.loads(EMPTY[0]["metadata"])["scene"]})["5"]
ok(row5["narration_text"] == "" and row5["scene"]["head"] == "Late-night baths",
   "lời rỗng giữ rỗng, chữ trên bảng lấy bản dịch", row5)
lost_narr = C.missing([{"id": "9", "narration": "Có lời."}], {"9": {"id": "9", "narration": "", "texts": {}}})
ok(len(lost_narr) == 1, "bản gốc có lời mà bản dịch trả lời rỗng → coi như thiếu, hỏi lại", lost_narr)

# ── 3–4: bước clone với model + Studio giả ────────────────────────────────────
SRC = [{"id": i, "storyboard_number": i, "narration_text": f"Câu số {i} của bài.", "title": "",
        "metadata": json.dumps({"scene": {"type": "board", "head": f"Ý {i}", "hot": "", "sprite": "lib:k"}})}
       for i in range(1, 16)]
SRC[2]["metadata"] = json.dumps({"scene": {"type": "diagram", "head": "Vòng da", "hot": "",
                                           "subject": "a cycle with labels 'tế bào mới', 'bong ra'"}})
TARGET = []
CALLS = {"ask": 0, "posts": [], "puts": [], "ck": {}}


def fake_ask(agent, system, user, budget):
    CALLS["ask"] += 1
    if "Reply with the title only" in system:
        return "Skin after 60"
    shots = json.loads(user)["shots"]
    out = []
    for it in shots:
        if it["id"] == "7" and CALLS.get("drop7", 0) > 0:     # lần đầu bỏ sót nhịp 7
            CALLS["drop7"] -= 1
            continue
        row = {"id": it["id"], "narration": "EN " + it["narration"]}
        if it.get("texts"):
            row["texts"] = {k: "EN " + v for k, v in it["texts"].items()}
        if it.get("labels"):
            row["labels"] = ["new cells", "shed"]
        out.append(row)
    return json.dumps({"shots": out})


def fake_post(path, payload, timeout=300):
    CALLS["posts"].append((path, payload))
    if path == "/api/v1/studio/dramas":
        return {"id": 900}
    if path.endswith("/episodes"):
        return {"id": 901}
    if path.endswith("/clone-shots"):
        for sid, row in payload["texts"].items():
            TARGET.append({"id": 1000 + int(sid), "storyboard_number": int(sid),
                           "narration_text": row["narration_text"]})
        return {"success": True, "count": len(payload["texts"]), "copied": 14, "redraw": 1, "missing": 0}
    raise AssertionError(path)


P._ask_model = fake_ask
P._post = fake_post
P._put = lambda path, payload, timeout=60: CALLS["puts"].append((path, payload)) or {}
P._get = lambda path, timeout=60: {"style": "chalk", "metadata": json.dumps(
    {"render_engine": "canvas", "scene_kit": "chalk_text", "tts_engine": "everai", "tts_voice": "vi_female",
     "tts_email": "x@y"})}
P._storyboards = lambda ep: SRC if int(ep) == 553 else sorted(TARGET, key=lambda s: s["storyboard_number"])
P._checkpoint_merge = lambda state, data: CALLS["ck"].update(data)
P.detect_language_sure = lambda text: "en"


class _Agent:
    id, name = "ag1", "Doctor"


def new_state(checkpoint=None):
    return {"agent": _Agent(), "checkpoint": checkpoint or {}, "_say": lambda *a, **k: None,
            "_cancelled": lambda: False, "warnings": [], "language": "en", "preset_name": "Chalk VI",
            "clone_source": {"episode_id": 553, "drama_id": 388, "title": "Da sau 60", "language": "vi"},
            "clone_source_seq": 113}


CALLS["drop7"] = 1
st = new_state()
P._step_clone(st, {"tts_engine": "edge", "tts_voice": "en-US-AriaNeural"})
drama_body = CALLS["posts"][0][1]
ok(drama_body["language"] == "en" and drama_body["title"] == "Skin after 60",
   "dự án mới: ngôn ngữ đích + tiêu đề đã dịch", drama_body)
m = drama_body["metadata"]
ok(m["scene_kit"] == "chalk_text" and m["tts_engine"] == "edge" and m["tts_voice"] == "en-US-AriaNeural"
   and "tts_email" not in m and m["cloned_from_episode"] == 553,
   "giữ meta dựng của dự án gốc, giọng = giọng đã chọn (bỏ tài khoản giọng cũ)", m)
clone_call = [p for p in CALLS["posts"] if p[0].endswith("/clone-shots")][0]
ok(clone_call[0] == "/api/v1/studio/episodes/553/clone-shots" and clone_call[1]["episode_id"] == 901
   and clone_call[1]["redraw_diagrams"] is True, "gọi Studio clone-shots từ tập gốc sang tập mới", clone_call[0])
texts = clone_call[1]["texts"]
ok(len(texts) == 15 and texts["7"]["narration_text"] == "EN Câu số 7 của bài.",
   "đủ 15 nhịp, nhịp model bỏ sót được hỏi lại một lần", (len(texts), texts.get("7")))
ok(texts["3"]["labels"] == ["new cells", "shed"] and texts["1"]["scene"]["head"] == "EN Ý 1",
   "chữ trên bảng + nhãn sơ đồ đi kèm", (texts["3"].get("labels"), texts["1"].get("scene")))
ok(st["script"].startswith("EN Câu số 1") and CALLS["ck"].get("script") == st["script"]
   and CALLS["ck"].get("episode_id") == 901, "kịch bản mới ghi vào state + checkpoint", st["script"][:40])
ok(any(p[0] == "/api/v1/studio/episodes/901" for p in CALLS["puts"]), "tab Kịch bản của Studio có chữ mới")

# Retry: checkpoint đã có tập + tập đã có nhịp → không tạo dự án, không dịch lại.
n_posts, n_ask = len(CALLS["posts"]), CALLS["ask"]
st2 = new_state({"drama_id": 900, "episode_id": 901, "title": "Skin after 60"})
P._step_clone(st2, {"tts_engine": "edge", "tts_voice": "en-US-AriaNeural"})
ok(len(CALLS["posts"]) == n_posts and CALLS["ask"] == n_ask and st2["shot_count"] == 15,
   "Retry: dùng lại tập + nhịp đã chép, không gọi model/Studio thêm", (len(CALLS["posts"]) - n_posts, CALLS["ask"] - n_ask))

# Model bỏ sót mãi → lỗi rõ, Studio KHÔNG bị gọi.
TARGET.clear()
CALLS["posts"].clear()
CALLS["drop7"] = 5
try:
    P._step_clone(new_state(), {"tts_engine": "edge"})
    ok(False, "bỏ sót mãi phải báo lỗi")
except RuntimeError as e:
    ok("did not translate 1 shot" in str(e) and not any(p[0].endswith("/clone-shots") for p in CALLS["posts"]),
       "model bỏ sót sau lần hỏi lại → lỗi rõ, chưa chép nhịp nào", str(e)[:120])

# ── Tạo task clone: options + chặn trường hợp sai (codex_manager giả) ──────────────────────────────────────────
import tubecli.extensions.codex.manager as CM  # noqa: E402

TASKS = {"src": {"id": "src", "seq": 113, "status": "review", "title": "Da sau 60", "assignee_id": "ag1",
                 "assignee_name": "Doctor", "priority": 2, "origin": {"channel": "web"}},
         "busy": {"id": "busy", "seq": 114, "status": "running"}}
KINDS = {"src": P.KIND_RENDER, "busy": P.KIND_RENDER}
EVENTS, CREATED = [], []
SRC_OPTS = {"preset": "Chalk VI", "drive": True, "drive_token_id": "tok1", "drive_public": True, "publish": True,
            "tts_engine": "everai", "tts_voice": "vi_female_huyenanh_mb", "source_text": "rất dài", "language": "vi"}
CM.codex_manager.get_task = lambda tid: TASKS.get(tid)
CM.codex_manager.kind_of = lambda tid: KINDS.get(tid)
CM.codex_manager.get_events = lambda tid, limit=1000: [{"data": {"kind": P.KIND_RENDER, "options": SRC_OPTS}}]
CM.codex_manager.create_task = lambda **k: CREATED.append(k) or {"id": "new", "seq": 120, **k}
CM.codex_manager.append_event = lambda tid, kind, text, actor=None, data=None: EVENTS.append(data or {})
P._read_checkpoint = lambda tid: ({"episode_id": 553, "drama_id": 388, "title": "Da sau 60", "language": "vi",
                                   "preset": "Chalk VI", "script": "x"} if tid == "src" else {})

info = P.clone_info("src")
ok(info["ok"] and info["language"] == "vi" and info["drive"] is True and all(l["code"] != "vi" for l in info["languages"]),
   "hộp Clone: ngôn ngữ gốc, bỏ ngôn ngữ gốc khỏi danh sách, biết bản gốc có lưu Drive", info.get("language"))
ok(P.clone_info("busy")["reason"] == "busy" and P.clone_info("nope")["reason"] == "not_found",
   "task đang chạy / không có → nói lý do")
P.create_clone_task("src", "en", "edge", "en-US-AriaNeural")
opts = EVENTS[-1]["options"]
ok(EVENTS[-1]["kind"] == P.KIND_CLONE and EVENTS[-1]["source_task_id"] == "src" and EVENTS[-1]["language"] == "en",
   "event kind clone trỏ về task gốc", EVENTS[-1].get("kind"))
ok(opts["language"] == "en" and opts["tts_engine"] == "edge" and opts["tts_voice"] == "en-US-AriaNeural"
   and opts["publish"] is False and "source_text" not in opts and opts["drive"] is True and opts["drive_token_id"] == "tok1",
   "options: ngôn ngữ + giọng mới, không đăng, bỏ bài gốc, giữ Drive như bản gốc", opts)
ok(CREATED[-1]["lane"] == P.CODEX_LANE and CREATED[-1]["hold"] is True and CREATED[-1]["title"] == "Da sau 60",      # tên bài thật; «Clone → English» là chip (25/9)
   "task clone xếp hàng trong làn video", CREATED[-1].get("title"))
P.create_clone_task("src", "ja", "", "", "", "user", False)
ok(EVENTS[-1]["options"]["drive"] is False and EVENTS[-1]["options"]["tts_voice"] == "ja-JP-NanamiNeural",
   "bỏ tick Drive → không tải lên; không chọn giọng → giọng Edge của ngôn ngữ", EVENTS[-1]["options"])
for bad, why in ((("src", "vi"), "cùng ngôn ngữ"), (("src", "xx"), "ngôn ngữ lạ"), (("busy", "en"), "task đang chạy")):
    try:
        P.create_clone_task(*bad)
        ok(False, f"{why} phải bị từ chối")
    except ValueError:
        ok(True, f"{why} → từ chối")

ok("narrator or the voice" in C.title_prompt("Sau 60 tuổi (giọng Huyền Anh)", "Vietnamese", "English")[0],
   "dịch tiêu đề: dặn bỏ ghi chú giọng đọc của bản gốc")

# ── 5: danh sách bước ────────────────────────────────────────────────────────
ids = [s[0] for s in P.CLONE_STEPS]
ok(ids == ["capabilities", "clone", "images", "tts", "render", "thumbnail", "drive"],
   "CLONE_STEPS: clone thay studio, không publish", ids)
ok("clone" in P._HANDLERS and P.LABELS.get("clone"), "bước clone có handler + nhãn")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
