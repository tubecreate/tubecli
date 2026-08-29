# -*- coding: utf-8 -*-
"""Giet ca cay tien trinh, va CHUNG MINH no da chet.

Run:  python tests/kill_tree_test.py     (exit 0 = pass)

Vi sao co file nay. _kill_tree() ban cu chi chay mot lenh:

    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], ...)
    except Exception:  process.terminate()

`taskkill` CHI CO tren Windows. Tren Linux no nem FileNotFoundError, roi xuong
process.terminate() — mot SIGTERM gui cho MOI tien trinh node. Chromium la con
cua node nen khong nhan duoc gi: no o lai mo coi, van giu user-data-dir va
SingletonLock cua ho so. Nhanh het gio con te hon: no goi _kill_tree roi ghi
ngay "timeout_killed" va return, khong mot lan process.wait(). Bang chung tu
may that: mot luot hen gio duoc ghi la "Timed out 4m", mot phut sau luot ke
tiep bi chan boi "Profile <tuan3> is being controlled by <agent> (opened 6 min
ago)" — tuc la cai duoc ghi la DA DUNG van dang chay.

Nen file nay khong kiem "co goi lenh giet khong". No kiem: BAN RA TIN HIEU ROI
THI CO AI CHET KHONG, va he thong co dam noi that khi khong ai chet khong.

GIOI HAN CUA HOST DANG CHAY — doc truoc khi tin ket qua:
  * Muc 1, 2, 3, 6, 7 chay THAT tren may nay: tien trinh that, con chau that.
    Chung chi chung minh nhanh cua CHINH nen tang nay (os.name).
  * Chay tren Windows thi nhanh POSIX (os.killpg, SIGTERM roi SIGKILL) KHONG
    he duoc thuc thi o day — no chi duoc kiem bang ham gia o muc 4. Khong dong
    nao trong file nay la bang chung ve Linux.
Muc 0 in ra host that su dang chay nhanh nao.
"""
import os
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import psutil

from tubecli.extensions.browser.process_manager import (
    BrowserProcessManager, KillResult, _process_group_kwargs,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PM_SRC = os.path.join(ROOT, "tubecli", "extensions", "browser", "process_manager.py")

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


# ── Tien trinh that de giet ──────────────────────────────────────────────────
# Chau ngu mai mai va KHONG chet theo cha: do dung la hinh dang cua chromium
# duoi node. Neu chi terminate() cha thi chau nay con song — muc 2 chung minh.
_GRANDCHILD = "import time\nwhile True: time.sleep(1)"
_CHILD = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', " + repr(_GRANDCHILD) + "])\n"
    "open(sys.argv[1], 'w').write(str(g.pid))\n"
    "time.sleep(600)\n"
)


def spawn_tree(tmpdir):
    """Cha + chau that, mo dung bang co ma spawn() dung. Tra (proc, pid_chau)."""
    pidfile = os.path.join(tmpdir, "gc_" + uuid.uuid4().hex + ".pid")
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD, pidfile],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **_process_group_kwargs()
    )
    gpid = None
    for _ in range(150):
        try:
            if os.path.getsize(pidfile) > 0:
                gpid = int(open(pidfile).read().strip())
                break
        except Exception:
            pass
        time.sleep(0.1)
    return proc, gpid


def alive(pid):
    if pid is None:
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return True


