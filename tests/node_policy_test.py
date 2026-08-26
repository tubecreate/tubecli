"""Who may build which node, and the switch that keeps run_api shut.

Run:  python tests/node_policy_test.py     (exit 0 = pass)

Everything runs against a temporary data dir; the real data/ is never opened,
and no HTTP request leaves this process.

WHAT IS BEING LOCKED IN

1. NODE POLICY (spec G0 section 1). create_node_from_dict used to take a bare
   dict and build whatever "type" it named. Two of its callers hand it JSON the
   model wrote seconds earlier (api.chat.create_skill, brain.run_workflow_linear)
   and one hands it a tool name the model invented mid-loop
   (brain.autonomous_run) — so "type": "run_command" was a shell, "python_code"
   was exec(), "api_request" was this server's own loopback API, and "output"
   was a write to any path on disk, data/global_settings.json included.

   The fix is a mandatory keyword-only `policy`. The tests below check the three
   things that make it a fix rather than a speed bump: the parameter cannot be
   forgotten (no default, and every call site in the tree passes it), the model
   allowlist holds nothing that shells out or writes files, and the schema list
   handed to the model is filtered by the same policy — advertising a tool the
   model may not call is an invitation to try it.

2. WHO IS ASKING (spec G0 section 1.3). POST /api/v1/workflows/run and
   POST /api/v1/skills/{id}/run reach the same node builder over loopback, which
   auth.check_request lets through without a session on purpose. server.py's
   _node_policy_for_request is the single place that decides, and it is pulled
   out of the file with ast and exercised directly here, because "we remembered
   to check" is not something a diff can promise a year from now.

3. RUN_API IS OFF (spec G0 section 9). The product owner kept run_api behind a
   technician_mode switch that defaults to OFF. Off must mean no HTTP at all —
   not "blocked at the endpoint" — and both states must leave a line in the
   group log, because a power tool nobody can audit is a power tool nobody can
   trust.
"""
import ast
import asyncio
import inspect
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import tubecli.config as cfg

TMP = pathlib.Path(tempfile.mkdtemp(prefix="node_policy_"))
_REAL_EXT_DATA_PATH = cfg.ext_data_path
_REAL_DATA_DIR = cfg.DATA_DIR
# Same redirection group_log_test uses: group_log resolves its directory through
# cfg.ext_data_path, and telegram_actions freezes DATA_DIR/"global_settings.json"
# into SETTINGS_FILE at import time — so both have to be pointed at TMP BEFORE
# those modules are imported below.
cfg.ext_data_path = lambda *parts: TMP.joinpath(*parts)
cfg.DATA_DIR = TMP

ROOT = pathlib.Path(__file__).resolve().parent.parent

PASS = FAIL = 0


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


# Node types that must never be reachable from a model-authored workflow. Each
# one is a capability, not a preference: what it gives away is written next to
# it so a future edit to MODEL_SAFE_NODE_TYPES has to argue with this list.
DANGEROUS = {
    "run_command": "subprocess",
    "python_code": "exec()",
    "custom": "exec()",
    "ffmpeg_command": "shells out to ffmpeg with arbitrary args",
    "api_request": "arbitrary HTTP incl. auth-exempt loopback",
    "output": "writes any path on disk",
    "file_manager": "creates/deletes/moves any path",
    "if_node": "eval() of a model-written condition",
    "browser_action": "drives the owner's logged-in browser profiles",
    "google_sheets": "the owner's Google credentials, no group gate",
    "google_auth": "the owner's Google credentials",
    "google_calendar": "the owner's Google credentials",
}


