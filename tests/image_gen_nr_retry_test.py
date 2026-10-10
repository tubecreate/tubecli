# -*- coding: utf-8 -*-
"""9Router: lỗi MẠNG thì nghỉ rồi thử lại (10/10/2026 — #334 hỏng 14/15 ảnh vì DNS hụt vài giây: «URLError: getaddrinfo
failed»). Lỗi HTTP của 9Router (từ chối / hết hạn mức) KHÔNG thử lại. Không gọi mạng thật.

Run:  python tests/image_gen_nr_retry_test.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from tubecli.core import image_gen as IG      # noqa: E402

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  ", label)
    else:
        FAIL += 1
        print("  FAIL", label, "—", str(detail)[:300])


waits, calls = [], []


async def no_sleep(s):
    waits.append(s)
IG._sleep = no_sleep
IG.nr_image_bytes = lambda ct, raw: raw
R = {"base": "https://nr.example/v1", "model": "cx/gpt-image-2", "headers": {}}
DNS = IG.ProviderError("error", "URLError: <urlopen error [Errno 11001] getaddrinfo failed>")


def post_seq(*outcomes):
    seq = list(outcomes)

    async def _post(url, data, headers, timeout):
        calls.append(url)
        o = seq.pop(0) if seq else seq_last[0]
        if isinstance(o, Exception):
            raise o
        return "image/png", o
    seq_last = [outcomes[-1]]
    return _post


IG._post_any = post_seq(DNS, DNS, b"PNG")
out = asyncio.run(IG._nr_generate(R, "p", "16:9", 60))
ok(out == b"PNG" and len(calls) == 3 and waits == [5.0, 15.0], "DNS hụt 2 lần → nghỉ 5 s, 15 s rồi vẽ được", (calls, waits))

calls.clear(), waits.clear()
IG._post_any = post_seq(IG.ProviderError("refused", "HTTP 400: content policy"))
try:
    asyncio.run(IG._nr_generate(R, "p", "16:9", 60))
    ok(False, "lỗi HTTP (từ chối) → ném ngay")
except IG.ProviderError as e:
    ok(e.kind == "refused" and len(calls) == 1 and not waits, "lỗi HTTP (từ chối) → ném ngay, không thử lại", (calls, waits))

calls.clear(), waits.clear()
IG._post_any = post_seq(IG.ProviderError("error", "HTTP 502: bad gateway"))
try:
    asyncio.run(IG._nr_generate(R, "p", "16:9", 60))
    ok(False, "HTTP 502 → ném")
except IG.ProviderError:
    ok(len(calls) == 1, "trả lời HTTP (kể cả 5xx) không coi là lỗi mạng", calls)

calls.clear(), waits.clear()
IG._post_any = post_seq(DNS)
try:
    asyncio.run(IG._nr_generate(R, "p", "16:9", 60))
    ok(False, "mạng chết hẳn → ném")
except IG.ProviderError as e:
    ok("getaddrinfo" in str(e) and len(calls) == 1 + len(IG.NR_NET_WAITS) and waits == list(IG.NR_NET_WAITS),
       "mạng chết hẳn → thử đủ 3 lần rồi ném lỗi gốc", (len(calls), waits))

ok(IG._net_glitch(IG.ProviderError("error", "TimeoutError: The read operation timed out"))
   and IG._net_glitch(IG.ProviderError("error", "RemoteDisconnected: Remote end closed connection"))
   and not IG._net_glitch(IG.ProviderError("rate_limit", "URLError: x")) and not IG._net_glitch(ValueError("timed out")),
   "phân loại: timeout / đứt kết nối là lỗi mạng; rate_limit hay lỗi khác loại thì không")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
