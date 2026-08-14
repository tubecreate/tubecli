"""CapCut TTS — CLI commands (tubecli capcut-tts …)."""
import sys

import click


@click.group("capcut-tts")
def capcut_tts_group():
    """Quản lý CapCut TTS: tài khoản, trạng thái server."""
    pass


@capcut_tts_group.command("accounts")
def accounts_cmd():
    """Liệt kê tài khoản CapCut đã lưu (không hiện mật khẩu)."""
    from tubecli.extensions.capcut_tts.account_store import account_store
    rows = account_store.list_masked()
    if not rows:
        click.echo("Chưa có tài khoản CapCut nào. Thêm bằng: tubecli capcut-tts add-account EMAIL")
        return
    for a in rows:
        state = "on " if a["enabled"] else "off"
        err = f"  ⚠ {a['last_error']}" if a.get("last_error") else ""
        click.echo(f"[{state}] {a['email']:32s} {a.get('label',''):12s}{err}")


@capcut_tts_group.command("add-account")
@click.argument("email")
@click.option("--password", "-p", prompt=True, hide_input=True, help="Mật khẩu CapCut")
@click.option("--label", "-l", default="", help="Nhãn tuỳ chọn")
def add_account_cmd(email, password, label):
    """Thêm/cập nhật một tài khoản CapCut."""
    from tubecli.extensions.capcut_tts.account_store import account_store
    res = account_store.add(email, password, label)
    click.echo(res["message"])
    if res["status"] == "error":
        sys.exit(1)


@capcut_tts_group.command("remove-account")
@click.argument("email")
def remove_account_cmd(email):
    """Xoá một tài khoản CapCut."""
    from tubecli.extensions.capcut_tts.account_store import account_store
    res = account_store.remove(email)
    click.echo(res["message"])
    if res["status"] == "error":
        sys.exit(1)


@capcut_tts_group.command("status")
def status_cmd():
    """Trạng thái server CapCut nền."""
    from tubecli.extensions.capcut_tts.account_store import account_store
    from tubecli.extensions.capcut_tts.process_manager import node_manager
    click.echo(f"Đã build : {node_manager.is_built()}")
    click.echo(f"Đang chạy: {node_manager.is_running()} (cổng {node_manager.port})")
    click.echo(f"Tài khoản bật: {account_store.count_enabled()}")
