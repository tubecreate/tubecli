"""tubecli password — set the dashboard password from the server's own shell.

Without this, the only way past the default-password refusal was to open an SSH
tunnel from another machine and use the browser — which is absurd advice for
someone who is already sitting in a terminal on that server. This is the same
operation, one line, where they already are.
"""
import click
from rich.console import Console

console = Console()


@click.command("password")
@click.option("--new", "new_password", default=None,
              help="Set it non-interactively. Avoid on a shared machine: it lands in your shell history.")
@click.option("--show-status", is_flag=True, default=False,
              help="Report whether a password is set, without changing it.")
def password_cmd(new_password, show_status):
    """Set the dashboard password."""
    from tubecli.core import auth

    auth.ensure_initialised()

    if show_status:
        if auth.is_default_password():
            console.print("[yellow]Đang dùng mật khẩu mặc định.[/yellow] "
                          "Truy cập từ xa bị chặn cho tới khi đổi.")
        else:
            console.print("[green]Đã đặt mật khẩu riêng.[/green] Truy cập từ xa đã mở.")
        return

    if auth.is_default_password():
        console.print("\n[yellow]Máy chủ đang dùng mật khẩu mặc định (123456).[/yellow]")
        console.print("[dim]Truy cập từ xa bị chặn cho tới khi bạn đổi nó.[/dim]\n")

    if new_password is None:
        new_password = click.prompt("Mật khẩu mới", hide_input=True,
                                    confirmation_prompt="Nhập lại mật khẩu")

    if new_password == auth.DEFAULT_PASSWORD:
        console.print("[red]Không thể đặt lại đúng mật khẩu mặc định.[/red]")
        raise SystemExit(1)

    try:
        auth.set_password(new_password)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    console.print("\n[green]Đã đổi mật khẩu.[/green]")
    console.print("[dim]Mọi phiên đăng nhập cũ đã bị huỷ. Giờ có thể vào từ xa.[/dim]")

    # Print the address the user will actually type, which is not necessarily
    # the one the server binds — a server on 0.0.0.0 is reached at its public
    # address, and printing "0.0.0.0:5295" would be useless.
    try:
        import socket

        from tubecli.config import get_api_port

        port = get_api_port()
        host = socket.gethostbyname(socket.gethostname())
        console.print(f"\n  http://{host}:{port}/dashboard")
        console.print("[dim]  (nếu máy có IP công khai khác, dùng IP đó)[/dim]\n")
    except Exception:
        pass
