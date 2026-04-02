"""
Calendar Manager Extension — CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group("calendar")
def calendar_group():
    """Manage Google Calendar events & schedules."""
    pass


@calendar_group.command("calendars")
@click.option("--email", "-e", default="", help="Filter by authorized email")
def list_calendars(email):
    """List all calendars for the authenticated user."""
    from tubecli.extensions.calendar_manager.extension import calendar_manager
    result = calendar_manager.list_calendars(email=email)

    if result["status"] == "error":
        console.print(f"[red]❌ {result['message']}[/red]")
        return

    calendars = result.get("calendars", [])
    if not calendars:
        console.print("[dim]No calendars found.[/dim]")
        return

    table = Table(title="📅 Google Calendars")
    table.add_column("ID", style="cyan", max_width=40)
    table.add_column("Name", style="bold")
    table.add_column("Primary", justify="center")
    table.add_column("Time Zone", style="dim")

    for cal in calendars:
        primary = "[green]✅[/green]" if cal.get("primary") else ""
        table.add_row(
            cal["id"][:40],
            cal.get("summary", ""),
            primary,
            cal.get("time_zone", ""),
        )

    console.print(table)


@calendar_group.command("list")
@click.option("--calendar-id", "-c", default="primary", help="Calendar ID")
@click.option("--days", "-d", default=1, help="Number of days ahead to show")
@click.option("--email", "-e", default="", help="Authorized email to use")
def list_events(calendar_id, days, email):
    """List upcoming events (default: today)."""
    from datetime import datetime, timedelta, timezone
    from tubecli.extensions.calendar_manager.extension import calendar_manager

    time_min = datetime.now(timezone.utc).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    result = calendar_manager.list_events(
        email=email,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
    )

    if result["status"] == "error":
        console.print(f"[red]❌ {result['message']}[/red]")
        return

    events = result.get("events", [])
    if not events:
        console.print(f"[dim]No events in the next {days} day(s).[/dim]")
        return

    table = Table(title=f"📅 Events (next {days} day{'s' if days > 1 else ''})")
    table.add_column("Time", style="cyan")
    table.add_column("Summary", style="bold")
    table.add_column("Location", style="dim")
    table.add_column("ID", style="dim", max_width=20)

    for ev in events:
        start = ev.get("start", "")
        try:
            dt = datetime.fromisoformat(start)
            time_str = dt.strftime("%H:%M %d/%m")
        except Exception:
            time_str = start[:16] if start else "?"

        table.add_row(
            time_str,
            ev.get("summary", "(No title)"),
            ev.get("location", ""),
            ev.get("id", "")[:20],
        )

    console.print(table)


@calendar_group.command("add")
@click.argument("summary")
@click.option("--start", "-s", required=True, help="Start time (ISO format)")
@click.option("--end", "-e", default="", help="End time (ISO format, default: +1h)")
@click.option("--desc", "-d", default="", help="Description")
@click.option("--location", "-l", default="", help="Location")
@click.option("--recurrence", "-r", default="", help="Recurrence rule (e.g., RRULE:FREQ=DAILY)")
@click.option("--email", default="", help="Authorized email to use")
@click.option("--calendar-id", "-c", default="primary", help="Calendar ID")
def add_event(summary, start, end, desc, location, recurrence, email, calendar_id):
    """Create a new calendar event.

    Example: tubecli calendar add "Daily Livestream" -s "2026-04-03T20:00:00+07:00" -r "RRULE:FREQ=DAILY;COUNT=30"
    """
    from tubecli.extensions.calendar_manager.extension import calendar_manager

    recurrence_list = [recurrence] if recurrence else []

    result = calendar_manager.create_event(
        email=email,
        calendar_id=calendar_id,
        summary=summary,
        start=start,
        end=end,
        description=desc,
        location=location,
        recurrence=recurrence_list,
    )

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
        console.print(f"[dim]Event ID: {result.get('event_id', '')}[/dim]")
        if result.get("html_link"):
            console.print(f"[dim]Link: {result['html_link']}[/dim]")
        if result.get("recurrence"):
            console.print(f"[cyan]🔄 Recurring: {result['recurrence']}[/cyan]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@calendar_group.command("quick-add")
@click.argument("text")
@click.option("--email", "-e", default="", help="Authorized email to use")
@click.option("--calendar-id", "-c", default="primary", help="Calendar ID")
def quick_add(text, email, calendar_id):
    """Quick-add an event from natural language.

    Example: tubecli calendar quick-add "Meeting tomorrow 10am-11am at office"
    """
    from tubecli.extensions.calendar_manager.extension import calendar_manager
    result = calendar_manager.quick_add(email=email, calendar_id=calendar_id, text=text)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
        console.print(f"[dim]Event ID: {result.get('event_id', '')}[/dim]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


@calendar_group.command("delete")
@click.argument("event_id")
@click.option("--calendar-id", "-c", default="primary", help="Calendar ID")
@click.option("--email", "-e", default="", help="Authorized email to use")
@click.confirmation_option(prompt="Are you sure you want to delete this event?")
def delete_event(event_id, calendar_id, email):
    """Delete a calendar event by ID."""
    from tubecli.extensions.calendar_manager.extension import calendar_manager
    result = calendar_manager.delete_event(email=email, calendar_id=calendar_id, event_id=event_id)

    if result["status"] == "success":
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")
