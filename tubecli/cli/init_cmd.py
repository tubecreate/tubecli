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

    # 4. Enable default extensions
    console.print("  🧩 Enabling core extensions...")
    from tubecli.core.extension_manager import extension_manager
    extension_manager.discover_extensions()
    for ext in extension_manager.get_all():
        if ext.extension_type == "system":
            extension_manager.enable(ext.name)
    console.print("  ✅ Core extensions enabled.")

    console.print("\n✅ [bold green]TubeCLI workspace successfully initialized![/bold green]\n")
    console.print(" [bold yellow]Next Steps — How to use TubeCLI:[/bold yellow]")
    console.print("  1. Start the API Server and Web UI:")
    console.print("     [cyan]tubecli api start[/cyan]")
    console.print("  2. Open the Dashboard in your browser:")
    console.print("     [cyan]http://localhost:5295/dashboard[/cyan]")
    console.print("  3. Check the API documentation:")
    console.print("     [cyan]http://localhost:5295/api/v1/docs[/cyan]\n")
