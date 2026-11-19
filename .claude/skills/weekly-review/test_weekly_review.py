"""Offline tests: python -m pytest .claude/skills/weekly-review"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "bin" / "weekly-review"
_loader = importlib.machinery.SourceFileLoader("weekly_review", str(BIN))
_spec = importlib.util.spec_from_loader("weekly_review", _loader)
wr = importlib.util.module_from_spec(_spec)
_loader.exec_module(wr)


def _leg(aid, kind, start, load, name="Leg"):
    return {"activityId": aid, "activityName": name, "activityTypeDTO": {"typeKey": kind},
            "summaryDTO": {"startTimeLocal": start, "duration": 600, "activityTrainingLoad": load}}


class FakeGarmin:
    def __init__(self, parents, legs):
        self.parents, self.legs = parents, legs

    def get_activity(self, aid):
        if aid in self.parents:
            return {"metadataDTO": {"childIds": self.parents[aid]}}
        return self.legs[aid]


def test_multisport_lift_is_expanded_into_named_legs():
    garmin = FakeGarmin(
        {1: [11, 12, 13]},
        {11: _leg(11, "indoor_cardio", "2026-10-06T06:10:00.0", 10, "Cardio"),
         12: _leg(12, "transition_v2", "2026-10-06T06:20:00.0", 10),
         13: _leg(13, "strength_training", "2026-10-06T06:21:00.0", 55, "Strength Training")},
    )
    parent = {"activityId": 1, "activityName": "Upper Push 1", "activityType": {"typeKey": "multi_sport"},
              "startTimeLocal": "2026-10-06 06:10:00"}
    plain = {"activityId": 2, "activityName": "Walk", "activityType": {"typeKey": "walking"}}
    out = wr.expand(garmin, [parent, plain])
    kinds = [(a["activityType"]["typeKey"], a["activityName"]) for a in out]
    assert kinds == [("indoor_cardio", "Cardio"), ("strength_training", "Upper Push 1"), ("walking", "Walk")]
    # Leg loads arrive as running totals; each leg keeps only its own share.
    assert [a.get("activityTrainingLoad") for a in out[:2]] == [10, 45]
    row = wr._activity_row(out[1])
    assert (row["date"], row["start"], row["type"]) == ("2026-10-06", "06:21", "strength_training")


def test_events_mirror_garmin_calendar(monkeypatch):
    week = {"timezone": "America/Denver",
            "days": {"mon": {"workouts": ["Treadmill Vest Walk 30", "Upper Push 1"]},
                     "sat": {"workouts": ["Zone 2: 45-60 min"]}},
            "google_calendar": {"calendar_id": "cal", "weekday": {"start": "05:30", "end": "06:45", "emoji": "💪"},
                                "sat": {"start": None, "end": None, "emoji": "🚴"}}}
    items = [{"date": "2026-11-23", "title": "Upper Push 1", "workoutId": 1},
             {"date": "2026-11-23", "title": "Treadmill Vest Walk 30", "workoutId": 2},
             {"date": "2026-11-28", "title": "Zone 2: 45-60 min", "workoutId": 3}]
    monkeypatch.setattr(wr.gw, "scheduled", lambda *a: items)
    monkeypatch.setattr(wr, "main_lifts", lambda g, wid: ["Block A (x3): Bench 60lb"])
    mon, sat = wr.events(None, week, wr.dt.date(2026, 11, 23), wr.dt.date(2026, 11, 29))
    assert mon["title"] == "💪 Treadmill Vest Walk 30 + Upper Push 1"
    assert (mon["start"], mon["end"]) == ("2026-11-23T05:30:00", "2026-11-23T06:45:00")
    assert mon["description"] == "Upper Push 1:\nBlock A (x3): Bench 60lb"
    assert sat["title"] == "🚴 Zone 2: 45-60 min" and "skip" in sat
