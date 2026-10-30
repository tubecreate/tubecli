"""Codex GPT: kiểm đăng nhập tài khoản + «Cần đăng nhập lại» (user 30/10/2026: «lỗi connect nhưng trong extension chưa
có tính năng check» — tài khoản vokiemtk4 hỏng đăng nhập mà vẫn «In use», chấm xanh).

Chạy:  python tests/codex_account_check_test.py      (mã thoát 0 = đạt)

Khoá: _is_auth_error (401 / unauthorized / token revoked…, KHÁC hết hạn mức); «Kiểm tra tài khoản» hỏi account/read
{refreshToken: true} cho cả tài khoản ĐANG DÙNG (trước nuốt lỗi) và đánh dấu auth_error; lượt chat / Codex-làm-model
lỗi xác thực → đánh dấu; tài khoản auth_error không được chọn khi tự đổi; đăng nhập lại tài khoản đang dùng → dừng
app-server rồi mới ghi khoá mới (khoá cũ trong home không đè ngược); trang hiện nhãn + nút; 9 locale.
App-server GIẢ, dữ liệu Codex GPT ở thư mục tạm — không đụng tài khoản / token thật.
"""
import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="tubecli_codex_acct_")
os.environ["TUBECLI_CODEX_GPT_DIR"] = TMP

from tubecli.extensions.codex_gpt import accounts as A  # noqa: E402
from tubecli.extensions.codex_gpt import llm  # noqa: E402
from tubecli.extensions.codex_gpt import service as S  # noqa: E402
from tubecli.extensions.codex_gpt.rpc import RpcError  # noqa: E402
from tubecli.extensions.codex_gpt.service import service  # noqa: E402

checks = failures = 0


def check(name, ok, detail=""):
    global checks, failures
    checks += 1
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failures += 1


check("dữ liệu ở thư mục tạm", str(service.root).startswith(TMP))

# ── 1. phân loại lỗi ─────────────────────────────────────────────────────────
ie = S._is_auth_error
check("lỗi thật của task #491 là lỗi XÁC THỰC", ie({"message": "workspace routing discovery unauthorized (401)"}))
check("token bị thu hồi / 401 trong codexErrorInfo", ie("Encountered invalidated oauth token for user (token_revoked)")
      and ie({"message": "Reconnecting...", "codexErrorInfo": {"responseStreamDisconnected": {"httpStatusCode": 401}}})
      and ie({"message": "x", "codexErrorInfo": "unauthorized"}))
check("hết hạn mức / lỗi thường KHÔNG phải lỗi xác thực",
      not ie({"message": "You've hit your usage limit", "codexErrorInfo": "usageLimitExceeded"})
      and not ie({"message": "model not supported"}) and not ie("connection reset (4010 bytes)"))

# ── 2. tài khoản giả ─────────────────────────────────────────────────────────
a1 = A.add_or_update({"label": "vokiemtk4", "kind": "chatgpt", "email": "v@x.com", "plan": "plus"}, b'{"tokens":"OLD"}')
a2 = A.add_or_update({"label": "backup", "kind": "chatgpt", "email": "b@x.com", "plan": "plus"}, b'{"tokens":"B"}')
st = service.state()
st["active"] = a1["id"]
service.save_state(st)


class Bridge:
    def __init__(self, read_err=None, account=True):
        self.alive = True
        self.read_err = read_err
        self.account = account
        self.calls = []

    async def request(self, method, params=None, timeout=120.0):
        self.calls.append((method, params))
        if method == "account/read":
            if self.read_err:
                raise RpcError(self.read_err)
            return {"account": {"type": "chatgpt", "email": "v@x.com", "planType": "plus"} if self.account else None,
                    "requiresOpenaiAuth": True}
        if method == "account/rateLimits/read":
            return {"rateLimits": {"primary": {"usedPercent": 7, "windowDurationMins": 300, "resetsAt": 1}}}
        return {}

    async def stop(self):
        self.alive = False


A.update(a2["id"], disabled=True)          # chỉ kiểm tài khoản đang dùng ở bước này
service.bridge = Bridge(read_err="failed to refresh token: 401 Unauthorized (token_revoked)")
accs = asyncio.run(service.refresh_limits())
me = next(a for a in accs if a["id"] == a1["id"])
check("Kiểm tra tài khoản: account/read refreshToken=TRUE trên app-server chính",
      ("account/read", {"refreshToken": True}) in service.bridge.calls, service.bridge.calls)
