# -*- coding: utf-8 -*-
"""File bí mật trong data/ phải nằm ngoài tầm với của agent AI.

Chạy:  .venv/Scripts/python tests/ai_secret_files_test.py     (exit 0 = pass)

VÌ SAO: `data/` nằm TRONG vùng agent được phép đọc ghi (allowed_roots), nên mọi bí mật
để dưới đó chỉ được che bằng AI_PROTECTED_DATA_SUBDIRS. Danh sách ấy đã có
cloud_api_keys.json và khoá của capcut_tts — vì từng đo được rằng agent đọc thẳng được
chúng. Hai file thêm vào 23/9/2026:

  cloud_identity.json — `town_key` là KHOÁ KÝ của máy: ai cầm nó thì ký được
                        POST /api/v1/public/invoke, tức chạy được skill công khai của
                        máy này. Kèm `owner` = mã chủ, mở luôn agent «chỉ mình tôi».
                        Cùng hôm đó route HTTP đã thôi phát hai thứ này ra ngoài — đóng
                        một cửa mà để hở cửa kia thì chỉ là đổi lối vào.
  public_agents.json  — cài đặt agent công khai. Agent sửa được file này là agent tự bật
                        mình ra cho người lạ, tự nâng trần lượt/ngày, tự đổi «chỉ mình
                        tôi» thành «mọi người». api/public_routes.py đòi phiên của CHỦ
                        đúng để chặn điều đó.

Bài test gọi thẳng bộ kiểm đường dẫn thật, không chép lại danh sách.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}  {detail}")


from tubecli.extensions.file_manager.file_service import (  # noqa: E402
    AI_PROTECTED_DATA_SUBDIRS, FileService,
)
from tubecli.config import DATA_DIR  # noqa: E402

svc = FileService()

SECRETS = ["cloud_identity.json", "public_agents.json", "cloud_api_keys.json", "global_settings.json"]
for f in SECRETS:
    check(f"{f} nằm trong danh sách chặn", f in AI_PROTECTED_DATA_SUBDIRS, AI_PROTECTED_DATA_SUBDIRS)

# Chặn THẬT: đường dẫn tuyệt đối tới file trong DATA_DIR phải bị _under() bắt.
blocked = getattr(svc, "ai_blocked", [])
check("bộ kiểm dựng được danh sách đường dẫn bị chặn", bool(blocked), blocked)
for f in SECRETS:
    target = os.path.join(str(DATA_DIR), f)
    hit = any(FileService._under(target, b) for b in blocked)
    check(f"chặn đúng đường dẫn thật: data/{f}", hit, target)

# Không chặn nhầm: file bình thường trong data/ vẫn đọc được.
for ok_file in ["flows.json", os.path.join("logs", "app.log")]:
    target = os.path.join(str(DATA_DIR), ok_file)
    hit = any(FileService._under(target, b) for b in blocked)
    check(f"KHÔNG chặn nhầm data/{ok_file}", not hit, target)

# Bẫy tên gần giống: "cloud_identity.json.bak" không được coi là file đã chặn, nhưng
# cũng KHÔNG được lọt nếu nó nằm trong một thư mục đã chặn.
near = os.path.join(str(DATA_DIR), "cloud_identity.json.bak")
check("tên gần giống không bị nhận nhầm là file đã chặn",
      not any(FileService._under(near, b) for b in blocked), near)

# ── Khách được chia sẻ cũng không đọc được ──────────────────────────────────
# Chủ chia sẻ nhầm thư mục cha thì khách đọc được cả data/. «Chia sẻ một thư mục» không
# phải là «trao khoá máy», nên đường của khách dùng CHUNG danh sách này.
from tubecli.api.server import _is_protected_secret  # noqa: E402

for f in SECRETS:
    target = os.path.join(str(DATA_DIR), f)
    check(f"đường của khách chặn data/{f}", _is_protected_secret(target) is True, target)
check("đường của khách KHÔNG chặn file làm việc bình thường",
      _is_protected_secret(os.path.join(str(DATA_DIR), "flows.json")) is False)
check("đường của khách không chặn thư mục ngoài data/",
      _is_protected_secret(os.path.join(str(ROOT), "README.md")) is False)

print(f"\n{passed} pass, {failed} fail")
sys.exit(1 if failed else 0)
