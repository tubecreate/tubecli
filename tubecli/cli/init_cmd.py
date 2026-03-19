"""
tubecli init — Initialize workspace, create data dirs, install default skills.
"""
import click
from rich.console import Console

console = Console()


@click.command("init")
def init_cmd():
    """Initialize TubeCLI workspace and install default skills."""
    from tubecli.config import ensure_data_dirs, DATA_DIR

    console.print("\n🚀 [bold cyan]Initializing TubeCLI workspace...[/bold cyan]\n")

    # 1. Create data directories
    ensure_data_dirs()
    console.print(f"  📁 Data directory: [green]{DATA_DIR}[/green]")

    # 2. Register default skills
    console.print("  📦 Installing default skills...")
    from tubecli.skills.default_skills import register_default_skills
    register_default_skills()

    # 3. Create default agent if none exist
    from tubecli.core.agent import agent_manager
    if not agent_manager.get_all():
        agent_manager.create(
            name="Personal Assistant",
            description="General purpose AI assistant",
            system_prompt="You are a helpful AI assistant. Respond concisely.",
        )
        console.print("  🤖 Created default agent: [green]Personal Assistant[/green]")

    # 4. Enable default extensions
    console.print("  🧩 Enabling core extensions...")
    from tubecli.core.extension_manager import extension_manager
    extension_manager.discover_extensions()
    for ext in extension_manager.get_all():
        if ext.extension_type == "system":
            extension_manager.enable(ext.name)
    console.print("  ✅ Core extensions enabled.")

    # 5. Check and Install Ollama
    from tubecli.core.ollama_utils import is_ollama_installed, install_ollama
    if not is_ollama_installed():
        console.print("\n⚠️  [bold yellow]Ollama is not installed![/bold yellow]")
        console.print("Ollama is required to run local AI models (like Qwen, Llama).")
        if click.confirm("Do you want to automatically install Ollama now?"):
            install_ollama()
    else:
        console.print("\n✅ [green]Ollama is already installed.[/green]")

    console.print("\n✅ [bold green]TubeCLI workspace successfully initialized![/bold green]\n")
    
    # 6. Launch Interactive Menu
    _run_control_panel()


