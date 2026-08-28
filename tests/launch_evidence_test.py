# -*- coding: utf-8 -*-
"""Bang chung mot luot mo de lai: khoa BAS con song khong, va co van tay khong.

Run:  python tests/launch_evidence_test.py     (exit 0 = pass)

Ba lo hong duoc dong o day, ca ba deu cung mot hinh dang: MAY DA BIET SU THAT,
NHUNG KHONG AI DOC.

1. shardx_runtime.mark_bas_key_ok() khong he co cho goi nao trong ma san pham.
   Phan quyet ve khoa BAS chi di duoc mot chieu (hong thi ghi, tot thi khong),
   nen mot may chi cai BAS chay bang khoa DUNG CHUNG ket vinh vien o "unknown".

2. ANTIDETECT_OFF — trinh duyet mo ma KHONG ap dau van tay nao — chi duoc in ra
   log. Ma thoat van 0, History van day, bao cao van "thanh cong". Chong phat
   hien co the tat hang tuan ma khong ai biet.

3. preview_server.cjs xoa fingerprint_saved.json khi THAN loi chua chuoi
   "fingerprint". Moi lan mo ShardX deu truyen --fingerprint-profile=<duong dan>
   va Playwright nhet ca dong lenh vao thong bao loi, nen mot engine crash du de
   thoi bay danh tinh chong phat hien cua ho so.

Khong dung dia that cua nguoi dung, khong goi mang: moi thu chay trong thu muc tam.
"""
import os
import re
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER_DIR = os.path.join(ROOT, "tubecli", "extensions", "browser")

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


# ── Ban sao dieu kien XOA VAN TAY trong preview_server.cjs ────────────────
# Viet lai o day de test khang dinh dung phep thu JS THUC SU chay, khong phai mot
# ban "gan giong". Test o duoi con doi chieu ban sao nay voi chinh file nguon.
def js_should_delete_fingerprint(message, code=""):
    head = str(message or "").split("\n")[0].lower()
    return (code == "FINGERPRINT_INVALID"
            or message == "FINGERPRINT_FATAL_ERROR"
            or "fingerprint" in head
            or "incorrect format" in head)


# Loi Playwright THAT khi engine khoi dong roi chet ngay: dong dau la headline,
# nhung "Call log" ben duoi keo nguyen dong lenh vao — ke ca --fingerprint-profile.
PLAYWRIGHT_CRASH = (
    "browserType.launchPersistentContext: spawn EINVAL\n"
    "Call log:\n"
    "  - <launching> C:\\engines\\149.0.7827.103\\ShardX-Windows\\chrome.exe "
    "--no-first-run --fingerprint-profile=C:\\profiles\\browser6\\fingerprint_saved.json "
    "--remote-debugging-port=51234\n"
)


