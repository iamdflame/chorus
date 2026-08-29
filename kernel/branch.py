"""Branches — forking a timeline in constant time.

A branch is a *reference*, not a copy: `(parent, fork_at_seq, overlay)`. Forking a
12,000-effect timeline writes one small record. Everything the branch does not itself
override is resolved by walking down the parent chain, the way an overlay filesystem
or a git object store resolves reads.

The subtle part, and the reason replay on a fork is nearly free:

    Effect lookup ignores `fork_at_seq`. State reads honour it.

These are different questions. `fork_at_seq` answers "what did the world look like at
the moment I forked" — a fact about data, so the Shadow World cuts state reads there.
Effect lookup asks something else: "has this exact request, with this exact causal
ancestry, been answered before?" An effect's address already encodes its entire causal
history, so if the branch has genuinely diverged the address differs and the lookup
misses on its own. Cutting effect lookups by sequence would add nothing for soundness
and would throw away every cache hit after the fork point — turning a cheap fork into
a full re-execution. The hash does the work that a sequence cutoff cannot.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

PRIMARY = "primary"
"""The branch representing reality. Irreversible effects execute for real only here."""


@dataclass(frozen=True, slots=True)
class Branch:
    """A named timeline.

    `fork_at_seq` is the parent sequence position this branch diverges from; effects
    recorded on the parent after that position are not part of this branch's history
    (though they remain available as replay cache — see the module docstring).
    """

    id: str
    name: str
    parent_id: str | None = None
    fork_at_seq: int | None = None
    fork_at_effect: str | None = None
    created_at: float = field(default_factory=time.time)
    # Human-readable description of what was changed at the fork, e.g.
    # {"kind": "policy_edit", "path": "refund.auto_approve_ceiling", "from": 500, "to": 50}
    perturbation: dict[str, Any] | None = None
    merged_into: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_primary(self) -> bool:
        return self.id == PRIMARY

    @classmethod
    def primary(cls) -> Branch:
        return cls(id=PRIMARY, name="production")

    @classmethod
    def fork(
        cls,
        *,
        parent: Branch,
        name: str,
        at_seq: int,
        at_effect: str | None = None,
        perturbation: dict[str, Any] | None = None,
    ) -> Branch:
        return cls(
            id=f"br_{uuid.uuid4().hex[:12]}",
            name=name,
            parent_id=parent.id,
            fork_at_seq=at_seq,
            fork_at_effect=at_effect,
            perturbation=perturbation,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "fork_at_seq": self.fork_at_seq,
            "fork_at_effect": self.fork_at_effect,
            "created_at": self.created_at,
            "perturbation": self.perturbation,
            "merged_into": self.merged_into,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Branch:
        return cls(
            id=d["id"],
            name=d["name"],
            parent_id=d.get("parent_id"),
            fork_at_seq=d.get("fork_at_seq"),
            fork_at_effect=d.get("fork_at_effect"),
            created_at=d.get("created_at", 0.0),
            perturbation=d.get("perturbation"),
            merged_into=d.get("merged_into"),
            meta=d.get("meta", {}),
        )