def _run_control_panel():
    """Interactive control panel menu displayed after initialization."""
    from tubecli.core.ollama_utils import is_ollama_installed, get_recommended_models, install_model
    import subprocess
    import requests
    from tubecli.config import get_api_port, DATA_DIR
    import json
    import os
    
    port = get_api_port()
    
    # Auto-start API Server if not running
    try:
        resp = requests.get(f"http://localhost:{port}/api/v1/health", timeout=1)
        if resp.status_code == 200:
            console.print(f"\n✅ [green]API server is already running on port {port}.[/green]")
    except requests.exceptions.ConnectionError:
        console.print(f"\n[cyan]Starting API Server on port {port}...[/cyan]")
        if os.name == "nt":
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen("tubecli api start", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags)
        else:
            subprocess.Popen("tubecli api start", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console.print("[green]API Server started in background.[/green]")

    while True:
        console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]       ⚡ [bold white]TubeCLI Workspace Ready[/bold white]             [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╠══════════════════════════════════════════════╣[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]1.[/bold yellow] 🖥️  Open Dashboard in Browser            [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]2.[/bold yellow] 🔑 Configure API Keys (Gemini/OpenAI)    [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]3.[/bold yellow] 🤖 Manage Agents                         [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]4.[/bold yellow] 🧠 Install AI Model (Ollama)             [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]5.[/bold yellow] 🌐 Launch Browser Profile                [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]6.[/bold yellow] 📖 View Documentation                    [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] ❌ Exit                                   [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")
        
        choice = click.prompt("\n👉 Select an option", type=str, default="1")
        
        if choice == "0":
            console.print("[yellow]Exiting Control Panel. You can run tubecli commands anytime.[/yellow]")
            break
            
        elif choice == "1":
            console.print("\n[cyan]Opening Dashboard...[/cyan]")
            try:
                import webbrowser
                dashboard_url = f"http://localhost:{port}/dashboard"
                webbrowser.open(dashboard_url)
                console.print(f"[green]Dashboard opened at {dashboard_url}[/green]")
            except Exception:
                console.print(f"[red]Could not open browser automatically. Please open http://localhost:{port}/dashboard[/red]")
                
        elif choice == "2":
            try:
                from tubecli.extensions.cloud_api.extension import key_manager, PROVIDERS
                
                while True:
                    console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
                    console.print("[bold cyan]║[/bold cyan]       🔑 [bold white]API Key Configuration[/bold white]               [bold cyan]║[/bold cyan]")
                    console.print("[bold cyan]╠══════════════════════════════════════════════╣[/bold cyan]")
                    
                    # Create a sorted list of providers for stable menu numbering
                    prov_keys = list(PROVIDERS.keys())
                    for i, prov_id in enumerate(prov_keys, 1):
                        prov = PROVIDERS[prov_id]
                        has_key = key_manager.get_active_key(prov_id) is not None
                        status = "[green]Set[/green]" if has_key else "[red]Not set[/red]"
                        # Format string to look like: ║  1. Google Gemini (Set) 
                        menu_item = f"  [bold yellow]{i}.[/bold yellow] {prov['name']} ({status})"
                        # Padding for visual alignment
                        padding = " " * max(0, 42 - len(click.unstyle(menu_item)))
                        console.print(f"[bold cyan]║[/bold cyan]{menu_item}{padding}[bold cyan]║[/bold cyan]")
                        
                    console.print("[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] 🔙 Return to Main Menu                   [bold cyan]║[/bold cyan]")
                    console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")
                    
                    sub_choice = click.prompt("\n👉 Select provider to configure (or 0 to return)", type=str, default="0")
                    
                    if sub_choice == "0":
                        break
                        
                    try:
                        idx = int(sub_choice) - 1
                        if 0 <= idx < len(prov_keys):
                            prov_id = prov_keys[idx]
                            prov_name = PROVIDERS[prov_id]["name"]
                            
                            console.print(f"\n[cyan]Configuring {prov_name}...[/cyan]")
                            new_key = click.prompt(f"Enter new API Key (or press Enter to cancel)", default="", show_default=False)
                            
                            if new_key.strip():
                                result = key_manager.add_key(prov_id, new_key.strip())
                                if result.get("status") == "success":
                                    console.print(f"[green]✅ {prov_name} API Key saved successfully![/green]")
                                else:
                                    console.print(f"[red]❌ Failed to save key: {result.get('message')}[/red]")
                            else:
                                console.print("[yellow]Cancelled. No changes made.[/yellow]")
                        else:
                            console.print("[red]Invalid selection. Please try again.[/red]")
                    except ValueError:
                        console.print("[red]Invalid selection. Please try again.[/red]")
                        
            except ImportError:
                console.print("[red]Could not load cloud_api extension. Please ensure it is enabled.[/red]")
                
        elif choice == "3":
            console.print("\n[cyan]Agent Management:[/cyan]")
            subprocess.run(["tubecli", "agent", "list"])
            console.print("\n[yellow]Run 'tubecli agent --help' for more commands.[/yellow]")
            
        elif choice == "4":
            if not is_ollama_installed():
                console.print("\n[red]Ollama is not installed. Please install it first.[/red]")
                continue
                
            console.print("\n[bold cyan]🧠 AI Model Installer (Ollama)[/bold cyan]")
            recs = get_recommended_models()
            
            console.print("\n[bold]Models recommended for your system RAM:[/bold]")
            for i, model in enumerate(recs, 1):
                console.print(f"  [yellow]{i}.[/yellow] [green]{model['name']}[/green] - {model['desc']}")
            console.print(f"  [yellow]0.[/yellow] Cancel")
            
            m_choice = click.prompt("\nSelect model to install", type=int, default=1)
            if 1 <= m_choice <= len(recs):
                model_name = recs[m_choice-1]['name']
                install_model(model_name)
            else:
                console.print("[yellow]Installation cancelled.[/yellow]")
                
        elif choice == "5":
            console.print("\n[cyan]Browser Profiles:[/cyan]")
            subprocess.run(["tubecli", "browser", "profiles"])
            console.print("\n[yellow]Run 'tubecli browser launch <profile-name>' to start a browser.[/yellow]")
            
        elif choice == "6":
            console.print("\n[cyan]Documentation:[/cyan]")
            from tubecli.config import BASE_DIR
            docs_path = BASE_DIR / "docs" / "index.html"
            if docs_path.exists():
                try:
                    import webbrowser
                    webbrowser.open(f"file://{docs_path.absolute()}")
                except Exception:
                    console.print(f"Open this file in your browser: {docs_path}")
            else:
                console.print("[yellow]Documentation file not found.[/yellow]")
                
        else:
            console.print("[red]Invalid selection. Please try again.[/red]")
