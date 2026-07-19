"""News command: pick a trending/recent tech news story and post about it."""

from typing import Optional

import typer
from openai import OpenAI

import db
from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DB_PATH_ABS,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    MAX_POST_LENGTH,
    POST_LANGUAGE,
    UNSPLASH_ACCESS_KEY,
    app,
    logger,
)
from converter import convert, escape_linkedin
from image_provider import ImageProvider, subject_to_tweet
from linkedin_client import LinkedInClient
from news_fetcher import NewsFetcher

# ── Helpers ────────────────────────────────────────────────────────────────


def generate_news_post(
    article: dict, language: str = "", max_length: int = 0
) -> str | None:
    """Generate a LinkedIn post reacting to a news article using the DeepSeek API.

    Args:
        article: A dict with at least "title", "description", "source" keys
            (as produced by ``news_fetcher.NewsFetcher``).
        language: Override language (defaults to POST_LANGUAGE env var).
        max_length: Override max character length (defaults to MAX_POST_LENGTH env var).

    Returns the generated text, or None if generation failed.
    """
    lang = language or POST_LANGUAGE
    length = max_length or MAX_POST_LENGTH
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

    system_prompt = (
        f"You are an expert LinkedIn content creator who writes sharp commentary "
        f"on tech news. Write engaging, professional LinkedIn posts in {lang} that "
        f"react to a news article — briefly summarizing what happened and adding "
        f"your own insight, opinion, or implications for software engineers and "
        f"the tech industry. Use a natural, conversational tone. "
        f"Keep the post under {length} characters. "
        f"The post should feel authentic, not like marketing. "
        f"STRUCTURE: The very first line MUST be a short, punchy hook of at most "
        f"10 words that grabs attention — like a newspaper headline or a bold "
        f"provocation. Follow it with a blank line, then the rest of the post. "
        f"Only use facts present in the provided title/summary — do not invent details. "
        f"Do NOT include raw URLs in the text. "
        f"CRITICAL: Output ONLY the post content itself. "
        f"Do NOT include any introductory phrases, meta-commentary, disclaimers, "
        f"or descriptions such as 'Here is a LinkedIn post...' or 'I hope this helps...'. "
        f"Do NOT wrap the post in quotes or code blocks. "
        f"Start directly with the hook line."
    )

    user_prompt = (
        f"Write a LinkedIn post reacting to the following news article:\n\n"
        f"Title: {article.get('title', '')}\n"
        f"Source: {article.get('source', '')}\n"
        f"Summary: {(article.get('description') or '')[:1500]}\n\n"
        f"Make it engaging and thought-provoking for other software engineers."
    )

    logger.info(
        "Calling DeepSeek API for news post (model=%s, max_tokens=%d, lang=%s)...",
        DEEPSEEK_MODEL,
        min(length, 4096),
        lang,
    )
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=min(length, 4096),
            temperature=0.8,
        )
        content = response.choices[0].message.content
        if content:
            content = content.strip().strip('"\u201c\u201d')
            logger.info("DeepSeek API response received (%d characters).", len(content))
            return content
        logger.warning("DeepSeek API returned empty content.")
        return None
    except Exception as e:
        logger.error("DeepSeek API call failed: %s", e)
        typer.secho(
            f"\n❌ Error generating post with DeepSeek: {e}",
            fg=typer.colors.RED,
            err=True,
        )
        return None


