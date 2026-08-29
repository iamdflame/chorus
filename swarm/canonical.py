"""Canonical projection — the mechanism that makes a swarm affordable.

Ten thousand agents would mean ten thousand model calls, which is why nobody gives every
entity its own agent. But most of those agents are not thinking different thoughts. Two
stranded platinum passengers, both travelling alone, both needing to move within four
hours, both with a checked bag, face the *same decision*. Their names differ. Their
reasoning does not.

So an agent reasons over a canonical projection of itself — the decision-relevant features
only, bucketed — and acts on its full entity. Because the kernel addresses every model
call by `H(kind, role, causal parents, request)`, two agents with identical projections at
the same point in a round produce the *same address*, and the second one hits the store
instead of the model.

The split that makes this sound:

    reasoning   shared   what do I want, and how flexible am I
    matching    private  which specific seat do I get

Reasoning is a function of a passenger's *situation*; matching is a function of their
identity and the live inventory. Collapsing the first is correct. Collapsing the second
would be a bug, so it is never sent to a model at all — it is deterministic allocation
over the shared preferences.

Buckets are deliberately coarse. Every extra distinction multiplies the number of distinct
thoughts, and a distinction that does not change the decision buys nothing but cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# -- bucketing ----------------------------------------------------------------

def urgency_band(hours_until: float) -> str:
    """How soon this passenger must move. Drives whether they will accept a worse
    itinerary, which is the single largest factor in their preference."""
    if hours_until <= 4:
        return "critical"
    if hours_until <= 12:
        return "urgent"
    if hours_until <= 24:
        return "same_day"
    return "flexible"


def party_band(size: int) -> str:
    """Whether the party can be split across itineraries."""
    if size == 1:
        return "solo"
    if size == 2:
        return "pair"
    if size <= 4:
        return "family"
    return "group"


def constraint_band(*, checked_bags: int, needs_assistance: bool) -> str:
    """What narrows the set of acceptable itineraries."""
    if needs_assistance:
        return "assisted"
    if checked_bags > 0:
        return "checked_bags"
    return "unencumbered"


@dataclass(frozen=True, slots=True)
class Projection:
    """A passenger's decision-relevant situation, and nothing else."""

    role: str
    tier: str
    urgency: str
    party: str
    constraints: str

    def key(self) -> str:
        return f"{self.role}|{self.tier}|{self.urgency}|{self.party}|{self.constraints}"

    def to_prompt(self) -> str:
        return (
            f"Traveller situation:\n"
            f"- loyalty tier: {self.tier}\n"
            f"- urgency: {self.urgency}\n"
            f"- party: {self.party}\n"
            f"- constraints: {self.constraints}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role, "tier": self.tier, "urgency": self.urgency,
            "party": self.party, "constraints": self.constraints,
        }


def project_passenger(passenger: dict[str, Any], *, now: datetime | None = None) -> Projection:
    """Reduce a passenger to the situation that determines their preferences.

    Identity, destination and flight number are deliberately absent. They decide *which*
    seat the passenger is matched to, never *what kind of itinerary they would accept* —
    and including them would make every passenger's reasoning unique, which is exactly the
    cost nobody can afford.
    """
    moment = now or datetime.now(timezone.utc)
    try:
        scheduled = datetime.fromisoformat(passenger["scheduled_departure"])
        hours = (scheduled - moment).total_seconds() / 3600.0
    except (KeyError, ValueError):
        hours = 24.0

    return Projection(
        role="passenger",
        tier=passenger.get("tier", "basic"),
        urgency=urgency_band(hours),
        party=party_band(int(passenger.get("party_size", 1))),
        constraints=constraint_band(
            checked_bags=int(passenger.get("checked_bags", 0)),
            needs_assistance=bool(passenger.get("needs_assistance", False)),
        ),
    )


def duty_band(hours_remaining: float) -> str:
    if hours_remaining <= 0:
        return "timed_out"
    if hours_remaining <= 2:
        return "marginal"
    if hours_remaining <= 6:
        return "workable"
    return "fresh"


def project_crew(member: dict[str, Any]) -> Projection:
    """Crew reason about duty legality and base position, not about their own name."""
    remaining = max(
        float(member.get("duty_hours_max", 14.0)) - float(member.get("duty_hours_used", 0.0)),
        0.0,
    )
    return Projection(
        role="crew",
        tier=member.get("role", "cabin"),
        urgency=duty_band(remaining),
        party="based" if member.get("base") == "ORD" else "away",
        constraints=f"{len(member.get('qualified_types', []))}_types",
    )


def collapse(entities: list[dict[str, Any]], projector) -> dict[str, list[str]]:
    """Group entities by projection. The returned map's size is the number of distinct
    thoughts the population actually requires."""
    groups: dict[str, list[str]] = {}
    for entity in entities:
        groups.setdefault(projector(entity).key(), []).append(entity["id"])
    return groups
