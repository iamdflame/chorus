"""Time as an input, never an ambient fact.

A determinism product that reads the wall clock is not deterministic, it is deterministic
until tomorrow. The failure is quiet and expensive: `urgency` is a function of
time-to-departure, so a passenger recorded today falls into a different band next week,
which changes their projection, which changes every address derived from it — and a
recorded run stops replaying without anything appearing to break. The store simply starts
missing, the bill returns, and the collapse ratio decays.

So every reading of "now" in this system comes from a `Clock` that is passed in. The
default is not `datetime.now()`; there is no default. Call sites must say which instant
they mean, and the type checker finds the ones that forgot.

`RecordedClock` goes further: each read is emitted as a `CLOCK` effect, so a replay
reproduces the exact instants the original run saw rather than approximating them. The
effect kind already existed in the enum and was never used — this is what it was for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

# The reference instant for every generated scenario and every projection in this
# repository. Fixed, committed, and printed by the proofs, so two runs on two machines on
# two different days agree by construction rather than by luck.
EPOCH = datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class Clock:
    """A fixed instant. Reading it is pure."""

    at: datetime = EPOCH

    def now(self) -> datetime:
        return self.at

    def unix(self) -> float:
        return self.at.timestamp()

    def shifted(self, **delta: float) -> Clock:
        """A clock at a different instant — for tests that need time to move."""
        return Clock(at=self.at + timedelta(**delta))

    def __str__(self) -> str:  # pragma: no cover - diagnostics
        return self.at.isoformat(timespec="seconds")


@dataclass(slots=True)
class RecordedClock:
    """A clock whose reads are recorded, so a replay sees the same instants.

    Used where a run genuinely needs to advance — a long-lived fleet reading the time
    between decisions — rather than sharing one frozen instant. On the first pass each
    read is captured; on replay the captured sequence is returned in order, so the agents
    observe exactly the timeline they observed originally.
    """

    source: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    recorded: list[str] = field(default_factory=list)
    replaying: bool = False
    _cursor: int = 0

    def now(self) -> datetime:
        if self.replaying:
            if self._cursor >= len(self.recorded):
                # Running past the end of the recording means the replayed execution
                # asked for the time more often than the original did — a divergence,
                # and one that would otherwise be papered over with a fresh timestamp.
                raise RuntimeError(
                    "clock read beyond the recorded sequence; execution diverged"
                )
            value = datetime.fromisoformat(self.recorded[self._cursor])
            self._cursor += 1
            return value
        value = self.source()
        self.recorded.append(value.isoformat())
        return value

    def rewind(self) -> None:
        self._cursor = 0
        self.replaying = True


#: The clock every proof, scenario and projection uses unless told otherwise.
FIXED = Clock()