def section_1_policy_object():
    print("=== 1. policy la tham so BAT BUOC ===")
    from tubecli.nodes import registry
    from tubecli.nodes.registry import (MODEL_SAFE_NODE_TYPES, NodePolicy,
                                        NodePolicyError, create_node_from_dict)

    sig = inspect.signature(create_node_from_dict)
    p = sig.parameters.get("policy")
    check("create_node_from_dict co tham so policy", p is not None)
    check("  keyword-only", p is not None and p.kind is inspect.Parameter.KEYWORD_ONLY)
    check("  KHONG co gia tri mac dinh (cua thu 8 khong the quen)",
          p is not None and p.default is inspect.Parameter.empty)
    # Called through an alias on purpose: section 4 scans every
    # create_node_from_dict CALL in the tree for policy=, and this one is
    # missing it deliberately.
    missing_policy = create_node_from_dict
    try:
        missing_policy({"type": "text_input"})
        check("goi thieu policy -> TypeError", False, "khong nem loi")
    except TypeError:
        check("goi thieu policy -> TypeError", True)

    sig2 = inspect.signature(registry.get_node_tool_schemas)
    q = sig2.parameters.get("policy")
    check("get_node_tool_schemas cung nhan policy", q is not None)
    check("  cung khong co mac dinh",
          q is not None and q.default is inspect.Parameter.empty)

    check("NodePolicyError la ValueError (call site tra 400, khong phai 500)",
          issubclass(NodePolicyError, ValueError))
    check("NodePolicy.user = khong gioi han", NodePolicy.user("t").allow is None)
    check("NodePolicy.user.source == 'user'", NodePolicy.user("t").source == "user")
    check("NodePolicy.model = allowlist", NodePolicy.model("t").allow == MODEL_SAFE_NODE_TYPES)
    check("NodePolicy.model.source == 'model'", NodePolicy.model("t").source == "model")


def section_2_allowlist():
    print("\n=== 2. model KHONG dung duoc node chay lenh ===")
    from tubecli.nodes.registry import (MODEL_SAFE_NODE_TYPES, NODE_REGISTRY,
                                        NodePolicy, NodePolicyError,
                                        create_node_from_dict)

    model = NodePolicy.model("test")
    user = NodePolicy.user("test")

    for node_type, why in sorted(DANGEROUS.items()):
        check(f"model KHONG dung duoc '{node_type}'",
              node_type not in MODEL_SAFE_NODE_TYPES, why)
        try:
            create_node_from_dict({"type": node_type, "config": {}}, policy=model)
            check(f"  dung '{node_type}' -> bi tu choi", False, "van dung duoc!")
        except NodePolicyError:
            check(f"  dung '{node_type}' -> bi tu choi", True)
        except Exception as e:
            # Refusing for the wrong reason (e.g. the type is not registered at
            # all) would make this test lie the day the node gets registered.
            check(f"  dung '{node_type}' -> bi tu choi", False, f"{type(e).__name__}: {e}")

    # The refusal must SAY what happened. A node silently dropped from a
    # generated workflow is the "the AI made me a flow that does nothing" bug.
    try:
        create_node_from_dict({"type": "run_command"}, policy=model)
        msg = ""
    except NodePolicyError as e:
        msg = str(e)
    check("loi noi ro loai node bi tu choi", "run_command" in msg, msg[:90])
    check("  va liet ke cai duoc phep", "text_input" in msg, msg[:90])

    # The user path is untouched: a person who drew a python_code box on the
    # canvas, or typed `tubecli workflow run`, still gets it.
    for node_type in ("python_code", "run_command", "output", "if_node"):
        try:
            node = create_node_from_dict({"type": node_type, "config": {}}, policy=user)
            check(f"nguoi dung VAN dung duoc '{node_type}'", node is not None)
        except Exception as e:
            check(f"nguoi dung VAN dung duoc '{node_type}'", False, str(e)[:90])

    # ...and what IS allowed still builds, aliases included.
    for node_type in sorted(MODEL_SAFE_NODE_TYPES):
        if node_type not in NODE_REGISTRY:
            check(f"allowlist khong co ten ma (khong ton tai): '{node_type}'", False)
            continue
        try:
            create_node_from_dict({"type": node_type, "config": {}}, policy=model)
            check(f"model dung duoc '{node_type}'", True)
        except Exception as e:
            check(f"model dung duoc '{node_type}'", False, str(e)[:90])

    # Every allowlisted class, read as source: no shell, no exec, no eval. This
    # is the guard against the allowlist rotting — the day someone adds
    # subprocess to json_parser, this fails instead of the customer finding out.
    for node_type in sorted(MODEL_SAFE_NODE_TYPES):
        cls = NODE_REGISTRY.get(node_type)
        if cls is None:
            continue
        try:
            src = inspect.getsource(cls)
        except Exception:
            continue
        bad = [tok for tok in ("subprocess", "os.system", "exec(", "eval(") if tok in src]
        check(f"'{node_type}' khong chay lenh/ma", not bad, ", ".join(bad))

    # An unknown type is still an unknown type, not a policy refusal.
    try:
        create_node_from_dict({"type": "khong_co_that"}, policy=user)
        check("type la khong co that -> van bao loi", False)
    except Exception as e:
        check("type la khong co that -> van bao loi", "Unknown node type" in str(e), str(e)[:60])


