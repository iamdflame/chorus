"""Extraction by Gemma — the same task, a different model family.

The point is not that Gemma is cheaper. It is not: its thinking cannot be disabled and it
spends roughly twenty-seven tokens reasoning for every token of answer. The point is that it
was trained separately, so where it agrees with Gemini the answer is corroborated by two
independent readers, and where it disagrees something is genuinely ambiguous — or one of
them is wrong.

That is worth more to this project than a cost saving, because the Necessity Ledger has a
blind spot exactly here: it re-asks the same model, which finds a stale table but never a
consistently mistaken one.

The schema is described in the prompt rather than enforced, because Gemma rejects
`response_schema` outright. Everything Gemma returns is therefore validated against the same
closed vocabulary the projection uses — an out-of-vocabulary value is a parse failure, not a
new bucket, or an unbounded input would quietly become an unbounded lattice.
"""

from __future__ import annotations

from typing import Any

from extract.situation import Extracted, parse
from models.gemma import GemmaReply, ask

# The closed vocabularies. Anything else is rejected rather than admitted as a new value.
VOCABULARY = {
    "tier": ("basic", "silver", "gold", "platinum"),
    "urgency": ("critical", "urgent", "same_day", "flexible"),
    "party": ("solo", "pair", "family", "group"),
    "constraints": ("assisted", "checked_bags", "unencumbered"),
}

# Deliberately terse, and the terseness is a finding rather than a style choice.
#
# Gemini reads the full rubric in `extract.situation.INSTRUCTION` and is more accurate for
# it. Handed the same rubric, Gemma does not merely do worse — it **never terminates**:
# 4,000 output tokens consumed entirely by deliberation, `finishReason: MAX_TOKENS`, no
# answer at all, on every message tried. The compact form below finishes in roughly 726
# thought tokens and parses cleanly.
#
# So the two models cannot be given the same prompt, and the comparison below is
# consequently between each model at its own best, not between one prompt on two models.
# That is the fairer test and it is also the only one available.
PROMPT = """Classify this traveller message. Answer with one JSON object and nothing else.

tier: basic|silver|gold|platinum
urgency: critical|urgent|same_day|flexible
party: solo|pair|family|group
constraints: assisted|checked_bags|unencumbered

Message: {text}

JSON:"""


def prompt_for(text: str) -> str:
    return PROMPT.format(text=text)


def coerce(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Reject anything outside the declared vocabulary.

    A model that invents a fifth tier has not given a worse answer, it has given an
    unusable one: the lattice is a fixed set of cells and a value outside it cannot be
    addressed, collapsed, or compared with Gemini's.
    """
    for field, allowed in VOCABULARY.items():
        value = payload.get(field)
        if not isinstance(value, str) or value not in allowed:
            return None
    return payload


def extract(message_id: str, text: str, *, api_key: str | None = None) -> tuple[Extracted, GemmaReply]:
    """One Gemma extraction, shaped like every other extractor's output."""
    reply = ask(prompt_for(text), api_key=api_key)
    if reply.payload is None:
        return Extracted(
            message_id=message_id,
            projection=_fallback_projection(),
            error=reply.error or "gemma returned no parseable JSON",
        ), reply
    cleaned = coerce(reply.payload)
    if cleaned is None:
        return Extracted(
            message_id=message_id,
            projection=_fallback_projection(),
            error="gemma returned a value outside the declared vocabulary",
        ), reply
    return parse(message_id, cleaned), reply


def _fallback_projection():
    from swarm.canonical import Projection

    return Projection(
        role="passenger", tier="basic", urgency="flexible",
        party="solo", constraints="unencumbered",
    )
