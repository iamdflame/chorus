"""B4 vs B5 — is collapse lossy?

Every other number in this project measures what collapse *saves*. This one measures what
it *costs*, which is the only question that matters: reusing one thought across a thousand
agents is worthless if the shared thought is worse than the thousand individual ones.

Two arms, differing in exactly one thing — the projection:

    B4  collapsed    one elicitation per distinct *situation*, from the bucketed lattice
    B5  uncollapsed  one elicitation per *traveller*, from the complete record

B5 is deliberately the stronger arm. It sees everything the lattice throws away: exact
party size rather than a band, the actual destination rather than a haul bucket, the
scheduled time rather than an urgency bucket, the bag count, and the traveller's identity.
If bucketing destroys decision-relevant signal, B5 is where it survives, and the two arms
diverge.

Both run through `Swarm.run` on the same population with the same instruction, the same
model and the same allocator. Substituting the projection is the entire experiment, so a
divergence cannot be blamed on anything else.

Note what B5 costs beyond money: it puts names in model prompts. B4 provably cannot —
`tests/test_projection_leakage.py` fails if identity reaches the projection. So agreement
between the arms is not only a cost result, it is the evidence that the private arm is not
paying for privacy with quality.

Fidelity is a property of the lattice, not of the population. A traveller's agreement with
their own cohort depends on their record and their bucket, both unchanged by how many other
travellers exist. So the rate measured on a sample holds at any scale, while the *cost*
ratio it is set against grows with population.

    python -m bench.fidelity --cohorts 40 --per-cohort 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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
from bench.metrics import Panel, score
from kernel.branch import PRIMARY
from kernel.clock import FIXED, Clock
from kernel.interposer import Mode
from kernel.store import InMemoryEffectStore
from swarm.canonical import SCHEMA_VERSION, bind, project_passenger
from swarm.runtime import Swarm
from swarm.scenario import build_scenario

# The six keys the elicitation returns. Booleans are compared for equality; the two
# numerics get a tolerance, because "max_wait_hours 6 vs 7" is not a disagreement anyone
# would act on and scoring it as one would understate agreement dishonestly.
BOOLEAN_FIELDS = (
    "accept_downgrade",
    "accept_split_party",
    "accept_nearby_airport",
    "needs_hotel",
)
NUMERIC_FIELDS = {"max_wait_hours": 2.0, "urgency_score": 10.0}


@dataclass(frozen=True, slots=True)
class FullRecord:
    """A projection that projects nothing — the B5 arm.

    Satisfies the same interface `Swarm.run` expects of `Projection`, so the uncollapsed
    arm runs the identical code path. `key()` is the traveller id, which is what forces
    one model call per traveller: the address is unique, so nothing can ever coalesce.
    """

    record: dict[str, Any]

    def key(self) -> str:
        return f"{SCHEMA_VERSION}|full|{self.record['id']}"

    def to_prompt(self) -> str:
        r = self.record
        return (
            f"Traveller record:\n"
            f"- booking: {r['id']} ({r.get('name')})\n"
            f"- loyalty tier: {r['tier']}\n"
            f"- party size: {r['party_size']} travelling together\n"
            f"- destination: {r['destination']} ({r['region']})\n"
            f"- original flight: {r['original_flight']}, "
            f"scheduled {r['scheduled_departure']}\n"
            f"- disrupted mid-journey: {'yes' if r['is_misconnect'] else 'no'}\n"
            f"- checked bags: {r['checked_bags']}\n"
            f"- requires mobility assistance: "
            f"{'yes' if r['needs_assistance'] else 'no'}\n"
            f"- overnight accommodation covered: "
            f"{'yes' if r['has_hotel_entitlement'] else 'no'}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"role": "passenger", "projection": "full_record", **self.record}


def _ranks(values: list[float]) -> list[float]:
    """Fractional ranks, ties averaged."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation, computed here to keep the bench dependency-free."""
    if len(a) < 2:
        return float("nan")
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else float("nan")


