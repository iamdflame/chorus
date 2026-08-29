"""Differential test: the Firestore backend must behave exactly like the reference.

Runs the same operation sequence through `InMemoryEffectStore` and
`FirestoreEffectStore` and asserts the observable results agree. Written this way
because the failure mode of a distributed backend is not a crash — it is a replay miss
that silently costs money and produces a subtly wrong counterfactual. Comparing against
a known-good implementation turns that into an ordinary assertion.

Skipped unless GOOGLE_CLOUD_PROJECT is set and Firestore is reachable, so CI stays
offline-capable; run it against the real database before deploying.
"""

from __future__ import annotations

import os
import uuid

import pytest

from kernel.branch import PRIMARY, Branch
from kernel.effect import Determinism, Effect, EffectKind
from kernel.store import InMemoryEffectStore

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
pytestmark = pytest.mark.skipif(not PROJECT, reason="GOOGLE_CLOUD_PROJECT not set")


def mk(agent, parents, request, response, seq, branch=PRIMARY):
    return Effect.create(
        branch_id=branch, seq=seq, agent=agent, kind=EffectKind.MODEL_CALL,
        determinism=Determinism.RECORDED, causal_parents=parents,
        request=request, response=response,
    )


@pytest.fixture
def stores():
    from kernel.firestore_store import FirestoreEffectStore

    root = f"lightcone_test_{uuid.uuid4().hex[:10]}"
    remote = FirestoreEffectStore(project=PROJECT, root=root)
    yield InMemoryEffectStore(), remote
    remote.purge()


def test_firestore_matches_the_reference_implementation(stores):
    memory, remote = stores

    # Same writes into both.
    a = mk("triage", (), {"n": 1}, {"r": "one"}, 1)
    b = mk("policy", (a.id,), {"n": 2}, {"r": "two"}, 2)
    c = mk("comms", (b.id,), {"n": 3}, {"r": "three"}, 3)
    for store in (memory, remote):
        store.put_many([a, b, c])
        store.append_manifest(PRIMARY, [a.id, b.id, c.id])

    # Lookup agrees, including on a miss.
    for address in (a.id, b.id, c.id, "definitely-not-an-address"):
        found_memory = memory.lookup(PRIMARY, address)
        found_remote = remote.lookup(PRIMARY, address)
        assert (found_memory is None) == (found_remote is None)
        if found_memory is not None:
            assert found_memory.content_id == found_remote.content_id
            assert found_memory.request == found_remote.request, "payload round trip"
            assert found_memory.response == found_remote.response

    assert [e.id for e in memory.timeline(PRIMARY)] == [e.id for e in remote.timeline(PRIMARY)]
    assert memory.dag(PRIMARY).root_hash() == remote.dag(PRIMARY).root_hash(), (
        "the two backends must agree on the causal root hash or replay is not portable"
    )

    # Branching agrees.
    fork_memory = memory.create_branch(
        Branch.fork(parent=memory.get_branch(PRIMARY), name="alt", at_seq=2)
    )
    fork_remote = remote.create_branch(
        Branch.fork(parent=remote.get_branch(PRIMARY), name="alt", at_seq=2)
    )
    # Ids are random per fork; compare structure, not identity.
    assert memory.get_branch(fork_memory.id).fork_at_seq == remote.get_branch(fork_remote.id).fork_at_seq

    # A post-fork parent effect stays addressable as cache on both.
    assert (memory.lookup(fork_memory.id, c.id) is None) == (remote.lookup(fork_remote.id, c.id) is None)
    assert memory.lookup(fork_memory.id, c.id) is not None

    # History is cut at the fork on both.
    assert [e.id for e in memory.timeline(fork_memory.id)] == [a.id, b.id]
    assert [e.id for e in remote.timeline(fork_remote.id)] == [a.id, b.id]

    # Sequence allocation starts above the fork on both.
    assert memory.next_seq(fork_memory.id) == remote.next_seq(fork_remote.id) == 3


def test_firestore_round_trips_a_realistic_llm_payload(stores):
    """Firestore cannot store nested arrays, and an LLM response is full of them."""
    _, remote = stores
    payload = {
        "llm_response": {
            "content": {
                "role": "model",
                "parts": [
                    {"text": "DECISION: APPROVE_REFUND"},
                    {"function_call": {"name": "issue_refund",
                                       "args": {"dispute_id": "D-1", "amount_usd": 87.6}}},
                ],
            },
            "usage_metadata": {"prompt_token_count": 1024, "candidates_token_count": 64},
        }
    }
    effect = mk("policy", (), {"contents": [[{"nested": "array"}]]}, payload, 1)
    remote.put(effect)
    remote._cache.clear()  # force a real read back rather than the write-through cache

    restored = remote.lookup(PRIMARY, effect.id)
    assert restored is not None
    assert restored.response == payload
    assert restored.request == {"contents": [[{"nested": "array"}]]}
    assert restored.content_id == effect.content_id, "identity must survive the round trip"
