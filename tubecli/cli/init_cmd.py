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
@click.option("--port", type=int, default=None,
              help="Set API server port (default: 5295)")
def init_cmd(lang, port):
    """Initialize TubeCLI workspace and install default skills."""
    from tubecli.config import ensure_data_dirs, DATA_DIR, set_language, get_language, SUPPORTED_LANGUAGES, BASE_DIR
    from tubecli.i18n import load_language, t

    # Check for temporary .restarted flag file to prevent opening browser on auto-restart
    restart_flag_file = os.path.join(str(BASE_DIR), ".restarted")
    if os.path.exists(restart_flag_file):
        os.environ["TUBECLI_RESTARTED"] = "1"
        try:
            os.remove(restart_flag_file)
        except Exception:
            pass

    # 0a. Port configuration — persist before anything else uses get_api_port()
    if port is not None:
        from tubecli.config import set_api_port
        if set_api_port(port):
            os.environ["TUBECLI_PORT"] = str(port)
            console.print(f"  [green]API port set to [bold]{port}[/bold][/green]")
        else:
            console.print(f"  [red]Failed to save port {port}[/red]")

    # 0b. Language selection
    if lang is None:
        # Interactive prompt if --lang not provided
        lang = click.prompt(
            "Choose language / 选择语言 / Chọn ngôn ngữ",
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
        console.print(f"  [green]Created {len(created_specialists)} specialist agents:[/green]")
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

    # 5. Ollama check — silently skip (optional, user can install via menu option 4)
    # No interactive prompt on startup

    console.print(t("init.workspace_ready"))

    # 6. Check if first run → launch Setup Wizard
    from tubecli.config import get_setting
    if not get_setting("setup_completed"):
        _run_setup_wizard()

    # 7. Launch Interactive Menu
    _run_control_panel()


def _kill_server_on_port(port: int):
    """Kill any process listening on the given port (cross-platform) and wait for it to be released."""
    import subprocess, os, time, socket
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
        
        # Wait up to 3 seconds for the socket to be completely released by the OS
        for _ in range(6):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    break # Port is free!
                except socket.error:
                    pass
            time.sleep(0.5)
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
            ("openrouter", "OpenRouter"),
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
                                    
                                console.print(f"[green]Đã tự động đặt AI mặc định: [bold]{selected_model}[/bold] cho tất cả agents.[/green]")
                            except Exception as e:
                                console.print(f"[red]Lỗi khi lưu cấu hình: {e}[/red]")
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
            console.print(f"[green]{provider_id.upper()} API Key {_t_safe('wizard.key_saved')}[/green]")
            # Auto-set model on all agents
            _auto_set_agent_model(provider_id, key)
        else:
            console.print(f"[red]{result.get('message', 'Error')}[/red]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


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
        console.print(f"[green]  Đã tự động đặt AI mặc định: [bold]{model}[/bold] cho tất cả agents.[/green]")
    except Exception as e:
        console.print(f"[yellow]  Không thể tự động cập nhật agent model: {e}[/yellow]")


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
            console.print(f"[green]{t('wizard.telegram_connected', name=bot_name, username=bot_username)}[/green]")

            # Save to global_settings.json
            _save_telegram_token(token)

            console.print(f"\n  {t('wizard.telegram_next_step', username=bot_username)}")
        else:
            console.print(t("wizard.telegram_invalid_token"))
    except Exception as e:
        console.print(f"[red]{t('wizard.telegram_test_fail')}: {e}[/red]")


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
    ai_status = ""
    try:
        from tubecli.extensions.cloud_api.extension import key_manager
        for prov in ["gemini", "openai", "claude", "deepseek"]:
            if key_manager.get_active_key(prov):
                ai_status = f"{prov.upper()}"
                break
    except Exception:
        pass
    # Check Ollama
    if ai_status == "":
        try:
            from tubecli.core.ollama_utils import is_ollama_installed
            if is_ollama_installed():
                ai_status = "Ollama"
        except Exception:
            pass

    # Check Telegram status
    tg_status = ""
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
                    tg_status = f"@{tg_username}"
        except Exception:
            tg_status = "(configured)"

    port = get_api_port()

    summary = (
        f"  AI Chat: {ai_status}\n"
        f"  Telegram: {tg_status}\n"
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
        console.print(f"  {t('wizard.summary_tip', username=tg_username)}")
    console.print()


# ═══════════════════════════════════════════════════════════════
#  CONTROL PANEL — Main interactive menu
# ═══════════════════════════════════════════════════════════════

def _run_control_panel():
    """Interactive control panel menu displayed after initialization."""
    from tubecli.core.ollama_utils import is_ollama_installed, get_recommended_models, install_model
    import subprocess
    import requests
    from tubecli.config import get_api_port, DATA_DIR, BASE_DIR
    from tubecli.i18n import t
    import json
    import os

    port = get_api_port()
    show_api_logs = False  # Default: quiet mode (no INFO spam)

    def _start_api(quiet: bool):
        """Start/restart API server."""
        _kill_server_on_port(port)
        import time
        import sys
        from tubecli.config import get_language
        cur_lang = get_language()
        
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["TUBECLI_PORT"] = str(port)
        env["TUBECLI_CLI_PID"] = str(os.getpid())
        
        # Ensure imports are resolved correctly even if CWD is the repo parent directory
        project_root = str(BASE_DIR)
        env["PYTHONPATH"] = project_root + os.path.pathsep + env.get("PYTHONPATH", "")
        
        python_exe = sys.executable
        if os.name == "nt":
            if quiet:
                cmd = f'"{python_exe}" -m tubecli.main api start --quiet --lang {cur_lang}'
                CREATE_NO_WINDOW = 0x08000000
                subprocess.Popen(
                    cmd, shell=True, creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                    cwd=project_root
                )
            else:
                # Force Windows to open a new interactive visible window with "start"
                cmd = f'start "TubeCLI API Logs" cmd /k ""{python_exe}" -m tubecli.main api start --lang {cur_lang}"'
                subprocess.Popen(cmd, shell=True, env=env, cwd=project_root)
        else:
            cmd = f'"{python_exe}" -m tubecli.main api start{" --quiet" if quiet else ""} --lang {cur_lang}'
            kwargs = {"shell": True, "env": env, "cwd": project_root}
            if quiet:
                kwargs["stdout"] = subprocess.DEVNULL
                kwargs["stderr"] = subprocess.DEVNULL
            subprocess.Popen(cmd, **kwargs)
        time.sleep(2)

    # Initial start — check if already running first
    import requests as _req_init
    server_already_running = False
    try:
        resp = _req_init.get(f"http://localhost:{port}/api/v1/health", timeout=2)
        server_already_running = resp.status_code == 200
    except Exception:
        pass

    if server_already_running:
        console.print(f"  [green]API server đang chạy tại port {port}[/green]")
    else:
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
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]9.[/bold yellow] {t('panel.update'):<42}[bold cyan]║[/bold cyan]")
        console.print(f"[bold cyan]║[/bold cyan]  [bold yellow]0.[/bold yellow] {t('panel.exit'):<42}[bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")

        choice = click.prompt(t("panel.select"), type=str, default="", show_default=False)
        
        if choice == "0":
            console.print(t("panel.exiting"))
            # Kill API server and all related TubeCLI processes
            try:
                _kill_server_on_port(port)
            except Exception:
                pass
            try:
                from tubecli.main import _kill_all_tubecli
                _kill_all_tubecli()
            except Exception:
                # Fallback: taskkill uvicorn directly on Windows
                import subprocess
                if os.name == "nt":
                    subprocess.run(
                        'taskkill /F /IM python.exe /FI "WINDOWTITLE eq TubeCLI*"',
                        shell=True, capture_output=True
                    )
                    # Kill any uvicorn process
                    result = subprocess.run(
                        'wmic process where "commandline like \'%uvicorn%\'" get processid',
                        shell=True, capture_output=True, text=True
                    )
                    for line in (result.stdout or "").splitlines():
                        line = line.strip()
                        if line.isdigit() and int(line) != os.getpid():
                            subprocess.run(f"taskkill /F /PID {line}", shell=True, capture_output=True)
                else:
                    subprocess.run(["pkill", "-f", "uvicorn"], capture_output=True)
            console.print("[green]✓ All TubeCLI processes stopped.[/green]")
            break
            
        elif choice == "1":
            console.print(t("panel.opening_dashboard"))
            try:
                import webbrowser
                import requests as _req
                dashboard_url = f"http://localhost:{port}/dashboard"
                
                # Health check: ensure API server is actually running
                server_alive = False
                try:
                    resp = _req.get(f"http://localhost:{port}/api/v1/health", timeout=2)
                    server_alive = resp.status_code == 200
                except Exception:
                    pass
                
                if not server_alive:
                    console.print("[yellow]  API server chưa sẵn sàng. Đang khởi động lại...[/yellow]")
                    _start_api(quiet=True)
                    # Wait for server to be ready (up to 8 seconds)
                    for _ in range(8):
                        try:
                            resp = _req.get(f"http://localhost:{port}/api/v1/health", timeout=1)
                            if resp.status_code == 200:
                                server_alive = True
                                break
                        except Exception:
                            pass
                        time.sleep(1)
                    
                    if not server_alive:
                        console.print("[red]  API server không thể khởi động. Vui lòng kiểm tra lỗi.[/red]")
                        console.print(f"[yellow]  Thử chạy: tubecli api start --lang vi (trong CMD riêng) để xem log lỗi chi tiết.[/yellow]")
                        time.sleep(3)
                        continue
                    
                    console.print("[green]  API server đã sẵn sàng![/green]")
                
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
            import sys
            env = os.environ.copy()
            env["PYTHONPATH"] = str(BASE_DIR) + os.path.pathsep + env.get("PYTHONPATH", "")
            subprocess.run([sys.executable, "-m", "tubecli.main", "agent", "list"], cwd=str(BASE_DIR), env=env)
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
            import sys
            env = os.environ.copy()
            env["PYTHONPATH"] = str(BASE_DIR) + os.path.pathsep + env.get("PYTHONPATH", "")
            subprocess.run([sys.executable, "-m", "tubecli.main", "browser", "profiles"], cwd=str(BASE_DIR), env=env)
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

        elif choice == "9":
            _run_update_check()

        else:
            console.print(t("panel.invalid_selection"))


# ═══════════════════════════════════════════════════════════════
#  UPDATE CHECKER — Check and apply TubeCLI updates
# ═══════════════════════════════════════════════════════════════

def _run_update_check():
    """Check for TubeCLI updates from git and optionally apply them.
    Smart update: only git pull, only install new deps if config files changed.
    Never runs 'pip install -e .' to avoid breaking the installation.
    """
    import subprocess
    import sys
    from tubecli.i18n import t
    from tubecli.config import BASE_DIR, get_api_port
    from tubecli import __version__

    port = get_api_port()
    project_root = str(BASE_DIR)

    console.print()
    console.print(Panel(
        t("update.checking_body"),
        title=t("update.title"),
        border_style="bright_cyan",
        padding=(1, 2),
    ))

    # Step 1: Get current version info
    current_hash = ""
    current_branch = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            current_hash = r.stdout.strip()
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            current_branch = r.stdout.strip()
    except Exception:
        pass

    console.print(f"  [bold]{t('update.current_version')}[/bold] [cyan]{__version__}[/cyan]")
    console.print(f"  [bold]{t('update.git_branch')}[/bold] [cyan]{current_branch}[/cyan] ({current_hash})")

    # Step 2: Fetch remote
    console.print(f"\n  [dim]{t('update.fetching')}[/dim]")
    try:
        r_fetch = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_root, capture_output=True, text=True, timeout=30,
        )
        if r_fetch.returncode != 0:
            console.print(f"  [red]{t('update.fetch_failed')}: {r_fetch.stderr.strip()}[/red]")
            _pause()
            return
    except FileNotFoundError:
        console.print(f"  [red]Git is not installed or not in PATH.[/red]")
        _pause()
        return
    except subprocess.TimeoutExpired:
        console.print(f"  [red]{t('update.fetch_timeout')}[/red]")
        _pause()
        return

    # Step 3: Compare commits
    remote_branch = f"origin/{current_branch}" if current_branch else "origin/main"

    latest_hash = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", remote_branch],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            latest_hash = r.stdout.strip()
    except Exception:
        pass

    commits_behind = 0
    try:
        r = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..{remote_branch}"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            commits_behind = int(r.stdout.strip())
    except Exception:
        pass

    # Read remote version from __init__.py
    remote_version = ""
    try:
        r = subprocess.run(
            ["git", "show", f"{remote_branch}:tubecli/__init__.py"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("__version__"):
                    remote_version = line.split("=")[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass

    console.print(f"  [bold]{t('update.remote_version')}[/bold] [green]{remote_version or '?'}[/green] ({latest_hash})")

    if commits_behind == 0:
        console.print(f"\n  [bold green]{t('update.up_to_date')}[/bold green]")
        _pause()
        return

    # Step 4: Check which files changed (to determine what needs updating)
    changed_files = []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"HEAD..{remote_branch}"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            changed_files = [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]
    except Exception:
        pass

    # Categorize changes
    deps_changed = any(f in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg") for f in changed_files)
    core_files = [f for f in changed_files if f.startswith("tubecli/") and not f.startswith("tubecli/extensions/")]
    extension_files = [f for f in changed_files if f.startswith("tubecli/extensions/")]
    doc_files = [f for f in changed_files if f.startswith("docs/") or f.endswith(".md")]
    other_files = [f for f in changed_files if f not in core_files + extension_files + doc_files]

    # Show changelog
    console.print(f"\n  [bold yellow]{t('update.commits_behind', count=commits_behind)}[/bold yellow]")

    changelog = []
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", f"HEAD..{remote_branch}", "--format=%h %s"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            changelog = [line.strip() for line in r.stdout.strip().split("\n") if line.strip()]
    except Exception:
        pass

    if changelog:
        console.print(f"\n  [bold cyan]{t('update.changelog')}[/bold cyan]")
        for entry in changelog[:15]:
            parts = entry.split(" ", 1)
            hash_str = parts[0] if len(parts) > 0 else ""
            msg = parts[1] if len(parts) > 1 else entry
            console.print(f"    [dim]{hash_str}[/dim] {msg}")
        if len(changelog) > 15:
            console.print(f"    [dim]... {t('update.and_more', count=len(changelog) - 15)}[/dim]")

    # Show what will be updated
    console.print(f"\n  [bold cyan]{t('update.changes_summary')}[/bold cyan]")
    if core_files:
        console.print(f"    [green]🔧 {t('update.cat_core')}:[/green] {len(core_files)} files")
    if extension_files:
        console.print(f"    [blue]{t('update.cat_extensions')}:[/blue] {len(extension_files)} files")
    if doc_files:
        console.print(f"    [dim]📄 {t('update.cat_docs')}:[/dim] {len(doc_files)} files")
    if deps_changed:
        console.print(f"    [yellow]{t('update.cat_deps')}[/yellow]")
    else:
        console.print(f"    [green]{t('update.cat_deps_no_change')}[/green]")
    if other_files:
        console.print(f"    [dim]{t('update.cat_other')}:[/dim] {len(other_files)} files")

    # Step 5: Confirm update
    console.print()
    console.print(f"  [bold yellow]1.[/bold yellow] {t('update.apply_now')}")
    console.print(f"  [bold yellow]0.[/bold yellow] {t('update.skip')}\n")

    choice = click.prompt(t("panel.select"), type=str, default="1")

    if choice != "1":
        console.print(f"  [yellow]{t('update.skipped')}[/yellow]")
        _pause()
        return

    # Step 6: Apply update — only git pull, no pip install -e .
    console.print(f"\n  [cyan]{t('update.pulling')}[/cyan]")
    
    bat_path = os.path.join(project_root, "TubeCLI.bat")
    had_bat = os.path.exists(bat_path)
    if had_bat:
        try:
            os.remove(bat_path)
        except Exception:
            pass

    try:
        r_pull = subprocess.run(
            ["git", "pull", "origin", current_branch or "main"],
            cwd=project_root, capture_output=True, text=True, timeout=60,
        )
        if r_pull.returncode != 0:
            # Recreate the deleted bat file if pull failed so the user is not left without it
            if had_bat and not os.path.exists(bat_path):
                # Let a later step handle writing it, or we can just leave it to retry
                pass
            console.print(f"  [red]Git pull failed: {r_pull.stderr.strip()}[/red]")
            _pause()
            return
        console.print(f"  [green]{t('update.pull_success')}[/green]")
    except Exception as e:
        console.print(f"  [red]Git pull error: {e}[/red]")
        _pause()
        return

    # Step 7: Smart dependency check — only if pyproject.toml or requirements.txt changed
    if deps_changed:
        console.print(f"  [cyan]{t('update.deps_changed_detected')}[/cyan]")
        # Read new requirements and compare with installed packages
        _install_missing_deps(project_root, sys.executable)
    else:
        console.print(f"  [green]{t('update.deps_skip')}[/green]")

    # Read new version
    new_version = ""
    try:
        init_file = os.path.join(project_root, "tubecli", "__init__.py")
        with open(init_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    new_version = line.split("=")[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass

    console.print()
    console.print(Panel(
        f"  {t('update.old_ver')}: [dim]{__version__}[/dim]\n"
        f"  {t('update.new_ver')}: [bold green]{new_version or 'updated'}[/bold green]\n\n"
        f"  {t('update.auto_restart')}",
        title=f"{t('update.complete')}",
        border_style="bright_green",
        padding=(1, 2),
    ))

    # Recreate/update TubeCLI.bat to ensure they get the single-instance safety fixes
    if had_bat or os.path.exists(bat_path):
        try:
            bat_content = f"""@echo off
setlocal enabledelayedexpansion

REM === Check if TubeCLI is already running (by checking API port) ===
set ALREADY_RUNNING=0
netstat -ano 2>nul | findstr ":{port}" | findstr "LISTENING" >nul 2>nul
if !ERRORLEVEL! EQU 0 set ALREADY_RUNNING=1

if %ALREADY_RUNNING% EQU 1 (
    cls
    echo.
    echo  ==================================================
    echo             TubeCLI - Already Running
    echo  ==================================================
    echo.
    echo    1. Open Dashboard
    echo    2. Restart TubeCLI
    echo    3. Shut down TubeCLI
    echo    0. Exit
    echo.
    echo  ==================================================
    echo.
    set /p opt="  Select an option: "
    
    if "!opt!"=="" set opt=1
    
    if "!opt!"=="1" (
        start http://localhost:{port}/dashboard
        exit
    )
    if "!opt!"=="2" (
        echo.
        echo   Restarting TubeCLI...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":{port}" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        timeout /t 2 /nobreak >nul
        goto :START_CLI
    )
    if "!opt!"=="3" (
        echo.
        echo   Shutting down TubeCLI...
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":{port}" ^| findstr "LISTENING"') do (
            taskkill /F /PID %%a >nul 2>nul
        )
        echo   Done.
        timeout /t 1 /nobreak >nul
        exit
    )
    exit
)

:START_CLI
title TubeCLI - AI Agent System
cd /d "{project_root}"

where tubecli >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    tubecli init
) else (
    python -m tubecli.main init
)
pause
"""
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
        except Exception:
            pass

    # Auto-restart TubeCLI
    import time

    # Kill old API server so it restarts with new code
    _kill_server_on_port(port)
    
    # Save the .restarted flag file so the next process knows it is a restart
    restart_flag = os.path.join(project_root, ".restarted")
    try:
        with open(restart_flag, "w") as f:
            f.write("1")
    except Exception:
        pass

    for i in range(3, 0, -1):
        console.print(f"  [cyan]⏳ Restarting in {i}...[/cyan]", end="\r")
        time.sleep(1)
    console.print()
    os.environ["TUBECLI_RESTARTED"] = "1"
    os.environ["PYTHONPATH"] = project_root + os.path.pathsep + os.environ.get("PYTHONPATH", "")
    try:
        os.chdir(project_root)
    except Exception:
        pass

    from tubecli.config import get_language
    cur_lang = get_language()
    args = [sys.executable, "-m", "tubecli.main", "init", "--lang", cur_lang]

    if os.name == "nt":
        # On Windows, os.execve terminates the parent, causing CMD to regain stdin control.
        # subprocess.run can inherit modified console modes (raw/no-echo) from rich/click.
        # os.system runs via cmd.exe, resetting the console mode and ensuring stdin works perfectly.
        cmd_str = f'"{sys.executable}" -m tubecli.main init --lang {cur_lang}'
        os.system(cmd_str)
        sys.exit(0)
    else:
        os.execve(sys.executable, args, os.environ)


def _install_missing_deps(project_root: str, python_exe: str):
    """Check pyproject.toml and requirements.txt for NEW dependencies
    and install only the missing ones. Never runs 'pip install -e .'."""
    import subprocess
    import re
    from tubecli.i18n import t

    # Collect required packages from pyproject.toml and requirements.txt
    required_packages = set()

    # From pyproject.toml
    pyproject_path = os.path.join(project_root, "pyproject.toml")
    if os.path.exists(pyproject_path):
        try:
            with open(pyproject_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Simple TOML parser for dependencies array
            in_deps = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("dependencies"):
                    in_deps = True
                    continue
                if in_deps:
                    if stripped == "]":
                        break
                    # Extract package name from lines like '"click>=8.0",'
                    match = re.match(r'^\s*"([a-zA-Z0-9_-]+)', stripped)
                    if match:
                        required_packages.add(match.group(1).lower().replace("-", "_"))
        except Exception:
            pass

    # From requirements.txt
    req_path = os.path.join(project_root, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pkg = re.split(r"[>=<!\[\];]", line)[0].strip().lower().replace("-", "_")
                        if pkg:
                            required_packages.add(pkg)
        except Exception:
            pass

    if not required_packages:
        console.print(f"  [dim]{t('update.deps_skip')}[/dim]")
        return

    # Get currently installed packages
    installed = set()
    try:
        r = subprocess.run(
            [python_exe, "-m", "pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines()[2:]:  # Skip header
                parts = line.split()
                if parts:
                    installed.add(parts[0].lower().replace("-", "_"))
    except Exception:
        pass

    # Find missing packages
    missing = required_packages - installed
    if not missing:
        console.print(f"  [green]{t('update.deps_all_present')}[/green]")
        return

    # Install only the missing packages
    console.print(f"  [cyan]{t('update.deps_installing_new', packages=', '.join(sorted(missing)))}[/cyan]")
    try:
        subprocess.run(
            [python_exe, "-m", "pip", "install", *sorted(missing), "--quiet"],
            capture_output=True, timeout=120,
        )
        console.print(f"  [green]{t('update.deps_installed')}[/green]")
    except Exception as e:
        console.print(f"  [yellow]{t('update.deps_warning')}: {e}[/yellow]")


def _pause():
    """Wait for user to press Enter before returning to menu."""
    from tubecli.i18n import t
    click.prompt(t("update.press_enter"), default="", show_default=False, prompt_suffix="")

