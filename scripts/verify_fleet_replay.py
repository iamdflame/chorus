"""End-to-end proof on the real six-agent fleet.

`verify_determinism.py` proves the kernel property on a three-stage pipeline.
This proves it on the actual product: six agents, real tools that move money and send
mail, real policy retrieval over embeddings, real branch-isolated state.

    RECORD    the fleet resolves disputes on production
    REPLAY    the same questions re-asked on a fork -- free and exact
    PERTURB   one policy clause rewritten -- only what read it re-executes,
              and every irreversible action is staged rather than dispatched

Usage:  python scripts/verify_fleet_replay.py [--disputes N]
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

from fleet.domain import COMMS, LEDGER, POLICIES, TICKETS, build_seed, load_into_world
from fleet.orchestrator import FleetRunner
from kernel.branch import PRIMARY, Branch
from kernel.interposer import Mode
from kernel.snapshot import save
from kernel.store import InMemoryEffectStore
from world.shadow import ShadowWorld

CEILING_CLAUSE = "POL-REFUND-CEILING"


def row(label: str, *cells: object) -> str:
    return f"  {label:<28}" + "".join(f"{str(c):>18}" for c in cells)


def money(world: ShadowWorld, branch: str) -> dict[str, float | int]:
    ledger = world.scan(branch_id=branch, collection=LEDGER)
    refunds = [e for e in ledger.values() if e.get("type") == "refund"]
    return {
        "refunds": len(refunds),
        "refund_usd": round(sum(e.get("amount_usd", 0) for e in refunds), 2),
        "emails": len(world.scan(branch_id=branch, collection=COMMS)),
        "tickets": len(world.scan(branch_id=branch, collection=TICKETS)),
    }


async def main(count: int) -> int:
    store, world = InMemoryEffectStore(), ShadowWorld()
    seed = build_seed()
    epoch = load_into_world(world, seed, branch_id=PRIMARY)
    ids = [d.id for d in seed.disputes[:count]]
    print(f"\n  FLEET   6 agents, gemini-3.5-flash, {count} disputes on a 3-week history")
    print(f"  STAKE   {', '.join(f'{d.id} ${d.amount_usd:,.2f}' for d in seed.disputes[:count])}\n")

    # 1 -- RECORD on production ------------------------------------------------
    rec = FleetRunner(store=store, world=world, mode=Mode.RECORD, state_seq_floor=epoch)
    record = (await rec.run_batch(ids)).totals()
    production = money(world, PRIMARY)

    # 2 -- REPLAY the same questions on a fork ---------------------------------
    same = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="replay-check", at_seq=epoch)
    )
    world.register_branch(same)
    rep = FleetRunner(store=store, world=world, branch_id=same.id,
                      mode=Mode.REPLAY, state_seq_floor=epoch)
    replay = (await rep.run_batch(ids)).totals()

    # 3 -- PERTURB: tighten the refund ceiling ---------------------------------
    forked = store.create_branch(
        Branch.fork(
            parent=store.get_branch(PRIMARY), name="tighter-ceiling", at_seq=epoch,
            perturbation={"clause": CEILING_CLAUSE, "from": "USD 500.00", "to": "USD 50.00"},
        )
    )
    world.register_branch(forked)
    clause = world.read(branch_id=forked.id, collection=POLICIES, key=CEILING_CLAUSE)
    world.write(
        branch_id=forked.id, collection=POLICIES, key=CEILING_CLAUSE, seq=epoch + 1,
        value={**clause, "text": clause["text"].replace("USD 500.00", "USD 50.00"),
               "version": clause.get("version", 1) + 1},
    )
    per = FleetRunner(store=store, world=world, branch_id=forked.id,
                      mode=Mode.REPLAY, state_seq_floor=epoch + 1)
    perturbed = (await per.run_batch(ids)).totals()
    counterfactual = money(world, forked.id)

    # -- report ----------------------------------------------------------------
    print("  " + "=" * 82)
    print(row("", "RECORD", "REPLAY", "PERTURBED"))
    print("  " + "-" * 82)
    for label, key in (
        ("boundary crossings", "boundary_crossings"),
        ("served from store", "replay_hits"),
        ("actually executed", "executed"),
        ("quarantined actions", "quarantined"),
    ):
        print(row(label, record[key], replay[key], perturbed[key]))
    print(row("cost incurred (USD)", f"${record['cost_usd']:.4f}",
              f"${replay['cost_usd']:.4f}", f"${perturbed['cost_usd']:.4f}"))
    print(row("cost avoided (USD)", f"${record['cost_avoided_usd']:.4f}",
              f"${replay['cost_avoided_usd']:.4f}", f"${perturbed['cost_avoided_usd']:.4f}"))
    print("  " + "=" * 82)

    print()
    print(row("", "PRODUCTION", "COUNTERFACTUAL"))
    print("  " + "-" * 64)
    print(row("refunds issued", production["refunds"], counterfactual["refunds"]))
    print(row("refunded (USD)", f"${production['refund_usd']:,.2f}",
              f"${counterfactual['refund_usd']:,.2f}"))
    print(row("emails sent", production["emails"], counterfactual["emails"]))
    print(row("tickets opened", production["tickets"], counterfactual["tickets"]))

    diff = store.dag(PRIMARY).diff(store.dag(forked.id))
    print()
    print(row("causal diff", str(diff.summary())))
    print(row("production effects", len(store.own_effects(PRIMARY))))
    print(row("replay fork stored", len(store.own_effects(same.id))))
    print(row("perturbed fork stored", len(store.own_effects(forked.id))))

    failures: list[str] = []
    if replay["cost_usd"] != 0.0:
        failures.append(f"replay incurred ${replay['cost_usd']}; an exact replay is free")
    if replay["executed"] != 0:
        failures.append(f"replay executed {replay['executed']} crossings; expected 0")
    if len(store.own_effects(same.id)) != 0:
        failures.append("an exact replay stored effects; it should inherit everything")
    if perturbed["quarantined"] == 0:
        failures.append("no irreversible action was quarantined on the fork")
    if counterfactual["refund_usd"] > production["refund_usd"]:
        failures.append("a tighter ceiling refunded more, which is incoherent")
    if not diff.diverged:
        failures.append("rewriting the controlling policy changed nothing")

    save(os.path.join(ROOT, "data/history.json"), store=store, world=world)
    print(row("snapshot", "data/history.json"))

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    print(f"  PASS  replay reproduced {replay['replay_hits']} crossings for $0.00, and the "
          f"counterfactual\n        staged {perturbed['quarantined']} irreversible actions "
          f"instead of dispatching them.\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--disputes", type=int, default=3)
    raise SystemExit(asyncio.run(main(ap.parse_args().disputes)))
