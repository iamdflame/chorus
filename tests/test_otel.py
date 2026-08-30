"""The trace is a projection of the causal DAG, so it inherits the DAG's guarantees.

These check that it actually does — in particular that a replay traces identically, which
is a property normal telemetry cannot offer and is the reason this mapping is worth having.
"""

from __future__ import annotations

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from kernel.effect import Determinism, Effect, EffectKind
from obs.otel import export, summarise, to_span


class Collector(SpanExporter):
    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):  # noqa: A003 - SpanExporter interface
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def call(seq: int, parents: tuple[str, ...] = (), **kw) -> Effect:
    return Effect.create(
        branch_id=kw.pop("branch_id", "primary"), seq=seq, agent="passenger",
        kind=EffectKind.MODEL_CALL, determinism=Determinism.RECORDED,
        causal_parents=parents, request={"q": seq}, response={"a": seq}, **kw,
    )


class TestIdentity:
    def test_a_replay_traces_identically(self) -> None:
        """Two exports of the same effect must produce the same span id, or a replayed
        run would look like new work in every trace viewer."""
        effect = call(1)
        assert to_span(effect).context.span_id == to_span(effect).context.span_id

    def test_different_effects_get_different_spans(self) -> None:
        assert to_span(call(1)).context.span_id != to_span(call(2)).context.span_id

    def test_a_branch_is_its_own_trace(self) -> None:
        """A fork is a separate timeline and should read as one."""
        here = to_span(call(1)).context.trace_id
        there = to_span(call(1, branch_id="what-if")).context.trace_id
        assert here != there


class TestCausality:
    def test_every_causal_parent_becomes_a_link(self) -> None:
        """A tree would drop edges or invent them. Agent causality is a DAG."""
        a, b = call(1), call(2)
        joined = call(3, parents=(a.id, b.id))
        span = to_span(joined)
        assert len(span.links) == 2

    def test_the_first_parent_is_also_the_span_parent(self) -> None:
        """So ordinary viewers that read only parents still render something useful."""
        a = call(1)
        span = to_span(call(2, parents=(a.id,)))
        assert span.parent is not None
        assert span.parent.span_id == to_span(a).context.span_id

    def test_a_root_effect_has_no_parent(self) -> None:
        assert to_span(call(1)).parent is None


class TestReplayRendering:
    def test_a_replayed_effect_takes_no_time(self) -> None:
        """Seventeen thousand free replays should collapse into a column of instants
        beside the few calls that cost something."""
        span = to_span(call(1, replayed=True, wall_ms=6_500))
        assert span.end_time == span.start_time

    def test_a_real_call_keeps_its_duration(self) -> None:
        span = to_span(call(1, wall_ms=6_500))
        assert (span.end_time - span.start_time) == 6_500 * 1_000_000

    def test_replay_is_marked_as_an_event(self) -> None:
        assert [e.name for e in to_span(call(1, replayed=True)).events] == ["replayed"]

    def test_a_quarantined_action_says_why(self) -> None:
        span = to_span(call(1, quarantined=True))
        names = [e.name for e in span.events]
        assert "quarantined" in names
        event = next(e for e in span.events if e.name == "quarantined")
        assert "not executed" in event.attributes["chorus.reason"]


class TestAttributes:
    def test_cost_and_tokens_reach_the_span(self) -> None:
        span = to_span(call(1, tokens_in=120, tokens_out=30, cost_usd=0.0009))
        assert span.attributes["gen_ai.usage.input_tokens"] == 120
        assert span.attributes["chorus.cost_usd"] == 0.0009

    def test_the_branch_is_queryable(self) -> None:
        span = to_span(call(1, branch_id="what-if"))
        assert span.attributes["chorus.branch"] == "what-if"


class TestExport:
    def test_a_run_exports_every_effect(self) -> None:
        collector = Collector()
        effects = [call(i) for i in range(1, 6)]
        assert export(effects, collector) == 5
        assert len(collector.spans) == 5

    def test_an_empty_run_exports_nothing_rather_than_failing(self) -> None:
        collector = Collector()
        assert export([], collector) == 0

    def test_the_summary_charges_only_for_work_actually_done(self) -> None:
        """A replayed effect carries the cost it avoided, so summing naively would bill
        the user for the saving."""
        effects = [call(1, cost_usd=0.001), call(2, replayed=True, cost_usd=0.001)]
        got = summarise(effects)
        assert got["executed"] == 1 and got["replayed"] == 1
        assert got["cost_usd"] == 0.001


class TestManifestExpansion:
    """A trace built from the store alone shows one span per stored effect, which is true
    about storage and misleading about work. The manifest restores the fan-out."""

    def test_repeat_visits_become_replay_spans(self) -> None:
        from obs.otel import expand_manifest

        a, b = call(1), call(2)
        manifest = [a.id, b.id, a.id, a.id, b.id]
        got = expand_manifest([a, b], manifest, branch_id="primary")
        assert len(got) == 5
        assert [e.replayed for e in got] == [False, False, True, True, True]

    def test_a_replay_costs_nothing_and_takes_no_time(self) -> None:
        from obs.otel import expand_manifest

        a = call(1, tokens_in=100, tokens_out=20, wall_ms=6_500)
        got = expand_manifest([a], [a.id, a.id], branch_id="primary")
        replay = got[1]
        assert replay.wall_ms == 0.0
        assert replay.tokens_in == 0 and replay.tokens_out == 0

    def test_replays_do_not_collide_with_each_other(self) -> None:
        """Reusing the original's id would make every replay the same span."""
        from obs.otel import expand_manifest

        a = call(1)
        got = expand_manifest([a], [a.id] * 50, branch_id="primary")
        assert len({to_span(e).context.span_id for e in got}) == 50

    def test_a_replay_links_to_the_thought_it_consumed(self) -> None:
        from obs.otel import expand_manifest

        a = call(1)
        replay = expand_manifest([a], [a.id, a.id], branch_id="primary")[1]
        assert replay.causal_parents == (a.id,)

    def test_the_summary_still_charges_once(self) -> None:
        """20,000 invocations of 1,964 thoughts cost what the 1,964 cost."""
        from obs.otel import expand_manifest

        a = call(1, cost_usd=0.001)
        got = expand_manifest([a], [a.id] * 1_000, branch_id="primary")
        assert summarise(got)["cost_usd"] == 0.001
        assert summarise(got)["replayed"] == 999

    def test_an_address_not_in_the_store_is_skipped_not_invented(self) -> None:
        from obs.otel import expand_manifest

        a = call(1)
        got = expand_manifest([a], [a.id, "deadbeef" * 4], branch_id="primary")
        assert len(got) == 1
