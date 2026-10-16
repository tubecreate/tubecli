# -*- coding: utf-8 -*-
"""Ô «Scenes» của form video Codex (user 12/10/2026: «thêm option chọn tạo video hoặc dùng ảnh tĩnh»).

Cam kết được canh ở đây:
  1. options.scene_media = "stills" → drama Content Studio mang clip_mode "hook" (trần clip cảnh 0) + hook_video ""
     (không clip mở đầu) — ĐÈ lên metadata của mẫu (mẫu Kiếm Lai bật clip).
  2. Bỏ trống → metadata của mẫu giữ nguyên (không lén tắt clip của ai).
  3. Studio đọc đúng hai khoá ấy: engines/key_scenes.plan cho trần 0 khi clip_mode "hook".
  4. Form Codex gửi scene_media và nhớ lựa chọn (kiểm theo mã nguồn).
Không gọi HTTP thật: _post bị thay, lượt chạy dừng ngay sau khi tạo drama.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label)


class Stop(Exception):
    pass


def drama_meta(options):
    """Metadata drama mà _step_studio gửi đi (mẫu bật clip: clip_mode important, hook_video cinematic)."""
    sent = {}

    def fake_post(path, payload, timeout=300):
        if path == "/api/v1/studio/dramas":
            sent.update(payload)
            raise Stop()
        raise AssertionError(f"unexpected POST {path}")
    real_post, real_meta = P._post, P._task_meta
    P._post, P._task_meta = fake_post, (lambda *a, **k: None)
    try:
        state = {"agent": SimpleNamespace(id="a1", name="Agent"), "checkpoint": {}, "title": "T", "language": "vi",
                 "preset": {"name": "Ink Wash Film · Kiếm Lai (tiếng Việt)",
                            "fields": {"style": "ink", "metadata": {"clip_mode": "important", "hook_video": "cinematic",
                                                                    "tts_voice": "vi_female_thuytrang_mb",
                                                                    "tts_engine": "everai"}}}}
        try:
            P._step_studio(state, dict(P.DEFAULTS, **options))
        except Stop:
            pass
    finally:
        P._post, P._task_meta = real_post, real_meta
    return sent.get("metadata") or {}


print("1. stills → không clip nào")
m = drama_meta({"scene_media": "stills"})
ok(m.get("clip_mode") == "hook" and m.get("hook_video") == "", f"drama: clip_mode hook + hook_video rỗng ({m.get('clip_mode')!r}, {m.get('hook_video')!r})")
ok(m.get("tts_voice") == "vi_female_thuytrang_mb", "các khoá khác của mẫu giữ nguyên (giọng)")
ok(P._scene_media_meta({"scene_media": " Stills "}) == {"clip_mode": "hook", "hook_video": ""}, "không phân biệt hoa thường / khoảng trắng")

print("2. bỏ trống → theo mẫu")
m = drama_meta({})
ok(m.get("clip_mode") == "important" and m.get("hook_video") == "cinematic", "mẫu bật clip thì vẫn bật")
ok(P.DEFAULTS.get("scene_media") == "", "mặc định = theo mẫu")
ok(P._scene_media_meta({"scene_media": "clips"}) == {}, "giá trị lạ = theo mẫu")

print("3. Studio đọc đúng hai khoá")
studio = ROOT / "data" / "extensions_external" / "content_studio" / "engines"
if (studio / "key_scenes.py").is_file():
    sys.path.insert(0, str(studio))
    import key_scenes as KS  # noqa: E402
    ok(KS.plan({"clip_mode": "hook"}, 25)[0] == 0, "key_scenes.plan: clip_mode hook → trần clip cảnh 0")
    ok(KS.plan({}, 25)[0] == 25, "key_scenes.plan: không khai → trần của style")
    src = (studio / "hook_video.py").read_text(encoding="utf-8")
    ok("def kind_of" in src, "hook_video.kind_of có (clip mở đầu theo metadata hook_video)")
else:
    print("  (bỏ qua — máy này không có Content Studio)")

print("4. form Codex")
js = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.js").read_text(encoding="utf-8")
html = (ROOT / "tubecli" / "extensions" / "codex" / "static" / "codex.html").read_text(encoding="utf-8")
ok('id="cx-v-media"' in html and 'value="stills"' in html, "ô chọn cx-v-media có lựa chọn stills")
ok("options.scene_media = 'stills'" in js, "submitVideo gửi scene_media")
ok("CV_MEDIA_KEY" in js and js.count("CV_MEDIA_KEY") >= 3, "nhớ lựa chọn (khai báo + nạp + lưu)")
import json  # noqa: E402
for lang in ("en", "vi", "es", "ja", "ko", "ru", "tr", "zh", "zh-TW"):
    d = json.loads((ROOT / "tubecli" / "extensions" / "codex" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    ok(all(d.get(k) for k in ("codex.field_video_media", "codex.cv_media_template", "codex.cv_media_stills",
                              "codex.field_video_media_hint")), f"locale {lang} đủ 4 khoá")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
