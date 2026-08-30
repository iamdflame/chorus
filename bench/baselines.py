"""Six strategies, scored identically, reported together.

v1 compared itself to one baseline it was certain to beat. An auditor ran the control it
had not run — hand-written rules, zero model calls — and the control won. The lesson is
not "pick a better baseline", it is "publish the one that beats you", so B2 is here as a
first-class arm and appears in every report whether or not it wins.

    B0  random              floor; proves the metric is not satisfied by noise
    B1  first-come          what airlines actually fall back to
    B2  rules, zero LLM     the control that beat v1
    B3  greedy on stated preferences   upper bound given the same preferences
    B4  Chorus              collapse + optimizer
    B5  per-entity LLM      fidelity reference, no collapse (sampled; costs money)

Every arm returns assignments only. Scoring lives in `bench/metrics.py` and never sees
which arm produced them.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from kernel.clock import FIXED
from swarm.canonical import project_passenger

Assignments = dict[str, str]


def _seats(flights: list[dict[str, Any]]) -> dict[str, int]:
    return {f["id"]: int(f.get("seats_free", 0)) for f in flights}


def _wait(flight: dict[str, Any]) -> float:
    return float(flight.get("departs_in_hours", 0.0))


def _fits(flight: dict[str, Any], passenger: dict[str, Any], prefs: dict[str, Any]) -> bool:
    """Whether a traveller would accept this flight, given what they said."""
    if flight.get("status") != "scheduled":
        return False
    same_place = flight.get("destination") == passenger.get("destination")
    if not same_place and not prefs.get("accept_nearby_airport", False):
        return False
    if not same_place and flight.get("region") != passenger.get("region"):
        return False
    if _wait(flight) > float(prefs.get("max_wait_hours", 24)):
        return False
    return True


# -- B0 ------------------------------------------------------------------------

def b0_random(passengers, flights, *, seed: int = 11, **_) -> Assignments:
    """Random order, random *valid* flight. The floor a real strategy must clear.

    Valid matters. An earlier version picked any flight with a free seat, which sent
    travellers to cities they were not going to and scored well for doing it — a floor
    that cheats is not a floor, it is a broken metric wearing one. The only thing random
    about this arm is the ordering and the choice among genuinely acceptable options.
    """
    rng = random.Random(seed)
    seats = _seats(flights)
    order = list(passengers)
    rng.shuffle(order)
    out: Assignments = {}
    for passenger in order:
        party = int(passenger.get("party_size", 1))
        options = [
            f for f in flights
            if seats.get(f["id"], 0) >= party
            and f.get("status") == "scheduled"
            and f.get("destination") == passenger.get("destination")
        ]
        if not options:
            continue
        chosen = rng.choice(options)
        seats[chosen["id"]] -= party
        out[passenger["id"]] = chosen["id"]
    return out


# -- B1 ------------------------------------------------------------------------

def b1_first_come(passengers, flights, **_) -> Assignments:
    """Queue order, earliest departure that fits. The airline fallback."""
    seats = _seats(flights)
    ordered = sorted(flights, key=_wait)
    out: Assignments = {}
    for passenger in sorted(passengers, key=lambda p: p.get("scheduled_departure", "")):
        party = int(passenger.get("party_size", 1))
        for flight in ordered:
            if seats.get(flight["id"], 0) < party:
                continue
            if flight.get("destination") != passenger.get("destination"):
                continue
            seats[flight["id"]] -= party
            out[passenger["id"]] = flight["id"]
            break
    return out


# -- B2 ------------------------------------------------------------------------

URGENCY_SCORE = {"critical": 95, "urgent": 78, "same_day": 55, "flexible": 30}
TIER_BONUS = {"platinum": 12, "gold": 8, "silver": 4, "basic": 0}


def rule_preferences(passenger: dict[str, Any]) -> dict[str, Any]:
    """Twelve lines, no model. This is the arm that beat v1 by 4.3 points.

    Kept deliberately simple and kept in the repository, because a control you can run is
    worth more than a paragraph explaining why the control would have lost.
    """
    j = project_passenger(passenger, clock=FIXED)
    urgent = j.urgency in ("critical", "urgent")
    return {
        "max_wait_hours": {"critical": 6, "urgent": 12, "same_day": 24, "flexible": 36}[j.urgency],
        "accept_downgrade": urgent,
        "accept_split_party": j.party in ("solo", "pair") or urgent,
        "accept_nearby_airport": urgent,
        "needs_hotel": j.urgency in ("same_day", "flexible"),
        "urgency_score": min(URGENCY_SCORE[j.urgency] + TIER_BONUS[j.tier], 100),
    }


def b2_rules(passengers, flights, **_) -> Assignments:
    prefs = {p["id"]: rule_preferences(p) for p in passengers}
    return allocate_by_preference(passengers, flights, prefs)


# -- B3 ------------------------------------------------------------------------

def b3_greedy_upper_bound(passengers, flights, *, preferences, **_) -> Assignments:
    """Best achievable by this allocator given these preferences.

    Value-ordered greedy, not a proven optimum. Called an upper *bound* rather than the
    optimum because seats are integral and parties are indivisible, so greedy can be beaten
    in principle. Naming it correctly matters more than the extra point it might buy.
    """
    return allocate_by_preference(passengers, flights, preferences, order="value")


# -- shared allocator ----------------------------------------------------------

def allocate_by_preference(
    passengers: list[dict[str, Any]],
    flights: list[dict[str, Any]],
    preferences: dict[str, dict[str, Any]],
    *,
    order: str = "urgency",
) -> Assignments:
    """One allocator, used by every preference-driven arm.

    Sharing it is deliberate: if each arm brought its own allocator, a difference in the
    results would not tell you whether the preferences or the packing was responsible.
    """
    seats = _seats(flights)
    by_wait = sorted(flights, key=_wait)

    def rank(p: dict[str, Any]) -> float:
        prefs = preferences.get(p["id"], {})
        score = float(prefs.get("urgency_score", 50))
        if order == "value":
            # Value per seat consumed: what a packing algorithm would prioritise.
            return -score / max(int(p.get("party_size", 1)), 1)
        return -score

    out: Assignments = {}
    for passenger in sorted(passengers, key=rank):
        prefs = preferences.get(passenger["id"])
        if not prefs:
            continue
        party = int(passenger.get("party_size", 1))
        for flight in by_wait:
            if seats.get(flight["id"], 0) < party:
                continue
            if not _fits(flight, passenger, prefs):
                continue
            seats[flight["id"]] -= party
            out[passenger["id"]] = flight["id"]
            break
    return out


ARMS: dict[str, tuple[str, Callable[..., Assignments]]] = {
    "B0": ("random", b0_random),
    "B1": ("first-come", b1_first_come),
    "B2": ("rules, zero LLM", b2_rules),
    "B3": ("greedy upper bound", b3_greedy_upper_bound),
}
