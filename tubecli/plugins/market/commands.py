"""
Marketplace CLI commands.
"""
import click
from rich.console import Console
from rich.table import Table

console = Console()

# Sample community skills registry (will be replaced by API later)
COMMUNITY_SKILLS = [
    {"id": "youtube-uploader", "name": "🎬 YouTube Uploader", "author": "community", "desc": "Auto upload videos with SEO", "type": "community"},
    {"id": "tiktok-poster", "name": "📱 TikTok Poster", "author": "community", "desc": "Post content to TikTok", "type": "community"},
    {"id": "email-sender", "name": "📧 Email Sender", "author": "community", "desc": "Batch email sending with templates", "type": "community"},
    {"id": "web-scraper", "name": "🕷️ Web Scraper", "author": "official", "desc": "Extract data from websites", "type": "official"},
    {"id": "social-poster", "name": "📤 Social Poster", "author": "community", "desc": "Post to multiple social platforms", "type": "community"},
    {"id": "seo-analyzer", "name": "🔍 SEO Analyzer", "author": "official", "desc": "Analyze website SEO metrics", "type": "official"},
]


@click.group("market")
def market_group():
    """Browse and install community skills."""
    pass


@market_group.command("search")
@click.argument("query", default="")
def search_market(query):
    """Search the marketplace for skills."""
    results = COMMUNITY_SKILLS
    if query:
        q = query.lower()
        results = [s for s in results if q in s["name"].lower() or q in s["desc"].lower()]

    if not results:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(title="🛒 Marketplace")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Author")
    table.add_column("Description", style="dim")
    table.add_column("Type")

    for s in results:
        type_style = "[green]official[/green]" if s["type"] == "official" else "[purple]community[/purple]"
        table.add_row(s["id"], s["name"], s["author"], s["desc"], type_style)

    console.print(table)


@market_group.command("install")
@click.argument("skill_id")
def install_skill(skill_id):
    """Install a skill from the marketplace."""
    skill = next((s for s in COMMUNITY_SKILLS if s["id"] == skill_id), None)
    if not skill:
        console.print(f"[red]❌ Skill '{skill_id}' not found in marketplace.[/red]")
        return

    # In real implementation: download workflow JSON from registry
    console.print(f"[green]✅ Installed: {skill['name']}[/green]")
    console.print(f"   Run with: tubecli skill run \"{skill['name']}\"")


@market_group.command("list")
def list_installed():
    """List marketplace skills."""
    search_market.callback("")
