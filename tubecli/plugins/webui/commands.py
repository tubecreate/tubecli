"""
WebUI CLI commands.
"""
import click
import threading
from rich.console import Console

console = Console()


@click.group("webui")
def webui_group():
    """Web dashboard for TubeCLI."""
    pass


@webui_group.command("start")
@click.option("--port", default=3000, help="Dashboard port")
def start_webui(port):
    """Start the web dashboard."""
    import http.server
    import os
    import functools

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    if not os.path.exists(os.path.join(static_dir, "index.html")):
        console.print("[red]❌ Dashboard files not found.[/red]")
        return

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=static_dir)
    server = http.server.HTTPServer(("0.0.0.0", port), handler)

    console.print(f"[green]🎨 TubeCLI Dashboard started[/green]")
    console.print(f"   URL: [cyan]http://localhost:{port}[/cyan]")
    console.print(f"   Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[yellow]Dashboard stopped.[/yellow]")
