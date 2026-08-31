"""Runs as durable jobs, not as request-response.

A twenty-thousand-agent sweep is exactly the workload that should not be a synchronous
HTTP call. It takes fifty minutes, it costs real money, and a dropped connection halfway
through should not lose the work — the hackathon's own framing is agents that "run in the
background" and "automate complex workflows asynchronously."

The useful part is that the checkpoint already exists. Every completed model call is a
durable, content-addressed effect, so a run that dies at agent 12,000 resumes by replaying
the 1,900 thoughts it already paid for **at zero model cost** and continuing. That is a
better resumption story than a job queue with checkpointing bolted on, because it is not
bolted on: it falls out of addressing effects by their causal history.

    POST /api/runs        →  enqueue, return 202 + run_id
    GET  /api/runs/{id}   →  status, progress, cost
    GET  /api/runs/{id}/stream  →  SSE, live or replayed from where it got to

Run records live in Firestore beside the effects when a project is configured, so status
survives an instance restart and any instance can answer for any run. With no project they
live in memory and the record says so, rather than pretending durability it does not have.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class Run:
    """One background sweep, and everything a caller needs to reason about it."""

    id: str
    agents: int
    concurrency: int
    state: str = "queued"          # queued | running | done | failed | cancelled
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: int = 0
    model_calls: int = 0
    cache_hits: int = 0
    cost_usd: float = 0.0
    distinct_thoughts: int = 0
    failed: int = 0
    error: str | None = None
    # Where the durable record lives, stated rather than assumed.
    durable: bool = False

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at or time.time()
        return round(end - (self.started_at or self.created_at), 1)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["elapsed_s"] = self.elapsed_s
        out["percent"] = round(100 * self.progress / self.agents, 1) if self.agents else 0.0
        return out


class RunStore:
    """Run records, durable where a project is configured.

    Deliberately separate from the effect store. Effects are immutable and content
    addressed; a run record is mutable status. Putting mutable status in an append-only
    log would either corrupt the log's guarantee or require a compaction step nobody
    wants to own.
    """

    COLLECTION = "runs"

    def __init__(self, project: str | None = None) -> None:
        self._memory: dict[str, Run] = {}
        self._db = None
        self.durable = False
        if project:
            try:
                from google.cloud import firestore

                self._db = firestore.Client(project=project)
                self.durable = True
            except Exception:  # noqa: BLE001 - degraded, and every record says so
                self._db = None

    def put(self, run: Run) -> None:
        run.durable = self.durable
        self._memory[run.id] = run
        if self._db is not None:
            try:
                self._db.collection(self.COLLECTION).document(run.id).set(run.to_dict())
            except Exception:  # noqa: BLE001 - the run continues; the mirror lags
                pass

    def get(self, run_id: str) -> Run | None:
        found = self._memory.get(run_id)
        if found is not None:
            return found
        if self._db is None:
            return None
        try:
            doc = self._db.collection(self.COLLECTION).document(run_id).get()
        except Exception:  # noqa: BLE001
            return None
        if not doc.exists:
            return None
        payload = doc.to_dict()
        # Any instance can answer for any run, which is the point of putting it here.
        return Run(**{k: v for k, v in payload.items()
                      if k in Run.__dataclass_fields__})

    def recent(self, limit: int = 20) -> list[Run]:
        runs = sorted(self._memory.values(), key=lambda r: -r.created_at)
        return runs[:limit]


class Runner:
    """Executes queued runs in the background, one at a time.

    Serial on purpose. Two concurrent twenty-thousand-agent sweeps on one instance would
    contend for the same quota and make both slower, and the interesting concurrency is
    already inside a run.
    """

    def __init__(self, store: RunStore) -> None:
        self.store = store
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._task: asyncio.Task | None = None

    def start(self, execute) -> None:
        """`execute(run, emit)` performs the work. Injected so the API owns the engine."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(execute))

    def enqueue(self, agents: int, concurrency: int) -> Run:
        run = Run(id=uuid.uuid4().hex[:12], agents=agents, concurrency=concurrency)
        self.store.put(run)
        self._events[run.id] = []
        self._queue.put_nowait(run.id)
        return run

    def events(self, run_id: str) -> list[dict[str, Any]]:
        """Everything emitted so far, so a late subscriber sees the whole run.

        A client that connects at agent 12,000 should not be shown a run that appears to
        start there — the events already emitted are replayed first, then the live tail.
        """
        return list(self._events.get(run_id, ()))

    async def _loop(self, execute) -> None:
        while True:
            run_id = await self._queue.get()
            run = self.store.get(run_id)
            if run is None or run.state == "cancelled":
                continue
            run.state = "running"
            run.started_at = time.time()
            self.store.put(run)

            def emit(event: dict[str, Any], _id: str = run_id) -> None:
                self._events.setdefault(_id, []).append(event)

            try:
                await execute(run, emit)
                run.state = "done"
            except asyncio.CancelledError:
                run.state = "cancelled"
                raise
            except Exception as exc:  # noqa: BLE001 - a failed run is a recorded state
                run.state = "failed"
                run.error = f"{type(exc).__name__}: {exc}"
            finally:
                run.finished_at = time.time()
                self.store.put(run)
                emit({"event": "run_finished", **run.to_dict()})


def store_from_env() -> RunStore:
    return RunStore(os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
