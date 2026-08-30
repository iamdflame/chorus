"""The fidelity harness reports a number nobody can check by eye, so its own
statistics are tested before they are trusted."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from bench.fidelity import (
    FullRecord,
    agreement,
    sample_populated,
    scale_seats,
    spearman,
    _ranks,
)
from kernel.clock import FIXED
from swarm.canonical import bind, project_passenger
from swarm.runtime import _check_projector
from swarm.scenario import build_scenario


class TestRanks:
    def test_ties_average(self) -> None:
        assert _ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_all_tied(self) -> None:
        assert _ranks([7.0, 7.0, 7.0]) == [2.0, 2.0, 2.0]


class TestSpearman:
    def test_perfect_agreement(self) -> None:
        assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)

    def test_perfect_disagreement(self) -> None:
        assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)

    def test_offset_does_not_reduce_rank_agreement(self) -> None:
        """The distinction the harness exists to draw.

        A systematically higher arm is not a disagreeing arm: the allocator sorts and
        never reads magnitude, so a constant offset must score as perfect agreement while
        the bias term reports the shift.
        """
        assert spearman([10, 20, 30], [60, 70, 80]) == pytest.approx(1.0)

    def test_zero_variance_is_not_a_number(self) -> None:
        """A constant arm has no ordering to agree with — nan, never a silent 0.0."""
        assert spearman([5, 5, 5], [1, 2, 3]) != spearman([5, 5, 5], [1, 2, 3])


class TestAgreement:
    def test_within_tolerance_agrees(self) -> None:
        a = {"urgency_score": 50, "max_wait_hours": 6}
        b = {"urgency_score": 58, "max_wait_hours": 7}
        got = agreement(a, b)
        assert got["urgency_score"] and got["max_wait_hours"]

    def test_outside_tolerance_disagrees(self) -> None:
        got = agreement({"urgency_score": 10}, {"urgency_score": 90})
        assert not got["urgency_score"]

    def test_unparseable_counts_as_disagreement(self) -> None:
        """A malformed answer must never be scored as agreement by accident."""
        got = agreement({"urgency_score": "very high"}, {"urgency_score": 50})
        assert not got["urgency_score"]

    def test_missing_boolean_is_falsey_not_crashing(self) -> None:
        assert agreement({}, {"needs_hotel": False})["needs_hotel"]


class TestSampling:
    def test_every_sampled_cohort_is_actually_populated(self) -> None:
        passengers = [asdict(p) for p in build_scenario(passengers=20_000).passengers]
        projector = bind(project_passenger, FIXED)
        sample, members = sample_populated(
            passengers, projector, cohorts=10, per_cohort=8
        )
        assert len(members) == 10
        assert len(sample) == 80
        for ids in members.values():
            assert len(ids) == 8

    def test_members_of_a_cohort_share_a_projection(self) -> None:
        """If they did not, the shared thought under test would not be shared."""
        passengers = [asdict(p) for p in build_scenario(passengers=20_000).passengers]
        projector = bind(project_passenger, FIXED)
        sample, members = sample_populated(
            passengers, projector, cohorts=6, per_cohort=5
        )
        by_id = {p["id"]: p for p in sample}
        for key, ids in members.items():
            assert {projector(by_id[i]).key() for i in ids} == {key}

    def test_impossible_request_returns_empty_rather_than_lying(self) -> None:
        passengers = [asdict(p) for p in build_scenario(passengers=50).passengers]
        sample, members = sample_populated(
            passengers, bind(project_passenger, FIXED), cohorts=5, per_cohort=999
        )
        assert sample == [] and members == {}


class TestScarcity:
    def test_seats_scale_with_the_sample(self) -> None:
        flights = [asdict(f) for f in build_scenario(passengers=20_000).flights]
        full = sum(f["seats_free"] for f in flights)
        scaled = scale_seats(flights, sampled=600, population=20_000)
        assert sum(f["seats_free"] for f in scaled) < full * 0.05

    def test_no_flight_is_scaled_out_of_existence(self) -> None:
        """A flight with zero seats is a flight the allocator cannot use at all."""
        flights = [asdict(f) for f in build_scenario(passengers=20_000).flights]
        scaled = scale_seats(flights, sampled=10, population=20_000)
        assert all(f["seats_free"] >= 1 for f in scaled)


class TestUncollapsedArm:
    def test_every_traveller_addresses_uniquely(self) -> None:
        """B5 must never coalesce, or it stops being the uncollapsed control."""
        passengers = [asdict(p) for p in build_scenario(passengers=200).passengers]
        keys = {FullRecord(p).key() for p in passengers}
        assert len(keys) == len(passengers)

    def test_prompt_carries_what_the_lattice_buckets_away(self) -> None:
        passenger = asdict(build_scenario(passengers=50).passengers[0])
        prompt = FullRecord(passenger).to_prompt()
        assert str(passenger["party_size"]) in prompt
        assert passenger["destination"] in prompt
        assert str(passenger["checked_bags"]) in prompt
        assert passenger["id"] in prompt


class TestProjectorGuard:
    def test_unbound_projector_is_rejected_before_the_run(self) -> None:
        with pytest.raises(TypeError, match="bind"):
            _check_projector(project_passenger)

    def test_bound_projector_is_accepted(self) -> None:
        _check_projector(bind(project_passenger, FIXED))

    def test_a_lambda_of_one_argument_is_accepted(self) -> None:
        _check_projector(lambda entity: FullRecord(entity))
