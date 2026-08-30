"""Generate the message corpus once, commit it, never generate it again.

Costs real money and takes real time, so it is not part of any proof. The proofs read
`data/corpus.json`, which is committed. This script exists so the corpus is reproducible
and so a reader can see exactly how the ground truth was established: messages are written
*from* known situations, never labelled afterwards.

    python scripts/build_corpus.py --messages 2000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from intake.corpus import (
    COMPLICATIONS,
    CORPUS_PATH,
    REGISTERS,
    Message,
    build_prompt,
    corpus_stats,
    sample_language,
    situation_brief,
)
from kernel.clock import FIXED
from swarm.canonical import project_passenger
from swarm.scenario import build_scenario

BATCH = 20
MODEL = "gemini-3.5-flash"


async def generate_batch(client, briefs) -> list[str]:
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL,
        contents=build_prompt(briefs),
        config={"response_mime_type": "application/json", "temperature": 1.0},
    )
    try:
        return json.loads(response.text).get("messages", [])
    except (json.JSONDecodeError, AttributeError):
        return []


async def main(count: int, concurrency: int) -> int:
    from google import genai

    rng = random.Random(4242)
    scenario = build_scenario(passengers=max(count, 2000))
    passengers = [asdict(p) for p in scenario.passengers]

    # Spread the corpus across situations rather than across passengers: the point is to
    # cover the lattice, and drawing uniformly from the population would over-sample the
    # crowded cells and leave the rare ones unrepresented.
    by_cell: dict[str, list[dict]] = {}
    for passenger in passengers:
        by_cell.setdefault(project_passenger(passenger, clock=FIXED).key(), []).append(passenger)
    cells = sorted(by_cell)
    print(f"  {len(cells)} situation cells across {len(passengers):,} travellers")

    jobs = []
    for i in range(count):
        cell = cells[i % len(cells)]
        passenger = rng.choice(by_cell[cell])
        projection = project_passenger(passenger, clock=FIXED)
        jobs.append((
            passenger,
            projection,
            situation_brief(passenger, projection),
            rng.choice(REGISTERS),
            sample_language(rng),
            rng.choice(COMPLICATIONS),
        ))

    client = genai.Client()
    gate = asyncio.Semaphore(concurrency)
    messages: list[Message] = []
    done = 0

    async def run_batch(chunk, offset: int):
        nonlocal done
        async with gate:
            briefs = [(brief, register, language, complication)
                      for _, _, brief, register, language, complication in chunk]
            texts = await generate_batch(client, briefs)
            for j, text in enumerate(texts[: len(chunk)]):
                passenger, projection, _, register, language, complication = chunk[j]
                messages.append(Message(
                    id=f"MSG-{offset + j:05d}",
                    passenger_id=passenger["id"],
                    text=text.strip(),
                    language=language,
                    register=register,
                    complication=complication,
                    truth=projection.to_dict(),
                ))
            done += len(chunk)
            print(f"\r  generated {done:,}/{count:,}", end="", flush=True)

    chunks = [jobs[i:i + BATCH] for i in range(0, len(jobs), BATCH)]
    await asyncio.gather(*(run_batch(c, i * BATCH) for i, c in enumerate(chunks)))
    print()

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(json.dumps(
        {"generator": MODEL, "messages": [m.to_dict() for m in messages]},
        ensure_ascii=False,
    ))

    stats = corpus_stats(messages)
    print(f"\n  {json.dumps(stats, indent=2)}")
    print(f"\n  written: {CORPUS_PATH.relative_to(ROOT)}")
    if stats["distinct_texts"] < stats["messages"] * 0.9:
        print("  WARNING: high duplication — raise temperature or widen the quirk set")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--messages", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=6)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.messages, a.concurrency)))
