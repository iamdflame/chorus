"""Derive a policy, serve traffic from it, then check whether it is still right.

    [1] derive   run the swarm on a population; every distinct situation costs one call
    [2] distill  compile those answers into a policy table with provenance
    [3] serve    run a *second, larger* population entirely from the table — free
    [4] shadow   re-ask the model for a slice of the table and compare
    [5] report   the Necessity Ledger

**The hazard this script is built around.** A shadow sample must reach the model. Re-asking
at the same causal position would resolve against the effect store, return the recorded
answer, and agree with itself every single time — a drift rate of 0.00% that measures
nothing and would be the most convincing wrong number in the whole project. So the shadow
swarm gets its own store and its own round, guaranteeing a real call, and the ledger counts
what it cost.

The second population matters too. Serving the same travellers the table was derived from
would prove only that a cache returns what was put in it. A fresh population exercises the
claim that actually matters: **situations recur, so a policy derived from one crowd serves
the next one for free.**

    python scripts/necessity.py --derive 4000 --serve 20000 --rate 0.02
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from kernel.branch import PRIMARY
from kernel.clock import FIXED
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from policy.ledger import NecessityLedger
from policy.shadow import shadow_sample
from policy.table import distill
from swarm.canonical import bind, project_passenger
from swarm.runtime import MODEL, Swarm
from swarm.scenario import build_scenario

CONTEXT = "A hub closure has stranded your flight. State your rebooking preferences."


async def main(derive: int, serve: int, rate: float, concurrency: int) -> int:
    projector = bind(project_passenger, FIXED)

    # -- [1] derive ------------------------------------------------------------
    scenario = build_scenario(passengers=derive)
    passengers = [asdict(p) for p in scenario.passengers]
    print(f"\n  [1] deriving a policy from {derive:,} travellers\n")

    swarm = Swarm(
        store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.RECORD,
        concurrency=concurrency,
    )

    def progress(i: int, total: int, m, *_) -> None:
        print(f"\r      {i:>6,}/{total:,}  calls {m.model_calls:>5}  ${m.cost_usd:.4f}",
              end="", flush=True)

    _, metrics = await swarm.run(
        entities=passengers, projector=projector, role="passenger",
        context=CONTEXT, round_id="necessity-derive", on_progress=progress,
    )
    print()

    # -- [2] distill -----------------------------------------------------------
    table = distill(swarm.last_cohorts.values(), clock=FIXED, model=MODEL)
    print(f"\n  [2] policy v{table.version} · {table.populated:,}/{table.ceiling:,} "
          f"cells populated ({100 * table.occupancy:.1f}%) "
          f"from {metrics.model_calls:,} model calls")

    # -- [3] serve a fresh, larger population ----------------------------------
    # A different crowd, not the one the table was derived from. Serving the same
    # travellers back would prove only that a cache returns what was put into it.
    later = build_scenario(passengers=serve)
    from_table = 0
    from_model = 0
    unseen: set[str] = set()
    for person in later.passengers:
        key = projector(asdict(person)).key()
        if table.lookup(key) is not None:
            from_table += 1
        else:
            from_model += 1
            unseen.add(key)
    print(f"\n  [3] serving {serve:,} fresh travellers")
    print(f"      {from_table:>7,} answered from the table, free")
    print(f"      {from_model:>7,} in {len(unseen):,} situations the policy has never "
          f"seen — these still cost")

    # -- [4] shadow sample -----------------------------------------------------
    # Its own store and its own round, so every sample is a real call. Sharing either
    # would replay the recorded answer and report perfect agreement with itself.
    print(f"\n  [4] shadow-sampling {100 * rate:.0f}% of the table against live "
          f"{MODEL}\n")
    shadow_swarm = Swarm(
        store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.RECORD,
        concurrency=concurrency,
    )
    by_key = {}
    for person in scenario.passengers:
        record = asdict(person)
        by_key.setdefault(projector(record).key(), record)

    checked = {"n": 0}

    async def ask(key: str):
        record = by_key.get(key)
        if record is None:
            return None, 0.0
        answers, m = await shadow_swarm.run(
            entities=[record], projector=projector, role="passenger",
            context=CONTEXT, round_id=f"necessity-shadow-{key}",
        )
        checked["n"] += 1
        print(f"\r      sampled {checked['n']:>4}  ${m.cost_usd:.4f}", end="", flush=True)
        return answers.get(record["id"]), m.cost_usd

    report = await shadow_sample(
        table, sorted(table.rows), ask=ask, rate=rate, salt="chorus",
    )
    print()
    if report.sampled and not report.cost_usd:
        print("\n  FAIL  shadow samples cost nothing, so they were replayed rather than "
              "asked.\n        A drift rate measured against a cache is not a "
              "measurement.\n")
        return 1

    # -- [5] report ------------------------------------------------------------
    ledger = NecessityLedger(
        served_from_table=from_table,
        served_from_model=from_model,
        model_cost_usd=metrics.cost_usd,
        shadow=report,
        policy_version=table.version,
        period=f"derive {derive:,} → serve {serve:,}",
    )
    print(ledger.render(table))

    if report.events:
        print("  Rows the model no longer agrees with:\n")
        for event in report.events[:5]:
            print(f"    {event.key}")
            print(f"      moved on: {', '.join(event.fields)}")
        print()

    out = Path("data/necessity.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "ledger": ledger.to_dict(),
        "policy": {k: v for k, v in table.to_dict().items() if k != "rows"},
        "unseen_situations": len(unseen),
    }, indent=2))
    Path("data/policy.json").write_text(json.dumps(table.to_dict(), indent=2))
    print(f"  Written to {out} and data/policy.json\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--derive", type=int, default=4000)
    ap.add_argument("--serve", type=int, default=20_000)
    ap.add_argument("--rate", type=float, default=0.02)
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(
        main(args.derive, args.serve, args.rate, args.concurrency)
    ))