def agreement(a: dict[str, Any], b: dict[str, Any]) -> dict[str, bool]:
    """Field-by-field agreement between one traveller's two answers."""
    out: dict[str, bool] = {}
    for field in BOOLEAN_FIELDS:
        out[field] = bool(a.get(field)) == bool(b.get(field))
    for field, tolerance in NUMERIC_FIELDS.items():
        try:
            out[field] = abs(float(a.get(field, 0)) - float(b.get(field, 0))) <= tolerance
        except (TypeError, ValueError):
            out[field] = False
    return out


async def elicit(
    passengers: list[dict[str, Any]], projector: Any, *, label: str, concurrency: int
) -> tuple[dict[str, dict[str, Any]], Any]:
    swarm = Swarm(
        store=InMemoryEffectStore(), branch_id=PRIMARY, mode=Mode.RECORD,
        concurrency=concurrency,
    )
    done = {"n": 0}

    def progress(i: int, total: int, m: Any, *_: Any) -> None:
        done["n"] = i
        print(f"\r  {label}: {i:>5,}/{total:,}  calls {m.model_calls:>5}  "
              f"${m.cost_usd:.4f}", end="", flush=True)

    preferences, metrics = await swarm.run(
        entities=passengers, projector=projector, role="passenger",
        context="A hub closure has stranded your flight. State your rebooking preferences.",
        round_id=f"fidelity-{label}", on_progress=progress,
    )
    print()
    return preferences, metrics


