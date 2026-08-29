"""Lỗi mở browser phải NÓI ĐÚNG lý do — không đoán "hết RAM" khi không phải.

Run:  python tests/preview_lasterror_test.py     (exit 0 = pass)

Bối cảnh (2026-08-27): người dùng hỏi "vì sao cứ báo 'Phiên đóng đột ngột — thường do
máy hết RAM…' trong khi mở trình duyệt KHÁC lại được?". Nếu thật hết RAM thì MỌI profile
đều fail; profile khác mở được ⇒ nguyên nhân RIÊNG của profile đó (user-data-dir lỗi,
nhân trình duyệt, tab cũ crash…), KHÔNG phải RAM. Nguyên nhân gốc: profile hỏng thường
MỞ ĐƯỢC Chromium (thoát vòng launch) rồi browser/renderer chết SAU đó, và
context.on('close') cũ chỉ `process.exit(0)` — thoát CÂM, không lý do → cloud rơi về câu
suy đoán "hết RAM".

Kiểm ở đây, đối chiếu code THẬT trong extensions/browser:
  PHẦN A (preview_server.cjs, chạy trên nguyên văn hàm trích ra):
    1. Chết TRƯỚC everReady (context close) → emitFatalAndExit('browser_crashed'), message
       nói rõ KHÔNG phải hết RAM, và GHI <profile>/preview_last_error.json.
    2. Chết SAU everReady → KHÔNG emit fatal, thoát 0 (đóng bình thường).
    3. markReady xoá dấu lỗi phiên trước.
    4. classifyFatal: Target closed / browserContext.newPage / Protocol error →
       browser_crashed; KHÔNG regress "Target page, context or browser has been closed"
       (vẫn launch_failed); engine_expired / oom giữ nguyên.
  PHẦN B (routes.py /preview/last-error):
    - Đọc file MỚI → {reason, message_vi, detail, at}; file CŨ (>cửa sổ) → {}.
    - Thiếu file / profile rỗng → {}. Path traversal ("../") → {}.
    - Owner-only: khách (guest_scope) → 403.
    - detail gom thêm tail stdout của tiến trình preview nếu phiên còn trong sổ.
"""
import os
import sys
import json
import time
import shutil
import asyncio
import tempfile
import subprocess
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tubecli.extensions.browser import routes as R  # noqa: E402
from tubecli.extensions.browser import profile_manager as PM  # noqa: E402
from fastapi import HTTPException  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class FakeState:
    def __init__(self, guest_scope=None):
        self.guest_scope = guest_scope


class FakeRequest:
    def __init__(self, guest_scope=None):
        self.state = FakeState(guest_scope)


def run_route(profile, request):
    return asyncio.run(R.api_preview_last_error(profile=profile, request=request))


print("=" * 70)
print("PREVIEW LAST-ERROR: NÓI ĐÚNG LÝ DO, KHÔNG ĐOÁN HẾT RAM")
print("=" * 70)

# ── PHẦN A — preview_server.cjs (behavioural, chạy trên nguyên văn file) ──────
PS = ROOT / "tubecli" / "extensions" / "browser" / "preview_server.cjs"
node = shutil.which("node")
if not node:
    print("  (bỏ qua PHẦN A: không có node trên máy này)")
