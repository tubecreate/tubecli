"""
tubecli init — Initialize workspace, create data dirs, install default skills.
Supports --lang option for multi-language setup.
"""
import click
from rich.console import Console

console = Console()


@click.command("init")
@click.option("--lang", type=click.Choice(["vi", "en"]), default=None,
              help="Set UI language (vi=Vietnamese, en=English)")
def init_cmd(lang):
    """Initialize TubeCLI workspace and install default skills."""
    from tubecli.config import ensure_data_dirs, DATA_DIR, set_language, get_language, SUPPORTED_LANGUAGES
    from tubecli.i18n import load_language, t

    # 0. Language selection
    if lang is None:
        # Interactive prompt if --lang not provided
        lang = click.prompt(
            "🌐 Choose language / Chọn ngôn ngữ",
            type=click.Choice(SUPPORTED_LANGUAGES),
            default=get_language(),
        )
    set_language(lang)
    load_language(lang)

    console.print(t("init.lang_saved", lang=lang))
    console.print(t("init.initializing"))

    # 1. Create data directories
    ensure_data_dirs()
    console.print(t("init.data_dir", path=DATA_DIR))

    # 2. Register default skills
    console.print(t("init.installing_skills"))
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
        console.print(t("init.created_agent", name="Personal Assistant"))

    # 4. Enable default extensions
    console.print(t("init.enabling_extensions"))
    from tubecli.core.extension_manager import extension_manager
    extension_manager.discover_extensions()
    for ext in extension_manager.get_all():
        if ext.extension_type == "system":
            extension_manager.enable(ext.name)
    console.print(t("init.extensions_enabled"))

    # 5. Check and Install Ollama
    from tubecli.core.ollama_utils import is_ollama_installed, install_ollama
    if not is_ollama_installed():
        console.print(t("init.ollama_not_installed"))
        console.print(t("init.ollama_required"))
        if click.confirm(t("init.ollama_install_confirm")):
            install_ollama()
    else:
        console.print(t("init.ollama_installed"))

    console.print(t("init.workspace_ready"))
    
    # 6. Launch Interactive Menu
    _run_control_panel()


