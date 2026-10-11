# -*- coding: utf-8 -*-
"""KHO NHÂN VẬT chung ở lõi (tubecli.core.characters + /api/v1/characters) và DÀN NHÂN VẬT của mẫu (templates.cast).

User 10/10/2026: «tạo 1 kho để khi tôi làm về nhân vật này có thể lấy để đồng nhất», chọn «kho ở lõi, mẫu mang dàn»;
rồi «bỏ cái sheet cũ đi, mỗi kho đúng loại style, mắc công nhầm» → MỖI KHO MỘT STYLE.

  A. lưu / đọc: <style>/<slug>/profile.json + sheet; prompt_name không dấu; sheet phải là ảnh; đúng MỘT sheet
  B. khớp tên trong kho của style: tiếng Việt có dấu, chữ Hán, phiên âm; không nửa từ; `only` (dàn); aliases=False
  C. hai kho tách bạch: cùng tên ở kho 3D không lọt vào kho thuỷ mặc
  D. gói Chợ: bundle → install_bundle trên máy khác (sheet + kho đi theo); slug đã có thì giữ bản máy này
  E. mẫu mang dàn: wizCast trong phần wizard ↔ t["cast"]; set_cast; summary có cast
  F. route: kho / danh sách / một / sheet / match / chặn khách workspace

Run:  python tests/characters_store_test.py
"""
import base64
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


INK = "Ink Wash Film"
CG = "Donghua 3D"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
LOOK = ("a lean young man about eighteen with sharp dark eyes, black hair in a high ponytail, faded grey-blue patched "
        "cross-collar tunic, dark belts, indigo wrap skirt, worn cloth boots, plain straight sword")