else:
    tmpA = tempfile.mkdtemp(prefix="preview_lasterr_A_")
    # Harness: trích các hàm module-scope THẬT rồi chạy trong sandbox có process giả.
    # Không mở browser thật (spec cấm) — chỉ nạp logic quyết định chết/không-chết.
    harness = r"""
const fs = require('fs');
const path = require('path');
const PS = process.argv[1];
const TMP = process.argv[2];
const src = fs.readFileSync(PS, 'utf8');

function extract(name) {
    const re = new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}');
    const m = src.match(re);
    if (!m) { console.error('NOFN', name); process.exit(2); }
    return m[0];
}
const funcs = ['classifyFatal','writeLastError','clearLastError','markReady',
               'emitFatalAndExit','onBrowserDeath'].map(extract).join('\n\n');

let lastExit = null;
class ExitSignal extends Error {}
const fakeProcess = { exit: (c) => { lastExit = c; throw new ExitSignal(); } };

function makeSandbox(initialEver, dir, attach) {
    const prelude = `
        // preview_server.cjs:51 khai  const attachMode = attachCdpPort > 0.
        // onBrowserDeath rẽ nhánh theo nó, nên sandbox PHẢI cấp — thiếu là
        // ReferenceError, và đó chính là cách test này từng đỏ.
        const attachMode = !!opts.attach;
        let everReady = opts.ever;
        let __fatalEmitted = false;
        let storageDirRef = opts.dir;
        const profileName = 'tuan5';
        const __ev = { broadcasts: [], logs: [], serverClosed: false };
        function broadcast(d) { __ev.broadcasts.push(d); }
        function log(m) { __ev.logs.push(m); }
        let serverRef = { close() { __ev.serverClosed = true; } };
    `;
    const ret = `
        return { __ev, onBrowserDeath, emitFatalAndExit, markReady, writeLastError,
                 clearLastError, classifyFatal, isReady: () => everReady };
    `;
    const factory = new Function('fs','path','process','opts', prelude + funcs + ret);
    return factory(fs, path, fakeProcess, { ever: initialEver, dir, attach: !!attach });
}

const errFile = path.join(TMP, 'preview_last_error.json');
function rm() { try { fs.unlinkSync(errFile); } catch (e) {} }
function readErr() { try { return JSON.parse(fs.readFileSync(errFile,'utf8')); } catch (e) { return null; } }

let bad = 0;
function ok(label, cond, extra) { if (!cond) { bad++; console.error('FAIL', label, extra || ''); } }

(async () => {
    // 1. Chết TRƯỚC everReady → browser_crashed + ghi file
    rm();
    let s = makeSandbox(false, TMP);
    lastExit = null;
    try { s.onBrowserDeath('context closed'); } catch (e) { if (!(e instanceof ExitSignal)) throw e; }
    const b = s.__ev.broadcasts.find(x => x.type === 'fatal');
    ok('A1 fatal-frame', !!b, JSON.stringify(s.__ev.broadcasts));
    ok('A1 reason=browser_crashed', b && b.reason === 'browser_crashed', b && b.reason);
    ok('A1 message KHONG-phai-RAM', b && /KHÔNG phải hết RAM/.test(b.message), b && b.message);
    const f = readErr();
    ok('A1 ghi file', !!f, f);
    ok('A1 file.reason', f && f.reason === 'browser_crashed', f && f.reason);
    ok('A1 file.at', f && !!f.at, f);
    await new Promise(r => setTimeout(r, 500));   // đợi setTimeout(300) gọi exit(1)
    ok('A1 exit=1', lastExit === 1, lastExit);

    // 2. Chết SAU everReady → không fatal, exit 0
    rm();
    s = makeSandbox(true, TMP);
    lastExit = null;
    try { s.onBrowserDeath('context closed'); } catch (e) { if (!(e instanceof ExitSignal)) throw e; }
    ok('A2 khong-fatal', !s.__ev.broadcasts.find(x => x.type === 'fatal'), JSON.stringify(s.__ev.broadcasts));
    ok('A2 exit=0', lastExit === 0, lastExit);
    ok('A2 khong-ghi-file', readErr() === null, readErr());

    // 3. markReady xoá dấu lỗi
    rm();
    s = makeSandbox(false, TMP);
    s.writeLastError('oom', 'x', 'y');
    ok('A3 writeLastError tao-file', readErr() !== null);
    s.markReady();
    ok('A3 everReady=true', s.isReady() === true);
    ok('A3 markReady xoa-file', readErr() === null);

    // 4. classifyFatal
    s = makeSandbox(false, TMP);
    const cf = s.classifyFatal;
    ok('A4 Target closed -> browser_crashed', cf(new Error('Protocol error: Target closed')).reason === 'browser_crashed');
    ok('A4 browserContext.newPage -> browser_crashed', cf(new Error('browserContext.newPage: Timeout')).reason === 'browser_crashed');
    ok('A4 Protocol error -> browser_crashed', cf(new Error('Protocol error (Page.navigate)')).reason === 'browser_crashed');
    ok('A4 REGRESS launch_failed', cf(new Error('Target page, context or browser has been closed')).reason === 'launch_failed', cf(new Error('Target page, context or browser has been closed')).reason);
    ok('A4 engine_expired', cf(new Error('Key expired!')).reason === 'engine_expired');
    ok('A4 oom', cf(new Error('spawn ENOMEM')).reason === 'oom');

    // ── A5. CHẾ ĐỘ GHÉP: khung xem KHÔNG được giết phiên của agent ──
    // Hồi quy tốn kém nhất mà tính năng "xem agent làm việc" có thể gây ra: nếu
    // đóng khung mà browser thật chết theo thì nó thành "âm thầm giết agent".
    rm();
    const s4 = makeSandbox(false, TMP, true);   // ghép, chưa kịp thấy hình
    lastExit = null;
    try { s4.onBrowserDeath('disconnected', 'cdp gone'); } catch (e) {}
    // exit(0) nam trong setTimeout(300) — kiem ngay thi lastExit con null.
    await new Promise(r => setTimeout(r, 500));
    const ev4 = s4.__ev;
    ok('A5 ghep: mat ket noi -> thoat 0, khong phai su co', lastExit === 0, 'lastExit=' + lastExit);
    ok('A5 ghep: KHONG phan loai crash/oom',
       !ev4.broadcasts.some(b => /fatal|crash|oom/i.test(String(b && b.type))),
       JSON.stringify(ev4.broadcasts).slice(0, 160));
    ok('A5 ghep: co bao attach_ended cho khung',
       ev4.broadcasts.some(b => b && b.type === 'attach_ended'),
       JSON.stringify(ev4.broadcasts).slice(0, 160));

    // Đường KHÔNG ghép phải giữ nguyên hành vi cũ — vá này không được nới lỏng nó.
    rm();
    const s5 = makeSandbox(false, TMP, false);
    lastExit = null;
    try { s5.onBrowserDeath('disconnected', 'crashed'); } catch (e) {}
    ok('A5 thuong: chet truoc khi thay hinh VAN la su co', lastExit !== 0, 'lastExit=' + lastExit);

    process.exit(bad ? 1 : 0);
})();
"""
    try:
        proc = subprocess.run([node, "-e", harness, str(PS), tmpA],
                              capture_output=True, text=True, timeout=40)
        check("PHẦN A: everReady/onBrowserDeath/classifyFatal đúng trên code thật",
              proc.returncode == 0, (proc.stdout + proc.stderr).strip())
    finally:
        shutil.rmtree(tmpA, ignore_errors=True)

