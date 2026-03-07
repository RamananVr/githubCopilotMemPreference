"""CLI entry point for copilot-mem."""
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from config import DB_PATH
from src.indexer.db import init_db, db_stats
from src.indexer.indexer import run_index
from src.search.search import (
    get_requests,
    list_projects,
    recent,
    search,
    timeline,
)

console = Console()


def _get_conn():
    return init_db(str(DB_PATH))


@click.group()
def cli():
    """copilot-mem — searchable index of your GitHub Copilot chat sessions."""


@cli.command()
@click.option("--force", is_flag=True, help="Re-index all sessions, ignoring cache.")
@click.option("--classify", is_flag=True, help="Run LLM classification after indexing.")
def index(force: bool, classify: bool):
    """Scan and index all Copilot chat sessions."""
    conn = _get_conn()
    with console.status("Indexing sessions..."):
        stats = run_index(conn, force=force, classify=classify)
    console.print(f"[green]Done.[/green] Scanned: {stats.scanned} | "
                  f"Indexed: {stats.indexed} | Skipped: {stats.skipped} | Errors: {stats.errors}")
    conn.close()


@cli.command()
@click.option("--force", is_flag=True, help="Re-classify already classified sessions.")
def classify(force: bool):
    """Run LLM classification on unclassified sessions."""
    from src.llm.classifier import classify_all_unclassified
    conn = _get_conn()
    if force:
        conn.execute("UPDATE sessions SET classified_at = NULL")
        conn.commit()
    with console.status("Classifying sessions..."):
        result = classify_all_unclassified(conn)
    mode = "LLM" if result.used_llm else "rule-based"
    console.print(
        f"[green]Done ({mode}).[/green] "
        f"Sessions: {result.sessions_processed} | "
        f"Requests: {result.requests_classified} | "
        f"Preferences: {result.preferences_extracted} | "
        f"Errors: {result.errors}"
    )
    conn.close()


@cli.command()
@click.option("--inject", is_flag=True, help="Write context to copilot-instructions.md")
@click.option("--inject-claude", is_flag=True, help="Print context for Claude Code hook")
@click.option("--hours", default=72, show_default=True, help="Hours of history to include")
def context(inject: bool, inject_claude: bool, hours: int):
    """Show or inject the recent context block."""
    from src.context.injector import generate_context_block, inject_context
    conn = _get_conn()
    if inject or inject_claude:
        block = inject_context(conn, hours=hours)
    else:
        block = generate_context_block(conn, hours=hours)
    if inject_claude:
        print(block)  # stdout for Claude Code hook
    elif not inject:
        console.print(block or "[yellow]No classified data. Run: copilot-mem classify[/yellow]")
    else:
        console.print("[green]Context injected.[/green]")
    conn.close()


@cli.command()
@click.option("--project", "-p", default=None, help="Filter by project name.")
def preferences(project: str | None):
    """List extracted preferences and decisions."""
    from src.search.search import get_preferences
    conn = _get_conn()
    prefs = get_preferences(conn, project=project)
    if not prefs:
        console.print("[yellow]No preferences found. Run: copilot-mem classify[/yellow]")
        conn.close()
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Project", width=20)
    table.add_column("Preference", width=60)
    for p in prefs:
        table.add_row(p.project_name or "(global)", p.content)
    console.print(table)
    conn.close()


@click.command()
@click.argument("query")
@click.option("--project", "-p", default=None, help="Filter by project name.")
@click.option("--type", "-t", "obs_type", default=None,
              help="Filter by type: bugfix, feature, refactor, discovery, decision, change, other")
@click.option("--limit", "-n", default=20, show_default=True, help="Max results.")
def search_cmd(query: str, project: str | None, obs_type: str | None, limit: int):
    """Search past Copilot sessions. Supports FTS5 query syntax."""
    conn = _get_conn()
    try:
        results = search(conn, query, project=project, obs_type=obs_type, limit=limit)
    except Exception as e:
        console.print(f"[red]Search error:[/red] {e}")
        conn.close()
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=3)
    table.add_column("Type", width=10)
    table.add_column("Project", width=14)
    table.add_column("Title / Question", width=50)
    table.add_column("Request ID", width=38)

    for i, r in enumerate(results, 1):
        display = r.title or r.user_message[:60]
        table.add_row(
            str(i),
            r.obs_type or "-",
            r.project_name or "(none)",
            display[:80],
            r.request_id,
        )

    console.print(table)
    conn.close()


# Register search under clean name (function is named search_cmd to avoid
# shadowing the imported search() function)
cli.add_command(search_cmd, name="search")


@click.command()
@click.argument("request_id")
@click.option("--before", default=3, show_default=True)
@click.option("--after", default=3, show_default=True)
def timeline_cmd(request_id: str, before: int, after: int):
    """Show surrounding context for a specific request."""
    conn = _get_conn()
    entries = timeline(conn, request_id, before=before, after=after)

    if not entries:
        console.print("[yellow]Request not found.[/yellow]")
        conn.close()
        return

    for e in entries:
        prefix = ">>> " if e.is_anchor else "    "
        style = "bold green" if e.is_anchor else ""
        console.print(f"{prefix}[{e.seq_num}] [{style}]User:[/{style}] {e.user_message[:120]}")
        if e.assistant_response:
            console.print(f"     [dim]Copilot:[/dim] {e.assistant_response[:200]}")
        console.print()

    conn.close()


cli.add_command(timeline_cmd, name="timeline")


@cli.command()
def projects():
    """List all indexed projects."""
    conn = _get_conn()
    rows = list_projects(conn)

    if not rows:
        console.print("[yellow]No projects indexed yet. Run: copilot-mem index[/yellow]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Project", width=25)
    table.add_column("Sessions", justify="right")
    table.add_column("Requests", justify="right")

    for r in rows:
        table.add_row(r.project_name, str(r.session_count), str(r.request_count))

    console.print(table)
    conn.close()


@click.command()
@click.option("--project", "-p", default=None, help="Filter by project name.")
@click.option("--limit", "-n", default=10, show_default=True)
def recent_cmd(project: str | None, limit: int):
    """Show most recent Copilot interactions."""
    conn = _get_conn()
    results = recent(conn, project=project, limit=limit)

    if not results:
        console.print("[yellow]No interactions found.[/yellow]")
        conn.close()
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Project", width=16)
    table.add_column("Question", width=70)
    table.add_column("Request ID", width=38)

    for r in results:
        table.add_row(r.project_name or "(none)", r.user_message[:100], r.request_id)

    console.print(table)
    conn.close()


cli.add_command(recent_cmd, name="recent")


@cli.command()
def stats():
    """Show database statistics."""
    conn = _get_conn()
    s = db_stats(conn)
    import os
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    console.print(f"Sessions:  {s['sessions']}")
    console.print(f"Requests:  {s['requests']}")
    console.print(f"Projects:  {s['projects']}")
    console.print(f"DB size:   {db_size / 1024:.1f} KB  ({DB_PATH})")
    conn.close()


if __name__ == "__main__":
    cli()
