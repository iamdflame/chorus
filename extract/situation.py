"""Stage [2]: unbounded text to a structured situation.

This is the stage that makes the model load-bearing, and it is the stage that cannot
collapse. A message is one person's words; two travellers in identical circumstances write
different sentences, so every distinct message is a distinct extraction. Only the stage
*after* this one — situation to preferences — shares, because by then the input is a
bounded lattice.

That is worth stating plainly because it changes the economics and the previous version of
this project did not account for it:

    naive          N extractions + N elicitations
    Chorus         D extractions + S elicitations

where D is the number of *distinct messages* and S the number of distinct situations. D is
large and grows with the population; S is bounded by the lattice. So collapse no longer
buys two orders of magnitude on the whole pipeline — it buys them on the half that is
bounded, and the honest headline is the blend, not the best stage.

What extraction returns beyond the projection:

    confidence          per field, because a guess and a certainty must not cost the same
    evidence            which span of the message supports each field, so a bucketing
                        decision is auditable rather than asserted
    unresolved          what could not be determined at all
    clarifying_question when a decision-critical field is missing, ask rather than guess
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from swarm.canonical import Projection

MODEL = "gemini-3.5-flash"

TIERS = ("basic", "silver", "gold", "platinum")
URGENCY = ("critical", "urgent", "same_day", "flexible")
PARTY = ("solo", "pair", "family", "group")
CONSTRAINTS = ("unencumbered", "checked_bags", "assisted")

SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {"type": "string", "enum": list(TIERS)},
        "urgency": {"type": "string", "enum": list(URGENCY)},
        "party": {"type": "string", "enum": list(PARTY)},
        "constraints": {"type": "string", "enum": list(CONSTRAINTS)},
        "confidence": {
            "type": "object",
            "properties": {k: {"type": "number"} for k in
                           ("tier", "urgency", "party", "constraints")},
        },
        "evidence": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in
                           ("tier", "urgency", "party", "constraints")},
        },
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "clarifying_question": {"type": "string"},
    },
    "required": ["tier", "urgency", "party", "constraints", "confidence", "evidence"],
}

INSTRUCTION = """You read one message from a traveller stranded by a major disruption and
determine their situation. You never see their name, booking or itinerary — only what they
wrote.

Assign exactly one value per field:

  tier         basic | silver | gold | platinum
               Their standing with the airline, if they indicate one. Mentioning frequent
               flying, a status card, lounge access or years of loyalty is evidence.
               Default to basic when nothing suggests otherwise.

  urgency      critical  must travel within a few hours
               urgent    must travel later today
               same_day  needs to travel by tomorrow
               flexible  can wait a day or more
               Judge from what they say is at stake, not from how upset they sound. A calm
               person with a funeral tomorrow is more urgent than a furious one with no
               deadline.

  party        solo | pair | family | group   (1 · 2 · 3-4 · 5+)
               Count the people travelling together, including the writer.

  constraints  assisted        anyone in the party needs mobility or medical assistance
               checked_bags    they have bags in the hold
               unencumbered    cabin baggage only
               Assistance outranks bags when both are present.

For every field give a confidence between 0 and 1, and quote the exact span of the message
that supports it in `evidence` — a substring of what they wrote, not a paraphrase. If a
field is genuinely undeterminable, still choose the most defensible value, put the field
name in `unresolved`, and give it a low confidence. If a decision-critical field is missing
and guessing would be irresponsible, write one `clarifying_question` you would ask them.

Messages may be in any language, may contain typos, may contradict themselves, and may
omit the thing that matters most. Report what the text supports, not what would be
convenient."""


@dataclass
class Extracted:
    """A structured situation, with its evidence."""

    message_id: str
    projection: Projection
    confidence: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    clarifying_question: str | None = None
    tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None

    @property
    def min_confidence(self) -> float:
        return min(self.confidence.values()) if self.confidence else 0.0

    def min_confidence_over(self, fields: tuple[str, ...]) -> float:
        """Lowest confidence among a chosen subset of fields.

        Routing must not weigh the model's uncertainty about an answer it is not going to
        use. Where the booking record is authoritative the extracted value is discarded,
        so doubt about it cannot put the traveller in the wrong bucket, and letting it
        force an escalation buys nothing and costs a full-price call.
        """
        picked = [self.confidence[f] for f in fields if f in self.confidence]
        return min(picked) if picked else 0.0

    @property
    def mean_confidence(self) -> float:
        values = list(self.confidence.values())
        return sum(values) / len(values) if values else 0.0

    def evidence_is_quoted(self, text: str) -> dict[str, bool]:
        """Whether each cited span actually appears in the message.

        An evidence field that does not is a paraphrase or a fabrication, and either way
        the audit trail is worthless. Checked rather than trusted.
        """
        return {k: (v or "").strip().lower() in text.lower() for k, v in self.evidence.items()}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["projection"] = self.projection.to_dict()
        payload["mean_confidence"] = round(self.mean_confidence, 3)
        return payload


def parse(message_id: str, payload: dict[str, Any]) -> Extracted:
    """Build an `Extracted` from model output, coercing anything out of range."""
    def pick(field_name: str, allowed: tuple[str, ...], fallback: str) -> str:
        value = str(payload.get(field_name, "")).strip().lower()
        return value if value in allowed else fallback

    projection = Projection(
        role="passenger",
        tier=pick("tier", TIERS, "basic"),
        urgency=pick("urgency", URGENCY, "same_day"),
        party=pick("party", PARTY, "solo"),
        constraints=pick("constraints", CONSTRAINTS, "unencumbered"),
    )
    raw_conf = payload.get("confidence") or {}
    confidence = {
        k: max(0.0, min(1.0, float(raw_conf.get(k, 0.5) or 0.5)))
        for k in ("tier", "urgency", "party", "constraints")
    }
    return Extracted(
        message_id=message_id,
        projection=projection,
        confidence=confidence,
        evidence={k: str(v) for k, v in (payload.get("evidence") or {}).items()},
        unresolved=[str(u) for u in (payload.get("unresolved") or [])],
        clarifying_question=payload.get("clarifying_question") or None,
    )
