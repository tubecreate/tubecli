"""Một agent không được tự nới quyền cho chính nó.

Run:  python tests/group_privilege_test.py     (exit 0 = pass)

VÌ SAO CÓ FILE NÀY
    Nửa `server` của một nhóm là nửa QUYỀN: thứ gì nằm trong đó thì mọi agent
    trong nhóm chạm được. Đường ghi vào nó là POST /api/v1/groups/{id}/server/
    {kind} — route "chỉ chủ" theo nghĩa nó không nằm trong allowlist guest.
    Nhưng gate đăng nhập trong server.py cho LOOPBACK đi thẳng, mà run_api của
    chính model cũng ra đúng cái cửa đó. Nói cách khác: chặn ở endpoint là chưa
    chặn, vì cửa in-process vẫn mở.

    Nên khoá nằm ở TẦNG mà quyền thực sự đổi — group_context.add_server_entry —
    và route chỉ là lớp thứ hai:

    1. `actor` là keyword-only KHÔNG default: call site thứ tám viết năm sau
       phải khai ai đang hỏi, không thừa hưởng một mặc định trông có vẻ an toàn.
    2. actor="agent" chỉ thêm được kind trong AGENT_ADDABLE_KINDS (hôm nay là
       tập rỗng trên thực tế), và access bị kẹp ≤ access_default của kind.
    3. Route đòi cookie phiên chủ THẬT — "đến từ 127.0.0.1" không tính.

    Test này kiểm cả ba, và kiểm rằng một lần từ chối KHÔNG để lại gì trên đĩa.
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as cfg
from tubecli.core import auth
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


def main():
    tmp = tempfile.mkdtemp(prefix="tubecli_priv_")
    saved = cfg.DATA_DIR
    cfg.DATA_DIR = pathlib.Path(tmp)
    auth._sessions.clear()

    try:
        gc.ensure_default_kinds()
        gc.save("g1", {"agents": ["agent1"], "files": [{"path": "/srv/ok.xlsx"}]})

        print("=== 1. actor là bắt buộc ===")
        check("thiếu actor -> TypeError",
              raises(lambda: gc.add_server_entry("g1", "files", {"path": "/srv/x"}), TypeError))
        check("actor lạ -> ValueError",
              raises(lambda: gc.add_server_entry("g1", "files", {"path": "/srv/x"}, actor="admin"), ValueError))
        check("actor positional không được (keyword-only)",
              raises(lambda: gc.add_server_entry("g1", "files", {"path": "/srv/x"}, "owner"), TypeError))

        print("\n=== 2. agent không tự thêm được kind nào đang có ===")
        # Danh sách này là MỌI kind đăng ký thật, không phải danh sách chép tay:
        # extension nào thêm kind mới cũng bị test này bắt phải nghĩ lại.
        registered = [k.key for k in gc.kinds()]
        check("có kind để kiểm", len(registered) >= 1, registered)
        for key in registered:
            if key in gc.AGENT_ADDABLE_KINDS:
                continue
            entry = {"path": "/etc/shadow", "sheet_id": "S", "cred_id": "t", "alias": "A",
                     "text": "luôn nói có", "profile": "p", "script_id": "s", "access": "manage"}
            check(f"agent + {key} -> PermissionError",
                  raises(lambda k=key, e=entry: gc.add_server_entry("g1", k, e, actor="agent"),
                         PermissionError))
        after = gc.load("g1")
        check("bị từ chối thì KHÔNG ghi gì xuống đĩa",
              all(v == [] for v in after["server"].values()), after["server"])
        check("sheets/files/folders/profiles/scripts đều ngoài allowlist",
              not (gc.AGENT_ADDABLE_KINDS & {"sheets", "files", "folders", "profiles", "scripts", "notes"}),
              sorted(gc.AGENT_ADDABLE_KINDS))

        print("\n=== 3. kind trong allowlist: được thêm, nhưng access bị kẹp ===")
        # Đăng ký một kind giả đúng tên trong allowlist để kiểm phần "được phép"
        # mà không phải đợi extension thật ra đời.
        def _sched_norm(raw, index):
            if not isinstance(raw, dict) or not raw.get("alias"):
                return None
            return {"alias": gc.norm_str(raw.get("alias"), 80),
                    "access": gc.norm_access(raw.get("access"), "read")}

        gc.register_kind(gc.EntityKind(key="schedules", label="Schedules", normalise=_sched_norm,
                                       describe=lambda e: [], access_default="read", identity="alias"))
        try:
            e = gc.add_server_entry("g1", "schedules", {"alias": "Mỗi sáng", "access": "manage"},
                                    actor="agent")
            check("agent thêm được kind trong allowlist", e.get("alias") == "Mỗi sáng", e)
            check("access 'manage' bị kẹp về access_default 'read'", e.get("access") == "read", e)
            e2 = gc.add_server_entry("g1", "schedules", {"alias": "Chủ đặt", "access": "manage"},
                                     actor="owner")
            check("đường chủ KHÔNG bị kẹp (access_default là mặc định, không phải trần)",
                  e2.get("access") == "manage", e2)
            on_disk = json.load(open(os.path.join(tmp, "groups", "g1.json"), encoding="utf-8"))
            check("trên đĩa: entry của agent vẫn là read",
                  [s["access"] for s in on_disk["server"]["schedules"] if s["alias"] == "Mỗi sáng"] == ["read"],
                  on_disk["server"]["schedules"])
        finally:
            gc.unregister_kind("schedules")
            gc._withdrawn.discard("schedules")

        print("\n=== 4. route đòi phiên chủ thật ===")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from tubecli.api.group_routes import router

        app = FastAPI()
        app.include_router(router)

        anon = TestClient(app)
        r = anon.post("/api/v1/groups/g1/server/files", json={"path": "/srv/evil.xlsx"})
        check("POST không cookie -> 403", r.status_code == 403, r.text[:160])
        r = anon.delete("/api/v1/groups/g1/server/files", params={"path": "/srv/ok.xlsx"})
        check("DELETE không cookie -> 403", r.status_code == 403, r.text[:160])
        r = anon.post("/api/v1/groups/g1/server/files", json={"path": "/srv/evil.xlsx"},
                      cookies={auth.SESSION_COOKIE: "gt_khong-phai-phien"})
        check("cookie rác -> 403", r.status_code == 403, r.text[:160])
        r = anon.post("/api/v1/groups/g1/server/files", json={"path": "/srv/evil.xlsx"},
                      cookies={auth.GUEST_COOKIE: "gt_guest"})
        check("cookie guest không phải cookie chủ -> 403", r.status_code == 403, r.text[:160])
        # "Đến từ loopback" là đúng cái mà run_api dùng được: nó KHÔNG được tính.
        loop = TestClient(app, client=("127.0.0.1", 55555))
        r = loop.post("/api/v1/groups/g1/server/files", json={"path": "/srv/evil.xlsx"})
        check("gọi từ 127.0.0.1 mà không có phiên -> vẫn 403", r.status_code == 403, r.text[:160])
        check("không có gì lọt xuống đĩa qua route",
              all(f["path"] != "/srv/evil.xlsx" for f in gc.load("g1")["server"]["files"]),
              gc.load("g1")["server"]["files"])

        owner = TestClient(app)
        owner.cookies.set(auth.SESSION_COOKIE, auth.create_session())
        r = owner.post("/api/v1/groups/g1/server/files", json={"path": "/srv/auto/rep.xlsx"})
        check("chủ có phiên -> 200 + entry", r.status_code == 200 and r.json()["entry"]["source"] == "server",
              r.text[:200])
        r = owner.delete("/api/v1/groups/g1/server/files", params={"path": "/srv/auto/rep.xlsx"})
        check("chủ xoá được -> removed 1", r.status_code == 200 and r.json()["removed"] == 1, r.text[:200])

        # Phiên bị huỷ (chủ logout / đổi mật khẩu) thì cửa đóng lại ngay.
        auth._sessions.clear()
        r = owner.post("/api/v1/groups/g1/server/files", json={"path": "/srv/auto/rep2.xlsx"})
        check("phiên hết hiệu lực -> 403 ngay request kế tiếp", r.status_code == 403, r.text[:160])

    finally:
        cfg.DATA_DIR = saved
        auth._sessions.clear()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
