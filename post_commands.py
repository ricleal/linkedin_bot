"""Unified `generate` and `post` commands: subjects, news, or blogs → LinkedIn.

Use --source to pick where the content comes from:
  - subjects (default): a topic from subjects.yaml, random unless --subject is given
  - news:   a recent tech news article (RSS)
  - blogs:  a recent post from a curated engineering blog (RSS)

For news/blogs, an interactive article-selection menu is shown by default;
pass --auto to skip it and auto-publish the top trending/most recent article
with no prompts at all (handy for cron).
"""

from typing import Optional

import typer

import db
from blog_fetcher import BlogFetcher
from config import (
    DB_PATH_ABS,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    MAX_POST_LENGTH,
    POST_LANGUAGE,
    UNSPLASH_ACCESS_KEY,
    DEEPSEEK_API_KEY,
    app,
    load_subjects,
    logger,
    pick_random_subject,
)
from content_sources import (
    DEFAULT_HOURS,
    Source,
    auto_pick_article,
    finalize_text,
    generate_article_post,
    generate_subject_post,
    select_article,
)
from image_provider import ImageProvider, subject_to_tweet
from linkedin_client import LinkedInClient
from news_fetcher import NewsFetcher

# ── Helpers ────────────────────────────────────────────────────────────────


def _fetcher_for(source: Source) -> NewsFetcher:
    return NewsFetcher() if source == Source.news else BlogFetcher()


def _label_for(source: Source, item) -> str:
    """Display label for a content item: the subject string, or an article's title."""
    return item if source == Source.subjects else item["title"]


def _resolve_item_and_text(
    source: Source,
    subject: Optional[str],
    hours: Optional[int],
    limit: int,
    auto: bool,
    language: str,
    max_length: int,
) -> tuple[object, str] | None:
    """Resolve a content item (subject str or article dict) and generate its post text.

    Returns (item, raw_text), or None if the user quit / nothing was found.
    """
    if source == Source.subjects:
        subjects_list = load_subjects()
        item = subject if subject else pick_random_subject(subjects_list)
        typer.echo(f"📌 Subject: {item}")
        typer.echo("⏳ Generating post with DeepSeek...")
        raw_text = generate_subject_post(item, language, max_length)
        return (item, raw_text) if raw_text else None

    fetcher = _fetcher_for(source)
    effective_hours = hours if hours is not None else DEFAULT_HOURS[source]
    label = source.value.upper()

    if auto:
        typer.echo(f"⏳ Auto-picking a {source.value[:-1]} article...")
        item = auto_pick_article(fetcher, effective_hours)
        if item is None:
            typer.secho(
                f"❌ No articles found in the last {effective_hours}h.",
                fg=typer.colors.RED,
                err=True,
            )
            return None
        typer.echo(f"📌 Auto-picked: [{item['source']}] {item['title']}")
    else:
        item = select_article(fetcher, effective_hours, limit, label=label)
        if item is None:
            return None

    typer.echo("⏳ Generating post with DeepSeek...")
    raw_text = generate_article_post(item, language, max_length)
    return (item, raw_text) if raw_text else None


def _generate_and_save(
    source: Source,
    item,
    image_provider: ImageProvider,
    language: str = "",
    max_length: int = 0,
) -> tuple[str, str | None, int] | None:
    """(Re)generate text for an already-resolved item, render its image, and save it.

    Returns (generated_text, local_image_path, post_id), or None on failure.
    """
    if source == Source.subjects:
        raw_text = generate_subject_post(item, language, max_length)
    else:
        raw_text = generate_article_post(item, language, max_length)
    if not raw_text:
        typer.secho("❌ Failed to generate post.", fg=typer.colors.RED, err=True)
        return None

    typer.echo("🔄 Converting Markdown to Unicode...")
    article = None if source == Source.subjects else item
    generated_text = finalize_text(source, raw_text, article)

    typer.echo("⏳ Finding an image...")
    local_image_path, image_url = image_provider.fetch_image(_label_for(source, item))

    post_id = db.save_post(
        DB_PATH_ABS,
        _label_for(source, item),
        generated_text,
        image_url=image_url,
        generated_raw_text=raw_text,
    )
    logger.info("Post saved to database (ID=%d).", post_id)
    return generated_text, local_image_path, post_id


