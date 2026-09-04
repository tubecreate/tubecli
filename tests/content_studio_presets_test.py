# -*- coding: utf-8 -*-
"""Preset của wizard Content Studio phải lưu được trên server và đổi ra trường drama.

Run:  python tests/content_studio_presets_test.py     (exit 0 = pass)
      In "SKIP" và exit 0 khi máy không có extension content_studio —
      thư mục data/extensions_external nằm ngoài git (gói Market).

Vì sao có file này (4/9/26): nút Preset → Save của wizard vẫn gọi
GET/POST/DELETE /api/v1/studio/presets nhưng server chưa hề có các route đó
(JS nuốt lỗi im lặng), nên preset chỉ sống trong localStorage của MỘT trình
duyệt. Agent (content_video) không đọc được localStorage → không thể "làm video
theo preset của tôi". Không dựng hệ template thứ hai: chỉ bổ sung nửa server
cho đúng cơ chế sync sẵn có của wizard.

Kiểm, đối chiếu studio_routes.py của extension:
  A. POST {name,data} và {presets:{...}} → lưu; GET trả {success, presets:{name: dict}}
     (JsonStore giữ data dạng chuỗi JSON, route phải parse ra dict; nhận cả dict lẫn chuỗi)
  B. preset_drama_fields = bản port của _createDramaFromWiz (static/studio2.js):
       preset đầy đủ đúng y payload wizard, __custom__ style → ô tự nhập / 'Default',
       wizNoTextPrompt kiểu boolean cũ, template custom → pipeline [],
       ép int như parseInt, chỉ phát khoá có trong preset
  C. Lỗi: preset không có → 404; tên rỗng → 400; data hỏng → 400; lô có tên rỗng → không ghi gì
  D. DELETE rồi GET không còn, drama-fields → 404
  E. version trong tubecli-extension.json phải vượt bản đang phát hành
"""
import asyncio
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

EXT = ROOT / "data" / "extensions_external" / "content_studio"
if not (EXT / "studio_routes.py").exists():
    print(f"SKIP: không có extension content_studio tại {EXT}")
    sys.exit(0)

# Extension import 'studio_db' và 'config' như package cấp cao, tương đối với
# thư mục của nó — phải vào sys.path TRƯỚC khi import studio_routes.
sys.path.insert(0, str(EXT))

# DATA_DIR trỏ vào temp TRƯỚC get_instance(): JsonStore là singleton, khởi tạo
# một lần là presets.json nằm cố định ở đó — không được đụng data thật.
TMP = tempfile.mkdtemp(prefix="cs_presets_")
import tubecli.config as cfg  # noqa: E402
cfg.DATA_DIR = Path(TMP)
from studio_db.json_store import JsonStore  # noqa: E402
STORE_DIR = os.path.join(TMP, "content_studio")
JsonStore.get_instance(STORE_DIR)

