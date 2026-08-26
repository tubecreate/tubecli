"""A script run must not leave a password on the owner's disk — and a function
name must not be a path.

Run:  python tests/exec_secrets_test.py     (exit 0 = pass)

Nothing here touches the real data dir, no browser is started and no server is
listening: the SQLite file is a temp file, the routes are called as plain
coroutines, and the runner's own source text is evaluated in a throwaway node
process.

WHAT THIS LOCKS IN

1. THE TABLE IS NOT A PASSWORD STORE (spec §3).
   POST /api/v1/scripts/{id}/run fills `variables` from the profile's saved
   account — {service}_email/_password/_recovery/_2fa — and create_execution
   used to json.dumps that dict straight into executions.variables, which
   GET /executions/history then read back. Masked now on the way in, on the way
   out, and once over the rows that were written before this code existed.
   Masked, not deleted: which inputs a run was given is the owner's history;
   what they WERE is the leak.

2. THE FILTER IS THE ONE group_log ALREADY HAD (spec §3).
   tubecli/core/secret_names.py holds the names; group_log's redactor and this
   table's filter both import them. A second copy is the one that forgets.

3. IT FAILS CLOSED.
   No shared name list (an extension hot-patched onto an older core — a real
   deployment here), a column that does not parse, the filter itself raising:
   every one of those keeps NOTHING rather than keeping the password. And the
   read path never trusts the column, because closing the HTTP door while
   list_executions still hands plaintext to in-process callers is not a fix.

4. A FUNCTION NAME IS A NAME (spec §5).
   The call_function step builds scripts_dir/<slug>.json and then EXECUTES the
   steps inside it, and the slug goes through interpolate() — so it can come
   from a variable the model chose. Three independent layers, one test each:
     (a) group_scripts.filter_variables judges function_slug/slug as a PATH, so
         a value carrying a separator or ".." never reaches the runner;
     (b) the runner resolves and then checks containment in the store
         directory, because path.join() folds ".." away in silence;
     (c) the runner will only load a name that is IN the store — which is what
         catches "a/../real_name", a value that survives (b) intact.
"""
import asyncio
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BS_DIR = os.path.join(REPO, "tubecli", "extensions", "browser_scripts")
DB_FILE = os.path.join(BS_DIR, "db", "database.py")
ROUTES_FILE = os.path.join(BS_DIR, "script_routes.py")
RUNNER_FILE = os.path.join(BS_DIR, "runner", "script_runner.js")

