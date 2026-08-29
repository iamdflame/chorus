"""An irregular-operations event: a storm closes a hub.

Chosen because the stakes need no explanation — everyone has been stranded at an airport
— and because IRROPS is a genuinely unsolved combinatorial problem that airlines lose
hundreds of millions a year to. Crucially it has *real scarcity*: seats, crew duty hours,
hotel rooms and gates are finite, so thousands of agents pursuing their own interests
must actually contend with one another rather than politely taking turns.

Generated deterministically from a fixed seed so a swarm run is reproducible and two runs
can be compared honestly.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

HUB = "ORD"
DESTINATIONS = (
    ("LHR", "europe"), ("CDG", "europe"), ("FRA", "europe"),
    ("LAX", "domestic_long"), ("SFO", "domestic_long"), ("SEA", "domestic_long"),
    ("DFW", "domestic_short"), ("ATL", "domestic_short"), ("BOS", "domestic_short"),
    ("MSP", "domestic_short"), ("DEN", "domestic_short"), ("PHX", "domestic_short"),
    ("NRT", "asia"), ("HKG", "asia"), ("GRU", "south_america"),
)
TIERS = ("basic", "basic", "basic", "basic", "silver", "silver", "gold", "platinum")

# Collections in the Shadow World.
PASSENGERS = "passengers"
CREW = "crew"
AIRCRAFT = "aircraft"
FLIGHTS = "flights"
SEATS = "seat_inventory"
HOTELS = "hotel_inventory"
AWARDS = "awards"


@dataclass(slots=True)
class Passenger:
    id: str
    name: str
    tier: str
    party_size: int
    destination: str
    region: str
    original_flight: str
    scheduled_departure: str
    is_misconnect: bool
    checked_bags: int
    needs_assistance: bool
    has_hotel_entitlement: bool
    status: str = "stranded"
    rebooked_to: str | None = None
    compensation_usd: float = 0.0


@dataclass(slots=True)
class CrewMember:
    id: str
    role: str
    duty_hours_used: float
    duty_hours_max: float
    qualified_types: list[str]
    base: str
    status: str = "available"
    assigned_flight: str | None = None

    @property
    def hours_remaining(self) -> float:
        return max(self.duty_hours_max - self.duty_hours_used, 0.0)


@dataclass(slots=True)
class Flight:
    id: str
    destination: str
    region: str
    aircraft_type: str
    seats_total: int
    seats_free: int
    departs_in_hours: float
    crew_required: int
    crew_assigned: int = 0
    status: str = "scheduled"


@dataclass(slots=True)
class Scenario:
    passengers: list[Passenger]
    crew: list[CrewMember]
    flights: list[Flight]
    hotel_rooms: int
    generated_at: str

    def summary(self) -> dict[str, Any]:
        seats = sum(f.seats_free for f in self.flights if f.status == "scheduled")
        souls = sum(p.party_size for p in self.passengers)
        return {
            "passengers": len(self.passengers),
            "souls_on_board": souls,
            "crew": len(self.crew),
            "flights": len(self.flights),
            "seats_available": seats,
            "seat_deficit": max(souls - seats, 0),
            "hotel_rooms": self.hotel_rooms,
            "agents_total": len(self.passengers) + len(self.crew) + len(self.flights),
        }


def build_scenario(*, passengers: int = 8000, seed: int = 20260829) -> Scenario:
    """A hub closure with genuine, deliberate scarcity.

    Seats are provisioned well below demand — roughly 60% of the souls needing to move —
    because an allocation problem where everyone can be accommodated is not an allocation
    problem, and the agents would never actually have to contend.
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)

    flights: list[Flight] = []
    for i in range(46):
        code, region = rng.choice(DESTINATIONS)
        total = rng.choice([76, 128, 166, 172, 214, 290])
        flights.append(
            Flight(
                id=f"UA{1200 + i}",
                destination=code,
                region=region,
                aircraft_type=rng.choice(["B738", "A320", "B739", "B77W", "A350"]),
                seats_total=total,
                seats_free=int(total * rng.uniform(0.18, 0.62)),
                departs_in_hours=round(rng.uniform(1.5, 34.0), 1),
                crew_required=rng.choice([4, 5, 6, 8, 10]),
            )
        )

    crew: list[CrewMember] = []
    for i in range(320):
        used = round(rng.uniform(2.0, 13.5), 1)
        crew.append(
            CrewMember(
                id=f"CRW-{7000 + i}",
                role=rng.choice(["captain", "first_officer", "purser", "cabin", "cabin", "cabin"]),
                duty_hours_used=used,
                duty_hours_max=rng.choice([14.0, 14.0, 16.0]),
                qualified_types=rng.sample(["B738", "A320", "B739", "B77W", "A350"],
                                           k=rng.choice([1, 2, 2, 3])),
                base=rng.choice([HUB, HUB, HUB, "IAH", "EWR", "DEN"]),
            )
        )

    people: list[Passenger] = []
    for i in range(passengers):
        code, region = rng.choice(DESTINATIONS)
        # Party sizes skew to solo travellers with a long tail of families.
        party = rng.choices([1, 1, 1, 1, 2, 2, 2, 3, 4, 5, 6], k=1)[0]
        people.append(
            Passenger(
                id=f"PAX-{100000 + i}",
                name=f"passenger-{i}",
                tier=rng.choice(TIERS),
                party_size=party,
                destination=code,
                region=region,
                original_flight=rng.choice(flights).id,
                scheduled_departure=(now + timedelta(hours=rng.uniform(0.5, 30))).isoformat(
                    timespec="minutes"
                ),
                is_misconnect=rng.random() < 0.38,
                checked_bags=rng.choices([0, 0, 1, 1, 2, 3], k=1)[0],
                needs_assistance=rng.random() < 0.06,
                has_hotel_entitlement=rng.random() < 0.44,
            )
        )

    return Scenario(
        passengers=people,
        crew=crew,
        flights=flights,
        hotel_rooms=int(passengers * 0.09),
        generated_at=now.isoformat(timespec="seconds"),
    )


def load_into_world(world, scenario: Scenario, *, branch_id: str, start_seq: int = 0) -> int:
    """Write the scenario into the Shadow World as versioned state."""
    seq = start_seq
    for flight in scenario.flights:
        seq += 1
        world.write(branch_id=branch_id, collection=FLIGHTS, key=flight.id,
                    value=asdict(flight), seq=seq)
    for member in scenario.crew:
        seq += 1
        world.write(branch_id=branch_id, collection=CREW, key=member.id,
                    value=asdict(member), seq=seq)
    for person in scenario.passengers:
        seq += 1
        world.write(branch_id=branch_id, collection=PASSENGERS, key=person.id,
                    value=asdict(person), seq=seq)
    seq += 1
    world.write(branch_id=branch_id, collection=HOTELS, key="ORD-block",
                value={"rooms_total": scenario.hotel_rooms,
                       "rooms_free": scenario.hotel_rooms}, seq=seq)
    return seq
