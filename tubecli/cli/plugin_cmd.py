"""
CLI commands for managing plugins.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("plugin")
def plugin_group():
    """Manage TubeCLI plugins."""
    pass


@plugin_group.command("list")
def list_plugins():
    """List all available plugins."""
    from tubecli.core.plugin_manager import plugin_manager
    plugin_manager.discover_plugins()

    plugins = plugin_manager.get_all()
    if not plugins:
        console.print("[dim]No plugins found.[/dim]")
        return

    table = Table(title="🔌 Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Description")

    for p in plugins:
        status = "[green]● Enabled[/green]" if p.enabled else "[dim]○ Disabled[/dim]"
        table.add_row(p.name, p.version, status, p.description)

    console.print(table)


@plugin_group.command("enable")
@click.argument("name")
def enable_plugin(name):
    """Enable a plugin."""
    from tubecli.core.plugin_manager import plugin_manager
    plugin_manager.discover_plugins()

    if plugin_manager.enable(name):
        console.print(f"[green]✅ Plugin '{name}' enabled.[/green]")
    else:
        console.print(f"[red]❌ Plugin '{name}' not found.[/red]")


@plugin_group.command("disable")
@click.argument("name")
def disable_plugin(name):
    """Disable a plugin."""
    from tubecli.core.plugin_manager import plugin_manager
    plugin_manager.discover_plugins()

    if plugin_manager.disable(name):
        console.print(f"[yellow]⏸ Plugin '{name}' disabled.[/yellow]")
    else:
        console.print(f"[red]❌ Plugin '{name}' not found.[/red]")
