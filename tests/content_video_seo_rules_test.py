# -*- coding: utf-8 -*-
"""QUY TẮC TIÊU ĐỀ / MÔ TẢ RIÊNG TỪNG MẪU + TỪ CẤM (30/10/2026) — pipeline chạy lại đã đăng thêm video «leyes»; user muốn chặn
ở khâu viết tiêu đề / khi duyệt và cho mỗi mẫu tự khai cách đặt tiêu đề, mô tả.

  A. _fold / _banned_hits: không phân biệt hoa thường + dấu, nguyên từ («ley» không dính «leyenda»), chữ Nhật so chuỗi con
  B. _banned_words: tách phẩy / chấm phẩy / xuống dòng, không trùng
  C. _seo_for: prompt mang quy tắc của mẫu; mẫu không khai ⇒ prompt và kết quả như cũ
  D. tiêu đề dính từ cấm ⇒ viết lại; vẫn dính ⇒ RuntimeError, KHÔNG có tiêu đề nào để đăng
  E. tag, hashtag, chương, câu trong mô tả có từ cấm bị bỏ bằng mã
  F. tiêu đề người gọi tự gõ ⇒ giữ + cảnh báo; có khung riêng ⇒ không ghép « | từ khoá»
  G. tiêu đề tạm (bước kịch bản): sửa một lần, vẫn dính ⇒ cảnh báo ở phần duyệt

Không gọi mạng: AgentBrain._call_llm và _preset_meta đều giả lập.

Run:  python tests/content_video_seo_rules_test.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.core import brain as B  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:500])


print("A. so từ")
W = ["leyes", "ley"]
ok(P._banned_hits("Las 6 LEYES mentales del Salmo 1", W) == ["leyes"], "hoa thường", P._banned_hits("Las 6 LEYES mentales", W))
ok(P._banned_hits("La leyenda del rey", W) == [], "nguyên từ: leyenda không dính ley")
ok(P._banned_hits("Secreto de JESÚS", ["jesus"]) == ["jesus"] and P._banned_hits("Secreto de Jesus", ["Jesús"]) == ["Jesús"],
   "bỏ dấu hai chiều")
ok(P._banned_hits("この法則で人生が変わる", ["法則"]) == ["法則"], "chữ Nhật không dấu cách ⇒ so chuỗi con")
ok(P._fold("が") != P._fold("か"), "không bỏ dakuten của kana", (P._fold("が"), P._fold("か")))
ok(P._banned_hits("leyes  mentales", ["Leyes mentales"]) == ["Leyes mentales"], "cụm từ, gộp khoảng trắng")
ok(P._banned_hits("", W) == [] and P._banned_hits("leyes", []) == [], "rỗng")

print("B. tách danh sách")
ok(P._banned_words("leyes, ley; Secreto\nLEYES,,  ") == ["leyes", "ley", "Secreto"], "tách + không trùng", P._banned_words("leyes, ley; Secreto\nLEYES,,  "))
ok(P._banned_words("") == [] and P._banned_words(None) == [], "rỗng")

print("C. prompt theo mẫu")
LLM = []
ANSWERS = []
DESC = ("Vencer la ansiedad con la Biblia, verso a verso, para quien hoy se siente sin fuerzas y busca paz.\n"
        "Una guía sencilla para volver a respirar con fe en medio de los días difíciles, paso a paso, sin prisa alguna.\n"
        "Las 6 leyes mentales que nadie te contó. Una oración final para terminar el día.\n\n#biblia #LeyesDeVida #fe")


def answer(title="Vencer la ansiedad: tres versos para volver a respirar hoy", desc=DESC, tags=None, chapters=None, keyword="vencer la ansiedad"):
    return json.dumps({"keyword": keyword, "title": title, "description": desc,
                       "tags": ["vencer la ansiedad", "biblia", "leyes mentales", "fe", "oracion", "paz"] if tags is None else tags,
                       "chapters": chapters or []})


def fake_llm(agent, messages, temperature=0.6):
    LLM.append(messages[1]["content"])
    return ANSWERS.pop(0) if ANSWERS else answer()


B.AgentBrain._call_llm = staticmethod(fake_llm)
META = {}
P._preset_meta = lambda state: META
P._seo_timeline = lambda st: []


class _Ag:
    name = "Bible ES"

    def to_dict(self):
        return {"name": self.name}


def st():
    return {"agent": _Ag(), "language": "es", "script": "[S1] El Señor es mi pastor " * 20, "title": "Salmo 23"}


CH = {"name": "Momento Bíblico", "id": "UCm", "about": ""}
seo0 = P._seo_for(st(), {}, CH)
ok("THIS TEMPLATE'S OWN RULES" not in LLM[-1], "mẫu không khai ⇒ prompt không có khối quy tắc")
ok(len(LLM) == 1 and "leyes mentales" in seo0["tags"], "mẫu không khai ⇒ không kiểm, không gọi thêm", seo0["tags"])
ok("vencer la ansiedad" in seo0["title"].lower(), "mẫu không khai ⇒ _fit_title như cũ", seo0["title"])

META.update(seo_title_rule='Use the frame "Vencer la ansiedad: …"', seo_desc_rule="Open with a verse.", seo_banned="leyes, ley")
LLM.clear()
seo1 = P._seo_for(st(), {}, CH)
ok(all(x in LLM[-1] for x in ("THIS TEMPLATE'S OWN RULES", 'Vencer la ansiedad: …', "Open with a verse.", "leyes, ley")),
   "prompt mang quy tắc tiêu đề, mô tả, từ cấm", LLM[-1][-400:])
ok(LLM[-1].index("THIS TEMPLATE'S OWN RULES") > LLM[-1].index("- title:"), "khối của mẫu đứng SAU luật chung")
ok(len(LLM) == 1, "tiêu đề sạch ⇒ không viết lại", len(LLM))

print("D. tiêu đề dính từ cấm")
LLM.clear()
ANSWERS[:] = [answer(title="Las 6 LEYES mentales del Salmo 1 y cómo aplicarlas en la vida"), answer()]
s = st()
seo2 = P._seo_for(s, {}, CH)
ok(seo2["title"].startswith("Vencer la ansiedad"), "lần đầu dính ⇒ viết lại, dùng bản sạch", seo2["title"])
ok(len(LLM) == 2 and "LEYES mentales" in LLM[1] and "different" in LLM[1], "lượt sau báo model tiêu đề vừa sai", LLM[-1][-300:])

LLM.clear()
BAD = answer(title="Las 6 leyes mentales del Salmo 1 y cómo aplicarlas en la vida")
ANSWERS[:] = [BAD, BAD, BAD]
try:
    P._seo_for(st(), {}, CH)
    raised = ""
except RuntimeError as e:
    raised = str(e)
ok("Not published" in raised and "leyes" in raised, "viết lại vẫn dính ⇒ RuntimeError, không đăng", raised)
ok(len(LLM) == 1 + P.SEO_BAN_RETRIES, "đúng số lần viết lại", len(LLM))
ok("publish" in P.SOFT_FAIL_STEPS, "lỗi ở bước đăng không làm hỏng cả task: video còn, Retry được")

print("E. dọn phần còn lại")
ANSWERS[:] = [answer(chapters=[{"start": "0:00", "title": "Las leyes"}])]
s = st()
seo3 = P._seo_for(s, {}, CH)
ok("leyes mentales" not in seo3["tags"] and "biblia" in seo3["tags"], "tag có từ cấm bị bỏ", seo3["tags"])
ok("#LeyesDeVida" not in seo3["description"], "hashtag viết liền có từ cấm bị bỏ", seo3["description"])
ok("#biblia" in seo3["description"], "hashtag khác còn", seo3["description"])
ok(not P._banned_hits(seo3["description"], ["leyes", "ley"]), "câu có từ cấm bị bỏ", seo3["description"])
ok("Una oración final" in seo3["description"], "câu khác cùng dòng còn", seo3["description"])
ok(any("description" in w for w in s.get("warnings", [])), "có cảnh báo đã bỏ", s.get("warnings"))
leg, cut = P._seo_scrub({"title": "t", "description": "Las leyes\nOtra", "tags": ["a"], "keyword": "ley", "chapters": []}, ["leyes", "ley"], keep_desc=True)
ok(leg["description"] == "Las leyes\nOtra" and not cut and leg["keyword"] == "", "mô tả người gọi tự gõ giữ nguyên; từ khoá dính ⇒ bỏ", leg)

print("F. tiêu đề tự gõ + khung riêng")
LLM.clear()
s = st()
seo4 = P._seo_for(s, {"seo_title": "Las leyes de mi canal"}, CH)
ok(seo4["title"] == "Las leyes de mi canal" and len(LLM) == 1, "tiêu đề tự gõ giữ nguyên, không viết lại", seo4["title"])
ok(any("you typed" in w for w in s.get("warnings", [])), "có cảnh báo", s.get("warnings"))

META.clear()
META.update(seo_title_rule='Use "Renovar + Jesús"')
ANSWERS[:] = [answer(title="Renovar tu mente con Jesús", keyword="salmo uno")]
seo5 = P._seo_for(st(), {}, CH)
ok(seo5["title"] == "Renovar tu mente con Jesús", "khung riêng ⇒ không ghép « | từ khoá», « | tên kênh»", seo5["title"])
META.clear()
ANSWERS[:] = [answer(title="Renovar tu mente con Jesús", keyword="salmo uno")]
seo6 = P._seo_for(st(), {}, CH)
ok("salmo uno" in seo6["title"], "không khung ⇒ vẫn ghép từ khoá như cũ", seo6["title"])
long_t = "Renovar tu mente con Jesús cuando todo parece perdido y ya no te quedan fuerzas para seguir adelante hoy"
META.update(seo_title_rule="x")
ANSWERS[:] = [answer(title=long_t)]
seo7 = P._seo_for(st(), {}, CH)
ok(len(seo7["title"]) <= P.SEO_TITLE_MAX, "khung riêng vẫn giữ giới hạn độ dài", len(seo7["title"]))
META.clear()

print("G. tiêu đề tạm ở bước kịch bản")
META.update(seo_title_rule='Use "Vencer la ansiedad: …"', seo_banned="leyes")
note = P._seo_title_note(st())
ok("Vencer la ansiedad" in note and "leyes" in note, "lời dặn cho dòng TITLE", note)
ok(P._seo_title_note({}) != "" and (META.clear() or True) and P._seo_title_note({}) == "", "mẫu không khai ⇒ không thêm chữ")

META.update(seo_banned="leyes")
ASK = []


def fake_ask(agent, system_prompt, user_prompt, budget):
    ASK.append(user_prompt)
    return ASK_ANSWERS.pop(0)


P._ask_model = fake_ask
ASK_ANSWERS = ["TITLE: **Vencer la ansiedad: tres versos**"]
s = st()
ok(P._title_within_rules(s, _Ag(), "Vencer la ansiedad hoy", "Spanish") == "Vencer la ansiedad hoy" and not ASK, "tiêu đề sạch ⇒ không gọi model")
t = P._title_within_rules(s, _Ag(), "Las 6 leyes del Salmo 1", "Spanish")
ok(t == "Vencer la ansiedad: tres versos" and not s.get("warnings"), "dính ⇒ xin tiêu đề khác, bỏ «TITLE:» + dấu", t)
ASK_ANSWERS = ["Otras leyes del Salmo 1"]
s = st()
t = P._title_within_rules(s, _Ag(), "Las 6 leyes del Salmo 1", "Spanish")
ok(t == "Las 6 leyes del Salmo 1" and any("will not post" in w for w in s["warnings"]), "vẫn dính ⇒ giữ + cảnh báo ở phần duyệt", s.get("warnings"))


def boom(*a):
    raise RuntimeError("model down")


P._ask_model = boom
s = st()
t = P._title_within_rules(s, _Ag(), "Las 6 leyes", "Spanish")
ok(t == "Las 6 leyes" and s.get("warnings"), "model lỗi ⇒ không đổ bước kịch bản, chỉ cảnh báo", t)

print("H. bị chặn ở bước đăng: video còn, không dựng lại từ đúng kho ấy")
from tubecli.extensions.content_video import autopublish as AP  # noqa: E402

MARK = {"high_water": "2026-10-01", "high_water_pending": "2026-10-05", "published_today": 1}
SAVED = []
AP.get_mark = lambda aid: dict(MARK)
AP.save_mark = lambda aid, **f: (SAVED.append(f) or MARK.update(f) or True)
ok(AP.skip_window("a1", "2026-10-09") and MARK["high_water"] == "2026-10-09" and MARK["published_today"] == 1,
   "mốc tiến, trần ngày giữ nguyên", MARK)
SAVED.clear()
ok(not AP.skip_window("a1", "2026-10-02") and not SAVED, "mốc không đi lui", SAVED)
ok(not AP.skip_window("", "2026-12-01"), "thiếu agent ⇒ thôi")


def run_publish(opts, err):
    calls = []
    P._video_secs = lambda s: 60.0
    P._too_short_to_autopublish = lambda s, o: ""
    P._remember_published = lambda s: None
    P._commit_autopublish = lambda s, o: calls.append("commit")

    def fake_publish(s, o):
        raise err
    P._publish_now = fake_publish
    real = AP.skip_window
    AP.skip_window = lambda aid, hw="": calls.append(("skip", aid, hw)) or True
    s = {"agent": type("A", (), {"id": "a1"})(), "video_path": "x.mp4", "high_water": "2026-10-09",
         "_say": lambda *a: None}
    try:
        P._step_publish(s, {"publish": True, **opts})
        raised = False
    except RuntimeError:
        raised = True
    AP.skip_window = real
    return s, calls, raised


s, calls, raised = run_publish({"autopublish": True}, P.SeoBannedTitle("Not published: x"))
ok(raised and s["publish_blocked"] == "banned_title" and "Not published" in s["publish_error"], "bước đăng báo lỗi, ghi lý do", s.get("publish_error"))
ok(("skip", "a1", "2026-10-09") in calls and "commit" not in calls, "tự đăng ⇒ dời mốc, không tính là đã đăng", calls)
s, calls, raised = run_publish({}, P.SeoBannedTitle("Not published: x"))
ok(raised and not calls, "lượt tay ⇒ không đụng sổ tự đăng", calls)
s, calls, raised = run_publish({"autopublish": True}, RuntimeError("network down"))
ok(raised and not calls and not s.get("publish_blocked"), "lỗi đăng khác ⇒ mốc đứng yên như cũ", calls)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
