"""Proofs for branch-isolated, time-travelling state.

These are safety properties. If branch isolation leaks, a counterfactual mutates
production; if time travel is wrong, a counterfactual answers a question about a world
that never existed.
"""

from __future__ import annotations

import pytest

from kernel.branch import PRIMARY, Branch
from world.shadow import ShadowWorld


@pytest.fixture
def world():
    w = ShadowWorld()
    for seq, amount in enumerate([100, 200, 300], start=1):
        w.write(branch_id=PRIMARY, collection="ledger", key="acct-1",
                value={"balance": amount}, seq=seq * 10)
    return w


def fork(world: ShadowWorld, at_seq: int, name: str = "what-if") -> Branch:
    branch = Branch.fork(parent=Branch.primary(), name=name, at_seq=at_seq)
    world.register_branch(branch)
    return branch


# -- time travel --------------------------------------------------------------

def test_read_reconstructs_any_past_instant(world):
    read = lambda at: world.read(branch_id=PRIMARY, collection="ledger", key="acct-1", at_seq=at)
    assert read(None) == {"balance": 300}
    assert read(25) == {"balance": 200}
    assert read(10) == {"balance": 100}
    assert read(5) is None, "before the first write the key did not exist"


def test_history_retains_every_version(world):
    assert [v.value["balance"] for v in world.history(collection="ledger", key="acct-1")] == [100, 200, 300]


# -- branch isolation ---------------------------------------------------------

def test_branch_writes_never_reach_production(world):
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-1",
                value={"balance": 999}, seq=40)

    assert world.read(branch_id=branch.id, collection="ledger", key="acct-1") == {"balance": 999}
    assert world.read(branch_id=PRIMARY, collection="ledger", key="acct-1") == {"balance": 300}, (
        "a counterfactual must not be able to mutate production"
    )


def test_branch_cannot_see_its_parents_future(world):
    """The core correctness property of a counterfactual."""
    branch = fork(world, at_seq=15)
    world.write(branch_id=PRIMARY, collection="ledger", key="acct-1",
                value={"balance": 4242}, seq=99)

    assert world.read(branch_id=branch.id, collection="ledger", key="acct-1") == {"balance": 100}, (
        "a branch forked at seq 15 must see the world as of seq 15"
    )


def test_branch_inherits_parent_state_before_the_fork(world):
    branch = fork(world, at_seq=20)
    assert world.read(branch_id=branch.id, collection="ledger", key="acct-1") == {"balance": 200}


def test_nested_branches_accumulate_the_minimum_cutoff(world):
    """A grandchild cannot see more of its grandparent than its parent could."""
    child = fork(world, at_seq=30, name="child")
    grandchild = Branch.fork(parent=child, name="grandchild", at_seq=10)
    world.register_branch(grandchild)

    assert world.read(branch_id=grandchild.id, collection="ledger", key="acct-1") == {"balance": 100}


def test_deletion_on_a_branch_shadows_the_inherited_value(world):
    branch = fork(world, at_seq=30)
    world.delete(branch_id=branch.id, collection="ledger", key="acct-1", seq=40)

    assert world.read(branch_id=branch.id, collection="ledger", key="acct-1") is None
    assert world.read(branch_id=PRIMARY, collection="ledger", key="acct-1") == {"balance": 300}


def test_scan_respects_branch_and_time(world):
    world.write(branch_id=PRIMARY, collection="ledger", key="acct-2", value={"balance": 7}, seq=50)
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-3", value={"balance": 5}, seq=60)

    on_branch = world.scan(branch_id=branch.id, collection="ledger")
    assert set(on_branch) == {"acct-1", "acct-3"}, "acct-2 was created after the fork"
    assert set(world.scan(branch_id=PRIMARY, collection="ledger")) == {"acct-1", "acct-2"}


# -- merge --------------------------------------------------------------------

def test_merge_applies_the_overlay_to_production(world):
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-1",
                value={"balance": 42}, seq=40)

    result = world.merge(branch_id=branch.id, into=PRIMARY, seq=100)
    assert result["merged"] is True and result["applied"] == 1
    assert world.read(branch_id=PRIMARY, collection="ledger", key="acct-1") == {"balance": 42}


def test_merge_refuses_when_production_moved_on(world):
    """Detected, not silently clobbered."""
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-1",
                value={"balance": 42}, seq=40)
    world.write(branch_id=PRIMARY, collection="ledger", key="acct-1",
                value={"balance": 555}, seq=50)

    result = world.merge(branch_id=branch.id, into=PRIMARY, seq=100)
    assert result["merged"] is False
    assert result["conflicts"][0]["ours"] == {"balance": 42}
    assert result["conflicts"][0]["theirs"] == {"balance": 555}
    assert result["conflicts"][0]["base"] == {"balance": 300}
    assert world.read(branch_id=PRIMARY, collection="ledger", key="acct-1") == {"balance": 555}, (
        "a refused merge must leave production untouched"
    )


def test_forced_merge_overrides_a_conflict(world):
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-1", value={"balance": 42}, seq=40)
    world.write(branch_id=PRIMARY, collection="ledger", key="acct-1", value={"balance": 555}, seq=50)

    result = world.merge(branch_id=branch.id, into=PRIMARY, seq=100, force=True)
    assert result["merged"] is True and result["forced"] is True
    assert world.read(branch_id=PRIMARY, collection="ledger", key="acct-1") == {"balance": 42}


def test_diff_reports_value_level_differences(world):
    branch = fork(world, at_seq=30)
    world.write(branch_id=branch.id, collection="ledger", key="acct-1", value={"balance": 42}, seq=40)

    d = world.diff(left=PRIMARY, right=branch.id)
    assert d["ledger/acct-1"] == {"left": {"balance": 300}, "right": {"balance": 42}}
