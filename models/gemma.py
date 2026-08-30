"""Gemma as an independent oracle — a second model family, not a cheaper one.

The plan for this integration was Gemma as a cheap triage classifier ahead of Gemini. That
premise does not survive contact with the model actually available. `gemma-4-26b-a4b-it` on
the Gemini API is a reasoning model whose thinking cannot be switched off — both
`thinking_budget` and `thinking_level` are rejected outright — and it spends 314 thought
tokens answering an eighteen-token prompt. Presenting it as a cost optimisation would be a
claim that fails the first time anyone measures it, which is the specific failure this
project keeps finding in other people's work.

So it is used for what it genuinely is: **a model from a different family, trained
differently, that can be asked the same question.** That fixes a real weakness in the
Necessity Ledger. Shadow sampling re-asks *the same model*, which detects the table going
stale but cannot detect the model being consistently wrong — ask Gemini twice about a cohort
it misreads and it agrees with itself, confidently, forever. Same-model agreement measures
drift. **Cross-family agreement measures something closer to correctness**, and a
disagreement between two independently trained models is a far stronger signal than a model
nodding at its own cached answer.

Two mechanical differences from the Gemini path, both load-bearing:

    no response schema   Gemma rejects `response_schema` and ignores `response_mime_type`,
                         so the JSON is fenced prose and has to be parsed defensively
    thought parts        the response carries `thought: true` parts before the answer;
                         reading `parts[0]` gets reasoning rather than a result

Both are handled here rather than at every call site, because getting either wrong produces
a parse failure that looks exactly like the model being bad at the task.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MODEL = "gemma-4-26b-a4b-it"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# Gemma returns JSON inside a markdown fence, sometimes with prose either side.
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_BARE = re.compile(r"(\{.*\})", re.S)


@dataclass
class GemmaReply:
    """One answer, with what it actually cost in tokens."""

    payload: dict[str, Any] | None
    prompt_tokens: int = 0
    answer_tokens: int = 0
    thought_tokens: int = 0
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.answer_tokens + self.thought_tokens


def answer_text(candidate: dict[str, Any]) -> str:
    """The answer, with the model's thinking discarded.

    Reading `parts[0]` would return reasoning about the task rather than the result, and
    that reasoning frequently contains a *draft* JSON object — so a naive parser does not
    fail loudly, it silently extracts an earlier, worse answer.
    """
    parts = candidate.get("content", {}).get("parts", [])
    visible = [p.get("text", "") for p in parts if not p.get("thought")]
    return "\n".join(visible) if visible else ""


def parse_json(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of fenced prose."""
    for pattern in (_FENCE, _BARE):
        found = pattern.search(text)
        if found:
            try:
                got = json.loads(found.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(got, dict):
                return got
    return None


def ask(prompt: str, *, api_key: str | None = None, timeout: float = 60.0) -> GemmaReply:
    """One Gemma call. Never raises — a failed oracle is a data point, not an outage."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        return GemmaReply(payload=None, error="GOOGLE_API_KEY is not set")

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        # No response_schema: Gemma rejects it. Temperature 0 for reproducibility, which
        # is the least this project can do given everything else is content-addressed.
        "generationConfig": {"temperature": 0, "maxOutputTokens": 3500},
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{ENDPOINT}/{MODEL}:generateContent?key={key}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            got = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return GemmaReply(payload=None, error=f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 - a failed oracle must not end the run
        return GemmaReply(payload=None, error=f"{type(exc).__name__}: {exc}")

    candidates = got.get("candidates") or []
    if not candidates:
        return GemmaReply(payload=None, error="no candidates")
    usage = got.get("usageMetadata", {})
    return GemmaReply(
        payload=parse_json(answer_text(candidates[0])),
        prompt_tokens=usage.get("promptTokenCount", 0),
        answer_tokens=usage.get("candidatesTokenCount", 0),
        thought_tokens=usage.get("thoughtsTokenCount", 0),
    )
