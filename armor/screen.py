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

    `flagged` is deliberately not `blocked`. A layer can be confident enough to warrant a
    human look without being confident enough to refuse a traveller, and collapsing those
    two into one boolean is what turns a good detector into a bad gate.
    """

    blocked: bool = False
    flagged: bool = False
    categories: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "flagged": self.flagged,
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


# ── Layer 0: Model Armor ─────────────────────────────────────────────────────
#
# The pattern screen above is honest about being weak. This is the managed guardrail in
# front of it: Google Cloud Model Armor's `sanitizeUserPrompt`, which does semantic
# prompt-injection and jailbreak detection rather than substring matching, and therefore
# catches the paraphrases that defeat a regex by construction.
#
# It returns the same `Verdict`, so nothing downstream changes. The layering is
# deliberate and the order matters:
#
#   layer 0   Model Armor        semantic, managed, and the one that can be evaded least
#   layer 1   the pattern screen fallback when layer 0 is unreachable, and a second
#                                opinion when it is not
#   layer 2   the typed airlock  the one that actually holds — an injected instruction
#                                has no field to live in, so it cannot reach a shared
#                                prompt even when both screens miss
#
# Two failure modes, treated differently on purpose. **Unreachable** means the network or
# the API is down, and blocking every traveller because a screening service is having a
# bad afternoon would be an outage of our own making — so it falls back to patterns and
# says so in the verdict. **Unintelligible** means the service answered with something we
# cannot interpret, and there is no safe reading of that: it fails closed.

import json as _json
import os as _os
import urllib.error as _urlerror
import urllib.request as _urlrequest

MODEL_ARMOR_TEMPLATE = "chorus-intake"


@dataclass(frozen=True, slots=True)
class ArmorConfig:
    """Where the managed guardrail lives. Absent a project, layer 0 is simply skipped."""

    project: str
    location: str = "us-central1"
    template: str = MODEL_ARMOR_TEMPLATE
    timeout: float = 8.0

    @classmethod
    def from_env(cls) -> "ArmorConfig | None":
        project = _os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            return None
        return cls(
            project=project,
            location=_os.environ.get("MODEL_ARMOR_LOCATION", "us-central1"),
            template=_os.environ.get("MODEL_ARMOR_TEMPLATE", MODEL_ARMOR_TEMPLATE),
        )

    @property
    def endpoint(self) -> str:
        return (
            f"https://modelarmor.{self.location}.rep.googleapis.com/v1/"
            f"projects/{self.project}/locations/{self.location}/"
            f"templates/{self.template}:sanitizeUserPrompt"
        )


class Unreachable(Exception):
    """Layer 0 could not be consulted. The caller falls back rather than failing."""


def _access_token() -> str:
    """Application Default Credentials, resolved lazily.

    Imported inside the function so the pattern screen — and therefore CI, and therefore
    `scripts/verify_armor.py` offline — never needs a cloud library present.
    """
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def screen_managed(text: str, config: ArmorConfig, *, token: str | None = None) -> Verdict:
    """Screen one message with Model Armor. Raises `Unreachable`; never returns None.

    A `MATCH_FOUND` on any filter blocks. An answer we cannot parse blocks — there is no
    safe reading of an unintelligible verdict from a security service, and treating it as
    "probably fine" would turn the strongest layer into the weakest.
    """
    body = _json.dumps({"user_prompt_data": {"text": text}}).encode("utf-8")
    request = _urlrequest.Request(
        config.endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token or _access_token()}",
            "Content-Type": "application/json",
            "x-goog-user-project": config.project,
        },
    )
    try:
        with _urlrequest.urlopen(request, timeout=config.timeout) as response:
            payload = _json.loads(response.read())
    except _urlerror.HTTPError as exc:
        # 4xx and 5xx alike: the guardrail did not render a judgement, so we fall back.
        raise Unreachable(f"HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 - transport, DNS, timeout, credentials
        raise Unreachable(f"{type(exc).__name__}") from exc

    result = payload.get("sanitizationResult")
    if not isinstance(result, dict):
        return Verdict(
            blocked=True,
            categories=["unparseable_verdict"],
            evidence=["Model Armor answered in a shape this code cannot read"],
        )

    state = result.get("filterMatchState")
    if state == "NO_MATCH_FOUND":
        return Verdict(blocked=False)
    if state != "MATCH_FOUND":
        return Verdict(
            blocked=True,
            categories=["unparseable_verdict"],
            evidence=[f"unknown filterMatchState {state!r}"],
        )

    # Name the filters that fired, so an operator can tell a real attack from a false
    # positive without opening a console.
    categories: list[str] = []
    for name, detail in (result.get("filterResults") or {}).items():
        if not isinstance(detail, dict):
            continue
        for inner in detail.values():
            if isinstance(inner, dict) and inner.get("matchState") == "MATCH_FOUND":
                categories.append(f"model_armor:{name}")
    return Verdict(
        blocked=True,
        categories=categories or ["model_armor:match"],
        evidence=["blocked by Model Armor sanitizeUserPrompt"],
    )


def screen_layered(
    text: str, config: ArmorConfig | None = None, *, token: str | None = None
) -> Verdict:
    """Layer 0 then layer 1, returning one `Verdict`.

    With no config, or when layer 0 is unreachable, this is exactly the pattern screen —
    which is why nothing downstream has to know whether the managed guardrail was
    available. The verdict records which layers actually ran, because a block whose origin
    is unknown is a block nobody can act on.
    """
    patterns = screen(text)

    if config is None:
        return patterns

    try:
        managed = screen_managed(text, config, token=token)
    except Unreachable as exc:
        # Degraded, not failed. Blocking every traveller because a screening service is
        # having a bad afternoon would be an outage of our own making.
        return Verdict(
            blocked=patterns.blocked,
            categories=[*patterns.categories, f"layer0_unreachable:{exc}"],
            evidence=patterns.evidence,
        )

    if managed.blocked:
        # An unintelligible answer from a security service has no safe reading, so it is
        # the one Model Armor result that refuses the traveller outright.
        if "unparseable_verdict" in managed.categories:
            return Verdict(
                blocked=True,
                categories=[*managed.categories, *patterns.categories],
                evidence=[*managed.evidence, *patterns.evidence],
            )

        # Otherwise a Model Armor match FLAGS rather than blocks, and this is a decision
        # made from measurement rather than taste.
        #
        # Screened against the same 2,000-message benign corpus, the managed guardrail
        # blocks 3.35% of genuine travellers where the pattern screen blocks 0.00% — and
        # the ones it blocks are not randomly distributed. They are the distressed:
        # "everything is melting down here at the gate", "please help us everything is
        # collapsing". Semantic jailbreak detection reads panic as manipulation.
        #
        # In an irregular-operations system those are precisely the people who most need
        # to get through, so blocking on this signal would deny help to the travellers the
        # product exists for. The match is kept, routed to review, and the structural
        # airlock — which cannot be evaded by paraphrase because there is no field for an
        # instruction to occupy — does the actual containment.
        return Verdict(
            blocked=patterns.blocked,
            flagged=True,
            categories=[*managed.categories, *patterns.categories],
            evidence=[*managed.evidence, *patterns.evidence],
        )
    # Layer 0 passed it; layer 1 still gets a say. Two screens disagreeing is information,
    # not a contradiction — and the cheap one occasionally catches what the clever one
    # waves through.
    return Verdict(
        blocked=patterns.blocked,
        categories=[*patterns.categories, "model_armor:clean"],
        evidence=patterns.evidence,
    )
