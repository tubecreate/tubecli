"""Thu hồi chia sẻ phải có hiệu lực NGAY, không đợi token hết hạn.

Run:  python tests/guest_revoke_test.py     (exit 0 = pass)

VÌ SAO CÓ FILE NÀY
    Guest token là bearer: đã phát ra thì máy chủ chỉ còn biết nó "còn hạn hay
    không". Chủ bấm thu hồi ở cloud thì cloud đổi một dòng trong D1 — máy chủ
    không hề hay biết, nên sharee vẫn dùng tiếp bằng cookie đang cầm. Hàm
    auth.revoke_guest_tokens_for_workspace() đã có sẵn từ lâu và KHÔNG nơi nào
    gọi; TTL lại dài 6 tiếng, nên cửa hé gần hết một ngày làm việc.

    Nay: có route POST /api/v1/auth/guest-token/revoke (chủ) để cloud bắn xuống
    ngay khi thu hồi/xoá/đổi phạm vi, và TTL rút còn 30 phút làm lưới cho lúc
    không gọi xuống được (tunnel đứt, máy tắt).

    Test này chốt: thu hồi xong thì request KẾ TIẾP đã bị từ chối (không phải
    "sau khi cache hết hạn"), workspace khác không bị vạ lây, route không nằm
    trong danh sách miễn đăng nhập, và TTL không âm thầm dài trở lại.
"""
import ast
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

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="tubecli_guest_")
    saved = cfg.DATA_DIR
    cfg.DATA_DIR = pathlib.Path(tmp)
    auth._guest_cache.clear()
    auth._sessions.clear()

    try:
        print("=== 1. TTL đủ ngắn để là một cái lưới, không phải cả ngày ===")
        check("GUEST_TTL_SECONDS ≤ 30 phút",
              auth.GUEST_TTL_SECONDS <= 30 * 60, auth.GUEST_TTL_SECONDS)
        check("TTL vẫn đủ dài để làm việc (≥ 10 phút)",
              auth.GUEST_TTL_SECONDS >= 10 * 60, auth.GUEST_TTL_SECONDS)

        print("\n=== 2. thu hồi có hiệu lực ở request kế tiếp ===")
        a1 = auth.mint_guest_token({"workspace": "wsA", "profiles": ["p1"]})["guest_token"]
        a2 = auth.mint_guest_token({"workspace": "wsA", "profiles": ["p2"]})["guest_token"]
        b1 = auth.mint_guest_token({"workspace": "wsB", "profiles": ["p3"]})["guest_token"]
        check("token vừa mint dùng được",
              auth.guest_scope_for(a1) and auth.guest_scope_for(a2) and auth.guest_scope_for(b1))
        # Đọc một lần trước khi thu hồi để CHẮC CHẮN cache đã giữ scope — bug kinh
        # điển của kiểu này là "xoá file rồi mà cache vẫn cho qua".
        check("cache đã giữ scope", a1 in auth._guest_cache)
        n = auth.revoke_guest_tokens_for_workspace("wsA")
        check("thu hồi đúng số token của wsA", n == 2, n)
        check("token wsA bị từ chối NGAY", auth.guest_scope_for(a1) is None and auth.guest_scope_for(a2) is None)
        check("workspace khác không vạ lây", (auth.guest_scope_for(b1) or {}).get("workspace") == "wsB")
        check("thu hồi lần 2 -> 0 (idempotent)", auth.revoke_guest_tokens_for_workspace("wsA") == 0)
        check("workspace rỗng -> 0, không đụng gì",
              auth.revoke_guest_tokens_for_workspace("") == 0 and auth.guest_scope_for(b1) is not None)

        print("\n=== 3. route thu hồi (cloud gọi xuống) ===")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from tubecli.api.auth_routes import router

        app = FastAPI()
        app.include_router(router)
        c = TestClient(app)

        c1 = auth.mint_guest_token({"workspace": "wsC"})["guest_token"]
        r = c.post("/api/v1/auth/guest-token/revoke", json={"workspace": "wsC"})
        check("POST revoke -> ok + số đã thu", r.status_code == 200 and r.json()["revoked"] == 1, r.text[:200])
        check("token wsC hết hiệu lực", auth.guest_scope_for(c1) is None)
        r = c.post("/api/v1/auth/guest-token/revoke", json={"workspace": "  "})
        check("thiếu workspace -> 400", r.status_code == 400, r.text[:200])
        r = c.post("/api/v1/auth/guest-token/revoke", json={"workspace": "khong-co"})
        check("workspace lạ -> 200 revoked=0 (idempotent)",
              r.status_code == 200 and r.json()["revoked"] == 0, r.text[:200])

        print("\n=== 3b. THU HỒI và ĐỒNG BỘ là hai việc khác nhau ===")
        # data/guest_drive/<ws> giữ file sharee vừa chọn từ Drive vào ô upload.
        # Playwright đọc file đó lúc trang SUBMIT (sau này) — extensions/browser/
        # routes.py nói thẳng "KHÔNG xoá staging ngay". Nên xoá nó khi CHỦ bấm
        # "Đồng bộ profile" (một thao tác bảo trì thường ngày, làm trong lúc
        # sharee đang làm việc) là hỏng đúng cái upload đang dở, với một lỗi
        # filesystem sharee không thể hiểu.
        def _staging(ws):
            return os.path.join(str(cfg.DATA_DIR), "guest_drive", ws)

        for ws in ("wsSync", "wsKill"):
            os.makedirs(_staging(ws), exist_ok=True)
            with open(os.path.join(_staging(ws), "clip.mp4"), "w", encoding="utf-8") as f:
                f.write("x")

        t_sync = auth.mint_guest_token({"workspace": "wsSync"})["guest_token"]
        r = c.post("/api/v1/auth/guest-token/revoke",
                   json={"workspace": "wsSync", "keep_staging": True})
        check("đồng bộ: token cũ vẫn bị giết", r.status_code == 200
              and r.json()["revoked"] == 1 and auth.guest_scope_for(t_sync) is None, r.text[:200])
        check("đồng bộ: file đang chờ SUBMIT còn nguyên",
              os.path.exists(os.path.join(_staging("wsSync"), "clip.mp4")))

        auth.mint_guest_token({"workspace": "wsKill"})
        r = c.post("/api/v1/auth/guest-token/revoke", json={"workspace": "wsKill"})
        check("thu hồi thật: staging bị dọn", r.status_code == 200
              and not os.path.exists(_staging("wsKill")), r.text[:200])

        # Không kẹp trong `if removed`: token vừa tự hết hạn thì vẫn phải dọn,
        # nếu không staging nằm lại vĩnh viễn.
        os.makedirs(_staging("wsGone"), exist_ok=True)
        check("thu hồi khi không còn token nào -> vẫn dọn staging",
              auth.revoke_guest_tokens_for_workspace("wsGone") == 0
              and not os.path.exists(_staging("wsGone")))

        route_src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", "tubecli-cloud", "app", "api", "workspaces", "[token]", "route.js"),
            encoding="utf-8", errors="replace").read()
        check("cloud: resync gửi keepStaging", "revokeGuestTokens(ws, { keepStaging: true })" in route_src)
        check("cloud: revoke/delete thì KHÔNG", route_src.count("revokeGuestTokens(ws)") == 1
              and "revokeGuestTokens(r.ws)" in route_src)
        # 8s phải bó CẢ lời gọi: tubecliFetch còn login() 2 lần x 15s trước khi
        # cái bó timeoutMs bắt đầu đếm, nên máy tắt = ~38s chủ ngồi đợi.
        check("cloud: hạn cứng bó cả helper, không chỉ fetch",
              "function withDeadline(" in route_src
              and "return withDeadline(call, HELPER_DEADLINE_MS," in route_src)

        print("\n=== 4. route KHÔNG được miễn đăng nhập ===")
        # Đọc bằng AST thay vì import server.py: import cả app kéo theo nửa hệ thống.
        server_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "tubecli", "api", "server.py")
        tree = ast.parse(open(server_src, encoding="utf-8").read())
        exempt_exact, exempt_prefix = None, None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_AUTH_EXEMPT_EXACT":
                    exempt_exact = ast.literal_eval(node.value)
                if isinstance(tgt, ast.Name) and tgt.id == "_AUTH_EXEMPT_PREFIX":
                    exempt_prefix = ast.literal_eval(node.value)
        p = "/api/v1/auth/guest-token/revoke"
        check("đọc được hai danh sách miễn trừ", exempt_exact is not None and exempt_prefix is not None)
        check("revoke KHÔNG nằm trong _AUTH_EXEMPT_EXACT", p not in (exempt_exact or ()), sorted(exempt_exact or ()))
        check("revoke KHÔNG khớp _AUTH_EXEMPT_PREFIX",
              not any(p.startswith(x) for x in (exempt_prefix or ())), exempt_prefix)
        check("mint cũng vẫn không được miễn", "/api/v1/auth/guest-token" not in (exempt_exact or ()))
        check("guest-login vẫn miễn (phải gọi được trước khi có phiên)",
              "/api/v1/auth/guest-login" in (exempt_exact or ()))

        print("\n=== 5. sharee không tự thu hồi / gia hạn được ===")
        # _guest_allowed là deny-by-default; chốt bằng nguồn: không có nhánh nào
        # nhắc tới đường /auth/ trong đó, nên guest không bao giờ tới được.
        src = open(server_src, encoding="utf-8").read()
        start = src.index("async def _guest_allowed(")
        end = src.index("def _cors_error_headers(", start)
        body = src[start:end]
        check("_guest_allowed không mở đường nào dưới /api/v1/auth/", "/api/v1/auth" not in body)
        check("_guest_allowed kết thúc bằng return False (deny mặc định)",
              body.rstrip().endswith("return False"), body.rstrip()[-40:])

    finally:
        cfg.DATA_DIR = saved
        auth._guest_cache.clear()
        auth._sessions.clear()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