try:
    print("A. lưu / đọc")
    src = os.path.join(TMP, "in.png")
    open(src, "wb").write(PNG)
    p = C.save({"name": "Trần Bình An", "aliases": ["Bình An", "陈平安", "Chen Ping'an"], "series": "Kiếm Lai",
                "look": LOOK, "status": "approved"}, INK, sheet_src=src)
    ok(p["slug"] == "tran_binh_an" and p["store"] == "ink_wash_film" and p["prompt_name"] == "Tran Binh An"
       and p["sheet_path"].endswith(os.path.join("ink_wash_film", "tran_binh_an", "sheet.png")),
       "hồ sơ + sheet trong kho của style, prompt_name không dấu", p)
    p2 = C.save({"name": "Trần Bình An", "personality": "giữ lời"}, INK)
    ok(p2["look"] == LOOK and p2["status"] == "approved" and p2["personality"] == "giữ lời" and p2["sheet_path"],
       "sửa một trường thì giữ các trường khác + sheet", p2)
    jpg = "data:image/jpeg;base64," + base64.b64encode(PNG + b"j").decode()
    p3 = C.save({"name": "Trần Bình An"}, INK, sheet_data=jpg)
    d = os.path.join(C.store_dir(INK), "tran_binh_an")
    ok(p3["sheet_path"].endswith("sheet.jpg") and not os.path.exists(os.path.join(d, "sheet.png")),
       "thay sheet: đúng MỘT sheet (bản cũ khác đuôi bị xoá)", os.listdir(d))
    bad = os.path.join(TMP, "secret.txt")
    open(bad, "w").write("x")
    try:
        C.save({"name": "X"}, INK, sheet_src=bad)
        ok(False, "sheet không phải ảnh bị từ chối")
    except ValueError:
        ok(True, "sheet không phải ảnh bị từ chối")
    try:
        C.save({"name": "Y"}, "")
        ok(False, "thiếu style bị từ chối")
    except ValueError:
        ok(True, "thiếu style bị từ chối")
    C.save({"name": "Bùi Tiền", "aliases": ["裴钱", "Pei Qian"], "look": "short"}, INK)

    print("B. khớp tên")
    m = [x["slug"] for x in C.match("Năm ấy, Bùi Tiền theo sư phụ Trần Bình An lên núi.", INK)]
    ok(m == ["bui_tien", "tran_binh_an"], "tiếng Việt có dấu, theo thứ tự xuất hiện", m)
    ok([x["slug"] for x in C.match("陈平安说了一句话", INK)] == ["tran_binh_an"]
       and [x["slug"] for x in C.match("CHEN PING'AN walks", INK)] == ["tran_binh_an"], "chữ Hán + phiên âm")
    ok(C.match("Trần Bình Anh là ai", INK) == [], "không khớp nửa từ («Bình Anh»)")
    ok([x["slug"] for x in C.match("Trần Bình An và Bùi Tiền", INK, only=["bui_tien"])] == ["bui_tien"],
       "only = dàn của mẫu")
    ok(C.match("Sống bình an giữa đời", INK, aliases=False) == [] and C.match("Sống bình an giữa đời", INK),
       "aliases=False: biệt danh chữ thường không kéo nhân vật vào")
    ents = C.as_canon(C.match("Trần Bình An và Bùi Tiền", INK))
    ok(len(ents) == 1 and ents[0]["name"] == "Tran Binh An" and ents[0]["library_store"] == "ink_wash_film"
       and ents[0]["sheet"], "as_canon: chỉ hồ sơ có look đủ dài; mang kho + sheet", ents)

    print("C. hai kho tách bạch")
    C.save({"name": "Trần Bình An", "look": LOOK + " in 3D"}, CG, sheet_src=src)
    ink = C.get("tran_binh_an", INK)
    cg = C.get("tran_binh_an", CG)
    ok(ink["sheet_path"] != cg["sheet_path"] and ink["look"] == LOOK and "3D" in cg["look"],
       "cùng nhân vật, hai kho, hai hồ sơ + hai sheet")
    ok([s["key"] for s in C.stores()] == ["donghua_3d", "ink_wash_film"] and len(C.load_all()) == 3
       and len(C.load_all(INK)) == 2, "stores + load_all theo kho", C.stores())
    ok(all(x["store"] == "ink_wash_film" for x in C.match("Trần Bình An", INK)), "match chỉ nhìn kho của style")

    print("D. gói Chợ")
    items = C.bundle(["tran_binh_an", "khong_co"], INK)
    ok(len(items) == 1 and items[0]["store"] == "ink_wash_film" and items[0]["sheet_data"].startswith("data:image/jpeg")
       and "sheet_path" not in items[0]["profile"], "bundle: kho + hồ sơ + sheet base64, không lộ đường dẫn", items[0])
    other = os.path.join(TMP, "other_machine")
    os.makedirs(other)
    C.save({"name": "Trần Bình An", "look": "machine copy keeps its own look text here ok"}, INK, base=other)
    done = C.install_bundle(items + [{"store": INK, "profile": {"name": "A Lương"}}, {"profile": {"name": "Z"}}], base=other)
    ok(done == ["ink_wash_film/tran_binh_an", "ink_wash_film/a_luong"]
       and C.get("tran_binh_an", INK, other)["look"].startswith("machine copy"),
       "install: slug đã có giữ bản máy này; mới thì cài; thiếu kho thì bỏ", done)
    C.install_bundle(items, base=other, overwrite=True)
    q = C.get("tran_binh_an", INK, other)
    ok(q["look"] == LOOK and open(q["sheet_path"], "rb").read() == PNG + b"j", "overwrite: lấy bản trong gói + sheet")
    ok(C.delete("a_luong", INK, other) and not C.get("a_luong", INK, other), "delete")

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

    print("G. tên theo ngôn ngữ (clone đổi ngôn ngữ)")
    C.save({"name": "Trần Bình An", "names": {"vi": "Trần Bình An", "en": "Chen Ping'an", "zh": "陈平安", "zh-TW": "陳平安"}},
           INK)
    C.save({"name": "Bùi Tiền", "names": {"en": "Pei Qian", "zh": "裴钱"}}, INK)
    p = C.get("tran_binh_an", INK)
    ok(C.name_in(p, "en") == "Chen Ping'an" and C.name_in(p, "es") == "Chen Ping'an" and C.name_in(p, "zh-TW") == "陳平安"
       and C.name_in(p, "zh") == "陈平安" and C.name_in(p, "ru") == "", "name_in: đúng ngôn ngữ, chữ Latinh lùi về en, ru để model phiên")
    ok([x["slug"] for x in C.match("陳平安來了", INK)] == ["tran_binh_an"], "tên trong `names` cũng khớp được")
    g = C.glossary("Hôm ấy Trần Bình An và Bùi Tiền lên núi.", "en")
    ok([(x["source"], x["target"]) for x in g] == [("Trần Bình An", "Chen Ping'an"), ("Bùi Tiền", "Pei Qian")]
       or [(x["source"], x["target"]) for x in g] == [("Bùi Tiền", "Pei Qian"), ("Trần Bình An", "Chen Ping'an")],
       "glossary: tên đang dùng → tên ngôn ngữ đích (một lần dù có ở hai kho)", g)
    from tubecli.extensions.content_video import clone as CLN
    sp = CLN.system_prompt("Vietnamese", "English", g)
    ok("«Trần Bình An» → «Chen Ping'an»" in sp and "Character names" in sp and "Character names" not in
       CLN.system_prompt("Vietnamese", "English"), "clone: lời dặn dịch có bảng tên (không kho → như cũ)", sp[-300:])
    ok("established Russian name (original: 裴钱" in CLN.glossary_rule([{"source": "Bùi Tiền", "target": "", "zh": "裴钱",
                                                                          "en": "Pei Qian"}], "Russian"),
       "thiếu tên đích → dặn model phiên theo tên gốc")

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
    ok([s["key"] for s in cl.get("/api/v1/characters/stores").json()["stores"]] == ["donghua_3d", "ink_wash_film"],
       "GET stores")
    r = cl.get("/api/v1/characters", params={"style": INK}).json()
    ok(r["success"] and {c["slug"] for c in r["characters"]} == {"tran_binh_an", "bui_tien"}
       and all("sheet_path" not in c for c in r["characters"]), "GET danh sách theo style, không lộ đường dẫn", r)
    one = cl.get("/api/v1/characters/ink_wash_film/陈平安").json()["character"]
    ok(one["slug"] == "tran_binh_an" and one["sheet_url"] == "/api/v1/characters/ink_wash_film/tran_binh_an/sheet",
       "GET theo biệt danh trong kho", one)
    s = cl.get(one["sheet_url"])
    ok(s.status_code == 200 and s.content == PNG + b"j", "GET sheet", s.status_code)
    mm = cl.post("/api/v1/characters/match", json={"text": "sống bình an", "style": INK}).json()["characters"]
    mc = cl.post("/api/v1/characters/match", json={"text": "sống bình an", "style": INK,
                                                   "cast": ["tran_binh_an"]}).json()["characters"]
    ok(mm == [] and [c["slug"] for c in mc] == ["tran_binh_an"], "match: không dàn → tên đầy đủ; có dàn → cả biệt danh")
    g = cl.post("/api/v1/characters", json={"name": "Hack", "style": INK}, headers={"x-guest": "1"})
    d = cl.delete("/api/v1/characters/ink_wash_film/tran_binh_an", headers={"x-guest": "1"})
    ok(g.status_code == 403 and d.status_code == 403 and C.get("tran_binh_an", INK), "khách workspace không ghi / xoá được")
    ok(cl.post("/api/v1/characters", json={"name": "Tề Tĩnh Xuân", "style": INK}).json()["character"]["store"]
       == "ink_wash_film" and cl.post("/api/v1/characters", json={"name": "Q"}).status_code == 400,
       "POST thêm nhân vật vào kho; thiếu style → 400")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
