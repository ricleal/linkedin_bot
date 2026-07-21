"""LinkedIn authentication command: `auth`."""

import typer

import db
from config import (
    DB_PATH_ABS,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    app,
    logger,
)
from linkedin_client import LinkedInClient

# ── Helpers ────────────────────────────────────────────────────────────────


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


# ── Command ────────────────────────────────────────────────────────────────


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
