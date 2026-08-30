"""Memory across weeks of simulated time, without paying for it in collapse.

The track asks for context that survives weeks of asynchronous operation. The naive
implementation — a returning traveller's history in their prompt — destroys this product:
every prompt becomes unique, every address becomes unique, and collapse goes to 1x. The
system would remember everyone and reason about no one twice.

So memory feeds the *projection*, not the prompt. This measures whether that actually holds
at scale: same population, three months apart in simulated time, with a third of travellers
returning and remembered.

    python scripts/verify_memory.py
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.clock import FIXED
from memory.profile import Profile, apply
from memory.store import InMemoryProfileStore, learn
from swarm.canonical import bind, project_passenger
from swarm.scenario import build_scenario

POPULATION = 20_000
CEILING = 4 * 4 * 4 * 3 * 3 * 2 * 2


def main() -> int:
    passengers = [asdict(p) for p in build_scenario(passengers=POPULATION).passengers]
    projector = bind(project_passenger, FIXED)
    failures: list[str] = []

    print(f"\n  Memory across weeks — {POPULATION:,} travellers\n")

    # -- March: a disruption nobody has been seen in before ---------------------
    march = FIXED
    cold = {projector(p).key() for p in passengers}
    print(f"  [1] first disruption      {len(cold):,} distinct situations, "
          f"{POPULATION / len(cold):.1f}x collapse")

    # The airline learns something about a third of them.
    store = InMemoryProfileStore()
    returning = passengers[::3]
    for person in returning:
        learn(Profile(person["id"]), {**person, "needs_assistance": True}, clock=march)
        profile = Profile(person["id"])
        profile.observe("needs_assistance", True, clock=march)
        store.put(profile)
    print(f"      learned a durable constraint for {len(returning):,} of them")

    # -- June: the same people, three months later ------------------------------
    june = FIXED.shifted(days=90)
    warm_keys = [
        apply(projector(p), store.get(p["id"]), clock=june).key() for p in passengers
    ]
    warm = set(warm_keys)
    remembered = sum(
        1 for p in returning
        if apply(projector(p), store.get(p["id"]), clock=june).constraints == "assisted"
    )
    print(f"\n  [2] 90 days later         {len(warm):,} distinct situations, "
          f"{POPULATION / len(warm):.1f}x collapse")
    print(f"      {remembered:,} travellers were recognised without re-stating anything")

    if not warm <= set(
        f"{k}" for k in warm
    ) or len(warm) > CEILING:
        failures.append(f"memory produced {len(warm):,} cells, above the {CEILING:,} ceiling")
    if POPULATION / len(warm) < 2.0:
        failures.append("collapse fell below 2x once memory was applied")
    if remembered != len(returning):
        failures.append(
            f"only {remembered:,} of {len(returning):,} remembered at 90 days"
        )

    # -- December: past the assistance TTL --------------------------------------
    december = FIXED.shifted(days=200)
    # Compared against the plain projection, not against a count of `assisted`. Some of
    # these travellers genuinely need assistance according to their booking, and counting
    # them as memory that failed to expire measured the scenario rather than the TTL —
    # this check failed on 377 travellers before it was asking the right question.
    still_influenced = sum(
        1 for p in returning
        if apply(projector(p), store.get(p["id"]), clock=december).key()
        != projector(p).key()
    )
    print(f"\n  [3] 200 days later        memory still influences "
          f"{still_influenced:,} travellers")
    print(f"      a wheelchair needed after surgery in March is not needed forever;")
    print(f"      the constraint expires rather than mislabelling someone for years")
    if still_influenced != 0:
        failures.append(
            f"memory still moved {still_influenced:,} travellers past its TTL"
        )

    # -- and nothing identifying ever reaches a prompt --------------------------
    leaked = 0
    for person in returning[:500]:
        prompt = apply(projector(person), store.get(person["id"]), clock=june).to_prompt()
        if person["id"] in prompt or str(person.get("name", "\0")) in prompt:
            leaked += 1
    print(f"\n  [4] identity in prompts   {leaked} of 500 remembered travellers")
    if leaked:
        failures.append(f"{leaked} prompts carried identity")

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    cost = (POPULATION / len(cold)) - (POPULATION / len(warm))
    print(f"  PASS  memory persisted 90 days and expired on schedule.")
    print(f"\n        It is not free. Remembering moved travellers between cells, so the")
    print(f"        lattice went from {len(cold):,} occupied cells to {len(warm):,} and "
          f"collapse from")
    print(f"        {POPULATION / len(cold):.1f}x to {POPULATION / len(warm):.1f}x — "
          f"a {100 * cost / (POPULATION / len(cold)):.0f}% cost, paid to stop asking "
          f"people to")
    print(f"        re-explain themselves. Both numbers are printed so the trade is "
          f"visible.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
