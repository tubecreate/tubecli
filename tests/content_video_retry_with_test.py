# -*- coding: utf-8 -*-
"""Hộp Retry của task video: đổi model viết / model vẽ / giọng cho RIÊNG lần chạy lại (25/9/2026).

User: «khi retry tôi nghĩ nên thêm dialog hiển thị model script, image, voice» — chốt: đổi được cả ba; đổi giọng
chỉ đọc nhịp còn thiếu; model ảnh chỉ vẽ ảnh thiếu, có ô «Vẽ lại tất cả». Cam kết:
  1. Lựa chọn nằm ở `retry_overrides` của payload MỚI (bản sao đầy đủ payload cũ) — executor đọc event có kind
     mới nhất; không nằm trong `options` nên không lây sang task dựng / bản clone.
  2. Model viết: agent được bọc — to_dict() mang model + provider mới, mọi thuộc tính khác của agent giữ nguyên.
  3. Giọng: options tts_engine/tts_voice (+ capcut_speaker, vì CapCut đọc nó TRƯỚC tts_voice).
  4. Model vẽ: gen-images nhận image_provider/image_model + force_model. «Vẽ lại tất cả» chỉ MỘT lần (mã trong
     checkpoint), Retry sau đó chỉ vẽ ảnh thiếu.
  5. Chỉ task lỗi / đã huỷ mới chạy lại được; task kịch bản (plan) chỉ đổi được model viết.
Mọi HTTP và codex_manager đều giả.
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

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", detail)


# ── 2–3: bọc agent + áp giọng ─────────────────────────────────────────────────
ok(P._model_ref("9router|cx/gpt-5.5") == ("9router", "cx/gpt-5.5") and P._model_ref("gemini-3.7-flash")
   == ("", "gemini-3.7-flash") and P._model_ref("") == ("", ""), "tách «nhà|model»")


class _Agent:
    id, name, model, allowed_profiles = "ag1", "Doctor", "ag/gemini-3.8-flash", ["p1"]

    def to_dict(self):
        return {"id": self.id, "model": self.model, "cloud_api_keys": {}}


opts = {"tts_engine": "auto", "tts_voice": "", "capcut_speaker": "old_speaker"}
st = {}
a = P._apply_retry_overrides({"retry_overrides": {"text_model": "9router|cx/gpt-5.5", "tts_engine": "capcut",
                                                  "tts_voice": "ICL_jp_female_tt_you", "capcut_email": "x@y"}},
                             _Agent(), opts, st)
ok(a.to_dict()["model"] == "cx/gpt-5.5" and a.to_dict()["provider"] == "9router" and a.model == "cx/gpt-5.5"
   and a.id == "ag1" and a.allowed_profiles == ["p1"], "model viết mới trong to_dict(); thuộc tính khác của agent giữ nguyên")
ok(st["text_model_ref"] == "9router|cx/gpt-5.5", "Studio nhận model đã chọn (ai_model)", st)
ok(opts["tts_engine"] == "capcut" and opts["tts_voice"] == "ICL_jp_female_tt_you" and opts["capcut_speaker"]
   == "ICL_jp_female_tt_you" and opts["capcut_email"] == "x@y", "giọng mới + capcut_speaker đặt lại (không để giọng cũ thắng)", opts)
opts2 = {"tts_engine": "auto", "tts_voice": ""}
a2 = P._apply_retry_overrides({}, _Agent(), opts2, {})
ok(isinstance(a2, _Agent) and opts2 == {"tts_engine": "auto", "tts_voice": ""}, "không chọn gì → không đụng agent/options")

# ── 1 + 5: retry_with ghi payload mới rồi mới retry ────────────────────────────
TASKS = {"t1": {"id": "t1", "seq": 119, "status": "failed", "title": "X", "assignee_id": "ag1"},
         "run": {"id": "run", "seq": 120, "status": "running"},
         "plan": {"id": "plan", "seq": 121, "status": "failed", "assignee_id": "ag1"}}
KINDS = {"t1": P.KIND_AUTO, "run": P.KIND_AUTO, "plan": P.KIND_PLAN}
EVENTS = {"t1": [{"data": {"kind": P.KIND_AUTO, "task_id": "t1", "agent_id": "ag1", "sources": [],
                           "options": {"preset": "Chalk VI", "source_text": "bài dán"}}}],
          "plan": [{"data": {"kind": P.KIND_PLAN, "task_id": "plan", "agent_id": "ag1", "options": {}}}]}
ORDER = []
CM.codex_manager.get_task = lambda tid: TASKS.get(tid)
CM.codex_manager.kind_of = lambda tid: KINDS.get(tid)
CM.codex_manager.get_events = lambda tid, limit=1000: list(EVENTS.get(tid, []))


def _append(tid, kind, text, actor=None, data=None):
    ORDER.append(("append", tid))
    EVENTS.setdefault(tid, []).append({"data": data or {}})


CM.codex_manager.append_event = _append
CM.codex_manager.retry = lambda tid, actor="user": ORDER.append(("retry", tid)) or {"id": tid, "status": "queued"}
P._read_checkpoint = lambda tid: {"language": "vi", "episode_id": 9}
P._load_preset = lambda name: {"language": "vi", "metadata": {"tts_engine": "omnivoice", "tts_voice": "2471e659",
                                                             "image_models": {"hook": "9router|cx/gpt-image-2"}}}
import tubecli.core.agent as _agmod  # noqa: E402
_agmod.agent_manager.get = lambda aid: _Agent()

info = P.retry_info("t1")
ok(info["ok"] and info["text"]["agent"] == "ag/gemini-3.8-flash" and info["voice"]["engine"] == "omnivoice"
   and info["voice"]["id"] == "2471e659" and info["image"]["roles"] == {"hook": "9router|cx/gpt-image-2"}
   and info["language"] == "vi", "hộp Retry thấy model agent, giọng + model ảnh của mẫu", info)
ok(P.retry_info("run")["reason"] == "not_retryable", "task đang chạy → không chạy lại được")

P.retry_with("t1", text_model="gemini|gemini-3.7-flash", image_model="cloudflare|@cf/black-forest-labs/flux-1-schnell",
             tts_engine="everai", tts_voice="vi_female_huyenanh_mb", redraw_images=True, actor="user:web")
new = EVENTS["t1"][-1]["data"]
ok(ORDER[-2:] == [("append", "t1"), ("retry", "t1")], "ghi payload mới TRƯỚC khi retry", ORDER[-2:])
ok(new["kind"] == P.KIND_AUTO and new["task_id"] == "t1" and new["options"]["source_text"] == "bài dán"
   and "retry_overrides" not in new["options"], "payload mới = bản sao đầy đủ + retry_overrides ngoài options", new)
ov = new["retry_overrides"]
ok(ov["text_model"] == "gemini|gemini-3.7-flash" and ov["image_model"].startswith("cloudflare|")
   and ov["tts_voice"] == "vi_female_huyenanh_mb" and len(ov["redraw_images"]) == 12, "lựa chọn được ghi đủ", ov)
code = ov["redraw_images"]
n = len(EVENTS["t1"])
P.retry_with("t1", text_model="gemini|gemini-3.7-flash", image_model="cloudflare|@cf/black-forest-labs/flux-1-schnell",
             tts_engine="everai", tts_voice="vi_female_huyenanh_mb", redraw_images=False)
ok(len(EVENTS["t1"]) == n and ORDER[-1] == ("retry", "t1")
   and EVENTS["t1"][-1]["data"]["retry_overrides"].get("redraw_images") == code,
   "không đổi gì (không tick) → không ghi event mới, mã «vẽ lại» đã dùng vẫn nằm ở payload mới nhất")
P.retry_with("t1", text_model="gemini|gemini-3.7-flash", image_model="cloudflare|@cf/black-forest-labs/flux-1-schnell",
             tts_engine="edge", tts_voice="vi-VN-HoaiMyNeural", redraw_images=False)
ok(len(EVENTS["t1"]) == n + 1 and EVENTS["t1"][-1]["data"]["retry_overrides"].get("redraw_images") == code
   and EVENTS["t1"][-1]["data"]["retry_overrides"]["tts_voice"] == "vi-VN-HoaiMyNeural",
   "đổi giọng mà không tick → event mới GIỮ mã «vẽ lại» cũ (đã dùng) — không vẽ lại lần nữa",
   EVENTS["t1"][-1]["data"]["retry_overrides"])
try:
    P.retry_with("run", text_model="x")
    ok(False, "task đang chạy phải bị từ chối")
except ValueError:
    ok(True, "task đang chạy → ValueError (route trả 400)")
P.retry_with("plan", text_model="9router|cx/gpt-5.5", image_model="cloudflare|x", tts_voice="v", tts_engine="edge")
ok(EVENTS["plan"][-1]["data"]["retry_overrides"] == {"text_model": "9router|cx/gpt-5.5"},
   "task kịch bản: chỉ nhận model viết", EVENTS["plan"][-1]["data"]["retry_overrides"])

# ── 4: bước ảnh gửi model ép + vẽ lại một lần ─────────────────────────────────
BODIES, CK = [], {}
P._canvas_kit_meta = lambda state: None
P._fill_missing_prompts = lambda state: 0
P._shots_without_media = lambda ep: []
P._post = lambda path, payload, timeout=60: BODIES.append((path, dict(payload))) or {"task_id": "g1", "total": 3,
                                                                                        "with_prompt": 3}
P._poll_studio = lambda *a, **k: {"status": "completed", "total": 3, "ok": 3, "errors": []}
P._checkpoint_merge = lambda state, data: CK.update(data)


def img_state(ov, ck=None):
    return {"episode_id": 9, "_say": lambda *a, **k: None, "warnings": [], "checkpoint": ck or {},
            "retry_overrides": ov, "aspect_ratio": "16:9"}


P._step_images(img_state({"image_model": "cloudflare|@cf/x", "redraw_images": "abc123"}), {})
b = BODIES[-1][1]
ok(b["image_provider"] == "cloudflare" and b["image_model"] == "@cf/x" and b["force_model"] is True
   and b["overwrite"] is True, "model ép + vẽ lại tất cả ở lần đầu", b)
ok(CK.get("redraw_done") == "abc123", "ghi mã «đã vẽ lại» vào checkpoint", CK)
P._step_images(img_state({"image_model": "cloudflare|@cf/x", "redraw_images": "abc123"}, {"redraw_done": "abc123"}), {})
ok(BODIES[-1][1]["overwrite"] is False, "Retry sau (mã đã dùng) → chỉ vẽ ảnh thiếu", BODIES[-1][1])
P._step_images(img_state({}), {})
ok("force_model" not in BODIES[-1][1] and BODIES[-1][1]["overwrite"] is False, "không chọn gì → như cũ", BODIES[-1][1])

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
