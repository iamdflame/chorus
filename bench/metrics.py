"""Scoring a recovery plan in a way no strategy can game.

v1 reported one number — tier-weighted satisfaction — and its allocator sorted by tier.
A strategy that optimises the quantity it is scored on will always look excellent, and the
audit was right to call that out. The defence is not a better single metric; there isn't
one. It is a panel, computed here from the assignments alone, with no knowledge of which
strategy produced them, and reported in full every time.

Two of these exist specifically to expose the failure mode v1 hid:

    satisfaction_tier_blind   the same score with every passenger worth the same
    gini_wait                 inequality of waiting time across those who were seated

If a strategy wins on tier-weighted and loses on tier-blind, it did not allocate better —
it reallocated toward passengers the objective happens to value. That is a legitimate
commercial choice and an illegitimate thing to report as an improvement, so both numbers
are always printed side by side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any

TIER_WEIGHT = {"platinum": 4.0, "gold": 3.0, "silver": 2.0, "basic": 1.0}
URGENCY_VALUE = {"critical": 4.0, "urgent": 3.0, "same_day": 2.0, "flexible": 1.0}


def gini(values: list[float]) -> float:
    """Inequality of a distribution, 0 = everyone equal, 1 = one person has everything.

    Applied to waiting time: a plan that seats the same people for the same mean wait but
    concentrates the waiting on a few travellers is a worse plan, and no average will say
    so.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    total = sum(ordered)
    if total == 0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(ordered))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round(p * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[idx], 2)


@dataclass
class Panel:
    """Every number, always. Reporting a subset is how v1 misled itself."""

    strategy: str
    bookings_seated: int = 0
    souls_seated: int = 0
    bookings_stranded: int = 0
    souls_stranded: int = 0
    # Totals over seated travellers, not per-passenger means. A strategy that seats more
    # people therefore scores higher even if it serves each of them slightly worse, which
    # is the intended reading — total welfare — but only comparable between arms run on
    # the same population. Never compare these across populations of different sizes.
    satisfaction_tier_weighted: float = 0.0
    satisfaction_tier_blind: float = 0.0
    mean_wait: float = 0.0
    p95_wait: float = 0.0
    worst_wait: float = 0.0
    gini_wait: float = 0.0
    parties_split: int = 0
    constraint_violations: int = 0
    model_calls: int = 0
    coalesced: int = 0
    cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def score(
    *,
    strategy: str,
    passengers: list[dict[str, Any]],
    flights: list[dict[str, Any]],
    assignments: dict[str, str],
    model_calls: int = 0,
    coalesced: int = 0,
    cost_usd: float = 0.0,
    notes: list[str] | None = None,
) -> Panel:
    """Score a plan from its assignments alone.

    Takes no preferences and no strategy internals on purpose: the scorer must not be
    reachable from the thing being scored.
    """
    by_id = {p["id"]: p for p in passengers}
    flight_by_id = {f["id"]: f for f in flights}

    waits: list[float] = []
    weighted = 0.0
    blind = 0.0
    souls_seated = 0
    violations = 0
    split = 0

    for pid, flight_id in assignments.items():
        passenger = by_id.get(pid)
        flight = flight_by_id.get(flight_id)
        if passenger is None or flight is None:
            continue
        souls_seated += int(passenger.get("party_size", 1))
        wait = float(flight.get("departs_in_hours", 0.0))
        waits.append(wait)

        # Satisfaction falls with waiting and rises with how badly the traveller needed
        # to move. Deliberately not a function of anything a strategy controls directly.
        urgency = _urgency_value(passenger)
        base = urgency * max(0.0, 1.0 - wait / 36.0)
        weighted += base * TIER_WEIGHT.get(passenger.get("tier", "basic"), 1.0)
        blind += base

        if passenger.get("needs_assistance") and flight.get("aircraft_type") in (None, ""):
            violations += 1
        if int(passenger.get("party_size", 1)) > 1 and flight.get("seats_free", 0) < 0:
            split += 1

    seated_ids = set(assignments)
    stranded = [p for p in passengers if p["id"] not in seated_ids]

    return Panel(
        strategy=strategy,
        bookings_seated=len(assignments),
        souls_seated=souls_seated,
        bookings_stranded=len(stranded),
        souls_stranded=sum(int(p.get("party_size", 1)) for p in stranded),
        satisfaction_tier_weighted=round(weighted, 1),
        satisfaction_tier_blind=round(blind, 1),
        mean_wait=round(mean(waits), 2) if waits else 0.0,
        p95_wait=percentile(waits, 0.95),
        worst_wait=round(max(waits), 2) if waits else 0.0,
        gini_wait=gini(waits),
        parties_split=split,
        constraint_violations=violations,
        model_calls=model_calls,
        coalesced=coalesced,
        cost_usd=round(cost_usd, 4),
        notes=notes or [],
    )


def _urgency_value(passenger: dict[str, Any]) -> float:
    """How badly this traveller needed to move, from the record rather than from any
    strategy's opinion of them."""
    from kernel.clock import FIXED

    try:
        scheduled = datetime.fromisoformat(passenger["scheduled_departure"])
        hours = (scheduled - FIXED.now()).total_seconds() / 3600.0
    except (KeyError, ValueError):
        hours = 24.0
    if hours <= 4:
        return URGENCY_VALUE["critical"]
    if hours <= 12:
        return URGENCY_VALUE["urgent"]
    if hours <= 24:
        return URGENCY_VALUE["same_day"]
    return URGENCY_VALUE["flexible"]


def table(panels: list[Panel]) -> str:
    """The panel as a fixed-width table, tier-blind beside tier-weighted."""
    rows = [
        ("strategy", lambda p: p.strategy, "{:<26}"),
        ("souls", lambda p: p.souls_seated, "{:>8,}"),
        ("bookings", lambda p: p.bookings_seated, "{:>9,}"),
        ("sat·tier", lambda p: p.satisfaction_tier_weighted, "{:>10,.1f}"),
        ("sat·blind", lambda p: p.satisfaction_tier_blind, "{:>11,.1f}"),
        ("mean wait", lambda p: p.mean_wait, "{:>11.2f}"),
        ("p95", lambda p: p.p95_wait, "{:>7.2f}"),
        ("gini", lambda p: p.gini_wait, "{:>8.3f}"),
        ("calls", lambda p: p.model_calls, "{:>7,}"),
        ("cost", lambda p: f"${p.cost_usd:.4f}", "{:>10}"),
    ]
    header = "".join(
        ("{:<26}" if i == 0 else fmt.replace(",", "").replace(".1f", "").replace(".2f", "")
         .replace(".3f", "").replace(".4f", "")).format(name)
        for i, (name, _, fmt) in enumerate(rows)
    )
    lines = [header, "-" * len(header)]
    for panel in panels:
        lines.append("".join(fmt.format(get(panel)) for _, get, fmt in rows))
    return "\n".join(lines)
