"""
WebUI Plugin class
"""
from tubecli.core.plugin_manager import Plugin


class WebUIPlugin(Plugin):
    name = "webui"
    version = "0.1.0"
    description = "Web dashboard for managing agents, browser, workflows, skills & market"
    author = "TubeCreate"

    def get_commands(self):
        from tubecli.plugins.webui.commands import webui_group
        return webui_group

    def get_routes(self):
        from tubecli.plugins.webui.routes import router
        return router
