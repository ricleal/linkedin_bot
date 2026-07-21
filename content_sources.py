"""Shared content-generation and source-selection helpers for `generate`/`post`.

Three content sources are supported (see the `Source` enum below):
  - "subjects": a curated list of software-engineering topics (subjects.yaml)
  - "news":     recent tech news articles (RSS, see news_fetcher.py)
  - "blogs":    recent posts from curated engineering blogs (RSS, see blog_fetcher.py)

Text generation and LinkedIn-formatting for "news" and "blogs" share the same
code path (an "article" is just a dict with title/description/source/link),
while "subjects" generation works from a plain topic string.
"""

from collections import Counter
from enum import Enum

import typer
from openai import OpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, MAX_POST_LENGTH, POST_LANGUAGE, logger
from converter import convert, escape_linkedin
from news_fetcher import NewsFetcher


class Source(str, Enum):
    subjects = "subjects"
    news = "news"
    blogs = "blogs"


# Default RSS look-back window, in hours, when the user doesn't pass --hours.
# Blogs post far less often than news outlets, so they get a longer default.
DEFAULT_HOURS = {Source.news: 24, Source.blogs: 24 * 14}


# ── DeepSeek generation ─────────────────────────────────────────────────────


def _chat_completion(system_prompt: str, user_prompt: str, length: int) -> str | None:
    """Call the DeepSeek chat API and return the stripped content, or None on failure."""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")
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


def generate_subject_post(subject: str, language: str = "", max_length: int = 0) -> str | None:
    """Generate a LinkedIn post about a subject/topic using the DeepSeek API."""
    lang = language or POST_LANGUAGE
    length = max_length or MAX_POST_LENGTH

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
    return _chat_completion(system_prompt, user_prompt, length)


def generate_article_post(article: dict, language: str = "", max_length: int = 0) -> str | None:
    """Generate a LinkedIn post reacting to a news/blog article using the DeepSeek API.

    Args:
        article: A dict with at least "title", "description", "source" keys
            (as produced by ``news_fetcher.NewsFetcher``/``blog_fetcher.BlogFetcher``).
    """
    lang = language or POST_LANGUAGE
    length = max_length or MAX_POST_LENGTH

    system_prompt = (
        f"You are an expert LinkedIn content creator who writes sharp commentary "
        f"on tech news and engineering blog posts. Write engaging, professional "
        f"LinkedIn posts in {lang} that react to an article — briefly summarizing "
        f"what it's about and adding your own insight, opinion, or implications "
        f"for software engineers and the tech industry. Use a natural, "
        f"conversational tone. Keep the post under {length} characters. "
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
        f"Write a LinkedIn post reacting to the following article:\n\n"
        f"Title: {article.get('title', '')}\n"
        f"Source: {article.get('source', '')}\n"
        f"Summary: {(article.get('description') or '')[:1500]}\n\n"
        f"Make it engaging and thought-provoking for other software engineers."
    )

    logger.info(
        "Calling DeepSeek API for article post (model=%s, max_tokens=%d, lang=%s)...",
        DEEPSEEK_MODEL,
        min(length, 4096),
        lang,
    )
    return _chat_completion(system_prompt, user_prompt, length)


def finalize_text(source: Source, raw_text: str, article: dict | None = None) -> str:
    """Apply Markdown→Unicode conversion, source attribution, and LinkedIn escaping.

    MUST be used on every generated post before it's sent to
    ``linkedin_client.create_post()`` — LinkedIn truncates the rendered post at
    the first unescaped reserved character otherwise (see escape_linkedin docs).
    """
    text = convert(raw_text)
    if source != Source.subjects and article and article.get("source"):
        text = f"{text}\n\n— via {article['source']}"
    return escape_linkedin(text)


# ── Article selection (news/blogs) ──────────────────────────────────────────


def order_by_trending(articles: list[dict], keywords: list[str]) -> list[dict]:
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


def auto_pick_article(fetcher: NewsFetcher, hours: int) -> dict | None:
    """Non-interactively pick the top trending article, or the most recent one.

    Used by --auto: fetches recent articles and returns the single best match
    with no user prompts.
    """
    articles = fetcher.get_recent_news(hours=hours)
    if not articles:
        return None
    keywords = fetcher.get_trending_topics(articles)
    ordered = order_by_trending(articles, keywords)
    return ordered[0]


def select_article(fetcher: NewsFetcher, hours: int, limit: int, label: str) -> dict | None:
    """Interactive loop to list recent/trending articles and let the user pick one.

    Args:
        label: Display label for the header, e.g. "NEWS" or "BLOG".

    Returns the chosen article dict, or None if the user quit.
    """
    mode = "recent"

    while True:
        typer.echo(f"⏳ Fetching latest {label.lower()}...")
        articles = fetcher.get_recent_news(hours=hours)
        if not articles:
            typer.secho(
                f"❌ No articles found in the last {hours}h.",
                fg=typer.colors.RED,
                err=True,
            )
            return None

        keywords = fetcher.get_trending_topics(articles)
        ordered = order_by_trending(articles, keywords) if mode == "trending" else articles
        display = ordered[:limit]

        typer.echo("\n" + "═" * 60)
        typer.echo(f"   📰  {'TRENDING' if mode == 'trending' else 'RECENT'} {label}")
        typer.echo("═" * 60)
        source_counts = Counter(a["source"] for a in articles)
        typer.echo(
            "📊 Sources: "
            + ", ".join(f"{name} ({count})" for name, count in source_counts.most_common())
        )
        typer.echo("─" * 60)
        if keywords:
            typer.echo(f"🔥 Trending keywords: {', '.join(keywords)}")
            typer.echo("─" * 60)
        for i, article in enumerate(display, start=1):
            published = (
                article["published"].strftime("%Y-%m-%d %H:%M") if article["published"] else "?"
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

        choice = typer.prompt("\nWhat would you like to do", default="1").strip().lower()

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
            typer.secho(f"❌ Invalid selection: {choice}", fg=typer.colors.RED, err=True)
            continue

        typer.secho(f"❌ Unknown option: {choice}", fg=typer.colors.RED, err=True)