def _run_control_panel():
    """Interactive control panel menu displayed after initialization."""
    from tubecli.core.ollama_utils import is_ollama_installed, get_recommended_models, install_model
    import subprocess
    import requests
    from tubecli.config import get_api_port, DATA_DIR
    from tubecli.i18n import t
    import json
    import os
    
    port = get_api_port()
    
    # Auto-start API Server if not running
    try:
        resp = requests.get(f"http://localhost:{port}/api/v1/health", timeout=1)
        if resp.status_code == 200:
            console.print(t("panel.api_running", port=port))
    except requests.exceptions.ConnectionError:
        console.print(t("panel.api_starting", port=port))
        if os.name == "nt":
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen("tubecli api start", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags)
        else:
            subprocess.Popen("tubecli api start", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        console.print(t("panel.api_started"))

    while True:
        console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]       {t('panel.title')}             [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╠══════════════════════════════════════════════╣[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]1.[/bold yellow] {t('panel.dashboard')}            [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]2.[/bold yellow] {t('panel.api_keys')}    [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]3.[/bold yellow] {t('panel.agents')}                         [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]4.[/bold yellow] {t('panel.install_model')}             [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]5.[/bold yellow] {t('panel.browser_profile')}                [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]6.[/bold yellow] {t('panel.docs')}                    [bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] {t('panel.exit')}                                   [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")
        
        choice = click.prompt(t("panel.select"), type=str, default="1")
        
        if choice == "0":
            console.print(t("panel.exiting"))
            break
            
        elif choice == "1":
            console.print(t("panel.opening_dashboard"))
            try:
                import webbrowser
                dashboard_url = f"http://localhost:{port}/dashboard"
                webbrowser.open(dashboard_url)
                console.print(t("panel.dashboard_opened", url=dashboard_url))
            except Exception:
                console.print(t("panel.dashboard_error", url=f"http://localhost:{port}/dashboard"))
                
        elif choice == "2":
            try:
                from tubecli.extensions.cloud_api.extension import key_manager, PROVIDERS
                
                while True:
                    console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
                    console.print(f"[bold cyan]║[/bold cyan]       {t('panel.api_key_title')}               [bold cyan]║[/bold cyan]")
                    console.print("[bold cyan]╠══════════════════════════════════════════════╣[/bold cyan]")
                    
                    # Create a sorted list of providers for stable menu numbering
                    prov_keys = list(PROVIDERS.keys())
                    for i, prov_id in enumerate(prov_keys, 1):
                        prov = PROVIDERS[prov_id]
                        has_key = key_manager.get_active_key(prov_id) is not None
                        status = t("panel.key_status_set") if has_key else t("panel.key_status_not_set")
                        # Format string to look like: ║  1. Google Gemini (Set) 
                        menu_item = f"  [bold yellow]{i}.[/bold yellow] {prov['name']} ({status})"
                        # Padding for visual alignment
                        padding = " " * max(0, 42 - len(click.unstyle(menu_item)))
                        console.print(f"[bold cyan]║[/bold cyan]{menu_item}{padding}[bold cyan]║[/bold cyan]")
                        
                    console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] {t('panel.return_main')}                   [bold cyan]║[/bold cyan]")
                    console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")
                    
                    sub_choice = click.prompt(t("panel.select_provider"), type=str, default="0")
                    
                    if sub_choice == "0":
                        break
                        
                    try:
                        idx = int(sub_choice) - 1
                        if 0 <= idx < len(prov_keys):
                            prov_id = prov_keys[idx]
                            prov_name = PROVIDERS[prov_id]["name"]
                            
                            console.print(t("panel.configuring", name=prov_name))
                            new_key = click.prompt(t("panel.enter_key"), default="", show_default=False)
                            
                            if new_key.strip():
                                result = key_manager.add_key(prov_id, new_key.strip())
                                if result.get("status") == "success":
                                    console.print(t("panel.key_saved", name=prov_name))
                                else:
                                    console.print(t("panel.key_failed", msg=result.get('message')))
                            else:
                                console.print(t("panel.cancelled"))
                        else:
                            console.print(t("panel.invalid_selection"))
                    except ValueError:
                        console.print(t("panel.invalid_selection"))
                        
            except ImportError:
                console.print(t("panel.cloud_api_error"))
                
        elif choice == "3":
            console.print(t("panel.agent_management"))
            subprocess.run(["tubecli", "agent", "list"])
            console.print(t("panel.agent_help"))
            
        elif choice == "4":
            if not is_ollama_installed():
                console.print(t("panel.ollama_not_installed_short"))
                continue
                
            console.print(t("panel.model_installer_title"))
            recs = get_recommended_models()
            
            console.print(t("panel.models_recommended"))
            for i, model in enumerate(recs, 1):
                console.print(f"  [yellow]{i}.[/yellow] [green]{model['name']}[/green] - {model['desc']}")
            console.print(f"  [yellow]0.[/yellow] Cancel")
            
            m_choice = click.prompt(t("panel.select_model"), type=int, default=1)
            if 1 <= m_choice <= len(recs):
                model_name = recs[m_choice-1]['name']
                install_model(model_name)
            else:
                console.print(t("panel.install_cancelled"))
                
        elif choice == "5":
            console.print(t("panel.browser_profiles"))
            subprocess.run(["tubecli", "browser", "profiles"])
            console.print(t("panel.browser_help"))
            
        elif choice == "6":
            console.print(t("panel.documentation"))
            from tubecli.config import BASE_DIR
            docs_path = BASE_DIR / "docs" / "index.html"
            if docs_path.exists():
                try:
                    import webbrowser
                    webbrowser.open(f"file://{docs_path.absolute()}")
                except Exception:
                    console.print(f"Open this file in your browser: {docs_path}")
            else:
                console.print(t("panel.docs_not_found"))
                
        else:
            console.print(t("panel.invalid_selection"))
