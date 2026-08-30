"""Two instances, one store: does the saving survive horizontal scale?

Cloud Run runs several instances. Every collapse number in this repository was measured in
one process, where a single in-memory store means the second agent in a cohort always finds
the first one's answer. Across instances that is no longer automatic — and if it does not
hold, the whole economic claim degrades exactly when the system becomes popular enough to
need more than one instance, which is the worst possible time to find out.

What has to be true:

    [1] convergence   an effect written by instance A is visible to instance B
    [2] collapse      the second instance pays nothing for a situation the first answered
    [3] agreement     both instances resolve the same address to the same answer

The third is the one that would be easy to miss. Two instances that each answer half the
population and never collide would still show a good hit rate while quietly giving two
travellers in the same situation two different answers — which is the thing collapse exists
to prevent.

Requires Firestore. With no credentials it says so and exits non-zero, rather than passing
against an in-memory store and proving nothing about the distributed case.

    python scripts/verify_convergence.py
"""

from __future__ import annotations

import os
import sys
import uuid
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
from kernel.effect import Determinism, Effect, EffectKind
from swarm.canonical import bind, project_passenger
from swarm.scenario import build_scenario
from kernel.clock import FIXED


def main() -> int:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("\n  GOOGLE_CLOUD_PROJECT is unset. This proof is about the distributed")
        print("  backend; running it against an in-memory store would prove nothing.\n")
        return 1

    try:
        from kernel.firestore_store import FirestoreEffectStore
    except ImportError as exc:
        print(f"\n  Firestore client unavailable: {exc}\n")
        return 1

    # A namespace per run, so a failed run never poisons the next one and two developers
    # can run this at the same time without meeting in the middle.
    run_id = uuid.uuid4().hex[:8]
    branch = f"converge-{run_id}"
    print(f"\n  Two instances against one Firestore, branch {branch}\n")

    from kernel.branch import Branch

    # Two stores, two clients, one database — as close to two Cloud Run instances as a
    # single machine gets.
    a = FirestoreEffectStore(project=project, root=f"conv_{run_id}")
    b = FirestoreEffectStore(project=project, root=f"conv_{run_id}")
    a.create_branch(Branch(id=branch, name=branch, parent_id=None, fork_at_seq=None))

    passengers = [asdict(p) for p in build_scenario(passengers=400).passengers]
    projector = bind(project_passenger, FIXED)
    situations = sorted({projector(p).key() for p in passengers})[:40]

    # -- [1] instance A answers every situation --------------------------------
    written: dict[str, str] = {}
    for i, key in enumerate(situations):
        effect = Effect.create(
            branch_id=branch, seq=i + 1, agent="passenger",
            kind=EffectKind.MODEL_CALL, determinism=Determinism.RECORDED,
            causal_parents=(), request={"situation": key},
            response={"answer": {"urgency_score": 50 + (i % 40)}},
        )
        a.put(effect)
        written[key] = effect.id
    print(f"  [1] instance A recorded {len(written)} situations")

    # -- [2] instance B resolves them without executing anything ---------------
    hits = misses = 0
    disagreements: list[str] = []
    for key, address in written.items():
        found = b.lookup(branch, address)
        if found is None:
            misses += 1
            continue
        hits += 1
        original = a.lookup(branch, address)
        if original is None or found.response != original.response:
            disagreements.append(key)
    print(f"  [2] instance B resolved {hits}/{len(written)} from the shared store")
    print(f"      {misses} would have been paid for a second time")

    # -- [3] and got the same answer -------------------------------------------
    print(f"  [3] answers identical across instances: "
          f"{len(written) - len(disagreements)}/{len(written)}")

    failures: list[str] = []
    if misses:
        failures.append(f"{misses} situations did not converge across instances")
    if disagreements:
        failures.append(f"{len(disagreements)} situations resolved to different answers")

    # Leave the database as it was found. Safe because the root is unique to this run —
    # purging a shared root would delete a real effect log to tidy up after a test.
    removed = a.purge()

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print()
        return 1
    print(f"  PASS  a second instance paid nothing for {len(written)} situations the")
    print(f"        first had answered, and resolved every one to the same answer.")
    print(f"        Collapse survives horizontal scale.")
    print(f"\n        Cleaned up {removed} documents under the run's scratch root.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
