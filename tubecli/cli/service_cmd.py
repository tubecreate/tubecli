"""tubecli service — keep the server running after you close the terminal.

`tubecli api start` runs uvicorn in the foreground; it prints "Press Ctrl+C to
stop" and means it. Over SSH that is fatal in a way that looks like a bug: you
start the server, close the terminal, and the dashboard is gone, because closing
the session sends SIGHUP to everything in it. Backgrounding with `&` only moves
the problem — the process still dies with the session, and it still does not come
back after a reboot.

systemd is the thing on a Linux server whose job this is. This command writes the
unit, so nobody has to know that.

On sudo: shardx_runtime deliberately refuses to call sudo because it runs inside
the server process, where a password prompt would hang forever with nobody to see
it. That reasoning does not apply here — the user typed this command into a
terminal they are sitting at, so prompting is exactly right.
"""
import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

SERVICE_NAME = "tubecli"
UNIT_PATH = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"


def _systemd_available() -> bool:
    # /run/systemd/system, not shutil.which("systemctl"): the binary exists on
    # WSL distros and in container images where systemd is NOT PID 1, and there
    # every systemctl call fails with "System has not been booted with systemd".
    # The directory only exists under a running systemd — it is the canonical
    # check (sd_booted() does the same).
    return sys.platform.startswith("linux") and os.path.isdir("/run/systemd/system")


def _target_user() -> str:
    """Who the server should run as — the human, not root.

    Under `sudo tubecli service install`, SUDO_USER holds the original account.
    Running the server as root would put the data directory in /root, where the
    same user's earlier `tubecli init` data would be invisible.
    """
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"


