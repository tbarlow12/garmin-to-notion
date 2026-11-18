---
name: debrief
description: Tanner's post-workout debrief. Pulls the morning's session from Garmin (HR, zones, intervals, sets and loads), collects reps from his round notes, applies load progression to the next workout, gives 2-3 specific observations and logs the session. Use for /debrief, after a training session, or when he sends his round notes or asks how a session went.
---

# Post-workout debrief

One session, end to end, in under a minute of his attention. Read
`docs/fitness-context.md` first: its rules, progression and "How to talk to
him" sections are binding. `docs/athlete.md` (if present) has his weight goal
and health notes.

Tool (repo root, after `pip install -r requirements.txt`):

```bash
D=.claude/bin/debrief
$D show                     # today's session (Mountain time)
$D show --date 2026-11-10   # any day
$D show --json              # same data, structured
$D progress "Upper Pull 1" --up hammer_curl --down renegade        # dry run
$D progress "Upper Pull 1" --up hammer_curl --down renegade --apply
```

Auth is `GARMIN_TOKENS`, shared with `garmin-workouts`. Never print it.

## Steps

1. **Find the session.** `$D show`. If it says nothing synced, stop: say
   "Not synced yet" and try once more later (the coach retries at 8:00, then
   logs the day as not synced). Never guess what he did.
2. **Read the detail.** Plan vs done (sessions, legs, sets per exercise vs
   planned rounds), first start vs 5:30, HR zones, rest lengths, cardio pace
   or stroke rate, readiness and resting HR.
3. **Collect reps**, in this order:
   - His round notes: a photo of the whiteboard/card, a typed reply, or the
     Garmin activity notes (`Notes:` line in `show`). Read photos carefully;
     ask about one unreadable number rather than guessing.
   - Watch reps, only for exercises without `[no usable watch reps]`.
   - Neither: ask once, "Anything hit 12 every round, or miss 6 in round 1?"
     and wait for his answer before step 4. He answers by exception.
4. **Apply progression.** For each lift: 12 on every round → `--up`; under 6
   in round 1 → `--down`; otherwise hold. Use the planned workout's exercise
   names (from the `Planned ...` lines) as fragments. Run `progress` without
   `--apply`, check the changes are what you meant, then `--apply`. This
   updates the Garmin workout (so the watch shows the new weight) and its spec
   in `.claude/skills/garmin-workouts/workouts/`; commit the spec change.
   Only load changes from this rule. Exercise swaps wait for the weekly review.
5. **Observe.** Two or three specific observations with numbers, things he
   can act on. Good: "Rests ran 3:43 and 19:41 vs the planned lap rest",
   "Vest walk: 20 of 33 min in zone 5, drop to 3.6 mph", "Started 5:48, 18 min
   late", "Readiness 15 (poor): normal session, lights out 10:15 tonight".
   Bad: "Great job!", "Consider hydrating".
6. **Log.** One row in the Notion "Coach Log" database (see `docs/fitness-context.md`;
   create it under the Fitness hub on first run and record its id there):
   date, workout, start, planned vs done, loads and reps per lift, next loads,
   weight if he gave it, observations, his notes.
7. **Reply** in one short message:
   - Line 1: done vs planned and start time.
   - Next session's load changes, if any.
   - The observations.
   - "Weight?" if he hasn't sent it today.

## Don'ts

- Don't re-plan tomorrow or make up a missed session (docs/fitness-context.md).
- Don't push or edit a workout beyond the progression step without his yes.
- Don't message him during the session; everything waits for the debrief.
