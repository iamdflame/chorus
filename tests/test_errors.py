"""Typed failures at the kernel's invariant boundaries.

The point is not that errors have nicer names. It is that a caller can tell three different
problems apart and respond to each — rebuild a snapshot, refuse a fork, fail the run —
where `except ValueError` could only give up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kernel.branch import PRIMARY, Branch
from kernel.errors import (
    BranchError,
    BranchExists,
    KernelError,
    ReplayError,
    SnapshotCorrupt,
    SnapshotError,
    SnapshotVersionMismatch,
    UnknownBranch,
)
from kernel.store import InMemoryEffectStore


class TestHierarchy:
    def test_every_kernel_error_is_catchable_as_one(self) -> None:
        """For the top-level handler deciding between failing a request and failing a
        process — the one place that granularity is right."""
        for cls in (BranchExists, UnknownBranch, SnapshotCorrupt,
                    SnapshotVersionMismatch):
            assert issubclass(cls, KernelError)

    def test_families_are_distinguishable(self) -> None:
        assert issubclass(BranchExists, BranchError)
        assert issubclass(SnapshotCorrupt, SnapshotError)
        assert not issubclass(BranchExists, SnapshotError)

    def test_replay_miss_joined_the_hierarchy(self) -> None:
        """It was a bare RuntimeError, so a caller could not catch replay failures without
        catching everything."""
        from kernel.interposer import ReplayMiss

        assert issubclass(ReplayMiss, ReplayError)
        assert issubclass(ReplayMiss, KernelError)

    def test_context_travels_with_the_error(self) -> None:
        """An error an operator cannot act on is an error that wasted their time."""
        err = SnapshotCorrupt("unreadable", path="data/history.json",
                              reason="JSONDecodeError")
        assert err.to_dict()["path"] == "data/history.json"
        assert err.to_dict()["error"] == "SnapshotCorrupt"


class TestBranchInvariants:
    def test_claiming_a_branch_id_twice_raises(self) -> None:
        """Silently reusing it would merge two timelines into one."""
        store = InMemoryEffectStore()
        store.create_branch(Branch(id="what-if", name="what-if",
                                   parent_id=PRIMARY, fork_at_seq=1))
        with pytest.raises(BranchExists) as raised:
            store.create_branch(Branch(id="what-if", name="again",
                                       parent_id=PRIMARY, fork_at_seq=1))
        assert raised.value.context["branch_id"] == "what-if"

    def test_forking_from_an_unknown_parent_raises(self) -> None:
        store = InMemoryEffectStore()
        with pytest.raises(UnknownBranch) as raised:
            store.create_branch(Branch(id="orphan", name="orphan",
                                       parent_id="nowhere", fork_at_seq=1))
        assert raised.value.context["parent_id"] == "nowhere"


class TestSnapshotFailsClosed:
    def test_an_unreadable_snapshot_raises_rather_than_loading_what_parsed(
        self, tmp_path: Path
    ) -> None:
        """A half-loaded effect log is worse than none: the store keeps answering
        lookups, and the answers are wrong for exactly the addresses it dropped."""
        from kernel.snapshot import load

        bad = tmp_path / "broken.json"
        bad.write_text('{"schema": "v1", "effects": {')
        with pytest.raises(SnapshotCorrupt):
            load(bad)

    def test_a_missing_snapshot_raises_the_same_typed_error(self, tmp_path: Path) -> None:
        from kernel.snapshot import load

        with pytest.raises(SnapshotCorrupt):
            load(tmp_path / "absent.json")

    def test_a_future_schema_is_named_as_such(self, tmp_path: Path) -> None:
        """Distinct from corruption: the file is fine, this build is old."""
        from kernel.snapshot import load

        future = tmp_path / "future.json"
        future.write_text(json.dumps({"schema": "v99", "effects": {}}))
        with pytest.raises(SnapshotVersionMismatch) as raised:
            load(future)
        assert raised.value.context["found"] == "v99"

    def test_the_two_snapshot_failures_are_separately_catchable(
        self, tmp_path: Path
    ) -> None:
        """Rebuild on corruption; upgrade on a version mismatch. Different responses."""
        assert not issubclass(SnapshotVersionMismatch, SnapshotCorrupt)
        assert not issubclass(SnapshotCorrupt, SnapshotVersionMismatch)