def section_3_tool_schemas():
    print("\n=== 3. schema day cho model khong chua node cam ===")
    from tubecli.nodes.registry import NodePolicy, get_node_tool_schemas

    model_tools = {t["function"]["name"] for t in get_node_tool_schemas(NodePolicy.model("t"))}
    user_tools = {t["function"]["name"] for t in get_node_tool_schemas(NodePolicy.user("t"))}

    for node_type in sorted(DANGEROUS):
        check(f"schema cua model khong nhac '{node_type}'", node_type not in model_tools)
    check("schema cua model van co viec de lam", len(model_tools) > 3, str(sorted(model_tools)))
    check("  van co finish_workflow (khong thi vong ReAct khong dung duoc)",
          "finish_workflow" in model_tools)
    # The control: filtering is the policy's doing, not a missing registry.
    check("schema cua NGUOI van co run_command", "run_command" in user_tools)
    check("  va nhieu hon cua model", len(user_tools) > len(model_tools),
          f"user={len(user_tools)} model={len(model_tools)}")


def _iter_py_files():
    for base in (ROOT / "tubecli", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def section_4_every_call_site():
    print("\n=== 4. MOI call site deu truyen policy ===")
    seen = unparsed = 0
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            unparsed += 1
            print(f"  (bo qua, khong parse duoc: {path.relative_to(ROOT)})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            rel = path.relative_to(ROOT).as_posix()
            if name == "create_node_from_dict":
                seen += 1
                check(f"{rel}:{node.lineno} truyen policy=",
                      any(kw.arg == "policy" for kw in node.keywords))
            elif name == "get_node_tool_schemas":
                seen += 1
                check(f"{rel}:{node.lineno} truyen policy cho schema",
                      bool(node.args) or any(kw.arg == "policy" for kw in node.keywords))
    # The spec counted seven call sites of create_node_from_dict plus the schema
    # call; if this number collapses, the scan stopped finding them, not the
    # code stopped having them.
    check("quet duoc it nhat 8 cho goi", seen >= 8, f"{seen} cho, {unparsed} file khong parse")


def _server_symbol(name, also=()):
    """Pull one top-level def/assign/class out of server.py without importing it.

    Importing api/server.py starts extension discovery and can clone
    extensions; group_log_test.py takes the same ast route for the same reason.

    `also` names companions the wanted symbol REFERS to — _node_policy_for_request
    tests `isinstance(request, _OwnerInProcessCall)`, and a slice without that
    class raises NameError on the first call. They are compiled in the same
    namespace, in source order, so the slice behaves like the real module.
    """
    tree = ast.parse((ROOT / "tubecli" / "api" / "server.py").read_text(encoding="utf-8",
                                                                       errors="replace"))
    wanted = (name,) + tuple(also)

    def _named(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return n.name
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if getattr(t, "id", "") in wanted:
                    return getattr(t, "id", "")
        return None

    body = [n for n in tree.body if _named(n) in wanted]
    assert len(body) == len(wanted), (
        f"server.py: expected {wanted}, found {[_named(n) for n in body]}")
    ns = {"Request": object, "_re": __import__("re")}
    exec(compile(ast.Module(body=body, type_ignores=[]), "server.py", "exec"), ns)
    return ns[name], tree, ns


class _Req:
    """Just enough of a Starlette request. Header keys are lowercase because
    that is what Starlette's case-insensitive Headers.get() sees."""

    def __init__(self, headers=None, cookies=None, guest=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.state = types.SimpleNamespace()
        if guest is not None:
            self.state.guest_scope = guest


def section_5_who_is_asking():
    print("\n=== 5. route HTTP: ai dang hoi? ===")
    policy_for, tree, _sns = _server_symbol("_node_policy_for_request",
                                            also=("_OwnerInProcessCall",))
    import tubecli.core.auth as auth_mod

    real_session_valid = auth_mod.session_valid
    auth_mod.session_valid = lambda token: token == "phien-that"
    try:
        # The agent's own loopback call — exec_run_api stamps this header.
        p = policy_for(_Req(headers={"x-tubecli-agent": "run_api"}), "t")
        check("header agent -> policy model", p.source == "model")
        # ...even carrying a valid owner cookie, which is what an agent replaying
        # a cookie it scraped would look like.
        p = policy_for(_Req(headers={"x-tubecli-agent": "run_api"},
                            cookies={"tubecli_session": "phien-that"}), "t")
        check("header agent thang ca cookie chu", p.source == "model")

        p = policy_for(_Req(guest={"profiles": ["tuan5"]}), "t")
        check("phien guest (sharee) -> model", p.source == "model")

        p = policy_for(_Req(cookies={"tubecli_session": "phien-that"}), "t")
        check("phien chu that -> user", p.source == "user")

        p = policy_for(_Req(headers={"origin": "http://localhost:5295"}), "t")
        check("trang dashboard cua chinh minh -> user", p.source == "user")
        # Referer MOT MINH khong con du. _guard_cross_origin chi kiem `origin`,
        # nen `referer` la header ma bat ky curl nao tren may cung tu go duoc -
        # ma _allowed_hosts() thi luon chua loopback. Trinh duyet gan Origin vao
        # moi fetch khong-GET/HEAD (ke ca same-origin) nen nut Run cua dashboard
        # khong he bi anh huong.
        p = policy_for(_Req(headers={"referer": "http://127.0.0.1:5295/webui/"}), "t")
        check("  referer MOT MINH -> model (header ai cung go duoc)", p.source == "model")
        p = policy_for(_Req(headers={"origin": "http://127.0.0.1:5295",
                                     "referer": "http://evil.example/"}), "t")
        check("  co Origin hop le thi van la user", p.source == "user")

        p = policy_for(_Req(headers={"origin": "http://evil.com"}), "t")
        check("trang la -> model", p.source == "model")
        p = policy_for(_Req(), "t")
        check("khong co bang chung gi -> model (fail closed)", p.source == "model")
        p = policy_for(_Req(cookies={"tubecli_session": "het-han"}), "t")
        check("cookie sai/het han -> model", p.source == "model")

        # Scheduler nen: khong co HTTP request nao ca. `request` la tham so BAT
        # BUOC nen loi goi thieu no nem TypeError, va cai except quanh no chi in
        # mot dong roi thoi — moi skill dat lich se lang le ngung chay.
        owner_call = _sns["_OwnerInProcessCall"]
        p = policy_for(owner_call("scheduler"), "t")
        check("loi goi in-process tu khai la cua chu -> user", p.source == "user")
        check("  where noi ro ai goi", p.where.endswith(":scheduler"), p.where)
        p = policy_for(object(), "t")
        check("mot object khong phai request -> model (fail closed)", p.source == "model")
    finally:
        auth_mod.session_valid = real_session_valid

    # Moi loi goi run_skill/run_workflow NOI BO trong server.py phai du tham so.
    for fname in ("run_skill", "run_workflow"):
        fn = [n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname]
        if not fn:
            continue
        need = len(fn[0].args.args) - len(fn[0].args.defaults)
        inner = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == fname]
        for call in inner:
            given = len(call.args) + len(call.keywords)
            check(f"{fname}() goi o dong {call.lineno} du {need} tham so bat buoc",
                  given >= need, f"chi co {given}")

    # The two routes must actually ASK. Checked on the shipped source.
    for fn_name, route in (("run_workflow", "/api/v1/workflows/run"),
                           ("run_skill", "/api/v1/skills/{skill_id}/run")):
        fn = [n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name]
        check(f"{fn_name} ton tai", len(fn) == 1)
        if not fn:
            continue
        args = [a.arg for a in fn[0].args.args]
        check(f"  {fn_name} nhan request", "request" in args, str(args))
        # run_skill hoi qua _policy_for_stored_skill (ket hop them dau nguon goc
        # cua skill); run_workflow hoi thang. Ca hai deu phai HOI dung mot lan.
        calls = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") in ("_node_policy_for_request",
                                                   "_policy_for_stored_skill")]
        check(f"  {fn_name} hoi chinh sach node", len(calls) == 1)
        check(f"  {fn_name} van la route {route}",
              any(isinstance(d, ast.Call)
                  and route in [getattr(a, "value", None) for a in d.args]
                  for d in fn[0].decorator_list))

    # And the login gate must keep covering it: the day someone adds this path
    # to the exempt list, the policy above is the only thing left.
    exempt, _, _ = _server_symbol("_AUTH_EXEMPT_EXACT")
    prefixes, _, _ = _server_symbol("_AUTH_EXEMPT_PREFIX")
    for route in ("/api/v1/workflows/run", "/api/v1/skills/{skill_id}/run"):
        check(f"{route} KHONG duoc mien dang nhap",
              route not in exempt and not route.startswith(tuple(prefixes)))


# ── run_api, spec G0 section 9 ───────────────────────────────────────

class _FakeResp:
    status_code = 200
    text = '{"status": "ok"}'

    def json(self):
        return {"status": "ok", "message": "xong"}


class _FakeClient:
    """Stands in for httpx.AsyncClient: records how it was built, answers 200.

    A test that let a real request out would either hit a live server on this
    machine or hang; either way it would stop testing what it says it tests.
    """
    calls = []
    kwargs = {}

    def __init__(self, **kw):
        _FakeClient.kwargs = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        _FakeClient.calls.append(("GET", url))
        return _FakeResp()

    async def post(self, url, json=None):
        _FakeClient.calls.append(("POST", url))
        return _FakeResp()


def _set_technician_mode(value):
    path = TMP / "global_settings.json"
    if value is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps({"technician_mode": value}), encoding="utf-8")


