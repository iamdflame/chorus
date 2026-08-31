"""Properties of the allocator, which decides who gets a seat.

This is the module where a bug has a human consequence: 20,367 stranded people, 2,888
seats. It is also the module every fairness claim in the README rests on, and until now it
was the only claim-bearing module in the repository with no test — which the project's own
audit had flagged as severe.

Examples are the wrong tool here. A handful of hand-written cases test the cases somebody
already thought of, and the bugs that matter in an allocator are the ones nobody thought
of: an ordering that leaks a seat, a party split that double-books, a priority that
inverts. So these are properties, checked over generated populations.

The last property — priority monotonicity — is the one that would catch a real bug, and it
is the one no amount of example testing finds.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from swarm.allocate import allocate_first_come, allocate_with_preferences

TIERS = ["basic", "silver", "gold", "platinum"]

passengers_st = st.lists(
    st.fixed_dictionaries({
        "id": st.uuids().map(lambda u: f"PAX-{u.hex[:8]}"),
        "tier": st.sampled_from(TIERS),
        "party_size": st.integers(min_value=1, max_value=6),
        "destination": st.sampled_from(["BOS", "FRA", "MSP", "LHR"]),
        "region": st.sampled_from(["domestic_short", "europe", "domestic_long"]),
        "needs_assistance": st.booleans(),
        "checked_bags": st.integers(min_value=0, max_value=3),
        "has_hotel_entitlement": st.booleans(),
        "is_misconnect": st.booleans(),
    }),
    min_size=1, max_size=40, unique_by=lambda p: p["id"],
)

flights_st = st.lists(
    st.fixed_dictionaries({
        "id": st.uuids().map(lambda u: f"UA{u.int % 9000 + 1000}"),
        "destination": st.sampled_from(["BOS", "FRA", "MSP", "LHR"]),
        "region": st.sampled_from(["domestic_short", "europe", "domestic_long"]),
        "seats_free": st.integers(min_value=0, max_value=25),
        "departs_in_hours": st.floats(min_value=0.5, max_value=48, allow_nan=False),
        "aircraft_type": st.just("B739"),
    }),
    min_size=1, max_size=10, unique_by=lambda f: f["id"],
)


def prefs_for(passengers: list[dict[str, Any]], score: int | None = None) -> dict:
    return {
        p["id"]: {
            "urgency_score": score if score is not None else (hash(p["id"]) % 101),
            "max_wait_hours": 24,
            "accept_downgrade": True,
            "accept_split_party": False,
            "accept_nearby_airport": False,
            "needs_hotel": False,
        }
        for p in passengers
    }


def seated_ids(allocation) -> list[str]:
    return list(allocation.assignments)


def seats_used(allocation, passengers) -> dict[str, int]:
    """Seats consumed per flight — per soul, because a party of six occupies six."""
    party = {p["id"]: int(p.get("party_size", 1)) for p in passengers}
    used: dict[str, int] = {}
    for pax, flight in allocation.assignments.items():
        used[flight] = used.get(flight, 0) + party.get(pax, 1)
    return used


SETTINGS = settings(
    max_examples=60, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


class TestConservation:
    """You cannot seat more people than there are seats. Ever."""

    @given(passengers_st, flights_st)
    @SETTINGS
    def test_never_oversells_a_flight(self, passengers, flights) -> None:
        got = allocate_with_preferences(
            passengers=passengers, preferences=prefs_for(passengers),
            flights=flights, hotel_rooms=50,
        )
        capacity = {f["id"]: f["seats_free"] for f in flights}
        for flight_id, taken in seats_used(got, passengers).items():
            assert taken <= capacity[flight_id], (
                f"{flight_id} oversold: {taken} of {capacity[flight_id]}"
            )

    @given(passengers_st, flights_st)
    @SETTINGS
    def test_first_come_never_oversells_either(self, passengers, flights) -> None:
        got = allocate_first_come(passengers=passengers, flights=flights, hotel_rooms=50)
        capacity = {f["id"]: f["seats_free"] for f in flights}
        used: dict[str, int] = {}
        for a in got.assignments:
            used[a["flight_id"]] = used.get(a["flight_id"], 0) + a.get("seats", 1)
        assert all(t <= capacity[f] for f, t in seats_used(got, passengers).items())


class TestUniqueness:
    @given(passengers_st, flights_st)
    @SETTINGS
    def test_nobody_is_seated_twice(self, passengers, flights) -> None:
        """A double allocation is a seat sold to two people, which is the failure that
        reaches a gate agent."""
        ids = seated_ids(allocate_with_preferences(
            passengers=passengers, preferences=prefs_for(passengers),
            flights=flights, hotel_rooms=50,
        ))
        assert len(ids) == len(set(ids))

    @given(passengers_st, flights_st)
    @SETTINGS
    def test_only_real_passengers_are_seated(self, passengers, flights) -> None:
        known = {p["id"] for p in passengers}
        assert set(seated_ids(allocate_with_preferences(
            passengers=passengers, preferences=prefs_for(passengers),
            flights=flights, hotel_rooms=50,
        ))) <= known


class TestDeterminism:
    @given(passengers_st, flights_st)
    @SETTINGS
    def test_same_input_gives_byte_identical_output(self, passengers, flights) -> None:
        """The allocator is the deterministic half of the system. If it were not, the
        replay guarantee would stop at the model boundary."""
        prefs = prefs_for(passengers)
        a = allocate_with_preferences(passengers=passengers, preferences=prefs,
                                      flights=flights, hotel_rooms=50)
        b = allocate_with_preferences(passengers=passengers, preferences=prefs,
                                      flights=flights, hotel_rooms=50)
        assert a.to_dict() == b.to_dict()


class TestOrderInsensitivity:
    @given(passengers_st, flights_st, st.integers(min_value=0, max_value=10_000))
    @SETTINGS
    def test_shuffling_the_queue_does_not_change_who_flies(
        self, passengers, flights, seed
    ) -> None:
        """Who gets a seat must depend on the situations, not on the order the records
        happened to arrive in. Without this, the fairness claim is an accident of input
        ordering — and the bench's arms would be comparing list positions."""
        import random

        prefs = prefs_for(passengers)
        straight = allocate_with_preferences(
            passengers=passengers, preferences=prefs, flights=flights, hotel_rooms=50)
        shuffled_list = list(passengers)
        random.Random(seed).shuffle(shuffled_list)
        shuffled = allocate_with_preferences(
            passengers=shuffled_list, preferences=prefs, flights=flights, hotel_rooms=50)
        assert set(seated_ids(straight)) == set(seated_ids(shuffled))


