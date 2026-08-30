"""Memory is the feature most likely to quietly destroy this product.

Per-traveller history in a prompt makes every prompt unique, every address unique, and
collapse 1x — the system would remember everyone and reason about no one twice. These tests
exist to fail loudly if that ever starts happening.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from kernel.clock import FIXED
from memory.profile import Observation, Profile, apply, remembered_fields
from memory.store import InMemoryProfileStore, MemoryBankProfileStore, learn
from swarm.canonical import Projection, bind, collapse, project_passenger
from swarm.scenario import build_scenario


def projection(**kw) -> Projection:
    base = dict(role="passenger", tier="basic", urgency="urgent", party="pair",
                constraints="checked_bags")
    base.update(kw)
    return Projection(**base)


class TestMemoryFeedsTheProjection:
    def test_a_remembered_need_changes_the_cohort(self) -> None:
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        before = projection()
        after = apply(before, profile, clock=FIXED)
        assert before.key() != after.key()
        assert after.constraints == "assisted"

    def test_it_does_not_change_the_prompt_for_that_cohort(self) -> None:
        """The whole design. Memory decides which bucket you are in; it never alters what
        the bucket thinks, or the thought would stop being shareable."""
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        remembered = apply(projection(), profile, clock=FIXED)
        plain = projection(constraints="assisted")
        assert remembered.to_prompt() == plain.to_prompt()
        assert remembered.key() == plain.key()

    def test_no_identity_reaches_the_prompt(self) -> None:
        profile = Profile("PAX-90210")
        profile.observe("needs_assistance", True, clock=FIXED)
        prompt = apply(projection(), profile, clock=FIXED).to_prompt()
        assert "PAX" not in prompt and "90210" not in prompt

    def test_memory_only_raises_a_constraint_never_lowers_one(self) -> None:
        """Forgetting on silence is the dangerous direction: it is the one case where
        being wrong strands someone at a gate they cannot reach."""
        profile = Profile("PAX-1")  # remembers nothing
        already = projection(constraints="assisted")
        assert apply(already, profile, clock=FIXED).constraints == "assisted"

    def test_no_profile_is_a_no_op(self) -> None:
        assert apply(projection(), None, clock=FIXED).key() == projection().key()


class TestCollapseSurvives:
    def test_a_population_with_profiles_still_collapses(self) -> None:
        """The test that matters. If memory made prompts unique, this ratio would be 1."""
        passengers = [asdict(p) for p in build_scenario(passengers=4_000).passengers]
        projector = bind(project_passenger, FIXED)

        store = InMemoryProfileStore()
        for i, person in enumerate(passengers):
            if i % 3 == 0:  # a third of travellers are returning
                profile = Profile(person["id"])
                profile.observe("needs_assistance", True, clock=FIXED)
                store.put(profile)

        remembered = [
            apply(projector(p), store.get(p["id"]), clock=FIXED) for p in passengers
        ]
        distinct = len({p.key() for p in remembered})
        assert distinct < 2_304, "memory must not exceed the lattice"
        assert len(passengers) / distinct > 2.0, "collapse collapsed"

    def test_memory_cannot_invent_a_cohort_outside_the_lattice(self) -> None:
        """An unbounded key would let memory mint cells, and each new cell is a model call
        somebody pays for."""
        passengers = [asdict(p) for p in build_scenario(passengers=2_000).passengers]
        projector = bind(project_passenger, FIXED)
        plain = {projector(p).key() for p in passengers}
        profile = Profile("x")
        profile.observe("needs_assistance", True, clock=FIXED)
        profile.observe("hotel_entitled", True, clock=FIXED)
        with_memory = {
            apply(projector(p), profile, clock=FIXED).key() for p in passengers
        }
        # Every remembered key is a well-formed lattice cell of the same shape.
        assert all(k.count("|") == next(iter(plain)).count("|") for k in with_memory)


class TestTimeTravel:
    def test_a_session_six_weeks_later_still_remembers(self) -> None:
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        later = FIXED.shifted(days=42)
        assert profile.live("needs_assistance", clock=later) is True
        assert apply(projection(), profile, clock=later).constraints == "assisted"

    def test_an_assistance_need_expires_after_its_ttl(self) -> None:
        """A wheelchair needed after surgery in March is not needed forever, and a system
        that remembers permanently mislabels people for years."""
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        stale = FIXED.shifted(days=200)
        assert profile.live("needs_assistance", clock=stale) is None
        assert apply(projection(), profile, clock=stale).constraints == "checked_bags"

    def test_preferences_outlive_assistance_needs(self) -> None:
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        profile.observe("hotel_entitled", True, clock=FIXED)
        at = FIXED.shifted(days=200)
        assert profile.live("needs_assistance", clock=at) is None
        assert profile.live("hotel_entitled", clock=at) is True

    def test_a_read_before_the_write_returns_nothing(self) -> None:
        """Time travel is real here: a counterfactual asked at an earlier instant must not
        see a fact recorded after it."""
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        assert profile.live("needs_assistance", clock=FIXED.shifted(days=-10)) is None

    def test_wall_clock_is_never_consulted(self) -> None:
        profile = Profile("PAX-1")
        profile.observe("needs_assistance", True, clock=FIXED)
        assert profile.observations["needs_assistance"].observed_at == (
            FIXED.now().isoformat()
        )


class TestLearning:
    def test_a_disruption_updates_the_profile(self) -> None:
        profile = learn(Profile("PAX-1"),
                        {"needs_assistance": True, "has_hotel_entitlement": False},
                        clock=FIXED)
        assert profile.disruptions_seen == 1
        assert profile.live("needs_assistance", clock=FIXED) is True
        assert profile.live("hotel_entitled", clock=FIXED) is None

    def test_repeated_disruptions_accumulate(self) -> None:
        profile = Profile("PAX-1")
        for _ in range(3):
            learn(profile, {"needs_assistance": True}, clock=FIXED)
        assert profile.disruptions_seen == 3


class TestAuditability:
    def test_a_profile_says_where_each_fact_came_from(self) -> None:
        """A memory whose influence on a decision cannot be explained to the person it
        describes is not one an airline can defend."""
        profile = learn(Profile("PAX-1"), {"needs_assistance": True}, clock=FIXED)
        got = profile.observations["needs_assistance"]
        assert got.source == "booking" and got.observed_at

    def test_only_declared_fields_can_be_recalled(self) -> None:
        assert "needs_assistance" in remembered_fields()
        assert "name" not in remembered_fields()
        assert "destination" not in remembered_fields()

    def test_round_trips_through_serialisation(self) -> None:
        profile = learn(Profile("PAX-1"), {"needs_assistance": True}, clock=FIXED)
        again = Profile.from_dict(profile.to_dict())
        assert again.live("needs_assistance", clock=FIXED) is True
        assert again.disruptions_seen == 1


class TestStore:
    def test_batched_reads_return_only_what_exists(self) -> None:
        store = InMemoryProfileStore()
        store.put(Profile("A"))
        got = store.many(["A", "B", "C"])
        assert set(got) == {"A"}

    def test_memory_bank_refuses_to_silently_forget(self) -> None:
        """A memory service that forgets everything while reporting success is worse than
        no memory service."""
        with pytest.raises(ValueError, match="silently forget"):
            MemoryBankProfileStore(None, InMemoryProfileStore())
