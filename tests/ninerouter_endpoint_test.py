# 9Router ở MÁY KHÁC: endpoint lưu trong Cloud API Keys, mọi chỗ gọi 9Router đọc qua đó.
#
# Chạy:  python tests/ninerouter_endpoint_test.py     (exit 0 = pass)
#
# VÌ SAO CÓ FILE NÀY
#   13/9/2026 người dùng: "chỗ api key nếu tôi muốn thêm endpoint khác thay vì local thì sao?
#   ví dụ provider 9router" — kèm tên miền tunnel của 9Router trên VPS khác. Hơn ba chục chỗ
#   viết cứng http://localhost:20128/v1, nên TubeCLI chỉ dùng được 9Router trên chính máy nó.
#   Đo endpoint thật: không key → 401 "API key required for remote API access"; có key →
#   /models 35 model, cx/gpt-5.5 trả lời trong 2,5 s.
#   Không đụng kho key thật: KeyManager trỏ vào file tạm, mạng được giả lập.
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.extensions.cloud_api.extension as CA  # noqa: E402
from tubecli.core import ninerouter as NR  # noqa: E402

failures, checks = [], 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


TMP = tempfile.mkdtemp(prefix="ninerouter_ep_")
REAL_KM = CA.key_manager
km = CA.KeyManager(data_file=os.path.join(TMP, "cloud_api_keys.json"))
CA.key_manager = km
REMOTE = "https://tungho2-23-9router.tubecreate.com/v1"
DEFAULT = "http://localhost:20128/v1"

