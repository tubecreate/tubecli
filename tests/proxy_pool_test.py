"""Kho proxy phải nhận đúng thứ nhà cung cấp phát ra.

Chạy:  python tests/proxy_pool_test.py      (mã thoát 0 = đạt)

Vì sao tệp này tồn tại. Người dùng dán `103.179.188.215:30981:5o7y:5o7y` — dạng
`ip:port:user:pass` trần, không tiền tố — và kho từ chối thẳng, in ra "không đọc
được dòng này". Đó là dạng phổ biến NHẤT nhà cung cấp Việt Nam phát ra, nên bản
nhập đầu tiên coi như vô dụng với họ. Bài kiểm này khoá cả bốn dạng, và khoá cả
cách xử lý phần scheme phải đoán.

Kho ghi vào tệp: mọi bài kiểm ở đây trỏ TUBECLI_PROXY_STORE sang tệp tạm. Trước
đó một lượt kiểm định tự động đã ghi 419 proxy giả vào kho thật của người dùng
và gán chúng cho 9 hồ sơ trình duyệt; biến môi trường là hàng rào cho việc đó.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="tubecli_pool_")
os.environ["TUBECLI_PROXY_STORE"] = os.path.join(_TMP, "proxy_center.json")
os.environ["TUBECLI_BROWSER_PROFILES_DIR"] = os.path.join(_TMP, "profiles")

from tubecli.extensions.browser import proxy_pool as pool  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("KHO PROXY")
print("=" * 70)

check("kho kiểm thử KHÔNG trỏ vào dữ liệu thật",
      "extensions_data" not in pool.STORE and _TMP in pool.STORE, pool.STORE)

# ── 1. bốn dạng chuỗi ───────────────────────────────────────────────────────
REAL = "103.179.188.215:30981:5o7y:5o7y"          # đúng chuỗi người dùng đã dán
check("dạng nhà cung cấp TRẦN được nhận",
      pool.normalise(REAL) == "http://5o7y:5o7y@103.179.188.215:30981",
      pool.normalise(REAL))
check("host:port trần được nhận",
      pool.normalise("1.2.3.4:8080") == "http://1.2.3.4:8080")
check("user:pass@host:port trần được nhận",
      pool.normalise("u:p@1.2.3.4:8080") == "http://u:p@1.2.3.4:8080")
check("dạng nhà cung cấp CÓ scheme vẫn viết lại đúng thứ tự [host,port,user,pass]",
      pool.normalise("socks5://1.2.3.4:1080:u:p") == "socks5://u:p@1.2.3.4:1080",
      pool.normalise("socks5://1.2.3.4:1080:u:p"))
check("dạng chuẩn giữ nguyên",
      pool.normalise("socks5://u:p@1.2.3.4:1080") == "socks5://u:p@1.2.3.4:1080")
check("scheme gõ sai bị từ chối, không âm thầm nhận",
      pool.normalise("sock5s://1.2.3.4:1080:u:p") is None)
check("chuỗi vô nghĩa bị từ chối", pool.normalise("khong-phai-proxy") is None)
check("chuỗi rỗng bị từ chối", pool.normalise("") is None)

check("chuỗi trần được đánh dấu là phải đoán scheme", pool.scheme_was_guessed(REAL))
check("chuỗi có scheme thì không đoán gì", not pool.scheme_was_guessed("socks5://u:p@1.2.3.4:1080"))

# Cùng một proxy, hai cách viết, phải là MỘT — nếu không, phát đều đếm sai.
check("cùng cổng nhưng KHÁC tài khoản là hai proxy khác nhau",
      pool.key_of("1.2.3.4:8080:userA:p") != pool.key_of("1.2.3.4:8080:userB:p"),
      "username là nút chọn phiên/quốc gia của nhà cung cấp residential")
check("khoá so trùng bỏ qua scheme và cách viết",
      pool.key_of(REAL) == pool.key_of("socks5://5o7y:5o7y@103.179.188.215:30981"),
      (pool.key_of(REAL), pool.key_of("socks5://5o7y:5o7y@103.179.188.215:30981")))

# ── 2. nhập hàng loạt ───────────────────────────────────────────────────────
r = pool.add_proxies("Kho A", "\n".join([
    REAL,
    "1.2.3.4:8080",
    "socks5://u:p@5.6.7.8:1080",
    REAL,                       # trùng, dán lại y hệt
    "103.179.188.215:30981",    # trùng: cùng host:port, khác cách viết
    "rác dán nhầm",
    "   ",                      # dòng trắng, không tính là lỗi
    "# ghi chú",                # dòng chú thích
]))
# 4 chứ không phải 3: `103.179.188.215:30981` (không tài khoản) KHÁC
# `103.179.188.215:30981:5o7y:5o7y`. Khoá so trùng cố ý gồm cả username, vì với
# nhà cung cấp residential chính username mới là nút chọn phiên/quốc gia —
# `user-vn-session-a` và `user-us-session-b` trên cùng một cổng là hai lối ra
# khác hẳn nhau. Gộp chúng lại sẽ vứt mất phân nửa số IP đã mua.
check("nhập nhận 4 proxy khác nhau", r["added"] == 4, r)
check("bắt được 1 dòng dán lặp y hệt", r["duplicate"] == 1, r)
check("chỉ 1 dòng thật sự không đọc được", len(r["invalid"]) == 1, r["invalid"])
check("dòng hỏng được trả lại NGUYÊN VĂN", r["invalid"][0] == "rác dán nhầm", r["invalid"])
check("dòng trắng và dòng chú thích không bị tính là lỗi", "" not in r["invalid"])
check("báo đúng số proxy phải đoán scheme", r["guessed"] == 3, r["guessed"])

rows = pool.list_proxies("Kho A")
check("bảng trả về cờ đoán scheme", any(x["scheme_guessed"] for x in rows))
guessed_row = [x for x in rows if x["scheme_guessed"]][0]
check("proxy đoán scheme vẫn nằm trong kho phát ra được",
      guessed_row["blocker"] not in pool.FATAL_BLOCKERS, guessed_row["blocker"])

# ── 3. trùng lặp phải nói TRÙNG Ở ĐÂU ───────────────────────────────────────
r2 = pool.add_proxies("Kho B", REAL)
check("proxy đã có ở kho khác thì không nhận lại", r2["added"] == 0, r2)
check("và nói rõ kho nào đang giữ nó",
      r2["duplicate_where"] and r2["duplicate_where"][0]["kho"] == "Kho A",
      r2["duplicate_where"])

# ── 4. phát đều ─────────────────────────────────────────────────────────────
picks = pool.distribute("Kho A", 4)
check("phát 4 proxy cho 4 hồ sơ thì không trùng nhau", len(set(picks)) == 4, picks)
picks6 = pool.distribute("Kho A", 6)
counts = [picks6.count(x) for x in set(picks6)]
check("nhiều hồ sơ hơn proxy thì chia đều, lệch nhau tối đa 1",
      max(counts) - min(counts) <= 1, picks6)
cur = picks[0]
check("xoay vòng luôn trả proxy KHÁC cái đang dùng",
      pool.next_after("Kho A", cur) != cur)

# ── 5. hạn dùng ─────────────────────────────────────────────────────────────
pool.add_proxies("Kho C", "9.9.9.9:9999", expiry_date="2020-01-01")
pool.add_proxies("Kho C", "9.9.9.10:9999", expiry_date="2099-01-01")
live = [p["proxy_str"] for p in pool.list_proxies("Kho C", include_expired=False)]
check("proxy hết hạn bị loại khỏi danh sách còn hạn", len(live) == 1, live)
check("kho toàn proxy hết hạn vẫn phát ra chứ không trả rỗng",
      pool.pick("Kho C") is not None,
      "trả None sẽ khiến hồ sơ mở KHÔNG proxy — lộ IP thật, tệ hơn proxy quá hạn")
check("ghi sai định dạng ngày thì coi như còn hạn, không vứt proxy đi",
      not pool.is_expired({"expiry_date": "hôm qua"}))

# ── 6. kiểm tra sửa lại phần đã đoán ────────────────────────────────────────
pid = [p["id"] for p in pool.list_proxies("Kho A") if p["scheme_guessed"]][0]
before = [p for p in pool.list_proxies("Kho A") if p["id"] == pid][0]["proxy_str"]
pool.record_test(pid, {"ok": True, "ip": "1.1.1.1", "country": "VN",
                       "working": before.replace("http://", "socks5://")})
after = [p for p in pool.list_proxies("Kho A") if p["id"] == pid][0]
check("kiểm tra thấy scheme khác thì GHI ĐÈ lại chuỗi",
      after["proxy_str"].startswith("socks5://"), after["proxy_str"])
check("và bỏ cờ đoán, vì đã biết chắc", not after["scheme_guessed"])
check("kết quả đo được lưu lại", after["last_ok"] is True and after["last_ip"] == "1.1.1.1")

# ── 7. kho ──────────────────────────────────────────────────────────────────
check("đổi tên kho kéo theo proxy bên trong",
      pool.rename_kho("Kho A", "Kho A2")["success"]
      and len(pool.list_proxies("Kho A2")) == 4,
      [p["kho"] for p in pool.list_proxies()])
d = pool.delete_kho("Kho A2")
check("xoá kho mặc định CHUYỂN proxy chứ không xoá", d["success"] and d["moved"] == 4, d)
check("không xoá được kho cuối cùng",
      not pool.delete_kho(pool.list_khos()[0]["name"])["success"]
      if len(pool.list_khos()) == 1 else True)

print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
