"""
tubecli agent — Create, list, show, and delete AI agents.
"""
import click
import json
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("agent")
def agent_cmd():
    """Manage AI agents."""
    pass


@agent_cmd.command("create")
@click.argument("name")
@click.option("--description", "-d", default="", help="Agent description")
@click.option("--system-prompt", "-s", default="You are a helpful AI assistant.", help="System prompt")
@click.option("--model", "-m", default=None, help="AI model (e.g. qwen:latest)")
def create(name, description, system_prompt, model):
    """Create a new agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.i18n import t

    agent = agent_manager.create(
        name=name,
        description=description,
        system_prompt=system_prompt,
        model=model,
    )
    console.print(t("agent.created", name=agent.name))
    console.print(t("agent.id_label", id=agent.id))


@agent_cmd.command("list")
def list_agents():
    """List all agents."""
    from tubecli.core.agent import agent_manager
    from tubecli.i18n import t

    agents = agent_manager.get_all()
    if not agents:
        console.print(t("agent.no_agents"))
        return

    table = Table(title=t("agent.table_title"), show_lines=True)
    table.add_column(t("agent.col_id"), style="dim", max_width=12)
    table.add_column(t("agent.col_name"), style="bold cyan")
    table.add_column(t("agent.col_description"))
    table.add_column(t("agent.col_model"), style="green")
    table.add_column(t("agent.col_skills"), justify="right")

    for a in agents:
        table.add_row(
            a.id[:12] + "...",
            a.name,
            a.description or "—",
            a.model or "default",
            str(len(a.allowed_skills)),
        )

    console.print()
    console.print(table)
    console.print()


@agent_cmd.command("show")
@click.argument("agent_id")
def show(agent_id):
    """Show agent details."""
    from tubecli.core.agent import agent_manager
    from tubecli.i18n import t

    agent = agent_manager.get(agent_id) or agent_manager.find_by_name(agent_id)
    if not agent:
        console.print(t("agent.not_found", id=agent_id))
        return

    console.print(f"\n🤖 [bold cyan]{agent.name}[/bold cyan]")
    console.print(json.dumps(agent.to_dict(), indent=2, ensure_ascii=False))
    console.print()


@agent_cmd.command("delete")
@click.argument("agent_id")
@click.confirmation_option(prompt="Are you sure you want to delete this agent?")
def delete(agent_id):
    """Delete an agent."""
    from tubecli.core.agent import agent_manager
    from tubecli.i18n import t

    agent = agent_manager.get(agent_id) or agent_manager.find_by_name(agent_id)
    if not agent:
        console.print(t("agent.not_found", id=agent_id))
        return

    name = agent.name
    agent_manager.delete(agent.id)
    console.print(t("agent.deleted", name=name))
