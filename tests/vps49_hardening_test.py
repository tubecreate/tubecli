# -*- coding: utf-8 -*-
"""Rà soát VPS 49 (22/10/2026) — «lần sau không lỗi lại»: các chốt chặn của lõi .213.

Kiểm (mọi model / trình duyệt / sổ task đều GIẢ):
  A. dàn ý THIẾU cảnh (47 định, model trả 6): hỏi lại một lần; vẫn thiếu thì xin viết TIẾP phần còn lại; đủ thì thôi
  B. kịch bản quá ngắn so với kế hoạch (< 50 %): lượt TỰ ĐĂNG dựng nhưng không đăng, cảnh báo có số; lệnh tay «đăng
     luôn» và chế độ nguyên văn vẫn đăng
  C. kênh chưa xác minh: lượt tự đăng viết kịch bản ~2000 chữ (≈13 phút) thay vì độ dài của mẫu (tĩnh + hằng)
  D. xoá task kèm purge chạy ở LUỒNG PHỤ (không treo vòng sự kiện của máy chủ)
  E. Muse: lượt ảnh/chữ quá hạn ở một chỗ ngồi thì lượt thử lại sang chỗ KHÁC

Run:  python tests/vps49_hardening_test.py
"""
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vps49_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


from tubecli.extensions.content_video import pipeline as P  # noqa: E402

# ── A ────────────────────────────────────────────────────────────────────────
print("A. dàn ý thiếu cảnh")


def lines(a, b):
    return "\n".join(f"[SHOW: picture {i}] — idea {i}" for i in range(a, b + 1))


def run_complete(answers, have=6, planned=47):
    asked = []

    def fake_ask(agent, system_prompt, user_prompt, budget_words):
        asked.append((user_prompt, budget_words))
        return answers[len(asked) - 1]

    P._ask_model = fake_ask
    said = []
    outline = [(f"picture {i}", f"idea {i}") for i in range(1, have + 1)]
    title, out = P._complete_outline(None, "sys", "PLAN", "T", outline, planned, lambda *a: said.append(a[2]))
    return title, out, asked, said


title, out, asked, said = run_complete(["TITLE: Again\n" + lines(1, 6), lines(7, 47)])
check("hỏi lại vẫn 6 ⇒ xin viết TIẾP 41 cảnh ⇒ đủ 47", len(out) == 47 and len(asked) == 2, (len(out), len(asked)))
check("lời xin viết tiếp nêu đúng khoảng cảnh + dàn ý đã có", "scenes 7-47" in asked[1][0] and "1. [SHOW: picture 1]" in asked[1][0]
      and asked[1][1] == 41 * P._OUTLINE_WORDS, asked[1][0][-300:])
check("thẻ bước nói rõ đang làm gì", any("6 scenes, 47 planned" in s for s in said) and any("other 41" in s for s in said), said)
title, out, asked, said = run_complete(["TITLE: Full\n" + lines(1, 47)])
check("hỏi lại ra đủ ⇒ lấy bản mới, không gọi thêm", len(out) == 47 and len(asked) == 1 and title == "Full", (len(out), len(asked), title))
title, out, asked, said = run_complete(["TITLE: X\n" + lines(1, 4), lines(7, 90)])
check("viết tiếp dư thì cắt đúng số cảnh đã định", len(out) == 47, len(out))
src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
check("đường viết mới gọi _complete_outline khi dàn ý < 60 % số cảnh",
      "if 2 <= len(outline) < scenes_n * _OUTLINE_SHORT:" in src and P._OUTLINE_SHORT == 0.6)
check("ngân sách dàn ý đủ chữ cho mọi dòng (55 chữ/cảnh thay 40)",
      "scenes_n * 40)" not in src and src.count("scenes_n * _OUTLINE_WORDS") >= 3)

# ── B ────────────────────────────────────────────────────────────────────────
print("B. kịch bản quá ngắn ⇒ không tự đăng")
SHORT = " ".join(["palabra"] * 342)
LONG = " ".join(["palabra"] * 2600)
st = {"target_words": 2820, "script": SHORT, "video_path": "/x/ep.mp4", "words_from": "content DNA"}
w = P._too_short_to_autopublish(st, {"publish": True, "autopublish": True})
check("342/2820 chữ ⇒ câu cảnh báo có số + giữ video", "~342 words" in w and "~2820 planned" in w and "/x/ep.mp4" in w, w)
check("lệnh tay «đăng luôn» (_publish_hard) ⇒ vẫn đăng", P._too_short_to_autopublish(st, {"_publish_hard": True}) == "")
check("nguyên văn ⇒ vẫn đăng", P._too_short_to_autopublish({**st, "words_from": "verbatim"}, {}) == "")
check("đủ dài ⇒ đăng", P._too_short_to_autopublish({**st, "script": LONG}, {}) == "")
check("không biết độ dài đã định ⇒ đăng", P._too_short_to_autopublish({**st, "target_words": 0}, {}) == "")

