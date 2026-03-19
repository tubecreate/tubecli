"""
Ollama Manager Extension — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("ollama")
def ollama_group():
    """Manage local Ollama AI models."""
    pass


@ollama_group.command("status")
def ollama_status():
    """Check Ollama server status."""
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager

    status = ollama_model_manager.server_status()
    if status["running"]:
        console.print(f"[green]✅ Ollama is running[/green] at {status['base_url']}")
        console.print(f"   Models: {status.get('model_count', 0)} installed, {status.get('loaded_count', 0)} loaded")
    else:
        console.print(f"[red]❌ Ollama is not running[/red] at {status['base_url']}")
        console.print("[dim]Start with: ollama serve[/dim]")


@ollama_group.command("models")
def list_models():
    """List locally installed models."""
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager

    result = ollama_model_manager.list_models()
    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
        return

    models = result.get("models", [])
    if not models:
        console.print("[dim]No models installed. Use: tubecli ollama pull <model>[/dim]")
        return

    table = Table(title="🧠 Ollama Models")
    table.add_column("Name", style="cyan bold")
    table.add_column("Size", style="green", justify="right")
    table.add_column("Modified", style="dim")
    table.add_column("Digest", style="dim")

    for m in models:
        table.add_row(m["name"], m["size_human"], m["modified_at"][:10], m["digest"])

    console.print(table)


@ollama_group.command("running")
def list_running():
    """List currently loaded/running models."""
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager

    result = ollama_model_manager.list_running()
    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
        return

    running = result.get("running", [])
    if not running:
        console.print("[dim]No models currently loaded.[/dim]")
        return

    table = Table(title="🔥 Running Models")
    table.add_column("Name", style="cyan bold")
    table.add_column("Size", style="green", justify="right")
    table.add_column("Expires", style="dim")

    for m in running:
        table.add_row(m["name"], m["size_human"], m.get("expires_at", "")[:19])

    console.print(table)


@ollama_group.command("pull")
@click.argument("model_name")
def pull_model(model_name):
    """Pull/download a model from Ollama registry.

    Example: tubecli ollama pull qwen:latest
    """
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager

    console.print(f"📥 Pulling model: [cyan]{model_name}[/cyan]...")
    console.print("[dim]This may take a while for large models...[/dim]")

    result = ollama_model_manager.pull_model(model_name)
    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
    else:
        console.print(f"[green]✅ {result['message']}[/green]")


@ollama_group.command("remove")
@click.argument("model_name")
@click.confirmation_option(prompt="Are you sure you want to remove this model?")
def remove_model(model_name):
    """Remove a locally stored model."""
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager

    result = ollama_model_manager.remove_model(model_name)
    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
    else:
        console.print(f"[green]✅ {result['message']}[/green]")


@ollama_group.command("show")
@click.argument("model_name")
def show_model(model_name):
    """Show details about a specific model."""
    from tubecli.extensions.ollama_manager.extension import ollama_model_manager
    import json

    result = ollama_model_manager.show_model(model_name)
    if "error" in result:
        console.print(f"[red]❌ {result['error']}[/red]")
    else:
        console.print(f"\n🧠 [bold cyan]{model_name}[/bold cyan]")
        # Show key fields
        if "modelfile" in result:
            console.print(f"[dim]Modelfile:[/dim] {result['modelfile'][:200]}...")
        if "parameters" in result:
            console.print(f"[dim]Parameters:[/dim] {result['parameters'][:200]}")
        if "template" in result:
            console.print(f"[dim]Template:[/dim] {result['template'][:200]}...")
        console.print()
