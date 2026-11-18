"""Human-editable workout specs <-> Garmin Connect workout JSON.

A spec is a small YAML/JSON document (see ``.claude/skills/garmin-workouts/reference.md``) that
describes a Garmin workout: name, sport, and a list of steps with optional
repeats. ``to_payload`` builds the JSON body Garmin's workout service accepts
(the same shape the Garmin Connect editor saves) and ``from_garmin`` turns a
workout fetched from Garmin back into a spec, so existing workouts can be
pulled, edited and pushed again.

Nothing here talks to the network; ``.claude/bin/garmin-workouts`` does that.
"""

from __future__ import annotations

import re
from typing import Any

from garminconnect import exercises as catalog

# --- Garmin enums (ids match garminconnect.workout / Garmin's workout/types) --

SPORTS: dict[str, int] = {
    "running": 1,
    "cycling": 2,
    "other": 3,
    "swimming": 4,
    "strength_training": 5,
    "cardio_training": 6,
    "yoga": 7,
    "pilates": 8,
    "hiit": 9,
    "multi_sport": 10,
    "mobility": 11,
}
SPORT_ALIASES = {
    "run": "running",
    "bike": "cycling",
    "ride": "cycling",
    "swim": "swimming",
    "strength": "strength_training",
    "cardio": "cardio_training",
    "multisport": "multi_sport",
}

STEP_TYPES: dict[str, int] = {
    "warmup": 1,
    "cooldown": 2,
    "interval": 3,
    "recovery": 4,
    "rest": 5,
    "repeat": 6,
    "other": 7,
}

CONDITIONS: dict[str, tuple[int, str, bool]] = {
    # spec key: (conditionTypeId, conditionTypeKey, displayable)
    "lap": (1, "lap.button", True),
    "time": (2, "time", True),
    "distance": (3, "distance", True),
    "calories": (4, "calories", True),
    "iterations": (7, "iterations", False),
    "reps": (10, "reps", True),
}
_CONDITION_BY_KEY = {v[1]: k for k, v in CONDITIONS.items()}

# spec key -> (workoutTargetTypeId, workoutTargetTypeKey)
TARGETS: dict[str, tuple[int, str]] = {
    "none": (1, "no.target"),
    "power": (2, "power.zone"),
    "cadence": (3, "cadence"),
    "hr": (4, "heart.rate.zone"),
    "speed": (5, "speed.zone"),
    "pace": (6, "pace.zone"),
}
_TARGET_BY_KEY = {v[1]: k for k, v in TARGETS.items()}

POUND = {"unitId": 9, "unitKey": "pound", "factor": 453.59237}
_KG_TO_LB = 2.2046226218

_MILE = 1609.344

# Step fields this module understands. Anything else found on a step pulled
# from Garmin goes into the step's ``extra`` dict so a pull/push round trip
# does not silently drop it.
_KNOWN_STEP_FIELDS = {
    "type", "stepId", "stepOrder", "stepType", "childStepId", "description",
    "endCondition", "endConditionValue", "preferredEndConditionUnit",
    "endConditionCompare", "targetType", "targetValueOne", "targetValueTwo",
    "targetValueUnit", "zoneNumber", "strokeType", "equipmentType", "category",
    "exerciseName", "weightValue", "weightUnit", "workoutProvider",
    "providerExerciseSourceId", "secondaryTargetType", "secondaryTargetValueOne",
    "secondaryTargetValueTwo", "secondaryTargetValueUnit", "secondaryZoneNumber",
    "endConditionZone", "numberOfIterations", "workoutSteps", "smartRepeat",
    "skipLastRestStep",
}


class SpecError(ValueError):
    """A workout spec is malformed."""


# --- Parsing helpers --------------------------------------------------------


