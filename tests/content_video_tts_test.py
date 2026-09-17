# Voice step: edge (tts_vibevoice) or CapCut (capcut_tts), chosen by what is installed.
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.content_video import capabilities as C
from tubecli.extensions.content_video import pipeline as P

# 1. any_of in check_job / guidance
C.installed_extensions = lambda: {"content_studio": True, "capcut_tts": True}
r = C.check_job("tts")
assert r["ready"] and r["missing"] == [] and r["any_of"] == ["tts_vibevoice", "capcut_tts"], r
C.installed_extensions = lambda: {"content_studio": True}
r = C.check_job("tts")
assert not r["ready"] and r["missing"] == ["tts_vibevoice", "capcut_tts"], r
g = C.guidance_for(["tts"])
assert "Install ONE of these" in g and "CapCut TTS" in g and "TTS VibeVoice" in g, g
C.installed_extensions = lambda: {"content_studio": True, "tts_vibevoice": False, "capcut_tts": True}
assert C.check_job("tts")["ready"], "one enabled member is enough"
print("1 any_of     : ready with either extension | both missing → 'Install ONE of these'")

# 2. engine selection
P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
P._get = lambda path, timeout=60: {"accounts": [{"email": "a@x.com", "enabled": True}]}
st = {}
assert P._tts_engine(st, {"tts_engine": "auto"}) == "capcut" and st["capcut_email"] == "a@x.com"
P._get = lambda path, timeout=60: {"accounts": [{"email": "a@x.com", "enabled": False}]}
assert P._tts_engine({}, {"tts_engine": "auto"}) == "edge", "no enabled CapCut account → edge"
P.installed_extensions = lambda: {"tts_vibevoice": False, "capcut_tts": False}
assert P._tts_engine({}, {"tts_engine": "auto"}) == ""
P.installed_extensions = lambda: {"tts_vibevoice": True}
assert P._tts_engine({}, {"tts_engine": "edge"}) == "edge"
try:
    P._tts_engine({}, {"tts_engine": "capcut"})
    raise SystemExit("capcut requested but absent must raise")
except RuntimeError as e:
    assert "CapCut" in str(e)
print("2 engine     : auto→capcut with account, →edge without | explicit choices validated")

# 3. CapCut per-shot path: synthesize → save mp3 → PUT tts_audio_url (absolute path)
import tubecli.config as CFG
tmp = tempfile.mkdtemp(prefix="cv-audio-")
CFG.DATA_DIR = tmp
puts, posts = [], []
shots = [{"id": 1, "storyboard_number": 1, "narration_text": "[nhạc nền] Xin chào các bạn hôm nay"},
         {"id": 2, "storyboard_number": 2, "narration_text": "Cảnh hai", "tts_audio_url": "/already.mp3"},
         {"id": 3, "storyboard_number": 3, "narration_text": "[]"}]
P._storyboards = lambda ep_id: shots
P._post_audio_marks = lambda path, payload, timeout=180: (posts.append(payload) or (b"ID3" + b"\x00" * 2000),
                                                          [{"word": "Xin", "start": 0.0, "end": 0.4}] if payload["text"].startswith("Xin") else [])
P._put = lambda path, payload, timeout=60: puts.append((path, payload)) or {}
reports = []
state = {"episode_id": 34, "capcut_email": "a@x.com", "_cancelled": lambda: False, "_say": lambda *a: reports.append(a)}
P._tts_capcut(state, {"capcut_speaker": "vi_female_01"})
# KHÔNG có speed/volume trong thân request: bỏ trống thì CapCut TTS lấy mặc định
# người dùng đã kéo trên giao diện. Ghi cứng 10/10 như trước nghĩa là thanh tốc độ
# ấy không bao giờ áp cho video do agent dựng, mà không có gì nói ra điều đó.
assert posts == [{"email": "a@x.com", "text": "Xin chào các bạn hôm nay", "speaker": "vi_female_01", "timestamps": True}], posts
assert "speed" not in posts[0] and "volume" not in posts[0], posts[0]
assert len(puts) == 1 and puts[0][0] == "/api/v1/studio/storyboards/1"
path = puts[0][1]["tts_audio_url"]
import os
assert os.path.isabs(path) and os.path.isfile(path) and path.endswith("shot001.mp3"), path
assert state["tts_summary"] == "1 voiced (CapCut), 1 silent", state["tts_summary"]
import json as _json
side = _json.load(open(path + ".words.json", encoding="utf-8"))
assert side["engine"] == "capcut" and side["words"][0]["word"] == "Xin", side
print("3 capcut     : cue stripped, voiced shot saved + PUT absolute path, existing audio kept, empty skipped")

