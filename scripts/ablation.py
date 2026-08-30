"""Is this just a GROUP BY?

It is the first thing anyone sensible asks, and it deserves a runnable answer rather than
a paragraph. Three arms, over two different populations, using the real addressing code
and no model spend at all:

    A  no store          every agent reaches the model
    B  hand-grouped      group by projection inside each run, call once per group
    C  Chorus            content-addressed store, persistent across runs

On a single population B and C cost the same, and saying otherwise would be dishonest —
if you already know the grouping key, grouping by it is exactly as cheap. That is the
honest half of the answer.

The difference appears the moment you stop assuming. B's sharing lives inside one pass
over one population: it cannot reuse anything from a run that already happened, and it
only ever discovers the equivalences its grouping key was written to expect. C's sharing
is a property of the addresses themselves, so a second population inherits everything it
has in common with the first without anyone deciding in advance that it should.

    python scripts/ablation.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kernel.effect import Determinism, Effect, EffectKind, hash_payload
from kernel.store import InMemoryEffectStore
from swarm.canonical import Projection, project_passenger
from swarm.scenario import build_scenario

ANCHOR = "irrops-round-1"
PRICE_PER_CALL = 0.00087  # measured mean for one passenger agent turn on gemini-3.5-flash


def address_for(projection: Projection) -> str:
    """The real address a passenger agent computes — same function the interposer uses."""
    return Effect.address(
        kind=EffectKind.MODEL_CALL,
        agent="passenger_agent",
        causal_parents=(ANCHOR,),
        request_hash=hash_payload({"projection": projection.to_dict()}),
    )


def arm_no_store(populations) -> int:
    return sum(len(p) for p in populations)


def arm_hand_grouped(populations) -> int:
    """Group by projection key within each run. The obvious, sensible implementation."""
    calls = 0
    for population in populations:
        calls += len({project_passenger(p).key() for p in population})
    return calls


def arm_chorus(populations) -> tuple[int, list[int]]:
    """Let genuinely independent agents collide in a content-addressed store."""
    store = InMemoryEffectStore()
    calls, per_run = 0, []
    for population in populations:
        before = calls
        for passenger in population:
            address = address_for(project_passenger(passenger))
            if store.lookup("primary", address) is None:
                calls += 1
                store.put(
                    Effect(
                        id=address, content_id=address, branch_id="primary", seq=calls,
                        agent="passenger_agent", kind=EffectKind.MODEL_CALL,
                        determinism=Determinism.RECORDED, causal_parents=(ANCHOR,),
                        request_hash=address, request={}, response={"ok": True},
                    )
                )
        per_run.append(calls - before)
    return calls, per_run


def row(label: str, *cells: object) -> str:
    return f"  {label:<26}" + "".join(f"{str(c):>16}" for c in cells)


def main() -> int:
    # Two different populations: same generator, different seed. They are not the same
    # people, but people are not infinitely various, so their situations overlap.
    first = [asdict(p) for p in build_scenario(passengers=4000, seed=20260829).passengers]
    second = [asdict(p) for p in build_scenario(passengers=4000, seed=771).passengers]
    populations = [first, second]

    a = arm_no_store(populations)
    b = arm_hand_grouped(populations)
    c, per_run = arm_chorus(populations)

    g1 = len({project_passenger(p).key() for p in first})
    g2 = len({project_passenger(p).key() for p in second})

    print(f"\n  Two populations of {len(first):,} agents each, generated from different seeds.\n")
    print(row("", "run 1", "run 2", "total", "cost"))
    print("  " + "-" * 90)
    print(row("A  no store", len(first), len(second), a, f"${a * PRICE_PER_CALL:,.2f}"))
    print(row("B  hand-grouped", g1, g2, b, f"${b * PRICE_PER_CALL:,.2f}"))
    print(row("C  Chorus", per_run[0], per_run[1], c, f"${c * PRICE_PER_CALL:,.2f}"))
    print("  " + "-" * 90)

    print(f"\n  On the first population alone, B and C are identical ({g1} calls each).")
    print("  Grouping by a key you already know is exactly as cheap as deriving it.\n")
    print(f"  On the second population B pays {g2} again, because its sharing lives inside")
    print(f"  one pass. C pays {per_run[1]} — only the situations it had never seen.\n")

    failures = []
    if per_run[0] != g1:
        failures.append(f"first run diverged from the hand-grouped count ({per_run[0]} vs {g1})")
    if per_run[1] >= g2:
        failures.append(f"second population cost {per_run[1]}, no better than regrouping ({g2})")
    if c >= b:
        failures.append("Chorus was not cheaper than hand-grouping across runs")

    reuse = 1 - (per_run[1] / g2) if g2 else 0
    print(row("second population reuse", f"{reuse:.0%}"))
    print(row("calls avoided vs B", b - c))
    print(row("calls avoided vs A", a - c))

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    print(f"  PASS  identical to hand-grouping on one population, and {reuse:.0%} cheaper on")
    print("        the next one — because the sharing is derived, not declared.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
