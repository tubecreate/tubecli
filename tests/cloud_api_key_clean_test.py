# -*- coding: utf-8 -*-
"""Khoá API lẫn chữ tiếng Việt bị chặn lúc lưu và không đưa ra dùng (25/9/2026).

VÌ SAO CÓ FILE NÀY
  Máy khách lưu khoá EverAI có «ú» (bộ gõ Telex ghép chữ lúc dán) ⇒ 287 nhịp đọc giọng hỏng với lỗi
  «'ascii' codec can't encode character '\xfa' in position 10» — không ai đoán ra là do khoá.

Run:  python tests/cloud_api_key_clean_test.py   (exit 0 = pass) — file khoá TẠM, không đụng khoá thật.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.extensions.cloud_api.extension import KeyManager, clean_key  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


ok(clean_key("  sk-abc_123​\n") == ("sk-abc_123", ""), "bỏ khoảng trắng, xuống dòng, ký tự vô hình")
ok(clean_key('"sk-abc"')[0] == "sk-abc", "bỏ ngoặc bao quanh khi dán cả dấu ngoặc")
v, err = clean_key("sk_úabc")
ok(err and "«ú»" in err and "Vietnamese keyboard" in err, "chữ có dấu → lỗi nói rõ ký tự + cách sửa", err)

tmp = tempfile.mkdtemp(prefix="keys_")
f = os.path.join(tmp, "keys.json")
km = KeyManager(f)
r = km.add_key("everai", "abcúdef123")
ok(r["status"] == "error" and "«ú»" in r["message"], "lưu khoá có «ú» → TỪ CHỐI, không ghi", r)
ok(km.get_active_key("everai") in (None, ""), "khoá bị từ chối không nằm trong kho")
r = km.add_key("everai", "  goodKEY123  ")
ok(r["status"] == "success" and km.get_active_key("everai") == "goodKEY123", "khoá đúng: lưu bản đã làm sạch", r)

# khoá lưu SAI từ trước khi có chốt chặn (như máy khách 28)
json.dump({"everai": {"old": {"key": "abcúdef", "active": True}}}, open(f, "w", encoding="utf-8"), ensure_ascii=False)
km2 = KeyManager(f)
ok(km2.get_active_key("everai") in (None, ""), "khoá cũ có «ú» → không đưa ra dùng (hết lỗi 'ascii' codec)")
st = km2.list_keys("everai")["everai"]["old"]
ok(st["active"] is False and "«ú»" in st["disable_reason"], "khoá cũ bị tắt, bảng Stored Keys hiện lý do", st)
r = km2.add_cloudflare_key("tokén", "acc123")
ok(r.get("status") == "error", "Cloudflare token có chữ có dấu → từ chối", r)

print(f"\n{PASS}/{PASS + FAIL} PASS" if not FAIL else f"\n{PASS}/{PASS + FAIL} PASS — {FAIL} HỎNG")
sys.exit(1 if FAIL else 0)