def wait_gone(pid, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


def hard_kill(pid):
    """Don rac cua chinh test nay, khong bao gio de lai tien trinh treo."""
    try:
        p = psutil.Process(pid)
        p.kill()
        p.wait(timeout=5)
    except Exception:
        pass


class LyingProc:
    """Popen gia noi doi dung MOT dieu: no khong bao gio thua nhan da chet.

    Boc quanh mot tien trinh THAT nen tin hieu van ban vao mot pid that (khong
    ban nham ai), nhung poll()/wait() luon bao "van chay". Day dung la hinh
    dang cua bug: he thong ban tin hieu roi tuyen bo xong ma khong co bang
    chung. _kill_tree phai tra ve confirmed=False cho ca nay.
    """

    def __init__(self, real):
        self._real = real
        self.pid = real.pid
        self.returncode = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("lying", timeout or 0)

    def kill(self):
        try:
            self._real.kill()
        except Exception:
            pass

    def terminate(self):
        try:
            self._real.terminate()
        except Exception:
            pass


def main():
    bpm = BrowserProcessManager()
    tmpdir = tempfile.mkdtemp(prefix="killtree_")
    posix = os.name != "nt"

    print("=== 0. host dang chay nhanh nao ===")
    print(f"  os.name={os.name!r}  ->  nhanh {'POSIX (killpg)' if posix else 'Windows (taskkill /T)'}")
    if not posix:
        print("  LUU Y: nhanh POSIX khong duoc thuc thi tren may nay. Muc 4 kiem")
        print("         logic leo thang bang ham gia, KHONG phai bang tin hieu that.")

    print("\n=== 1. cay THAT: giet cha thi chau cung phai chet ===")
    proc, gpid = spawn_tree(tmpdir)
    check("mo duoc cay that (cha + chau)", proc.poll() is None and gpid is not None,
          f"cha={proc.pid} chau={gpid}")
    check("  chau dang song truoc khi giet", alive(gpid), str(gpid))
    if posix:
        try:
            check("  cha co nhom rieng (pgid == pid)", os.getpgid(proc.pid) == proc.pid,
                  f"pgid={os.getpgid(proc.pid)}")
        except Exception as e:
            check("  cha co nhom rieng (pgid == pid)", False, str(e))
    else:
        print("  (Windows: khong co pgid de kiem — bo qua, khong phai PASS)")

    report = bpm._kill_tree(proc)
    check("_kill_tree tra ve KillResult, khong phai None",
          isinstance(report, KillResult), type(report).__name__)
    check("  no bao da giet duoc", bool(report) and report.confirmed, report.detail)
    check("  CHA that su chet", proc.poll() is not None, str(proc.poll()))
    check("  CHAU that su chet", wait_gone(gpid), f"pid {gpid}")
    hard_kill(gpid)

    print("\n=== 2. vi sao nhanh du phong cu KHONG du (tai hien tren may nay) ===")
    # Day la chinh xac nhung gi Linux lam moi lan het gio: taskkill khong ton
    # tai -> except -> process.terminate(). Chi cha nhan duoc, chau o lai.
    proc2, gpid2 = spawn_tree(tmpdir)
    check("mo duoc cay thu hai", proc2.poll() is None and gpid2 is not None,
          f"cha={proc2.pid} chau={gpid2}")
    proc2.terminate()
    try:
        proc2.wait(timeout=8)
    except subprocess.TimeoutExpired:
        pass
    check("terminate() giet duoc CHA", proc2.poll() is not None, str(proc2.poll()))
    orphan = alive(gpid2)
    check("terminate() KHONG cham duoc chau -> mo coi (dung nhu bug)", orphan,
          f"chau {gpid2} " + ("con song" if orphan else "da chet — nhanh cu du?"))
    hard_kill(gpid2)
    check("  don sach chau mo coi sau khi chung minh", not alive(gpid2), str(gpid2))

    print("\n=== 3. khong bao gio bao thanh cong khi chua co bang chung ===")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    rep_dead = bpm._kill_tree(dead)
    check("tien trinh da chet san -> confirmed True", rep_dead.confirmed, rep_dead.detail)

    # Tien trinh that, nhung Popen noi doi la no chua chet: phai bao KHONG XONG.
    decoy, _ = spawn_tree(tmpdir)
    lying = LyingProc(decoy)
    old_confirm = bpm._KILL_CONFIRM_SEC
    bpm._KILL_CONFIRM_SEC = 0.3
    try:
        rep_lie = bpm._kill_tree(lying, grace=0.2)
    finally:
        bpm._KILL_CONFIRM_SEC = old_confirm
    check("khong co bang chung chet -> confirmed False", not rep_lie.confirmed,
          rep_lie.detail)
    check("  bool(KillResult) di theo confirmed",
          bool(rep_lie) is False and bool(rep_dead) is True)
    check("  detail noi ro pid nao", str(decoy.pid) in rep_lie.detail, rep_lie.detail)
    hard_kill(decoy.pid)
    try:
        decoy.wait(timeout=5)
    except Exception:
        pass

    # _still_alive: ban than phep kiem phai bat duoc mot tien trinh con song.
    me = psutil.Process(os.getpid())
    got, checked = bpm._still_alive([(os.getpid(), me.create_time())], deadline=0.2)
    check("_still_alive bat duoc tien trinh con song", got == [os.getpid()] and checked,
          str(got))
    got2, _ = bpm._still_alive([(os.getpid(), me.create_time() - 9999)], deadline=0.2)
    check("  PID bi cap lai (create_time lech) khong bi tinh nham", got2 == [], str(got2))
    got3, checked3 = bpm._still_alive([], deadline=0.2)
    check("  anh chup rong -> khong co ai song", got3 == [] and checked3)

    print("\n=== 4. logic leo thang POSIX (ham gia — chay duoc tren moi nen) ===")
    import signal as _sig
    SIGTERM = getattr(_sig, "SIGTERM", 15)
    SIGKILL = getattr(_sig, "SIGKILL", 9)

    def make_ops(pgid_of, group_empty_after, log):
        """pgid_of: gia tri os.getpgid tra ve. group_empty_after: sau bao nhieu
        lan gui thi tin hieu 0 bao 'khong con ai'."""
        state = {"sends": 0}

        def getpgid(pid):
            if pgid_of is None:
                raise ProcessLookupError(pid)
            return pgid_of

        def killpg(pg, sig):
            if sig == 0:
                if state["sends"] >= group_empty_after:
                    raise ProcessLookupError(pg)
                return None
            state["sends"] += 1
            log.append(("killpg", pg, sig))

        def kill(pid, sig):
            if sig == 0:
                if state["sends"] >= group_empty_after:
                    raise ProcessLookupError(pid)
                return None
            state["sends"] += 1
            log.append(("kill", pid, sig))

        return {"getpgid": getpgid, "killpg": killpg, "kill": kill}

    # a) SIGTERM du: nhom rong ngay sau phat dau -> khong ban them SIGKILL.
    log = []
    sent = bpm._kill_group_posix(4242, 0, lambda t: True,
                                 _ops=make_ops(4242, 1, log))
    check("SIGTERM du thi khong SIGKILL them", sent == [SIGTERM], str(sent))
    check("  va ban vao ca NHOM chu khong rieng pid",
          log == [("killpg", 4242, SIGTERM)], str(log))

    # b) SIGTERM khong du (chromium con song) -> phai leo len SIGKILL.
    log = []
    sent = bpm._kill_group_posix(4242, 0, lambda t: True,
                                 _ops=make_ops(4242, 99, log))
    check("con tho thi leo len SIGKILL", sent == [SIGTERM, SIGKILL], str(sent))
    check("  ca hai phat deu vao nhom",
          log == [("killpg", 4242, SIGTERM), ("killpg", 4242, SIGKILL)], str(log))

    # c) Nhom khong phai cua rieng ta (pgid != pid): CAM killpg — no se cuon ca
    #    nhom cua may chu vao. Chi duoc ban dung pid do.
    log = []
    sent = bpm._kill_group_posix(4242, 0, lambda t: True,
                                 _ops=make_ops(1, 99, log))
    check("pgid != pid thi khong bao gio killpg",
          all(c[0] == "kill" for c in log) and log, str(log))
    check("  van leo thang tren dung pid do",
          [c[1] for c in log] == [4242, 4242] and sent == [SIGTERM, SIGKILL], str(log))

    # d) Chet san giua chung: ProcessLookupError o phat dau tien = het viec.
    log = []

    def ops_gone():
        def getpgid(pid):
            return pid

        def killpg(pg, sig):
            raise ProcessLookupError(pg)

        def kill(pid, sig):
            raise ProcessLookupError(pid)

        return {"getpgid": getpgid, "killpg": killpg, "kill": kill}

    sent = bpm._kill_group_posix(4242, 0, lambda t: True, _ops=ops_gone())
    check("da chet san -> khong gui gi them, khong nem", sent == [], str(sent))

    print("\n=== 5. spawn() mo tien trinh trong nhom cua rieng no ===")
    check("_process_group_kwargs(POSIX) = start_new_session",
          _process_group_kwargs(windows=False) == {"start_new_session": True},
          str(_process_group_kwargs(windows=False)))
    win_kw = _process_group_kwargs(windows=True)
    check("_process_group_kwargs(Windows) = creationflags",
          list(win_kw) == ["creationflags"], str(win_kw))
    if not posix:
        check("  dung co CREATE_NEW_PROCESS_GROUP",
              win_kw["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP,
              str(win_kw))
    src = open(PM_SRC, encoding="utf-8").read()
    check("spawn() that su truyen co do vao Popen",
          "**_process_group_kwargs()," in src)
    check("khong con nhanh du phong process.terminate() trong _kill_tree",
          "falling back to terminate" not in src)

    print("\n=== 6. duong het gio: ghi dung cai da xay ra ===")
    made = []
    try:
        # 6a. Giet duoc that -> chuoi cu "timeout_killed" GIU NGUYEN (run_log,
        #     tools/check_browsing.py va bang Hoat dong deu doc chuoi nay).
        proc3, gpid3 = spawn_tree(tmpdir)
        iid = "browser-test-ok"
        made.append(iid)
        with bpm._instances_lock:
            bpm._instances[iid] = {
                "instance_id": iid, "pid": proc3.pid, "profile": "test-killtree",
                "status": "running", "started_at": "2026-01-01T00:00:00",
                "_process": proc3, "_run_id": None, "_agent_id": None,
                "log_file": None,
            }
        bpm._monitor(iid, timeout_seconds=1)
        st = bpm.get_status(iid) or {}
        check("het gio + giet duoc -> status 'timeout_killed'",
              st.get("status") == "timeout_killed", str(st.get("status")))
        check("  co ghi la da xac nhan", st.get("kill_confirmed") is True,
              str(st.get("kill_confirmed")))
        # Ket cuc phai SONG SOT qua cac lan doc sau. get_status/list_running cu
        # ghi de moi luot doc, nen "timeout_killed" chi ton tai toi lan /status
        # ke tiep roi thanh "error" — chinh cho hien thi xoa mat su that.
        bpm.list_running()
        st_again = bpm.get_status(iid) or {}
        check("  van la 'timeout_killed' sau khi doc lai nhieu lan",
              st_again.get("status") == "timeout_killed", str(st_again.get("status")))
        check("  chau cung chet theo", wait_gone(gpid3), str(gpid3))
        hard_kill(gpid3)

        # 6b. Khong giet duoc -> KHONG duoc ghi la da dung.
        decoy2, gdec = spawn_tree(tmpdir)
        iid2 = "browser-test-fail"
        made.append(iid2)
        with bpm._instances_lock:
            bpm._instances[iid2] = {
                "instance_id": iid2, "pid": decoy2.pid, "profile": "test-killtree",
                "status": "running", "started_at": "2026-01-01T00:00:00",
                "_process": LyingProc(decoy2), "_run_id": None, "_agent_id": None,
                "log_file": None,
            }
        bpm._KILL_CONFIRM_SEC = 0.3
        bpm._KILL_GRACE_SEC = 0.2
        try:
            bpm._monitor(iid2, timeout_seconds=1)
        finally:
            bpm._KILL_CONFIRM_SEC = old_confirm
            bpm._KILL_GRACE_SEC = 5.0
        st2 = bpm.get_status(iid2) or {}
        check("het gio + KHONG giet duoc -> khong con la 'timeout_killed'",
              st2.get("status") != "timeout_killed", str(st2.get("status")))
        check("  co ket cuc rieng 'timeout_kill_failed'",
              st2.get("status") == "timeout_kill_failed", str(st2.get("status")))
        check("  noi ro chua xac nhan chet", st2.get("kill_confirmed") is False,
              str(st2.get("kill_confirmed")))
        check("  va noi ai con song", bool(st2.get("still_alive")),
              str(st2.get("still_alive")))
        check("  co dau KILL_UNCONFIRMED de run_log ghi lai",
              bpm._MARK_KILL_UNCONFIRMED == "KILL_UNCONFIRMED",
              bpm._MARK_KILL_UNCONFIRMED)
        hard_kill(decoy2.pid)
        hard_kill(gdec)

        print("\n=== 7. terminate() / stop_by_profile() cung phai that tha ===")
        proc4, gpid4 = spawn_tree(tmpdir)
        iid3 = "browser-test-term"
        made.append(iid3)
        with bpm._instances_lock:
            bpm._instances[iid3] = {
                "instance_id": iid3, "pid": proc4.pid, "profile": "test-killtree-2",
                "status": "running", "started_at": "2026-01-01T00:00:00",
                "_process": proc4, "_run_id": None, "_agent_id": None,
                "log_file": None,
            }
        ok = bpm.terminate(iid3)
        st3 = bpm.get_status(iid3) or {}
        check("terminate() giet duoc -> True + 'terminated'",
              ok is True and st3.get("status") == "terminated",
              f"{ok} / {st3.get('status')}")
        check("  chau cung chet", wait_gone(gpid4), str(gpid4))
        hard_kill(gpid4)

        decoy3, gdec3 = spawn_tree(tmpdir)
        iid4 = "browser-test-term-fail"
        made.append(iid4)
        with bpm._instances_lock:
            bpm._instances[iid4] = {
                "instance_id": iid4, "pid": decoy3.pid, "profile": "test-killtree-3",
                "status": "running", "started_at": "2026-01-01T00:00:00",
                "_process": LyingProc(decoy3), "_run_id": None, "_agent_id": None,
                "log_file": None,
            }
        bpm._KILL_CONFIRM_SEC = 0.3
        bpm._KILL_GRACE_SEC = 0.2
        try:
            ok2 = bpm.stop_by_profile("test-killtree-3")
        finally:
            bpm._KILL_CONFIRM_SEC = old_confirm
            bpm._KILL_GRACE_SEC = 5.0
        st4 = bpm.get_status(iid4) or {}
        check("stop_by_profile() khong giet duoc -> False (khong bao da dung)",
              ok2 is False, str(ok2))
        check("  status 'terminate_failed', khong phai 'terminated'",
              st4.get("status") == "terminate_failed", str(st4.get("status")))
        check("  ho so nay KHONG duoc coi la da roi",
              st4.get("kill_confirmed") is False, str(st4.get("kill_confirmed")))
        hard_kill(decoy3.pid)
        hard_kill(gdec3)
    finally:
        with bpm._instances_lock:
            for i in made:
                bpm._instances.pop(i, None)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    if not posix:
        print("(chay tren Windows: khong co dong nao o day la bang chung ve Linux)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
