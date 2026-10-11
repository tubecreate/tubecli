# -*- coding: utf-8 -*-
"""NHIỀU KHOÁ NODE Muse song song + huỷ từng khoá (11/10/2026 — user «thêm logic có thể sử dụng nhiều khoá song song và
có cơ chế huỷ copy khoá»). global_settings.json tạm, không đụng máy thật.

  A. khoá CŨ (muse_node_key, chuỗi thô) vẫn dùng được như khoá «legacy» — máy đang mượn không đứt khi lên bản mới
  B. thêm khoá: khoá cũ vẫn chạy; chỉ lưu BẢN BĂM + đuôi; khoá đầy đủ chỉ trả lúc tạo; trùng / quá ngắn / quá số → lỗi
  C. huỷ một khoá: chỉ khoá ấy ngừng; huỷ khoá legacy xoá muse_node_key
  D. node_key_ok: Bearer / trần, sai / ngắn → False; «lần dùng cuối» được nhớ
  E. set_settings(node_key=…) của hộp cũ: THÊM chứ không thay; chuỗi rỗng không xoá gì
  F. route: GET /node-keys, POST /node-key {label}, DELETE /node-keys/{id}; settings có node_keys, không lộ bản băm

Run:  python tests/muse_node_keys_test.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

TMP = Path(tempfile.mkdtemp(prefix="nodekeys_"))
import tubecli.config as cfg  # noqa: E402
cfg.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.core import muse as M  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


def disk():
    return json.loads(cfg.GLOBAL_SETTINGS_FILE.read_text(encoding="utf-8"))


OLD = "OLDkey-abcdefghijklmnop-9Jwd"
try:
    print("A. khoá cũ")
    cfg.set_global_setting("muse_node_key", OLD)
    ks = M.node_keys()
    ok(len(ks) == 1 and ks[0]["id"] == "legacy" and ks[0]["tail"] == "9Jwd" and ks[0]["legacy"], "khoá cũ hiện là legacy", ks)
    ok(M.node_key_ok("Bearer " + OLD) and M.node_key_ok(OLD), "khoá cũ vẫn mượn được (Bearer hoặc trần)")

    print("B. thêm khoá")
    a = M.add_node_key("tungho2")
    b = M.add_node_key("  contabo   vps ")
    ok(len(a["node_key"]) >= M.NODE_KEY_MIN and a["tail"] == a["node_key"][-4:] and b["label"] == "contabo vps",
       "khoá mới + nhãn gọn", (a, b))
    raw = json.dumps(disk())
    ok(a["node_key"] not in raw and b["node_key"] not in raw and M._key_hash(a["node_key"]) in raw,
       "đĩa chỉ giữ bản băm, không giữ khoá đầy đủ")
    ok(M.node_key_ok("Bearer " + a["node_key"]) and M.node_key_ok("Bearer " + b["node_key"]) and M.node_key_ok(OLD),
       "ba khoá chạy SONG SONG (cũ vẫn chạy)")
    ok([k["id"] for k in M.node_keys()] == ["legacy", a["id"], b["id"]] and all("hash" not in k for k in M.node_keys()),
       "node_keys: đủ ba, không lộ bản băm")
    for bad, why in ((a["node_key"], "trùng"), ("short", "quá ngắn")):
        try:
            M.add_node_key("", bad)
            ok(False, f"khoá {why} bị từ chối")
        except ValueError:
            ok(True, f"khoá {why} bị từ chối")
    old_max = M.MAX_NODE_KEYS
    M.MAX_NODE_KEYS = 3
    try:
        M.add_node_key("x")
        ok(False, "quá số khoá bị từ chối")
    except ValueError:
        ok(True, "quá số khoá bị từ chối")
    M.MAX_NODE_KEYS = old_max

    print("C. huỷ")
    ok(M.revoke_node_key(a["id"]) and not M.node_key_ok("Bearer " + a["node_key"]) and M.node_key_ok("Bearer " + b["node_key"])
       and M.node_key_ok(OLD), "huỷ khoá A: chỉ A ngừng, B và khoá cũ vẫn chạy")
    ok(not M.revoke_node_key("khong-co"), "huỷ id lạ → False")
    ok(M.revoke_node_key("legacy") and not M.node_key_ok(OLD) and disk().get("muse_node_key") == ""
       and M.node_key_ok("Bearer " + b["node_key"]), "huỷ khoá cũ: xoá muse_node_key, B vẫn chạy")

    print("D. kiểm khoá")
    ok(not M.node_key_ok("Bearer wrong-key-1234567890") and not M.node_key_ok("") and not M.node_key_ok(None)
       and not M.node_key_ok("Bearer abc"), "sai / rỗng / ngắn → False")
    M._KEY_USED.clear()
    M.node_key_ok("Bearer " + b["node_key"])
    row = [r for r in disk()["muse_node_keys"] if r["id"] == b["id"]][0]
    ok(row["last_used_at"] and [k for k in M.node_keys() if k["id"] == b["id"]][0]["last_used_at"],
       "lần dùng cuối được nhớ (đĩa + giao diện)", row)

    print("E. hộp cài đặt cũ")
    M.set_settings(node_key="manual-key-chosen-by-user-123")
    ok(M.node_key_ok("manual-key-chosen-by-user-123") and M.node_key_ok("Bearer " + b["node_key"]),
       "node_key=… THÊM khoá, khoá cũ vẫn chạy")
    n = len(M.node_keys())
    M.set_settings(node_key="")
    M.set_settings(node_key="manual-key-chosen-by-user-123")
    ok(len(M.node_keys()) == n, "chuỗi rỗng không xoá; gửi lại khoá đã có không thêm trùng")

    print("F. route")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tubecli.api.muse_routes import router as R
    app = FastAPI()
    app.include_router(R)
    cl = TestClient(app)
    made = cl.post("/api/v1/muse/node-key", json={"label": "máy mới"}).json()
    ok(made.get("node_key") and made.get("label") == "máy mới" and M.node_key_ok(made["node_key"]), "POST /node-key {label}")
    ok(cl.post("/api/v1/muse/node-key").status_code == 200, "POST /node-key không body (hộp thoại cũ)")
    lst = cl.get("/api/v1/muse/node-keys").json()
    ok(made["id"] in [k["id"] for k in lst["node_keys"]] and "hash" not in json.dumps(lst), "GET /node-keys", lst)
    st = cl.get("/api/v1/muse/settings").json()
    ok(st.get("node_keys") and st.get("node_key_set") and "hash" not in json.dumps(st.get("node_keys"))
       and "node_key" not in st, "settings có node_keys, không lộ khoá / bản băm")
    d = cl.delete(f"/api/v1/muse/node-keys/{made['id']}")
    ok(d.status_code == 200 and not M.node_key_ok(made["node_key"]) and cl.delete("/api/v1/muse/node-keys/zz").status_code == 404,
       "DELETE /node-keys/{id} + 404")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
