#!/usr/bin/env python3
"""Manage Garmin Connect workouts: list, show, pull, push, delete, schedule.

Workouts are described as small YAML specs (format: reference.md next to this file).
Garmin is the source of truth: pull a workout to a file, edit it, push it
back. Pushing a spec with an ``id`` updates that workout in place (calendar
entries keep pointing at it); a spec without one is matched by exact name,
or created, and its new id is written back into the file.

Usage (from the repo root; needs `pip install -r requirements.txt`):
    python .claude/skills/garmin-workouts/workouts.py list [--search TEXT]
    python .claude/skills/garmin-workouts/workouts.py show ID|NAME [--json]
    python .claude/skills/garmin-workouts/workouts.py pull ID|NAME... [--dir workouts] | --all
    python .claude/skills/garmin-workouts/workouts.py push FILE... [--dry-run] [--schedule YYYY-MM-DD]
    python .claude/skills/garmin-workouts/workouts.py validate FILE...
    python .claude/skills/garmin-workouts/workouts.py delete ID|NAME... [--yes]
    python .claude/skills/garmin-workouts/workouts.py schedule ID|NAME|FILE [YYYY-MM-DD...] [--weekly mon,wed,fri --weeks 8 --start DATE]
    python .claude/skills/garmin-workouts/workouts.py calendar [--from DATE] [--to DATE]
    python .claude/skills/garmin-workouts/workouts.py unschedule SCHEDULE_ID... | --workout REF [--from --to] [--yes]
    python .claude/skills/garmin-workouts/workouts.py send ID|NAME   # push to the watch now
    python .claude/skills/garmin-workouts/workouts.py exercises TERM

Auth: the GARMIN_TOKENS env var (base64 tokenstore from
scripts/generate_token.py) or a cached tokenstore at GARMIN_TOKENSTORE,
falling back to GARMIN_EMAIL / GARMIN_PASSWORD. Same as the sync.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from workout_spec import SpecError, from_garmin, to_payload

logger = logging.getLogger("workouts")
HERE = Path(__file__).resolve().parent
DEFAULT_DIR = HERE / "workouts"


# --- Garmin -----------------------------------------------------------------


def login():
    from garminconnect import Garmin

    tokenstore = Path(os.getenv("GARMIN_TOKENSTORE", "~/.garmin_tokens")).expanduser() / "garmin_tokens.json"
    raw = os.getenv("GARMIN_TOKENS", "").strip()
    if raw and not tokenstore.exists():
        tokenstore.parent.mkdir(parents=True, exist_ok=True)
        tokenstore.write_text(base64.b64decode(raw).decode())
    garmin = Garmin(os.getenv("GARMIN_EMAIL", ""), os.getenv("GARMIN_PASSWORD", ""))
    try:
        garmin.login(tokenstore=str(tokenstore))
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"Garmin login failed: {e}\n"
            "The saved token has probably expired. Regenerate it with "
            "scripts/generate_token.py and update GARMIN_TOKENS."
        )
    try:
        garmin.client.dump(str(tokenstore))
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not persist tokenstore: %s", e)
    return garmin


def all_workouts(garmin) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        page = garmin.get_workouts(start, 100, my_workouts_only=True) or []
        out.extend(page)
        if len(page) < 100:
            return out
        start += 100


def find_workout(garmin, ref: str, workouts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A workout summary by id, exact name, or unique case-insensitive name fragment."""
    workouts = workouts if workouts is not None else all_workouts(garmin)
    if str(ref).isdigit():
        for w in workouts:
            if str(w["workoutId"]) == str(ref):
                return w
        return garmin.get_workout_by_id(int(ref))
    exact = [w for w in workouts if w.get("workoutName") == ref]
    if len(exact) == 1:
        return exact[0]
    partial = [w for w in workouts if ref.lower() in (w.get("workoutName") or "").lower()]
    if len(exact) > 1 or len(partial) > 1:
        names = "\n  ".join(f"{w['workoutId']}  {w['workoutName']}" for w in (exact or partial))
        sys.exit(f"{ref!r} matches several workouts, use an id:\n  {names}")
    if not partial:
        sys.exit(f"No workout matches {ref!r}")
    return partial[0]


