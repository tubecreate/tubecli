"""tubecli cloud-key — the key TubeCLI Cloud signs in with, managed from the machine's own shell.

TubeCLI Connect runs `tubecli cloud-key --new` when it pairs the machine, and hands the key to the cloud
together with the pairing code. That replaces typing the dashboard password into the pairing window: the cloud
no longer holds that password, and changing or forgetting it no longer cuts the cloud off (core/auth.py).

Running this needs the same rights as `tubecli password`: a shell on the machine, as the user who owns the
install. There is deliberately no HTTP route that creates a key.
"""
import click


@click.command("cloud-key")
@click.option("--new", "make_new", is_flag=True, default=False,
              help="Create a new cloud key (replaces the current one) and print it. It is shown only once.")
@click.option("--revoke", is_flag=True, default=False,
              help="Remove the cloud key. TubeCLI Cloud can no longer sign in until the machine is paired again.")
@click.option("--status", "show_status", is_flag=True, default=False,
              help="Report whether a cloud key is set, without changing it.")
def cloud_key_cmd(make_new, revoke, show_status):
    """Create, check or revoke the key TubeCLI Cloud signs in with."""
    from tubecli.core import auth

    if sum(bool(x) for x in (make_new, revoke, show_status)) != 1:
        raise click.UsageError("Choose one of --new, --revoke, --status.")

    if show_status:
        info = auth.cloud_key_info()
        if info["set"]:
            import datetime
            when = datetime.datetime.fromtimestamp(info["created_at"]).strftime("%Y-%m-%d %H:%M") \
                if info["created_at"] else "?"
            click.echo(f"cloud key: set (created {when})")
        else:
            click.echo("cloud key: not set")
        return

    if revoke:
        click.echo("cloud key: revoked" if auth.revoke_cloud_key() else "cloud key: not set")
        return

    # Plain click.echo on its own line: TubeCLI Connect reads the key from stdout, and rich markup or a
    # wrapped line would corrupt it.
    click.echo(auth.mint_cloud_key())
