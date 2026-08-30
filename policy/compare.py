"""One definition of what it means for two answers to agree.

Three places need this and they must never drift apart: the fidelity experiment asking
whether a collapsed thought matches an uncollapsed one, drift detection asking whether the
model still agrees with a cached row, and any report built on either. A second copy would
eventually disagree with the first, and then two numbers claiming to measure the same thing
would quietly stop doing so.

The numerics carry a tolerance and the reason is not convenience. A traveller who would
wait six hours and one who would wait seven are not in disagreement in any sense an
allocator can act on, and scoring them as such would understate agreement while sounding
rigorous. Where the *ordering* matters rather than the magnitude — the allocator sorts by
urgency and never reads it — rank correlation is the honest instrument, and it lives beside
this one.
"""

from __future__ import annotations

from typing import Any

BOOLEAN_FIELDS = (
    "accept_downgrade",
    "accept_split_party",
    "accept_nearby_airport",
    "needs_hotel",
)

# field -> the largest difference that is still not a disagreement anyone would act on.
NUMERIC_FIELDS = {"max_wait_hours": 2.0, "urgency_score": 10.0}

ALL_FIELDS = (*BOOLEAN_FIELDS, *NUMERIC_FIELDS)


def agreement(a: dict[str, Any], b: dict[str, Any]) -> dict[str, bool]:
    """Field-by-field agreement between two answers to the same question."""
    out: dict[str, bool] = {}
    for field in BOOLEAN_FIELDS:
        out[field] = bool(a.get(field)) == bool(b.get(field))
    for field, tolerance in NUMERIC_FIELDS.items():
        try:
            out[field] = abs(float(a.get(field, 0)) - float(b.get(field, 0))) <= tolerance
        except (TypeError, ValueError):
            # An unparseable answer is a disagreement, never an accidental match.
            out[field] = False
    return out


def agrees(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two answers agree on every field."""
    return all(agreement(a, b).values())


def disagreeing_fields(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Which fields diverged — what a drift event has to name to be actionable."""
    return sorted(f for f, ok in agreement(a, b).items() if not ok)