def _interactive_review_loop(
    source: Source,
    item,
    generated_text: str,
    local_image_path: str | None,
    image_provider: ImageProvider,
    post_id: int,
    language: str = "",
    max_length: int = 0,
    hours: int = 24,
    limit: int = 10,
) -> tuple[object, str, str | None, int]:
    """Interactive loop to review, regenerate, or pick a different item before publishing.

    Common options: p (post), r (regenerate same item), q (quit).
    Subjects-only:   n (new random subject), s (specify your own subject).
    News/blogs-only: c (choose a different article).

    Returns updated (item, generated_text, local_image_path, post_id).
    """
    subjects_list = load_subjects() if source == Source.subjects else None
    fetcher = None if source == Source.subjects else _fetcher_for(source)

    while True:
        typer.echo("\n" + "═" * 60)
        typer.echo("   📝  POST PREVIEW")
        typer.echo("═" * 60)
        typer.echo(generated_text)
        typer.echo("\n" + "─" * 60)
        typer.echo(f"   📊 Characters: {len(generated_text)}")
        if source == Source.subjects:
            typer.echo(f"   📌 Subject: {item[:70]}")
        else:
            typer.echo(f"   📰 Article: {item['title'][:70]}")
            typer.echo(f"   🔗 {item['link']}")
        typer.echo("─" * 60)
        typer.echo("\n🐦 Tweet card text:")
        typer.secho(subject_to_tweet(_label_for(source, item)), fg=typer.colors.CYAN)
        typer.echo("─" * 60)

        typer.echo("\nOptions:")
        typer.echo("  [p]  Post to LinkedIn")
        if source == Source.subjects:
            typer.echo("  [r]  Regenerate post (same subject)")
            typer.echo("  [n]  New random subject & regenerate")
            typer.echo("  [s]  Specify your own subject")
        else:
            typer.echo("  [r]  Regenerate post (same article)")
            typer.echo("  [c]  Choose a different article")
        typer.echo("  [q]  Quit without posting")

        choice = typer.prompt("\nWhat would you like to do", default="p").strip().lower()

        if choice == "p":
            return item, generated_text, local_image_path, post_id

        if choice == "q":
            typer.echo("👋 Exiting without posting.")
            if local_image_path:
                image_provider.cleanup(local_image_path)
            raise typer.Exit(0)

        if source == Source.subjects and choice in ("r", "n", "s"):
            if choice == "n":
                item = pick_random_subject(subjects_list)
                typer.echo(f"📌 New subject: {item}")
            elif choice == "s":
                user_subject = typer.prompt("Enter your subject").strip()
                if not user_subject:
                    continue
                item = user_subject
            new_entry = _generate_and_save(source, item, image_provider, language, max_length)
            if new_entry is None:
                continue
            if local_image_path:
                image_provider.cleanup(local_image_path)
            generated_text, local_image_path, post_id = new_entry
            typer.echo(f"💾 Saved as entry #{post_id}")
            continue

        if source != Source.subjects and choice in ("r", "c"):
            if choice == "c":
                new_item = select_article(fetcher, hours, limit, label=source.value.upper())
                if new_item is None:
                    continue
                item = new_item
            new_entry = _generate_and_save(source, item, image_provider, language, max_length)
            if new_entry is None:
                continue
            if local_image_path:
                image_provider.cleanup(local_image_path)
            generated_text, local_image_path, post_id = new_entry
            typer.echo(f"💾 Saved as entry #{post_id}")
            continue

        typer.secho(f"❌ Unknown option: {choice}", fg=typer.colors.RED, err=True)


