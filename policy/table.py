"""The distilled policy table — every thought the fleet has had, with its receipts.

A run produces one answer per distinct situation. Those answers are not disposable: the
same situations recur every disruption, and paying a model to re-derive an answer it has
already given is the waste this project exists to remove. Compiling them into a table
turns a swarm's reasoning into a deterministic lookup — after which the interesting
question is no longer "how much did we save" but **"is the model still needed at all?"**

Every row carries provenance, and this is the part that makes the table trustworthy rather
than merely fast:

    the effect address that produced it   — the exact call, replayable, auditable
    the model that answered               — so a model change can invalidate rows
    when it was derived                   — from the injected clock, never wall time
    how many entities it has served       — what it would cost to lose it

A row without provenance is a cached guess. A row with it is a decision you can defend to
an auditor, which is the difference between a system an enterprise can deploy and one it
cannot.

The table's `version` is derived from its content, exactly as effect addresses are. Two
tables with identical rows have identical versions on any machine; changing one answer
changes the version. That is what lets a deployment pin a policy, and what makes drift
detectable rather than anecdotal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from kernel.clock import Clock
from kernel.effect import canonical_json, digest
from swarm.canonical import SCHEMA_VERSION

# The lattice size for the current projection: 4 tiers x 4 urgencies x 4 parties
# x 3 constraints x 3 hauls x 2 hotel x 2 misconnect. Stated rather than discovered,
# because a table's occupancy is meaningless without the ceiling it is measured against.
LATTICE_CEILING = 4 * 4 * 4 * 3 * 3 * 2 * 2


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a row came from. Never optional, never inferred."""

    effect_id: str | None
    model: str
    derived_at: str
    served: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "model": self.model,
            "derived_at": self.derived_at,
            "served": self.served,
        }


@dataclass
class PolicyRow:
    """One situation and the answer the fleet settled on for it."""

    key: str
    answer: dict[str, Any]
    provenance: Provenance
    confirmations: int = 0
    disagreements: int = 0
    invalidated: bool = False

    @property
    def trust(self) -> float:
        """Share of shadow samples that confirmed this row.

        Unsampled rows return nan rather than 1.0. An untested row is not a trusted row,
        and reporting it as one would be the single most dishonest number this file could
        produce.
        """
        seen = self.confirmations + self.disagreements
        return self.confirmations / seen if seen else float("nan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "answer": self.answer,
            "provenance": self.provenance.to_dict(),
            "confirmations": self.confirmations,
            "disagreements": self.disagreements,
            "invalidated": self.invalidated,
        }


@dataclass
class PolicyTable:
    """A versioned, content-addressed set of rows."""

    rows: dict[str, PolicyRow] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    ceiling: int = LATTICE_CEILING

    # -- identity --------------------------------------------------------------

    @property
    def version(self) -> str:
        """Content hash of every live answer, in a canonical order.

        Invalidated rows are excluded deliberately: an invalidated row is not part of the
        policy, so a table that has dropped one must not claim to be the table that
        still had it.
        """
        parts: list[str] = [self.schema_version]
        for key in sorted(self.rows):
            row = self.rows[key]
            if row.invalidated:
                continue
            parts.append(key)
            parts.append(canonical_json(row.answer).decode("utf-8"))
        return digest(*parts)[:12]

    # -- reads -----------------------------------------------------------------

    def lookup(self, key: str) -> PolicyRow | None:
        """The answer for a situation, or None if the model is still needed.

        An invalidated row returns None rather than its stale answer. Drift detection is
        worthless if the row it flagged keeps being served.
        """
        row = self.rows.get(key)
        if row is None or row.invalidated:
            return None
        return row

    @property
    def populated(self) -> int:
        return sum(1 for r in self.rows.values() if not r.invalidated)

    @property
    def occupancy(self) -> float:
        return self.populated / self.ceiling if self.ceiling else 0.0

    @property
    def served_total(self) -> int:
        return sum(r.provenance.served for r in self.rows.values())

    # -- writes ----------------------------------------------------------------

    def add(self, row: PolicyRow) -> None:
        self.rows[row.key] = row

    def confirm(self, key: str) -> None:
        row = self.rows.get(key)
        if row is not None:
            row.confirmations += 1

    def invalidate(self, key: str) -> None:
        """Mark a row stale. The answer is kept, so an audit can see what was served."""
        row = self.rows.get(key)
        if row is not None:
            row.disagreements += 1
            row.invalidated = True

    # -- serialisation ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "schema_version": self.schema_version,
            "ceiling": self.ceiling,
            "populated": self.populated,
            "occupancy": round(self.occupancy, 4),
            "rows": [self.rows[k].to_dict() for k in sorted(self.rows)],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PolicyTable:
        table = cls(
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            ceiling=payload.get("ceiling", LATTICE_CEILING),
        )
        for raw in payload.get("rows", []):
            prov = raw.get("provenance", {})
            table.add(PolicyRow(
                key=raw["key"],
                answer=raw["answer"],
                provenance=Provenance(
                    effect_id=prov.get("effect_id"),
                    model=prov.get("model", "unknown"),
                    derived_at=prov.get("derived_at", ""),
                    served=prov.get("served", 0),
                ),
                confirmations=raw.get("confirmations", 0),
                disagreements=raw.get("disagreements", 0),
                invalidated=raw.get("invalidated", False),
            ))
        return table


def distill(
    cohorts: Iterable[Any], *, clock: Clock, model: str
) -> PolicyTable:
    """Compile a run's cohort traces into a policy table.

    Takes traces rather than effects on purpose. Recovering which projection produced
    which model call from the effect log alone would mean matching prompt text back to a
    situation — the fragile inference that content addressing exists to make unnecessary.
    The trace records it at the moment it is known.

    A cohort that produced no answer contributes no row. A table is a set of answers, and
    inventing one for a situation the fleet failed on would be the worst kind of quiet
    lie: it would look identical to a real row and serve traffic forever.
    """
    table = PolicyTable()
    derived_at = clock.now().isoformat()
    for trace in cohorts:
        if trace.answer is None:
            continue
        table.add(PolicyRow(
            key=trace.key,
            answer=trace.answer,
            provenance=Provenance(
                effect_id=trace.address,
                model=model,
                derived_at=derived_at,
                served=trace.served,
            ),
        ))
    return table
