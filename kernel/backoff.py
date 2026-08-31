"""Retry at the one place the fleet touches a paid, rate-limited service.

Every model call and every tool call already funnels through the interposer, so this is a
single chokepoint rather than a decorator scattered across call sites. That is the same
property that makes replay possible, reused: interposing once means you only have to get
the hard thing right once.

Two constraints shape this, and both are load-bearing.

**A retry must not create a new causal address.** The address is a hash of the request at
its causal position, and a retried call is the *same* request at the *same* position. If a
retry re-opened an effect it would record two thoughts where the fleet had one, and the
collapse number — which is the entire product claim — would be inflated by exactly the
number of transient failures the run happened to hit. So retries live strictly inside the
execution of one already-opened effect.

**Only the miss path retries.** A replay hit never reaches the network, so retrying there
would be a replay contacting a live service, which breaks the guarantee that a replay
costs nothing and — under `REPLAY_STRICT` — would turn a determinism failure into a
silent network call.

Full jitter rather than a fixed multiple, in AWS's formulation. Sleeping `base * 2**i`
exactly synchronises every retrying worker onto the same schedule, which is how a brief
quota blip becomes a thundering herd at the moment the service can least absorb one. That
matters more here than in most systems: a swarm is by construction thousands of workers
doing the same thing at the same time.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

# Transient by nature: the call may succeed if repeated. Everything else — a bad request,
# a permission denial, a malformed schema — is a fact about the request that will not
# change however many times it is sent, so retrying it wastes the caller's time and the
# service's quota while hiding the real error behind a delay.
_RETRYABLE_NAMES = (
    "ResourceExhausted",     # 429, quota
    "ServiceUnavailable",    # 503
    "DeadlineExceeded",      # 504
    "InternalServerError",   # 500
    "TooManyRequests",
    "Aborted",
)

DEFAULT_ATTEMPTS = 5
DEFAULT_BASE = 0.5
DEFAULT_CAP = 30.0


def is_retryable(exc: BaseException) -> bool:
    """Whether an exception is worth repeating the call for.

    Matched on the exception's own type name rather than by importing
    `google.api_core.exceptions`, so the kernel stays free of cloud dependencies — the
    same reason the effect store is a Protocol. `asyncio.TimeoutError` counts: a request
    that ran out of time may well complete on a quieter second attempt.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    name = type(exc).__name__
    if name in _RETRYABLE_NAMES:
        return True
    # Vendored and wrapped variants keep the name but move the module, and the status is
    # often only visible in the message.
    text = f"{name}: {exc}"
    return "RESOURCE_EXHAUSTED" in text or "429" in text and "Too Many" in text




class Attempts:
    """Counts what actually happened, so a run can report it rather than guess."""

    __slots__ = ("calls", "retries", "slept_s", "exhausted")

    def __init__(self) -> None:
        self.calls = 0
        self.retries = 0
        self.slept_s = 0.0
        self.exhausted = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "retries": self.retries,
            "slept_s": round(self.slept_s, 3),
            "exhausted": self.exhausted,
        }


async def with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base: float = DEFAULT_BASE,
    cap: float = DEFAULT_CAP,
    stats: Attempts | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[float, float], float] = random.uniform,
) -> T:
    """Call `fn`, retrying transient failures with full jitter.

    `sleep` and `rand` are injectable so the tests can assert the schedule without
    actually waiting — a retry test that sleeps for real is a test nobody runs.
    """
    if stats is not None:
        stats.calls += 1
    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return await fn()
        except BaseException as exc:  # noqa: BLE001 - classified immediately below
            if not is_retryable(exc):
                raise
            last = exc
            if i == attempts - 1:
                break
            delay = rand(0.0, min(cap, base * (2**i)))
            if stats is not None:
                stats.retries += 1
                stats.slept_s += delay
            await sleep(delay)
    if stats is not None:
        stats.exhausted += 1
    assert last is not None
    raise last