def parse_duration(value: Any) -> float:
    """Seconds from 90, "90s", "3m", "1m30s", "1:30", "1h", "1:02:00"."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}", s):
        secs = 0
        for part in s.split(":"):
            secs = secs * 60 + int(part)
        return float(secs)
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?\s*(?:(\d+(?:\.\d+)?)m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)s(?:ec)?)?", s)
    if m and any(m.groups()):
        h, mi, se = (float(g) if g else 0.0 for g in m.groups())
        return h * 3600 + mi * 60 + se
    raise SpecError(f"Can't read duration {value!r} (try 90, '90s', '3m', '1m30s', '1:30')")


def format_duration(secs: float) -> str | int:
    secs = int(round(secs))
    if secs < 60:
        return f"{secs}s"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    out = (f"{h}h" if h else "") + (f"{m}m" if m else "") + (f"{s}s" if s else "")
    return out


def parse_distance(value: Any) -> float:
    """Meters from 400, "400m", "5km", "1.5mi", "800 m"."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|km|mi|k)?\s*", str(value).lower())
    if not m:
        raise SpecError(f"Can't read distance {value!r} (try 400, '400m', '5km', '1mi')")
    n, unit = float(m.group(1)), m.group(2) or "m"
    return n * {"m": 1, "km": 1000, "k": 1000, "mi": _MILE}[unit]


def format_distance(meters: float) -> str:
    if meters >= 1000 and abs(meters / _MILE - round(meters / _MILE, 2)) < 0.001 and meters % 1000:
        return f"{round(meters / _MILE, 2):g}mi"
    if meters >= 1000:
        return f"{meters / 1000:g}km"
    return f"{meters:g}m"


def parse_weight(value: Any) -> float:
    """Pounds from 40, "40lb", "40 lbs", "20kg"."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(lbs?|kg)?\s*", str(value).lower())
    if not m:
        raise SpecError(f"Can't read weight {value!r} (try 40, '40lb', '20kg')")
    n = float(m.group(1))
    return n * _KG_TO_LB if m.group(2) == "kg" else n


def _range(value: Any, what: str) -> tuple[float, float]:
    """(low, high) from "130-145", [130, 145] or a single number."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = float(value[0]), float(value[1])
    elif isinstance(value, (int, float)):
        lo = hi = float(value)
    else:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*", str(value))
        if not m:
            raise SpecError(f"Can't read {what} range {value!r} (try '130-145')")
        lo, hi = float(m.group(1)), float(m.group(2))
    return min(lo, hi), max(lo, hi)


def _pace_to_mps(pace: str) -> tuple[float, float]:
    """("9:00-9:30/mi") -> (slow m/s, fast m/s). Single pace allowed."""
    m = re.fullmatch(r"\s*(\d+:\d{2})(?:\s*-\s*(\d+:\d{2}))?\s*/\s*(mi|km)\s*", str(pace).lower())
    if not m:
        raise SpecError(f"Can't read pace {pace!r} (try '9:00-9:30/mi' or '5:30/km')")
    unit = _MILE if m.group(3) == "mi" else 1000.0
    paces = [parse_duration(m.group(1)), parse_duration(m.group(2) or m.group(1))]
    speeds = sorted(unit / p for p in paces)
    return speeds[0], speeds[1]


def _mps_to_pace(mps: float, unit: str = "mi") -> str:
    secs = (_MILE if unit == "mi" else 1000.0) / mps
    return f"{int(secs // 60)}:{int(round(secs % 60)):02d}"


# --- Exercises --------------------------------------------------------------


def resolve_exercise(name: str) -> tuple[str, str]:
    """(category, exercise) from "CATEGORY/EXERCISE", "EXERCISE" or a display name.

    Display names and keys come from garminconnect's copy of the Garmin
    Connect strength catalog. Use ``garmin-workouts exercises TERM`` to
    search it.
    """
    raw = str(name).strip()
    if "/" in raw:
        # Explicit keys are passed through as-is: Garmin knows categories
        # (and custom exercises) that garminconnect's catalog doesn't list.
        cat, ex = (p.strip().upper() for p in raw.split("/", 1))
        if not cat:
            raise SpecError(f"Missing exercise category in {name!r}")
        return cat, ex
    by_name = {e["name"].lower(): e for e in catalog.EXERCISES}
    if raw.lower() in by_name:
        e = by_name[raw.lower()]
        return e["category"], e["exercise"]
    key = raw.upper().replace(" ", "_").replace("-", "_")
    matches = [e for e in catalog.EXERCISES if e["exercise"] == key]
    if len(matches) == 1:
        return matches[0]["category"], matches[0]["exercise"]
    if len(matches) > 1:
        opts = ", ".join(f"{e['category']}/{e['exercise']}" for e in matches)
        raise SpecError(f"Exercise {name!r} is ambiguous, write one of: {opts}")
    if key in catalog.CATEGORIES:
        return key, key
    hints = ", ".join(e["name"] for e in catalog.find(raw)[:5])
    raise SpecError(f"Unknown exercise {name!r}" + (f" (did you mean: {hints}?)" if hints else ""))


