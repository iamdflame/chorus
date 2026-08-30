"""Blast radius — which entities consumed a poisoned thought.

When an address is later found to be compromised, the question an incident responder has
to answer within minutes is *who was affected*. In almost every agent system this is a
forensic exercise: read the logs, guess at the propagation, hope nothing was missed.

Here it is a graph query, and the graph already exists. Because every effect is addressed
over its full causal history, the set of things downstream of a compromised call is its
**forward lightcone** — computed, not estimated. The property that makes replay cheap is
the same property that makes containment exact, which is the nicest thing about this design
and was not planned.

Two distinct radii, and conflating them would understate the damage:

    effects    everything causally downstream of the compromised call
    entities   every traveller served the thought that call produced

The second is larger than intuition suggests, and that is the whole warning. A poisoned
call in a cohort of four thousand did not affect one traveller. It affected four thousand,
because sharing the answer is precisely what the system was built to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from kernel.dag import CausalDAG
from policy.table import PolicyTable


@dataclass
class BlastRadius:
    """Everything one compromised address touched."""

    effect_id: str
    effects: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    cohorts: list[str] = field(default_factory=list)
    rows_invalidated: list[str] = field(default_factory=list)

    @property
    def amplification(self) -> int:
        """Entities reached per compromised model call.

        In an uncollapsed fleet this is 1 by construction. Here it is the collapse ratio,
        which is the same number the cost report celebrates.
        """
        return len(self.entities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "effects": self.effects,
            "entities": self.entities,
            "cohorts": self.cohorts,
            "rows_invalidated": self.rows_invalidated,
            "amplification": self.amplification,
        }


def blast_radius(
    dag: CausalDAG,
    effect_id: str,
    *,
    cohorts: Iterable[Any] = (),
) -> BlastRadius:
    """Compute who was affected by a compromised effect.

    `cohorts` are the traces from the run that served the traffic. A cohort is in the
    radius when the call that answered it lies in the compromised effect's forward
    lightcone — including the compromised call itself, because the entities it served are
    the primary victims, not collateral.
    """
    cone = dag.forward_lightcone(effect_id, include_roots=True)
    radius = BlastRadius(effect_id=effect_id, effects=sorted(cone))
    entities: list[str] = []
    for trace in cohorts:
        if trace.address is not None and trace.address in cone:
            radius.cohorts.append(trace.key)
            entities.extend(trace.members)
    radius.entities = sorted(entities)
    radius.cohorts.sort()
    return radius


def quarantine(
    table: PolicyTable, radius: BlastRadius
) -> BlastRadius:
    """Invalidate every policy row derived from inside the radius.

    Containment is worthless if the compromised answer stays in the table and keeps being
    served, so this runs as part of the response rather than as a follow-up. Rows are
    invalidated, not deleted: an auditor has to be able to see what was served and to
    whom, and destroying the evidence during incident response is its own failure.
    """
    for key in radius.cohorts:
        if table.lookup(key) is not None:
            table.invalidate(key)
            radius.rows_invalidated.append(key)
    # A row whose provenance names an effect inside the cone, even if its cohort was not
    # in this run's traces — a table outlives the run that derived it.
    for key, row in table.rows.items():
        if row.invalidated:
            continue
        if row.provenance.effect_id in set(radius.effects):
            table.invalidate(key)
            radius.rows_invalidated.append(key)
    radius.rows_invalidated = sorted(set(radius.rows_invalidated))
    return radius
