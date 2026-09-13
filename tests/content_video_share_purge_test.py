# -*- coding: utf-8 -*-
"""Kết quả video có link chia sẻ CÔNG KHAI; xoá task "cả file" dọn đúng file (13/9/2026).

User: "kết quả trả về lưu một file main đã ghép ảnh và audio, và file hoàn chỉnh đã add
layout, ở dạng link share ai xem cũng được — không phải http://127.0.0.1:5295/… vì trên
telegram không xem được". Đối chiếu code thật:
  A. public_host   — học địa chỉ công khai từ lần đăng nhập (Host header + scheme của Origin),
                     bỏ loopback/IP riêng; env TUBECLI_PUBLIC_URL thắng; origin_guard gọi vào
  B. _use_video    — tìm bản chính cạnh bản xuất; tạo link /s/<token> cho cả hai; tuyệt đối
                     khi biết địa chỉ; thẻ kết quả + bản tin Telegram mang link
  C. purge_task_files — xoá ảnh/giọng/phụ đề/video/link chia sẻ trong DATA_DIR, không đụng
                     file ngoài, chỉ ẩn phim do pipeline tạo

Run:  PYTHONIOENCODING=utf-8 python tests/content_video_share_purge_test.py     (exit 0 = pass)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402
from tubecli.core import public_host as PH  # noqa: E402
from tubecli.core import origin_guard as OG  # noqa: E402
from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


TMP = tempfile.mkdtemp(prefix="cv-share-")
CFG.DATA_DIR = TMP
os.environ.pop("TUBECLI_PUBLIC_URL", None)

# ── A. public_host ────────────────────────────────────────────────────────────
print("── A. địa chỉ công khai của máy ─────────────────────────────")
ok(PH.public_base_url() == "", "chưa đăng nhập qua đâu → chưa biết")
ok(PH.remember("http://127.0.0.1:5295", "127.0.0.1:5295") is None and PH.public_base_url() == "", "loopback không tính")
ok(PH.remember("http://192.168.1.20:5295", "192.168.1.20:5295") is None, "IP riêng không tính")
ok(PH.remember("https://cloud.tubecreate.com", "may-cua-toi-41.tubecreate.com") == "https://may-cua-toi-41.tubecreate.com",
   "cloud đăng nhập hộ qua tunnel: host = máy này (Host header), scheme https của Origin")
ok(PH.public_base_url() == "https://may-cua-toi-41.tubecreate.com" and PH.absolute("/s/abc") == "https://may-cua-toi-41.tubecreate.com/s/abc",
   "ghi vào data/public_host.json, absolute() ghép link", PH.public_base_url())
ok(PH.remember("http://43.155.135.49:5295", "43.155.135.49:5295") == "http://43.155.135.49:5295", "VPS IP công khai + cổng")
os.environ["TUBECLI_PUBLIC_URL"] = "https://vps.example.com/"
ok(PH.public_base_url() == "https://vps.example.com", "env TUBECLI_PUBLIC_URL thắng file, bỏ / cuối")
os.environ.pop("TUBECLI_PUBLIC_URL", None)
OG._learned_hosts.clear()
OG.remember_host("https://cloud.tubecreate.com", "vps-9.tubecreate.com")
ok(PH.public_base_url() == "https://vps-9.tubecreate.com", "origin_guard.remember_host (đăng nhập đúng) → ghi địa chỉ công khai")
OG.remember_host("https://evil.example", "vps-10.tubecreate.com")
ok(PH.public_base_url() == "https://vps-9.tubecreate.com", "Origin khác site → không học, không ghi")

# ── B. link chia sẻ trong kết quả ───────────────────────────────────────────
print("── B. link chia sẻ cho bản chính + bản hoàn chỉnh ───────────")
exp = os.path.join(TMP, "content_studio", "outputs", "exports")
os.makedirs(exp)
final = os.path.join(exp, "episode_9_pipeline_export.mp4")
main = os.path.join(exp, "episode_9_pipeline_main.mp4")
for p in (final, main):
    open(p, "wb").write(b"\0" * 4096)
posts = []


def fake_post(path, payload, timeout=300):
    posts.append((path, payload))
    if path == "/api/v1/files/share":
        tok = "tokMAIN" if "main" in payload["path"] else "tokFINAL"
        return {"success": True, "share": {"token": tok, "url_path": "/s/" + tok, "path": payload["path"]}, "created": True}
    raise AssertionError(path)


P._post = fake_post
P.media_seconds = lambda path: 1393.0
st = {"title": "La pregunta", "episode_id": 9}
P._use_video(st, final)
ok(st["video_main_path"] == main, "tìm thấy bản chính cạnh bản xuất")
ok(st["share_links"] == {"final": "https://vps-9.tubecreate.com/s/tokFINAL", "main": "https://vps-9.tubecreate.com/s/tokMAIN"},
   "hai link chia sẻ tuyệt đối, không hết hạn", st["share_links"])
ok(all(p[1]["expires_days"] == 0 for p in posts) and posts[0][1]["name"].startswith("La pregunta"), "gọi File Manager: path + tên + không hạn", posts)
card = P._render_result({**st, "shot_count": 69, "video_seconds": 1393.0, "language": "es"}, {}, [], [], 10.0)
ok("- **Share** (final video, with layout): https://vps-9.tubecreate.com/s/tokFINAL" in card
   and "- **Main video** (images + voice, no layout): https://vps-9.tubecreate.com/s/tokMAIN" in card
   and "127.0.0.1" in card and "relative" not in card, "thẻ kết quả: hai link công khai (+ link cục bộ vẫn còn)", card)
os.remove(main)
os.remove(os.path.join(TMP, "public_host.json"))
st2 = {"title": "T", "episode_id": 9}
P._use_video(st2, final)
ok(st2["video_main_path"] == "" and st2["share_links"] == {"final": "/s/tokFINAL", "relative": True},
   "Studio cũ (không có bản chính) + chưa biết địa chỉ → chỉ link tương đối, đánh dấu", st2["share_links"])
card2 = P._render_result({**st2, "shot_count": 1}, {}, [], [], 1.0)
ok("Share links are relative" in card2 and "TUBECLI_PUBLIC_URL" in card2, "…thẻ chỉ cách có link đầy đủ")
P._post = lambda path, payload, timeout=300: (_ for _ in ()).throw(RuntimeError("HTTP 404"))
st3 = {"title": "T", "episode_id": 9}
P._use_video(st3, final)
ok(st3["share_links"] == {} and "Share" not in P._render_result({**st3, "shot_count": 1}, {}, [], [], 1.0).split("Watch")[1],
   "không có File Manager → không link, không lỗi")
# bản tin Telegram: link công khai đứng đầu query
import tubecli.core.run_log as RL  # noqa: E402
import tubecli.core.run_bulletin as RB  # noqa: E402

got = {}
RL.start = lambda *a, **k: None
RL.launch = lambda run_id, agent_id, behavior="", profile="", query="": got.update(query=query)
RL.end = lambda *a, **k: got.update(work=k.get("work"))
RB.post_end = lambda *a, **k: None


class A:
    id, name = "a1", "MC"


P._bulletin({"agent": A(), "task_id": "t", "title": "La pregunta",
             "share_links": {"final": "https://vps-9.tubecreate.com/s/tokFINAL"}}, "completed", 5.0, "", "render")
ok(got["query"].startswith("https://vps-9.tubecreate.com/s/tokFINAL · La pregunta") and got["work"]["url"] == "https://vps-9.tubecreate.com/s/tokFINAL",
   "bản tin 🔔/Telegram: link chia sẻ đứng trước tiêu đề, work.url là link", got)
P._bulletin({"agent": A(), "task_id": "t", "title": "T", "share_links": {"final": "/s/x", "relative": True}}, "completed", 5.0, "", "render")
ok(got["query"] == "T" and "url" not in got["work"], "link tương đối không vào bản tin (Telegram không mở được)")

# ── C. purge_task_files ──────────────────────────────────────────────────────
print("── C. xoá cả file của một task ──────────────────────────────")
img_dir = os.path.join(TMP, "content_studio", "grok_images")
aud_dir = os.path.join(TMP, "content_video", "audio", "ep9")
sub_dir = os.path.join(TMP, "content_studio", "subtitles")
for d in (img_dir, aud_dir, sub_dir):
    os.makedirs(d, exist_ok=True)
img1 = os.path.join(img_dir, "ep9_shot001.jpg")
img2 = os.path.join(img_dir, "ep9_shot002.jpg")          # shot đã bị thay, không còn trong storyboard
mp3 = os.path.join(aud_dir, "shot001.mp3")
words = mp3 + ".words.json"
ass = os.path.join(sub_dir, "ep9_shot001.ass")
main = os.path.join(exp, "episode_9_pipeline_main.mp4")
other = os.path.join(TMP, "content_studio", "grok_images", "ep8_shot001.jpg")   # tập KHÁC
outside = os.path.join(tempfile.mkdtemp(prefix="cv-outside-"), "user_video.mp4")
for p in (img1, img2, mp3, words, ass, main, other, outside, final):
    open(p, "wb").write(b"\0" * 1000)
P._read_checkpoint = lambda tid: {"episode_id": 9, "drama_id": 3, "video_path": final}
P._storyboards = lambda ep: [{"id": 1, "composed_image": img1, "tts_audio_url": mp3, "subtitle_url": ass, "video_url": outside}]
gets, dels = [], []


def fake_get(path, timeout=60):
    gets.append(path)
    if path == "/api/v1/files/shares":
        return {"shares": [{"token": "tokFINAL", "path": final}, {"token": "tokOTHER", "path": other}]}
    if path == "/api/v1/studio/dramas/3":
        return {"id": 3, "metadata": json.dumps({"source": "content_video", "agent_id": "a1"})}
    if path == "/api/v1/studio/dramas/4":
        return {"id": 4, "metadata": json.dumps({"source": "wizard"})}
    raise AssertionError(path)


P._get = fake_get
P._delete = lambda path, timeout=60: dels.append(path) or {"status": "ok"}
res = P.purge_task_files({"id": "t9"})
ok(res["files"] == 7 and res["bytes"] == 7000 and res["errors"] == [], "xoá 7 file: ảnh (kể cả ảnh mồ côi), mp3 + mốc, phụ đề, bản chính, bản xuất", res)
ok(not any(os.path.exists(p) for p in (img1, img2, mp3, words, ass, main, final)), "…thật sự mất trên đĩa")
ok(os.path.exists(other) and os.path.exists(outside), "tập khác và file NGOÀI data dir để nguyên")
ok(not os.path.isdir(aud_dir), "thư mục giọng rỗng được dọn")
ok(dels == ["/api/v1/files/share/tokFINAL", "/api/v1/studio/dramas/3"] and res["shares"] == 1 and res["drama_hidden"],
   "thu hồi đúng link chia sẻ, ẩn phim do pipeline tạo", dels)
dels.clear()
P._read_checkpoint = lambda tid: {"episode_id": 9, "drama_id": 4}
P._storyboards = lambda ep: []
res = P.purge_task_files({"id": "t9"})
ok(dels == [] and not res["drama_hidden"] and any("not created by this pipeline" in e for e in res["errors"]),
   "phim của người dùng (không phải pipeline tạo) không bị ẩn", res)
P._read_checkpoint = lambda tid: {}
ok(P.purge_task_files({"id": "t0"}) == {"files": 0, "bytes": 0, "episode": None, "drama": None, "drama_hidden": False, "shares": 0, "errors": []},
   "task chưa tới bước Studio → không có gì để xoá")

print()
print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
