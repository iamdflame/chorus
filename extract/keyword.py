"""The control: extract the situation without a model.

Built in good faith and tuned against the corpus, because a strawman control proves
nothing. If a keyword extractor can read these messages as well as Gemini can, then the
model is not earning its place at this stage either, and the honest thing is to find that
out here rather than have a judge find it.

Includes multilingual cues, negation handling, and numeric party detection — everything a
competent engineer would reach for before deciding they needed an LLM.

What it fundamentally cannot do, and what the comparison is really testing:

    inference     "my mother is 84 and can't manage stairs" implies assistance without
                  containing any assistance keyword
    weighing      "I'd rather not fly tomorrow but I suppose I could" is flexible, and
                  every keyword in it says urgent
    contradiction "we're not in a rush, though we must land before the funeral at six"
    omission      deciding what is *unsaid* is not a pattern match
"""

from __future__ import annotations

import re
from typing import Any

from extract.situation import Extracted
from swarm.canonical import Projection

# Multilingual, because a third of the corpus is not in English and an extractor that
# silently defaults on those is not a fair control.
ASSIST = (
    r"wheelchair|wheel chair|mobility|assistance|assisted|disabled|crutch|walker|stretcher",
    r"silla de ruedas|asistencia|movilidad",
    r"fauteuil roulant|assistance|mobilité",
    r"rollstuhl|hilfe|mobilität",
    r"cadeira de rodas|assistência",
    r"車椅子|介助|サポート",
    r"व्हीलचेयर|सहायता",
    r"كرسي متحرك|مساعدة",
)
BAGS = (
    r"checked bag|hold bag|luggage|suitcase|suitcases|baggage|bags in the hold|cases",
    r"maleta|equipaje|facturad",
    r"valise|bagage|soute",
    r"koffer|gepäck|aufgegeben",
    r"mala|bagagem|despachad",
    r"スーツケース|預け|荷物",
    r"सूटकेस|सामान",
    r"حقيبة|أمتعة",
)
CABIN_ONLY = r"carry[- ]on|hand luggage|cabin bag|only a backpack|no checked|nothing in the hold"
CRITICAL = (
    r"next few hours|within hours|couple of hours|tonight|this evening|right now|immediately",
    r"en las próximas horas|esta noche|ahora mismo",
    r"dans quelques heures|ce soir|immédiatement",
    r"in den nächsten stunden|heute abend|sofort",
)
TOMORROW = r"tomorrow|by morning|mañana|demain|morgen|amanhã|明日|कल|غدا"
LATER = r"day after tomorrow|next week|no rush|not in a hurry|whenever|flexible|sin prisa|pas pressé"
STATUS = {
    "platinum": r"platinum|top tier|highest tier|1k|executive platinum|diamond",
    "gold": r"gold|premier|elite",
    "silver": r"silver|plus member",
}
LOYALTY_HINT = r"frequent flyer|loyalty|lounge|miles|status|member since|years with"
NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "dos": 2, "tres": 3, "cuatro": 4, "deux": 2, "trois": 3, "quatre": 4,
    "zwei": 2, "drei": 3, "vier": 4,
}
NEGATION = r"\b(no|not|without|don'?t|doesn'?t|didn'?t|sin|sans|kein|nicht)\b[^.!?]{0,30}"


def _any(text: str, patterns) -> bool:
    if isinstance(patterns, str):
        patterns = (patterns,)
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _negated(text: str, pattern: str) -> bool:
    """Crude but real: 'no checked bags' must not read as checked bags."""
    for match in re.finditer(NEGATION, text, re.IGNORECASE):
        window = text[match.start(): match.end() + 40]
        if re.search(pattern if isinstance(pattern, str) else "|".join(pattern),
                     window, re.IGNORECASE):
            return True
    return False


def party_size(text: str) -> int:
    """Count travellers from digits, number words and relationship nouns."""
    for match in re.finditer(r"(?:party|group|family) of (\d+)", text, re.IGNORECASE):
        return int(match.group(1))
    for match in re.finditer(r"\b(\d+)\s+(?:of us|people|passengers|adults|travellers)",
                             text, re.IGNORECASE):
        return int(match.group(1))
    for word, value in NUMBERS.items():
        if re.search(rf"\b{word}\s+of us\b", text, re.IGNORECASE):
            return value
    # Relationship nouns, plus the writer. Plurals count as two, since "my sons" is at
    # least two people and treating it as one is the difference between a pair and a
    # family — a bucket boundary, not a rounding error.
    singular = r"wife|husband|partner|son|daughter|mother|father|mum|mom|dad|" \
               r"colleague|friend|baby|toddler|grandmother|grandfather|sister|brother"
    plural = r"sons|daughters|kids|children|parents|colleagues|friends|grandparents|" \
             r"sisters|brothers|twins"
    companions = 0
    for match in re.finditer(rf"\b({plural})\b", text, re.IGNORECASE):
        companions += 2
    for match in re.finditer(rf"\b({singular})\b", text, re.IGNORECASE):
        companions += 1
    # "my two sons" — an explicit count overrides the plural default.
    for word, value in NUMBERS.items():
        if re.search(rf"\b{word}\s+({plural})\b", text, re.IGNORECASE):
            companions = companions - 2 + value
    for match in re.finditer(rf"\b(\d+)\s+({plural})\b", text, re.IGNORECASE):
        companions = companions - 2 + int(match.group(1))
    if companions:
        return min(companions + 1, 6)
    if re.search(r"\b(i am alone|travelling alone|by myself|on my own|solo)\b", text, re.IGNORECASE):
        return 1
    return 1


def extract(message_id: str, text: str) -> Extracted:
    """Best-effort structured situation, no model involved."""
    tier = "basic"
    for name, pattern in STATUS.items():
        if _any(text, pattern):
            tier = name
            break
    else:
        if _any(text, LOYALTY_HINT):
            tier = "silver"

    if _any(text, LATER):
        urgency = "flexible"
    elif _any(text, CRITICAL):
        urgency = "critical"
    elif _any(text, TOMORROW):
        urgency = "same_day"
    else:
        urgency = "urgent"

    size = party_size(text)
    party = "solo" if size <= 1 else "pair" if size == 2 else "family" if size <= 4 else "group"

    if _any(text, ASSIST) and not _negated(text, ASSIST):
        constraints = "assisted"
    elif _any(text, CABIN_ONLY) or _negated(text, BAGS):
        constraints = "unencumbered"
    elif _any(text, BAGS):
        constraints = "checked_bags"
    else:
        constraints = "unencumbered"

    return Extracted(
        message_id=message_id,
        projection=Projection(role="passenger", tier=tier, urgency=urgency,
                              party=party, constraints=constraints),
        # A keyword extractor has no calibrated notion of confidence, and inventing one
        # would flatter it. Reported as unknown rather than fabricated.
        confidence={k: 0.5 for k in ("tier", "urgency", "party", "constraints")},
        evidence={},
    )
