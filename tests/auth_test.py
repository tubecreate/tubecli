"""The dashboard password must actually keep people out.

Run:  python tests/auth_test.py     (exit 0 = pass)

Why this file exists. Before this, the API had no authentication at all and the
only thing standing between the internet and data/cloud_api_keys.json was
origin_guard's refusal of non-loopback browser origins — which users were told
to switch off with TUBECLI_ALLOWED_ORIGIN_HOSTS in order to use the dashboard
remotely. Security code that is never exercised is security theatre, so every
property this module claims is asserted here: the hash is salted and slow, the
stored file is not world-readable, the default password cannot be used from
outside, a wrong password is throttled, and loopback keeps working untouched.
"""
import json
import os
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg
from tubecli.core import auth

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="tubecli_auth_")
    saved = cfg.DATA_DIR
    cfg.DATA_DIR = __import__("pathlib").Path(tmp)
    auth._sessions.clear()
    auth._failures.clear()

    try:
        print("=== 1. khoi tao voi mat khau mac dinh ===")
        auth.ensure_initialised()
        check("da tao auth.json", auth.is_configured())
        check("nhan biet la mat khau mac dinh", auth.is_default_password())
        check("dung mat khau 123456 thi verify OK", auth.verify_password("123456"))
        check("mat khau khac thi truot", not auth.verify_password("123457"))

        print("\n=== 2. file khong cho nguoi khac doc ===")
        p = auth._auth_file()
        raw = json.load(open(p, encoding="utf-8"))
        check("KHONG luu mat khau dang chu thuong",
              "123456" not in json.dumps(raw), "tim thay chuoi 123456 trong file")
        check("co salt rieng", bool(raw.get("salt")))
        check("co secret ky phien", bool(raw.get("secret")))
        if os.name != "nt":
            mode = stat.S_IMODE(os.stat(p).st_mode)
            check("quyen file la 0600", mode == 0o600, oct(mode))
        else:
            print("  (Windows: bo qua kiem tra chmod)")

        print("\n=== 3. hai lan dat cung mat khau ra hai hash khac nhau ===")
        h1 = json.load(open(p, encoding="utf-8"))["password_hash"]
        auth.set_password("cungmotmatkhau")
        h2 = json.load(open(p, encoding="utf-8"))["password_hash"]
        auth.set_password("cungmotmatkhau")
        h3 = json.load(open(p, encoding="utf-8"))["password_hash"]
        check("salt ngau nhien -> hash khac nhau", h2 != h3, "hai hash giong nhau")
        check("va khac hash cua mat khau cu", h1 != h2)

        print("\n=== 4. doi mat khau thi huy het phien cu ===")
        auth.set_password("matkhaucu")
        tok = auth.create_session()
        check("phien vua tao hop le", auth.session_valid(tok))
        auth.set_password("matkhaumoi")
        check("doi mat khau -> phien cu het hieu luc", not auth.session_valid(tok))
        check("mat khau moi verify duoc", auth.verify_password("matkhaumoi"))
        check("mat khau cu khong con dung", not auth.verify_password("matkhaucu"))
        check("khong con la mat khau mac dinh", not auth.is_default_password())

        print("\n=== 5. loopback khong bi hoi gi ===")
        for h in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1", "127.0.0.53"):
            check(f"{h} duoc di thang", auth.check_request(h, None) is None)

        print("\n=== 6. tu xa thi phai co phien ===")
        r = auth.check_request("203.0.113.9", None)
        check("khong co cookie -> tu choi", r is not None and r["reason"] == "login_required", str(r))
        good = auth.create_session()
        check("co phien hop le -> cho qua", auth.check_request("203.0.113.9", good) is None)
        check("cookie bia dat -> tu choi", auth.check_request("203.0.113.9", "khong-phai-token") is not None)
        auth.destroy_session(good)
        check("dang xuat roi -> tu choi", auth.check_request("203.0.113.9", good) is not None)

        print("\n=== 7. con mat khau mac dinh thi CHAN tu xa ===")
        # The window this closes: a fresh install sitting on a public IP with a
        # published password, before the user has logged in even once.
        auth.set_password(auth.DEFAULT_PASSWORD, _is_default=True)
        tok2 = auth.create_session()
        r = auth.check_request("203.0.113.9", tok2)
        check("tu xa bi tu choi du CO phien hop le",
              r is not None and r["reason"] == "default_password", str(r))
        check("nhung loopback van vao duoc de doi mat khau",
              auth.check_request("127.0.0.1", None) is None)
        auth.set_password("daDoiRoi123")
        check("doi xong thi tu xa mo ra",
              auth.check_request("203.0.113.9", auth.create_session()) is None)

        print("\n=== 7b. proxy cung may KHONG duoc coi la loopback ===")
        # The hole this closes: nginx, Caddy or `cloudflared tunnel --url
        # http://127.0.0.1:5295` connects over loopback, so every request it
        # relays arrives with client.host == 127.0.0.1. Trusting the address
        # alone would turn authentication off for the entire API the moment
        # anyone put a tunnel in front — which is the standard way to expose
        # this thing.
        auth.set_password("MatKhauThat2026")
        check("loopback KHONG co header proxy -> van vao thang",
              auth.check_request("127.0.0.1", None, {}) is None)
        for hdr in ("x-forwarded-for", "x-real-ip", "forwarded",
                    "x-forwarded-host", "cf-connecting-ip"):
            r = auth.check_request("127.0.0.1", None, {hdr: "203.0.113.9"})
            check(f"  loopback + {hdr} -> phai dang nhap",
                  r is not None and r["reason"] == "login_required", str(r))
        r = auth.check_request("127.0.0.1", auth.create_session(),
                               {"x-forwarded-for": "203.0.113.9"})
        check("  qua proxy nhung co phien hop le -> cho qua", r is None, str(r))
        check("khong truyen headers -> giu hanh vi cu (loopback vao thang)",
              auth.check_request("127.0.0.1", None) is None)

        print("\n=== 8. chan do mat khau ===")
        auth._failures.clear()
        key = "203.0.113.9"
        for _ in range(5):
            auth.record_failure(key)
        locked, secs = auth.throttle_status(key)
        check("5 lan sai -> khoa", locked, f"con {secs}s")
        auth.clear_failures(key)
        check("dang nhap dung -> mo khoa", not auth.throttle_status(key)[0])

        print("\n=== 9. phien het han thi khong dung duoc ===")
        t = auth.create_session()
        auth._sessions[t] = time.time() - 1
        check("phien qua han bi tu choi", not auth.session_valid(t))
        check("va bi don khoi bo nho", t not in auth._sessions)

        print("\n=== 10. mat khau qua ngan bi tu choi ===")
        for bad in ("", "abc", "12345"):
            try:
                auth.set_password(bad)
                check(f"tu choi mat khau {bad!r}", False, "lai chap nhan")
            except ValueError:
                check(f"tu choi mat khau {bad!r}", True)

        print("\n=== 11. file hong khong bien thanh 'khong can mat khau' ===")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{ day khong phai json")
        check("file hong -> coi nhu chua thiet lap", not auth.is_configured())
        r = auth.check_request("203.0.113.9", None)
        check("  va tu xa bi tu choi, khong pha cua",
              r is not None and r["reason"] == "not_configured", str(r))
        check("  loopback van vao duoc de sua", auth.check_request("127.0.0.1", None) is None)
    finally:
        cfg.DATA_DIR = saved
        auth._sessions.clear()
        auth._failures.clear()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
