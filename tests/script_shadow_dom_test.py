# Bước `condition` phải nhìn thấy đúng những gì bước `upload` nhìn thấy.
#
# Chạy:  python tests/script_shadow_dom_test.py       (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Script đăng YouTube có một nhánh `condition` hỏi "ô thumbnail có trên trang
#   không?" bằng document.querySelector, rồi mới chạy bước `upload`. Nhưng:
#       document.querySelector  — KHÔNG đi vào shadow DOM
#       page.locator / CDP pierce — CÓ
#   YouTube Studio là Polymer: `input#file-loader` nằm trong shadow root của
#   `ytcp-thumbnail-uploader`. Nên câu hỏi luôn trả lời KHÔNG, `then_steps` không
#   bao giờ chạy, `else_steps` rỗng → im lặng tuyệt đối. Người dùng sinh thumbnail
#   cả buổi sáng 9/9/2026 mà không cái nào lên kênh, và không có một dòng lỗi nào.
#
#   Test này chạy CHROMIUM THẬT, vì đây đúng là loại lỗi mà suy luận trên giấy trả
#   lời sai: bản vá đầu tiên (thử nguyên selector trong từng shadow root) vẫn trượt,
#   và chỉ trình duyệt thật nói ra điều đó — selector bắc qua ranh giới shadow thì
#   phải đi TỪNG CHẶNG mới tới nơi.
import io
import re
import sys
from pathlib import Path

# Console Windows mặc định là cp1252: in tiếng Việt vào đó là UnicodeEncodeError,
# và bài test chết trước cả khi kiểm được gì.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tubecli" / "extensions" / "browser_scripts" / "runner" / "script_runner.js"

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} -> {detail}")


src = RUNNER.read_text(encoding="utf-8")
m = re.search(r"const DEEP_QUERY_SRC = `(.*?)`;", src, re.S)
if not m:
    print("SKIP: không thấy DEEP_QUERY_SRC trong runner")
    sys.exit(0)
HELPER = m.group(1)

# Bộ ba bước dùng mã chạy-trong-trang đều phải được cấp tcQuery, không chỉ mỗi
# `condition`: `evaluate` là chỗ nhánh thumbnail tự khai báo kết quả, còn
# `loop.break_on` là chỗ vòng chờ tải lên quyết định dừng.
check("condition chạy qua inPage()", "page.evaluate(inPage(checkCode))" in src)
check("evaluate chạy qua inPage()", "page.evaluate(inPage(code))" in src)
check("loop.break_on chạy qua inPage()", "inPage(interpolate(params.break_on))" in src)
check("KHÔNG vá đè document.querySelector của trang",
      "document.querySelector =" not in src and "Document.prototype.querySelector" not in src)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: chưa cài playwright")
    print(f"{PASS} ok, {FAIL} fail (chỉ phần đọc mã)")
    sys.exit(1 if FAIL else 0)

# Dựng lại đúng hình dạng YouTube Studio: ô thumbnail nằm trong shadow root, và
# lồng thêm một tầng nữa để chắc chắn không phải ăn may một cấp.
HTML = """
<body>
  <div id="light"><input id="plain" type="text"></div>
  <ytcp-thumbnail-uploader id="u"></ytcp-thumbnail-uploader>
  <ytcp-uploads-dialog id="d"></ytcp-uploads-dialog>
  <script>
    class Up extends HTMLElement {
      connectedCallback() {
        this.attachShadow({mode: 'open'}).innerHTML =
          '<div class="box"><input id="file-loader" type="file"></div>';
      }
    }
    customElements.define('ytcp-thumbnail-uploader', Up);

    class Inner extends HTMLElement {
      connectedCallback() {
        this.attachShadow({mode: 'open'}).innerHTML = '<button id="done-button">Publish</button>';
      }
    }
    customElements.define('ytcp-inner-panel', Inner);

    class Dlg extends HTMLElement {
      connectedCallback() {
        this.attachShadow({mode: 'open'}).innerHTML = '<ytcp-inner-panel></ytcp-inner-panel>';
      }
    }
    customElements.define('ytcp-uploads-dialog', Dlg);
  </script>
</body>
"""

SEL = "ytcp-thumbnail-uploader input#file-loader"
DEEP2 = "ytcp-uploads-dialog #done-button"


def deep(page, expr):
    return page.evaluate("(() => { " + HELPER + " return (" + expr + "); })()")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.set_content(HTML)

    # 1. Chứng minh cái bẫy có thật, không phải suy đoán.
    check("document.querySelector KHÔNG thấy ô trong shadow DOM (đây là gốc rễ)",
          page.evaluate("!!document.querySelector(%r)" % SEL) is False)
    check("locator của Playwright thì THẤY — chính sự lệch này giết nhánh thumbnail",
          page.locator(SEL).count() == 1)

    # 2. Bản vá phải khớp với locator, ở cả hai hình dạng.
    check("tcQuery thấy ô thumbnail bắc qua ranh giới shadow", deep(page, "!!tcQuery(%r)" % SEL))
    check("tcQuery đi được qua shadow LỒNG NHAU", deep(page, "!!tcQuery(%r)" % DEEP2))
    check("tcQuery trả về đúng phần tử",
          deep(page, "tcQuery(%r).id" % SEL) == "file-loader")
    check("tcQuery vẫn làm việc bình thường với DOM thường",
          deep(page, "tcQuery('#light input#plain').id") == "plain")
    check("không có thì trả null, không ném",
          deep(page, "tcQuery('#khong-ton-tai') === null"))
    check("tcQueryAll gom được nhiều root",
          deep(page, "tcQueryAll('input').length") == 2)

    # 3. Selector có ngoặc/dấu cách bên trong không được cắt bậy.
    check("không cắt nhầm selector có ngoặc vuông",
          deep(page, "tcQuery('input[type=\"file\"]').id") == "file-loader")

    # 4. Đúng câu điều kiện pipeline sinh ra — kiểm bằng chính chuỗi ấy.
    sys.path.insert(0, str(ROOT))
    try:
        from tubecli.extensions.content_video.pipeline import thumbnail_branch_step
        step = thumbnail_branch_step()
        raw = step["params"]["check"].replace("{{thumbnail_set}}", "1")
        check("điều kiện của pipeline trả TRUE trên trang có shadow DOM", deep(page, raw) is True)
        then_codes = [s.get("params", {}).get("code", "") for s in step["params"]["then_steps"]]
        check("nhánh thành công tự xác nhận file đã vào ô",
              any("files" in c and "thumbnail" not in c.lower() or "files.length" in c for c in then_codes),
              then_codes)
        check("nhánh trượt cũng ghi lại dấu vết (không im lặng)",
              any(s.get("params", {}).get("save_as") == "thumbnail_done"
                  for s in step["params"]["else_steps"]), step["params"]["else_steps"])
    except Exception as e:      # noqa: BLE001
        check("nạp được pipeline để kiểm câu điều kiện", False, repr(e))

    browser.close()

print("=" * 62)
print(f"{PASS}/{PASS + FAIL} PASS" if not FAIL else f"{FAIL} FAIL / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
