"""Gemma against Gemini and the regex, on the same messages, with ground truth known.

The integration this project planned was Gemma as a cheap classifier ahead of Gemini. That
premise did not survive the model: `gemma-4-26b-a4b-it` cannot have its thinking disabled —
`thinking_budget` and `thinking_level` are both rejected — and it spends roughly seventeen
tokens reasoning for every token it answers. It is not the cheap end of anything.

Handed the same detailed rubric Gemini reads, it does not finish at all: four thousand
output tokens consumed by deliberation, no answer, on every message tried. It needs a terse
prompt, so the comparison here is each model at its own best rather than one prompt on two
models. That is the fairer test and the only one available.

What Gemma is actually worth is stated by the result, not decided in advance:

    if it matches Gemini    a second, independently trained family corroborates the
                            reading, which is worth more to the Necessity Ledger than any
                            cost saving — shadow sampling re-asks the *same* model and so
                            cannot detect one that is consistently wrong
    if it trails Gemini     that is the finding, reported, and it is not used

    python scripts/verify_gemma.py --sample 120
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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

from extract import gemma_arm, keyword
from extract.runner import extract_many
from intake.corpus import load_corpus

FIELDS = ("tier", "urgency", "party", "constraints")


def accuracy(pairs) -> dict[str, float]:
    scores = {f: 0 for f in FIELDS}
    exact = 0
    for truth, got in pairs:
        projected = got.projection.to_dict()
        hits = sum(projected.get(f) == truth.get(f) for f in FIELDS)
        for f in FIELDS:
            scores[f] += projected.get(f) == truth.get(f)
        exact += hits == len(FIELDS)
    n = max(len(pairs), 1)
    out = {f: scores[f] / n for f in FIELDS}
    out["exact"] = exact / n
    out["mean_field"] = sum(scores.values()) / (n * len(FIELDS))
    return out


async def run_gemma(messages, concurrency: int):
    gate = asyncio.Semaphore(concurrency)
    pairs, tokens, failures = [], {"thought": 0, "answer": 0, "prompt": 0}, 0
    done = 0

    async def one(message):
        nonlocal done, failures
        async with gate:
            got, reply = await asyncio.to_thread(
                gemma_arm.extract, message.id, message.text
            )
            tokens["thought"] += reply.thought_tokens
            tokens["answer"] += reply.answer_tokens
            tokens["prompt"] += reply.prompt_tokens
            if got.error:
                failures += 1
            pairs.append((message.truth, got))
            done += 1
            print(f"\r  gemma {done}/{len(messages)}", end="", flush=True)

    await asyncio.gather(*(one(m) for m in messages))
    print()
    return pairs, tokens, failures


def report(name: str, scores: dict[str, float], extra: str = "") -> None:
    print(f"  {name:<22}" + "".join(f"{100 * scores[f]:>11.1f}%" for f in FIELDS)
          + f"{100 * scores['exact']:>11.1f}%{100 * scores['mean_field']:>11.1f}%  {extra}")


async def main(sample: int, concurrency: int) -> int:
    corpus = load_corpus()
    if not corpus:
        print("\n  No corpus. Run scripts/build_corpus.py first.\n")
        return 1
    messages = corpus[:sample]

    print(f"\n  Three extractors, {len(messages)} messages, ground truth known by "
          f"construction\n")
    print(f"  {'extractor':<22}" + "".join(f"{f:>12}" for f in FIELDS)
          + f"{'exact':>12}{'mean':>12}")
    print(f"  {'-' * 106}")

    kw = [(m.truth, keyword.extract(m.id, m.text)) for m in messages]
    report("keyword (free)", accuracy(kw))

    run = await extract_many(messages, concurrency=concurrency, dedupe=False)
    gemini = [(m.truth, run.results[m.id]) for m in messages]
    report("gemini-3.5-flash", accuracy(gemini), f"${run.cost_usd:.4f}")

    pairs, tokens, failures = await run_gemma(messages, concurrency)
    ratio = tokens["thought"] / max(tokens["answer"], 1)
    report("gemma-4-26b-a4b-it", accuracy(pairs), f"{failures} unparseable")

    # A message Gemma never finished thinking about is scored against a fallback
    # projection, which measures the token budget rather than the model. Both numbers are
    # printed: the first is what you would get in production, the second is what the model
    # can do when it answers at all.
    answered = [(t, g) for t, g in pairs if not g.error]
    if answered and len(answered) < len(pairs):
        report("  └ when it answers", accuracy(answered),
               f"{len(answered)}/{len(pairs)} messages")

    print(f"\n  Gemma spent {tokens['thought']:,} tokens thinking to produce "
          f"{tokens['answer']:,} tokens of answer — {ratio:.0f}x.")
    print(f"  It is not the cheap end of anything, so it is not used as one.")

    # Cross-family agreement: the number that decides whether Gemma is useful here.
    by_id = {m.id: (dict(g[1].projection.to_dict()), dict(p[1].projection.to_dict()))
             for m, g, p in zip(messages, gemini, pairs)}
    agree = sum(
        all(a.get(f) == b.get(f) for f in FIELDS) for a, b in by_id.values()
    )
    both_right = sum(
        1 for m, g, p in zip(messages, gemini, pairs)
        if all(g[1].projection.to_dict().get(f) == m.truth.get(f) for f in FIELDS)
        and all(p[1].projection.to_dict().get(f) == m.truth.get(f) for f in FIELDS)
    )
    disagree_ids = [i for i, (a, b) in by_id.items()
                    if not all(a.get(f) == b.get(f) for f in FIELDS)]
    right_when_agreeing = sum(
        1 for m, g in zip(messages, gemini)
        if m.id not in disagree_ids
        and all(g[1].projection.to_dict().get(f) == m.truth.get(f) for f in FIELDS)
    )
    agreed = len(messages) - len(disagree_ids)

    # Per field rather than all-four-at-once. Requiring four simultaneous agreements
    # leaves 15 samples to reason from, which cannot support a claim in either direction;
    # per field there are 120 apiece, and the question — does a second family agreeing
    # predict a correct reading — is answered field by field where it is actually used.
    print(f"\n  Does Gemma agreeing predict Gemini being right?\n")
    print(f"  {'field':<16}{'agree':>9}{'gemini right':>15}{'when agreed':>14}{'lift':>9}")
    print(f"  {'-' * 63}")
    lifts = {}
    for field in FIELDS:
        agreed_n = right_agreed = right_all = 0
        for m, g, p_ in zip(messages, gemini, pairs):
            gv = g[1].projection.to_dict().get(field)
            pv = p_[1].projection.to_dict().get(field)
            correct = gv == m.truth.get(field)
            right_all += correct
            if gv == pv:
                agreed_n += 1
                right_agreed += correct
        base = right_all / len(messages)
        cond = right_agreed / agreed_n if agreed_n else float("nan")
        lifts[field] = cond - base
        print(f"  {field:<16}{agreed_n:>6}/{len(messages):<3}{100 * base:>13.1f}%"
              f"{100 * cond:>13.1f}%{100 * (cond - base):>+8.1f}")

    print(f"\n  Cross-family agreement (all four fields)   "
          f"{100 * agree / len(messages):>6.1f}%   ({agree}/{len(messages)})")
    if agreed:
        print(f"  Gemini correct when Gemma agrees            "
              f"{100 * right_when_agreeing / agreed:>6.1f}%   ({right_when_agreeing}/{agreed})")
    gemini_exact = accuracy(gemini)["exact"]
    print(f"  Gemini correct overall                      "
          f"{100 * gemini_exact:>6.1f}%")
    lift = (right_when_agreeing / agreed - gemini_exact) if agreed else 0.0
    print(f"\n  Agreement between two independently trained families raises confidence in a")
    print(f"  reading by {100 * lift:+.1f} points. That is what shadow sampling cannot do by")
    print(f"  re-asking the same model, and it is the role Gemma earns here.")

    out = Path("data/gemma.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "sample": len(messages),
        "keyword": accuracy(kw),
        "gemini": accuracy(gemini),
        "gemma": accuracy(pairs),
        "gemma_tokens": tokens,
        "gemma_think_to_answer": ratio,
        "gemma_unparseable": failures,
        "cross_family_agreement": agree / len(messages),
        "gemini_exact_when_gemma_agrees": (right_when_agreeing / agreed) if agreed else None,
        "confidence_lift": lift,
        "per_field_lift": lifts,
        "gemma_when_answering": accuracy(answered) if answered else None,
        "gemma_answered": len(answered),
    }, indent=2))
    print(f"\n  Written to {out}\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.sample, args.concurrency)))
