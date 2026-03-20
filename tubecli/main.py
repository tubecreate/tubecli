"""
TubeCLI — Main CLI Entry Point
All commands are organized into groups: agent, skill, workflow, api, init, extension.
Extension system auto-discovers and registers enabled extension commands.
"""
import click
from tubecli import __version__


@click.group()
@click.version_option(version=__version__, prog_name="tubecli")
def cli():
    """🚀 TubeCLI — Open Source AI Agent CLI System

    Manage agents, skills, and workflows from the command line.
    AI agents can read .agents/skills/SKILL.md to self-operate.
    """
    # Auto-load language on every CLI invocation
    from tubecli.config import get_language
    from tubecli.i18n import load_language
    load_language(get_language())


# ── Core Commands ─────────────────────────────────────────
from tubecli.cli.init_cmd import init_cmd
from tubecli.cli.agent_cmd import agent_cmd
from tubecli.cli.skill_cmd import skill_cmd
from tubecli.cli.workflow_cmd import workflow_cmd
from tubecli.cli.api_cmd import api_cmd
from tubecli.cli.extension_cmd import extension_group

cli.add_command(init_cmd)
cli.add_command(agent_cmd)
cli.add_command(skill_cmd)
cli.add_command(workflow_cmd)
cli.add_command(api_cmd)
cli.add_command(extension_group)

# ── Extension Commands (auto-discover enabled extensions) ───────
try:
    from tubecli.core.extension_manager import extension_manager
    extension_manager.discover_extensions()   # system + external extensions
    extension_manager.register_cli_commands(cli)
except Exception:
    pass  # Graceful fallback if extensions fail


if __name__ == "__main__":
    cli()
