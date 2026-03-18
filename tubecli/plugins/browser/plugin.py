"""
Browser Plugin class — registers CLI commands and API routes.
"""
from tubecli.core.plugin_manager import Plugin


class BrowserPlugin(Plugin):
    name = "browser"
    version = "0.1.0"
    description = "Browser profile management & automation (profiles, proxy, cookies)"
    author = "TubeCreate"

    def on_enable(self):
        from tubecli.plugins.browser.profile_manager import ensure_profiles_dir
        ensure_profiles_dir()

    def get_commands(self):
        from tubecli.plugins.browser.commands import browser_group
        return browser_group

    def get_routes(self):
        from tubecli.plugins.browser.routes import router
        return router
