"""End-to-end smoke test for GET /raw — the media preview byte channel.

Run:  python tests/file_manager_media_smoke.py     (exit 0 = pass)

Why this file exists. /raw is the only endpoint in the extension that returns
file bytes rather than JSON, and it serves them from the dashboard's own origin
while ~/Downloads — where anything the user downloads from the web lands — is a
default allowed root. If the extension allowlist ever springs a leak, a
downloaded .html or .svg becomes script running on an origin that has no
authentication and an endpoint that does git clone + pip install. That property
cannot be checked by reading the code, because the failure mode is a Content-Type
the browser is willing to execute; it needs a real request and a real assertion
on the status and the headers.

The same goes for Range: <video> is unseekable without it and Safari refuses a
plain 200 outright, so a regression there looks like "video preview is broken"
with nothing in the log.

The fixture lives under ~/Downloads (a default allowed root) and contains only
files this test creates and removes itself.
"""
import os
import re
import shutil
import struct
import sys
import zlib

# sys.path[0] is tests/, not the repo root, so `import tubecli` only works on a
# machine where the package happens to be pip-installed. Without this the test
# fails with ImportError on a fresh checkout, which reads as "the fix is broken"
# rather than "the package is not installed".
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The refusal messages are Vietnamese; a cp1252 console would otherwise abort the
# run with UnicodeEncodeError and look like a test failure.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tubecli.extensions.file_manager.routes import _MEDIA_TYPES, router_fm, router_legacy

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


