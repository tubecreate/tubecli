# -*- coding: utf-8 -*-
"""Chợ của máy cài được MẪU (29/9/2026) — market/templates.py + nhánh template trong routes.

Trước đây nút Cài của mẫu trả «Unknown category: template» (400). User: «khi chủ server mua thì
tải dữ liệu về máy». Giờ: Studio /market/install (tải gói bằng khoá Chợ) → chờ việc nền →
/preset-bundle/import (xem trước rồi apply) → sổ market_installed.json.

Run: python tests/market_template_install_test.py   (exit 0 = pass) — giả lập MỌI HTTP.
"""
import asyncio
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx                                                     # noqa: E402

import tubecli.config as cfg                                     # noqa: E402

_tmp = tempfile.mkdtemp()
cfg.DATA_DIR = type(cfg.DATA_DIR)(_tmp) if hasattr(cfg, "DATA_DIR") else _tmp
from tubecli.extensions.market import templates as T             # noqa: E402

T.POLL_SEC = 0.01
PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("[PASS]", label)
    else:
        FAIL += 1
        print("[FAIL]", label, detail)


def studio(existing=(), job_phases=("downloading", "ready"), install_status=200, fail_job=None):
    """Studio giả: ghi lại mọi lượt gọi; import trả kế hoạch như preset_bundle.build_import."""
    seen = []
    phases = list(job_phases)

    def handler(req: httpx.Request):
        body = json.loads(req.content or b"{}") if req.content else {}
        seen.append((req.method, req.url.path, body, dict(req.headers)))
        if req.url.path == "/api/v1/studio/market/install":
            if install_status != 200:
                return httpx.Response(install_status, json={"detail": "nope"})
            return httpx.Response(200, json={"success": True, "job": "j1"})
        if req.url.path == "/api/v1/studio/market/jobs/j1":
            ph = phases.pop(0) if len(phases) > 1 else phases[0]
            job = {"id": "j1", "phase": ph, "error": "", "status": 0, "result": None}
            if ph == "ready":
                job["result"] = {"success": True, "upload_id": "u123", "bundle": {}, "libraries": []}
            if ph == "error":
                job.update(error=fail_job or "boom", status=403)
            return httpx.Response(200, json={"success": True, "job": job})
        if req.url.path == "/api/v1/studio/preset-bundle/import":
            items = [{"index": 0, "name": "Math Noir", "status": "conflict" if "Math Noir" in existing else "new"}]
            ch = body.get("choices") or {}
            for it in items:
                it["action"] = (ch.get(str(it["index"])) or {}).get("action") or ("rename" if it["status"] == "conflict" else "add")
            if not body.get("apply"):
                return httpx.Response(200, json={"success": True, "plan": {"items": items}})
            saved = [("Math Noir (2)" if it["action"] == "rename" else it["name"]) for it in items]
            return httpx.Response(200, json={"success": True, "plan": {"items": items}, "saved": saved,
                                             "layouts_added": [], "errors": []})
        return httpx.Response(404, json={"detail": "not found"})
    return seen, handler


async def run(handler, **kw):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        return await T.install("feqs1ISYn8x6", "Math Noir", kw.pop("token", "tok-abc"),
                               version="2026.09.29", base_url="http://studio", client=c, **kw)


# ── 1. cài mới: khoá Chợ đi qua X-Market-Token, apply sau khi xem trước, sổ ghi lại ────
seen, h = studio()
out = asyncio.run(run(h))
paths = [p for _, p, _, _ in seen]
check("gọi đúng thứ tự: install → jobs (chờ) → import xem trước → import apply",
      paths[0] == "/api/v1/studio/market/install" and paths.count("/api/v1/studio/market/jobs/j1") >= 2
      and [b.get("apply") for m, p, b, _ in seen if p.endswith("/import")] == [False, True], paths)
check("khoá Chợ của người dùng đi qua header X-Market-Token (không vào thân)",
      seen[0][3].get("x-market-token") == "tok-abc" and "tok-abc" not in json.dumps(seen[0][2]))
check("nhập bằng upload_id của gói đã tải", all(b.get("upload_id") == "u123" for _, p, b, _ in seen if p.endswith("/import")))
check("kết quả: mẫu đã thêm", out["saved"] == ["Math Noir"], out)
st = T.installed("feqs1ISYn8x6", "Tên khác")
check("sổ phiên bản → Chợ biết «Đã cài» + bản đã cài (kể cả khi tên hiện khác)",
      st["installed"] and st["local_version"] == "2026.09.29", st)
check("mã chưa cài → chưa cài", not T.installed("zzzzzzzzzzzz", "Không có")["installed"])

# ── 2. trùng tên: mặc định GIỮ CẢ HAI (đổi tên bản nhập); «Cập nhật» thì THAY ──────────
seen, h = studio(existing=("Math Noir",))
out = asyncio.run(run(h))
check("trùng tên, cài thường → không đè (Studio đổi tên bản nhập)", out["saved"] == ["Math Noir (2)"], out)
seen, h = studio(existing=("Math Noir",))
out = asyncio.run(run(h, force_update=True))
applied = [b for _, p, b, _ in seen if p.endswith("/import") and b.get("apply")][0]
check("Cập nhật (force_update) → chọn replace đúng mẫu trùng",
      applied.get("choices") == {"0": {"action": "replace"}} and out["saved"] == ["Math Noir"], applied)

# ── 3. lỗi nói rõ, đúng mã ────────────────────────────────────────────────────────────
def err_of(coro):
    try:
        asyncio.run(coro)
        return None
    except T.TemplateInstallError as e:
        return (e.status, str(e))