def section_6_run_api_switch():
    print("\n=== 6. run_api sau cong tac 'che do ky thuat vien' ===")
    from tubecli.core import group_log
    from tubecli.core import telegram_actions as ta

    check("SETTINGS_FILE tro vao thu muc tam (khong dung data/ that)",
          str(TMP) in str(ta.SETTINGS_FILE), str(ta.SETTINGS_FILE))

    real_httpx = ta.httpx
    ta.httpx = types.SimpleNamespace(AsyncClient=_FakeClient)
    ctx = {"group_ids": ["g_runapi"], "agent": {"id": "a1", "name": "Tro ly"}}
    try:
        # ── TAT (mac dinh) ──
        _set_technician_mode(None)
        _FakeClient.calls = []
        reply = run(ta.exec_run_api({"method": "GET", "endpoint": "/api/v1/health"}, ctx))
        check("mac dinh TAT: bi tu choi", reply.startswith("❌"), reply[:70])
        check("  noi ro cach bat", "technician_mode" in reply and "global_settings.json" in reply)
        check("  co canh bao rui ro", "Rủi ro" in reply, reply[-90:])
        check("  KHONG co request nao di ra", _FakeClient.calls == [], str(_FakeClient.calls))
        rows = group_log.read("g_runapi").get("lines") or []
        check("  van ghi mot dong nhat ky nhom", len(rows) == 1, str(len(rows)))
        check("  dong do la run_api va bi danh dau hong",
              bool(rows) and rows[-1].get("kind") == "run_api" and rows[-1].get("ok") is False,
              str(rows[-1] if rows else None)[:120])

        _set_technician_mode(False)
        reply = run(ta.exec_run_api({"method": "GET", "endpoint": "/api/v1/health"}, ctx))
        check("technician_mode=false cung la TAT", reply.startswith("❌"))

        # ── BAT ──
        _set_technician_mode(True)
        _FakeClient.calls = []
        reply = run(ta.exec_run_api({"method": "GET", "endpoint": "/api/v1/health"}, ctx))
        check("BAT: chay that", reply.startswith("✅"), reply[:70])
        check("  co dung mot request", len(_FakeClient.calls) == 1, str(_FakeClient.calls))
        headers = _FakeClient.kwargs.get("headers") or {}
        check("  co dan dau X-TubeCLI-Agent (route biet day la agent)",
              headers.get("X-TubeCLI-Agent") == "run_api", str(headers))
        rows = group_log.read("g_runapi").get("lines") or []
        check("  luot THANH CONG cung co dong nhat ky", len(rows) == 3, str(len(rows)))
        check("  va duoc danh dau la xong", rows[-1].get("ok") is True)
        check("  tieu de noi ro goi gi", "/api/v1/health" in (rows[-1].get("title") or ""),
              rows[-1].get("title"))

        # ── BAT nhung /groups van cam (hanh vi cu giu nguyen) ──
        _FakeClient.calls = []
        for ep in ("/api/v1/groups/g_khac/log", "/api/v1/groups",
                   "api/v1/groups/g/context", "/api/v1/agents/../groups/g/context"):
            r = run(ta.exec_run_api({"method": "GET", "endpoint": ep}, ctx))
            check(f"BAT: van chan {ep}", r.startswith("❌") and "nhóm" in r, r[:70])
        check("  khong loi nao di ra ngoai", _FakeClient.calls == [], str(_FakeClient.calls))

        # No group in this turn (Telegram DM, a scheduled run) must not crash
        # the call just because there is nothing to log to.
        reply = run(ta.exec_run_api({"method": "GET", "endpoint": "/api/v1/health"}, None))
        check("khong co nhom -> van chay, khong no", reply.startswith("✅"), reply[:70])
    finally:
        ta.httpx = real_httpx
        _set_technician_mode(None)

    # A switch the agent can flip is not a switch. data/global_settings.json
    # sits inside the AI file sandbox's allowed root, so until it was named in
    # AI_PROTECTED_DATA_SUBDIRS one file_action create_file turned run_api back
    # on - closing the HTTP door while that stayed open would not be a fix.
    from tubecli.extensions.file_manager import file_service as fs_mod

    check("global_settings.json nam trong danh sach cam cua sandbox AI",
          "global_settings.json" in fs_mod.AI_PROTECTED_DATA_SUBDIRS,
          str(fs_mod.AI_PROTECTED_DATA_SUBDIRS))
    # Probed against the REAL data dir, not TMP: TMP lives under
    # ~/AppData/Local, which BLOCKED_PATHS already refuses, so a probe there
    # would pass whatever this list said. Nothing is written - validate_path
    # only resolves and checks.
    ai_fs = fs_mod.FileService(enforce_roots=True)
    real_data = os.path.abspath(os.environ.get("TUBECLI_DATA_DIR", "data"))
    try:
        ai_fs.validate_path(os.path.join(real_data, "global_settings.json"))
        check("AI khong ghi duoc global_settings.json", False, "khong bi chan")
    except ValueError as e:
        check("AI khong ghi duoc global_settings.json",
              "bảo mật" in str(e), str(e)[:110])
    # skills.json / agents.json are the same switch one floor down: both carry
    # schedule_enabled, and scheduler._tick fires whatever is due through
    # _OwnerInProcessCall, which hands the run NodePolicy.user. The sentinel's
    # stated premise is "no route can set schedule_enabled, so a schedule can
    # only come from the owner" - true of routes, false of the FILE, which was
    # writable by one file_action create_file.
    for name in ("skills.json", "agents.json"):
        check(f"{name} nam trong danh sach cam cua sandbox AI",
              name in fs_mod.AI_PROTECTED_DATA_SUBDIRS,
              str(fs_mod.AI_PROTECTED_DATA_SUBDIRS))
        try:
            ai_fs.validate_path(os.path.join(real_data, name))
            check(f"AI khong ghi duoc {name}", False, "khong bi chan")
        except ValueError as e:
            check(f"AI khong ghi duoc {name}", "bảo mật" in str(e), str(e)[:110])
    # Control: the rest of data/ is still reachable, so what refused above was
    # this rule and not the allowlist.
    try:
        ai_fs.validate_path(os.path.join(real_data, "downloads"))
        check("  file khac trong data/ van cham duoc", True)
    except ValueError as e:
        check("  file khac trong data/ van cham duoc", False, str(e)[:110])

    # ── Nguon goc skill quyet dinh quyen node, khong phai duong chay ──
    #
    # Ban truoc dat NodePolicy.model cho MOI skill trong run_workflow_linear.
    # Do tren kho that: 10/10 skill co workflow deu chet vi `output` (co mat
    # trong ca 10) khong nam trong allowlist. Do la skill CHU ve, khong phai
    # "workflow do model sinh". Cua that nam o cho DUA node vao kho.
    import inspect

    from tubecli.core.brain import AgentBrain
    from tubecli.core.skill import Skill

    src = inspect.getsource(AgentBrain.run_workflow_linear)
    check("run_workflow_linear doc dau nguon goc", "authored_by" in src, src[:200])

    seen = {}

    def _fake_create(node_data, *, policy):
        seen["source"] = policy.source
        raise RuntimeError("stop")   # khong dung node that

    import tubecli.nodes.registry as reg_mod

    saved_create = reg_mod.create_node_from_dict
    reg_mod.create_node_from_dict = _fake_create
    try:
        wf = {"nodes": [{"id": "n1", "type": "output"}], "connections": []}
        for authored, want in (("user", "user"), ("model", "model"), (None, "user")):
            skill = {"name": "s", "workflow_data": wf}
            if authored is not None:
                skill["authored_by"] = authored
            seen.clear()
            try:
                run(AgentBrain.run_workflow_linear("xin chao", {"id": "a"}, skill))
            except Exception:
                pass
            check(f"authored_by={authored!r} -> policy {want}", seen.get("source") == want,
                  seen.get("source"))
    finally:
        reg_mod.create_node_from_dict = saved_create

    # Dau nay do MAY CHU dong, khong do body: mot agent goi POST /skills van cat
    # duoc skill vao kho, nhung skill ay mang dau "model".
    check("Skill mac dinh la cua nguoi", Skill(name="x").authored_by == "user")
    check("Skill nhan dau model", Skill(name="x", authored_by="model").authored_by == "model")
    check("gia tri la -> ve 'user' (fail-safe nguoc: khong tu nhan la model)",
          Skill(name="x", authored_by="MoDeL").authored_by == "model"
          and Skill(name="x", authored_by="hacker").authored_by == "user")
    check("dau nam trong to_dict (con lai sau khi luu/doc)",
          Skill(name="x", authored_by="model").to_dict().get("authored_by") == "model")

    server_src = (ROOT / "tubecli" / "api" / "server.py").read_text(
        encoding="utf-8", errors="replace")
    check("POST /skills dong dau theo NGUOI GOI",
          'data["authored_by"] = _skill_author_for_request(request)' in server_src)
    check("auto-skill (AI sinh workflow) luu voi dau model",
          server_src.count('authored_by="model",') >= 2, server_src.count('authored_by="model",'))
    check("auto-skill khong con nuot NodePolicyError",
          "except NodePolicyError as pol_err:" in server_src)
    check("  va noi that la CHUA chay", "CHƯA chạy nó lần này" in server_src)
    check("skill do model tao thi chu bam Run cung chi duoc allowlist",
          "def _policy_for_stored_skill" in server_src
          and "_policy_for_stored_skill(request, skill" in server_src)

    # Referer khong phai bang chung: middleware chi kiem `origin`, con `referer`
    # thi bat ky curl nao tren may cung tu go duoc.
    check("_node_policy_for_request bo Referer",
          'request.headers.get("origin") or ""' in server_src
          and 'request.headers.get("referer")' not in server_src)

    # The Telegram path calls exec_run_api directly, skipping the dispatcher
    # that writes the group-log line for canvas turns — so it has to hand over
    # its context or that turn leaves no trace at all.
    listener = (ROOT / "tubecli" / "core" / "telegram_listener.py").read_text(
        encoding="utf-8", errors="replace")
    check("telegram_listener truyen context vao exec_run_api",
          "exec_run_api(brain_result.get(\"action_data\", {}), context)" in listener)


def main():
    try:
        section_1_policy_object()
        section_2_allowlist()
        section_3_tool_schemas()
        section_4_every_call_site()
        section_5_who_is_asking()
        section_6_run_api_switch()
    finally:
        cfg.ext_data_path = _REAL_EXT_DATA_PATH
        cfg.DATA_DIR = _REAL_DATA_DIR
        shutil.rmtree(TMP, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
