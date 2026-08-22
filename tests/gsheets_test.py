"""Google Sheets client + group-scoped gsheet_* actions must behave without Google.

Run:  python tests/gsheets_test.py     (exit 0 = pass)

Why this file exists. gsheets.py is the one place the worklog writer, the cloud
Sheet node and the chat actions all go through, and none of them can be exercised
against a real spreadsheet in CI. So the REST layer is driven through an
httpx.MockTransport here (URL quoting, tail/max_rows slicing, error mapping,
append options) and the action handlers are driven with a stubbed
tubecli.core.group_context — the one property that matters most being that a
sheet outside the agent's group is refused, not looked up.
"""
import asyncio
import json
import os
import sys
import types
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import httpx

from tubecli.extensions.auth_manager import gsheets

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


# ── Fake Google ──────────────────────────────────────────────────

SID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefg"
ROWS = [["Time", "Agent", "Task"]] + [[f"t{i}", f"a{i}", f"task{i}"] for i in range(1, 10)]  # 10 rows
REQUESTS = []


def fake_google(request: httpx.Request) -> httpx.Response:
    REQUESTS.append(request)
    path = request.url.path
    if request.headers.get("authorization") != "Bearer tok":
        return httpx.Response(401, json={"error": {"code": 401, "message": "bad token"}})
    if "/FORBIDDEN" in path:
        return httpx.Response(403, json={"error": {"code": 403, "message": "The caller does not have permission"}})
    if "/MISSING" in path:
        return httpx.Response(404, json={"error": {"code": 404, "message": "Requested entity was not found."}})
    if "/BOOM" in path:
        raise httpx.ConnectError("dns down")
    if path == f"/v4/spreadsheets/{SID}" and request.method == "GET":
        return httpx.Response(200, json={
            "spreadsheetId": SID,
            "properties": {"title": "Plan"},
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Tasks", "index": 0,
                                "gridProperties": {"rowCount": 1000, "columnCount": 26}}},
                {"properties": {"sheetId": 77, "title": "My Tab", "index": 1,
                                "gridProperties": {"rowCount": 50, "columnCount": 6}}},
                {"properties": {"sheetId": 78, "title": "Empty", "index": 2,
                                "gridProperties": {"rowCount": 10, "columnCount": 2}}},
            ],
        })
    if path.startswith(f"/v4/spreadsheets/{SID}/values/") and path.endswith(":append"):
        body = json.loads(request.content)
        n = len(body["values"])
        return httpx.Response(200, json={"updates": {
            "updatedRange": f"'My Tab'!A{11}:C{10 + n}", "updatedRows": n, "updatedCells": n * 3}})
    if path.startswith(f"/v4/spreadsheets/{SID}/values/") and request.method == "GET":
        # the "Empty" tab has no values at all; anything else → the 10 demo rows
        if "'Empty'" in path:
            return httpx.Response(200, json={"range": "'Empty'!A1:B10"})
        return httpx.Response(200, json={"range": "'Tasks'!A1:C10", "values": ROWS})
    if path.startswith(f"/v4/spreadsheets/{SID}/values/") and request.method == "PUT":
        body = json.loads(request.content)
        return httpx.Response(200, json={"updatedRange": body["range"], "updatedRows": len(body["values"]),
                                         "updatedCells": sum(len(r) for r in body["values"])})
    if path == f"/v4/spreadsheets/{SID}:batchUpdate":
        body = json.loads(request.content)
        title = body["requests"][0]["addSheet"]["properties"]["title"]
        if title == "Tasks":
            return httpx.Response(400, json={"error": {"code": 400, "message": f'A sheet with the name "{title}" already exists.'}})
        return httpx.Response(200, json={"replies": [{"addSheet": {"properties": {"sheetId": 99, "title": title}}}]})
    return httpx.Response(500, json={"error": {"code": 500, "message": "unhandled in fake"}})


