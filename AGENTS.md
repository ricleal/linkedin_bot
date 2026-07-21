# AGENTS.md

## What this is

A CLI that generates tech-focused LinkedIn posts with DeepSeek (OpenAI-compatible API) and
publishes them via the official LinkedIn API. `generate`/`post` take a `--source
subjects|news|blogs` option: write about a random/chosen subject (`subjects.yaml`), or react
to a recent article pulled from RSS feeds (tech news outlets, or curated engineering blogs).
`--auto` skips all prompts for unattended/cron use. Every generated/posted entry is tracked
in a local SQLite DB (`posts.db`).

## Why it's structured this way

- `config.py` is a dependency-free leaf module: env loading, constants, logging, and the
  shared Typer `app` instance all live here. `linkedin_commands.py`, `post_commands.py`, and
  `main.py` each `import app from config` and register commands on it. **Do not move `app`
  into `main.py`** — a command module importing `main` would re-run it under a second module
  name (`main` vs `__main__`), creating a duplicate `app` with no commands.
- `content_sources.py` holds source-agnostic generation/selection logic shared by the
  `subjects`/`news`/`blogs` sources (a `Source` enum). `news_fetcher.py` and `blog_fetcher.py`
  both fetch RSS feeds; `BlogFetcher` is a thin subclass of `NewsFetcher` with its own source
  list — don't duplicate the fetch/rank logic when adding a new RSS-based source.
- `converter.py`'s `escape_linkedin()` must be applied (after `convert()`) to every post body
  sent to `linkedin_client.create_post()`. LinkedIn silently truncates the rendered post at
  the first unescaped reserved character (`()*[]{}<>@|~_`), even though the API call itself
  returns 201. This has bitten us in production — don't skip it when adding new post paths.

## How to build/run/verify

- Dependency manager is `uv`, not `pip`. Install/sync: `uv sync`. Run anything with
  `uv run python main.py <command>` (never call `python` directly, and never `pip install`).
- No automated test suite exists yet. Verify changes by running the CLI directly, e.g.
  `uv run python main.py --help` and `uv run python main.py <command> --help` to confirm
  commands still register, plus a real dry run of the affected command where feasible.
- Secrets/config come from `.env` (see `.env.template`) — never hardcode credentials.
