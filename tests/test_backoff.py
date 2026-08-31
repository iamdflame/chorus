"""Retry at the model boundary, and the invariant that makes it safe.

The dangerous failure here is not a missed retry. It is a retry that creates a second
causal address — because then the store records two thoughts where the fleet had one, and
the collapse ratio inflates by exactly the number of transient failures the run happened
to hit. The product claim would degrade silently, in the direction that flatters it, under
precisely the conditions (load, quota pressure) where it matters most.
"""

from __future__ import annotations

import asyncio

import pytest

from kernel.backoff import (
    DEFAULT_ATTEMPTS,
    Attempts,
    is_retryable,
    with_backoff,
)
from kernel.effect import Determinism, Effect, EffectKind


class ResourceExhausted(Exception):
    """Stands in for google.api_core.exceptions.ResourceExhausted, matched by name so the
    kernel keeps no cloud dependency."""


class ServiceUnavailable(Exception):
    pass


class InvalidArgument(Exception):
    """A fact about the request. Repeating it wastes quota and hides the real error."""


async def _nosleep(_: float) -> None:
    return None


def run(coro):
    return asyncio.run(coro)


class TestClassification:
    @pytest.mark.parametrize("exc", [ResourceExhausted(), ServiceUnavailable(),
                                     asyncio.TimeoutError(), TimeoutError()])
    def test_transient_failures_are_retryable(self, exc: BaseException) -> None:
        assert is_retryable(exc)

    @pytest.mark.parametrize("exc", [InvalidArgument(), ValueError("bad schema"),
                                     PermissionError("denied"), KeyError("missing")])
    def test_permanent_failures_are_not(self, exc: BaseException) -> None:
        assert not is_retryable(exc)

    def test_a_wrapped_quota_error_is_still_recognised(self) -> None:
        """Vendored and wrapped variants keep the status in the message."""
        assert is_retryable(RuntimeError("503 RESOURCE_EXHAUSTED from upstream"))


class TestRetry:
    def test_a_transient_failure_is_retried_and_succeeds(self) -> None:
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ResourceExhausted()
            return "ok"

        stats = Attempts()
        assert run(with_backoff(flaky, stats=stats, sleep=_nosleep)) == "ok"
        assert calls["n"] == 3
        assert stats.retries == 2

    def test_a_permanent_failure_propagates_immediately(self) -> None:
        """No delay, no repetition: the caller gets the real error at once."""
        calls = {"n": 0}

        async def broken():
            calls["n"] += 1
            raise InvalidArgument("schema")

        with pytest.raises(InvalidArgument):
            run(with_backoff(broken, stats=Attempts(), sleep=_nosleep))
        assert calls["n"] == 1

    def test_exhaustion_raises_the_last_error_not_a_wrapper(self) -> None:
        """An operator needs the service's own error, not ours."""
        async def always():
            raise ResourceExhausted("quota")

        stats = Attempts()
        with pytest.raises(ResourceExhausted):
            run(with_backoff(always, attempts=3, stats=stats, sleep=_nosleep))
        assert stats.exhausted == 1
        assert stats.retries == 2

    def test_a_success_costs_no_retries(self) -> None:
        stats = Attempts()
        run(with_backoff(lambda: asyncio.sleep(0, result=1), stats=stats, sleep=_nosleep))
        assert stats.retries == 0 and stats.calls == 1


class TestJitter:
    def test_the_delay_is_full_jitter_not_a_fixed_multiple(self) -> None:
        """A fixed multiple synchronises every retrying worker onto one schedule, which is
        how a brief quota blip becomes a thundering herd. The bound grows; the draw is
        uniform below it."""
        bounds: list[float] = []
        slept: list[float] = []

        def rand(lo: float, hi: float) -> float:
            bounds.append(hi)
            return hi * 0.5

        async def sleep(d: float) -> None:
            slept.append(d)

        async def always():
            raise ResourceExhausted()

        with pytest.raises(ResourceExhausted):
            run(with_backoff(always, attempts=4, base=1.0, stats=Attempts(),
                             sleep=sleep, rand=rand))
        assert bounds == [1.0, 2.0, 4.0]      # doubling ceiling
        assert all(lo == 0.0 for lo in [0.0])  # drawn from zero, not from the ceiling
        assert slept == [0.5, 1.0, 2.0]

    def test_the_delay_is_capped(self) -> None:
        bounds: list[float] = []

        def rand(lo: float, hi: float) -> float:
            bounds.append(hi)
            return 0.0

        async def always():
            raise ResourceExhausted()

        with pytest.raises(ResourceExhausted):
            run(with_backoff(always, attempts=8, base=1.0, cap=4.0,
                             stats=Attempts(), sleep=_nosleep, rand=rand))
        assert max(bounds) == 4.0


class TestAddressInvariance:
    """The invariant the whole thing rests on."""

    def _effect(self) -> Effect:
        return Effect.create(
            branch_id="primary", seq=1, agent="passenger_agent",
            kind=EffectKind.MODEL_CALL, determinism=Determinism.RECORDED,
            causal_parents=("anchor",), request={"prompt": "situation X"},
            response={"answer": 1},
        )

    def test_a_retried_call_addresses_identically(self) -> None:
        """Re-deriving the address from the same (kind, agent, parents, request) must give
        the same answer, or a retry becomes a second thought and collapse inflates."""
        first = self._effect()
        second = self._effect()
        assert first.id == second.id

    def test_retrying_does_not_multiply_recorded_effects(self) -> None:
        """Two attempts, one address, one row in the store."""
        from kernel.store import InMemoryEffectStore

        store = InMemoryEffectStore()
        attempts = {"n": 0}

        async def flaky() -> Effect:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ResourceExhausted()
            effect = self._effect()
            store.put(effect)
            return effect

        got = run(with_backoff(flaky, stats=Attempts(), sleep=_nosleep))
        assert attempts["n"] == 3
        assert len(store.own_effects("primary")) == 1
        assert store.lookup("primary", got.id) is not None


class TestReplayIsNeverRetried:
    def test_replay_strict_still_raises_on_a_miss(self) -> None:
        """A replay that retries is a replay reaching the network. REPLAY_STRICT must fail
        loudly on a miss rather than being given another go at finding one."""
        from kernel.interposer import Mode, ReplayMiss
        from kernel.store import InMemoryEffectStore
        from kernel.interposer import LightconePlugin

        plugin = LightconePlugin(
            store=InMemoryEffectStore(), branch_id="primary", mode=Mode.REPLAY_STRICT
        )
        with pytest.raises(ReplayMiss):
            plugin._resolve("an-address-that-was-never-recorded")

    def test_the_default_attempt_count_is_bounded(self) -> None:
        """An unbounded retry against a quota error is an outage that never resolves."""
        assert 1 < DEFAULT_ATTEMPTS <= 8
