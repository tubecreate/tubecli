"""The agent run log: what it must record, and what it must never record.

Run:  python tests/run_log_test.py     (exit 0 = pass)

Two things are being locked in here.

First, credentials must never reach disk. The browser launcher is invoked with
--login-password on its argv for any profile with a saved login, and this store
captures excerpts of the log that argv is echoed into. Without the redactor,
adding run logging would have turned a transient leak into a permanent one,
served over HTTP to anyone with a dashboard session.

Second, a run whose process vanished must still resolve to a terminal state. The
server can be killed by systemd or the OOM killer mid-run, and there is then no
writer left to close the run out. Folding is done at read time from the age of
the row, so a crash needs no recovery pass — but only if the age rules are right,
which is what the fold tests check.
"""
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import tubecli.config as cfg

TMP = Path(tempfile.mkdtemp(prefix="run_log_"))
_REAL_EXT_DATA_PATH = cfg.ext_data_path
cfg.ext_data_path = lambda *parts: TMP.joinpath(*parts)

from tubecli.core import run_log

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def reset():
    for f in TMP.glob("agent_runs/*.jsonl"):
        f.unlink()


def raw_lines():
    p = run_log._day_file()
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def main():
    try:
        print("=== 1. LOC MAT KHAU (quan trong nhat) ===")
        # The exact shape process_manager builds, and the exact shape open.js prints.
        flat = "node open.js --profile p1 --login-email a@b.com --login-password Hunter2! --instance-id x"
        r = run_log.redact(flat)
        check("mat khau bien mat khoi dong lenh", "Hunter2!" not in r, r)
        check("  email cung bien mat", "a@b.com" not in r, r)
        check("  van doc duoc phan con lai", "--profile p1" in r and "--instance-id x" in r, r)

        argv_style = "\n".join([
            "RAW ARGV: [", "  'node',", "  '--login-password',", "  'SieuBiMat123',",
            "  '--profile',", "  'hihi',", "]"])
        r2 = run_log.redact(argv_style)
        check("dang argv nhieu dong: gia tri o dong sau bi che",
              "SieuBiMat123" not in r2, r2.replace("\n", " | "))
        check("  gia tri khong phai bi mat thi giu nguyen", "'hihi'," in r2)

        check("None khong lam no vo", run_log.redact(None) is None)

        print("\n=== 2. GHI VA GAP MOT LAN CHAY THANH CONG ===")
        reset()
        rid = run_log.new_run_id()
        run_log.start(rid, "ag1", "Agent Một", trigger="schedule",
                      scheduled_for="2026-08-09T03:00:00", overdue_sec=12.4)
        run_log.launch(rid, "ag1", profile="hihi", query="phở", spawn_status="running",
                       instance_id="browser-1", pid=42, max_duration_sec=360)
        run_log.end(rid, "ag1", "completed", return_code=0,
                    instance_id="browser-1", duration_sec=321.7)

        runs = run_log.list_for_agent("ag1")
        check("tra ve dung 1 lan chay", len(runs) == 1, str(len(runs)))
        run = runs[0]
        check("  ket qua la completed", run["outcome"] == "completed", str(run.get("outcome")))
        check("  giu ten agent", run.get("agent_name") == "Agent Một", str(run.get("agent_name")))
        check("  giu profile", run.get("profile") == "hihi")
        check("  giu thoi luong", run.get("duration_sec") == 321.7)
        check("  ghi dung 3 dong", len(raw_lines()) == 3, str(len(raw_lines())))

        print("\n=== 3. KHONG LAN AGENT KHAC ===")
        reset()
        a = run_log.new_run_id(); b = run_log.new_run_id()
        run_log.start(a, "ag1", "Một"); run_log.start(b, "ag2", "Hai")
        check("ag1 chi thay lan chay cua minh", len(run_log.list_for_agent("ag1")) == 1)
        check("ag2 chi thay lan chay cua minh", len(run_log.list_for_agent("ag2")) == 1)

        print("\n=== 4. LAN CHAY BI BO DO -> VAN CO KET LUAN ===")
        # Nothing is left alive to close these out; the fold must do it by age.
        reset()
        old = (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat()
        rid = "run-cu"
        run_log._append({"kind": "start", "run_id": rid, "ts": old,
                         "agent_id": "ag1", "agent_name": "Một", "trigger": "schedule"})
        run = run_log.list_for_agent("ag1")[0]
        check("start cu, khong co launch -> never_started",
              run["outcome"] == "never_started", str(run["outcome"]))

        reset()
        rid = "run-treo"
        run_log._append({"kind": "start", "run_id": rid, "ts": old, "agent_id": "ag1"})
        run_log._append({"kind": "launch", "run_id": rid, "ts": old, "agent_id": "ag1",
                         "spawn_status": "running", "max_duration_sec": 360})
        run = run_log.list_for_agent("ag1")[0]
        check("launch cu, khong co end -> interrupted",
              run["outcome"] == "interrupted", str(run["outcome"]))

        reset()
        rid = run_log.new_run_id()
        run_log.start(rid, "ag1", "Một")
        run_log.launch(rid, "ag1", spawn_status="running", max_duration_sec=360)
        run = run_log.list_for_agent("ag1")[0]
        check("vua chay xong -> running (chua ket luan voi)",
              run["outcome"] == "running", str(run["outcome"]))

        print("\n=== 5. SPAWN HONG -> GIU LY DO, DA LOC ===")
        reset()
        rid = run_log.new_run_id()
        run_log.start(rid, "ag1", "Một")
        run_log.launch(rid, "ag1", spawn_status="error",
                       error="Browser process exited immediately (code 1).",
                       log_tail="RAW ARGV: [\n  '--login-password',\n  'LoRo123',\n]")
        run = run_log.list_for_agent("ag1")[0]
        check("ket qua la launch_failed", run["outcome"] == "launch_failed")
        check("  giu thong bao loi", "exited immediately" in (run.get("error") or ""))
        check("  log kem theo DA loc mat khau",
              "LoRo123" not in json.dumps(run, ensure_ascii=False))

        print("\n=== 6. LY DO KHONG CHAY ===")
        reset()
        run_log.skip("ag1", "Một", "outside_window", "Ngoài khung giờ 08:00–22:00.",
                     next_attempt="2026-08-10T08:00:00")
        entries = run_log.list_for_agent("ag1")
        check("co ghi lai lan bi bo qua", len(entries) == 1)
        check("  danh dau la skip", entries[0]["type"] == "skip", str(entries[0].get("type")))
        check("  noi ro ly do", "khung giờ" in entries[0]["detail"])
        check("  co gio thu lai", entries[0]["next_attempt"] == "2026-08-10T08:00:00")

        print("\n=== 7. DONG RACH KHONG KEO DO DONG SAU ===")
        # A kill mid-append leaves a file with no trailing newline. The next
        # append must not fuse onto it — that would destroy two records, and the
        # second is usually the one explaining the crash.
        reset()
        p = run_log._day_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"kind": "start", "run_id": "run-x", "agent_i',
                     encoding="utf-8", newline="\n")
        rid = run_log.new_run_id()
        run_log.start(rid, "ag1", "Một")
        lines = raw_lines()
        check("dong moi nam rieng mot dong", len(lines) == 2, str(len(lines)))
        check("  dong moi doc duoc", json.loads(lines[-1])["run_id"] == rid)
        check("  dong rach bi bo qua, khong lam vo ham doc",
              len(run_log.list_for_agent("ag1")) == 1)

        print("\n=== 8. DON DEP KHONG DUOC AN FILE HOM NAY ===")
        reset()
        run_log.start(run_log.new_run_id(), "ag1", "Một")
        today = run_log._day_file()
        old_file = TMP / "agent_runs" / "runs-2020-01-01.jsonl"
        old_file.write_text('{"kind":"skip"}\n', encoding="utf-8")
        run_log.sweep()
        check("file qua han bi xoa", not old_file.exists())
        check("  file hom nay con nguyen", today.exists())

        print("\n=== 9. NOI DAY: process_manager ghi duoc dong 'end' ===")
        # The unit tests above prove the store works. This proves the browser
        # monitor actually reaches it — the wiring is where this would silently
        # do nothing.
        reset()
        from tubecli.extensions.browser.process_manager import BrowserProcessManager
        pm = BrowserProcessManager()
        rid = run_log.new_run_id()
        run_log.start(rid, "ag9", "Chín")

        leaky = TMP / "fake_instance.log"
        leaky.write_text("RAW ARGV: [\n  '--login-password',\n  'MatKhauThat',\n]\nboom\n",
                         encoding="utf-8")
        pm._record_run_end(rid, "ag9", "browser-9", "error", 1,
                           datetime.datetime.now().isoformat(), str(leaky))
        runs = run_log.list_for_agent("ag9")
        check("co dong end", len(runs) == 1 and runs[0].get("outcome") == "error",
              str(runs[0].get("outcome") if runs else "khong co"))
        check("  co kem log de doc", bool(runs[0].get("log_tail")))
        check("  log da loc mat khau",
              "MatKhauThat" not in json.dumps(runs[0], ensure_ascii=False))

        check("spawn nhan run_id/agent_id",
              all(p in __import__("inspect").signature(pm.spawn).parameters
                  for p in ("run_id", "agent_id")))

        # A manual dashboard launch has no run_id and must record nothing.
        reset()
        pm._record_run_end(None, None, "browser-x", "completed", 0,
                           datetime.datetime.now().isoformat(), None)
        check("mo tay (khong run_id) thi khong ghi gi", len(raw_lines()) == 0,
              str(len(raw_lines())))

        print("\n=== 10. LOI KHI GHI KHONG DUOC NEM RA NGOAI ===")
        # The store must never be able to break a scheduler tick.
        saved = run_log._day_file
        run_log._day_file = lambda *a, **k: (_ for _ in ()).throw(OSError("đĩa đầy"))
        try:
            run_log.start("r", "ag1", "Một")   # must not raise
            check("ghi that bai van im lang", True)
        except Exception as e:
            check("ghi that bai van im lang", False, str(e))
        finally:
            run_log._day_file = saved
    finally:
        cfg.ext_data_path = _REAL_EXT_DATA_PATH
        shutil.rmtree(TMP, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