def _launcher() -> str:
    """Absolute path to the tubecli entry point, for ExecStart.

    systemd does not read a login shell, so ~/.local/bin is not on PATH and a
    bare `tubecli` fails with status=203/EXEC. The console script sits next to
    the interpreter that is running us; falling back to `python -m` covers an
    install where it is missing.
    """
    exe = Path(sys.executable)
    candidate = exe.parent / "tubecli"
    if candidate.exists():
        return str(candidate)
    return f"{exe} -m tubecli.main"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _unit_text() -> str:
    # PYTHONUNBUFFERED matters more than it looks. Python block-buffers stdout
    # when it is a pipe rather than a terminal, and under systemd it is a pipe to
    # the journal — so every print() the scheduler makes (which is the only place
    # a failed browser launch is reported) would sit in a buffer for minutes, or
    # be lost entirely if the process was killed. Unbuffered puts them in
    # `journalctl -u tubecli -f` as they happen.
    return f"""[Unit]
Description=TubeCLI API Server
Documentation=https://github.com/tubecreate/tubecli
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={_target_user()}
WorkingDirectory={_project_root()}
Environment=PYTHONUNBUFFERED=1
ExecStart={_launcher()} api start --quiet
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def _run(cmd: list, check: bool = True) -> int:
    """Run a privileged command, adding sudo only when we are not already root."""
    if os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        raise click.ClickException(f"Lệnh thất bại: {' '.join(cmd)}")
    return result.returncode


def _require_systemd():
    if not _systemd_available():
        raise click.ClickException(
            "Lệnh này cần systemd (Linux). Trên Windows dùng Task Scheduler, "
            "trên macOS dùng launchd."
        )


@click.group("service")
def service_cmd():
    """Chạy máy chủ như một dịch vụ nền (systemd).

    Chạy KHÔNG cần sudo — lệnh tự xin quyền ở đúng bước cần. Gõ
    `sudo tubecli service install` sẽ báo "command not found", vì sudo đặt lại
    PATH và bỏ mất ~/.local/bin, nơi trình khởi chạy được cài.
    """
    pass


@service_cmd.command("install")
@click.option("--show-only", is_flag=True, default=False,
              help="In ra nội dung unit rồi dừng, không ghi và không cần sudo.")
def install(show_only):
    """Cài dịch vụ, bật chạy cùng máy, và khởi động ngay."""
    # --show-only writes nothing and needs no privileges, so it stays available
    # everywhere — including a Windows workstation, where reading the unit you are
    # about to deploy is the only way to check it without a Linux box.
    unit = _unit_text()
    if show_only:
        # click.echo, not console.print: rich would read "[Unit]" and "[Service]"
        # as markup tags and could mangle the one thing this flag exists to show,
        # and its line wrapping would corrupt a long ExecStart on copy-paste.
        console.print(f"\n[dim]# {UNIT_PATH.as_posix()}[/dim]")
        click.echo(unit)
        return

    _require_systemd()

    console.print(f"\n[cyan]Cài dịch vụ {SERVICE_NAME}[/cyan]")
    console.print(f"   Chạy dưới người dùng: [green]{_target_user()}[/green]")
    console.print(f"   Thư mục: [green]{_project_root()}[/green]")

    # A foreground server already holding the port would make the unit fail on
    # start, and the reason (address in use) is buried in the journal.
    try:
        from tubecli.config import get_api_port
        import socket
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", get_api_port())) == 0:
                console.print("\n[yellow]Cổng đang có tiến trình khác chiếm.[/yellow]")
                console.print("[dim]Dừng nó trước: tubecli api stop[/dim]")
    except Exception:
        pass

    if not install_service():
        raise click.ClickException(
            f"Dịch vụ chưa chạy được. Xem lỗi:  journalctl -u {SERVICE_NAME} -n 50")

    console.print(f"\n[green]Xong.[/green] Máy chủ chạy nền, và tự bật lại sau khi khởi động lại máy.")
    console.print(f"   Xem log:      [cyan]journalctl -u {SERVICE_NAME} -f[/cyan]")
    console.print(f"   Xem trạng thái:[cyan] tubecli service status[/cyan]")
    console.print(f"   Gỡ ra:        [cyan]tubecli service uninstall[/cyan]\n")


def install_service(quiet: bool = False) -> bool:
    """Write the unit, enable it, start it, and WAIT until it answers.

    Extracted from the `install` command so the headless setup finisher can call
    it. Returns False instead of raising — the finisher must be able to continue
    to its summary screen (which tells the user how to recover) no matter what
    failed here.

    Success is earned, not assumed: this used to print "Xong." right after
    `systemctl restart`, which returns 0 even when the unit then crash-loops on
    a taken port. Now it polls /api/v1/health for up to 30 seconds — the control
    panel's own startup poll is 20s with the comment "extensions load slowly",
    and a first boot on a 2 GB VPS is slower still.
    """
    try:
        unit = _unit_text()
        tmp = Path.home() / f".{SERVICE_NAME}.service.tmp"
        tmp.write_text(unit, encoding="utf-8")
        try:
            _run(["cp", str(tmp), str(UNIT_PATH)])
        finally:
            tmp.unlink(missing_ok=True)

        _run(["systemctl", "daemon-reload"])
        _run(["systemctl", "enable", SERVICE_NAME])
        _run(["systemctl", "restart", SERVICE_NAME])
    except Exception as e:
        # Broad on purpose: the contract is "returns False instead of raising",
        # and the caller (the headless finisher) must reach its summary screen
        # no matter what went wrong here — even an os.geteuid() AttributeError
        # on a platform this never should have been called on.
        if not quiet:
            console.print(f"[yellow]{e}[/yellow]")
        return False

    from tubecli.cli.server_summary import health_ok
    from tubecli.config import get_api_port
    import time
    try:
        port = get_api_port()
    except Exception:
        port = 5295
    deadline = time.time() + 30
    while time.time() < deadline:
        if health_ok(port):
            return True
        time.sleep(2)
    # The unit may still be loading extensions; report state honestly.
    try:
        r = subprocess.run(["systemctl", "is-active", SERVICE_NAME],
                           capture_output=True, text=True, timeout=5)
        return (r.stdout or "").strip() == "active"
    except Exception:
        return False


@service_cmd.command("uninstall")
def uninstall():
    """Gỡ dịch vụ (không xoá dữ liệu)."""
    _require_systemd()
    if not UNIT_PATH.exists():
        console.print("[yellow]Chưa cài dịch vụ nào.[/yellow]")
        return
    _run(["systemctl", "disable", "--now", SERVICE_NAME], check=False)
    _run(["rm", "-f", str(UNIT_PATH)])
    _run(["systemctl", "daemon-reload"])
    console.print("[green]Đã gỡ dịch vụ.[/green] Dữ liệu giữ nguyên.")


@service_cmd.command("status")
def status():
    """Xem dịch vụ đang chạy thế nào."""
    _require_systemd()
    if not UNIT_PATH.exists():
        console.print("[yellow]Chưa cài dịch vụ.[/yellow] Chạy: [cyan]tubecli service install[/cyan]")
        return
    subprocess.run(["systemctl", "status", SERVICE_NAME, "--no-pager"])


@service_cmd.command("logs")
@click.option("--lines", "-n", default=50, type=int, help="Số dòng gần nhất.")
@click.option("--follow", "-f", is_flag=True, default=False, help="Theo dõi liên tục.")
def logs(lines, follow):
    """Xem log máy chủ."""
    _require_systemd()
    cmd = ["journalctl", "-u", SERVICE_NAME, "-n", str(lines), "--no-pager"]
    if follow:
        cmd = ["journalctl", "-u", SERVICE_NAME, "-f"]
    subprocess.run(cmd)
