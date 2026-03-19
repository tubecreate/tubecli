"""
Browser Extension — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("browser")
def browser_group():
    """Manage browser profiles and automation."""
    pass


@browser_group.command("profiles")
def list_profiles():
    """List all browser profiles."""
    from tubecli.extensions.browser.profile_manager import list_profiles as _list
    profiles = _list()

    if not profiles:
        console.print("[dim]No profiles found. Use 'tubecli browser create <name>' to create one.[/dim]")
        return

    table = Table(title="🌐 Browser Profiles")
    table.add_column("Name", style="cyan bold")
    table.add_column("Proxy", style="dim")
    table.add_column("Tags")
    table.add_column("Created", style="dim")
    table.add_column("Cookies", style="green")

    for p in profiles:
        tags = ", ".join(p.get("tags", []))
        created = p.get("created_at", "")[:10]
        cookies = "✓" if p.get("has_cookies") else ""
        proxy = p.get("proxy", "") or "-"
        table.add_row(p["name"], proxy, tags, created, cookies)

    console.print(table)


@browser_group.command("create")
@click.argument("name")
@click.option("--proxy", default="", help="Proxy URL (socks5://...)")
@click.option("--tags", default="Windows,Chrome", help="Comma-separated tags")
def create_profile(name, proxy, tags):
    """Create a new browser profile."""
    from tubecli.extensions.browser.profile_manager import create_profile as _create
    try:
        tag_list = [t.strip() for t in tags.split(",")]
        profile = _create(name, proxy=proxy, tags=tag_list)
        console.print(f"[green]✅ Profile created: {profile['name']}[/green]")
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")


@browser_group.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="Are you sure?")
def delete_profile(name):
    """Delete a browser profile."""
    from tubecli.extensions.browser.profile_manager import delete_profile as _delete
    if _delete(name):
        console.print(f"[yellow]🗑 Profile '{name}' deleted.[/yellow]")
    else:
        console.print(f"[red]❌ Profile '{name}' not found.[/red]")


@browser_group.command("launch")
@click.argument("profile")
@click.option("--prompt", default="", help="AI prompt for automation")
@click.option("--url", default="", help="URL to navigate to")
@click.option("--headless", is_flag=True, help="Run headless")
def launch_browser(profile, prompt, url, headless):
    """Launch a browser with a profile."""
    from tubecli.extensions.browser.process_manager import browser_process_manager
    result = browser_process_manager.spawn(
        profile=profile, prompt=prompt, url=url, headless=headless
    )
    if result.get("status") == "error":
        console.print(f"[red]❌ {result.get('error', 'Launch failed')}[/red]")
    else:
        console.print(f"[green]🚀 Browser launched[/green]")
        console.print(f"   Instance: {result['instance_id']}")
        console.print(f"   Profile:  {result['profile']}")
        if result.get("pid"):
            console.print(f"   PID:      {result['pid']}")


@browser_group.command("stop")
@click.argument("profile")
def stop_browser(profile):
    """Stop a running browser by profile name."""
    from tubecli.extensions.browser.process_manager import browser_process_manager
    if browser_process_manager.stop_by_profile(profile):
        console.print(f"[yellow]⏹ Browser '{profile}' stopped.[/yellow]")
    else:
        console.print(f"[red]❌ No running browser for '{profile}'[/red]")


@browser_group.command("status")
def browser_status():
    """Show running browser instances."""
    from tubecli.extensions.browser.process_manager import browser_process_manager
    instances = browser_process_manager.list_running()

    if not instances:
        console.print("[dim]No running browsers.[/dim]")
        return

    table = Table(title="🌐 Running Browsers")
    table.add_column("Instance ID", style="cyan")
    table.add_column("Profile", style="bold")
    table.add_column("PID")
    table.add_column("Started", style="dim")
    table.add_column("Prompt", style="dim")

    for inst in instances:
        table.add_row(
            inst["instance_id"],
            inst["profile"],
            str(inst.get("pid", "")),
            inst.get("started_at", "")[:19],
            inst.get("prompt", "")[:40],
        )

    console.print(table)
