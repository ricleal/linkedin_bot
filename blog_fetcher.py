"""Fetch recent posts from curated software-engineering blogs.

Reuses the RSS fetch/rank logic in ``news_fetcher.NewsFetcher`` — a "blog" is
just a lower-frequency content source with its own list of feeds, used by the
`--source blogs` option on the `generate`/`post` commands.

Feed URLs were verified individually (2026-07-19); Uber Engineering was
requested but has no publicly reachable RSS/Atom feed as of this writing
(every candidate path returned 404/406), so it was omitted.
"""

from news_fetcher import NewsFetcher

BLOG_SOURCES = [
    {"name": "Martin Fowler", "url": "https://martinfowler.com/feed.atom", "category": "blog"},
    {"name": "Stack Overflow Blog", "url": "https://stackoverflow.blog/feed/", "category": "blog"},
    {"name": "Meta Engineering", "url": "https://engineering.fb.com/feed/", "category": "blog"},
    {
        "name": "Pinterest Engineering",
        "url": "https://medium.com/feed/pinterest-engineering",
        "category": "blog",
    },
    {"name": "Netflix Tech Blog", "url": "https://netflixtechblog.com/feed", "category": "blog"},
    {
        "name": "AWS Architecture Blog",
        "url": "https://aws.amazon.com/blogs/architecture/feed/",
        "category": "blog",
    },
    {
        "name": "Google Developers Blog",
        "url": "https://developers.googleblog.com/feeds/posts/default",
        "category": "blog",
    },
    {
        "name": "Datadog Engineering",
        "url": "https://www.datadoghq.com/blog/engineering/index.xml",
        "category": "blog",
    },
    {
        "name": "Spotify Engineering",
        "url": "https://engineering.atspotify.com/feed/",
        "category": "blog",
    },
    {"name": "GitHub Engineering", "url": "https://github.blog/engineering/feed/", "category": "blog"},
    {
        "name": "The Pragmatic Engineer",
        "url": "https://newsletter.pragmaticengineer.com/feed",
        "category": "blog",
    },
    {"name": "Joel on Software", "url": "https://www.joelonsoftware.com/feed/", "category": "blog"},
    {"name": "High Scalability", "url": "https://feeds.feedburner.com/HighScalability", "category": "blog"},
    {"name": "Cloudflare Blog", "url": "https://blog.cloudflare.com/rss/", "category": "blog"},
    {"name": "Stripe Engineering", "url": "https://stripe.com/blog/feed.rss", "category": "blog"},
    {"name": "Slack Engineering", "url": "https://slack.engineering/feed/", "category": "blog"},
    {"name": "Dropbox Tech Blog", "url": "https://dropbox.tech/feed", "category": "blog"},
    {"name": "Etsy Code as Craft", "url": "https://codeascraft.com/feed/", "category": "blog"},
]


class BlogFetcher(NewsFetcher):
    """Fetch and rank recent posts from curated engineering blogs."""

    def __init__(self) -> None:
        super().__init__(sources=BLOG_SOURCES)
