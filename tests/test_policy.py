"""The policy table is the artifact an auditor would read, and the ledger is the number a
CFO would act on. Both have failure modes that look like success, so those are what these
tests aim at."""

from __future__ import annotations

import asyncio
import math

import pytest

from kernel.clock import FIXED
from policy.compare import agreement as agreement_fn, agrees, disagreeing_fields
from policy.ledger import NecessityLedger
from policy.shadow import ShadowReport, sampled, shadow_sample
from policy.table import LATTICE_CEILING, PolicyRow, PolicyTable, Provenance, distill
from swarm.runtime import CohortTrace

ANSWER = {
    "max_wait_hours": 6, "accept_downgrade": True, "accept_split_party": False,
    "accept_nearby_airport": True, "needs_hotel": False, "urgency_score": 70,
}


def table_of(*keys: str) -> PolicyTable:
    return distill(
        [CohortTrace(k, dict(ANSWER), f"eff-{k}", 10, True) for k in keys],
        clock=FIXED, model="gemini-3.5-flash",
    )


class TestDistillation:
    def test_a_cohort_without_an_answer_contributes_no_row(self) -> None:
        """Inventing a row for a situation the fleet failed on would look identical to a
        real one and serve traffic forever."""
        table = distill(
            [CohortTrace("a", dict(ANSWER), "eff-a", 5, True),
             CohortTrace("b", None, None, 3, False)],
            clock=FIXED, model="m",
        )
        assert table.populated == 1
        assert table.lookup("b") is None

    def test_every_row_carries_the_call_that_produced_it(self) -> None:
        row = table_of("x").lookup("x")
        assert row is not None
        assert row.provenance.effect_id == "eff-x"
        assert row.provenance.model == "gemini-3.5-flash"
        assert row.provenance.derived_at == FIXED.now().isoformat()

    def test_derivation_time_comes_from_the_clock_not_the_wall(self) -> None:
        shifted = distill(
            [CohortTrace("a", dict(ANSWER), "e", 1, True)],
            clock=FIXED.shifted(days=10), model="m",
        )
        assert shifted.lookup("a").provenance.derived_at != (
            table_of("a").lookup("a").provenance.derived_at
        )


class TestVersioning:
    def test_identical_content_versions_identically(self) -> None:
        assert table_of("a", "b").version == table_of("b", "a").version

    def test_a_changed_answer_changes_the_version(self) -> None:
        one = table_of("a")
        two = table_of("a")
        two.rows["a"].answer = {**ANSWER, "urgency_score": 5}
        assert one.version != two.version

    def test_an_invalidated_row_leaves_the_version(self) -> None:
        """A table that has dropped a row must not claim to be the table that had it."""
        table = table_of("a", "b")
        before = table.version
        table.invalidate("a")
        assert table.version != before

    def test_ceiling_is_the_stated_lattice(self) -> None:
        assert LATTICE_CEILING == 2304
        assert table_of("a").ceiling == 2304


class TestServing:
    def test_an_invalidated_row_is_never_served_again(self) -> None:
        """Drift detection is worthless if the row it flagged keeps being served."""
        table = table_of("a")
        table.invalidate("a")
        assert table.lookup("a") is None
        assert table.populated == 0

    def test_an_unsampled_row_has_no_trust_rather_than_full_trust(self) -> None:
        row = table_of("a").lookup("a")
        assert math.isnan(row.trust)

    def test_confirmation_raises_trust(self) -> None:
        table = table_of("a")
        table.confirm("a")
        assert table.lookup("a").trust == 1.0

    def test_round_trips_through_serialisation(self) -> None:
        table = table_of("a", "b")
        table.confirm("a")
        again = PolicyTable.from_dict(table.to_dict())
        assert again.version == table.version
        assert again.lookup("a").confirmations == 1
        assert again.lookup("a").provenance.effect_id == "eff-a"


