"""Offline tests: python -m pytest .claude/skills/garmin-workouts"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from workout_spec import (  # noqa: E402
    SpecError,
    from_garmin,
    parse_distance,
    parse_duration,
    resolve_exercise,
    to_payload,
)


def test_durations_and_distances():
    assert parse_duration(90) == 90
    assert parse_duration("1m30s") == 90
    assert parse_duration("1:30") == 90
    assert parse_duration("1h") == 3600
    assert parse_distance("400m") == 400
    assert round(parse_distance("1mi")) == 1609
    with pytest.raises(SpecError):
        parse_duration("soon")


def test_exercise_resolution():
    assert resolve_exercise("GOBLET_SQUAT") == ("SQUAT", "GOBLET_SQUAT")
    assert resolve_exercise("Goblet Squat") == ("SQUAT", "GOBLET_SQUAT")
    assert resolve_exercise("core/russian_twist") == ("CORE", "RUSSIAN_TWIST")
    with pytest.raises(SpecError, match="ambiguous"):
        resolve_exercise("RUSSIAN_TWIST")
    with pytest.raises(SpecError):
        resolve_exercise("Underwater Basket Weaving")


def test_payload_shape():
    spec = {
        "name": "Test",
        "sport": "run",
        "steps": [
            {"warmup": "10m", "hr_zone": 2},
            {"repeat": 4, "steps": [
                {"distance": "400m", "pace": "7:00-7:30/mi"},
                {"recovery": "90s"},
            ]},
            {"cooldown": "lap"},
        ],
    }
    p = to_payload(spec)
    steps = p["workoutSegments"][0]["workoutSteps"]
    assert p["sportType"]["sportTypeKey"] == "running"
    assert [s["stepOrder"] for s in steps] == [1, 2, 5]
    assert [c["stepOrder"] for c in steps[1]["workoutSteps"]] == [3, 4]
    assert steps[0]["zoneNumber"] == 2
    assert steps[2]["endCondition"]["conditionTypeKey"] == "lap.button"
    assert p["estimatedDurationInSecs"] == 600 + 4 * 90


def test_rejects_bad_specs():
    with pytest.raises(SpecError):
        to_payload({"name": "x", "steps": [{"time": "1m", "reps": 5}]})
    with pytest.raises(SpecError):
        to_payload({"name": "x", "steps": [{"tiem": "1m"}]})
    with pytest.raises(SpecError):
        to_payload({"steps": [{"time": "1m"}]})


@pytest.mark.parametrize("path", sorted((HERE / "workouts").glob("*.yaml")), ids=lambda p: p.name)
def test_repo_specs_round_trip(path):
    spec = yaml.safe_load(path.read_text())
    payload = to_payload(spec)
    again = from_garmin({**payload, "workoutId": spec["id"]})
    assert to_payload(again) == payload
