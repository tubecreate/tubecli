"""Gate guest cho EXTENSION node (option "mở cả nhóm, chạy bằng tài khoản chủ").

Chốt bằng nguồn: trích _guest_allowed từ server.py bằng AST (không import cả server —
import chạy discover_extensions() có thể git-clone), rồi gọi trực tiếp. Bảo vệ ranh
giới DÙNG vs QUẢN LÝ: sharee tổng hợp TTS được nhưng KHÔNG xoá tài khoản CapCut của
chủ / restart server, và không chạm namespace nhạy cảm (file-manager…) hay extension
chưa chia sẻ.
"""
import ast
import asyncio
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "tubecli", "api", "server.py")


def _load_guest_allowed():
    src = open(SERVER, encoding="utf-8").read()
    tree = ast.parse(src)
    fn = [n for n in tree.body
          if isinstance(n, ast.AsyncFunctionDef) and n.name == "_guest_allowed"]
    assert len(fn) == 1, "server.py phải có đúng một _guest_allowed"
    ns = {"_re": re, "Request": object}
    exec(compile(ast.Module(body=fn[:1], type_ignores=[]), "server.py", "exec"), ns)
    return ns["_guest_allowed"]


class _QP:
    def get(self, k, d=None):
        return d

    def getlist(self, k):
        return []


class _Req:
    def __init__(self, path, method="GET"):
        self.url = types.SimpleNamespace(path=path)
        self.method = method
        self.query_params = _QP()


def main():
    ga = _load_guest_allowed()
    passed = failed = 0

    def chk(desc, path, method, scope, expect):
        nonlocal passed, failed
        got = asyncio.run(ga(_Req(path, method), scope))
        ok = got is expect
        print(("[PASS]" if ok else "[FAIL]"), desc, "->", got)
        if ok:
            passed += 1
        else:
            failed += 1

    ctrl = {"extension_routes": ["/capcut-tts"], "access": "control"}
    view = {"extension_routes": ["/capcut-tts"], "access": "view"}
    none = {"access": "control"}   # nhóm không có extension node

    # ── DÙNG được (chạy bằng tài khoản chủ) ──
    chk("trang UI", "/capcut-tts", "GET", ctrl, True)
    chk("liệt kê ngôn ngữ", "/api/v1/capcut-tts/languages", "GET", ctrl, True)
    chk("liệt kê giọng", "/api/v1/capcut-tts/speakers", "GET", ctrl, True)
    chk("nghe thử giọng", "/api/v1/capcut-tts/preview/xyz", "GET", ctrl, True)
    chk("tổng hợp TTS", "/api/v1/capcut-tts/synthesize", "POST", ctrl, True)
    chk("trạng thái", "/api/v1/capcut-tts/status", "GET", ctrl, True)
    # ĐỌC quản lý cho qua: UI cần liệt kê tài khoản để điền dropdown chọn giọng.
    chk("đọc danh sách tài khoản (điền dropdown)", "/api/v1/capcut-tts/accounts", "GET", ctrl, True)
    chk("đọc region", "/api/v1/capcut-tts/region", "GET", ctrl, True)

    # ── GHI quản lý bị cấm (không để guest đụng tài khoản/máy chủ của chủ) ──
    chk("thêm tài khoản", "/api/v1/capcut-tts/accounts", "POST", ctrl, False)
    chk("XOÁ tài khoản chủ", "/api/v1/capcut-tts/accounts/a@b.com", "DELETE", ctrl, False)
    chk("bật/tắt tài khoản", "/api/v1/capcut-tts/accounts/a@b.com/toggle", "POST", ctrl, False)
    chk("đổi region", "/api/v1/capcut-tts/region", "POST", ctrl, False)
    chk("restart server ext", "/api/v1/capcut-tts/server/restart", "POST", ctrl, False)
    chk("xoá lịch sử", "/api/v1/capcut-tts/history/f.wav", "DELETE", ctrl, False)

    # ── Ranh giới ──
    chk("namespace nhạy cảm (file-manager)", "/api/v1/file-manager/list", "GET", ctrl, False)
    chk("extension chưa chia sẻ", "/api/v1/some-other/x", "GET", ctrl, False)
    chk("không có extension trong scope", "/api/v1/capcut-tts/synthesize", "POST", none, False)

    # ── view (chỉ xem): mở trang + đọc, KHÔNG hành động ──
    chk("view mở trang", "/capcut-tts", "GET", view, True)
    chk("view đọc giọng", "/api/v1/capcut-tts/speakers", "GET", view, True)
    chk("view KHÔNG tổng hợp", "/api/v1/capcut-tts/synthesize", "POST", view, False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
