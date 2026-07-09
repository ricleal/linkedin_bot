"""Generate a fake tweet-card image to accompany LinkedIn posts.

Renders a Twitter/X dark-mode card using Pillow so every LinkedIn post gets
a visually consistent, branded image — no external API key required.
"""

import logging
import tempfile
import textwrap
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Twitter / X dark-mode palette ──────────────────────────────────────────
_BG = (21, 32, 43)
_WHITE = (231, 233, 234)
_GREY = (113, 118, 123)
_BLUE = (29, 155, 240)
_BORDER = (47, 51, 54)

# ── Profile identity ────────────────────────────────────────────────────────
_DISPLAY_NAME = "Ricardo Leal"
_HANDLE = "@ricferrazleal"
_AVATAR_URL = "https://unavatar.io/x/ricferrazleal"

# ── Card geometry ───────────────────────────────────────────────────────────
_CARD_W = 1200
_MARGIN = 52
_AVATAR_SIZE = 96
_GAP = 20  # gap between avatar and name column


# ── Font helpers ────────────────────────────────────────────────────────────


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return a truetype font, falling back to Pillow's built-in bitmap font."""
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates_bold if bold else candidates_regular:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    logger.debug("No system truetype font found; using Pillow default.")
    return ImageFont.load_default()


# ── Avatar helpers ──────────────────────────────────────────────────────────


def _circular_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    return mask


def _fetch_avatar() -> Image.Image | None:
    """Fetch the profile picture from unavatar.io and crop it to a circle."""
    try:
        r = requests.get(_AVATAR_URL, timeout=8)
        r.raise_for_status()
        avatar = (
            Image.open(BytesIO(r.content))
            .convert("RGBA")
            .resize((_AVATAR_SIZE, _AVATAR_SIZE), Image.LANCZOS)
        )
        avatar.putalpha(_circular_mask(_AVATAR_SIZE))
        return avatar
    except Exception as exc:
        logger.debug("Could not fetch avatar: %s", exc)
        return None


def _placeholder_avatar() -> Image.Image:
    """Blue circle with initials as a fallback avatar."""
    img = Image.new("RGBA", (_AVATAR_SIZE, _AVATAR_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, _AVATAR_SIZE, _AVATAR_SIZE), fill=_BLUE)
    font = _load_font(36, bold=True)
    initials = "RL"
    bbox = draw.textbbox((0, 0), initials, font=font)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((_AVATAR_SIZE - iw) / 2, (_AVATAR_SIZE - ih) / 2 - 2),
        initials,
        font=font,
        fill=_WHITE,
    )
    return img


# ── Tweet text helpers ──────────────────────────────────────────────────────

_HASHTAGS = "#SoftwareEngineering #Engineering #Tech"

_QUESTION_STARTERS = (
    "how ",
    "why ",
    "what ",
    "when ",
    "where ",
    "who ",
    "is ",
    "are ",
    "should ",
    "can ",
    "could ",
    "would ",
    "do ",
    "does ",
    "will ",
)


def subject_to_tweet(subject: str) -> str:
    """Turn the post subject into a punchy tweet snippet (≤ 240 chars)."""
    text = subject.strip()
    lower = text.lower()

    if any(lower.startswith(w) for w in _QUESTION_STARTERS):
        tweet = text.rstrip("?.") + "?"
    else:
        tweet = text.rstrip("?.") + "."

    # Truncate to leave room for hashtags
    max_body = 240 - len(_HASHTAGS) - 4  # 4 for "\n\n" + space
    if len(tweet) > max_body:
        tweet = tweet[: max_body - 1].rstrip() + "…"

    return f"{tweet}\n\n{_HASHTAGS}"


# ── Card renderer ───────────────────────────────────────────────────────────


