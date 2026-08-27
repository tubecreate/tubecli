"""The group activity log: what reaches the canvas panel, and what must not.

Run:  python tests/group_log_test.py     (exit 0 = pass)

Everything runs against a temporary data dir; the real data/ is never opened.

Three things are being locked in.

FIRST, THE LEAKS. This log is the first thing in the codebase that takes a
handler reply — text written for an LLM — and publishes it to a browser panel
verbatim. Those replies carry spreadsheet ids, Google credential ids, the
absolute path of a browser profile, and script variables (the exact place a
password leaked once already). group_log.scrub() is the only thing between
them and disk, and it is checked here against the real shapes: auth_manager's
own `cred_xxxx` strings, a /spreadsheets/d/<id> URL, group_scripts'
`name = value` output block, and a Windows profile directory.

SECOND, THE SEQUENCE. The panel polls with ?since=<seq> every couple of
seconds, so seq must be per group, strictly increasing, and must survive both
a file trim and a clear() — a counter that restarts would make the panel
replay lines it has already shown as if they were new.

THIRD, THE GATE. These two routes hang off the group router, which is
owner-only by omission: server.py::_guest_allowed denies by default and this
path is nowhere in it. That is asserted here against the code that actually
shipped (pulled out of server.py with ast, because importing server.py can
clone extensions), because "we forgot to add it to the allowlist" is not a
guarantee anyone can read off a diff a year from now.
"""
import asyncio
import ast
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import tubecli.config as cfg

TMP = pathlib.Path(tempfile.mkdtemp(prefix="group_log_"))
_REAL_EXT_DATA_PATH = cfg.ext_data_path
_REAL_DATA_DIR = cfg.DATA_DIR
# group_log resolves its directory through cfg.ext_data_path (imported late,
# like run_log does); group_context resolves data/groups/ through cfg.DATA_DIR.
cfg.ext_data_path = lambda *parts: TMP.joinpath(*parts)
cfg.DATA_DIR = TMP

from tubecli.core import group_context as gc
from tubecli.core import group_log

PASS = FAIL = 0

SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefg"
CRED_ID = "cred_deadbeef"
SECRET = "SieuBiMat123"
PROFILE_DIR = r"C:\Users\ADMIN\tubecli\data\extensions_data\browser\browser_profiles\tuan5\Default"
# Same path under a home directory with a SPACE in it. On Windows the drive
# letter is the only anchor the rule has, so a rule that cannot cross a space
# does not match this at all — and installs under "C:\Users\John Doe" are not
# exotic. Kept as its own constant so the assertion below cannot drift.
PROFILE_DIR_SPACED = r"C:\Users\John Doe\tubecli\data\extensions_data\browser\browser_profiles\tuan5\Default"


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def run(coro):
    return asyncio.run(coro)


def reset(group_id="g_log"):
    """Wipe one group's file AND the in-RAM seq, so a section starts at seq 1."""
    group_log.clear(group_id)
    group_log._seq.pop(group_id, None)
    group_log._lines.pop(group_id, None)


def raw_lines(group_id="g_log"):
    p = group_log._file_for(group_id)
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def server_source():
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "tubecli", "api", "server.py"), encoding="utf-8").read()