def sample_populated(
    passengers: list[dict[str, Any]], projector: Any, *, cohorts: int, per_cohort: int
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Draw travellers from cohorts that collapse actually shares a thought across.

    Measuring fidelity on a small random sample would be measuring nothing: at 600
    travellers most sit alone in their bucket, B4 and B5 both make one call each, and the
    shared thought under test is never shared. So the sample is stratified over cohorts
    with at least `per_cohort` members, spanning the size distribution rather than taking
    the largest — the biggest cohorts are the coarsest buckets and would flatter the
    result.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for p in passengers:
        grouped.setdefault(projector(p).key(), []).append(p)
    eligible = sorted(
        ((k, v) for k, v in grouped.items() if len(v) >= per_cohort),
        key=lambda kv: (len(kv[1]), kv[0]),
    )
    if not eligible:
        return [], {}
    if len(eligible) <= cohorts:
        chosen = eligible
    else:
        step = (len(eligible) - 1) / (cohorts - 1) if cohorts > 1 else 1
        chosen = [eligible[round(i * step)] for i in range(cohorts)]
    out: list[dict[str, Any]] = []
    members: dict[str, list[str]] = {}
    for key, group in chosen:
        take = group[:per_cohort]
        out.extend(take)
        members[key] = [p["id"] for p in take]
    return out, members


def scale_seats(
    flights: list[dict[str, Any]], *, sampled: int, population: int
) -> list[dict[str, Any]]:
    """Shrink seat supply to the sample so scarcity is preserved.

    Without this, a few hundred travellers face an aircraft fleet built for twenty
    thousand, every preference is satisfiable, and the arms agree for a reason that has
    nothing to do with collapse.
    """
    ratio = sampled / population
    out = []
    for f in flights:
        scaled = dict(f)
        scaled["seats_free"] = max(1, int(round(f["seats_free"] * ratio)))
        out.append(scaled)
    return out


async def main(
    population: int, cohorts: int, per_cohort: int, concurrency: int, clock: Clock
) -> int:
    scenario = build_scenario(passengers=population)
    everyone = [asdict(p) for p in scenario.passengers]
    projector = bind(project_passenger, clock)

    passengers, members = sample_populated(
        everyone, projector, cohorts=cohorts, per_cohort=per_cohort
    )
    if not passengers:
        print(f"  FAIL: no cohort in a {population:,} population has "
              f"{per_cohort} members")
        return 1
    flights = scale_seats(
        [asdict(f) for f in scenario.flights],
        sampled=len(passengers), population=population,
    )

    print(f"\n  Fidelity of collapse — schema {SCHEMA_VERSION}\n")
    print(f"  drawn from      {population:,} travellers")
    print(f"  sample          {len(passengers):,} travellers in {len(members)} cohorts "
          f"of {per_cohort}")
    print(f"  seats free      {sum(f['seats_free'] for f in flights):,} "
          f"(scaled to the sample)")
    print(f"  within-sample   {len(passengers) / len(members):.0f}× collapse\n")

    b4_prefs, b4_metrics = await elicit(
        passengers, projector, label="B4 collapsed  ", concurrency=concurrency
    )
    b5_prefs, b5_metrics = await elicit(
        passengers, lambda e: FullRecord(e), label="B5 uncollapsed",
        concurrency=concurrency,
    )

    # -- agreement -------------------------------------------------------------
    both = [p["id"] for p in passengers if p["id"] in b4_prefs and p["id"] in b5_prefs]
    if not both:
        print("\n  FAIL: no traveller answered on both arms")
        return 1

    per_field: dict[str, list[bool]] = {}
    exact: list[bool] = []
    by_cohort: dict[str, list[bool]] = {}
    cohort_of = {pid: k for k, ids in members.items() for pid in ids}
    for pid in both:
        a = agreement(b4_prefs[pid], b5_prefs[pid])
        for field, ok in a.items():
            per_field.setdefault(field, []).append(ok)
        allowed = all(a.values())
        exact.append(allowed)
        by_cohort.setdefault(cohort_of[pid], []).append(allowed)

    print(f"\n  Agreement on {len(both):,} travellers answered by both arms\n")
    print(f"  {'field':<24}{'agree':>8}")
    print(f"  {'-' * 34}")
    for field in (*BOOLEAN_FIELDS, *NUMERIC_FIELDS):
        vals = per_field[field]
        note = f"  (±{NUMERIC_FIELDS[field]:g})" if field in NUMERIC_FIELDS else ""
        print(f"  {field:<24}{100 * sum(vals) / len(vals):>7.1f}%{note}")
    print(f"  {'-' * 34}")
    print(f"  {'all six fields':<24}{100 * sum(exact) / len(exact):>7.1f}%")

    # A tolerance test on the numerics answers a question the allocator never asks. It
    # sorts by urgency_score and never reads its magnitude, so what matters is whether the
    # two arms order travellers the same way, and whether one is systematically higher.
    print(f"\n  {'numeric':<24}{'bias':>8}{'spearman':>11}")
    print(f"  {'-' * 43}")
    numerics: dict[str, tuple[float, float]] = {}
    for field in NUMERIC_FIELDS:
        av, bv = [], []
        for pid in both:
            try:
                av.append(float(b4_prefs[pid].get(field, 0)))
                bv.append(float(b5_prefs[pid].get(field, 0)))
            except (TypeError, ValueError):
                continue
        bias = sum(x - y for x, y in zip(av, bv)) / len(av) if av else float("nan")
        rho = spearman(av, bv)
        numerics[field] = (bias, rho)
        print(f"  {field:<24}{bias:>+8.2f}{rho:>11.3f}")
    print("\n  bias is B4 − B5; spearman is rank agreement, which is what the "
          "allocator\n  actually consumes.")

    # -- decisions -------------------------------------------------------------
    b4_assign = allocate_by_preference(passengers, flights, b4_prefs)
    b5_assign = allocate_by_preference(passengers, flights, b5_prefs)
    same = sum(1 for pid in both if b4_assign.get(pid) == b5_assign.get(pid))
    # Seats are scarce by design, so most travellers go unseated on both arms and count
    # as agreeing for a reason that says nothing about the projection. The number that
    # carries information is agreement over the contested set: those either arm seated.
    contested = [pid for pid in both if b4_assign.get(pid) or b5_assign.get(pid)]
    same_contested = sum(
        1 for pid in contested if b4_assign.get(pid) == b5_assign.get(pid)
    )
    print(f"\n  Same flight, all sampled     {100 * same / len(both):>7.1f}%   "
          f"({same:,}/{len(both):,})")
    if contested:
        print(f"  Same flight, contested set   "
              f"{100 * same_contested / len(contested):>7.1f}%   "
              f"({same_contested:,}/{len(contested):,} either arm seated)")
    else:
        print("  Contested set empty — seat supply too tight to discriminate")

    panels = [
        score(strategy="B4 collapsed", passengers=passengers, flights=flights,
              assignments=b4_assign, model_calls=b4_metrics.model_calls,
              cost_usd=b4_metrics.cost_usd),
        score(strategy="B5 uncollapsed", passengers=passengers, flights=flights,
              assignments=b5_assign, model_calls=b5_metrics.model_calls,
              cost_usd=b5_metrics.cost_usd),
    ]
    print(f"\n  {'arm':<18}{'seated':>8}{'sat(w)':>9}{'sat(blind)':>12}"
          f"{'p95 wait':>10}{'gini':>8}{'calls':>8}{'cost':>10}")
    print(f"  {'-' * 83}")
    for pan in panels:
        print(f"  {pan.strategy:<18}{pan.souls_seated:>8,}"
              f"{pan.satisfaction_tier_weighted:>9.3f}"
              f"{pan.satisfaction_tier_blind:>12.3f}{pan.p95_wait:>10.1f}"
              f"{pan.gini_wait:>8.3f}{pan.model_calls:>8,}{pan.cost_usd:>10.4f}")

    delta = (panels[0].satisfaction_tier_weighted
             - panels[1].satisfaction_tier_weighted)
    print(f"\n  Outcome delta (B4 − B5), tier-weighted satisfaction: {delta:+.4f}")
    print(f"  Cost ratio within this sample: "
          f"{b5_metrics.model_calls / max(b4_metrics.model_calls, 1):.1f}× "
          f"— and it grows with population, while agreement does not.")

    # -- where collapse is lossy ----------------------------------------------
    worst = sorted(
        ((k, sum(v) / len(v), len(v)) for k, v in by_cohort.items()),
        key=lambda t: t[1],
    )[:5]
    if worst:
        print("\n  Worst-agreeing cohorts — where the bucket loses signal:\n")
        for key, rate, n in worst:
            print(f"    {100 * rate:>5.1f}%  n={n:<4} {key}")

    out = Path("data/fidelity.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "population": population,
        "schema_version": SCHEMA_VERSION,
        "sample": len(passengers),
        "cohorts": len(members),
        "per_cohort": per_cohort,
        "compared": len(both),
        "exact_agreement": sum(exact) / len(exact),
        "per_field": {f: sum(v) / len(v) for f, v in per_field.items()},
        "numeric": {f: {"bias": b, "spearman": r} for f, (b, r) in numerics.items()},
        "same_flight": same / len(both),
        "same_flight_contested": (
            same_contested / len(contested) if contested else None
        ),
        "contested": len(contested),
        "b4_calls": b4_metrics.model_calls,
        "b5_calls": b5_metrics.model_calls,
        "panels": [asdict(p) for p in panels],
        "worst_cohorts": [{"key": k, "agreement": r, "n": n} for k, r, n in worst],
    }, indent=2))
    print(f"\n  Written to {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", type=int, default=20_000)
    ap.add_argument("--cohorts", type=int, default=40)
    ap.add_argument("--per-cohort", type=int, default=15)
    ap.add_argument("--concurrency", type=int, default=32)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(
        args.population, args.cohorts, args.per_cohort, args.concurrency, FIXED,
    )))
