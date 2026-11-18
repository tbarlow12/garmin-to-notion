# Coach agent spec

The coach is a Claude Code subagent (`.claude/agents/coach.md`). It gets Tanner
through a planned session every training morning with zero decisions left for
5:10 AM, debriefs each session, and reviews the week on Sunday. Rules and
context: `docs/fitness-context.md`. Profile: `docs/athlete.md`.

## Success

| Metric | Target |
| --- | --- |
| Sessions done / planned | 6 / 6 per week |
| On-time starts (first activity by 5:30) | 5+ per week |
| Back-to-back misses | 0 |
| Weekly weight change (7-day average) | about -1.25 lb |
| Average bedtime (Fitbit) | 10:15 PM or earlier |

The coach itself is working if Tanner never decides anything at 5:10 and never
opens Garmin Connect to build or schedule a workout.

## Triggers (Mountain time)

| When | What the coach does | Message |
| --- | --- | --- |
| 7:30 PM Sun-Fri | Confirms tomorrow's card is scheduled and on the watch; fixes it if not | "Tomorrow: Upper Push 1 + vest walk, 5:30-6:25. Alarm 5:10." |
| 9:45 PM Sun-Fri (first two weeks) | Bedtime nudge | "Lights out by 10:15." |
| 5:30 AM Mon-Sat | Reads Garmin for a started activity | None |
| 6:30 AM Mon-Sat | If nothing started, one nudge | "No session yet. Lift now, skip cardio." |
| ~7:00 AM Mon-Sat | Runs `/debrief`; retries 8:00 if not synced | Done vs planned, load changes, 2-3 observations, "Weight?" |
| Sun 7 PM | Runs `/weekly-review`, schedules next week | Scoreboard, one pattern, at most one change |

Nothing during the workout needs Tanner to open a session or reply. One nudge
per trigger, never a chain. If he was in bed after midnight, the day is
skipped and the coach is quiet until the nightly plan.

## Debrief (`/debrief`)

1. Find the morning's activities (multisport split into legs), match them to
   the day's plan.
2. Pull HR trace and zones, intervals and rests, strength sets with weights,
   RPE/feel, readiness and resting HR (`.claude/bin/debrief show`).
3. Collect reps: his round notes, then believable watch reps, then one
   exceptions question.
4. Apply progression to the next instance of that workout on Garmin
   (`.claude/bin/debrief progress ... --apply`), commit the spec.
5. Two or three specific observations with numbers.
6. Log to the Notion Coach Log.
7. Reply in one short message.

## Decisions taken (Nov 18 2026)

These were open questions in the draft; defaults were taken. Change them here.

- Messages: push notification for nudges, the session/thread for debriefs and reviews.
- 5:30 check-in sends nothing; only the 6:30 nudge speaks.
- Bedtime nudge on for two weeks, then reviewed.
- Coach Log lives in Notion.
- Weight: he replies with a number to the debrief.
- Rewrite the six Notion workout cards to the current format after the coach is running.
- Review day: Sunday 7 PM, so Monday's accountability check-in has the numbers.

## Not built yet

- Scheduled triggers for the times above (Claude Code scheduled tasks or a
  cron). They need Tanner's go-ahead, since they message him.
- The Notion Coach Log database (created by `/debrief` on first run).
