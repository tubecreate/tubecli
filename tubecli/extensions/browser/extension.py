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
        from tubecli.extensions.browser.profile_manager import ensure_profiles_dir
        ensure_profiles_dir()

    def get_commands(self):
        from tubecli.extensions.browser.commands import browser_group
        return browser_group

    def get_routes(self):
        from tubecli.extensions.browser.routes import router
        return router
