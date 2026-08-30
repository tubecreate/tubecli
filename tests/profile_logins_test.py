# -*- coding: utf-8 -*-
"""Detect logins: profile the dang nhap site nao, doc tu kho cookie THAT.

Run:  python tests/profile_logins_test.py     (exit 0 = pass)

Mo hinh kiem tra o day (khop du lieu that tren may nay, xem profile_manager.py):
  - "Tham != dang nhap": chi COOKIE PHIEN dac trung moi tinh (fb c_user, tiktok
    sessionid, google SID...). Cookie domain khong-phien (vd .facebook.com "datr")
    KHONG duoc coi la da dang nhap.
  - Phien google phu tro YouTube: co google session => youtube cung sang (chu ho
    quan tam youtube), va youtube chi xuat hien DUNG MOT LAN.
  - DB thieu/khoa/hong => tra [] chu KHONG sap.
  - Cache theo (path, mtime, size): goi lai tra DUNG object cu, khong truy van lai.

Khong dung dia that cua may: monkeypatch PROFILES_DIR sang thu muc tam, tu dung
SQLite cookie be xiu. Style plain-assert giong cac test khac trong thu muc nay.
"""
import os
import sys
import shutil
import sqlite3
import tempfile

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
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


# ------------------------------------------------------------------ cong cu

