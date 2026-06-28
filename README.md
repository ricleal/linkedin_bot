# LinkedIn Bot 🚀

AI-powered LinkedIn post generator using **DeepSeek** for content creation and the **official LinkedIn API** for publishing.

## Features

- 🤖 Generates engaging tech posts via DeepSeek API
- 🎛️  Typer CLI — clean subcommand-based interface
- 📚 340+ curated software engineering subjects across 10+ categories
- 💾 SQLite database — tracks every post with status and timestamps
- 🔐 OAuth 2.0 with token persistence (no repeated logins)
- 🖼️  Unsplash image integration for post visuals
- 📋 Full-featured history viewer with filters and detail view

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A [DeepSeek API key](https://platform.deepseek.com/)
- A [LinkedIn Developer App](https://www.linkedin.com/developers/apps/) with the
  **Sign In With LinkedIn using OpenID Connect** and **Share on LinkedIn** API products enabled

## Setup

```bash
# Clone / enter the project
cd linkedin-bot

# Sync dependencies
uv sync

# Configure credentials (edit the file)
cp .env.template .env
```

### `.env` configuration

```env
# LinkedIn API Credentials
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_REDIRECT_URI=http://localhost:8080/callback

# DeepSeek API
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-chat

# Post Configuration
MAX_POST_LENGTH=3000
POST_LANGUAGE=en

# Unsplash API (optional — enables image search)
UNSPLASH_ACCESS_KEY=

# Database
DB_PATH=posts.db

# Logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO
```

> **LinkedIn OAuth scopes required:** `openid`, `profile`, `w_member_social`, `email`

## Usage

The CLI is built with [Typer](https://typer.tiangolo.com/) and offers several subcommands:

```bash
# ── Post to LinkedIn ─────────────────────────────────────────────────────

# Generate a fresh post and publish it
uv run python main.py post

# Publish an existing entry from the database by its ID
uv run python main.py post --entry-id 5

# Use a specific subject
uv run python main.py post --subject "Microservices architecture"

# Override language or max length
uv run python main.py post --language pt --max-length 2000

# ── Generate (local preview, no LinkedIn) ───────────────────────────────

# Generate a post and print it (saves to DB as draft)
uv run python main.py generate

# Generate with a specific subject
uv run python main.py generate --subject "Rust vs Go in 2026"

# ── Authentication ──────────────────────────────────────────────────────

# Authenticate with LinkedIn (stores token for future use)
uv run python main.py auth

# ── History ─────────────────────────────────────────────────────────────

# Show last 10 posts
uv run python main.py history

# Show last 20 posts
uv run python main.py history --limit 20

# Filter by status
uv run python main.py history --status posted
uv run python main.py history --status draft

# Filter by date (ISO format)
uv run python main.py history --created-after 2026-06-01

# Sort oldest first
uv run python main.py history --order asc

# View full content of a specific entry
uv run python main.py history --view 5

# Combine filters
uv run python main.py history --status posted --limit 5 --order asc

# ── Subjects ────────────────────────────────────────────────────────────

# List all available subjects
uv run python main.py subjects
```

### First-time setup

1. **Authenticate** with LinkedIn: `uv run python main.py auth`
   - Opens your browser for OAuth authorization.
   - The token is stored locally; you won't need to re-authenticate unless it expires.

2. **Post to LinkedIn**: `uv run python main.py post`
   - Generates a post and publishes it immediately.

3. **Preview a post** (without posting): `uv run python main.py generate`
   - Generates content via DeepSeek, saves to DB, and prints it to stdout.

#### Crontab example

```cron
# Post every Monday and Thursday at 10 AM ET (peak engagement)
0 10 * * 1,4 cd /home/leal/git/PythonCode/LinkedInBot && /home/leal/git/PythonCode/LinkedInBot/.venv/bin/python main.py post >> /tmp/linkedin-bot.log 2>&1
```

> Use the **full path** to `.venv/bin/python` in cron since it doesn't source your shell.

## Project structure

```
linkedin-bot/
├── main.py              # Entry point — Typer CLI with 5 commands
├── linkedin_client.py   # LinkedIn API wrapper (official client library)
├── db.py                # SQLite operations (posts, tokens)
├── image_provider.py    # Unsplash image search and download
├── converter.py         # Markdown to Unicode for LinkedIn compatibility
├── subjects.yaml        # 340+ curated post subjects
├── .env.template        # Environment variable template
├── pyproject.toml       # Project metadata and dependencies
├── subjects.yaml        # 241 post subjects across 18 categories
├── .env                 # API keys and configuration (git-ignored)
├── .gitignore
├── pyproject.toml       # Project metadata and dependencies
├── uv.lock              # Locked dependency versions
└── README.md
```

## Subjects categories

| Category | # | Topics |
|---|---|---|
| General Software Engineering | 30 | Clean code, microservices, testing, code review |
| System Design | 15 | URL shorteners, CDN, payment systems, ride-sharing |
| Distributed Systems | 13 | Raft, CRDTs, gossip protocols, split-brain |
| Streaming & Event Processing | 20 | Kafka failures, Flink checkpoints, exactly-once |
| Kubernetes & Cloud Native | 14 | Scheduling, eBPF, service mesh, GitOps |
| Cloud Cost Optimization & Multi-Cloud | 12 | Cloud exit stories, FinOps, egress fees |
| Cloud Security & CSPM | 10 | OPA/Rego, JIT access, IaC security, zero trust |
| Infrastructure as Code | 10 | Terraform, Pulumi, CloudFormation, drift detection |
| Data Engineering & Warehousing | 13 | ELT/ETL, BigQuery, Spark, data catalogs, Arrow |
| Workflow Engines & Durable Execution | 8 | Temporal, DBOS, Sagas, Airflow |
| Databases | 15 | Sharding, CDC, NewSQL, zero-downtime migrations |
| Scalability from Industry Leaders | 15 | Netflix, Stripe, GitHub, Cloudflare |
| Software Architecture & Engineering | 15 | CQRS, hexagonal, chaos engineering, DDD |
| DevOps, SRE & Observability | 11 | SLOs, OpenTelemetry, DORA metrics |
| Emerging Tech & Career | 10 | AI assistants, tech lead transition |
| Programming Languages & Ecosystems | 12 | Go, Python, FastAPI, Pydantic, PydanticAI |
| Scientific Computing & Open Source | 10 | NumPy/SciPy, CUDA, research software, OSS |
| Task Queues & Background Processing | 8 | Celery, Airflow, Beam, job scheduling |

## Database

Posts are stored in `posts.db` (SQLite) with the following schema:

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-increment primary key |
| `subject` | TEXT | The subject/topic |
| `generated_text` | TEXT | The full generated post |
| `status` | TEXT | `generated`, `posted`, `draft`, `discarded`, or `regenerated` |
| `created_at` | TIMESTAMP | When the post was generated |
| `posted_at` | TIMESTAMP | When (if) it was posted to LinkedIn |

OAuth tokens are stored separately in the `linkedin_tokens` table.

## Troubleshooting

### 426 Upgrade Required

The LinkedIn API version was out of date. Update `API_VERSION` in
`linkedin_client.py` to the current month (format `YYYYMM`, e.g. `202506`).

### "No stored LinkedIn token" in auto mode

Run interactive mode once to complete the OAuth flow and cache your token:

```bash
uv run python main.py
```

### LinkedIn post not appearing

Check the database status — if it says `posted` but you don't see it on LinkedIn,
verify your LinkedIn Developer App has the **Share on LinkedIn** API product enabled
and the `w_member_social` scope is authorized.
