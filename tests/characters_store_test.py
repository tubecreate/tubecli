# -*- coding: utf-8 -*-
"""KHO NHÂN VẬT chung ở lõi (tubecli.core.characters + /api/v1/characters) và DÀN NHÂN VẬT của mẫu (templates.cast).

User 10/10/2026: «tạo 1 kho để khi tôi làm về nhân vật này có thể lấy để đồng nhất», chọn «kho ở lõi, mẫu mang dàn».

  A. lưu / đọc: thư mục <slug>/profile.json + sheet; prompt_name không dấu; sheet phải là ảnh
  B. khớp tên: tiếng Việt có dấu, chữ Hán, phiên âm; không khớp nửa từ; `only` (dàn mẫu); aliases=False bỏ biệt danh
  C. gói Chợ: bundle → install_bundle trên máy khác (sheet đi theo); slug đã có thì giữ bản máy này
  D. chuyển kho cũ content_studio/character_library sang kho lõi MỘT lần khi root() chạy lần đầu
  E. mẫu mang dàn: wizCast trong phần wizard ↔ t["cast"]; set_cast; summary có cast
  F. route: danh sách / một / sheet / match / chặn khách workspace

Run:  python tests/characters_store_test.py
"""
import base64
import json
import os
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

TMP = tempfile.mkdtemp(prefix="chars_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
from tubecli.core import characters as C  # noqa: E402
from tubecli.core import templates as T  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
LOOK = ("a lean young man about eighteen with sharp dark eyes, black hair in a high ponytail, faded grey-blue patched "
        "cross-collar tunic, dark belts, indigo wrap skirt, worn cloth boots, plain straight sword")
try:
    # D trước tiên: kho cũ có sẵn khi root() chạy LẦN ĐẦU
    old = os.path.join(TMP, "content_studio", "character_library", "ninh_dieu")
    os.makedirs(old)
    open(os.path.join(old, "sheet.png"), "wb").write(PNG)
    json.dump({"name": "Ninh Diêu", "aliases": ["宁姚"], "status": "draft", "sheet": "sheet.png"},
              open(os.path.join(old, "profile.json"), "w", encoding="utf-8"), ensure_ascii=False)

    print("D. chuyển kho cũ")
    base = C.root()
    ok(base == os.path.join(TMP, "characters") and os.path.isfile(os.path.join(base, "ninh_dieu", "sheet.png"))
       and C.get("宁姚")["name"] == "Ninh Diêu", "kho cũ của Content Studio sang DATA_DIR/characters (kèm sheet)",
       os.listdir(base))
    C.save({"name": "Ninh Diêu", "notes": "đã sửa ở kho lõi"})
    C._MIGRATED = False
    C.root()
    ok(C.get("ninh_dieu")["notes"] == "đã sửa ở kho lõi", "chạy lại không đè bản đã sửa ở kho lõi")

    print("A. lưu / đọc")
    src = os.path.join(TMP, "in.png")
    open(src, "wb").write(PNG)
    p = C.save({"name": "Trần Bình An", "aliases": ["Bình An", "陈平安", "Chen Ping'an"], "series": "Kiếm Lai",
                "look": LOOK, "status": "approved"}, sheet_src=src)
    ok(p["slug"] == "tran_binh_an" and p["prompt_name"] == "Tran Binh An" and p["kind"] == "person"
       and p["sheet_path"].endswith(os.path.join("tran_binh_an", "sheet.png")), "hồ sơ + sheet, prompt_name không dấu", p)
    p2 = C.save({"name": "Trần Bình An", "personality": "giữ lời"})
    ok(p2["look"] == LOOK and p2["status"] == "approved" and p2["personality"] == "giữ lời" and p2["sheet_path"],
       "sửa một trường thì giữ các trường khác + sheet", p2)
    bad = os.path.join(TMP, "secret.txt")
    open(bad, "w").write("x")
    try:
        C.save({"name": "X"}, sheet_src=bad)
        ok(False, "sheet không phải ảnh bị từ chối")
    except ValueError:
        ok(True, "sheet không phải ảnh bị từ chối")
    C.save({"name": "Bùi Tiền", "aliases": ["裴钱", "Pei Qian"], "look": "short"},
           sheet_data="data:image/jpeg;base64," + base64.b64encode(PNG).decode())
    ok(C.get("Bùi Tiền")["sheet_path"].endswith("sheet.jpg"), "sheet từ data URL (jpeg → .jpg)")

    print("B. khớp tên")
    m = [x["slug"] for x in C.match("Năm ấy, Bùi Tiền theo sư phụ Trần Bình An lên núi.")]
    ok(m == ["bui_tien", "tran_binh_an"], "tiếng Việt có dấu, theo thứ tự xuất hiện", m)
    ok([x["slug"] for x in C.match("陈平安说了一句话")] == ["tran_binh_an"]
       and [x["slug"] for x in C.match("CHEN PING'AN walks")] == ["tran_binh_an"], "chữ Hán + phiên âm")
    ok(C.match("Trần Bình Anh là ai") == [], "không khớp nửa từ («Bình Anh»)")
    ok([x["slug"] for x in C.match("Trần Bình An và Bùi Tiền", only=["bui_tien"])] == ["bui_tien"],
       "only = dàn của mẫu: chỉ xét nhân vật trong dàn")
    ok(C.match("Sống bình an giữa đời", aliases=False) == [] and C.match("Sống bình an giữa đời"),
       "aliases=False: biệt danh chữ thường («bình an») không kéo nhân vật vào")
    ents = C.as_canon(C.match("Trần Bình An và Bùi Tiền"))
    ok(len(ents) == 1 and ents[0]["name"] == "Tran Binh An" and ents[0]["from"] == "library" and ents[0]["sheet"],
       "as_canon: chỉ hồ sơ có look đủ dài", ents)

    print("C. gói Chợ")
    items = C.bundle(["tran_binh_an", "khong_co"])
    ok(len(items) == 1 and items[0]["sheet_data"].startswith("data:image/png;base64,")
       and "sheet_path" not in items[0]["profile"], "bundle: hồ sơ + sheet base64, không lộ đường dẫn máy", items[0]["profile"])
    other = os.path.join(TMP, "other_machine")
    os.makedirs(other)
    C.save({"name": "Trần Bình An", "look": "machine copy keeps its own look text here ok"}, base=other)
    done = C.install_bundle(items + [{"profile": {"name": "A Lương"}}], base=other)
    ok(done == ["tran_binh_an", "a_luong"] and C.get("tran_binh_an", other)["look"].startswith("machine copy")
       and C.get("a_luong", other), "install: slug đã có giữ bản máy này; mới thì cài", done)
    C.install_bundle(items, base=other, overwrite=True)
    q = C.get("tran_binh_an", other)
    ok(q["look"] == LOOK and q["sheet_path"] and open(q["sheet_path"], "rb").read() == PNG, "overwrite: lấy bản trong gói + sheet")
    ok(C.delete("a_luong", other) and not C.get("a_luong", other), "delete")

    print("E. mẫu mang dàn")
    t = T.save_section("Kiếm Lai · đạo lý", "wizard", {"wizAspectRatio": "16:9", "wizCast": "tran_binh_an, Bui_Tien"})
    ok(t["cast"] == ["tran_binh_an", "bui_tien"] and "wizCast" not in t["sections"]["wizard"]["data"],
       "wizCast vào t['cast'], không nằm lặp trong phần wizard", t)
    v = T.section_view(T.get_template("Kiếm Lai · đạo lý"), "wizard")
    ok(v.get("wizCast") == "tran_binh_an,bui_tien" and v.get("wizAspectRatio") == "16:9", "section_view chở wizCast lại", v)
    T.save_section("Kiếm Lai · đạo lý", "wizard", {"wizAspectRatio": "9:16"})
    ok(T.get_template("Kiếm Lai · đạo lý")["cast"] == ["tran_binh_an", "bui_tien"], "lưu wizard không có wizCast thì giữ dàn")
    t = T.set_cast("Kiếm Lai · đạo lý", ["ninh_dieu"])
    ok(T.summary(t)["cast"] == ["ninh_dieu"], "set_cast + summary có cast")
    ok(T.parse_cast(["A b", "a_b", "", "x"]) == ["ab", "a_b", "x"], "parse_cast làm sạch slug")

    print("F. route")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tubecli.api.characters_routes import router as R
    app = FastAPI()

    @app.middleware("http")
    async def _guest(request, call_next):
        if request.headers.get("x-guest"):
            request.state.guest_scope = {"ext": "x"}
        return await call_next(request)
    app.include_router(R)
    cl = TestClient(app)
    r = cl.get("/api/v1/characters").json()
    ok(r["success"] and {c["slug"] for c in r["characters"]} >= {"tran_binh_an", "bui_tien", "ninh_dieu"}
       and all("sheet_path" not in c for c in r["characters"]), "GET danh sách, không lộ đường dẫn", r)
    one = cl.get("/api/v1/characters/陈平安").json()["character"]
    ok(one["slug"] == "tran_binh_an" and one["sheet_url"] == "/api/v1/characters/tran_binh_an/sheet", "GET theo biệt danh")
    s = cl.get(one["sheet_url"])
    ok(s.status_code == 200 and s.content == PNG, "GET sheet", s.status_code)
    mm = cl.post("/api/v1/characters/match", json={"text": "sống bình an"}).json()["characters"]
    mc = cl.post("/api/v1/characters/match", json={"text": "sống bình an", "cast": ["tran_binh_an"]}).json()["characters"]
    ok(mm == [] and [c["slug"] for c in mc] == ["tran_binh_an"], "match: không dàn → tên đầy đủ; có dàn → cả biệt danh")
    g = cl.post("/api/v1/characters", json={"name": "Hack"}, headers={"x-guest": "1"})
    d = cl.delete("/api/v1/characters/tran_binh_an", headers={"x-guest": "1"})
    ok(g.status_code == 403 and d.status_code == 403 and C.get("tran_binh_an"), "khách workspace không ghi / xoá được")
    ok(cl.post("/api/v1/characters", json={"name": "Tề Tĩnh Xuân", "aliases": ["齐静春"]}).json()["character"]["slug"]
       == "te_tinh_xuan", "POST thêm nhân vật")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