def _authenticated_linkedin_client() -> LinkedInClient:
    """Load the stored LinkedIn token and return a ready-to-use client, or exit(1)."""
    stored_token = db.get_linkedin_token(DB_PATH_ABS)
    linkedin_client = LinkedInClient(
        LINKEDIN_CLIENT_ID,
        LINKEDIN_CLIENT_SECRET,
        LINKEDIN_REDIRECT_URI,
    )
    if not stored_token or not stored_token.get("access_token"):
        logger.error("No stored LinkedIn token found.")
        typer.secho(
            "❌ No stored LinkedIn token. Run `python main.py auth` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    linkedin_client.set_access_token(stored_token["access_token"])
    try:
        logger.info("Verifying LinkedIn access token...")
        user_info = linkedin_client.get_user_info()
        logger.info("Authenticated as: %s", user_info.get("name", "Unknown"))
        typer.echo(f"🔑 Authenticated as: {user_info.get('name', 'Unknown')}")
    except Exception as e:
        logger.error("LinkedIn token expired or invalid: %s", e)
        typer.secho(
            f"❌ LinkedIn token expired or invalid: {e}", fg=typer.colors.RED, err=True
        )
        typer.echo("   Run `python main.py auth` to re-authenticate.")
        raise typer.Exit(1)
    return linkedin_client


# ── Options shared by generate/post ─────────────────────────────────────────

_SOURCE_OPTION = typer.Option(
    Source.subjects.value,
    "--source",
    "-src",
    help="Content source: subjects, news, or blogs.",
)
_SUBJECT_OPTION = typer.Option(
    None,
    "--subject",
    "-s",
    help="Subject to write about (subjects source only). Random if omitted.",
)
_HOURS_OPTION = typer.Option(
    None,
    "--hours",
    "-H",
    help="Look-back window in hours (news/blogs only; default 24 for news, 336 for blogs).",
)
_LIMIT_OPTION = typer.Option(
    10, "--limit", "-n", help="Max articles shown in the selection menu (news/blogs only)."
)
_AUTO_OPTION = typer.Option(
    False,
    "--auto",
    "-a",
    help="Auto-pick the top trending/most recent article with no prompts (news/blogs only).",
)
_LANGUAGE_OPTION = typer.Option(
    None, "--language", "-l", help=f"Post language (default: {POST_LANGUAGE})"
)
_MAX_LENGTH_OPTION = typer.Option(
    None, "--max-length", "-m", help=f"Max post length in characters (default: {MAX_POST_LENGTH})"
)


# ── Commands ───────────────────────────────────────────────────────────────


@app.command()
def generate(
    source: Source = _SOURCE_OPTION,
    subject: Optional[str] = _SUBJECT_OPTION,
    hours: Optional[int] = _HOURS_OPTION,
    limit: int = _LIMIT_OPTION,
    auto: bool = _AUTO_OPTION,
    language: Optional[str] = _LANGUAGE_OPTION,
    max_length: Optional[int] = _MAX_LENGTH_OPTION,
):
    """Generate a LinkedIn post and save it as a draft (no publishing)."""
    logger.info("=== Command: generate (source=%s) ===", source.value)

    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY is not set in .env file.")
        typer.secho("❌ DEEPSEEK_API_KEY is not set in .env file.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    logger.info("Initializing database...")
    db.init_db(DB_PATH_ABS)

    resolved = _resolve_item_and_text(
        source, subject, hours, limit, auto, language or "", max_length or 0
    )
    if resolved is None:
        typer.echo("👋 Exiting without generating.")
        raise typer.Exit(0)
    item, raw_text = resolved

    typer.echo("🔄 Converting Markdown to Unicode...")
    article = None if source == Source.subjects else item
    generated_text = finalize_text(source, raw_text, article)
    logger.info(
        "Converted: %d characters → %d characters", len(raw_text), len(generated_text)
    )

    typer.echo("⏳ Finding an image...")
    image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
    local_image_path, image_url = image_provider.fetch_image(_label_for(source, item))

    post_id = db.save_post(
        DB_PATH_ABS,
        _label_for(source, item),
        generated_text,
        image_url=image_url,
        generated_raw_text=raw_text,
    )
    logger.info("Post saved to database (ID=%d).", post_id)
    typer.echo(f"\n💾 Post saved to database (ID: {post_id})")

    typer.echo("\n" + "═" * 60)
    typer.echo("   📝  GENERATED POST")
    typer.echo("═" * 60)
    typer.echo(generated_text)
    typer.echo("\n" + "─" * 60)
    typer.echo(f"   📊 Characters: {len(generated_text)}")
    if image_url:
        typer.echo(f"   🖼️  Image: {image_url}")
    typer.echo("─" * 60)

    image_provider.cleanup(local_image_path)


@app.command()
def post(
    source: Source = _SOURCE_OPTION,
    entry_id: Optional[int] = typer.Option(
        None,
        "--entry-id",
        "-e",
        help="Post an existing entry from the database by its ID (skips generation, ignores --source).",
    ),
    subject: Optional[str] = _SUBJECT_OPTION,
    hours: Optional[int] = _HOURS_OPTION,
    limit: int = _LIMIT_OPTION,
    auto: bool = _AUTO_OPTION,
    language: Optional[str] = _LANGUAGE_OPTION,
    max_length: Optional[int] = _MAX_LENGTH_OPTION,
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Review the post (regenerate/pick again) before publishing.",
    ),
):
    """Generate a post and publish it to LinkedIn."""
    logger.info("=== Command: post (source=%s) ===", source.value)

    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY is not set in .env file.")
        typer.secho("❌ DEEPSEEK_API_KEY is not set in .env file.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
        logger.error("LinkedIn credentials not configured in .env.")
        typer.secho(
            "❌ LinkedIn credentials are not configured in .env file.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    logger.info("Initializing database...")
    db.init_db(DB_PATH_ABS)

    logger.info("Retrieving stored LinkedIn token...")
    linkedin_client = _authenticated_linkedin_client()

    effective_hours = hours if hours is not None else DEFAULT_HOURS.get(source, 24)
    # --auto is fully unattended: skip both the selection menu and the review loop.
    effective_interactive = interactive and not auto

    # ── Resolve the post to publish ────────────────────────────────────────

    if entry_id is not None:
        entry = db.get_post_by_id(DB_PATH_ABS, entry_id)
        if not entry:
            logger.error("Entry #%d not found in database.", entry_id)
            typer.secho(
                f"❌ Entry #{entry_id} not found in database.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

        # Existing entries are always reviewed/regenerated as a "subject" —
        # regardless of which source originally produced them — since only
        # the saved subject/title text (not the original article) is stored.
        review_source = Source.subjects
        post_id = entry["id"]
        item = entry["subject"]
        generated_text = entry["generated_text"]
        image_url = entry.get("image_url")
        logger.info("Using existing entry #%d: %.80s", post_id, item)
        typer.echo(f"📌 Entry #{post_id}: {item}")

        image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
        local_image_path = None
        if image_url:
            logger.info("Re-downloading image from: %s", image_url)
            local_image_path, _ = image_provider.fetch_image(item)
    else:
        review_source = source
        image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
        resolved = _resolve_item_and_text(
            source, subject, effective_hours, limit, auto, language or "", max_length or 0
        )
        if resolved is None:
            typer.echo("👋 Exiting without posting.")
            raise typer.Exit(0)
        item, raw_text = resolved

        typer.echo("🔄 Converting Markdown to Unicode...")
        article = None if source == Source.subjects else item
        generated_text = finalize_text(source, raw_text, article)

        typer.echo("⏳ Finding an image...")
        local_image_path, image_url = image_provider.fetch_image(_label_for(source, item))

        post_id = db.save_post(
            DB_PATH_ABS,
            _label_for(source, item),
            generated_text,
            image_url=image_url,
            generated_raw_text=raw_text,
        )
        logger.info("Post saved to database (ID=%d).", post_id)

    # ── Interactive review ─────────────────────────────────────────────────

    if effective_interactive:
        item, generated_text, local_image_path, post_id = _interactive_review_loop(
            review_source,
            item,
            generated_text,
            local_image_path,
            image_provider,
            post_id,
            language=language or "",
            max_length=max_length or 0,
            hours=effective_hours,
            limit=limit,
        )

    # ── Publish to LinkedIn ────────────────────────────────────────────────

    typer.echo("⏳ Posting to LinkedIn...")
    try:
        image_urn = None
        if local_image_path:
            typer.echo("   ⏳ Uploading image to LinkedIn...")
            image_urn = linkedin_client.upload_image(local_image_path)
            image_provider.cleanup(local_image_path)

        logger.info("Posting to LinkedIn (lifecycle=PUBLISHED)...")
        result = linkedin_client.create_post(
            generated_text,
            image_urn=image_urn,
            lifecycle_state="PUBLISHED",
        )
        db.update_post_status(DB_PATH_ABS, post_id, "posted")
        label = _label_for(review_source, item)
        typer.echo(f"✅ Published! (post #{post_id}) — {label[:60]}")
        typer.echo(f"   🔗 {result['post_url']}")
        logger.info("Post #%d successfully published: %s", post_id, result["post_url"])
    except Exception as e:
        logger.error("Failed to post to LinkedIn: %s", e)
        typer.secho(f"❌ Failed to post to LinkedIn: {e}", fg=typer.colors.RED, err=True)
        db.update_post_status(DB_PATH_ABS, post_id, "draft")
        raise typer.Exit(1)
