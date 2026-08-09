"""The server-ready screen, and `tubecli info` to see it again.

One block of text answers everything a person who just installed on a VPS needs:
the URL to open, the password situation, the firewall step nobody can do for
them, and the three commands they will actually use. It used to exist only as
terminal scrollback at the end of install.sh — and the commonest way in is a
cloud provider's web console, whose scrollback dies with the browser tab. Hence
`tubecli info`: the same screen, reprintable forever.

Address handling: a cloud VM behind NAT (Tencent, AWS, GCP) cannot see its own
public IP — every local address is private, and the best we can do is teach the
user where to find the public one. But Hetzner/DigitalOcean/Vultr-style hosts
put the public address directly on eth0, and for them we can print a URL that is
literally clickable. So addresses are classified, not assumed: public ones are
shown as ready URLs, private ones as a labelled hint that this is NOT the
address to browse to.
"""
import os
import subprocess
import sys

import click
from rich.console import Console

console = Console()


def local_addresses() -> list:
    """Every IP this machine answers on, deduplicated, loopback excluded.

    Reuses origin_guard's discovery (getaddrinfo + UDP-connect trick) rather than
    growing a third implementation — password_cmd's gethostbyname was already a
    second, and printed 127.0.1.1 on Debian. `hostname -I` is added on Linux
    because it also lists addresses on interfaces the default route ignores.
    """
    addrs = set()
    try:
        from tubecli.core.origin_guard import _local_ip_addresses
        addrs |= set(_local_ip_addresses())
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.run(["hostname", "-I"], capture_output=True,
                                 text=True, timeout=3)
            addrs |= set((out.stdout or "").split())
        except Exception:
            pass
    return sorted(a for a in addrs if a and not a.startswith("127."))


def split_public_private(addrs: list) -> tuple:
    """(public, private) — IPv4 only. is_global is the test: it already knows
    RFC1918, CGNAT 100.64/10, link-local and loopback are not routable from a
    laptop. IPv6 is dropped entirely: a bare v6 in a URL is invalid without
    brackets (the first smoke run printed exactly that), and the audience of
    this screen browses to their VPS's IPv4.
    """
    import ipaddress
    public, private = [], []
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.version != 4:
            continue
        (public if ip.is_global else private).append(a)
    return public, private


def service_state() -> str:
    """'active' | 'inactive' | 'no-systemd'. /run/systemd/system is the canonical
    check for a RUNNING systemd — the systemctl binary alone exists on WSL and in
    container images where systemd is not PID 1 and every call would fail."""
    if not sys.platform.startswith("linux") or not os.path.isdir("/run/systemd/system"):
        return "no-systemd"
    try:
        r = subprocess.run(["systemctl", "is-active", "tubecli"],
                           capture_output=True, text=True, timeout=5)
        return "active" if (r.stdout or "").strip() == "active" else "inactive"
    except Exception:
        return "inactive"


def health_ok(port: int, timeout_sec: int = 3) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=timeout_sec) as r:
            return r.status == 200
    except Exception:
        return False


def print_server_ready(*, update_status: str = "") -> None:
    """The one screen. Never raises — it is the last thing setup shows."""
    from tubecli.i18n import t, load_language
    from tubecli.config import get_api_port, get_language
    from tubecli.core import auth

    # Self-sufficient about i18n: t() returns the raw KEY until a catalog is
    # loaded, and this function is called from places that never went through
    # init's language step. Loading the saved language is idempotent.
    try:
        load_language(get_language())
    except Exception:
        pass

    try:
        port = get_api_port()
    except Exception:
        port = 5295

    state = service_state()
    alive = health_ok(port)
    public, private = split_public_private(local_addresses())

    line = "=" * 58
    console.print(f"\n[cyan]{line}[/cyan]")
    console.print(t("server.ready_title"))
    console.print(f"[cyan]{line}[/cyan]\n")

    if alive:
        console.print(t("server.check_ok", port=port))
    elif state == "active":
        console.print(t("server.check_starting", port=port))
    elif state == "no-systemd":
        console.print(t("server.check_container"))
    else:
        console.print(t("server.check_down"))

    if state == "active":
        console.print(t("server.systemd_note"))

    console.print("")
    if public:
        for a in public:
            console.print(f"      [bold green]http://{a}:{port}/dashboard[/bold green]")
        console.print(t("server.url_public_note"))
    else:
        console.print(f"      [bold]http://<ip-máy-chủ>:{port}/dashboard[/bold]"
                      if _is_vi() else
                      f"      [bold]http://<your-server-ip>:{port}/dashboard[/bold]")
        console.print(t("server.url_nat_note",
                        private=", ".join(private) if private else "?"))
    console.print(t("server.firewall_note", port=port))

    console.print("")
    try:
        auth.ensure_initialised()
        if auth.is_default_password():
            console.print(t("server.password_default"))
        else:
            console.print(t("server.password_set"))
    except Exception:
        pass

    if update_status:
        console.print("")
        console.print(t("server.update_stale") if update_status == "stale"
                      else t("server.update_ok"))
    try:
        from tubecli import __version__
        console.print(t("server.version_line", version=__version__))
    except Exception:
        pass

    console.print("")
    console.print(t("server.commands_title"))
    console.print(t("server.cmd_password"))
    console.print(t("server.cmd_logs") if state != "no-systemd" else t("server.cmd_logs_container"))
    console.print(t("server.cmd_update"))
    console.print(t("server.cmd_info"))
    console.print(f"[cyan]{line}[/cyan]\n")


def _is_vi() -> bool:
    try:
        from tubecli.i18n import get_current_language
        return (get_current_language() or "").startswith("vi")
    except Exception:
        return False


@click.command("info")
def info_cmd():
    """Xem lại màn hình 'server đã sẵn sàng': URL, mật khẩu, các lệnh cần nhớ."""
    from tubecli.config import get_language
    from tubecli.i18n import load_language
    load_language(get_language())
    print_server_ready()
