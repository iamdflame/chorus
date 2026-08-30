"""The saving must not depend on how fast you run.

The attack this answers: lookup happens before the model call, so agents in one cohort
that start together all miss and all pay. The collapse then degrades exactly as you raise
concurrency — the one thing you would raise to make a swarm fast — and the degradation is
invisible, because the store still reports a healthy hit rate while the bill records the
duplicates.

This runs the same population at concurrency 1, 4, 16 and 48 and asserts the number of
model calls is identical. A run at 48 that costs more than the same run at 1 is a system
whose central claim only holds when nobody is in a hurry.

Offline: uses the counting instrument, so it spends nothing and runs in CI.

    python scripts/verify_concurrency.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kernel.branch import PRIMARY
from kernel.clock import FIXED
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from swarm.canonical import bind, project_passenger
from swarm.runtime import Swarm
from swarm.scenario import build_scenario
from tests.instruments import CountingLlm

LEVELS = (1, 4, 16, 48)
POPULATION = 600


async def measure(concurrency: int, passengers: list[dict]) -> dict:
    store = InMemoryEffectStore()
    swarm = Swarm(store=store, branch_id=PRIMARY, mode=Mode.REPLAY, concurrency=concurrency)
    model = CountingLlm()
    for role in swarm.agents:
        swarm.agents[role].model = model
    _, metrics = await swarm.run(
        entities=passengers, projector=bind(project_passenger, FIXED),
        role="passenger", context="ORD closed by weather.", round_id="concurrency-proof",
    )
    result = metrics.to_dict()
    result["real_invocations"] = model.calls
    return result


async def main() -> int:
    passengers = [asdict(p) for p in build_scenario(passengers=POPULATION).passengers]
    distinct = len({project_passenger(p, clock=FIXED).key() for p in passengers})

    print(f"\n  {POPULATION:,} agents · {distinct} distinct situations")
    print("  The same work, run at four speeds. The cost must not move.\n")
    print(f"  {'concurrency':>12}{'model calls':>14}{'coalesced':>12}"
          f"{'duplicates':>12}{'collapse':>11}{'wall':>9}")
    print("  " + "-" * 72)

    runs = []
    for level in LEVELS:
        r = await measure(level, passengers)
        runs.append((level, r))
        print(f"  {level:>12}{r['model_calls']:>14,}{r['coalesced']:>12,}"
              f"{r['duplicate_calls']:>12,}{r['collapse']:>10.1f}x{r['wall_s']:>8.1f}s")

    calls = {r["model_calls"] for _, r in runs}
    failures = []
    if len(calls) != 1:
        failures.append(
            f"model calls varied with concurrency: {sorted(calls)} — the saving is "
            "throughput-dependent, which is the same as saying it does not hold in production"
        )
    for level, r in runs:
        if r["duplicate_calls"]:
            failures.append(f"concurrency {level} produced {r['duplicate_calls']} duplicate calls")
        if r["model_calls"] > distinct:
            failures.append(
                f"concurrency {level} made {r['model_calls']} calls for {distinct} situations"
            )
        if r["failed"]:
            failures.append(f"concurrency {level} failed {r['failed']} agents")

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    total_coalesced = sum(r["coalesced"] for _, r in runs)
    print(f"  PASS  {calls.pop()} model calls at every concurrency level from "
          f"{LEVELS[0]} to {LEVELS[-1]},\n        matching the {distinct} distinct situations "
          "exactly. Nothing is paid for twice.\n")
    if not total_coalesced:
        print("  Note: coalescing did not fire here. The counting instrument returns "
              "instantly, so\n  agents finish before their cohort-mates begin and the "
              "store already holds the answer.\n  Under real model latency the herd does "
              "overlap; tests/test_singleflight.py proves that\n  path with a deliberately "
              "slow instrument. Both mechanisms are load-bearing, at\n  different latencies.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