def make_cookie_db(path, cookies, corrupt=False):
    """Dung mot DB cookie be: cookies = list (host_key, name). Neu corrupt=True,
    ghi rac de mo phong file hong."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if corrupt:
        with open(path, "wb") as f:
            f.write(b"this is not a sqlite database at all")
        return
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT)")
    conn.executemany(
        "INSERT INTO cookies (host_key, name, value) VALUES (?, ?, ?)",
        [(h, n, "encrypted-blob-we-never-read") for h, n in cookies],
    )
    conn.commit()
    conn.close()


def cookie_path(root, name, sub=""):
    return os.path.join(root, name + sub, "Default", "Network", "Cookies")


def make_profile(root, name, cookies, sub=""):
    make_cookie_db(cookie_path(root, name, sub), cookies)


# ------------------------------------------------------------------ chay test

def run():
    root = tempfile.mkdtemp(prefix="tubecli_logins_")
    orig_dir = pm.PROFILES_DIR
    orig_cache = pm._LOGIN_CACHE
    pm.PROFILES_DIR = root
    pm._LOGIN_CACHE = {}
    try:
        # 1) facebook c_user -> [facebook]
        make_profile(root, "fb", [(".facebook.com", "c_user"), (".facebook.com", "datr")])
        r = pm.detect_logins("fb")
        check("fb c_user -> [facebook]", r == ["facebook"], repr(r))

        # 2) tiktok sessionid -> [tiktok]
        make_profile(root, "tt", [(".tiktok.com", "sessionid")])
        r = pm.detect_logins("tt")
        check("tiktok sessionid -> [tiktok]", r == ["tiktok"], repr(r))

        # 3) google SID -> gom google VA youtube (phien google phu tro YT)
        make_profile(root, "goog", [(".google.com", "SID")])
        r = pm.detect_logins("goog")
        check("google SID -> gom google", "google" in r, repr(r))
        check("google SID -> youtube ngam theo", "youtube" in r, repr(r))
        check("google SID -> youtube DUNG MOT LAN", r.count("youtube") == 1, repr(r))

        # 3b) youtube LOGIN_INFO truc tiep, khong co google -> [youtube] khong [google]
        make_profile(root, "ytonly", [(".youtube.com", "LOGIN_INFO")])
        r = pm.detect_logins("ytonly")
        check("youtube LOGIN_INFO -> co youtube", "youtube" in r, repr(r))
        check("youtube truc tiep -> KHONG suy ra google", "google" not in r, repr(r))

        # 3c) youtube truc tiep + google session cung mot profile -> youtube 1 lan
        make_profile(root, "both", [(".youtube.com", "LOGIN_INFO"), (".google.com", "__Secure-1PSID")])
        r = pm.detect_logins("both")
        check("youtube+google -> youtube khong nhan doi", r.count("youtube") == 1 and "google" in r, repr(r))

        # 4) cookie KHONG-phien (chi .facebook.com datr) -> KHONG dang nhap
        make_profile(root, "visited", [(".facebook.com", "datr"), (".facebook.com", "wd")])
        r = pm.detect_logins("visited")
        check("datr-only -> khong dang nhap", r == [], repr(r))

        # 4b) instagram can CA sessionid VA ds_user_id
        make_profile(root, "ig_half", [(".instagram.com", "sessionid")])
        check("instagram thieu ds_user_id -> khong dang nhap", pm.detect_logins("ig_half") == [], "")
        make_profile(root, "ig_full", [(".instagram.com", "sessionid"), (".instagram.com", "ds_user_id")])
        check("instagram du 2 marker -> [instagram]", pm.detect_logins("ig_full") == ["instagram"], "")

        # 4c) x auth_token qua .twitter.com cung tinh la x; bien gioi ten mien chat
        make_profile(root, "xt", [(".twitter.com", "auth_token")])
        check("twitter auth_token -> [x]", pm.detect_logins("xt") == ["x"], "")
        make_profile(root, "notg", [("notgoogle.com", "SID")])
        check("notgoogle.com SID -> KHONG trung google (bien gioi ten mien)", pm.detect_logins("notg") == [], "")

        # 5) DB thieu -> []; DB hong -> []; ca hai khong sap
        check("profile khong co DB -> []", pm.detect_logins("ghost") == [], "")
        make_cookie_db(cookie_path(root, "broken", ""), None, corrupt=True)
        pm._LOGIN_CACHE.pop("broken", None)
        check("DB hong -> [] khong sap", pm.detect_logins("broken") == [], "")

        # 5b) profile anh em _bas cung duoc gop
        make_profile(root, "sib", [(".facebook.com", "datr")])          # profile chinh: chua dang nhap
        make_profile(root, "sib", [(".tiktok.com", "sessionid")], sub="_bas")  # anh em _bas: co tiktok
        r = pm.detect_logins("sib")
        check("gop _bas -> [tiktok]", r == ["tiktok"], repr(r))

        # 6) Cache theo (path,mtime,size): goi lai KHONG truy van lai, tra DUNG object cu
        counter = {"n": 0}
        orig_read = pm._read_cookie_markers

        def counting_read(path):
            counter["n"] += 1
            return orig_read(path)

        pm._read_cookie_markers = counting_read
        pm._LOGIN_CACHE.pop("cachep", None)
        make_profile(root, "cachep", [(".google.com", "SID")])
        r1 = pm.detect_logins("cachep")
        after_first = counter["n"]
        r2 = pm.detect_logins("cachep")
        after_second = counter["n"]
        pm._read_cookie_markers = orig_read
        check("lan 1 co truy van DB", after_first >= 1, f"n={after_first}")
        check("lan 2 (cache) KHONG truy van them", after_second == after_first, f"{after_first}->{after_second}")
        check("cache tra DUNG object cu", r1 is r2, "")

        # 6b) File cookie doi (size/mtime) -> cache lech, doc lai
        counter["n"] = 0
        pm._read_cookie_markers = counting_read
        # them cookie moi lam size doi
        dbp = cookie_path(root, "cachep", "")
        conn = sqlite3.connect(dbp)
        conn.execute("INSERT INTO cookies (host_key,name,value) VALUES (?,?,?)",
                     (".facebook.com", "c_user", "x"))
        conn.commit()
        conn.close()
        r3 = pm.detect_logins("cachep")
        pm._read_cookie_markers = orig_read
        check("cookie doi -> doc lai (cache lech)", counter["n"] >= 1, f"n={counter['n']}")
        check("cookie doi -> facebook xuat hien", "facebook" in r3, repr(r3))

    finally:
        pm.PROFILES_DIR = orig_dir
        pm._LOGIN_CACHE = orig_cache
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