PASSWORD = "Sieu!MatKhau#2026"
TWOFA = "111 222 333"
RECOVERY = "cuu@gmail.com"

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def load_by_path(name, path):
    """The way script_routes loads these files in production: by path, no package."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def raw_column(db_path, table="executions", column="variables"):
    conn = sqlite3.connect(db_path)
    try:
        return "\n".join(str(r[0]) for r in
                         conn.execute(f"SELECT {column} FROM {table}").fetchall())
    finally:
        conn.close()


def leaky_variables():
    """Exactly what run_script injects, plus one honest input."""
    return {
        "google_email": "chu@gmail.com",
        "google_password": PASSWORD,
        "google_recovery": RECOVERY,
        "google_2fa": TWOFA,
        "caption": "video moi",
        "nested": {"login": {"password": PASSWORD}},
    }


# ── 1. The shared name list ──────────────────────────────────────────

def part_shared_list():
    print("\n=== 1. MOT danh sach ten, dung chung voi group_log ===")
    from tubecli.core import secret_names
    from tubecli.core import group_log

    check("group_log dung dung danh sach do",
          secret_names.SECRET_NAME_ALT in group_log._ID_FIELD_RE.pattern
          and secret_names.SECRET_NAME_ALT in group_log._SECRET_KV_RE.pattern)
    for name in ("google_password", "loginPwd", "twoFactorCodes", "recoveryEmail",
                 "google_2fa", "mat_khau", "access_token", "sheet_id", "totp"):
        check(f"  '{name}' la ten bi mat", secret_names.is_secret_name(name))
    for name in ("caption", "video_title", "url", "profile", "so_luong"):
        check(f"  '{name}' KHONG bi che nham", not secret_names.is_secret_name(name))

    out = secret_names.scrub_mapping(leaky_variables())
    check("gia tri bi che, KHOA thi con",
          out["google_password"] == "***" and out["google_2fa"] == "***"
          and out["google_recovery"] == "***" and "google_password" in out, str(out))
    check("bien that van doc duoc", out["caption"] == "video moi")
    check("mat khau nam SAU mot lop cung bi che",
          out["nested"]["login"]["password"] == "***", str(out["nested"]))
    class Unreadable:
        def __str__(self):
            raise RuntimeError("khong doc duoc")

    check("ten khoa doc khong duoc -> coi nhu bi mat", secret_names.is_secret_name(Unreadable()))
    masked = secret_names.scrub_mapping({Unreadable(): PASSWORD})
    check("  va gia tri duoi no bi che", list(masked.values()) == ["***"], str(masked))
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": PASSWORD}}}}}}}}
    check("sau qua sau thi cat ca nhanh, khong bo qua",
          PASSWORD not in json.dumps(secret_names.scrub_mapping(deep)))


# ── 2. executions.variables ──────────────────────────────────────────

def part_db(tmp):
    print("\n=== 2. Bang executions khong con la kho mat khau ===")
    db_mod = load_by_path("script_studio_db_test", DB_FILE)
    db_path = os.path.join(tmp, "scripts.db")
    db = db_mod.ScriptDatabase(db_path)

    exec_id = db.create_execution("s1", "profile_1", leaky_variables())
    stored = raw_column(db_path)
    check("mat khau khong con tren dia",
          PASSWORD not in stored and TWOFA not in stored and RECOVERY not in stored, stored)
    check("  van biet luot chay nhan nhung bien nao",
          "google_password" in stored and "***" in stored, stored)
    check("  bien vo hai khong bi xoa", "video moi" in stored)

    rows = db.list_executions()
    check("doc lai qua list_executions cung khong thay",
          rows and rows[0]["variables"]["google_password"] == "***"
          and rows[0]["variables"]["caption"] == "video moi", str(rows[:1]))
    one = db.list_executions("s1", limit=1)
    check("  duong /status (list_executions co script_id) cung the",
          one and one[0]["variables"]["google_2fa"] == "***", str(one[:1]))

    db.update_execution(exec_id, variables={"google_password": PASSWORD, "caption": "x"})
    stored = raw_column(db_path)
    check("update_execution cung che (cua chua ai dung, nen phai dong truoc)",
          PASSWORD not in stored, stored)

    # `result` la gio bien runner tra ve — cung mot loai du lieu, cung mot cua.
    db.update_execution(exec_id, result={"google_password": PASSWORD, "out": "ok"})
    got = db.list_executions()[0]["result"]
    check("cot result cung khong tra ve mat khau",
          got["google_password"] == "***" and got["out"] == "ok", str(got))
    db.update_execution(exec_id, result="mot chuoi thuong")
    check("  result khong phai mapping thi tra nguyen ven",
          db.list_executions()[0]["result"] == "mot chuoi thuong")

    # scripts.variables is the AUTHOR's declared input list, defaults included.
    # Masking it would write "***" back into the script the next time Script
    # Studio saved it — so the executions filter must not reach that table.
    db.create_script(name="Dang video", variables=[{"name": "password", "default": "giu_nguyen"}])
    scripts = db.list_scripts()
    check("bien KHAI BAO cua script khong bi dong cham (khong pha Script Studio)",
          scripts and scripts[0]["variables"][0]["default"] == "giu_nguyen", str(scripts[:1]))
    return db_mod


# ── 3. Migration over rows written before the patch ──────────────────

def part_migration(tmp, db_mod):
    print("\n=== 3. Don not nhung dong da ghi truoc khi va ===")
    db_path = os.path.join(tmp, "old.db")
    db = db_mod.ScriptDatabase(db_path)
    # A row exactly as the unpatched create_execution wrote it.
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO executions (script_id, profile_name, status, variables) "
                 "VALUES ('s9', 'p9', 'success', ?)",
                 (json.dumps(leaky_variables(), ensure_ascii=False),))
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    check("dung la dong cu con nguyen van mat khau", PASSWORD in raw_column(db_path))

    cleaned = db.scrub_stored_variables()
    stored = raw_column(db_path)
    check("quet mot lan -> dong cu sach", cleaned == 1 and PASSWORD not in stored,
          f"cleaned={cleaned}")
    check("  KHONG xoa dong (lich su cua chu van con)",
          len(raw_column(db_path).splitlines()) == 1 and "google_password" in stored)
    check("  chay lai thi khong lam gi nua (user_version)", db.scrub_stored_variables() == 0)
    check("  ep chay lai duoc", db.scrub_stored_variables(force=True) == 0)

    # ...and the same sweep is what a server start does, not a CLI the owner
    # has to remember.
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO executions (script_id, profile_name, status, variables) "
                 "VALUES ('s10', 'p10', 'success', ?)",
                 (json.dumps({"google_password": PASSWORD}, ensure_ascii=False),))
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    db_mod.ScriptDatabase(db_path)          # mo lai = khoi dong lai
    check("mo DB len la quet (khong can lenh tay)", PASSWORD not in raw_column(db_path))


# ── 4. Fail closed ───────────────────────────────────────────────────

def part_fail_closed(tmp, db_mod):
    print("\n=== 4. Khong loc duoc thi khong giu ===")
    saved = db_mod._scrub_mapping
    db_path = os.path.join(tmp, "nolist.db")
    db = db_mod.ScriptDatabase(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO executions (script_id, status, variables) VALUES ('s1','ok',?)",
                 (json.dumps({"google_password": PASSWORD}, ensure_ascii=False),))
    conn.commit()
    conn.close()
    try:
        db_mod._scrub_mapping = None        # core cu, chua co secret_names
        check("khong co danh sach -> khong ghi gi", db_mod.scrub_variables({"caption": "hi"}) == {})
        db.create_execution("s2", "p", leaky_variables())
        check("  luot chay moi khong de lai gi", PASSWORD not in raw_column(db_path).split("\n")[-1])
        check("  doc lai cung khong tra ve",
              all(r["variables"] == {} for r in db.list_executions()))
        check("  KHONG xoa trang dong cu (mat du lieu khong phai cach va ro ri)",
              db.scrub_stored_variables(force=True) == 0
              and PASSWORD in raw_column(db_path))
    finally:
        db_mod._scrub_mapping = saved

    check("cot khong phai JSON -> khong tin", db_mod.scrub_variables("khong-phai-json") == {})
    check("None -> rong", db_mod.scrub_variables(None) == {})

    def boom(*a, **k):
        raise RuntimeError("boom")
    db_mod._scrub_mapping = boom
    try:
        check("bo loc nem loi -> bo ca gio", db_mod.scrub_variables(leaky_variables()) == {})
    finally:
        db_mod._scrub_mapping = saved


# ── 5. The HTTP way out ──────────────────────────────────────────────

def part_routes(tmp, db_mod):
    print("\n=== 5. Endpoint tra ve khong mang mat khau ===")
    routes = load_by_path("script_routes_test", ROUTES_FILE)
    db_path = os.path.join(tmp, "routes.db")
    db_mod.ScriptDatabase.get_instance(db_path)     # dat singleton cho _db()
    routes._db_mod = db_mod
    db = routes._db()
    db.create_execution("s1", "p1", leaky_variables())

    payload = asyncio.run(routes.execution_history(limit=10))
    text = json.dumps(payload, ensure_ascii=False)
    check("/executions/history khong tra mat khau", PASSWORD not in text, text[:200])
    check("  van tra ve luot chay do", "google_password" in text and "video moi" in text)
    status = asyncio.run(routes.get_execution_status("s1"))
    check("/{id}/status cung the", PASSWORD not in json.dumps(status, ensure_ascii=False))

    # The hot-patch bundle carries script_routes.py but NOT db/database.py, so a
    # server can be running a database.py that never learned to scrub. The route
    # must still not hand the password out.
    leaked = {"id": 1, "script_id": "s1", "variables": dict(leaky_variables())}
    saved_list = db.list_executions
    db.list_executions = lambda *a, **k: [dict(leaked)]
    try:
        payload = asyncio.run(routes.execution_history(limit=10))
        check("database.py doi cu -> route van loc",
              PASSWORD not in json.dumps(payload, ensure_ascii=False), str(payload)[:200])
        saved_scrub = db_mod.scrub_variables
        db_mod.scrub_variables = None       # khong goi duoc bo loc
        try:
            payload = asyncio.run(routes.execution_history(limit=10))
            check("  khong goi duoc bo loc -> tra rong, khong tra tho",
                  PASSWORD not in json.dumps(payload, ensure_ascii=False))
        finally:
            db_mod.scrub_variables = saved_scrub
    finally:
        db.list_executions = saved_list


# ── 6. call_function, layer (a): the variable never leaves Python ────

def part_slug_variable():
    print("\n=== 6. call_function lop (a): bien khong mang duoc duong dan ===")
    from tubecli.extensions.browser_scripts import group_scripts as gs

    check("function_slug/slug duoc coi la DUONG DAN",
          gs._context_of("function_slug") == "path" and gs._context_of("slug") == "path")

    script = {"steps": [{"type": "call_function",
                         "params": {"function_slug": "{{fn}}", "inputs": {"x": "{{who}}"}}},
                        {"type": "call_function", "params": {"slug": "{{other}}"}}],
              "variables": [{"name": "who"}]}
    inputs = gs.script_inputs(script)
    check("  duoc thu nhan la input cua script",
          inputs.get("fn") == {"path"} and inputs.get("other") == {"path"}, str(inputs))

    for bad in ("../../../../etc/passwd", "..\\..\\Windows\\win", "/etc/passwd",
                "C:/Windows/win", "a/../gmail_login", "~/secrets", "sub/evil"):
        kept, dropped = gs.filter_variables(script, {"fn": bad})
        check(f"  tu choi '{bad}'", "fn" not in kept and "fn" in dropped, str(kept))
    kept, dropped = gs.filter_variables(script, {"fn": "gmail_login", "who": "chu"})
    check("  ten that van chay duoc", kept.get("fn") == "gmail_login" and kept.get("who") == "chu",
          str(kept))


# ── 7. call_function, layers (b) and (c): inside the runner ──────────

def node_available():
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=20)
        return True
    except Exception:
        return False


HARNESS = r"""
// Danh gia CHINH doan ma cua script_runner.js, khong chep lai.
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(process.argv[2], 'utf-8');
const root = process.argv[3];
const a = src.indexOf('let _fnAllowlist = null;');
const b = src.indexOf('const sleep = ms => {');
if (a < 0 || b < 0 || b <= a) {
    console.log(JSON.stringify({ error: 'khong tim thay resolveFunctionScript' }));
    process.exit(2);
}
const block = src.slice(a, b);
function fresh(execData) {
    const make = new Function('fs', 'path', 'execData',
        block + '\nreturn { resolveFunctionScript };');
    return make(fs, path, execData);
}
const out = {};
function ask(label, execData, slug) {
    const r = fresh(execData).resolveFunctionScript(root, slug);
    out[label] = { ok: !!r.path, p: r.path || '', reason: r.reason || '' };
}
const byDir = {};                                   // khong co function_slugs
const byList = { function_slugs: ['gmail_login'] };  // co danh sach tu kho

