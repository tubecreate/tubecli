"""The ffmpeg/ffprobe resolver must return a binary that RUNS.

Run:  python tests/ffmpeg_resolver_test.py     (exit 0 = pass)

Why this file exists. The resolver used shutil.which(), which answers "is there
a file with this name on PATH" — not "does it start". A conda install ships
Library/bin/ffprobe.exe that dies at load with exit 3221225785 (0xC0000139,
STATUS_ENTRYPOINT_NOT_FOUND) because a sibling DLL does not export a symbol it
links against. The server runs on that same conda Python, so which() returned
the broken copy, the resolver accepted it, and a working ffprobe further down
the very same PATH was never reached. Every probe then failed with a raw
"non-zero exit status 3221225785" and the UI told the user to install FFmpeg —
which was already installed.

Two properties are locked in: a candidate that does not run is skipped rather
than returned, and ALL PATH entries are considered, not just the first.

Selection is tested with _runs() stubbed, because a portable fake that really
executes is not available on Windows — a .bat renamed to .exe fails
CreateProcess, which would make the "working" fake look broken and prove
nothing. _runs() itself is then tested against real binaries on this machine.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.extensions.video_studio import ffmpeg_utils as fu

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
    tmp = tempfile.mkdtemp(prefix="ffres_")
    broken_dir = os.path.join(tmp, "broken")
    good_dir = os.path.join(tmp, "good")
    for d in (broken_dir, good_dir):
        os.makedirs(d, exist_ok=True)
    broken = os.path.join(broken_dir, fu._exe("ffprobe"))
    good = os.path.join(good_dir, fu._exe("ffprobe"))
    for p in (broken, good):
        with open(p, "wb") as f:
            f.write(b"placeholder")

    saved_path = os.environ.get("PATH", "")
    saved_cache = dict(fu._RESOLVED)
    real_runs = fu._runs

    def stub(exe):
        # Only the copy in good_dir "starts".
        return os.path.normcase(os.path.normpath(exe)) == os.path.normcase(os.path.normpath(good))

    try:
        print("=== 1. ban hong dung dau PATH van bi bo qua ===")
        os.environ["PATH"] = broken_dir + os.pathsep + good_dir
        fu._RESOLVED.clear()
        fu._runs = stub
        got = fu.find_ffprobe()
        check("khong tra ve ban hong", got is None or os.path.normcase(got) != os.path.normcase(broken),
              str(got))
        check("tra ve ban chay duoc o cuoi PATH",
              got is not None and os.path.normcase(got) == os.path.normcase(good), str(got))

        print("\n=== 2. shutil.which mot minh thi khong du ===")
        first = shutil.which("ffprobe")
        check("which() van tra ve ban hong dung dau",
              first is not None and os.path.normcase(first) == os.path.normcase(broken),
              str(first))

        print("\n=== 3. khong ban nao chay duoc -> None, khong nem loi ===")
        os.environ["PATH"] = broken_dir
        fu._RESOLVED.clear()
        check("tra ve None", fu.find_ffprobe() is None)

        print("\n=== 4. cache: nhieu lan goi chi probe mot lan ===")
        os.environ["PATH"] = good_dir
        fu._RESOLVED.clear()
        calls = {"n": 0}

        def counting(exe):
            calls["n"] += 1
            return stub(exe)

        fu._runs = counting
        for _ in range(5):
            fu.find_ffprobe()
        check("5 lan goi -> 1 lan probe", calls["n"] == 1, f"{calls['n']} lan")
    finally:
        fu._runs = real_runs
        os.environ["PATH"] = saved_path
        fu._RESOLVED.clear()
        fu._RESOLVED.update(saved_cache)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== 5. _runs() that, tren binary that ===")
    # A file that is not a valid executable must be rejected, not accepted.
    tmp2 = tempfile.mkdtemp(prefix="ffres2_")
    junk = os.path.join(tmp2, fu._exe("ffprobe"))
    with open(junk, "wb") as f:
        f.write(b"not an executable at all")
    check("file rac -> _runs() False", not fu._runs(junk))
    shutil.rmtree(tmp2, ignore_errors=True)

    conda = os.path.join(sys.prefix, "Library", "bin", fu._exe("ffprobe"))
    if os.path.isfile(conda):
        r = subprocess.run([conda, "-version"], capture_output=True, timeout=20)
        if r.returncode != 0:
            check("ban conda hong -> _runs() False", not fu._runs(conda),
                  f"exit {r.returncode}")
        else:
            check("ban conda o may nay chay duoc -> _runs() True", fu._runs(conda))
    else:
        print("  (khong co ban conda tren may nay)")

    print("\n=== 6. ket qua that tren may nay ===")
    fu._RESOLVED.clear()
    real = fu.find_ffprobe()
    if real:
        r = subprocess.run([real, "-version"], capture_output=True, timeout=20)
        check("ffprobe resolver chon duoc chay that", r.returncode == 0,
              f"{real} -> exit {r.returncode}")
    else:
        check("khong tim thay ffprobe nao chay duoc", True,
              "may nay chua co FFmpeg dung duoc")
    fu._RESOLVED.clear()

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
