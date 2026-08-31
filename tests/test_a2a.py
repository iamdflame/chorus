"""The A2A card is a mapping over the registry, not a second source of truth.

A hand-maintained copy of what the agents are would drift from the registry, and the drift
would be invisible because both would keep looking plausible. These check the mapping holds
and that the card carries the thing that makes it worth publishing: consequence, not just
capability.
"""

from __future__ import annotations

from fleet.a2a import agent_card
from fleet.registry import build_registry

CARD = agent_card("https://chorus.example")
REGISTRY = build_registry()


class TestShape:
    def test_names_a_protocol_version(self) -> None:
        assert CARD["protocolVersion"]

    def test_urls_are_absolute_and_derived_from_the_base(self) -> None:
        """A card advertising localhost is worse than no card."""
        assert CARD["url"].startswith("https://chorus.example")
        assert CARD["provider"]["url"] == "https://chorus.example"

    def test_declares_the_transports_it_actually_has(self) -> None:
        # /api/swarm streams over SSE, and every effect is kept and addressable.
        assert CARD["capabilities"]["streaming"] is True
        assert CARD["capabilities"]["stateTransitionHistory"] is True
        # Push is not implemented, and saying so is the point.
        assert CARD["capabilities"]["pushNotifications"] is False


class TestMapping:
    def test_every_registered_agent_appears(self) -> None:
        listed = {a["id"] for a in CARD["x-chorus"]["agents"]}
        assert listed == {a["id"] for a in REGISTRY["agents"]}

    def test_every_tool_becomes_a_skill(self) -> None:
        tools = {
            f"{a['id']}.{t['name']}"
            for a in REGISTRY["agents"] for t in a.get("tools", [])
        }
        skills = {s["id"] for s in CARD["skills"]}
        assert tools <= skills

    def test_a_reasoning_agent_is_still_discoverable(self) -> None:
        """An agent with no tools has a skill — its role. Omitting it would make the
        agents that carry the product invisible to discovery."""
        assert "chorus.passenger.reason" in {s["id"] for s in CARD["skills"]}

    def test_versions_come_from_the_registry(self) -> None:
        by_id = {a["id"]: a for a in REGISTRY["agents"]}
        for entry in CARD["x-chorus"]["agents"]:
            assert entry["version"] == by_id[entry["id"]]["version"]


class TestConsequence:
    """What this card carries that most do not."""

    def test_every_skill_declares_whether_it_can_be_undone(self) -> None:
        for skill in CARD["skills"]:
            assert "reversible" in skill["x-chorus"]
            assert isinstance(skill["x-chorus"]["reversible"], bool)

    def test_irreversible_skills_are_marked_as_such(self) -> None:
        """A caller should know an operation is one-way before invoking it, not after."""
        oneway = [s for s in CARD["skills"] if not s["x-chorus"]["reversible"]]
        assert oneway, "a fleet that issues refunds has irreversible skills"
        assert any("refund" in s["id"] for s in oneway)

    def test_the_data_policy_travels_with_the_agent(self) -> None:
        """Every agent states its policy, and the two kinds are distinguishable.

        The projection agents carry a structural guarantee — identity cannot reach them.
        The fleet agents operate on customer records through tools and claim no such
        guarantee. Emitting empty arrays for the second kind would let a caller read
        "declared nothing" as "sees nothing", which is the more dangerous misreading.
        """
        structural = 0
        for entry in CARD["x-chorus"]["agents"]:
            assert entry["dataPolicy"] in ("structural", "undeclared")
            if entry["dataPolicy"] == "structural":
                structural += 1
                assert entry["neverSees"]
            else:
                assert "No field-level guarantee" in entry["dataPolicyNote"]
        assert structural >= 2, "the collapsing agents must carry a structural policy"

    def test_coverage_gaps_are_published_rather_than_silent(self) -> None:
        assert "escalates to a human" in CARD["x-chorus"]["coverageGaps"]
