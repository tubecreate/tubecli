"""Live view phải NÓI RA lý do — preflight (server) + phân loại lastError (JS).

Run:  python tests/preview_preflight_test.py     (exit 0 = pass)

Bối cảnh (2026-08-27): trên VPS 2 lõi / 1.9GB, mở hai browser cùng lúc thì cả hai
báo "The live view session closed before anything was shown", KHÔNG hề nói vì sao
(hết RAM? profile đang bị agent giữ? engine hết key?). Nguyên nhân: /preview/launch
không kiểm gì trước khi spawn Chromium, còn preview_server.cjs chết CÂM (throw không
.catch → tiến trình biến mất, WS đóng không lý do).

Kiểm ở đây, đối chiếu code thật trong extensions/browser:
  A. Preflight RAM thấp        → reason='low_memory' kèm free/need MB
  B. Profile đang chạy (agent) → reason='profile_busy', by='agent', who=<agent>
     Profile đang mở (khung)   → reason='profile_busy', by='frame'
     Proc đã chết              → KHÔNG tính là bận (không chặn nhầm)
  C. Engine BAS thiếu key      → reason='engine_key'
  D. Thứ tự ưu tiên            → profile_busy thắng low_memory (cụ thể nhất trước)
  E. env TUBECLI_PREVIEW_SESSION_MB ghi đè ngưỡng
  F. classifyFatal (preview_server.cjs) map lastError → engine_expired/lock/oom/
     launch_failed đúng; chuỗi mơ hồ KHÔNG bị đoán bừa thành oom
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.browser import routes as R  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class LiveProc:
    """poll() -> None nghĩa là tiến trình còn sống (đúng ngữ nghĩa Popen)."""
    def poll(self):
        return None


class DeadProc:
    def poll(self):
        return 0


print("=" * 70)
print("LIVE VIEW PREFLIGHT NÓI RA LÝ DO")
print("=" * 70)

# ── A. RAM thấp → low_memory ────────────────────────────────────────────────
r = R._low_memory_reason(180, 450, 0)
check("RAM 180<450 → low_memory", r and r["reason"] == "low_memory", r)
check("low_memory kèm free", r and r.get("free") == 180, r)
check("low_memory kèm need", r and r.get("need") == 450, r)
check("low_memory có message_vi tiếng Việt", r and "MB" in r.get("message_vi", ""), r)
check("RAM dư → không chặn", R._low_memory_reason(2000, 450, 0) is None)
# một launch khác đang bay → cần gấp đôi → browser thứ 2 bị từ chối
r2 = R._low_memory_reason(600, 450, 1)
check("in_flight=1 nâng need lên 2 phiên", r2 and r2["need"] == 900, r2)
check("không đọc được RAM → không đoán (None)", R._low_memory_reason(None, 450, 0) is None)

# ── B. profile_busy ─────────────────────────────────────────────────────────
inst_agent = [{"profile": "tuan5", "_process": LiveProc(),
               "_agent_id": "Trợ lý", "started_at": None, "pid": 111}]
r = R._preview_busy_reason("tuan5", {}, inst_agent)
check("agent sống → profile_busy", r and r["reason"] == "profile_busy", r)
check("profile_busy by=agent", r and r["by"] == "agent", r)
check("profile_busy nêu ai giữ (who)", r and r["who"] == "Trợ lý", r)
check("message nêu tên agent", r and "Trợ lý" in r.get("message_vi", ""), r)

inst_manual = [{"profile": "tuan5", "_process": LiveProc(),
                "_agent_id": None, "started_at": None, "pid": 222}]
r = R._preview_busy_reason("tuan5", {}, inst_manual)
check("browser tay (không agent) → profile_busy by=manual",
      r and r["reason"] == "profile_busy" and r["by"] == "manual", r)

inst_dead = [{"profile": "tuan5", "_process": DeadProc(),
              "_agent_id": "x", "started_at": None}]
check("proc CHẾT không tính là bận", R._preview_busy_reason("tuan5", {}, inst_dead) is None)

sess = {"preview_1": {"proc": LiveProc(), "profile": "tuan5",
                      "port": 9001, "started_at": None}}
r = R._preview_busy_reason("tuan5", sess, [])
check("khung preview khác cùng profile → profile_busy by=frame",
      r and r["reason"] == "profile_busy" and r["by"] == "frame", r)
check("profile khác → không bận (không chặn nhầm)",
      R._preview_busy_reason("tuan3", sess, inst_dead) is None)

# ── C. engine BAS thiếu key → engine_key ────────────────────────────────────
_orig_blockers = R.check_launch_blockers
try:
    R.check_launch_blockers = lambda p: "BAS_KEY_REQUIRED"
    r = R._engine_key_reason("tuanBAS")
    check("BAS thiếu key → engine_key", r and r["reason"] == "engine_key", r)
    check("engine_key có message_vi", r and "ShardX" in r.get("message_vi", ""), r)
    R.check_launch_blockers = lambda p: None
    check("engine ok → không chặn", R._engine_key_reason("tuanShardX") is None)
finally:
    R.check_launch_blockers = _orig_blockers

# ── D. thứ tự ưu tiên: profile_busy thắng low_memory ────────────────────────
# Vô hiệu hoá check engine ở block này (profile thật trên máy build có thể là BAS
# thiếu key → engine_key sẽ chen vào), để đo đúng thứ tự busy vs RAM.
_orig_ram = R._available_ram_mb
_orig_blk = R.check_launch_blockers
try:
    R.check_launch_blockers = lambda p: None
    R._available_ram_mb = lambda: 50   # RAM cực thấp
    # có agent giữ profile → phải báo profile_busy, KHÔNG phải low_memory
    r = R.preview_preflight("tuan5", {}, inst_agent, in_flight_others=0)
    check("bận + RAM thấp → báo profile_busy (cụ thể nhất trước)",
          r and r["reason"] == "profile_busy", r)
    # không bận → mới rơi xuống low_memory
    r = R.preview_preflight("tuan5", {}, [], in_flight_others=0)
    check("không bận + RAM thấp → low_memory", r and r["reason"] == "low_memory", r)
    # RAM dư, không bận, engine ok → cho mở (None)
    R._available_ram_mb = lambda: 4000
    check("mọi thứ ổn → preflight cho qua (None)",
          R.preview_preflight("tuan5", {}, [], in_flight_others=0) is None)
finally:
    R._available_ram_mb = _orig_ram
    R.check_launch_blockers = _orig_blk

# ── E. env ghi đè ngưỡng phiên ──────────────────────────────────────────────
_old = os.environ.get("TUBECLI_PREVIEW_SESSION_MB")
try:
    os.environ["TUBECLI_PREVIEW_SESSION_MB"] = "700"
    check("env override ngưỡng session", R._preview_session_mb() == 700, R._preview_session_mb())
    os.environ["TUBECLI_PREVIEW_SESSION_MB"] = "rác"
    check("env rác → fallback mặc định 450", R._preview_session_mb() == 450, R._preview_session_mb())
finally:
    if _old is None:
        os.environ.pop("TUBECLI_PREVIEW_SESSION_MB", None)
    else:
        os.environ["TUBECLI_PREVIEW_SESSION_MB"] = _old

# ── F. classifyFatal trong preview_server.cjs (chạy trên nguyên văn file) ────
PS = ROOT / "tubecli" / "extensions" / "browser" / "preview_server.cjs"
node = shutil.which("node")
if not node:
    print("  (bỏ qua kiểm classifyFatal: không có node trên máy này)")
else:
    harness = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
// Trích nguyên hàm classifyFatal từ file thật (nó tự chứa, chỉ dùng `err`).
const m = src.match(/function classifyFatal\(err\)\s*\{[\s\S]*?\n\}/);
if (!m) { console.error('NOFN'); process.exit(2); }
eval(m[0]);
const cases = [
  ['Key expired! I have installed a Bypass hook.', 'engine_expired'],
  ['invalid key for Security Browser',             'engine_expired'],
  ['Failed to create a ProcessSingleton / SingletonLock present', 'lock'],
  ['spawn ENOMEM',                                 'oom'],
  ['Cannot allocate memory',                       'oom'],
  ['Target page, context or browser has been closed', 'launch_failed'],
  ['ShardX browser engine (149) not found. Reinstall it.', 'launch_failed'],
];
let bad = 0;
for (const [inp, exp] of cases) {
  const r = classifyFatal(new Error(inp));
  if (!r || r.reason !== exp) { console.error('MISMATCH', JSON.stringify(inp), '->', r && r.reason, 'exp', exp); bad++; }
  if (!r || !r.message) { console.error('NO_MESSAGE', inp); bad++; }
}
process.exit(bad ? 1 : 0);
"""
    proc = subprocess.run([node, "-e", harness, str(PS)],
                          capture_output=True, text=True, timeout=30)
    check("classifyFatal map đúng 4 reason (engine_expired/lock/oom/launch_failed)",
          proc.returncode == 0, (proc.stdout + proc.stderr).strip())

# ── report ──────────────────────────────────────────────────────────────────
print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
