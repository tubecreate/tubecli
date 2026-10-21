# -*- coding: utf-8 -*-
"""DÒNG CẢNH BÁO «ẢNH VẼ BẰNG ĐƯỜNG LÙI» trong kết quả task video (21/10/2026).

User: «khi làm ảnh với đường lùi thì hiện thêm thông tin ở phần duyệt để người dùng biết là video sử dụng model fallback
để hoàn thành». Content Studio ghi `fallback_images` {count, total, drew, from} vào lượt vẽ; bước «images» đọc nó.

  A. _fallback_image_warnings: một dòng — bao nhiêu ảnh / tổng, vẽ bằng gì (nhiều nhất trước), vì sao model mẫu hỏng,
     cách sửa; Studio cũ / không ảnh nào lùi / dữ liệu rác ⇒ []
  B. _step_images đưa dòng ấy vào warnings (cùng chỗ với cảnh báo clip Muse)

Run:  python tests/fallback_image_warning_test.py
"""
import sys
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


print("A. _fallback_image_warnings")
w = P._fallback_image_warnings({"fallback_images": {
    "count": 13, "total": 14, "drew": {"cloudflare/@cf/black-forest-labs/flux-1-schnell": 1, "muse/muse-image": 12},
    "from": '9router/cx/gpt-image-2: HTTP 400: {"error":{"message":"No credentials for provider: codex"}}'}})
ok(len(w) == 1, "đúng một dòng", w)
line = w[0] if w else ""
ok(line.startswith("13/14 shot image(s) were drawn with the FALLBACK model"), "nói số ảnh / tổng", line)
ok(line.index("muse/muse-image ×12") < line.index("flux-1-schnell ×1"), "bên vẽ nhiều nhất đứng trước", line)
ok("No credentials for provider: codex" in line and "Settings → AI image" in line, "nói lý do + cách sửa", line)
ok(P._fallback_image_warnings({}) == [] and P._fallback_image_warnings({"fallback_images": {"count": 0}}) == []
   and P._fallback_image_warnings({"fallback_images": "rác"}) == [] and P._fallback_image_warnings(None) == []
   and P._fallback_image_warnings({"fallback_images": {"count": "x"}}) == [], "Studio cũ / không lùi / rác ⇒ []")
ok("a fallback model" in P._fallback_image_warnings({"fallback_images": {"count": 2}})[0], "thiếu `drew` vẫn nói được")

print("B. _step_images")
src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
body = src[src.index("def _step_images("):src.index("def _fallback_image_warnings(")]
ok('state["warnings"].extend(_fallback_image_warnings(data))' in body
   and body.index("_clip_warnings(data)") < body.index("_fallback_image_warnings(data)"), "bước ảnh ghi dòng ấy vào warnings")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
