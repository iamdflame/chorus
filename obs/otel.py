"""The causal DAG is already a distributed trace. This is the mapping, not an instrumentation.

Most agent systems bolt tracing on: a decorator here, a context manager there, and a trace
that shows what was called without showing what caused what. This project recorded causality
first because replay required it, which means the trace is a projection of data that already
exists rather than a parallel bookkeeping system that can disagree with it.

    Effect                  Span
    causal_parents          Span links — a true DAG, not a single parent chain
    branch_id               resource/span attribute, so timelines separate in the UI
    replayed                span event, zero duration: the visual signature of free work
    quarantined             span event: an action recorded but deliberately not taken
    cost_usd, tokens        span attributes

Two decisions worth stating.

**Links, not parents.** OpenTelemetry's parent-child relation is a tree and agent causality
is not. An effect caused by three upstream effects has three parents, and forcing that into
a tree would either drop edges or invent them. Links carry the real shape; the first parent
is also set as the span parent so ordinary trace viewers still render something useful.

**Identifiers derive from content.** A span id is the first 8 bytes of the effect address,
and the trace id is derived from the branch. So replaying a run produces a byte-identical
trace, and two machines exporting the same run cannot disagree about it — the same property
that makes replay sound makes the telemetry reproducible, which is not normally a thing
telemetry can claim.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import Link, SpanContext, SpanKind, TraceFlags
from opentelemetry.trace.status import Status, StatusCode

from kernel.effect import Effect, EffectKind, digest

SERVICE_NAME = "chorus"

# Nanoseconds. Effects record wall_ms; a replayed effect records none, which is the point.
_MS = 1_000_000


def _span_id(effect_id: str) -> int:
    """8 bytes of the effect address. Deterministic, so replays trace identically."""
    return int(effect_id[:16], 16) or 1


def _trace_id(branch_id: str) -> int:
    """One trace per branch: a fork is a separate timeline and should read as one."""
    return int(digest("trace", branch_id)[:32], 16) or 1


def _context(effect: Effect) -> SpanContext:
    return SpanContext(
        trace_id=_trace_id(effect.branch_id),
        span_id=_span_id(effect.id),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )


def _parent_context(effect: Effect) -> SpanContext | None:
    if not effect.causal_parents:
        return None
    return SpanContext(
        trace_id=_trace_id(effect.branch_id),
        span_id=_span_id(effect.causal_parents[0]),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )


def _links(effect: Effect) -> list[Link]:
    """Every causal parent, including the first.

    The first is also the span parent, so it appears twice — deliberately. A viewer that
    reads only parents sees a tree; one that reads links sees the graph. Dropping it from
    the links to avoid the duplication would make the link set an incomplete answer to
    "what caused this", which is the one question it exists to answer.
    """
    return [
        Link(
            SpanContext(
                trace_id=_trace_id(effect.branch_id),
                span_id=_span_id(parent),
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            ),
            attributes={"chorus.causal_parent": parent},
        )
        for parent in effect.causal_parents
    ]


def _attributes(effect: Effect) -> dict[str, Any]:
    return {
        "chorus.effect_id": effect.id,
        "chorus.content_id": effect.content_id,
        "chorus.branch": effect.branch_id,
        "chorus.seq": effect.seq,
        "chorus.agent": effect.agent,
        "chorus.kind": effect.kind.value,
        "chorus.determinism": effect.determinism.value,
        "chorus.replayed": effect.replayed,
        "chorus.quarantined": effect.quarantined,
        "chorus.causal_parents": len(effect.causal_parents),
        "gen_ai.usage.input_tokens": effect.tokens_in,
        "gen_ai.usage.output_tokens": effect.tokens_out,
        "chorus.cost_usd": effect.cost_usd,
    }


def _events(effect: Effect) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if effect.replayed:
        events.append({
            "name": "replayed",
            "attributes": {
                "chorus.replayed": True,
                "chorus.cost_avoided_usd": effect.cost_usd,
            },
        })
    if effect.quarantined:
        events.append({
            "name": "quarantined",
            "attributes": {
                "chorus.quarantined": True,
                "chorus.reason": "irreversible action off primary; recorded, not executed",
            },
        })
    return events


def to_span(effect: Effect, *, resource: Resource | None = None) -> ReadableSpan:
    """One effect as one span.

    A replayed effect gets zero duration rather than its original wall time. That is the
    honest rendering and it is also the most legible one: in a trace viewer, seventeen
    thousand free replays collapse into a column of instants beside the few calls that
    actually cost something.
    """
    start = int(effect.wall_ts * 1e9)
    duration = 0 if effect.replayed else int(effect.wall_ms * _MS)
    from opentelemetry.sdk.trace import Event

    return ReadableSpan(
        name=f"{effect.agent}:{effect.kind.value}",
        context=_context(effect),
        parent=_parent_context(effect),
        resource=resource or Resource.create({"service.name": SERVICE_NAME}),
        attributes=_attributes(effect),
        events=tuple(
            Event(name=e["name"], attributes=e["attributes"], timestamp=start)
            for e in _events(effect)
        ),
        links=tuple(_links(effect)),
        kind=SpanKind.CLIENT if effect.kind is EffectKind.MODEL_CALL else SpanKind.INTERNAL,
        status=Status(StatusCode.OK),
        start_time=start,
        end_time=start + duration,
    )


def export(
    effects: Iterable[Effect], exporter: SpanExporter, *, resource: Resource | None = None
) -> int:
    """Export a run. Returns the number of spans written."""
    spans: Sequence[ReadableSpan] = [to_span(e, resource=resource) for e in effects]
    if spans:
        exporter.export(spans)
    return len(spans)


def summarise(effects: Iterable[Effect]) -> dict[str, Any]:
    """What the trace would show, without needing a backend to look at it."""
    total = replayed = quarantined = 0
    cost = 0.0
    branches: set[str] = set()
    for effect in effects:
        total += 1
        replayed += effect.replayed
        quarantined += effect.quarantined
        cost += 0.0 if effect.replayed else effect.cost_usd
        branches.add(effect.branch_id)
    return {
        "spans": total,
        "traces": len(branches),
        "replayed": replayed,
        "quarantined": quarantined,
        "executed": total - replayed,
        "cost_usd": round(cost, 4),
    }


def expand_manifest(
    effects: Iterable[Effect], manifest: Sequence[str], *, branch_id: str
) -> list[Effect]:
    """Every operation the run performed, not just every effect it stored.

    The store keeps one effect per address — that economy is the entire product. So a
    trace built from the store alone shows 1,966 spans for a run of 20,000 agents, which
    is true about storage and misleading about work.

    The manifest records the ordered addresses each invocation visited, so the full
    sequence can be reconstructed exactly: the first visit to an address is the call that
    was executed, and every later visit is an agent being handed that recorded answer.
    Replays are emitted as distinct zero-duration effects linked to the thought they
    consumed, which is what makes collapse legible in a trace viewer — a wall of instants
    beside a handful of real calls.

    Nothing here is synthesised. Both the durations and the ordering come from the record;
    only the fan-out, which the store deliberately does not duplicate, is reconstructed.
    """
    by_id = {effect.id: effect for effect in effects}
    seen: dict[str, int] = {}
    out: list[Effect] = []
    for address in manifest:
        original = by_id.get(address)
        if original is None:
            continue
        count = seen.get(address, 0)
        seen[address] = count + 1
        if count == 0:
            out.append(original)
            continue
        # A replay: same answer, its own moment, no duration and no cost.
        out.append(
            Effect(
                id=digest("replay", address, str(count)),
                content_id=original.content_id,
                branch_id=branch_id,
                seq=original.seq,
                agent=original.agent,
                kind=original.kind,
                determinism=original.determinism,
                causal_parents=(address,),
                request_hash=original.request_hash,
                request=original.request,
                response=original.response,
                replayed=True,
                tokens_in=0,
                tokens_out=0,
                cost_usd=original.cost_usd,
                wall_ms=0.0,
                wall_ts=original.wall_ts,
            )
        )
    return out
