"""Does the model actually read better than a competent regex?

This is the experiment that decides whether Chorus has a thesis. v1's model sat behind a
five-field categorical input, so a lookup table replicated it exactly and beat it. v2 puts
the model in front of unbounded free text, where a table cannot follow. That is an
argument, and an argument is not evidence.

So: both extractors, the same messages, ground truth known by construction because each
message was written *from* a situation rather than labelled afterwards.

    keyword   free, instant, multilingual, negation-aware, tuned in good faith
    model     gemini-3.5-flash with evidence spans and per-field confidence

If the keyword arm keeps up, the model is not earning its place at this stage either and
we would rather find out here.

    python scripts/verify_extraction.py                 # keyword arm only, offline
    python scripts/verify_extraction.py --model 300     # plus a model sample
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from extract import keyword
from extract.situation import INSTRUCTION, MODEL, SCHEMA, Extracted, parse
from intake.corpus import load_corpus

FIELDS = ("tier", "urgency", "party", "constraints")
PRICE_IN, PRICE_OUT = 1.35, 8.10


def accuracy(results: list[tuple[dict, Extracted]]) -> dict[str, float]:
    if not results:
        return {}
    scores = {f: 0 for f in FIELDS}
    exact = 0
    for truth, got in results:
        projected = got.projection.to_dict()
        hits = 0
        for f in FIELDS:
            if projected.get(f) == truth.get(f):
                scores[f] += 1
                hits += 1
        exact += hits == len(FIELDS)
    n = len(results)
    out = {f: scores[f] / n for f in FIELDS}
    out["exact"] = exact / n
    out["mean_field"] = sum(scores.values()) / (n * len(FIELDS))
    return out


async def run_model(messages, limit: int, concurrency: int):
    from google import genai

    client = genai.Client()
    gate = asyncio.Semaphore(concurrency)
    results: list[tuple[dict, Extracted]] = []
    cost = 0.0
    quoted = {"checked": 0, "genuine": 0}
    done = 0

    async def one(message):
        nonlocal cost, done
        async with gate:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=MODEL,
                    contents=f"{INSTRUCTION}\n\nMessage:\n{message.text}",
                    config={"response_mime_type": "application/json",
                            "response_schema": SCHEMA, "temperature": 0.0},
                )
                got = parse(message.id, json.loads(response.text))
                usage = response.usage_metadata
                cost += ((usage.prompt_token_count or 0) * PRICE_IN
                         + (usage.candidates_token_count or 0) * PRICE_OUT) / 1e6
                for _, ok in got.evidence_is_quoted(message.text).items():
                    quoted["checked"] += 1
                    quoted["genuine"] += ok
                results.append((message.truth, got))
            except Exception as exc:  # noqa: BLE001 - a failed extraction is a data point
                results.append((message.truth, Extracted(
                    message_id=message.id,
                    projection=keyword.extract(message.id, message.text).projection,
                    error=f"{type(exc).__name__}: {exc}",
                )))
            done += 1
            if done % 25 == 0:
                print(f"\r  model: {done}/{limit}", end="", flush=True)

    await asyncio.gather(*(one(m) for m in messages[:limit]))
    print()
    return results, cost, quoted


def report(name: str, scores: dict[str, float], extra: str = "") -> None:
    print(f"  {name:<24}" + "".join(f"{scores[f]:>12.1%}" for f in FIELDS)
          + f"{scores['exact']:>12.1%}{scores['mean_field']:>12.1%}  {extra}")


async def main(model_limit: int, concurrency: int) -> int:
    messages = load_corpus()
    if not messages:
        print("\n  No corpus. Run scripts/build_corpus.py first.\n")
        return 1

    print(f"\n  {len(messages):,} messages · "
          f"{len({m.text for m in messages}):,} distinct texts · "
          f"{len({m.language for m in messages})} languages")
    print("  Ground truth known by construction: each message was written from a situation.\n")
    print(f"  {'extractor':<24}" + "".join(f"{f:>12}" for f in FIELDS)
          + f"{'exact':>12}{'mean':>12}")
    print("  " + "-" * 108)

    kw = [(m.truth, keyword.extract(m.id, m.text)) for m in messages]
    kw_scores = accuracy(kw)
    report("keyword (free)", kw_scores)

    model_scores = None
    if model_limit:
        sample = messages[:model_limit]
        kw_sample = accuracy([(m.truth, keyword.extract(m.id, m.text)) for m in sample])
        results, cost, quoted = await run_model(messages, model_limit, concurrency)
        model_scores = accuracy(results)
        report("keyword (same sample)", kw_sample)
        report(f"gemini-3.5-flash", model_scores, f"${cost:.4f}")
        errors = sum(1 for _, g in results if g.error)
        if quoted["checked"]:
            print(f"\n  evidence spans genuinely quoted from the message: "
                  f"{quoted['genuine']}/{quoted['checked']} "
                  f"({quoted['genuine'] / quoted['checked']:.0%})")
        if errors:
            print(f"  extraction failures: {errors}")

    print()
    if model_scores is None:
        print("  Keyword arm only. Add --model N to test whether the model beats it.\n")
        return 0

    lift = model_scores["mean_field"] - kw_sample["mean_field"]
    exact_lift = model_scores["exact"] - kw_sample["exact"]
    print(f"  model minus keyword:  mean field {lift:+.1%}   exact match {exact_lift:+.1%}")
    print()
    if lift <= 0:
        print("  FAIL  the model did not read better than a regex. On this corpus the "
              "extraction\n        stage does not justify a model, and the thesis needs "
              "the input to be harder\n        than this before it holds.\n")
        return 1
    print(f"  PASS  the model reads {lift:.1%} more fields correctly and gets "
          f"{exact_lift:+.1%} more\n        situations entirely right. Unbounded input is "
          "where it earns its place.\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=int, default=0, help="how many messages to send to the model")
    ap.add_argument("--concurrency", type=int, default=6)
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.model, a.concurrency)))
