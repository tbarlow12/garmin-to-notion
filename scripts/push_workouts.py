#!/usr/bin/env python3
"""Upload the boot camp circuits to Garmin Connect as strength workouts.

Workouts land in Garmin Connect under Training > Workouts. Open one on the
phone app and tap "Send to Device", or pass --schedule YYYY-MM-DD to put
them on the Garmin calendar (scheduled workouts sync to the watch).

Re-running is safe: a workout with the same name is updated in place
rather than duplicated.

Usage:
    PYTHONPATH=src python scripts/push_workouts.py --dry-run   # print JSON only
    PYTHONPATH=src python scripts/push_workouts.py             # upload / update
    PYTHONPATH=src python scripts/push_workouts.py --only 1    # just circuit 1

Auth is the same as the sync: GARMIN_EMAIL / GARMIN_PASSWORD, plus the
GARMIN_TOKENS secret or a cached tokenstore (see scripts/generate_token.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from garmin_to_notion.bootcamp import CIRCUITS, to_payload

logger = logging.getLogger("push_workouts")


def _login():
    from garminconnect import Garmin

    from garmin_to_notion.clients import TOKENSTORE_PATH, _seed_tokenstore_from_env

    _seed_tokenstore_from_env()
    garmin = Garmin(os.getenv("GARMIN_EMAIL", ""), os.getenv("GARMIN_PASSWORD", ""))
    garmin.login(tokenstore=str(TOKENSTORE_PATH))
    try:
        TOKENSTORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        garmin.client.dump(str(TOKENSTORE_PATH))
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not persist tokenstore: %s", e)
    logger.info("Logged in to Garmin Connect as %s", garmin.display_name)
    return garmin


def _existing_by_name(garmin) -> dict[str, int]:
    found: dict[str, int] = {}
    start = 0
    while True:
        page = garmin.get_workouts(start, 100, my_workouts_only=True) or []
        for w in page:
            found.setdefault(w.get("workoutName", ""), w["workoutId"])
        if len(page) < 100:
            return found
        start += 100


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Print payloads, don't upload")
    parser.add_argument("--only", type=int, action="append", help="Circuit number(s), e.g. --only 1")
    parser.add_argument("--schedule", metavar="YYYY-MM-DD", help="Also schedule on this date")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    circuits = [c for i, c in enumerate(CIRCUITS, 1) if not args.only or i in args.only]
    payloads = [to_payload(c) for c in circuits]

    if args.dry_run:
        print(json.dumps(payloads, indent=2))
        return 0

    garmin = _login()
    existing = _existing_by_name(garmin)

    for payload in payloads:
        name = payload["workoutName"]
        workout_id = existing.get(name)
        if workout_id:
            garmin.update_workout(workout_id, {**payload, "workoutId": workout_id})
            logger.info("Updated  %s (id %s)", name, workout_id)
        else:
            created = garmin.upload_workout(payload)
            workout_id = created["workoutId"]
            logger.info("Created  %s (id %s)", name, workout_id)
        if args.schedule:
            garmin.schedule_workout(workout_id, args.schedule)
            logger.info("Scheduled %s on %s", name, args.schedule)

    return 0


if __name__ == "__main__":
    sys.exit(main())
