"""
Browser Extension class — registers CLI commands, API routes, and the
`profiles` group kind with its four agent actions.
"""
from tubecli.core.extension_manager import Extension

# The shape of a shared browser profile and the browser_* handlers live in
# group_actions.py — this class only publishes them. Guarded because the
# extension must still load on a core whose group_context predates the kind
# registry (hot-patched servers), where there is simply nothing to publish.
try:
    from .group_actions import GROUP_KINDS, TELEGRAM_ACTIONS
except Exception as _e:  # pragma: no cover
    import logging
    logging.getLogger("BrowserExtension").warning(f"group actions unavailable: {_e}")
    GROUP_KINDS, TELEGRAM_ACTIONS = [], {}


class BrowserExtension(Extension):
    name = "browser"
    version = "0.1.0"
    description = "Browser profile management & automation (profiles, proxy, cookies)"
    author = "TubeCreate"

    def on_enable(self):
        from .profile_manager import ensure_profiles_dir
        import os
        import subprocess
        
        ensure_profiles_dir()
        
        # Ensure Playwright dependencies are installed
        ext_dir = os.path.dirname(__file__)
        node_modules = os.path.join(ext_dir, "node_modules")
        
        if not os.path.exists(node_modules):
            import shutil

            def say(msg):
                try:
                    from rich.console import Console
                    Console().print(msg)
                except Exception:
                    import re as _re
                    print(_re.sub(r"\[/?[a-z ]+\]", "", msg))

            # Check for npm before running it. shell=True used to hide this: on
            # POSIX a missing command makes /bin/sh exit 127, which Python reports
            # as CalledProcessError, so the FileNotFoundError branch that explained
            # how to fix it was dead code and the user saw a raw exit status.
            npm = shutil.which("npm")
            if not npm:
                say("\n[yellow]Browser automation is unavailable: Node.js (npm) is not installed.[/yellow]")
                say("[dim]Everything else works. To enable it, install Node.js from "
                    "https://nodejs.org (or your package manager), then run "
                    "`tubecli extension enable browser`.[/dim]\n")
                return

            say("\n[cyan]📦 Installing browser automation dependencies (Playwright)...[/cyan]")
            say("[dim]This may take a few minutes as it downloads Chromium binaries.[/dim]")
            try:
                # shell=False. With shell=True and a list, POSIX passes only the
                # first element as the command and binds the rest to $0, $1... —
                # so this ran a bare `npm` with no arguments and never installed
                # anything on Linux or macOS.
                subprocess.run([npm, "install"], cwd=ext_dir, check=True)
                say("[green]✅ Browser dependencies installed successfully.[/green]\n")
            except subprocess.CalledProcessError as e:
                say(f"[yellow]Could not install browser dependencies (npm exited "
                    f"{e.returncode}).[/yellow]")
                say("[dim]Everything else works. Retry later with "
                    "`tubecli extension enable browser`.[/dim]\n")

    def get_commands(self):
        from .commands import browser_group
        return browser_group

    def get_routes(self):
        from .routes import router
        return router

    def get_group_kinds(self):
        return list(GROUP_KINDS)

    def get_telegram_actions(self):
        # Disabling this extension withdraws both the kind and these actions:
        # the group's profiles then stop existing for the agent, which is the
        # intended off switch.
        return dict(TELEGRAM_ACTIONS)
