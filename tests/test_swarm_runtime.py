"""Tests for the module that carries the collapse claim.

`swarm/runtime.py` had no test file. It is the module every headline number comes from,
which is the coverage inversion the audit named: the rigour was concentrated in the kernel
where the marketing wasn't.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict

import pytest

from kernel.branch import PRIMARY
from kernel.clock import FIXED
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from swarm.canonical import bind, project_passenger
from swarm.runtime import Swarm, SwarmMetrics
from swarm.scenario import build_scenario
from tests.instruments import CountingLlm


def test_collapse_is_measured_from_real_calls_not_distinct_situations():
    """The two were both called 'collapse' and disagreed by 16% in one document."""
    m = SwarmMetrics(agents_invoked=20000, model_calls=222, distinct_thoughts=192)
    assert round(m.collapse, 1) == 90.1, "collapse must divide by calls actually paid for"
    assert round(m.structural_ceiling, 1) == 104.2, "the ceiling divides by distinct situations"
    assert m.to_dict()["duplicate_calls"] == 30


def test_a_fully_replayed_run_reports_no_collapse():
    m = SwarmMetrics(agents_invoked=20000, model_calls=0, distinct_thoughts=0)
    assert m.collapse == 0.0
    assert m.naive_cost_usd == 0.0


def test_failed_agents_stay_in_the_denominator():
    """A failure that vanishes from the denominator flatters every ratio above it."""
    m = SwarmMetrics(agents_invoked=100, model_calls=10, failed=40)
    assert m.collapse == 10.0
    assert m.to_dict()["failed"] == 40


def test_naive_cost_scales_with_agents_not_calls():
    m = SwarmMetrics(agents_invoked=1000, model_calls=10, cost_usd=0.10)
    # $0.01 per real call, so one call per agent would be $10.
    assert m.naive_cost_usd == pytest.approx(10.0, rel=0.01)


class TinyLlm(CountingLlm):
    model: str = "tiny"


@pytest.mark.asyncio
async def test_a_swarm_run_counts_every_agent_it_was_given():
    store = InMemoryEffectStore()
    swarm = Swarm(store=store, branch_id=PRIMARY, mode=Mode.REPLAY, concurrency=4)
    for role in swarm.agents:
        swarm.agents[role].model = TinyLlm()

    scenario = build_scenario(passengers=40)
    passengers = [asdict(p) for p in scenario.passengers]

    preferences, metrics = await swarm.run(
        entities=passengers, projector=bind(project_passenger, FIXED),
        role="passenger", context="ORD closed.", round_id="t1",
    )
    assert metrics.agents_invoked == len(passengers), (
        "agents_invoked must equal the population, including any that failed"
    )
    assert metrics.model_calls + metrics.cache_hits + metrics.coalesced >= len(passengers) - metrics.failed
    assert metrics.distinct_thoughts <= metrics.model_calls or metrics.model_calls == 0


@pytest.mark.asyncio
async def test_identical_situations_do_not_each_reach_the_model():
    """The claim itself, at small scale, through the real runtime."""
    store = InMemoryEffectStore()
    swarm = Swarm(store=store, branch_id=PRIMARY, mode=Mode.REPLAY, concurrency=3)
    model = TinyLlm()
    for role in swarm.agents:
        swarm.agents[role].model = model

    scenario = build_scenario(passengers=120)
    passengers = [asdict(p) for p in scenario.passengers]
    distinct = len({project_passenger(p, clock=FIXED).key() for p in passengers})

    _, metrics = await swarm.run(
        entities=passengers, projector=bind(project_passenger, FIXED),
        role="passenger", context="ORD closed.", round_id="t2",
    )
    assert metrics.model_calls < len(passengers), "no sharing happened at all"
    assert metrics.model_calls <= distinct + metrics.failed, (
        f"{metrics.model_calls} calls for {distinct} distinct situations — "
        "more calls than situations means duplicate work survived coalescing"
    )
