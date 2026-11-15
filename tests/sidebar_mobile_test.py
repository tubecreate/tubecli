"""Dashboard: menu bên thu nhỏ — ba gạch thẳng hàng, menu nhiều cấp gọn, điện thoại mở được menu đầy đủ.

Chạy:  python tests/sidebar_mobile_test.py      (mã thoát 0 = đạt)

Vì sao (user 15/11/2026): «phần cuộn thu nhỏ menu trên di động bấm không được và dấu ba gạch bị lệch», «menu nhiều cấp
nó lỗi», hộp «Update now» tràn ra ngoài dải. Nguyên nhân chung: phần tử có display viết thẳng trong thẻ nên luật ẩn của
CSS không ăn; ở màn ≤ 720px ba gạch chỉ bật/tắt lớp «collapsed» mà CSS ở đó ép thu nhỏ bất kể lớp này.

Kiểm tĩnh trên mã nguồn (không trình duyệt, không mạng). Ảnh chụp kiểm tay: scratchpad/sb_shot*.js.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
S = ROOT / "tubecli" / "extensions" / "webui" / "static"
css = (S / "style.css").read_text(encoding="utf-8")
js = (S / "app.js").read_text(encoding="utf-8")
html = (S / "index.html").read_text(encoding="utf-8")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


media = css[css.index("@media (max-width: 720px) {"):]
media = media[:media.index("/* ─── Content ─── */")]

check("1 ô logo bị ẩn bằng !important ở cả hai chế độ dải (display viết thẳng trong thẻ từng thắng luật cũ)",
      ".sidebar.collapsed .sidebar-logo-container { display: none !important; }" in css
      and ".sidebar:not(.mobile-open) .sidebar-logo-container { display: none !important; }" in media)
check("2 nút ba gạch: ô bấm 44px, canh giữa dải", "sidebar-head-row { justify-content: center !important; }" in css
      and re.search(r"\.sidebar\.collapsed \.sidebar-menu-btn \{ width: 44px !important; height: 44px;", css)
      and 'class="sidebar-head"' in html and 'class="sidebar-head-row"' in html)
check("3 menu nhiều cấp trong dải: bỏ thụt lề + viền trái, nhóm là một khối, ẩn mũi tên, tên nhóm ẩn theo .nav-text",
      ".sidebar.collapsed .sidebar-group-items { padding-left: 0; margin-left: 0; border-left: none; }" in css
      and ".sidebar.collapsed .sidebar-group { margin: 4px 0;" in css
      and ".sidebar.collapsed .sidebar-group-chevron { display: none; }" in css
      and '<span class="nav-text">${esc(g.name)}</span>' in js)
check("4 dải không cuộn ngang", ".sidebar.collapsed .sidebar-nav { overflow-x: hidden; }" in css
      and ".sidebar:not(.mobile-open) .sidebar-nav { overflow-x: hidden; }" in media)
check("5 điện thoại: luật thu nhỏ chỉ áp khi menu KHÔNG mở", "  .sidebar {" not in media and "  .sidebar ." not in media
      and media.count(".sidebar:not(.mobile-open)") >= 15)
check("6 điện thoại: menu đầy đủ đè lên trang + nền mờ, dải 68px vẫn giữ chỗ",
      ".sidebar.mobile-open {" in media and "position: fixed" in media and "#app.sidebar-mobile-open { padding-left: 68px; }" in media
      and ".sidebar-shade { display: block; position: fixed; inset: 0;" in media)
fn = js[js.index("function toggleSidebar()"):js.index("window.addEventListener('resize'")]
check("7 ba gạch: màn hẹp mở/đóng menu đè, màn rộng thu/mở như cũ", "if (!sidebarIsMobile()) { closeMobileSidebar(); sb.classList.toggle('collapsed'); return; }" in fn
      and "sb.classList.add('mobile-open')" in fn and "(max-width: 720px)" in js)
check("8 chọn một mục / bấm nền mờ / Esc → đóng menu", "e.target.closest('#sidebar .nav-item')) closeMobileSidebar();" in fn
      and "shade.addEventListener('click', closeMobileSidebar)" in fn and "e.key === 'Escape'" in fn)
check("9 hộp Update trong dải: một biểu tượng 44px, bấm = mở menu",
      ".sidebar.collapsed .sidebar-update { width: 44px; height: 44px;" in css
      and ".sidebar:not(.mobile-open) .sidebar-update { width: 44px; height: 44px;" in media
      and "closest('#sidebar-update')" in js and "if (rail) toggleSidebar();" in js)
check("10 mục trong dải đủ lớn cho ngón tay (44px)", ".sidebar:not(.mobile-open) .nav-item { padding: 10px; justify-content: center; min-height: 44px; }" in media)
check("11 đổi số phiên bản file tĩnh để trình duyệt nạp bản mới", "style.css?v=10" in html and "app.js?v=41" in html)

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