def main():
    print("=== 1. preview_server.cjs khong duoc xoa van tay vi mot dong lenh ===")
    src = open(os.path.join(BROWSER_DIR, "preview_server.cjs"),
               encoding="utf-8", errors="replace").read()

    check("dieu kien xoa chi con soi DONG DAU cua loi",
          re.search(r"const fpErrHead = String\(e\.message \|\| ''\)"
                    r"\.split\('\\n'\)\[0\]\.toLowerCase\(\);", src) is not None)
    check("khong con so khop NGUYEN THAN loi voi 'fingerprint'",
          "e.message.toLowerCase().includes('fingerprint')" not in src)
    check("van ton trong ma loi tuong minh do chinh engine dat",
          "e.code === 'FINGERPRINT_INVALID'" in src)
    check("van ton trong sentinel cu (browser_manager van nem)",
          "e.message === 'FINGERPRINT_FATAL_ERROR'" in src)

    check("loi Playwright co --fingerprint-profile trong THAN: KHONG duoc xoa",
          js_should_delete_fingerprint(PLAYWRIGHT_CRASH) is False,
          "day chinh la ca da tai hien duoc, va no pha du lieu that")
    check("nhung ca do THAT SU co chu 'fingerprint' o dau ra",
          "fingerprint" in PLAYWRIGHT_CRASH.lower(),
          "chung to ban cu se xoa")
    check("sentinel co chu dich -> van xoa",
          js_should_delete_fingerprint("FINGERPRINT_FATAL_ERROR") is True)
    check("ma loi tuong minh -> van xoa",
          js_should_delete_fingerprint("spawn EINVAL", code="FINGERPRINT_INVALID") is True)
    check("engine tu noi van tay hong o DONG DAU -> van xoa",
          js_should_delete_fingerprint("Fingerprint has incorrect format\nCall log: ...") is True)
    check("loi proxy thuong -> khong dong cham van tay",
          js_should_delete_fingerprint("net::ERR_NO_SUPPORTED_PROXIES") is False)

    # Ban hot-patch tren cloud phai giong het, khong thi ban va se lui lo hong nay
    # ve lai cac may hosted (desk_first_test.py cung giu dieu nay).
    mirror = os.path.join(os.path.dirname(ROOT), "tubecli-cloud",
                          "public", "patch", "preview_server.cjs")
    if os.path.exists(mirror):
        check("ban hot-patch cloud da dong bo",
              open(mirror, encoding="utf-8", errors="replace").read() == src)
    else:
        print(f"[SKIP] ban hot-patch cloud khong co o {mirror}")

    print("\n=== 2. browser_manager.js de lai dau moc doc duoc bang may ===")
    bm = open(os.path.join(BROWSER_DIR, "browser_manager.js"),
              encoding="utf-8", errors="replace").read()
    # Phai nam GIUA loi goi mo thanh cong va `return context;` — in truoc khi mo
    # thi no khong con la bang chung gi ca.
    _open = bm.index("launchPersistentContext(profilePath, {")
    _mark = bm.find("BAS_LAUNCH_OK", _open)
    _ret = bm.find("return context;", _open)
    check("in BAS_LAUNCH_OK SAU khi plugin mo duoc that, truoc khi tra ve",
          _mark > _open and _ret > _mark, f"open={_open} mark={_mark} ret={_ret}")
    check("in ANTIDETECT_OFF ca hai nhanh engine",
          bm.count("ANTIDETECT_OFF") >= 2)
    check("khong con ghi chu noi doi rang open.js/run_log da bat chuoi nay",
          "open.js và run_log bắt bằng chuỗi" not in bm)

    print("\n=== 3. monitor doc log va rut ra hai su that ===")
    from tubecli.extensions.browser.process_manager import browser_process_manager as bpm
    from tubecli.extensions.browser import shardx_runtime as sx

    marks = []
    with mock.patch.object(sx, "mark_bas_key_ok", lambda: marks.append("ok") or True), \
         mock.patch.object(sx, "mark_bas_key_bad", lambda r="": marks.append(("bad", r)) or True):

        p = write_log("[Launch] ANTIDETECT_ON profile=x engine=bas\n"
                      "[Launch] BAS_LAUNCH_OK profile=x engine=bas version=30.2.0\n")
        warns = bpm._note_launch_evidence(p)
        os.unlink(p)
        check("mo BAS duoc -> ghi 'khoa con song'", marks == ["ok"], str(marks))
        check("va khong canh bao gi", warns == [], str(warns))

        marks.clear()
        p = write_log("[Launch] ANTIDETECT_OFF profile=x engine=bas reason=no_fingerprint_applied\n"
                      "[Launch] BAS_LAUNCH_OK profile=x engine=bas version=30.2.0\n")
        warns = bpm._note_launch_evidence(p)
        os.unlink(p)
        check("mo TRAN -> tra ve canh bao ANTIDETECT_OFF",
              warns == ["ANTIDETECT_OFF"], str(warns))
        check("van ghi nhan khoa con song (hai su that doc lap nhau)",
              marks == ["ok"], str(marks))

        marks.clear()
        p = write_log("Error: Key expired! I have installed a Bypass hook.\n")
        warns = bpm._note_launch_evidence(p)
        os.unlink(p)
        check("log noi khoa het han -> ghi 'khoa hong'",
              marks and marks[0][0] == "bad", str(marks))
        check("ly do giu nguyen cau chu that", "Key expired" in marks[0][1], str(marks))

        marks.clear()
        # Mot phien co the mo duoc luc dau roi khoa het han giua chung. Bang chung
        # XAU thang: neu khong, dau moc thanh cong se xoa mat phan quyet dung.
        p = write_log("[Launch] BAS_LAUNCH_OK profile=x engine=bas version=30.2.0\n"
                      "Error: FingerprintSwitcher key is missing\n")
        bpm._note_launch_evidence(p)
        os.unlink(p)
        check("hong VA tot trong cung mot log -> bang chung XAU thang",
              [m for m in marks if m != "ok"] and "ok" not in marks, str(marks))

        marks.clear()
        check("log khong ton tai -> khong ghi gi, khong nem",
              bpm._note_launch_evidence(os.path.join(tempfile.gettempdir(), "khong-co.log")) == []
              and marks == [], str(marks))
        check("log_path rong -> khong ghi gi", bpm._note_launch_evidence("") == [])

    print("\n=== 4. canh bao di duoc toi ban ghi luot chay ===")
    from tubecli.core import run_log

    appended = []
    with mock.patch.object(run_log, "_append", lambda e: appended.append(e)):
        run_log.end("r1", "a1", "completed", return_code=0,
                    log_tail="[Launch] ANTIDETECT_OFF profile=x",
                    warnings=["ANTIDETECT_OFF"])
    ev = appended[0]
    check("su kien end mang warnings", ev.get("warnings") == ["ANTIDETECT_OFF"], str(ev))
    check("luot chay XONG ma co canh bao thi VAN giu log_tail lam bang chung",
          bool(ev.get("log_tail")), str(ev.get("log_tail")))

    appended.clear()
    with mock.patch.object(run_log, "_append", lambda e: appended.append(e)):
        run_log.end("r2", "a1", "completed", return_code=0, log_tail="binh thuong")
    check("luot chay sach thi khong bia them truong warnings",
          "warnings" not in appended[0], str(appended[0]))
    check("va van khong giu log_tail (giu nguyen hanh vi cu)",
          "log_tail" not in appended[0], str(appended[0]))

    # Tang DOC phai thay: khong thi canh bao chi nam trong file jsonl.
    day = []

    def fake_read_days(_days):
        return day

    day[:] = [
        {"kind": "start", "run_id": "r9", "ts": "2026-08-28T10:00:00",
         "agent_id": "a9", "agent_name": "A", "trigger": "schedule"},
        {"kind": "launch", "run_id": "r9", "ts": "2026-08-28T10:00:01",
         "agent_id": "a9", "profile": "p1", "spawn_status": "running"},
        {"kind": "end", "run_id": "r9", "ts": "2026-08-28T10:05:00", "agent_id": "a9",
         "outcome": "completed", "return_code": 0, "warnings": ["ANTIDETECT_OFF"]},
    ]
    with mock.patch.object(run_log, "_read_days", fake_read_days):
        rows = run_log.list_for_agent("a9")
    row = [r for r in rows if r.get("run_id") == "r9"][0]
    check("tang doc noi ro luot nay KHONG sach",
          row.get("warnings") == ["ANTIDETECT_OFF"], str(row.get("warnings")))
    check("nhung ket qua van la su that (completed, khong bia ra 'error')",
          row.get("outcome") == "completed", str(row.get("outcome")))

    print("\n=== 5. cong cu chu may doc bang chinh cai tren ===")
    tool = open(os.path.join(ROOT, "tools", "check_browsing.py"),
                encoding="utf-8", errors="replace").read()
    check("check_browsing.py go 'warnings' ra khoi su kien", "'warnings'" in tool)
    check("va hien no canh ket qua", "r.get('warnings')" in tool)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
