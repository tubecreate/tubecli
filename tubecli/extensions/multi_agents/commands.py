"""
Multi-Agents Extension — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("multi-agent")
def multi_agents_group():
    """Manage multi-agent teams and delegation."""
    pass


@multi_agents_group.command("teams")
def list_teams():
    """List all agent teams."""
    from tubecli.extensions.multi_agents.extension import orchestrator

    teams = orchestrator.get_all_teams()
    if not teams:
        console.print("[dim]No teams found. Use 'tubecli multi-agent create-team' to create one.[/dim]")
        return

    table = Table(title="👥 Agent Teams")
    table.add_column("ID", style="dim", max_width=15)
    table.add_column("Name", style="cyan bold")
    table.add_column("Strategy", style="green")
    table.add_column("Agents", justify="right")
    table.add_column("Lead", style="yellow")
    table.add_column("Description")

    for t in teams:
        table.add_row(
            t.id, t.name, t.strategy, str(len(t.agent_ids)),
            t.lead_agent_id[:12] + "..." if t.lead_agent_id else "—",
            (t.description or "—")[:40],
        )

    console.print(table)


@multi_agents_group.command("create-team")
@click.argument("name")
@click.option("--agents", "-a", required=True, help="Comma-separated agent IDs")
@click.option("--lead", "-l", default="", help="Lead agent ID (default: first agent)")
@click.option("--strategy", "-s", default="sequential", type=click.Choice(["sequential", "parallel", "lead-delegate"]))
@click.option("--description", "-d", default="", help="Team description")
def create_team(name, agents, lead, strategy, description):
    """Create a new agent team.

    Example: tubecli multi-agent create-team "Research Team" -a id1,id2,id3 -s parallel
    """
    from tubecli.extensions.multi_agents.extension import orchestrator

    agent_ids = [a.strip() for a in agents.split(",") if a.strip()]
    if not agent_ids:
        console.print("[red]❌ At least one agent ID is required.[/red]")
        return

    team = orchestrator.create_team(
        name=name, agent_ids=agent_ids, lead_agent_id=lead,
        strategy=strategy, description=description,
    )
    console.print(f"[green]✅ Team '{team.name}' created with {len(agent_ids)} agents.[/green]")
    console.print(f"   ID: [dim]{team.id}[/dim]")
    console.print(f"   Strategy: {team.strategy}")


@multi_agents_group.command("delete-team")
@click.argument("team_id")
@click.confirmation_option(prompt="Are you sure?")
def delete_team(team_id):
    """Delete an agent team."""
    from tubecli.extensions.multi_agents.extension import orchestrator

    if orchestrator.delete_team(team_id):
        console.print(f"[green]✅ Team deleted.[/green]")
    else:
        console.print(f"[red]❌ Team '{team_id}' not found.[/red]")


@multi_agents_group.command("delegate")
@click.argument("team_id")
@click.argument("task")
def delegate_task(team_id, task):
    """Delegate a task to an agent team.

    Example: tubecli multi-agent delegate team_abc123 "Summarize the latest news"
    """
    import asyncio
    from tubecli.extensions.multi_agents.extension import orchestrator

    console.print(f"\n🚀 Delegating task to team [cyan]{team_id}[/cyan]...")
    console.print(f"   Task: {task[:100]}")

    result = asyncio.run(orchestrator.delegate(team_id, task))

    if result.get("status") == "error":
        console.print(f"[red]❌ {result['message']}[/red]")
        return

    console.print(f"\n✅ [green]Delegation complete[/green] — Strategy: {result.get('strategy')}")
    for r in result.get("results", []):
        console.print(f"\n  🤖 [bold]{r.get('agent_name', r.get('agent_id', '?'))}[/bold]")
        reply = r.get("reply", "")
        console.print(f"     {reply[:300]}")
        if r.get("action"):
            console.print(f"     [dim]Action: {r['action']}[/dim]")

    console.print()


@multi_agents_group.command("log")
def show_log():
    """Show recent delegation task log."""
    from tubecli.extensions.multi_agents.extension import orchestrator

    log = orchestrator.get_task_log()
    if not log:
        console.print("[dim]No delegation history.[/dim]")
        return

    table = Table(title="📋 Delegation Log")
    table.add_column("Time", style="dim")
    table.add_column("Team", style="cyan")
    table.add_column("Strategy", style="green")
    table.add_column("Agents")
    table.add_column("Task")

    for entry in log[-20:]:
        table.add_row(
            entry.get("timestamp", "")[:19],
            entry.get("team_name", ""),
            entry.get("strategy", ""),
            str(entry.get("agent_count", 0)),
            entry.get("task", "")[:50],
        )

    console.print(table)
