# -*- coding: utf-8 -*-
"""Vân tay BAS: gọi THẲNG fingerprints.bablosoft.com bằng khoá người dùng, không được mới qua PHP.

Run:  python tests/fingerprint_direct_fallback_test.py     (exit 0 = pass)

User 10/10/2026: «gọi fingerprints.bablosoft.com không được thì mới dùng
api.tubecreate.com/getfinger.php» — «vẫn đẩy key bas lên getfinger.php», «ko có lấy key
mặc định, php nó chỉ là trung gian». Vài máy bị mạng/ISP chặn Bablosoft; trước đây mọi lượt
lấy đều đi qua PHP (và PHP tự dùng khoá của server).

Không gọi mạng thật: requests.get/post của profile_manager đều bị thay.
"""
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.browser import profile_manager as pm

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}  {detail}")


FP = {"ua": "Mozilla/5.0 Chrome/153.0.0.0", "valid": True, "width": 1920, "height": 1080, "perfectcanvas": {}}
FP_RAW = json.dumps(FP)


class Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def run(key, direct):
    """direct: 'ok' | 'blocked' | 'refused'. Trả (fp, các lượt gọi)."""
    calls = []
    php_body = json.dumps({"status": "success", "source": "bablosoft", "id_finger": "fp_x", "fingerprint": FP})

    def fake_get(url, params=None, timeout=None, **kw):
        calls.append(("GET", url, dict(params or {})))
        if url == pm.BABLOSOFT_PREPARE_URL:
            if direct == "blocked":
                raise ConnectionError("connection reset by peer")
            if direct == "refused":
                return Resp('{"valid":false,"message":"Key not found"}')
            return Resp(FP_RAW)
        return Resp(php_body)

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append(("POST", url, dict(json or {})))
        return Resp(php_body)

    with tempfile.TemporaryDirectory() as root:
        profiles = os.path.join(root, "profiles")
        data = os.path.join(root, "data")
        os.makedirs(os.path.join(profiles, "p1"))
        os.makedirs(data)
        with open(os.path.join(profiles, "p1", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"tags": ["Windows", "Chrome"], "browser_version": "153.0.8010.37",
                       "window_size": {"width": 1920, "height": 1080}}, f)
        with open(os.path.join(data, "global_settings.json"), "w", encoding="utf-8") as f:
            json.dump({"bas_fingerprint_key": key} if key else {}, f)
        with mock.patch.object(pm, "PROFILES_DIR", profiles), mock.patch.object(pm, "DATA_DIR", data), \
                mock.patch.object(pm.requests, "get", fake_get), mock.patch.object(pm.requests, "post", fake_post):
            fp = pm.get_fingerprint("p1")
            saved = os.path.exists(os.path.join(profiles, "p1", "fingerprint.json"))
    return fp, calls, saved


# 1. Có khoá, tới được Bablosoft → lấy thẳng, KHÔNG chạm PHP
fp, calls, saved = run("USERKEY123", "ok")
check("co khoa + Bablosoft song: lay thang", fp == FP and saved, str(calls))
check("co khoa + Bablosoft song: khong goi PHP", all(c[1] == pm.BABLOSOFT_PREPARE_URL for c in calls), str(calls))
check("goi thang: dung khoa nguoi dung + version 5 + returnpc",
      calls and calls[0][2].get("key") == "USERKEY123" and calls[0][2].get("version") == "5"
      and calls[0][2].get("returnpc") == "true" and calls[0][2].get("min_browser_version") == "153",
      str(calls[:1]))

# 2. Có khoá, máy bị chặn Bablosoft → qua PHP, khoá đi trong thân POST (không nằm trên URL)
fp, calls, saved = run("USERKEY123", "blocked")
php = [c for c in calls if c[1] == pm.FINGER_PHP_URL]
check("bi chan: lui ve PHP va lay duoc", fp == FP and saved, str(calls))
check("bi chan: chi thu Bablosoft 1 lan roi bo", sum(c[1] == pm.BABLOSOFT_PREPARE_URL for c in calls) == 1, str(calls))
check("bi chan: PHP nhan DUNG khoa nguoi dung qua POST",
      php and php[0][0] == "POST" and php[0][2].get("key") == "USERKEY123", str(php))

# 3. Có khoá nhưng Bablosoft từ chối → vẫn hỏi PHP (trung gian), cùng khoá
fp, calls, saved = run("USERKEY123", "refused")
php = [c for c in calls if c[1] == pm.FINGER_PHP_URL]
check("khoa bi tu choi: van hoi PHP cung khoa", php and php[0][2].get("key") == "USERKEY123" and fp == FP, str(calls))

# 4. Không có khoá → không gọi được Bablosoft (cần khoá), đi PHP luôn, không gửi khoá nào
fp, calls, saved = run("", "ok")
check("khong khoa: khong goi Bablosoft", not any(c[1] == pm.BABLOSOFT_PREPARE_URL for c in calls), str(calls))
check("khong khoa: PHP khong kem khoa", calls and calls[0][1] == pm.FINGER_PHP_URL and "key" not in calls[0][2], str(calls))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
