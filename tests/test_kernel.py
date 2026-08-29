"""Structural proofs for the causal kernel.

These run offline and prove the properties the rest of the system assumes:
addressing is stable, causality propagates through the hash, forking is O(1), and
lightcone queries return the right sets. If any of these fail, replay is unsound.
"""

from __future__ import annotations

import pytest

from kernel.branch import PRIMARY, Branch
from kernel.dag import CausalDAG
from kernel.effect import Determinism, Effect, EffectKind
from kernel.store import InMemoryEffectStore


def mk(agent: str, parents: tuple[str, ...], request: dict, response=None, seq: int = 0,
       branch: str = PRIMARY, kind: EffectKind = EffectKind.MODEL_CALL) -> Effect:
    return Effect.create(
        branch_id=branch, seq=seq, agent=agent, kind=kind,
        determinism=Determinism.RECORDED, causal_parents=parents,
        request=request, response=response,
    )


# -- addressing ---------------------------------------------------------------

def test_address_is_stable_across_identical_inputs():
    a = mk("triage", (), {"prompt": "hello"})
    b = mk("triage", (), {"prompt": "hello"})
    assert a.id == b.id, "identical request at identical causal position must address identically"


def test_address_is_insensitive_to_dict_ordering():
    a = mk("triage", (), {"x": 1, "y": 2})
    b = mk("triage", (), {"y": 2, "x": 1})
    assert a.id == b.id, "canonical serialisation must ignore key order"


@pytest.mark.parametrize("mutate", [
    lambda: mk("other", (), {"prompt": "hello"}),
    lambda: mk("triage", (), {"prompt": "goodbye"}),
    lambda: mk("triage", ("deadbeef",), {"prompt": "hello"}),
    lambda: mk("triage", (), {"prompt": "hello"}, kind=EffectKind.TOOL_CALL),
])
def test_address_changes_when_any_component_changes(mutate):
    base = mk("triage", (), {"prompt": "hello"})
    assert mutate().id != base.id


def test_response_does_not_affect_address_but_does_affect_content_id():
    """The core split. Replay looks up by address *before* it has a response;
    integrity checks compare content ids, which commit to the response."""
    a = mk("triage", (), {"prompt": "x"}, response={"answer": 1})
    b = mk("triage", (), {"prompt": "x"}, response={"answer": 2})
    assert a.id == b.id
    assert a.content_id != b.content_id


def test_causal_change_propagates_to_every_descendant():
    """The property that makes cache invalidation free."""
    root_a = mk("triage", (), {"n": 1})
    root_b = mk("triage", (), {"n": 2})          # perturbed root
    child_a = mk("policy", (root_a.id,), {"same": "request"})
    child_b = mk("policy", (root_b.id,), {"same": "request"})
    grand_a = mk("refund", (child_a.id,), {"same": "request"})
    grand_b = mk("refund", (child_b.id,), {"same": "request"})

    assert child_a.id != child_b.id, "a changed parent must change the child's address"
    assert grand_a.id != grand_b.id, "divergence must reach the whole subtree"


def test_sibling_branches_do_not_collide():
    """Two agents issuing the same request from different histories must not share a slot."""
    p1, p2 = mk("t", (), {"n": 1}), mk("t", (), {"n": 2})
    assert mk("policy", (p1.id,), {"q": "x"}).id != mk("policy", (p2.id,), {"q": "x"}).id


def test_with_seq_preserves_both_identities():
    e = mk("triage", (), {"a": 1}, response={"ok": True})
    assert e.with_seq(99).id == e.id
    assert e.with_seq(99).content_id == e.content_id


# -- causal DAG ---------------------------------------------------------------

@pytest.fixture
def diamond():
    """root -> (left, right) -> join -> tail, plus an unrelated effect."""
    root = mk("a", (), {"s": "root"})
    left = mk("b", (root.id,), {"s": "left"})
    right = mk("c", (root.id,), {"s": "right"})
    join = mk("d", (left.id, right.id), {"s": "join"})
    tail = mk("e", (join.id,), {"s": "tail"})
    other = mk("z", (), {"s": "unrelated"})
    dag = CausalDAG([root, left, right, join, tail, other])
    return dag, root, left, right, join, tail, other


def test_forward_lightcone_is_the_blast_radius(diamond):
    dag, root, left, right, join, tail, other = diamond
    cone = dag.forward_lightcone(left.id)
    assert cone == {left.id, join.id, tail.id}
    assert other.id not in cone, "unrelated work must never enter the cone"
    assert right.id not in cone, "a sibling is not downstream"


def test_backward_lightcone_is_provenance(diamond):
    dag, root, left, right, join, tail, other = diamond
    assert dag.backward_lightcone(tail.id) == {tail.id, join.id, left.id, right.id, root.id}


def test_forward_cone_from_root_covers_everything_downstream(diamond):
    dag, root, left, right, join, tail, other = diamond
    assert dag.forward_lightcone(root.id) == {root.id, left.id, right.id, join.id, tail.id}


