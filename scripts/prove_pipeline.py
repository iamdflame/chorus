"""The whole pipeline, end to end, against live Gemini — and what it really cost.

Every other proof in this repo isolates one stage. This one runs all five in sequence on
the same travellers, so the number it prints is the number a customer would be billed:

    [1] intake       a real free-text message per traveller, 8 languages
    [2] extraction   MODEL, per distinct message   — unbounded input, no table follows it
    [3] route        KERNEL, free                  — collapse, escalate, or ask
    [4] elicitation  MODEL, per distinct situation — bounded input, so the kernel earns
    [5] allocation   DETERMINISTIC                 — no model touches seat assignment

Two things this script exists to keep honest.

**The blend, not the best stage.** Extraction is per-message and cannot collapse.
Quoting the elicitation ratio alone is how an earlier version of this project claimed
104x for a pipeline that achieves rather less. `PipelineReport` computes both and the
summary line leads with the blend.

**Escalation is paid for, not hidden.** A traveller the extractor was unsure about does
not get answered from a cohort's shared thought, because the cohort may be the wrong one.
They are reasoned about individually at full price, and that price lands in the same total
as everything else. A system that quietly drops its hard cases would post a better number
and be worth less.

The projection is composed from two sources, which is a design claim worth stating out
loud: extraction infers only what the traveller alone knows — how urgent this is, who is
travelling, what they will accept — while haul, hotel entitlement and misconnect status
come from the booking record, because the airline already knows them and asking a model to
guess facts it holds in a database is not intelligence, it is waste.

    python scripts/prove_pipeline.py --travellers 2000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from bench.baselines import allocate_by_preference
from bench.metrics import score
from extract.runner import extract_many
from intake.corpus import load_corpus
from kernel.branch import PRIMARY
from kernel.clock import FIXED
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from swarm.canonical import Projection, haul_band
from swarm.pipeline import PipelineReport, plan, situations
from swarm.runtime import Swarm
from swarm.scenario import build_scenario

CONTEXT = (
    "A hub closure has stranded your flight. State your rebooking preferences."
)


def compose(projection: Projection, record: dict) -> Projection:
    """Merge what the traveller said with what the airline already knows.

    The model is asked only about what the traveller alone can settle. Overwriting the
    rest from the booking record is not a shortcut — it is the correct division
    of labour, and it removes three chances for the model to be confidently wrong about a
    fact already in the database.
    """
    return replace(
        projection,
        tier=record["tier"],
        haul=haul_band(record["region"]),
        hotel_entitled=bool(record["has_hotel_entitlement"]),
        misconnect=bool(record["is_misconnect"]),
    )


async def main(travellers: int, concurrency: int) -> int:
    corpus = load_corpus()
    if not corpus:
        print("\n  No corpus. Run scripts/build_corpus.py first.\n")
        return 1

    scenario = build_scenario(passengers=20_000)
    by_id = {p.id: asdict(p) for p in scenario.passengers}
    messages = [m for m in corpus if m.passenger_id in by_id][:travellers]
    if not messages:
        print("\n  Corpus and scenario do not share travellers.\n")
        return 1
    passengers = [by_id[m.passenger_id] for m in messages]
    flights = [asdict(f) for f in scenario.flights]

    report = PipelineReport(entities=len(messages))
    print(f"\n  Chorus end to end — {len(messages):,} travellers, live gemini\n")

    # -- [2] extraction --------------------------------------------------------
    def tick(done: int, total: int) -> None:
        print(f"\r  extracting  {done:>5,}/{total:,}", end="", flush=True)

    run = await extract_many(messages, concurrency=concurrency, on_progress=tick)
    print()
    report.extraction.calls = run.calls
    report.extraction.cached = run.deduped
    report.extraction.cost_usd = run.cost_usd
    report.distinct_messages = run.calls + run.failed

    # Compose the two halves of the projection before anything routes on it.
    record_of = {m.id: by_id[m.passenger_id] for m in messages}
    extractions = []
    for message in messages:
        got = run.results[message.id]
        extractions.append(
            replace(got, projection=compose(got.projection, record_of[message.id]))
        )

    # -- [3] route -------------------------------------------------------------
    buckets = plan(extractions)
    grouped = situations(buckets["collapse"])
    report.distinct_situations = len(grouped)
    report.escalated = len(buckets["escalate"])

    print(f"\n  extraction   {run.calls:,} calls, {run.deduped:,} avoided as duplicate "
          f"text, {run.failed} failed")
    if run.quoted_checked:
        print(f"               {100 * run.quotation_rate:.1f}% of cited evidence "
              f"genuinely appears in the message")
    print(f"  routing      {len(buckets['collapse']):,} collapsible into "
          f"{len(grouped):,} situations · {len(buckets['escalate']):,} escalated · "
          f"{len(buckets['ask']):,} need a clarifying question")

    # -- [4] elicitation -------------------------------------------------------
    # Collapsible travellers share a thought per situation; escalated ones do not share at
    # all. Both go through the same Swarm, so both are priced by the same meter.
    swarm = Swarm(
        store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.RECORD,
        concurrency=concurrency,
    )
    projection_of = {e.message_id: e.projection for e in extractions}
    passenger_of = {m.id: by_id[m.passenger_id] for m in messages}

    collapsible = [passenger_of[e.message_id] for e in buckets["collapse"]]
    escalated = [passenger_of[e.message_id] for e in buckets["escalate"]]
    id_to_message = {by_id[m.passenger_id]["id"]: m.id for m in messages}

    def shared(entity: dict) -> Projection:
        return projection_of[id_to_message[entity["id"]]]

    class Individual:
        """An escalated traveller reasons alone: unique address, no sharing."""

        __slots__ = ("_p", "_pid")

        def __init__(self, entity: dict) -> None:
            self._p = projection_of[id_to_message[entity["id"]]]
            self._pid = entity["id"]

        def key(self) -> str:
            return f"escalated|{self._pid}|{self._p.key()}"

        def to_prompt(self) -> str:
            return self._p.to_prompt()

        def to_dict(self) -> dict:
            return {**self._p.to_dict(), "escalated": True}

    preferences: dict[str, dict] = {}
    for label, group, projector in (
        ("collapsed", collapsible, shared),
        ("escalated", escalated, Individual),
    ):
        if not group:
            continue

        def progress(i: int, total: int, m, *_, _label=label) -> None:
            print(f"\r  {_label:<10}  {i:>5,}/{total:,}  calls {m.model_calls:>5}  "
                  f"${m.cost_usd:.4f}", end="", flush=True)

        got, metrics = await swarm.run(
            entities=group, projector=projector, role="passenger",
            context=CONTEXT, round_id=f"pipeline-{label}", on_progress=progress,
        )
        print()
        preferences.update(got)
        report.elicitation.calls += metrics.model_calls
        report.elicitation.cached += metrics.cache_hits
        report.elicitation.cost_usd += metrics.cost_usd

    # -- [5] allocation --------------------------------------------------------
    assignments = allocate_by_preference(passengers, flights, preferences)
    panel = score(
        strategy="Chorus", passengers=passengers, flights=flights,
        assignments=assignments, model_calls=report.total_calls,
        cost_usd=report.extraction.cost_usd + report.elicitation.cost_usd,
    )

    total_cost = report.extraction.cost_usd + report.elicitation.cost_usd
    per_call = total_cost / report.total_calls if report.total_calls else 0.0
    print(f"\n  {'stage':<14}{'calls':>9}{'cost':>11}")
    print(f"  {'-' * 34}")
    print(f"  {'extraction':<14}{report.extraction.calls:>9,}"
          f"{report.extraction.cost_usd:>11.4f}")
    print(f"  {'elicitation':<14}{report.elicitation.calls:>9,}"
          f"{report.elicitation.cost_usd:>11.4f}")
    print(f"  {'-' * 34}")
    print(f"  {'total':<14}{report.total_calls:>9,}{total_cost:>11.4f}")
    print(f"  {'naive':<14}{report.naive_calls:>9,}"
          f"{report.naive_calls * per_call:>11.4f}  ← projected at the measured "
          f"per-call cost")

    print(f"\n  {report.summary()}")
    print(f"\n  seated {panel.souls_seated:,} souls · tier-weighted satisfaction "
          f"{panel.satisfaction_tier_weighted:.3f} · tier-blind "
          f"{panel.satisfaction_tier_blind:.3f} · p95 wait {panel.p95_wait:.1f}h")

    out = Path("data/pipeline.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        **report.to_dict(),
        "extraction_failed": run.failed,
        "quotation_rate": run.quotation_rate,
        "routed": {k: len(v) for k, v in buckets.items()},
        "panel": asdict(panel),
    }, indent=2))
    print(f"\n  Written to {out}\n")

    if report.blended_collapse <= 1.0:
        print("  FAIL  the pipeline cost more than the naive one.\n")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--travellers", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.travellers, args.concurrency)))
