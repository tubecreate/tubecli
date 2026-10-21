# -*- coding: utf-8 -*-
"""Lồng lại giọng bằng Muse (bước "dub", 21/10/2026).

User: «làm capcut xong lồng lại bằng muse», «chỗ logic lồng giọng bạn để ở phần tạo task, template vẫn dùng model theo
template». Kiểm (KHÔNG gọi Muse / Studio thật — mọi HTTP và Muse đều giả; ffmpeg thật để dựng + cắt âm thanh tổng hợp):
  A. narration_dub: cắt theo khoảng lặng chuyển đoạn (không Whisper) + theo mốc Whisper giả (cắt + mốc chữ theo ký tự);
     bản đọc lệch kịch bản bị từ chối.
  B. muse.speech_prompt / generate_speech: một lượt, chat mới, xin file tiếng; không có file → MuseError; ask gửi want_audio
     tới công cụ trình duyệt và tránh nút từ xa.
  C. pipeline: bước dub nằm sau tts, mặc định tắt, hỏng mềm; _step_dub thay đường giọng từng cảnh, nhớ checkpoint (Retry
     không gọi Muse lại), cảnh không lời bỏ qua.

Chạy: python tests/content_video_dub_test.py   (exit 0 = pass)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.extensions.content_video import narration_dub as ND  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.core import muse as M  # noqa: E402

PASS = FAIL = 0


def ok(cond, name, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", name)
    else:
        FAIL += 1
        print("  FAIL", name, "->", str(info)[:300])


try:
    from tubecli.extensions.video_studio.ffmpeg_utils import find_ffmpeg
    FF = find_ffmpeg() or shutil.which("ffmpeg") or ""
except Exception:      # noqa: BLE001
    FF = shutil.which("ffmpeg") or ""

tmp = tempfile.mkdtemp(prefix="dub_test_")
PARAS = ["一つ目の段落です。短い文です。", "二つ目の段落はもう少し長く書いてあります。ここにも文があります。", "三つ目。おわり。"]


def tone_layout():
    """Âm thanh tổng hợp: mỗi câu = tiếng bíp (0,12 s/ký tự), nghỉ 0,4 s giữa câu, 1,4 s giữa đoạn. Trả (đường dẫn,
    [(giờ bắt đầu đoạn, giờ hết đoạn)], (ký tự Whisper giả, giờ))."""
    parts, t, spans, chars, times = [], 0.0, [], [], []
    for pi, para in enumerate(PARAS):
        sents = [x + "。" for x in para.split("。") if x]
        p0 = t
        for si, sent in enumerate(sents):
            n, rawmap = ND.norm_with_map(sent)
            dur = 0.12 * len(n)
            parts.append(("tone", dur))
            for k, c in enumerate(n):
                chars.append(c)
                times.append(t + 0.12 * (k + 0.5) + 0.25)      # Whisper trễ 0,25 s như đo thật
            t += dur
            if si < len(sents) - 1:
                parts.append(("sil", 0.4))
                t += 0.4
        spans.append((p0, t))
        if pi < len(PARAS) - 1:
            parts.append(("sil", 1.4))
            t += 1.4
    parts.append(("sil", 0.3))
    t += 0.3
    inputs, filt = [], []
    for i, (kind, d) in enumerate(parts):
        src = f"sine=frequency=440:sample_rate=24000:duration={d:.3f}" if kind == "tone" else \
            f"anullsrc=r=24000:cl=mono:d={d:.3f}"
        inputs += ["-f", "lavfi", "-i", src]
        filt.append(f"[{i}:a]")
    out = os.path.join(tmp, "full.mp3")
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex",
                    "".join(filt) + f"concat=n={len(parts)}:v=0:a=1[o]", "-map", "[o]", "-ac", "1", "-c:a", "libmp3lame",
                    out], check=True)
    return out, spans, ("".join(chars), times)


print("── A. narration_dub ──")
if not FF:
    print("  (bỏ qua A: máy không có ffmpeg)")
else:
    full, spans, heard = tone_layout()
    info = ND.split_by_paragraph(full, PARAS, os.path.join(tmp, "a1"), FF, "ja", transcribe=lambda s, l: None)
    ends = [f["end"] for f in info["files"]][:-1]
    want = [(spans[i][1] + spans[i + 1][0]) / 2 for i in range(len(PARAS) - 1)]
    ok(info["engine"] == "silence" and all(abs(e - w) < 0.25 for e, w in zip(ends, want)),
       "không Whisper: cắt giữa khoảng lặng chuyển đoạn (1,4 s), bỏ qua khoảng nghỉ câu (0,4 s)", (ends, want))
    ok(all(os.path.isfile(f["path"]) and not os.path.isfile(f["path"] + ".words.json") for f in info["files"]),
       "không Whisper: có file từng cảnh, không ghi mốc chữ (Studio tự ước lượng)")
    info2 = ND.split_by_paragraph(full, PARAS, os.path.join(tmp, "a2"), FF, "ja", transcribe=lambda s, l: heard)
    ends2 = [f["end"] for f in info2["files"]][:-1]
    ok(info2["engine"] == "whisper" and info2["match"] == 1.0 and all(abs(e - w) < 0.25 for e, w in zip(ends2, want)),
       "Whisper giả (trễ 0,25 s): cắt đúng chỗ chuyển đoạn", (info2["match"], ends2, want))
    side = info2["files"][1]["path"] + ".words.json"
    marks = json.load(open(side, encoding="utf-8"))["words"] if os.path.isfile(side) else []
    n1 = ND.norm_with_map(PARAS[1])[0]
    ok(len(marks) == len(n1) and "".join(m["word"] for m in marks) == n1, "mốc chữ: một mốc mỗi ký tự, chữ gốc của kịch bản",
       (len(marks), len(n1)))
    ok(marks and 0.0 <= marks[0]["start"] < 1.2 and all(b["start"] >= a["start"] for a, b in zip(marks, marks[1:])),
       "mốc chữ tính từ đầu file cảnh, tăng dần", marks[:3])
    bad = ("あいうえおかきくけこ" * 3, [0.1 * i for i in range(30)])
    try:
        ND.split_by_paragraph(full, PARAS, os.path.join(tmp, "a3"), FF, "ja", transcribe=lambda s, l: bad)
        ok(False, "bản đọc lệch kịch bản phải bị từ chối")
    except ValueError as e:
        ok("does not follow the script" in str(e), "bản đọc lệch kịch bản → ValueError", e)
    one = ND.split_by_paragraph(full, ["ひとつだけ。"], os.path.join(tmp, "a4"), FF, "ja", transcribe=lambda s, l: None)
    ok(len(one["files"]) == 1 and one["files"][0]["start"] == 0.0, "một đoạn: cả file là một cảnh")

print("── B. muse ──")
pr = M.speech_prompt(["一つ目。", "", "二つ目「こんにちは」"], "a warm male voice", "Japanese")
ok("ONE Japanese voice-over AUDIO FILE" in pr and "VOICE: a warm male voice." in pr and "一つ目。\n\n二つ目「こんにちは」" in pr
   and "1.2-1.5 seconds" in pr and "about 1 minute." in pr, "lời xin: một file, mô tả giọng, đoạn ngăn dòng trống, bỏ đoạn rỗng", pr[:300])
ok("VOICE: " + M.SPEECH_DIRECTION_DEFAULT in M.speech_prompt(["x"]), "không mô tả → giọng mặc định")
got_kw = {}


def fake_ask(prompt, **kw):
    got_kw.update(kw, prompt=prompt)
    os.makedirs(kw["audio_dir"], exist_ok=True)
    f = os.path.join(kw["audio_dir"], "muse_x_0.mp3")
    open(f, "wb").write(b"ID3fake")
    return {"ok": True, "text": "0:00", "audios": [{"path": f, "mime": "audio/mpeg", "bytes": 7}], "thread_id": "t1",
            "profile": "p1"}


_real_ask = M.ask
M.ask = fake_ask
res = M.generate_speech(["一つ目。", "二つ目。"], os.path.join(tmp, "b", "full.mp3"), "calm", "Japanese")
ok(res["path"].endswith("full.mp3") and os.path.isfile(res["path"]) and got_kw.get("thread_id") == "new"
   and got_kw.get("want_audio") is True and got_kw.get("max_audios") == 1 and got_kw.get("timeout", 0) >= 600,
   "generate_speech: chat MỚI, xin file tiếng, chuyển file về đường dẫn đích", (res, {k: v for k, v in got_kw.items() if k != "prompt"}))
M.ask = lambda prompt, **kw: {"ok": True, "text": "I can't do that.", "audios": []}
try:
    M.generate_speech(["一つ目。"], os.path.join(tmp, "b2", "full.mp3"))
    ok(False, "không có file tiếng phải ném MuseError")
except M.MuseError as e:
    ok("without an audio file" in str(e) and "can't do that" in str(e), "không có file tiếng → MuseError kèm lời Muse", e)
try:
    M.generate_speech(["", "  "], os.path.join(tmp, "b3", "full.mp3"))
    ok(False, "bài rỗng phải ném")
except M.MuseError:
    ok(True, "bài rỗng → MuseError, không gọi Muse")
M.ask = _real_ask
# ask: yêu cầu tới công cụ trình duyệt mang want_audio; chỗ ngồi từ xa bị tránh
seen_req = {}
_saved = (M.settings, M.ensure_browser, M.run_tool)
M.settings = lambda: {"profile": "p1", "pool": ["p1"], "lanes": 1, "turns_per_chat": 10,
                      "remotes": [{"base_url": "http://x/api/v1/muse", "key": "k" * 20, "seats": 3}]}
M.ensure_browser = lambda profile, launch=True: 9222


def tool(port, action, req=None, timeout=60):
    seen_req.update(req or {})
    return {"ok": True, "text": "0:00", "audios": [{"path": "x.mp3"}], "thread_id": "t9"}


M.run_tool = tool
r = M.ask("read this", thread_id="new", want_audio=True, audio_dir="D:/a", max_audios=1)
ok(seen_req.get("want_audio") is True and seen_req.get("audio_dir") == "D:/a" and seen_req.get("thread") == "new"
   and r.get("profile") == "p1", "ask: gửi want_audio/audio_dir tới công cụ, chạy ở hồ sơ máy này (không nút từ xa)",
   ({k: v for k, v in seen_req.items() if k != "prompt"}, r.get("profile")))
M.settings, M.ensure_browser, M.run_tool = _saved

print("── C. pipeline ──")
order = [s[0] for s in P.RENDER_STEPS]
ok(order.index("dub") == order.index("tts") + 1 and order.index("dub") < order.index("render"), "bước dub ngay sau tts, trước dựng", order)
ok(P.DEFAULTS.get("dub") is False and P.DEFAULTS.get("dub_voice") == "" and "dub" in P.SOFT_FAIL_STEPS
   and P._HANDLERS.get("dub") is P._step_dub, "mặc định tắt, hỏng mềm (giữ giọng mẫu), có hàm xử lý")
plan = {s["step"]: s for s in P.plan({})}
ok(plan["dub"]["enabled"] is False and P.plan({"dub": True})[[s["step"] for s in P.plan({"dub": True})].index("dub")]["enabled"],
   "kế hoạch: chỉ bật khi task bật dub")

shots = [{"id": 11, "storyboard_number": 1, "narration_text": "一つ目。", "tts_audio_url": "/api/v1/tts/audio/a.mp3"},
         {"id": 12, "storyboard_number": 2, "narration_text": "", "tts_audio_url": ""},
         {"id": 13, "storyboard_number": 3, "narration_text": "三つ目。", "tts_audio_url": "/api/v1/tts/audio/c.mp3"}]
puts, calls, meta, ckp = [], {"speech": 0, "split": 0}, {}, {}
P._storyboards = lambda ep: [dict(s) for s in shots]
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
P._task_meta = lambda tid, **kw: meta.update(kw)
P._audio_check = lambda state: None
P._checkpoint_merge = lambda state, extra: (ckp.update(extra), state.setdefault("checkpoint", {}).update(extra))
dub_dir = os.path.join(tmp, "c")


def fake_speech(paragraphs, out_path, direction="", language=""):
    calls["speech"] += 1
    calls["args"] = (list(paragraphs), direction, language)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    open(out_path, "wb").write(b"x")
    return {"path": out_path, "thread_id": "t", "profile": "p1", "bytes": 1}


def fake_split(src, paragraphs, out_dir, ffmpeg="", language="", names=None, transcribe=None, duration=None):
    calls["split"] += 1
    calls["names"] = names
    files = []
    for nm in names:
        f = os.path.join(out_dir, nm + ".mp3")
        open(f, "wb").write(b"x")
        files.append({"path": f, "start": 0, "end": 1, "seconds": 1})
    return {"files": files, "engine": "whisper", "match": 0.93, "anchors": 4}


M.generate_speech = fake_speech
ND.split_by_paragraph = fake_split
import tubecli.config as _cfg  # noqa: E402
_cfg.DATA_DIR = tmp
said = []
state = {"episode_id": 830, "task_id": "", "language": "ja", "checkpoint": {},
         "_say": lambda *a: said.append(a), "_cancelled": lambda: False}
P._step_dub(state, {"dub": True, "dub_voice": "  warm  male\nnarrator "})
ok(calls["speech"] == 1 and calls["args"] == (["一つ目。", "三つ目。"], "warm male narrator", "Japanese"),
   "Muse đọc CẢ bài một lượt: chỉ cảnh có lời, mô tả giọng gọn, tên ngôn ngữ", calls.get("args"))
ok(calls["names"] == ["shot001", "shot003"], "file cảnh đặt theo số cảnh", calls.get("names"))
ok([p for p, _ in puts] == ["/api/v1/studio/storyboards/11", "/api/v1/studio/storyboards/13"]
   and all(pl["tts_audio_url"].endswith((".mp3",)) and "ep830_dub" in pl["tts_audio_url"] for _, pl in puts),
   "thay đường giọng của từng cảnh có lời (thư mục ep<id>_dub)", puts)
ok(ckp.get("dub", {}).get("key") and len(ckp["dub"]["files"]) == 2 and meta.get("voice", {}).get("engine") == "muse",
   "nhớ checkpoint + chip giọng «muse» trên thẻ", (ckp, meta))
# Retry: checkpoint khớp → không gọi Muse, chỉ ghi lại đường giọng nếu cảnh đã bị đổi
shots[0]["tts_audio_url"] = ckp["dub"]["files"][0]
shots[2]["tts_audio_url"] = "/api/v1/tts/audio/c2.mp3"
puts.clear()
P._step_dub(state, {"dub": True, "dub_voice": "warm male narrator"})
ok(calls["speech"] == 1 and calls["split"] == 1 and [p for p, _ in puts] == ["/api/v1/studio/storyboards/13"],
   "Retry: dùng lại file đã cắt, không gọi Muse lại, chỉ sửa cảnh lệch", (calls, puts))
P._step_dub(state, {"dub": True, "dub_voice": "a different voice"})
ok(calls["speech"] == 2, "đổi mô tả giọng → đọc lại")
P._storyboards = lambda ep: [{"id": 1, "storyboard_number": 1, "narration_text": " "}]
said.clear()
P._step_dub(state, {"dub": True})
ok(calls["speech"] == 2 and any("no narration" in str(a) for a in said), "không cảnh nào có lời → bỏ qua, không gọi Muse")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
