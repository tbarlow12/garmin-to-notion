---
name: weekly-review
description: Tanner's weekly training review. Pulls the past week from Garmin, scores consistency (5:15 starts, sessions done vs planned, misses) and strength performance, then schedules the coming week's workouts on his Garmin calendar. Use for /weekly-review or when he asks how his week went or to plan next week.
---

# Weekly review

Two jobs, in this order: tell Tanner honestly how last week went, then put
next week on his Garmin calendar so he wakes up to zero decisions.

Tools (run from the repo root, after `pip install -r requirements.txt`):

```bash
R=.claude/bin/weekly-review
$R review                      # last complete Mon-Sun week
$R review --week-of 2026-11-16 # any week; days after today show as upcoming
$R review --json               # same data, for digging in
$R plan                        # next Mon-Sun (today if it's Monday), dry run
$R plan --from 2026-11-19 --to 2026-11-29 --apply
$R events --from 2026-11-23 --to 2026-11-29  # Google Calendar events for what's on Garmin (JSON)
```

Auth is `GARMIN_TOKENS`, shared with `garmin-workouts` (see that skill for
login failures; never print the token). The standard week lives in
`week.yaml` next to this file: which Garmin workouts go on which day, the
5:15 start-by time and the time zone. The workouts themselves live on Garmin
(the source of truth) and are changed with the `garmin-workouts` skill, never
through a pull request. Each weekday is two workouts in order: 30 min of
cardio (its own workout, so the watch records treadmill, bike or rower
correctly), then the lift.

## Context

Read `docs/fitness-context.md` first: Tanner's rules, schedule, session
format, equipment, limits and where his data lives. It is the only source for
those; don't rely on anything outside the repo. The rules the review must
enforce, in short:

- On time = first activity starts by 5:15 (alarm 4:55).
- Mon-Fri: 30 min cardio workout, then the lift workout. Sat zone 2, Sun rest.
- A missed day is never made up and the week never shifts.
- Two misses in a row: fix the evening, not the morning.
- Pick, don't offer menus. No new equipment. No jumping (Achilles).

## Steps

1. **Pull the week.** `$R review` for the last complete week. If it's
   midweek, also run `$R review --week-of <today>` so the plan accounts for
   what has happened since.
2. **Sleep (optional, best lever).** Garmin has no sleep data: he sleeps in a
   Fitbit. If the Notion Sleep database (listed in `docs/fitness-context.md`)
   has rows for the week, add average sleep and
   bedtime. If it's stale, say so in one line and move on.
3. **Assess consistency.** Lead with the scoreboard: sessions done/planned,
   lift days done/5, on-time starts, missed days, longest miss streak, and
   partial days (showed up but didn't lift). Name the pattern, not a lecture:
   which days fell through, whether starts drifted later, whether a miss turned
   into two.
4. **Assess performance.** For each lift, compare top weights with the last
   time he did that workout (the tool prints "was ..."). Garmin's watch
   usually doesn't record reps, so the progression rule can't be applied from
   data alone: list movements that have sat at the same weight for 3+ sessions
   as candidates to go up, and ask him once, in one line, whether he hit 12s.
   Note fewer rounds than planned (e.g. 2 sets where the workout has 3) and
   cardio swaps. Use training load, minutes and RHR only as trend context.
5. **Plan the coming week.** Run `$R plan` (add `--from` today/tomorrow if
   reviewing midweek so the rest of this week gets scheduled too). If it
   reports a workout missing on Garmin, create it with the `garmin-workouts`
   skill first. Then `$R plan --apply`. The plan is the
   standard week every week: don't rotate, swap or "make up" anything. Change
   `week.yaml` only when Tanner asks for a different week or agrees to a change
   you proposed. Commit `week.yaml`; workout edits happen on Garmin only.
6. **Log pages and Google Calendar.** Right after `plan --apply`, with the
   same dates, run `$R events`. It reads what is actually on the Garmin
   calendar and returns one entry per training day with two parts:
   - `log`: a Planned page for his Notion **Workout Log** (data source in
     `week.yaml` under `workout_log`). Create it with the Notion connector:
     Session (title), Date, Workout, Status "Planned", Garmin workout and
     Garmin cardio URLs, and `body` as the page content (a table per block:
     Exercise, Weight, Target, one column per round, Notes, pre-filled from
     Garmin). Skip a day that already has a Workout Log page for that date.
   - The Google Calendar event: title (`💪 <cardio> + <lift>` on weekdays,
     `🚴 Zone 2: 45-60 min` on Saturday), start/end in his time zone, and the
     Block A/B weights as the description. Make the description's first line
     `Log (reps per round): <that day's Workout Log page URL>`. The calendar
     id and times are under `google_calendar` in `week.yaml` (his "Habits"
     calendar; weekdays 5:15-6:30 America/Denver). List that calendar's
     events for the range first and skip any day that already has an event
     with the same title, so reruns never duplicate.
   Skip entries marked `skip` (Saturday has no time until he picks one; its
   log page is still fine to create) and say so in one line. Don't touch his
   other events. If a connector isn't in the session, say which and move on;
   Garmin is what matters.
7. **Report** (keep it short; he skims):
   - One-line verdict.
   - Scoreboard line (from step 3).
   - What went well, what fell through (2-4 bullets total).
   - One change for next week, at most, and only if the data supports it
     (e.g. "two misses in a row Thu-Fri: lights out 10:15 Wed and Thu").
   - Next week: day by day, one line each, as scheduled on Garmin (and
     whether it reached Google Calendar).

When to ask before scheduling: the first time this skill runs for him, and
any time you propose changing `week.yaml` or a workout. Otherwise scheduling
the standard week is expected; just do it and report. Never unschedule or
delete calendar entries he added himself without asking.
