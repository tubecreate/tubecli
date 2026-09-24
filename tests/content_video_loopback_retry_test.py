# -*- coding: utf-8 -*-
"""Dựng lại sự cố 23/9/2026: máy chủ ngừng nhận kết nối rồi quay lại — job có sống không?

Hôm nay một lệnh `_get` đọc lại storyboard bị từ chối đã giết trọn job 30 phút ĐÃ ghi xong 320 nhịp.
Test này KHÔNG giả lập bằng mock: nó dựng một máy chủ thật, tắt hẳn cổng, rồi mở lại.

Kiểm cả hai chiều:
  A. kết nối bị từ chối rồi máy chủ quay lại  ⇒ PHẢI sống (thử lại ở tầng connect)
  B. lỗi xảy ra SAU khi đã gửi yêu cầu        ⇒ PHẢI hỏng ngay, KHÔNG gửi lại
     (đây mới là chỗ an toàn: gửi lại một POST đã tới nơi là tạo trùng tập / gọi CapCut hai lần)

Run:  python test_loopback_retry.py     (exit 0 = pass)
"""
import http.server
import socket
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\tubecreate-vue\tubecli")

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
HITS = {"n": 0, "half": 0}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS["n"] += 1
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Nhận HẾT yêu cầu rồi CẮT ngang: mô phỏng lỗi xảy ra SAU khi dữ liệu đã tới máy chủ.
        HITS["half"] += 1
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.close_connection = True
        self.wfile.close()

    def log_message(self, *a):
        pass


def serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


import tubecli.extensions.content_video.pipeline as P     # noqa: E402
P._base_url = lambda: "http://127.0.0.1:%d" % PORT

print("\nA. kết nối bị TỪ CHỐI rồi máy chủ quay lại")
srv = serve()
time.sleep(0.2)
srv.shutdown()
srv.server_close()                                        # cổng đóng hẳn: mọi kết nối bị từ chối
print("   máy chủ tắt, sẽ bật lại sau 6 giây (lần thử lại thứ 2 rơi vào ~4s, thứ 3 ~12s)")


def relight():
    time.sleep(6)
    serve()


threading.Thread(target=relight, daemon=True).start()
t0 = time.time()
try:
    got = P._get("/api/v1/studio/episodes/533/storyboards", timeout=10)
    took = time.time() - t0
    ok(got == {"ok": True}, "job SỐNG qua cửa sổ máy chủ từ chối kết nối", got)
    ok(took >= 3, "có chờ thật rồi thử lại (%.1f giây), không phải may mà trúng" % took, took)
except Exception as e:      # noqa: BLE001
    ok(False, "job sống qua cửa sổ từ chối", "%s: %s" % (type(e).__name__, str(e)[:200]))

print("\nB. lỗi SAU khi đã gửi ⇒ KHÔNG được gửi lại")
HITS["half"] = 0
try:
    P._post("/api/v1/studio/episodes", {"title": "x"}, timeout=6)
    ok(False, "POST bị cắt ngang phải NÉM lỗi", "không ném")
except Exception as e:      # noqa: BLE001
    ok(True, "POST bị cắt ngang thì hỏng ngay (%s)" % type(e).__name__)
ok(HITS["half"] == 1,
   "máy chủ chỉ nhận ĐÚNG MỘT lần — gửi lại là tạo trùng tập / gọi CapCut hai lần / tính tiền vẽ hai lần",
   "nhận %d lần" % HITS["half"])

print("\n%d/%d PASS" % (PASS, PASS + FAIL) if not FAIL else "\n%d/%d PASS — %d HỎNG" % (PASS, PASS + FAIL, FAIL))
sys.exit(1 if FAIL else 0)
