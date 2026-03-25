"""
tubecli api — Start/stop the REST API server.
"""
import click
from rich.console import Console

console = Console()


@click.group("api")
def api_cmd():
    """Manage the REST API server."""
    pass


@api_cmd.command("start")
@click.option("--port", "-p", default=None, type=int, help="Port number")
@click.option("--host", "-h", default="0.0.0.0", help="Host to bind")
@click.option("--lang", "-l", default=None, type=click.Choice(["vi", "en"]),
              help="UI language (vi=Vietnamese, en=English). Saves to settings.")
def start(port, host, lang):
    """Start the API server."""
    from tubecli.config import get_api_port
    import uvicorn

    actual_port = port or get_api_port()

    # Apply language if provided
    if lang:
        from tubecli.config import set_language
        from tubecli.i18n import load_language
        set_language(lang)
        load_language(lang)

    console.print(f"\n🌐 [bold cyan]Starting TubeCLI API Server[/bold cyan]")
    console.print(f"   URL: [green]http://{host}:{actual_port}[/green]")
    console.print(f"   Docs: [green]http://localhost:{actual_port}/api/v1/docs[/green]")
    if lang:
        console.print(f"   Lang: [green]{lang}[/green]")
    console.print(f"   Press Ctrl+C to stop.\n")

    uvicorn.run(
        "tubecli.api.server:app",
        host=host,
        port=actual_port,
        reload=False,
    )


@api_cmd.command("status")
def status():
    """Check if the API server is running."""
    import requests
    from tubecli.config import get_api_port

    port = get_api_port()
    try:
        resp = requests.get(f"http://localhost:{port}/api/v1/health", timeout=3)
        if resp.status_code == 200:
            console.print(f"\n✅ [green]API server is running[/green] on port {port}\n")
        else:
            console.print(f"\n⚠️  [yellow]API returned status {resp.status_code}[/yellow]\n")
    except requests.exceptions.ConnectionError:
        console.print(f"\n❌ [red]API server is not running[/red] (port {port})\n")
    except Exception as e:
        console.print(f"\n❌ [red]Error:[/red] {e}\n")
