"""A Flow Builder group must grant exactly what it contains — no more.

Run:  python tests/group_context_test.py     (exit 0 = pass)

Everything runs against a temporary data dir; the real data/groups/ is never
opened. What this locks in:

1. THE FILE NAME. group_id comes from the canvas and becomes a path under
   data/groups/. Anything outside ^[A-Za-z0-9_-]{1,64}$ is refused, never
   sanitised — "../auth" must not become a file write next to auth.json.

2. THE BOUNDARY. Folder sharing is a realpath prefix joined with os.sep, so a
   folder named tuan5 does not admit tuan50, and "tuan5/../tuan50/x.xlsx"
   resolves to where it really points before the comparison.

3. THE PROMPT. prompt_block lists only the kinds a group really has: an agent
   with one Google Sheet is not taught xlsx verbs, and a sheet id or
   credential id never appears in the text the model sees.

4. THE ROUTES. PUT/GET/DELETE/list behave as the cloud sync expects,
   including idempotent DELETE and 404 for an unknown group.

5. THE WORKLOG. record_worklog writes the documented row shape through the
   gsheets client on a background thread, creates the Log tab once, and
   never raises — even when the client is broken.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg
from tubecli.core import group_context as gc

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def raises(fn, exc=Exception):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


SPEC_GROUP = {
    "group_id": "ignored-by-server",
    "label": "Content team",
    "agents": ["agent1", "agent1", "", None],
    "files": [{"alias": "upload_video_template.xlsx",
               "path": "/home/ubuntu/Downloads/upload_video_template.xlsx"},
              {"path": "/home/ubuntu/Downloads/plan.csv", "access": "bogus"},
              {"alias": "no path"}],
    "folders": [{"path": "/home/ubuntu/Downloads", "access": "append"}, "/home/ubuntu/Desktop"],
    "sheets": [{"alias": "Kế hoạch tuần", "sheet_id": "1AbC_xyz",
                "url": "https://docs.google.com/spreadsheets/d/1AbC_xyz/edit",
                "cred_id": "tok_123", "tabs": ["Tasks", "Log"], "default_tab": "Tasks",
                "access": "append", "role": "worklog"},
               {"alias": "Second log", "sheet_id": "2DeF", "cred_id": "tok_123",
                "tabs": ["Log"], "role": "worklog"},
               {"sheet_id": "", "alias": "dropped"}],
}


def main():
    tmp = tempfile.mkdtemp(prefix="tubecli_groups_")
    saved = cfg.DATA_DIR
    cfg.DATA_DIR = pathlib.Path(tmp)
    gc._ensured_worklogs.clear()

    try:
        print("=== 1. group_id la ten file: tu choi moi thu ngoai regex ===")
        for bad in ("../auth", "a b", "a.b", "", "x" * 65, None, 5, "group/1"):
            check(f"save({bad!r}) bi tu choi", raises(lambda: gc.save(bad, {}), ValueError))
            check(f"load({bad!r}) -> None", gc.load(bad) is None)
            check(f"delete({bad!r}) -> False", gc.delete(bad) is False)
        check("khong co file nao bi ghi ra ngoai groups/",
              not os.path.exists(os.path.join(tmp, "auth.json")))
        check("id hop le", gc.valid_group_id("group_" + "a" * 58) and gc.valid_group_id("A-1_b"))
        check("id 65 ky tu khong hop le", not gc.valid_group_id("a" * 65))

        print("\n=== 2. save/load: chuan hoa shape ===")
        stored = gc.save("group_a", SPEC_GROUP)
        check("group_id lay tu tham so, khong phai body", stored["group_id"] == "group_a")
        check("updated_at do server dat (UTC Z)", stored["updated_at"].endswith("Z"), stored["updated_at"])
        check("agents dedupe + bo rong", stored["agents"] == ["agent1"], stored["agents"])
        check("file khong path bi bo", len(stored["files"]) == 2, stored["files"])
        check("ext suy tu path", stored["files"][0]["ext"] == "xlsx" and stored["files"][1]["ext"] == "csv")
        check("file mac dinh write; access la bi thay mac dinh",
              stored["files"][0]["access"] == "write" and stored["files"][1]["access"] == "write")
        check("alias mac dinh = basename", stored["files"][1]["alias"] == "plan.csv")
        check("folder dang chuoi duoc nhan", stored["folders"][1] == {"path": "/home/ubuntu/Desktop", "access": "write"})
        check("folder giu access append", stored["folders"][0]["access"] == "append")
        check("sheet khong sheet_id bi bo", len(stored["sheets"]) == 2)
        check("sheet dau giu role worklog + access append",
              stored["sheets"][0]["role"] == "worklog" and stored["sheets"][0]["access"] == "append")
        check("chi MOT worklog / nhom (cai dau thang)", stored["sheets"][1]["role"] == "")
        check("sheet mac dinh read", stored["sheets"][1]["access"] == "read")
        check("default_tab mac dinh = tab dau", stored["sheets"][1]["default_tab"] == "Log")
        on_disk = json.load(open(os.path.join(tmp, "groups", "group_a.json"), encoding="utf-8"))
        check("file JSON nam trong <data>/groups/", on_disk["label"] == "Content team")
        loaded = gc.load("group_a")
        check("load == stored", loaded == stored)
        check("load nhom khong ton tai -> None", gc.load("group_nope") is None)
        check("container sai kieu bi tu choi", raises(lambda: gc.save("group_bad", {"files": "x"}), ValueError))
        check("body khong phai dict bi tu choi", raises(lambda: gc.save("group_bad", []), ValueError))
        check("nhom bi tu choi khong duoc ghi", gc.load("group_bad") is None)
        empty = gc.save("group_empty", {})
        check("body rong -> nhom rong hop le", empty["label"] == "Group" and empty["sheets"] == [])

        print("\n=== 3. list / groups_for_agent / effective_groups ===")
        gc.save("group_b", {"label": "B", "agents": ["agent1", "agent2"],
                            "sheets": [{"alias": "Kế hoạch tuần", "sheet_id": "1AbC_xyz", "access": "write"}]})
        ids = [g["group_id"] for g in gc.list_all()]
        check("list_all liet ke ca 3", ids == ["group_a", "group_b", "group_empty"], ids)
        check("groups_for_agent(agent1) = 2", sorted(g["group_id"] for g in gc.groups_for_agent("agent1")) == ["group_a", "group_b"])
        check("groups_for_agent(agent2) = 1", [g["group_id"] for g in gc.groups_for_agent("agent2")] == ["group_b"])
        check("groups_for_agent(nobody) = []", gc.groups_for_agent("nobody") == [])
        check("groups_for_agent('') = []", gc.groups_for_agent("") == [])
        check("effective: khong group_id -> hop", len(gc.effective_groups("agent1")) == 2)
        check("effective: group_id ro -> chi nhom do",
              [g["group_id"] for g in gc.effective_groups("agent1", "group_b")] == ["group_b"])
        # Dong khi group_id ro ma khong khop: nhom chua sync / PUT hong khong duoc
        # mo rong sang hop cac nhom khac; ten nhom khong thay manifest — agent bi keo
        # ra khoi nhom thi phien chat cu van nho ten nhom nhung manifest da bo agent.
        check("effective: group_id khong ton tai -> [] (khong roi ve hop)", gc.effective_groups("agent1", "group_zzz") == [])
        check("effective: group_id sai regex -> []", gc.effective_groups("agent1", "../x") == [])
        check("effective: agent ngoai nhom nhung group_id ro -> [] (manifest quyet, khong phai ten)",
              gc.effective_groups("agent9", "group_a") == [])
        gc.save("group_b", {"label": "B", "agents": ["agent2"],
                            "sheets": [{"alias": "Kế hoạch tuần", "sheet_id": "1AbC_xyz", "access": "write"}]})
        check("effective: agent bi bo khoi manifest -> mat nhom ngay", gc.effective_groups("agent1", "group_b") == [])
        gc.save("group_b", {"label": "B", "agents": ["agent1", "agent2"],
                            "sheets": [{"alias": "Kế hoạch tuần", "sheet_id": "1AbC_xyz", "access": "write"}]})
        check("effective: them lai agent -> co nhom lai",
              [g["group_id"] for g in gc.effective_groups("agent1", "group_b")] == ["group_b"])

        print("\n=== 4. allows: read < append < write < manage ===")
        order = ["read", "append", "write", "manage"]
        ok = True
        for i, have in enumerate(order):
            for j, need in enumerate(order):
                if gc.allows(have, need) != (i >= j):
                    ok = False
        check("ma tran thu tu dung", ok)
        check("access la -> tu choi", not gc.allows("owner", "read") and not gc.allows("", "read"))
        check("need la (typo trong handler) -> tu choi", not gc.allows("manage", "wrte"))
        check("khong phan biet hoa/thuong", gc.allows("Write", "APPEND"))

        print("\n=== 5. resolve_sheet: alias / id / URL ===")
        groups = gc.effective_groups("agent1")
        s = gc.resolve_sheet(groups, "  kế hoạch TUẦN ")
        check("alias casefold + trim", s is not None and s["sheet_id"] == "1AbC_xyz")
        check("hop 2 nhom -> quyen rong nhat (write tu group_b)", s is not None and s["access"] == "write" and s["group_id"] == "group_b")
        check("theo sheet_id", (gc.resolve_sheet(groups, "2DeF") or {}).get("alias") == "Second log")
        check("theo URL chua id", (gc.resolve_sheet(groups, "https://docs.google.com/spreadsheets/d/2DeF/edit#gid=0") or {}).get("sheet_id") == "2DeF")
        check("alias la -> None", gc.resolve_sheet(groups, "Ngân sách") is None)
        check("ref rong -> None", gc.resolve_sheet(groups, "") is None and gc.resolve_sheet(groups, None) is None)
        check("khong nhom -> None", gc.resolve_sheet([], "Kế hoạch tuần") is None)
        only_a = gc.effective_groups("agent1", "group_a")
        check("chi group_a -> access append cua group_a", gc.resolve_sheet(only_a, "Kế hoạch tuần")["access"] == "append")
        # Cùng alias nhưng HAI sheet_id khác nhau (agent ở 2 nhóm) -> phải báo mơ hồ, không chọn thầm
        twin = [
            {"group_id": "g1", "label": "Nhóm A", "agents": ["agent1"], "files": [], "folders": [],
             "sheets": [{"alias": "Log", "sheet_id": "AAA", "access": "write", "tabs": []}]},
            {"group_id": "g2", "label": "Nhóm B", "agents": ["agent1"], "files": [], "folders": [],
             "sheets": [{"alias": "log", "sheet_id": "BBB", "access": "read", "tabs": []}]},
        ]
        amb = gc.resolve_sheet(twin, "LOG")
        check("alias trung 2 sheet khac nhau -> ambiguous", isinstance(amb, dict) and amb.get("ambiguous") is True)
        check("ambiguous liet ke nhan nhom, khong lo sheet_id",
              amb is not None and {c["group_label"] for c in amb["choices"]} == {"Nhóm A", "Nhóm B"}
              and "AAA" not in str(amb) and "BBB" not in str(amb))
        check("cung alias cung sheet_id o 2 nhom -> KHONG mo ho", not (gc.resolve_sheet(groups, "Kế hoạch tuần") or {}).get("ambiguous"))

        print("\n=== 6. resolve_xlsx: realpath + prefix (tuan5 vs tuan50) ===")
        d5 = os.path.join(tmp, "tuan5")
        d50 = os.path.join(tmp, "tuan50")
        os.makedirs(os.path.join(d5, "sub"))
        os.makedirs(d50)
        for p in (os.path.join(d5, "a.xlsx"), os.path.join(d5, "sub", "b.xlsx"), os.path.join(d50, "a.xlsx"),
                  os.path.join(tmp, "lone.xlsx")):
            open(p, "wb").close()
        gc.save("group_fs", {"agents": ["fsagent"],
                             "folders": [{"path": d5, "access": "append"}, {"path": "relative/dir"},
                                         {"path": os.path.splitdrive(tmp)[0] + os.sep}, "/"],
                             "files": [{"path": os.path.join(d50, "a.xlsx"), "access": "read"},
                                       {"path": "~/this-file-does-not-exist-tubecli.xlsx"}]})
        fsg = gc.effective_groups("fsagent")
        r = gc.resolve_xlsx(fsg, os.path.join(d5, "a.xlsx"))
        check("file trong folder -> via folder, access cua folder",
              r is not None and r["via"] == "folder" and r["access"] == "append", r)
        check("path tra ve la realpath", r is not None and r["path"] == os.path.realpath(os.path.join(d5, "a.xlsx")))
        r = gc.resolve_xlsx(fsg, os.path.join(d5, "sub", "b.xlsx"))
        check("file sau trong folder van khop", r is not None and r["via"] == "folder")
        r = gc.resolve_xlsx(fsg, os.path.join(d50, "a.xlsx"))
        check("tuan50 KHONG khop prefix tuan5 -> chi khop file le (read)",
              r is not None and r["via"] == "file" and r["access"] == "read", r)
        check("file khac trong tuan50 -> None", gc.resolve_xlsx(fsg, os.path.join(d50, "zzz.xlsx")) is None)
        check("'tuan5/../tuan50/zzz.xlsx' -> None (.. duoc gop truoc)",
              gc.resolve_xlsx(fsg, os.path.join(d5, "..", "tuan50", "zzz.xlsx")) is None)
        check("'tuan50/../tuan5/a.xlsx' -> khop folder",
              (gc.resolve_xlsx(fsg, os.path.join(d50, "..", "tuan5", "a.xlsx")) or {}).get("via") == "folder")
        check("file ngoai moi thu -> None (root/drive/relative KHONG mo ca may)",
              gc.resolve_xlsx(fsg, os.path.join(tmp, "lone.xlsx")) is None)
        check("chinh folder cung resolve (prefix ==)", (gc.resolve_xlsx(fsg, d5) or {}).get("via") == "folder")
        check("path rong -> None", gc.resolve_xlsx(fsg, "") is None)
        check("khong nhom -> None", gc.resolve_xlsx([], os.path.join(d5, "a.xlsx")) is None)
        check("~ mo rong ve home", gc._canon("~") == os.path.realpath(os.path.expanduser("~")))
        home_file = os.path.expanduser("~/this-file-does-not-exist-tubecli.xlsx")
        check("entry '~/x' khop request tuyet doi", (gc.resolve_xlsx(fsg, home_file) or {}).get("via") == "file")

        print("\n=== 7. worklog_sheet ===")
        w = gc.worklog_sheet(gc.effective_groups("agent1"))
        check("sheet worklog dau tien + group_id", w is not None and w["sheet_id"] == "1AbC_xyz" and w["group_id"] == "group_a")
        check("khong worklog -> None", gc.worklog_sheet(gc.effective_groups("agent2")) is None)
        check("None/[] -> None", gc.worklog_sheet(None) is None and gc.worklog_sheet([]) is None)

        print("\n=== 8. prompt_block: chi liet ke thu dang co ===")
        check("khong nhom -> ''", gc.prompt_block([]) == "" and gc.prompt_block(None) == "")
        check("nhom rong -> ''", gc.prompt_block([gc.load("group_empty")]) == "")
        pa = gc.prompt_block([gc.load("group_a")])
        check("tieu de nhom", "### GROUP WORKSPACE: Content team" in pa)
        check("co Google Sheets + worklog", "Google Sheets" in pa and "THIS IS THE GROUP WORKLOG" in pa and 'tab "Log"' in pa)
        check("co file + folder", "Spreadsheet files" in pa and "Folders: /home/ubuntu/Downloads, /home/ubuntu/Desktop" in pa)
        check("co cu phap ca 2 loai", '"action":"gsheet_append"' in pa and '"action":"xlsx_write"' in pa)
        check("KHONG lo sheet_id / cred_id", "1AbC_xyz" not in pa and "tok_123" not in pa)
        check("alias + tabs + access", '"Kế hoạch tuần" — tabs: Tasks, Log (access: append)' in pa)
        check("nhom dien hinh < 2000 ky tu", len(pa) < 2000, str(len(pa)))
        pb = gc.prompt_block([gc.load("group_b")])
        check("chi sheet -> khong xlsx/Folders", "xlsx_" not in pb and "Spreadsheet files" not in pb and "Folders:" not in pb)
        check("chi sheet -> co gsheet", "gsheet_read" in pb and "GROUP WORKLOG" not in pb)
        pf = gc.prompt_block([gc.load("group_fs")])
        check("chi file/folder -> khong gsheet", "gsheet_" not in pf and "Google Sheets" not in pf and "xlsx_read" in pf)
        both = gc.prompt_block(gc.effective_groups("agent1"))
        check("hop 2 nhom -> 2 tieu de, 1 khoi cu phap", both.count("### GROUP WORKSPACE") == 2 and both.count("ACTION SYNTAX") == 1)
        big = gc.save("group_big", {"files": [{"path": f"/srv/f{i}.xlsx"} for i in range(25)]})
        pbig = gc.prompt_block([big])
        check("cat danh sach 20 + bao con lai", pbig.count("/srv/f") == 20 and "5 more files" in pbig)

        print("\n=== 9. record_worklog: nen, dung shape, khong raise ===")
        calls = []

        class _Fake(types.ModuleType):
            fail_header_once = True

            def ensure_header(self, cred_id, sheet_id, tab, header):
                calls.append(("ensure_header", cred_id, sheet_id, tab, list(header)))
                if _Fake.fail_header_once:
                    _Fake.fail_header_once = False
                    raise RuntimeError("no such tab")

            def create_tab(self, cred_id, sheet_id, title):
                calls.append(("create_tab", cred_id, sheet_id, title))

            def append(self, cred_id, sheet_id, tab, rows):
                calls.append(("append", cred_id, sheet_id, tab, rows))

        fake = _Fake("tubecli.extensions.auth_manager.gsheets")
        sys.modules["tubecli.extensions.auth_manager.gsheets"] = fake
        groups = gc.effective_groups("agent1")
        agent = {"id": "agent1", "name": "Writer"}
        gc.record_worklog(groups, agent, task="x" * 300, result="line1\nline2  " + "y" * 300,
                          artifacts=["/tmp/a.srt", "/tmp/b.txt"], status="done")
        deadline = time.time() + 5
        while time.time() < deadline and not any(c[0] == "append" for c in calls):
            time.sleep(0.05)
        names = [c[0] for c in calls]
        check("tao tab khi ensure_header that bai lan dau",
              names == ["ensure_header", "create_tab", "ensure_header", "append"], names)
        check("header dung", calls[0][4] == ["Time", "Agent", "Task", "Result", "Files", "Status"] and calls[0][3] == "Log")
        app = [c for c in calls if c[0] == "append"][0]
        check("append vao tab Log cua sheet worklog voi cred_id", app[1] == "tok_123" and app[2] == "1AbC_xyz" and app[3] == "Log")
        row = app[4][0]
        check("1 dong, 6 cot", len(app[4]) == 1 and len(row) == 6)
        check("cot: time ISO, ten agent", "T" in row[0] and row[1] == "Writer")
        check("task cat 120, result cat 200 + gop xuong dong", len(row[2]) == 120 and len(row[3]) == 200 and "\n" not in row[3] and row[3].startswith("line1 line2 y"))
        check("files noi '; ' + status", row[4] == "/tmp/a.srt; /tmp/b.txt" and row[5] == "done")
        calls.clear()
        gc.record_worklog(groups, agent, "t", "r", [], "error")
        deadline = time.time() + 5
        while time.time() < deadline and not any(c[0] == "append" for c in calls):
            time.sleep(0.05)
        check("lan 2: tab da cache -> chi append", [c[0] for c in calls] == ["append"], [c[0] for c in calls])
        check("status error duoc ghi", calls[0][4][0][5] == "error")
        calls.clear()
        gc.record_worklog(gc.effective_groups("agent2"), agent, "t", "r", [], "done")
        time.sleep(0.2)
        check("khong worklog -> khong goi gi", calls == [])
        check("groups None/agent None khong raise", gc.record_worklog(None, None, "t", "r", None, "done") is None)

        def _boom(*a, **k):
            raise RuntimeError("quota")
        fake.append = _boom
        gc.record_worklog(groups, agent, "t", "r", [], "done")
        time.sleep(0.3)
        check("client hong -> khong raise (chi warning)", True)

        print("\n=== 10. routes ===")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from tubecli.api.group_routes import router

        app_ = FastAPI()
        app_.include_router(router)
        c = TestClient(app_)
        r = c.put("/api/v1/groups/group_r1/context", json=SPEC_GROUP)
        check("PUT -> ok + group_id", r.status_code == 200 and r.json()["ok"] is True and r.json()["group_id"] == "group_r1", r.text[:200])
        r = c.get("/api/v1/groups/group_r1/context")
        check("GET -> context da chuan hoa", r.status_code == 200 and r.json()["label"] == "Content team" and r.json()["sheets"][1]["role"] == "")
        check("GET unknown -> 404", c.get("/api/v1/groups/group_none/context").status_code == 404)
        check("PUT id xau -> 400", c.put("/api/v1/groups/a%20b/context", json={}).status_code == 400
              and c.put("/api/v1/groups/a.b/context", json={}).status_code == 400)
        check("GET id xau -> 400 (khong 404)", c.get("/api/v1/groups/a.b/context").status_code == 400)
        check("PUT body khong phai object -> 400", c.put("/api/v1/groups/group_r2/context", json=[1]).status_code == 400)
        check("PUT container sai -> 400", c.put("/api/v1/groups/group_r2/context", json={"sheets": "x"}).status_code == 400)
        r = c.put("/api/v1/groups/group_r2/context", content=b"not json", headers={"content-type": "application/json"})
        check("PUT JSON hong -> 400", r.status_code == 400)
        check("nhom bi tu choi khong ton tai", c.get("/api/v1/groups/group_r2/context").status_code == 404)
        r = c.get("/api/v1/groups", params={"agent_id": "agent1"})
        ids = sorted(g["group_id"] for g in r.json()["groups"])
        check("list theo agent", r.status_code == 200 and ids == ["group_a", "group_b", "group_r1"], ids)
        r = c.get("/api/v1/groups")
        check("list tat ca", r.json()["count"] >= 6 and r.json()["count"] == len(r.json()["groups"]))
        check("DELETE -> ok", c.delete("/api/v1/groups/group_r1/context").json() == {"ok": True})
        check("DELETE lan 2 van ok (idempotent)", c.delete("/api/v1/groups/group_r1/context").json() == {"ok": True})
        check("sau DELETE -> 404", c.get("/api/v1/groups/group_r1/context").status_code == 404)
        check("DELETE id xau -> 400", c.delete("/api/v1/groups/a.b/context").status_code == 400)

        print("\n=== 11. chat store + pipeline ky hop dong ===")
        from tubecli.extensions.chat import store as chat_store

        chat_dir = os.path.join(tmp, "chat")
        chat_store.CHAT_DATA_DIR = chat_dir
        chat_store.SESSIONS_FILE = os.path.join(chat_dir, "sessions.json")
        chat_store.MESSAGES_DIR = os.path.join(chat_dir, "messages")
        cs = chat_store.ConversationStore()
        sess = cs.create_session(agent_id="agent1", group_id="group_a")
        check("session luu group_id", sess["group_id"] == "group_a")
        check("session mac dinh group_id ''", cs.create_session()["group_id"] == "")
        check("update_session doi group_id", cs.update_session(sess["id"], group_id="group_b")["group_id"] == "group_b")
        check("reload tu dia", chat_store.ConversationStore().get_session(sess["id"])["group_id"] == "group_b")

        import inspect
        from tubecli.extensions.chat import pipeline, routes as chat_routes

        check("run_turn(..., group_id='')", inspect.signature(pipeline.run_turn).parameters["group_id"].default == "")
        sig = inspect.signature(pipeline._dispatch_extension_action)
        check("_dispatch_extension_action(reply, agent_dict, group_ids, group_id)",
              list(sig.parameters) == ["reply", "agent_dict", "group_ids", "group_id"])
        check("CreateSessionRequest.group_id", chat_routes.CreateSessionRequest(agent_id="a").group_id == "")
        check("SendMessageRequest.group_id", chat_routes.SendMessageRequest(message="hi", group_id="group_a").group_id == "group_a")
        check("_group_workspace khong raise + dung", [g["group_id"] for g in pipeline._group_workspace("agent1", "group_b")] == ["group_b"])
        check("_worklog_status", pipeline._worklog_status("❌ x") == "error" and pipeline._worklog_status("done") == "done")
        calls.clear()
        fake.append = lambda cred_id, sheet_id, tab, rows: calls.append(("append", rows))
        pipeline._log_worklog(gc.effective_groups("agent1"), agent, "task", "ok /tmp/none.srt", ["/x/y.srt"])
        deadline = time.time() + 5
        while time.time() < deadline and not calls:
            time.sleep(0.05)
        check("_log_worklog -> record_worklog", bool(calls) and calls[0][1][0][4] == "/x/y.srt" and calls[0][1][0][5] == "done")
        check("_log_worklog khong nhom -> no-op", pipeline._log_worklog([], agent, "t", "r", []) is None)
    finally:
        cfg.DATA_DIR = saved
        sys.modules.pop("tubecli.extensions.auth_manager.gsheets", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
