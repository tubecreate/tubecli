"""
tubecli skill — List, run, and manage skills.
"""
import click
import json
import asyncio
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("skill")
def skill_cmd():
    """Manage and run skills."""
    pass


@skill_cmd.command("list")
def list_skills():
    """List all available skills."""
    from tubecli.core.skill import skill_manager
    from tubecli.i18n import t

    skills = skill_manager.get_all()
    if not skills:
        console.print(t("skill.no_skills"))
        return

    table = Table(title=t("skill.table_title"), show_lines=True)
    table.add_column(t("skill.col_id"), style="dim", max_width=12)
    table.add_column(t("skill.col_name"), style="bold cyan")
    table.add_column(t("skill.col_type"), style="green")
    table.add_column(t("skill.col_description"))
    table.add_column(t("skill.col_nodes"), justify="right")

    for s in skills:
        nodes_count = len(s.workflow_data.get("nodes", []))
        table.add_row(
            s.id[:12] + "...",
            s.name,
            s.skill_type,
            (s.description or "—")[:60],
            str(nodes_count),
        )

    console.print()
    console.print(table)
    console.print()


@skill_cmd.command("run")
@click.argument("name")
@click.option("--input", "-i", "input_text", default="", help="Input text for the skill")
def run_skill(name, input_text):
    """Run a skill by name."""
    from tubecli.core.skill import skill_manager
    from tubecli.nodes.registry import create_node_from_dict
    from tubecli.core.workflow_engine import WorkflowEngine
    from tubecli.i18n import t

    skill = skill_manager.find_by_name(name)
    if not skill:
        console.print(t("skill.not_found", name=name))
        console.print(t("skill.use_list"))
        return

    console.print(t("skill.running", name=skill.name))

    workflow_data = skill.workflow_data
    nodes_data = workflow_data.get("nodes", [])
    connections = workflow_data.get("connections", [])

    # Inject input text into text_input nodes
    if input_text:
        for nd in nodes_data:
            if nd.get("type") in ("text_input", "manual_input"):
                nd.setdefault("config", {})["text"] = input_text

    # Create node instances
    try:
        nodes = [create_node_from_dict(nd) for nd in nodes_data]
    except Exception as e:
        console.print(t("skill.node_error", error=e))
        return

    def on_progress(step, total, msg):
        console.print(f"  [{step}/{total}] {msg}")

    engine = WorkflowEngine(nodes=nodes, connections=connections, on_progress=on_progress)

    # Run workflow
    result = asyncio.run(engine.run())

    status = result.get("status", "unknown")
    if status == "completed":
        console.print(t("skill.completed"))
    else:
        console.print(t("skill.finished_status", status=status))


@skill_cmd.command("show")
@click.argument("name")
def show_skill(name):
    """Show skill details and workflow definition."""
    from tubecli.core.skill import skill_manager
    from tubecli.i18n import t

    skill = skill_manager.find_by_name(name) or skill_manager.get(name)
    if not skill:
        console.print(t("skill.not_found", name=name))
        return

    console.print(f"\n⚡ [bold cyan]{skill.name}[/bold cyan]")
    console.print(json.dumps(skill.to_dict(), indent=2, ensure_ascii=False))
    console.print()