PUB = []
P.media_seconds = lambda path: 135.0
P._publish_now = lambda state, options: PUB.append(1)
P._remember_published = lambda state: None
P._commit_autopublish = lambda state, options: None
s = {**st, "_say": lambda *a: None, "warnings": []}
P._step_publish(s, {"publish": True, "autopublish": True})
check("_step_publish: kịch bản ngắn ⇒ không gọi đăng, publish_blocked=short_script, không ném",
      not PUB and s.get("publish_blocked") == "short_script" and any("Not auto-published" in x for x in s["warnings"]), s)
s = {**st, "script": LONG, "_say": lambda *a: None, "warnings": []}
P._step_publish(s, {"publish": True, "autopublish": True})
check("_step_publish: đủ dài ⇒ đăng như cũ", PUB == [1] and not s.get("publish_blocked"), s.get("publish_blocked"))

# ── C ────────────────────────────────────────────────────────────────────────
print("C. kênh chưa xác minh ⇒ kịch bản vừa 15 phút")
check("trần ~2000 chữ ≈ 13 phút (< 15)", P.UNVERIFIED_SAFE_WORDS == 2000 and P.minutes_of(2000) < 15)
cap = src[src.index("words, words_from = resolve_words(opts_len"):src.index("scenes_n, sent_lo, sent_hi = scene_budget(words)")]
check("chỉ lượt ĐĂNG + cờ chưa xác minh + mẫu dài hơn trần mới bị giới hạn; cảnh báo nêu cách gỡ",
      'options.get("publish") and options.get("publish_unverified") and words > UNVERIFIED_SAFE_WORDS' in cap
      and "VERIFY_URL" in cap and 'state["words_capped"] = True' in cap, cap)

# ── D ────────────────────────────────────────────────────────────────────────
print("D. xoá task kèm purge không treo máy chủ")
from tubecli.extensions.codex import routes as CR  # noqa: E402

seen = {}


def fake_delete(task_id, purge=False, actor="user"):
    seen["thread"] = threading.current_thread() is threading.main_thread()
    try:
        asyncio.get_running_loop()
        seen["loop"] = True
    except RuntimeError:
        seen["loop"] = False
    return {"task": {"id": task_id}, "purge": {"files": 3}}


CR._require = lambda tid: {"id": tid}
CR.codex_manager.delete = fake_delete
out = asyncio.run(CR.delete_task("t1", purge=True))
check("delete chạy ở luồng phụ (không có vòng sự kiện đang chạy trong hook)",
      seen == {"thread": False, "loop": False} and out["purge"] == {"files": 3}, seen)

# ── E ────────────────────────────────────────────────────────────────────────
print("E. Muse: quá hạn ở chỗ A ⇒ thử lại ở chỗ B")
from tubecli.core import muse as M  # noqa: E402

PROFILES = TMP / "profiles"
for p in ("seatA", "seatB"):
    (PROFILES / p).mkdir(parents=True)
M._profiles_dir = lambda: str(PROFILES)
M._state_file = lambda: str(TMP / "muse_state.json")
M.set_settings(profile="seatA", extra_profiles=["seatB"])
PORTS = {"seatA": 9001, "seatB": 9002}
M.ensure_browser = lambda profile, launch=True: PORTS[profile]
M.reset_browser = lambda profile: None
M.RESET_WAIT = 0
used = []


def tool(port, action, req=None, timeout=60):
    used.append(port)
    if port == 9001:
        return {"ok": False, "kind": "timeout", "error": "Muse did not finish within 300 s."}
    return {"ok": True, "text": "done", "images": [], "thread_id": "T1"}


M.run_tool = tool
M._LAST_USED.clear()
M._LAST_USED["seatB"] = time.time() + 3600      # «vừa dùng» ⇒ không có tránh thì lượt sau lại vào A
res = M.ask("hello", timeout=5)
check("A treo ⇒ lượt thử lại sang B (không quay lại đúng chỗ vừa treo)", used == [9001, 9002] and res.get("profile") == "seatB",
      (used, res.get("profile")))
used.clear()
M._LAST_USED.clear()
M.set_settings(profile="seatA", extra_profiles=[])
try:
    M.ask("hello", timeout=5)
except M.MuseError as e:
    check("chỉ một chỗ ⇒ vẫn thử lại chính nó (không đứng chờ chỗ không tồn tại)", used == [9001] * M.MUSE_ATTEMPTS
          and e.kind == "timeout", (used, e.kind))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
