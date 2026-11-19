"""Sync Fitbit sleep (via the Google Health API) to the Notion Sleep database.

Rows use the same shape as the Garmin sleep sync, keyed by the local date the
sleep *ended* (the wake-up date), which is also how Garmin's calendarDate is
defined. That shared key is the dedup rule: one row per night, and whichever
source writes a night first owns it. The CLI runs this before the Garmin sleep
sync, so on nights recorded by both devices the Fitbit night wins.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from notion_client import Client as NotionClient

from garmin_to_notion.config import Settings
from garmin_to_notion.formatters import format_duration
from garmin_to_notion.google_health import (
    GoogleHealthClient,
    GoogleHealthError,
    local_date,
    parse_civil_date,
    parse_timestamp,
)
from garmin_to_notion.syncers.sleep import (
    _compute_sleep_score,
    _get_existing_sleep_dates,
)

logger = logging.getLogger(__name__)

# Stage type -> bucket. CLASSIC sessions (no HRV-based staging) only report
# ASLEEP / RESTLESS / AWAKE; ASLEEP is counted as light sleep.
STAGE_BUCKETS = {
    "DEEP": "deep",
    "LIGHT": "light",
    "REM": "rem",
    "AWAKE": "awake",
    "ASLEEP": "light",
    "RESTLESS": "awake",
}


def _as_int(value: Any) -> int:
    """Google returns int64 fields as strings ("455"); normalize to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _stage_seconds(sleep: dict) -> dict[str, int]:
    """Seconds per bucket, from stagesSummary when present, else from stages."""
    totals = {"deep": 0, "light": 0, "rem": 0, "awake": 0}
    summary = (sleep.get("summary") or {}).get("stagesSummary") or []
    if summary:
        for item in summary:
            bucket = STAGE_BUCKETS.get(item.get("type", ""))
            if bucket:
                totals[bucket] += _as_int(item.get("minutes")) * 60
        return totals
    for stage in sleep.get("stages") or []:
        bucket = STAGE_BUCKETS.get(stage.get("type", ""))
        if not bucket or not stage.get("startTime") or not stage.get("endTime"):
            continue
        delta = parse_timestamp(stage["endTime"]) - parse_timestamp(stage["startTime"])
        totals[bucket] += max(0, int(delta.total_seconds()))
    return totals


def _is_main_sleep(metadata: dict) -> bool | None:
    """The docs name this flag both `mainSleep` and `main`; accept either."""
    for key in ("mainSleep", "main"):
        if key in metadata:
            return bool(metadata[key])
    return None


def _wake_date(sleep: dict, settings: Settings) -> date | None:
    interval = sleep.get("interval") or {}
    if interval.get("endTime"):
        return local_date(
            interval["endTime"], interval.get("endUtcOffset"), settings.timezone
        )
    return parse_civil_date(interval.get("civilEndTime"))


