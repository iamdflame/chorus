"""Screening free text before it can become a shared thought.

Collapse creates a vulnerability class that does not exist in an uncollapsed fleet, and it
is worth stating precisely because the mechanism is the same one that makes the system
cheap:

    In a collapsed fleet one successful injection does not compromise one agent. It
    compromises every entity sharing that projection. A single malicious message landing
    in a populous cohort is served, from cache, to thousands. **Collapse amplifies
    injection by exactly the collapse ratio.**

That is not a reason to abandon collapse. It is a reason to be honest about where the
defence actually lives, and it is not here.

This module is the *first* layer and the weakest one. Pattern matching on natural language
is defeated by paraphrase, and any claim that a regex list stops prompt injection is a
claim that should not survive contact with an adversary. Its job is to catch the obvious,
cheaply, and to make the expensive cases visible.

The defence that actually holds is structural, and it is enforced elsewhere: extraction
returns *only* a typed `Projection` whose every field is drawn from a closed vocabulary, so
free text physically cannot reach the elicitation prompt. An injected instruction has
nowhere to go — there is no field it can occupy. The schema is the airlock, and
`tests/test_armor.py` fails if a single byte of traveller-controlled text can cross it.

False positives are measured, not assumed. `scripts/verify_armor.py` runs this screen over
the 2,000-message benign corpus and reports the rate, because a screen that blocks real
travellers has replaced one failure with a worse one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Patterns chosen for having no natural use in a traveller's message to an airline. Each
# is an attempt to address the *system* rather than describe a situation. Phrasings are
# included in the corpus languages, because an English-only screen on a multilingual
# intake is a screen with a documented bypass.
_INJECTION = [
    ("instruction_override", re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.!?]{0,40}\b"
        r"(previous|prior|earlier|above|all)\b[^.!?]{0,20}\b"
        r"(instruction|prompt|rule|direction|command)", re.I)),
    ("instruction_override", re.compile(
        r"\b(ignor(e|ez|a)|olvida|vergiss|dimentica|negeer|esque(ce|ça))\b"
        r"[^.!?]{0,40}\b(instruc|consigne|anweisung|istruzion|regra|regel)", re.I)),
    ("role_reassignment", re.compile(
        r"\b(you are now|from now on you|act as|pretend to be|your new role|"
        r"tu es maintenant|du bist jetzt|ahora eres)\b", re.I)),
    ("system_impersonation", re.compile(
        r"(^|\n)\s*(system|assistant|developer)\s*[:>\]]", re.I)),
    ("delimiter_break", re.compile(
        r"(```|</?(system|instruction|prompt)>|\[/?INST\]|<\|.*?\|>)", re.I)),
    ("exfiltration", re.compile(
        r"\b(reveal|print|repeat|show|output|dump)\b[^.!?]{0,30}\b"
        r"(system prompt|instructions|your prompt|api key|credential|token)", re.I)),
    ("policy_subversion", re.compile(
        r"\b(always|must)\b[^.!?]{0,30}\b(approve|grant|award|upgrade|refund)\b"
        r"[^.!?]{0,30}\b(every|all|any)\b", re.I)),
]

# Characters with no business in a typed message and a long history of being used to hide
# payloads from screens that read what a human sees.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")


@dataclass
class Verdict:
    """What the screen concluded, and why — never a bare boolean.

    An unexplained block is unactionable: the operator cannot tell a real attack from a
    false positive, so every verdict carries the category and the span that triggered it.
    """

    blocked: bool = False
    categories: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "categories": self.categories,
            "evidence": self.evidence,
        }


def normalise(text: str) -> str:
    """Strip the tricks that hide a payload from a screen but not from a model.

    Zero-width and bidirectional characters are removed and the text is NFKC-folded, so a
    payload spelled with fullwidth or combining forms is screened as what it is. Without
    this, the screen reads one string and the model reads another — which is the entire
    game.
    """
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))


def _variants(text: str) -> tuple[str, ...]:
    """Every reading of the message an attacker might have intended.

    Deleting invisible characters is not enough on its own. An attacker who writes
    "Ignore\u200ball\u200bprevious\u200binstructions" is using them as word separators, so
    deletion yields one long token and a word-boundary pattern sails past it. Substituting
    a space defeats that, while deletion still defeats the opposite trick of hiding a
    zero-width character *inside* a word. Both readings are screened, because the model
    will see whichever one the tokeniser produces and the screen does not get to choose.
    """
    folded = unicodedata.normalize("NFKC", text)
    return tuple({folded, _INVISIBLE.sub("", folded), _INVISIBLE.sub(" ", folded)})


def screen(text: str) -> Verdict:
    """Screen one inbound message. Conservative by construction.

    Only patterns that address the system are matched. A traveller writing "ignore my last
    email, I meant Tuesday" is describing their situation, not instructing the fleet, and
    blocking them would replace one failure mode with a worse one.
    """
    verdict = Verdict()
    if normalise(text) != text:
        verdict.categories.append("hidden_characters")
        verdict.evidence.append("message contained invisible or bidirectional characters")
    for reading in _variants(text):
        for name, pattern in _INJECTION:
            found = pattern.search(reading)
            if found:
                if name not in verdict.categories:
                    verdict.categories.append(name)
                    verdict.evidence.append(found.group(0)[:120])
    verdict.blocked = bool(
        [c for c in verdict.categories if c != "hidden_characters"]
    )
    return verdict


def amplification(cohort_size: int) -> int:
    """How many entities one poisoned thought would reach.

    Trivial arithmetic, named because the point is easy to miss: the blast radius of an
    injection in a collapsed fleet is the cohort it landed in, and the cohort is exactly
    what the system built to save money.
    """
    return max(cohort_size, 0)