class TestPriorityMonotonicity:
    """Raising one passenger's urgency must never make their outcome worse.

    This is the property that would catch a real bug, and the one no example test finds:
    a comparator with an inverted sign, a tie-break that reorders under pressure, a
    priority that wraps. It is checked by moving exactly one passenger and holding
    everything else fixed.
    """

    @given(passengers_st, flights_st)
    @SETTINGS
    def test_raising_urgency_never_loses_a_seat(self, passengers, flights) -> None:
        prefs = prefs_for(passengers, score=50)
        target = passengers[0]["id"]

        before = allocate_with_preferences(
            passengers=passengers, preferences=prefs, flights=flights, hotel_rooms=50)
        if target not in seated_ids(before):
            return  # nothing to lose; the interesting direction is tested below

        raised = {k: dict(v) for k, v in prefs.items()}
        raised[target]["urgency_score"] = 100
        after = allocate_with_preferences(
            passengers=passengers, preferences=raised, flights=flights, hotel_rooms=50)
        assert target in seated_ids(after), (
            "a passenger became more urgent and lost their seat"
        )

    @given(passengers_st, flights_st)
    @SETTINGS
    def test_lowering_urgency_never_gains_a_seat_others_wanted(
        self, passengers, flights
    ) -> None:
        prefs = prefs_for(passengers, score=50)
        target = passengers[0]["id"]

        lowered = {k: dict(v) for k, v in prefs.items()}
        lowered[target]["urgency_score"] = 0
        after = allocate_with_preferences(
            passengers=passengers, preferences=lowered, flights=flights, hotel_rooms=50)
        before = allocate_with_preferences(
            passengers=passengers, preferences=prefs, flights=flights, hotel_rooms=50)
        # Dropping to the bottom of the queue cannot seat someone who was previously
        # unseated while every other preference is unchanged.
        if target not in seated_ids(before):
            assert target not in seated_ids(after)


class TestDegenerateInputs:
    def test_no_flights_seats_nobody_rather_than_raising(self) -> None:
        people = [{"id": "PAX-1", "tier": "basic", "party_size": 1,
                   "destination": "BOS", "region": "domestic_short",
                   "needs_assistance": False, "checked_bags": 0,
                   "has_hotel_entitlement": False, "is_misconnect": False}]
        got = allocate_with_preferences(
            passengers=people, preferences=prefs_for(people), flights=[], hotel_rooms=0)
        assert got.assignments == {}

    def test_a_passenger_with_no_preferences_is_skipped_not_guessed_for(self) -> None:
        """Inventing preferences for someone the swarm failed on would seat them against
        constraints nobody stated."""
        people = [{"id": "PAX-1", "tier": "basic", "party_size": 1,
                   "destination": "BOS", "region": "domestic_short",
                   "needs_assistance": False, "checked_bags": 0,
                   "has_hotel_entitlement": False, "is_misconnect": False}]
        flights = [{"id": "UA1", "destination": "BOS", "region": "domestic_short",
                    "seats_free": 10, "departs_in_hours": 2.0, "aircraft_type": "B739"}]
        got = allocate_with_preferences(
            passengers=people, preferences={}, flights=flights, hotel_rooms=0)
        assert got.assignments == {}