def exercise_label(category: str | None, exercise: str | None) -> str | None:
    """Shortest spec string that resolves back to this (category, exercise)."""
    if not category:
        return None
    if not exercise:
        return f"{category}/"
    matches = [e for e in catalog.EXERCISES if e["exercise"] == exercise]
    if len(matches) == 1 and matches[0]["category"] == category:
        return exercise
    if not matches and exercise == category:
        return category
    return f"{category}/{exercise}"


# --- Spec -> Garmin JSON ----------------------------------------------------


def _sport(key: Any) -> dict[str, Any]:
    k = str(key or "strength_training").strip().lower().replace(" ", "_")
    k = SPORT_ALIASES.get(k, k)
    if k not in SPORTS:
        raise SpecError(f"Unknown sport {key!r}; use one of {', '.join(SPORTS)}")
    return {"sportTypeId": SPORTS[k], "sportTypeKey": k}


def _step_type(kind: str) -> dict[str, Any]:
    if kind not in STEP_TYPES:
        raise SpecError(f"Unknown step type {kind!r}; use one of {', '.join(STEP_TYPES)}")
    return {"stepTypeId": STEP_TYPES[kind], "stepTypeKey": kind}


def _condition(key: str) -> dict[str, Any]:
    cid, ckey, displayable = CONDITIONS[key]
    return {"conditionTypeId": cid, "conditionTypeKey": ckey, "displayable": displayable}


def _target(key: str) -> dict[str, Any]:
    tid, tkey = TARGETS[key]
    return {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tkey}


def _normalize_step(raw: Any) -> dict[str, Any]:
    """Expand shorthands like ``{rest: 30s}`` or ``{warmup: 5m}``."""
    if not isinstance(raw, dict):
        raise SpecError(f"Each step must be a mapping, got {raw!r}")
    step = dict(raw)
    for kind in ("warmup", "cooldown", "rest", "recovery"):
        if kind in step and "type" not in step:
            val = step.pop(kind)
            step["type"] = kind
            if isinstance(val, dict):
                step.update(val)
            elif val in ("lap", True):
                step["lap"] = True
            elif val is not None:
                step["time"] = val
    return step


def _executable(step: dict[str, Any], order: int) -> dict[str, Any]:
    kind = step.get("type", "interval")
    ends = [k for k in ("time", "reps", "distance", "calories", "lap") if k in step]
    if len(ends) > 1:
        raise SpecError(f"Step has more than one end condition ({', '.join(ends)}): {step}")
    end = ends[0] if ends else "lap"

    d: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": _step_type(kind),
        "endCondition": _condition(end),
        "targetType": _target("none"),
    }
    if end == "time":
        d["endConditionValue"] = parse_duration(step["time"])
    elif end == "distance":
        d["endConditionValue"] = parse_distance(step["distance"])
    elif end in ("reps", "calories"):
        d["endConditionValue"] = float(step[end])

    if "exercise" in step:
        d["category"], ex = resolve_exercise(step["exercise"])
        d["exerciseName"] = ex or None
    if "weight" in step:
        d["weightValue"] = parse_weight(step["weight"])
        d["weightUnit"] = dict(POUND)
    if step.get("note"):
        d["description"] = str(step["note"])

    targets = [k for k in ("hr_zone", "hr", "power_zone", "power", "pace", "speed", "cadence") if k in step]
    if len(targets) > 1:
        raise SpecError(f"Step has more than one target ({', '.join(targets)}): {step}")
    if targets:
        t = targets[0]
        val = step[t]
        if t == "hr_zone":
            d["targetType"], d["zoneNumber"] = _target("hr"), int(val)
        elif t == "power_zone":
            d["targetType"], d["zoneNumber"] = _target("power"), int(val)
        elif t == "pace":
            d["targetType"] = _target("pace")
            d["targetValueOne"], d["targetValueTwo"] = _pace_to_mps(val)
        elif t == "speed":  # mph range
            lo, hi = _range(val, "speed")
            d["targetType"] = _target("speed")
            d["targetValueOne"], d["targetValueTwo"] = lo * _MILE / 3600, hi * _MILE / 3600
        else:
            d["targetType"] = _target(t)
            d["targetValueOne"], d["targetValueTwo"] = _range(val, t)

    unknown = set(step) - {
        "type", "time", "reps", "distance", "calories", "lap", "exercise", "weight",
        "note", "extra", *targets,
    }
    if unknown:
        raise SpecError(f"Unknown step field(s) {sorted(unknown)} in {step}")
    d.update(step.get("extra") or {})
    return d


