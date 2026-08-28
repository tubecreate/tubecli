"""Every built-in extension page must follow the dashboard's theme, light included.

Run:  python tests/theme_sync_test.py              (exit 0 = pass)
      python tests/theme_sync_test.py --dashboard   (only the dashboard-side contract)

Why this file exists. The dashboard grew a light theme (?theme=glass, or the OS
preference when opened standalone) and every embedded extension stayed a dark
rectangle inside it: the pages defined their own dark palettes as literals, and
the dashboard told an iframe about its theme only by injecting a handful of
tokens after load — nothing set data-theme on the page, nothing reached a page's
own tokens, and a page's pre-paint script had no URL parameter to read.

Two contracts, both asserted against the files as served:

  1. Dashboard side (tubecli/extensions/webui/static/app.js)
     - every extension iframe URL carries theme=<light|dark>;
     - syncThemeToIframe stamps data-theme on the iframe's <html>;
     - an OS prefers-color-scheme flip re-syncs every loaded iframe.

  2. Page side (each built-in page listed in PAGES)
     - a pre-paint script in <head> reads ?theme= (light|glass -> light,
       dark -> dark, embedded without a parameter -> dark) BEFORE the first
       stylesheet, so there is no dark flash inside a light dashboard;
     - a :root[data-theme="light"] block and a prefers-color-scheme: light
       block exist and are token-identical (CSS cannot share them; a value
       edited in one and forgotten in the other is the classic drift);
     - the light ground / panel / ink values are the dashboard's own
       (#f7f8fa / #ffffff / #1e293b) so pages do not clash with each other.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "tubecli" / "extensions"
WEBUI = EXT / "webui" / "static"

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


# ── 1. dashboard side ──────────────────────────────────────────────────────
app = read(WEBUI / "app.js")
check("app.js defines window.currentTheme", "window.currentTheme = function" in app)
check("currentTheme honours an explicit data-theme pin before the OS preference",
      re.search(r"pinned === 'light' \|\| pinned === 'dark'\) return pinned", app) is not None)
check("app.js has one themedSrc helper that appends the theme to a URL",
      "window.themedSrc = function(url)" in app and "'theme=' + window.currentTheme()" in app)
# Three places create an extension iframe: the lazy tab loader, the full-page
# extension host and the workflow builder. Every one must go through the helper,
# or that surface loads dark inside a light dashboard and flashes when it syncs.
iframe_srcs = re.findall(r"(?:iframe\.src\s*=|<iframe src=)([^;\n]*)", app)
check("every iframe src goes through themedSrc",
      bool(iframe_srcs) and all("themedSrc" in src for src in iframe_srcs),
      [src for src in iframe_srcs if "themedSrc" not in src])
check("syncThemeToIframe stamps data-theme on the iframe root",
      "doc.documentElement.setAttribute('data-theme', window.currentTheme())" in app)
check("an OS light/dark flip re-syncs every loaded iframe",
      "matchMedia('(prefers-color-scheme: light)').addEventListener('change'" in app
      and "querySelectorAll('iframe.ext-iframe[src]').forEach(f => window.syncThemeToIframe(f))" in app)

# ── 1b. the user's own choice ──────────────────────────────────────────────
# Until this control existed the light palette could only be reached by an OS
# preference or by the ?theme= parameter the cloud canvas appends — a user who
# wanted light on a dark machine had no way to ask for it.
index = read(WEBUI / "index.html")
check("Settings carries a Theme control with system/light/dark",
      'id="set-theme"' in index
      and 'value="system"' in index and 'value="light"' in index and 'value="dark"' in index)
check("changing it goes through applyThemeChoice",
      'onchange="applyThemeChoice(this.value, this)"' in index)
check("the control is labelled through i18n, not a hardcoded string",
      'data-i18n="settings.theme"' in index and 'data-i18n="settings.theme_system"' in index)

# The pre-paint script decides before the first frame, so it — not app.js — is
# what stops a dark flash on a light-themed dashboard.
head = index.split("</head>", 1)[0]
check("the pre-paint script reads the saved choice AND acts on it",
      "localStorage.getItem('tubecli_theme')" in head
      and "saved === 'light' || saved === 'dark'" in head
      and "dataset.theme = saved" in head,
      "the value is read but never applied")
check("a ?theme= parameter still outranks the saved choice",
      head.index("get('theme')") < head.index("localStorage.getItem('tubecli_theme')"),
      "the stored preference is read before the URL parameter")
check("'system' means the OS decides — the embedded dark pin must not override it",
      "saved !== 'system' && window.self !== window.top" in head)

check("app.js applies a choice without a reload and re-syncs open iframes",
      "window.applyTheme = function(choice)" in app
      and "delete document.documentElement.dataset.theme" in app
      and "forEach(f => window.syncThemeToIframe(f))" in app)
check("choosing a theme saves it locally AND to the server",
      "localStorage.setItem('tubecli_theme', choice)" in app
      and "autoSaveSetting('theme', choice, inputEl)" in app)
check("Settings reconciles the page with the stored choice, unless the URL asked",
      "if (!new URLSearchParams(location.search).get('theme')) window.applyTheme(savedTheme)" in app)
check("an extension opened in a NEW TAB carries the theme too",
      "window.open(window.themedSrc(url), '_blank')" in app,
      "new-tab opens still pass a bare URL")

# ── 1c. what the verification pass found ───────────────────────────────────
# The blanket rescue rules. syncThemeToIframe used to force body, .header and the
# studio containers into every embedded page with !important. That was the only
# way to move a page that knew nothing about themes — and it overrode five pages
# that now theme themselves. It is now applied only when the page did not follow
# the injected tokens, so the pages that handle themselves are left alone and the
# ones that do not are still rescued.
check("the rescue rules are conditional, not unconditional",
      "if (!followed) {" in app and "const wantLight = window.currentTheme() === 'light'" in app,
      "body/.header/.studio-* are injected into every page again")
check("the decision reads what the page actually rendered",
      "getComputedStyle(doc.body).backgroundColor" in app and "0.2126 * r + 0.7152 * g + 0.0722 * b" in app)
check("tokens are still injected unconditionally",
      "styleEl.innerHTML = cssText;" in app)

# Every window.open of an extension page carries the theme: a popup has no
# parent to sync it afterwards, so the URL is the only channel.
opens = re.findall(r"window\.open\(([^,]+),", app)
check("every window.open of a page goes through themedSrc",
      bool(opens) and all("themedSrc" in o for o in opens),
      [o.strip()[:60] for o in opens if "themedSrc" not in o])

# A translation interpolated into an attribute. The auto-refresh tooltip quotes
# Google's wording — …consent screen is in "Testing" mode… — and the raw double
# quote closed the title attribute, spilling the rest of the sentence into the
# STATUS cell as markup on every auto-refresh row.
am = read(WEBUI / "auth_manager.js")
check("auth_manager escapes text interpolated into an attribute",
      "function escAttr(" in am and 'title="${escAttr(' in am,
      "a translation is interpolated into title= unescaped")
check("escAttr neutralises the quote that caused it",
      ".replace(/\"/g, '&quot;')" in am)

# An unresolved i18n key used to be written over the element, replacing authored
# English with the key itself. 104 of the 105 unresolved keys in this repo sit on
# markup that already carries good text.
i18n = read(WEBUI / "i18n.js")
check("applyI18n leaves the markup's own text alone when a key resolves nowhere",
      "function _resolves(key)" in i18n
      and "if (_resolves(key)) el.textContent = T(key);" in i18n,
      "the applier still overwrites with T(key) unconditionally")
check("the same holds for placeholder and title",
      "if (_resolves(key)) el.placeholder = T(key);" in i18n
      and "if (_resolves(key)) el.title = T(key);" in i18n)

# The one key with nothing to fall back on.
fm_locales = EXT / "file_manager" / "locales"
import json as _json
for lang in ("en", "vi"):
    try:
        d = _json.loads((fm_locales / f"{lang}.json").read_text(encoding="utf-8"))
    except Exception:
        d = {}
    check(f"fm.upload has a {lang} string (the button has no fallback text)", bool(d.get("fm.upload")))

# Tokenising a literal is only safe when the token's dark value equals it.
wm = read(EXT / "website_manager" / "static" / "index.html")
check("the deploy error banner keeps its original dark red",
      "--err-on-wash: #f87171;" in wm and "color:var(--err-on-wash)" in wm,
      "the banner reads var(--red) (#ef4444) instead of the #f87171 it had")
check("the terminal's error rows use the same ink as the banner",
      ".terminal-body .log-err { color: var(--err-on-wash); }" in wm)
bv = read(WEBUI / "browser_view.html")
check("the Retry button on the black preview stage keeps its white hairline",
      "--stage-btn-line: rgba(255, 255, 255, 0.2);" in bv
      and "border:1px solid var(--stage-btn-line)" in bv,
      "it reads var(--border), which is the page chrome's colour")

# An extension page is HTML with no asset token of its own; served with only an
# ETag a browser may reuse it without revalidating, which is how a rewritten
# page kept rendering its old markup in an open tab.
routes = read(EXT / "webui" / "routes.py")
check("extension HTML pages are served no-store",
      'FileResponse(path, headers={"Cache-Control": "no-store"})' in routes
      and "return FileResponse(html_file)" not in routes,
      "a page route still returns a bare FileResponse")

if "--dashboard" in sys.argv:
    print(f"\n{checks - len(failures)}/{checks} PASS")
    for f in failures:
        print("  FAIL " + f)
    sys.exit(1 if failures else 0)

# ── 2. page side ───────────────────────────────────────────────────────────
# (html, [css files whose light blocks are checked]). A page whose styling is
# inline lists no css — its light blocks are searched in the html itself.
PAGES = {
    "file_manager":     (EXT / "file_manager/static/file_manager.html", [EXT / "file_manager/static/file_manager.css"]),
    "chat":             (EXT / "chat/static/chat.html", [EXT / "chat/static/chat.css"]),
    "codex":            (EXT / "codex/static/codex.html", [EXT / "codex/static/codex.css"]),
    "browser_scripts":  (EXT / "browser_scripts/static/index.html", [EXT / "browser_scripts/static/styles.css"]),
    "video_downloader": (EXT / "video_downloader/static/index.html", []),
    "video_editor":     (EXT / "video_editor/static/editor.html", [EXT / "video_editor/static/editor.css"]),
    "video_processing": (EXT / "video_editor/static/processing.html", []),
    "website_manager":  (EXT / "website_manager/static/index.html", []),
    "auth_manager":     (WEBUI / "auth_manager.html", [WEBUI / "auth_manager.css"]),
    "downloader":       (WEBUI / "downloader.html", []),
    "market":           (WEBUI / "market.html", [WEBUI / "market.css"]),
    "pipeline_monitor": (WEBUI / "pipeline_monitor.html", []),
    "story":            (WEBUI / "story.html", []),
    "studio":           (WEBUI / "studio.html", [WEBUI / "teams.css"]),
    "teams":            (WEBUI / "teams.html", [WEBUI / "teams.css"]),
    "tracker":          (WEBUI / "tracker.html", []),
    "workflow":         (WEBUI / "workflow.html", [WEBUI / "workflow.css"]),
    "browser_view":     (WEBUI / "browser_view.html", []),
}

LIGHT_ATTR = re.compile(r':root\[data-theme="light"\]\s*\{([^}]*)\}', re.S)
LIGHT_MEDIA = re.compile(r'@media\s*\(prefers-color-scheme:\s*light\)\s*\{\s*:root:not\(\[data-theme="dark"\]\)\s*\{([^}]*)\}', re.S)


def hue(v: str):
    """Hue in degrees of a #rgb/#rrggbb value, or None if it is not one."""
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v.strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return None  # grey: no hue to compare
    d = mx - mn
    if mx == r:
        deg = 60 * (((g - b) / d) % 6)
    elif mx == g:
        deg = 60 * ((b - r) / d + 2)
    else:
        deg = 60 * ((r - g) / d + 4)
    return deg


