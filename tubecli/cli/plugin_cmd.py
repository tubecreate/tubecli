"""
CLI commands for managing plugins.
Supports: list, enable, disable, install (git), uninstall, info.
"""
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

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
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Description")
    table.add_column("Extras", style="dim")

    for p in plugins:
        status = "[green]● Enabled[/green]" if p.enabled else "[dim]○ Disabled[/dim]"
        ptype = "[blue]system[/blue]" if p.plugin_type == "system" else "[yellow]external[/yellow]"
        extras = []
        if p.get_skill_md():
            extras.append("📖MD")
        if p.get_nodes():
            extras.append("🧩Nodes")
        if p.get_ui_static_dir():
            extras.append("🖥️UI")
        table.add_row(p.name, p.version, ptype, status, p.description, " ".join(extras))

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


@plugin_group.command("install")
@click.argument("git_url")
def install_plugin(git_url):
    """Install a plugin from a git repository URL.

    The repository must contain a tubecli-plugin.json manifest.

    Example:
        tubecli plugin install https://github.com/user/my-plugin.git
    """
    from tubecli.core.plugin_manager import plugin_manager

    console.print(f"\n📦 Installing plugin from: [cyan]{git_url}[/cyan]")

    with console.status("Cloning repository..."):
        result = plugin_manager.install_from_git(git_url)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
        plugin_info = result.get("plugin", {})
        if plugin_info:
            console.print(f"   Name:    [bold]{plugin_info.get('name')}[/bold]")
            console.print(f"   Version: {plugin_info.get('version')}")
            console.print(f"   Author:  {plugin_info.get('author', '—')}")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")

    console.print()


@plugin_group.command("uninstall")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to uninstall this plugin?")
def uninstall_plugin(name):
    """Uninstall an external plugin."""
    from tubecli.core.plugin_manager import plugin_manager
    plugin_manager.discover_plugins()

    result = plugin_manager.uninstall(name)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@plugin_group.command("info")
@click.argument("name")
def plugin_info(name):
    """Show detailed information about a plugin."""
    from tubecli.core.plugin_manager import plugin_manager
    plugin_manager.discover_plugins()

    plugin = plugin_manager.get(name)
    if not plugin:
        console.print(f"[red]❌ Plugin '{name}' not found.[/red]")
        return

    info_lines = []
    info_lines.append(f"**Name:** {plugin.name}")
    info_lines.append(f"**Version:** {plugin.version}")
    info_lines.append(f"**Author:** {plugin.author or '—'}")
    info_lines.append(f"**Type:** {plugin.plugin_type}")
    info_lines.append(f"**Status:** {'Enabled' if plugin.enabled else 'Disabled'}")
    info_lines.append(f"**Description:** {plugin.description}")

    if plugin.plugin_dir:
        info_lines.append(f"**Directory:** {plugin.plugin_dir}")

    if plugin.get_nodes():
        nodes = list(plugin.get_nodes().keys())
        info_lines.append(f"**Nodes:** {', '.join(nodes)}")

    has_md = plugin.get_skill_md()
    info_lines.append(f"**SKILL.md:** {'✅ Available' if has_md else '—'}")

    has_ui = plugin.get_ui_static_dir()
    info_lines.append(f"**UI Static:** {'✅ ' + has_ui if has_ui else '—'}")

    if plugin.current_port:
        info_lines.append(f"**Port:** {plugin.current_port}")

    console.print()
    console.print(Panel("\n".join(info_lines), title=f"🔌 Plugin: {plugin.name}", border_style="cyan"))
    console.print()
