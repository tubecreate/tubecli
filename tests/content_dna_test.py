# -*- coding: utf-8 -*-
"""Content DNA (16/10/2026) — extension content_dna + nối vào content_video / Content Studio / Codex.

User: «làm thêm một dạng mẫu customize, kiểu như xây dựng mẫu cấu trúc, cách hành văn (ADN) để AI viết content dựa
vào đó… tạo 1 extension mới trong tubecli chức năng giống như t2content (đọc dữ liệu, bài mẫu, đúc kết thành mẫu),
xong template list mẫu đó để chọn». Kiểm (KHÔNG gọi model, KHÔNG ra mạng — model, phụ đề YouTube đều giả):
  A. store: id có đuôi ngẫu nhiên (tên toàn chữ Hán không đè nhau), normalize (tỷ lệ cộng 100, rác → khuôn rỗng),
     lưu lại = phiên bản mới + bản cũ cất .vN, list bỏ file phiên bản, xoá sạch
  B. learn: phụ đề SRT/VTT → đoạn văn, tên file yt-dlp → tiêu đề, gom (dán «---», file, link, bỏ bài ngắn), chọn mẫu
     rải đều bỏ dị biệt, trích giữ đầu/giữa/cuối, đọc JSON lỗi vặt, hỏi lại một lần, cả lượt học với model giả
  C. apply: chọn ADN (form > mẫu, "none" tắt), khối prompt (nhịp theo thứ tự + số chữ, giữ TITLE/[SHOW], câu cửa miệng
     tối đa một, chỉ giọng khi structure=False), độ dài theo ADN
  D. pipeline: _step_script chèn khối ADN; "none" tắt; nguyên văn không có; tham khảo chỉ giọng; resolve_words theo ADN
  E. API: danh sách / chi tiết / sửa (phiên bản +1) / xem trước prompt / học nền / xoá
  F. Content Studio + Codex + thanh bên: ô chọn, metadata, locale 9 thứ tiếng
Run:  python tests/content_dna_test.py
"""
import json

import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="dna_test_")
cfg.DATA_DIR = type(cfg.DATA_DIR)(_TMP) if hasattr(cfg, "DATA_DIR") else _TMP

from tubecli.extensions.content_dna import apply as A, learn as L, store as S  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402
from tubecli.core import youtube_transcript as YT  # noqa: E402

