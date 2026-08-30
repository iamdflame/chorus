"""The registry must describe the system that exists, not the one we meant to build.

An agent card that lists `never_sees` fields is a compliance claim. Left unchecked it is
also the easiest thing in the repository to quietly falsify — someone widens the
projection, the card still says the field is withheld, and the document that an approver
relied on is now wrong. These tests make the card falsifiable.
"""

from __future__ import annotations

from dataclasses import asdict

from fleet.registry import PASSENGER_NEVER_SEES, PASSENGER_SEES, build_registry
from kernel.effect import Determinism
from swarm.canonical import project_passenger
from swarm.scenario import build_scenario


def test_every_agent_publishes_a_content_derived_version():
    registry = build_registry()
    assert registry["count"] >= 8
    versions = {a["id"]: a["version"] for a in registry["agents"]}
    assert all(len(v) == 12 for v in versions.values())
    assert len(set(versions.values())) == len(versions), "two agents share a version"


def test_editing_an_instruction_moves_the_version():
    """A hand-maintained version is a promise someone eventually forgets to keep."""
    from fleet.registry import AgentCard

    base = AgentCard(id="x", role="r", summary="s", model="m",
                     thinking_level="low", temperature=0.0, instruction="do the thing")
    edited = AgentCard(id="x", role="r", summary="s", model="m",
                       thinking_level="low", temperature=0.0, instruction="do the OTHER thing")
    renamed_summary = AgentCard(id="x", role="r", summary="different summary", model="m",
                                thinking_level="low", temperature=0.0, instruction="do the thing")

    assert base.version != edited.version, "behaviour changed but the version did not"
    assert base.version == renamed_summary.version, (
        "prose changed and the version moved; versions must track behaviour, not wording"
    )


def test_the_passenger_projection_withholds_everything_the_card_says_it_does():
    """The compliance claim, checked against the projection that actually runs."""
    scenario = build_scenario(passengers=60)
    for passenger in (asdict(p) for p in scenario.passengers[:25]):
        projection = project_passenger(passenger)
        emitted = projection.to_dict()
        rendered = projection.to_prompt()

        for withheld in PASSENGER_NEVER_SEES:
            value = passenger.get(withheld)
            if value in (None, "", 0):
                continue
            assert str(value) not in rendered, (
                f"{withheld} reached the prompt; the card says it never does"
            )
            assert str(value) not in str(emitted.values()), (
                f"{withheld} is present in the projection payload"
            )

        # And the fields it claims to see are exactly the ones it carries — no more.
        assert set(emitted) == set(PASSENGER_SEES), (
            f"projection emits {sorted(set(emitted) ^ set(PASSENGER_SEES))} that the card "
            "does not account for"
        )
        assert emitted["tier"] == passenger["tier"]


def test_irreversible_tools_are_declared_as_such_on_the_cards():
    """A card must not describe a tool as safer than the quarantine gate treats it."""
    registry = build_registry()
    by_tool = {
        t["name"]: t
        for agent in registry["agents"]
        for t in agent["tools"]
    }
    for name in ("issue_refund", "send_customer_email", "escalate_to_human"):
        assert by_tool[name]["reversibility"] == Determinism.EXTERNAL_IRREVERSIBLE.value, (
            f"{name} moves the world and must be published as irreversible"
        )
    assert by_tool["record_ledger_entry"]["has_compensator"] is True


def test_reversibility_classes_are_documented_for_an_approver():
    classes = build_registry()["reversibility_classes"]
    assert set(classes) == {d.value for d in Determinism}
    assert all(isinstance(v, str) and v for v in classes.values())