# ── PHẦN B — routes.py /preview/last-error ───────────────────────────────────
tmpB = tempfile.mkdtemp(prefix="preview_lasterr_B_")
_orig_profiles_dir = PM.PROFILES_DIR
_orig_sessions = dict(R._preview_processes)
try:
    PM.PROFILES_DIR = tmpB
    prof = "tuan5"
    prof_dir = os.path.join(tmpB, prof)
    os.makedirs(prof_dir, exist_ok=True)
    err_path = os.path.join(prof_dir, "preview_last_error.json")

    def write_err(reason="browser_crashed", message="mở rồi tắt ngay, KHÔNG phải hết RAM",
                  detail="stack…", when=None):
        with open(err_path, "w", encoding="utf-8") as fp:
            json.dump({"reason": reason, "message": message, "detail": detail,
                       "at": "2026-08-27T00:00:00Z"}, fp)
        if when is not None:
            os.utime(err_path, (when, when))

    # B1. File MỚI → trả reason/message_vi/detail/at
    R._preview_processes.clear()
    write_err()
    r = run_route(prof, FakeRequest())
    check("B1 file mới → có reason", r.get("reason") == "browser_crashed", r)
    check("B1 message → message_vi", r.get("message_vi") == "mở rồi tắt ngay, KHÔNG phải hết RAM", r)
    check("B1 có at", r.get("at") == "2026-08-27T00:00:00Z", r)
    check("B1 có detail", "stack" in r.get("detail", ""), r)

    # B2. File CŨ (mtime cách đây >2 phút) → {}
    write_err(when=time.time() - 300)
    r = run_route(prof, FakeRequest())
    check("B2 file cũ >cửa sổ → {} (không nói lý do cũ)", r == {}, r)

    # B3. Không có file → {}
    os.remove(err_path)
    r = run_route(prof, FakeRequest())
    check("B3 thiếu file → {}", r == {}, r)

    # B4. profile rỗng → {}
    check("B4 profile rỗng → {}", run_route("", FakeRequest()) == {}, "")

    # B5. Path traversal → {} (không đọc ra ngoài PROFILES_DIR)
    # tạo một file lỗi ngay dưới tmpB (cha của PROFILES_DIR nếu prof='..')
    outside = os.path.join(os.path.dirname(tmpB), "preview_last_error.json")
    try:
        with open(outside, "w", encoding="utf-8") as fp:
            json.dump({"reason": "oom", "message": "leaked", "detail": "", "at": "x"}, fp)
        r = run_route("..", FakeRequest())
        check("B5 traversal '..' → {} (chặn ra ngoài)", r == {}, r)
    finally:
        try: os.remove(outside)
        except OSError: pass

    # B6. Owner-only: khách (guest_scope) → 403
    write_err()
    raised = False
    try:
        run_route(prof, FakeRequest(guest_scope={"profiles": ["tuan5"]}))
    except HTTPException as e:
        raised = (e.status_code == 403)
    check("B6 guest → 403 (owner-only)", raised)

    # B7. detail gom tail stdout của phiên preview còn trong sổ
    write_err(detail="lỗi engine")
    R._preview_processes.clear()
    R._preview_processes["preview_x"] = {
        "proc": None, "port": 9001, "profile": prof,
        "early_output": deque(["[ShardX] Spawning…", "Key expired!"], maxlen=40),
    }
    r = run_route(prof, FakeRequest())
    check("B7 detail có nhật ký preview", "Key expired!" in r.get("detail", ""), r)
    check("B7 detail vẫn giữ detail gốc", "lỗi engine" in r.get("detail", ""), r)
    # _preview_tail_for_profile trực tiếp
    check("B7 tail helper trả dòng cuối", "Key expired!" in R._preview_tail_for_profile(prof))
    check("B7 tail profile khác → rỗng", R._preview_tail_for_profile("khac") == "")
finally:
    PM.PROFILES_DIR = _orig_profiles_dir
    R._preview_processes.clear()
    R._preview_processes.update(_orig_sessions)
    shutil.rmtree(tmpB, ignore_errors=True)

# ── report ──────────────────────────────────────────────────────────────────
print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