def install_fake():
    gsheets._client = lambda: httpx.Client(transport=httpx.MockTransport(fake_google), timeout=gsheets.TIMEOUT)
    gsheets._token = lambda cred_id: "tok" if cred_id == "c1" else (_ for _ in ()).throw(
        gsheets.GSheetsError(403, f"no active Google token for credential '{cred_id}'"))
    gsheets._authorized_email = lambda cred_id: "owner@example.com"


# ── Stub group context (the real module is written by another builder) ──

ACCESS_ORDER = {"read": 0, "append": 1, "write": 2, "manage": 3}
GROUPS = {
    "g1": {
        "group_id": "g1", "label": "Content team", "agents": ["a1"], "files": [], "folders": [],
        "sheets": [{"alias": "Kế hoạch tuần", "sheet_id": SID, "cred_id": "c1",
                    "tabs": ["Tasks", "My Tab"], "default_tab": "Tasks", "access": "append", "role": "worklog"}],
    },
    "g2": {
        "group_id": "g2", "label": "Other", "agents": ["zz"], "files": [], "folders": [],
        "sheets": [{"alias": "Secret", "sheet_id": "FORBIDDEN", "cred_id": "c1", "access": "manage"}],
    },
}


def make_stub():
    gc = types.ModuleType("tubecli.core.group_context")
    gc.ACCESS_ORDER = ACCESS_ORDER
    gc.load = lambda gid: GROUPS.get(gid)
    gc.effective_groups = lambda agent_id, group_id="": (
        [GROUPS[group_id]] if group_id in GROUPS else [g for g in GROUPS.values() if agent_id in g["agents"]])
    gc.allows = lambda have, need: ACCESS_ORDER.get(have, 0) >= ACCESS_ORDER.get(need, 0)

    def resolve_sheet(groups, ref):
        key = (ref or "").strip().casefold()
        for g in groups:
            for s in g.get("sheets") or []:
                if s.get("alias", "").casefold() == key or s.get("sheet_id") == ref or (s.get("sheet_id") and s["sheet_id"] in ref):
                    return s
        return None
    gc.resolve_sheet = resolve_sheet
    return gc


def use_stub(module):
    import tubecli.core
    sys.modules["tubecli.core.group_context"] = module
    if module is None:
        # a None entry makes `import tubecli.core.group_context` raise ImportError
        if hasattr(tubecli.core, "group_context"):
            delattr(tubecli.core, "group_context")
    else:
        tubecli.core.group_context = module


def run(coro):
    return asyncio.run(coro)


