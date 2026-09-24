# -*- coding: utf-8 -*-
"""Giọng OmniVoice (app desktop OmniVoice Studio, 127.0.0.1:3900) trong dây chuyền video — 24/9/2026.

VÌ SAO CÓ FILE NÀY
  User chọn giọng clone «thuy trang 6» cho bản tiếng Việt. Đo bằng Gemini chép lại lời đọc:
    · thiếu `language` / thiếu lời chép giọng mẫu ⇒ đọc sai thanh, giọng trôi thành nam;
    · đoạn 52 tiếng một lượt ⇒ OmniVoice đặt độ dài quá ngắn, đọc dồn, RƠI MẤT CÂU; cụm ≤24 tiếng thì đúng.
  A. pipeline: preset `tts_engine=omnivoice` đi đường batch-tts (như edge); app tắt ⇒ báo rõ, không chạy 191 nhịp hỏng
  B. engine (tts_vibevoice/engines/omnivoice_engine.py): đoán ngôn ngữ, ước thời lượng, tách cụm câu, ghép WAV

Run:  python tests/content_video_omnivoice_test.py     (exit 0 = pass) — không mạng, không cần OmniVoice.
"""
import importlib.util
import io
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


print("── A. pipeline nhận engine omnivoice ──────────────────────")
import tubecli.extensions.content_video.pipeline as P  # noqa: E402

P.installed_extensions = lambda: {"tts_vibevoice": True, "capcut_tts": True}
P._preset_meta = lambda state: {"tts_engine": "omnivoice", "tts_voice": "2471e659"}
P._omnivoice_up = lambda: True
st = {}
eng = P._tts_engine(st, {"tts_engine": "auto"})
ok(eng == "edge" and st.get("tts_batch_engine") == "omnivoice" and st.get("tts_voice_pref") == "2471e659",
   "preset omnivoice → đường batch-tts của Studio, engine omnivoice, giọng = mã hồ sơ", (eng, st))
P._omnivoice_up = lambda: False
try:
    P._tts_engine({}, {"tts_engine": "auto"})
    ok(False, "OmniVoice Studio tắt phải báo lỗi ngay")
except RuntimeError as e:
    ok("OmniVoice Studio is not running" in str(e) and "Retry" in str(e),
       "app tắt → báo rõ phải mở OmniVoice Studio rồi Retry (không đọc 191 nhịp hỏng)", e)
P._preset_meta = lambda state: {"tts_engine": "everai", "tts_voice": "vi_male_onyx_default"}
P._everai_key = lambda: True
st3 = {}
ok(P._tts_engine(st3, {}) == "edge" and st3.get("tts_batch_engine") == "everai"
   and st3.get("tts_voice_pref") == "vi_male_onyx_default",
   "preset EverAI (Onyx) → đường batch-tts, engine everai", st3)
P._everai_key = lambda: False
try:
    P._tts_engine({}, {})
    ok(False, "thiếu khoá EverAI phải báo lỗi ngay")
except RuntimeError as e:
    ok("EverAI API key" in str(e), "thiếu khoá EverAI → báo rõ thêm khoá rồi Retry", e)
P._preset_meta = lambda state: {"tts_engine": "edge", "tts_voice": ""}
st2 = {}
ok(P._tts_engine(st2, {}) == "edge" and st2.get("tts_batch_engine") == "edge", "edge vẫn như cũ", st2)
import types as _types  # noqa: E402
import importlib as _il  # noqa: E402
_fresh = _il.reload(_il.import_module("tubecli.extensions.content_video.pipeline"))


def _probe(code, body):
    import requests as _rq
    _orig = _rq.get
    _rq.get = lambda *a, **k: _types.SimpleNamespace(status_code=code, json=lambda: body)
    try:
        return _fresh._omnivoice_up()
    finally:
        _rq.get = _orig
ok(_probe(200, {"status": "idle", "loaded": False, "detail": "Model ready", "error": None}) is True,
   "app mở nhưng đã NHẢ model khi rảnh (loaded=false) → vẫn tính là chạy (model tự nạp lượt đầu) — lỗi #110")
