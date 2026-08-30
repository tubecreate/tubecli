# -*- coding: utf-8 -*-
"""Pool email hệ thống cho send_report ngẫu nhiên (opt-in).

Kiểm phần rủi ro: trích email từ google_account (str/dict/pipe), loại profile
đang chạy để agent không tự gửi cho mình, dedup, bỏ qua profile không có tài khoản.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.api import server  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + ("  -> " + str(extra) if extra else ""))


# ── _extract_account_email: str, dict, pipe, không phải email ──
check("dict.email", server._extract_account_email({"email": "a@x.com"}) == "a@x.com")
check("str thuần", server._extract_account_email("b@x.com") == "b@x.com")
check("str pipe 'email|pass'", server._extract_account_email("c@x.com|matkhau|abc") == "c@x.com")
check("str tab", server._extract_account_email("d@x.com\tpass") == "d@x.com")
check("không có @ -> rỗng", server._extract_account_email("khong-phai-email") == "")
check("None -> rỗng", server._extract_account_email(None) == "")
check("dict rỗng -> rỗng", server._extract_account_email({}) == "")


# ── _system_report_emails: monkeypatch list_profiles ──
FAKE = [
    {"name": "tuan5", "google_account": "tuan5@gmail.com"},
    {"name": "tuan3", "google_account": {"email": "tuan3@gmail.com", "password": "x"}},
    {"name": "test", "google_account": "test@gmail.com|pw|rec"},
    {"name": "noacct", "google_account": None},
    {"name": "dupe", "google_account": "TUAN5@gmail.com"},   # trùng tuan5 (khác hoa/thường)
]
import tubecli.extensions.browser.profile_manager as pm  # noqa: E402
_orig = pm.list_profiles
pm.list_profiles = lambda: FAKE
try:
    all_e = server._system_report_emails()
    check("gom đủ email hợp lệ", set(e.lower() for e in all_e) ==
          {"tuan5@gmail.com", "tuan3@gmail.com", "test@gmail.com"}, all_e)
    check("bỏ profile không có tài khoản", "noacct" not in str(all_e))
    check("dedup không phân biệt hoa/thường", len(all_e) == 3, all_e)

    excl = server._system_report_emails(exclude_profile="tuan5")
    check("loại profile đang chạy (self)", "tuan5@gmail.com" not in excl, excl)
    # 'dupe' cũng mang email tuan5 -> loại theo TÊN profile, nhưng email vẫn có thể
    # tới từ dupe. Kiểm: exclude theo TÊN 'tuan5' bỏ tuan5, dupe(TUAN5) vẫn vào.
    check("exclude theo tên, không theo email", "TUAN5@gmail.com" in excl or "tuan5@gmail.com" in [e for e in excl], excl)

    pm.list_profiles = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    check("list_profiles ném -> trả rỗng, không crash", server._system_report_emails() == [])
finally:
    pm.list_profiles = _orig

print("\n%d pass, %d fail" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
