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
from policy.compare import agrees
from policy.shadow import sampled, shadow_sample
from policy.table import PolicyTable, distill
from swarm.canonical import bind, project_passenger
from swarm.runtime import MODEL, Swarm
from swarm.scenario import build_scenario

CONTEXT = "A hub closure has stranded your flight. State your rebooking preferences."


async def main(derive: int, serve: int, rate: float, concurrency: int,
               reuse: str | None) -> int:
    projector = bind(project_passenger, FIXED)

    # -- [1] derive ------------------------------------------------------------
    scenario = build_scenario(passengers=derive)
    passengers = [asdict(p) for p in scenario.passengers]

    # A distilled policy outlives the run that derived it — that is the entire point of
    # distilling one. Reusing a stored table lets the shadow and noise phases be repeated
    # against the same policy without paying to re-derive it, and it exercises the
    # round-trip through disk that a real deployment would use.
    stored = Path(reuse) if reuse else None
    if stored and stored.exists():
        table = PolicyTable.from_dict(json.loads(stored.read_text()))
        derive_calls = len(table.rows)
        print(f"\n  [1] reusing policy v{table.version} from {stored} — "
              f"{table.populated:,} rows, no re-derivation")
        prior = json.loads(Path("data/necessity.json").read_text()) if Path(
            "data/necessity.json").exists() else {}
        derive_cost = float(prior.get("ledger", {}).get("cost_usd", 0.0))
        metrics = None
    else:
        print(f"\n  [1] deriving a policy from {derive:,} travellers\n")
        swarm = Swarm(
            store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.REPLAY,
            concurrency=concurrency,
        )

        def progress(i: int, total: int, m, *_) -> None:
            print(f"\r      {i:>6,}/{total:,}  calls {m.model_calls:>5}  "
                  f"${m.cost_usd:.4f}", end="", flush=True)

        _, metrics = await swarm.run(
            entities=passengers, projector=projector, role="passenger",
            context=CONTEXT, round_id="necessity-derive", on_progress=progress,
        )
        print()
        derive_calls, derive_cost = metrics.model_calls, metrics.cost_usd

    # A swarm that pays for answers the store already holds is not collapsing, and the
    # symptom is quiet: the run completes, the numbers look plausible, and the bill is
    # several times what it should be. That happened here once, from a mode that never
    # consults the store, so the invariant is asserted rather than assumed.
    distinct = len({projector(p).key() for p in passengers})
    if metrics is not None and metrics.model_calls > distinct * 1.1 + 5:
        print(f"\n  FAIL  {metrics.model_calls:,} model calls for {distinct:,} distinct "
              f"situations.\n        The store is not being consulted — check the "
              f"interposer Mode.\n")
        return 1

    # -- [2] distill -----------------------------------------------------------
    if metrics is not None:
        table = distill(swarm.last_cohorts.values(), clock=FIXED, model=MODEL)
    print(f"\n  [2] policy v{table.version} · {table.populated:,}/{table.ceiling:,} "
          f"cells populated ({100 * table.occupancy:.1f}%) "
          f"from {derive_calls:,} model calls")

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
        store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.REPLAY,
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

    # -- [4b] the noise floor --------------------------------------------------
    # A disagreement between the table and a fresh call is only evidence of drift if the
    # model agrees with *itself*. Temperature is 0, but batched serving is not bitwise
    # deterministic, so some fraction of "drift" is the model differing from its own
    # previous answer for no reason at all. Asking the same question twice measures that
    # fraction, and necessity is only the part above it.
    #
    # Without this the ledger reports the model's own variance as evidence that the model
    # is needed, which would be the most flattering possible way to be wrong.
    print(f"\n  [4b] noise floor — asking the same questions twice\n")
    sampled_keys = [k for k in sorted(table.rows) if sampled(k, rate=rate, salt="chorus")]
    noise_seen = noise_diff = noise_failed = 0
    noise_cost = 0.0
    for i, key in enumerate(sampled_keys, 1):
        first, cost_a = await ask(key)
        second, cost_b = await ask(key)
        noise_cost += cost_a + cost_b
        print(f"\r      re-asked {i:>4}/{len(sampled_keys)}  ${noise_cost:.4f}",
              end="", flush=True)
        if first is None or second is None:
            noise_failed += 1
            continue
        noise_seen += 1
        noise_diff += not agrees(first, second)
    print()
    noise_rate = noise_diff / noise_seen if noise_seen else float("nan")
    if report.sampled and not report.cost_usd:
        print("\n  FAIL  shadow samples cost nothing, so they were replayed rather than "
              "asked.\n        A drift rate measured against a cache is not a "
              "measurement.\n")
        return 1

    # -- [5] report ------------------------------------------------------------
    ledger = NecessityLedger(
        served_from_table=from_table,
        served_from_model=from_model,
        model_calls_made=derive_calls,
        model_cost_usd=derive_cost,
        shadow=report,
        policy_version=table.version,
        period=f"derive {derive:,} → serve {serve:,}",
    )
    print(ledger.render(table))

    lo, hi = report.interval()
    print(f"  How much of that is real\n")
    print(f"    raw disagreement with the table   {100 * report.drift_rate:>6.1f}%   "
          f"({report.drifted}/{report.answered})")
    if noise_seen:
        print(f"    the model disagreeing with itself {100 * noise_rate:>6.1f}%   "
              f"({noise_diff}/{noise_seen})")
        adjusted = max(0.0, report.drift_rate - noise_rate)
        print(f"    necessity above the noise floor   {100 * adjusted:>6.1f}%")
    print(f"\n    95% interval on the raw rate      [{100 * lo:.1f}%, {100 * hi:.1f}%]")
    print(f"    on {report.answered} answered samples — this is a direction, not a "
          f"decimal.\n")

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
        "noise_floor": {
            "compared": noise_seen, "disagreed": noise_diff, "failed": noise_failed,
            "rate": noise_rate, "cost_usd": round(noise_cost, 4),
        },
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
    ap.add_argument("--reuse", default=None,
                    help="path to a stored policy table; skips re-derivation")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(
        main(args.derive, args.serve, args.rate, args.concurrency, args.reuse)
    ))
