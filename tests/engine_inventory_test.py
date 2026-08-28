# -*- coding: utf-8 -*-
"""Kiem ke nhan: profile moi PHAI ghim nhan MOI NHAT thuc su DUNG DUOC o day.

Run:  python tests/engine_inventory_test.py     (exit 0 = pass)

Mo hinh duoc kiem tra o day (chu KHONG phai "Linux thi ShardX, Windows thi BAS"):

    QUYET DINH = nhan ghim tren profile (config.json browser_version)
    HOP LE     = nhan do co THAT va DUNG DUOC tren host nay, ngay bay gio
    MAC DINH   = nhan moi nhat thuc su dung duoc, viet thanh mot cai ghim TUONG MINH

Nen tang bi ha xuong lam MOT dau vao cua "dung duoc" (supports_bas), khong bao gio
la mot luat o tang tren. "Linux khong co BAS" tu roi ra: binding BAS khai os=win32
nen o do khong cai duoc, va thu muc engine BAS cung khong ton tai.

"Dung duoc" KHAT KHE hon "da cai". Tren may Windows nay ca hai ho nhan deu da cai,
nhung khoa ban quyen BAS het han nen moi luot mo BAS chet o "Key expired" — mot ban
kiem ke bao BAS san sang o day la tiep tuc san xuat profile chet. Vi the case 3
duoi day (ca hai da cai, khoa BAS hong) la case quan trong nhat file nay.

Moi dau vao deu duoc monkeypatch: khong dung dia that, khong goi mang.
"""
import os
import sys
import time
import inspect
import builtins
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.browser import profile_manager as pm
from tubecli.extensions.browser import shardx_runtime as sx

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

def js_is_shardx(value) -> bool:
    """Ban sao phep thu DUY NHAT browser_manager.js dung de dinh tuyen engine:

        targetChromiumVer.includes('ShardX')

    Viet lai o day de test khang dinh dung dieu kien JS THUC SU chay, chu khong
    phai mot phien ban "gan giong" do test tu nghi ra. Phan biet chu hoa chu thuong.
    """
    return bool(value) and "ShardX" in str(value)


def js_version_of(value) -> str:
    """Ban sao buoc boc so phien ban ben JS: bo tien to roi trim.

    Chi lot duoc includes('ShardX') ma bo lai rac o phan so thi engine van khong
    tim thay thu muc — nen phai kiem tra ca buoc nay.
    """
    return str(value).replace("ShardX", "", 1).lstrip().lstrip("-").strip()


def host(shardx=(), bas=(), supports_bas=True, key=None, latest="149.0.7827.103"):
    """Gia lap TOAN BO dau vao cua kiem ke: dia ShardX, dia BAS, OS, khoa, manifest."""
    key_state = key if key is not None else {"available": False, "why_not": "khoa xau"}
    return [
        mock.patch.object(sx, "installed_versions", lambda: list(shardx)),
        mock.patch.object(sx, "installed_bas_versions", lambda: list(bas)),
        mock.patch.object(sx, "supports_bas", lambda: supports_bas),
        mock.patch.object(sx, "bas_key_state", lambda: dict(key_state)),
        mock.patch.object(sx, "current_version", lambda: latest),
    ]


class using:
    """Bat mot danh sach patch cung luc (contextlib.ExitStack thu gon)."""

    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


KEY_OK = {"available": True, "verdict": "ok", "why_not": ""}
KEY_EXPIRED = {"available": False, "verdict": "bad",
               "why_not": "khoa BAS vua bao loi o lan mo gan nhat"}


def broken_import():
    """Lam CHINH cau `from ... import shardx_runtime` NEM loi.

    Day la ly do resolve_default_browser_version phai import muon: mot module hong
    khong duoc phep lam chet viec tao profile. Patch tung ham gia lap loi thi chi
    thu duoc nhanh except ben trong; patch __import__ moi thu dung duong di that.
    """
    real_import = builtins.__import__

    def boom(name, glob=None, loc=None, fromlist=(), level=0):
        if "shardx_runtime" in (fromlist or ()) or str(name).endswith("shardx_runtime"):
            raise ImportError("simulated: shardx_runtime khong import duoc")
        return real_import(name, glob, loc, fromlist, level)

    return mock.patch.object(builtins, "__import__", boom)


# ------------------------------------------------------------------ cac case

