"""The saturation property, checked without spending a token.

`prove_swarm.py` measures collapse against the live model, which costs money and time.
This asserts the structural claim underneath it — that distinct situations stay bounded
while population grows without bound — using nothing but the projection. That makes it
safe to run on every push, which is where a claim like this belongs.

The bound is not empirical. It is the product of the buckets:

    tier(4) x urgency(4) x party(4) x constraints(3) = 192

so no population, however large, can require more than 192 distinct thoughts. The test
checks both that the measured count respects the bound and that it actually saturates
rather than merely growing slowly.

    python scripts/verify_collapse.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kernel.clock import FIXED
from swarm.canonical import (
    bind,
    collapse,
    constraint_band,
    party_band,
    project_passenger,
    urgency_band,
)
from swarm.scenario import build_scenario

# The bound, derived rather than observed.
TIERS = 4          # basic, silver, gold, platinum
URGENCY = 4        # critical, urgent, same_day, flexible
PARTY = 4          # solo, pair, family, group
CONSTRAINTS = 3    # unencumbered, checked_bags, assisted
CEILING = TIERS * URGENCY * PARTY * CONSTRAINTS

SCALES = (500, 1_000, 2_000, 4_000, 8_000, 20_000)


def main() -> int:
    print(f"\n  Bucket product: {TIERS} x {URGENCY} x {PARTY} x {CONSTRAINTS} = {CEILING}")
    print("  No population can require more distinct thoughts than this.\n")
    print(f"  {'agents':>9}  {'distinct':>9}  {'collapse':>10}")
    print("  " + "-" * 32)

    measured: list[tuple[int, int]] = []
    for n in SCALES:
        scenario = build_scenario(passengers=n)
        passengers = [asdict(p) for p in scenario.passengers]
        groups = collapse(passengers, bind(project_passenger, FIXED))
        measured.append((n, len(groups)))
        print(f"  {n:>9,}  {len(groups):>9}  {n / len(groups):>9.1f}x")

    failures: list[str] = []

    for n, distinct in measured:
        if distinct > CEILING:
            failures.append(f"{n:,} agents produced {distinct} distinct situations, above the "
                            f"bucket ceiling of {CEILING} — the projection is leaking detail")

    # Saturation: the last doubling must add almost nothing. Growth that merely slows is
    # not the claim; the claim is that the curve flattens.
    (_, second_last), (_, last) = measured[-2], measured[-1]
    growth = last - second_last
    if growth > 12:
        failures.append(f"distinct count grew by {growth} over the final 12,000 agents; "
                        "that is not saturation")

    # Collapse must actually improve with scale, or there is no argument for a swarm.
    if measured[-1][0] / measured[-1][1] <= measured[0][0] / measured[0][1]:
        failures.append("collapse did not improve with population")

    # The projection must not depend on identity. If it does, every agent is unique and
    # nothing is ever shared — this is the property the whole system rests on.
    sample = asdict(build_scenario(passengers=40).passengers[0])
    renamed = {**sample, "id": "PAX-999999", "name": "someone else",
               "order_id": "ORD-00000", "customer_id": "CUST-0000"}
    if project_passenger(sample, clock=FIXED).key() != project_passenger(renamed, clock=FIXED).key():
        failures.append("changing identity changed the projection — identity is leaking "
                        "into reasoning, and no two agents will ever share a thought")

    print()
    print(f"  final growth over last 12,000 agents: +{growth} distinct situations")
    print(f"  identity-invariant projection: "
          f"{project_passenger(sample, clock=FIXED).key() == project_passenger(renamed, clock=FIXED).key()}")

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    print(f"  PASS  distinct thoughts saturate at {measured[-1][1]} against a derived "
          f"ceiling of {CEILING};\n        {measured[-1][0]:,} agents collapse "
          f"{measured[-1][0] / measured[-1][1]:.0f}x, and identity never reaches the model.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
