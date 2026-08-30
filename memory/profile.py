"""Memory that survives contact with collapse.

The track asks for context that persists across weeks of asynchronous operation: a
returning traveller should not have to re-explain that their mother cannot manage stairs.
The obvious implementation destroys this product.

    Per-traveller memory in the prompt is identity-bearing and anti-collapse. If every
    returning passenger carries personal history into their elicitation, every prompt
    becomes unique, every address becomes unique, and collapse goes to 1x. The system
    would remember everyone and reason about no one twice.

That is the same constraint the injection analysis arrives at from the other side: anything
traveller-specific that reaches shared reasoning either makes it unshareable or makes it
poisonable. There is no version that keeps both.

So memory does not go in the prompt. **Memory feeds the projection.**

A remembered constraint — *this traveller always needs assistance*, *this traveller will not
split their party* — is a fact about the traveller, and facts about travellers already have
a home: the record-sourced half of the projection, beside tier and hotel entitlement. A
profile therefore changes **which cohort someone lands in**, never what that cohort thinks.

    remembered            what it changes             what it does not change
    ----------------------------------------------------------------------------
    needs assistance      constraints -> assisted     the prompt for `assisted`
    never splits party    the cohort they join        that cohort's shared answer
    hotel entitlement     the cohort they join        anyone else's reasoning

The consequences are all good and none of them were free anywhere else in this design:
collapse is untouched because the lattice is unchanged; privacy is untouched because
nothing identifying is added to any prompt; and the memory is *auditable*, because a
profile is a small set of typed fields rather than an opaque embedding whose influence on a
decision cannot be explained to a regulator.

Profiles are timestamped from the injected clock rather than the wall, so a session six
weeks later in simulated time is a real test rather than a sleep.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from kernel.clock import Clock
from swarm.canonical import Projection

# How long a remembered constraint is trusted without being observed again.
#
# Not forever. A traveller who needed a wheelchair after surgery in March may not need one
# in December, and a system that remembers permanently is one that mislabels people for
# years. Assistance needs are re-confirmed sooner than travel preferences because getting
# them wrong is worse in one direction than the other.
TTL_DAYS = {
    "needs_assistance": 180,
    "never_splits_party": 365,
    "accepts_nearby_airport": 365,
    "hotel_entitled": 365,
}
DEFAULT_TTL_DAYS = 365


@dataclass(frozen=True, slots=True)
class Observation:
    """One durable fact, with when it was learned and where from."""

    value: bool
    observed_at: str
    source: str = "stated"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "observed_at": self.observed_at,
                "source": self.source}


@dataclass
class Profile:
    """What the airline has learned about one traveller across disruptions.

    Deliberately a handful of typed booleans rather than free text or an embedding. A
    profile that cannot be printed on one line and explained to the person it describes is
    not a memory an airline can defend, and free text here would re-open the injection
    path that the typed projection closes.
    """

    passenger_id: str
    observations: dict[str, Observation] = field(default_factory=dict)
    disruptions_seen: int = 0

    def observe(self, field_name: str, value: bool, *, clock: Clock,
                source: str = "stated") -> None:
        self.observations[field_name] = Observation(
            value=value, observed_at=clock.now().isoformat(), source=source,
        )

    def live(self, field_name: str, *, clock: Clock) -> bool | None:
        """The value, if it is still within its time to live.

        An expired observation returns None rather than its last value, so a stale
        constraint stops being applied instead of quietly persisting forever.
        """
        got = self.observations.get(field_name)
        if got is None:
            return None
        from datetime import datetime

        try:
            seen = datetime.fromisoformat(got.observed_at)
        except ValueError:
            return None
        age_days = (clock.now() - seen).total_seconds() / 86_400
        if age_days < 0:
            # Recorded after the moment being asked about — a read from before the write.
            return None
        if age_days > TTL_DAYS.get(field_name, DEFAULT_TTL_DAYS):
            return None
        return got.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "passenger_id": self.passenger_id,
            "disruptions_seen": self.disruptions_seen,
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Profile:
        return cls(
            passenger_id=payload["passenger_id"],
            disruptions_seen=payload.get("disruptions_seen", 0),
            observations={
                k: Observation(**v) for k, v in payload.get("observations", {}).items()
            },
        )


def apply(projection: Projection, profile: Profile | None, *, clock: Clock) -> Projection:
    """Fold remembered facts into the projection, before bucketing.

    Only ever *raises* a constraint, never lowers one. A traveller who said last time that
    they need assistance keeps that until it expires; a traveller who said nothing this
    time does not have a remembered need removed by silence. Forgetting on absence would
    make memory actively dangerous — the one case where being wrong strands someone at a
    gate they cannot reach.
    """
    if profile is None:
        return projection

    updated = projection
    if profile.live("needs_assistance", clock=clock) and updated.constraints != "assisted":
        updated = replace(updated, constraints="assisted")
    if profile.live("hotel_entitled", clock=clock) and not updated.hotel_entitled:
        updated = replace(updated, hotel_entitled=True)
    return updated


def remembered_fields() -> tuple[str, ...]:
    """What memory is allowed to influence. Anything not listed here cannot be recalled."""
    return tuple(sorted(TTL_DAYS))