def _pick_nightly_sessions(
    points: list[dict], settings: Settings
) -> dict[str, dict]:
    """Group sleep sessions by wake date and keep the main one for each night."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        sleep = point.get("sleep") or {}
        metadata = sleep.get("metadata") or {}
        if metadata.get("nap"):
            continue
        d = _wake_date(sleep, settings)
        if d:
            by_date[d.isoformat()].append(sleep)

    chosen: dict[str, dict] = {}
    for date_str, sessions in by_date.items():
        flagged = [s for s in sessions if _is_main_sleep(s.get("metadata") or {})]
        pool = flagged or sessions
        chosen[date_str] = max(
            pool, key=lambda s: _as_int((s.get("summary") or {}).get("minutesAsleep"))
        )
    return chosen


def _build_properties(
    date_str: str, sleep: dict, resting_hr: int | None
) -> dict | None:
    stages = _stage_seconds(sleep)
    summary = sleep.get("summary") or {}
    total_sleep = _as_int(summary.get("minutesAsleep")) * 60 or (
        stages["deep"] + stages["light"] + stages["rem"]
    )
    if total_sleep == 0:
        logger.info("Skipping Fitbit sleep for %s (total sleep is 0)", date_str)
        return None

    awake = stages["awake"] or _as_int(summary.get("minutesAwake")) * 60
    score = _compute_sleep_score(stages["deep"], stages["light"], stages["rem"], awake)

    def text(seconds: int) -> dict:
        return {"rich_text": [{"text": {"content": format_duration(seconds)}}]}

    props = {
        "Name": {"title": [{"text": {"content": format_duration(total_sleep)}}]},
        "Date": {"date": {"start": date_str}},
        "Duration": text(total_sleep),
        "Deep": text(stages["deep"]),
        "Light": text(stages["light"]),
        "REM": text(stages["rem"]),
        "Awake": text(awake),
        "Score": {"number": score},
    }
    if resting_hr:
        props["Resting HR"] = {"number": resting_hr}
    return props


def _fetch_resting_hr(
    client: GoogleHealthClient, since: date
) -> dict[str, int]:
    """Best-effort {date: bpm}; returns {} if the scope or data isn't available."""
    result: dict[str, int] = {}
    filters = [f'daily_resting_heart_rate.date >= "{since.isoformat()}"', None]
    for filter_expr in filters:
        try:
            for point in client.list_data_points(
                "daily-resting-heart-rate",
                filter_expr=filter_expr,
                page_size=100,
                max_pages=1 if filter_expr is None else 10,
            ):
                rhr = point.get("dailyRestingHeartRate") or {}
                d = parse_civil_date(rhr.get("date"))
                bpm = _as_int(rhr.get("beatsPerMinute"))
                if d and d >= since and bpm:
                    result[d.isoformat()] = bpm
            return result
        except GoogleHealthError as e:
            if e.status == 400 and filter_expr is not None:
                logger.debug("RHR filter rejected, retrying unfiltered: %s", e)
                continue
            logger.info("Resting HR unavailable from Google Health (%s); skipping", e)
            return {}
    return result


def sync_fitbit_sleep(notion: NotionClient, settings: Settings) -> None:
    """Create Notion Sleep rows for Fitbit nights not already in the database."""
    if not settings.sleep_db_id:
        logger.info("No sleep database configured, skipping Fitbit sleep")
        return

    client = GoogleHealthClient(
        settings.google_health_client_id,
        settings.google_health_client_secret,
        settings.google_health_refresh_token,
    )
    client.authenticate()

    existing = _get_existing_sleep_dates(notion, settings.sleep_db_id)
    logger.info("Found %d existing sleep entries in Notion", len(existing))

    today = datetime.now(tz=settings.timezone).date()
    since = today - timedelta(days=settings.fitbit_days_back)
    # Filter on end time with a day of slack so a night ending early on the
    # first day of the window (in any timezone) is still included.
    start = datetime.combine(since - timedelta(days=1), datetime.min.time(), timezone.utc)
    filter_expr = f'sleep.interval.end_time >= "{start.strftime("%Y-%m-%dT%H:%M:%SZ")}"'

    points = list(client.list_data_points("sleep", filter_expr=filter_expr))
    nights = _pick_nightly_sessions(points, settings)
    logger.info(
        "Fetched %d Fitbit sleep sessions covering %d nights", len(points), len(nights)
    )

    missing = sorted(
        d for d in nights if d not in existing and date.fromisoformat(d) >= since
    )
    resting_hr = _fetch_resting_hr(client, since) if missing else {}

    created = 0
    for date_str in missing:
        props = _build_properties(date_str, nights[date_str], resting_hr.get(date_str))
        if not props:
            continue
        notion.pages.create(
            parent={"database_id": settings.sleep_db_id}, properties=props
        )
        created += 1

    logger.info(
        "Fitbit sleep sync complete: %d created, %d nights already in Notion",
        created, len(nights) - len(missing),
    )