# 4. _step_tts dispatch: edge path still goes through the Studio's batch-tts
P.installed_extensions = lambda: {"tts_vibevoice": True}
calls = []
P._post = lambda path, payload, timeout=300: calls.append((path, payload)) or {"task_id": "t"}
P._poll_studio = lambda *a, **k: {"status": "done", "success": 3, "failed": 0}
st = {"episode_id": 34, "_cancelled": lambda: False, "_say": lambda *a: None}
P._step_tts(st, {"tts_engine": "auto", "tts_voice": "vi-VN-HoaiMyNeural"})
assert st["tts_engine"] == "edge" and calls[0][0].endswith("/batch-tts") and calls[0][1]["engine"] == "edge"
assert st["tts_summary"] == "3 voiced (edge)"
print("4 dispatch   : edge → Studio batch-tts; summary names the engine")
# 5. Giọng lưu trong preset: preset thắng "auto", chat thắng preset; CapCut mang speaker + email
P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
P._capcut_account = lambda preferred="": preferred or "first@x"
pre = lambda meta: {"preset": {"name": "T", "fields": {"metadata": meta}}}
st = {**pre({"tts_engine": "capcut", "tts_voice": "vi_female_01", "tts_email": "a@x.com"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {}) == "capcut" and st["capcut_email"] == "a@x.com" and st["capcut_speaker"] == "vi_female_01", st
st = {**pre({"tts_engine": "vibevoice", "tts_voice": "Alice"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {}) == "edge" and st["tts_batch_engine"] == "vibevoice" and st["tts_voice_pref"] == "Alice", st
st = {**pre({"tts_engine": "vibevoice", "tts_voice": "Alice"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {"tts_engine": "edge", "tts_voice": "vi-VN-NamMinhNeural"}) == "edge" and st["tts_voice_pref"] == "vi-VN-NamMinhNeural", "chat wins over preset"
assert P._preset_voice({}, {}) == ("auto", "", "")
# Options THẬT của task luôn là {**DEFAULTS, …} ⇒ luôn có tts_engine="auto". Giọng của mẫu vẫn
# phải thắng (tập 336, 13/9/2026: "auto" đè "capcut" của mẫu → tự chọn giọng sami, đọc từng shot).
real_opts = dict(P.DEFAULTS)
assert real_opts.get("tts_engine") == "auto", "DEFAULTS đổi — xem lại ca này"
st = {**pre({"tts_engine": "capcut", "tts_voice": "sKgg4MPUDBy69X7iv3fA", "tts_email": "a@x.com"}),
      "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._preset_voice(st, real_opts) == ("capcut", "sKgg4MPUDBy69X7iv3fA", "a@x.com"), P._preset_voice(st, real_opts)
assert P._tts_engine(st, real_opts) == "capcut" and st["capcut_speaker"] == "sKgg4MPUDBy69X7iv3fA" \
    and st["capcut_email"] == "a@x.com", st
st = {**pre({"tts_engine": "capcut", "tts_voice": "sKgg4MPUDBy69X7iv3fA"}), "_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, {**real_opts, "tts_engine": "edge"}) == "edge", "chat nói rõ edge vẫn thắng mẫu"
st = {"_cancelled": lambda: False, "_say": lambda *a: None}
assert P._tts_engine(st, real_opts) == "capcut" and not st.get("capcut_speaker"), \
    "không mẫu: auto giữ nguyên (CapCut có tài khoản, giọng tự chọn theo ngôn ngữ)"
# batch-tts nhận engine của preset và giọng VibeVoice không bị so ngôn ngữ
calls.clear()
P._post = lambda path, payload, timeout=300: calls.append((path, payload)) or {"task_id": "t"}
P._poll_studio = lambda *a, **k: {"status": "done", "success": 2, "failed": 0}
st = {"episode_id": 1, "language": "vi", "tts_batch_engine": "vibevoice", "tts_voice_pref": "Alice", "_cancelled": lambda: False, "_say": lambda *a: None}
P._tts_edge(st, {})
assert calls[-1][1] == {"voice_id": "Alice", "engine": "vibevoice"} and not st.get("warnings") and st["tts_summary"] == "2 voiced (vibevoice)", (calls[-1], st)
# _step_studio: preset có giọng → agent_meta không ghi đè; không có → mặc định edge theo ngôn ngữ; "auto" từ chat không lọt vào drama
bodies = []
P._post = lambda path, payload, timeout=300: bodies.append((path, payload)) or {"id": 7}
P._write_checkpoint = lambda *a, **k: None
P._storyboards = lambda ep_id: [{"id": 1, "narration_text": "x"}]
P._stream_storyboard = lambda *a, **k: None


class _A:
    id = "a1"
    name = "MC"


for meta, opts, want_engine, want_voice in [
    ({"tts_engine": "capcut", "tts_voice": "spk", "tts_email": "a@x.com"}, {}, "capcut", "spk"),
    ({}, {}, "edge", "vi-VN-HoaiMyNeural"),
    ({}, {"tts_engine": "auto"}, "edge", "vi-VN-HoaiMyNeural"),
    ({"tts_engine": "vibevoice", "tts_voice": "Alice"}, {"tts_voice": "vi-VN-NamMinhNeural"}, "vibevoice", "vi-VN-NamMinhNeural"),
]:
    bodies.clear()
    st = {"agent": _A(), "language": "vi", "script": "[SHOW: a]\nx", "title": "T", "task_id": "",
          "preset": {"name": "T", "fields": {"metadata": meta}} if meta else None, "preset_name": "T" if meta else "",
          "_cancelled": lambda: False, "_say": lambda *a: None}
    P._step_studio(st, opts)
    dm = bodies[0][1]["metadata"]
    assert dm.get("tts_engine") == want_engine and dm.get("tts_voice") == want_voice, (meta, opts, dm)
    if meta.get("tts_email"):
        assert dm.get("tts_email") == "a@x.com", dm
print("5 preset voice: preset thắng auto, chat thắng preset, CapCut mang speaker+email, VibeVoice không bị so ngôn ngữ, 'auto' không lọt vào drama")
# 6. Bước tuỳ chọn ĐÃ CHẠY mà hỏng → lượt hỏng (có Retry); chỉ publish được nuốt lỗi; thiếu năng lực vẫn bỏ qua
P.check_job = lambda job: {"ready": job != "missing_cap", "missing": ["x"] if job == "missing_cap" else [], "disabled": []}
def boom(state, options): raise RuntimeError("CapCut TTS failed for every shot (15)")
P._HANDLERS["tts"] = boom
P._HANDLERS["publish"] = boom
notes, skipped = [], []
try:
    P._run_steps([("tts", "Voice the narration", "tts", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
    raise SystemExit("tts failure must fail the run")
except RuntimeError as e:
    assert "every shot" in str(e)
notes.clear()
P._run_steps([("publish", "Publish to YouTube", "publish", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
assert notes and "Publish to YouTube** failed" in notes[0], notes
try:
    P._run_steps([("publish", "Publish to YouTube", "publish", True)], {}, {"_publish_hard": True}, lambda *a: None, lambda: False, notes, skipped)
    raise SystemExit("lượt do người dùng ra lệnh đăng: đăng hỏng phải làm task hỏng (Retry)")
except RuntimeError:
    pass
notes.clear()
P._run_steps([("tts", "Voice the narration", "missing_cap", True)], {}, {}, lambda *a: None, lambda: False, notes, skipped)
assert notes and "skipped" in notes[0] and skipped == ["missing_cap"], (notes, skipped)
print("6 fail policy : tts chạy mà hỏng → RuntimeError (Retry); publish hỏng → ghi chú; thiếu năng lực → bỏ qua")
# 7. Tự chọn giọng CapCut theo ngôn ngữ: ưu tiên giọng engine sami (có mốc từ), 11labs chỉ khi hết cách
P._get = lambda path, timeout=60: [
    {"id": "es_11", "name": "Alejandro Durán", "language": "es", "platform": "11labs"},
    {"id": "es_sami", "name": "Enrique", "language": "es", "platform": ""},
    {"id": "en_sami", "name": "Emma", "language": "en", "platform": ""},
]
pick = P._capcut_speaker_for("a@x", "es")
assert pick["id"] == "es_sami" and pick["platform"] == "", pick
P._get = lambda path, timeout=60: [{"id": "es_11", "name": "Alejandro Durán", "language": "es", "platform": "11labs"}]
pick = P._capcut_speaker_for("a@x", "es")
assert pick["id"] == "es_11" and pick["platform"] == "11labs", pick
P._get = lambda path, timeout=60: [{"id": "en_sami", "name": "Emma", "language": "en", "platform": ""}]
assert P._capcut_speaker_for("a@x", "es") is None
print("7 capcut pick : giọng sami trước, 11labs chỉ khi không còn giọng nào, khác ngôn ngữ → None")
# 8. Giọng KHÔNG có mốc (11labs) → đọc theo ĐỢT: một lượt CapCut cho nhiều shot, audio riêng từng shot
import base64 as _b64
tmp8 = tempfile.mkdtemp(prefix="cv-batch-")
CFG.DATA_DIR = tmp8
out8 = os.path.join(tmp8, "content_video", "audio", "ep8")
os.makedirs(out8, exist_ok=True)
with open(os.path.join(out8, "shot001.mp3.words.json"), "w", encoding="utf-8") as f:
    f.write('{"engine": "capcut", "words": [{"word": "viejo", "start": 0, "end": 1}]}')
shots8 = [{"id": 100 + n, "storyboard_number": n, "narration_text": f"Escena {n}. " + "palabra " * 20}
          for n in range(1, 21)]
shots8[4]["narration_text"] = "[música]"
P._storyboards = lambda ep_id: shots8
ELEVEN = [{"id": "es_11", "name": "Alejandro Durán", "language": "es", "platform": "11labs"}]
P._get = lambda path, timeout=60: ELEVEN
batch_calls, single_calls, puts8 = [], [], []


def batch_resp(payload):
    items = []
    for k, t in enumerate(payload["texts"]):
        good = not t.startswith("Escena 7.")
        items.append({"index": k, "ok": good, "error": "" if good else "CapCut trả audio rỗng (0 byte)",
                      "audio_b64": _b64.b64encode(b"ID3" + t.encode("utf-8") + b"\x00" * 2000).decode() if good else ""})
    return {"success": True, "account": "a@x.com", "items": items}


def fake_batch(path, payload, timeout=300):
    assert path == "/api/v1/capcut-tts/synthesize/batch", path
    batch_calls.append((payload, timeout))
    return batch_resp(payload)


def st_new(ep):
    return {"episode_id": ep, "capcut_email": "a@x.com", "_cancelled": lambda: False, "_say": lambda *a: None}


P._post = fake_batch
P._post_audio_marks = lambda path, payload, timeout=180: (single_calls.append(payload) or (b"ID3" + b"\x01" * 2000), [])
P._put = lambda path, payload, timeout=60: puts8.append((path, payload)) or {}
st8 = st_new(8)
P._tts_capcut(st8, {"capcut_speaker": "es_11"})
texts8 = [t for c in batch_calls for t in c[0]["texts"]]
assert len(texts8) == 19 and len(batch_calls) == 2, [len(c[0]["texts"]) for c in batch_calls]
assert all(len(c[0]["texts"]) <= P.CAPCUT_BATCH_SHOTS and sum(map(len, c[0]["texts"])) <= P.CAPCUT_BATCH_CHARS
           for c in batch_calls), [sum(map(len, c[0]["texts"])) for c in batch_calls]
assert all(c[0]["speaker"] == "es_11" and c[0]["email"] == "a@x.com" and "timestamps" not in c[0]
           for c in batch_calls), batch_calls[0][0]
assert all(c[1] >= 120 + 2 * 180 for c in batch_calls), [c[1] for c in batch_calls]
assert [p["text"][:9] for p in single_calls] == ["Escena 7."], single_calls
assert single_calls[0]["timestamps"] is True and single_calls[0]["speaker"] == "es_11", single_calls[0]
assert len(puts8) == 19 and {p[0] for p in puts8} == {f"/api/v1/studio/storyboards/{100 + n}" for n in range(1, 21) if n != 5}
p7 = next(p[1]["tts_audio_url"] for p in puts8 if p[0].endswith("/107"))
assert open(p7, "rb").read().startswith(b"ID3\x01"), "shot 7 phải là audio đọc riêng"
p3 = next(p[1]["tts_audio_url"] for p in puts8 if p[0].endswith("/103"))
assert b"Escena 3." in open(p3, "rb").read(), "audio của đợt phải vào ĐÚNG shot"
assert not os.path.exists(os.path.join(out8, "shot001.mp3.words.json")), "đọc lại không có mốc → bỏ mốc cũ"
assert st8["tts_summary"] == "19 voiced (CapCut), 1 silent", st8["tts_summary"]

# 8b. extension cũ chưa có route đợt (404) → thử ĐÚNG MỘT lần rồi đọc từng shot
batch_calls.clear(); single_calls.clear(); puts8.clear()


def batch_404(path, payload, timeout=300):
    batch_calls.append((payload, timeout))
    raise RuntimeError(f"{path} → HTTP 404: Not Found")


P._post = batch_404
st8 = st_new(81)
P._tts_capcut(st8, {"capcut_speaker": "es_11"})
assert len(batch_calls) == 1 and len(single_calls) == 19, (len(batch_calls), len(single_calls))
assert st8["tts_summary"] == "19 voiced (CapCut), 1 silent", st8["tts_summary"]

# 8c. mọi tài khoản đang nghỉ (503) → dừng cả bước, không đọc từng shot
batch_calls.clear(); single_calls.clear()


def batch_503(path, payload, timeout=300):
    batch_calls.append((payload, timeout))
    raise RuntimeError(f"{path} → HTTP 503: Tất cả tài khoản CapCut đang nghỉ")


P._post = batch_503
try:
    P._tts_capcut(st_new(82), {"capcut_speaker": "es_11"})
    raise SystemExit("503 của cả máy phải dừng bước giọng đọc")
except RuntimeError as e:
    assert "stopped at shot" in str(e) and single_calls == [] and len(batch_calls) == 1, (e, single_calls)

# 8d. một đợt hỏng (502) → chỉ shot của đợt đó đọc từng cái, đợt sau vẫn theo đợt
batch_calls.clear(); single_calls.clear()


def first_batch_fails(path, payload, timeout=300):
    batch_calls.append((payload, timeout))
    if len(batch_calls) == 1:
        raise RuntimeError(f"{path} → HTTP 502: CapCut không đọc được đợt này")
    return batch_resp(payload)


P._post = first_batch_fails
st8 = st_new(83)
P._tts_capcut(st8, {"capcut_speaker": "es_11"})
assert len(batch_calls) == 2 and len(single_calls) == len(batch_calls[0][0]["texts"]), (len(batch_calls), len(single_calls))
assert st8["tts_summary"] == "19 voiced (CapCut), 1 silent", st8["tts_summary"]

# 8e. giọng sami (có mốc từng từ) và 8f. không tra được engine → giữ đường từng shot
for label, getter, spk in (
    ("sami", lambda path, timeout=60: [{"id": "es_sami", "name": "Enrique", "language": "es", "platform": ""}], "es_sami"),
    ("lookup down", lambda path, timeout=60: (_ for _ in ()).throw(RuntimeError("speakers → HTTP 502: down")), "es_11"),
):
    batch_calls.clear(); single_calls.clear()
    P._get = getter
    P._post = fake_batch
    st8 = st_new(84)
    P._tts_capcut(st8, {"capcut_speaker": spk})
    assert batch_calls == [] and len(single_calls) == 19, (label, len(batch_calls), len(single_calls))

# 8g. gom đợt: trần số shot, trần ký tự, shot quá dài đứng riêng
items = [(1, {}, "a" * 50), (2, {}, "b" * 2000), (3, {}, "c" * 50)] + [(k, {}, "d") for k in range(4, 40)]
assert [len(g) for g in P._capcut_batches(items, max_shots=16, max_chars=1800)] == [1, 1, 16, 16, 5]

# 8h. tự chọn giọng ghi luôn engine → không phải tra lại
seen_state = {}
orig_tts_capcut = P._tts_capcut
P._tts_capcut = lambda st, opt: seen_state.update(st)
P.installed_extensions = lambda: {"capcut_tts": True}
P._capcut_account = lambda preferred="": "a@x.com"
P._get = lambda path, timeout=60: ELEVEN
P._step_tts({"language": "es", "_cancelled": lambda: False, "_say": lambda *a: None}, {"tts_engine": "capcut"})
P._tts_capcut = orig_tts_capcut
assert seen_state.get("capcut_speaker") == "es_11" and seen_state.get("capcut_platform") == "11labs", seen_state
print("8 capcut batch: giọng 11labs đọc theo đợt (≤16 shot/≤1800 ký tự), shot hỏng đọc riêng, route cũ → từng shot, 503 dừng, sami giữ mốc")

# ── 9. giọng sami có mốc HỎNG (giọng ICL tiếng Nhật, đo thật 17/9/2026) → bỏ mốc, phần còn lại đọc theo đợt ──
# User: "giúp tôi xem logic tiếng nhật trung hàn, gom nhóm voice lại chưa có thì phải, vẫn làm từng câu".
JA_BAD = [{"word": c, "start": round(k * 0.03, 3), "end": round(k * 0.03 + 0.03, 3)} for k, c in enumerate("だからこそ水は道に近い")]
JA_BAD[3]["start"], JA_BAD[3]["end"] = 1.635, 1.665
ZH_GOOD = [{"word": c, "start": round(0.17 + k * 0.32, 2), "end": round(0.17 + k * 0.32 + 0.3, 2)} for k, c in enumerate("老子说上善若水水善利万物")]
assert P._marks_reliable(JA_BAD) is False and P._marks_reliable(ZH_GOOD) is True, "ngưỡng mốc: Nhật ICL hỏng, Trung tốt"
assert P._marks_reliable(JA_BAD[:3]) is True and P._marks_reliable([]) is True, "quá ít mốc thì không chê"
P._get = lambda path, timeout=60: [{"id": "ja_icl", "name": "Yukiko", "language": "ja", "platform": ""}]
said9 = []


def st9(ep):
    st = st_new(ep)
    st["_say"] = lambda *a: said9.append(a)
    return st


tmp9 = tempfile.mkdtemp(prefix="cv-marks-")
CFG.DATA_DIR = tmp9
for label, words, want_single, want_batch_texts in (("mốc hỏng", JA_BAD, 2, 18), ("mốc tốt", ZH_GOOD, 19, 0)):
    batch_calls.clear(); single_calls.clear(); puts8.clear(); said9.clear()
    P._post = fake_batch
    P._post_audio_marks = (lambda w: (lambda path, payload, timeout=180:
                                      (single_calls.append(payload) or (b"ID3" + b"\x02" * 2000), list(w))))(words)
    ep = 90 if label == "mốc hỏng" else 91
    st = st9(ep)
    P._tts_capcut(st, {"capcut_speaker": "ja_icl"})
    texts = [t for c in batch_calls for t in c[0]["texts"]]
    assert len(single_calls) == want_single and len(texts) == want_batch_texts, (label, len(single_calls), len(texts))
    assert st["tts_summary"] == "19 voiced (CapCut), 1 silent", (label, st["tts_summary"])
    side = os.path.join(tmp9, "content_video", "audio", f"ep{ep}", "shot001.mp3.words.json")
    if label == "mốc hỏng":
        assert not os.path.exists(side), "mốc hỏng KHÔNG được ghi sidecar (phụ đề sẽ tô sai chữ)"
        assert any("reading the remaining shots in batches" in str(a[2]) for a in said9), said9
        assert any("· CapCut · batch" in str(a[2]) for a in said9 if len(a) > 2), "thẻ bước ghi · batch"
        assert texts[0].startswith("Escena 2.") and "Escena 7." in " ".join(texts), "đợt bắt đầu từ shot kế tiếp"
    else:
        assert os.path.exists(side), "mốc tốt (Trung/Hàn/Việt) vẫn ghi sidecar cho phụ đề chạy chữ"
        assert not any("in batches" in str(a[2]) for a in said9), said9

# 9c. chuyển sang đợt mà CapCut cũ chưa có route đợt (404) → đọc từng shot phần còn lại, KHÔNG lặp chuyển mãi
batch_calls.clear(); single_calls.clear(); puts8.clear()
P._post = batch_404
P._post_audio_marks = lambda path, payload, timeout=180: (single_calls.append(payload) or (b"ID3" + b"\x02" * 2000), list(JA_BAD))
st = st9(92)
P._tts_capcut(st, {"capcut_speaker": "ja_icl"})
assert len(batch_calls) == 1 and len(single_calls) == 19 and st["tts_summary"] == "19 voiced (CapCut), 1 silent", \
    (len(batch_calls), len(single_calls), st["tts_summary"])
print("9 capcut marks: mốc hỏng (ICL tiếng Nhật 30 ms/chữ) → bỏ mốc + đọc phần còn lại theo đợt; mốc tốt giữ từng shot; CapCut cũ → từng shot")
print()
print("ALL 9 GROUPS PASSED")
