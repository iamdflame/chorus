"""Shadow sampling — calling the model on purpose when you already have the answer.

A cached agent decision goes stale silently. The model is updated, a policy changes, the
world moves, and the table keeps serving an answer that was right in March. Nothing in the
system notices, because a lookup that returns a value looks identical whether the value is
still correct or not. This is the failure mode that makes enterprises refuse to cache agent
decisions at all, and refusing to cache them is why agent fleets cost what they do.

So on a small, deterministic slice of traffic the model is called *even though the table
has an answer*, and the two are compared:

    agree     the row is confirmed, its trust rises, and the call cost is recorded as the
              price of knowing rather than assuming
    disagree  the row is invalidated, a drift event is emitted naming the fields that
              moved, and the next request for that situation pays for a fresh answer

The sample is chosen by hashing the situation key with the run's salt, not by calling a
random number generator. Randomness would make the audit unreproducible: an auditor asking
"why was this row never sampled" deserves an answer better than "chance". The same table,
salt and rate select the same rows on every machine, forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from kernel.effect import digest
from policy.compare import agrees, disagreeing_fields
from policy.table import PolicyTable

# Hash space used to turn a key into a stable fraction in [0, 1).
_SPACE = 1 << 32


def sampled(key: str, *, rate: float, salt: str) -> bool:
    """Whether this situation falls in the shadow slice — deterministically.

    A rate of 0 samples nothing and a rate of 1 samples everything, with no special-casing
    needed: the comparison is strict on a value that can never reach 1.0.
    """
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    bucket = int(digest(salt, key)[:8], 16) / _SPACE
    return bucket < rate


@dataclass
class DriftEvent:
    """One situation where the model no longer agrees with the table."""

    key: str
    fields: list[str]
    was: dict[str, Any]
    now: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "fields": self.fields, "was": self.was, "now": self.now}


@dataclass
class ShadowReport:
    """What the shadow slice cost and what it bought."""

    sampled: int = 0
    confirmed: int = 0
    drifted: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    events: list[DriftEvent] = field(default_factory=list)

    @property
    def answered(self) -> int:
        """Samples that produced an answer. Failures are not evidence either way."""
        return self.sampled - self.failed

    @property
    def drift_rate(self) -> float:
        """Share of *answered* samples the model no longer agrees with.

        Failed samples are excluded from the denominator rather than counted as
        agreement, which would let a rate-limited run report a reassuringly low drift
        rate simply for having asked less.

        nan when nothing was answered. A drift rate of 0.0 from zero samples is the most
        reassuring number this system could print and the least true, so it is not printed.
        """
        return self.drifted / self.answered if self.answered else float("nan")

    def interval(self, confidence: float = 0.95) -> tuple[float, float]:
        """Wilson score interval on the drift rate.

        Twenty-seven samples do not measure a percentage to two decimal places, and
        printing one as though they did is the kind of false precision this project
        exists to avoid. The interval is reported beside every rate derived from a small
        sample so nobody has to guess how much of it is noise.
        """
        n = self.answered
        if not n:
            return (float("nan"), float("nan"))
        z = 1.959963985 if confidence >= 0.95 else 1.6448536269
        phat = self.drifted / n
        denom = 1 + z * z / n
        centre = (phat + z * z / (2 * n)) / denom
        spread = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5) / denom
        return (max(0.0, centre - spread), min(1.0, centre + spread))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampled": self.sampled,
            "confirmed": self.confirmed,
            "drifted": self.drifted,
            "failed": self.failed,
            "cost_usd": round(self.cost_usd, 4),
            "answered": self.answered,
            "drift_rate": self.drift_rate,
            "drift_interval_95": list(self.interval()),
            "events": [e.to_dict() for e in self.events],
        }


async def shadow_sample(
    table: PolicyTable,
    keys: list[str],
    *,
    ask: Callable[[str], Awaitable[tuple[dict[str, Any] | None, float]]],
    rate: float = 0.02,
    salt: str = "chorus",
) -> ShadowReport:
    """Re-ask the model for a deterministic slice of the table and act on the answer.

    `ask` takes a situation key and returns the model's answer with what it cost. A failed
    sample is counted, never treated as agreement — an error that silently confirmed a row
    would turn the safety mechanism into a rubber stamp.
    """
    report = ShadowReport()
    for key in keys:
        if not sampled(key, rate=rate, salt=salt):
            continue
        row = table.lookup(key)
        if row is None:
            continue
        report.sampled += 1
        answer, cost = await ask(key)
        report.cost_usd += cost
        if answer is None:
            report.failed += 1
            continue
        if agrees(row.answer, answer):
            report.confirmed += 1
            table.confirm(key)
        else:
            report.drifted += 1
            report.events.append(DriftEvent(
                key=key,
                fields=disagreeing_fields(row.answer, answer),
                was=row.answer,
                now=answer,
            ))
            table.invalidate(key)
    return report