ok(_probe(200, {"status": "ready", "loaded": True}) is True, "model đang nạp sẵn → chạy")
ok(_probe(200, {"status": "error", "loaded": False, "error": "CUDA out of memory"}) is False, "app báo lỗi model → không chạy")
ok(_probe(500, {}) is False, "app trả 500 → không chạy")
src = open(P.__file__, encoding="utf-8").read()
ok('"http://127.0.0.1:3900/model/status"' in src, "hỏi app ở 127.0.0.1 (không localhost — Windows hay thử ::1)")

print("── B. engine OmniVoice của tts_vibevoice ───────────────────")
ENG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "extensions_external",
                   "tts_vibevoice", "engines", "omnivoice_engine.py")
if not os.path.isfile(ENG):
    print("  (máy này không có tts_vibevoice — bỏ qua)")
else:
    spec = importlib.util.spec_from_file_location("omnivoice_engine_t", ENG)
    O = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(O)
    ok(O.API_BASE == "http://127.0.0.1:3900" and O.GENERATE_TIMEOUT_S >= 300, "127.0.0.1, chờ ≥ 300 s")
    ok(O.language_of("Bạn sẽ không ngủ.") == "Vietnamese" and O.language_of("ある火曜日") == "Japanese"
       and O.language_of("Hello") is None and O.language_of("Chỉ vậy thôi") == "Vietnamese",
       "đoán ngôn ngữ theo chữ; tiếng Anh để trống cho model tự đoán")
    T = "Bạn sẽ không ngủ. Không gây mê toàn thân. Chỉ một mũi thuốc tê ở cổ tay, hoặc ở bẹn."
    d = O.vi_duration(T)
    ok(abs(d - (20 / 3.2 + 0.25 * 3 + 0.12 * 1)) < 0.02, "thời lượng = tiếng/3,2 + 0,25/dấu chấm + 0,12/dấu phẩy "
       "(20 tiếng, 3 dấu chấm, 1 dấu phẩy)", d)
    L = ("Cho tôi kể bạn nghe về một buổi chiều thứ Ba. Buổi chiều đã thay đổi cách tôi nghĩ về nghề bác sĩ của mình. "
         "Một người đàn ông bảy mươi hai tuổi, nguyên là giáo viên dạy văn cấp hai.")
    parts = O.split_sentences(L)
    ok(len(parts) == 3 and all(len(p.split()) <= 24 for p in parts) and " ".join(parts) == L,
       "đoạn dài tách thành cụm ≤24 tiếng, không cắt giữa câu, ghép lại đúng nguyên văn", parts)
    ok(O.split_sentences("Ngắn thôi.") == ["Ngắn thôi."] and O.split_sentences("A. B. C.") == ["A. B. C."],
       "câu ngắn giữ một cụm")

    class _E(O.OmniVoiceTTSEngine):
        def _resolve_clean_instruct(self, voice_id):
            return " "
    pl = _E()._payload("Chỉ vậy thôi.", "2471e659", 2.0, None)
    ok(pl["language"] == "Vietnamese" and pl["duration"] == O.vi_duration("Chỉ vậy thôi.") and pl["profile_id"] == "2471e659",
       "payload tiếng Việt có language + duration", pl)
    ok("duration" not in _E()._payload("Hello there.", "x", 2.0, None), "tiếng Anh không ép thời lượng")

    def wav(n, sr=24000):
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(b"\x01\x00" * n)
        return b.getvalue()
    j = O.join_wavs([wav(1000), wav(500)])
    with wave.open(io.BytesIO(j)) as w:
        frames, sr = w.getnframes(), w.getframerate()
    ok(sr == 24000 and frames == 1000 + 500 + int(24000 * O.CHUNK_GAP_S), "ghép WAV: đủ khung + khoảng lặng giữa cụm", frames)
    try:
        O.join_wavs([wav(10), wav(10, 16000)])
        ok(False, "khác khuôn WAV phải báo lỗi")
    except ValueError:
        ok(True, "hai cụm khác khuôn WAV → báo lỗi, không ghép ra tiếng méo")

    # Nắn nhịp (user 24/9/2026: «voice nghe được mà nó giật giật» — lặng giữa câu 0,6–0,9 s, giữa nhịp 0,35 s).
    from array import array
    SR = 24000

    def tone(s):
        return array("h", [9000 if (i // 20) % 2 else -9000 for i in range(int(SR * s))])

    def quiet(s):
        return array("h", bytes(2 * int(SR * s)))
    pcm = quiet(0.4) + tone(1.0) + quiet(0.8) + tone(0.5) + quiet(0.12) + tone(0.5) + quiet(0.6)
    got = O.tighten_pcm(pcm, SR)
    want = O.EDGE_LEAD_S + (1.0 + 0.04) + O.PAUSE_S + (0.5 + 0.12 + 0.5 + 0.04) + O.EDGE_TAIL_S
    ok(abs(len(got) / SR - want) < 0.03,
       "lặng dài giữa câu → 0,30 s; ngắt ngắn (dấu phẩy, 0,12 s) giữ; đầu 0,10 s, cuối 0,25 s", (len(got) / SR, want))
    _lead = int(SR * O.EDGE_LEAD_S) + int(SR * 0.02)          # đầu lặng + 20 ms lề giữ quanh tiếng
    ok(all(v == 0 for v in got[:_lead]) and got[_lead] != 0,
       "tiếng bắt đầu đúng sau 0,10 s đầu + 20 ms lề (cắt trong vùng lặng, không xén phụ âm đầu)")
    ok(O.tighten_pcm(quiet(1.0), SR) == quiet(1.0), "không có tiếng → giữ nguyên, không xoá sạch")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(400))
    ok(O.tighten_wav_bytes(b.getvalue()) == b.getvalue(), "khuôn khác (stereo) → trả nguyên, không đoán")

print("── C. engine EverAI: hỏi nhanh + một đoạn không qua ffmpeg ──")
TV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "extensions_external", "tts_vibevoice")
EV = os.path.join(TV, "engines", "everai_engine.py")
if not os.path.isfile(EV):
    print("  (máy này không có tts_vibevoice — bỏ qua)")
else:
    import asyncio
    import tempfile
    import types
    spec = importlib.util.spec_from_file_location("everai_engine_t", EV)
    E = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(E)
    ok(E.EVERAI_POLL_S <= 1.0 and E.EVERAI_WAIT_S >= 300,
       "hỏi trạng thái ≤ 1 s một lần (bản cũ 2 s), vẫn chờ tối đa 5 phút", (E.EVERAI_POLL_S, E.EVERAI_WAIT_S))
    calls = {"get": 0}

    class _R:
        def __init__(self, code, data=None, body=b""):
            self.status_code, self._d, self._b, self.text = code, data, body, ""

        def json(self):
            return self._d

        async def aiter_bytes(self):
            yield self._b

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):     # noqa: A002
            return _R(200, {"status": 1, "result": {"request_id": "r1"}})

        async def get(self, url, headers=None):
            calls["get"] += 1
            if calls["get"] < 3:
                return _R(200, {"result": {"status": "mới", "progress": 40}})
            return _R(200, {"result": {"status": "hoàn thành", "progress": 100, "audio_link": "https://x/a.mp3"}})

        def stream(self, method, url):
            return _R(200, body=b"ID3" + bytes(1000))

    E.httpx = types.SimpleNamespace(AsyncClient=_C)
    slept = []
    _sleep = asyncio.sleep

    async def _fast(s):
        slept.append(s)
        await _sleep(0)

    class _Eng(E.EverAITTSEngine):
        def _get_api_key(self):
            return "k"
    out = os.path.join(tempfile.mkdtemp(prefix="everai_t_"), "a.mp3")
    asyncio.sleep = _fast
    try:
        res = asyncio.run(_Eng().synthesize_async("Xin chào.", "vi_male_onyx_default", out))
    finally:
        asyncio.sleep = _sleep
    ok(res["status"] == "success" and os.path.getsize(out) == 1003 and calls["get"] == 3,
       "«mới» → «hoàn thành» (trạng thái tiếng Việt) → tải về đúng file", (res, calls))
    ok(slept and set(slept) == {E.EVERAI_POLL_S}, "mỗi lần hỏi cách EVERAI_POLL_S", slept)
    rt = open(os.path.join(TV, "tts_routes.py"), encoding="utf-8").read()
    i = rt.index('elif body.engine == "everai":')
    blk = rt[i:rt.index('background_tasks.add_task(_run_everai)', i)]
    ok("if len(temp_files) == 1:" in blk and "_mv.move(temp_files[0], output_path)" in blk
       and "await asyncio.to_thread(subprocess.check_call" in blk,
       "một đoạn → chuyển thẳng file; nhiều đoạn → ffmpeg chạy ngoài vòng sự kiện (4 làn song song không đứng chờ)")

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