def main():
    print("=== 0. chu ky ham va hai cho goi giu nguyen ===")
    sig = str(inspect.signature(pm.resolve_default_browser_version))
    check("chu ky van la () -> str", sig == "() -> str", sig)
    src = inspect.getsource(pm)
    check("create_profile van goi resolve_default_browser_version()",
          "browser_version = resolve_default_browser_version()" in src)
    check("update_profile van goi resolve_default_browser_version()",
          'kwargs["browser_version"] = resolve_default_browser_version()' in src)
    check("khong con luat dinh tuyen theo nen tang trong profile_manager",
          "sys.platform" not in src, "sys.platform van con trong file")

    print("\n=== 1. host CHI CO ShardX ===")
    with using(host(shardx=["149.0.7827.103", "148.0.7778.97"], bas=[])):
        engines = sx.installed_engines()
        got = pm.resolve_default_browser_version()
    check("kiem ke thay dung 2 nhan", len(engines) == 2, str(len(engines)))
    check("ca hai deu la shardx va dung duoc",
          all(e["family"] == "shardx" and e["usable"] for e in engines))
    check("moi nhat dung dau", engines[0]["version"] == "149.0.7827.103", engines[0]["version"])
    check("ghim 'ShardX 149.0.7827.103'", got == "ShardX 149.0.7827.103", got)
    check("JS includes('ShardX') nhan ra", js_is_shardx(got), got)
    check("JS boc ra dung so phien ban", js_version_of(got) == "149.0.7827.103", js_version_of(got))

    print("\n=== 2. host CHI CO BAS, khoa TOT -> ghim so tran (BAS la ghim so tran) ===")
    with using(host(shardx=[], bas=["30.2.0", "30.1.0"], supports_bas=True, key=KEY_OK)):
        engines = sx.installed_engines()
        got = pm.resolve_default_browser_version()
    check("kiem ke thay 2 engine BAS", len(engines) == 2, str(len(engines)))
    check("BAS dung duoc khi khoa tot", all(e["usable"] for e in engines))
    check("BAS 30.2.0 -> Chromium 149.0.7827.54", got == "149.0.7827.54", got)
    check("day la mot ghim BAS that (JS se di nhanh BAS)", not js_is_shardx(got), got)
    check("giu ca so engine BAS goc de UI noi ro",
          engines[0]["engine_version"] == "30.2.0", engines[0]["engine_version"])

    print("\n=== 3. CA HAI da cai, khoa BAS HONG -> mac dinh PHAI la ShardX ===")
    # Dung canh may Windows nay: engine BAS 30.2.0 (Chromium 149.0.7827.54) MOI HON
    # ban ShardX da cai. Neu quyet dinh chi nhin "moi nhat da CAI" thi BAS thang, va
    # moi profile moi lai chet o "Key expired" — dung con bug 23/23 lan 0 trang.
    with using(host(shardx=["148.0.7778.216"], bas=["30.2.0"],
                    supports_bas=True, key=KEY_EXPIRED)):
        engines = sx.installed_engines()
        got = pm.resolve_default_browser_version()
    bas_entry = [e for e in engines if e["family"] == "bas"][0]
    check("BAS van bao CO CAI (khong noi doi ve dia)", bas_entry["installed"] is True)
    check("nhung KHONG dung duoc", bas_entry["usable"] is False)
    check("va noi ro vi sao", bool(bas_entry["why_not"]), bas_entry["why_not"])
    check("BAS moi hon van dung dau danh sach (sap xep theo phien ban)",
          engines[0]["family"] == "bas", engines[0]["family"])
    check("mac dinh BO QUA BAS, ghim ShardX 148.0.7778.216",
          got == "ShardX 148.0.7778.216", got)
    check("JS includes('ShardX') nhan ra", js_is_shardx(got), got)

    print("\n=== 4. KHONG CO GI -> van la mot ghim ShardX chay duoc ===")
    with using(host(shardx=[], bas=[], supports_bas=False, latest="151.0.7900.10")):
        got = pm.resolve_default_browser_version()
    check("ghim ban dang phat hanh", got == "ShardX 151.0.7900.10", got)
    check("JS includes('ShardX') nhan ra", js_is_shardx(got), got)
    check("KHONG phai hang so tran cu '149.0.7827.54'", got != "149.0.7827.54", got)

    print("\n=== 5. khong co gi VA mat mang -> FALLBACK_VERSION, van co tien to ===")
    with using(host(shardx=[], bas=[], supports_bas=False)), \
         mock.patch.object(sx, "current_version", mock.Mock(side_effect=OSError("no network"))):
        got = pm.resolve_default_browser_version()
    check("dung FALLBACK_VERSION co tien to", got == "ShardX " + sx.FALLBACK_VERSION, got)
    check("JS includes('ShardX') nhan ra", js_is_shardx(got), got)

    print("\n=== 6. host khong chay duoc BAS: nen tang chi la MOT dau vao cua usable ===")
    with using(host(shardx=["149.0.7827.103"], bas=["30.2.0"],
                    supports_bas=False, key=KEY_OK)):
        engines = sx.installed_engines()
        got = pm.resolve_default_browser_version()
    bas_entry = [e for e in engines if e["family"] == "bas"][0]
    check("BAS khong dung duoc du khoa TOT", bas_entry["usable"] is False)
    check("ly do noi ve binary Windows", "Windows" in bas_entry["why_not"], bas_entry["why_not"])
    check("mac dinh la ShardX", got == "ShardX 149.0.7827.103", got)

    print("\n=== 7. trang thai khoa BAS: khong ton mot luot mang nao ===")
    src_sx = inspect.getsource(sx.bas_key_state)
    check("bas_key_state khong goi requests/axios",
          "requests" not in src_sx and "urlopen" not in src_sx)

    now = time.time()
    cases = [
        ("khoa rieng da dat, chua co phan quyet", "local:abc", {}, True),
        ("dau HONG con han", "shared",
         {"bas_key": {"key_id": "shared", "verdict": "bad", "at": now - 60,
                      "reason": "Key expired"}}, False),
        ("dau HONG da het han -> thu lai", "shared",
         {"bas_key": {"key_id": "shared", "verdict": "bad",
                      "at": now - sx.BAS_KEY_BAD_TTL - 10}}, False),
        ("dau TOT con han", "shared",
         {"bas_key": {"key_id": "shared", "verdict": "ok", "at": now - 60}}, True),
        ("dau TOT da het han", "shared",
         {"bas_key": {"key_id": "shared", "verdict": "ok",
                      "at": now - sx.BAS_KEY_OK_TTL - 10}}, False),
        ("dan khoa MOI -> dau hong cua khoa cu het hieu luc", "local:new",
         {"bas_key": {"key_id": "local:old", "verdict": "bad", "at": now}}, True),
    ]
    for label, key_id, state, expect_available in cases:
        with mock.patch.object(sx, "_local_bas_key", lambda: "" if key_id == "shared" else "K"), \
             mock.patch.object(sx, "_bas_key_id", lambda k, _id=key_id: _id), \
             mock.patch.object(sx, "_read_engine_state", lambda _s=state: dict(_s)):
            st = sx.bas_key_state()
        check(f"[{label}] available={expect_available}",
              st["available"] is expect_available, str(st))
        if not st["available"]:
            check(f"[{label}] co ly do de hien cho nguoi dung", bool(st["why_not"]), str(st))

    print("\n=== 8. mot luot mo hong vi khoa lam kiem ke thoi tien cu BAS ===")
    written = {}

    def fake_write(state):
        written.clear()
        written.update(state)
        return True

    with mock.patch.object(sx, "_local_bas_key", lambda: ""), \
         mock.patch.object(sx, "_read_engine_state", lambda: {}), \
         mock.patch.object(sx, "_write_engine_state", fake_write):
        ok = sx.mark_bas_key_bad("Key expired!")
    check("mark_bas_key_bad ghi duoc", ok is True)
    check("ghi dung phan quyet", written.get("bas_key", {}).get("verdict") == "bad", str(written))
    check("gan voi danh tinh khoa dang dung",
          written.get("bas_key", {}).get("key_id") == "shared", str(written))
    check("KHONG luu chinh chuoi khoa", "K" not in str(written.get("bas_key", {}).get("key_id")))

    with mock.patch.object(sx, "_local_bas_key", lambda: ""), \
         mock.patch.object(sx, "_read_engine_state", lambda: dict(written)):
        st = sx.bas_key_state()
    check("sau khi danh dau, khoa bi coi la khong dung duoc", st["available"] is False, str(st))
    check("ly do giu nguyen thong diep that", "Key expired" in st["why_not"], st["why_not"])

    with using(host(shardx=["148.0.7778.97"], bas=["30.2.0"], supports_bas=True)), \
         mock.patch.object(sx, "bas_key_state", lambda: st):
        got = pm.resolve_default_browser_version()
    check("=> profile moi khong con bi dong dau ghim BAS", js_is_shardx(got), got)

    print("\n=== 9. khong exception nao thoat vao create_profile ===")
    raisers = [
        ("installed_versions no", {"installed_versions": OSError("io")}),
        ("installed_bas_versions no", {"installed_bas_versions": OSError("io")}),
        ("supports_bas no", {"supports_bas": RuntimeError("boom")}),
        ("bas_key_state no", {"bas_key_state": RuntimeError("boom")}),
        ("current_version no", {"current_version": OSError("io")}),
        ("installed_engines no", {"installed_engines": RuntimeError("boom")}),
        ("default_engine_pin no", {"default_engine_pin": RuntimeError("boom")}),
    ]
    for label, blowups in raisers:
        patches = host(shardx=[], bas=["30.2.0"], supports_bas=True)
        for fname, exc in blowups.items():
            patches.append(mock.patch.object(sx, fname, mock.Mock(side_effect=exc)))
        with using(patches):
            try:
                got, raised = pm.resolve_default_browser_version(), None
            except BaseException as e:      # khong duoc phep xay ra
                got, raised = None, e
        check(f"[{label}] khong nem ra ngoai", raised is None, repr(raised))
        check(f"[{label}] van tra ve ghim ShardX", js_is_shardx(got), str(got))

    print("\n=== 10. chinh cau import HONG -> van chay (ly do phai import muon) ===")
    with broken_import():
        try:
            got, raised = pm.resolve_default_browser_version(), None
        except BaseException as e:
            got, raised = None, e
    check("khong nem ra ngoai", raised is None, repr(raised))
    check("van ghim ShardX", js_is_shardx(got), str(got))
    check("dung hang so du phong trong file",
          got == "ShardX " + pm._SHARDX_FALLBACK_VERSION, str(got))
    check("hang so du phong khop shardx_runtime.FALLBACK_VERSION",
          pm._SHARDX_FALLBACK_VERSION == sx.FALLBACK_VERSION,
          f"{pm._SHARDX_FALLBACK_VERSION} vs {sx.FALLBACK_VERSION}")

    print("\n=== 11. hoi quy: khong to hop nao lot ra so tran khi BAS khong dung duoc ===")
    # Chi can MOT to hop lot ra so tran la du de tai tao con bug 23/23.
    bare_leaks = []
    combos = []
    for shardx in ([], ["149.0.7827.103"], ["148.0.7778.97", "149.0.7827.103"]):
        for bas in ([], ["30.2.0"], ["29.5.0", "30.2.0"]):
            for supports in (True, False):
                for key in (KEY_EXPIRED, {"available": False, "why_not": ""}):
                    combos.append((shardx, bas, supports, key))
    for shardx, bas, supports, key in combos:
        with using(host(shardx=shardx, bas=bas, supports_bas=supports, key=key)):
            out = pm.resolve_default_browser_version()
        if not js_is_shardx(out):
            bare_leaks.append(f"shardx={shardx} bas={bas} win={supports} -> {out!r}")
    check(f"{len(combos)} to hop, khong cai nao ra so tran", not bare_leaks,
          "; ".join(bare_leaks[:3]))

    print("\n=== 12. bang quy doi BAS chi con MOT ban ===")
    check("bang song trong shardx_runtime", isinstance(sx.BAS_TO_CHROMIUM, dict))
    check("profile_manager khong con ban chep",
          "_BAS_TO_CHROMIUM" not in src and "'30.2.0'" not in src)
    check("engine BAS la o ngoai bang van ghim duoc",
          sx.bas_chromium_for("99.9.9") == max(sx.BAS_TO_CHROMIUM.values(),
                                               key=sx._version_key),
          sx.bas_chromium_for("99.9.9"))

    print("\n=== 13. hinh dang JSON ma Builder B va API se doc ===")
    with using(host(shardx=["149.0.7827.103"], bas=["30.2.0"], supports_bas=True)), \
         mock.patch.object(sx, "fingerprints_installed", lambda: True):
        inv = sx.engine_inventory()
    for field in ("engines", "default_pin", "usable_count", "bas", "shardx", "generated_at"):
        check(f"co khoa '{field}'", field in inv, str(sorted(inv)))
    for field in ("family", "version", "engine_version", "pin", "installed", "usable",
                  "runnable_here", "why_not"):
        check(f"moi engine co '{field}'", all(field in e for e in inv["engines"]))
    check("default_pin khop resolve_default_browser_version",
          inv["default_pin"] == "ShardX 149.0.7827.103", inv["default_pin"])
    check("usable_count dem dung", inv["usable_count"] == 1, str(inv["usable_count"]))
    check("bao trang thai khoa BAS cho UI", "key" in inv["bas"], str(inv["bas"]))
    import json as _json
    try:
        _json.dumps(inv)
        serialisable = True
    except TypeError as e:
        serialisable = False
        print("   ", e)
    check("serialise duoc sang JSON", serialisable)

    print("\n=== 14. may CHI CO BAS: 'dung duoc' khat khe den dau thi dung lai ===")
    # Con bug doi chieu, do duoc bang mo phong: mot may Windows chi cai BAS va chay
    # bang khoa DUNG CHUNG khong bao gio co verdict "ok" (mark_bas_key_ok chi duoc
    # goi sau mot luot mo BAS that). Neu "khong usable" la het chuyen thi may do
    # nhan ghim ShardX CHUA TAI VE, va MOI profile moi o do thanh khong mo duoc —
    # trong khi truoc thay doi nay chung chay binh thuong.
    #
    # Nen default_engine_pin() co bac 2: khong nhan nao usable thi muon nhan da cai
    # ma host chay duoc VA khong co bang chung nao noi no chet.
    KEY_UNKNOWN = {"available": False, "verdict": "unknown",
                   "why_not": "chua cau hinh khoa BAS rieng, khoa dung chung chua tung mo duoc"}

    with using(host(shardx=[], bas=["30.2.0"], supports_bas=True, key=KEY_UNKNOWN)):
        got_unknown = pm.resolve_default_browser_version()
        entries_unknown = sx.installed_engines()
    check("chi co BAS + khoa CHUA RO -> ghim chinh BAS da cai (so tran)",
          got_unknown == "149.0.7827.54", got_unknown)
    check("van khai bao THANG la no chua chac dung duoc",
          entries_unknown[0]["usable"] is False and entries_unknown[0]["runnable_here"] is True,
          str(entries_unknown[0]))

    with using(host(shardx=[], bas=["30.2.0"], supports_bas=True, key=KEY_EXPIRED)):
        got_bad = pm.resolve_default_browser_version()
    check("cung may do nhung khoa DA CHET -> khong muon BAS nua, ghim ShardX",
          js_is_shardx(got_bad), got_bad)

    with using(host(shardx=[], bas=["30.2.0"], supports_bas=False, key=KEY_UNKNOWN)):
        got_linux = pm.resolve_default_browser_version()
    check("host khong chay duoc BAS -> khong muon, du khoa chua ro",
          js_is_shardx(got_linux), got_linux)

    # Khong doc duoc trang thai khoa thi KHONG muon: muon phai dua tren hieu biet,
    # khong dua tren im lang. (host() mac dinh tra ve dict khong co 'verdict', dung
    # nhu nhanh _bas_entries() bat exception.)
    with using(host(shardx=[], bas=["30.2.0"], supports_bas=True)):
        got_silent = pm.resolve_default_browser_version()
    check("khong doc duoc verdict -> khong muon BAS", js_is_shardx(got_silent), got_silent)

    with using(host(shardx=["149.0.7827.103"], bas=["30.2.0"],
                    supports_bas=True, key=KEY_UNKNOWN)):
        got_both = pm.resolve_default_browser_version()
    check("co ShardX thi bac 1 van thang, bac 2 khong duoc chen ngang",
          got_both == "ShardX 149.0.7827.103", got_both)

    print("\n=== 15. chieu 'khoa con song' phai co nguoi goi that ===")
    # mark_bas_key_ok() tung khong co MOT cho goi nao trong ma san pham, nen verdict
    # chi di duoc mot chieu: hong thi ghi, tot thi khong ai ghi. Ket qua la may o
    # case 14 vinh vien ket o "unknown". Nguoi goi dung la monitor nen trong
    # process_manager: no luon thay tien trinh ket thuc VA doc duoc ca log.
    pm_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "tubecli", "extensions", "browser", "process_manager.py"),
                     encoding="utf-8").read()
    check("process_manager goi mark_bas_key_ok", "mark_bas_key_ok" in pm_src)
    check("process_manager goi note_launch_output (chieu hong)",
          "note_launch_output" in pm_src)
    bm_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "tubecli", "extensions", "browser", "browser_manager.js"),
                     encoding="utf-8").read()
    check("browser_manager in dau moc BAS_LAUNCH_OK sau khi mo duoc",
          "BAS_LAUNCH_OK" in bm_src)
    check("hai ben dung DUNG mot chuoi", "BAS_LAUNCH_OK" in pm_src)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
