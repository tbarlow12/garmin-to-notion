"""Boot camp circuits as Garmin Connect strength workouts.

Each circuit is described with a few small step builders and turned into the
JSON payload that Garmin Connect's workout service accepts (the same shape the
Garmin Connect workout editor saves). ``scripts/push_workouts.py`` uploads
them so they show up under Training > Workouts and can be sent to the watch.

Exercise ``category``/``exercise`` keys come from garminconnect's strength
catalog (``garminconnect.exercises``), so the watch shows the right name and
animation for each step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Garmin enums (ids match garminconnect.workout) -------------------------

_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}

_STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "interval": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "rest": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
}
_CONDITIONS = {
    "lap": {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True},
    "time": {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
    "iterations": {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
    "reps": {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10, "displayable": True},
}

# Exercise keys (category, exercise) from garminconnect.exercises.
KB_SWING = ("HIP_RAISE", "KETTLEBELL_SWING")
MED_BALL_SLAM = ("PLYO", "MEDICINE_BALL_SLAM")
PUSH_UP = ("PUSH_UP", "PUSH_UP")
AIR_BIKE = ("INDOOR_BIKE", "AIR_BIKE")
ROWER = ("ROW", "INDOOR_ROW")
GOBLET_SQUAT = ("SQUAT", "GOBLET_SQUAT")
RENEGADE_ROW = ("ROW", "RENEGADE_ROW")
THRUSTER = ("SQUAT", "THRUSTERS")
DEAD_BUG = ("HIP_STABILITY", "DEAD_BUG")
AB_WHEEL = ("CORE", "KNEELING_AB_WHEEL")
RUSSIAN_TWIST = ("CORE", "RUSSIAN_TWIST")
BENCH_MOUNTAIN_CLIMBER = ("PLANK", "MOUNTAIN_CLIMBER_WITH_HANDS_ON_BENCH")
TRX_ROLLOUT = ("SUSPENSION", "ROLLOUT")
BURPEE = ("TOTAL_BODY", "BURPEE")
PLANK = ("PLANK", "PLANK")

# --- Step model -------------------------------------------------------------


@dataclass
class Step:
    """One executable step. ``end`` is 'time' (secs), 'reps' or 'lap'."""

    kind: str  # warmup | interval | rest | cooldown
    end: str
    value: float | None = None
    exercise: tuple[str, str] | None = None
    note: str | None = None


@dataclass
class Repeat:
    rounds: int
    steps: list[Step]


@dataclass
class Circuit:
    name: str
    description: str
    minutes: int
    steps: list[Step | Repeat] = field(default_factory=list)


def timed(exercise: tuple[str, str], secs: int, note: str | None = None) -> Step:
    return Step("interval", "time", secs, exercise, note)


def reps(exercise: tuple[str, str], n: int, note: str | None = None) -> Step:
    return Step("interval", "reps", n, exercise, note)


def lap(exercise: tuple[str, str], note: str) -> Step:
    """Ends when you press the lap button (for distance work like a 250 m row)."""
    return Step("interval", "lap", None, exercise, note)


def rest(secs: int) -> Step:
    return Step("rest", "time", secs)


WARMUP = Step(
    "warmup",
    "time",
    180,
    note="1 min easy air bike, then 10 KB halos, 10 goblet squats, 10 band pull-aparts",
)


# --- The circuits -----------------------------------------------------------

CIRCUITS: list[Circuit] = [
    Circuit(
        name="Boot Camp 1: Swing & Slam (EMOM 20)",
        description=(
            "EMOM 20, 5 rounds. Each minute: do the reps, rest the remainder. "
            "If reps take >45 s, drop reps or weight. No jumping (Achilles)."
        ),
        minutes=23,
        steps=[
            WARMUP,
            Repeat(5, [
                timed(KB_SWING, 60, "15 swings (40 lb KB), rest rest of minute"),
                timed(MED_BALL_SLAM, 60, "12 slams (15 lb ball), rest rest of minute"),
                timed(PUSH_UP, 60, "10 push-ups (handles), rest rest of minute"),
                timed(AIR_BIKE, 60, "30 s all-out, then easy spin"),
            ]),
        ],
    ),
    Circuit(
        name="Boot Camp 2: Engine Room (AMRAP 20)",
        description=(
            "AMRAP 20: as many rounds as possible in 20 min. Press lap after each "
            "station. Stop at 20:00 and note your rounds to beat next time."
        ),
        minutes=23,
        steps=[
            WARMUP,
            Repeat(8, [
                lap(ROWER, "250 m row, press lap when done"),
                reps(GOBLET_SQUAT, 10, "40 lb KB"),
                reps(RENEGADE_ROW, 10, "5 per side, PowerBlocks 25-30"),
                reps(THRUSTER, 10, "15 lb med ball, no jump"),
                reps(DEAD_BUG, 20, "10 per side"),
            ]),
        ],
    ),
    Circuit(
        name="Boot Camp 3: Core Burner (40/20 x4)",
        description="40 s work / 20 s rest, 5 stations, 4 rounds = 20 min.",
        minutes=23,
        steps=[
            WARMUP,
            Repeat(4, [
                timed(AIR_BIKE, 40, "Hard"), rest(20),
                timed(AB_WHEEL, 40, "Ab roller rollouts"), rest(20),
                timed(RUSSIAN_TWIST, 40, "8 lb Rhino ball"), rest(20),
                timed(BENCH_MOUNTAIN_CLIMBER, 40, "Hands on bench, controlled"), rest(20),
                timed(TRX_ROLLOUT, 40, "TRX body saw / fallout"), rest(20),
            ]),
        ],
    ),
    Circuit(
        name="Boot Camp 4: Bare Minimum (AMRAP 12)",
        description=(
            "AMRAP 12 for when you're really short. Press lap after each station; "
            "stop at 12:00. Something beats nothing."
        ),
        minutes=12,
        steps=[
            Repeat(6, [
                reps(KB_SWING, 10, "40 lb KB"),
                reps(MED_BALL_SLAM, 8, "15 lb ball"),
                reps(BURPEE, 6, "Step back, step in, no jump"),
                timed(PLANK, 20),
            ]),
        ],
    ),
]


# --- JSON payload -----------------------------------------------------------


def _executable(step: Step, order: int) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _STEP_TYPES[step.kind],
        "endCondition": _CONDITIONS[step.end],
        "targetType": _NO_TARGET,
    }
    if step.value is not None:
        d["endConditionValue"] = float(step.value)
    if step.exercise:
        d["category"], d["exerciseName"] = step.exercise
    if step.note:
        d["description"] = step.note
    return d


def to_payload(circuit: Circuit) -> dict[str, Any]:
    """Build the Garmin Connect workout JSON for a circuit.

    Garmin wants every step (including those nested in repeats) numbered in
    depth-first order, starting at 1.
    """
    order = 0

    def nxt() -> int:
        nonlocal order
        order += 1
        return order

    steps: list[dict[str, Any]] = []
    for item in circuit.steps:
        if isinstance(item, Repeat):
            group_order = nxt()
            children = [_executable(s, nxt()) for s in item.steps]
            steps.append({
                "type": "RepeatGroupDTO",
                "stepOrder": group_order,
                "stepType": _STEP_TYPES["repeat"],
                "numberOfIterations": item.rounds,
                "endCondition": _CONDITIONS["iterations"],
                "endConditionValue": float(item.rounds),
                "smartRepeat": False,
                "workoutSteps": children,
            })
        else:
            steps.append(_executable(item, nxt()))

    return {
        "workoutName": circuit.name,
        "description": circuit.description,
        "sportType": _STRENGTH,
        "estimatedDurationInSecs": circuit.minutes * 60,
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": _STRENGTH,
            "workoutSteps": steps,
        }],
    }
