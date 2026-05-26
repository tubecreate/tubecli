"""
TubeCLI — Main CLI Entry Point
All commands are organized into groups: agent, skill, workflow, api, init, extension.
Extension system auto-discovers and registers enabled extension commands.
"""
import os
import sys

# ── Fix Windows Console Encoding ──────────────────────────────────
# Ensures Vietnamese characters, box-drawing Unicode (╔═╗║), and emoji
# display correctly in ANY CMD window, even freshly opened ones.
if os.name == "nt":
    try:
        os.system("chcp 65001 >nul 2>&1")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
from tubecli import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="tubecli")
@click.option("--shutdown", "--kill", "do_kill", is_flag=True, default=False,
              help="Shutdown all running TubeCLI processes (API server, background tasks)")
@click.pass_context
def cli(ctx, do_kill):
    """TubeCLI — Open Source AI Agent CLI System

    Manage agents, skills, and workflows from the command line.
    AI agents can read .agents/skills/SKILL.md to self-operate.
    """
    # Auto-load language on every CLI invocation
    from tubecli.config import get_language
    from tubecli.i18n import load_language
    load_language(get_language())

    # Handle --shutdown flag
    if do_kill:
        _kill_all_tubecli()
        ctx.exit(0)
        return

    # If no subcommand given → auto-run init with last saved language
    if ctx.invoked_subcommand is None:
        ctx.invoke(init_cmd, lang=get_language(), port=None)


def _kill_all_tubecli():
    """Kill all running TubeCLI-related processes."""
    import os
    import signal

    try:
        import psutil
    except ImportError:
        # Fallback without psutil
        _kill_all_fallback()
        return

    current_pid = os.getpid()
    killed = []
    keywords = ["tubecli", "uvicorn"]

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.pid == current_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            name = (proc.info.get("name") or "").lower()

            is_tubecli = any(kw in cmdline for kw in keywords) or "tubecli" in name

            if is_tubecli:
                proc.terminate()
                killed.append(f"PID {proc.pid} ({name})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if killed:
        click.echo(f"Shutdown {len(killed)} TubeCLI process(es):")
        for p in killed:
            click.echo(f"   • {p}")
    else:
        click.echo("No running TubeCLI processes found.")


def _kill_all_fallback():
    """Fallback kill using OS commands when psutil is not available."""
    import subprocess
    import os

    killed_count = 0

    if os.name == "nt":
        # Windows: kill by image name patterns
        for pattern in ["tubecli", "uvicorn"]:
            try:
                # Find PIDs matching the pattern
                result = subprocess.run(
                    f'wmic process where "commandline like \'%{pattern}%\'" get processid',
                    shell=True, capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.isdigit() and int(line) != os.getpid():
                        subprocess.run(f"taskkill /F /PID {line}", shell=True,
                                       capture_output=True, timeout=5)
                        killed_count += 1
            except Exception:
                continue
    else:
        # Unix: use pkill
        for pattern in ["tubecli", "uvicorn"]:
            try:
                subprocess.run(["pkill", "-f", pattern], capture_output=True, timeout=5)
                killed_count += 1
            except Exception:
                continue

    if killed_count > 0:
        click.echo(f"Shutdown TubeCLI processes.")
    else:
        click.echo("No running TubeCLI processes found.")


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