def _order_by_trending(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Sort articles by how many trending keywords appear in their title.

    Falls back to the original order when no keywords are given, or none of
    the articles actually match a keyword.
    """
    if not keywords:
        return articles

    keyword_set = set(keywords)

    def _score(article: dict) -> int:
        title_words = set(article["title"].lower().split())
        return len(title_words & keyword_set)

    scored = sorted(articles, key=_score, reverse=True)
    return scored if _score(scored[0]) > 0 else articles


def _select_news_article(fetcher: NewsFetcher, hours: int, limit: int) -> dict | None:
    """Interactive loop to list recent/trending news and let the user pick one.

    Returns the chosen article dict, or None if the user quit.
    """
    mode = "recent"

    while True:
        typer.echo("⏳ Fetching latest tech news...")
        articles = fetcher.get_recent_news(hours=hours)
        if not articles:
            typer.secho(
                f"❌ No articles found in the last {hours}h.",
                fg=typer.colors.RED,
                err=True,
            )
            return None

        keywords = fetcher.get_trending_topics(articles)
        ordered = (
            _order_by_trending(articles, keywords) if mode == "trending" else articles
        )
        display = ordered[:limit]

        typer.echo("\n" + "═" * 60)
        typer.echo(f"   📰  {'TRENDING' if mode == 'trending' else 'RECENT'} TECH NEWS")
        typer.echo("═" * 60)
        if keywords:
            typer.echo(f"🔥 Trending keywords: {', '.join(keywords)}")
            typer.echo("─" * 60)
        for i, article in enumerate(display, start=1):
            published = (
                article["published"].strftime("%Y-%m-%d %H:%M")
                if article["published"]
                else "?"
            )
            typer.echo(f"  {i:2d}. [{article['source']}] {article['title'][:80]}")
            typer.echo(f"      {published}")
        typer.echo("─" * 60)

        other_mode = "recent" if mode == "trending" else "trending"
        typer.echo("\nOptions:")
        typer.echo("  [1-N] Select an article")
        typer.echo(f"  [t]   Switch to {other_mode} view")
        typer.echo("  [f]   Refresh")
        typer.echo("  [q]   Quit")

        choice = (
            typer.prompt("\nWhat would you like to do", default="1").strip().lower()
        )

        if choice == "q":
            return None
        if choice == "f":
            continue
        if choice == "t":
            mode = other_mode
            continue
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(display):
                return display[idx - 1]
            typer.secho(
                f"❌ Invalid selection: {choice}", fg=typer.colors.RED, err=True
            )
            continue

        typer.secho(f"❌ Unknown option: {choice}", fg=typer.colors.RED, err=True)


def _generate_and_save_news_entry(
    article: dict,
    image_provider: ImageProvider,
    language: str = "",
    max_length: int = 0,
) -> tuple[str, str | None, int] | None:
    """Generate a LinkedIn post for a news article, render its tweet card, and save it.

    Returns (generated_text, local_image_path, post_id), or None on failure.
    """
    typer.echo("⏳ Generating post with DeepSeek...")
    raw_text = generate_news_post(article, language, max_length)
    if not raw_text:
        typer.secho("❌ Failed to generate post.", fg=typer.colors.RED, err=True)
        return None

    typer.echo("🔄 Converting Markdown to Unicode...")
    generated_text = convert(raw_text)
    source = article.get("source")
    if source:
        generated_text = f"{generated_text}\n\n— via {source}"
    generated_text = escape_linkedin(generated_text)

    typer.echo("⏳ Rendering tweet card...")
    local_image_path, image_url = image_provider.fetch_image(article["title"])

    post_id = db.save_post(
        DB_PATH_ABS,
        article["title"],
        generated_text,
        image_url=image_url,
        generated_raw_text=raw_text,
    )
    logger.info("News post saved to database (ID=%d).", post_id)
    return generated_text, local_image_path, post_id


# ── Command ────────────────────────────────────────────────────────────────


@app.command()
def news(
    hours: int = typer.Option(
        24,
        "--hours",
        "-H",
        help="Look back this many hours for recent articles.",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Max number of articles to list.",
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language",
        "-l",
        help=f"Post language (default: {POST_LANGUAGE})",
    ),
    max_length: Optional[int] = typer.Option(
        None,
        "--max-length",
        "-m",
        help=f"Max post length in characters (default: {MAX_POST_LENGTH})",
    ),
):
    """Pick a trending/recent tech news story and post about it on LinkedIn."""
    logger.info("=== Command: news ===")

    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY is not set in .env file.")
        typer.secho(
            "❌ DEEPSEEK_API_KEY is not set in .env file.",
            fg=typer.colors.RED,
            err=True,
        )
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

    fetcher = NewsFetcher()
    image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)

    article = _select_news_article(fetcher, hours, limit)
    if article is None:
        typer.echo("👋 Exiting without posting.")
        raise typer.Exit(0)

    entry = _generate_and_save_news_entry(
        article, image_provider, language or "", max_length or 0
    )
    if entry is None:
        raise typer.Exit(1)
    generated_text, local_image_path, post_id = entry

    # ── Interactive preview / regenerate / publish loop ────────────────────

    while True:
        typer.echo("\n" + "═" * 60)
        typer.echo("   📝  POST PREVIEW")
        typer.echo("═" * 60)
        typer.echo(generated_text)
        typer.echo("\n" + "─" * 60)
        typer.echo(f"   📊 Characters: {len(generated_text)}")
        typer.echo(f"   📰 Article: {article['title'][:70]}")
        typer.echo(f"   🔗 {article['link']}")
        typer.echo("─" * 60)
        typer.echo("\n🐦 Tweet card text:")
        typer.secho(subject_to_tweet(article["title"]), fg=typer.colors.CYAN)
        typer.echo("─" * 60)

        typer.echo("\nOptions:")
        typer.echo("  [p]  Post to LinkedIn")
        typer.echo("  [r]  Regenerate post (same article)")
        typer.echo("  [c]  Choose a different article")
        typer.echo("  [q]  Quit without posting")

        choice = (
            typer.prompt("\nWhat would you like to do", default="p").strip().lower()
        )

        if choice == "p":
            break

        if choice == "q":
            typer.echo("👋 Exiting without posting.")
            image_provider.cleanup(local_image_path)
            raise typer.Exit(0)

        if choice == "r":
            new_entry = _generate_and_save_news_entry(
                article, image_provider, language or "", max_length or 0
            )
            if new_entry is None:
                continue
            image_provider.cleanup(local_image_path)
            generated_text, local_image_path, post_id = new_entry
            typer.echo(f"💾 Saved as entry #{post_id}")
            continue

        if choice == "c":
            new_article = _select_news_article(fetcher, hours, limit)
            if new_article is None:
                continue
            new_entry = _generate_and_save_news_entry(
                new_article, image_provider, language or "", max_length or 0
            )
            if new_entry is None:
                continue
            image_provider.cleanup(local_image_path)
            article = new_article
            generated_text, local_image_path, post_id = new_entry
            typer.echo(f"💾 Saved as entry #{post_id}")
            continue

        typer.secho(f"❌ Unknown option: {choice}", fg=typer.colors.RED, err=True)

    # ── Publish to LinkedIn ─────────────────────────────────────────────────

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
        typer.echo(f"✅ Published! (post #{post_id}) — {article['title'][:60]}")
        typer.echo(f"   🔗 {result['post_url']}")
        logger.info("Post #%d successfully published: %s", post_id, result["post_url"])
    except Exception as e:
        logger.error("Failed to post to LinkedIn: %s", e)
        typer.secho(
            f"❌ Failed to post to LinkedIn: {e}", fg=typer.colors.RED, err=True
        )
        db.update_post_status(DB_PATH_ABS, post_id, "draft")
        raise typer.Exit(1)
