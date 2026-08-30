"""Garmin and Notion client initialization."""

from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

from garmin_to_notion.config import Settings

logger = logging.getLogger(__name__)

TOKENSTORE_PATH = (
    Path(os.getenv("GARMIN_TOKENSTORE", "~/.garmin_tokens")).expanduser()
    / "garmin_tokens.json"
)


@dataclass
class Clients:
    garmin: GarminClient
    notion: NotionClient


def _seed_tokenstore_from_env() -> None:
    """Write the GARMIN_TOKENS secret to the tokenstore path if nothing is cached there.

    The GitHub Actions cache restores a previously-refreshed tokenstore
    before this runs; only a cold cache (or a first run) needs the secret
    as the initial seed. Once seeded, garminconnect's own login() takes
    over: it refreshes the token in place via the (non-rate-limited) DI
    refresh endpoint, and only falls back to a full credential login if
    that refresh isn't possible.
    """
    if TOKENSTORE_PATH.exists():
        return
    raw = os.getenv("GARMIN_TOKENS", "").strip()
    if not raw:
        return
    try:
        token_json = base64.b64decode(raw).decode()
    except Exception as e:
        logger.warning("Failed to decode GARMIN_TOKENS: %s", e)
        return
    TOKENSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKENSTORE_PATH.write_text(token_json)
    logger.info("Seeded tokenstore from GARMIN_TOKENS secret")


def init_clients(settings: Settings) -> Clients:
    """Initialize and authenticate both Garmin and Notion clients.

    garminconnect's own login() handles the full auth chain: load the
    cached tokenstore, proactively refresh it if expiring soon, and only
    fall back to a fresh username/password login (via several TLS-fingerprint
    strategies) if the cached token is unusable. No prompt_mfa is supplied
    here, since an MFA challenge can't be completed non-interactively in
    CI -- if one is required, login() raises a clear authentication error
    instead of silently hanging or succeeding with a dead session.
    """
    logger.info("Authenticating with Garmin Connect...")
    _seed_tokenstore_from_env()

    garmin = GarminClient(settings.garmin_email, settings.garmin_password)
    try:
        garmin.login(tokenstore=str(TOKENSTORE_PATH))
    except Exception as e:
        logger.error("Garmin authentication failed: %s", e)
        raise SystemExit(1) from e

    logger.info("Garmin auth successful (user: %s)", garmin.display_name)

    # Persist whatever token state resulted (refreshed or freshly logged in)
    # so the next run's restored cache is as current as possible.
    try:
        TOKENSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        garmin.client.dump(str(TOKENSTORE_PATH))
    except Exception as e:
        logger.debug("Could not persist refreshed tokenstore: %s", e)

    return Clients(garmin=garmin, notion=NotionClient(auth=settings.notion_token))


def call_with_retry(func, *args, max_retries: int = 3, base_delay: float = 5.0, **kwargs):
    """Call a Garmin API function, retrying on transient 429 rate-limit errors."""
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                wait = base_delay * (2 ** attempt)
                logger.warning(
                    "Garmin rate limited, retrying in %.0fs (attempt %d/%d)...",
                    wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
            else:
                raise


def init_notion_only(settings: Settings) -> NotionClient:
    """Initialize only the Notion client (for tools that don't need Garmin)."""
    return NotionClient(auth=settings.notion_token)
