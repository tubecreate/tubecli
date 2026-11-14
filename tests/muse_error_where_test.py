# -*- coding: utf-8 -*-
"""Lỗi Muse báo MÁY nào, TRÌNH DUYỆT nào (14/11/2026).

User: GET /api/v1/muse/v1/videos/jobs/<id> trả 504 «Muse did not finish within 180 s» — «giúp tôi trả về thêm mã
server, tên server, tên trình duyệt».

Kiểm:
  A. cloud_identity cất server_name (None = giữ tên cũ, "" = xoá), làm sạch ký tự điều khiển, ≤ 80 ký tự
  B. _error: máy này → server_code + server_name + browser (hồ sơ) trong error{} và câu lỗi có nhãn
  C. việc quay clip nền lỗi → GET jobs/{id} trả cùng các trường
  D. lỗi từ nút Muse từ xa → máy + hồ sơ CỦA NÚT (không phải máy này), nhãn không gắn hai lần;
     nút cũ không báo → địa chỉ nút; chỗ ngồi remote<i> → địa chỉ nút
  E. route PUT cloud-identity nhận server_name

Run:  python tests/muse_error_where_test.py     (exit 0 = pass)
"""
import io
import json
import sys
import tempfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="muse_where_"))
CFG.DATA_DIR = TMP / "data"
CFG.EXTENSIONS_DATA_DIR = CFG.DATA_DIR / "extensions_data"
CFG.DATA_DIR.mkdir(parents=True)

from tubecli.core import cloud_identity as CI, muse as M  # noqa: E402
from tubecli.api import muse_routes as MR  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAIL.append(name)


def body(resp):
    return json.loads(resp.body.decode("utf-8"))


# ── A ──
CI.save("tuan89tk", "t3rwap", server_name="VPS\x07  Contabo\n 49")
check("A1 server_name làm sạch", CI.load().get("server_name") == "VPS Contabo 49", CI.load())
CI.save("tuan89tk", "t3rwap")
check("A2 None = giữ tên cũ", CI.load().get("server_name") == "VPS Contabo 49", CI.load())
CI.save("tuan89tk", "t3rwap", server_name="x" * 200)
check("A3 tối đa 80 ký tự", len(CI.load().get("server_name")) == 80)
CI.save("tuan89tk", "t3rwap", server_name="VPS Contabo 49")
check("A4 server_label", CI.server_label() == {"server_code": "t3rwap", "server_name": "VPS Contabo 49"},
      CI.server_label())

# ── B ──
e = M.MuseError("timeout", "Muse did not finish within 180 s.")
e.profile = "muse-vinh-21"
r = MR._error(e)
err = body(r)["error"]
check("B1 504 + code giữ nguyên", r.status_code == 504 and err["code"] == "timeout" and err["type"] == "muse_timeout", err)
check("B2 server_code/server_name/browser", err.get("server_code") == "t3rwap"
      and err.get("server_name") == "VPS Contabo 49" and err.get("browser") == "muse-vinh-21", err)
check("B3 câu lỗi có nhãn", err["message"] == "Muse: Muse did not finish within 180 s. "
      "[server t3rwap (VPS Contabo 49) · browser muse-vinh-21]", err["message"])
r = MR._error(M.MuseError("busy", "all seats busy"))
err = body(r)["error"]
check("B4 không có hồ sơ → vẫn báo máy, không có browser", err.get("server_code") == "t3rwap" and "browser" not in err, err)

# ── C ──
MR._VIDEO_JOBS["job1"] = {"status": "error", "created": __import__("time").time(), "error": e}
import asyncio  # noqa: E402
r = asyncio.run(MR.api_video_job("job1"))
err = body(r)["error"]
check("C1 jobs/{id} lỗi mang máy + trình duyệt", r.status_code == 504 and err.get("browser") == "muse-vinh-21"
      and err.get("server_code") == "t3rwap", err)

# ── D ── nút từ xa: giả lập urlopen
import urllib.request  # noqa: E402

_real_urlopen = urllib.request.urlopen


def fake_http_error(payload, code=504):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(json.dumps(payload).encode("utf-8")))
    return _open


remote_err = {"error": {"message": "Muse: Muse did not finish within 180 s. [server abc234 (Node B) · browser muse-b]",
                        "type": "muse_timeout", "code": "timeout", "server_code": "abc234",
                        "server_name": "Node B", "browser": "muse-b"}}
urllib.request.urlopen = fake_http_error(remote_err)
try:
    try:
        M._ask_remote({"base_url": "https://node-b.example/api/v1/muse", "key": "k"}, "remote0", "hi")
        got = None
    except M.MuseError as ex:
        got = ex
finally:
    urllib.request.urlopen = _real_urlopen
check("D1 nút báo máy của nó", got is not None and got.kind == "timeout"
      and got.where.get("server_code") == "abc234" and got.where.get("browser") == "muse-b", getattr(got, "where", got))
got.profile = "remote0"
err = body(MR._error(got))["error"]
check("D2 _error dùng máy CỦA NÚT", err.get("server_code") == "abc234" and err.get("server_name") == "Node B"
      and err.get("browser") == "muse-b" and err.get("node") == "https://node-b.example/api/v1/muse", err)
check("D3 nhãn không gắn hai lần", err["message"].count("[server ") == 1, err["message"])

urllib.request.urlopen = fake_http_error({"error": {"message": "Muse: boom", "code": "error"}}, 502)
try:
    try:
        M._ask_remote({"base_url": "https://old-node.example/api/v1/muse"}, "remote0", "hi")
        got = None
    except M.MuseError as ex:
        got = ex
finally:
    urllib.request.urlopen = _real_urlopen
err = body(MR._error(got))["error"]
check("D4 nút cũ → chỉ địa chỉ nút", err.get("node") == "https://old-node.example/api/v1/muse"
      and "server_code" not in err and "remote node https://old-node.example" in err["message"], err)

_real_settings = M.settings
M.settings = lambda: {**_real_settings(), "remotes": [{"base_url": "https://n0.example/api/v1/muse", "key": ""}]}
try:
    e2 = M.MuseError("error", "Muse did not make a video.")
    e2.profile = "remote0"
    err = body(MR._error(e2))["error"]
finally:
    M.settings = _real_settings
check("D5 chỗ ngồi remote0 → địa chỉ nút, không phải máy này", err.get("node") == "https://n0.example/api/v1/muse"
      and "server_code" not in err, err)

# ── E ──
from tubecli.api import instance_routes as IR  # noqa: E402
req = IR.CloudIdentityRequest(username="tuan89tk", server_code="t3rwap", server_name="Máy mới")
check("E1 request nhận server_name", req.server_name == "Máy mới")
check("E2 request cũ không có server_name = None", IR.CloudIdentityRequest(username="u1", server_code="t3rwap").server_name is None)

print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAIL: {FAIL}"))
sys.exit(1 if FAIL else 0)
