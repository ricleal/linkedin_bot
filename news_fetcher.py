"""Fetch recent tech news from RSS feeds for the `news` command.

Inspired by https://github.com/ZainulabdeenOfficial/social-news-bot
(news_fetcher.py / config.py), trimmed down to what this bot needs:
no article-image scraping, since post images are locally rendered
tweet cards (see image_provider.py).
"""

import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta

import feedparser

logger = logging.getLogger(__name__)

# ── News sources ─────────────────────────────────────────────────────────

NEWS_SOURCES = [
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "category": "tech"},
    {
        "name": "The Verge",
        "url": "https://www.theverge.com/rss/index.xml",
        "category": "tech",
    },
    {"name": "Wired", "url": "https://www.wired.com/feed/rss", "category": "tech"},
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "tech",
    },
    {
        "name": "Engadget",
        "url": "https://www.engadget.com/rss.xml",
        "category": "tech",
    },
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of with by is are was were "
    "this that these those it its as from into after over under new "
    "says say your you our out about more what how why who when will "
    "have has had not than here there".split()
)


def strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace from an RSS summary/content field."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", text)).strip()


class NewsFetcher:
    """Fetch and rank recent tech news articles from a set of RSS feeds."""

    def __init__(self, sources: list[dict] | None = None) -> None:
        self.sources = sources if sources is not None else NEWS_SOURCES

    def fetch_news_from_source(
        self, source: dict, per_source_limit: int = 10
    ) -> list[dict]:
        """Fetch and normalize the latest entries from a single RSS source."""
        try:
            logger.info("Fetching news from %s (%s)", source["name"], source["url"])
            feed = feedparser.parse(source["url"], agent=_USER_AGENT)
            if getattr(feed, "bozo", 0):
                logger.warning(
                    "Feed for %s reported a parse issue: %s",
                    source["name"],
                    getattr(feed, "bozo_exception", "unknown"),
                )

            articles = []
            for entry in feed.entries[:per_source_limit]:
                try:
                    articles.append(
                        {
                            "title": strip_html(entry.get("title", "")),
                            "description": strip_html(entry.get("summary", "")),
                            "link": entry.get("link", ""),
                            "published": self._parse_date(entry),
                            "source": source["name"],
                            "category": source.get("category", ""),
                        }
                    )
                except Exception as exc:
                    logger.error(
                        "Error processing entry from %s: %s", source["name"], exc
                    )
            logger.info("Fetched %d articles from %s", len(articles), source["name"])
            return articles
        except Exception as exc:
            logger.error("Error fetching from %s: %s", source["name"], exc)
            return []

    def fetch_all_news(self, per_source_limit: int = 10) -> list[dict]:
        """Fetch news from all configured sources, newest first."""
        all_articles: list[dict] = []
        for source in self.sources:
            all_articles.extend(
                self.fetch_news_from_source(source, per_source_limit=per_source_limit)
            )
        all_articles.sort(key=lambda a: a["published"] or datetime.min, reverse=True)
        logger.info("Total articles fetched: %d", len(all_articles))
        return all_articles

    def get_recent_news(
        self, hours: int = 24, per_source_limit: int = 10
    ) -> list[dict]:
        """Get articles published within the last `hours` hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        all_articles = self.fetch_all_news(per_source_limit=per_source_limit)
        recent = [a for a in all_articles if a["published"] and a["published"] > cutoff]
        logger.info("Found %d recent articles (last %d hours)", len(recent), hours)
        return recent

    @staticmethod
    def get_trending_topics(articles: list[dict], top_n: int = 10) -> list[str]:
        """Extract the most frequent keywords across article titles."""
        keywords = []
        for article in articles:
            words = article["title"].lower().split()
            keywords.extend(w.strip(".,:;!?\"'()") for w in words if len(w) > 3)
        keywords = [w for w in keywords if w and w not in _STOP_WORDS]
        counts = Counter(keywords)
        return [word for word, _ in counts.most_common(top_n)]

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        """Parse an entry's publish date, preferring feedparser's struct_time fields."""
        for field in ("published_parsed", "updated_parsed"):
            struct = entry.get(field)
            if struct:
                try:
                    return datetime.fromtimestamp(time.mktime(struct))
                except (ValueError, OverflowError, OSError):
                    continue
        return None