# --- Files ------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    pass


def _str_rep(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_rep)


def dump_spec(spec: dict[str, Any]) -> str:
    return yaml.dump(spec, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text()
    spec = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(spec, dict):
        raise SpecError(f"{path}: expected a mapping at the top level")
    return spec


def write_id(path: Path, workout_id: int) -> None:
    """Record a newly created workout's id at the top of its spec file."""
    text = path.read_text()
    if path.suffix == ".json":
        spec = json.loads(text)
        path.write_text(json.dumps({"id": workout_id, **spec}, indent=2) + "\n")
    elif re.search(r"(?m)^id:", text):
        path.write_text(re.sub(r"(?m)^id:.*$", f"id: {workout_id}", text, count=1))
    else:
        path.write_text(f"id: {workout_id}\n{text}")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workout"


# --- Commands ---------------------------------------------------------------


def cmd_list(args) -> None:
    garmin = login()
    rows = all_workouts(garmin)
    if args.search:
        rows = [w for w in rows if args.search.lower() in (w.get("workoutName") or "").lower()]
    for w in sorted(rows, key=lambda w: w.get("updatedDate") or "", reverse=True):
        sport = (w.get("sportType") or {}).get("sportTypeKey", "")
        mins = round((w.get("estimatedDurationInSecs") or 0) / 60)
        updated = (w.get("updatedDate") or "")[:10]
        print(f"{w['workoutId']:>12}  {sport:<18} {mins:>4} min  {updated}  {w['workoutName']}")
    print(f"{len(rows)} workout(s)")


def cmd_show(args) -> None:
    garmin = login()
    w = garmin.get_workout_by_id(find_workout(garmin, args.ref)["workoutId"])
    print(json.dumps(w, indent=2) if args.json else dump_spec(from_garmin(w)))


def cmd_pull(args) -> None:
    garmin = login()
    workouts = all_workouts(garmin)
    targets = workouts if args.all else [find_workout(garmin, r, workouts) for r in args.refs]
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = {}
    for p in out_dir.glob("*.y*ml"):
        try:
            existing[load_spec(p).get("id")] = p
        except Exception:  # noqa: BLE001
            pass
    for summary in targets:
        w = garmin.get_workout_by_id(summary["workoutId"])
        path = existing.get(w["workoutId"]) or out_dir / f"{slug(w['workoutName'])}.yaml"
        path.write_text(dump_spec(from_garmin(w)))
        print(f"Pulled {w['workoutName']} (id {w['workoutId']}) -> {path}")


def _payloads(files: list[str]) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    errors = []
    for f in files:
        path = Path(f)
        try:
            out.append((path, to_payload(load_spec(path))))
        except (SpecError, yaml.YAMLError, json.JSONDecodeError) as e:
            errors.append(f"{path}: {e}")
    if errors:
        sys.exit("Invalid spec(s):\n  " + "\n  ".join(errors))
    return out


def cmd_validate(args) -> None:
    for path, payload in _payloads(args.files):
        n = sum(len(s["workoutSteps"]) for s in payload["workoutSegments"])
        mins = round(payload["estimatedDurationInSecs"] / 60)
        print(f"OK  {path}: {payload['workoutName']} ({n} top-level steps, ~{mins} min)")


def cmd_push(args) -> None:
    items = _payloads(args.files)
    if args.dry_run:
        print(json.dumps([p for _, p in items], indent=2))
        return
    garmin = login()
    workouts = all_workouts(garmin)
    by_name = {}
    for w in workouts:
        by_name.setdefault(w.get("workoutName"), w["workoutId"])
    for path, payload in items:
        name = payload["workoutName"]
        workout_id = payload.pop("workoutId", None) or by_name.get(name)
        if workout_id:
            try:
                garmin.update_workout(workout_id, payload)
            except Exception as e:  # noqa: BLE001
                if "404" in str(e):
                    sys.exit(f"{path}: workout {workout_id} no longer exists on Garmin. "
                             "Remove the id line to create it again.")
                raise
            print(f"Updated   {name} (id {workout_id})")
        else:
            workout_id = garmin.upload_workout(payload)["workoutId"]
            print(f"Created   {name} (id {workout_id})")
        if str(load_spec(path).get("id")) != str(workout_id):
            write_id(path, workout_id)
        schedule_on(garmin, workout_id, name, expand_dates(args))


def cmd_delete(args) -> None:
    garmin = login()
    workouts = all_workouts(garmin)
    targets = [find_workout(garmin, r, workouts) for r in args.refs]
    for w in targets:
        if not args.yes:
            print(f"Would delete {w['workoutId']}  {w['workoutName']}  (re-run with --yes)")
            continue
        garmin.delete_workout(w["workoutId"])
        print(f"Deleted {w['workoutId']}  {w['workoutName']}")


_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def expand_dates(args) -> list[str]:
    """Explicit dates plus any --weekly days over --weeks weeks from --start."""
    dates = {dt.date.fromisoformat(d) for d in (getattr(args, "dates", None) or [])}
    dates |= {dt.date.fromisoformat(d) for d in (getattr(args, "schedule", None) or [])}
    if getattr(args, "weekly", None):
        try:
            days = {_DAYS.index(d.strip().lower()[:3]) for d in args.weekly.split(",") if d.strip()}
        except ValueError:
            sys.exit(f"--weekly takes day names like mon,wed,fri (got {args.weekly!r})")
        start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
        for i in range(args.weeks * 7):
            day = start + dt.timedelta(days=i)
            if day.weekday() in days:
                dates.add(day)
    return [d.isoformat() for d in sorted(dates)]


def scheduled(garmin, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """Calendar entries for workouts between two dates (inclusive)."""
    # Month views include the edges of neighbouring months, so dedupe by id.
    items: dict[Any, dict[str, Any]] = {}
    for y, m in _months(start, end):
        data = garmin.get_scheduled_workouts(y, m) or {}
        for it in data.get("calendarItems") or []:
            if it.get("itemType") == "workout" and start.isoformat() <= (it.get("date") or "") <= end.isoformat():
                items[it.get("id")] = it
    return sorted(items.values(), key=lambda i: i["date"])


def schedule_on(garmin, workout_id: int, name: str, dates: list[str]) -> None:
    """Schedule a workout on each date, skipping dates it's already on."""
    if not dates:
        return
    taken = {
        it["date"]
        for it in scheduled(garmin, dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1]))
        if str(it.get("workoutId")) == str(workout_id)
    }
    for date in dates:
        if date in taken:
            print(f"Already on {date}: {name}")
            continue
        res = garmin.schedule_workout(workout_id, date)
        sid = (res or {}).get("workoutScheduleId", "?")
        print(f"Scheduled {name} on {date} (schedule id {sid})")


