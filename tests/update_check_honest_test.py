# Dò cập nhật phải NÓI khi nó chưa hỏi được, và bản cài từ git cũng phải được so với Chợ.
#
# Chạy:  python tests/update_check_honest_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   Ngày 10/9/2026 người dùng chờ một bản extension đã phát hành lên Chợ mà bảng
#   Quản lý Extension vẫn ghi "Mọi extension đã ở bản mới nhất", và nút cập nhật lõi
#   thì không hiện. Hai chỗ cùng một bệnh: KHÔNG HỎI ĐƯỢC và KHÔNG CÓ GÌ MỚI trả về
#   y hệt nhau, nên giao diện nói câu khẳng định cho một thứ nó chưa biết.
#
#   Ba lỗ đã đo được trong mã:
#     1. market/routes._scan_git_extensions chỉ ghi extension KHÔNG có .git vào bảng
#        so với Chợ. Extension từng cài bằng git URL vĩnh viễn "đã mới nhất": git
#        remote không có commit mới, mà đường Chợ không bao giờ được hỏi tới.
#     2. _merge_marketplace_updates nuốt lỗi gọi Chợ (chỉ print) rồi trả danh sách
#        rỗng — giống hệt lúc thật sự không có gì mới.
#     3. system/check-update chạy `git fetch origin` mà KHÔNG xem returncode. Fetch
#        hỏng thì origin/main đứng im, rev-list đếm ra 0, và badge nói đã mới nhất.
import ast
import asyncio
import io
import json
import os
import sys
import tempfile
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


# ── A. bảng so với Chợ nhận CẢ extension có .git ───────────────────────────
import tubecli.config as cfg  # noqa: E402
import tubecli.extensions.market.routes as MR  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="updchk_"))
ext_root = TMP / "extensions_external"
for name, ver, has_git in (("plain_ext", "1.0.0", False), ("git_ext", "2.0.0", True)):
    d = ext_root / name
    d.mkdir(parents=True)
    io.open(d / "tubecli-extension.json", "w", encoding="utf-8").write(
        json.dumps({"name": name, "display_name": name.replace("_", " ").title(), "version": ver}))
    if has_git:
        (d / ".git").mkdir()          # có .git nhưng KHÔNG phải repo thật → git lệnh nào cũng hỏng
cfg.EXTENSIONS_EXTERNAL_DIR = ext_root

updates, local_extensions, git_updated = MR._scan_git_extensions()
check("A extension thường vào bảng", "plain_ext" in local_extensions, list(local_extensions))
check("A extension CÓ .git cũng vào bảng", "git_ext" in local_extensions, list(local_extensions))
check("A .git không có commit mới → chưa báo gì", updates == [] and git_updated == set(), (updates, git_updated))

# ── B. Chợ có bản mới hơn → báo, kể cả bản cài từ git ──────────────────────
async def market(items, raise_it=False):
    async def _list(*a, **k):
        if raise_it:
            raise RuntimeError("tunnel rớt")
        return {"status": "success", "data": items}
    MR.market_service.list_items = _list
    return await MR._merge_marketplace_updates([], dict(local_extensions), git_updated)


res = asyncio.run(market([
    {"title": "Plain Ext", "version": "1.5.0", "public_id": "aaa"},
    {"title": "Git Ext", "version": "3.0.0", "public_id": "bbb"},
]))
names = sorted(u["name"] for u in res["updates"])
check("B cả hai được báo bản mới", names == ["git_ext", "plain_ext"], names)
check("B không có lỗi khi hỏi được Chợ", res.get("error") == "", res.get("error"))

res = asyncio.run(market([{"title": "Plain Ext", "version": "1.0.0", "public_id": "aaa"}]))
check("B Chợ bằng bản đang cài → không báo", res["updates"] == [] and res["error"] == "", res)

# Đã có bản mới theo git thì đừng báo lần hai từ Chợ.
res = asyncio.run(MR._merge_marketplace_updates(
    [{"name": "git_ext", "is_git": True}], dict(local_extensions), {"git_ext"}))
check("B git đã báo rồi thì Chợ không báo trùng",
      [u["name"] for u in res["updates"]] == ["git_ext"], res["updates"])

# ── C. hỏi Chợ hỏng → error, KHÔNG phải "đã mới nhất" ─────────────────────
res = asyncio.run(market([], raise_it=True))
check("C ngoại lệ → error nói lý do", res["updates"] == [] and "tunnel rớt" in res["error"], res)
res = asyncio.run(market([]))
check("C Chợ trả danh sách rỗng → cũng là error", res["updates"] == [] and res["error"] != "", res)

# ── D. lõi: fetch hỏng phải nói ra ─────────────────────────────────────────
# Đọc mã bằng AST: gọi thật sẽ chạy git trên chính repo này.
src = io.open(ROOT / "tubecli" / "api" / "server.py", encoding="utf-8").read()
fn = next(n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "system_check_update")
body = ast.get_source_segment(src, fn) or ""
check("D fetch được gán vào biến", "fetch = subprocess.run(" in body)
check("D có xem returncode của fetch", "if fetch.returncode != 0:" in body)
check("D trả check_error", '"check_error": check_error' in body)
check("D rev-list hỏng cũng vào check_error", "if r_count.returncode != 0 and not check_error:" in body)
check("D thiếu git → trả lời có lý do, không 500", "except FileNotFoundError:" in body
      and "Không tìm thấy git" in body)

# ── E. giao diện cloud: lỗi hiện ra, dò lại được ───────────────────────────
CLOUD = ROOT.parent / "tubecli-cloud"
if not CLOUD.is_dir():
    print(f"(bỏ E: không thấy repo cloud ở {CLOUD})")
else:
    fb = io.open(CLOUD / "components" / "flow" / "FlowBuilder.js", encoding="utf-8").read()
    hub = io.open(CLOUD / "components" / "flow" / "ExtensionHub.js", encoding="utf-8").read()
    btn = io.open(CLOUD / "components" / "flow" / "FlowUpdateButton.js", encoding="utf-8").read()
    route = io.open(CLOUD / "app" / "api" / "servers" / "[id]" / "update-check" / "route.js", encoding="utf-8").read()
    check("E loadUpdates dò lại được", "loadUpdates = useCallback(async (force = false)" in fb
          and "if (updatesStarted.current && !force) return;" in fb)
    check("E giữ lỗi dò vào state", "setUpdatesError(String(r.error || ''))" in fb
          and "const [updatesError, setUpdatesError]" in fb)
    check("E lỗi đi qua context", "updatesMap, updatesError, loadUpdates" in fb)
    check("E bảng quản lý hiện lỗi + nút dò lại", "flow.hub.updCheckFailed" in hub
          and "loadUpdates(true)" in hub)
    check("E rỗng + có lỗi thì KHÔNG nói 'đã mới nhất'",
          "updatesError ? t('flow.hub.updUnknown') : t('flow.hub.allUpToDate')" in hub)
    check("E route chuyển check_error ra", "check_error: checkError" in route)
    check("E nút lõi hiện chip khi chưa dò được", "if (!info?.check_error) return null;" in btn
          and "upd.checkFailed" in btn)
    KEYS = ("flow.hub.updCheckFailed", "flow.hub.updRecheck", "flow.hub.updUnknown", "upd.checkFailed")
    for lang in ("en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"):
        loc = io.open(CLOUD / "lib" / "locales" / f"{lang}.js", encoding="utf-8").read()
        miss = [k for k in KEYS if f"'{k}':" not in loc]
        check(f"E locale {lang} đủ khoá", not miss, miss)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
