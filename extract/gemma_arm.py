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

# Compact, but not stripped — and the difference between those two turned out to matter
# more than anything else in this comparison.
#
# Gemma cannot be handed `extract.situation.INSTRUCTION`, the rubric Gemini reads. Given it,
# Gemma does not merely score worse; it **never terminates**: 4,000 output tokens consumed
# by deliberation, `finishReason: MAX_TOKENS`, no answer at all, on every message tried.
#
# The obvious response was a bare field list, and that produced a badly misleading result.
# Gemma scored 26.7% on urgency — worse than a regex — because a bare list names the four
# bands without saying what they mean, so the model was guessing boundaries that Gemini had
# been given. Restoring one line of definition per field took urgency to 91.7% on the same
# messages. The first measurement was a fact about the prompt, not about the model.
#
# So the comparison is each model at its own best, which is the fairer test and also the
# only one available.
PROMPT = """Classify this traveller message. Answer with one JSON object and nothing else.

tier: basic|silver|gold|platinum  (mentions of status, loyalty, lounge = higher)
urgency: critical = must travel within hours | urgent = later today |
         same_day = by tomorrow | flexible = can wait a day or more
         Judge by what is at stake, not by how upset they sound.
party: solo=1 | pair=2 | family=3-4 | group=5+  (count everyone travelling together)
constraints: assisted = anyone needs mobility/medical help | checked_bags = bags in hold |
             unencumbered = cabin only.  Assistance outranks bags.

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
