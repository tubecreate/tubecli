# -*- coding: utf-8 -*-
"""Cú pháp f-string chỉ có từ Python 3.12 (PEP 701) KHÔNG được lọt vào lõi — pyproject khai requires-python >= 3.10.

Sự cố 9/11/2026: muse.py có  f"... minute{"s" if minutes != 1 else ""} ..."  (nháy kép lồng trong f-string nháy kép).
Python 3.12 chạy được; máy khách Python 3.11 cập nhật lên .230/.231 thì «SyntaxError: f-string: expecting '}'» và máy chủ
không bật được nữa. ast.parse(feature_version=(3, 10)) KHÔNG bắt lỗi này, nên test đọc token:

  - trong phần biểu thức {…} của một f-string có chuỗi / f-string dùng CÙNG loại nháy với f-string bao ngoài
  - trong phần biểu thức có dấu «\\» (3.12 mới cho)

Run:  python tests/py310_fstring_compat_test.py
"""
import io
import os
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _quote(tok_string: str) -> str:
    s = tok_string.lstrip("rRbBuUfF")
    return s[:3] if s[:3] in ('"""', "'''") else s[:1]


def problems(src: str):
    """[(dòng, lý do)] — cần Python 3.12 tokenize (FSTRING_START/MIDDLE/END)."""
    out = []
    stack = []        # mỗi f-string đang mở: [nháy, độ sâu ngoặc nhọn trong phần biểu thức]
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError):
        return out
    for tok in toks:
        ttype, s = tok.type, tok.string
        in_expr = bool(stack) and stack[-1][1] > 0
        if ttype == tokenize.FSTRING_START:
            if in_expr and _quote(s) in [q for q, _ in stack]:
                out.append((tok.start[0], "nested f-string reuses the enclosing quote"))
            stack.append([_quote(s), 0])
        elif ttype == tokenize.FSTRING_END:
            if stack:
                stack.pop()
        elif not stack:
            continue
        elif ttype == tokenize.OP and s == "{":
            stack[-1][1] += 1
        elif ttype == tokenize.OP and s == "}":
            stack[-1][1] = max(0, stack[-1][1] - 1)
        elif in_expr and ttype == tokenize.STRING:
            if _quote(s) in [q for q, _ in stack]:
                out.append((tok.start[0], "string inside {…} reuses the f-string's quote"))
            elif "\\" in s:
                out.append((tok.start[0], "backslash inside {…} of an f-string"))
    return out


PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(ok), FAIL + (not ok)
    print(("[PASS] " if ok else "[FAIL] ") + label + ("" if ok else f"  → {detail}"))


if sys.version_info < (3, 12):
    # Python cũ tự từ chối cú pháp ấy khi nạp — bộ dò token chỉ cần trên 3.12+.
    import py_compile
    bad = []
    for p in (ROOT / "tubecli").rglob("*.py"):
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            bad.append(str(e)[:200])
    check(f"mọi file tubecli/ biên dịch được trên Python {sys.version_info[0]}.{sys.version_info[1]}", not bad, bad[:5])
else:
    check("A1 bắt đúng ca muse.py (nháy kép lồng nháy kép)",
          problems('m = 2\nx = f"about {m} minute{"s" if m != 1 else ""}."\n') != [])
    check("A2 bắt nháy đơn lồng nháy đơn", problems("x = f'{'a'}'\n") != [])
    check("A3 bắt dấu \\ trong biểu thức", problems('x = f"{chr(10).join([\'\\n\'])}"\n') != [])
    check("A4 cách viết hợp lệ cho 3.10 không bị báo",
          problems('m = 2\nx = f"minute{\'s\' if m != 1 else \'\'}"\ny = f"{x!r:>10} {{literal}}"\n') == [])
    check("A5 f-string lồng KHÁC nháy không bị báo", problems("x = f\"{f'{1}'}\"\n") == [])
    found = []
    for p in sorted((ROOT / "tubecli").rglob("*.py")):
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "f\"" not in src and "f'" not in src and "F\"" not in src and "F'" not in src:
            continue
        for line, why in problems(src):
            found.append(f"{p.relative_to(ROOT)}:{line}: {why}")
    check("B mọi file trong tubecli/ chạy được trên Python 3.10 / 3.11 (không f-string kiểu 3.12)", not found,
          "\n    " + "\n    ".join(found[:30]))

print(f"\n{PASS}/{PASS + FAIL} PASS")
sys.exit(1 if FAIL else 0)