class TestSampling:
    def test_the_slice_is_reproducible(self) -> None:
        """An auditor asking why a row was never sampled deserves better than 'chance'."""
        keys = [f"k{i}" for i in range(500)]
        first = [k for k in keys if sampled(k, rate=0.1, salt="s")]
        second = [k for k in keys if sampled(k, rate=0.1, salt="s")]
        assert first == second and first

    def test_rate_is_approximately_honoured(self) -> None:
        keys = [f"k{i}" for i in range(20_000)]
        hit = sum(1 for k in keys if sampled(k, rate=0.02, salt="chorus"))
        assert 0.015 < hit / len(keys) < 0.025

    def test_zero_samples_nothing_and_one_samples_everything(self) -> None:
        keys = [f"k{i}" for i in range(200)]
        assert not any(sampled(k, rate=0.0, salt="s") for k in keys)
        assert all(sampled(k, rate=1.0, salt="s") for k in keys)

    def test_a_different_salt_selects_a_different_slice(self) -> None:
        keys = [f"k{i}" for i in range(2000)]
        a = {k for k in keys if sampled(k, rate=0.1, salt="a")}
        b = {k for k in keys if sampled(k, rate=0.1, salt="b")}
        assert a != b


class TestDrift:
    def test_agreement_confirms_and_disagreement_invalidates(self) -> None:
        table = table_of(*[f"k{i}" for i in range(200)])

        async def ask(key: str):
            # Every second sampled row has moved.
            if int(key[1:]) % 2:
                return {**ANSWER, "urgency_score": 5, "needs_hotel": True}, 0.001
            return dict(ANSWER), 0.001

        report = asyncio.run(shadow_sample(table, list(table.rows), ask=ask, rate=1.0))
        assert report.sampled == 200
        assert report.confirmed + report.drifted == 200
        assert report.drifted > 0
        assert all(table.lookup(e.key) is None for e in report.events)

    def test_a_drift_event_names_the_fields_that_moved(self) -> None:
        table = table_of("a")

        async def ask(key: str):
            return {**ANSWER, "needs_hotel": True}, 0.0

        report = asyncio.run(shadow_sample(table, ["a"], ask=ask, rate=1.0))
        assert report.events[0].fields == ["needs_hotel"]

    def test_a_failed_sample_never_counts_as_agreement(self) -> None:
        """An error that silently confirmed a row would make the safety mechanism a
        rubber stamp."""
        table = table_of("a")

        async def ask(key: str):
            return None, 0.0

        report = asyncio.run(shadow_sample(table, ["a"], ask=ask, rate=1.0))
        assert report.failed == 1 and report.confirmed == 0
        assert table.lookup("a") is not None

    def test_drift_rate_is_not_a_number_when_nothing_was_sampled(self) -> None:
        assert math.isnan(ShadowReport().drift_rate)


class TestLedger:
    def test_necessity_is_the_disagreement_rate_not_the_miss_rate(self) -> None:
        """Cache warmth flatters the system and answers a question nobody asked."""
        led = NecessityLedger(
            served_from_table=9_900, served_from_model=100, model_cost_usd=1.0,
            shadow=ShadowReport(sampled=200, confirmed=180, drifted=20),
        )
        assert led.necessity == pytest.approx(0.10)
        assert led.table_share == pytest.approx(0.99)

    def test_unmeasured_necessity_is_never_reported_as_zero(self) -> None:
        led = NecessityLedger(served_from_table=100, served_from_model=1)
        assert math.isnan(led.necessity)
        assert "not measured" in led.render()
        assert "This is not 0%" in led.render()

    def test_the_projection_is_labelled_as_one(self) -> None:
        led = NecessityLedger(
            served_from_table=1_000, served_from_model=10, model_cost_usd=0.10,
            shadow=ShadowReport(sampled=10, confirmed=10),
        )
        assert "← projected" in led.render()

    def test_projected_cost_exceeds_actual_when_the_table_serves_most_traffic(self) -> None:
        led = NecessityLedger(
            served_from_table=10_000, served_from_model=100, model_cost_usd=1.0,
            shadow=ShadowReport(sampled=0),
        )
        assert led.projected_naive_cost() > led.total_cost() * 50

    def test_no_traffic_projects_no_cost_rather_than_dividing_by_zero(self) -> None:
        assert NecessityLedger().projected_naive_cost() == 0.0
        NecessityLedger().render()


class TestComparisonIsShared:
    def test_the_bench_uses_the_same_definition_as_drift_detection(self) -> None:
        """Two numbers claiming to measure the same agreement must not drift apart."""
        import bench.fidelity as fid

        assert fid.agreement is agreement_fn
        assert agrees({"urgency_score": 50}, {"urgency_score": 55})
        assert disagreeing_fields({"needs_hotel": True}, {"needs_hotel": False}) == [
            "needs_hotel"
        ]
