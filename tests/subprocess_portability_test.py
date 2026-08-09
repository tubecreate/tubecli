"""No subprocess call may pass an argument LIST together with shell=True.

Run:  python tests/subprocess_portability_test.py     (exit 0 = pass)

Why this file exists. `subprocess.Popen(["node", "open.js", "--profile", p],
shell=True)` means two entirely different things depending on the platform:

  Windows (CPython subprocess.py, _execute_child):
      args = list2cmdline(args)          -> `node open.js --profile p`
  POSIX (CPython subprocess.py, _execute_child):
      args = ['/bin/sh', '-c'] + args    -> sh -c "node" "open.js" "--profile" "p"

On POSIX only args[0] is the command; everything after it is bound to $0, $1...
and is silently discarded unless the command string references them. So the call
above runs a bare `node`, which reads EOF on stdin and exits 0 immediately.

This shipped three separate times in this repo. It is invisible on Windows, it
produces no error on Linux (exit code 0), and the surrounding code read that as
success — a scheduled agent recorded a browser run that never happened, and an
extension reported a successful install having installed nothing.

The property locked in here: if you pass a list, you do not pass shell=True.
Passing a STRING with shell=True is fine and stays allowed — that is the only
form that behaves the same on both platforms.
"""
import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "tubecli"

_SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def _is_truthy_shell(node: ast.AST) -> bool:
    """True only when shell= is a literal True. A variable is left alone."""
    return isinstance(node, ast.Constant) and node.value is True


def _is_list_arg(node: ast.AST) -> bool:
    """True when the first positional arg is written as a list/tuple literal.

    A name (`args`, `cmd`) cannot be judged from the call site alone, so it is
    not reported here — process_manager.py's `args` was exactly that shape and
    is covered by the dedicated regression below instead.
    """
    return isinstance(node, (ast.List, ast.Tuple))


def offending_calls(tree: ast.AST):
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in _SPAWNERS:
            continue
        shell = next((k for k in node.keywords if k.arg == "shell"), None)
        if shell is None or not _is_truthy_shell(shell.value):
            continue
        if node.args and _is_list_arg(node.args[0]):
            out.append(node.lineno)
    return out


def main():
    print("=== 1. quet toan bo goi tubecli/ ===")
    scanned = 0
    bad = {}
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            check(f"phan tich duoc {path.name}", False, str(e))
            continue
        scanned += 1
        lines = offending_calls(tree)
        if lines:
            bad[str(path.relative_to(ROOT))] = lines

    check(f"quet duoc {scanned} file", scanned > 50, f"{scanned} file")
    check("khong con list + shell=True", not bad,
          "; ".join(f"{f}:{l}" for f, l in bad.items()) or "sach")

    print("\n=== 2. cac cho da sua, kiem tra ro tung cai ===")
    # Count real shell=True keywords via the AST. A plain substring scan matches
    # the comments that EXPLAIN the bug — which is exactly what happened when
    # this test was first written, and it failed on its own prose.
    def shell_true_count(path: Path) -> int:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(
                    k.arg == "shell" and _is_truthy_shell(k.value)
                    for k in node.keywords):
                n += 1
        return n

    pm_path = PKG / "extensions" / "browser" / "process_manager.py"
    pm = pm_path.read_text(encoding="utf-8", errors="replace")
    check("process_manager: khong con shell=True nao",
          shell_true_count(pm_path) == 0, f"{shell_true_count(pm_path)} cho")
    check("process_manager: co giai ra duong dan node",
          'shutil.which("node")' in pm)
    check("process_manager: gan lai args[0]", "args[0] = node_exe" in pm)

    em_path = PKG / "core" / "extension_manager.py"
    em = em_path.read_text(encoding="utf-8", errors="replace")
    check("extension_manager: khong con shell=True nao",
          shell_true_count(em_path) == 0, f"{shell_true_count(em_path)} cho")
    check("extension_manager: npm qua _run_node_tool",
          em.count("_run_node_tool(") >= 4, f"{em.count('_run_node_tool(')} lan")

    print("\n=== 3. chuoi + shell=True van duoc phep ===")
    # The Windows-only `start`/`taskkill`/`wmic` calls are strings and must not
    # be flagged, or this test would push someone into rewriting working code.
    sample = ast.parse(
        'subprocess.run("taskkill /F /IM python.exe", shell=True)\n'
        'subprocess.Popen(f"start cmd /k {x}", shell=True)\n'
    )
    check("khong bat nham dang chuoi", offending_calls(sample) == [],
          str(offending_calls(sample)))

    print("\n=== 4. bat dung dang list ===")
    sample_bad = ast.parse(
        'subprocess.Popen(["node", "open.js"], shell=True)\n'
        'subprocess.run(("npm", "install"), shell=True, cwd=d)\n'
        'subprocess.run(["npm", "install"])\n'          # fine, no shell
        'subprocess.run(["npm"], shell=flag)\n'         # variable, not judged
    )
    check("bat ca list va tuple", offending_calls(sample_bad) == [1, 2],
          str(offending_calls(sample_bad)))

    print("\n=== 5. hanh vi POSIX that su (tai hien) ===")
    # Not a mock: build the exact argv CPython would build on POSIX and show
    # that the trailing elements vanish. Skipped where there is no /bin/sh.
    import shutil as _shutil
    import subprocess as sp
    # which("sh") rather than a hardcoded /bin/sh: native Windows Python cannot
    # see the MSYS path, but it does find sh.exe, which behaves the same here.
    shell_path = _shutil.which("sh") or ("/bin/sh" if os.path.exists("/bin/sh") else None)
    if shell_path:
        probe = "echo CMD=$0 ARG1=$1"
        r = sp.run([shell_path, "-c", probe, "open.js", "--profile"],
                   capture_output=True, text=True, timeout=10)
        check("args[1:] bi day sang $0/$1, khong phai tham so",
              "CMD=open.js" in r.stdout and "ARG1=--profile" in r.stdout,
              r.stdout.strip())
    else:
        print("  (khong co /bin/sh — bo qua)")

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
