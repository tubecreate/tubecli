# Máy Windows/macOS cũng phải đo được CPU/RAM/đĩa, và cũng phải cập nhật được.
#
# Chạy:  python tests/system_stats_supervisor_test.py      (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   1) Cloud vẽ thanh CPU/RAM/đĩa bằng cách SSH vào máy rồi đọc /proc — chỉ dùng
#      được với VPS thuê. Máy nối bằng tunnel không có IP, không có SSH, nên route
#      trả 409 và thanh đứng ở "—" vĩnh viễn (người dùng chụp ảnh 9/9/2026).
#   2) Nút Cập nhật kéo code mới rồi cần khởi động lại, nhưng _schedule_restart()
#      chỉ biết systemd. Trên Windows nó bỏ cuộc và bảo người dùng chạy
#      `systemctl restart tubecli` — một câu vô nghĩa ở đó. Code mới về đĩa mà máy
#      chủ vẫn chạy bản cũ trong RAM.
#
#   Cả hai đều được giải bằng thứ ĐÃ CÓ SẴN: hỏi thẳng node qua tunnel, và để
#   TubeCLI Connect (vòng canh 20 giây của nó) đóng vai systemd trên Windows.
import io
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT.parent / "tubecli-cloud"
sys.path.insert(0, str(ROOT))

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} -> {detail}")


SRC = io.open(ROOT / "tubecli/api/server.py", encoding="utf-8").read()

# ── 1. Node có route đo máy, và nó dùng được trên MỌI hệ ────────────────────
check("có /api/v1/system/stats", '@app.get("/api/v1/system/stats")' in SRC)
check("đo bằng psutil (chạy trên cả ba hệ), không đọc /proc",
      "psutil.virtual_memory()" in SRC and "/proc/meminfo" not in SRC)
check("không CHẶN 1 giây để đo CPU (cloud poll 7 giây, không cần)",
      "psutil.cpu_percent(interval=None)" in SRC)
check("đo ổ chứa TubeCLI chứ không phải ổ hệ thống",
      "shutil.disk_usage(str(BASE_DIR))" in SRC)
check("trả đúng các khoá mà cloud đang vẽ",
      all(k in SRC for k in ('"mem_pct"', '"cores"', '"disk_used_gb"', '"disk_total_gb"', '"cpu"')))

# Gọi thật hàm ấy — số phải có nghĩa, không phải hình dạng suông.
import asyncio  # noqa: E402

from tubecli.api.server import system_stats  # noqa: E402

d = asyncio.get_event_loop().run_until_complete(system_stats()) if False else asyncio.run(system_stats())
check("RAM tổng > 0 và phần trăm nằm trong 0–100",
      d["mem_total_mb"] > 0 and 0 <= d["mem_pct"] <= 100, d)
check("số nhân ≥ 1", d["cores"] >= 1, d["cores"])
check("đĩa: đã dùng không vượt tổng",
      0 <= d["disk_used_gb"] <= d["disk_total_gb"] and d["disk_total_gb"] > 0, d)
check("có nói rõ nền tảng", isinstance(d.get("platform"), str) and d["platform"])

# ── 2. Bộ giám sát ngoài systemd ────────────────────────────────────────────
import tubecli.api.server as srv  # noqa: E402

srv._SUPERVISOR["at"] = 0
check("chưa ai báo → coi như KHÔNG có ai giám sát", not srv._supervised_externally())
srv._SUPERVISOR["at"] = time.time()
srv._SUPERVISOR["by"] = "TubeCLI Connect"
check("vừa báo → có giám sát", srv._supervised_externally())
check("và nói được tên của nó", srv._supervisor_name() == "TubeCLI Connect")
srv._SUPERVISOR["at"] = time.time() - (srv.SUPERVISOR_TTL + 5)
check("nhịp tim cũ quá thì HẾT hiệu lực (không dám tự thoát nữa)",
      not srv._supervised_externally())
check("hạn rộng hơn chu kỳ canh 20 giây của client", srv.SUPERVISOR_TTL >= 60)

check("tự thoát khi có bộ giám sát ngoài", "if _supervised_externally():" in SRC)
check("vẫn giữ nhánh systemd cho Linux", "if _under_systemd():" in SRC)
check("nhịp tim CHỈ nhận từ loopback (đây là giấy phép cho máy tự thoát)",
      'host not in ("127.0.0.1", "::1", "localhost")' in SRC)
check("route nhịp tim được miễn đăng nhập (client báo trước khi có phiên)",
      '"/api/v1/system/supervisor",' in SRC)
check("không đọc lệnh systemd cho người dùng Windows/macOS",
      "Open TubeCLI Connect and leave it running" in SRC)

# ── 3. Client thật sự báo nhịp, và chỉ hứa điều nó làm được ─────────────────
CL = io.open(ROOT / "client/tubecli_connect.pyw", encoding="utf-8").read()
check("client có hàm báo nhịp tim", "def supervisor_beat()" in CL)
check("gọi trong vòng canh — chính vòng dựng lại máy chủ", "supervisor_beat()" in CL)
check("chỉ báo khi máy chủ đang sống (nhịp tim là lời hứa, không phải tiếng ồn)",
      "else:\n                    # Chỉ báo khi máy chủ ĐANG SỐNG" in CL)
check("bản TubeCLI cũ chưa có route thì bỏ qua êm", "return False" in CL.split("def supervisor_beat")[1][:1200])

# ── 4. Cloud hỏi qua tunnel trước khi nghĩ tới SSH ──────────────────────────
route = CLOUD / "app/api/servers/[id]/stats/route.js"
if route.exists():
    js = io.open(route, encoding="utf-8").read()
    check("cloud hỏi node qua tunnel", "tubecliFetch(row, '/api/v1/system/stats'" in js)
    check("hỏi tunnel TRƯỚC khi kiểm tra IP/SSH",
          js.index("tubecliFetch(row, '/api/v1/system/stats'") < js.index("Server chưa có IP"))
    check("tunnel hỏng thì vẫn rơi xuống đường SSH cũ", "if (!row.ip) return" in js)
else:
    print("  (bỏ qua phần cloud: không thấy repo tubecli-cloud cạnh đây)")

print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{FAIL} FAIL / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
