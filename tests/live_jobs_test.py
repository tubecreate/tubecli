# -*- coding: utf-8 -*-
"""Live view biết ô đang chạy model nào, ghế nào, máy nào (22/10/2026).

User (bảng việc → Live view, ô cảnh đang vẽ): «chỗ placeholder hiển thị loading biết ảnh đó đang chạy model nào ở ghế nào,
ở máy chủ nào».

Kiểm:
  A. core/live_jobs: không nhãn → note() không làm gì; begin/note/finish; mốc since (đặt / xoá / giữ); nhãn đi qua
     asyncio.to_thread và KHÔNG lẫn giữa hai coroutine chạy song song; dòng mồ côi bị bỏ; cắt chuỗi dài; host_of / server_of
  B. image_gen._live_note + _generate_bytes: 9Router ghi model + tài khoản + máy 9Router (127.0.0.1 → «local»);
     Cloudflare ghi tên nhà; lùi sang Muse xoá ghế / máy / mốc giờ của nhà trước (ô hiện «chờ ghế»)
  C. muse._live_seat: ghế máy này = khoá chỗ ngồi + «local»; nút từ xa = «remote seat N» + tên máy; ask() gọi sau _acquire

Run:  python tests/live_jobs_test.py
"""
import asyncio
import inspect
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

import tubecli.config as CFG  # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="live_jobs_"))
CFG.GLOBAL_SETTINGS_FILE = TMP / "global_settings.json"
from tubecli.core import live_jobs as LJ  # noqa: E402
from tubecli.core import image_gen as G  # noqa: E402
from tubecli.core import muse as M  # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "" if detail is None else f"— {str(detail)[:300]}")


def row(tag):
    return LJ.snapshot().get(tag) or {}


print("A. core/live_jobs")
LJ.note(model="x")
ok(LJ.snapshot() == {}, "không nhãn → note() không mở dòng nào")
tok = LJ.begin("shot:7")
ok(LJ.TAG.get() == "shot:7" and "shot:7" in LJ.snapshot("shot:"), "begin gắn nhãn + mở dòng")
ok("since" not in row("shot:7"), "chưa ghi gì → chưa có mốc giờ")
LJ.note(provider="9router", model="cx/gpt-image-2")
s1 = row("shot:7").get("since")
ok(row("shot:7").get("model") == "cx/gpt-image-2" and s1, "ghi model lần đầu → đặt mốc since", row("shot:7"))
time.sleep(0.01)
LJ.note(seat="key 2")
ok(row("shot:7").get("since") == s1 and row("shot:7").get("seat") == "key 2", "since=None giữ mốc cũ")
LJ.note(seat="", since=False)
ok("since" not in row("shot:7") and row("shot:7").get("seat") == "", "since=False xoá mốc (đang chờ ghế)")
LJ.note(seat="chayagent", since=True)
ok(row("shot:7").get("since", 0) > s1, "since=True đặt lại = bây giờ")
LJ.note(model="m" * 500)
ok(len(row("shot:7")["model"]) == 120, "chuỗi dài bị cắt 120 ký tự")
ok(set(LJ.snapshot("hook:")) == set(), "snapshot lọc theo tiền tố")
LJ.finish(tok)
ok(LJ.TAG.get() == "" and "shot:7" not in LJ.snapshot(), "finish gỡ dòng + trả nhãn")
LJ.finish(None)
ok(LJ.begin("") is None and LJ.begin("   ") is None, "nhãn rỗng → không mở")


def _worker(model):
    LJ.note(provider="p", model=model)
    return LJ.TAG.get()


async def _shot(sid, model):
    t = LJ.begin(f"shot:{sid}")
    try:
        await asyncio.sleep(0.01)
        seen = await asyncio.to_thread(_worker, model)
        await asyncio.sleep(0.01)
        return seen, row(f"shot:{sid}").get("model")
    finally:
        LJ.finish(t)


async def _both():
    return await asyncio.gather(_shot(1, "alpha"), _shot(2, "beta"))


res = asyncio.run(_both())
ok(res == [("shot:1", "alpha"), ("shot:2", "beta")], "hai cảnh song song: nhãn đi qua to_thread, không lẫn model", res)
ok(LJ.snapshot() == {}, "xong cả hai → không còn dòng", LJ.snapshot())

tok = LJ.begin("shot:old")
with LJ._LOCK:
    LJ._JOBS["shot:old"]["at"] = time.time() - LJ.STALE_SEC - 5
ok("shot:old" not in LJ.snapshot(), "dòng mồ côi quá STALE_SEC bị bỏ")
LJ.finish(tok)
ok(LJ.host_of("https://tungho2-23.tubecreate.com/api/v1/muse") == "tungho2-23.tubecreate.com"
   and LJ.host_of("") == "" and LJ.host_of(None) == "", "host_of lấy tên máy")