def decls(block: str) -> dict:
    out = {}
    for line in block.split(";"):
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            if k.startswith("--") or k == "color-scheme":
                out[k] = re.sub(r"\s+", " ", v.strip()).lower()
    return out


for name, (html_path, css_paths) in PAGES.items():
    html = read(html_path)
    if not html:
        check(f"{name}: page file exists", False, str(html_path))
        continue

    # pre-paint reader in <head>, before the first stylesheet / inline style
    head = html.split("</head>", 1)[0]
    reader = re.search(r"<script[^>]*>(?:(?!</script>).)*get\('theme'\)(?:(?!</script>).)*</script>", head, re.S)
    check(f"{name}: a pre-paint script reads ?theme= in <head>", reader is not None)
    if reader:
        body = reader.group(0)
        check(f"{name}: theme reader maps glass/light -> light and dark -> dark, embedded -> dark",
              "'glass'" in body and "'light'" in body and "'dark'" in body and "window.self" in body and "window.top" in body,
              body[:160])
        # A fonts.googleapis.com <link> carries no palette, so it does not count:
        # what must not paint before the reader is the page's OWN styling.
        styles = [m.start() for m in re.finditer(r"<link[^>]+rel=\"stylesheet\"[^>]*>|<style", head)
                  if "fonts.googleapis.com" not in head[m.start():m.end()]]
        first_style = min(styles or [len(head)])
        check(f"{name}: theme reader runs before the first stylesheet", reader.start() < first_style)

    # light blocks: in the css files, or in the html when styling is inline.
    # Pages that link /static/style.css (market, auth_manager) inherit the ground
    # and ink from it and define only their own extra tokens, so the palette
    # check runs against the UNION of everything the page actually loads.
    sources = [(str(p.name), read(p)) for p in css_paths] or [(html_path.name, html)]
    inherited = {}
    for href in re.findall(r'href="/static/([a-z_0-9]+\.css)', html):
        blk = LIGHT_ATTR.search(read(WEBUI / href))
        if blk:
            inherited.update(decls(blk.group(1)))
    for src_name, src in sources:
        a = LIGHT_ATTR.search(src)
        m = LIGHT_MEDIA.search(src)
        check(f"{name}/{src_name}: has a :root[data-theme=\"light\"] block", a is not None)
        check(f"{name}/{src_name}: has a guarded prefers-color-scheme: light block", m is not None)
        if a and m:
            da, dm = decls(a.group(1)), decls(m.group(1))
            diff = sorted(set(da.items()) ^ set(dm.items()))
            check(f"{name}/{src_name}: the two light blocks are token-identical", not diff, str(diff[:4]))
            # Token NAMES are each page's own (--bg-base, --bg-primary, --bg …);
            # what must match across pages are the VALUES, or two extensions
            # side by side in the dashboard render two different whites.
            values = set(da.values()) | set(inherited.values())
            check(f"{name}/{src_name}: the light ground is the dashboard's #f7f8fa",
                  any(v.startswith("#f7f8fa") for v in values), sorted(values)[:6])
            check(f"{name}/{src_name}: the light ink is the dashboard's #1e293b",
                  any(v.startswith("#1e293b") for v in values), sorted(values)[:6])
            # An accent may DARKEN for white ground (cyan #06b6d4 -> #0e7490) but
            # must not change identity — same hue as the page's own dark value.
            dark_first = re.search(r":root\s*\{([^}]*)\}", src, re.S)
            dark = decls(dark_first.group(1)) if dark_first else {}
            for key in ("--primary", "--accent"):
                if key not in da or key not in dark:
                    continue
                hl, hd = hue(da[key]), hue(dark[key])
                if hl is None or hd is None:
                    continue  # an alias like var(--primary), or a grey
                gap = abs(hl - hd)
                gap = min(gap, 360 - gap)
                # A neon that cannot be darkened legibly (mint #66fcf1, cyan
                # #22d3ee) may fall back to the dashboard primary instead —
                # that is the one sanctioned identity change.
                fallback = da[key].startswith("#5276eb")
                check(f"{name}/{src_name}: light {key} keeps the dark hue, or falls back to the dashboard primary",
                      gap <= 25 or fallback, f"{dark[key]} -> {da[key]} ({gap:.0f} deg apart)")

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
