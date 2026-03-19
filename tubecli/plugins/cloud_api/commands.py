"""
Cloud API Plugin — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("cloud-api")
def cloud_api_group():
    """Manage cloud AI providers and API keys."""
    pass


@cloud_api_group.command("providers")
def list_providers():
    """List all supported cloud AI providers."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    providers = key_manager.list_providers()

    table = Table(title="☁️ Cloud AI Providers")
    table.add_column("Provider", style="cyan bold")
    table.add_column("Name", style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Models")

    for p in providers:
        key_status = "[green]✅ Active[/green]" if p["has_key"] else "[red]❌ None[/red]"
        models = ", ".join(p["models"][:3])
        if len(p["models"]) > 3:
            models += f" +{len(p['models']) - 3}"
        table.add_row(p["id"], p["name"], key_status, models)

    console.print(table)


@cloud_api_group.command("keys")
@click.option("--provider", "-p", default=None, help="Filter by provider")
def list_keys(provider):
    """List stored API keys (masked)."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    keys = key_manager.list_keys(provider)

    if not keys:
        console.print("[dim]No keys stored. Use 'tubecli cloud-api add-key' to add one.[/dim]")
        return

    table = Table(title="🔑 API Keys")
    table.add_column("Provider", style="cyan")
    table.add_column("Label", style="bold")
    table.add_column("Key (masked)", style="dim")
    table.add_column("Active")
    table.add_column("Added", style="dim")

    for prov, labels in keys.items():
        for label, info in labels.items():
            active = "[green]●[/green]" if info["active"] else "[dim]○[/dim]"
            table.add_row(prov, label, info["masked_key"], active, info["added_at"][:10])

    console.print(table)


@cloud_api_group.command("add-key")
@click.argument("provider")
@click.argument("api_key")
@click.option("--label", "-l", default="default", help="Label for this key")
def add_key(provider, api_key, label):
    """Add an API key for a cloud provider.

    Example: tubecli cloud-api add-key gemini AIzaSy... --label main
    """
    from tubecli.plugins.cloud_api.plugin import key_manager
    result = key_manager.add_key(provider, api_key, label)
    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@cloud_api_group.command("remove-key")
@click.argument("provider")
@click.option("--label", "-l", default="default", help="Label of key to remove")
def remove_key(provider, label):
    """Remove a stored API key."""
    from tubecli.plugins.cloud_api.plugin import key_manager
    result = key_manager.remove_key(provider, label)
    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@cloud_api_group.command("test")
@click.argument("provider")
@click.option("--label", "-l", default="default", help="Label of key to test")
def test_key(provider, label):
    """Test if an API key is valid."""
    from tubecli.plugins.cloud_api.plugin import key_manager

    with console.status(f"Testing {provider} key..."):
        result = key_manager.test_key(provider, label)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    elif result["status"] == "info":
        console.print(f"[blue]ℹ️ {result['message']}[/blue]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")
