# -*- coding: utf-8 -*-
"""Storyboard ra VỎ RỖNG → pipeline lấp bằng đúng những cảnh bị rơi (11/9/2026).

Bệnh: một đợt storyboard (6 cảnh) ra khuôn lạ, Studio lưu thành 6 shot không lời,
không prompt — tập 308 mất #37–#42, máy PC của user "26/26 ảnh · 6 shot không có
lời" — video thiếu ~3 phút mà thẻ vẫn xanh vì độ phủ 69–88% còn trên ngưỡng 60%.
Cam kết được canh ở đây:
  1. Vỏ k nhận ĐÚNG lời của cảnh bị rơi nằm giữa hai shot thật kẹp quanh nó.
  2. Prompt ảnh = phong cách mẫu + dòng [SHOW] của cảnh — không phải lời thoại.
  3. Cảnh thừa dồn vào vỏ cuối nhóm; vỏ thừa để nguyên và có cảnh báo.
  4. _step_studio lấp TRƯỚC khi đo độ phủ, thẻ kết quả nói đã lấp.
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
        print("  FAIL", label, "—", detail)


def mk_script(n):
    return "\n\n".join(f"[SHOW: frame {i} of topic{i}]\nTopic{i} sentence one here. "
                       + " ".join([f"topic{i}word"] * 20) + f". Topic{i} ends." for i in range(n))


SCRIPT = mk_script(12)
SCENES = [sc for sc in P.scenes_of(SCRIPT) if sc[1]]
STYLE = "Simple 2D stick figure."


def real(i, num):
    return {"id": 100 + num, "storyboard_number": num, "image_prompt": f"img {i}",
            "narration_text": f"Topic{i} sentence one here. " + " ".join([f"topic{i}word"] * 20)}


def shell(num):
    return {"id": 100 + num, "storyboard_number": num, "narration_text": "", "image_prompt": "",
            "scene_id": "scene_0x"}


print("── fill_empty_shots ──────────────────────────────────────────")
shots = [real(0, 1), real(1, 2), real(2, 3)] + [shell(n) for n in range(4, 10)] + \
        [real(9, 10), real(10, 11), real(11, 12)]
fixed = P.fill_empty_shots(shots, SCRIPT, STYLE)
ok([sid for sid, _ in fixed] == [104, 105, 106, 107, 108, 109], "6 vỏ (tập 308) đều được lấp, đúng thứ tự",
   [sid for sid, _ in fixed])
ok([p["narration_text"] for _, p in fixed] == [SCENES[k][1] for k in range(3, 9)],
   "vỏ nhận ĐÚNG lời của 6 cảnh bị rơi (3..8), nguyên văn")
ok(fixed and fixed[0][1]["image_prompt"] == "Simple 2D stick figure. frame 3 of topic3",
   "prompt ảnh = phong cách mẫu + dòng [SHOW] của chính cảnh", fixed[0][1] if fixed else None)
ok(all("sentence" not in p["image_prompt"] for _, p in fixed), "KHÔNG lấy lời thoại làm prompt (Flux sẽ vẽ chữ)")
ok(all(p["tts_audio_url"] == "" and p["title"].startswith("frame") for _, p in fixed), "xoá tiếng cũ, có tiêu đề")

# 3 vỏ cho 6 cảnh bị rơi: hai vỏ đầu một cảnh, vỏ cuối gánh phần còn lại
shots2 = [real(0, 1), real(1, 2), real(2, 3)] + [shell(n) for n in (4, 5, 6)] + \
         [real(9, 7), real(10, 8), real(11, 9)]
fixed2 = P.fill_empty_shots(shots2, SCRIPT, STYLE)
ok(len(fixed2) == 3 and fixed2[0][1]["narration_text"] == SCENES[3][1]
   and fixed2[2][1]["narration_text"] == " ".join(SCENES[k][1] for k in (5, 6, 7, 8)),
   "ít vỏ hơn cảnh: không mất chữ nào — cảnh thừa dồn vào vỏ cuối nhóm", [p["narration_text"][:12] for _, p in fixed2])

# 6 vỏ cho 3 cảnh bị rơi: 3 vỏ lấp, 3 vỏ để nguyên
shots3 = [real(0, 1), real(1, 2), real(2, 3)] + [shell(n) for n in range(4, 10)] + \
         [real(k, 10 + k - 6) for k in range(6, 12)]
fixed3 = P.fill_empty_shots(shots3, SCRIPT, STYLE)
ok([p["narration_text"] for _, p in fixed3] == [SCENES[k][1] for k in (3, 4, 5)], "nhiều vỏ hơn cảnh: lấp đủ cảnh, vỏ thừa để nguyên")
ok(P.fill_empty_shots([real(i, i + 1) for i in range(12)], SCRIPT, STYLE) == [], "không vỏ nào → không làm gì")
fixed4 = P.fill_empty_shots([shell(n) for n in (1, 2, 3)], SCRIPT, "")
ok(len(fixed4) == 3 and fixed4[2][1]["narration_text"].startswith(SCENES[2][1])
   and fixed4[0][1]["image_prompt"] == "frame 0 of topic0", "toàn vỏ: chia cả kịch bản; không có phong cách thì chỉ dòng [SHOW]")

print("── shot CÓ prompt ảnh mà mất LỜI (tập 330, 11/9/2026) ────────")


def mute(num, with_img=False):
    d = {"id": 100 + num, "storyboard_number": num, "narration_text": "",
         "image_prompt": f"model prompt {num}", "scene_id": f"scene_00{num}", "angle": "Medium Shot"}
    if with_img:
        d["composed_image"] = f"C:/x/ep330_shot{num:03d}.jpg"
    return d


MUTED = [real(0, 1), real(1, 2), real(2, 3)] + [mute(n) for n in range(4, 10)] + \
        [real(9, 10), real(10, 11), real(11, 12)]
fixed5 = P.fill_empty_shots(MUTED, SCRIPT, STYLE)
ok([sid for sid, _ in fixed5] == [104, 105, 106, 107, 108, 109]
   and [p["narration_text"] for _, p in fixed5] == [SCENES[k][1] for k in range(3, 9)],
   "6 shot có prompt mà mất lời: nhận ĐÚNG lời 6 cảnh bị rơi (bệnh cũ: bỏ qua vì 'có prompt')",
   [sid for sid, _ in fixed5])
ok(all(set(p) == {"narration_text", "tts_audio_url"} for _, p in fixed5),
   "giữ nguyên prompt ảnh của model — chỉ nhận lời", [sorted(p) for _, p in fixed5][:1])
fixed6 = P.fill_empty_shots([dict(s, **({"composed_image": "x.jpg"} if not s["narration_text"] else {}))
                             for s in MUTED], SCRIPT, STYLE)
ok(len(fixed6) == 6 and all("image_prompt" not in p for _, p in fixed6),
   "Retry sau khi đã vẽ ảnh: vẫn lấp lời, không đụng tới ảnh", len(fixed6))
ok(P.fill_empty_shots([real(i, i + 1) for i in range(12)] + [mute(13, True)], SCRIPT, STYLE) == [],
   "shot không lời mà KHÔNG có cảnh nào bị rơi quanh nó (ảnh tự tải lên) → để nguyên")

print("── _step_studio ──────────────────────────────────────────────")


class A:
    name, id, model = "MC", "a1", "x"


def run_studio(start):
    store = {"shots": [dict(s) for s in start]}
    puts = []

    def fake_sb(ep_id):
        for sh in store["shots"]:
            for path, payload in puts:
                if path.endswith(f"/{sh['id']}"):
                    sh.update(payload)
        return [dict(s) for s in store["shots"]]

    P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
    P._storyboards = fake_sb
    P._stream_storyboard = lambda *a, **k: None
    P._template_style = lambda state: STYLE
    said = []
    st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": SCRIPT,
          "_say": lambda *a: said.append(a), "_cancelled": lambda: False, "warnings": []}
    P._step_studio(st, {})
    return st, puts, said


st, puts, said = run_studio(shots)
ok(st.get("storyboard_filled") == 6 and len(puts) == 6, "6 vỏ lấp qua 6 lần PUT", (st.get("storyboard_filled"), len(puts)))
ok(not st["warnings"], "lấp đủ → không cảnh báo", st["warnings"])
ok(st.get("storyboard_coverage", 0) > 0.9, "độ phủ đo SAU khi lấp (bệnh cũ: 69–88% mà không ai cứu)", st.get("storyboard_coverage"))
ok(any("filled 6 from the script" in str(a) for a in said), "thẻ bước nói đã lấp", said)
out = P._render_result(st, {}, [], [], 1.0)
ok("6 shot(s) without narration filled from the script" in out, "thẻ kết quả nói đã lấp",
   [l for l in out.splitlines() if "Storyboard" in l])

st, puts, said = run_studio([real(i, i + 1) for i in range(12)] + [shell(13), shell(14)])
ok(st.get("storyboard_filled") is None
   and any("2 storyboard shot(s) came back without narration" in w for w in st["warnings"]),
   "vỏ không khớp cảnh nào → để nguyên và CẢNH BÁO (không im lặng)", st["warnings"])

st, puts, said = run_studio(MUTED)
ok(st.get("storyboard_filled") == 6 and st.get("storyboard_coverage", 0) > 0.9 and not st["warnings"],
   "_step_studio: 6 shot có prompt mà mất lời được lấp, độ phủ đo SAU khi lấp",
   (st.get("storyboard_filled"), st.get("storyboard_coverage"), st["warnings"]))
ok(all(set(p) == {"narration_text", "tts_audio_url"} for _, p in puts), "…PUT chỉ gửi lời, không đè prompt ảnh",
   [sorted(p) for _, p in puts][:1])

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
