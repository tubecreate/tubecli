"""File Manager: vùng cho phép của AI gồm thư mục data THẬT của TubeCLI, kể cả khi server khởi động ở thư mục khác.

Chạy:  python tests/file_manager_real_data_root_test.py      (mã thoát 0 = đạt)

Vì sao (user 15/11/2026): giao agent «sao lưu video Content Studio lên Google Drive» — agent báo bị chặn quyền. Server do
TubeCLI Connect mở đứng ở C:\\Users\\<tên>\\TubeCLI nên «data» (tính theo thư mục đang đứng) trỏ sang chỗ khác; mọi file
trong <repo>\\data bị từ chối «nằm ngoài vùng cho phép». Kèm: tải file có sẵn trên đĩa lên Drive không dính trần 512 MB.

Cách ly: chỉ kiểm đường dẫn (không đọc / ghi file thật), đứng trong thư mục tạm; không mạng.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {str(detail)[:300]}")


from tubecli.config import DATA_DIR  # noqa: E402
from tubecli.extensions.file_manager import file_service as FS  # noqa: E402

REAL = os.path.abspath(str(DATA_DIR))
os.environ.pop("TUBECLI_DATA_DIR", None)
os.chdir(str(ROOT / "tests"))          # như server do Connect mở: đứng ở một thư mục KHÁC gốc repo (thư mục tạm của
                                       # Windows nằm trong AppData\Local — vùng luôn bị chặn — nên không dùng được)
svc = FS.FileService()


def allowed(path):
    try:
        svc._validate_path(path)
        return True
    except ValueError:
        return False


video = os.path.join(REAL, "extensions_data", "content_studio", "outputs", "exports", "episode_1.mp4")
check("1 đứng ở thư mục khác: thư mục data thật vẫn nằm trong vùng cho phép", os.path.normpath(REAL) in svc.allowed_roots,
      svc.allowed_roots)
check("2 video Content Studio trong data thật → được phép", allowed(video))
check("3 «data» theo thư mục đang đứng vẫn được phép như cũ", allowed(os.path.join(os.getcwd(), "data", "x.txt")))
check("4 bí mật trong data thật VẪN bị chặn (agents.json, global_settings.json, groups/)",
      not allowed(os.path.join(REAL, "agents.json")) and not allowed(os.path.join(REAL, "global_settings.json"))
      and not allowed(os.path.join(REAL, "groups", "g1.json")))
check("5 hồ sơ trình duyệt trong data thật vẫn bị chặn",
      not allowed(os.path.join(REAL, "extensions_data", "browser", "browser_profiles", "p1", "Cookies")))
outside = os.path.join(os.path.dirname(REAL), "tubecli", "core", "auth.py")
check("6 ngoài data (mã nguồn cạnh data) vẫn bị từ chối", not allowed(outside) or FS.FileService._under(outside, os.path.expanduser("~")))
check("7 không có gốc trùng lặp", len(svc.allowed_roots) == len(set(svc.allowed_roots)))

src = (ROOT / "tubecli" / "extensions" / "file_manager" / "drive.py").read_text(encoding="utf-8")
up = src[src.index("async def drive_upload_path"):src.index("async def drive_upload_content")]
check("8 tải file trên đĩa: trần riêng MAX_UPLOAD_PATH_MB (≥ 2 GB), không dùng trần 512 MB của đường trình duyệt",
      "MAX_UPLOAD_PATH_MB" in up and "MAX_TRANSFER_MB" not in up and "MAX_UPLOAD_PATH_MB = 8192" in src)
check("9 …gửi tiếp nối từng khúc (không nạp cả file vào RAM)", "resumable=True, chunksize=UPLOAD_CHUNK_MB * 1024 * 1024" in up)
check("10 đường nhận byte từ trình duyệt giữ trần 512 MB", "MAX_TRANSFER_MB = 512" in src
      and "MAX_TRANSFER_MB" in src[src.index("async def drive_upload_content"):src.index("def _dl_note")])

print(f"\n{passed}/{passed + failed} PASS")
sys.exit(1 if failed else 0)