ok(LJ.server_of("http://127.0.0.1:20128/v1") == "local" and LJ.server_of("http://localhost:5295") == "local"
   and LJ.server_of("https://nr.example.com/v1") == "nr.example.com", "server_of: địa chỉ về chính máy = «local»")

print("B. image_gen")
tok = LJ.begin("shot:11")
G._live_note({"provider": "9router", "model": "cx/gpt-image-2", "label": "key 2", "base": "https://nr.example.com/v1"})
r11 = row("shot:11")
ok(r11.get("provider") == "9router" and r11.get("model") == "cx/gpt-image-2" and r11.get("seat") == "key 2"
   and r11.get("server") == "nr.example.com" and r11.get("job") == "image" and r11.get("since"), "9Router: model + tài khoản + máy", r11)
G._live_note({"provider": "9router", "model": "cx/gpt-image-2", "label": "", "base": "http://127.0.0.1:20128/v1"})
ok(row("shot:11").get("server") == "local", "9Router chạy ở máy này → «local»")
G._live_note({"provider": "cloudflare", "model": "@cf/black-forest-labs/flux-1-schnell", "label": "acc 1",
              "base": "https://api.cloudflare.com/client/v4"})
ok(row("shot:11").get("server") == "cloudflare" and row("shot:11").get("seat") == "acc 1", "Cloudflare: máy = tên nhà, không «api»")
G._live_note({"provider": "muse", "model": "muse-image"})
r11 = row("shot:11")
ok(r11.get("provider") == "muse" and r11.get("seat") == "" and r11.get("server") == "" and "since" not in r11,
   "lùi sang Muse: xoá ghế / máy / mốc của nhà trước", r11)
LJ.finish(tok)
G._live_note({"provider": "gemini", "model": "g"})
ok(LJ.snapshot() == {}, "không nhãn cảnh → _live_note không ghi")

_real_nrg, _real_gmg = G._nr_generate, G._gemini_generate
SEEN = []


async def _nr_boom(r, prompt, aspect, timeout):
    SEEN.append(dict(row("shot:12")))
    raise G.ProviderError("error", "HTTP 502: bad gateway")


async def _gm_ok(r, prompt, aspect, refs, timeout):
    SEEN.append(dict(row("shot:12")))
    return b"IMG"


async def _draw():
    t = LJ.begin("shot:12")
    try:
        r = {"provider": "9router", "model": "cx/gpt-image-2", "label": "key 1", "base": "https://nr.example.com/v1",
             "fallback": {"provider": "gemini", "model": "gemini-2.5-flash-image", "label": "default", "base": ""}}
        return await G._generate_bytes(r, "p", "16:9", None, 30)
    finally:
        LJ.finish(t)


G._nr_generate, G._gemini_generate = _nr_boom, _gm_ok
try:
    data = asyncio.run(_draw())
finally:
    G._nr_generate, G._gemini_generate = _real_nrg, _real_gmg
ok(data == b"IMG" and len(SEEN) == 2, "_generate_bytes vẽ qua đường lùi", SEEN)
ok(SEEN and SEEN[0].get("model") == "cx/gpt-image-2" and SEEN[0].get("server") == "nr.example.com",
   "lúc gọi 9Router: ô ghi đúng model / máy 9Router", SEEN[:1])
ok(len(SEEN) > 1 and SEEN[1].get("provider") == "gemini" and SEEN[1].get("model") == "gemini-2.5-flash-image"
   and SEEN[1].get("server") == "gemini", "lùi: ô đổi sang nhà / model THẬT đang vẽ", SEEN[1:])

print("C. muse")
tok = LJ.begin("shot:21")
M._live_seat("chayagent", "chayagent#2", [], False, True, False)
r21 = row("shot:21")
ok(r21.get("provider") == "muse" and r21.get("seat") == "chayagent#2" and r21.get("server") == "local"
   and r21.get("job") == "video" and r21.get("since"), "ghế máy này: khoá chỗ ngồi + «local» + clip", r21)
M._live_seat(f"{M.REMOTE_PREFIX}0", f"{M.REMOTE_PREFIX}0#3", [{"base_url": "https://muse-node.example.com/api/v1/muse"}],
             True, False, False)
r21 = row("shot:21")
ok(r21.get("seat") == "remote seat 3" and r21.get("server") == "muse-node.example.com" and r21.get("job") == "image",
   "nút từ xa: «remote seat N» + tên máy", r21)
M._live_seat(f"{M.REMOTE_PREFIX}5", "k", [], True, False, False)
ok(row("shot:21").get("seat") == "remote seat 3", "chỉ số nút sai → không ném, giữ dòng cũ")
LJ.finish(tok)
src = inspect.getsource(M.ask)
ok(src.index("_acquire(") < src.index("_live_seat(prof, key"), "ask() ghi ghế NGAY sau khi giữ được chỗ")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
