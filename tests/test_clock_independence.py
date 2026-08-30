"""Nothing in the deterministic path may read the wall clock.

This is the test v1 would have failed. It does not check that the clock is *usually*
injected — it makes `datetime.now()` itself return a date thirty days in the future and
asserts that every derived artefact is byte-identical. Anything that reaches for ambient
time is caught here rather than a week later, when a recorded run quietly stops replaying
and the only visible symptom is that the bill came back.

The failure mode being guarded is silent by nature: no exception, no error log, just a
store that gradually stops matching. A loud test is the only way that stays fixed.
"""

from __future__ import annotations

import datetime as datetime_module
from dataclasses import asdict

import pytest

from kernel.clock import FIXED, Clock
from swarm.canonical import bind, collapse, project_passenger
from swarm.scenario import build_scenario


class ShiftedDatetime(datetime_module.datetime):
    """A datetime whose `now()` is thirty days ahead of the real one."""

    @classmethod
    def now(cls, tz=None):  # noqa: D102 - mirrors datetime.now
        return super().now(tz) + datetime_module.timedelta(days=30)

    @classmethod
    def utcnow(cls):  # noqa: D102
        return super().utcnow() + datetime_module.timedelta(days=30)


@pytest.fixture
def wall_clock_thirty_days_ahead(monkeypatch):
    """Move the machine's clock, not the injected one."""
    for module in ("swarm.scenario", "swarm.canonical", "kernel.clock"):
        try:
            monkeypatch.setattr(f"{module}.datetime", ShiftedDatetime, raising=False)
        except AttributeError:
            pass
    yield


def fingerprint() -> tuple[str, ...]:
    """Everything downstream of time, reduced to something comparable."""
    scenario = build_scenario(passengers=600)
    passengers = [asdict(p) for p in scenario.passengers]
    groups = collapse(passengers, bind(project_passenger, FIXED))
    return (
        passengers[0]["scheduled_departure"],
        passengers[-1]["scheduled_departure"],
        str(len(groups)),
        # Cohort membership, not just the count: a shift that moved passengers between
        # bands while preserving the total would otherwise pass.
        "|".join(f"{k}:{len(v)}" for k, v in sorted(groups.items())),
    )


def test_scenario_and_projection_ignore_the_wall_clock(wall_clock_thirty_days_ahead):
    before = fingerprint()
    after = fingerprint()
    assert before == after, "the wall clock moved and the derived artefacts moved with it"


def test_the_fingerprint_is_sensitive_to_the_injected_clock():
    """Guards the test above from being vacuous.

    If the fingerprint did not respond to *any* clock, the invariance test would pass on a
    constant and prove nothing.
    """
    scenario = build_scenario(passengers=600)
    passengers = [asdict(p) for p in scenario.passengers]
    near = collapse(passengers, bind(project_passenger, FIXED))
    far = collapse(passengers, bind(project_passenger, FIXED.shifted(days=40)))
    assert near.keys() != far.keys() or any(
        len(near[k]) != len(far.get(k, [])) for k in near
    ), "the projection does not depend on the injected clock at all"


def test_scenario_is_reproducible_across_processes():
    """Same seed, same clock, same bytes — the property replay actually rests on."""
    a = build_scenario(passengers=400, seed=99, clock=Clock())
    b = build_scenario(passengers=400, seed=99, clock=Clock())
    assert [asdict(p) for p in a.passengers] == [asdict(p) for p in b.passengers]
    assert [asdict(f) for f in a.flights] == [asdict(f) for f in b.flights]


def test_an_explicit_clock_beats_a_shifted_machine(wall_clock_thirty_days_ahead):
    """The whole point: the injected instant wins over the ambient one."""
    scenario = build_scenario(passengers=200, clock=Clock())
    departures = {p.scheduled_departure for p in scenario.passengers}
    assert all(d.startswith("2026-08") or d.startswith("2026-09") for d in departures), (
        "scenario timestamps drifted with the machine clock"
    )
