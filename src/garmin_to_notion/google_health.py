"""Minimal client for the Google Health API (the successor to the Fitbit Web API).

The legacy Fitbit Web API and its OAuth endpoints were turned off on
2026-11-02, so Fitbit data is now read through Google OAuth and
https://health.googleapis.com/v4. This module only implements what the sleep
sync needs: refreshing an access token and listing data points.

Token handling mirrors the Garmin tokenstore: the GOOGLE_HEALTH_REFRESH_TOKEN
secret seeds a small JSON file, and any refresh token Google returns is
written back there so the GitHub Actions cache carries it to the next run.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

API_BASE = "https://health.googleapis.com/v4"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
# Resting heart rate lives under the "health metrics" scope (the mapping of
# the old Fitbit `heartrate` scope). It's optional: without it the sleep sync
# still works and just leaves Resting HR empty.
METRICS_SCOPE = (
    "https://www.googleapis.com/auth/"
    "googlehealth.health_metrics_and_measurements.readonly"
)
DEFAULT_SCOPES = (SLEEP_SCOPE, METRICS_SCOPE)

TOKENSTORE_PATH = (
    Path(os.getenv("GOOGLE_HEALTH_TOKENSTORE", "~/.google_health_tokens")).expanduser()
    / "token.json"
)


class GoogleHealthError(RuntimeError):
    """Raised for non-2xx responses from Google OAuth or the Health API."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def _request(
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Send a GET (or form POST when *data* is given) and decode the JSON reply."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req_headers = {"Accept": "application/json", **(headers or {})}
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=body, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = 2.0 * (2 ** attempt)
                logger.warning(
                    "Google Health HTTP %d, retrying in %.0fs (attempt %d/%d)",
                    e.code, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            raise GoogleHealthError(e.code, text) from None
    raise AssertionError("unreachable")


def exchange_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> dict[str, Any]:
    """Trade an authorization code for tokens (used by the setup script)."""
    return _request(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )


def build_auth_url(
    client_id: str, redirect_uri: str, scopes: tuple[str, ...] = DEFAULT_SCOPES
) -> str:
    """Build the consent URL that yields a long-lived refresh token."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": " ".join(scopes),
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _load_cached_refresh_token() -> str | None:
    try:
        return json.loads(TOKENSTORE_PATH.read_text()).get("refresh_token") or None
    except (OSError, ValueError):
        return None


def _save_refresh_token(token: str) -> None:
    try:
        TOKENSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKENSTORE_PATH.write_text(json.dumps({"refresh_token": token}))
    except OSError as e:
        logger.warning("Could not persist Google Health refresh token: %s", e)


class GoogleHealthClient:
    """Authenticated access to one user's Google Health data (users/me)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._secret_refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _refresh_with(self, refresh_token: str) -> None:
        resp = _request(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        self._access_token = resp["access_token"]
        self._expires_at = time.time() + int(resp.get("expires_in", 3600)) - 60
        # Google may hand back a new refresh token; always keep the latest.
        _save_refresh_token(resp.get("refresh_token") or refresh_token)

    def authenticate(self) -> None:
        """Get an access token, preferring the cached (most recent) refresh token.

        If the cached token has been revoked or expired, fall back to the
        secret, so updating the GOOGLE_HEALTH_REFRESH_TOKEN secret is always
        enough to recover without clearing the Actions cache.
        """
        candidates = []
        cached = _load_cached_refresh_token()
        if cached:
            candidates.append(("cached", cached))
        if self._secret_refresh_token and self._secret_refresh_token != cached:
            candidates.append(("secret", self._secret_refresh_token))
        if not candidates:
            raise GoogleHealthError(0, "no refresh token configured")

        last_error: GoogleHealthError | None = None
        for label, token in candidates:
            try:
                self._refresh_with(token)
                logger.info("Google Health auth successful (%s refresh token)", label)
                return
            except GoogleHealthError as e:
                logger.warning("Google Health refresh with %s token failed: %s", label, e)
                last_error = e
        assert last_error is not None
        raise last_error

    def _headers(self) -> dict[str, str]:
        if not self._access_token or time.time() >= self._expires_at:
            self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def list_data_points(
        self,
        data_type: str,
        *,
        filter_expr: str | None = None,
        page_size: int = 25,
        max_pages: int = 40,
    ) -> Iterator[dict[str, Any]]:
        """Yield data points of *data_type* (e.g. "sleep"), following pagination."""
        url = f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints"
        page_token: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"pageSize": page_size}
            if filter_expr:
                params["filter"] = filter_expr
            if page_token:
                params["pageToken"] = page_token
            resp = _request(
                f"{url}?{urllib.parse.urlencode(params)}", headers=self._headers()
            )
            yield from resp.get("dataPoints", [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                return
        logger.warning("Stopped paging %s after %d pages", data_type, max_pages)


# --- Parsing helpers -------------------------------------------------------


def parse_offset(value: str | None) -> timedelta:
    """Parse a protobuf Duration string such as "-25200s" into a timedelta."""
    if not value:
        return timedelta(0)
    try:
        return timedelta(seconds=float(str(value).rstrip("s")))
    except ValueError:
        return timedelta(0)


def parse_timestamp(value: str) -> datetime:
    """Parse an RFC 3339 timestamp (with Z or numeric offset) to aware UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def local_date(timestamp: str, utc_offset: str | None, fallback_tz) -> date:
    """Calendar date of *timestamp* in the wearer's local time at that moment."""
    ts = parse_timestamp(timestamp)
    if utc_offset:
        return (ts + parse_offset(utc_offset)).date()
    return ts.astimezone(fallback_tz).date()


def parse_civil_date(value: Any) -> date | None:
    """Accept either "YYYY-MM-DD" or a google.type.Date {year, month, day}."""
    if not value:
        return None
    if isinstance(value, dict):
        try:
            return date(int(value["year"]), int(value["month"]), int(value["day"]))
        except (KeyError, TypeError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
