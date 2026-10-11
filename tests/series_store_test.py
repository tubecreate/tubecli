# -*- coding: utf-8 -*-
"""HỒ SƠ TRUYỆN (tubecli.core.series + /api/v1/series, 11/10/2026 — user: «template có xây dựng các mối quan hệ của câu
chuyện không?», «tuỳ dạng chứ không phải cái nào cũng phải xây dựng nhân vật»).

  A. lưu / đọc: slug theo tên, tìm theo biệt danh / tên ngôn ngữ; làm sạch members / relations / phases
  B. member_slugs: thành viên + mọi giai đoạn tuổi, không lặp
  C. brief: chỉ quan hệ giữa người CÓ MẶT; cách gọi nhau + cách đứng cùng nhau; quy tắc giai đoạn; tên theo prompt_name
  D. is_narrative: chỉ Film / Drama, Xianxia
  E. route: danh sách / một / brief / chặn khách workspace

Run:  python tests/series_store_test.py
"""
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

TMP = tempfile.mkdtemp(prefix="series_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
from tubecli.core import series as S  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


KL = {"name": "Kiếm Lai", "aliases": ["Sword of Coming"], "names": {"zh": "剑来", "en": "Sword of Coming"},
      "summary": "A poor kiln apprentice from a small town becomes a swordsman who keeps every promise.",
      "world": "ONE WORLD ONLY - the world of Sword of Coming; never a present-day frame.",
      "members": ["tran_binh_an", "Bùi Tiền", "chu_me_lap", ""],
      "relations": [
          {"a": "bui_tien", "b": "tran_binh_an", "rel": "the first disciple of", "a_calls_b": "sư phụ",
           "staging": "she walks half a step behind him and watches his back"},
          {"a": "chu_me_lap", "b": "bui_tien", "rel": "the devoted little friend of", "a_calls_b": "Bùi Tiền tỷ"},
          {"a": "x", "b": ""}],
      "phases": {"bui_tien": [{"slug": "bui_tien", "when": "childhood, about thirteen"},
                              {"slug": "bui_tien_adult", "when": "grown up, a strong martial artist"}]}}
try:
    print("A. lưu / đọc")
    s = S.save(KL)
    ok(s["slug"] == "kiem_lai" and s["members"] == ["tran_binh_an", "bui_tien", "chu_me_lap"]
       and len(s["relations"]) == 2 and s["relations"][0]["a"] == "bui_tien", "slug + làm sạch members / relations", s)
    ok(S.get("剑来")["slug"] == "kiem_lai" and S.get("sword of coming")["slug"] == "kiem_lai", "tìm theo tên zh / biệt danh")
    S.save({"name": "Kiếm Lai", "summary": "New summary."})
    ok(S.get("kiem_lai")["summary"] == "New summary." and len(S.get("kiem_lai")["relations"]) == 2,
       "sửa một trường giữ phần còn lại")

    print("B. member_slugs")
    ok(S.member_slugs(S.get("kiem_lai")) == ["tran_binh_an", "bui_tien", "bui_tien_adult", "chu_me_lap"],
       "thành viên + giai đoạn tuổi theo thứ tự", S.member_slugs(S.get("kiem_lai")))

    print("C. brief")
    names = {"tran_binh_an": "Chen Ping'an", "bui_tien": "young Pei Qian", "bui_tien_adult": "grown Pei Qian",
             "chu_me_lap": "Zhou Mili"}
    b = S.brief(S.get("kiem_lai"), None, names)
    ok("young Pei Qian is the first disciple of Chen Ping'an" in b and "calls Chen Ping'an «sư phụ»" in b
       and "half a step behind" in b and "Zhou Mili is the devoted little friend of young Pei Qian" in b,
       "quan hệ + cách gọi + cách đứng cùng nhau, tên theo prompt_name", b)
    ok("AGES:" in b and "grown Pei Qian = grown up, a strong martial artist" in b and "never mix" in b, "quy tắc giai đoạn", b)
    b2 = S.brief(S.get("kiem_lai"), ["tran_binh_an", "bui_tien"], names)
    ok("Zhou Mili" not in b2 and "first disciple" in b2, "chỉ quan hệ giữa người có mặt", b2)
    ok(S.brief(None) == "", "không hồ sơ → rỗng")

    print("D. is_narrative")
    ok(S.is_narrative("Xianxia Donghua") and S.is_narrative("Drama / Narrative") and not S.is_narrative("Educational / Learning")
       and not S.is_narrative(""), "chỉ dạng kể chuyện")

    print("E. route")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tubecli.api.series_routes import router as R
    app = FastAPI()

    @app.middleware("http")
    async def _guest(request, call_next):
        if request.headers.get("x-guest"):
            request.state.guest_scope = {"ext": "x"}
        return await call_next(request)
    app.include_router(R)
    cl = TestClient(app)
    ls = cl.get("/api/v1/series").json()
    ok([x["slug"] for x in ls["series"]] == ["kiem_lai"] and "Xianxia Donghua" in ls["formats"], "GET danh sách", ls)
    ok(cl.get("/api/v1/series/剑来").json()["series"]["slug"] == "kiem_lai", "GET theo tên zh")
    br = cl.get("/api/v1/series/kiem_lai/brief", params={"present": "tran_binh_an,bui_tien"}).json()["brief"]
    ok("first disciple" in br and "chu me lap" not in br.lower(), "GET brief theo người có mặt", br)
    ok(cl.post("/api/v1/series", json={"name": "X"}, headers={"x-guest": "1"}).status_code == 403
       and cl.delete("/api/v1/series/kiem_lai", headers={"x-guest": "1"}).status_code == 403, "khách không ghi / xoá được")
    ok(cl.delete("/api/v1/series/kiem_lai").status_code == 200 and S.get("kiem_lai") is None, "DELETE")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
