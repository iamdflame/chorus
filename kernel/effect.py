"""Content-addressed effect records — the atomic unit of agent execution.

An Effect is one interaction between an agent and the world: a model call, a tool call,
a state read or write, a delegation. Effects are content-addressed over their *entire
causal history*:

    id = H(kind, agent, [parent ids], request_hash)

Because each parent id is itself a hash of that parent's own history, a change anywhere
upstream changes every downstream id. Cache invalidation is therefore free: a perturbed
run misses the effect store at exactly the points where it genuinely diverges, and hits
everywhere else. This is the content-addressed derivation trick Nix and Bazel use for
builds, applied to agent execution.

Two distinct identities matter, and conflating them breaks replay:

    id          the *address* — request side only. Replay looks up by this.
    content_id  the *value*   — H(id, response). DAG integrity is checked with this.

A replay hit means "an identical request was issued at an identical causal position",
which is precisely the condition under which reusing the recorded response is sound.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

# Digest size in bytes. 16 bytes = 128 bits = 32 hex chars: collision-safe far beyond
# the scale of any effect log, and short enough to read in a UI.
_DIGEST_SIZE = 16

# stdlib blake2b, deliberately. blake3's Python wheels ship SIMD builds that fault on
# pre-AVX2 hardware, and hashing sits in the hot path of every single effect.
_HASHER = hashlib.blake2b


class EffectKind(str, Enum):
    """What kind of boundary crossing this effect represents."""

    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    AGENT_ENTER = "agent_enter"
    AGENT_EXIT = "agent_exit"
    DELEGATION = "delegation"
    STATE_READ = "state_read"
    STATE_WRITE = "state_write"
    USER_MESSAGE = "user_message"
    # A tool call the gateway refused. Recorded rather than logged, so a refusal is
    # content-addressed, replayable and diffable across branches like anything else.
    GATEWAY_DENIED = "gateway_denied"
    CLOCK = "clock"
    RANDOM = "random"


class Determinism(str, Enum):
    """How an effect behaves under replay.

    PURE
        A deterministic function of its inputs. Safe to re-execute at any time; the
        recorded response is an optimisation, not a requirement.
    RECORDED
        Non-deterministic but side-effect free with respect to the outside world: model
        calls, clock reads, randomness, reads of external state. Replayable *only* from
        the record. This is the class that makes replay free.
    EXTERNAL_REVERSIBLE
        Mutates the world, but a compensating effect exists that restores the prior
        state (create a record -> delete it). Undoable.
    EXTERNAL_IRREVERSIBLE
        Mutates the world with no compensator that truly restores it: sending an email,
        issuing a refund, charging a card. These are quarantined on non-primary branches
        rather than executed, and recorded as counterfactual "would have" effects.
    """

    PURE = "pure"
    RECORDED = "recorded"
    EXTERNAL_REVERSIBLE = "external_reversible"
    EXTERNAL_IRREVERSIBLE = "external_irreversible"

    @property
    def mutates_world(self) -> bool:
        return self in (Determinism.EXTERNAL_REVERSIBLE, Determinism.EXTERNAL_IRREVERSIBLE)


def canonical_json(obj: Any) -> bytes:
    """Serialise to a byte string that is stable across processes and machines.

    Determinism of the *address* depends entirely on this being canonical, so it uses
    stdlib json with sorted keys and no incidental whitespace. Non-JSON values are
    coerced via repr rather than raising: an unserialisable value in a request must
    still hash to something stable, and a hash mismatch degrades to a cache miss (a
    real call) rather than a wrong answer.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    ).encode("utf-8")


def digest(*parts: bytes | str) -> str:
    """Hash an ordered sequence of parts, length-prefixed to prevent ambiguity.

    Length prefixing matters: without it, ("ab", "c") and ("a", "bc") would hash
    identically, letting an attacker or an accident forge a causal position.
    """
    h = _HASHER(digest_size=_DIGEST_SIZE)
    for part in parts:
        raw = part.encode("utf-8") if isinstance(part, str) else part
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    return h.hexdigest()


def hash_payload(payload: Any) -> str:
    """Content hash of an arbitrary request or response payload."""
    return digest(canonical_json(payload))


