"""The dashboard's HTML must actually nest the way it is indented.

Run:  python tests/dashboard_markup_test.py     (exit 0 = pass)

Why this file exists. The agent detail modal grew a wrapper div for the history
pane, and the wrapper's closing tag was added without removing the pane's old
one. One surplus </div>. The file still LOOKED right — every element was
present, every id was spelled correctly, the indentation lined up — so nothing
that reads this file as text could have noticed.

What the browser did with it was not subtle. The extra close ended
.modal-content early, which left the footer as a direct child of .modal:

    .modal { display: flex; align-items: center; justify-content: center }

so the Cancel and Save Agent buttons became a second flex item and landed
OUTSIDE the dialog, floating in the backdrop next to it, vertically centred.
The only way to save an agent was gone.

Two guards, because the first one alone would not have caught it:

  1. Tags nest and close. Catches the surplus </div> at its source.
  2. Every .modal-actions is inside a .modal-content. This is the property that
     actually matters — the footer belongs to the dialog, not to the overlay —
     and it fails even if some future markup is balanced but misplaced.

Guard 2 is the one to keep honest: it is asserted against a parsed tree, not a
regex, so "the string modal-content appears nearby" cannot satisfy it.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "tubecli" / "extensions" / "webui" / "static"

# Not closed, and not expected to be. The SVG shapes matter: the dashboard draws
# sparklines inline, and treating <path> as a container corrupts the whole stack.
VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
    "path", "circle", "rect", "line", "polygon", "polyline", "ellipse", "use",
    "stop", "animate",
}

# Tags the HTML spec lets you leave open. A missing </li> is legal and the
# parser recovers; flagging it would bury the real defect in noise.
OPTIONAL_END = {"li", "dt", "dd", "p", "option", "thead", "tbody", "tfoot", "tr", "td", "th"}

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


class Tree(HTMLParser):
    """Builds a real element tree so ancestry can be asked, not guessed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "classes": set(), "line": 0, "kids": [], "parent": None}
        self.cur = self.root
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        d = dict(attrs)
        node = {
            "tag": tag,
            "classes": set((d.get("class") or "").split()),
            "id": d.get("id"),
            "line": self.getpos()[0],
            "kids": [],
            "parent": self.cur,
        }
        self.cur["kids"].append(node)
        self.cur = node

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing: opens and closes, nothing to track

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        node = self.cur
        while node is not self.root and node["tag"] != tag:
            if node["tag"] not in OPTIONAL_END:
                self.errors.append(
                    f"line {self.getpos()[0]}: </{tag}> arrives while "
                    f"<{node['tag']}> from line {node['line']} is still open"
                )
            node = node["parent"]
        if node is self.root:
            self.errors.append(f"line {self.getpos()[0]}: stray </{tag}> with nothing open")
            return
        self.cur = node["parent"]

    def close(self):
        super().close()
        node = self.cur
        while node is not self.root:
            if node["tag"] not in OPTIONAL_END:
                self.errors.append(f"line {node['line']}: <{node['tag']}> is never closed")
            node = node["parent"]

    def walk(self, node=None):
        node = self.root if node is None else node
        for kid in node["kids"]:
            yield kid
            yield from self.walk(kid)


def strip_noise(text):
    """Comments and script/style bodies are not markup and must not be parsed.

    HTMLParser handles them, but a </div> inside a JS template literal would be
    reported as a real tag, so they are removed with the line count preserved.
    """
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
    text = re.sub(r"(<script\b[^>]*>)(.*?)(</script>)",
                  lambda m: m.group(1) + blank(re.match(r".*", m.group(2), re.S)) + m.group(3),
                  text, flags=re.S | re.I)
    text = re.sub(r"(<style\b[^>]*>)(.*?)(</style>)",
                  lambda m: m.group(1) + blank(re.match(r".*", m.group(2), re.S)) + m.group(3),
                  text, flags=re.S | re.I)
    return text


def ancestors(node):
    n = node["parent"]
    while n is not None:
        yield n
        n = n["parent"]


print("=" * 70)
print("DASHBOARD MARKUP")
print("=" * 70)

pages = sorted(STATIC.glob("*.html"))
check("static pages found", len(pages) >= 5, f"only {len(pages)}")

trees = {}
for page in pages:
    tree = Tree()
    tree.feed(strip_noise(page.read_text(encoding="utf-8")))
    tree.close()
    trees[page.name] = tree

    # ---- 1. tags nest and close -------------------------------------------
    check(f"{page.name} nests", not tree.errors,
          "; ".join(tree.errors[:3]) + (f" (+{len(tree.errors) - 3} more)" if len(tree.errors) > 3 else ""))

# ---- 2. every modal footer lives inside its dialog -------------------------
# The property the surplus </div> broke. Asked of the parsed tree: walk up from
# each .modal-actions and require a .modal-content on the way. A footer that is
# a direct child of .modal becomes a flex sibling of the dialog and renders
# beside it, off the panel, which is what the user saw.
footers = 0
for name, tree in trees.items():
    for node in tree.walk():
        if "modal-actions" not in node["classes"]:
            continue
        footers += 1
        chain = list(ancestors(node))
        inside = any("modal-content" in a["classes"] for a in chain)
        where = " > ".join(
            a["tag"] + ("." + ".".join(sorted(a["classes"])) if a["classes"] else "")
            for a in reversed(chain[:2])
        )
        check(f"{name}:{node['line']} footer inside dialog", inside,
              f".modal-actions escaped .modal-content — parent chain: {where}")