def main():
    install_fake()

    print("=== 1. parse_sheet_id ===")
    url = f"https://docs.google.com/spreadsheets/d/{SID}/edit#gid=77"
    check("full edit url", gsheets.parse_sheet_id(url) == SID)
    check("/u/1/ url", gsheets.parse_sheet_id(f"https://docs.google.com/spreadsheets/u/1/d/{SID}/edit?usp=sharing") == SID)
    check("bare id", gsheets.parse_sheet_id(f"  {SID} ") == SID)
    check("legacy ?key=", gsheets.parse_sheet_id(f"https://spreadsheets.google.com/ccc?key={SID}&hl=en") == SID)
    check("garbage → empty", gsheets.parse_sheet_id("Tasks") == "" and gsheets.parse_sheet_id("") == "")
    check("docs url without /d/ → empty", gsheets.parse_sheet_id("https://docs.google.com/spreadsheets/") == "")

    print("\n=== 2. A1 quoting ===")
    check("space in tab", gsheets.a1_range("My Tab", "A1:B2") == "'My Tab'!A1:B2")
    check("apostrophe doubled", gsheets.a1_range("It's", "A1") == "'It''s'!A1")
    check("tab only", gsheets.a1_range("Log") == "'Log'")
    check("no tab → range only", gsheets.a1_range("", "A1:B2") == "A1:B2")
    check("split full ref", gsheets.split_range("'My Tab'!A1:B2") == ("My Tab", "A1:B2"))
    check("split plain", gsheets.split_range("A1:B2") == ("", "A1:B2"))

    print("\n=== 3. normalise_rows ===")
    check("flat list → one row", gsheets.normalise_rows(["a", "b"]) == [["a", "b"]])
    check("None → empty string, nested → json",
          gsheets.normalise_rows([[None, 3, True, {"k": 1}]]) == [["", 3, True, '{"k": 1}']])
    check("scalar row wrapped", gsheets.normalise_rows([["a"], "b"]) == [["a"], ["b"]])
    try:
        gsheets.normalise_rows("abc")
        check("string rejected", False)
    except gsheets.GSheetsError as e:
        check("string rejected", e.status == 400)

    print("\n=== 4. read: slicing + URL encoding ===")
    REQUESTS.clear()
    res = gsheets.read("c1", SID, "My Tab", "A1:C10", max_rows=3)
    check("first max_rows", res["values"] == ROWS[:3] and res["total_rows"] == 10 and res["truncated"])
    path = REQUESTS[-1].url.raw_path.decode()
    check("tab quoted + percent-encoded once", "/values/%27My%20Tab%27%21A1%3AC10" in path, path)
    check("no double encoding", "%25" not in path)
    res = gsheets.read("c1", SID, "Tasks", tail=2)
    check("tail keeps last rows", res["values"] == ROWS[-2:] and res["truncated"] and res["total_rows"] == 10)
    res = gsheets.read("c1", SID, "Tasks", max_rows=0)
    check("max_rows=0 → all", res["values"] == ROWS and not res["truncated"])
    REQUESTS.clear()
    res = gsheets.read("c1", SID, "", None, max_rows=200)
    check("missing tab → first tab via one metadata call",
          res["tab"] == "Tasks" and len(REQUESTS) == 2 and REQUESTS[0].url.path == f"/v4/spreadsheets/{SID}")
    res = gsheets.read("c1", SID, "", "My Tab!A1:B2")
    check("tab taken from full A1 ref", res["tab"] == "My Tab")

    print("\n=== 5. inspect / tabs ===")
    info = gsheets.inspect("c1", SID)
    check("inspect shape", info["sheet_id"] == SID and info["title"] == "Plan"
          and [t["title"] for t in info["tabs"]] == ["Tasks", "My Tab", "Empty"]
          and info["tabs"][1]["gid"] == 77 and info["tabs"][1]["rows"] == 50 and info["tabs"][1]["cols"] == 6
          and info["authorized_email"] == "owner@example.com")
    check("fields param limits payload", "sheets.properties" in parse_qs(REQUESTS[-1].url.query.decode()).get("fields", [""])[0])

    print("\n=== 6. append / update / create_tab ===")
    REQUESTS.clear()
    res = gsheets.append("c1", SID, "My Tab", [["x", "y", "z"], ["1", "2", "3"]])
    q = parse_qs(REQUESTS[-1].url.query.decode())
    check("append options", q.get("valueInputOption") == ["USER_ENTERED"] and q.get("insertDataOption") == ["INSERT_ROWS"], str(q))
    check("append path", "/values/%27My%20Tab%27:append?" in REQUESTS[-1].url.raw_path.decode())
    check("append result", res["updated_rows"] == 2 and res["updated_range"].startswith("'My Tab'!") and res["tab"] == "My Tab")
    try:
        gsheets.append("c1", SID, "My Tab", [])
        check("append empty rejected", False)
    except gsheets.GSheetsError as e:
        check("append empty rejected", e.status == 400)
    res = gsheets.update("c1", SID, "Tasks", "B2:C2", [["p", "q"]])
    body = json.loads(REQUESTS[-1].content)
    check("update range + body", res["updated_range"] == "'Tasks'!B2:C2" and body["values"] == [["p", "q"]]
          and REQUESTS[-1].method == "PUT" and parse_qs(REQUESTS[-1].url.query.decode()).get("valueInputOption") == ["USER_ENTERED"])
    res = gsheets.create_tab("c1", SID, "Week 35")
    check("create_tab", res == {"title": "Week 35", "gid": 99})
    try:
        gsheets.create_tab("c1", SID, "Tasks")
        check("duplicate tab surfaces Google's message", False)
    except gsheets.GSheetsError as e:
        check("duplicate tab surfaces Google's message", e.status == 400 and "already exists" in e.message, e.message)

    print("\n=== 7. ensure_header ===")
    REQUESTS.clear()
    res = gsheets.ensure_header("c1", SID, "Log", ["Time", "Agent"])
    kinds = [r.method for r in REQUESTS]
    check("missing tab → created + header written (GET meta, POST addSheet, PUT header)",
          res == {"tab": "Log", "created_tab": True, "wrote_header": True} and kinds == ["GET", "POST", "PUT"]
          and json.loads(REQUESTS[-1].content)["values"] == [["Time", "Agent"]], f"{res} {kinds}")
    REQUESTS.clear()
    res = gsheets.ensure_header("c1", SID, "empty", ["Time", "Agent"])
    check("existing empty tab → header written only",
          res == {"tab": "Empty", "created_tab": False, "wrote_header": True}
          and [r.method for r in REQUESTS] == ["GET", "GET", "PUT"], f"{res} {[r.method for r in REQUESTS]}")
    REQUESTS.clear()
    res = gsheets.ensure_header("c1", SID, "tasks", ["Time", "Agent"])
    check("existing tab with data: nothing written, canonical name returned",
          res == {"tab": "Tasks", "created_tab": False, "wrote_header": False}
          and not any(r.method in ("PUT", "POST") for r in REQUESTS))

    print("\n=== 8. error mapping ===")
    try:
        gsheets.inspect("c1", "FORBIDDEN")
        check("403 mapped", False)
    except gsheets.GSheetsError as e:
        check("403 mapped", e.status == 403 and "spreadsheets scope" in e.message, e.message)
    try:
        gsheets.inspect("c1", "MISSING")
        check("404 mapped", False)
    except gsheets.GSheetsError as e:
        check("404 mapped", e.status == 404 and "not found" in e.message, e.message)
    try:
        gsheets.inspect("c1", "BOOM")
        check("network error → 502", False)
    except gsheets.GSheetsError as e:
        check("network error → 502", e.status == 502 and "cannot reach" in e.message, e.message)
    try:
        gsheets.inspect("nope", SID)
        check("no token → 403 before any request", False)
    except gsheets.GSheetsError as e:
        check("no token → 403 before any request", e.status == 403 and "nope" in e.message)
    check("str(err) is the message", str(gsheets.GSheetsError(404, "spreadsheet not found")) == "spreadsheet not found")

    from tubecli.extensions.auth_manager.routes import _gsheets_http_status as hs
    check("route status map", [hs(gsheets.GSheetsError(s, "")) for s in (400, 401, 403, 404, 429, 500, 502)]
          == [400, 403, 403, 404, 502, 502, 502])

    print("\n=== 9. gsheet_* handlers: group scoping ===")
    from tubecli.extensions.auth_manager.extension import AuthManagerExtension
    ext = AuthManagerExtension()
    actions = ext.get_telegram_actions()
    check("five gsheet actions registered",
          all(k in actions for k in ("gsheet_read", "gsheet_append", "gsheet_update", "gsheet_tabs", "gsheet_create_tab"))
          and "generate_auth_link" in actions)

    use_stub(make_stub())
    ctx_web = {"agent": {"id": "a1", "name": "Bot"}, "group_ids": ["g1"], "group_id": "g1", "source": "web_chat"}
    ctx_tg = {"agent": {"id": "a1", "name": "Bot"}, "lang": "vi"}  # no group_ids → union for the agent

    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Secret"}, ctx_web))
    check("alias from another group refused", "not shared" in out and "Kế hoạch tuần" in out and "FORBIDDEN" not in out, out)
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": SID}, ctx_web))
    check("own sheet also reachable by id (server-side only)", out.startswith("📊"), out[:60])
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Secret"}, ctx_tg))
    check("telegram path computes union itself → still refused", "not shared" in out, out)

    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Kế hoạch tuần"},
                                     {"agent": {"id": "nobody"}}))
    check("no groups → exact spec refusal",
          out == "❌ No Google Sheet is shared with this agent. Add a Sheet node to the agent's group.", out)
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Kế hoạch tuần"},
                                     {"agent": {"id": "a1"}, "group_ids": []}))
    check("explicit empty group_ids → no groups (no silent union)", "No Google Sheet is shared" in out, out)

    REQUESTS.clear()
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "kế hoạch tuần", "max_rows": 3}, ctx_web))
    lines = out.split("\n")
    check("read → compact table", lines[0].startswith('📊 "Kế hoạch tuần"') and lines[1] == "| Time | Agent | Task |"
          and len([l for l in lines if l.startswith("|")]) == 3 and "first 3 of 10" in out, out)
    check("default_tab used when tab omitted", "%27Tasks%27" in REQUESTS[-1].url.raw_path.decode())
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Kế hoạch tuần", "tail": 2}, ctx_web))
    check("tail read", "last 2 of 10" in out and "| t9 | a9 | task9 |" in out, out)
    out = run(actions["gsheet_read"]({"action": "gsheet_read"}, ctx_web))
    check("single shared sheet: 'sheet' may be omitted", out.startswith("📊"), out[:60])

    out = run(actions["gsheet_update"]({"action": "gsheet_update", "sheet": "Kế hoạch tuần", "range": "B2", "values": [["x"]]}, ctx_web))
    check("update on an append-only sheet refused", 'needs "write"' in out and '"append"' in out, out)
    out = run(actions["gsheet_create_tab"]({"action": "gsheet_create_tab", "sheet": "Kế hoạch tuần", "title": "W"}, ctx_web))
    check("create_tab needs manage", 'needs "manage"' in out, out)
    out = run(actions["gsheet_append"]({"action": "gsheet_append", "sheet": "Kế hoạch tuần", "tab": "My Tab",
                                        "rows": [["a", "b", "c"]]}, ctx_web))
    check("append allowed + reports where", out.startswith("✅ Appended 1 row(s)") and "My Tab" in out and "| a | b | c |" in out, out)
    out = run(actions["gsheet_append"]({"action": "gsheet_append", "sheet": "Kế hoạch tuần"}, ctx_web))
    check("append without rows → usage hint", out.startswith("❌") and '"rows"' in out, out)
    out = run(actions["gsheet_tabs"]({"action": "gsheet_tabs", "sheet": "Kế hoạch tuần"}, ctx_web))
    check("tabs listing", "- Tasks" in out and "- My Tab" in out and "Default tab: Tasks" in out, out)

    # manage-level sheet in a group whose sheet Google refuses → error text, no traceback
    GROUPS["g2"]["agents"] = ["a1"]
    out = run(actions["gsheet_create_tab"]({"action": "gsheet_create_tab", "sheet": "Secret", "title": "W"}, ctx_tg))
    check("Google 403 becomes readable text", out.startswith("❌ Google Sheets error") and "scope" in out, out)
    GROUPS["g2"]["agents"] = ["zz"]

    print("\n=== 10. core without group_context ===")
    use_stub(None)
    out = run(actions["gsheet_read"]({"action": "gsheet_read", "sheet": "Kế hoạch tuần"}, ctx_web))
    check("missing module → clear refusal, no crash", "not available" in out, out)
    del sys.modules["tubecli.core.group_context"]

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