ask('good_dir', byDir, 'gmail_login');
ask('good_list', byList, 'gmail_login');
ask('up', byDir, '../outside');
ask('up_win', byDir, '..\\outside');
ask('deep_up', byDir, '../../../../../../etc/passwd');
ask('abs_posix', byDir, '/etc/passwd');
ask('abs_win', byDir, 'C:\\Windows\\win.ini');
ask('subdir', byDir, 'sub/nested');
ask('folded', byDir, 'sub/../gmail_login');
ask('not_in_list', byList, 'other_fn');
ask('listed_but_missing', { function_slugs: ['ghost'] }, 'ghost');
ask('empty', byDir, '');
ask('dotdot_only', byDir, '..');
ask('nul', byDir, 'gmail\u0000login');
console.log(JSON.stringify(out));
"""


def part_runner(tmp):
    print("\n=== 7. call_function lop (b)+(c): trong runner ===")
    if not node_available():
        print("[SKIP] khong co node -> khong kiem duoc runner")
        return
    root = os.path.join(tmp, "store")
    os.makedirs(os.path.join(root, "sub"), exist_ok=True)
    for rel in ("gmail_login.json", "other_fn.json", os.path.join("sub", "nested.json")):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            json.dump({"steps": []}, f)
    with open(os.path.join(tmp, "outside.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": [{"type": "evaluate", "params": {"code": "1"}}]}, f)

    harness = os.path.join(tmp, "harness.js")
    with open(harness, "w", encoding="utf-8") as f:
        f.write(HARNESS)
    proc = subprocess.run(["node", harness, RUNNER_FILE, root],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        check("harness chay duoc", False, (proc.stdout + proc.stderr)[-400:])
        return
    r = json.loads(proc.stdout.strip().splitlines()[-1])
    if "error" in r:
        check("tim thay resolveFunctionScript trong runner", False, r["error"])
        return

    check("ten that (tu thu muc kho) van nap duoc",
          r["good_dir"]["ok"] and r["good_dir"]["p"].endswith("gmail_login.json"), str(r["good_dir"]))
    check("ten that (tu danh sach script_routes gui) van nap duoc", r["good_list"]["ok"])
    for label, why in (("up", "leo ra ngoai kho"),
                       ("up_win", "leo ra ngoai kho kieu Windows"),
                       ("deep_up", "leo nhieu tang"),
                       ("abs_posix", "duong dan tuyet doi POSIX"),
                       ("abs_win", "duong dan tuyet doi Windows"),
                       ("subdir", "thu muc con"),
                       ("empty", "ten rong"),
                       ("dotdot_only", "chi mot '..'"),
                       ("nul", "co ky tu NUL")):
        check(f"  tu choi: {why}", not r[label]["ok"], str(r[label]))
    check("  '..' bi path.resolve rut gon van bi chan — boi ALLOWLIST (lop c)",
          not r["folded"]["ok"] and "store" in r["folded"]["reason"], str(r["folded"]))
    check("  co tren dia nhung khong co trong danh sach kho -> tu choi",
          not r["not_in_list"]["ok"], str(r["not_in_list"]))
    check("  co trong danh sach nhung khong co file -> tu choi",
          not r["listed_but_missing"]["ok"], str(r["listed_but_missing"]))
    check("  loi tu choi khong in duong dan tuyet doi ra log",
          all(not r[k]["p"] for k in r if not r[k]["ok"]))


# ── 8. The allowlist script_routes hands down ────────────────────────

def part_allowlist_source(tmp):
    print("\n=== 8. Danh sach kho ma script_routes gui xuong runner ===")
    routes = load_by_path("script_routes_allow_test", ROUTES_FILE)
    root = os.path.join(tmp, "store")

    class FakeStore:
        def list_scripts(self):
            return [{"slug": "from_store"}, {"slug": ""}, None]

    routes._store = lambda: FakeStore()
    names = routes._function_slugs(root)
    check("gop ca thu muc runner doc va slug ScriptStore biet",
          "gmail_login" in names and "from_store" in names, str(names))
    check("  khong co ten rong", "" not in names)
    routes._store = lambda: (_ for _ in ()).throw(RuntimeError("no store"))
    names = routes._function_slugs(root)
    check("  kho hong -> van con danh sach tu thu muc, khong sap",
          "gmail_login" in names, str(names))
    names = routes._function_slugs(os.path.join(tmp, "khong_ton_tai"))
    check("  thu muc khong co -> danh sach rong, khong nem loi", names == [])

    src = open(ROUTES_FILE, encoding="utf-8").read()
    check("ca hai duong chay deu gui danh sach xuong runner",
          src.count('"function_slugs": _function_slugs(') == 2)


# ── 8. The hot-patch bundle has to carry what the patch NEEDS ────────

def part_patch_bundle():
    import io

    print("\n=== 8. Goi hot-patch mang du ca phu thuoc ===")
    # Máy chỉ hot-patch (không `git pull`) là chế độ triển khai mà gói này tồn
    # tại để phục vụ. bs/database.py import tubecli.core.secret_names — một
    # module MỚI, chỉ có trong git. Thiếu nó thì _scrub_mapping = None và cả hai
    # đầu đều tệ: mọi lần ghi mới lưu `{}` (chủ mất sạch lịch sử "lượt chạy này
    # nhận biến gì"), còn các dòng CŨ đang giữ mật khẩu thì không được quét —
    # ngay sau khi khách vừa được báo "vá bảo mật: OK".
    patch_dir = os.path.join(os.path.dirname(REPO), "tubecli-cloud", "public", "patch")
    if not os.path.isdir(patch_dir):
        check("(bo qua) khong thay repo cloud canh ben", True, patch_dir)
        return

    def same(a, b):
        return (io.open(a, encoding="utf-8", errors="replace").read()
                == io.open(b, encoding="utf-8", errors="replace").read())

    mirrors = [
        (DB_FILE, os.path.join(patch_dir, "bs", "database.py")),
        (os.path.join(REPO, "tubecli", "core", "secret_names.py"),
         os.path.join(patch_dir, "secret_names.py")),
        (os.path.join(BS_DIR, "group_scripts.py"), os.path.join(patch_dir, "bs", "group_scripts.py")),
        (ROUTES_FILE, os.path.join(patch_dir, "bs", "script_routes.py")),
        (os.path.join(REPO, "tubecli", "extensions", "file_manager", "file_service.py"),
         os.path.join(patch_dir, "fm", "file_service.py")),
    ]
    for src, mirror in mirrors:
        name = os.path.basename(mirror)
        check(f"{name}: ban mirror ton tai", os.path.exists(mirror), mirror)
        if os.path.exists(mirror):
            check(f"{name}: mirror trung khop repo", same(src, mirror))

    sp = io.open(os.path.join(patch_dir, "server-patch.py"),
                 encoding="utf-8", errors="replace").read()
    check("server-patch.py co tai secret_names.py", "secret_names.py" in sp)
    check("  va ghi vao tubecli/core/, khong phai vao extension",
          "os.path.join(PKG, 'core', 'secret_names.py')" in sp)
    check("  ghi CHUNG khoi staged voi database.py (mot khoi, khong nua voi)",
          sp.index("secret_names.py") > sp.index("BS_FILES = [")
          and sp.index("secret_names.py") < sp.index("staged, aborted = {}, None"))
    check("  duoc phep TAO MOI (may chua tung co file nay)",
          "must_exist" in sp and "if must_exist and not os.path.exists(dst):" in sp)
    # database.py nam trong tien trinh FastAPI dang chay va script_routes._db()
    # cache module — khong restart thi ban CU van ghi mat khau.
    check("  goi va canh bao phai restart", "BAT BUOC restart tubecli" in sp
          and "van ghi mat khau" in sp)

    import ast as _ast
    _ast.parse(io.open(os.path.join(patch_dir, "secret_names.py"),
                       encoding="utf-8", errors="replace").read())
    check("  secret_names.py trong goi la Python hop le", True)
    # Leaf module: không được kéo theo gì của tubecli, nếu không thì ghi nó vào
    # một máy cũ lại đẻ ra một import hỏng khác.
    src = io.open(os.path.join(patch_dir, "secret_names.py"),
                  encoding="utf-8", errors="replace").read()
    check("  va khong import nguoc lai tubecli.*",
          "import tubecli" not in src and "from tubecli" not in src)


def main():
    tmp = tempfile.mkdtemp(prefix="tubecli_execsec_")
    try:
        part_shared_list()
        db_mod = part_db(tmp)
        part_migration(tmp, db_mod)
        part_fail_closed(tmp, db_mod)
        part_routes(tmp, db_mod)
        part_slug_variable()
        part_runner(tmp)
        part_allowlist_source(tmp)
        part_patch_bundle()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
