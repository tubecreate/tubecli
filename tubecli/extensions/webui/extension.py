"""
WebUI Extension class
"""
from tubecli.core.extension_manager import Extension


class WebUIExtension(Extension):
    name = "webui"
    version = "0.1.0"
    description = "Web dashboard for managing agents, browser, workflows, skills & market"
    author = "TubeCreate"
    default_port = 3000

    def get_commands(self):
        from tubecli.extensions.webui.commands import webui_group
        return webui_group

    def get_routes(self):
        from tubecli.extensions.webui.routes import router
        return router
