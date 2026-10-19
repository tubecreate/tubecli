# -*- coding: utf-8 -*-
"""CANH VÒNG «ĐI TỚI BƯỚC HIỂN THỊ» của script đăng YouTube Studio (19/10/2026).

User (Activity: step 15.loop5 → loop6 … cùng chuỗi [Kiếm tiền] → Bấm Tiếp): «này chặn luôn loop liên tục».

  A. JS chạy thật trong node (DOM giả): đứng yên một màn WIZARD_STUCK_ROUNDS vòng ⇒ ném T2_STUCK kèm chữ lỗi + tiến
     độ của Studio; màn đổi đều ⇒ không ném; không nhận ra màn nào (Studio đổi DOM) ⇒ không ném
  B. lời ném không chứa «Timeout / waiting for / locator» (runner coi là lỗi selector → chuỗi tự sửa dài)
  C. ensure_wizard_guard: chèn ĐẦU vòng có break_on hỏi radio PUBLIC; chạy lại không đổi; bản cũ thì làm mới;
     script không có vòng ấy ⇒ không đụng; script mặc định (assets) có vòng ấy
  D. ensure_thumbnail_branch gọi ensure_wizard_guard (vá cả script đã cài trên VPS lúc chạy)

Run:  python tests/wizard_guard_test.py
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tubecli.extensions.content_video import pipeline as P  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:400])


HARNESS = r"""
const code = process.argv[1];
const pages = JSON.parse(process.argv[2]);        // mỗi vòng: tên thẻ đang hiện (hay '' = không nhận ra)
const errText = process.argv[3] || '';
const el = (w, text) => ({ getBoundingClientRect: () => ({ width: w }), textContent: text || '', id: '' });
let current = '';
global.window = {};
global.document = {
  querySelector: (s) => {
    if (s === 'ytcp-video-upload-progress') return el(1, 'Upload complete ... Processing abandoned');
    return s === current ? el(100) : null;
  },
  querySelectorAll: (s) => (s.includes('error') && errText ? [el(10, errText)] : []),
};
const out = [];
for (const p of pages) {
  current = p;
  try { out.push({ ok: eval(code) }); } catch (e) { out.push({ err: e.message }); break; }
}
console.log(JSON.stringify(out));
"""


def run(pages, err=""):
    r = subprocess.run(["node", "-e", HARNESS, P.WIZARD_GUARD_CODE, json.dumps(pages), err],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        return [{"crash": r.stderr[:300]}]
    return json.loads(r.stdout)


print("A. JS trong node")
mon = "ytcp-video-monetization"
res = run(["ytcp-video-metadata-editor", mon, mon, mon, mon, mon], "Video is too long")
ok(len(res) == 4 and "err" in res[-1] and res[-1]["err"].startswith("T2_STUCK")
   and "3 rounds" in res[-1]["err"] and "Video is too long" in res[-1]["err"] and "Processing abandoned" in res[-1]["err"],
   "kẹt màn Kiếm tiền 3 vòng ⇒ ném T2_STUCK ở vòng thứ 4, kèm lỗi + tiến độ", res)
res = run(["ytcp-video-metadata-editor", mon, "ytcp-uploads-video-elements", "ytcp-uploads-checks", "ytcp-uploads-review"])
ok(all("ok" in x for x in res) and len(res) == 5, "màn đổi đều ⇒ không ném", res)
res = run(["", "", "", "", "", ""])
ok(all("ok" in x for x in res), "không nhận ra màn nào ⇒ im như trước", res)
res = run([mon, mon, "ytcp-uploads-video-elements", "ytcp-uploads-video-elements", "ytcp-uploads-checks"])
ok(all("ok" in x for x in res), "đứng 2 vòng rồi qua ⇒ không ném (ngưỡng 3)", res)

print("B. lời ném")
low = P.WIZARD_GUARD_CODE.lower()
msg = low[low.index("t2_stuck"):low.index("return sig")]
ok(not any(w in msg for w in ("timeout", "waiting for", "locator")), "không mang chữ lỗi selector", msg)

print("C. ensure_wizard_guard")
asset = json.loads((ROOT / "tubecli" / "extensions" / "content_video" / "assets" / "youtube_upload.json").read_text(encoding="utf-8"))
steps = copy.deepcopy(asset["steps"])
loop = P._visibility_loop(steps)
ok(loop is not None and loop["label"].startswith("Đi tới bước HIỂN THỊ"), "script mặc định có vòng đi tới Hiển thị")
ok(P.ensure_wizard_guard(steps) is True, "lần đầu ⇒ chèn")
inner = P._visibility_loop(steps)["params"]["steps"]
ok(inner[0]["label"] == P.WIZARD_GUARD_LABEL and inner[1]["label"].startswith("Dò kênh có bật kiếm tiền"),
   "đứng ĐẦU vòng, trước bước dò kiếm tiền", [s.get("label") for s in inner[:2]])
ok(P.ensure_wizard_guard(steps) is False and sum(1 for s in inner if s.get("label") == P.WIZARD_GUARD_LABEL) == 1,
   "chạy lại ⇒ không đổi, không chèn đôi")
inner[0]["params"] = {"code": "old"}
ok(P.ensure_wizard_guard(steps) is True and P._visibility_loop(steps)["params"]["steps"][0]["params"]["code"] == P.WIZARD_GUARD_CODE,
   "bản cũ ⇒ làm mới tại chỗ")
plain = [{"type": "loop", "label": "x", "params": {"break_on": "true", "steps": []}}]
ok(P.ensure_wizard_guard(plain) is False and plain[0]["params"]["steps"] == [], "không có vòng Hiển thị ⇒ không đụng")

print("D. vá lúc chạy")
src = (ROOT / "tubecli" / "extensions" / "content_video" / "pipeline.py").read_text(encoding="utf-8")
body = src[src.index("def ensure_thumbnail_branch("):src.index("LIVE_CDP_WAIT =")]
ok("changed = ensure_wizard_guard(steps) or changed" in body, "ensure_thumbnail_branch gọi ensure_wizard_guard")


class _Store:
    def __init__(self, script):
        self.script, self.saved = script, None

    def get_script(self, slug):
        return copy.deepcopy(self.script)

    def update_script(self, slug, steps=None):
        self.saved = steps


import tubecli.extensions.browser_scripts.script_routes as SR  # noqa: E402
store = _Store({"steps": copy.deepcopy(asset["steps"])})
SR._store = lambda: store
P.ensure_thumbnail_branch("youtube_upload")
ok(store.saved and P._visibility_loop(store.saved)["params"]["steps"][0]["label"] == P.WIZARD_GUARD_LABEL,
   "script trong kho được lưu lại có bước canh")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
