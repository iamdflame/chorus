"""One in-flight execution per address; everyone else waits for the winner.

Without this the collapse is a lie under concurrency, and the lie gets worse the faster
you run. Lookup happens before the model call, so N agents in the same cohort that start
within the same round trip all miss, all call the model, and all write the same answer.
The store dedupes the *result* and reports a high hit rate afterwards, while the bill
records N calls. The saving therefore degrades exactly as you parallelise for throughput
— the one thing you would do to make a swarm fast.

The fix is to make the second caller wait rather than compute. It turns a bug into a
reportable number: `coalesced` counts calls suppressed here, so the residual gap between
distinct situations and actual model calls stops being something to explain away and
becomes something measured.

Two layers, because a single process is not the whole story:

    in-process   an asyncio future per address, for concurrency inside one worker
    cross-instance  a Firestore lease per address, for concurrency across containers

The second is optional and degrades safely: if the lease cannot be taken the caller
proceeds as it would have before, which is the old behaviour rather than a new failure.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass
class SingleFlight:
    """Coalesces concurrent work on the same address within one process."""

    _inflight: dict[str, asyncio.Future] = field(default_factory=dict)
    coalesced: int = 0
    executed: int = 0

    async def do(self, address: str, fn: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        """Run `fn` for this address, or await whoever is already running it.

        Returns `(result, was_coalesced)`. The flag is the point: without it a suppressed
        call is indistinguishable from a cache hit, and the two mean very different things
        — one is work that was already recorded, the other is work that was about to be
        duplicated.
        """
        existing = self._inflight.get(address)
        if existing is not None:
            self.coalesced += 1
            return await asyncio.shield(existing), True

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._inflight[address] = future
        try:
            result = await fn()
        except BaseException as exc:
            # Followers must fail the same way rather than hang. Set the exception before
            # removing the entry, or a waiter can wake to a future nobody will resolve.
            if not future.done():
                future.set_exception(exc)
            self._inflight.pop(address, None)
            raise
        self.executed += 1
        if not future.done():
            future.set_result(result)
        self._inflight.pop(address, None)
        return result, False

    # -- split form, for callback-style interposition ---------------------------
    # ADK splits a model call across before_model_callback and after_model_callback, so
    # the leader cannot hold the critical section inside one `await`. `begin` claims the
    # address or hands back the leader's future to wait on; `resolve` completes it.

    def begin(self, address: str) -> asyncio.Future | None:
        """Claim `address`, or return the in-flight future to await.

        `None` means the caller is the leader and must go on to do the work.
        """
        existing = self._inflight.get(address)
        if existing is not None:
            self.coalesced += 1
            return existing
        self._inflight[address] = asyncio.get_running_loop().create_future()
        return None

    def resolve(self, address: str, value: Any) -> None:
        future = self._inflight.pop(address, None)
        if future is not None and not future.done():
            self.executed += 1
            future.set_result(value)

    def fail(self, address: str, exc: BaseException) -> None:
        """Followers must fail the way the leader failed, not hang forever."""
        future = self._inflight.pop(address, None)
        if future is not None and not future.done():
            future.set_exception(exc)

    def abandon(self, address: str) -> None:
        """The leader finished without producing a value — release the waiters.

        Happens when a callback path returns early. Followers are woken with `None` so
        they fall through to doing the work themselves rather than blocking on a promise
        nobody intends to keep.
        """
        future = self._inflight.pop(address, None)
        if future is not None and not future.done():
            future.set_result(None)

    def report(self) -> dict[str, int]:
        return {"coalesced": self.coalesced, "executed": self.executed}


@dataclass
class FirestoreLease:
    """A cross-instance lease on an address, so four containers do not each pay once.

    Deliberately best-effort. If the lease cannot be acquired or the backend is
    unavailable, the caller proceeds exactly as it would have without leasing — the
    outcome is the duplicate call we already tolerate, not an outage. A coordination layer
    that can take the system down is worse than the duplication it prevents.
    """

    client: Any
    root: str = "chorus_leases"
    ttl_seconds: float = 45.0
    acquired: int = 0
    deferred: int = 0

    def acquire(self, address: str) -> bool:
        from google.api_core import exceptions as gexc
        from google.cloud import firestore

        ref = self.client.collection(self.root).document(address)
        now = time.time()

        @firestore.transactional
        def claim(transaction) -> bool:
            snapshot = ref.get(transaction=transaction)
            if snapshot.exists:
                held = (snapshot.to_dict() or {}).get("expires_at", 0)
                if held > now:
                    return False
            transaction.set(ref, {"expires_at": now + self.ttl_seconds})
            return True

        try:
            won = claim(self.client.transaction())
        except (gexc.GoogleAPICallError, gexc.RetryError):
            return True  # fail open: duplicate work beats refusing to work
        self.acquired += won
        self.deferred += not won
        return won

    def release(self, address: str) -> None:
        try:
            self.client.collection(self.root).document(address).delete()
        except Exception:  # noqa: BLE001 - the TTL is the real guarantee
            pass
