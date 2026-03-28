"""
Auth Manager Extension — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("auth")
def auth_group():
    """Manage OAuth credentials & tokens for Google, Facebook, TikTok."""
    pass


@auth_group.command("providers")
def list_providers():
    """List all supported OAuth providers."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    providers = auth_manager.list_providers()

    table = Table(title="🔐 OAuth Providers")
    table.add_column("ID", style="cyan bold")
    table.add_column("Name")
    table.add_column("Icon")
    table.add_column("Credentials", justify="center")
    table.add_column("Tokens", justify="center")
    table.add_column("Scopes")

    for p in providers:
        cred_str = f"[green]{p['credential_count']}[/green]" if p["credential_count"] > 0 else "[dim]0[/dim]"
        token_str = f"[green]{p['token_count']}[/green]" if p["token_count"] > 0 else "[dim]0[/dim]"
        scopes = ", ".join(list(p["scopes"].keys())[:4])
        if len(p["scopes"]) > 4:
            scopes += f" +{len(p['scopes']) - 4}"
        table.add_row(p["id"], p["name"], p["icon"], cred_str, token_str, scopes)

    console.print(table)


@auth_group.command("list")
@click.option("--provider", "-p", default=None, help="Filter by provider")
def list_credentials(provider):
    """List stored OAuth credentials."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    creds = auth_manager.list_credentials(provider)

    if not creds:
        console.print("[dim]No credentials stored. Use 'tubecli auth add' to add one.[/dim]")
        return

    table = Table(title="🔑 OAuth Credentials")
    table.add_column("ID", style="cyan")
    table.add_column("Provider", style="bold")
    table.add_column("Name")
    table.add_column("Client ID", style="dim")
    table.add_column("Token", justify="center")

    for c in creds:
        token_status = {
            "active": "[green]✅ Active[/green]",
            "expired": "[yellow]⏰ Expired[/yellow]",
            "none": "[dim]—[/dim]",
            "revoked": "[red]❌ Revoked[/red]",
        }.get(c["token_status"], "[dim]—[/dim]")
        table.add_row(c["id"], c["provider"], c["name"], c["client_id"], token_status)

    console.print(table)


@auth_group.command("add")
@click.argument("provider")
@click.option("--name", "-n", prompt="Credential name", help="Friendly name")
@click.option("--client-id", prompt="Client ID", help="OAuth Client ID")
@click.option("--client-secret", prompt="Client Secret", hide_input=True, help="OAuth Client Secret")
def add_credential(provider, name, client_id, client_secret):
    """Add an OAuth credential for a provider.

    Example: tubecli auth add google --name "My YouTube App"
    """
    from tubecli.extensions.auth_manager.extension import auth_manager
    result = auth_manager.add_credential(provider, name, client_id, client_secret)
    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
        console.print(f"[dim]Credential ID: {result['credential_id']}[/dim]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@auth_group.command("authorize")
@click.argument("cred_id")
@click.option("--scope", "-s", multiple=True, required=True, help="Scopes to request")
@click.option("--profile", "-p", default="", help="Browser profile to use for OAuth")
def authorize(cred_id, scope, profile):
    """Start OAuth authorization flow.

    Example: tubecli auth authorize cred_abc123 -s youtube -p agent_001
    """
    from tubecli.extensions.auth_manager.extension import auth_manager
    result = auth_manager.build_oauth_url(cred_id, list(scope), profile)

    if result["status"] == "error":
        console.print(f"[red]❌ {result['message']}[/red]")
        return

    console.print(f"[cyan]🔗 Authorization URL:[/cyan]")
    console.print(f"[dim]{result['auth_url']}[/dim]")

    if profile:
        try:
            from tubecli.extensions.browser.process_manager import browser_process_manager
            console.print(f"\n[cyan]🌐 Launching browser profile '{profile}'...[/cyan]")
            browser_process_manager.spawn(profile=profile, url=result["auth_url"], manual=True)
        except Exception as e:
            console.print(f"[yellow]⚠️ Could not launch profile: {e}[/yellow]")
            import webbrowser
            webbrowser.open(result["auth_url"])
    else:
        import webbrowser
        webbrowser.open(result["auth_url"])

    console.print("\n[green]Waiting for callback... Complete authorization in the browser.[/green]")


@auth_group.command("tokens")
@click.option("--provider", "-p", default=None, help="Filter by provider")
def list_tokens(provider):
    """List authorized tokens."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    tokens = auth_manager.list_tokens(provider)

    if not tokens:
        console.print("[dim]No authorized tokens.[/dim]")
        return

    table = Table(title="🎫 Authorized Tokens")
    table.add_column("Credential", style="cyan")
    table.add_column("Provider")
    table.add_column("Email")
    table.add_column("Profile")
    table.add_column("Scopes")
    table.add_column("Status")

    for t in tokens:
        status = {
            "active": "[green]✅ Active[/green]",
            "expired": "[yellow]⏰ Expired[/yellow]",
            "revoked": "[red]❌ Revoked[/red]",
        }.get(t["status"], "[dim]?[/dim]")
        scopes = ", ".join(t.get("scopes", []))
        table.add_row(
            t["credential_id"], t["provider"],
            t.get("authorized_email", ""), t.get("browser_profile", ""),
            scopes, status,
        )

    console.print(table)


@auth_group.command("revoke")
@click.argument("cred_id")
@click.confirmation_option(prompt="Are you sure you want to revoke this token?")
def revoke(cred_id):
    """Revoke an authorized token."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    result = auth_manager.revoke_token(cred_id)
    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@auth_group.command("refresh")
@click.argument("cred_id")
def refresh(cred_id):
    """Refresh an expired token."""
    from tubecli.extensions.auth_manager.extension import auth_manager
    with console.status("Refreshing token..."):
        result = auth_manager.refresh_token(cred_id)
    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")