def main():
    try:
        # ── 1 ────────────────────────────────────────────────────────
        print("=== 1. SCRUB: nhung thu KHONG duoc len bang log ===")
        leaky = "\n".join([
            f'✅ Script "Dang video" finished on profile "tuan5".',
            f"password = {SECRET}",
            f"mat_khau = {SECRET}",
            f"sheet_url = https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit",
            f'"cred_id": "{CRED_ID}"',
            f"credential {CRED_ID} refreshed",
            f"profile_dir = {PROFILE_DIR}",
        ])
        out = group_log.scrub(leaky, 4000)
        one = out.replace("\n", " | ")
        check("mat khau bien mat", SECRET not in out, one)
        check("  ca dong tieng Viet 'mat_khau'", out.count("***") >= 2)
        check("sheet_id bien mat khoi URL", SHEET_ID not in out)
        check("  van con nhan ra la link Sheet", "/spreadsheets/d/***" in out)
        check("cred_id bien mat ca khi co nhan...", CRED_ID not in out)
        check("  ...lan khi dung mot minh giua cau", "credential ***" in out)
        check("duong dan tuyet doi cua profile bi cat dau",
              "C:\\Users\\ADMIN" not in out and "browser_profiles" in out)
        check("phan doc duoc cua cau tra loi van con", "Dang video" in out)

        # The `k = v` block above is the SCRIPT shape. A handler reply is JSON
        # far more often: GET /api/v1/browser/profiles/<name> answers with the
        # whole profile dict, and run_api pastes that into `detail`. Nothing
        # here carries an `=`, which is exactly what used to be required.
        js = json.dumps({"google_account": {"email": "chu@gmail.com", "password": SECRET,
                                            "recoveryEmail": "cuu@gmail.com",
                                            "twoFactorCodes": ["111 222", "333 444"]},
                         "profile_dir": PROFILE_DIR_SPACED,
                         "cookie": "SID=abc123def"}, ensure_ascii=False)
        out = group_log.scrub(js, 4000)
        check("mat khau dang JSON (khong co dau '=') van bi che", SECRET not in out, out)
        check("  ma 2FA, email khoi phuc, cookie cung the",
              "111 222" not in out and "cuu@gmail.com" not in out and "abc123def" not in out, out)
        check("  van con biet la profile nao", "tuan5" in out, out)
        out = group_log.scrub("Authorization: Bearer ya29.KhoaTruyCap0123456789", 400)
        check("header Authorization khong mang token len bang",
              "ya29.KhoaTruyCap0123456789" not in out and "Bearer" in out, out)

        out = group_log.scrub(f"user_data_dir = {PROFILE_DIR_SPACED}", 400)
        check("duong dan profile duoi thu muc nha CO DAU CACH van bi cat dau",
              "John Doe" not in out and "browser_profiles" in out, out)

        # The launcher argv shape run_log.redact was written for must still work
        # through this layer: group_log leans on it instead of re-implementing.
        argv = "node open.js --profile p1 --login-password Hunter2! --instance-id x"
        out = group_log.scrub(argv, 400)
        check("van tai su dung run_log.redact (argv launcher)",
              "Hunter2!" not in out and "--profile p1" in out, out)

        check("None/rong -> chuoi rong", group_log.scrub(None) == "" and group_log.scrub("   ") == "")
        check("cat dung DETAIL_CAP", len(group_log.scrub("x" * 5000, group_log.DETAIL_CAP)) == 400)
        check("hang so theo spec", group_log.MAX_LINES == 2000 and group_log.DETAIL_CAP == 400)

        # Fail closed: if the redactor cannot even be reached, nothing is kept.
        import tubecli.core.run_log as _rl
        _real_redact = _rl.redact
        _rl.redact = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
        check("redactor hong -> giu lai NOI DUNG, khong ghi tho",
              group_log.scrub(f"password = {SECRET}") == group_log.WITHHELD)
        _rl.redact = _real_redact

        # ── 2 ────────────────────────────────────────────────────────
        print("\n=== 2. TIEU DE: allowlist, khong phai thu model gui ===")
        t = group_log.summarise_action(
            "browser_open", {"action": "browser_open", "profile": "tuan5",
                             "url": "https://www.tiktok.com/upload?token=abc123#x"})
        check("dung mau trong spec", t == "browser_open tuan5 → www.tiktok.com/upload", t)
        check("  query string (cho token song) bi cat", "abc123" not in t)

        t = group_log.summarise_action(
            "script_run", {"action": "script_run", "script": "Dang video", "profile": "tuan5",
                           "variables": {"password": SECRET, "caption": "hi"}})
        check("script_run: ten script + profile chay", t == "script_run Dang video @tuan5", t)
        check("  BIEN SCRIPT khong bao gio vao tieu de", SECRET not in t and "caption" not in t, t)

        t = group_log.summarise_action("gsheet_append", {"sheet": "Ke hoach", "tab": "Log",
                                                         "rows": [["a", SECRET]]})
        check("gsheet_append: alias + tab, khong co du lieu dong", t == "gsheet_append Ke hoach → Log", t)
        t = group_log.summarise_action("xlsx_write", {"path": "/home/ubuntu/Downloads/plan.xlsx"})
        check("path chi con ten file", t == "xlsx_write plan.xlsx", t)
        check("action_data rac khong lam vo",
              group_log.summarise_action("", None) == "action"
              and group_log.summarise_action("x", []) == "x")

        # ── 3 ────────────────────────────────────────────────────────
        print("\n=== 3. APPEND / READ / since_seq ===")
        reset()
        check("nhom chua co log -> rong, next_seq 0",
              group_log.read("g_log") == {"lines": [], "next_seq": 0, "total": 0})
        group_log.append("g_log", "a1", "Bot Một", "browser_open", "browser_open tuan5",
                         detail="✅ opened", ok=True)
        group_log.append("g_log", "a1", "Bot Một", "gsheet_append", "gsheet_append KH",
                         detail="❌ refused", ok=False)
        got = group_log.read("g_log")
        check("2 dong, next_seq = seq cuoi, total = so dong",
              len(got["lines"]) == 2 and got["next_seq"] == 2 and got["total"] == 2, got)
        first = got["lines"][0]
        check("shape mot dong", sorted(first) == ["agent", "agent_id", "at", "detail", "kind", "ok", "seq", "title"],
              sorted(first))
        check("seq tang don dieu", [l["seq"] for l in got["lines"]] == [1, 2])
        check("ok dung", [l["ok"] for l in got["lines"]] == [True, False])
        check("agent giu ca ten co dau", first["agent"] == "Bot Một" and first["agent_id"] == "a1")
        check("at la ISO gio may (panel doi chieu dong ho trinh duyet)",
              re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$", first["at"]) is not None, first["at"])

        got = group_log.read("g_log", since_seq=1)
        check("since_seq chi tra dong moi", [l["seq"] for l in got["lines"]] == [2], got)
        got = group_log.read("g_log", since_seq=2)
        check("khong co gi moi -> rong nhung next_seq GIU nguyen (khong keo lui)",
              got["lines"] == [] and got["next_seq"] == 2, got)
        got = group_log.read("g_log", since_seq=99)
        check("since_seq vuot truoc -> khong phat lai lich su", got["lines"] == [], got)

        for i in range(10):
            group_log.append("g_log", "a1", "Bot", "chat", f"line {i}")
        got = group_log.read("g_log", limit=3)
        check("limit tra DUOI cung (panel muon cai moi nhat)",
              [l["title"] for l in got["lines"]] == ["line 7", "line 8", "line 9"], got)
        check("  next_seq theo dong cuoi da tra", got["next_seq"] == 12, got)
        check("limit bi ket vao [1, READ_LIMIT_MAX]",
              len(group_log.read("g_log", limit=-5)["lines"]) == 1
              and len(group_log.read("g_log", limit=10 ** 9)["lines"]) == 12
              and len(group_log.read("g_log", limit=0)["lines"]) == 12)   # 0 = "mac dinh"
        check("since_seq rac -> coi nhu 0",
              len(group_log.read("g_log", since_seq="x")["lines"]) == 12
              and len(group_log.read("g_log", since_seq=-5)["lines"]) == 12)

        # ── 4 ────────────────────────────────────────────────────────
        print("\n=== 4. group_id la TEN FILE: tu choi, khong lam sach ===")
        for bad in ("../auth", "a b", "a.b", "", "x" * 65, None, 5, "group/1", "g\\x"):
            group_log.append(bad, "a1", "Bot", "chat", "should not exist")
            check(f"append({bad!r}) khong ghi gi", group_log.read(bad) == {"lines": [], "next_seq": 0, "total": 0})
            check(f"clear({bad!r}) -> False", group_log.clear(bad) is False)
        stray = [p for p in TMP.rglob("*") if p.is_file() and "group_logs" not in str(p)]
        check("khong file nao bi ghi ngoai group_logs/", stray == [], [str(p) for p in stray])
        check("id hop le van chay", group_log.read("A-1_b") == {"lines": [], "next_seq": 0, "total": 0})

        # ── 5 ────────────────────────────────────────────────────────
        print("\n=== 5. CAT FILE: khong phinh vo han tren VPS ===")
        reset("g_trim")
        real_max = group_log.MAX_LINES
        group_log.MAX_LINES = 20            # cung logic, chay trong tich tac
        try:
            for i in range(30):
                group_log.append("g_trim", "a1", "Bot", "chat", f"n{i}")
            lines = raw_lines("g_trim")
            check("file bi cat khi vuot MAX_LINES", len(lines) <= 20, len(lines))
            rows = [json.loads(l) for l in lines]
            check("giu NUA SAU (cai moi nhat)", rows[-1]["title"] == "n29", rows[-1]["title"])
            check("seq KHONG bi dat lai sau khi cat -> since= cu van dung",
                  rows[-1]["seq"] == 30 and rows[0]["seq"] > 1, [rows[0]["seq"], rows[-1]["seq"]])
            got = group_log.read("g_trim", since_seq=28)
            check("  poll voi since= truoc luc cat van chay",
                  [l["title"] for l in got["lines"]] == ["n28", "n29"], got)
        finally:
            group_log.MAX_LINES = real_max

        # ── 6 ────────────────────────────────────────────────────────
        print("\n=== 6. CLEAR ===")
        check("clear nhom co log -> True", group_log.clear("g_trim") is True)
        check("  file bien mat", not group_log._file_for("g_trim").exists())
        check("  doc lai -> rong", group_log.read("g_trim") == {"lines": [], "next_seq": 0, "total": 0})
        check("clear lan 2 -> False (idempotent, khong nem loi)", group_log.clear("g_trim") is False)
        group_log.append("g_trim", "a1", "Bot", "chat", "sau khi xoa")
        after = group_log.read("g_trim")
        check("seq TIEP TUC sau clear (panel dang poll khong bi phat lai)",
              after["lines"][0]["seq"] > 30, after["lines"][0]["seq"])

        # ── 7 ────────────────────────────────────────────────────────
        print("\n=== 7. NHIEU LUONG GHI CUNG LUC ===")
        # Real writers: the FastAPI threadpool, the scheduler thread, and the
        # daemon threads extension handlers spawn — all on one group at once.
        reset("g_race")
        errors = []

        def writer(n):
            try:
                for i in range(25):
                    group_log.append("g_race", f"a{n}", f"Bot {n}", "chat", f"t{n}-{i}")
            except Exception as e:          # append must never raise, ever
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("khong luong nao nem loi", errors == [], errors)
        lines = raw_lines("g_race")
        check("khong mat dong nao", len(lines) == 200, len(lines))
        rows = [json.loads(l) for l in lines]      # a torn line would fail here
        seqs = sorted(r["seq"] for r in rows)
        check("seq duy nhat va lien tuc 1..200", seqs == list(range(1, 201)),
              f"{seqs[:3]}…{seqs[-3:]}")

        # A torn tail (killed mid-append) must be repaired, not fused.
        reset("g_torn")
        group_log.append("g_torn", "a1", "Bot", "chat", "truoc khi chet")
        with open(group_log._file_for("g_torn"), "a", encoding="utf-8") as f:
            f.write('{"seq": 2, "at": "x", "title": "nua dong')   # no newline
        group_log.append("g_torn", "a1", "Bot", "chat", "sau khi song lai")
        rows = [json.loads(l) for l in raw_lines("g_torn") if l.strip().endswith("}")]
        check("dong rach khong nuot dong moi",
              rows[-1]["title"] == "sau khi song lai", rows[-1] if rows else None)
        check("  doc van chay, chi bo dong hong", len(group_log.read("g_torn")["lines"]) == 2)

        # ...and the tail torn INSIDE a character, which is the common shape of
        # a real crash here: every line carries ✅/❌ and tieng Viet, so a random
        # cut lands mid-character most of the time. Probing that last byte
        # through the text decoder raised instead of repairing — append()
        # swallowed it, so the group's log silently froze for good while the
        # in-RAM seq kept counting.
        reset("g_torn2")
        group_log.append("g_torn2", "a1", "Bot", "chat", "truoc khi chet")
        with open(group_log._file_for("g_torn2"), "ab") as f:
            f.write('{"seq": 2, "at": "x", "title": "nua ky tu ✅'.encode("utf-8")[:-2])
        group_log.append("g_torn2", "a1", "Bot", "chat", "sau khi song lai")
        group_log.append("g_torn2", "a1", "Bot", "chat", "va van ghi tiep")
        rows = group_log.read("g_torn2")["lines"]
        check("duoi file rach GIUA mot ky tu utf-8 -> van ghi tiep duoc",
              [r["title"] for r in rows] == ["truoc khi chet", "sau khi song lai", "va van ghi tiep"],
              [r.get("title") for r in rows])
        check("  seq trong RAM khong chay xa file",
              rows[-1]["seq"] == group_log._seq.get("g_torn2"),
              (rows[-1]["seq"], group_log._seq.get("g_torn2")))

        # ── 8 ────────────────────────────────────────────────────────
        print("\n=== 8. ROUTES ===")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from tubecli.api.group_routes import router

        app_ = FastAPI()
        app_.include_router(router)
        c = TestClient(app_)

        reset("g_route")
        group_log.append("g_route", "a1", "Bot", "browser_open", "browser_open tuan5",
                         detail="✅ opened")
        r = c.get("/api/v1/groups/g_route/log")
        body = r.json()
        check("GET -> lines/next_seq/total", r.status_code == 200
              and sorted(body) == ["lines", "next_seq", "total"]
              and body["lines"][0]["title"] == "browser_open tuan5", r.text[:200])
        group_log.append("g_route", "a1", "Bot", "chat", "moi")
        r = c.get("/api/v1/groups/g_route/log", params={"since": body["next_seq"]})
        check("GET ?since= -> chi cai moi", [l["title"] for l in r.json()["lines"]] == ["moi"], r.text[:200])
        r = c.get("/api/v1/groups/g_route/log", params={"limit": 1})
        check("GET ?limit=", len(r.json()["lines"]) == 1)
        # A polling panel's first tick sends whatever it has, which on tick one
        # is often nothing at all. That must start the log, not 422 it.
        for junk in ("", "undefined", "null", "NaN", "abc"):
            r = c.get("/api/v1/groups/g_route/log", params={"since": junk, "limit": junk})
            check(f"GET ?since={junk!r} -> 200, bat dau tu dau (khong 422)",
                  r.status_code == 200 and len(r.json()["lines"]) == 2, r.text[:120])
        r = c.get("/api/v1/groups/g_khong_ton_tai/log")
        check("nhom chua co log -> 200 rong (khong 404)",
              r.status_code == 200 and r.json() == {"lines": [], "next_seq": 0, "total": 0}, r.text[:200])
        check("GET id xau -> 400", c.get("/api/v1/groups/a.b/log").status_code == 400
              and c.get("/api/v1/groups/a%20b/log").status_code == 400)
        r = c.delete("/api/v1/groups/g_route/log")
        check("DELETE -> ok", r.status_code == 200 and r.json()["ok"] is True, r.text[:200])
        check("  log da sach", c.get("/api/v1/groups/g_route/log").json()["lines"] == [])
        check("DELETE lan 2 van ok (idempotent)", c.delete("/api/v1/groups/g_route/log").json()["ok"] is True)
        check("DELETE id xau -> 400", c.delete("/api/v1/groups/a.b/log").status_code == 400)

        # ── 9 ────────────────────────────────────────────────────────
        print("\n=== 9. GUEST BI CHAN (doc tu server.py da landed) ===")
        # server.py is not imported: importing it runs discover_extensions(),
        # which can git-clone. The two gates are lifted out with ast instead —
        # what is tested is still the code that shipped.
        tree = ast.parse(server_source())
        fn = [n for n in tree.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_guest_allowed"]
        check("server.py co _guest_allowed", len(fn) == 1)
        # `Request` only has to exist: the annotation is evaluated when the
        # def runs, and nothing in the body touches the type.
        ns = {"_re": re, "Request": object}
        exec(compile(ast.Module(body=fn[:1], type_ignores=[]), "server.py", "exec"), ns)
        guest_allowed = ns["_guest_allowed"]

        class _Req:
            def __init__(self, path, method="GET"):
                self.url = types.SimpleNamespace(path=path)
                self.method = method
                self.query_params = {}

        # The widest scope a sharee can hold today — profiles, folders, files
        # and Drive all switched on — still must not reach the log.
        wide = {"profiles": ["tuan5"], "folders": ["/home/ubuntu"], "files": ["/home/ubuntu/a.xlsx"],
                "file_manager": {"drive": True, "drive_cred_ids": ["c1"]}}
        for path, method in (("/api/v1/groups/g_route/log", "GET"),
                             ("/api/v1/groups/g_route/log", "DELETE"),
                             ("/api/v1/groups/g_route/context", "GET"),
                             ("/api/v1/groups", "GET")):
            check(f"guest bi tu choi {method} {path}",
                  run(guest_allowed(_Req(path, method), wide)) is False)

        assign = [n for n in tree.body if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "_READ_KEY_PATHS" for t in n.targets)]
        check("server.py co _READ_KEY_PATHS", len(assign) == 1)
        ns2 = {"_re": re}
        exec(compile(ast.Module(body=assign[:1], type_ignores=[]), "server.py", "exec"), ns2)
        check("read-key (GET-only, cho scraped) khong mo duoc log",
              ns2["_READ_KEY_PATHS"].match("/api/v1/groups/g_route/log") is None)

        # The HTTP gate is only one door. The file itself sits inside the AI's
        # file sandbox (the whole data dir is an allowed root), and file_action
        # list/read are executed inline — so without this the agent reads every
        # OTHER group's log straight off disk.
        from tubecli.extensions.file_manager import file_service as fs_mod

        check("group_logs nam trong danh sach cam cua sandbox AI",
              os.path.join("extensions_data", "group_logs") in fs_mod.AI_PROTECTED_DATA_SUBDIRS,
              fs_mod.AI_PROTECTED_DATA_SUBDIRS)
        # Probed against the REAL data dir, not TMP: TMP lives under
        # ~/AppData/Local, which BLOCKED_PATHS already refuses — a probe there
        # would pass no matter what this list says.
        ai_fs = fs_mod.FileService(enforce_roots=True)
        real_data = os.path.abspath(os.environ.get("TUBECLI_DATA_DIR", "data"))
        for probe in (os.path.join(real_data, "extensions_data", "group_logs"),
                      os.path.join(real_data, "extensions_data", "group_logs", "g_khac.jsonl")):
            try:
                ai_fs.validate_path(probe)
                check(f"AI khong doc duoc {os.path.basename(probe)}", False, "khong bi chan")
            except ValueError as e:
                check(f"AI khong doc duoc {os.path.basename(probe)}",
                      "bảo mật" in str(e), str(e)[:120])
        # Secrets live in that same sandbox. Verified before this guard existed:
        # an agent could read data/extensions_data/capcut_tts/.enc_key AND
        # accounts.json — the AES key and the ciphertext it opens — which made
        # that extension's encryption decorative; cloud_api_keys.json is not
        # encrypted at all, so every provider key was one file_action away.
        for probe in (os.path.join(real_data, "cloud_api_keys.json"),
                      os.path.join(real_data, "extensions_data", "capcut_tts"),
                      os.path.join(real_data, "extensions_data", "capcut_tts", ".enc_key"),
                      os.path.join(real_data, "extensions_data", "capcut_tts", "accounts.json"),
                      os.path.join(real_data, "extensions_data", "database_manager")):
            try:
                ai_fs.validate_path(probe)
                check(f"AI khong doc duoc bi mat {os.path.basename(probe)}", False, "khong bi chan")
            except ValueError as e:
                check(f"AI khong doc duoc bi mat {os.path.basename(probe)}",
                      "bảo mật" in str(e), str(e)[:120])

        # ...and the control: a sibling folder in the same data dir is still
        # reachable, so what refused above was this rule and not the allowlist.
        try:
            ai_fs.validate_path(os.path.join(real_data, "extensions_data", "web_crawler"))
            check("  thu muc extension khac trong data van doc duoc", True)
        except ValueError as e:
            check("  thu muc extension khac trong data van doc duoc", False, str(e)[:120])

        # ...and run_api is a third door: it calls the internal API over
        # loopback, which is auth-exempt, so it reaches owner-only routes with
        # the server's own privileges. No HTTP is attempted below — the refusal
        # happens before httpx.
        from tubecli.core import telegram_actions as ta

        # run_api now sits behind the technician_mode switch and is OFF by
        # default (spec G0 section 9), so a bare call is refused for a reason
        # that has nothing to do with /groups. Assert that first, then turn the
        # switch ON: this block exists to prove the GROUP gate holds, and with
        # the switch off it would pass whatever that gate did.
        ta.SETTINGS_FILE = TMP / "global_settings.json"
        off = run(ta.exec_run_api({"method": "GET", "endpoint": "/api/v1/groups"}))
        check("run_api TAT theo mac dinh (technician_mode)",
              off.startswith("❌") and "technician_mode" in off, off[:100])
        ta.SETTINGS_FILE.write_text(json.dumps({"technician_mode": True}),
                                    encoding="utf-8")
        try:
            for ep in ("/api/v1/groups/g_khac/log", "/api/v1/groups",
                       "api/v1/groups/g/context"):
                r = run(ta.exec_run_api({"method": "GET", "endpoint": ep}))
                check(f"run_api {ep} bi tu choi", r.startswith("❌"), r[:120])
                check(f"  vi la API nhom, khong phai vi cong tac",
                      "nhóm" in r, r[:120])
        finally:
            # Tra lai mac dinh TAT cho phan con lai cua test.
            ta.SETTINGS_FILE.unlink()
        check("  route khac khong bi cam nham",
              ta._GROUP_API_RE.match("/api/v1/browser/profiles/tuan5") is None
              and ta._GROUP_API_RE.match("/api/v1/groupsomething") is None)

        # ── 10 ───────────────────────────────────────────────────────
        print("\n=== 10. XUYEN SUOT: action bi chan + action thanh cong ===")
        from tubecli.core.telegram_actions import handle_extension_action
        from tubecli.core.extension_manager import extension_manager
        from tubecli.extensions.auth_manager.extension import AuthManagerExtension

        gc.save("g_e2e", {"label": "Studio", "agents": ["a1"],
                          "sheets": [{"alias": "Ke hoach tuan", "sheet_id": SHEET_ID,
                                      "cred_id": CRED_ID, "tabs": ["Log"], "access": "read"}]})
        gc.save("g_other", {"label": "Rieng", "agents": ["a1"]})
        reset("g_e2e")
        reset("g_other")

        async def fake_script_run(action_data, context):
            # The shape group_scripts.script_run really returns: a success line
            # plus the run's output variables, one `name = value` per line.
            return ("✅ Script \"Dang video\" finished on profile \"tuan5\".\n"
                    f"password = {SECRET}\n"
                    f"sheet = https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit\n"
                    f"cred = {CRED_ID}\n"
                    f"user_data_dir = {PROFILE_DIR}")

        actions = {k: {"handler": v} for k, v in AuthManagerExtension().get_telegram_actions().items()}
        actions["script_run"] = {"handler": fake_script_run}
        _real_all = extension_manager.get_all_telegram_actions
        extension_manager.get_all_telegram_actions = lambda: actions
        try:
            agent = {"id": "a1", "name": "Bot Một"}
            ctx = {"source": "web_chat", "group_ids": ["g_e2e"], "group_id": "g_e2e"}

            # (a) refused — the REAL gsheet_append gate, no Google involved:
            # the sheet is shared read-only and append needs "append".
            blocked = run(handle_extension_action(
                '```json\n{"action":"gsheet_append","sheet":"Ke hoach tuan",'
                '"tab":"Log","rows":[["x"]]}\n```', agent, ctx))
            check("action bi chan tra ve tu choi that", blocked.startswith("❌")
                  and 'needs "append"' in blocked, blocked[:160])

            # (b) allowed
            done = run(handle_extension_action(
                '```json\n{"action":"script_run","script":"Dang video","profile":"tuan5",'
                f'"variables":{{"password":"{SECRET}"}}}}\n```', agent, ctx))
            check("action chay duoc tra ve thanh cong", done.startswith("✅"), done[:80])

            rows = group_log.read("g_e2e")["lines"]
            check("ca hai vao dung nhom", len(rows) == 2, rows)
            check("  nhom khac cua chu KHONG dinh gi", group_log.read("g_other")["lines"] == [])
            check("ok doc dung dau ❌", [r["ok"] for r in rows] == [False, True], rows)
            check("kind = ten action",
                  [r["kind"] for r in rows] == ["gsheet_append", "script_run"], rows)
            check("agent duoc ghi ten", all(r["agent"] == "Bot Một" for r in rows))
            check("tieu de doc duoc",
                  rows[0]["title"] == "gsheet_append Ke hoach tuan → Log"
                  and rows[1]["title"] == "script_run Dang video @tuan5",
                  [r["title"] for r in rows])

            blob = json.dumps(rows, ensure_ascii=False)
            check("KHONG co mat khau trong log", SECRET not in blob)
            check("KHONG co sheet_id trong log", SHEET_ID not in blob)
            check("KHONG co cred_id trong log", CRED_ID not in blob)
            check("KHONG co duong dan tuyet doi cua profile", "C:\\\\Users\\\\ADMIN" not in blob)
            check("van con thong tin huu ich", "Ke hoach tuan" in blob and "Dang video" in blob)

            # An older caller that never decided the groups writes nothing:
            # guessing the union here would narrate one group's work into
            # another group's panel.
            reset("g_e2e")
            run(handle_extension_action(
                '```json\n{"action":"script_run","script":"X","profile":"tuan5"}\n```',
                agent, {"source": "telegram"}))
            check("vang group_ids -> khong ghi (khong doan nhom)",
                  group_log.read("g_e2e")["lines"] == [])
            run(handle_extension_action(
                '```json\n{"action":"script_run","script":"X","profile":"tuan5"}\n```',
                agent, {"source": "web_chat", "group_ids": []}))
            check("group_ids rong -> khong ghi", group_log.read("g_e2e")["lines"] == [])

            # No action in the reply at all: nothing ran, so nothing is logged.
            plain = run(handle_extension_action("chi la mot cau tra loi", agent, ctx))
            check("khong co action -> khong ghi dong nao",
                  plain == "chi la mot cau tra loi" and group_log.read("g_e2e")["lines"] == [])

            # And the log must never be able to break the action it logs.
            _real_append = group_log.append
            group_log.append = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
            try:
                still = run(handle_extension_action(
                    '```json\n{"action":"script_run","script":"X","profile":"tuan5"}\n```',
                    agent, ctx))
                check("log hong -> action VAN tra ket qua", still.startswith("✅"), still[:60])
            finally:
                group_log.append = _real_append
        finally:
            extension_manager.get_all_telegram_actions = _real_all

        print("\n=== 11. PIPELINE / SERVER: cac diem moc da noi day ===")
        import inspect
        from tubecli.extensions.chat import pipeline

        check("pipeline co _log_group_activity", callable(getattr(pipeline, "_log_group_activity", None)))
        sig = inspect.signature(pipeline._log_group_activity)
        check("  (groups, agent_dict, message, reply_text, ok)",
              list(sig.parameters) == ["groups", "agent_dict", "message", "reply_text", "ok"], list(sig.parameters))
        reset("g_e2e")
        pipeline._log_group_activity(gc.effective_groups("a1", "g_e2e"), {"id": "a1", "name": "Bot"},
                                     "them 3 dong vao Ke hoach", "✅ xong")
        rows = group_log.read("g_e2e")["lines"]
        check("luot chat len bang log", len(rows) == 1 and rows[0]["kind"] == "chat"
              and rows[0]["title"] == "them 3 dong vao Ke hoach", rows)
        check("  agent ngoai nhom -> khong co nhom -> khong ghi",
              pipeline._log_group_activity(gc.effective_groups("nobody"), {"id": "x"}, "hi", "ok") is None
              and len(group_log.read("g_e2e")["lines"]) == 1)
        check("  loi ben trong khong nem ra ngoai luot chat",
              pipeline._log_group_activity([{"group_id": "g_e2e"}], None, None, None) is None)

        src = server_source()
        check("run_agent_routine ghi log nhom (bat dau + ket thuc)",
              src.count("_group_log_routine(") >= 4, src.count("_group_log_routine("))
        fn = [n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "_group_log_routine"]
        check("server.py co _group_log_routine", len(fn) == 1)
        ns3 = {}
        exec(compile(ast.Module(body=fn[:1], type_ignores=[]), "server.py", "exec"), ns3)
        reset("g_e2e")
        ns3["_group_log_routine"](gc.effective_groups("a1", "g_e2e"),
                                  types.SimpleNamespace(id="a1", name="Bot"),
                                  "schedule tuan5 → pho ha noi", detail="Search for 'pho ha noi'")
        rows = group_log.read("g_e2e")["lines"]
        check("luot chay theo lich len bang log",
              len(rows) == 1 and rows[0]["kind"] == "schedule" and rows[0]["ok"] is True, rows)
        check("  khong co nhom -> khong ghi",
              ns3["_group_log_routine"]([], types.SimpleNamespace(id="a1", name="B"), "x") is None)
        check("  agent rac khong lam vo lich",
              ns3["_group_log_routine"]([{"group_id": "g_e2e"}], None, "x") is None)

        # run_api KHÔNG được chạm API nhóm, kể cả khi viết đường dẫn vòng vèo:
        # cổng so chuỗi thẳng để lọt //api/…, /./api/…, /api/v1/agents/../groups/…
        # và %61pi, trong khi uvicorn vẫn đưa chúng tới đúng route.
        print("=== run_api: cong chan API nhom ===")
        from tubecli.core.telegram_actions import _canon_endpoint, _GROUP_API_RE
        for ep in ("/api/v1/groups/g1/log", "//api/v1/groups/g1/log",
                   "/./api/v1/groups/g1/log", "/api/v1/../v1/groups/g1/log",
                   "/api/v1//groups/g1/log", "/api/v1/agents/../groups/g1/log",
                   "/%61pi/v1/groups/g1/log", "/%2561pi/v1/groups/g1/log",
                   "/api/v1/groups%2Fg1/log", "/API/V1/GROUPS/g1/log",
                   "http://127.0.0.1:5295/api/v1/groups/g1/context"):
            check(f"chặn {ep}", bool(_GROUP_API_RE.match(_canon_endpoint(ep))), _canon_endpoint(ep))
        for ep in ("/api/v1/agents", "/api/v1/browser/status", "/api/v1/groupsomething",
                   "/api/v1/skills"):
            check(f"cho qua {ep}", not _GROUP_API_RE.match(_canon_endpoint(ep)), _canon_endpoint(ep))
    finally:
        cfg.ext_data_path = _REAL_EXT_DATA_PATH
        cfg.DATA_DIR = _REAL_DATA_DIR
        shutil.rmtree(TMP, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
