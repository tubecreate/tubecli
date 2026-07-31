"""
tubecli api — Start/stop the REST API server.
"""
import os
import click
from rich.console import Console
from tubecli.config import SUPPORTED_LANGUAGES

console = Console()


@click.group("api")
def api_cmd():
    """Manage the REST API server."""
    pass


@api_cmd.command("start")
@click.option("--port", "-p", default=None, type=int, help="Port number")
@click.option("--host", "-h", default=None,
              help="Host to bind. Defaults to 127.0.0.1, or 0.0.0.0 inside a container.")
@click.option("--lang", "-l", default=None, type=click.Choice(SUPPORTED_LANGUAGES),
              help="UI language. Saves to settings.")
@click.option("--quiet", "-q", is_flag=True, default=False,
              help="Suppress HTTP access logs (runs silently in background)")
def start(port, host, lang, quiet):
    """Start the API server."""
    from tubecli.config import get_api_port
    import uvicorn

    actual_port = port or get_api_port()

    # Reaches the extension loader, which prints a line per registered router.
    # Set before the app is imported so those prints never happen — otherwise
    # `api start --quiet &` still filled the terminal with routine startup output
    # and looked like it had hung instead of started.
    if quiet:
        os.environ["TUBECLI_QUIET"] = "1"

    # 127.0.0.1 keeps the API off the LAN, which is what you want on a desktop.
    # Inside a container it instead makes the dashboard unreachable from anywhere:
    # the socket listens on the container's own loopback while Docker forwards
    # published ports to the container's eth0, so even `-p 5295:5295` is refused.
    # There the container is the isolation boundary and the user has already chosen
    # which ports to publish. The origin guard still refuses cross-site browser
    # requests in both cases.
    if host is None:
        from tubecli.cli.init_cmd import _in_container
        host = "0.0.0.0" if _in_container() else "127.0.0.1"

    # Apply language if provided
    if lang:
        from tubecli.config import set_language
        from tubecli.i18n import load_language
        set_language(lang)
        load_language(lang)

    if not quiet:
        console.print(f"\n[bold cyan]Starting TubeCLI API Server[/bold cyan]")
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
        log_level="error" if quiet else "info",
        access_log=not quiet,
    )


@api_cmd.command("stop")
@click.option("--port", "-p", default=None, type=int, help="Port number")
def stop(port):
    """Stop the API server.

    This command is documented in every README but never existed, so `tubecli api
    stop` answered "Error: No such command 'stop'" for anyone who followed the docs.
    """
    from tubecli.config import get_api_port
    from tubecli.cli.init_cmd import _kill_server_on_port

    actual_port = port or get_api_port()

    # Say nothing was running rather than claiming a stop that did not happen.
    import requests
    try:
        requests.get(f"http://127.0.0.1:{actual_port}/api/v1/health", timeout=3)
        was_running = True
    except Exception:
        was_running = False

    if not was_running:
        console.print(f"\n[yellow]No API server is running on port {actual_port}.[/yellow]\n")
        return

    killed = _kill_server_on_port(actual_port)
    if killed:
        console.print(f"\n[bold green][OK][/bold green] [green]API server stopped[/green] (port {actual_port})\n")
    else:
        console.print(
            f"\n[bold yellow][!][/bold yellow] [yellow]Something is still listening on port "
            f"{actual_port} and could not be stopped.[/yellow]\n"
        )


@api_cmd.command("status")
def status():
    """Check if the API server is running."""
    import requests
    from tubecli.config import get_api_port

    port = get_api_port()
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=3)
        if resp.status_code == 200:
            console.print(f"\n[bold green][OK][/bold green] [green]API server is running[/green] on port {port}\n")
        else:
            console.print(f"\n[bold yellow][!][/bold yellow] [yellow]API returned status {resp.status_code}[/yellow]\n")
    except requests.exceptions.ConnectionError:
        console.print(f"\n[bold red][x][/bold red] [red]API server is not running[/red] (port {port})\n")
    except Exception as e:
        console.print(f"\n[bold red][x][/bold red] [red]Error:[/red] {e}\n")
