"""Background runs: the workload that should not be a request-response.

A fifty-minute, real-money sweep dying with a dropped connection is the failure this
exists to prevent. These pin the contract without running a swarm.
"""

from __future__ import annotations

import asyncio

import pytest

from api.runs import Run, Runner, RunStore


def store() -> RunStore:
    return RunStore(project=None)  # in-memory; durability is asserted separately


class TestRunRecord:
    def test_percent_is_derived_not_stored(self) -> None:
        run = Run(id="a", agents=200, concurrency=4, progress=50)
        assert run.to_dict()["percent"] == 25.0

    def test_zero_agents_does_not_divide_by_zero(self) -> None:
        assert Run(id="a", agents=0, concurrency=1).to_dict()["percent"] == 0.0

    def test_a_run_says_whether_it_is_durable(self) -> None:
        """Claiming durability an instance does not have is worse than not having it."""
        s = store()
        run = Run(id="a", agents=10, concurrency=1)
        s.put(run)
        assert run.durable is False
        assert s.durable is False


class TestQueue:
    def test_enqueue_returns_immediately_with_an_id(self) -> None:
        runner = Runner(store())
        run = runner.enqueue(20_000, 48)
        assert run.state == "queued"
        assert run.agents == 20_000
        assert len(run.id) == 12

    def test_a_run_is_retrievable_by_id(self) -> None:
        s = store()
        runner = Runner(s)
        run = runner.enqueue(10, 2)
        assert s.get(run.id) is not None
        assert s.get("nope") is None

    def test_execution_moves_through_the_states(self) -> None:
        s = store()
        runner = Runner(s)
        run = runner.enqueue(3, 1)
        seen: list[str] = []

        async def execute(r, emit):
            seen.append(r.state)
            emit({"event": "progress", "done": 3})

        async def drive():
            runner.start(execute)
            for _ in range(60):
                await asyncio.sleep(0.01)
                if s.get(run.id).state in ("done", "failed"):
                    return

        asyncio.run(drive())
        assert seen == ["running"]
        assert s.get(run.id).state == "done"
        assert s.get(run.id).finished_at is not None

    def test_a_failing_run_records_the_failure_rather_than_vanishing(self) -> None:
        s = store()
        runner = Runner(s)
        run = runner.enqueue(3, 1)

        async def execute(r, emit):
            raise RuntimeError("vertex exploded")

        async def drive():
            runner.start(execute)
            for _ in range(60):
                await asyncio.sleep(0.01)
                if s.get(run.id).state in ("done", "failed"):
                    return

        asyncio.run(drive())
        got = s.get(run.id)
        assert got.state == "failed"
        assert "vertex exploded" in got.error


class TestReplayForLateSubscribers:
    def test_a_late_subscriber_sees_the_whole_run(self) -> None:
        """A client connecting at agent 12,000 should not be shown a run that appears to
        start there."""
        s = store()
        runner = Runner(s)
        run = runner.enqueue(3, 1)

        async def execute(r, emit):
            for i in range(3):
                emit({"event": "progress", "done": i + 1})

        async def drive():
            runner.start(execute)
            for _ in range(60):
                await asyncio.sleep(0.01)
                if s.get(run.id).state in ("done", "failed"):
                    return

        asyncio.run(drive())
        events = runner.events(run.id)
        # Three progress events plus the terminal frame.
        assert [e.get("done") for e in events if e["event"] == "progress"] == [1, 2, 3]
        assert any(e["event"] == "run_finished" for e in events)

    def test_events_for_an_unknown_run_are_empty_not_an_error(self) -> None:
        assert Runner(store()).events("nope") == []
