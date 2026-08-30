"""Does selective escalation buy back what collapse loses?

Offline and free: it replays the saved answers from bench.fidelity through the allocator
rather than calling the model again, so allocator and routing policy can be varied without
paying for a single token. The ordering it sweeps — worst-agreeing cohorts first — is the
obvious one and not the best one, which the output shows: the first two cohorts recover
nothing, because agreement is not the same as decision impact.

    python scripts/escalation_sweep.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.baselines import _fits, _seats, _wait
from bench.metrics import score
from bench.fidelity import sample_populated, scale_seats
from kernel.clock import FIXED
from policy.compare import agreement
from swarm.canonical import bind, project_passenger
from swarm.scenario import build_scenario

raw = json.load(open("data/fidelity_raw.json"))
POP, PER = raw["population"], raw["per_cohort"]
scenario = build_scenario(passengers=POP)
everyone = [asdict(p) for p in scenario.passengers]
projector = bind(project_passenger, FIXED)
sample, members = sample_populated(everyone, projector, cohorts=40, per_cohort=PER)
flights = scale_seats([asdict(f) for f in scenario.flights], sampled=len(sample), population=POP)
by_id = {p["id"]: p for p in sample}
ids = [pid for pid in raw["b4"] if pid in by_id]
passengers = [by_id[pid] for pid in ids]
cohort_of = raw["cohort_of"]

# Per-cohort agreement between the shared thought and individual reasoning.
per_cohort = {}
for pid in ids:
    ok = all(agreement(raw["b4"][pid], raw["b5"][pid]).values())
    per_cohort.setdefault(cohort_of[pid], []).append(ok)
ranked = sorted(per_cohort, key=lambda k: sum(per_cohort[k]) / len(per_cohort[k]))

def allocate(prefs):
    seats = _seats(flights); by_wait = sorted(flights, key=_wait); out = {}
    def rank(p): return -float(prefs.get(p["id"], {}).get("urgency_score", 50))
    for p in sorted(passengers, key=rank):
        pr = prefs.get(p["id"])
        if not pr: continue
        party = int(p.get("party_size", 1))
        for f in by_wait:
            if seats.get(f["id"], 0) < party: continue
            if not _fits(f, p, pr): continue
            seats[f["id"]] -= party; out[p["id"]] = f["id"]; break
    return out

def panel(prefs, name):
    return score(strategy=name, passengers=passengers, flights=flights,
                 assignments=allocate(prefs))

base = panel(raw["b4"], "B4")
top  = panel(raw["b5"], "B5")
span = top.satisfaction_tier_weighted - base.satisfaction_tier_weighted
n_cohorts = len(per_cohort)
print(f"\n  Escalating the worst-agreeing cohorts, cheapest first")
print(f"  {n_cohorts} cohorts, {len(ids)} travellers. Collapse costs "
      f"{span:.1f} weighted satisfaction.\n")
print(f"  {'escalated':>10}{'travellers':>12}{'calls':>8}{'sat(w)':>9}"
      f"{'gap closed':>12}{'cost':>9}")
print("  " + "-"*62)
for k in (0, 2, 4, 8, 12, 20, n_cohorts):
    escalated = set(ranked[:k])
    mixed = {pid: (raw["b5"][pid] if cohort_of[pid] in escalated else raw["b4"][pid])
             for pid in ids}
    people = sum(1 for pid in ids if cohort_of[pid] in escalated)
    # cost: one call per non-escalated cohort + one per escalated traveller
    calls = (n_cohorts - k) + people
    pan = panel(mixed, f"esc{k}")
    closed = (pan.satisfaction_tier_weighted - base.satisfaction_tier_weighted) / span if span else 0
    print(f"  {k:>10}{people:>12}{calls:>8}{pan.satisfaction_tier_weighted:>9.1f}"
          f"{100*closed:>11.0f}%{calls/n_cohorts:>8.1f}x")
