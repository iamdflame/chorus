"""Live extraction, shared by everything that needs it.

This logic existed once inside `scripts/verify_extraction.py`. The pipeline needs the
identical call — same model, same schema, same temperature, same thinking budget — and a
second copy would eventually drift from the first, at which point the accuracy the
verifier reports would no longer be the accuracy the pipeline gets. So there is one.

The one thing the verifier does not want and the pipeline cannot do without is
deduplication. Accuracy must be measured per message, including repeats. Cost must be paid
per *distinct* message, because two travellers who type the same sentence are one
extraction. `dedupe` selects between them, and the count of avoided calls is reported
rather than folded silently into the total.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from extract import keyword
from extract.situation import INSTRUCTION, MODEL, SCHEMA, Extracted, parse
from kernel.interposer import PRICE_IN_PER_M, PRICE_OUT_PER_M
from swarm.canonical import Projection
from swarm.pipeline import message_address

# A stalled request otherwise holds its concurrency permit for the whole run. Bounding it
# is what stopped an earlier version hanging at 200 of 300.
CALL_TIMEOUT = 45.0


@dataclass
class ExtractionRun:
    """What a batch of extractions produced and what it cost."""

    results: dict[str, Extracted] = field(default_factory=dict)
    calls: int = 0
    deduped: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    quoted_checked: int = 0
    quoted_genuine: int = 0

    @property
    def quotation_rate(self) -> float:
        """Share of cited evidence spans that genuinely appear in the message.

        An extractor that invents its evidence is worse than one that admits doubt, so
        this is checked rather than assumed.
        """
        if not self.quoted_checked:
            return float("nan")
        return self.quoted_genuine / self.quoted_checked


async def extract_many(
    messages: Iterable[Any],
    *,
    concurrency: int = 16,
    dedupe: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> ExtractionRun:
    """Extract every message, optionally paying only once per distinct text.

    `messages` need only carry `.id` and `.text`. On failure the keyword extractor stands
    in, so a traveller whose message could not be read still reaches the allocator with a
    best-effort situation — and the failure is counted, never absorbed.
    """
    from google import genai

    client = genai.Client()
    gate = asyncio.Semaphore(concurrency)
    run = ExtractionRun()
    items = list(messages)
    total = len(items)

    # One in-flight extraction per distinct text; the rest await its result.
    by_address: dict[str, asyncio.Future[Extracted]] = {}
    loop = asyncio.get_running_loop()
    done = 0

    async def one(message: Any) -> None:
        nonlocal done
        address = message_address(message.text) if dedupe else message.id
        existing = by_address.get(address)
        if existing is not None:
            run.deduped += 1
            shared = await existing
            # A shared reading, re-addressed to this traveller. The situation is a
            # property of the words, so copying it is sound; the id must not be, or two
            # travellers would collapse into one booking.
            run.results[message.id] = replace_id(shared, message.id)
            done += 1
            if on_progress:
                on_progress(done, total)
            return

        promise: asyncio.Future[Extracted] = loop.create_future()
        by_address[address] = promise
        got: Extracted | None = None
        async with gate:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=MODEL,
                        contents=f"{INSTRUCTION}\n\nMessage:\n{message.text}",
                        config={
                            "response_mime_type": "application/json",
                            "response_schema": SCHEMA,
                            "temperature": 0.0,
                            # Structured reading, not deliberation: the answer is in the
                            # text and the schema fixes the shape. The default budget
                            # spent 12s a call for no gain.
                            "thinking_config": {"thinking_level": "low"},
                        },
                    ),
                    timeout=CALL_TIMEOUT,
                )
                got = parse(message.id, json.loads(response.text))
                usage = response.usage_metadata
                run.calls += 1
                run.cost_usd += (
                    (usage.prompt_token_count or 0) * PRICE_IN_PER_M
                    + (usage.candidates_token_count or 0) * PRICE_OUT_PER_M
                ) / 1e6
                for _, ok in got.evidence_is_quoted(message.text).items():
                    run.quoted_checked += 1
                    run.quoted_genuine += ok
            except Exception as exc:  # noqa: BLE001 - a failure is a data point
                run.failed += 1
                got = _fallback(message, exc)
            finally:
                # Every traveller who wrote this same text is blocked on the promise, so
                # it must be resolved on every path out of here — including one where the
                # fallback itself raised. An unresolved promise hangs the entire run on a
                # single bad message.
                if got is None:
                    got = _fallback(message, None)
                if not promise.done():
                    promise.set_result(got)
                run.results[message.id] = got
            done += 1
            if on_progress:
                on_progress(done, total)

    await asyncio.gather(*(one(m) for m in items))
    return run


def _fallback(message: Any, exc: BaseException | None) -> Extracted:
    """A best-effort situation for a message the model could not read.

    The traveller still reaches the allocator; the failure is counted, never absorbed.
    """
    try:
        projection = keyword.extract(message.id, message.text).projection
    except Exception:  # noqa: BLE001 - the fallback must not have a failure mode
        projection = Projection(
            role="passenger", tier="basic", urgency="flexible",
            party="solo", constraints="unencumbered",
        )
    return Extracted(
        message_id=message.id,
        projection=projection,
        error=f"{type(exc).__name__}: {exc}" if exc else "unresolved",
    )


def replace_id(extracted: Extracted, message_id: str) -> Extracted:
    from dataclasses import replace

    return replace(extracted, message_id=message_id)
