# -*- coding: utf-8 -*-
"""read_live_action: doc duoi log ra "dang lam gi" cho luot con chay.

Run:  python tests/live_action_test.py     (exit 0 = pass)

Vi sao dang mot test rieng: bang Hoat dong va mat node truoc day chi ghi tro
"Dang chay". Nguoi dung muon thay "dang check mail" / "dang luot abc.com". Tin
hieu do rut tu chinh log open.js: dong "[Session] .. | Step: <verb> .. | Page:
<pt>" cho hanh dong, "[TabManager] Now on: <url>" cho trang. Cai de vo nhat la
lay NHAM step cu thay vi moi nhat, va host phai thanh ten than thien (Gmail),
nen ca hai deu co case rieng o duoi.

Khong dung dia that, khong goi mang: log viet vao thu muc tam.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def write_log(text):
    fd, path = tempfile.mkstemp(suffix=".log")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# Dong log THAT open.js in ra (open.js:1930 + TabManager:1310).
GMAIL = (
    "[Session] Auto-login complete. Resuming session...\n"
    "[TabManager] Now on: https://www.google.com\n"
    "\n[Session] 0.4/22 min | Step: search (1) | Page: google_search\n"
    "[TabManager] Now on: https://mail.google.com/mail/u/0/#inbox\n"
    "\n[Session] 3.1/22 min | Step: read_gmail (14) | Page: gmail\n"
)
SEARCH = (
    "\n[Session] 0.2/15 min | Step: navigate (1) | Page: general_website\n"
    "[TabManager] Now on: https://www.google.com/search?q=ai+tools\n"
    "\n[Session] 0.6/15 min | Step: search (2) | Page: google_search\n"
)
BROWSE_ABC = (
    "\n[Session] 1.0/20 min | Step: navigate (3) | Page: general_website\n"
    "[Manual] Navigated in-page. Now on: https://abc.com/news/today\n"
)
NO_URL = (   # chi co Page:, khong co dong Now on: -> where suy tu pageType
    "\n[Session] 2.0/20 min | Step: watch (5) | Page: youtube_video\n"
)


def main():
    from tubecli.extensions.browser.process_manager import browser_process_manager as bpm

    print("=== read_live_action ===")

    p = write_log(GMAIL)
    la = bpm.read_live_action(p)
    check("Gmail: buckets 'reading', where 'Gmail'",
          la and la["bucket"] == "reading" and la["where"] == "Gmail",
          repr(la))
    check("lay STEP MOI NHAT (read_gmail), khong phai search cu",
          la and la["action"] == "read_gmail" and la["step"] == 14, repr(la))
    os.unlink(p)

    p = write_log(SEARCH)
    la = bpm.read_live_action(p)
    check("Search tren Google: bucket 'searching', where 'Google'",
          la and la["bucket"] == "searching" and la["where"] == "Google", repr(la))
    os.unlink(p)

    p = write_log(BROWSE_ABC)
    la = bpm.read_live_action(p)
    check("Luot web la: bucket 'browsing', where 'abc.com' (host tho, khong map)",
          la and la["bucket"] == "browsing" and la["where"] == "abc.com", repr(la))
    check("URL tu dong 'Navigated in-page. Now on:' cung bat duoc",
          la and la["url"] == "https://abc.com/news/today", repr(la))
    os.unlink(p)

    p = write_log(NO_URL)
    la = bpm.read_live_action(p)
    check("Khong co URL -> where suy tu Page: youtube_video -> 'YouTube'",
          la and la["where"] == "YouTube" and la["bucket"] == "watching", repr(la))
    os.unlink(p)

    p = write_log("chua co dong Session/Step/Now on nao ca\n")
    check("log chua co buoc nao -> None (khong bia 'dang lam gi')",
          bpm.read_live_action(p) is None)
    os.unlink(p)

    check("log_path rong -> None", bpm.read_live_action("") is None)
    check("log_path khong ton tai -> None",
          bpm.read_live_action(os.path.join(tempfile.gettempdir(), "khong-co.log")) is None)

    print(f"\n{PASS} pass, {FAIL} fail")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
