# -*- coding: utf-8 -*-
"""Token git không được rời máy — core/git_secrets.py (user 22/11/2026: «phần mà người khác có thể thấy trong tương lai»).

Bối cảnh: GET /api/v1/extensions trả git_url = remote.origin.url nguyên văn ⇒ extension cài bằng
https://ghp_…@github.com/… làm lộ token cho mọi kết nối MCP và khách dùng chung.

  A. strip_credentials / scrub: mọi dạng địa chỉ; không đụng chữ thường
  B. repo git THẬT (token giả): to_dict().git_url, sổ nguồn gốc, câu lỗi git pull; .git/config GIỮ NGUYÊN
  C. Chợ: kiểm cập nhật; đăng / sửa hàng: địa chỉ được gỡ token, gói có token thì KHÔNG gửi đi và lỗi không chứa token
  D. MCP: lớp che cuối ở text_result — kể cả token nằm đúng chỗ bị cắt
  E. cập nhật lõi: câu lỗi của git được che

Chạy:  python tests/git_secrets_test.py   (exit 0 = pass). Token đều là giả, ghép lúc chạy; không gọi mạng nào.
"""
import asyncio
import base64
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
os.environ["TUBECLI_CODEX_GPT_DIR"] = tempfile.mkdtemp(prefix="git_secrets_codex_")
os.environ["GIT_TERMINAL_PROMPT"] = "0"
os.environ["GCM_INTERACTIVE"] = "never"

from tubecli.core import git_secrets as G                       # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {str(detail).replace(TOK, '<TOK>')[:400]}")


TOK = "gh" + "p_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2"        # giả, đủ 36 ký tự
PAT = "github" + "_pat_" + "11ABCDEFG0aBcDeFgHiJkL_mNoPqRsTuVwXyZ0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ01234567"

# ── A ──
for name, url, want in [
    ("token làm tên đăng nhập", f"https://{TOK}@github.com/o/r.git", "https://github.com/o/r.git"),
    ("x-access-token:token", f"https://x-access-token:{TOK}@github.com/o/r.git", "https://github.com/o/r.git"),
    ("mật khẩu có dấu @", "https://me:p@ss@host.com/r.git", "https://host.com/r.git"),
    ("token không phải GitHub (GitLab)", "https://oauth2:glpat-abc123@gitlab.com/o/r.git", "https://gitlab.com/o/r.git"),
    ("HTTPS hoa", f"HTTPS://{TOK}@github.com/o/r", "HTTPS://github.com/o/r"),
    ("token trong query", f"https://host.com/r.git?t={TOK}", "https://host.com/r.git?t=ghp_***"),
    ("fine-grained", f"https://{PAT}@github.com/o/r.git", "https://github.com/o/r.git"),
    ("ssh kèm mật khẩu", "ssh://git:pw@host.com/r.git", "ssh://git@host.com/r.git"),
    ("sạch giữ nguyên", "https://github.com/o/r.git", "https://github.com/o/r.git"),
    ("git@ giữ nguyên", "git@github.com:o/r.git", "git@github.com:o/r.git"),
    ("đường dẫn có @ sau host giữ nguyên", "https://www.npmjs.com/package/@vue/core", "https://www.npmjs.com/package/@vue/core"),
    ("thư mục máy", r"C:\repo\x", r"C:\repo\x"), ("None", None, ""), ("khoảng trắng", "  https://github.com/o/r \n", "https://github.com/o/r"),
]:
    check(f"A {name}", G.strip_credentials(url) == want, G.strip_credentials(url))
msg = f"fatal: could not read Password for 'https://{TOK}@github.com': terminal prompts disabled"
check("A câu lỗi git thật: che token, giữ phần còn lại", G.scrub(msg) == "fatal: could not read Password for 'https://github.com': terminal prompts disabled", G.scrub(msg))
plain = "gửi a@gmail.com, xem https://tubecreate.com/@kenh?x=1 và high_ghost_story; ghp_ là gì; user@host"
check("A chữ thường không bị đụng (email, /@kenh, «ghp_»)", G.scrub(plain) == plain, G.scrub(plain))
check("A nhiều token một dòng", G.scrub(f"{TOK} {TOK}") == "ghp_*** ghp_***")

# ── B ──
import tubecli.core.extension_manager as EM                     # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="git_secrets_"))
repo = tmp / "ext"
repo.mkdir()
BAD = f"https://{TOK}@127.0.0.1:9/o/r.git"


def git(*a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


git("init", "-q")
git("remote", "add", "origin", BAD)
(repo / "tubecli-extension.json").write_text(json.dumps({"name": "x_ext", "version": "1.0.0"}), encoding="utf-8")
git("add", "-A")
git("-c", "user.name=t", "-c", "user.email=t@t.t", "commit", "-q", "-m", "x")
check("B1 get_git_remote_url không có token", EM.get_git_remote_url(str(repo)) == "https://127.0.0.1:9/o/r.git", EM.get_git_remote_url(str(repo)))
check("B2 .git/config GIỮ NGUYÊN (git trên máy vẫn dùng được)", TOK in (repo / ".git" / "config").read_text(encoding="utf-8"))


class Ext(EM.Extension):
    name, version, description, author, extension_type = "x_ext", "1.0.0", "", "", "external"


try:
    e = Ext()
    e.extension_dir = str(repo)
    d = e.to_dict()
    check("B3 to_dict (GET /api/v1/extensions) có git_url, không có token ở bất kỳ trường nào", d["git_url"] == "https://127.0.0.1:9/o/r.git" and TOK not in json.dumps(d, default=str), d)
except TypeError as ex:
    check("B3 dựng được Extension giả", False, ex)
prov = EM._provenance_entry(BAD, str(repo))
check("B4 sổ nguồn gốc (mới + dòng cũ ghi lại) không có token", TOK not in json.dumps(prov) and prov["source"].endswith("/o/r.git"), prov)
r = git("pull", "origin", "main")
check("B5 git thật hỏng → câu lỗi đã che", r.returncode != 0 and TOK not in EM._scrub_git(r.stderr), r.stderr)
src = (ROOT / "tubecli/core/extension_manager.py").read_text(encoding="utf-8")
check("B6 không còn chỗ trả stderr git thô", "{result.stderr}" not in src.split("def install_from_git")[1].split("def ", 1)[0] and "Git pull failed: {result.stderr}" not in src)

# ── C ──
from tubecli.extensions.market import market_service as MSM     # noqa: E402

MS = MSM.market_service
SENT = []


class Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"status": "success"}


class Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _send(self, url, json=None, **k):
        SENT.append(json)
        return Resp()

    post = put = _send


if getattr(MSM, "httpx", None):
    MSM.httpx.AsyncClient = Client


def files_pack(content, **extra):
    return {"manifest": {"name": "x"}, "files": [{"path": "readme.md", "content": "ok"}, {"path": "core/a.py", "content": content, **extra}]}


def gz(obj):
    return json.dumps({"format": "gzip+b64", "data": base64.b64encode(gzip.compress(json.dumps(obj).encode())).decode()})


def up(item_data, git_url=None, fn="upload_item"):
    SENT.clear()
    kw = dict(token="t", title="X", description="", category="extension", price=0, item_data=item_data, git_url=git_url)
    if fn == "update_item":
        kw["public_id"] = "abc"
    return asyncio.run(getattr(MS, fn)(**kw))


for fn in ("upload_item", "update_item"):
    up(json.dumps(files_pack("print(1)")), BAD, fn)
    check(f"C1 {fn}: gói sạch được gửi, git_url đã gỡ token", len(SENT) == 1 and SENT[0]["git_url"] == "https://127.0.0.1:9/o/r.git" and TOK not in json.dumps(SENT), SENT)
    for label, data in (("JSON", json.dumps(files_pack(f"T='{TOK}'"))), ("gzip+b64", gz(files_pack(f"T='{TOK}'"))),
                        ("JSON lồng chuỗi", json.dumps(json.dumps(files_pack(f"x {PAT}")))),
                        ("file nhị phân base64", json.dumps(files_pack("", content_b64=base64.b64encode(f"a {TOK}".encode()).decode())))):
        r = up(data, None, fn)
        check(f"C2 {fn}: token trong gói ({label}) → KHÔNG gửi, nói đúng file, không in token", not SENT and "core/a.py" in str(r.get("error"))
              and TOK not in str(r) and PAT not in str(r) and "readme.md" not in str(r), r)
    r = up(json.dumps({"manifest": {"git_url": BAD}, "files": []}), None, fn)
    check(f"C3 {fn}: token trong manifest.git_url → từ chối", not SENT and "manifest.git_url" in str(r.get("error")), r)
for label, ok in (("ví dụ ghp_xxxx", "ghp_" + "x" * 36), ("ví dụ ngắn", "ghp_abc"), ("chữ ghost_", "high_" + "ghp_like text"), ("<your token>", "ghp_<token>"),
                  ("ví dụ ghp_1234", "ghp_" + "1234567890" * 2)):
    check(f"C4 tài liệu có {label} không bị chặn oan", G.publish_refusal(json.dumps(files_pack(ok))) == "", G.publish_refusal(json.dumps(files_pack(ok))))
for bad in (None, "", "không phải json", {"format": "gzip+b64", "data": "!!"}, 5, []):
    check(f"C5 dữ liệu lạ không ném ({type(bad).__name__})", G.publish_refusal(bad) == "")
mr = (ROOT / "tubecli/extensions/market/routes.py").read_text(encoding="utf-8")
check("C6 kiểm cập nhật của Chợ gỡ token", "git_url = strip_credentials(url_out)" in mr and "git_url = url_out.strip()" not in mr)

# ── D ──
from tubecli.extensions.codex_gpt import tools as T             # noqa: E402


def mcp(s):
    return T.text_result(s)["content"][0]["text"]


check("D1 MCP: token trong JSON bị che", TOK not in mcp(json.dumps({"git_url": BAD})) and "127.0.0.1:9/o/r.git" in mcp(json.dumps({"git_url": BAD})))
check("D2 proxy / địa chỉ kèm mật khẩu bị che", "pw9" not in mcp("http://u:pw9@1.2.3.4:80"))
edge = "a" * (T.OUT_CAP - 12) + " " + TOK
check("D3 token nằm ở chỗ bị cắt: không lọt một nửa", TOK[:8] not in mcp(edge), mcp(edge)[-60:])
check("D4 chữ thường, tiếng Việt giữ nguyên", mcp(plain) == plain)

# ── E ──
sv = (ROOT / "tubecli/api/server.py").read_text(encoding="utf-8")
check("E1 cập nhật lõi: mọi lệnh git trong _git_pull_safe đi qua che", "res.stdout, res.stderr = scrub(res.stdout), scrub(res.stderr)" in sv)
check("E2 kiểm bản mới: câu lỗi git fetch được che", 'check_error = scrub("git fetch origin: "' in sv)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
