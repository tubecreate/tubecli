# -*- coding: utf-8 -*-
"""TIÊU CHÍ SEO KHI ĐĂNG YOUTUBE (19/10/2026) — bảng chấm TubeLens: video agent tự đăng được 15/100, 2/8 tiêu chí.

  A. tiêu đề 40–70 ký tự, chứa từ khoá chính (cắt ở dấu ngăn / khoảng trắng; thiếu từ khoá thì thêm; ngắn thì ghép kênh)
  B. chương hợp luật YouTube: bám đầu cảnh, 0:00 đầu, tăng dần, cách ≥ 10 s, 3–8 chương; thiếu ⇒ không chương
  C. mô tả: từ khoá ở 2 dòng đầu, ≥ 250 ký tự, chương chèn TRƯỚC dòng hashtag, link kênh khi chưa có link nào
  D. ≥ 5 tag, từ khoá đứng đầu; phần người gọi tự viết (seo_title / seo_description) giữ nguyên
  E. _seo_for trọn vòng: prompt có SCENE TIMELINE + luật; mốc model chép vào mô tả bị bỏ, chương hợp lệ được chèn
  F. _seo_timeline: mốc cảnh theo giọng đọc, co giãn theo video thật; lệch > 3 % ⇒ không chương

Run:  python tests/seo_criteria_test.py
"""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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


print("A. tiêu đề")
long_t = "El Secreto Bíblico y Neurocientífico para Reiniciar Tu Mente y Vencer la Ansiedad Hoy"   # 87 ký tự
t = P._fit_title(long_t, "vencer la ansiedad", "Momento Bíblico")
ok(40 <= len(t) <= 70 and not t.endswith(("y", " ")), "81+ ký tự ⇒ cắt về 40–70 ở khoảng trắng", (len(t), t))
t2 = P._fit_title("Salmo 23 explicado verso a verso: el Señor es mi pastor | Enseñanzas de Jesús para hoy",
                  "salmo 23", "")
ok(t2 == "Salmo 23 explicado verso a verso: el Señor es mi pastor", "cắt ở dấu ngăn « | » khi phần trước ≥ 40", t2)
t3 = P._fit_title("Cómo orar cuando tienes miedo en la noche", "oración contra el miedo", "")
ok("oración contra el miedo" in t3 and len(t3) <= 70, "thiếu từ khoá ⇒ thêm cuối", t3)
t4 = P._fit_title("Salmo 91 explicado", "salmo 91", "Momento Bíblico")
ok(t4 == "Salmo 91 explicado | Momento Bíblico", "ngắn ⇒ ghép tên kênh", t4)

print("B. chương")
pts = [(0.0, "a"), (8.0, "b"), (95.0, "c"), (240.5, "d"), (400.0, "e"), (640.0, "f"), (1020.0, "g")]
ch = P._chapters_fit([{"start": "0:03", "title": "Intro"}, {"start": "1:36", "title": "El problema"},
                      {"start": "0:09", "title": "Muy cerca"}, {"start": "4:00", "title": "La respuesta"},
                      {"start": "10:41", "title": "Oración"}, {"start": "16:59", "title": "Cierre"},
                      {"start": "99:00", "title": "Fuera"}], pts, 1031.0)
ok([(P._ts(s), n) for s, n in ch] == [("0:00", "Intro"), ("1:35", "El problema"), ("4:00", "La respuesta"),
                                         ("10:40", "Oración"), ("17:00", "Cierre")],
   "bám đầu cảnh, 0:00 đầu, bỏ mốc < 10 s và mốc ngoài video", [(P._ts(s), n) for s, n in ch])
ok(P._chapters_fit([{"start": "0:00", "title": "A"}, {"start": "1:35", "title": "B"}], pts, 1031.0) == [],
   "< 3 chương ⇒ không chương")
ok(P._chapters_fit("rác", pts, 1031) == [] and P._chapters_fit([{"start": "x", "title": "A"}], pts, 0) == [],
   "rác ⇒ không chương")
ok(P._ts(3725) == "1:02:05" and P._ts_secs("1:02:05") == 3725 and P._ts_secs("4:00") == 240, "mốc h:mm:ss khi ≥ 1 giờ")

print("C/D. mô tả + tag")
state = {"script": "Texto del guion " * 40}
desc = "Hoy hablamos del miedo y la fe.\nUna reflexión corta.\n\n#fe #biblia #oracion"
r = P._seo_polish("Cómo vencer la ansiedad con la Biblia: 3 versículos clave", desc, ["biblia", "fe"],
                  "vencer la ansiedad", [(0.0, "Inicio"), (95.0, "El miedo"), (240.0, "La fe")],
                  {"name": "Momento Bíblico", "id": "UCabc"}, state)
lines = [ln for ln in r["description"].splitlines() if ln.strip()]
ok(any("vencer la ansiedad" in ln.lower() for ln in lines[:2]), "từ khoá ở 2 dòng đầu (thêm dòng tiêu đề)", lines[:2])
ok(len(r["description"]) >= 250, "mô tả ≥ 250 ký tự", len(r["description"]))
d = r["description"]
ok(d.index("0:00 Inicio") < d.index("#fe") and "1:35 El miedo" in d and lines[-1].startswith("#"),
   "chương trước dòng hashtag, hashtag vẫn là dòng cuối", d)
