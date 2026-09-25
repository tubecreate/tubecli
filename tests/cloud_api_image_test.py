# -*- coding: utf-8 -*-
"""Nút Test trong Cloud API Keys nhận ra model VẼ ẢNH (25/9/2026).

Trước đây mọi model đi vào /chat/completions — máy khách test cx/gpt-image-2 «không được» dù model vẫn tốt.
Nay model ảnh vẽ thử một tấm qua bộ vẽ của lõi (đúng /images/generations), không đường lùi.

Run:  python tests/cloud_api_image_test_test.py   (exit 0 = pass) — không mạng.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.extensions.cloud_api.routes import is_image_model  # noqa: E402

PASS = FAIL = 0
for model, want in [("cx/gpt-image-2", True), ("ag/gemini-3.1-flash-image", True), ("gemini-2.5-flash-image", True),
                    ("@cf/black-forest-labs/flux-1-schnell", True), ("@cf/stabilityai/stable-diffusion-xl-base-1.0", True),
                    ("@cf/leonardo/phoenix-1.0", True), ("cx/gpt-5.5-review", False), ("ag/gemini-3.8-flash", False),
                    ("ag/claude-sonnet-4-6", False), ("@cf/meta/llama-3.1-8b-instruct", False)]:
    got = is_image_model(model)
    if got == want:
        PASS += 1
        print("  ok  ", model, "→", "ảnh" if got else "chat")
    else:
        FAIL += 1
        print("  FAIL", model, got)
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tubecli", "extensions", "cloud_api",
                        "routes.py"), encoding="utf-8").read()
ok = 'r.pop("fallback", None)' in src and "is_image_model(req.model)" in src
PASS += ok
FAIL += not ok
print("  ok  " if ok else "  FAIL", "test ảnh bỏ đường lùi, route test-model rẽ nhánh ảnh")
print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
