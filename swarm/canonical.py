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
from datetime import datetime
from typing import Any

from swarm.scenario import EPOCH

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


#: Bumped whenever the shape of a projection changes. It is part of the key, so a bump
#: invalidates every recorded thought cleanly rather than silently mixing answers computed
#: under different schemas — the worst kind of cache bug, because the wrong answer is
#: well-formed.
SCHEMA_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class Projection:
    """A passenger's decision-relevant situation, and nothing else.

    v1 carried four fields while the elicitation prompt asked about hotels, alternate
    airports and misconnections — none of which the projection contained. That is **false
    sharing**: a traveller to London and one to Dallas received the same reasoning about
    whether a nearby airport would do, because as far as the address was concerned they
    were the same person. Sharing is only sound when the situations are genuinely
    equivalent, and equivalence has to include everything the decision depends on.

    Fixing it costs collapse, and should. A projection that omits load-bearing fields
    collapses beautifully and answers the wrong question.
    """

    role: str
    tier: str            # 4
    urgency: str         # 4
    party: str           # 4
    constraints: str     # 3
    haul: str = "short"  # 3  — the prompt asks about alternate airports
    hotel_entitled: bool = False   # 2  — the prompt asks whether they need a hotel
    misconnect: bool = False       # 2  — 38% of travellers, previously invisible
    schema_version: str = SCHEMA_VERSION

    def key(self) -> str:
        return "|".join((
            self.schema_version, self.role, self.tier, self.urgency, self.party,
            self.constraints, self.haul,
            "hotel" if self.hotel_entitled else "nohotel",
            "misconnect" if self.misconnect else "origin",
        ))

    def to_prompt(self) -> str:
        return (
            f"Traveller situation:\n"
            f"- loyalty tier: {self.tier}\n"
            f"- urgency: {self.urgency}\n"
            f"- party: {self.party}\n"
            f"- constraints: {self.constraints}\n"
            f"- journey: {self.haul}\n"
            f"- overnight accommodation covered: "
            f"{'yes' if self.hotel_entitled else 'no'}\n"
            f"- disrupted mid-journey: {'yes' if self.misconnect else 'no'}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role, "tier": self.tier, "urgency": self.urgency,
            "party": self.party, "constraints": self.constraints,
            "haul": self.haul, "hotel_entitled": self.hotel_entitled,
            "misconnect": self.misconnect,
        }


def haul_band(region: str) -> str:
    """How far they are going, which is what makes an alternate airport acceptable or not.

    Not the destination itself: the destination decides which seat they are matched to and
    would make every traveller unique. The *class* of journey is what changes the decision.
    """
    if region in ("europe", "asia", "south_america"):
        return "intercontinental"
    if region == "domestic_long":
        return "long"
    return "short"


def project_passenger(passenger: dict[str, Any], *, clock: Clock) -> Projection:
    """Reduce a passenger to the situation that determines their preferences.

    Identity and flight number are deliberately absent: they decide *which* seat the
    passenger is matched to, and including them would make every passenger's reasoning
    unique, which is exactly the cost nobody can afford.

    `clock` is required and has no default. Urgency is a function of time-to-departure,
    so an ambient `datetime.now()` here means the same passenger falls into a different
    band tomorrow, which changes their projection, which changes every address derived
    from it — and a run recorded today silently stops replaying next week. A default would
    have hidden that; requiring the argument makes the type checker find every call site
    that has not decided which instant it means.
    """
    moment = clock.now()
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
        haul=haul_band(str(passenger.get("region", ""))),
        hotel_entitled=bool(passenger.get("has_hotel_entitlement", False)),
        misconnect=bool(passenger.get("is_misconnect", False)),
    )


def duty_band(hours_remaining: float) -> str:
    if hours_remaining <= 0:
        return "timed_out"
    if hours_remaining <= 2:
        return "marginal"
    if hours_remaining <= 6:
        return "workable"
    return "fresh"


def project_crew(member: dict[str, Any], *, clock: Clock | None = None) -> Projection:
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


def bind(projector, clock: Clock):
    """A projector with its clock already supplied.

    `collapse` takes a callable of one argument, and threading a clock through every call
    site by hand is exactly the kind of friction that makes someone reach for a default.
    """
    return lambda entity: projector(entity, clock=clock)


def collapse(entities: list[dict[str, Any]], projector) -> dict[str, list[str]]:
    """Group entities by projection. The returned map's size is the number of distinct
    thoughts the population actually requires."""
    groups: dict[str, list[str]] = {}
    for entity in entities:
        groups.setdefault(projector(entity).key(), []).append(entity["id"])
    return groups
