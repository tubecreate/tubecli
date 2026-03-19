"""
Market Extension class
"""
from tubecli.core.extension_manager import Extension


class MarketExtension(Extension):
    name = "market"
    version = "0.1.0"
    description = "Browse and install community skills from the marketplace"
    author = "TubeCreate"

    def get_commands(self):
        from tubecli.extensions.market.commands import market_group
        return market_group

    def get_routes(self):
        from tubecli.extensions.market.routes import router
        return router