PASS = FAIL = 0
LANGS = ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW")


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def es(n):
    base = "la mente encuentra paz cuando aprende a mirar con calma lo que pasa cada día".split()
    return " ".join((base * (n // len(base) + 1))[:n]) + "."


DNA = {
    "language": "Spanish", "genre": "Christian teaching", "audience": "Spanish-speaking believers",
    "persona": "a warm pastor who talks to «tú»", "tone": "warm, reflective", "style_summary": "Short sentences.",
    "words": 1400,
    "formats": [{"name": "Numbered teachings", "description": "N lessons from Jesus",
                 "beats": [{"name": "Hook question", "share": 20, "purpose": "stop the scroll", "how": "a direct question"},
                           {"name": "Lessons", "share": 50, "purpose": "teach", "how": "verse then life"},
                           {"name": "Prayer close", "share": 10, "purpose": "close", "how": "short prayer"}],
                 "transitions": ["La siguiente enseñanza…"], "pacing": "calm"}],
    "topics": {"clusters": [{"name": "Mind", "share": 3, "angles": ["anxiety"], "anchors": ["Mateo 6"]},
                            {"name": "Power", "share": 1}], "title_formulas": ["N ENSEÑANZAS de JESÚS sobre X"],
               "hook_types": ["question"]},
    "openings": ["A question to the viewer"], "closings": ["A short prayer"], "devices": ["triads"],
    "signature_phrases": ["Dios te bendiga", "Amén"], "avoid": ["politics"],
}

print("── A. store ────────────────────────────────────────────────")
ids = {S.new_id("诗经 讲解") for _ in range(20)}
ok(len(ids) == 20 and all(S.valid_id(i) and i.startswith("dna-") for i in ids),
   "tên toàn chữ Hán → id «dna-xxxxxx» không trùng (T2Content: «mau» đè nhau)", sorted(ids)[:3])
ok(S.new_id("Momento Bíblico — Enseñanzas").startswith("momento-biblico-ensenanzas-"), "slug bỏ dấu")
n = S.normalize(DNA)
beats = n["formats"][0]["beats"]
ok(sum(b["share"] for b in beats) == 100 and [b["name"] for b in beats] == ["Hook question", "Lessons", "Prayer close"],
   "nhịp: tỷ lệ cộng đúng 100, giữ thứ tự", [b["share"] for b in beats])
ok(sum(c["share"] for c in n["topics"]["clusters"]) == 100 and n["topics"]["clusters"][0]["share"] == 75,
   "cụm đề tài 3:1 → 75/25", n["topics"]["clusters"])
z = S.normalize({"formats": "rác", "openings": "Mở 1\nMở 2\n\nMở 1", "words": "abc"})
ok(z["formats"] == [] and z["openings"] == ["Mở 1", "Mở 2"] and z["words"] == 0, "rác → khuôn rỗng, danh sách bỏ trùng", z)
even = S.normalize({"formats": [{"name": "x", "beats": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}]})
ok([b["share"] for b in even["formats"][0]["beats"]] in ([34, 33, 33], [33, 34, 33], [33, 33, 34]), "không tỷ lệ → chia đều",
   even["formats"][0]["beats"])
rec = S.save({"name": "Momento bíblico", "dna": DNA, "stats": {"docs": 12, "samples": 8, "words_median": 1500}})
ok(rec["version"] == 1 and S.get(rec["id"])["name"] == "Momento bíblico", "lưu lần đầu = phiên bản 1")
rec2 = S.save(dict(S.get(rec["id"]), name="Momento bíblico v2"))
ok(rec2["version"] == 2 and S.versions(rec["id"]) == [1] and S.get(rec["id"])["name"] == "Momento bíblico v2",
   "lưu lại → phiên bản 2, bản cũ cất .v1", S.versions(rec["id"]))
for _ in range(7):
    S.save(dict(S.get(rec["id"])))
ok(len(S.versions(rec["id"])) == S.MAX_VERSIONS, f"chỉ giữ {S.MAX_VERSIONS} bản cũ", S.versions(rec["id"]))
lst = S.list_all()
ok(len(lst) == 1 and lst[0]["beats"] == 3 and lst[0]["words"] == 1400 and lst[0]["docs"] == 12,
   "danh sách: một ADN (bỏ file phiên bản), tóm tắt đúng", lst)
ok(S.usual_words({"dna": {"words": 0}, "stats": {"words_median": 900}}) == 900, "độ dài: ADN không ghi → trung vị lúc học")
tmp = S.save({"name": "tạm", "dna": DNA})
S.save(dict(S.get(tmp["id"])))
ok(S.delete(tmp["id"]) and S.get(tmp["id"]) is None and S.versions(tmp["id"]) == [], "xoá sạch cả phiên bản")
ok(S.get("../etc/passwd") is None and not S.valid_id("A B"), "id lạ không đọc file ngoài kho")

print("── B. learn ────────────────────────────────────────────────")
SRT = "1\n00:00:01,000 --> 00:00:03,000\nHola amigo,\n\n2\n00:00:03,000 --> 00:00:05,000\nhoy hablamos de la mente.\n\n" \
      "3\n00:00:05,000 --> 00:00:07,000\n<i>Jesús enseñó</i> algo.\n"
txt = L.clean_subtitles(SRT)
ok("-->" not in txt and "Hola amigo, hoy hablamos de la mente." in txt and "<i>" not in txt, "SRT → đoạn văn", txt)
VTT = "WEBVTT\nKind: captions\n\n00:00:01.000 --> 00:00:02.000\nla paz\n\n00:00:02.000 --> 00:00:03.000\nla paz\nde Dios.\n"
ok(L.clean_subtitles(VTT).count("la paz") == 1, "VTT: dòng lặp liền nhau chỉ giữ một", L.clean_subtitles(VTT))
ok(L._title_from_name("Momento - 6 ENSEÑANZAS de JESÚS [abcdefghijk].es.srt") == "Momento - 6 ENSEÑANZAS de JESÚS",
   "tên file yt-dlp → tiêu đề", L._title_from_name("Momento - 6 ENSEÑANZAS de JESÚS [abcdefghijk].es.srt"))


def fake_fetch(ref, prefer_lang="", **kw):
    if "bad" in ref:
        return {"ok": False, "message": "This video has no subtitles"}
    return {"ok": True, "url": ref, "title": "Video " + ref[-3:], "text": es(1200), "language": "es"}


YT.fetch_transcript = fake_fetch
docs, notes = L.gather([f"Primera\n{es(400)}\n---\nSegunda\n{es(600)}\n---\nCorto"],
                       [("sermon [abcdefghijk].es.srt", SRT.replace("algo", es(300)).encode()),
                        ("foto.png", b"x")],
                       ["https://youtu.be/aaaaaaaaa01", "https://youtu.be/bad", "https://youtu.be/aaaaaaaaa01"])
titles = [d["title"] for d in docs]
ok(titles[:2] == ["Primera", "Segunda"] and "sermon" in titles and sum(d["source"] == "youtube" for d in docs) == 1,
   "gom: dán tách «---», file .srt, link (trùng link chỉ một)", titles)
ok(any("too short" in x for x in notes) and any("foto.png" in x for x in notes) and any("no subtitles" in x for x in notes),
   "bài ngắn / file lạ / link hỏng → cảnh báo, không ném", notes)
many = [{"title": str(i), "text": "", "words": w} for i, w in enumerate([100, 5000] + list(range(800, 2000, 50)))]
pick = L.pick_samples(many, 8)
ok(len(pick) == 8 and all(800 <= d["words"] <= 2000 for d in pick) and len({d["title"] for d in pick}) == 8,
   "chọn 8 mẫu rải đều, bỏ bài dị biệt 100 / 5000 chữ", [d["words"] for d in pick])
long = "INICIO " + es(4000) + " MEDIO " + es(4000) + " FINAL"
ex = L.excerpt(long, 3000)
ok(ex.startswith("INICIO") and ex.rstrip().endswith("FINAL") and len(ex) <= 3100 and ex.count("[…]") == 2,
   "trích: giữ đầu + giữa + cuối", len(ex))
ok(L.parse_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}, "đọc JSON: bỏ ``` và dấu phẩy thừa")
asked = []


def flaky(agent, system, user, max_tokens, temperature):
    asked.append(temperature)
    return "not json" if len(asked) == 1 else '{"ok": true}'


ok(L.ask_json(None, "s", "u", 100, flaky) == {"ok": True} and asked == [0.3, 0.1], "JSON hỏng → hỏi lại một lần, nhiệt độ thấp")

AGENT = SimpleNamespace(id="ag1", name="Writer", model="9router|fake-model", to_dict=lambda: {"id": "ag1"})
L.resolve_agent = lambda agent_id: AGENT
seen = {"analyze": 0, "merge": None}


def fake_call(agent, system, user, max_tokens, temperature):
    if system == L.ANALYZE_SYSTEM:
        seen["analyze"] += 1
        assert "EXTERNAL DATA" in user
        return json.dumps({"format": "teaching", "beats": [{"name": "Hook", "share": 30}, {"name": "Body", "share": 70}],
                           "signature_phrases": ["Amén"]})
    seen["merge"] = user
    return json.dumps(DNA)


progress = []
got = L.learn("Canal bíblico", texts=["\n---\n".join(f"Pieza {i}\n{es(500 + 40 * i)}" for i in range(12))],
              progress=progress.append, call=fake_call)
ok(seen["analyze"] == L.SAMPLE_MAX and got["stats"]["docs"] == 12 and got["stats"]["samples"] == L.SAMPLE_MAX,
   f"12 bài → phân tích riêng {L.SAMPLE_MAX} bài, rồi GỘP một lượt", (seen["analyze"], got["stats"]))
ok("ANALYSES of 8 sample pieces" in seen["merge"] and "Pieza 0" in seen["merge"] and "Pieza 11" in seen["merge"],
   "lượt gộp đọc mọi bản phân tích + TOÀN BỘ tiêu đề")
ok(S.get(got["id"])["dna"]["formats"][0]["beats"][0]["name"] == "Hook question" and got["model"] == "9router|fake-model"
   and any("Merging" in p for p in progress), "ADN được lưu, ghi model, báo tiến độ", progress)
again = L.learn("Canal bíblico (again)", texts=["\n---\n".join(f"P{i}\n{es(500)}" for i in range(3))], dna_id=got["id"],
                call=fake_call)
ok(again["id"] == got["id"] and again["version"] == 2, "học lại vào đúng ADN cũ → phiên bản 2")
try:
    L.learn("x", texts=[es(500)], call=fake_call)
    ok(False, "phải ném khi chỉ 1 bài")
except L.LearnError as e:
    ok("at least 2 sample" in str(e), "1 bài → lỗi nói rõ cần ≥ 2 bài", e)
S.delete(got["id"])

print("── C. apply ────────────────────────────────────────────────")
ok(A.choose({"content_dna": "abc-123456"}, {"content_dna": "def-654321"}) == "abc-123456", "form thắng mẫu")
ok(A.choose({"content_dna": "none"}, {"content_dna": "def-654321"}) == "", "form «none» tắt ADN của mẫu")
ok(A.choose({}, {"content_dna": "def-654321"}) == "def-654321", "form trống → ADN của mẫu")
r = S.get(rec["id"])
block = A.prompt_block(r, 1000)
# 20/50/10 (tổng 80) đã chuẩn hoá thành 25/63/12 lúc lưu ⇒ 1000 chữ = 250 / 630 / 120
ok("STRUCTURE — Numbered teachings" in block and "1. Hook question (~250 words)" in block
   and "2. Lessons (~630 words)" in block and "3. Prayer close (~120 words)" in block
   and "keep the TITLE line and the [SHOW] scene format" in block,
   "khối prompt: nhịp theo thứ tự + số chữ từ độ dài mục tiêu, giữ TITLE/[SHOW]", block[:600])
ok("use AT MOST ONE in the whole piece" in block and "Dios te bendiga" in block and "Never:\n- politics" in block,
   "câu cửa miệng tối đa một + điều không bao giờ làm")
voice = A.prompt_block(r, 1000, structure=False)
ok("STRUCTURE" not in voice and "warm pastor" in voice, "structure=False → chỉ giọng")
ok(A.usual_words({}, {"content_dna": rec["id"], "content_dna_length": "dna"}) == 1400
   and A.usual_words({}, {"content_dna": rec["id"]}) == 0, "độ dài theo ADN chỉ khi mẫu bật «dna»")

print("── D. pipeline ─────────────────────────────────────────────")
meta = {"content_dna": rec["id"], "content_dna_length": "dna", "video_length": "standard"}
ok(P.resolve_words({}, {"fields": {"metadata": meta}}) == (1400, "content DNA"), "resolve_words: mẫu bật «dna» → 1400 chữ",
   P.resolve_words({}, {"fields": {"metadata": meta}}))
ok(P.resolve_words({"source_text": es(600)}, {"fields": {"metadata": meta}})[1] == "content",
   "bài dán (độ dài theo nội dung) vẫn thắng — như cũ")
ok(P.resolve_words({"source_text": es(600), "length_mode": "template"}, {"fields": {"metadata": meta}}) == (1400, "content DNA"),
   "chọn «theo mẫu» → độ dài theo ADN")
ok(P.resolve_words({}, {"fields": {"metadata": dict(meta, content_dna_length="")}}) == (800, "template"),
   "không bật «dna» → Video length như cũ")
ok(P.DEFAULTS.get("content_dna") == "", "DEFAULTS: content_dna = theo mẫu")
P._checkpoint_merge = lambda state, extra: state.setdefault("checkpoint", {}).update(extra)
P._publish_plan = lambda task_id, name, title, text: len([s for s in P.scenes_of(text) if s[1]])
calls = []


def fake_ask(agent, system_prompt, user_prompt, budget_words):
    calls.append({"system": system_prompt, "user": user_prompt})
    return "TITLE: Paz\n\n" + "\n\n".join(f"[SHOW: escena {i}]\n{es(130)}" for i in range(6))


P._ask_model = fake_ask


class Agent:
    id, name, model, language = "a1", "Writer", "fake", "auto"

    def to_dict(self):
        return {"id": self.id, "name": self.name}


def run(opts, meta_):
    said = []
    st = {"agent": Agent(), "task_id": "t1", "warnings": [], "feedback": [], "checkpoint": {},
          "preset": {"fields": {"language": "es", "metadata": meta_}}, "_cancelled": lambda: False,
          "_say": lambda step, status, msg, pct=None: said.append(msg),
          "corpus": [{"title": "", "url": "", "content": opts.get("source_text", ""), "source": "pasted", "scraped_at": ""}]}
    calls.clear()
    P._step_script(st, dict(opts))
    return st, said, [c["system"] for c in calls]


st, said, systems = run({"source_text": es(700), "language": "es"}, meta)
ok(systems and all("CONTENT DNA \"Momento bíblico v2\"" in s and "STRUCTURE — Numbered teachings" in s for s in systems),
   "viết lại: MỌI lượt viết có khối ADN (cấu trúc + giọng)", systems[0][-400:] if systems else "")
ok(st.get("content_dna", {}).get("id") == rec["id"] and any("content DNA" in m for m in said), "state + dòng trạng thái ghi ADN", said)
st, said, systems = run({"source_text": es(700), "language": "es", "content_dna": "none"}, meta)
ok(systems and not any("CONTENT DNA" in s for s in systems), "form «none» → không có ADN")
st, said, systems = run({"source_text": es(700), "language": "es"}, {})
ok(systems and not any("CONTENT DNA" in s for s in systems), "mẫu không chọn ADN → prompt như cũ")
st, said, systems = run({"source_text": es(700), "language": "es", "script_mode": "verbatim"}, meta)
ok(not any("CONTENT DNA" in s for s in systems), "đọc nguyên văn → không có ADN")
st, said, systems = run({"source_text": es(700), "language": "es", "script_mode": "reference"}, meta)
dna_sys = [s for s in systems if "CONTENT DNA" in s]
ok(dna_sys and not any("STRUCTURE —" in s for s in dna_sys) and all("warm pastor" in s for s in dna_sys),
   "«Tham khảo cấu trúc» → ADN chỉ mang GIỌNG, cấu trúc là của video tham khảo", len(dna_sys))
st, said, systems = run({"source_text": es(700), "language": "es", "content_dna": "missing-000000"}, {})
ok(systems and not any("CONTENT DNA" in s for s in systems), "ADN đã xoá → viết như cũ, không hỏng lượt")

print("── E. API ──────────────────────────────────────────────────")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tubecli.extensions.content_dna import routes as R  # noqa: E402

app = FastAPI()
app.include_router(R.router)
app.include_router(R.page_router)
c = TestClient(app)
ok(c.get("/api/v1/content-dna").json()["items"][0]["id"] == rec["id"], "GET danh sách")
d = c.get(f"/api/v1/content-dna/{rec['id']}").json()
ok(d["usual_words"] == 1400 and isinstance(d["versions"], list), "GET chi tiết + phiên bản + độ dài")
v0 = d["version"]
dna2 = dict(d["dna"])
dna2["formats"] = [dict(dna2["formats"][0], beats=dna2["formats"][0]["beats"][:2])]
u = c.put(f"/api/v1/content-dna/{rec['id']}", json={"name": "Renamed", "dna": dna2}).json()
ok(u["version"] == v0 + 1 and u["name"] == "Renamed" and len(u["dna"]["formats"][0]["beats"]) == 2
   and sum(b["share"] for b in u["dna"]["formats"][0]["beats"]) == 100, "PUT sửa tay → phiên bản +1, tỷ lệ chuẩn lại")
ok(c.put(f"/api/v1/content-dna/{rec['id']}", json={"dna": {"formats": []}}).status_code == 400, "PUT bỏ hết nhịp → 400")
pv = c.get(f"/api/v1/content-dna/{rec['id']}/prompt?words=600").json()
ok("CONTENT DNA \"Renamed\"" in pv["prompt"] and "~" in pv["prompt"], "xem trước prompt")
ok(c.post("/api/v1/content-dna/learn", data={"name": "x"}).status_code == 400, "học không có mẫu → 400")
real_learn = L.learn
L.learn = lambda **kw: S.save({"name": kw["name"], "dna": DNA, "stats": {"docs": len(kw["files"])}})
j = c.post("/api/v1/content-dna/learn", data={"name": "Nuevo", "links": ""},
           files=[("files", ("a.txt", es(300).encode(), "text/plain")), ("files", ("b.txt", es(300).encode(), "text/plain"))]).json()
for _ in range(50):
    st_ = c.get(f"/api/v1/content-dna/jobs/{j['job']}").json()
    if st_["status"] != "running":
        break
    time.sleep(0.05)
L.learn = real_learn
ok(st_["status"] == "done" and S.get(st_["dna_id"])["stats"]["docs"] == 2, "POST học (file tải lên) → việc nền xong, có ADN", st_)
ok(c.delete(f"/api/v1/content-dna/{st_['dna_id']}").json()["ok"] and c.get(f"/api/v1/content-dna/{st_['dna_id']}").status_code == 404,
   "DELETE → 404 sau đó")
page = c.get("/content-dna")
ok(page.status_code == 200 and "__ASSET_VER__" not in page.text and "/content-dna-static/app.js?v=" in page.text, "trang /content-dna")
ok(c.get("/content-dna-static/../routes.py").status_code == 404, "file tĩnh không thoát khỏi static/")

print("── F. Studio + Codex + thanh bên ───────────────────────────")
import importlib  # noqa: E402
from tubecli.core.extension_manager import ExtensionManager  # noqa: E402

pkg = importlib.import_module("tubecli.extensions.content_dna")
ok("tubecli.extensions.content_dna" in ExtensionManager.BUILTIN_EXTENSIONS
   and getattr(pkg, "extension_instance", None) is not None and pkg.extension_instance.extension_type == "system",
   "lõi tìm thấy extension: có trong BUILTIN_EXTENSIONS + package lộ extension_instance (thiếu → mọi route 404)")
ext = ROOT / "tubecli" / "extensions"
js = (ext / "codex" / "static" / "codex.js").read_text(encoding="utf-8")
html = (ext / "codex" / "static" / "codex.html").read_text(encoding="utf-8")
ok('id="cx-v-dna"' in html and 'value="none"' in html and "options.content_dna = dna" in js and "loadDnaOptions()" in js,
   "Codex: ô ADN (theo mẫu / không / danh sách), gửi options.content_dna")
for lang in LANGS:
    dc = json.loads((ext / "codex" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    dd = json.loads((ext / "content_dna" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    ok(all(dc.get(k) for k in ("codex.field_dna", "codex.dna_template", "codex.dna_none", "codex.field_dna_hint"))
       and dd.get("content_dna") and len(dd) == len(json.loads((ext / "content_dna" / "locales" / "en.json").read_text(encoding="utf-8"))),
       f"locale {lang}: Codex + trang ADN đủ khoá")
ui = (ext / "webui" / "static")
ok("tab:'ext-content-dna'" in (ui / "app.js").read_text(encoding="utf-8")
   and 'data-src="/content-dna"' in (ui / "index.html").read_text(encoding="utf-8"), "thanh bên: mục Content DNA → iframe /content-dna")
studio = ROOT / "data" / "extensions_external" / "content_studio"
if (studio / "studio_routes.py").is_file():
    sr = (studio / "studio_routes.py").read_text(encoding="utf-8")
    sh = (studio / "static" / "studio.html").read_text(encoding="utf-8")
    s2 = (studio / "static" / "studio2.js").read_text(encoding="utf-8")
    tj = (studio / "static" / "templates.js").read_text(encoding="utf-8")
    ok('has("wizContentDna")' in sr and 'meta["content_dna"]' in sr and 'meta["content_dna_length"]' in sr,
       "Studio preset_drama_fields: wizContentDna / wizDnaLength → metadata")
    ok('id="wizContentDna"' in sh and 'id="wizDnaLength"' in sh and "'wizContentDna', 'wizDnaLength'" in s2
       and "_loadContentDnaIntoSelect('wizContentDna')" in s2 and "'wizVideoLength', 'wizEpisodes',\n                   'wizContentDna'" in tj,
       "Studio: hai ô cạnh Video length (wizard + trình sửa mẫu), danh sách nạp động")
    for lang in LANGS:
        dl = json.loads((studio / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        ok(all(dl.get(k) for k in ("cs.f.content_dna", "cs.opt.dna_none", "cs.f.dna_length", "cs.opt.dna_len_video",
                                    "cs.opt.dna_len_dna", "cs.opt.dna_missing", "cs.sum.dna")), f"Studio locale {lang}")
else:
    print("  (bỏ qua Studio — máy này không có Content Studio)")

print()
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
