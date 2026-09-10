# Phát hành lõi: __version__ và MIN_SERVER_VERSION phải đi cùng nhau, và mức độ phải đúng.
#
# Chạy:  python tests/release_version_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Ngày 10/9/2026 tôi đẩy ba commit sửa lỗi lên origin/main rồi bảo người dùng
#   cập nhật — nhưng KHÔNG bump `__version__`. TubeCLI có hai đường báo bản mới:
#
#     1. đếm commit (`git rev-list HEAD..origin/main`) — chết ngay khi `git fetch`
#        trên máy khách hỏng, và cái hỏng đó không ai xem returncode;
#     2. so phiên bản (`isOutdated(version)` với MIN_SERVER_VERSION) — đường này
#        KHÔNG cần git trên máy khách chạy được.
#
#   Không bump thì chỉ còn đường 1, nên máy nào fetch hỏng là không bao giờ thấy
#   bản mới. Đường 2 mới là cơ chế phát hành thật.
#
#   Kèm một bẫy nữa: hai route ghi cứng kind/severity = 'security' cho MỌI máy dưới
#   mức tối thiểu, bỏ qua hằng SEVERITY. Một bản sửa lỗi cũng ra banner đỏ không
#   tắt được — dùng sai màu đỏ một lần thì lần sau không ai đọc banner đỏ nữa.
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


def ver_tuple(v):
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))


from tubecli import __version__ as core_version  # noqa: E402

check("A __version__ đúng dạng 4 số", re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d+", core_version) is not None, core_version)

CLOUD = ROOT.parent / "tubecli-cloud"
if not CLOUD.is_dir():
    print(f"SKIP: không thấy repo cloud ở {CLOUD}")
    print(f"{checks}/{checks} PASS" if not failures else failures)
    sys.exit(1 if failures else 0)

sv = io.open(CLOUD / "lib" / "serverVersion.js", encoding="utf-8").read()
m = re.search(r"MIN_SERVER_VERSION = '([\d.]+)'", sv)
check("B đọc được MIN_SERVER_VERSION", m is not None)
min_version = m.group(1) if m else "0"

# Lõi KHÔNG được thấp hơn mức cloud coi là an toàn: khi đó chính máy dev cũng bị
# báo "cũ", và không có bản nào để cập nhật lên.
check("B lõi >= mức tối thiểu", ver_tuple(core_version) >= ver_tuple(min_version),
      (core_version, min_version))
# Và mức tối thiểu phải ĐUỔI THEO lõi, không được tụt lại: tụt là mọi máy cũ đều
# im lặng, đúng chuyện đã xảy ra hôm nay.
check("B mức tối thiểu = phiên bản lõi hiện tại", min_version == core_version, (min_version, core_version))

sev = re.search(r"SEVERITY = '(\w+)'", sv)
check("C đọc được SEVERITY", sev is not None)
check("C SEVERITY chỉ nhận hai giá trị", sev and sev.group(1) in ("security", "recommended"), sev and sev.group(1))
check("C có severityKind()", "export function severityKind()" in sv)

# Hai route PHẢI đi qua severityKind, không ghi cứng 'security'.
for rel in (Path("app/api/servers/[id]/update-check/route.js"), Path("app/api/servers/updates/route.js")):
    src = io.open(CLOUD / rel, encoding="utf-8").read()
    check(f"C {rel.parent.name} dùng severityKind", "severityKind()" in src)
    check(f"C {rel.parent.name} không ghi cứng 'security'",
          "? 'security' :" not in src, [l.strip() for l in src.split("\n") if "? 'security' :" in l])

# Câu lý do mà cloud trỏ tới phải TỒN TẠI ở cả 9 ngôn ngữ, nếu không khách đọc
# thấy nguyên cái khoá.
rk = re.search(r"REASON_KEY = '([\w.]+)'", sv)
check("D đọc được REASON_KEY", rk is not None)
if rk:
    for lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
        loc = io.open(CLOUD / "lib" / "locales" / f"{lang}.js", encoding="utf-8").read()
        check(f"D {lang} có {rk.group(1)}", f"'{rk.group(1)}':" in loc)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