check("tài khoản ĐANG DÙNG hỏng đăng nhập → auth_error (trước bị nuốt lỗi, vẫn «In use»)",
      "401" in (me.get("auth_error") or "") and me.get("auth_checked_at"), me)
check("public() trả auth_error / auth_checked_at / probe_error cho trang", {"auth_error", "auth_checked_at", "probe_error"} <= set(me))
check("tài khoản auth_error không còn «usable» (tự đổi tài khoản bỏ qua nó)", not A.usable(A.get(a1["id"])))

service.bridge = Bridge(account=False)
asyncio.run(service.refresh_limits())
check("account/read không có tài khoản → «not signed in»", "not signed in" in (A.get(a1["id"]).get("auth_error") or ""))

service.bridge = Bridge()
asyncio.run(service.refresh_limits())
me = A.get(a1["id"])
check("đăng nhập sống lại → gỡ auth_error, cập nhật hạn mức", not me.get("auth_error") and (me.get("limits") or {}).get("primary", {}).get("used") == 7, me)

service.bridge = Bridge(read_err="timed out")
asyncio.run(service.refresh_limits())
me = A.get(a1["id"])
check("lỗi khác (mạng) → probe_error, KHÔNG đánh dấu cần đăng nhập lại", not me.get("auth_error") and "timed out" in (me.get("probe_error") or ""), me)
A.update(a1["id"], probe_error="")

# ── 3. lượt chat lỗi xác thực → đánh dấu ────────────────────────────────────


async def turn_fail():
    await service._on_notify("turn/completed", {"threadId": "chat-1", "turn": {"id": "u1", "status": "failed",
                             "error": {"message": "workspace routing discovery unauthorized (401)"}}})
    await asyncio.sleep(0.1)
service._sync_back = lambda: None
asyncio.run(turn_fail())
check("lượt chat lỗi 401 → tài khoản đang dùng bị đánh dấu", "401" in (A.get(a1["id"]).get("auth_error") or ""))
A.update(a1["id"], auth_error="")

# ── 4. Codex-làm-model: lỗi xác thực ─────────────────────────────────────────
S.cli.command = lambda: ["codex-fake"]


class TurnBridge(Bridge):
    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = outcomes
        self.n = 0

    async def request(self, method, params=None, timeout=120.0):
        self.calls.append((method, params))
        if method == "thread/start":
            self.n += 1
            return {"thread": {"id": f"L{self.n}"}}
        if method == "turn/start":
            tid = params["threadId"]
            kind = self.outcomes.pop(0)

            async def play():
                if kind == "auth":
                    await service._on_notify("turn/completed", {"threadId": tid, "turn": {"status": "failed",
                                             "error": {"message": "workspace routing discovery unauthorized (401)"}}})
                else:
                    await service._on_notify("item/completed", {"threadId": tid, "item": {"type": "agentMessage", "text": kind}})
                    await service._on_notify("turn/completed", {"threadId": tid, "turn": {"status": "completed"}})
            asyncio.get_running_loop().call_later(0.03, lambda: asyncio.ensure_future(play()))
            return {"turn": {"id": "t"}}
        return {}


tb = TurnBridge(["auth"])


async def eb():
    return tb
service.ensure_bridge = eb
try:
    asyncio.run(llm.complete([{"role": "user", "content": "x"}]))
    check("Codex-làm-model lỗi xác thực, không còn tài khoản → CodexLLMError auth_error", False, "không ném")
except llm.CodexLLMError as e:
    check("Codex-làm-model lỗi xác thực, không còn tài khoản → CodexLLMError auth_error + đánh dấu tài khoản",
          e.code == "auth_error" and "sign in again" in e.message and "401" in (A.get(a1["id"]).get("auth_error") or ""), (e.code, e.message))
A.update(a1["id"], auth_error="")

SW = []


async def sw(reason="limit", msg=""):
    SW.append(reason)
    return True
_orig_sw = service.llm_limit_switch
service.llm_limit_switch = sw
tb = TurnBridge(["auth", "after relogin switch"])
r = asyncio.run(llm.complete([{"role": "user", "content": "x"}]))
check("lỗi xác thực + có tài khoản khác → đổi (lý do auth) rồi chạy lại luồng mới",
      r["text"] == "after relogin switch" and SW == ["auth"], (r, SW))
