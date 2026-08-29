"""The Shadow World — branch-isolated, time-travelling state.

Replaying an agent's reasoning is useless if the agent then reads today's database. A
counterfactual asked at effect 500 has to see the world as it stood at effect 500, not as
it stands now, or the answer is about a world that never existed.

So state here is not a mutable map. Every write is a *version* stamped with the sequence
position and branch that produced it, and a read resolves the newest version visible from
a given branch at a given moment. That is multi-version concurrency control, arranged over
a tree of branches rather than a line of transactions, and it buys three things at once:

    branch isolation   a fork writes into its own layer; production is never touched
    time travel        read(at_seq=N) reconstructs the world as of any past instant
    honest merges      a conflict is *detected*, because both sides' versions are kept

Visibility is the subtle part. A branch sees everything it wrote itself, but only what its
parent had written *before the fork* — otherwise a counterfactual would read data created
by the very future it is trying to reconsider. Cutoffs therefore accumulate as the minimum
along the ancestry chain.

Note the deliberate asymmetry with the effect store: effect *lookup* ignores fork points
(a recorded answer stays valid wherever it was recorded), while state *reads* honour them
strictly. Cache is about identity; state is about time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from kernel.branch import PRIMARY, Branch
from kernel.effect import canonical_json, digest

# Sentinel for "this key was deleted at this version", so a deletion on a branch can
# shadow an inherited value instead of silently falling through to the parent's.
TOMBSTONE = object()


@dataclass(frozen=True, slots=True)
class Version:
    """One immutable write."""

    collection: str
    key: str
    value: Any
    seq: int
    branch_id: str
    effect_id: str | None = None
    wall_ts: float = field(default_factory=time.time)

    @property
    def deleted(self) -> bool:
        return self.value is TOMBSTONE


@dataclass(frozen=True, slots=True)
class Conflict:
    """A key both sides changed after they diverged."""

    collection: str
    key: str
    base: Any
    ours: Any
    theirs: Any


class ShadowWorld:
    """Versioned, branch-aware state.

    `branches` is the same branch registry the effect store uses, so a timeline and the
    world it produced can never drift apart.
    """

    def __init__(self, branches: dict[str, Branch] | None = None) -> None:
        self._versions: dict[tuple[str, str], list[Version]] = {}
        self._branches: dict[str, Branch] = branches if branches is not None else {}
        if PRIMARY not in self._branches:
            self._branches[PRIMARY] = Branch.primary()

    # -- branch registry -------------------------------------------------------

    def register_branch(self, branch: Branch) -> None:
        self._branches[branch.id] = branch

    def _visibility(self, branch_id: str) -> list[tuple[str, int | None]]:
        """Ancestry as (branch, cutoff) pairs, nearest first.

        `None` means unrestricted. Cutoffs take the running minimum: a grandchild cannot
        see more of its grandparent than its parent could.
        """
        out: list[tuple[str, int | None]] = []
        cutoff: int | None = None
        current = self._branches.get(branch_id)
        seen: set[str] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            out.append((current.id, cutoff))
            if current.parent_id and current.fork_at_seq is not None:
                cutoff = (
                    current.fork_at_seq
                    if cutoff is None
                    else min(cutoff, current.fork_at_seq)
                )
            current = self._branches.get(current.parent_id) if current.parent_id else None
        return out

    # -- writes ----------------------------------------------------------------

    def write(
        self,
        *,
        branch_id: str,
        collection: str,
        key: str,
        value: Any,
        seq: int,
        effect_id: str | None = None,
    ) -> Version:
        version = Version(
            collection=collection,
            key=key,
            value=value,
            seq=seq,
            branch_id=branch_id,
            effect_id=effect_id,
        )
        history = self._versions.setdefault((collection, key), [])
        history.append(version)
        # Kept sorted so resolution is a reverse scan rather than a sort per read.
        history.sort(key=lambda v: (v.seq, v.branch_id))
        return version

    def delete(
        self, *, branch_id: str, collection: str, key: str, seq: int,
        effect_id: str | None = None,
    ) -> Version:
        return self.write(
            branch_id=branch_id, collection=collection, key=key,
            value=TOMBSTONE, seq=seq, effect_id=effect_id,
        )

    # -- reads -----------------------------------------------------------------

    def _resolve(
        self, collection: str, key: str, branch_id: str, at_seq: int | None
    ) -> Version | None:
        history = self._versions.get((collection, key))
        if not history:
            return None
        for bid, cutoff in self._visibility(branch_id):
            limit = cutoff if at_seq is None else (
                at_seq if cutoff is None else min(cutoff, at_seq)
            )
            for version in reversed(history):
                if version.branch_id != bid:
                    continue
                if limit is not None and version.seq > limit:
                    continue
                return version
        return None

    def read(
        self, *, branch_id: str, collection: str, key: str, at_seq: int | None = None
    ) -> Any | None:
        """The value visible from `branch_id`, optionally as of sequence `at_seq`."""
        version = self._resolve(collection, key, branch_id, at_seq)
        if version is None or version.deleted:
            return None
        return version.value

    def keys(self, *, branch_id: str, collection: str, at_seq: int | None = None) -> list[str]:
        found = {
            key
            for (coll, key) in self._versions
            if coll == collection
            and self.read(branch_id=branch_id, collection=collection, key=key, at_seq=at_seq)
            is not None
        }
        return sorted(found)

    def scan(
        self, *, branch_id: str, collection: str, at_seq: int | None = None
    ) -> dict[str, Any]:
        """The whole collection as visible from a branch at a moment."""
        return {
            key: self.read(branch_id=branch_id, collection=collection, key=key, at_seq=at_seq)
            for key in self.keys(branch_id=branch_id, collection=collection, at_seq=at_seq)
        }

    def history(self, *, collection: str, key: str) -> list[Version]:
        return list(self._versions.get((collection, key), ()))

    # -- comparison and merge --------------------------------------------------

    def written_on(self, branch_id: str) -> Iterator[Version]:
        """Versions physically written by this branch — its overlay."""
        for history in self._versions.values():
            for version in history:
                if version.branch_id == branch_id:
                    yield version

    def diff(self, *, left: str, right: str, at_seq: int | None = None) -> dict[str, dict[str, Any]]:
        """Value-level differences between two timelines.

        Keyed `collection/key`, each entry carrying both sides. This is what the console
        renders as the reality diff, and what makes a counterfactual answerable in the
        units the business cares about rather than in effect counts.
        """
        touched = {
            (v.collection, v.key)
            for branch in (left, right)
            for v in self.written_on(branch)
        }
        out: dict[str, dict[str, Any]] = {}
        for collection, key in sorted(touched):
            lv = self.read(branch_id=left, collection=collection, key=key, at_seq=at_seq)
            rv = self.read(branch_id=right, collection=collection, key=key, at_seq=at_seq)
            if lv != rv:
                out[f"{collection}/{key}"] = {"left": lv, "right": rv}
        return out

    def conflicts(self, *, branch_id: str, into: str = PRIMARY) -> list[Conflict]:
        """Keys this branch changed that `into` also changed after the fork.

        Merging without this check would let a counterfactual silently overwrite work
        production did while the branch was being explored.
        """
        branch = self._branches.get(branch_id)
        if branch is None or branch.fork_at_seq is None:
            return []
        found: list[Conflict] = []
        for version in self.written_on(branch_id):
            target_history = self._versions.get((version.collection, version.key), [])
            moved_on = [
                v for v in target_history
                if v.branch_id == into and v.seq > branch.fork_at_seq
            ]
            if moved_on:
                base = self.read(
                    branch_id=into, collection=version.collection,
                    key=version.key, at_seq=branch.fork_at_seq,
                )
                found.append(
                    Conflict(
                        collection=version.collection,
                        key=version.key,
                        base=base,
                        ours=version.value,
                        theirs=moved_on[-1].value,
                    )
                )
        return found

    def merge(
        self, *, branch_id: str, into: str = PRIMARY, seq: int, force: bool = False
    ) -> dict[str, Any]:
        """Apply a branch's overlay onto another timeline.

        Refuses on conflict unless forced. The refusal is the point: a system that lets
        you rewrite production from a counterfactual without noticing that production
        moved is not safer than having no branches at all.
        """
        conflicts = self.conflicts(branch_id=branch_id, into=into)
        if conflicts and not force:
            return {
                "merged": False,
                "conflicts": [
                    {"collection": c.collection, "key": c.key,
                     "base": c.base, "ours": c.ours, "theirs": c.theirs}
                    for c in conflicts
                ],
                "applied": 0,
            }

        # Apply the branch's final value per key, not every intermediate version.
        final: dict[tuple[str, str], Version] = {}
        for version in self.written_on(branch_id):
            existing = final.get((version.collection, version.key))
            if existing is None or version.seq >= existing.seq:
                final[(version.collection, version.key)] = version

        for (collection, key), version in sorted(final.items()):
            self.write(
                branch_id=into, collection=collection, key=key,
                value=version.value, seq=seq, effect_id=version.effect_id,
            )
        return {
            "merged": True,
            "conflicts": [],
            "applied": len(final),
            "forced": force and bool(conflicts),
        }

    def fingerprint(
        self, *, branch_id: str, collections: tuple[str, ...], at_seq: int | None = None
    ) -> str:
        """A content hash of the state visible to a reader of `collections`.

        This closes the hole that otherwise makes counterfactuals silently wrong. A tool
        that reads world state is not a pure function of its arguments: `search_policy`
        with an unchanged query returns different clauses after a policy edit. Addressing
        it by arguments alone means a replay hits the cache and hands the agent the old
        policy, so the perturbation never propagates and the counterfactual reports that
        nothing changed.

        Folding this fingerprint into the address makes the dependency explicit: edit a
        clause, and every call that reads the corpus misses and re-executes, while calls
        reading untouched collections still hit. The read set is the unit of invalidation.
        """
        parts: list[str] = []
        for collection in sorted(collections):
            visible = self.scan(branch_id=branch_id, collection=collection, at_seq=at_seq)
            parts.append(collection)
            parts.append(canonical_json(visible).decode("utf-8"))
        return digest(*parts)

    # -- diagnostics -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "keys": len(self._versions),
            "versions": sum(len(v) for v in self._versions.values()),
            "collections": sorted({c for (c, _) in self._versions}),
        }