import studio_routes as R  # noqa: E402
from fastapi import HTTPException  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class _Req:
    """Đủ cho route: chỉ cần await request.json()."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def run(coro):
    return asyncio.run(coro)


def status_of(coro):
    """Mã HTTP mà route ném ra, None nếu route trả về bình thường."""
    try:
        asyncio.run(coro)
        return None
    except HTTPException as e:
        return e.status_code


print("=" * 70)
print("CONTENT STUDIO — PRESET WIZARD LƯU TRÊN SERVER + ĐỔI RA TRƯỜNG DRAMA")
print("=" * 70)

# Route phải có đúng đường dẫn/phương thức mà studio2.js đang gọi.
routes = {(r.path, m) for r in R.router.routes for m in getattr(r, "methods", ())}
check("route đăng ký đúng hợp đồng", {
    ("/api/v1/studio/presets", "GET"),
    ("/api/v1/studio/presets", "POST"),
    ("/api/v1/studio/presets/{name:path}", "DELETE"),
    ("/api/v1/studio/presets/{name:path}/drama-fields", "GET"),
} <= routes, sorted(p for p, _ in routes if "preset" in p))

# ── A. lưu / liệt kê ────────────────────────────────────────────────────────
FULL = {
    "wizContentFormat": "drama", "wizEpisodes": "3",
    "wizStyle": "Cinematic Realism", "wizStyleCustom": "",
    "wizCharacterStyle": "Anime", "wizCharStyleCustom": "",
    "wizCameraAngle": "wide", "wizEthnicity": "asian", "wizPromptFocus": "character",
    "wizAspectRatio": "9:16", "wizNarrationSource": "ai", "wizLanguage": "vi",
    "wizPipelineTemplate": "drama_full", "wizGalleryCategory": "7",
    "wizNoTextPrompt": "english_only", "wizVideoLength": "short_60s",
}
CUSTOM = dict(FULL, wizStyle="__custom__", wizStyleCustom="  Phim tài liệu VTV  ",
              wizCharacterStyle="__custom__", wizCharStyleCustom="   ")
OLD_BOOL = dict(FULL, wizNoTextPrompt=True)
TPL_CUSTOM = dict(FULL, wizPipelineTemplate="custom")

res = run(R.save_wiz_presets(_Req({"name": " Tin tức dọc ", "data": FULL})))
check("A POST {name,data} → saved (tên đã trim như wizard)", res == {"success": True, "saved": ["Tin tức dọc"]}, res)
res = run(R.save_wiz_presets(_Req({"presets": {"custom": CUSTOM, "old": OLD_BOOL, "tpl_custom": TPL_CUSTOM}})))
check("A POST {presets:{...}} → saved cả lô", res.get("success") and sorted(res.get("saved", [])) == ["custom", "old", "tpl_custom"], res)

res = run(R.list_wiz_presets())
check("A GET → {success, presets:{name: dict}}", res.get("success") is True and res["presets"].get("Tin tức dọc") == FULL, res)
check("A GET đủ 4 preset", set(res["presets"]) == {"Tin tức dọc", "custom", "old", "tpl_custom"}, sorted(res["presets"]))

presets_path = os.path.join(STORE_DIR, "presets.json")
check("A presets.json nằm trong temp, không đụng data thật", os.path.exists(presets_path), presets_path)
with open(presets_path, encoding="utf-8") as f:
    raw = json.load(f)
check("A JsonStore giữ data dạng chuỗi JSON (route đã parse khi trả)", all(isinstance(p.get("data"), str) for p in raw), raw)

run(R.save_wiz_presets(_Req({"name": "str", "data": json.dumps({"wizLanguage": "en"})})))
check("A data gửi dạng chuỗi JSON cũng nhận", run(R.list_wiz_presets())["presets"].get("str") == {"wizLanguage": "en"})
run(R.save_wiz_presets(_Req({"name": "str", "data": {"wizLanguage": "ja"}})))
res = run(R.list_wiz_presets())["presets"]
check("A lưu trùng tên = ghi đè, không nhân đôi", res.get("str") == {"wizLanguage": "ja"} and len(raw) + 1 == len(res), res)
print("A lưu/liệt kê : {name,data} + {presets} + chuỗi JSON + ghi đè")

# ── B. drama-fields = port _createDramaFromWiz ──────────────────────────────
EXPECT_FULL = {
    "style": "Visual Style: Cinematic Realism | Character Style: Anime",
    "total_episodes": 3,
    "language": "vi",
    "metadata": {
        "pipeline_template": "drama_full",
        "pipeline": ["raw", "rewrite", "extract", "storyboard", "images", "audio", "video", "publish"],
        "camera_angle": "wide", "ethnicity": "asian", "prompt_focus": "character",
        "aspect_ratio": "9:16", "content_format": "drama", "narration_source": "ai",
        "text_in_video": "english_only", "video_length": "short_60s",
        "gallery_category_id": 7,
    },
}
res = run(R.wiz_preset_drama_fields("Tin tức dọc"))
check("B route trả {success, name, fields}", res.get("success") is True and res.get("name") == "Tin tức dọc", res)
check("B preset đầy đủ → đúng y payload wizard", res.get("fields") == EXPECT_FULL, res.get("fields"))
check("B total_episodes / gallery_category_id là int thật",
      type(res["fields"]["total_episodes"]) is int and type(res["fields"]["metadata"]["gallery_category_id"]) is int)

f = run(R.wiz_preset_drama_fields("custom"))["fields"]
check("B __custom__ → ô tự nhập (trim); ô trống → 'Default' như wizard",
      f["style"] == "Visual Style: Phim tài liệu VTV | Character Style: Default", f["style"])

f = run(R.wiz_preset_drama_fields("old"))["fields"]
check("B wizNoTextPrompt=true (preset cũ) → 'notext'", f["metadata"]["text_in_video"] == "notext", f["metadata"])
check("B wizNoTextPrompt=false → 'none'", R.preset_drama_fields(dict(FULL, wizNoTextPrompt=False))["metadata"]["text_in_video"] == "none")
check("B wizNoTextPrompt='' → 'notext' (|| của wizard)", R.preset_drama_fields(dict(FULL, wizNoTextPrompt=""))["metadata"]["text_in_video"] == "notext")
_no_len = dict(FULL)
del _no_len["wizVideoLength"]
check("B thiếu wizVideoLength → 'standard'", R.preset_drama_fields(_no_len)["metadata"]["video_length"] == "standard")

f = run(R.wiz_preset_drama_fields("tpl_custom"))["fields"]
check("B template custom → pipeline [] + pipeline_template 'custom'",
      f["metadata"]["pipeline"] == [] and f["metadata"]["pipeline_template"] == "custom", f["metadata"])
check("B template lạ → pipeline [] (wizard rơi về nhánh custom)",
      R.preset_drama_fields(dict(FULL, wizPipelineTemplate="nope"))["metadata"]["pipeline"] == [])
check("B bảng pipeline khớp PIPELINE_TEMPLATES của studio2.js",
      R.preset_drama_fields(dict(FULL, wizPipelineTemplate="drama_scene"))["metadata"]["pipeline"]
      == ["raw", "rewrite", "extract", "storyboard", "videos", "audio", "video", "publish"]
      and R.preset_drama_fields(dict(FULL, wizPipelineTemplate="audio_story"))["metadata"]["pipeline"]
      == ["raw", "rewrite", "storyboard", "audio", "video"]
      and R.preset_drama_fields(dict(FULL, wizPipelineTemplate="content_only"))["metadata"]["pipeline"]
      == ["raw", "rewrite"])

# Ép số như parseInt: "" → 0, chữ → 0, "12abc" → 12, "3.7" → 3
check("B wizEpisodes ép như parseInt || 0",
      [R.preset_drama_fields(dict(FULL, wizEpisodes=v))["total_episodes"] for v in ("", "abc", "12abc", "3.7", " 5")]
      == [0, 0, 12, 3, 5])
check("B wizGalleryCategory rỗng/không phải số → không có gallery_category_id",
      "gallery_category_id" not in R.preset_drama_fields(dict(FULL, wizGalleryCategory=""))["metadata"]
      and "gallery_category_id" not in R.preset_drama_fields(dict(FULL, wizGalleryCategory="abc"))["metadata"])

# Chỉ phát khoá có trong preset (preset cũ thiếu trường không được xoá trắng giá trị của caller).
check("B preset chỉ có ngôn ngữ → chỉ language + 2 mặc định",
      R.preset_drama_fields({"wizLanguage": "en"})
      == {"language": "en", "metadata": {"text_in_video": "notext", "video_length": "standard"}},
      R.preset_drama_fields({"wizLanguage": "en"}))
check("B preset rỗng → chỉ metadata mặc định",
      R.preset_drama_fields({}) == {"metadata": {"text_in_video": "notext", "video_length": "standard"}})
check("B wizLanguage rỗng → không phát language (kẻo đè ngôn ngữ pipeline đã chốt)",
      "language" not in R.preset_drama_fields(dict(FULL, wizLanguage="")))
check("B preset_drama_fields thuần, không sửa input", (lambda d: (R.preset_drama_fields(d), d == FULL)[1])(dict(FULL)))
print("B drama-fields : đầy đủ | __custom__ | boolean cũ | custom → [] | parseInt | chỉ khoá có mặt")

# ── C. lỗi ──────────────────────────────────────────────────────────────────
check("C preset không có → 404", status_of(R.wiz_preset_drama_fields("không có")) == 404)
check("C drama-fields tên rỗng → 400", status_of(R.wiz_preset_drama_fields("  ")) == 400)
check("C POST tên rỗng → 400", status_of(R.save_wiz_presets(_Req({"name": "  ", "data": {}}))) == 400)
check("C POST data không phải JSON → 400", status_of(R.save_wiz_presets(_Req({"name": "x", "data": "{oops"}))) == 400)
check("C POST data không phải object → 400", status_of(R.save_wiz_presets(_Req({"name": "x", "data": [1]}))) == 400)
check("C POST presets không phải object → 400", status_of(R.save_wiz_presets(_Req({"presets": []}))) == 400)
before = run(R.list_wiz_presets())["presets"]
check("C lô có tên rỗng → 400", status_of(R.save_wiz_presets(_Req({"presets": {"ok_batch": FULL, " ": FULL}}))) == 400)
check("C   ...và không ghi dở dang phần hợp lệ", run(R.list_wiz_presets())["presets"] == before)
check("C DELETE tên rỗng → 400", status_of(R.delete_wiz_preset(" ")) == 400)
print("C lỗi         : 404 thiếu | 400 tên rỗng/data hỏng | lô hỏng không ghi dở")

# ── D. xoá ──────────────────────────────────────────────────────────────────
check("D DELETE → {success}", run(R.delete_wiz_preset("Tin tức dọc")) == {"success": True})
check("D   GET không còn", "Tin tức dọc" not in run(R.list_wiz_presets())["presets"])
check("D   drama-fields → 404", status_of(R.wiz_preset_drama_fields("Tin tức dọc")) == 404)
check("D DELETE tên chưa từng có vẫn {success} (idempotent)", run(R.delete_wiz_preset("chưa từng có")) == {"success": True})
print("D xoá         : mất khỏi GET + drama-fields 404")

# ── E. version ──────────────────────────────────────────────────────────────
with open(EXT / "tubecli-extension.json", encoding="utf-8") as fh:
    manifest = json.load(fh)


def _ver(s):
    return tuple(int(x) for x in s.split("."))


check("E version vượt bản đang phát hành (compare_versions so dotted ints)",
      _ver(manifest["version"]) > _ver("2026.05.06.032354"), manifest.get("version"))
print("E version     :", manifest.get("version"))

# ── F. tên có "/" ──────────────────────────────────────────────────────────
# Starlette giải mã %2F trước khi so route, nên {name} một đoạn không bao giờ khớp
# "Tin/Shorts": lưu được, liệt kê được, mà không tra/xoá được. {name:path} chữa.
run(R.save_wiz_presets(_Req({"name": "Tin/Shorts", "data": FULL})))
check("F tên có / → drama-fields tra được", run(R.wiz_preset_drama_fields("Tin/Shorts"))["fields"]["style"] == EXPECT_FULL["style"])
check("F   xoá được", run(R.delete_wiz_preset("Tin/Shorts")) == {"success": True}
      and "Tin/Shorts" not in run(R.list_wiz_presets())["presets"])
print("F ten co /    : tra + xoá được nhờ {name:path}")


shutil.rmtree(TMP, ignore_errors=True)


print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    for x in failures:
        print("  FAIL", x)
    sys.exit(1)
print(f"{checks}/{checks} PASS")
