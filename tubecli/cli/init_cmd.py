"""
tubecli init — Initialize workspace, create data dirs, install default skills.
Supports --lang option for multi-language setup.
Includes first-run Setup Wizard for guided onboarding.
"""
import click
import re
import json
import os
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


@click.command("init")
@click.option("--lang", type=click.Choice(["zh", "vi", "en"]), default=None,
              help="Set UI language (zh=Chinese, vi=Vietnamese, en=English)")
def init_cmd(lang):
    """Initialize TubeCLI workspace and install default skills."""
    from tubecli.config import ensure_data_dirs, DATA_DIR, set_language, get_language, SUPPORTED_LANGUAGES
    from tubecli.i18n import load_language, t

    # 0. Language selection
    if lang is None:
        # Interactive prompt if --lang not provided
        lang = click.prompt(
            "🌐 Choose language / 选择语言 / Chọn ngôn ngữ",
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

    # 3b. Create built-in specialist agents for team delegation
    from tubecli.core.specialists import register_builtin_specialists
    created_specialists = register_builtin_specialists()
    if created_specialists:
        console.print(f"  [green]✅ Created {len(created_specialists)} specialist agents:[/green]")
        for name in created_specialists:
            console.print(f"    • {name}")

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

    # 6. Check if first run → launch Setup Wizard
    from tubecli.config import get_setting
    if not get_setting("setup_completed"):
        _run_setup_wizard()

    # 7. Launch Interactive Menu
    _run_control_panel()


def _kill_server_on_port(port: int):
    """Kill any process listening on the given port (cross-platform)."""
    import subprocess, os
    try:
        if os.name == "nt":
            result = subprocess.run(
                f"netstat -ano | findstr :{port}",
                shell=True, capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        else:
            subprocess.run(f"fuser -k {port}/tcp", shell=True, capture_output=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  SETUP WIZARD — First-run guided onboarding
# ═══════════════════════════════════════════════════════════════

def _run_setup_wizard():
    """3-step setup wizard for first-time users."""
    from tubecli.i18n import t
    from tubecli.config import set_setting

    # Welcome banner
    console.print()
    console.print(Panel(
        t("wizard.welcome_body"),
        title=t("wizard.welcome_title"),
        border_style="bright_cyan",
        padding=(1, 2),
    ))

    # Option to skip entirely
    console.print(f"\n  [bold yellow]0.[/bold yellow] {t('wizard.skip_all')}")
    console.print(f"  [bold yellow]1.[/bold yellow] {t('wizard.start_setup')}\n")
    choice = click.prompt(t("panel.select"), type=str, default="1")
    if choice == "0":
        set_setting("setup_completed", True)
        console.print(t("wizard.skipped_all"))
        return

    # ── Step 1: AI Chat Setup ────────────────────────────────
    _wizard_step_ai(t)

    # ── Step 2: Telegram Setup ───────────────────────────────
    _wizard_step_telegram(t)

    # ── Step 3: Summary ──────────────────────────────────────
    _wizard_step_summary(t)

    set_setting("setup_completed", True)


def _wizard_step_ai(t):
    """Step 1: Configure AI provider (API key or Ollama)."""
    console.print()
    console.print(Panel(
        t("wizard.ai_body"),
        title=t("wizard.ai_title"),
        border_style="green",
        padding=(1, 2),
    ))

    console.print(f"  [bold yellow]1.[/bold yellow] {t('wizard.ai_gemini')}")
    console.print(f"  [bold yellow]2.[/bold yellow] {t('wizard.ai_other')}")
    console.print(f"  [bold yellow]3.[/bold yellow] {t('wizard.ai_ollama')}")
    console.print(f"  [bold yellow]0.[/bold yellow] {t('wizard.skip_step')}\n")

    choice = click.prompt(t("panel.select"), type=str, default="1")

    if choice == "0":
        console.print(t("wizard.step_skipped"))
        return

    if choice == "1":
        # Gemini setup
        console.print(t("wizard.gemini_guide"))
        key = click.prompt(t("wizard.enter_api_key"), default="", show_default=False)
        if key.strip():
            _save_api_key("gemini", key.strip())
        else:
            console.print(t("wizard.step_skipped"))

    elif choice == "2":
        # Other providers submenu
        providers = [
            ("openai", "OpenAI"),
            ("claude", "Anthropic Claude"),
            ("deepseek", "DeepSeek"),
        ]
        for i, (pid, pname) in enumerate(providers, 1):
            console.print(f"  [bold yellow]{i}.[/bold yellow] {pname}")
        console.print(f"  [bold yellow]0.[/bold yellow] {t('wizard.skip_step')}\n")

        sub = click.prompt(t("panel.select"), type=str, default="0")
        try:
            idx = int(sub) - 1
            if 0 <= idx < len(providers):
                pid, pname = providers[idx]
                key = click.prompt(f"{t('wizard.enter_api_key')} ({pname})", default="", show_default=False)
                if key.strip():
                    _save_api_key(pid, key.strip())
                else:
                    console.print(t("wizard.step_skipped"))
            else:
                console.print(t("wizard.step_skipped"))
        except ValueError:
            console.print(t("wizard.step_skipped"))

    elif choice == "3":
        # Ollama guide
        from tubecli.core.ollama_utils import is_ollama_installed, get_installed_models
        if is_ollama_installed():
            models = get_installed_models()
            if models:
                console.print("\n[bold cyan]  Mô hình Ollama đã cài đặt:[/bold cyan]")
                for i, m in enumerate(models, 1):
                    console.print(f"  [bold yellow]{i}.[/bold yellow] {m}")
                console.print(f"  [bold yellow]0.[/bold yellow] {t('wizard.skip_step')}\n")
                
                sel = click.prompt(t("panel.select"), type=str, default="1")
                if sel == "0":
                    console.print(t("wizard.step_skipped"))
                else:
                    try:
                        idx = int(sel) - 1
                        if 0 <= idx < len(models):
                            selected_model = models[idx]
                            # Update global config
                            try:
                                from tubecli.extensions.webui.routes import _DEFAULT_SETTINGS, _settings_path
                                import json, os
                                p = _settings_path()
                                existing = _DEFAULT_SETTINGS.copy()
                                if os.path.exists(p):
                                    with open(p, "r", encoding="utf-8") as f:
                                        existing.update(json.load(f))
                                existing["default_model"] = selected_model
                                with open(p, "w", encoding="utf-8") as f:
                                    json.dump(existing, f, indent=2, ensure_ascii=False)
                                    
                                from tubecli.core.agent import agent_manager
                                for agent in agent_manager.get_all():
                                    agent_manager.update(agent.id, model=selected_model)
                                    
                                console.print(f"[green]✅ Đã tự động đặt AI mặc định: [bold]{selected_model}[/bold] cho tất cả agents.[/green]")
                            except Exception as e:
                                console.print(f"[red]❌ Lỗi khi lưu cấu hình: {e}[/red]")
                        else:
                            console.print(t("panel.invalid_selection"))
                    except ValueError:
                        console.print(t("wizard.step_skipped"))
            else:
                console.print("[yellow]Ollama đã được cài đặt nhưng chưa có mô hình nào.[/yellow]")
                console.print(t("wizard.ollama_ready"))
        else:
            console.print(t("wizard.ollama_not_ready"))


def _save_api_key(provider_id: str, key: str):
    """Save an API key via the cloud_api extension's key_manager.
    Also auto-sets the default AI model on all agents."""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        result = key_manager.add_key(provider_id, key)
        if result.get("status") == "success":
            console.print(f"[green]✅ {provider_id.upper()} API Key {_t_safe('wizard.key_saved')}[/green]")
            # Auto-set model on all agents
            _auto_set_agent_model(provider_id, key)
        else:
            console.print(f"[red]❌ {result.get('message', 'Error')}[/red]")
    except Exception as e:
        console.print(f"[red]❌ {e}[/red]")


def _auto_set_agent_model(provider_id: str, key: str):
    """Auto-update all agents to use the cloud model when a key is saved."""
    # Map provider → default cloud model
    model_map = {
        "gemini": "gemini-1.5-flash",
        "openai": "gpt-4o-mini",
        "claude": "claude-sonnet-4-20250514",
        "deepseek": "deepseek-chat",
    }
    model = model_map.get(provider_id)
    if not model:
        return

    try:
        from tubecli.core.agent import agent_manager
        for agent in agent_manager.get_all():
            # Update model
            cloud_keys = agent.cloud_api_keys or {}
            cloud_keys[provider_id] = key
            agent_manager.update(
                agent.id,
                model=model,
                cloud_api_keys=cloud_keys,
            )
        console.print(f"[green]  🧠 Đã tự động đặt AI mặc định: [bold]{model}[/bold] cho tất cả agents.[/green]")
    except Exception as e:
        console.print(f"[yellow]  ⚠️ Không thể tự động cập nhật agent model: {e}[/yellow]")


def _t_safe(key):
    """Try to translate, fallback to key."""
    try:
        from tubecli.i18n import t
        return t(key)
    except Exception:
        return key


def _wizard_step_telegram(t):
    """Step 2: Connect Telegram bot."""
    console.print()
    console.print(Panel(
        t("wizard.telegram_body"),
        title=t("wizard.telegram_title"),
        border_style="blue",
        padding=(1, 2),
    ))

    console.print(f"  [bold yellow]1.[/bold yellow] {t('wizard.telegram_start')}")
    console.print(f"  [bold yellow]0.[/bold yellow] {t('wizard.skip_step')}\n")

    choice = click.prompt(t("panel.select"), type=str, default="1")

    if choice == "0":
        console.print(t("wizard.step_skipped"))
        return

    # Guide
    console.print(t("wizard.telegram_guide"))

    token = click.prompt(t("wizard.telegram_enter_token"), default="", show_default=False)
    if not token.strip():
        console.print(t("wizard.step_skipped"))
        return

    token = token.strip()

    # Validate token format
    if not re.match(r'^\d+:[A-Za-z0-9_-]+$', token):
        console.print(t("wizard.telegram_invalid_token"))
        return

    # Test the token
    try:
        import requests
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.status_code == 200 and resp.json().get("ok"):
            bot_info = resp.json()["result"]
            bot_name = bot_info.get("first_name", "Bot")
            bot_username = bot_info.get("username", "")
            console.print(f"[green]✅ {t('wizard.telegram_connected', name=bot_name, username=bot_username)}[/green]")

            # Save to global_settings.json
            _save_telegram_token(token)

            console.print(f"\n  💡 {t('wizard.telegram_next_step', username=bot_username)}")
        else:
            console.print(t("wizard.telegram_invalid_token"))
    except Exception as e:
        console.print(f"[red]❌ {t('wizard.telegram_test_fail')}: {e}[/red]")


def _save_telegram_token(token: str):
    """Save telegram bot token to global_settings.json."""
    from tubecli.config import DATA_DIR
    settings_path = DATA_DIR / "global_settings.json"

    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            pass

    settings["telegram_bot_token"] = token
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def _wizard_step_summary(t):
    """Step 3: Show setup summary."""
    from tubecli.config import DATA_DIR, get_api_port

    # Check AI status
    ai_status = "❌"
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        for prov in ["gemini", "openai", "claude", "deepseek"]:
            if key_manager.get_active_key(prov):
                ai_status = f"✅ {prov.upper()}"
                break
    except Exception:
        pass
    # Check Ollama
    if ai_status == "❌":
        try:
            from tubecli.core.ollama_utils import is_ollama_installed
            if is_ollama_installed():
                ai_status = "✅ Ollama"
        except Exception:
            pass

    # Check Telegram status
    tg_status = "❌"
    tg_username = ""
    settings_path = DATA_DIR / "global_settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                gs = json.load(f)
            token = gs.get("telegram_bot_token", "")
            if token:
                import requests
                resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
                if resp.status_code == 200 and resp.json().get("ok"):
                    tg_username = resp.json()["result"].get("username", "")
                    tg_status = f"✅ @{tg_username}"
        except Exception:
            tg_status = "✅ (configured)"

    port = get_api_port()

    summary = (
        f"  🧠 AI Chat: {ai_status}\n"
        f"  💬 Telegram: {tg_status}\n"
        f"  🖥️  Dashboard: [cyan]http://localhost:{port}/dashboard[/cyan]\n"
    )

    console.print()
    console.print(Panel(
        summary,
        title=t("wizard.summary_title"),
        border_style="bright_green",
        padding=(1, 2),
    ))

    if tg_username:
        console.print(f"  💡 {t('wizard.summary_tip', username=tg_username)}")
    console.print()


# ═══════════════════════════════════════════════════════════════
#  CONTROL PANEL — Main interactive menu
# ═══════════════════════════════════════════════════════════════

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
    show_api_logs = False  # Default: quiet mode (no INFO spam)

    def _start_api(quiet: bool):
        """Start/restart API server — always hidden (no console window)."""
        _kill_server_on_port(port)
        import time
        from tubecli.config import get_language
        cur_lang = get_language()
        cmd = f"tubecli api start{' --quiet' if quiet else ''} --lang {cur_lang}"
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"  # Ensure UTF-8 output even if hidden
        if os.name == "nt":
            CREATE_NO_WINDOW = 0x08000000  # Completely suppress console window
            subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
                env=env,
            )
        else:
            subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env,
            )
        time.sleep(2)

    # Initial start — quiet by default
    console.print(t("panel.api_starting", port=port))
    _start_api(quiet=True)
    console.print(t("panel.api_started"))

    import time

    while True:
        # ── Clear screen then draw menu cleanly ──────────────────
        os.system("cls" if os.name == "nt" else "clear")
        log_status = t("panel.logs_on") if show_api_logs else t("panel.logs_off")
        console.print("[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  {t('panel.title'):^44}[bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╠══════════════════════════════════════════════╣[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]1.[/bold yellow] {t('panel.dashboard'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]2.[/bold yellow] {t('panel.api_keys'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]3.[/bold yellow] {t('panel.agents'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]4.[/bold yellow] {t('panel.install_model'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]5.[/bold yellow] {t('panel.browser_profile'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]6.[/bold yellow] {t('panel.docs'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]7.[/bold yellow] {t('panel.setup_wizard'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]8.[/bold yellow] {t('panel.toggle_logs')} [{log_status}]{'':>19}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] {t('panel.exit'):<42}[bold cyan]║[/bold cyan]")
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
                                    _auto_set_agent_model(prov_id, new_key.strip())
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
            from tubecli.config import BASE_DIR, get_language
            lang = get_language()
            # Map language to docs file
            lang_doc_map = {
                "vi":  "index.html",
                "en":  "en.html",
                "zh":  "zh.html",
            }
            doc_file = lang_doc_map.get(lang, "index.html")
            docs_path = BASE_DIR / "docs" / doc_file
            # Fallback to index.html if lang-specific file not found
            if not docs_path.exists():
                docs_path = BASE_DIR / "docs" / "index.html"
            if docs_path.exists():
                try:
                    import webbrowser
                    webbrowser.open(f"file://{docs_path.absolute()}")
                except Exception:
                    console.print(f"Open this file in your browser: {docs_path}")
            else:
                console.print(t("panel.docs_not_found"))

        elif choice == "7":
            _run_setup_wizard()

        elif choice == "8":
            show_api_logs = not show_api_logs
            mode = t("panel.logs_on") if show_api_logs else t("panel.logs_off")
            console.print(f"[cyan]{t('panel.toggle_logs_msg')} → [{mode}][/cyan]")
            console.print(t("panel.api_restarting"))
            _start_api(quiet=not show_api_logs)
            console.print(t("panel.api_started"))

        else:
            console.print(t("panel.invalid_selection"))
