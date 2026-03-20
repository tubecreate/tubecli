"""
CLI commands for managing extensions.
Supports: list, enable, disable, install (git), uninstall, info.
"""
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


@click.group("extension")
def extension_group():
    """Manage TubeCLI extensions."""
    pass


@extension_group.command("list")
def list_extensions():
    """List all available extensions."""
    from tubecli.core.extension_manager import extension_manager
    from tubecli.i18n import t
    extension_manager.discover_extensions()

    extensions = extension_manager.get_all()
    if not extensions:
        console.print(t("ext.no_extensions"))
        return

    table = Table(title=t("ext.table_title"))
    table.add_column(t("ext.col_name"), style="cyan")
    table.add_column(t("ext.col_version"), style="dim")
    table.add_column(t("ext.col_type"), style="magenta")
    table.add_column(t("ext.col_status"), style="bold")
    table.add_column(t("ext.col_description"))
    table.add_column(t("ext.col_extras"), style="dim")

    for p in extensions:
        status = t("ext.enabled") if p.enabled else t("ext.disabled")
        ptype = t("ext.type_system") if p.extension_type == "system" else t("ext.type_external")
        extras = []
        if p.get_skill_md():
            extras.append("📖MD")
        if p.get_nodes():
            extras.append("🧩Nodes")
        if p.get_ui_static_dir():
            extras.append("🖥️UI")
        table.add_row(p.name, p.version, ptype, status, p.description, " ".join(extras))

    console.print(table)


@extension_group.command("enable")
@click.argument("name")
def enable_extension(name):
    """Enable a extension."""
    from tubecli.core.extension_manager import extension_manager
    from tubecli.i18n import t
    extension_manager.discover_extensions()

    if extension_manager.enable(name):
        console.print(t("ext.enable_ok", name=name))
    else:
        console.print(t("ext.enable_fail", name=name))


@extension_group.command("disable")
@click.argument("name")
def disable_extension(name):
    """Disable a extension."""
    from tubecli.core.extension_manager import extension_manager
    from tubecli.i18n import t
    extension_manager.discover_extensions()

    if extension_manager.disable(name):
        console.print(t("ext.disable_ok", name=name))
    else:
        console.print(t("ext.disable_fail", name=name))


@extension_group.command("install")
@click.argument("git_url")
def install_extension(git_url):
    """Install a extension from a git repository URL.

    The repository must contain a tubecli-extension.json manifest.

    Example:
        tubecli extension install https://github.com/user/my-extension.git
    """
    from tubecli.core.extension_manager import extension_manager
    from tubecli.i18n import t

    console.print(t("ext.installing", url=git_url))

    with console.status(t("ext.cloning")):
        result = extension_manager.install_from_git(git_url)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
        extension_info = result.get("extension", {})
        if extension_info:
            console.print(f"   Name:    [bold]{extension_info.get('name')}[/bold]")
            console.print(f"   Version: {extension_info.get('version')}")
            console.print(f"   Author:  {extension_info.get('author', '—')}")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")

    console.print()


@extension_group.command("uninstall")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure you want to uninstall this extension?")
def uninstall_extension(name):
    """Uninstall an external extension."""
    from tubecli.core.extension_manager import extension_manager
    extension_manager.discover_extensions()

    result = extension_manager.uninstall(name)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@extension_group.command("info")
@click.argument("name")
def extension_info(name):
    """Show detailed information about a extension."""
    from tubecli.core.extension_manager import extension_manager
    from tubecli.i18n import t
    extension_manager.discover_extensions()

    extension = extension_manager.get(name)
    if not extension:
        console.print(t("ext.not_found", name=name))
        return

    info_lines = []
    info_lines.append(f"**Name:** {extension.name}")
    info_lines.append(f"**Version:** {extension.version}")
    info_lines.append(f"**Author:** {extension.author or '—'}")
    info_lines.append(f"**Type:** {extension.extension_type}")
    info_lines.append(f"**Status:** {'Enabled' if extension.enabled else 'Disabled'}")
    info_lines.append(f"**Description:** {extension.description}")

    if extension.extension_dir:
        info_lines.append(f"**Directory:** {extension.extension_dir}")

    if extension.get_nodes():
        nodes = list(extension.get_nodes().keys())
        info_lines.append(f"**Nodes:** {', '.join(nodes)}")

    has_md = extension.get_skill_md()
    info_lines.append(f"**SKILL.md:** {'✅ Available' if has_md else '—'}")

    has_ui = extension.get_ui_static_dir()
    info_lines.append(f"**UI Static:** {'✅ ' + has_ui if has_ui else '—'}")

    if extension.current_port:
        info_lines.append(f"**Port:** {extension.current_port}")

    console.print()
    console.print(Panel("\n".join(info_lines), title=f"🔌 Extension: {extension.name}", border_style="cyan"))
    console.print()
