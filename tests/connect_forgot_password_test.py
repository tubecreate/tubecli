"""TubeCLI Connect: «Quên mật khẩu? Đặt mật khẩu mới» trong cửa sổ ghép nối (user 29/10/2026).

Chạy:  python tests/connect_forgot_password_test.py      (mã thoát 0 = đạt)

Máy chưa nối cloud mà quên mật khẩu dashboard thì kẹt ở cửa sổ ghép nối (bắt nhập mật khẩu, cloud chưa có
bản nào để xem lại). Khoá: liên kết dưới ô mật khẩu, hộp đặt mật khẩu mới gọi change_node_password(new)
KHÔNG kèm mật khẩu cũ (đường `tubecli password --new`), đặt xong điền sẵn vào ô; sai luật thì không gọi;
câu báo sai mật khẩu chỉ tới liên kết; chế độ dòng lệnh cũng hỏi. Hộp thoại chạy THẬT bằng Tk (ẩn), hàm
đặt mật khẩu là bản giả — không đụng mật khẩu thật của máy. APPDATA trỏ thư mục tạm.
"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = ROOT / "client" / "tubecli_connect.pyw"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="tc_forgot_pw_")

mod = types.ModuleType("tubecli_connect")
mod.__file__ = str(SRC)
exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), mod.__dict__)
TXT = SRC.read_text(encoding="utf-8").replace("\r\n", "\n")

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failures += 1


LOGS = []
mod.log = lambda m: LOGS.append(str(m))

# ── 1. tĩnh: móc vào cửa sổ ghép nối + dòng lệnh ─────────────────────────────
pair = TXT[TXT.index("def ask_pairing(default_code"):TXT.index("def ask_pairing(default_code") + 12000]
check("liên kết «Quên mật khẩu?» nằm NGAY dưới gợi ý 123456 trong cửa sổ ghép nối",
      'forgot = tk.Label(body, text=FORGOT_LINK' in pair
      and pair.index("Máy vừa cài xong thì để 123456.") < pair.index("forgot = tk.Label(body, text=FORGOT_LINK"))
check("bấm liên kết → open_forgot_password(root, on_new_password)",
      'forgot.bind("<Button-1>", lambda _e: open_forgot_password(root, on_new_password))' in pair)
check("đặt xong: điền mật khẩu mới vào ô + mở nút Kết nối",
      'e_pw.delete(0, "end")' in pair and "e_pw.insert(0, new_pw)" in pair and 'btn.state(["!disabled"])' in pair)
check("sai mật khẩu → câu lỗi chỉ tới liên kết", 'f"Quên mật khẩu? Bấm «{FORGOT_LINK}» dưới ô mật khẩu."' in pair)
check("fail() tô lại màu đỏ (on_new_password tô xanh)", 'msg.config(text=text, fg=UI["red"])' in pair)
con = TXT[TXT.index("def ask_pairing_console("):][:3000]
check("dòng lệnh: sai mật khẩu → hỏi đặt mật khẩu mới, gọi change_node_password(a) KHÔNG kèm mật khẩu cũ",
      "Quên mật khẩu? Đặt mật khẩu mới cho máy này [c/K]" in con and "change_node_password(a)" in con
      and "password_problem(a, b)" in con and "suggest = a" in con)

# ── 2. hộp thoại thật (Tk ẩn) với change_node_password giả ──────────────────
CALLS = []


def fake_change(new_pw, current=""):
    CALLS.append((new_pw, current))
    return True, "Đã đặt mật khẩu mới.", "cli"


mod.change_node_password = fake_change
try:
    import tkinter as tk
    from tkinter import ttk  # noqa: F401
    root = tk.Tk()
    root.withdraw()
except Exception as e:  # noqa: BLE001
    root = None
    print(f"SKIP phần Tk: {e}")

if root is not None:
    got = []

    def pump(cond, secs=5.0):
        end = time.time() + secs
        while time.time() < end and not cond():
            root.update()
            time.sleep(0.02)

    def dialog_parts():
        dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        box = dlg.winfo_children()[0]
        entries = [w for w in box.winfo_children() if w.winfo_class() == "TEntry"]
        labels = [w for w in box.winfo_children() if w.winfo_class() == "TLabel"]
        row = [w for w in box.winfo_children() if w.winfo_class() == "TFrame"][0]
        btns = [w for w in row.winfo_children() if w.winfo_class() == "TButton"]
        return dlg, entries, labels[-1], btns[0]

    mod.open_forgot_password(root, got.append)
    root.update()
    dlg, (e1, e2), note, b_ok = dialog_parts()
    check("hộp có 2 ô mật khẩu che (•) + nút «Đặt mật khẩu»",
          e1.cget("show") == "•" and e2.cget("show") == "•" and b_ok.cget("text") == "Đặt mật khẩu")
    check("hộp nói rõ không cần mật khẩu cũ", "Không cần mật khẩu cũ" in str(note.cget("text")))

    e1.insert(0, "abc"); e2.insert(0, "abc")
    b_ok.invoke(); root.update()
    check("quá ngắn → báo lỗi, KHÔNG gọi đặt mật khẩu", not CALLS and "ít nhất 6" in str(note.cget("text")), note.cget("text"))
    e1.delete(0, "end"); e2.delete(0, "end")
    e1.insert(0, "mat-khau-moi-1"); e2.insert(0, "mat-khau-moi-2")
    b_ok.invoke(); root.update()
    check("hai lần không khớp → báo lỗi, KHÔNG gọi", not CALLS and "không khớp" in str(note.cget("text")), note.cget("text"))
    e1.delete(0, "end"); e2.delete(0, "end")
    e1.insert(0, "123456"); e2.insert(0, "123456")
    b_ok.invoke(); root.update()
    check("đặt lại 123456 → từ chối", not CALLS and "123456" in str(note.cget("text")))
    e1.delete(0, "end"); e2.delete(0, "end")
    e1.insert(0, "mat-khau-moi-9x"); e2.insert(0, "mat-khau-moi-9x")
    b_ok.invoke()
    pump(lambda: got)
    check("hợp lệ → change_node_password(mới) KHÔNG kèm mật khẩu cũ (đường tubecli password --new)",
          CALLS == [("mat-khau-moi-9x", "")], CALLS)
    check("đặt xong → gọi on_set(mật khẩu mới) để điền sẵn vào ô", got == ["mat-khau-moi-9x"], got)
    check("đặt xong → hộp tự đóng", not dlg.winfo_exists())
    check("log không chứa mật khẩu", not any("mat-khau-moi-9x" in m for m in LOGS), LOGS)

    # lỗi từ máy chủ → giữ hộp mở, hiện lý do
    mod.change_node_password = lambda new_pw, current="": (False, "lệnh đổi mật khẩu trả mã 1", "cli")
    got.clear()
    mod.open_forgot_password(root, got.append)
    root.update()
    dlg, (e1, e2), note, b_ok = dialog_parts()
    e1.insert(0, "mat-khau-moi-7y"); e2.insert(0, "mat-khau-moi-7y")
    b_ok.invoke()
    pump(lambda: "trả mã 1" in str(note.cget("text")))
    check("đặt hỏng → hộp vẫn mở, hiện lý do, nút bấm lại được",
          dlg.winfo_exists() and "trả mã 1" in str(note.cget("text")) and not got and str(b_ok.cget("state")) == "normal")
    root.destroy()

print(f"\n{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