def test_root_hash_is_order_insensitive_but_content_sensitive(diamond):
    dag, root, left, *_ = diamond
    shuffled = CausalDAG(list(reversed(dag.ordered())))
    assert shuffled.root_hash() == dag.root_hash(), "concurrent interleaving must not change the hash"

    changed = CausalDAG([e for e in dag.ordered() if e.id != left.id])
    assert changed.root_hash() != dag.root_hash()


def test_diff_classifies_by_content_not_text(diamond):
    dag, root, left, right, join, tail, other = diamond
    left2 = left.with_response({"changed": True})
    extra = mk("new", (tail.id,), {"s": "extra"})
    right_dag = CausalDAG([root, left2, right, join, tail, extra])

    d = dag.diff(right_dag)
    assert left.id in d.changed
    assert extra.id in d.added
    assert other.id in d.removed
    assert root.id in d.identical


# -- branching ----------------------------------------------------------------

def test_fork_copies_nothing():
    """O(1) fork: the branch record is written, the parent's effects are not copied."""
    store = InMemoryEffectStore()
    for i in range(500):
        store.put(mk("a", (), {"i": i}, response={"r": i}, seq=i + 1))
    assert len(store.own_effects(PRIMARY)) == 500

    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="what-if", at_seq=250))
    assert store.own_effects(br.id) == [], "forking must not copy the parent's effects"


def test_lookup_resolves_through_the_chain_without_a_sequence_cutoff():
    """Effects recorded on the parent *after* the fork are still valid replay cache —
    this is what makes replay on a fork cheap."""
    store = InMemoryEffectStore()
    early = mk("a", (), {"i": "early"}, response={"r": 1}, seq=10)
    late = mk("a", (), {"i": "late"}, response={"r": 2}, seq=900)
    store.put_many([early, late])
    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=100))

    assert store.lookup(br.id, early.id) is not None
    assert store.lookup(br.id, late.id) is not None, (
        "a post-fork parent effect must remain addressable as cache"
    )


def test_timeline_honours_the_fork_point():
    """History, unlike cache, is cut at the fork: a branch inherits its parent's past."""
    store = InMemoryEffectStore()
    early = mk("a", (), {"i": "early"}, response={"r": 1}, seq=10)
    late = mk("a", (), {"i": "late"}, response={"r": 2}, seq=900)
    store.put_many([early, late])
    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=100))

    ids = {e.id for e in store.timeline(br.id)}
    assert early.id in ids
    assert late.id not in ids, "a branch must not inherit its parent's future"


def test_branch_timeline_includes_its_own_executed_effects():
    store = InMemoryEffectStore()
    base = mk("a", (), {"i": 1}, response={"r": 1}, seq=5)
    store.put(base)
    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=5))
    own = mk("a", (base.id,), {"i": 2}, response={"r": 2}, seq=6, branch=br.id)
    store.put(own)
    store.append_manifest(br.id, [own.id])

    ids = [e.id for e in store.timeline(br.id)]
    assert ids == [base.id, own.id]


def test_manifest_materialises_inherited_effects_without_copying():
    """A branch that replayed a parent effect shows it in its timeline while storing nothing."""
    store = InMemoryEffectStore()
    a = mk("x", (), {"i": 1}, response={"r": 1}, seq=1)
    b = mk("x", (a.id,), {"i": 2}, response={"r": 2}, seq=2)
    store.put_many([a, b])
    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=1))
    store.append_manifest(br.id, [b.id])  # replayed, not executed

    assert store.own_effects(br.id) == []
    assert [e.id for e in store.timeline(br.id)] == [a.id, b.id]


def test_next_seq_on_a_fork_starts_above_the_fork_point():
    store = InMemoryEffectStore()
    br = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=400))
    assert store.next_seq(br.id) == 401


# -- snapshots ----------------------------------------------------------------

def test_snapshot_roundtrip_preserves_timeline_and_state(tmp_path):
    """A recorded history is expensive real work; it must survive the process."""
    from kernel.snapshot import load, save
    from world.shadow import TOMBSTONE, ShadowWorld

    store = InMemoryEffectStore()
    a = mk("triage", (), {"i": 1}, response={"r": 1}, seq=1)
    b = mk("policy", (a.id,), {"i": 2}, response={"r": 2}, seq=2)
    store.put_many([a, b])
    store.append_manifest(PRIMARY, [a.id, b.id])
    branch = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="alt", at_seq=1)
    )

    world = ShadowWorld(branches={x.id: x for x in store.list_branches()})
    world.write(branch_id=PRIMARY, collection="ledger", key="k", value={"v": 1}, seq=1)
    world.delete(branch_id=branch.id, collection="ledger", key="k", seq=2)

    path = save(tmp_path / "snap.json", store=store, world=world)
    store2, world2 = load(path)

    assert store2.dag(PRIMARY).root_hash() == store.dag(PRIMARY).root_hash()
    assert [e.id for e in store2.timeline(PRIMARY)] == [a.id, b.id]
    assert store2.get_branch(branch.id).fork_at_seq == 1
    assert world2.read(branch_id=PRIMARY, collection="ledger", key="k") == {"v": 1}
    assert world2.read(branch_id=branch.id, collection="ledger", key="k") is None, (
        "a tombstone must survive the round trip or deletions silently un-delete"
    )
