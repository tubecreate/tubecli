# -*- coding: utf-8 -*-
"""Việc một lượt chạy làm được, rút từ log của chính nó.

Vì sao đáng một test riêng: bảng Hoạt động trước đây chỉ có outcome, nên một lượt
gõ + tìm + bấm + đọc 39 lần rồi hỏng ở bước cuối trông y hệt một lượt chết ngay
giây đầu. Người dùng nhìn cột toàn "Lỗi" rồi kết luận sai rằng nó chưa từng chạy.

Định dạng dưới đây KHÔNG phải bịa: đã đối chiếu với log thật trong
tubecli/extensions/logs/browser/ (browser-e1e51887.log → 39 hành động, 100%).

    python tests/run_work_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tubecli.extensions.browser.process_manager import BrowserProcessManager  # noqa: E402

MGR = BrowserProcessManager.__new__(BrowserProcessManager)
PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   " + label)
    else:
        FAIL += 1
        print("  FAIL " + label + ("  -> " + str(extra) if extra else ""))


def work_of(text):
    fd, path = tempfile.mkstemp(suffix=".log")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        return MGR._read_run_work(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


REAL = """Launching browser [Profile: tuan5]...
[Session] 0/10 min | Step: type (1) | Page: general_website
[Session] 0/10 min | Step: search (2) | Page: general_website
[Session] 2/10 min | Step: browse (3) | Page: general_website
[Session] 6/10 min | Step: click (4) | Page: article
[Session] 9/10 min | Step: browse (5) | Page: article

=== SESSION COMPLETED ===
Duration: 10 minutes
Actions: 39
Final URL: https://example.com
"""

print("=== việc đã làm trong một lượt chạy ===")

w = work_of(REAL)
check("đọc được log kiểu thật", w is not None)
check("'Actions:' thắng số suy từ dòng Step", w and w["actions"] == 39, w and w["actions"])
check("giữ THỨ TỰ xuất hiện của hành động",
      w and [k["name"] for k in w["kinds"]] == ["type", "search", "browse", "click"],
      w and [k["name"] for k in w["kinds"]])
check("đếm đúng số lần mỗi loại",
      w and dict((k["name"], k["n"]) for k in w["kinds"])["browse"] == 2, w and w["kinds"])
check("tiến độ lấy từ dòng Step CUỐI", w and w["progress_pct"] == 90, w and w.get("progress_pct"))

# Lượt hỏng giữa chừng: không có "=== SESSION COMPLETED ===", không có "Actions:".
BROKEN = """[Session] 0/8 min | Step: search (1) | Page: general_website
[Session] 1/8 min | Step: click (2) | Page: article
[Session] 3/8 min | Step: extract_content (3) | Page: article
!!! Execution failed: Profile is already open in another process
"""
w2 = work_of(BROKEN)
check("lượt hỏng vẫn kể được việc đã làm", w2 is not None)
check("thiếu 'Actions:' thì lấy số thứ tự cao nhất", w2 and w2["actions"] == 3, w2 and w2["actions"])
check("hỏng giữa chừng -> tiến độ dưới 100%", w2 and w2["progress_pct"] == 38, w2 and w2.get("progress_pct"))

# Chạy quá giờ: 15/10 phút. "Đi hết phiên" là 100%, không phải 150%.
OVER = "[Session] 15/10 min | Step: browse (7) | Page: article\nActions: 35\n"
w3 = work_of(OVER)
check("quá giờ bị chặn ở 100%", w3 and w3["progress_pct"] == 100, w3 and w3.get("progress_pct"))

# KHÔNG BIẾT khác KHÔNG LÀM ĐƯỢC GÌ. Log câm phải trả None để giao diện nói
# "không rõ" thay vì vẽ 0% — một con số bịa trông y như sự thật.
check("log câm -> None, không phải 0%", work_of("Launching browser...\nboom\n") is None)
check("log rỗng -> None", work_of("") is None)
check("không có file -> None, không ném", MGR._read_run_work("/khong/co/that.log") is None)
check("log_path rỗng -> None", MGR._read_run_work("") is None)

# Dòng Step không có số thứ tự (bản open.js cũ hơn) vẫn phải đếm được.
NOIDX = "[Session] 2/4 min | Step: search | Page: x\n[Session] 3/4 min | Step: click | Page: y\n"
w4 = work_of(NOIDX)
check("không có (n) thì đếm số dòng Step", w4 and w4["actions"] == 2, w4 and w4.get("actions"))

print("\n%d pass, %d fail" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