check("footers were actually examined", footers >= 8, f"found {footers}")

# ---- 3. the agent modal specifically ---------------------------------------
# This is the dialog that broke, and the one with the most nesting (a tab strip
# plus ten panes), so it gets named assertions rather than relying on the sweep.
idx = trees.get("index.html")
check("index.html parsed", idx is not None, "missing")
if idx:
    modal = next((n for n in idx.walk() if n.get("id") == "modal-agent"), None)
    check("agent modal exists", modal is not None, "#modal-agent not found")
    if modal:
        content = [k for k in modal["kids"] if "modal-content" in k["classes"]]
        check("agent modal has one .modal-content", len(content) == 1, f"found {len(content)}")

        # The failure state exactly: a footer sitting next to the dialog.
        strays = [k["tag"] + "." + ".".join(sorted(k["classes"]))
                  for k in modal["kids"] if "modal-content" not in k["classes"]]
        check("nothing sits beside the dialog", not strays, f"stray children of #modal-agent: {strays}")

        if content:
            panes = [n for n in idx.walk() if "agent-tab-pane" in n["classes"]]
            check("tab panes found", len(panes) >= 9, f"only {len(panes)}")

            # Every pane must be a child of .agent-tabs-content. A pane that
            # drifts out of the scroll container still shows its fields, so this
            # is invisible until the tab strip stops switching it.
            for pane in panes:
                parent = pane["parent"]
                check(f"pane {pane.get('id')} in tab body",
                      parent is not None and "agent-tabs-content" in parent["classes"],
                      f"parent is {parent['tag']}.{'.'.join(sorted(parent['classes']))}"
                      if parent else "no parent")

            # And panes are siblings, never nested — a nested pane is hidden by
            # its parent's display:none no matter which tab is active.
            for pane in panes:
                nested = [k.get("id") for k in idx.walk(pane) if "agent-tab-pane" in k["classes"]]
                check(f"pane {pane.get('id')} not nesting another", not nested, f"contains {nested}")

# ── 4. translation keys resolve ─────────────────────────────────────────────
# T(key) returns the KEY ITSELF when it is missing, so a forgotten entry does
# not fall back to English — it renders the literal string
# "agent_modal.agent_id_label" on the page. Every key this file introduces is
# therefore checked in all nine locales.
#
# The wider backlog is reported, not asserted: 250 keys used across the
# dashboard have no entry anywhere, which predates this test. Failing on them
# would mean this guard could never go green, and a red suite that is expected
# to be red stops being read.
LOCALES = ROOT / "tubecli" / "extensions" / "webui" / "locales"
REQUIRED = ["agent_modal.agent_id_label", "agent_modal.copy_id",
            "common.copied", "common.copy_failed", "common.loading",
            "agent_modal.ai_guide_btn", "agent_modal.ai_guide_copy",
            "agent_modal.ai_guide_hint", "agent_modal.ai_guide_save_first",
            "agent_modal.ai_guide_failed", "agent_modal.ai_guide_rotate",
            "agent_modal.ai_guide_rotate_confirm", "gen.system_prompt",
            "gen.system_prompt_placeholder", "gen.system_prompt_hint"]

import json  # noqa: E402

locale_files = sorted(LOCALES.glob("*.json"))
check("locale files found", len(locale_files) >= 9, f"only {len(locale_files)}")
for lf in locale_files:
    try:
        data = json.loads(lf.read_text(encoding="utf-8"))
    except ValueError as e:
        check(f"{lf.name} is valid JSON", False, str(e))
        continue
    check(f"{lf.name} is valid JSON", True)
    missing = [k for k in REQUIRED if k not in data]
    check(f"{lf.name} has the agent-id keys", not missing, f"missing {missing}")
    blank = [k for k in REQUIRED if k in data and not str(data[k]).strip()]
    check(f"{lf.name} keys are not blank", not blank, f"blank {blank}")

used = set()
for page in pages:
    used |= set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"',
                           page.read_text(encoding="utf-8")))

# Against EVERY locale file, not just the dashboard's own. /api/v1/i18n/{lang}
# merges all sixteen extension dictionaries before the page sees them, so a key
# defined by the browser or market extension is present at runtime even though
# webui/locales/en.json has never heard of it. Measuring one file reported 250
# missing keys when the real number is a tenth of that — a scary number that
# sent me looking at a problem that mostly did not exist.
merged = {}
for lf in sorted((ROOT / "tubecli" / "extensions").glob("*/locales/en.json")):
    try:
        merged.update(json.loads(lf.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        continue
check("merged locale dictionary is populated", len(merged) > 1000, f"only {len(merged)} keys")
gap = sorted(used - set(merged))
if gap:
    print(f"  (note: {len(gap)} of {len(used)} i18n keys resolve in no locale file "
          f"and render as raw key text — e.g. {', '.join(gap[:3])})")

print(f"\n{checks - len(failures)}/{checks} PASS")
for f in failures:
    print("  FAIL " + f)
sys.exit(1 if failures else 0)