service.llm_limit_switch = _orig_sw

# llm_limit_switch(auth) thật: đánh dấu + chọn tài khoản khác dùng được
A.update(a2["id"], disabled=False)
SWITCHED = []


async def fake_switch(acc_id, reason="manual", force=False):
    SWITCHED.append((acc_id, reason))
    return {"active": acc_id}
service.switch = fake_switch
ok = asyncio.run(service.llm_limit_switch("auth", "token_revoked 401"))
check("llm_limit_switch('auth') đánh dấu tài khoản hỏng + đổi sang tài khoản còn tốt (lý do auth)",
      ok and SWITCHED == [(a2["id"], "auth")] and "token_revoked" in (A.get(a1["id"]).get("auth_error") or ""), (ok, SWITCHED))
A.update(a2["id"], auth_error="hỏng luôn")
SWITCHED.clear()
ok = asyncio.run(service.llm_limit_switch("auth", "401"))
check("mọi tài khoản đều hỏng đăng nhập → không đổi", ok is False and SWITCHED == [])
A.update(a1["id"], auth_error="")
A.update(a2["id"], auth_error="")

# ── 5. đăng nhập lại tài khoản ĐANG DÙNG: khoá cũ trong home không đè khoá mới ─
del service._sync_back                                   # dùng _sync_back thật
service.home.mkdir(parents=True, exist_ok=True)
(service.home / "auth.json").write_bytes(b'{"tokens":"OLD-IN-HOME"}')
service._marker().write_text(a1["id"], encoding="utf-8")
A.write_auth(a1["id"], b'{"tokens":"NEW-FROM-LOGIN"}')       # _finish_login vừa ghi khoá mới vào két
service.bridge = Bridge()
asyncio.run(service._reload_active_auth(a1["id"]))
check("đăng nhập lại tài khoản đang dùng → home + két đều là khoá MỚI, app-server cũ đã dừng",
      (service.home / "auth.json").read_bytes() == b'{"tokens":"NEW-FROM-LOGIN"}'
      and A.read_auth(a1["id"]) == b'{"tokens":"NEW-FROM-LOGIN"}' and service.bridge is None)
SRC = io.open(ROOT / "tubecli/extensions/codex_gpt/service.py", encoding="utf-8").read().replace("\r\n", "\n")
fl = SRC[SRC.index("async def _finish_login("):][:3500]
check("_finish_login: gỡ auth_error + nạp lại khoá khi là tài khoản đang dùng",
      'self._clear_auth(saved["id"])' in fl and 'await self._reload_active_auth(saved["id"])' in fl)

# ── 6. trang + locale ────────────────────────────────────────────────────────
APP = io.open(ROOT / "tubecli/extensions/codex_gpt/static/app.js", encoding="utf-8").read().replace("\r\n", "\n")
check("chấm trên thanh: đỏ khi auth_error", "(limited || a.auth_error ? 'bad' : sev(used))" in APP)
check("thẻ tài khoản: nhãn «Cần đăng nhập lại» + lý do + nút Đăng nhập lại",
      'data-auth-bad="1"' in APP and 'data-auth-why="1"' in APP and 'data-act="relogin"' in APP
      and "if (act === 'relogin') { openAddAccount(); return; }" in APP)
check("«checked» lấy mốc kiểm mới nhất (đăng nhập hoặc hạn mức)", "Math.max(a.auth_checked_at || 0, lim.at || 0)" in APP)
for lang in ["en", "vi", "zh", "zh-TW", "ja", "ko", "es", "tr", "ru"]:
    d = json.load(io.open(ROOT / f"tubecli/extensions/codex_gpt/locales/{lang}.json", encoding="utf-8"))
    miss = [k for k in ("cg.auth_bad", "cg.auth_hint", "cg.relogin") if k not in d]
    check(f"locale {lang}: đủ khoá + nút kiểm đổi nghĩa thành kiểm tài khoản", not miss and d.get("cg.refresh_limits") not in ("Check limits", "Kiểm hạn mức"), (miss, d.get("cg.refresh_limits")))

print(f"\n{checks - failures}/{checks} PASS")
sys.exit(1 if failures else 0)