def png_1x1():
    """A real 1x1 PNG, built here so Content-Length and Range offsets are exact."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
            + chunk(b"IEND", b""))


BASE = os.path.join(os.path.expanduser("~/Downloads"), "_fm_media_smoke")
PNG = png_1x1()
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\xAB" * 4000
FILES = {
    "pic.png": PNG,
    "clip.mp4": MP4,
    "doc.pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"0" * 200,
    # The three that must never be served, whatever else changes.
    "evil.html": b"<script>alert(document.domain)</script>",
    "evil.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "payload.js": b"fetch('/api/v1/files/read')",
    "notes.txt": b"hello",
}

app = FastAPI()
app.include_router(router_legacy)
app.include_router(router_fm)
client = TestClient(app)


def raw(path, prefix="/api/v1/file-manager", **kw):
    return client.get(f"{prefix}/raw", params={"path": path}, **kw)


def main():
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)
    for name, body in FILES.items():
        with open(os.path.join(BASE, name), "wb") as f:
            f.write(body)
    p = {n: os.path.join(BASE, n) for n in FILES}

    try:
        # ── Mounted under both prefixes ──────────────────────────────
        # include_router() snapshots the routes present when it runs, so a
        # decorator added below those two calls mounts nothing and 404s against
        # a server that reports a healthy startup.
        for prefix in ("/api/v1/files", "/api/v1/file-manager"):
            r = raw(p["pic.png"], prefix=prefix)
            check(f"{prefix}/raw phuc vu anh (200)", r.status_code == 200, f"got {r.status_code}")

        # ── The allowlist ────────────────────────────────────────────
        for name in ("evil.html", "evil.svg", "payload.js", "notes.txt"):
            r = raw(p[name])
            check(f"tu choi {name} (415)", r.status_code == 415, f"got {r.status_code}")
            check(f"  {name}: khong tra ra byte goc", FILES[name] not in r.content)

        # ── Headers that keep a served file from becoming a document ──
        r = raw(p["pic.png"])
        h = {k.lower(): v for k, v in r.headers.items()}
        csp = h.get("content-security-policy") or ""
        check("Content-Type lay tu bang, khong doan", h.get("content-type") == "image/png",
              h.get("content-type"))
        check("X-Content-Type-Options: nosniff", h.get("x-content-type-options") == "nosniff")
        check("Cross-Origin-Resource-Policy: same-origin",
              h.get("cross-origin-resource-policy") == "same-origin")
        check("CSP co default-src 'none' va sandbox",
              "default-src 'none'" in csp and "sandbox" in csp, csp)
        check("Content-Disposition: inline (khong phai attachment)",
              (h.get("content-disposition") or "").startswith("inline"), h.get("content-disposition"))
        check("byte tra ve nguyen ven", r.content == PNG, f"{len(r.content)}/{len(PNG)}")

        # PDF is the one type that must keep scripts, or Firefox's pdf.js
        # renders an empty frame.
        r = raw(p["doc.pdf"])
        csp = r.headers.get("content-security-policy", "")
        check("PDF bo token sandbox", r.status_code == 200 and "sandbox" not in csp, csp)
        check("PDF giu frame-ancestors 'self'", "frame-ancestors 'self'" in csp, csp)

        # Audio/video need media-src 'self' and cannot keep sandbox: a sandboxed
        # document has an opaque origin, so 'self' matches nothing and the
        # "open in a new tab" fallback plays silence. Measured in Chrome 150:
        # readyState stays 0 with sandbox, reaches 4 with this policy.
        r = raw(p["clip.mp4"])
        csp = r.headers.get("content-security-policy", "")
        check("video co media-src 'self'", "media-src 'self'" in csp, csp)
        check("video bo token sandbox", "sandbox" not in csp, csp)
        check("video giu default-src 'none'", "default-src 'none'" in csp, csp)
        # An image cannot execute anything, so it keeps the strictest policy.
        check("anh van giu sandbox",
              "sandbox" in raw(p["pic.png"]).headers.get("content-security-policy", ""))

        # ── Client and server media tables must not drift ────────────
        # A client entry the server refuses is a guaranteed error toast; a
        # server entry the client does not know about is a preview that never
        # opens. Read the JS table rather than trusting a comment.
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "tubecli", "extensions", "file_manager", "static", "file_manager.js")
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        block = re.search(r"var MEDIA = \{(.*?)\};", js, re.S)
        check("tim thay bang MEDIA trong file_manager.js", block is not None)
        if block:
            js_exts = set(re.findall(r"'(\.[a-z0-9]+)'\s*:", block.group(1)))
            py_exts = set(_MEDIA_TYPES)
            check(f"hai bang khop nhau ({len(py_exts)} duoi)", js_exts == py_exts,
                  f"chi client={sorted(js_exts - py_exts)} chi server={sorted(py_exts - js_exts)}")

        # ── Range: what makes <video> seekable and playable in Safari ──
        size = len(MP4)
        r = client.get("/api/v1/file-manager/raw", params={"path": p["clip.mp4"]},
                       headers={"Range": "bytes=0-1"})
        check("Range 0-1 tra 206", r.status_code == 206, f"got {r.status_code}")
        check("  Content-Range dung", r.headers.get("content-range") == f"bytes 0-1/{size}",
              r.headers.get("content-range"))
        r = client.get("/api/v1/file-manager/raw", params={"path": p["clip.mp4"]},
                       headers={"Range": f"bytes={size + 50}-"})
        check("Range vuot file tra 416", r.status_code == 416, f"got {r.status_code}")
        check("Accept-Ranges: bytes", raw(p["clip.mp4"]).headers.get("accept-ranges") == "bytes")

        # ── The sandbox still decides what exists ────────────────────
        blocked = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"
        check("ngoai vung cho phep bi tu choi", raw(blocked).status_code in (403, 404, 415),
              f"got {raw(blocked).status_code}")
        r = raw(BASE)
        check("thu muc bi tu choi", r.status_code in (400, 415), f"got {r.status_code}")

        # ── The cross-site guard must not lock out non-browser clients ─
        for site, want in ((None, 200), ("same-origin", 200), ("none", 200),
                           ("cross-site", 403), ("same-site", 403)):
            hdr = {} if site is None else {"Sec-Fetch-Site": site}
            r = raw(p["pic.png"], headers=hdr)
            check(f"Sec-Fetch-Site={site or '(vang)'} -> {want}", r.status_code == want,
                  f"got {r.status_code}")

        # ── HEAD: FastAPI's @get registers GET alone, so this needs the
        #    explicit methods list and silently 405s without it.
        r = client.head("/api/v1/file-manager/raw", params={"path": p["pic.png"]})
        check("HEAD tra 200 voi than rong",
              r.status_code == 200 and r.content == b"", f"got {r.status_code}")
    finally:
        shutil.rmtree(BASE, ignore_errors=True)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
