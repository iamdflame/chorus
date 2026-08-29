"""Search the space of refund policies against real recorded history.

Every candidate is executed by the actual six-agent fleet, on the actual disputes, with
the actual tools — and every irreversible action it chooses is staged rather than
dispatched. That is what makes searching against production history possible: the
experiment would otherwise send thousands of real emails and issue thousands of real
refunds.

    python scripts/optimize_policy.py --generations 2 --population 3
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from fleet.domain import build_seed, load_into_world
from kernel.branch import PRIMARY
from kernel.snapshot import save
from kernel.store import InMemoryEffectStore
from optimizer.search import PolicySearch
from world.shadow import ShadowWorld

# Chosen so the baseline has a known failure in BOTH directions: repeat disputers whose
# claims should never be auto-paid, and a first-time disputer above the ceiling whose
# valid claim the current policy wrongly escalates.
SEARCH_SET = ["D-4420", "D-4505", "D-4402", "D-4489", "D-4516", "D-4427"]


async def main(generations: int, population: int, disputes: list[str]) -> int:
    store, world = InMemoryEffectStore(), ShadowWorld()
    seed = build_seed()
    epoch = load_into_world(world, seed, branch_id=PRIMARY)

    by_id = {d.id: d for d in seed.disputes}
    print(f"\n  SEARCH SET  {len(disputes)} disputes, "
          f"${sum(by_id[d].amount_usd for d in disputes):,.2f} at stake")
    for did in disputes:
        d = by_id[did]
        print(f"    {d.id}  ${d.amount_usd:8,.2f}  {d.reason}")
    print(f"\n  {generations} generations x {population} candidates, "
          f"proposed by gemini-3.5-flash reading its own scoreboard\n")

    search = PolicySearch(
        store=store, world=world, dispute_ids=disputes, epoch=epoch, concurrency=3
    )

    winner = None
    async for event in search.run(
        generations=generations, population=population, survivors=2
    ):
        kind = event["event"]
        if kind == "history":
            if event.get("recorded"):
                print(f"  HISTORY    recorded {event['effects']} effects on production "
                      f"for ${event.get('cost_usd', 0):.4f} — every candidate inherits this")
            else:
                print(f"  HISTORY    reusing {event['effects']} effects already on production")
            print()
        elif kind == "baseline":
            o = event["candidate"]["outcome"]
            print(f"  BASELINE   cost ${o['total_cost_usd']:>9,.2f}   "
                  f"wrongful ${o['wrongful_refunds_usd']:>8,.2f}   "
                  f"escalations {o['escalations']}   missed ${o['missed_valid_usd']:,.2f}")
            print()
        elif kind == "generation_start":
            print(f"  -- generation {event['generation']} " + "-" * 58)
            for c in event["candidates"]:
                print(f"     {c['id']}  {c['rationale'][:82]}")
        elif kind == "evaluated":
            c = event["candidate"]
            if c["error"]:
                print(f"     {c['id']}  ERROR {c['error'][:70]}")
                continue
            o = c["outcome"]
            delta = event["baseline_cost"] - o["total_cost_usd"]
            mark = "+" if delta > 0 else " "
            print(f"   {mark} {c['id']}  cost ${o['total_cost_usd']:>9,.2f}  "
                  f"delta ${delta:>+9,.2f}  wrongful ${o['wrongful_refunds_usd']:>8,.2f}  "
                  f"esc {o['escalations']}  missed ${o['missed_valid_usd']:>8,.2f}")
        elif kind == "generation_done":
            print(f"     best so far: ${event['best']['outcome']['total_cost_usd']:,.2f} "
                  f"(improvement ${event['improvement_usd']:,.2f})\n")
        elif kind == "search_done":
            winner = event

    print("  " + "=" * 78)
    if not winner or not winner["winner"]:
        print("  no candidate completed evaluation\n")
        return 1

    base, win = winner["baseline"], winner["winner"]["outcome"]
    print(f"  {'':26s}{'BASELINE':>16s}{'FOUND':>16s}{'DELTA':>16s}")
    print("  " + "-" * 78)
    for label, key in (
        ("total cost (USD)", "total_cost_usd"),
        ("wrongful refunds (USD)", "wrongful_refunds_usd"),
        ("missed valid (USD)", "missed_valid_usd"),
        ("escalations", "escalations"),
        ("refunds issued", "refunds_issued"),
    ):
        b, w = base[key], win[key]
        d = b - w
        fmt = ",.2f" if "USD" in label else "d"
        print(f"  {label:26s}{b:>16{fmt}}{w:>16{fmt}}{d:>+16{fmt}}")
    print("  " + "=" * 78)
    print(f"\n  {winner['evaluations']} full fleet evaluations against real history")
    print(f"  replay hits {winner['replay_hits']} / executed {winner['executed']}")
    print(f"  total compute ${winner['compute_usd']:,.4f}")
    print(f"  improvement  ${winner['improvement_usd']:,.2f} on {len(disputes)} disputes")
    print(f"\n  WINNING CLAUSE\n  {winner['winner']['text']}\n")
    print(f"  rationale: {winner['winner']['rationale']}\n")

    save(os.path.join(ROOT, "data/search.json"), store=store, world=world)
    print("  snapshot -> data/search.json\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=2)
    ap.add_argument("--population", type=int, default=3)
    ap.add_argument("--disputes", nargs="*", default=SEARCH_SET)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.generations, a.population, a.disputes)))
