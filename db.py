"""SQLite database operations for LinkedIn Bot."""

import logging
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    """Initialize the database and create tables if they don't exist."""
    logger.debug("Initializing database: %s", db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            generated_text TEXT NOT NULL,
            generated_raw_text TEXT,
            status TEXT NOT NULL DEFAULT 'generated',
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            posted_at TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS linkedin_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.debug("Database initialized: %s", db_path)


def save_post(
    db_path: str,
    subject: str,
    generated_text: str,
    status: str = "generated",
    image_url: str | None = None,
    generated_raw_text: str | None = None,
) -> int:
    """Save a generated post to the database. Returns the post ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO posts (subject, generated_text, generated_raw_text, status, image_url) VALUES (?, ?, ?, ?, ?)",
        (subject, generated_text, generated_raw_text, status, image_url),
    )
    conn.commit()
    post_id = cursor.lastrowid
    conn.close()
    logger.debug("Saved post #%d (status=%s, subject=%.50s)", post_id, status, subject)
    return post_id


def update_post_status(db_path: str, post_id: int, status: str) -> None:
    """Update the status of a post."""
    logger.debug("Updating post #%d status → %s", post_id, status)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if status == "posted":
        cursor.execute(
            "UPDATE posts SET status = ?, posted_at = ? WHERE id = ?",
            (status, datetime.now(), post_id),
        )
    else:
        cursor.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id),
        )

    conn.commit()
    conn.close()
    logger.info("Post #%d status updated to %s", post_id, status)


def get_post_by_id(db_path: str, post_id: int) -> dict | None:
    """Fetch a single post by its primary key."""
    logger.debug("Fetching post #%d from database...", post_id)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, subject, generated_text, generated_raw_text, status, image_url, created_at, posted_at "
        "FROM posts WHERE id = ?",
        (post_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        logger.debug("Post #%d found (status=%s).", post_id, row["status"])
    else:
        logger.warning("Post #%d not found in database.", post_id)
    return dict(row) if row else None


def update_post_image(db_path: str, post_id: int, image_url: str) -> None:
    """Update the image_url for a post."""
    logger.debug("Updating post #%d image_url", post_id)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE posts SET image_url = ? WHERE id = ?",
        (image_url, post_id),
    )
    conn.commit()
    conn.close()
    logger.debug("Post #%d image_url updated", post_id)


def save_linkedin_token(
    db_path: str,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: str | None = None,
) -> None:
    """Save LinkedIn OAuth tokens, replacing any existing tokens."""
    logger.info("Saving LinkedIn access token to database...")
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM linkedin_tokens")
    cursor.execute(
        "INSERT INTO linkedin_tokens (access_token, refresh_token, expires_at) VALUES (?, ?, ?)",
        (access_token, refresh_token, expires_at),
    )
    conn.commit()
    conn.close()
    logger.info("LinkedIn access token saved to database.")


def get_linkedin_token(db_path: str) -> dict | None:
    """Get the stored LinkedIn OAuth token, if any."""
    logger.debug("Reading LinkedIn token from database...")
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM linkedin_tokens ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        logger.debug("LinkedIn token found in database.")
    else:
        logger.debug("No LinkedIn token in database.")
    return dict(row) if row else None


def get_post_history(
    db_path: str,
    limit: int = 10,
    status: str | None = None,
    created_after: str | None = None,
    order: str = "desc",
) -> list[dict]:
    """Get recent post history with optional filters.

    Args:
        db_path: Path to the SQLite database.
        limit: Maximum number of posts to return.
        status: Filter by post status (e.g. "posted", "draft", "generated").
        created_after: Only posts created after this ISO datetime string.
        order: Sort direction — "asc" (oldest first) or "desc" (newest first).
    """
    order_sql = "ASC" if order.lower() == "asc" else "DESC"
    logger.debug(
        "Fetching history (limit=%d, status=%s, created_after=%s, order=%s)",
        limit,
        status,
        created_after,
        order_sql,
    )

    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT id, subject, status, image_url, created_at, posted_at FROM posts"
    params: list = []
    conditions: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if created_after:
        conditions.append("created_at >= ?")
        params.append(created_after)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += f" ORDER BY created_at {order_sql} LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    logger.debug("Fetched %d posts from history.", len(rows))
    return [dict(row) for row in rows]
