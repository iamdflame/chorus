"""Concurrency must not dissolve the collapse.

The attack this answers: lookup happens *before* the model call, so N agents in one
cohort that start together all miss, all call the model, and all write the same answer.
The store then reports a healthy hit rate while the bill records N calls — the saving
degrades exactly as you parallelise, which is the one thing you would do to make a swarm
fast.

These tests run genuinely concurrent agents through the real interposer and assert the
model layer is reached once.
"""

from __future__ import annotations

import asyncio

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from kernel.branch import PRIMARY
from kernel.interposer import LightconePlugin, Mode
from kernel.singleflight import SingleFlight
from kernel.store import InMemoryEffectStore
from tests.instruments import CountingLlm

APP, USER = "singleflight-test", "tester"


class SlowCountingLlm(CountingLlm):
    """Counts invocations and takes long enough for the herd to pile up behind it.

    Without the delay the first agent finishes before the others start, and the test
    passes for the wrong reason.
    """

    delay: float = 0.08

    async def generate_content_async(self, llm_request, stream: bool = False):
        await asyncio.sleep(self.delay)
        async for response in super().generate_content_async(llm_request, stream):
            yield response


async def run_one(store, model, single_flight, anchor: str) -> LightconePlugin:
    plugin = LightconePlugin(
        store=store, branch_id=PRIMARY, mode=Mode.REPLAY,
        seed_parents=(anchor,), single_flight=single_flight,
    )
    sessions = InMemorySessionService()
    agent = LlmAgent(name="passenger_agent", model=model, instruction="Identical instruction.")
    runner = Runner(
        app=App(name=APP, root_agent=agent, plugins=[plugin]), session_service=sessions
    )
    session = await sessions.create_session(app_name=APP, user_id=USER)
    async for _ in runner.run_async(
        user_id=USER, session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="same situation")]),
    ):
        pass
    plugin.flush()
    return plugin


@pytest.mark.asyncio
async def test_a_cohort_starting_together_reaches_the_model_once():
    store, model = InMemoryEffectStore(), SlowCountingLlm()
    sf = SingleFlight()

    plugins = await asyncio.gather(*(run_one(store, model, sf, "round-1") for _ in range(12)))

    assert model.calls == 1, (
        f"12 identical agents reached the model {model.calls} times; without coalescing "
        "the collapse evaporates under concurrency"
    )
    assert sf.coalesced >= 1
    assert sum(p.coalesced for p in plugins) == sf.coalesced


@pytest.mark.asyncio
async def test_without_single_flight_the_herd_stampedes():
    """The control. If this passed too, the test above would prove nothing."""
    store, model = InMemoryEffectStore(), SlowCountingLlm()

    await asyncio.gather(*(run_one(store, model, None, "round-1") for _ in range(12)))

    assert model.calls > 1, (
        "concurrent agents did not duplicate work even without coalescing; "
        "the scenario does not reproduce the problem being fixed"
    )


@pytest.mark.asyncio
async def test_coalesced_is_reported_separately_from_hits():
    """A suppressed call and a cache hit mean different things and must not be conflated:
    one is work already recorded, the other is work about to be duplicated."""
    store, model = InMemoryEffectStore(), SlowCountingLlm()
    sf = SingleFlight()

    first = await asyncio.gather(*(run_one(store, model, sf, "round-1") for _ in range(6)))
    coalesced_first = sum(p.coalesced for p in first)

    # Second wave: the answer is recorded now, so these are hits, not coalesces.
    second = await asyncio.gather(*(run_one(store, model, sf, "round-1") for _ in range(6)))
    assert sum(p.coalesced for p in second) == 0
    assert sum(p.hits for p in second) > 0
    assert coalesced_first > 0
    assert model.calls == 1
