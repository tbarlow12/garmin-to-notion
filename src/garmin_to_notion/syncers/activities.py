"""Sync Garmin activities to the Notion Activities database."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from garminconnect import Garmin as GarminClient
from notion_client import Client as NotionClient

from garmin_to_notion.clients import call_with_retry
from garmin_to_notion.config import Settings
from garmin_to_notion.formatters import (
    format_activity_type,
    format_duration,
    format_effect_rich,
    format_pace,
    format_training_effect,
    gmt_to_local,
)
from garmin_to_notion.mappings import ACTIVITY_EMOJIS
from garmin_to_notion.notion_helpers import fetch_all_pages, get_prop

logger = logging.getLogger(__name__)

# Fetch recent-first in small batches instead of one big historical pull.
# Once a whole batch is already in Notion (by Garmin ID), we stop paging
# further back -- everything older is assumed already synced.
PAGE_SIZE = 50


def _build_properties(activity: dict, settings: Settings) -> dict:
    """Build the Notion properties payload from a Garmin activity."""
    activity_name = activity.get("activityName", "Unnamed Activity")
    activity_type, activity_subtype = format_activity_type(
        activity.get("activityType", {}).get("typeKey", "Unknown"),
        activity_name,
    )
    local_date = gmt_to_local(activity.get("startTimeGMT"), settings.timezone)

    # Heatmap properties
    day_of_week = local_date.strftime("%A")
    hour = local_date.hour
    block_start = (hour // 2) * 2
    hour_block = f"{block_start:02d}:00-{block_start + 2:02d}:00"

    return {
        "Date": {"date": {"start": local_date.isoformat()}},
        "Type": {"select": {"name": activity_type}},
        "SubType": {"select": {"name": activity_subtype}},
        "Name": {"title": [{"text": {"content": activity_name}}]},
        "Distance (km)": {"number": round(activity.get("distance", 0) / 1000, 2)},
        "Duration": {
            "rich_text": [
                {"text": {"content": format_duration(activity.get("duration", 0))}}
            ]
        },
        "Calories": {"number": round(activity.get("calories", 0))},
        "Avg Pace": {
            "rich_text": [
                {"text": {"content": format_pace(activity.get("averageSpeed", 0))}}
            ]
        },
        "Avg HR": {"number": round(activity.get("averageHR", 0) or 0)},
        "Max HR": {"number": round(activity.get("maxHR", 0) or 0)},
        "Avg Power": {"number": round(activity.get("avgPower", 0) or 0, 1)},
        "Training Effect": {
            "rich_text": [
                {
                    "text": {
                        "content": format_training_effect(
                            activity.get("trainingEffectLabel", "Unknown")
                        )
                    }
                }
            ]
        },
        "Aerobic Effect": {
            "rich_text": [
                {
                    "text": {
                        "content": format_effect_rich(
                            activity.get("aerobicTrainingEffect", 0) or 0,
                            activity.get("aerobicTrainingEffectMessage", "Unknown"),
                        )
                    }
                }
            ]
        },
        "Anaerobic Effect": {
            "rich_text": [
                {
                    "text": {
                        "content": format_effect_rich(
                            activity.get("anaerobicTrainingEffect", 0) or 0,
                            activity.get("anaerobicTrainingEffectMessage", "Unknown"),
                        )
                    }
                }
            ]
        },
        "Steps": {"number": activity.get("steps", 0) or 0},
        "Garmin ID": {"number": activity.get("activityId")},
        "Day of Week": {"select": {"name": day_of_week}},
        "Hour Block": {"select": {"name": hour_block}},
    }


def _get_icon_emoji(activity: dict) -> str:
    """Get the emoji icon for an activity based on its type."""
    activity_name = activity.get("activityName", "")
    _, activity_subtype = format_activity_type(
        activity.get("activityType", {}).get("typeKey", "Unknown"),
        activity_name,
    )
    return ACTIVITY_EMOJIS.get(activity_subtype, ACTIVITY_EMOJIS["Other"])


def _find_existing(
    by_garmin_id: dict[int, dict],
    legacy_pages: list[dict],
    garmin_id: int | None,
    activity_date: datetime,
    activity_type: str,
    activity_name: str,
) -> dict | None:
    """Find a matching existing Notion page from a preloaded snapshot.

    Primary lookup: by Garmin ID (unique, unambiguous). Fallback: date + type
    + name, scanned only against legacy entries recorded before Garmin ID
    tracking was added. Matching is always per-activity, never per-day, so a
    batch boundary landing mid-day can never cause a partially-synced day to
    look "done" to a later run.
    """
    if garmin_id and garmin_id in by_garmin_id:
        return by_garmin_id[garmin_id]

    lookup_type = (
        "Stretching" if "stretch" in activity_name.lower() else activity_type
    )
    lookup_min = activity_date - timedelta(minutes=5)
    lookup_max = activity_date + timedelta(minutes=5)

    for page in legacy_pages:
        props = page["properties"]
        if get_prop(props, "Type", "select") != lookup_type:
            continue
        if get_prop(props, "Name", "title") != activity_name:
            continue
        page_date_str = get_prop(props, "Date", "date")
        if not page_date_str:
            continue
        try:
            page_date = datetime.fromisoformat(page_date_str)
        except ValueError:
            continue
        if lookup_min <= page_date <= lookup_max:
            return page
    return None


def _activity_needs_update(
    existing: dict, new_activity: dict, settings: Settings
) -> bool:
    """Compare an existing Notion page with new Garmin data to detect changes."""
    props = existing["properties"]

    try:
        existing_date = props["Date"]["date"]["start"]
        new_date = gmt_to_local(
            new_activity.get("startTimeGMT"), settings.timezone
        ).isoformat()
        date_changed = existing_date != new_date

        distance_changed = (
            props["Distance (km)"]["number"]
            != round(new_activity.get("distance", 0) / 1000, 2)
        )
        calories_changed = (
            props["Calories"]["number"] != round(new_activity.get("calories", 0))
        )
        pace_changed = (
            props["Avg Pace"]["rich_text"][0]["text"]["content"]
            != format_pace(new_activity.get("averageSpeed", 0))
        )
        hr_changed = (
            props["Avg HR"]["number"] != round(new_activity.get("averageHR", 0) or 0)
            or props["Max HR"]["number"]
            != round(new_activity.get("maxHR", 0) or 0)
        )
        return (
            date_changed or distance_changed or calories_changed
            or pace_changed or hr_changed
        )
    except (KeyError, TypeError, IndexError):
        return True


def sync_activities(
    garmin: GarminClient,
    notion: NotionClient,
    settings: Settings,
) -> None:
    """Sync Garmin activities to the Notion Activities database.

    Fetches from Garmin in small pages, most recent first, checking each
    activity against a single preloaded snapshot of what's already in
    Notion. Stops paging further back once an entire page is already known,
    since everything older is assumed already synced -- avoiding a full
    historical re-fetch (and a Notion query per activity) on every run.
    """
    logger.info("Fetching existing activities from Notion...")
    existing_pages = fetch_all_pages(notion, settings.activities_db_id)
    by_garmin_id: dict[int, dict] = {}
    legacy_pages: list[dict] = []
    for page in existing_pages:
        garmin_id = get_prop(page["properties"], "Garmin ID", "number")
        if garmin_id:
            by_garmin_id[garmin_id] = page
        else:
            legacy_pages.append(page)
    known_ids = set(by_garmin_id.keys())
    logger.info("Found %d existing activities in Notion", len(existing_pages))

    created, updated, skipped = 0, 0, 0
    start = 0

    while start < settings.fetch_limit:
        page_limit = min(PAGE_SIZE, settings.fetch_limit - start)
        batch = call_with_retry(garmin.get_activities, start, page_limit)
        if not batch:
            break

        batch_all_known = True

        for activity in batch:
            activity_name = activity.get("activityName", "Unnamed Activity")
            activity_type, _ = format_activity_type(
                activity.get("activityType", {}).get("typeKey", "Unknown"),
                activity_name,
            )
            activity_date = gmt_to_local(activity.get("startTimeGMT"), settings.timezone)
            garmin_id = activity.get("activityId")

            if garmin_id not in known_ids:
                batch_all_known = False

            existing = _find_existing(
                by_garmin_id, legacy_pages,
                garmin_id, activity_date, activity_type, activity_name,
            )

            if existing:
                if _activity_needs_update(existing, activity, settings):
                    props = _build_properties(activity, settings)
                    emoji = _get_icon_emoji(activity)
                    notion.pages.update(
                        page_id=existing["id"],
                        properties=props,
                        icon={"emoji": emoji},
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                props = _build_properties(activity, settings)
                emoji = _get_icon_emoji(activity)
                created_page = notion.pages.create(
                    parent={"database_id": settings.activities_db_id},
                    properties=props,
                    icon={"emoji": emoji},
                )
                created += 1
                if garmin_id:
                    by_garmin_id[garmin_id] = created_page

        if len(batch) < page_limit:
            break  # Reached the end of Garmin's activity history

        if batch_all_known:
            logger.info(
                "Batch at offset %d already fully synced, stopping early", start
            )
            break

        start += page_limit

    logger.info(
        "Activities sync complete: %d created, %d updated, %d unchanged",
        created,
        updated,
        skipped,
    )