_, h = studio(install_status=404)
e = err_of(run(h))
check("máy chưa có Content Studio (404) → 409 + câu hướng dẫn cài Studio", e and e[0] == 409 and "Content Studio" in e[1], e)
_, h = studio(job_phases=("downloading", "error"), fail_job="You have not bought this template")
e = err_of(run(h))
check("chưa mua (Studio báo 403 trong việc nền) → 403 kèm lý do", e and e[0] == 403 and "bought" in e[1], e)
_, h = studio()
e = err_of(run(h, token=""))
check("chưa đăng nhập Chợ → 401, không gọi Studio", e and e[0] == 401, e)

# ── 4. route: «Unknown category: template» đã hết; kiểm đã cài qua market_links / tên mẫu ─
from tubecli.extensions.market import routes as R                 # noqa: E402
st = R._check_item_installed("feqs1ISYn8x6", "Math Noir", "template")
check("routes._check_item_installed hiểu category template", st["installed"] is True, st)
os.makedirs(os.path.join(_tmp, "content_studio"), exist_ok=True)
json.dump({"Codex Sacra": "6idWd68b2XfZ"}, open(os.path.join(_tmp, "content_studio", "market_links.json"), "w", encoding="utf-8"))
json.dump([{"name": "Tâm Lý Nhật"}], open(os.path.join(_tmp, "content_studio", "presets.json"), "w", encoding="utf-8"))
check("máy ĐĂNG mẫu (market_links) → coi như đã cài", T.installed("6idWd68b2XfZ", "Codex Sacra")["installed"])
check("Studio đã có mẫu trùng tên → coi như đã cài", T.installed("W0414Ym5u2vP", "Tâm Lý Nhật")["installed"])
src = open(R.__file__, encoding="utf-8").read()
check("route install có nhánh template TRƯỚC nhánh extension",
      src.index('if category == "template":\n        from tubecli.extensions.market import templates as _tpl')
      < src.index('if category == "extension" and _builtin_extension(req.item_name) is not None'))

# ── 5. phiên bản (15/10/2026: «mẫu template cũng có phiên bản để người bán cập nhật và người mua update») ──
sd = os.path.join(_tmp, "content_studio")
legacy = os.path.join(sd, "market_installed.json")
check("sổ phiên bản là file RIÊNG, không ghi vào market_installed.json của Studio",
      os.path.basename(T._record_path()) == "market_template_versions.json"
      and "feqs1ISYn8x6" in json.load(open(T._record_path(), encoding="utf-8"))
      and not os.path.exists(legacy))
# Studio cài một mẫu khác: ghi market_installed.json dạng «tên → mã» — trước đây xoá mất phiên bản.
json.dump({"Tâm Lý Nhật": "W0414Ym5u2vP"}, open(legacy, "w", encoding="utf-8"))
check("Studio ghi đè market_installed.json → phiên bản đã cài vẫn còn",
      T.installed("feqs1ISYn8x6", "Math Noir")["local_version"] == "2026.09.29")
st = T.installed("W0414Ym5u2vP", "Tâm Lý Nhật")
check("Studio cài (không ghi phiên bản) → đã cài, không rõ bản (version_unknown: cho Cập nhật, không giục)",
      st == {"installed": True, "path": "content_studio", "local_version": "", "version_unknown": True}, st)
# Bản ghi kiểu cũ (dict) còn sót trong market_installed.json vẫn được đọc.
json.dump({"Tâm Lý Nhật": "W0414Ym5u2vP", "OLDcode00001": {"title": "Cũ", "version": "2026.09.01", "presets": ["Cũ"]}},
          open(legacy, "w", encoding="utf-8"))
check("bản ghi cũ trong market_installed.json vẫn cho ra phiên bản",
      T.installed("OLDcode00001", "Cũ")["local_version"] == "2026.09.01")
st = T.installed("6idWd68b2XfZ", "Codex Sacra")
check("máy NGƯỜI BÁN → đã cài, không có phiên bản (không tự mời thay mẫu gốc của mình)",
      st["installed"] and st["local_version"] == "" and st.get("seller") is True, st)
st = T.installed("SelfMade0001", "Tâm Lý Nhật")
check("mẫu trùng tên do người dùng tự tạo → đã cài, không phiên bản, KHÔNG cho cập nhật (đè mẫu của họ)",
      st == {"installed": True, "path": "content_studio", "local_version": ""}, st)
json.dump({"Codex Sacra": "6idWd68b2XfZ"}, open(legacy, "w", encoding="utf-8"))
st = T.installed("6idWd68b2XfZ", "Codex Sacra")
check("người bán tự cài lại mẫu của mình trong Studio → vẫn là người bán, không cho cập nhật",
      st.get("seller") is True and not st.get("version_unknown"), st)
check("chưa cài → local_version rỗng", T.installed("zzzzzzzzzzzz", "Không có")["local_version"] == "")


async def run_v(handler, version, **kw):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        return await T.install("feqs1ISYn8x6", "Math Noir", "tok-abc", version=version,
                               base_url="http://studio", client=c, **kw)


_, h = studio(existing=("Math Noir",))
asyncio.run(run_v(h, "2026.10.15.1429", force_update=True))
check("người bán đăng bản mới → người mua Cập nhật → sổ lên bản mới",
      T.installed("feqs1ISYn8x6", "Math Noir")["local_version"] == "2026.10.15.1429")
_, h = studio(existing=("Math Noir",))
asyncio.run(run_v(h, "", force_update=True))
check("Chợ không trả phiên bản → giữ phiên bản cũ, không xoá trắng",
      T.installed("feqs1ISYn8x6", "Math Noir")["local_version"] == "2026.10.15.1429")
check("route _check_item_installed trả local_version của sổ",
      R._check_item_installed("feqs1ISYn8x6", "Math Noir", "template")["local_version"] == "2026.10.15.1429")

print()
print(f"{PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