try:
    print("== A. chuẩn hoá endpoint người dùng dán vào")
    N = CA.normalize_base_url
    check("A1 tên miền trần → https + /v1", N("tungho2-23-9router.tubecreate.com") == REMOTE, N("tungho2-23-9router.tubecreate.com"))
    check("A2 bỏ '/' cuối, giữ đường /v1", N("https://tungho2-23-9router.tubecreate.com/v1/") == REMOTE)
    check("A3 IP:cổng trần → http + /v1", N("10.0.0.5:20128") == "http://10.0.0.5:20128/v1", N("10.0.0.5:20128"))
    check("A4 localhost trần → http", N("localhost:20128") == DEFAULT, N("localhost:20128"))
    check("A5 đường riêng giữ nguyên", N("https://proxy.example.com/api/v1") == "https://proxy.example.com/api/v1")
    check("A6 rỗng = về mặc định", N("   ") == "")
    for bad in ("ftp://x.com", "https://", "http:///v1"):
        try:
            N(bad)
            check(f"A7 từ chối {bad!r}", False, "không ném")
        except ValueError:
            check(f"A7 từ chối {bad!r}", True)
    check("A8 nhận ra endpoint cục bộ", CA.is_local_url(DEFAULT) and CA.is_local_url("http://127.0.0.1:20128/v1")
          and not CA.is_local_url(REMOTE))

    print("== B. lưu / đọc / về mặc định")
    check("B1 chưa đặt → mặc định", km.get_base_url("9router") == DEFAULT and NR.base_url() == DEFAULT, NR.base_url())
    r = km.set_base_url("9router", "tungho2-23-9router.tubecreate.com")
    check("B2 đặt endpoint trả bản đã chuẩn hoá", r["status"] == "success" and r["base_url"] == REMOTE and r["custom"] is True, r)
    check("B3 ninerouter đọc endpoint mới", NR.base_url() == REMOTE and NR.models_url() == REMOTE + "/models"
          and NR.chat_url() == REMOTE + "/chat/completions" and NR.is_local() is False)
    check("B4 bảng PROVIDERS đồng bộ (Content Studio/Pod Studio đọc thẳng bảng này)",
          CA.PROVIDERS["9router"]["base_url"] == REMOTE, CA.PROVIDERS["9router"]["base_url"])
    saved = json.load(open(km.data_file, encoding="utf-8"))
    check("B5 lưu trong _settings cạnh danh sách model", saved["_settings"]["9router"]["base_url"] == REMOTE, saved)
    km2 = CA.KeyManager(data_file=km.data_file)
    check("B6 máy chủ khởi động lại vẫn nhớ", km2.get_base_url("9router") == REMOTE)
    CA.key_manager = km
    check("B7 provider không tự host không đổi được", km.set_base_url("gemini", REMOTE)["status"] == "error")
    check("B8 endpoint sai → lỗi, giữ bản cũ", km.set_base_url("9router", "ftp://x")["status"] == "error"
          and km.get_base_url("9router") == REMOTE)

    print("== C. danh sách provider cho giao diện")
    p9 = next(p for p in km.list_providers() if p["id"] == "9router")
    check("C1 có endpoint + mặc định + cờ sửa được", p9["base_url"] == REMOTE and p9["base_url_default"] == DEFAULT
          and p9["base_url_custom"] is True and p9["base_url_editable"] is True, p9)
    check("C2 9Router ở máy khác KHÔNG còn 'cục bộ', chưa key thì chưa sẵn sàng",
          p9["local"] is False and p9["has_key"] is False, (p9["local"], p9["has_key"]))
    km.add_key("9router", "sk-test-remote", "remote")
    p9 = next(p for p in km.list_providers() if p["id"] == "9router")
    check("C3 thêm key → sẵn sàng", p9["has_key"] is True)
    hd = NR.auth_headers()
    check("C4 key + User-Agent của TubeCLI đi kèm mọi lượt hỏi (tunnel Cloudflare chặn UA mặc định)",
          hd.get("Authorization") == "Bearer sk-test-remote" and hd.get("User-Agent", "").startswith("TubeCLI"), hd)
    seen = {}
    real_fetch_json = km._fetch_json
    km._fetch_json = lambda url, headers=None: (seen.update(url=url, headers=headers) or
                                               {"data": [{"id": "cx/gpt-5.5"}, {"id": "ag/gemini-3.8-flash"}]})
    models = km.fetch_provider_models("9router")
    check("C5 lấy danh sách model từ endpoint mới, có key",
          seen.get("url") == REMOTE + "/models" and seen.get("headers") == {"Authorization": "Bearer sk-test-remote"}
          and models == ["cx/gpt-5.5", "ag/gemini-3.8-flash"], seen)

    # _fetch_json thật luôn gửi User-Agent riêng (bắt Request thay vì đi mạng).
    import urllib.request as _UR
    cap = {}

    class _Body:
        def read(self):
            return b'{"data": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    _real_open = _UR.urlopen
    _UR.urlopen = lambda req, timeout=None: (cap.update(ua=req.get_header("User-agent"), auth=req.get_header("Authorization")) or _Body())
    try:
        real_fetch_json(REMOTE + "/models", {"Authorization": "Bearer x"})
    finally:
        _UR.urlopen = _real_open
    check("C6 _fetch_json gửi User-Agent riêng, giữ header người gọi", str(cap.get("ua", "")).startswith("TubeCLI")
          and cap.get("auth") == "Bearer x", cap)

    print("== D. brain gọi đúng endpoint")
    import tubecli.core.brain as B
    check("D1 model 9Router → endpoint mới + key thật",
          B.AgentBrain.openai_compat_params({"model": "cx/gpt-5.5"}) == (REMOTE, "sk-test-remote", "cx/gpt-5.5"),
          B.AgentBrain.openai_compat_params({"model": "cx/gpt-5.5"}))
    got = {}

    class _Resp:
        def __init__(self, body):
            self._b = body

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as UR
    real_urlopen = UR.urlopen

    def fake_urlopen(req, timeout=None):
        got.update(url=req.full_url, auth=req.get_header("Authorization"), timeout=timeout)
        return _Resp(json.dumps({"data": [{"id": "cx/gpt-5.5"}]}).encode())

    UR.urlopen = fake_urlopen
    B._9R_CACHE.update(at=0.0, ids=[], base="")
    try:
        ids = B.list_9router_models(ttl=60)
    finally:
        UR.urlopen = real_urlopen
    check("D2 danh mục 9Router hỏi endpoint mới, kèm key, chờ lâu hơn cổng cục bộ",
          ids == ["cx/gpt-5.5"] and got.get("url") == REMOTE + "/models" and got.get("auth") == "Bearer sk-test-remote"
          and got.get("timeout") == 10, got)
    B._9R_CACHE.update(at=0.0, ids=[], base="")

    print("== E. route")
    import asyncio
    import tubecli.extensions.cloud_api.routes as RT
    res = asyncio.run(RT.api_update_provider_settings("9router", RT.UpdateProviderSettings(base_url="")))
    check("E1 PUT settings chỉ base_url='' → về mặc định", res["status"] == "success" and res["base_url"] == DEFAULT
          and res["custom"] is False and km.get_base_url("9router") == DEFAULT and CA.PROVIDERS["9router"]["base_url"] == DEFAULT, res)
    res = asyncio.run(RT.api_update_provider_settings("9router", RT.UpdateProviderSettings(base_url="tungho2-23-9router.tubecreate.com")))
    check("E2 PUT settings đặt lại endpoint", res["base_url"] == REMOTE and km.get_base_url("9router") == REMOTE, res)
    try:
        asyncio.run(RT.api_update_provider_settings("9router", RT.UpdateProviderSettings()))
        check("E3 PUT rỗng → 400", False, "không ném")
    except RT.HTTPException as e:
        check("E3 PUT rỗng → 400", e.status_code == 400)
    import requests
    real_get = requests.get
    calls = []

    class _R:
        def __init__(self, code, body):
            self.status_code, self._body = code, body
            self.text = json.dumps(body)

        def json(self):
            return self._body

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, dict(headers or {}), timeout))
        if (headers or {}).get("Authorization"):
            return _R(200, {"data": [{"id": "cx/gpt-5.5"}, {"id": "ag/gemini-3.8-flash"}]})
        return _R(401, {"error": "API key required for remote API access"})

    requests.get = fake_get
    try:
        t = RT.api_test_provider_endpoint("9router", RT.TestEndpointRequest(base_url="tungho2-23-9router.tubecreate.com"))
        check("E4 test-endpoint: chuẩn hoá + key đang bật → ok, đếm model",
              t["ok"] and t["base_url"] == REMOTE and t["model_count"] == 2 and calls[-1][0] == REMOTE + "/models", t)
        km.remove_key("9router", "remote")
        t = RT.api_test_provider_endpoint("9router", RT.TestEndpointRequest(base_url=REMOTE))
        check("E5 không key → báo 401 và has_key=False (giao diện nhắc thêm key)",
              not t["ok"] and t["status_code"] == 401 and t["has_key"] is False and "API key required" in t["error"], t)
        t = RT.api_test_provider_endpoint("9router", RT.TestEndpointRequest(base_url=REMOTE, api_key="sk-typed"))
        check("E6 key gõ trong ô thử được dùng", t["ok"] and calls[-1][1] == {"Authorization": "Bearer sk-typed"}, calls[-1])
        st = asyncio.run(RT.api_9router_status())
        check("E7 /9router/status đi endpoint đang lưu, nói rõ remote", st.get("base_url") == REMOTE and st.get("remote") is True
              and calls[-1][0] == REMOTE + "/models" and calls[-1][2] == 10, st)
    finally:
        requests.get = real_get

    print("== F. không còn chỗ nào viết cứng localhost:20128")
    files = ["tubecli/core/ai_generator.py", "tubecli/core/ai_workflow_builder.py", "tubecli/api/server.py",
             "tubecli/extensions/webui/story_api.py", "tubecli/extensions/studio3d/ai_builder.py",
             "tubecli/extensions/browser_scripts/script_routes.py", "tubecli/extensions/chat/routes.py",
             "tubecli/extensions/video_studio/region_detect.py", "tubecli/extensions/cloud_api/routes.py"]
    left = [f for f in files if '"http://localhost:20128' in io.open(ROOT / f, encoding="utf-8").read()]
    check("F1 các file gọi 9Router không còn URL cứng", not left, left)
    brain_src = io.open(ROOT / "tubecli/core/brain.py", encoding="utf-8").read()
    check("F2 brain chỉ còn hằng mặc định", brain_src.count('"http://localhost:20128/v1"') == 1
          and "base_url=_9R_BASE" not in brain_src)
    for f in ("tubecli/core/ai_generator.py", "tubecli/core/brain.py"):
        src = io.open(ROOT / f, encoding="utf-8").read()
        check(f"F2b {f}: OpenAI SDK có endpoint riêng thì gửi User-Agent của TubeCLI",
              'default_headers' in src and "user_agent()" in src)
    js = io.open(ROOT / "tubecli/extensions/webui/static/app.js", encoding="utf-8").read()
    check("F3 trình duyệt không gọi thẳng cổng 20128 nữa", "fetch('http://localhost:20128" not in js)
    check("F4 hộp ⚙ có ô endpoint + kiểm tra + lưu", "_renderEndpointPanel()" in js and "/test-endpoint" in js
          and "{ base_url: url }" in js)
finally:
    CA.key_manager = REAL_KM
    CA.PROVIDERS["9router"]["base_url"] = DEFAULT

print("=" * 70)
if failures:
    print(f"{len(failures)} FAIL / {checks}")
    sys.exit(1)
print(f"{checks}/{checks} PASS")
