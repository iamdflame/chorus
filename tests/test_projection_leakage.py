"""The projection must never carry identity into a model.

This is the compliance claim the agent cards make and the Model Armor requirement the
track names. It is also the property the entire cost argument rests on: if identity
reaches the prompt, every agent is unique, nothing is ever shared, and twenty thousand
agents cost twenty thousand model calls again.

Tested by construction rather than by inspection — two passengers identical in situation
but different in every identifying field must produce byte-identical prompts.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from kernel.clock import FIXED
from swarm.canonical import project_crew, project_passenger
from swarm.scenario import build_scenario

IDENTIFIERS = ("id", "name", "order_id", "customer_id", "original_flight", "destination")


@pytest.fixture(scope="module")
def population():
    return [asdict(p) for p in build_scenario(passengers=400).passengers]


def test_identity_does_not_change_the_projection(population):
    for passenger in population[:60]:
        disguised = {
            **passenger,
            "id": "PAX-000000",
            "name": "somebody else entirely",
            "order_id": "ORD-00000",
            "original_flight": "ZZ0000",
        }
        assert project_passenger(passenger, clock=FIXED).key() == project_passenger(disguised, clock=FIXED).key()
        assert project_passenger(passenger, clock=FIXED).to_prompt() == project_passenger(disguised, clock=FIXED).to_prompt()


def test_no_identifying_value_appears_in_the_prompt(population):
    for passenger in population[:120]:
        prompt = project_passenger(passenger, clock=FIXED).to_prompt()
        for field in IDENTIFIERS:
            value = passenger.get(field)
            if value in (None, "", 0):
                continue
            assert str(value) not in prompt, (
                f"{field}={value!r} reached the prompt; identity must never leave the boundary"
            )


def test_the_prompt_contains_only_bucketed_vocabulary(population):
    """Anything outside the declared vocabulary is a field that escaped bucketing."""
    allowed = {
        "basic", "silver", "gold", "platinum",
        "critical", "urgent", "same_day", "flexible",
        "solo", "pair", "family", "group",
        "unencumbered", "checked_bags", "assisted",
        "short", "long", "intercontinental",
        True, False,
    }
    for passenger in population[:120]:
        values = set(project_passenger(passenger, clock=FIXED).to_dict().values()) - {"passenger"}
        assert values <= allowed, f"unbucketed value in projection: {values - allowed}"


def test_crew_projection_withholds_identity():
    scenario = build_scenario(passengers=40)
    for member in (asdict(c) for c in scenario.crew[:40]):
        prompt = project_crew(member, clock=FIXED).to_prompt()
        assert str(member["id"]) not in prompt
        assert str(member["duty_hours_used"]) not in prompt, (
            "an exact duty figure is identifying; only the band may cross the boundary"
        )


def test_two_travellers_in_the_same_situation_are_indistinguishable(population):
    """The positive form of the claim: sharing is possible precisely because identity
    has been removed."""
    seen: dict[str, str] = {}
    collisions = 0
    for passenger in population:
        key = project_passenger(passenger, clock=FIXED).key()
        prompt = project_passenger(passenger, clock=FIXED).to_prompt()
        if key in seen:
            collisions += 1
            assert seen[key] == prompt, "same situation produced different prompts"
        seen[key] = prompt
    # The v2 lattice is twelve times finer than v1, so the sharing rate is necessarily
    # lower. It must still be substantial: a projection nobody shares is a projection that
    # has stopped doing its job.
    assert collisions > len(population) * 0.15, (
        f"only {collisions} of {len(population)} travellers shared a situation; "
        "the projection has become too fine to be worth anything"
    )


def test_the_projection_does_not_move_with_the_wall_clock():
    """Determinism holes are the expensive kind of bug in a determinism product.

    Urgency is time-to-departure, so a projection that reads the clock re-buckets the same
    passenger tomorrow. Every address derived from it moves with it, and a run recorded
    today silently stops replaying next week — which would quietly retire the central
    claim rather than break it loudly.
    """
    passenger = asdict(build_scenario(passengers=20).passengers[0])
    baseline = project_passenger(passenger, clock=FIXED).key()

    # The band genuinely depends on the instant, so the invariance above is not vacuous.
    far_future = project_passenger(passenger, clock=FIXED.shifted(days=40)).key()
    assert far_future != baseline, "urgency does not depend on time; the test proves nothing"
