#!/usr/bin/env python3
"""LinkedIn Bot — Generate posts with DeepSeek and publish to LinkedIn.

Usage:
  python main.py generate     Generate a post and save as draft
  python main.py post         Generate and publish to LinkedIn
  python main.py news         Pick a trending/recent news story and post about it
  python main.py auth         Authenticate with LinkedIn
  python main.py history      Show post history
  python main.py subjects     List available subjects
"""

import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml
from dotenv import load_dotenv
from openai import OpenAI

import db
from converter import convert, escape_linkedin
from image_provider import ImageProvider, subject_to_tweet
from linkedin_client import LinkedInClient
from news_fetcher import NewsFetcher

# ── Configuration ──────────────────────────────────────────────────────────

load_dotenv()

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv(
    "LINKEDIN_REDIRECT_URI", "http://localhost:8080/callback"
)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
MAX_POST_LENGTH = int(os.getenv("MAX_POST_LENGTH", "3000"))
POST_LANGUAGE = os.getenv("POST_LANGUAGE", "en")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
DB_PATH = os.getenv("DB_PATH", "posts.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

BASE_DIR = Path(__file__).parent
SUBJECTS_FILE = BASE_DIR / "subjects.yaml"
DB_PATH_ABS = BASE_DIR / DB_PATH

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Typer App ──────────────────────────────────────────────────────────────

app = typer.Typer(
    name="linkedinbot",
    help="LinkedIn Bot — AI-powered post generator using DeepSeek",
    add_completion=False,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def load_subjects() -> list[str]:
    """Load the list of subjects from the YAML file."""
    if not SUBJECTS_FILE.exists():
        logger.error("Subjects file not found: %s", SUBJECTS_FILE)
        sys.exit(1)
    with open(SUBJECTS_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data.get("subjects", [])


def pick_random_subject(subjects: list[str]) -> str:
    """Pick a random subject from the list."""
    return random.choice(subjects)


def generate_post(subject: str, language: str = "", max_length: int = 0) -> str | None:
    """Generate a LinkedIn post using the DeepSeek API.

    Args:
        subject: The topic to write about.
        language: Override language (defaults to POST_LANGUAGE env var).
        max_length: Override max character length (defaults to MAX_POST_LENGTH env var).

    Returns the generated text, or None if generation failed.
    """
    lang = language or POST_LANGUAGE
    length = max_length or MAX_POST_LENGTH
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

    system_prompt = (
        f"You are an expert LinkedIn content creator. "
        f"Write engaging, professional LinkedIn posts in {lang}. "
        f"The post should be insightful, well-structured, and suitable for a "
        f"tech-savvy audience of software engineers and developers. "
        f"Use a natural, conversational tone. "
        f"Keep the post under {length} characters. "
        f"The post should feel authentic, not like marketing. "
        f"STRUCTURE: The very first line MUST be a short, punchy hook of at most "
        f"10 words that grabs attention — like a newspaper headline or a bold "
        f"provocation (e.g. 'The title \"Tech Lead\" is a trap.' or "
        f"'Most code reviews are a waste of time.'). "
        f"Follow it with a blank line, then the rest of the post. "
        f"CRITICAL: Output ONLY the post content itself. "
        f"Do NOT include any introductory phrases, meta-commentary, disclaimers, "
        f"or descriptions such as 'Here is a LinkedIn post...' or 'I hope this helps...'. "
        f"Do NOT wrap the post in quotes or code blocks. "
        f"Start directly with the hook line."
    )

    user_prompt = (
        f"Write a LinkedIn post about the following topic:\n\n"
        f"Subject: {subject}\n\n"
        f"Make it engaging and thought-provoking. Include personal insights, "
        f"practical advice, or lessons learned. The post should feel authentic "
        f"and provide value to other software engineers."
    )

    logger.info(
        "Calling DeepSeek API (model=%s, max_tokens=%d, lang=%s)...",
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


def handle_linkedin_auth() -> LinkedInClient | None:
    """Handle LinkedIn authentication, using stored token if available."""
    client = LinkedInClient(
        LINKEDIN_CLIENT_ID,
        LINKEDIN_CLIENT_SECRET,
        LINKEDIN_REDIRECT_URI,
    )

    # Check if we already have a stored token
    stored_token = db.get_linkedin_token(DB_PATH_ABS)
    if stored_token and stored_token.get("access_token"):
        logger.info("Using stored LinkedIn access token.")
        client.set_access_token(stored_token["access_token"])
        try:
            # Verify the token is still valid
            user_info = client.get_user_info()
            logger.info("Authenticated as: %s", user_info.get("name", "Unknown"))
            return client
        except Exception:
            logger.warning("Stored token expired or invalid. Re-authenticating...")

    # Run OAuth flow
    logger.info("Need to authenticate with LinkedIn...")
    try:
        client.authenticate()
        user_info = client.get_user_info()
        logger.info("Authenticated as: %s", user_info.get("name", "Unknown"))
        # Store the token
        db.save_linkedin_token(DB_PATH_ABS, client.access_token)
        return client
    except Exception as e:
        logger.error("LinkedIn authentication failed: %s", e)
        logger.warning("You can still generate posts and save them as drafts.")
        return None


# ── Commands ───────────────────────────────────────────────────────────────


@app.command()
def generate(
    subject: Optional[str] = typer.Option(
        None,
        "--subject",
        "-s",
        help="Subject to write about. Random if omitted.",
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
    """Generate a LinkedIn post and save it as a draft."""
    logger.info("=== Command: generate ===")

    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY is not set in .env file.")
        typer.secho(
            "❌ DEEPSEEK_API_KEY is not set in .env file.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    logger.info("Initializing database...")
    db.init_db(DB_PATH_ABS)

    subjects = load_subjects()
    current_subject = subject if subject else pick_random_subject(subjects)
    logger.info("Subject picked: %.80s", current_subject)
    typer.echo(f"📌 Subject: {current_subject}")

    typer.echo("⏳ Generating post with DeepSeek...")
    raw_text = generate_post(current_subject, language or "", max_length or 0)
    if not raw_text:
        logger.error("Post generation failed.")
        typer.secho("❌ Failed to generate post.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.echo("🔄 Converting Markdown to Unicode...")
    logger.info("Converting Markdown to Unicode for LinkedIn compatibility...")
    generated_text = escape_linkedin(convert(raw_text))
    logger.info(
        "Converted: %d characters → %d characters", len(raw_text), len(generated_text)
    )

    typer.echo("⏳ Finding an image...")
    image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
    local_image_path, image_url = image_provider.fetch_image(current_subject)

    post_id = db.save_post(
        DB_PATH_ABS,
        current_subject,
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


def _run_interactive_menu(
    generated_text: str,
    current_subject: str,
    local_image_path: str | None,
    image_provider: ImageProvider,
    post_id: int,
    language: str = "",
    max_length: int = 0,
) -> tuple[str, str, str | None, int]:
    """Interactive loop to review, regenerate, or refine a post before publishing.

    Shows the post preview and offers options:
        p — Post to LinkedIn
        r — Regenerate with the same subject
        n — New random subject & regenerate
        s — Specify your own subject
        q — Quit without posting

    Returns:
        Updated (generated_text, current_subject, local_image_path, post_id).
    """
    subjects = load_subjects()

    while True:
        typer.echo("\n" + "═" * 60)
        typer.echo("   📝  POST PREVIEW")
        typer.echo("═" * 60)
        typer.echo(generated_text)
        typer.echo("\n" + "─" * 60)
        typer.echo(f"   📊 Characters: {len(generated_text)}")
        typer.echo(f"   📌 Subject: {current_subject[:70]}")
        typer.echo("─" * 60)
        typer.echo("\n🐦 Tweet card text:")
        typer.secho(subject_to_tweet(current_subject), fg=typer.colors.CYAN)
        typer.echo("─" * 60)

        typer.echo("\nOptions:")
        typer.echo("  [p]  Post to LinkedIn")
        typer.echo("  [r]  Regenerate post (same subject)")
        typer.echo("  [n]  New random subject & regenerate")
        typer.echo("  [s]  Specify your own subject")
        typer.echo("  [q]  Quit without posting")

        choice = (
            typer.prompt("\nWhat would you like to do", default="p").strip().lower()
        )

        if choice == "p":
            return generated_text, current_subject, local_image_path, post_id

        if choice == "q":
            typer.echo("👋 Exiting without posting.")
            if local_image_path:
                image_provider.cleanup(local_image_path)
            raise typer.Exit(0)

        if choice in ("r", "n", "s"):
            # Resolve the subject
            if choice == "n":
                current_subject = pick_random_subject(subjects)
                typer.echo(f"📌 New subject: {current_subject}")
            elif choice == "s":
                user_subject = typer.prompt("Enter your subject").strip()
                if not user_subject:
                    continue
                current_subject = user_subject
            # choice == "r" keeps current_subject unchanged

            # Regenerate
            typer.echo("⏳ Generating post with DeepSeek...")
            raw_text = generate_post(current_subject, language, max_length)
            if not raw_text:
                typer.secho(
                    "❌ Failed to generate post.", fg=typer.colors.RED, err=True
                )
                continue

            typer.echo("🔄 Converting Markdown to Unicode...")
            generated_text = escape_linkedin(convert(raw_text))

            # Fetch a new image
            if local_image_path:
                image_provider.cleanup(local_image_path)
            local_image_path, image_url = image_provider.fetch_image(current_subject)

            # Save the new post to the database
            post_id = db.save_post(
                DB_PATH_ABS,
                current_subject,
                generated_text,
                image_url=image_url,
                generated_raw_text=raw_text,
            )
            logger.info("New post saved (ID=%d).", post_id)
            typer.echo(f"💾 Saved as entry #{post_id}")
            continue

        typer.secho(f"❌ Unknown option: {choice}", fg=typer.colors.RED, err=True)


# ── News command helpers ────────────────────────────────────────────────────


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


@app.command()
def post(
    entry_id: Optional[int] = typer.Option(
        None,
        "--entry-id",
        "-e",
        help="Post an existing entry from the database by its ID (skips generation).",
    ),
    subject: Optional[str] = typer.Option(
        None,
        "--subject",
        "-s",
        help="Subject to write about. Random if omitted.",
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
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Review the post interactively before publishing.",
    ),
):
    """Generate a post and publish it to LinkedIn."""
    logger.info("=== Command: post ===")

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

    # ── Resolve the post to publish ────────────────────────────────────────

    if entry_id is not None:
        # Use an existing entry from the database
        entry = db.get_post_by_id(DB_PATH_ABS, entry_id)
        if not entry:
            logger.error("Entry #%d not found in database.", entry_id)
            typer.secho(
                f"❌ Entry #{entry_id} not found in database.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

        post_id = entry["id"]
        current_subject = entry["subject"]
        generated_text = entry["generated_text"]
        image_url = entry.get("image_url")
        logger.info("Using existing entry #%d: %.80s", post_id, current_subject)
        typer.echo(f"📌 Entry #{post_id}: {current_subject}")

        # Download the original image if one was saved
        local_image_path = None
        if image_url:
            logger.info("Re-downloading image from: %s", image_url)
            image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
            local_image_path, _ = image_provider.fetch_image(current_subject)
        else:
            image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
    else:
        # Generate a fresh post
        subjects = load_subjects()
        current_subject = subject if subject else pick_random_subject(subjects)
        logger.info("Subject picked: %.80s", current_subject)
        typer.echo(f"📌 Subject: {current_subject}")

        typer.echo("⏳ Generating post with DeepSeek...")
        raw_text = generate_post(current_subject, language or "", max_length or 0)
        if not raw_text:
            logger.error("Post generation failed.")
            typer.secho("❌ Failed to generate post.", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

        typer.echo("🔄 Converting Markdown to Unicode...")
        logger.info("Converting Markdown to Unicode for LinkedIn compatibility...")
        generated_text = escape_linkedin(convert(raw_text))
        logger.info(
            "Converted: %d characters → %d characters",
            len(raw_text),
            len(generated_text),
        )

        typer.echo("⏳ Finding an image...")
        image_provider = ImageProvider(UNSPLASH_ACCESS_KEY)
        local_image_path, image_url = image_provider.fetch_image(current_subject)

        post_id = db.save_post(
            DB_PATH_ABS,
            current_subject,
            generated_text,
            image_url=image_url,
            generated_raw_text=raw_text,
        )
        logger.info("Post saved to database (ID=%d).", post_id)

    # ── Interactive review ─────────────────────────────────────────────────

    if interactive:
        generated_text, current_subject, local_image_path, post_id = (
            _run_interactive_menu(
                generated_text,
                current_subject,
                local_image_path,
                image_provider,
                post_id,
                language=language or "",
                max_length=max_length or 0,
            )
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
        typer.echo(f"✅ Published! (post #{post_id}) — {current_subject[:60]}")
        typer.echo(f"   🔗 {result['post_url']}")
        logger.info("Post #%d successfully published: %s", post_id, result["post_url"])
    except Exception as e:
        logger.error("Failed to post to LinkedIn: %s", e)
        typer.secho(
            f"❌ Failed to post to LinkedIn: {e}", fg=typer.colors.RED, err=True
        )
        db.update_post_status(DB_PATH_ABS, post_id, "draft")
        raise typer.Exit(1)


@app.command()
def auth():
    """Authenticate with LinkedIn and store the access token."""
    logger.info("=== Command: auth ===")

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
    client = handle_linkedin_auth()
    if client:
        logger.info("Authentication flow completed successfully.")
        typer.echo("\n✅ Authentication successful! Token stored.")
    else:
        logger.error("Authentication flow failed.")
        raise typer.Exit(1)


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
