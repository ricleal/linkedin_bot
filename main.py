#!/usr/bin/env python3
"""LinkedIn Bot — Generate posts with DeepSeek and publish to LinkedIn.

Usage:
  python main.py generate     Generate a post and save as draft (--source subjects|news|blogs)
  python main.py post         Generate and publish to LinkedIn (--source subjects|news|blogs)
  python main.py auth         Authenticate with LinkedIn
  python main.py history      Show post history
  python main.py subjects     List available subjects
"""

from typing import Optional

import typer

import db
import linkedin_commands  # noqa: F401  (registers the auth command)
import post_commands  # noqa: F401  (registers the generate/post commands)
from config import DB_PATH_ABS, app, load_subjects, logger

# ── Commands ───────────────────────────────────────────────────────────────


@app.command()
def history(
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Number of posts to show.",
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (posted, draft, generated, discarded).",
    ),
    created_after: Optional[str] = typer.Option(
        None,
        "--created-after",
        "-c",
        help="Only posts created after this date (ISO format, e.g. 2026-06-01 or 2026-06-01T12:00:00).",
    ),
    view: Optional[int] = typer.Option(
        None,
        "--view",
        "-v",
        help="View the full content of a specific entry by its ID.",
    ),
    order: str = typer.Option(
        "desc",
        "--order",
        "-o",
        help="Sort order: asc (oldest first) or desc (newest first).",
    ),
):
    """Show recent post history from the database."""
    logger.info("=== Command: history ===")
    db.init_db(DB_PATH_ABS)

    if view is not None:
        entry = db.get_post_by_id(DB_PATH_ABS, view)
        if not entry:
            logger.error("Entry #%d not found.", view)
            typer.secho(
                f"❌ Entry #{view} not found in database.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

        status_icon = {
            "posted": "✅",
            "generated": "📝",
            "discarded": "🗑️",
            "draft": "📄",
        }.get(entry["status"], "❓")
        created = entry["created_at"][:19] if entry["created_at"] else "?"
        posted = entry["posted_at"][:19] if entry.get("posted_at") else "—"

        typer.echo("\n" + "═" * 60)
        typer.echo(f"   {status_icon}  ENTRY #{entry['id']}")
        typer.echo("═" * 60)
        typer.echo(f"  Subject:    {entry['subject']}")
        typer.echo(f"  Status:     {entry['status']}")
        typer.echo(f"  Created:    {created}")
        typer.echo(f"  Posted:     {posted}")
        if entry.get("image_url"):
            typer.echo(f"  Image:      {entry['image_url']}")
        typer.echo("─" * 60)
        typer.echo("  CONTENT:")
        typer.echo("─" * 60)
        typer.echo(entry["generated_text"])
        typer.echo("─" * 60)
        if entry.get("generated_raw_text"):
            typer.echo("  RAW (pre-conversion):")
            typer.echo("─" * 60)
            typer.echo(entry["generated_raw_text"])
            typer.echo("─" * 60)
        return

    posts = db.get_post_history(
        DB_PATH_ABS,
        limit=limit,
        status=status,
        created_after=created_after,
        order=order,
    )
    if not posts:
        logger.info("No posts in history.")
        typer.echo("📭 No posts in history yet.")
        return

    typer.echo("\n" + "─" * 60)
    typer.echo("📋  RECENT POST HISTORY")
    typer.echo("─" * 60)
    for post in posts:
        status_icon = {
            "posted": "✅",
            "generated": "📝",
            "discarded": "🗑️",
            "draft": "📄",
        }.get(post["status"], "❓")
        created = post["created_at"][:19] if post["created_at"] else "?"
        posted = f" | posted: {post['posted_at'][:19]}" if post.get("posted_at") else ""
        typer.echo(f"  {status_icon}  #{post['id']} — {post['subject'][:60]}")
        typer.echo(f"     {created}{posted} | status: {post['status']}")
    typer.echo("─" * 60)


@app.command()
def subjects():
    """List all available subjects."""
    logger.info("=== Command: subjects ===")
    subjects_list = load_subjects()
    typer.echo(f"\n📚 Available subjects ({len(subjects_list)}):\n")
    for i, s in enumerate(subjects_list, start=1):
        typer.echo(f"  {i:4d}. {s}")
    typer.echo()


if __name__ == "__main__":
    app()
