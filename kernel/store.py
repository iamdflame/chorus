"""Effect storage — a content-addressed cache with branch-chain resolution.

The store is the replay oracle. `lookup` is the hottest operation in the system: the
interposer calls it before every model call and every tool call, and its hit rate is the
difference between a free replay and a full re-execution.

Three reads, deliberately distinct (see `kernel/branch.py` for why the first two differ):

    lookup(branch, address)   replay oracle  — walks the whole chain, ignores fork_at_seq
    timeline(branch)          history view   — honours fork_at_seq, used for UI and diff
    own_effects(branch)       storage view   — only what this branch physically holds
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol, runtime_checkable

from kernel.branch import PRIMARY, Branch
from kernel.dag import CausalDAG
from kernel.effect import Effect
from kernel.errors import BranchExists, UnknownBranch


@runtime_checkable
class EffectStore(Protocol):
    """Storage backend contract.

    `InMemoryEffectStore` and `FirestoreEffectStore` both satisfy this, so the kernel
    never imports Google Cloud. That separation is what allows the determinism proof to
    run offline in CI against the same code path production uses.
    """

    def put(self, effect: Effect) -> None: ...
    def put_many(self, effects: Iterable[Effect]) -> None: ...
    def lookup(self, branch_id: str, address: str) -> Effect | None: ...
    def own_effects(self, branch_id: str) -> list[Effect]: ...
    def timeline(self, branch_id: str) -> list[Effect]: ...
    def next_seq(self, branch_id: str) -> int: ...
    def append_manifest(self, branch_id: str, addresses: list[str]) -> None: ...
    def manifest(self, branch_id: str) -> list[str]: ...
    def create_branch(self, branch: Branch) -> Branch: ...
    def get_branch(self, branch_id: str) -> Branch | None: ...
    def list_branches(self) -> list[Branch]: ...


class InMemoryEffectStore:
    """Reference implementation — the test backend and the local-dev backend.

    Kept deliberately simple and obviously correct: `FirestoreEffectStore` is validated
    against this one's behaviour, so a bug in the distributed backend surfaces as
    divergence from a known-good implementation rather than as a mysterious replay miss.
    """

    def __init__(self) -> None:
        self._by_branch: dict[str, dict[str, Effect]] = defaultdict(dict)
        self._seq: dict[str, int] = defaultdict(int)
        self._branches: dict[str, Branch] = {}
        self._manifests: dict[str, list[str]] = defaultdict(list)
        primary = Branch.primary()
        self._branches[primary.id] = primary

    # -- branches --------------------------------------------------------------

    def create_branch(self, branch: Branch) -> Branch:
        if branch.id in self._branches:
            raise BranchExists(f"branch already exists: {branch.id}",
                               branch_id=branch.id)
        if branch.parent_id and branch.parent_id not in self._branches:
            raise UnknownBranch(f"unknown parent branch: {branch.parent_id}",
                                branch_id=branch.id, parent_id=branch.parent_id)
        self._branches[branch.id] = branch
        return branch

    def get_branch(self, branch_id: str) -> Branch | None:
        return self._branches.get(branch_id)

    def list_branches(self) -> list[Branch]:
        return sorted(self._branches.values(), key=lambda b: b.created_at)

    def _chain(self, branch_id: str) -> list[Branch]:
        """The branch and all its ancestors, nearest first."""
        chain: list[Branch] = []
        seen: set[str] = set()
        current = self._branches.get(branch_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = self._branches.get(current.parent_id) if current.parent_id else None
        return chain

    # -- writes ----------------------------------------------------------------

    def put(self, effect: Effect) -> None:
        self._by_branch[effect.branch_id][effect.id] = effect
        if effect.seq > self._seq[effect.branch_id]:
            self._seq[effect.branch_id] = effect.seq

    def put_many(self, effects: Iterable[Effect]) -> None:
        for effect in effects:
            self.put(effect)

    def next_seq(self, branch_id: str) -> int:
        """Allocate the next sequence number on a branch.

        A fork starts numbering above its parent's fork point, so a branch timeline
        stays monotonic when rendered alongside the history it inherited.
        """
        if branch_id not in self._seq:
            branch = self._branches.get(branch_id)
            if branch and branch.fork_at_seq is not None:
                self._seq[branch_id] = branch.fork_at_seq
        self._seq[branch_id] += 1
        return self._seq[branch_id]

    def append_manifest(self, branch_id: str, addresses: list[str]) -> None:
        """Record the ordered addresses a run visited on this branch.

        The manifest is what lets a fork present a complete timeline while physically
        storing only the effects it actually executed. Without it a branch would have to
        copy its parent's history in order to display it, and forking would stop being
        O(1) — which is the property the whole product rests on.
        """
        self._manifests[branch_id].extend(addresses)

    def manifest(self, branch_id: str) -> list[str]:
        return list(self._manifests.get(branch_id, ()))

    # -- reads -----------------------------------------------------------------

    def lookup(self, branch_id: str, address: str) -> Effect | None:
        """Resolve an effect address against a branch and all its ancestors.

        No sequence cutoff, by design. An address encodes the full causal history of a
        request, so a hit is sound wherever in the parent's timeline it was recorded,
        and a genuinely diverged request cannot collide with one.
        """
        for branch in self._chain(branch_id):
            found = self._by_branch.get(branch.id, {}).get(address)
            if found is not None:
                return found
        return None

    def own_effects(self, branch_id: str) -> list[Effect]:
        """Only the effects recorded directly on this branch."""
        return sorted(
            self._by_branch.get(branch_id, {}).values(), key=lambda e: (e.seq, e.id)
        )

    def timeline(self, branch_id: str) -> list[Effect]:
        """The branch's history: inherited past, then its own run, in execution order.

        Unlike `lookup`, this honours `fork_at_seq` — a branch inherits its parent's
        past, not its parent's future. Effects the branch replayed rather than executed
        resolve through the chain to the parent's copy and therefore still carry the
        parent's `branch_id`, which is how the console distinguishes inherited work from
        newly executed work.
        """
        branch = self._branches.get(branch_id)
        if branch is None:
            return []
        out: list[Effect] = []
        seen: set[str] = set()

        if branch.parent_id and branch.fork_at_seq is not None:
            for effect in self.timeline(branch.parent_id):
                if effect.seq <= branch.fork_at_seq and effect.id not in seen:
                    seen.add(effect.id)
                    out.append(effect)

        visited = self._manifests.get(branch_id)
        if visited:
            for address in visited:
                if address in seen:
                    continue
                resolved = self.lookup(branch_id, address)
                if resolved is not None:
                    seen.add(address)
                    out.append(resolved)
        else:
            for effect in self.own_effects(branch_id):
                if effect.id not in seen:
                    seen.add(effect.id)
                    out.append(effect)
        return out

    def dag(self, branch_id: str) -> CausalDAG:
        """Materialise a branch's timeline as a causal graph."""
        return CausalDAG(self.timeline(branch_id))

    # -- diagnostics -----------------------------------------------------------

    def stats(self) -> dict[str, object]:
        return {
            "branches": len(self._branches),
            "effects_total": sum(len(v) for v in self._by_branch.values()),
            "effects_by_branch": {
                b: len(self._by_branch.get(b, {})) for b in self._branches
            },
        }


__all__ = ["EffectStore", "InMemoryEffectStore", "Branch", "PRIMARY"]
