"""The claim: a swarm costs what its distinct decisions cost, not what its agent count costs.

Every agent is invoked independently — nothing in the runtime groups them. The collapse is
discovered by the content-addressed store when two agents in the same round compute the
same address, which happens exactly when their situations are genuinely equivalent.

    python scripts/prove_swarm.py --agents 300
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from kernel.branch import PRIMARY
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from swarm.canonical import collapse, project_passenger
from swarm.runtime import Swarm
from swarm.scenario import build_scenario, load_into_world
from world.shadow import ShadowWorld


def bar(done: int, total: int, width: int = 34) -> str:
    filled = int(width * done / max(total, 1))
    return "#" * filled + "." * (width - filled)


async def main(count: int, concurrency: int) -> int:
    scenario = build_scenario(passengers=count)
    world = ShadowWorld()
    store = InMemoryEffectStore()
    load_into_world(world, scenario, branch_id=PRIMARY)

    passengers = [asdict(p) for p in scenario.passengers]
    predicted = collapse(passengers, project_passenger)

    summary = scenario.summary()
    context = (
        f"Hub {scenario.generated_at[:10]}: ORD closed by severe weather. "
        f"{summary['souls_on_board']:,} travellers need to move. "
        f"{summary['seats_available']:,} seats exist on the next 46 departures. "
        f"{summary['hotel_rooms']} hotel rooms are available. "
        f"Seats are scarce: roughly one for every seven travellers."
    )

    print(f"\n  SCENARIO   ORD closure · {summary['souls_on_board']:,} souls · "
          f"{summary['seats_available']:,} seats · deficit {summary['seat_deficit']:,}")
    print(f"  SWARM      {len(passengers):,} independent passenger agents, "
          f"concurrency {concurrency}")
    print(f"  PREDICTED  {len(predicted)} distinct situations "
          f"({len(passengers)/len(predicted):.1f}x)\n")

    swarm = Swarm(store=store, branch_id=PRIMARY, mode=Mode.REPLAY, concurrency=concurrency)

    def progress(done: int, total: int, m) -> None:
        if done % 10 == 0 or done == total:
            print(f"\r  [{bar(done, total)}] {done:>5,}/{total:,}  "
                  f"model calls {m.model_calls:>4}  cache {m.cache_hits:>5}  "
                  f"${m.cost_usd:.4f}", end="", flush=True)

    preferences, metrics = await swarm.run(
        entities=passengers, projector=project_passenger, role="passenger",
        context=context, round_id="irrops-round-1", on_progress=progress,
    )
    print()

    m = metrics.to_dict()
    print("\n  " + "=" * 70)
    print(f"  {'agents invoked':<30}{m['agents_invoked']:>12,}")
    print(f"  {'model calls actually made':<30}{m['model_calls']:>12,}")
    print(f"  {'served from the store':<30}{m['cache_hits']:>12,}")
    print(f"  {'distinct thoughts':<30}{m['distinct_thoughts']:>12,}")
    print(f"  {'collapse':<30}{m['collapse']:>11.1f}x")
    print("  " + "-" * 70)
    print(f"  {'cost incurred':<30}{'$' + format(m['cost_usd'], '.4f'):>12}")
    print(f"  {'cost if one call per agent':<30}{'$' + format(m['naive_cost_usd'], '.4f'):>12}")
    print(f"  {'saved':<30}"
          f"{'$' + format(m['naive_cost_usd'] - m['cost_usd'], '.4f'):>12}")
    print(f"  {'wall clock':<30}{format(m['wall_s'], '.1f') + 's':>12}")
    print(f"  {'preferences produced':<30}{len(preferences):>12,}")
    print("  " + "=" * 70)

    failures = []
    if m["model_calls"] >= m["agents_invoked"]:
        failures.append("no collapse: every agent reached the model")
    if m["collapse"] < 2:
        failures.append(f"collapse of {m['collapse']}x is not a saving worth claiming")
    if len(preferences) < m["agents_invoked"] * 0.9:
        failures.append(
            f"only {len(preferences)} of {m['agents_invoked']} agents produced a preference"
        )
    if metrics.errors:
        print(f"\n  first errors: {metrics.errors[:3]}")

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    print(f"  PASS  {m['agents_invoked']:,} agents reasoned for "
          f"${m['cost_usd']:.4f} instead of ${m['naive_cost_usd']:.4f} — "
          f"{m['collapse']:.0f}x fewer thoughts than agents.\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.agents, a.concurrency)))
