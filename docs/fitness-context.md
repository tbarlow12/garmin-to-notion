# Tanner's training context

This is what the Claude Code skills in this repo (`weekly-review`,
`garmin-workouts`) need to know about Tanner. It lives in the repo so it works
in any Claude session. Update this file when a rule changes, and don't keep
the same fact anywhere else. This repo is public, so keep body weight, health
details and other personal numbers out.

## Goal and limits

- Goal: steady fat loss while keeping strength. Strength work is there to keep
  muscle during the cut; consistency matters more than intensity.
- Achilles history: no jumping or other high-impact work. Mobility is part of
  every session.
- Busy (engineering job, startup, family). He wants bright-line rules and no
  decisions in the morning. Don't hand him options; pick one and say what you
  picked.
- Don't suggest new equipment.

## Equipment (home gym)

Rogue Echo air bike, rower, treadmill, PowerBlock Pro dumbbells (to 100 lb),
kettlebell (to 40 lb), bench, pull-up bar and TRX, bands, 40 lb weighted vest,
medicine balls.

## Schedule

- Alarm 5:10 every training day. Lifting starts 5:30, done by about 6:25,
  hard stop 6:45. Lights out by 10:15 PM.
- Skip a morning only if he was in bed after midnight. A 20-minute midday
  walk is fine on those days.
- Sunday is rest. Mon and Wed afternoons are kids' MTB practice. A midday
  ride or walk is a bonus when it happens, never planned.

## Session format (Mon-Fri, under 60 minutes)

| Time | Segment |
|---|---|
| 5:30 | Warm-up, 5 min (3 min Echo bike + mobility) |
| 5:35 | Block A: 4 movements, 5-min circuit x 3 |
| 5:52 | Block B: 4 movements, 5-min circuit x 3 |
| 6:10 | Cardio, 15 min |

- Cardio: incline vest walk Mon/Wed/Fri (12%, 40 lb vest, about 3.6 mph; if
  calves or Achilles are tight, drop to 8-10% or lose the vest first), Echo
  bike intervals Tue, rower intervals Thu.
- Saturday: zone 2 only, 45-60 min (bike or walk).
- Lift first. When short on time cut cardio, then Block B, never Block A.
- Long cardio sessions are extras, never part of the plan.
- The standard week, as Garmin workouts, is in
  `.claude/skills/weekly-review/week.yaml`.

## Rules

- Missed day: never make it up and never shift the week. Do today's card.
- Never miss twice: two misses in a row means fix the evening (bedtime), not
  the morning.
- Load progression: 6-12 reps, stop with about 2 in reserve. 12 reps on all 3
  rounds means up one step next time (smallest dumbbell, kettlebell or band
  jump) and start back near 6-8 reps. Can't reach 6 in round 1 means down one
  step. Otherwise same weight, aim for +1 rep.

## Where the data is

- **Garmin Connect** is the source of truth for workouts and activities.
  Access is through `garminconnect` with the `GARMIN_TOKENS` env var (see
  `.claude/skills/garmin-workouts/SKILL.md`). The watch logs strength weights
  but usually not reps. "Running" or "Treadmill Running" activities are
  usually the incline vest walk. Garmin has no sleep data, because he sleeps in
  a Fitbit.
- **Notion**, through this repo's sync (`src/garmin_to_notion`) and the Notion
  connector when a session has it:
  - Fitness hub page: https://app.notion.com/p/2d7e9187fa6580d7b482dc945e35c0d7
  - Workout Rules page (older copy of the rules above; this file is current):
    https://app.notion.com/p/af0f81de3d55433a9e48385ff15719c8
  - Workout plan cards: `collection://2d7e9187-fa65-8053-9db6-000bc1803048`
    (the "Monday Workout" to "Saturday Workout" cards predate the format above)
  - Garmin activities: `collection://09be9187-fa65-8375-8046-8786d58d5aa6`
  - Sleep (Fitbit via the `fitbit-sleep` syncer when it's running):
    `collection://596e9187-fa65-833e-9e46-8734b4c16fbd`
  - Daily steps: `collection://33de9187-fa65-8373-a421-07268160b270`
  - Monthly activity summary: `collection://f1fe9187-fa65-8302-8317-87a881c9e3a5`
