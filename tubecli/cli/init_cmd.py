"""
tubecli init — Initialize workspace, create data dirs, install default skills.
"""
import click
from rich.console import Console

console = Console()


@click.command("init")
def init_cmd():
    """Initialize TubeCLI workspace and install default skills."""
    from tubecli.config import ensure_data_dirs, DATA_DIR

    console.print("\n🚀 [bold cyan]Initializing TubeCLI workspace...[/bold cyan]\n")

    # 1. Create data directories
    ensure_data_dirs()
    console.print(f"  📁 Data directory: [green]{DATA_DIR}[/green]")

    # 2. Register default skills
    console.print("  📦 Installing default skills...")
    from tubecli.skills.default_skills import register_default_skills
    register_default_skills()

    # 3. Create default agent if none exist
    from tubecli.core.agent import agent_manager
    if not agent_manager.get_all():
        agent_manager.create(
            name="Personal Assistant",
            description="General purpose AI assistant",
            system_prompt="You are a helpful AI assistant. Respond concisely.",
        )
        console.print("  🤖 Created default agent: [green]Personal Assistant[/green]")

    console.print("\n✅ [bold green]TubeCLI workspace ready![/bold green]")
    console.print("   Try: [cyan]tubecli agent list[/cyan]")
    console.print("   Try: [cyan]tubecli skill list[/cyan]\n")
