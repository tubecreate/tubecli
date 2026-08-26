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

6. THE REGISTRY. Kinds are pluggable: an extension's get_group_kinds() is
   registered on enable and withdrawn on disable, a withdrawn built-in kind
   is not resurrected by ensure_default_kinds, and a list under a key no
   kind claims is stored verbatim (bounded) instead of being dropped.

7. THE PLAYBOOK. notes are the owner's instructions: trimmed, capped,
   aliased from the first line, listed before everything else.

8. FILES BY TYPE. A png is an image, not a spreadsheet; the xlsx verbs are
   taught only when a workbook or a folder is present.

9. CANVAS / SERVER. A PUT replaces the canvas half only; what the server
   added (add_server_entry, POST …/server/{kind}) survives it, is merged
   into the flat view tagged source="server", and dedups on the kind's
   identity.

10. MIGRATION. A phase-1 flat file reads as the canvas half.

11. THE STORE IS NOT IN THE SANDBOX. data/groups/ is refused by the
    enforce_roots=True FileService the model's file_action uses, so an
    agent cannot rewrite its own group; the owner's UI service still can.

12. MATERIALS BY NAME. resolve_entry finds a material by alias or by the
    kind's identity (a profile name, a script id, a path), refuses to guess
    when one name means two different things, and answers nothing for a kind
    nobody registered. resolve_file takes an alias or a path — including a
    path that only a shared FOLDER covers — and always hands back an
    absolute canonical path, because that is what a handler uploads.
    only_entry answers "the group's one profile" and None as soon as there
    are two. The scheduled run drives a profile the group shares.
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

        print("\n=== 4. allows: read < use/run < append < write/edit < manage ===")
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
        # Phase 2b: dieu khien mot thu cua nhom (browser profile, script) nam GIUA
        # doc va ghi — xem duoc chua chac lai duoc, ma lai duoc thi chua duoc ghi du lieu.
        ladder = ["read", "use", "append", "write", "manage"]
        ok = all(gc.allows(h, n) == (i >= j)
                 for i, h in enumerate(ladder) for j, n in enumerate(ladder))
        check("use xen giua read va append", ok)
        check("run ngang use", gc.ACCESS_ORDER["run"] == gc.ACCESS_ORDER["use"]
              and gc.allows("run", "use") and gc.allows("use", "run"))
        check("edit ngang write", gc.ACCESS_ORDER["edit"] == gc.ACCESS_ORDER["write"]
              and gc.allows("edit", "write") and gc.allows("write", "edit"))
        check("read chua du de dieu khien", not gc.allows("read", "use") and not gc.allows("read", "run"))
        check("use chua du de ghi", not gc.allows("use", "append") and not gc.allows("use", "write"))
        check("ghi/quan tri thi dieu khien duoc", gc.allows("append", "use") and gc.allows("manage", "run"))
        check("norm_access giu ten moi", gc.norm_access("use", "read") == "use"
              and gc.norm_access("RUN", "read") == "run" and gc.norm_access("Edit", "read") == "edit")

        print("\n=== 5. resolve_sheet: alias / id / URL ===")
        groups = gc.effective_groups("agent1")
        only_a = gc.effective_groups("agent1", "group_a")
        s = gc.resolve_sheet(only_a, "  kế hoạch TUẦN ")
        check("alias casefold + trim", s is not None and s["sheet_id"] == "1AbC_xyz")
        # ĐỔI (G0 §7): trước đây hợp hai nhóm lấy QUYỀN RỘNG NHẤT — group_a cho
        # "append", group_b cho "write" trên đúng cùng một sheet, và agent được
        # "write" kể cả khi đang làm việc ở bàn group_a. Đó là cộng gộp quyền:
        # chủ group_a không hề đồng ý cho ghi. Nay hai mức khác nhau ở hai nhóm
        # khác nhau là MƠ HỒ — hỏi lại, đúng luật "một alias hai thực thể".
        amb_acc = gc.resolve_sheet(groups, "  kế hoạch TUẦN ")
        check("cung 1 sheet, 2 nhom cho 2 muc quyen -> ambiguous (KHONG cong gop)",
              isinstance(amb_acc, dict) and amb_acc.get("ambiguous") is True, amb_acc)
        check("ambiguous vi quyen: chi nhan nhom, khong lo sheet_id",
              amb_acc is not None and {c["group_label"] for c in amb_acc["choices"]} == {"Content team", "B"}
              and "1AbC_xyz" not in str(amb_acc), amb_acc)
        check("theo sheet_id", (gc.resolve_sheet(groups, "2DeF") or {}).get("alias") == "Second log")
        check("theo URL chua id", (gc.resolve_sheet(groups, "https://docs.google.com/spreadsheets/d/2DeF/edit#gid=0") or {}).get("sheet_id") == "2DeF")
        check("alias la -> None", gc.resolve_sheet(groups, "Ngân sách") is None)
        check("ref rong -> None", gc.resolve_sheet(groups, "") is None and gc.resolve_sheet(groups, None) is None)
        check("khong nhom -> None", gc.resolve_sheet([], "Kế hoạch tuần") is None)
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
        # Cùng một sheet, hai nhóm, CÙNG một mức quyền: không có gì để phân xử.
        same_acc = [
            {"group_id": "g1", "label": "Nhóm A", "agents": ["agent1"], "files": [], "folders": [],
             "sheets": [{"alias": "Log", "sheet_id": "AAA", "access": "read", "tabs": []}]},
            {"group_id": "g2", "label": "Nhóm B", "agents": ["agent1"], "files": [], "folders": [],
             "sheets": [{"alias": "log", "sheet_id": "AAA", "access": "read", "tabs": []}]},
        ]
        check("cung alias cung sheet_id cung quyen o 2 nhom -> KHONG mo ho",
              (gc.resolve_sheet(same_acc, "Kế hoạch tuần") is None)
              and (gc.resolve_sheet(same_acc, "LOG") or {}).get("access") == "read")

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
        check("co file + folder", "Spreadsheet files" in pa and "Folders you may read and write in:" in pa
              and "- /home/ubuntu/Downloads (access: append)" in pa and "- /home/ubuntu/Desktop (access: write)" in pa)
        check("co cu phap ca 2 loai", '"action":"gsheet_append"' in pa and '"action":"xlsx_write"' in pa)
        check("KHONG lo sheet_id / cred_id", "1AbC_xyz" not in pa and "tok_123" not in pa)
        check("alias + tabs + access", '"Kế hoạch tuần" — tabs: Tasks, Log (access: append)' in pa)
        check("nhom dien hinh < 2000 ky tu", len(pa) < 2000, str(len(pa)))
        pb = gc.prompt_block([gc.load("group_b")])
        check("chi sheet -> khong xlsx/Folders", "xlsx_" not in pb and "Spreadsheet files" not in pb and "Folders you may" not in pb)
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

        print("\n=== 12. registry: kinds dang ky / thu tu / go bo ===")
        from tubecli.extensions.file_manager import extension as fm_ext
        from tubecli.extensions.auth_manager import extension as am_ext

        gc.ensure_default_kinds()
        order_keys = [k.key for k in gc.kinds()]
        check("4 kind mac dinh theo thu tu notes, files, folders, sheets",
              order_keys == ["notes", "files", "folders", "sheets"], order_keys)
        check("GROUP_KINDS cua extension la nguon",
              gc.kind("files") is fm_ext.GROUP_KINDS[0] and gc.kind("sheets") is am_ext.GROUP_KINDS[0])
        check("kind(unknown) -> None", gc.kind("scripts") is None)

        def _script_norm(raw, i):
            if not isinstance(raw, dict) or not raw.get("cmd"):
                return None
            return {"alias": str(raw.get("alias") or f"script {i + 1}"), "cmd": str(raw["cmd"])[:200]}

        scripts_kind = gc.EntityKind(
            key="scripts", label="Scripts", normalise=_script_norm,
            describe=lambda es: ["Scripts you may run:"] + [f'- "{e["alias"]}"' for e in es],
            action_docs=lambda es: ['{"action":"run_script","script":"<alias>"}'], order=50)
        gc.register_kind(scripts_kind)
        check("dang ky kind moi -> xep sau theo order", [k.key for k in gc.kinds()][-1] == "scripts")
        gc.register_kind(gc.EntityKind(key="scripts", label="Scripts v2", normalise=_script_norm,
                                       describe=scripts_kind.describe, action_docs=scripts_kind.action_docs, order=5))
        check("dang ky lai cung key -> thay the (order moi, khong trung)",
              [k.key for k in gc.kinds()][0] == "scripts" and len([k for k in gc.kinds() if k.key == "scripts"]) == 1)
        gc.register_kind(scripts_kind)
        for bad in ("agents", "Bad Key", "", "canvas", "1x"):
            check(f"key kind {bad!r} bi tu choi",
                  raises(lambda: gc.EntityKind(key=bad, label="x", normalise=_script_norm, describe=lambda e: []), ValueError))
        check("register_kind(dict) bi tu choi", raises(lambda: gc.register_kind({"key": "x"}), TypeError))
        ps = gc.prompt_block([gc.save("group_s", {"scripts": [{"alias": "Deploy", "cmd": "make deploy"}, {"alias": "no cmd"}]})])
        check("kind moi: describe + action docs di vao prompt",
              "Scripts you may run:" in ps and '- "Deploy"' in ps and '"action":"run_script"' in ps and "no cmd" not in ps, ps)

        # Extension hook + ExtensionManager wiring: enable registers, disable withdraws.
        from tubecli.core import extension_manager as em_mod
        check("Extension.get_group_kinds mac dinh []", em_mod.Extension().get_group_kinds() == [])
        em_mod.EXTENSIONS_CONFIG_FILE = os.path.join(tmp, "extensions.json")

        class _KindExt(em_mod.Extension):
            name = "fake_kinds"

            def get_group_kinds(self):
                return [scripts_kind]

        class _BrokenExt(em_mod.Extension):
            name = "broken_kinds"

            def get_group_kinds(self):
                raise RuntimeError("boom")

        em = em_mod.ExtensionManager()
        em.register(_KindExt())
        check("register (chua enable) -> kind bi rut", gc.kind("scripts") is None)
        em.register(_BrokenExt())
        check("enable extension hong khong raise", em.enable("broken_kinds") is True)
        check("enable -> kind co mat", em.enable("fake_kinds") is True and gc.kind("scripts") is scripts_kind)
        check("disable -> kind bien mat", em.disable("fake_kinds") is True and gc.kind("scripts") is None)
        check("disable extension hong khong raise", em.disable("broken_kinds") is True)
        gc.ensure_default_kinds()
        check("ensure_default_kinds khong dong cham kind ngoai", gc.kind("scripts") is None)
        em.enable("fake_kinds")
        check("config ghi vao file tam, khong phai data that", os.path.exists(os.path.join(tmp, "extensions.json")))

        # A withdrawn default stays withdrawn: "disabled" must outlive the next prompt.
        gc.unregister_kind("sheets")
        gc.ensure_default_kinds()
        check("unregister sheets -> ensure_default_kinds khong hoi sinh", gc.kind("sheets") is None)
        pa_nosheets = gc.prompt_block([gc.load("group_a")])
        check("kind bi rut -> im lang trong prompt",
              "Google Sheets" not in pa_nosheets and "gsheet_" not in pa_nosheets and "Spreadsheet files" in pa_nosheets)
        check("kind bi rut -> khong co o view hop nhat", "sheets" not in gc.load("group_a"))
        check("...nhung van nam trong canvas tren dia (verbatim)", len(gc.load("group_a")["canvas"]["sheets"]) == 2)
        gc.save("group_a", SPEC_GROUP)
        check("PUT khi kind bi rut -> danh sach giu nguyen verbatim (3 entry tho)",
              len(gc.load("group_a")["canvas"]["sheets"]) == 3)
        gc.register_kind(am_ext.GROUP_KINDS[0])
        check("dang ky lai -> chuan hoa lai tu verbatim (2 sheet, 1 worklog)",
              len(gc.load("group_a")["sheets"]) == 2 and gc.load("group_a")["sheets"][0]["role"] == "worklog"
              and gc.load("group_a")["sheets"][1]["role"] == "")
        check("unregister key la khong sao", gc.unregister_kind("nope") is None)

        print("\n=== 13. kind chua dang ky: giu verbatim, im lang ===")
        raw_bp = [{"alias": "Work", "profile": "p1", "extra": {"k": 1}}, "plain-string", 7]
        st = gc.save("group_v", {"agents": ["agent1"], "browser_profiles": raw_bp,
                                  "files": [{"path": "/srv/v.xlsx"}]})
        check("list la -> khong o view hop nhat", "browser_profiles" not in st)
        check("...nhung nam nguyen trong canvas", st["canvas"]["browser_profiles"] == raw_bp)
        on_disk = json.load(open(os.path.join(tmp, "groups", "group_v.json"), encoding="utf-8"))
        check("tren dia: canvas/server tach doi, list la o canvas",
              on_disk["canvas"]["browser_profiles"] == raw_bp and "server" in on_disk and "files" not in on_disk)
        check("load giu verbatim", gc.load("group_v")["canvas"]["browser_profiles"] == raw_bp)
        pv = gc.prompt_block([gc.load("group_v")])
        check("prompt im lang ve kind la", "browser_profiles" not in pv and "p1" not in pv and "Spreadsheet files" in pv)
        check("gia tri khong phai list cua key la -> bo qua (khong loi)",
              "meta" not in gc.save("group_v", {"meta": {"a": 1}})["canvas"])
        big_v = gc.save("group_v", {"zzz": [{"i": i} for i in range(300)]})
        check("verbatim cap 200 entry", len(big_v["canvas"]["zzz"]) == 200)
        fat = gc.save("group_v", {"zzz": [{"blob": "x" * 1000} for _ in range(100)]})
        check("verbatim cap 64KB", len(json.dumps(fat["canvas"]["zzz"])) <= 64 * 1024 and 0 < len(fat["canvas"]["zzz"]) < 100)
        check("key dang ky khong phai list van bi tu choi", raises(lambda: gc.save("group_v", {"notes": "x"}), ValueError))
        # Cap tung list chua du: ten key, so key va tong byte cung phai bi chan.

        def _verbatim(ctx):
            return {k: v for k, v in ctx["canvas"].items() if k != "agents" and gc.kind(k) is None}

        odd = gc.save("group_v", {"Bad Key": [1], "": [1], "1x": [1], "x" * 33: [1], "a\nb": [1],
                                  "canvas": [1], "ok_key": [1]})
        check("key khong hop KIND_KEY_RE / reserved bi bo, key hop le giu",
              list(_verbatim(odd)) == ["ok_key"], list(_verbatim(odd)))
        wide = gc.save("group_v", {f"k{i:02d}": [i] for i in range(40)})
        check("toi da 16 key verbatim / section (40 -> 16 dau tien)",
              list(_verbatim(wide)) == [f"k{i:02d}" for i in range(16)], list(_verbatim(wide)))
        fat_keys = gc.save("group_v", {f"blob{i}": [{"b": "x" * 1000} for _ in range(60)] for i in range(8)})
        sizes = {k: len(json.dumps(v, ensure_ascii=False).encode("utf-8")) for k, v in _verbatim(fat_keys).items()}
        check("tong verbatim / section <= 256KB (8 x ~60KB -> khoang 4 list day)",
              200 * 1024 < sum(sizes.values()) <= 256 * 1024 and 4 <= len([s for s in sizes.values() if s > 2]) <= 5, sizes)
        kept, used = gc._cap_verbatim([{"b": "x" * 100} for _ in range(10)], 500)
        check("_cap_verbatim: 1 luot, size == json.dumps(prefix), <= budget",
              len(kept) == 4 and used <= 500 and used == len(json.dumps(kept, ensure_ascii=False).encode("utf-8"))
              and len(json.dumps(kept + [{"b": "x" * 100}], ensure_ascii=False).encode("utf-8")) > 500, (len(kept), used))
        t0 = time.time()
        huge = gc.save("group_v", {"zzz": [{"blob": "x" * (64 * 1024)} for _ in range(200)]})
        dt = time.time() - t0
        check("200 x 64KB: moi entry qua cap -> [] va khong O(n^2) (< 2s)",
              huge["canvas"]["zzz"] == [] and dt < 2.0, f"{dt:.2f}s")

        print("\n=== 14. notes: playbook cua nhom ===")
        long_text = "Rule one\n" + "y" * 2500
        st = gc.save("group_n", {
            "agents": ["agent1"],
            "notes": [
                {"alias": "Weekly routine", "text": "Post on Monday.\r\nReview on Friday."},
                {"text": long_text},
                {"text": "   \n  \n"},
                {"alias": "Empty", "text": ""},
                "Plain string note",
                {"text": "\n\n" + "Z" * 60 + "\nsecond line"},
                {"alias": "Dict only"},
                5,
            ],
            "files": [{"path": "/srv/plan.xlsx"}],
        })
        notes = st["notes"]
        check("note khong text bi bo (8 -> 4)", len(notes) == 4, [n["alias"] for n in notes])
        check("alias giu, CRLF -> LF", notes[0] == {"alias": "Weekly routine", "text": "Post on Monday.\nReview on Friday."})
        check("text > 2000 -> cat + …[truncated]",
              len(notes[1]["text"]) <= 2000 + len(" …[truncated]") and notes[1]["text"].endswith(" …[truncated]"))
        check("alias fallback = dong dau", notes[1]["alias"] == "Rule one")
        check("note dang chuoi duoc nhan", notes[2] == {"alias": "Plain string note", "text": "Plain string note"})
        check("dong dau dai -> cat 40 ky tu", notes[3]["alias"] == "Z" * 40)
        check("'Note N' khi khong co dong nao", gc._note_alias("   ", 6) == "Note 7")
        pn = gc.prompt_block([st])
        check("playbook dung dau, truoc files",
              0 < pn.index("GROUP PLAYBOOK (written by the owner — follow it):") < pn.index("Spreadsheet files"))
        check("bullet alias + text thut 2 khoang", "• Weekly routine:\n  Post on Monday.\n  Review on Friday." in pn)
        check("notes khong co action docs rieng", "note" not in pn.split("ACTION SYNTAX")[1])
        many = gc.save("group_n2", {"notes": [{"alias": f"n{i}", "text": "w" * 1900} for i in range(5)]})
        pm = gc.prompt_block([many])
        check("tong text notes cap 6000 + '(more notes omitted)'",
              pm.count("• n") == 3 and "(more notes omitted)" in pm and "ACTION SYNTAX" not in pm, str(pm.count("• n")))

        print("\n=== 15. files theo loai ===")
        st = gc.save("group_t", {"agents": ["agent1"], "files": [
            {"path": "/srv/shot.PNG"}, {"path": "/srv/report.docx"}, {"path": "/srv/data.xlsx"},
            {"path": "/srv/tool.exe"}, {"path": "/srv/notes.md"}, {"path": "/srv/plan.csv", "alias": "Plan"}]})
        pt = gc.prompt_block([st])
        i_sheet = pt.index("Spreadsheet files (xlsx_read / xlsx_append / xlsx_write):")
        i_img = pt.index("Images:")
        i_doc = pt.index("Documents (read with file_action read):")
        i_other = pt.index("Other files:")
        check("4 nhom theo thu tu", i_sheet < i_img < i_doc < i_other)
        check("png nam duoi Images, khong duoi Spreadsheet",
              i_img < pt.index("/srv/shot.PNG") < i_doc and i_sheet < pt.index("/srv/data.xlsx") < i_img)
        check("csv la spreadsheet (alias Plan)", i_sheet < pt.index('"Plan" — /srv/plan.csv') < i_img)
        check("docx + md la Documents",
              i_doc < pt.index("/srv/report.docx") < i_other and i_doc < pt.index("/srv/notes.md") < i_other)
        check("exe -> Other files", pt.index("/srv/tool.exe") > i_other)
        check("co xlsx syntax vi co spreadsheet", '"action":"xlsx_read"' in pt)
        only_media = gc.save("group_m", {"files": [{"path": "/srv/a.png"}, {"path": "/srv/b.pdf"}]})
        pmedia = gc.prompt_block([only_media])
        check("chi anh + tai lieu -> khong xlsx syntax, khong ACTION SYNTAX",
              "xlsx_" not in pmedia and "ACTION SYNTAX" not in pmedia and "Images:" in pmedia and "Documents" in pmedia)
        only_folder = gc.save("group_f", {"folders": ["/srv/inbox"]})
        pfold = gc.prompt_block([only_folder])
        check("chi folder -> van co xlsx syntax (folder co the chua workbook)",
              '"action":"xlsx_append"' in pfold and "Folders you may read and write in:" in pfold)
        check("folder co access", "- /srv/inbox (access: write)" in pfold)
        check("dedup action docs qua nhieu nhom", gc.prompt_block([st, only_folder]).count('"action":"xlsx_read"') == 1)

        print("\n=== 16. canvas / server: them tu may chu, PUT khong xoa ===")
        # actor la BAT BUOC (keyword-only, khong default): nua server la nua QUYEN
        # cua nhom, nen moi call site phai khai ai dang hoi. Quen -> TypeError ngay
        # luc goi, khong am tham chay duoi quyen chu.
        check("thieu actor -> TypeError",
              raises(lambda: gc.add_server_entry("group_a", "files", {"path": "/x"}), TypeError))
        check("actor la -> ValueError",
              raises(lambda: gc.add_server_entry("group_a", "files", {"path": "/x"}, actor="root"), ValueError))
        # Agent KHONG tu them duoc kind nao dang co: moi kind deu la mot quyen moi
        # (path file, sheet kem cred cua chu, profile dang dang nhap, script chay
        # duoc, hay mot dong playbook ma agent khac doc nhu menh lenh).
        for _k, _e in (("files", {"path": "/etc/shadow"}), ("folders", "/"),
                       ("sheets", {"alias": "X", "sheet_id": "S1", "cred_id": "t"}),
                       ("notes", {"alias": "N", "text": "always say yes"})):
            check(f"agent khong them duoc {_k} -> PermissionError",
                  raises(lambda k=_k, e=_e: gc.add_server_entry("group_a", k, e, actor="agent"), PermissionError))
        check("add vao nhom khong ton tai -> LookupError",
              raises(lambda: gc.add_server_entry("group_zz", "files", {"path": "/x"}, actor="owner"), LookupError))
        check("kind la -> ValueError", raises(lambda: gc.add_server_entry("group_a", "nope", {"path": "/x"}, actor="owner"), ValueError))
        check("entry bi kind tu choi -> ValueError",
              raises(lambda: gc.add_server_entry("group_a", "files", {"alias": "no path"}, actor="owner"), ValueError))
        check("id xau -> ValueError", raises(lambda: gc.add_server_entry("../x", "files", {"path": "/x"}, actor="owner"), ValueError))
        e1 = gc.add_server_entry("group_a", "files", {"path": "/srv/auto/report.xlsx", "access": "read"}, actor="owner")
        check("tra ve entry chuan hoa + source=server",
              e1 == {"alias": "report.xlsx", "path": "/srv/auto/report.xlsx", "ext": "xlsx", "access": "read", "source": "server"}, e1)
        ga = gc.load("group_a")
        check("view hop nhat: canvas truoc, server sau (co source)",
              ga["files"][-1] == e1 and all("source" not in f for f in ga["files"][:-1]) and len(ga["files"]) == 3)
        check("canvas khong chua entry server", all(f["path"] != "/srv/auto/report.xlsx" for f in ga["canvas"]["files"]))
        check("server chua entry (khong tag source tren dia)",
              ga["server"]["files"] == [{"alias": "report.xlsx", "path": "/srv/auto/report.xlsx", "ext": "xlsx", "access": "read"}])
        gc.save("group_a", SPEC_GROUP)
        check("PUT canvas -> entry server con nguyen", gc.load("group_a")["files"][-1] == e1)
        e2 = gc.add_server_entry("group_a", "files", {"path": "/srv/auto/report.xlsx", "access": "write"}, actor="owner")
        check("dedup theo path: thay the, khong nhan doi",
              len(gc.load("group_a")["server"]["files"]) == 1 and e2["access"] == "write")
        gc.add_server_entry("group_a", "notes", {"alias": "Learned", "text": "Always CC the editor."}, actor="owner")
        gc.add_server_entry("group_a", "notes", {"alias": "learned", "text": "Always CC the editor (v2)."}, actor="owner")
        check("dedup notes theo alias (casefold)",
              [n["text"] for n in gc.load("group_a")["server"]["notes"]] == ["Always CC the editor (v2)."])
        gc.add_server_entry("group_a", "sheets", {"alias": "Auto log", "sheet_id": "SRV1", "cred_id": "tok_9", "role": "worklog"}, actor="owner")
        gc.add_server_entry("group_a", "sheets", {"alias": "Auto log 2", "sheet_id": "SRV1", "cred_id": "tok_9"}, actor="owner")
        check("dedup sheets theo sheet_id", [s["alias"] for s in gc.load("group_a")["server"]["sheets"]] == ["Auto log 2"])
        pa2 = gc.prompt_block([gc.load("group_a")])
        check("prompt ke ca entry server",
              "/srv/auto/report.xlsx" in pa2 and "• learned:" in pa2 and '"Auto log 2"' in pa2
              and "SRV1" not in pa2 and "tok_9" not in pa2)
        check("resolve_xlsx thay file server",
              (gc.resolve_xlsx(gc.effective_groups("agent1", "group_a"), "/srv/auto/report.xlsx") or {}).get("access") == "write")
        # Echoing the merged view back (GET then PUT, flat) must not copy server entries into the canvas.
        gc.save("group_a", {k: v for k, v in gc.load("group_a").items() if k not in ("canvas", "server")})
        ga = gc.load("group_a")
        check("PUT lai view hop nhat (phang) -> khong nhan doi vao canvas",
              len([f for f in ga["files"] if f["path"] == "/srv/auto/report.xlsx"]) == 1 and ga["files"][-1]["source"] == "server")
        gc.save("group_a", gc.load("group_a"))
        check("PUT lai view hop nhat (co canvas/server) -> nhu tren",
              len([f for f in gc.load("group_a")["files"] if f["path"] == "/srv/auto/report.xlsx"]) == 1)
        check("remove theo predicate -> 1",
              gc.remove_server_entry("group_a", "files", lambda e: e["path"] == "/srv/auto/report.xlsx") == 1)
        check("remove lan 2 -> 0",
              gc.remove_server_entry("group_a", "files", lambda e: e["path"] == "/srv/auto/report.xlsx") == 0)
        check("remove nhom khong ton tai -> 0", gc.remove_server_entry("group_zz", "files", lambda e: True) == 0)
        check("remove kind la -> ValueError", raises(lambda: gc.remove_server_entry("group_a", "nope", lambda e: True), ValueError))
        # routes — nua server doi PHIEN CHU THAT. Gate trong server.py cho loopback
        # di thang, ma run_api cua model cung ra dung cua do, nen "den tu 127.0.0.1"
        # khong con duoc tinh la chu o hai route nay.
        from tubecli.core import auth as _auth
        check("POST khong co phien chu -> 403",
              c.post("/api/v1/groups/group_a/server/files", json={"path": "/srv/x.csv"}).status_code == 403)
        check("DELETE khong co phien chu -> 403",
              c.delete("/api/v1/groups/group_a/server/files", params={"path": "/srv/x.csv"}).status_code == 403)
        check("cookie phien rac -> 403",
              c.post("/api/v1/groups/group_a/server/files", json={"path": "/srv/x.csv"},
                     cookies={_auth.SESSION_COOKIE: "not-a-session"}).status_code == 403)
        check("khong co gi duoc ghi khi bi tu choi",
              all(f["path"] != "/srv/x.csv" for f in gc.load("group_a")["server"]["files"]))
        co = TestClient(app_)
        co.cookies.set(_auth.SESSION_COOKIE, _auth.create_session())
        r = co.post("/api/v1/groups/group_a/server/files", json={"path": "/srv/auto/weekly.csv"})
        check("POST server entry (co phien chu) -> ok + entry",
              r.status_code == 200 and r.json()["entry"]["source"] == "server" and r.json()["entry"]["ext"] == "csv", r.text[:200])
        check("GET context thay entry server",
              any(f.get("source") == "server" and f["path"] == "/srv/auto/weekly.csv"
                  for f in c.get("/api/v1/groups/group_a/context").json()["files"]))
        check("POST nhom khong ton tai -> 404", co.post("/api/v1/groups/group_zz/server/files", json={"path": "/x"}).status_code == 404)
        check("POST kind la -> 400", co.post("/api/v1/groups/group_a/server/nope", json={"path": "/x"}).status_code == 400)
        check("POST entry hong -> 400", co.post("/api/v1/groups/group_a/server/files", json={"alias": "x"}).status_code == 400)
        check("POST body khong phai object -> 400", co.post("/api/v1/groups/group_a/server/files", json=[1]).status_code == 400)
        check("POST id xau -> 400", co.post("/api/v1/groups/a.b/server/files", json={"path": "/x"}).status_code == 400)
        check("DELETE khong selector -> 400", co.delete("/api/v1/groups/group_a/server/files").status_code == 400)
        echo_path = "/srv/auto/../auto/WEEKLY.csv" if os.name == "nt" else "/srv/auto/../auto/weekly.csv"
        r = co.delete("/api/v1/groups/group_a/server/files", params={"path": echo_path})
        check("DELETE theo path (canonical) -> removed 1", r.status_code == 200 and r.json()["removed"] == 1, r.text)
        check("DELETE lan 2 -> removed 0",
              co.delete("/api/v1/groups/group_a/server/files", params={"path": "/srv/auto/weekly.csv"}).json()["removed"] == 0)
        r = co.delete("/api/v1/groups/group_a/server/notes", params={"alias": "LEARNED"})
        check("DELETE theo alias (casefold) -> 1", r.json()["removed"] == 1, r.text)
        check("DELETE theo sheet_id -> 1",
              co.delete("/api/v1/groups/group_a/server/sheets", params={"sheet_id": "SRV1"}).json()["removed"] == 1)
        check("DELETE kind la -> 400", co.delete("/api/v1/groups/group_a/server/nope", params={"alias": "x"}).status_code == 400)
        check("server trong lai", all(v == [] for v in gc.load("group_a")["server"].values()))

        print("\n=== 17. file phang (phase 1) -> doc nhu canvas ===")
        flat = {"group_id": "group_old", "label": "Old", "updated_at": "2026-01-01T00:00:00Z",
                "agents": ["agent1"],
                "files": [{"alias": "a.xlsx", "path": "/old/a.xlsx", "ext": "xlsx", "access": "write"}],
                "folders": [],
                "sheets": [{"alias": "S", "sheet_id": "OLD1", "cred_id": "t", "tabs": ["Log"], "default_tab": "Log",
                            "access": "read", "role": "worklog"}]}
        with open(os.path.join(tmp, "groups", "group_old.json"), "w", encoding="utf-8") as f:
            json.dump(flat, f)
        old = gc.load("group_old")
        check("load file phang: agents + files + sheets o canvas",
              old["agents"] == ["agent1"] and old["canvas"]["files"][0]["path"] == "/old/a.xlsx"
              and old["canvas"]["sheets"][0]["sheet_id"] == "OLD1")
        check("file phang: server rong, notes []",
              all(v == [] for v in old["server"].values()) and old["notes"] == [] and old["canvas"]["notes"] == [])
        check("view hop nhat nhu cu",
              old["files"][0]["alias"] == "a.xlsx" and old["sheets"][0]["role"] == "worklog" and "source" not in old["files"][0])
        check("label + updated_at giu", old["label"] == "Old" and old["updated_at"] == "2026-01-01T00:00:00Z")
        gc.add_server_entry("group_old", "folders", "/old/out", actor="owner")
        on_disk = json.load(open(os.path.join(tmp, "groups", "group_old.json"), encoding="utf-8"))
        check("ghi lai -> dang tach canvas/server, khong con list o top-level",
              "canvas" in on_disk and "server" in on_disk and "files" not in on_disk
              and on_disk["server"]["folders"] == [{"path": "/old/out", "access": "write"}])
        check("canvas cu van con sau khi them server", gc.load("group_old")["files"][0]["path"] == "/old/a.xlsx")
        gc.save("group_old", {"agents": ["agent1"], "files": []})
        check("PUT sau migration: canvas thay, server giu",
              gc.load("group_old")["files"] == []
              and gc.load("group_old")["folders"][0] == {"path": "/old/out", "access": "write", "source": "server"})
        print("\n=== 18. data/groups nam ngoai sandbox cua AI ===")
        from tubecli.extensions.file_manager import file_service as fs_mod

        # tmp nam duoi ~/AppData/Local tren Windows — BLOCKED_PATHS chan moi nguoi o
        # do — nen dung mot data dir KHONG ton tai duoi ~/Documents (root cho phep):
        # validate_path khong can no ton tai, va khong duoc tao ra gi tren dia.
        fake_data = os.path.join(os.path.expanduser("~/Documents"), "tubecli-groups-test-does-not-exist")
        gdir = os.path.join(fake_data, "groups")
        cfg.DATA_DIR = pathlib.Path(fake_data)
        try:
            ai = fs_mod.FileService(enforce_roots=True)
        finally:
            cfg.DATA_DIR = pathlib.Path(tmp)
        try:
            check("DATA_DIR/groups nam trong ai_blocked",
                  any(os.path.normcase(b) == os.path.normcase(os.path.normpath(gdir)) for b in ai.ai_blocked), ai.ai_blocked)
            check("phan con lai cua data dir van mo cho AI",
                  ai.validate_path(os.path.join(fake_data, "exports", "x.txt")).endswith("x.txt"))
            attempts = {
                "validate_path": lambda: ai.validate_path(os.path.join(gdir, "group_a.json")),
                "create_file": lambda: ai.create_file(os.path.join(gdir, "group_a.json"), '{"agents":["evil"]}'),
                "read_file": lambda: ai.read_file(os.path.join(gdir, "group_a.json")),
                "list_dir": lambda: ai.list_dir(gdir),
                "delete": lambda: ai.delete(os.path.join(gdir, "group_a.json")),
                "create_folder": lambda: ai.create_folder(os.path.join(gdir, "sub")),
                "'..' vao groups": lambda: ai.validate_path(os.path.join(fake_data, "exports", "..", "groups", "g.json")),
                "chinh thu muc groups": lambda: ai.validate_path(gdir),
                "hoa/thuong (Windows)": lambda: ai.validate_path(os.path.join(fake_data, "GROUPS", "g.json")) if os.name == "nt" else ai.validate_path(gdir),
            }
            for name, fn in attempts.items():
                check(f"AI {name} trong groups/ -> ValueError", raises(fn, ValueError))
            check("khong co gi duoc tao tren dia", not os.path.exists(fake_data))
            check("groups_x ben canh KHONG bi chan (tach theo os.sep)",
                  ai.validate_path(os.path.join(fake_data, "groups_x", "y.txt")).endswith("y.txt"))
            sandbox_groups = os.path.join(os.path.abspath(os.environ.get("TUBECLI_DATA_DIR", "data")), "groups", "z.json")
            check("singleton file_action chan <cwd>/data/groups",
                  raises(lambda: fs_mod.file_service.validate_path(sandbox_groups), ValueError))
            check("UI (enforce_roots=False) van mo groups/ cho chu may",
                  fs_mod.user_file_service.validate_path(os.path.join(gdir, "group_a.json")).endswith("group_a.json"))
        finally:
            shutil.rmtree(fake_data, ignore_errors=True)
        print("\n=== 19. resolve_entry / only_entry / resolve_file: nguyen lieu goi theo TEN ===")
        # Hai kind nay se do extension browser / browser_scripts mang toi (spec 2b).
        # Dinh nghia ban sao o day de resolver duoc thu tren identity KHONG phai alias,
        # va de test khong phu thuoc vao extension nao da load.
        def _profile_norm(raw, i):
            if isinstance(raw, str):
                raw = {"profile": raw}
            if not isinstance(raw, dict):
                return None
            name = gc.norm_str(raw.get("profile"), 200)
            if not name:
                return None
            return {"alias": gc.norm_str(raw.get("alias"), 200) or name, "profile": name,
                    "access": gc.norm_access(raw.get("access"), "use")}

        def _script_norm2(raw, i):
            if not isinstance(raw, dict):
                return None
            sid = gc.norm_str(raw.get("script_id"), 200)
            if not sid:
                return None
            slug = gc.norm_str(raw.get("slug"), 200)
            return {"alias": gc.norm_str(raw.get("alias"), 200) or slug or f"Script {i + 1}",
                    "script_id": sid, "slug": slug,
                    "access": gc.norm_access(raw.get("access"), "run")}

        gc.register_kind(gc.EntityKind(
            key="profiles", label="Browser profiles", normalise=_profile_norm,
            describe=lambda es: ["Browser profiles you may drive:"] + [f'- "{e["alias"]}"' for e in es],
            access_default="use", order=25, identity="profile"))
        gc.register_kind(gc.EntityKind(
            key="scripts", label="Browser scripts", normalise=_script_norm2,
            describe=lambda es: ["Browser scripts you may run:"] + [f'- "{e["alias"]}"' for e in es],
            access_default="run", order=35, identity="script_id"))

        open(os.path.join(d5, "poster.png"), "wb").close()
        gc.save("group_2b", {
            "label": "Studio", "agents": ["agent2b"],
            "profiles": [{"alias": "Tuấn", "profile": "tuan5"},
                         {"profile": "ads1", "access": "manage"}, {"profile": ""}],
            "scripts": [{"alias": "Upload TikTok", "script_id": "sc_1", "slug": "upload-tiktok"},
                        {"script_id": "sc_2", "slug": "warmup"}],
            "files": [{"alias": "Poster", "path": os.path.join(d5, "poster.png")},
                      {"path": os.path.join(d50, "a.xlsx")},
                      {"alias": "Tuong doi", "path": "relative/x.xlsx"}],
            "folders": [{"path": d5, "access": "append"}],
        })
        g2b = gc.effective_groups("agent2b")
        check("nhom 2b co profiles/scripts sau khi dang ky kind",
              len(g2b) == 1 and len(g2b[0]["profiles"]) == 2 and len(g2b[0]["scripts"]) == 2)

        r = gc.resolve_entry(g2b, "profiles", "  tuẤn ")
        check("resolve_entry theo alias (casefold + trim)", (r or {}).get("profile") == "tuan5", r)
        check("kem group_id + group_label", r["group_id"] == "group_2b" and r["group_label"] == "Studio")
        check("resolve_entry theo identity (ten profile, khong phai alias)",
              (gc.resolve_entry(g2b, "profiles", "tuan5") or {}).get("alias") == "Tuấn")
        check("alias mac dinh = profile", (gc.resolve_entry(g2b, "profiles", "ADS1") or {}).get("access") == "manage")
        check("profile ngoai nhom -> None", gc.resolve_entry(g2b, "profiles", "tuan50") is None)
        check("ref rong / kind rong -> None",
              gc.resolve_entry(g2b, "profiles", "") is None and gc.resolve_entry(g2b, "", "tuan5") is None
              and gc.resolve_entry(g2b, "profiles", None) is None)
        check("khong nhom -> None", gc.resolve_entry([], "profiles", "tuan5") is None
              and gc.resolve_entry(None, "profiles", "tuan5") is None)
        check("script theo alias", (gc.resolve_entry(g2b, "scripts", "upload tiktok") or {}).get("script_id") == "sc_1")
        check("script theo slug (alias mac dinh = slug)", (gc.resolve_entry(g2b, "scripts", "Warmup") or {}).get("script_id") == "sc_2")
        check("script theo id", (gc.resolve_entry(g2b, "scripts", "sc_2") or {}).get("slug") == "warmup")
        # Id so KHOP TUYET DOI: hai id chi khac hoa/thuong la hai id khac nhau.
        check("id sai hoa/thuong -> None", gc.resolve_entry(g2b, "scripts", "SC_2") is None)
        check("kind khong co trong nhom -> None", gc.resolve_entry(g2b, "notes", "bat ky") is None)
        check("access mac dinh cua kind duoc giu",
              gc.resolve_entry(g2b, "profiles", "Tuấn")["access"] == "use"
              and gc.resolve_entry(g2b, "scripts", "sc_1")["access"] == "run")
        # sheets van di qua resolve_sheet: nguoi dung dan ca URL bang tinh.
        check("kind sheets -> uy quyen cho resolve_sheet (URL van khop)",
              (gc.resolve_entry(gc.effective_groups("agent1"), "sheets",
                                "https://docs.google.com/spreadsheets/d/2DeF/edit") or {}).get("alias") == "Second log")
        # Kind chua dang ky (extension tat): chi con alias — load() da bo entry khoi
        # view hop nhat roi, day chi la luoi an toan cho scope tu dung tay.
        hand = [{"group_id": "gx", "label": "Tay", "widgets": [{"alias": "Nut do", "widget_id": "w1"}]}]
        check("kind la: khop alias, khong khop identity la",
              (gc.resolve_entry(hand, "widgets", "nut do") or {}).get("widget_id") == "w1"
              and gc.resolve_entry(hand, "widgets", "w1") is None)

        twin_p = [
            {"group_id": "g1", "label": "Nhóm A", "agents": ["a"], "profiles": [{"alias": "Chính", "profile": "p_a", "access": "use"}]},
            {"group_id": "g2", "label": "Nhóm B", "agents": ["a"], "profiles": [{"alias": "chính", "profile": "p_b", "access": "manage"}]},
        ]
        amb = gc.resolve_entry(twin_p, "profiles", "CHÍNH")
        check("mot ten, hai profile khac nhau -> ambiguous", isinstance(amb, dict) and amb.get("ambiguous") is True)
        check("ambiguous chi lo alias + nhan nhom",
              {c["group_label"] for c in amb["choices"]} == {"Nhóm A", "Nhóm B"}
              and "p_a" not in str(amb) and "p_b" not in str(amb))
        same_p = [
            {"group_id": "g1", "label": "Nhóm A", "profiles": [{"alias": "A", "profile": "p_x", "access": "use"}]},
            {"group_id": "g2", "label": "Nhóm B", "profiles": [{"alias": "B", "profile": "p_x", "access": "manage"}]},
        ]
        r = gc.resolve_entry(same_p, "profiles", "p_x")
        # ĐỔI (G0 §7): cùng MỘT profile nhưng nhóm A cho "use", nhóm B cho
        # "manage" — bản cũ trả về "manage", tức là quyền của bàn B theo agent
        # sang bàn A. Nay là mơ hồ: chỉ chủ nhóm mới trả lời được câu "định cho
        # nó làm gì", và trả lời bằng cách sửa canvas.
        check("cung profile, 2 nhom 2 muc quyen -> ambiguous (KHONG cong gop)",
              isinstance(r, dict) and r.get("ambiguous") is True, r)
        check("ambiguous vi quyen: khong lo ten profile",
              "p_x" not in str(r) and {c["group_label"] for c in r["choices"]} == {"Nhóm A", "Nhóm B"}, r)
        same_p_eq = [
            {"group_id": "g1", "label": "Nhóm A", "profiles": [{"alias": "A", "profile": "p_y", "access": "use"}]},
            {"group_id": "g2", "label": "Nhóm B", "profiles": [{"alias": "B", "profile": "p_y", "access": "use"}]},
        ]
        check("cung profile, 2 nhom CUNG mot muc -> mot ket qua",
              (gc.resolve_entry(same_p_eq, "profiles", "p_y") or {}).get("access") == "use")

        print("--- only_entry ---")
        check("2 profile -> None (phai hoi)", gc.only_entry(g2b, "profiles") is None)
        one = gc.save("group_one", {"label": "Mot", "agents": ["agent2c"],
                                    "profiles": [{"profile": "solo"}], "scripts": []})
        g1 = gc.effective_groups("agent2c")
        o = gc.only_entry(g1, "profiles")
        check("dung 1 profile -> tra ve kem nhom", (o or {}).get("profile") == "solo" and o["group_label"] == "Mot", o)
        check("kind rong -> None", gc.only_entry(g1, "scripts") is None)
        check("kind la / rong -> None", gc.only_entry(g1, "nope") is None and gc.only_entry(g1, "") is None)
        check("khong nhom -> None", gc.only_entry([], "profiles") is None and gc.only_entry(None, "profiles") is None)
        check("cung profile, 2 nhom CUNG muc -> van la MOT",
              (gc.only_entry(same_p_eq, "profiles") or {}).get("access") == "use")
        # ĐỔI (G0 §7): vẫn là một profile, nhưng "được làm gì với nó" thì hai
        # nhóm nói khác nhau — only_entry chỉ có một câu trả lời an toàn.
        check("cung profile, 2 nhom 2 muc quyen -> None (khong lay quyen rong nhat)",
              gc.only_entry(same_p, "profiles") is None)
        check("hai profile khac nhau o 2 nhom -> None", gc.only_entry(twin_p, "profiles") is None)
        check("only_entry cua scripts trong group_2b -> None (2 script)", gc.only_entry(g2b, "scripts") is None)

        print("--- resolve_file ---")
        rf = gc.resolve_file(g2b, "poster")
        check("theo alias, moi loai file (png cung duoc)",
              (rf or {}).get("path") == os.path.realpath(os.path.join(d5, "poster.png")), rf)
        check("kem access + nhom", rf["access"] == "write" and rf["group_id"] == "group_2b"
              and rf["group_label"] == "Studio" and rf["via"] == "file")
        check("theo path chinh xac cua entry",
              (gc.resolve_file(g2b, os.path.join(d50, "a.xlsx")) or {}).get("via") == "file")
        rf = gc.resolve_file(g2b, os.path.join(d5, "sub", "b.xlsx"))
        check("path CHI nam trong folder chia se -> via folder, access cua folder",
              (rf or {}).get("via") == "folder" and rf["access"] == "append" and rf["group_label"] == "Studio", rf)
        check("path '..' duoc gop truoc khi so",
              (gc.resolve_file(g2b, os.path.join(d5, "sub", "..", "a.xlsx")) or {}).get("via") == "folder")
        check("file ngoai nhom -> None", gc.resolve_file(g2b, os.path.join(tmp, "lone.xlsx")) is None)
        check("path model tu bia -> None", gc.resolve_file(g2b, "/etc/passwd") is None
              and gc.resolve_file(g2b, os.path.join(d50, "zzz.xlsx")) is None)
        check("alias khong co -> None", gc.resolve_file(g2b, "khong-ton-tai") is None)
        check("ref rong / khong nhom -> None",
              gc.resolve_file(g2b, "") is None and gc.resolve_file([], "poster") is None)
        # Entry co path tuong doi khong bao gio thanh duong dan thao tac: handler se
        # upload chinh chuoi nay, ma tuong doi thi phu thuoc cwd cua server.
        check("entry path tuong doi -> None (khong tra path tuong doi)",
              gc.resolve_file(g2b, "Tuong doi") is None)
        twin_f = [
            {"group_id": "g1", "label": "Nhóm A", "files": [{"alias": "Poster", "path": os.path.join(d5, "poster.png"), "access": "write"}]},
            {"group_id": "g2", "label": "Nhóm B", "files": [{"alias": "poster", "path": os.path.join(d50, "a.xlsx"), "access": "read"}]},
        ]
        ambf = gc.resolve_file(twin_f, "POSTER")
        check("mot alias, hai file khac nhau -> ambiguous",
              isinstance(ambf, dict) and ambf.get("ambiguous") is True
              and {c["group_label"] for c in ambf["choices"]} == {"Nhóm A", "Nhóm B"})
        if os.name == "nt":
            check("Windows: path khac hoa/thuong van khop",
                  (gc.resolve_file(g2b, os.path.join(d50, "A.XLSX")) or {}).get("via") == "file")

        print("\n=== 20. luot chay theo lich dung profile cua nhom ===")
        # KHONG import tubecli.api.server: import no chay extension_manager.
        # discover_extensions() (co the git clone, va se dang ky kind cua MOI
        # extension vao registry ma muc 12 vua kiem tra). Rut dung ham can thu
        # ra khoi source bang ast — thu duoc van la code that da landed.
        import ast

        server_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "tubecli", "api", "server.py")
        with open(server_src, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        picker = [n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_group_browser_profiles"]
        check("server.py co _group_browser_profiles", len(picker) == 1)
        ns = {"List": list}
        exec(compile(ast.Module(body=picker[:1], type_ignores=[]), server_src, "exec"), ns)
        pick = ns.get("_group_browser_profiles", lambda groups: [])
        gc.save("group_ads", {"label": "Ads", "agents": ["agent2b"],
                              "profiles": [{"profile": "ads_only", "access": "manage"},
                                           {"profile": "chi_xem", "access": "read"}]})
        got = sorted(pick(gc.effective_groups("agent2b")))
        check("chi lay profile cua nhom, bo cai duoi 'use'",
              got == [("ads1", "Studio"), ("ads_only", "Ads"), ("tuan5", "Studio")], got)
        check("agent khong co nhom -> [] (giu duong cu: allowed_profiles)",
              pick(gc.effective_groups("nobody")) == [] and pick([]) == [] and pick(None) == [])
        check("entry rac khong lam vo", pick([{"profiles": ["chuoi", None, {}]}, "x"]) == [])
        gc.unregister_kind("profiles")
        check("extension browser tat -> khong con profile nhom -> ve duong cu",
              pick(gc.effective_groups("agent2b")) == [])

        gc.unregister_kind("scripts")
    finally:
        cfg.DATA_DIR = saved
        sys.modules.pop("tubecli.extensions.auth_manager.gsheets", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
