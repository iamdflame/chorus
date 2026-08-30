"""Generating the unbounded input the thesis actually needs.

v1 fed the model five categorical fields. A 192-row table replicates that exactly, which
is why a hand-written table beat it — and any corpus built from templates would reproduce
the same defeat in a new costume, because a regex parses a template.

So the corpus is written by a model, and the ground truth is known **by construction**
rather than by labelling. We start from a situation we already know, ask for a message a
person in that situation might plausibly send, and never show the generator the bucket
vocabulary. The label is therefore exact and free, and the text is genuinely varied — the
two properties a labelled-afterwards corpus cannot have at once.

What makes it hard on purpose:

    register      panicked, curt, formal, rambling, resigned, angry, apologetic
    mechanics     typos, abbreviations, missing punctuation, emoji, ALL CAPS
    completeness  some messages omit the very thing the decision needs
    conflict      some contradict themselves, because people do
    language      a slice in other languages, collapsing to the same cells as English

Generated once, committed, and read from disk by every proof, so the offline path stays
free and reproducible while the input space stays genuinely open.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "corpus.json"

REGISTERS = (
    "panicked and rambling", "clipped and businesslike", "polite but exhausted",
    "angry", "resigned and dry", "apologetic and over-explaining",
    "texting shorthand with typos", "formal, almost legalistic",
)
LANGUAGES = (
    ("English", 0.72), ("Spanish", 0.07), ("French", 0.05), ("German", 0.05),
    ("Portuguese", 0.04), ("Japanese", 0.03), ("Hindi", 0.02), ("Arabic", 0.02),
)
COMPLICATIONS = (
    "mentions a detail that is irrelevant to the decision",
    "omits the single most decision-relevant fact",
    "contradicts itself once, the way a stressed person does",
    "buries the important detail in the last sentence",
    "understates the urgency out of politeness",
    "overstates the urgency",
    "mentions a companion whose needs differ from their own",
    "asks a question instead of stating a need",
)


@dataclass
class Message:
    """One message, and the situation it was generated from."""

    id: str
    passenger_id: str
    text: str
    language: str
    register: str
    complication: str
    # Ground truth, known because the message was written from it.
    truth: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def situation_brief(passenger: dict[str, Any], projection: Any) -> str:
    """Describe the situation in prose the generator can act on.

    Deliberately avoids the bucket names. If the generator is told the traveller is
    "critical urgency, solo, checked bags", it writes those words back and extraction
    becomes string matching — which would make the whole corpus worthless as evidence.
    """
    hours = {"critical": "within the next few hours",
             "urgent": "later today",
             "same_day": "by tomorrow",
             "flexible": "some time in the next couple of days"}[projection.urgency]
    party = {"solo": "travelling alone",
             "pair": "travelling with one other person",
             "family": "travelling with their family, three or four of them",
             "group": "travelling in a group of five or more"}[projection.party]
    constraint = {"unencumbered": "has only a cabin bag",
                  "checked_bags": "has bags in the hold",
                  "assisted": "needs mobility assistance"}[projection.constraints]
    status = {"basic": "no particular status with the airline",
              "silver": "some frequent-flyer status",
              "gold": "good frequent-flyer status",
              "platinum": "top-tier frequent-flyer status"}[projection.tier]
    return (
        f"They need to reach {passenger.get('destination', 'their destination')} {hours}. "
        f"They are {party}. They {constraint}. They have {status}."
    )


def sample_language(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for name, weight in LANGUAGES:
        cumulative += weight
        if roll <= cumulative:
            return name
    return "English"


def build_prompt(briefs: list[tuple[str, str, str, str]]) -> str:
    """One call produces many messages — the corpus is the expensive part, not the point."""
    items = "\n".join(
        f'{i+1}. situation: {brief}\n   voice: {register}\n   language: {language}\n'
        f'   quirk: {complication}'
        for i, (brief, register, language, complication) in enumerate(briefs)
    )
    return (
        "Write the message each of these stranded air travellers would actually send to "
        "an airline, by text or web form, during a major disruption.\n\n"
        "Rules:\n"
        "- Write as the traveller, in the first person. One short paragraph each.\n"
        "- Use the given voice, language and quirk.\n"
        "- NEVER use airline jargon or category words like 'tier', 'urgency', 'party "
        "size', 'critical', 'flexible', 'assisted', 'unencumbered'. Real people do not "
        "talk like a database.\n"
        "- Convey the situation indirectly, the way a person would: through what they "
        "mention, what they worry about, and what they ask for.\n"
        "- Vary sentence length and structure between messages. Include realistic typos "
        "where the voice calls for it.\n\n"
        f"{items}\n\n"
        'Return ONLY JSON: {"messages": ["...", "..."]} in the same order.'
    )


# Words that would mean the generator wrote the label instead of the situation. Ordinary
# English collisions are excluded deliberately: "family", "group" and "pair" are how people
# actually describe who they are with, and a traveller writing "our family of four" is
# giving information, not reciting a schema. The words below have no natural use in a
# stranded traveller's message and their presence means the corpus is describing itself.
# Only terms with no natural use in a stranded traveller's message. Bare category words
# are deliberately absent: "critical" is an ordinary adjective ("her critical medical
# appointment"), "family" and "group" are how people describe who they are with, and
# flagging those produced false positives that said more about the checker than the
# corpus. What survives here is language a person would never reach for — schema names,
# snake_case, and the category words only in an explicitly categorical context.
JARGON = (
    "urgency band", "urgency:", "critical urgency", "same_day", "same-day band",
    "unencumbered", "party size", "party band", "loyalty tier", "tier:",
    "platinum tier", "gold tier", "silver tier", "basic tier",
    "constraint band", "constraints:", "projection", "bucket",
)


def jargon_leaks(text: str) -> list[str]:
    """Category words a real message would never contain."""
    low = text.lower()
    return [word for word in JARGON if word in low]


def load_corpus(path: Path | None = None) -> list[Message]:
    """Read the committed corpus. Every offline proof uses this rather than generating."""
    target = path or CORPUS_PATH
    if not target.exists():
        return []
    payload = json.loads(target.read_text())
    return [Message(**m) for m in payload.get("messages", [])]


def corpus_stats(messages: Iterable[Message]) -> dict[str, Any]:
    messages = list(messages)
    if not messages:
        return {"messages": 0}
    texts = {m.text for m in messages}
    return {
        "messages": len(messages),
        "distinct_texts": len(texts),
        "languages": len({m.language for m in messages}),
        "registers": len({m.register for m in messages}),
        "mean_chars": round(sum(len(m.text) for m in messages) / len(messages)),
        "shortest": min(len(m.text) for m in messages),
        "longest": max(len(m.text) for m in messages),
    }
