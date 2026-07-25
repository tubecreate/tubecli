"""
Codex CLI — `tubecli codex ...`
"""
import click
from rich.console import Console
from rich.table import Table

from tubecli.extensions.codex.manager import codex_manager

console = Console()

_ICON = {
    "pending_approval": "🟡",
    "queued": "⏳",
    "running": "⚙️",
    "review": "🔍",
    "done": "✅",
    "failed": "❌",
    "rejected": "🚫",
    "cancelled": "⛔",
}


@click.group(name="codex")
def codex_group():
    """Mission control — giao việc cho AI agent."""


@codex_group.command("list")
@click.option("--status", default="", help="Lọc theo trạng thái (hoặc 'active')")
@click.option("--limit", default=30, help="Số task tối đa")
def list_tasks(status, limit):
    """Liệt kê task."""
    tasks = codex_manager.list_tasks(status=status, limit=limit)
    if not tasks:
        console.print("[yellow]Chưa có task nào.[/yellow]")
        return
    table = Table(title=f"Codex tasks ({status or 'all'})")
    table.add_column("#", justify="right")
    table.add_column("Trạng thái")
    table.add_column("Tiêu đề")
    table.add_column("Giao cho")
    table.add_column("Tạo lúc")
    for t in tasks:
        table.add_row(
            str(t.get("seq")),
            f"{_ICON.get(t.get('status'), '•')} {t.get('status')}",
            (t.get("title") or "")[:50],
            t.get("assignee_name") or t.get("assignee_type") or "-",
            (t.get("created_at") or "")[:19].replace("T", " "),
        )
    console.print(table)


@codex_group.command("show")
@click.argument("ref")
def show_task(ref):
    """Xem chi tiết một task."""
    task = codex_manager.resolve_ref(ref)
    if not task:
        console.print(f"[red]Không tìm thấy task '{ref}'[/red]")
        return
    console.print(f"[bold]#{task['seq']} — {task['title']}[/bold]")
    console.print(f"Trạng thái : {_ICON.get(task['status'], '•')} {task['status']}")
    console.print(f"Giao cho   : {task.get('assignee_name') or task.get('assignee_type')}")
    console.print(f"Tạo bởi    : {task.get('created_by')}")
    console.print(f"\n[dim]{task.get('goal', '')}[/dim]")
    for step in task.get("steps") or []:
        console.print(f"  {_ICON.get(step.get('status'), '•')} {step.get('label')} — {step.get('message', '')}")
    if task.get("result"):
        console.print(f"\n[green]Kết quả:[/green]\n{task['result'][:2000]}")
    if task.get("error"):
        console.print(f"\n[red]Lỗi:[/red] {task['error'][:1000]}")


@codex_group.command("create")
@click.argument("goal")
@click.option("--agent", default="", help="Tên agent nhận việc")
@click.option("--team", default="", help="Tên team nhận việc")
@click.option("--now", is_flag=True, help="Chạy ngay, bỏ qua bước duyệt")
def create_task(goal, agent, team, now):
    """Tạo task mới."""
    task = codex_manager.create_task(
        goal=goal,
        created_by="cli",
        assignee_type="team" if team else "agent",
        assignee_name=team or agent,
        approval_required=not now,
    )
    console.print(
        f"[green]✅ Đã tạo task #{task['seq']}[/green] — {task['status']}"
    )


def _decide(ref, fn, label, **kwargs):
    task = codex_manager.resolve_ref(ref)
    if not task:
        console.print(f"[red]Không tìm thấy task '{ref}'[/red]")
        return
    try:
        updated = fn(task["id"], actor="cli", **kwargs)
    except Exception as e:
        console.print(f"[red]❌ {e}[/red]")
        return
    console.print(f"[green]{label} task #{updated['seq']} → {updated['status']}[/green]")


@codex_group.command("approve")
@click.argument("ref")
@click.option("--note", default="")
def approve(ref, note):
    """Duyệt task."""
    _decide(ref, codex_manager.approve, "✅ Đã duyệt", note=note)


@codex_group.command("reject")
@click.argument("ref")
@click.option("--note", default="")
def reject(ref, note):
    """Từ chối task."""
    _decide(ref, codex_manager.reject, "🚫 Đã từ chối", note=note)


@codex_group.command("cancel")
@click.argument("ref")
def cancel(ref):
    """Huỷ task."""
    _decide(ref, codex_manager.cancel, "⛔ Đã huỷ")


@codex_group.command("retry")
@click.argument("ref")
def retry(ref):
    """Chạy lại task."""
    _decide(ref, codex_manager.retry, "🔁 Đã xếp lại")


@codex_group.command("stats")
def stats():
    """Thống kê board."""
    data = codex_manager.get_stats()
    table = Table(title="Codex stats")
    table.add_column("Trạng thái")
    table.add_column("Số lượng", justify="right")
    for key, value in data.items():
        table.add_row(key, str(value))
    console.print(table)
