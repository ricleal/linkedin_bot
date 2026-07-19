"""Shared configuration, constants, and Typer app instance for LinkedIn Bot.

Every command module (linkedin_commands.py, news_commands.py) and the main
entry point (main.py) import from here, so this module must stay free of
imports from those other modules to avoid circular imports.
"""

import logging
import os
import random
import sys
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

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


# ── Shared helpers ───────────────────────────────────────────────────────────


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
