# Workout spec format

A spec is one YAML (or JSON) file per workout.

```yaml
id: 1766434547                # set automatically after the first push; keep it
name: "Boot Camp 2: Engine Room (AMRAP 20)"
sport: strength_training      # see Sports below
description: Shown on the workout's page in Garmin Connect.
estimated_minutes: 23         # optional; otherwise summed from timed steps
steps:
  - warmup: 3m
    note: 1 min easy air bike, then 10 KB halos
  - repeat: 8
    steps:
      - exercise: INDOOR_ROW
        lap: true
        note: 250 m row, press lap when done
      - exercise: GOBLET_SQUAT
        reps: 10
        weight: 40lb
      - rest: 20s
  - cooldown: lap
```

Multi-sport workouts (strength block plus a run, say) use `segments` instead
of `steps`, each with its own `sport`:

```yaml
name: Full Body 1
sport: multi_sport
segments:
  - sport: strength_training
    steps: [...]
  - sport: running
    steps: [...]
```

## Sports

`running` (`run`), `cycling` (`bike`), `swimming` (`swim`),
`strength_training` (`strength`), `cardio_training` (`cardio`), `hiit`,
`yoga`, `pilates`, `mobility`, `other`, `multi_sport`.

## Steps

A step is a mapping. Its `type` is one of `interval` (default), `warmup`,
`cooldown`, `rest`, `recovery`, `other`. Shorthand: `- rest: 30s`,
`- warmup: 5m`, `- cooldown: lap`, `- recovery: 90s` (other fields can sit
beside it, like `note:`).

**How the step ends** (at most one; none means lap button):

| Field | Example | Notes |
|---|---|---|
| `time` | `45`, `45s`, `3m`, `1m30s`, `1:30` | plain numbers are seconds |
| `reps` | `12` | |
| `distance` | `400m`, `5km`, `1mi` | plain numbers are meters |
| `calories` | `50` | |
| `lap` | `true` | ends when you press lap |

**Other fields:**

| Field | Example | Notes |
|---|---|---|
| `exercise` | `GOBLET_SQUAT`, `SQUAT/GOBLET_SQUAT`, `Goblet Squat` | strength catalog; search with `garmin-workouts exercises TERM`. Use `CATEGORY/EXERCISE` when the bare key is ambiguous (validate tells you) |
| `weight` | `40lb`, `20kg`, `40` | stored in pounds |
| `note` | `"Hands on bench"` | shows on the watch |
| `hr_zone` / `power_zone` | `2` | your Garmin zones |
| `hr` / `power` / `cadence` | `"130-145"` | bpm / watts / spm or rpm |
| `pace` | `"9:00-9:30/mi"`, `"5:30/km"` | |
| `speed` | `"14-16"` | mph |
| `extra` | `{endConditionCompare: gt}` | raw Garmin step fields, merged in as-is; `pull` puts fields it doesn't model here so nothing is lost |

At most one target (`hr_zone`, `hr`, `pace`, ...) per step.

## Repeats

```yaml
- repeat: 5             # rounds
  skip_last_rest: true  # optional: skip the final rest step
  steps:
    - ...
```

Repeats can nest.

## Patterns

- **EMOM**: a repeat of `time: 1m` steps with the reps in `note`.
- **AMRAP**: a repeat with more rounds than you'll finish, `reps`/`lap`
  steps, and the time cap in `description`; stop at the cap.
- **Tabata / 40-20**: alternate `time: 40s` work steps with `- rest: 20s`.
- **Run intervals**: `distance: 400m` + `pace`, then `- recovery: 90s`.