def generate_tweet_image(subject: str, destination: str) -> bool:
    """Render a Twitter/X dark-mode card and save it as a PNG.

    Args:
        subject: The LinkedIn post subject line.
        destination: Output file path (should end in .png).

    Returns:
        True on success, False on failure.
    """
    tweet_text = subject_to_tweet(subject)
    date_str = datetime.now().strftime("%-I:%M %p · %b %-d, %Y")

    # Fonts
    f_name = _load_font(30, bold=True)
    f_handle = _load_font(26)
    f_tweet = _load_font(38)
    f_meta = _load_font(24)
    f_x = _load_font(26, bold=True)

    # Wrap tweet text (character-width approximation for the chosen font/card width)
    wrapped = textwrap.fill(tweet_text, width=50)

    # Measure tweet block height on a dummy canvas
    probe = ImageDraw.Draw(Image.new("RGB", (_CARD_W, 10)))
    tweet_bbox = probe.textbbox((0, 0), wrapped, font=f_tweet, spacing=10)
    tweet_h = tweet_bbox[3] - tweet_bbox[1]

    # Total card height
    card_h = (
        _MARGIN  # top padding
        + _AVATAR_SIZE  # avatar / header row
        + 28  # gap below header
        + tweet_h  # tweet body
        + 32  # gap
        + 28  # meta line height
        + _MARGIN  # bottom padding
    )

    # Canvas
    img = Image.new("RGB", (_CARD_W, card_h), _BG)
    draw = ImageDraw.Draw(img)

    # Top border accent
    draw.rectangle([(0, 0), (_CARD_W, 3)], fill=_BLUE)

    # ── Avatar ──
    avatar = _fetch_avatar() or _placeholder_avatar()
    ax, ay = _MARGIN, _MARGIN
    img.paste(avatar, (ax, ay), avatar)

    # ── Name + handle ──
    nx = ax + _AVATAR_SIZE + _GAP
    draw.text((nx, ay + 4), _DISPLAY_NAME, font=f_name, fill=_WHITE)
    draw.text((nx, ay + 42), _HANDLE, font=f_handle, fill=_GREY)

    # ── X logo (top-right) ──
    x_logo_x = _CARD_W - _MARGIN - 36
    x_logo_y = _MARGIN + 4
    draw.text((x_logo_x, x_logo_y), "\U0001d54f", font=f_x, fill=_GREY)

    # ── Tweet body ──
    ty = _MARGIN + _AVATAR_SIZE + 28
    draw.text(
        (_MARGIN, ty),
        wrapped,
        font=f_tweet,
        fill=_WHITE,
        spacing=10,
    )

    # ── Meta line ──
    my = ty + tweet_h + 32
    draw.text((_MARGIN, my), date_str, font=f_meta, fill=_GREY)

    # ── Bottom separator ──
    sep_y = my + 34
    draw.line([(_MARGIN, sep_y), (_CARD_W - _MARGIN, sep_y)], fill=_BORDER, width=1)

    try:
        img.save(destination, format="PNG", optimize=True)
        return True
    except Exception as exc:
        logger.error("Failed to save tweet card: %s", exc)
        return False


# ── Public interface (drop-in replacement for the old ImageProvider) ─────────


class ImageProvider:
    """Generate a fake tweet-card image for a LinkedIn post subject.

    The constructor accepts (and ignores) any legacy positional/keyword
    arguments so it remains a drop-in replacement for the old Unsplash-backed
    provider.
    """

    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch_image(self, subject: str) -> tuple[str | None, str | None]:
        """Generate a tweet-card PNG for *subject*.

        Returns:
            ``(local_file_path, None)`` on success, ``(None, None)`` on failure.
            The second element (image_url) is always ``None`` because the image
            is generated locally.
        """
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            ok = generate_tweet_image(subject, tmp.name)
            if ok:
                logger.info("Tweet card generated: %s", tmp.name)
                return tmp.name, None
            Path(tmp.name).unlink(missing_ok=True)
        except Exception as exc:
            logger.error("Failed to generate tweet card: %s", exc)
        return None, None

    @staticmethod
    def cleanup(path: str | Path | None) -> None:
        """Delete a temporary image file."""
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
