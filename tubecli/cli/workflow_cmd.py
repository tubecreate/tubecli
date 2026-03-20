"""
tubecli workflow — Run workflow JSON files.
"""
import click
import json
import asyncio
from pathlib import Path
from rich.console import Console

console = Console()


@click.group("workflow")
def workflow_cmd():
    """Run and manage workflows."""
    pass


@workflow_cmd.command("run")
@click.argument("file", type=click.Path(exists=True))
@click.option("--input", "-i", "input_text", default="", help="Input text injection")
def run_workflow(file, input_text):
    """Run a workflow from a JSON file."""
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine
    from tubecli.i18n import t

    # Load workflow JSON
    try:
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        console.print(t("workflow.load_error", error=e))
        return

    nodes_data = data.get("nodes", [])
    connections = data.get("connections", [])
    wf_name = data.get("name", Path(file).stem)

    if not nodes_data:
        console.print(t("workflow.no_nodes"))
        return

    # Inject input
    if input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = input_text

    console.print(t("workflow.running", name=wf_name))
    console.print(t("workflow.node_info", nodes=len(nodes_data), connections=len(connections)))

    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        console.print(t("workflow.node_error", error=e))
        return

    def on_progress(step, total, msg):
        console.print(f"  [{step}/{total}] {msg}")

    engine = WorkflowEngine(nodes=nodes, connections=connections, on_progress=on_progress)
    result = asyncio.run(engine.run())

    status = result.get("status", "unknown")
    if status == "completed":
        console.print(t("workflow.completed"))
    else:
        console.print(t("workflow.status", status=status))


@workflow_cmd.command("list")
def list_workflows():
    """List saved workflows."""
    from tubecli.config import WORKFLOWS_DIR
    from tubecli.i18n import t

    if not WORKFLOWS_DIR.exists():
        console.print(t("workflow.no_dir"))
        return

    files = list(WORKFLOWS_DIR.glob("*.json"))
    if not files:
        console.print(t("workflow.no_files"))
        return

    console.print(t("workflow.saved_title"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("name", f.stem)
            nodes = len(data.get("nodes", []))
            console.print(f"  📄 {f.name} — [cyan]{name}[/cyan] ({nodes} nodes)")
        except Exception:
            console.print(f"  📄 {f.name} — [dim]invalid JSON[/dim]")
    console.print()
