"""The five-stage pipeline, and an honest account of what each stage costs.

    [1] intake       unbounded   free text, one message per traveller
    [2] extraction   MODEL       text -> situation + confidence + evidence   (per message)
    [3] collapse     KERNEL      identical situations share one thought
    [4] elicitation  MODEL       situation -> preferences                    (per situation)
    [5] allocation   DETERMINISTIC  who gets which seat                      (no model)

The boundaries are the argument, and each is defensible out loud:

    [2] must be a model      the input is unbounded natural language; no table follows it
    [4] may be a model       the input is a bounded lattice, so this is where the kernel
                             earns its keep
    [5] must not be a model  allocation under hard constraints is what deterministic
                             optimisation is for, and a model is both dearer and worse

The economics that matter, stated plainly because the previous version got this wrong:

    naive     N extractions + N elicitations
    Chorus    D extractions + S elicitations

D is the number of distinct messages and grows with the population; S is the number of
distinct situations and is bounded by the lattice. Collapse therefore does not buy two
orders of magnitude across the pipeline — it buys them on the bounded half. The headline
must be the blend. Reporting only the collapsible stage is how a project ends up claiming
104x for a system that achieves rather less.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from extract.situation import Extracted
from kernel.effect import hash_payload
from swarm.canonical import Projection

# Below this, a situation is not trusted enough to answer from a shared thought: the
# traveller gets their own reasoning, uncollapsed, because a confident wrong bucket is
# worse than an expensive right one.
ESCALATION_THRESHOLD = 0.55


@dataclass
class StageCost:
    calls: int = 0
    cached: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "cached": self.cached,
                "cost_usd": round(self.cost_usd, 4)}


@dataclass
class PipelineReport:
    """What the whole pipeline cost, stage by stage, with nothing hidden."""

    entities: int = 0
    distinct_messages: int = 0
    distinct_situations: int = 0
    escalated: int = 0
    extraction: StageCost = field(default_factory=StageCost)
    elicitation: StageCost = field(default_factory=StageCost)

    @property
    def total_calls(self) -> int:
        return self.extraction.calls + self.elicitation.calls

    @property
    def naive_calls(self) -> int:
        """One extraction and one elicitation per entity — the uncollapsed pipeline."""
        return self.entities * 2

    @property
    def blended_collapse(self) -> float:
        """The number that must be quoted: the whole pipeline, not its best stage."""
        return self.naive_calls / self.total_calls if self.total_calls else 0.0

    @property
    def elicitation_collapse(self) -> float:
        """The bounded stage alone. Reported, but never as the headline."""
        return self.entities / self.elicitation.calls if self.elicitation.calls else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": self.entities,
            "distinct_messages": self.distinct_messages,
            "distinct_situations": self.distinct_situations,
            "escalated": self.escalated,
            "extraction": self.extraction.to_dict(),
            "elicitation": self.elicitation.to_dict(),
            "total_calls": self.total_calls,
            "naive_calls": self.naive_calls,
            "blended_collapse": round(self.blended_collapse, 1),
            "elicitation_collapse": round(self.elicitation_collapse, 1),
        }

    def summary(self) -> str:
        return (
            f"{self.entities:,} travellers · "
            f"{self.extraction.calls:,} extractions + {self.elicitation.calls} elicitations "
            f"= {self.total_calls:,} calls against {self.naive_calls:,} naive "
            f"({self.blended_collapse:.1f}x blended, "
            f"{self.elicitation_collapse:.0f}x on the collapsible stage)"
        )


def message_address(text: str) -> str:
    """Distinct messages are content-addressed too.

    Two travellers who send the same words are the same extraction. This is not a trick:
    in a real disruption a great many people write "what are my options", and paying twice
    to read the same sentence is the same waste the rest of the system exists to avoid.
    """
    return hash_payload({"stage": "extract", "text": text.strip().lower()})


def route(extracted: Extracted) -> str:
    """Where a traveller's reasoning should happen, and what it should cost.

    The escalation rule is the honest part of the design. A situation the extractor is
    unsure of must not be answered from a cohort's shared thought, because the cohort may
    be the wrong one — so it is reasoned about individually, at full price. That cost is
    reported rather than absorbed.
    """
    if extracted.error:
        return "escalate"
    if extracted.clarifying_question:
        return "ask"
    if extracted.min_confidence < ESCALATION_THRESHOLD:
        return "escalate"
    return "collapse"


def plan(extractions: list[Extracted]) -> dict[str, list[Extracted]]:
    """Group by destination stage, so the report can price each one separately."""
    buckets: dict[str, list[Extracted]] = {"collapse": [], "escalate": [], "ask": []}
    for extracted in extractions:
        buckets[route(extracted)].append(extracted)
    return buckets


def situations(extractions: list[Extracted]) -> dict[str, list[Extracted]]:
    """Distinct situations among the collapsible extractions."""
    grouped: dict[str, list[Extracted]] = {}
    for extracted in extractions:
        grouped.setdefault(extracted.projection.key(), []).append(extracted)
    return grouped
