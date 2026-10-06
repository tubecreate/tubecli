# -*- coding: utf-8 -*-
"""Chép/dán trong trang /terminal (xterm) — chạy THẬT trong Chromium (Playwright), WebSocket giả ghi lại thứ gửi xuống máy.

User 6/10/2026: «tôi không copy được» — Ctrl+V bị gửi thành ^V (Codex CLI: «Failed to paste image: clipboard
unavailable»), Ctrl+C luôn ngắt lệnh, không chép được chữ ra.
Chạy:  python tests/terminal_clipboard_test.py      (exit 0 = pass; cần mạng tải xterm từ jsDelivr)
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from tubecli.api.terminal_routes import _TERMINAL_HTML  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} -> {detail}")


FAKE_WS = """<script>
window.SENT = [];
window.WebSocket = function(){ var self = this; window.WSI = this; this.readyState = 1;
  this.send = function(m){ window.SENT.push(JSON.parse(m)); };
  setTimeout(function(){ self.onopen && self.onopen(); }, 10); };
</script>"""


async def main():
    from playwright.async_api import async_playwright
    html = _TERMINAL_HTML.replace("<body>", "<body>" + FAKE_WS, 1)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(permissions=["clipboard-read", "clipboard-write"])
        page = await ctx.new_page()
        # Trang phải ở origin https/localhost để Clipboard API sống → phục vụ qua route giả
        await page.route("https://term.test/terminal", lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        await page.goto("https://term.test/terminal")
        await page.wait_for_function("window.Terminal && document.querySelector('.xterm-helper-textarea')", timeout=30000)
        await page.wait_for_timeout(300)

        async def inputs():
            return [m["data"] for m in await page.evaluate("window.SENT") if m.get("type") == "input"]

        # 1. Ctrl+V dán CHỮ của clipboard trình duyệt, không gửi ^V
        await page.evaluate("navigator.clipboard.writeText('echo hello từ clipboard')")
        await page.focus(".xterm-helper-textarea")
        await page.keyboard.press("Control+v")
        await page.wait_for_timeout(300)
        got = await inputs()
        check("1 Ctrl+V dán chữ từ clipboard trình duyệt, KHÔNG gửi ^V (\\x16) xuống máy",
              any("echo hello từ clipboard" in d for d in got) and "\x16" not in got, got)

        # 2. Ctrl+C khi không bôi đen = ngắt lệnh (^C) như cũ
        await page.evaluate("window.SENT.length = 0")
        await page.keyboard.press("Control+c")
        await page.wait_for_timeout(150)
        check("2 Ctrl+C khi KHÔNG bôi đen vẫn là ^C (ngắt lệnh)", await inputs() == ["\x03"], await inputs())

        # 3. Máy in một dòng chữ → bôi đen bằng chuột → Ctrl+C chép ĐÚNG chữ đó ra clipboard, không gửi ^C
        await page.evaluate("window.WSI.onmessage({ data: 'copy-me-12345 xin chào' })")
        await page.wait_for_timeout(200)
        await page.evaluate("navigator.clipboard.writeText('')")
        await page.evaluate("window.SENT.length = 0")
        box = await page.locator(".xterm-screen").bounding_box()
        await page.mouse.move(box["x"] + 2, box["y"] + 4)
        await page.mouse.down()
        await page.mouse.move(box["x"] + box["width"] - 4, box["y"] + 6)
        await page.mouse.up()
        await page.wait_for_timeout(300)
        await page.keyboard.press("Control+c")
        await page.wait_for_timeout(300)
        clip = await page.evaluate("navigator.clipboard.readText()")
        sent = await inputs()
        check("3 bôi đen rồi Ctrl+C → chữ vào clipboard, KHÔNG gửi ^C xuống máy",
              "copy-me-12345 xin chào" in clip and "" not in sent, (clip, sent))

        # 3b. Bôi đen là tự chép (không cần bấm gì)
        await page.evaluate("navigator.clipboard.writeText('')")
        await page.mouse.move(box["x"] + 2, box["y"] + 4)
        await page.mouse.down()
        await page.mouse.move(box["x"] + box["width"] - 4, box["y"] + 6)
        await page.mouse.up()
        await page.wait_for_timeout(500)
        clip = await page.evaluate("navigator.clipboard.readText()")
        check("3b bôi đen là tự chép vào clipboard", "copy-me-12345" in clip, clip)

        # 4. Ctrl+Shift+V cũng dán
        await page.evaluate("window.SENT.length = 0")
        await page.evaluate("navigator.clipboard.writeText('ls -la')")
        await page.focus(".xterm-helper-textarea")
        await page.keyboard.press("Control+Shift+v")
        await page.wait_for_timeout(300)
        got = await inputs()
        check("4 Ctrl+Shift+V cũng dán", any("ls -la" in d for d in got), got)
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{PASS} pass, {FAIL} fail")
    sys.exit(1 if FAIL else 0)