@dataclass(frozen=True, slots=True)
class Effect:
    """One recorded crossing of the agent/world boundary.

    Immutable by construction. `id` and `content_id` are derived, never assigned by
    callers — see `Effect.create`.
    """

    id: str
    content_id: str
    branch_id: str
    seq: int
    agent: str
    kind: EffectKind
    determinism: Determinism
    causal_parents: tuple[str, ...]
    request_hash: str
    request: dict[str, Any]
    response: dict[str, Any] | None
    # Set when this effect was served from the store instead of really executing.
    replayed: bool = False
    # Set when an irreversible effect was intercepted on a non-primary branch and
    # recorded as a counterfactual instead of being executed against the world.
    quarantined: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    wall_ms: float = 0.0
    wall_ts: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- construction ----------------------------------------------------------

    @staticmethod
    def address(
        *,
        kind: EffectKind,
        agent: str,
        causal_parents: tuple[str, ...],
        request_hash: str,
    ) -> str:
        """Compute the replay address for a request at a causal position.

        This is the whole mechanism. Callers compute an address *before* executing, look
        it up, and execute only on a miss. Note that `determinism` and `branch_id` are
        deliberately excluded: the same request at the same causal position must address
        identically on every branch, or forked timelines could never reuse their parent's
        recorded work — which is exactly what makes forking cheap.
        """
        return digest(
            kind.value,
            agent,
            canonical_json(list(causal_parents)),
            request_hash,
        )

    @classmethod
    def create(
        cls,
        *,
        branch_id: str,
        seq: int,
        agent: str,
        kind: EffectKind,
        determinism: Determinism,
        causal_parents: tuple[str, ...],
        request: dict[str, Any],
        response: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Effect:
        """Build an effect, deriving both identities from its content."""
        request_hash = hash_payload(request)
        eid = cls.address(
            kind=kind,
            agent=agent,
            causal_parents=causal_parents,
            request_hash=request_hash,
        )
        return cls(
            id=eid,
            content_id=digest(eid, hash_payload(response)),
            branch_id=branch_id,
            seq=seq,
            agent=agent,
            kind=kind,
            determinism=determinism,
            causal_parents=tuple(causal_parents),
            request_hash=request_hash,
            request=request,
            response=response,
            **kwargs,
        )

    def with_response(self, response: dict[str, Any] | None, **kwargs: Any) -> Effect:
        """Return a copy carrying a response, with `content_id` re-derived.

        Used when an effect is opened before execution and closed after it. `id` is
        unchanged by construction, so the address stays stable across the call.
        """
        return replace(
            self,
            response=response,
            content_id=digest(self.id, hash_payload(response)),
            **kwargs,
        )

    def with_seq(self, seq: int) -> Effect:
        """Return a copy at a new sequence position.

        Safe by construction: `seq` participates in neither `id` nor `content_id`, so
        renumbering an effect at flush time cannot change its address or its integrity
        hash. Ordering is presentation; causality is the DAG.
        """
        return replace(self, seq=seq)

    # -- serialisation ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content_id": self.content_id,
            "branch_id": self.branch_id,
            "seq": self.seq,
            "agent": self.agent,
            "kind": self.kind.value,
            "determinism": self.determinism.value,
            "causal_parents": list(self.causal_parents),
            "request_hash": self.request_hash,
            "request": self.request,
            "response": self.response,
            "replayed": self.replayed,
            "quarantined": self.quarantined,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "wall_ms": self.wall_ms,
            "wall_ts": self.wall_ts,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Effect:
        return cls(
            id=d["id"],
            content_id=d["content_id"],
            branch_id=d["branch_id"],
            seq=d["seq"],
            agent=d["agent"],
            kind=EffectKind(d["kind"]),
            determinism=Determinism(d["determinism"]),
            causal_parents=tuple(d["causal_parents"]),
            request_hash=d["request_hash"],
            request=d["request"],
            response=d["response"],
            replayed=d.get("replayed", False),
            quarantined=d.get("quarantined", False),
            tokens_in=d.get("tokens_in", 0),
            tokens_out=d.get("tokens_out", 0),
            cost_usd=d.get("cost_usd", 0.0),
            wall_ms=d.get("wall_ms", 0.0),
            wall_ts=d.get("wall_ts", 0.0),
            meta=d.get("meta", {}),
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        flags = "".join(
            [
                "R" if self.replayed else "-",
                "Q" if self.quarantined else "-",
            ]
        )
        return (
            f"<Effect {self.id[:8]} {flags} seq={self.seq} {self.agent}:"
            f"{self.kind.value} parents={len(self.causal_parents)}>"
        )
