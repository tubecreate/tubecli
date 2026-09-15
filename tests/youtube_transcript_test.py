# -*- coding: utf-8 -*-
"""Phụ đề YouTube làm nguyên liệu kịch bản — tubecli/core/youtube_transcript.py (15/9/2026).

Không ra mạng: yt-dlp, tải track và lớp cookie đều được giả.

Kiểm:
  A. nhận diện: watch?v= / youtu.be / shorts / live / embed / tham số đứng trước v=; link + vài chữ vẫn là link;
     bài viết có lẫn link KHÔNG phải link (lối cũ giữ nguyên)
  B. chọn track: tải lên theo ngôn ngữ gốc > tự động gốc (-orig) > tự động dịch; json3 trước vtt; không có → None
  C. đọc: json3 chèn dấu cách ở "\\n" (hết "casisin"), bỏ [Música]; vtt bỏ dòng cuộn trùng và thẻ
  D. fetch_transcript: ok kèm words/minutes/title/channel; cache 1 giờ; không có phụ đề / bị đòi đăng nhập /
     thiếu yt-dlp → ok False với câu chỉ đường; public_info không có text
  E. cookie khi YouTube đòi đăng nhập (lõi .97): không cookie trước; bị chặn mới thử cookie dán tay → hồ sơ
     browser ĐANG MỞ (tối đa 2, kèm proxy của hồ sơ, file tạm luôn bị xoá) → trình duyệt cài trên máy; tuỳ chọn
     tắt / chỉ có hồ sơ đang tắt / lỗi không phải chặn → câu chỉ đường đúng tình huống, không đụng cookie

Run:  python tests/youtube_transcript_test.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.core import youtube_transcript as Y  # noqa: E402
from tubecli.core import youtube_cookies as YC  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


# Lớp cookie giả: KHÔNG đọc cài đặt / hồ sơ browser thật của máy chạy test.
COOKIE_STATE = {"settings": {"auto": True, "profile": "", "pasted": False, "browser": ""},
                "plan": {"live": [], "closed": []}}
YC.settings = lambda: dict(COOKIE_STATE["settings"])
YC.plan = lambda preferred="": {k: list(v) for k, v in COOKIE_STATE["plan"].items()}
YC.export_attempt = lambda name: (None, "not used in this group")
YC.remove_file = lambda path: None
Y._cookie_file = lambda: None

print("── A. nhận diện link ───────────────────────────────────────")
ok(Y.youtube_ids("https://www.youtube.com/watch?v=4Br45kOed_s") == ["4Br45kOed_s"], "watch?v=")
ok(Y.youtube_ids("https://youtu.be/4Br45kOed_s?si=x") == ["4Br45kOed_s"], "youtu.be")
ok(Y.youtube_ids("https://www.youtube.com/shorts/abcdefghijk https://youtube.com/live/ABCDEFGHIJK") == ["abcdefghijk", "ABCDEFGHIJK"], "shorts + live")
ok(Y.youtube_ids("https://www.youtube.com/watch?feature=share&v=4Br45kOed_s&t=10") == ["4Br45kOed_s"], "tham số đứng trước v=")
ok(Y.youtube_ids("https://youtu.be/4Br45kOed_s https://youtu.be/4Br45kOed_s") == ["4Br45kOed_s"], "không trùng")
ok(Y.link_only("https://www.youtube.com/watch?v=4Br45kOed_s") == ["4Br45kOed_s"], "chỉ link → link")
ok(Y.link_only("video tham khảo kênh Paz en el Tao:\nhttps://youtu.be/4Br45kOed_s") == ["4Br45kOed_s"], "link + vài chữ ghi chú → vẫn là link")
article = ("La calma ordena tu vida. " * 10) + "Mira este vídeo https://youtu.be/4Br45kOed_s para más."
ok(Y.link_only(article) == [], "bài viết có lẫn link → KHÔNG phải link (lối cũ)")
ok(Y.link_only("Hola, esto es un texto sin enlaces") == [], "không link → []")
ok(Y.count_words("Hola mundo, esto es una prueba.") == 6 and Y.count_words("你好世界") == 2, "count_words khớp content_words")

print("── B. chọn track ───────────────────────────────────────────")
J = lambda: [{"ext": "vtt", "url": "u-vtt"}, {"ext": "json3", "url": "u-json3"}]
info = {"language": "es-US", "subtitles": {}, "automatic_captions": {"en": J(), "es-orig": J(), "es": J(), "vi": J()}}
ok(Y.pick_track(info, "vi")[:2] == ("es-orig", "auto") and Y.pick_track(info)[2]["ext"] == "json3", "chỉ có tự động → es-orig (gốc), json3 trước vtt", Y.pick_track(info))
info2 = {"language": "es", "subtitles": {"en": J(), "es-419": J()}, "automatic_captions": {"es-orig": J()}}
ok(Y.pick_track(info2)[:2] == ("es-419", "manual"), "có tải lên đúng ngôn ngữ gốc → thắng tự động", Y.pick_track(info2))
info3 = {"language": "", "subtitles": {"en": [{"ext": "vtt", "url": "x"}]}, "automatic_captions": {}}
ok(Y.pick_track(info3)[:2] == ("en", "manual"), "không biết ngôn ngữ gốc → tải lên bất kỳ")
ok(Y.pick_track({"language": "es", "subtitles": {"live_chat": J()}, "automatic_captions": {}}) is None, "chỉ có live_chat → None")
ok(Y.pick_track({"language": "es", "subtitles": {"es": [{"ext": "ttml", "url": "x"}]}}) is None, "định dạng không đọc được → None")

print("── C. đọc phụ đề ───────────────────────────────────────────")
j3 = {"events": [{"segs": [{"utf8": "¿Por qué hay personas que consiguen casi"}, {"utf8": "\n"}, {"utf8": "sin esfuerzo"}]},
                 {"segs": [{"utf8": "[Música]"}]}, {"segs": [{"utf8": "aquello que tú llevas &amp; años"}]}]}
t = Y.parse_json3(j3)
ok(t == "¿Por qué hay personas que consiguen casi sin esfuerzo aquello que tú llevas & años", "json3: dấu cách ở chỗ ngắt, bỏ [Música], giải &amp;", t)
vtt = ("WEBVTT\nKind: captions\nLanguage: es\n\n00:00:00.000 --> 00:00:02.000 align:start\n"
       "La calma<00:00:01.000><c> no</c>\n\n00:00:02.000 --> 00:00:04.000\nLa calma no\nllega sola\n")
ok(Y.parse_vtt(vtt) == "La calma no llega sola", "vtt: bỏ thẻ thời gian, bỏ dòng cuộn trùng", Y.parse_vtt(vtt))

print("── D. fetch_transcript ─────────────────────────────────────")
body = {"events": [{"segs": [{"utf8": " ".join(["palabra"] * 300)}]}]}
calls = {"extract": 0, "get": 0}


def fake_extract(url, timeout, **kw):
    calls["extract"] += 1
    return {"title": "La Calma", "channel": "Paz en el Tao", "duration": 2229, "language": "es",
            "automatic_captions": {"es-orig": [{"ext": "json3", "url": "https://sub/json3"}]}}


def fake_get(url, timeout):
    calls["get"] += 1
    return json.dumps(body).encode("utf-8")


Y._ydl_extract, Y._http_get = fake_extract, fake_get
Y._CACHE.clear()
r = Y.fetch_transcript("https://www.youtube.com/watch?v=4Br45kOed_s")
ok(r["ok"] and r["words"] == 300 and r["minutes"] == 2.0 and r["title"] == "La Calma" and r["channel"] == "Paz en el Tao"
   and r["language"] == "es-orig" and r["kind"] == "auto" and r["url"].endswith("4Br45kOed_s"), "ok kèm words/minutes/title/channel/track", {k: r.get(k) for k in ("ok", "words", "minutes", "language", "kind")})
r2 = Y.fetch_transcript("4Br45kOed_s")
ok(r2["ok"] and calls == {"extract": 1, "get": 1}, "lần hai (id trần) lấy từ cache, không gọi lại", calls)
ok("text" not in Y.public_info(r) and Y.public_info(r)["words"] == 300 and Y.public_info(r)["cookie_source"] == "", "public_info bỏ text, có cookie_source")
Y._CACHE.clear()
Y._ydl_extract = lambda url, timeout, **kw: {"language": "es", "subtitles": {}, "automatic_captions": {}}
r = Y.fetch_transcript("https://youtu.be/abcdefghijk")
ok(not r["ok"] and "no subtitles" in r["message"], "không có phụ đề → câu chỉ đường", r)


def bot(url, timeout, **kw):
    raise RuntimeError("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies")


Y._ydl_extract = bot
r = Y.fetch_transcript("https://youtu.be/abcdefghijk")
ok(not r["ok"] and "cookies" in r["message"] and "Video Downloader" in r["message"] and "sign in" in r["message"], "bị đòi đăng nhập → gợi ý cookie", r)


def no_ytdlp(url, timeout, **kw):
    raise ImportError("No module named 'yt_dlp'")


Y._ydl_extract = no_ytdlp
r = Y.fetch_transcript("https://youtu.be/abcdefghijk")
ok(not r["ok"] and "pip install yt-dlp" in r["message"], "thiếu yt-dlp → câu chỉ đường", r)
Y._ydl_extract = fake_extract
Y._http_get = lambda url, timeout: json.dumps({"events": [{"segs": [{"utf8": "hola"}]}]}).encode()
r = Y.fetch_transcript("https://youtu.be/abcdefghijk")
ok(not r["ok"] and "almost empty" in r["message"], "phụ đề gần rỗng → ok False", r)
ok(Y.fetch_transcript("không phải link")["ok"] is False, "không phải link → ok False")

print("── E. cookie khi YouTube đòi đăng nhập ─────────────────────")
BOT = "ERROR: [youtube] 4Br45kOed_s: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"
attempts, exports, removed = [], [], []


def make_extract(outcomes):
    """outcomes: nguồn → "ok" | câu lỗi; nguồn = "none" | đường file cookie | "browser:<tên>". Thiếu = bị chặn."""
    def ext(url, timeout, cookiefile=None, proxy=None, browser=""):
        src = ("browser:" + browser) if browser else (cookiefile or "none")
        attempts.append((src, proxy))
        out = outcomes.get(src, BOT)
        if out != "ok":
            raise RuntimeError(out)
        return fake_extract(url, timeout)
    return ext


def fake_export(name):
    exports.append(name)
    if name == "unreadable":
        return None, "could not read its cookies (boom)"
    return {"profile": name, "cookiefile": f"cookies-{name}.txt",
            "proxy": "http://u:p@h:1" if name == "proxied" else None, "count": 9}, ""


def run_case(settings, plan, outcomes, pasted=None):
    Y._CACHE.clear()
    attempts.clear(), exports.clear(), removed.clear()
    COOKIE_STATE["settings"] = {"auto": True, "profile": "", "pasted": False, "browser": "", **settings}
    COOKIE_STATE["plan"] = {"live": [], "closed": [], **plan}
    Y._cookie_file = lambda: pasted
    Y._ydl_extract = make_extract(outcomes)
    return Y.fetch_transcript("https://youtu.be/4Br45kOed_s")


YC.export_attempt = fake_export
YC.remove_file = lambda path: removed.append(path)
Y._http_get = fake_get

r = run_case({}, {"live": ["p1"]}, {"none": "ok"})
ok(r["ok"] and r["cookie_source"] == "" and attempts == [("none", None)] and not exports, "tải được không cookie → không đụng hồ sơ nào", (attempts, exports))
r = run_case({}, {"live": ["proxied"]}, {"cookies-proxied.txt": "ok"})
ok(r["ok"] and r["cookie_source"] == "profile:proxied" and attempts[1] == ("cookies-proxied.txt", "http://u:p@h:1")
   and removed == ["cookies-proxied.txt"], "bị chặn → cookie hồ sơ đang mở, đi qua proxy của hồ sơ, file tạm bị xoá", (attempts, removed))
r = run_case({}, {"live": ["p1", "p2", "p3"]}, {"cookies-p1.txt": "ERROR: [youtube] x: The page needs to be reloaded.", "cookies-p2.txt": "ok"})
ok(r["ok"] and r["cookie_source"] == "profile:p2" and exports == ["p1", "p2"] and removed == ["cookies-p1.txt", "cookies-p2.txt"],
   "cookie hồ sơ 1 hỏng → sang hồ sơ 2; cả hai file đều bị xoá", (exports, removed))
r = run_case({}, {"live": ["p1", "p2", "p3"]}, {})
ok(not r["ok"] and exports == ["p1", "p2"] and "refused the cookies of p1, p2" in r["message"], "tối đa 2 hồ sơ mỗi lượt; vẫn bị chặn → nói hồ sơ nào bị từ chối", (exports, r["message"]))
r = run_case({"pasted": True}, {"live": ["p1"]}, {"pasted.txt": "ok"}, pasted="pasted.txt")
ok(r["ok"] and r["cookie_source"] == "pasted" and not exports and removed == [], "cookie dán tay đi trước hồ sơ, KHÔNG bị xoá", (exports, removed))
r = run_case({"auto": False, "browser": "firefox"}, {"live": ["p1"]}, {"browser:firefox": "ok"})
ok(r["ok"] and r["cookie_source"] == "browser:firefox" and not exports, "tuỳ chọn tự động tắt → không đọc hồ sơ; trình duyệt cài trên máy vẫn thử", exports)
r = run_case({"auto": False}, {"live": ["p1"]}, {})
ok(not r["ok"] and "Turn on «Auto cookies" in r["message"] and "Video Downloader" in r["message"] and not exports, "tắt + không nguồn nào → chỉ chỗ bật", r["message"])
r = run_case({}, {"closed": ["alpha", "beta"]}, {})
ok(not r["ok"] and "Open a browser profile" in r["message"] and "alpha, beta" in r["message"] and not exports, "chỉ có hồ sơ đang tắt → bảo mở hồ sơ nào, không dùng cookie cũ", r["message"])
r = run_case({}, {"live": ["unreadable"]}, {})
ok(not r["ok"] and "Could not read YouTube cookies from the open browser profile(s) unreadable" in r["message"] and removed == [], "hồ sơ đang mở mà không đọc được cookie → nói đúng thế", r["message"])
r = run_case({}, {"live": ["p1"]}, {"none": "ERROR: [youtube] 4Br45kOed_s: Private video. Sign in if you've been granted access"})
ok(not r["ok"] and "private" in r["message"] and not exports and len(attempts) == 1, "lỗi không phải chặn (video riêng tư) → không thử cookie", (attempts, r["message"]))
r = run_case({}, {}, {"none": "ERROR: [youtube] 4Br45kOed_s: Sign in to confirm your age. This video may be inappropriate"})
ok(not r["ok"] and r["message"].startswith("The video is age-restricted.") and "No browser profile is logged into YouTube" in r["message"], "giới hạn tuổi cũng là chặn, câu mở đầu đúng", r["message"])

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
ok('"yt-dlp' in pyproject, "pyproject.toml có yt-dlp (máy cập nhật tự cài)")

print()
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