ok("https://www.youtube.com/channel/UCabc?sub_confirmation=1" in d, "chưa có link ⇒ thêm link kênh")
ok(r["tags"][0] == "vencer la ansiedad" and len(r["tags"]) >= 5, "≥ 5 tag, từ khoá đầu", r["tags"])
ok(r["keyword"] == "vencer la ansiedad" and r["chapters"][1] == {"start": "1:35", "title": "El miedo"}, "trả keyword + chapters")
keep = P._seo_polish("Mi título", "Mi descripción propia", [], "kw", [(0.0, "A"), (20.0, "B"), (40.0, "C")],
                     {"id": "UC1"}, state, keep_title=True, keep_desc=True)
ok(keep["title"] == "Mi título" and keep["description"] == "Mi descripción propia", "người gọi tự viết ⇒ giữ nguyên")
linked = P._seo_polish("x" * 50, "Fuentes: https://example.org/a\n\n#a", ["a"], "", [], {"id": "UC1"}, state)
ok("sub_confirmation" not in linked["description"], "đã có link nguồn ⇒ không thêm link kênh")

print("E. _seo_for trọn vòng")
from tubecli.core import brain as B  # noqa: E402
SEEN = {}


def fake_llm(agent, messages, temperature=0.6):
    SEEN["sys"], SEEN["user"] = messages[0]["content"], messages[1]["content"]
    return json.dumps({
        "keyword": "salmo 23",
        "title": "Salmo 23 explicado: el Señor es mi pastor y por qué nada te faltará en tiempos de crisis",
        "description": "El Salmo 23 explicado verso a verso.\n0:00 Intro\n1:35 Verso 1\nUna guía para hoy.\n\n#salmo23 #biblia",
        "tags": ["salmo 23 explicado", "el señor es mi pastor", "biblia", "fe", "oracion"],
        "chapters": [{"start": "0:00", "title": "Introducción"}, {"start": "1:35", "title": "Verso 1"},
                     {"start": "4:00", "title": "Verso 4"}, {"start": "10:40", "title": "Oración final"}],
    })


B.AgentBrain._call_llm = staticmethod(fake_llm)
P._seo_timeline = lambda st: (st.__setitem__("_seo_video_secs", 1031.0) or pts)


class _Ag:
    name = "Bible ES"

    def to_dict(self):
        return {"name": self.name}


st = {"agent": _Ag(), "language": "es", "script": "[S1] El Señor es mi pastor " * 20, "title": "Salmo 23"}
seo = P._seo_for(st, {}, {"name": "Momento Bíblico", "id": "UCm", "about": ""})
ok("SCENE TIMELINE" in SEEN["user"] and "[1:35] c" in SEEN["user"] and "FIRST TWO LINES" in SEEN["user"]
   and '"chapters"' in SEEN["sys"], "prompt có dòng thời gian + luật", SEEN.get("user", "")[-600:])
ok(40 <= len(seo["title"]) <= 70 and "salmo 23" in seo["title"].lower(), "tiêu đề đạt", seo["title"])
dl = seo["description"].splitlines()
ok("salmo 23" in " ".join(dl[:2]).lower(), "từ khoá trong 2 dòng đầu")
stamps = [ln for ln in dl if re.match(r"^\d+:\d{2} ", ln)]
ok(stamps == ["0:00 Introducción", "1:35 Verso 1", "4:00 Verso 4", "10:40 Oración final"],
   "mốc model chép vào mô tả bị bỏ, chương hợp lệ được chèn", stamps)
ok(seo["tags"][0] == "salmo 23" and len(seo["tags"]) >= 5, "tag đạt", seo["tags"])

print("F. _seo_timeline")
P2 = __import__("importlib").reload(P)
TMP = Path(tempfile.mkdtemp(prefix="seo-"))
for n in ("v.mp4", "a1.mp3", "a2.mp3", "a3.mp3", "i1.png", "i2.png", "i3.png"):
    (TMP / n).write_bytes(b"x")
DUR = {str(TMP / "a1.mp3"): 10.0, str(TMP / "a2.mp3"): 20.0, str(TMP / "a3.mp3"): 30.0, str(TMP / "v.mp4"): 61.0}
P2._storyboards = lambda ep: [
    {"id": 3, "storyboard_number": 3, "tts_audio_url": str(TMP / "a3.mp3"), "image_url": str(TMP / "i3.png"), "narration_text": "tres"},
    {"id": 1, "storyboard_number": 1, "tts_audio_url": str(TMP / "a1.mp3"), "image_url": str(TMP / "i1.png"), "narration_text": "[S1] uno"},
    {"id": 2, "storyboard_number": 2, "tts_audio_url": str(TMP / "a2.mp3"), "image_url": str(TMP / "i2.png"), "narration_text": "dos"}]
P2._studio_subtitles = lambda: None
P2._srt_seconds = lambda path, mod=None: DUR.get(str(path), 0.0)
st = {"episode_id": 7, "video_path": str(TMP / "v.mp4")}
tl = P2._seo_timeline(st)
ok([(round(t, 2), s) for t, s in tl] == [(0.0, "uno"), (10.17, "dos"), (30.5, "tres")] and st["_seo_video_secs"] == 61.0,
   "mốc theo giọng, xếp theo số cảnh, co giãn theo video thật, bỏ thẻ [S1]", tl)
DUR[str(TMP / "v.mp4")] = 90.0
ok(P2._seo_timeline({"episode_id": 7, "video_path": str(TMP / "v.mp4")}) == [], "lệch > 3 % ⇒ không chương")
ok(P2._seo_timeline({"episode_id": None, "video_path": ""}) == [], "chưa có video ⇒ []")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
