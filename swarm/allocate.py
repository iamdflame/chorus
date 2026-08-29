"""Allocation — turning twenty thousand stated preferences into one recovery plan.

The swarm's reasoning is worthless unless something acts on it. This is the half that
must NOT go through a model: matching a specific passenger to a specific seat depends on
their identity and on live inventory, so it is individual by nature and cannot be shared.
Sending it to a model would be both expensive and worse, because allocation under hard
constraints is exactly what deterministic code is good at.

So the split is: agents reason about what they want (shared, expensive, judgement), and
the allocator decides who gets what (individual, cheap, exact). The agents' preferences
are the input that makes the allocation better than a rule could — a passenger who has
said they will accept a downgrade, split their party, or fly to a nearby airport opens
options that a first-come-first-served queue can never see.

Scored against a first-come-first-served baseline, which is what airlines actually fall
back to when a hub goes down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TIER_WEIGHT = {"platinum": 4.0, "gold": 3.0, "silver": 2.0, "basic": 1.0}


@dataclass
class Allocation:
    """The outcome of one recovery plan."""

    strategy: str
    seated: int = 0
    souls_seated: int = 0
    stranded: int = 0
    hotel_granted: int = 0
    parties_split: int = 0
    downgrades: int = 0
    total_wait_hours: float = 0.0
    weighted_satisfaction: float = 0.0
    assignments: dict[str, str] = field(default_factory=dict)

    @property
    def mean_wait(self) -> float:
        return round(self.total_wait_hours / self.seated, 2) if self.seated else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "seated": self.seated,
            "souls_seated": self.souls_seated,
            "stranded": self.stranded,
            "hotel_granted": self.hotel_granted,
            "parties_split": self.parties_split,
            "downgrades": self.downgrades,
            "mean_wait_hours": self.mean_wait,
            "weighted_satisfaction": round(self.weighted_satisfaction, 1),
        }


def _acceptable(flight: dict[str, Any], passenger: dict[str, Any],
                preference: dict[str, Any]) -> bool:
    """Whether this itinerary is one the passenger said they would take."""
    if flight["seats_free"] <= 0 or flight.get("status") != "scheduled":
        return False
    if flight["destination"] != passenger["destination"]:
        # Only a passenger who said so will accept an alternate arrival airport.
        if not preference.get("accept_nearby_airport"):
            return False
        if flight["region"] != passenger["region"]:
            return False
    wait = float(flight["departs_in_hours"])
    return wait <= float(preference.get("max_wait_hours", 6) or 6)


def allocate_with_preferences(
    *,
    passengers: list[dict[str, Any]],
    preferences: dict[str, dict[str, Any]],
    flights: list[dict[str, Any]],
    hotel_rooms: int,
) -> Allocation:
    """Allocate scarce seats using what the agents said they would accept.

    Passengers are served in order of urgency as *they* assessed it, weighted by tier —
    so the queue is built from reasoning about each situation rather than from arrival
    order. A party that agreed to be split can be seated across two aircraft; one that
    did not is all-or-nothing.
    """
    result = Allocation(strategy="swarm")
    inventory = {f["id"]: dict(f) for f in flights}
    rooms = hotel_rooms

    def rank(passenger: dict[str, Any]) -> float:
        pref = preferences.get(passenger["id"], {})
        urgency = float(pref.get("urgency_score", 50) or 50)
        return -(urgency * TIER_WEIGHT.get(passenger.get("tier", "basic"), 1.0))

    for passenger in sorted(passengers, key=rank):
        pref = preferences.get(passenger["id"])
        if pref is None:
            result.stranded += 1
            continue

        party = int(passenger.get("party_size", 1))
        options = [
            f for f in inventory.values() if _acceptable(f, passenger, pref)
        ]
        options.sort(key=lambda f: f["departs_in_hours"])

        placed = 0
        used: list[dict[str, Any]] = []
        for flight in options:
            if placed >= party:
                break
            take = min(flight["seats_free"], party - placed)
            if take <= 0:
                continue
            if placed > 0 and not pref.get("accept_split_party"):
                break
            if take < party - placed and not pref.get("accept_split_party"):
                continue
            flight["seats_free"] -= take
            placed += take
            used.append(flight)

        if placed == 0:
            result.stranded += 1
            if pref.get("needs_hotel") and rooms > 0 and passenger.get("has_hotel_entitlement"):
                rooms -= 1
                result.hotel_granted += 1
            continue

        # A partially seated party that refused splitting must be rolled back whole.
        if placed < party and not pref.get("accept_split_party"):
            for flight in used:
                flight["seats_free"] += 1
            result.stranded += 1
            continue

        result.seated += 1
        result.souls_seated += placed
        result.assignments[passenger["id"]] = used[0]["id"]
        if len(used) > 1:
            result.parties_split += 1
        if pref.get("accept_downgrade"):
            result.downgrades += 1
        wait = used[0]["departs_in_hours"]
        result.total_wait_hours += wait
        result.weighted_satisfaction += TIER_WEIGHT.get(passenger.get("tier", "basic"), 1.0) * (
            1.0 - min(wait / 36.0, 1.0)
        )

    return result


def allocate_first_come(
    *, passengers: list[dict[str, Any]], flights: list[dict[str, Any]], hotel_rooms: int
) -> Allocation:
    """The baseline airlines actually fall back to: queue order, next available seat,
    no knowledge of what anyone would accept."""
    result = Allocation(strategy="first_come_first_served")
    inventory = {f["id"]: dict(f) for f in flights}
    rooms = hotel_rooms

    for passenger in passengers:
        party = int(passenger.get("party_size", 1))
        options = [
            f for f in inventory.values()
            if f["seats_free"] >= party
            and f.get("status") == "scheduled"
            and f["destination"] == passenger["destination"]
        ]
        options.sort(key=lambda f: f["departs_in_hours"])
        if not options:
            result.stranded += 1
            if rooms > 0 and passenger.get("has_hotel_entitlement"):
                rooms -= 1
                result.hotel_granted += 1
            continue
        flight = options[0]
        flight["seats_free"] -= party
        result.seated += 1
        result.souls_seated += party
        result.assignments[passenger["id"]] = flight["id"]
        wait = flight["departs_in_hours"]
        result.total_wait_hours += wait
        result.weighted_satisfaction += TIER_WEIGHT.get(passenger.get("tier", "basic"), 1.0) * (
            1.0 - min(wait / 36.0, 1.0)
        )
    return result
