"""Workflow builder: the run must not lie, and extension nodes must exist.

Run:  python tests/workflow_fixes_test.py     (exit 0 = pass)

Three properties, each of which was false and each of which produced the same
user-visible symptom — "the AI made me a flow and it doesn't work":

1. Extension-contributed nodes reach the registry regardless of import order.
   Registration used to happen once at registry import, inside a bare
   `except Exception: pass`; if the extension manager had not discovered
   anything yet, the nodes were missing for the life of the process with no log
   line. Seven were lost, including video_processing — which build_system_prompt
   explicitly instructs the model to use ("For ANY video processing task, ALWAYS
   use the video_processing node", ai_workflow_builder.py:254). The model obeys,
   the type is absent, and generate_workflow rewrites it to an empty python_code
   box (:540). The complaint and the cause are one bug apart.

2. A malformed extension cannot take the palette down. One extension returns a
   dict instead of a class from get_nodes(); merging it unvalidated put a dict
   in the registry, and the next `cls not in seen` raised
   "TypeError: unhashable type: 'dict'" — no node list at all, for anyone.

3. A failed run reports failure. The engine hardcodes status="completed" for any
   run that was not cancelled and reports real failure separately in has_errors;
   the UI read only status, so every broken run showed a green tick. The most
   common failure of all — a node that was never configured — did not even set
   has_errors, because its output does not start with "Error:".
"""
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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
    print("=== 1. node cua extension vao duoc registry ===")
    from tubecli.nodes.registry import list_available_nodes, build_port_defs, NODE_REGISTRY
    nodes = list_available_nodes()
    types = {n["type"] for n in nodes}
    check("palette nhieu hon 19 node built-in", len(nodes) > 19, f"{len(nodes)} node")
    check("video_processing co mat", "video_processing" in types,
          "node ma prompt AI luon day dung")
    check("build_port_defs cung thay no", "video_processing" in build_port_defs())

    print("\n=== 2. moi gia tri trong registry deu la CLASS ===")
    bad = {k: type(v).__name__ for k, v in NODE_REGISTRY.items() if not isinstance(v, type)}
    check("khong co gia tri la dict/instance", not bad, str(bad))
    # list_available_nodes() puts classes in a set; a non-class would raise here.
    try:
        list_available_nodes()
        check("list_available_nodes khong no", True)
    except TypeError as e:
        check("list_available_nodes khong no", False, str(e))

    print("\n=== 3. dang ky lai la idempotent ===")
    from tubecli.nodes.registry import ensure_extension_nodes
    n = len(NODE_REGISTRY)
    ensure_extension_nodes(); ensure_extension_nodes()
    check("goi them 2 lan khong doi gi", len(NODE_REGISTRY) == n, f"{n} -> {len(NODE_REGISTRY)}")

    print("\n=== 4. luot chay hong phai bao hong ===")
    from tubecli.core.workflow_engine import WorkflowEngine
    from tubecli.nodes.registry import create_node_from_dict

    def mk(t, nid, label="", **cfg):
        return create_node_from_dict({"id": nid, "type": t, "label": label, "config": cfg})

    async def run(nodes, conns=None):
        return await WorkflowEngine(nodes, conns or []).run()

    # The commonest AI leftover: the right box, no code in it.
    r = asyncio.run(run([mk("text_input", "n1", "Nhap", text="hi"),
                         mk("python_code", "n2", "Gui email cho toi")],
                        [{"from_node_id": "n1", "from_port_id": "text",
                          "to_node_id": "n2", "to_port_id": "input"}]))
    check("hop python_code rong -> has_errors", r["has_errors"] is True)
    errs = [l for l in r["logs"] if l["status"] == "error"]
    check("  co dong log loi", bool(errs))
    check("  goi node theo NHAN nguoi dung dat",
          any(l["node_name"] == "Gui email cho toi" for l in errs),
          str([l["node_name"] for l in errs]))

    # Two boxes of the same type must be distinguishable.
    r2 = asyncio.run(run([mk("python_code", "n3", "Buoc A"), mk("python_code", "n4", "Buoc B")]))
    names = {l["node_name"] for l in r2["logs"] if l["status"] == "error"}
    check("hai node cung loai phan biet duoc", names == {"Buoc A", "Buoc B"}, str(names))

    # And a run that genuinely works must NOT be flagged.
    r3 = asyncio.run(run([mk("text_input", "n5", "", text="hello")]))
    check("flow chay that -> khong bao oan", r3["has_errors"] is False)
    check("  khong co nhan thi dung ten lop",
          any(l["node_name"].endswith("Text Input") for l in r3["logs"]),
          str([l["node_name"] for l in r3["logs"]]))

    print("\n=== 5. nhan dien node chua cau hinh ===")
    det = WorkflowEngine._detect_output_error
    for sentinel in ("No code provided", "No command provided", "⚠️ No results",
                     "Unknown action: create", "Error: boom"):
        check(f"bat '{sentinel[:26]}'", det({"result": sentinel}) is not None)
    check("bat dict long {'error':...}", det({"out": {"error": "hong"}}) is not None)
    check("KHONG bat ket qua binh thuong", det({"text": "xin chao"}) is None)
    check("KHONG bat chuoi chua tu 'error' o giua",
          det({"text": "khong co error nao ca"}) is None)

    print("\n=== 6. provider 'global' cua AI Generate ===")
    from tubecli.core.ai_workflow_builder import resolve_global_ai
    prov, model, key = resolve_global_ai()
    check("tra ve provider that", bool(prov) and prov != "global", f"{prov}")
    check("  co model", bool(model), model)
    check("  ollama thi khong can key", (prov != "ollama") or (key == ""))

    print("\n=== 7. giao dien: option 'global' duoc dung lai ===")
    from pathlib import Path
    js = Path(__file__).resolve().parent.parent / "tubecli" / "extensions" / "webui" / "static" / "workflow.js"
    src = js.read_text(encoding="utf-8", errors="replace")
    check("html dropdown co option global", "value=\"global\"" in src)
    check("co duong lui khi value khong khop", "selectedIndex = 0" in src)
    check("doc has_errors chu khong chi status", "result.has_errors" in src)
    check("kiem resp.ok truoc khi doc ket qua", "!resp.ok" in src)

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
