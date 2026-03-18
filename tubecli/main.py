"""
TubeCLI — Main CLI Entry Point
All commands are organized into groups: agent, skill, workflow, api, init.
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
    pass


# Register commands
from tubecli.cli.init_cmd import init_cmd
from tubecli.cli.agent_cmd import agent_cmd
from tubecli.cli.skill_cmd import skill_cmd
from tubecli.cli.workflow_cmd import workflow_cmd
from tubecli.cli.api_cmd import api_cmd

cli.add_command(init_cmd)
cli.add_command(agent_cmd)
cli.add_command(skill_cmd)
cli.add_command(workflow_cmd)
cli.add_command(api_cmd)


if __name__ == "__main__":
    cli()
