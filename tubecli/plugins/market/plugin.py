"""
Market Plugin class
"""
from tubecli.core.plugin_manager import Plugin


class MarketPlugin(Plugin):
    name = "market"
    version = "0.1.0"
    description = "Browse and install community skills from the marketplace"
    author = "TubeCreate"

    def get_commands(self):
        from tubecli.plugins.market.commands import market_group
        return market_group

    def get_routes(self):
        from tubecli.plugins.market.routes import router
        return router
