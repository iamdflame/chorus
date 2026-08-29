"""The causal DAG — what turns a trace into a queryable structure.

A trace answers "what happened, in what order". It cannot answer "what did this
particular decision cause", because ordering is not causation: two effects adjacent in
a log may be entirely unrelated, and an effect 4,000 entries later may be a direct
consequence.

Every Effect carries explicit `causal_parents`, so the log is a directed acyclic graph
rather than a list. That upgrade is what makes the central questions computable:

    forward_lightcone(e)   everything e could have affected  -> blast radius, undo scope
    backward_lightcone(e)  everything that produced e        -> provenance, "why did it do that"

The name is borrowed from relativity, where an event's future light cone is the region
of spacetime it can causally influence. An agent action has exactly the same structure,
and the same practical meaning: nothing outside the cone needs to be re-examined.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Iterator

from kernel.effect import Effect, digest


@dataclass(frozen=True, slots=True)
class CausalDiff:
    """A structural comparison of two timelines.

    Deliberately not a textual diff. Two runs are compared by content address, so
    "identical" means *provably the same request at the same causal position with the
    same response* — not similar-looking text.
    """

    identical: frozenset[str]  # same address, same response
    changed: frozenset[str]    # same address, different response
    added: frozenset[str]      # present only in the right timeline
    removed: frozenset[str]    # present only in the left timeline

    @property
    def diverged(self) -> frozenset[str]:
        return frozenset(self.changed | self.added | self.removed)

    def summary(self) -> dict[str, int]:
        return {
            "identical": len(self.identical),
            "changed": len(self.changed),
            "added": len(self.added),
            "removed": len(self.removed),
            "diverged": len(self.diverged),
        }


class CausalDAG:
    """An append-only causal graph of effects.

    Acyclicity is guaranteed by construction rather than checked: an effect's address
    is a hash of its parents' addresses, so producing a cycle would require finding a
    hash preimage.
    """

    __slots__ = ("_effects", "_children", "_by_seq")

    def __init__(self, effects: Iterable[Effect] = ()) -> None:
        self._effects: dict[str, Effect] = {}
        self._children: dict[str, set[str]] = defaultdict(set)
        self._by_seq: list[str] = []
        for e in effects:
            self.add(e)

    # -- construction ----------------------------------------------------------

    def add(self, effect: Effect) -> None:
        """Insert an effect, indexing its inbound causal edges.

        Re-adding the same address replaces the record. That is intentional: an effect
        is opened (no response) before execution and closed (with response) after, and
        both carry the same address.
        """
        self._effects[effect.id] = effect
        if effect.id not in self._by_seq:
            self._by_seq.append(effect.id)
        for parent in effect.causal_parents:
            self._children[parent].add(effect.id)

    def __len__(self) -> int:
        return len(self._effects)

    def __contains__(self, effect_id: object) -> bool:
        return effect_id in self._effects

    def __iter__(self) -> Iterator[Effect]:
        return iter(self.ordered())

    def get(self, effect_id: str) -> Effect | None:
        return self._effects.get(effect_id)

    def ordered(self) -> list[Effect]:
        """Effects in recorded sequence order."""
        return sorted(self._effects.values(), key=lambda e: (e.seq, e.id))

    def children(self, effect_id: str) -> set[str]:
        return set(self._children.get(effect_id, ()))

    # -- the core queries ------------------------------------------------------

    def forward_lightcone(self, *roots: str, include_roots: bool = True) -> set[str]:
        """Every effect causally downstream of `roots`.

        This is the answer to "if this decision was wrong, what else is wrong?" — the
        blast radius. It is also exactly the set that must be re-executed when the root
        is perturbed, which is why replay cost scales with the cone and not the run.
        """
        seen: set[str] = set()
        queue = deque(r for r in roots if r in self._effects)
        while queue:
            node = queue.popleft()
            for child in self._children.get(node, ()):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        if include_roots:
            seen |= {r for r in roots if r in self._effects}
        return seen

    def backward_lightcone(self, *leaves: str, include_leaves: bool = True) -> set[str]:
        """Every effect that causally contributed to `leaves` — full provenance.

        This is the audit answer: "show me everything that led to this refund being
        issued", derived from recorded causality rather than reconstructed by reading
        a log.
        """
        seen: set[str] = set()
        queue = deque(l for l in leaves if l in self._effects)
        while queue:
            node = queue.popleft()
            effect = self._effects.get(node)
            if effect is None:
                continue
            for parent in effect.causal_parents:
                if parent not in seen and parent in self._effects:
                    seen.add(parent)
                    queue.append(parent)
        if include_leaves:
            seen |= {l for l in leaves if l in self._effects}
        return seen

    def frontier(self) -> tuple[str, ...]:
        """Effects with no recorded children — the current causal edge of the timeline."""
        return tuple(
            eid for eid in self._effects if not self._children.get(eid)
        )

    # -- integrity -------------------------------------------------------------

    def root_hash(self) -> str:
        """A single hash committing to the entire graph.

        Content ids are folded in sorted order rather than sequence order, so the hash
        is insensitive to the arbitrary interleaving of genuinely concurrent effects
        (agents running in parallel over Pub/Sub) while remaining sensitive to any
        change in causal structure or any response. Two runs sharing a root hash are
        the same computation, not merely a similar one.
        """
        return digest(*sorted(e.content_id for e in self._effects.values()))

    # -- comparison ------------------------------------------------------------

    def diff(self, other: CausalDAG) -> CausalDiff:
        """Compare this timeline (left/baseline) against `other` (right/counterfactual)."""
        left, right = set(self._effects), set(other._effects)
        shared = left & right
        identical, changed = set(), set()
        for eid in shared:
            if self._effects[eid].content_id == other._effects[eid].content_id:
                identical.add(eid)
            else:
                changed.add(eid)
        return CausalDiff(
            identical=frozenset(identical),
            changed=frozenset(changed),
            added=frozenset(right - left),
            removed=frozenset(left - right),
        )

    # -- reporting -------------------------------------------------------------

    def stats(self) -> dict[str, object]:
        replayed = sum(1 for e in self._effects.values() if e.replayed)
        quarantined = sum(1 for e in self._effects.values() if e.quarantined)
        by_agent: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        for e in self._effects.values():
            by_agent[e.agent] += 1
            by_kind[e.kind.value] += 1
        return {
            "effects": len(self._effects),
            "replayed": replayed,
            "executed": len(self._effects) - replayed,
            "quarantined": quarantined,
            "tokens_in": sum(e.tokens_in for e in self._effects.values()),
            "tokens_out": sum(e.tokens_out for e in self._effects.values()),
            "cost_usd": round(sum(e.cost_usd for e in self._effects.values()), 6),
            "by_agent": dict(by_agent),
            "by_kind": dict(by_kind),
            "root_hash": self.root_hash(),
        }
