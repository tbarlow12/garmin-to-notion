---
name: garmin-workouts
description: List, create, edit, delete, schedule or send Tanner's Garmin Connect workouts (strength circuits, runs, rides, routines). Use whenever he asks to change a workout, add a new one, move one on his Garmin calendar, or get one onto his watch.
---

# Garmin workouts

The tool is `.claude/bin/garmin-workouts` (talks to Garmin Connect through
`garminconnect`), with `.claude/bin/workout_spec.py` converting the YAML spec
format to and from Garmin's workout JSON. This folder holds the rest:

- `reference.md`: the spec format. Read it before writing or editing a spec.
- `workouts/`: spec files for Tanner's Garmin workouts (pulled Nov 18 2026; pull again before editing).
- `exercises.yaml`: the full strength exercise catalog (1,527 exercises by category) for picking `exercise:` keys.
- `test_workout_spec.py`: offline tests (`python -m pytest .claude/skills/garmin-workouts`).

## Setup (once per session)

```bash
pip install -r requirements.txt          # garminconnect, PyYAML
W=.claude/bin/garmin-workouts
```

Auth comes from the `GARMIN_TOKENS` env var (a base64 tokenstore made by
`scripts/generate_token.py`), cached at `~/.garmin_tokens`. Never print or log
`GARMIN_TOKENS`. If login fails, the token has expired: tell Tanner to rerun
`scripts/generate_token.py` locally and update `GARMIN_TOKENS` in the cloud
environment. Don't try password login: it hits MFA and Garmin rate limits.

## Commands

| Goal | Command |
|---|---|
| See what's there | `$W list` (or `--search boot`) |
| Read one as a spec | `$W show "Engine Room"` (id, exact name or unique fragment; `--json` for raw) |
| Save to a file for editing | `$W pull "Engine Room"` (writes `workouts/<slug>.yaml`; `--all`, `--dir DIR`) |
| Check a spec offline | `$W validate FILE` |
| Create or update | `$W push FILE [--schedule 2026-11-20] [--weekly ...]` (`--dry-run` prints JSON only) |
| Put on the calendar | `$W schedule REF|FILE 2026-11-20 [more dates]` |
| Recurring | `$W schedule REF --weekly mon,wed,fri --weeks 8 [--start 2026-11-23]` (start defaults to today, weeks to 4) |
| See the calendar | `$W calendar [--from DATE --to DATE]` (default: next 14 days; shows schedule ids) |
| Take off the calendar | `$W unschedule SCHEDULE_ID --yes`, or a whole series: `$W unschedule --workout REF [--from DATE --to DATE] --yes` |
| Delete a workout | `$W delete REF --yes` |
| Send to the watch now | `$W send REF` |
| Find exercise keys | `$W exercises "goblet squat"` |

`delete` and `unschedule` only print what they would do unless given `--yes`.

## How to make a change

1. **Pull first.** Garmin is the source of truth; Tanner may have edited a
   workout in the app since the file in `workouts/` was written. Run
   `$W pull REF` (it overwrites the matching file by id) before editing.
2. Edit the YAML (see `reference.md`). Look up exercise keys with
   `$W exercises TERM` instead of guessing.
3. `$W validate FILE`, then `$W push FILE`.
4. `$W show REF` to confirm what Garmin now holds, and tell Tanner what changed.
5. If the spec is in `workouts/`, commit it so the repo matches Garmin.

Rules that matter:

- A spec with `id:` updates that workout in place, so a rename is safe and
  calendar entries keep pointing at it. A spec without `id:` updates the
  workout with the exact same name, or creates a new one, and the new id is
  written back into the file. Keep the `id:` line.
- Push replaces the whole workout, so always push a complete spec (that is
  why you pull first).
- Garmin has no recurring schedule for a single workout. `--weekly` creates one
  calendar entry per day, and skips days the workout is already on, so
  re-running is safe. Entries point at the workout, so editing it updates
  every scheduled day. To change a series' days, unschedule it with
  `--workout` and schedule again.
- New workouts reach the watch once they're on the calendar (`--schedule`) or
  sent with `$W send`, followed by a watch sync.
- Deleting a workout or removing calendar entries can't be undone: confirm
  with Tanner first unless he asked for exactly that. Creating, editing and
  scheduling are fine to just do and report.
- Garmin estimates duration from timed steps only; set `estimated_minutes`
  when reps/lap/distance steps make the estimate wrong.

## Tanner's context

Read `docs/fitness-context.md` for his equipment, goals and limits
before designing workouts (for example: avoid jumping, Achilles). Write
notes in the step `note:` field; that text shows on the watch.

Garmin has no official workout API; this uses the private Connect endpoints
via `garminconnect`, so it can break if Garmin changes them. If a call
starts failing, check for a newer `garminconnect` release first.