def cmd_schedule(args) -> None:
    dates = expand_dates(args)
    if not dates:
        sys.exit("Give dates (YYYY-MM-DD ...) and/or --weekly mon,wed,fri")
    garmin = login()
    ref = args.ref
    if Path(ref).is_file():
        spec = load_spec(Path(ref))
        ref = str(spec.get("id") or spec["name"])
    w = find_workout(garmin, ref)
    schedule_on(garmin, w["workoutId"], w["workoutName"], dates)


def _months(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def cmd_calendar(args) -> None:
    garmin = login()
    start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
    end = dt.date.fromisoformat(args.end) if args.end else start + dt.timedelta(days=14)
    items = scheduled(garmin, start, end)
    for it in items:
        print(f"{it['date']}  schedule {it.get('id')!s:>12}  workout {it.get('workoutId')!s:>12}  {it.get('title')}")
    print(f"{len(items)} scheduled workout(s) {start} to {end}")


def cmd_unschedule(args) -> None:
    garmin = login()
    entries = [(sid, f"calendar entry {sid}") for sid in args.schedule_ids]
    if args.workout:
        w = find_workout(garmin, args.workout)
        start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
        end = dt.date.fromisoformat(args.end) if args.end else start + dt.timedelta(days=365)
        entries += [
            (it["id"], f"{it['date']} {it.get('title')} (calendar entry {it['id']})")
            for it in scheduled(garmin, start, end)
            if str(it.get("workoutId")) == str(w["workoutId"])
        ]
    if not entries:
        sys.exit("Nothing to unschedule (give schedule ids, or --workout REF [--from --to])")
    for sid, label in entries:
        if not args.yes:
            print(f"Would remove {label} (re-run with --yes)")
            continue
        garmin.unschedule_workout(sid)
        print(f"Removed {label}")


def cmd_send(args) -> None:
    garmin = login()
    w = find_workout(garmin, args.ref)
    garmin.push_workout_to_device(w["workoutId"])
    print(f"Sent {w['workoutName']} to your most recently used device; it arrives on next sync.")


def cmd_exercises(args) -> None:
    from garminconnect import exercises as catalog

    term = " ".join(args.term).lower()
    hits = [e for e in catalog.EXERCISES
            if term in e["name"].lower() or term.replace(" ", "_") in e["exercise"].lower()]
    for e in hits[:60]:
        print(f"{e['category']}/{e['exercise']:<45} {e['name']}")
    print(f"{len(hits)} match(es)" + (" (showing 60)" if len(hits) > 60 else ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="List your workouts")
    s.add_argument("--search")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="Print a workout as a spec (or raw JSON)")
    s.add_argument("ref")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("pull", help="Save workouts as spec files")
    s.add_argument("refs", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--dir", default=str(DEFAULT_DIR))
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("push", help="Create or update workouts from spec files")
    s.add_argument("files", nargs="+")
    s.add_argument("--dry-run", action="store_true", help="Print the JSON, don't upload")
    s.add_argument("--schedule", action="append", metavar="YYYY-MM-DD")
    s.add_argument("--weekly", metavar="DAYS", help="Repeat weekly on these days, e.g. mon,wed,fri")
    s.add_argument("--weeks", type=int, default=4, help="How many weeks for --weekly (default 4)")
    s.add_argument("--start", metavar="YYYY-MM-DD", help="First day for --weekly (default today)")
    s.set_defaults(func=cmd_push)

    s = sub.add_parser("validate", help="Check spec files offline")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("delete", help="Delete workouts (dry run without --yes)")
    s.add_argument("refs", nargs="+")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("schedule", help="Put a workout on the Garmin calendar")
    s.add_argument("ref")
    s.add_argument("dates", nargs="*", metavar="YYYY-MM-DD")
    s.add_argument("--weekly", metavar="DAYS", help="Repeat weekly on these days, e.g. mon,wed,fri")
    s.add_argument("--weeks", type=int, default=4, help="How many weeks for --weekly (default 4)")
    s.add_argument("--start", metavar="YYYY-MM-DD", help="First day for --weekly (default today)")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("calendar", help="List scheduled workouts")
    s.add_argument("--from", dest="start")
    s.add_argument("--to", dest="end")
    s.set_defaults(func=cmd_calendar)

    s = sub.add_parser("unschedule", help="Remove calendar entries (dry run without --yes)")
    s.add_argument("schedule_ids", nargs="*")
    s.add_argument("--workout", metavar="REF", help="Remove this workout's entries in --from/--to")
    s.add_argument("--from", dest="start", help="With --workout (default today)")
    s.add_argument("--to", dest="end", help="With --workout (default a year out)")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_unschedule)

    s = sub.add_parser("send", help="Send a workout to the watch now")
    s.add_argument("ref")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("exercises", help="Search the strength exercise catalog")
    s.add_argument("term", nargs="+")
    s.set_defaults(func=cmd_exercises)

    args = p.parse_args()
    if args.cmd == "pull" and not args.all and not args.refs:
        p.error("pull needs workout ids/names or --all")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
