# -*- coding: utf-8 -*-
"""Lời thoại của storyboard phải LÀ kịch bản: đúng ngôn ngữ, đủ cảnh, không nhãn "VO:".

Ca thật 13/9/2026, tập 337: kịch bản Tây Ban Nha 71 cảnh → Content Studio trả 69 shot
TIẾNG ANH, mở đầu "VO: …", bỏ cảnh 35–36; thẻ bước vẫn "69 shots · covers 100%" vì độ
phủ chỉ đếm SỐ CHỮ. Video 21 phút đọc tiếng Anh bằng giọng Tây Ban Nha.

Canh ở đây, đối chiếu code thật trong extensions/content_video/pipeline.py:
  A. _shot_narration / strip_shot_labels — bỏ nhãn người nói ở đầu lời, không cắt nhầm
  B. _token_counts / align_shots_to_scenes — chữ Hán/Thái theo cặp ký tự; lời bị DỊCH
     vẫn gióng được theo vị trí, đơn điệu, phủ hết cảnh
  C. scene_coverage / storyboard_coverage / missing_scenes / foreign_shots — đo theo NỘI DUNG
  D. _step_studio — dịch → chép lại kịch bản; bỏ cảnh → chép lại; chỉ nhãn → chỉ bỏ nhãn;
     tốt → không đụng; thẻ kết quả nói rõ
  E. _step_script — bản nháp sai ngôn ngữ → hỏi lại một lần (một lượt và theo đợt); vẫn
     sai → cảnh báo; bài dán Tây Ban Nha KHÔNG còn bị bảo "translate into Spanish"

Run:  python tests/content_video_narration_guard_test.py     (exit 0 = pass)
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
        print("  FAIL", label, "—", str(detail)[:400])


ES = ["Hay una pregunta que puede revelar hacia dónde va realmente tu vida.",
      "No es cuánto dinero ganas, ni qué puesto tienes, ni cuántas personas te conocen.",
      "Lo que pones en primer lugar termina ordenando todo lo demás en tu casa y en tu trabajo.",
      "Por eso las prioridades importan tanto, y por eso hoy quiero hablarte de orden y de dirección."]
EN = ["There is a question that can reveal where your life is really going.",
      "It is not how much money you make, what position you hold, or how many people know you.",
      "What you put first ends up ordering everything else in your home and in your work.",
      "That is why priorities matter so much, and why today I want to talk to you about order and direction."]


def es_narr(n):
    return f"En la escena {n} hablamos del tema{n} con calma. {ES[n % 4]} Recuerda bien el tema{n}."


def en_narr(n):
    return f"In scene {n} we talk about topic{n} calmly. {EN[n % 4]} Remember topic{n} well."


N = 71
SCRIPT = "\n\n".join(f"[SHOW: escena {n} en la ciudad]\n{es_narr(n)}" for n in range(1, N + 1))
SCENES = [sc for sc in P.scenes_of(SCRIPT) if sc[1]]
assert len(SCENES) == N and len(SCRIPT.split()) >= P.STORYBOARD_COVERAGE_MIN_WORDS


def shot(i, text, **extra):
    d = {"id": 1000 + i, "storyboard_number": i, "title": f"Shot {i}", "image_prompt": f"stick figure {i}",
         "narration_text": text}
    d.update(extra)
    return d


# ── A. nhãn người nói ────────────────────────────────────────────────────────
print("── A. nhãn người nói ở đầu lời ──────────────────────────────")
S = P._shot_narration
ok(S({"narration_text": "VO: There is a question."}) == "There is a question.", "VO: bị bỏ", S({"narration_text": "VO: There is a question."}))
ok(S({"narration_text": "V.O. — Hay una pregunta."}) == "Hay una pregunta.", "V.O. — bị bỏ")
ok(S({"narration_text": "(VO) Hay una pregunta."}) == "Hay una pregunta.", "(VO) trong ngoặc bị bỏ")
ok(S({"narration_text": "Narrator (warm, slow): Hay una pregunta."}) == "Hay una pregunta.", "Narrator (ghi chú): bị bỏ")
ok(S({"narration_text": "Người dẫn chuyện: Có một câu hỏi."}) == "Có một câu hỏi.", "Người dẫn chuyện: bị bỏ")
ok(S({"narration_text": "Voz en off: Hay una pregunta."}) == "Hay una pregunta.", "Voz en off: bị bỏ")
ok(S({"narration_text": "[fade in] VO: Hay una pregunta."}) == "Hay una pregunta.", "[cue] rồi VO: đều bỏ")
ok(S({"narration_text": "Os dias passam depressa."}) == "Os dias passam depressa.", "'Os dias' (Bồ) KHÔNG bị cắt")
ok(S({"narration_text": "Volver a casa es lo primero."}) == "Volver a casa es lo primero.", "'Vo…' đầu chữ thường không bị cắt")
ok(S({"narration_text": "Nota: la voz en off llega después."}) == "Nota: la voz en off llega después.", "nhãn ở giữa câu để nguyên")
labelled = P.strip_shot_labels([shot(1, "VO: uno"), shot(2, "dos"), shot(3, "  Narrator: tres"), shot(4, "")])
ok(labelled == [(1001, "uno"), (1003, "tres")], "strip_shot_labels: chỉ shot có nhãn, id + lời sạch", labelled)

# ── B. chữ CJK + gióng theo vị trí ───────────────────────────────────────────
print("── B. chữ Hán theo cặp ký tự · gióng lời bị dịch ────────────")
tc = P._token_counts("這是一個關於時間的故事。時間很重要。")
ok(tc.get("時間") == 2 and "關於" in tc and "是一" in tc, "chữ Hán: cặp ký tự liền nhau, đếm số lần", tc)
ok(P._tokens("นี่คือสคริปต์") and P._tokens("hello world there") == {"hello", "world", "there"}, "Thái theo cặp; Latinh theo từ ≥3")
TOPICS = ["時間", "金錢", "關係", "注意力", "決定", "工作", "家庭", "健康", "學習", "朋友", "信心", "平安"]
ZH = "\n\n".join(f"[SHOW: 場景{i}]\n在這個場景裡我們談到{t}。你把{t}放在第一位，它就會安排其餘的一切，這是很重要的道理。" for i, t in enumerate(TOPICS, 1))
zh_scenes = [sc for sc in P.scenes_of(ZH) if sc[1]]
zh_shots = [shot(i, narr) for i, (_, narr) in enumerate(zh_scenes, 1)]
ok(P.align_shots_to_scenes(zh_shots, zh_scenes) == list(range(12)), "kịch bản Trung chép đúng gióng 1-1 (bệnh cũ: 0 chữ trùng)",
   P.align_shots_to_scenes(zh_shots, zh_scenes))
ok(P.storyboard_coverage(zh_shots, ZH) > 0.9 and P.foreign_shots(zh_shots, "zh-TW") == [], "…độ phủ ~1, zh-TW không bị coi là lạ",
   P.storyboard_coverage(zh_shots, ZH))
zh_en = [shot(i, en_narr(i)) for i in range(1, 13)]
ok(len(P.foreign_shots(zh_en, "zh-TW")) == 12 and P.storyboard_coverage(zh_en, ZH) < 0.1, "shot tiếng Anh cho kịch bản Trung → lạ, phủ ~0")

EN_SHOTS = [shot(k, "VO: " + en_narr(n)) for k, n in enumerate([n for n in range(1, N + 1) if n not in (35, 36)], 1)]
owner = P.align_shots_to_scenes(EN_SHOTS, SCENES)
ok(owner == sorted(owner) and owner[0] == 0 and owner[-1] == N - 1, "lời bị DỊCH: gióng đơn điệu, từ cảnh đầu tới cảnh cuối", (owner[0], owner[-1]))
ok(len(set(owner)) >= 60, "…trải đều theo vị trí (không dồn hết vào cảnh 0)", len(set(owner)))
ok(not P.storyboard_stopped_early(EN_SHOTS, SCENES), "…KHÔNG bị coi là 'dừng sớm' (bệnh: gọi Studio làm tiếp → thêm shot)")

# ── C. độ phủ theo nội dung ──────────────────────────────────────────────────
print("── C. độ phủ theo NỘI DUNG từng cảnh ───────────────────────")
GOOD = [shot(n, es_narr(n)) for n in range(1, N + 1)]
ok(P.storyboard_coverage(GOOD, SCRIPT) > 0.95 and P.missing_scenes(GOOD, SCRIPT) == [] and P.foreign_shots(GOOD, "es") == [],
   "chép đúng: phủ ~1, không cảnh thiếu, không shot lạ", P.storyboard_coverage(GOOD, SCRIPT))
ok(P.storyboard_coverage(EN_SHOTS, SCRIPT) < 0.1, "DỊCH sang tiếng Anh: phủ ~0 (bệnh cũ: 100% vì cùng số chữ)", P.storyboard_coverage(EN_SHOTS, SCRIPT))
fo = P.foreign_shots(EN_SHOTS, "es")
ok(len(fo) == 69 and all(code == "en" for _, code in fo), "…69/69 shot bị nhận là tiếng Anh", (len(fo), fo[:2]))
DROP = [shot(k, es_narr(n)) for k, n in enumerate([n for n in range(1, N + 1) if n not in (35, 36)], 1)]
ok(P.missing_scenes(DROP, SCRIPT) == [34, 35], "bỏ cảnh 35–36 giữa chừng → đúng hai cảnh ấy bị nêu", P.missing_scenes(DROP, SCRIPT))
ok(P.storyboard_coverage(DROP, SCRIPT) > 0.9, "…độ phủ chung vẫn cao (2/71) — nên phải nhìn từng cảnh", P.storyboard_coverage(DROP, SCRIPT))
FOLD = [shot(n, es_narr(n) + (" " + es_narr(11) if n == 10 else "")) for n in range(1, N + 1) if n != 11]
ok(P.missing_scenes(FOLD, SCRIPT) == [] and P.storyboard_coverage(FOLD, SCRIPT) > 0.95,
   "một shot gánh hai cảnh liền (11 dồn vào 10) → không bị nêu là thiếu", P.missing_scenes(FOLD, SCRIPT))
MIX = [shot(n, en_narr(n) if n in (5, 6, 7) else es_narr(n)) for n in range(1, N + 1)]
ok([sid for sid, _ in P.foreign_shots(MIX, "es")] == [1005, 1006, 1007], "3 shot tiếng Anh giữa 68 shot Tây Ban Nha → đúng 3 shot đó")
ok(P.foreign_shots([shot(1, "Reino primero. Carácter primero. Verdad primero.")], "es") == [], "shot ngắn / toàn tên → không kết tội")
ok(P.foreign_shots(GOOD, "") == [], "không biết ngôn ngữ kịch bản → không kết tội")

# ── D. _step_studio ──────────────────────────────────────────────────────────
print("── D. _step_studio ──────────────────────────────────────────")


class A:
    name, id, model = "MC", "a1", "x"


def run_studio(start, language="es"):
    store = {"shots": [dict(s) for s in start]}
    puts, streams = [], []

    def fake_sb(ep_id):
        for sh in store["shots"]:
            for path, payload in puts:
                if path.endswith(f"/{sh['id']}"):
                    sh.update(payload)
        return [dict(s) for s in store["shots"]]

    P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
    P._storyboards = fake_sb
    P._stream_storyboard = lambda ep_id, st, append=False: streams.append((ep_id, append))
    P._template_style = lambda state: "Stick figure."
    said = []
    st = {"agent": A(), "checkpoint": {"drama_id": 9, "episode_id": 9}, "script": SCRIPT, "language": language,
          "_say": lambda *a: said.append(a), "_cancelled": lambda: False, "warnings": []}
    P._step_studio(st, {})
    return st, puts, streams, said, fake_sb(9)


st, puts, streams, said, final = run_studio(EN_SHOTS)
ok(st.get("storyboard_labels") == 69 and st.get("storyboard_foreign") == [69, "English"] and st.get("storyboard_restored") == 69,
   "tập 337: 69 nhãn VO bỏ, 69 shot tiếng Anh, chép lại 69 lời", (st.get("storyboard_labels"), st.get("storyboard_foreign"), st.get("storyboard_restored")))
ok(len(puts) == 138 and all(p["tts_audio_url"] == "" for _, p in puts), "138 lần PUT (bỏ nhãn + chép lại), tiếng cũ xoá", len(puts))
ok(sum(1 for a in said if "shot(s)" in str(a) and "/" in str(a)) >= 4,
   "69 nhãn + 69 lời: cả hai vòng lặp đều báo tiến độ", [a for a in said if "/" in str(a)][:2])
ok(all("tema" in s["narration_text"] and "VO:" not in s["narration_text"] for s in final), "mọi shot cuối cùng là lời Tây Ban Nha, không 'VO:'")
joined = " ".join(s["narration_text"] for s in final)
ok(all(f"tema{n}" in joined for n in range(1, N + 1)), "đủ 71 cảnh, kể cả 35–36 bị bỏ")
ok(st["storyboard_coverage"] > 0.95 and streams == [] and st["shot_count"] == 69 and not st["warnings"],
   "phủ ~1 sau khi chép, KHÔNG gọi Studio làm tiếp, không cảnh báo", (st["storyboard_coverage"], streams, st["warnings"]))
ok(any("69/69 shots came back in English instead of Spanish" in str(a) for a in said), "thẻ bước nói vì sao", said[-4:])
out = P._render_result(st, {}, [], [], 1.0)
ok("69 shot(s) came back in English — replaced with the script" in out and "speaker labels removed from 69 shot(s)" in out,
   "thẻ kết quả nói rõ", [l for l in out.splitlines() if "Storyboard" in l])

st, puts, streams, said, final = run_studio(DROP)
ok(st.get("storyboard_missing") == [35, 36] and 0 < st.get("storyboard_restored", 0) <= 69 and "storyboard_foreign" not in st,
   "bỏ cảnh 35–36: nêu đúng cảnh, chép lại, không nói 'lạ'", (st.get("storyboard_missing"), st.get("storyboard_restored")))
ok(st["storyboard_restored"] < 69, "…shot trước chỗ mất vốn đã đúng thì không chép lại", st["storyboard_restored"])
ok(not any("restoring the narration of" in str(a) for a in said),
   f"…dưới {P.PUT_SAY_EVERY} shot thì không báo tiến độ cho rối mắt", st["storyboard_restored"])
ok(all(f"tema{n}" in " ".join(s["narration_text"] for s in final) for n in (35, 36)) and st["storyboard_coverage"] > 0.95,
   "…cảnh 35–36 quay lại lời, phủ ~1")
ok("scene(s) 35, 36 were skipped — put back" in P._render_result(st, {}, [], [], 1.0), "…thẻ kết quả nêu cảnh")

st, puts, streams, said, final = run_studio([shot(n, "VO: " + es_narr(n)) for n in range(1, N + 1)])
ok(st.get("storyboard_labels") == 71 and "storyboard_restored" not in st and len(puts) == 71,
   "chỉ nhãn VO: → chỉ bỏ nhãn (71 PUT), không chép lại", (st.get("storyboard_labels"), st.get("storyboard_restored"), len(puts)))
ok(all(s["narration_text"] == es_narr(i) for i, s in enumerate(final, 1)) and st["storyboard_coverage"] > 0.95, "…lời sạch, phủ ~1")

st, puts, streams, said, final = run_studio(GOOD)
ok(puts == [] and streams == [] and st["storyboard_coverage"] > 0.95 and not any(k.startswith("storyboard_") and k != "storyboard_coverage" for k in st),
   "storyboard tốt → không đụng gì", [k for k in st if k.startswith("storyboard_")])

st, puts, streams, said, final = run_studio(MIX)
ok(st.get("storyboard_foreign") == [3, "English"] and st.get("storyboard_restored") == 3 and st["storyboard_coverage"] > 0.95,
   "3 shot tiếng Anh lẫn trong 71 → CHỈ chép lại 3 shot ấy, phủ ~1", (st.get("storyboard_foreign"), st.get("storyboard_restored")))
ok(len(puts) == 3 and all(p["tts_audio_url"] == "" for _, p in puts),
   "…68 shot vốn đúng KHÔNG bị đụng (không mất tiếng đã đọc)", len(puts))
ok(any("restoring the narration of" in str(a) for a in said) is False,
   "…ít shot thì không cần báo tiến độ", [a for a in said if "restoring" in str(a)][:2])

st, puts, streams, said, final = run_studio(EN_SHOTS, language="")
ok(st.get("storyboard_foreign") == [69, "English"], "không có ngôn ngữ trong state → dò từ chính kịch bản (es) rồi vẫn bắt được")

# ── E. _step_script: sai ngôn ngữ thì hỏi lại ────────────────────────────────
print("── E. _step_script hỏi lại khi bản nháp sai ngôn ngữ ────────")
import tubecli.core.brain as B  # noqa: E402


class Agent:
    id, name, language, model = "a1", "MC", "auto", "x"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "model": self.model}


def es_script(n_scenes, start=1):
    return "TITLE: La pregunta\n\n" + "\n\n".join(f"[SHOW: escena {n}]\n{es_narr(n)} {ES[(n + 1) % 4]} {ES[(n + 2) % 4]}"
                                                  for n in range(start, start + n_scenes))


def en_script(n_scenes, start=1):
    return "TITLE: The question\n\n" + "\n\n".join(f"[SHOW: scene {n}]\n{en_narr(n)} {EN[(n + 1) % 4]} {EN[(n + 2) % 4]}"
                                                   for n in range(start, start + n_scenes))


PASTED = " ".join(es_narr(n) for n in range(1, 9))
calls = []
answers = []


def fake_llm(agent, messages, temperature=0.7):
    calls.append((messages[0]["content"], messages[-1]["content"]))
    return answers.pop(0)


B.AgentBrain._call_llm = staticmethod(fake_llm)
P._write_checkpoint = lambda *a, **k: None
P._read_checkpoint = lambda tid: {}
P._checkpoint_sources = lambda state: []


def run_script(target_words):
    calls.clear()
    st = {"agent": Agent(), "corpus": [{"title": "", "url": "", "content": PASTED, "source": "pasted"}],
          "preset": {"name": "ink", "fields": {"language": "es"}}, "task_id": "", "checkpoint": {},
          "_say": lambda *a: None, "_cancelled": lambda: False, "warnings": [], "feedback": []}
    P._step_script(st, {"source_text": PASTED, "target_words": target_words})
    return st


# Mục tiêu ~280 chữ ≈ độ dài bản nháp 5 cảnh giả (~300 chữ lời): nhóm này kiểm HỎI LẠI NGÔN NGỮ; mục tiêu
# 120 thì bản nháp dài gấp 2,4 lần và lượt «rút gọn» (lõi .96, 15/9/2026) chen vào đếm lượt gọi.
answers[:] = [en_script(5), es_script(5)]
st = run_script(280)
ok(len(calls) == 2 and "IMPORTANT: the previous draft came back in English" in calls[1][0]
   and "Write in Spanish." in calls[1][0], "một lượt: nháp tiếng Anh → hỏi lại MỘT lần với câu nhắc thẳng", [c[0][-200:] for c in calls])
ok("pregunta" in st["script"] and not any("came back in" in w for w in st["warnings"]), "…bản hai tiếng Tây Ban Nha được dùng, không cảnh báo", st["warnings"])
ok("translate and adapt" not in calls[0][0], "bài dán Tây Ban Nha + mẫu Tây Ban Nha → KHÔNG còn bị bảo 'translate into Spanish' (bệnh 336)", calls[0][0])
answers[:] = [en_script(5), en_script(5)]
st = run_script(280)
ok(len(calls) == 2 and any("came back in English although Spanish was asked" in w for w in st["warnings"]),
   "vẫn sai sau khi hỏi lại → chỉ một lần hỏi lại + cảnh báo rõ", (len(calls), st["warnings"]))
answers[:] = [es_script(5)]
st = run_script(280)
ok(len(calls) == 1 and not st["warnings"], "đúng ngôn ngữ ngay → một lượt, không cảnh báo", st["warnings"])


def chunked_llm(agent, messages, temperature=0.7):
    sys_p, user_p = messages[0]["content"], messages[-1]["content"]
    calls.append((sys_p, user_p))
    if "Plan a" in user_p:
        return "TITLE: La pregunta\n" + "\n".join(f"[SHOW: escena {n}] — idea {n}" for n in range(1, 26))
    import re
    m = re.search(r"scenes (\d+)-(\d+) ONLY", user_p)
    a, b = int(m.group(1)), int(m.group(2))
    if a == 1 and "came back in" not in sys_p:
        return en_script(b - a + 1, a).split("\n\n", 1)[1]        # đợt 1 lần đầu: tiếng Anh
    return es_script(b - a + 1, a).split("\n\n", 1)[1]


B.AgentBrain._call_llm = staticmethod(chunked_llm)
st = run_script(1500)
retried = [u for s, u in calls if "IMPORTANT: the previous draft came back in English" in s]
ok(len(retried) == 1 and "scenes 1-6 ONLY" in retried[0] and len(calls) == 1 + 5 + 1,
   "theo đợt: đợt 1 tiếng Anh → hỏi lại đúng đợt ấy; các đợt khác một lượt", (len(retried), len(calls)))
ok("topic" not in st["script"] and st["script"].count("[SHOW:") >= 25 and not any("came back in" in w for w in st["warnings"]),
   "…kịch bản cuối toàn Tây Ban Nha, đủ cảnh, không cảnh báo", st["warnings"])

# ── F. báo động sai: lời ĐỦ CHỮ, chỉ khác chỗ cắt nhịp ───────────────────────
# Tập 454 (20/9/2026): 203 nhịp ghép lại đúng bằng kịch bản TBN, mà foreign_shots gắn cờ 3 nhịp là
# pt/fr (cả ba là tiếng TBN thuần — nhịp ngắn thì bộ dò đoán sai). Guard chép lại 191 nhịp, xoá
# tts_audio_url, nên lượt dựng sau phải làm lại 50 phút — và lượt Retry nào cũng vậy.
print("── F. lời đủ chữ thì đừng chép lại ──────────────────────────")

# Cắt mỗi cảnh thành HAI nhịp ở ranh giới câu (kiểu scene_plan.split_beats). Cùng chữ, khác chỗ cắt:
# restore_narration chia đều theo ký tự nên sẽ thấy «khác» ở gần hết các nhịp.
NHIP = []
for n in range(1, N + 1):
    head, _, tail = es_narr(n).partition(". ")
    NHIP.append(shot(len(NHIP) + 1, head + "."))
    NHIP.append(shot(len(NHIP) + 1, tail))
ok(len(NHIP) == 2 * N and P.narration_is_faithful(NHIP, SCRIPT),
   "nhịp ngắn ghép lại ĐÚNG BẰNG kịch bản (chỉ khác chỗ cắt)", len(NHIP))
ok(len(P._narration_differs(NHIP, P.restore_narration(NHIP, SCRIPT))) > N,
   "…mà phép so từng shot vẫn báo «khác» ở phần lớn các nhịp — đây là cái bẫy",
   len(P._narration_differs(NHIP, P.restore_narration(NHIP, SCRIPT))))

_real_foreign = P.foreign_shots
P.foreign_shots = lambda shots, lang: [(shots[4]["id"], "pt"), (shots[9]["id"], "fr")]
try:
    st, puts, streams, said, final = run_studio(NHIP)
finally:
    P.foreign_shots = _real_foreign
ok(puts == [], "bộ dò báo ngoại ngữ SAI → không PUT một lời nào, giọng đã thu còn nguyên", puts[:3])
ok("storyboard_restored" not in st and "storyboard_foreign" not in st,
   "…không ghi vào báo cáo là đã chép lại", (st.get("storyboard_restored"), st.get("storyboard_foreign")))
ok(any("already matches the script word for word" in str(a) for a in said),
   "…thẻ bước NÓI RA là đã bỏ qua, không im lặng", said[-3:])
ok(st["shot_count"] == 2 * N and not st["warnings"], "…đi tiếp với đúng số nhịp, không cảnh báo",
   (st.get("shot_count"), st["warnings"]))

# Mất chữ thật thì guard PHẢI chạy như cũ.
THIEU = [dict(x) for x in NHIP]
THIEU[8]["narration_text"] = ""
ok(not P.narration_is_faithful(THIEU, SCRIPT), "mất lời một nhịp → không còn coi là đủ chữ")
P.foreign_shots = lambda shots, lang: [(shots[4]["id"], "pt")]
try:
    st2, puts2, _s2, _sd2, _f2 = run_studio(THIEU)
finally:
    P.foreign_shots = _real_foreign
ok(len(puts2) > 0 and st2.get("storyboard_restored", 0) > 0,
   "…lúc ấy vẫn chép lại kịch bản như trước (chốt mới không làm mất lưới an toàn)",
   (len(puts2), st2.get("storyboard_restored")))

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