def _build_steps(items: list[Any], counter: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items or []:
        if isinstance(raw, dict) and "repeat" in raw:
            counter[0] += 1
            rounds = int(raw["repeat"])
            group: dict[str, Any] = {
                "type": "RepeatGroupDTO",
                "stepOrder": counter[0],
                "stepType": _step_type("repeat"),
                "numberOfIterations": rounds,
                "endCondition": _condition("iterations"),
                "endConditionValue": float(rounds),
                "smartRepeat": False,
            }
            if raw.get("skip_last_rest"):
                group["skipLastRestStep"] = True
            group["workoutSteps"] = _build_steps(raw.get("steps") or [], counter)
            if not group["workoutSteps"]:
                raise SpecError("A repeat needs at least one step")
            out.append(group)
        else:
            counter[0] += 1
            out.append(_executable(_normalize_step(raw), counter[0]))
    return out


def _step_seconds(steps: list[dict[str, Any]]) -> float:
    total = 0.0
    for s in steps:
        if s["type"] == "RepeatGroupDTO":
            total += s["numberOfIterations"] * _step_seconds(s["workoutSteps"])
        elif s["endCondition"]["conditionTypeKey"] == "time":
            total += s.get("endConditionValue") or 0
    return total


def to_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """Build the Garmin Connect workout JSON for a spec."""
    if not spec.get("name"):
        raise SpecError("A workout spec needs a name")
    has_steps, has_segments = "steps" in spec, "segments" in spec
    if has_steps == has_segments:
        raise SpecError("Give either 'steps' (one sport) or 'segments' (multi-sport), not both")

    counter = [0]  # stepOrder is numbered depth-first across the whole workout
    if has_steps:
        sport = _sport(spec.get("sport"))
        segments = [{
            "segmentOrder": 1,
            "sportType": sport,
            "workoutSteps": _build_steps(spec["steps"], counter),
        }]
    else:
        sport = _sport(spec.get("sport", "multi_sport"))
        segments = [
            {
                "segmentOrder": i,
                "sportType": _sport(seg.get("sport")),
                "workoutSteps": _build_steps(seg.get("steps") or [], counter),
            }
            for i, seg in enumerate(spec["segments"], 1)
        ]
    if not any(seg["workoutSteps"] for seg in segments):
        raise SpecError(f"Workout {spec['name']!r} has no steps")

    if "estimated_minutes" in spec:
        est = float(spec["estimated_minutes"]) * 60
    else:
        est = sum(_step_seconds(seg["workoutSteps"]) for seg in segments)

    payload: dict[str, Any] = {
        "workoutName": str(spec["name"]),
        "sportType": sport,
        "estimatedDurationInSecs": int(est),
        "workoutSegments": segments,
    }
    if spec.get("description"):
        payload["description"] = str(spec["description"]).strip()
    if spec.get("id"):
        payload["workoutId"] = int(spec["id"])
    return payload


# --- Garmin JSON -> spec ----------------------------------------------------


def _num(v: float) -> int | float:
    return int(v) if float(v).is_integer() else round(v, 2)


def _step_to_spec(s: dict[str, Any]) -> dict[str, Any]:
    if s.get("type") == "RepeatGroupDTO":
        out: dict[str, Any] = {"repeat": int(s.get("numberOfIterations") or s.get("endConditionValue") or 1)}
        if s.get("skipLastRestStep"):
            out["skip_last_rest"] = True
        out["steps"] = [_step_to_spec(c) for c in s.get("workoutSteps") or []]
        return out

    kind = (s.get("stepType") or {}).get("stepTypeKey") or "interval"
    out = {}
    if kind != "interval":
        out["type"] = kind
    ex = exercise_label(s.get("category"), s.get("exerciseName"))
    if ex:
        out["exercise"] = ex

    end = _CONDITION_BY_KEY.get((s.get("endCondition") or {}).get("conditionTypeKey"), "lap")
    val = s.get("endConditionValue")
    if end == "time" and val:
        out["time"] = format_duration(val)
    elif end == "distance" and val:
        out["distance"] = format_distance(val)
    elif end in ("reps", "calories") and val is not None:
        out[end] = _num(val)
    elif end == "lap":
        out["lap"] = True

    w, unit = s.get("weightValue"), s.get("weightUnit") or {}
    if w is not None and w > 0:
        if unit.get("unitKey") == "kilogram":
            # garminconnect stores kg targets in grams
            w = w / (unit.get("factor") or 1000.0) * _KG_TO_LB
        out["weight"] = f"{round(w, 1):g}lb"

    tkey = _TARGET_BY_KEY.get((s.get("targetType") or {}).get("workoutTargetTypeKey") or "no.target")
    lo, hi, zone = s.get("targetValueOne"), s.get("targetValueTwo"), s.get("zoneNumber")
    extra: dict[str, Any] = {}
    if tkey in ("hr", "power") and zone:
        out[f"{tkey}_zone"] = int(zone)
    elif tkey == "pace" and lo and hi:
        out["pace"] = f"{_mps_to_pace(hi)}-{_mps_to_pace(lo)}/mi"
    elif tkey == "speed" and lo and hi:
        out["speed"] = f"{lo * 3600 / _MILE:.1f}-{hi * 3600 / _MILE:.1f}"
    elif tkey in ("hr", "power", "cadence") and lo is not None and hi is not None:
        out[tkey] = f"{_num(lo)}-{_num(hi)}"
    elif tkey not in (None, "none"):
        extra.update({k: s[k] for k in ("targetType", "targetValueOne", "targetValueTwo", "zoneNumber") if s.get(k) is not None})
    elif tkey is None:
        extra.update({k: s[k] for k in ("targetType", "targetValueOne", "targetValueTwo", "zoneNumber") if s.get(k) is not None})

    if s.get("description"):
        out["note"] = s["description"]

    if s.get("secondaryTargetType"):
        extra.update({k: s[k] for k in s if k.startswith("secondary") and s[k] is not None})
    if s.get("endConditionCompare"):
        extra["endConditionCompare"] = s["endConditionCompare"]
    for k, v in s.items():
        if k not in _KNOWN_STEP_FIELDS and v not in (None, "", [], {}):
            extra[k] = v
    if extra:
        out["extra"] = extra
    # Prefer the shorthand ``{rest: 20s}`` / ``{warmup: 5m, note: ...}``.
    if kind in ("warmup", "cooldown", "rest", "recovery") and "exercise" not in out:
        if "time" in out:
            short = {kind: out.pop("time")}
        elif out.get("lap"):
            out.pop("lap")
            short = {kind: "lap"}
        else:
            return out
        out.pop("type", None)
        return short | out
    return out


def from_garmin(workout: dict[str, Any]) -> dict[str, Any]:
    """Turn a workout from ``get_workout_by_id`` into an editable spec."""
    sport = (workout.get("sportType") or {}).get("sportTypeKey") or "other"
    spec: dict[str, Any] = {
        "id": workout.get("workoutId"),
        "name": workout.get("workoutName"),
        "sport": sport,
    }
    if workout.get("description"):
        spec["description"] = workout["description"]
    segments = workout.get("workoutSegments") or []
    if len(segments) == 1 and sport != "multi_sport":
        spec["steps"] = [_step_to_spec(s) for s in segments[0].get("workoutSteps") or []]
    else:
        spec["segments"] = [
            {
                "sport": (seg.get("sportType") or {}).get("sportTypeKey") or sport,
                "steps": [_step_to_spec(s) for s in seg.get("workoutSteps") or []],
            }
            for seg in segments
        ]
    try:
        computed = sum(
            _step_seconds(seg["workoutSteps"]) for seg in to_payload(spec)["workoutSegments"]
        )
    except SpecError:
        computed = 0.0
    est = workout.get("estimatedDurationInSecs")
    if est and abs(est - computed) > 30:
        spec["estimated_minutes"] = _num(round(est / 60, 1))
    if spec["id"] is None:
        del spec["id"]
    return spec
