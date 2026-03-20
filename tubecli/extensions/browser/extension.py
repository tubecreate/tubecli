"""
Browser Extension class — registers CLI commands and API routes.
"""
from tubecli.core.extension_manager import Extension


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
            try:
                from rich.console import Console
                console = Console()
                console.print("\n[cyan]📦 Installing browser automation dependencies (Playwright)...[/cyan]")
                console.print("[dim]This may take a few minutes as it downloads Chromium binaries.[/dim]")
            except ImportError:
                print("\n📦 Installing browser automation dependencies (Playwright)...")
                print("This may take a few minutes as it downloads Chromium binaries.")
                
            try:
                # Run npm install, which automatically runs postinstall scripts to download browsers
                subprocess.run(["npm", "install"], cwd=ext_dir, check=True, shell=True)
                try:
                    console.print("[green]✅ Browser dependencies installed successfully.[/green]\n")
                except NameError:
                    print("✅ Browser dependencies installed successfully.\n")
            except subprocess.CalledProcessError as e:
                try:
                    console.print(f"[red]❌ Failed to install browser dependencies: {e}[/red]\n")
                except NameError:
                    print(f"❌ Failed to install browser dependencies: {e}\n")
            except FileNotFoundError:
                try:
                    console.print("[red]❌ 'npm' command not found. Please install Node.js (https://nodejs.org).[/red]\n")
                except NameError:
                    print("❌ 'npm' command not found. Please install Node.js (https://nodejs.org).\n")

    def get_commands(self):
        from .commands import browser_group
        return browser_group

    def get_routes(self):
        from .routes import router
        return router
