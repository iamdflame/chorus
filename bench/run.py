"""Run every baseline, score them identically, print the whole panel.

    python -m bench.run                 # offline arms only (B0-B3)
    python -m bench.run --preferences data/preferences.json

The rule this file exists to enforce: **every arm that can run, runs, and all of them are
printed.** There is no flag to hide a losing arm. B2 — hand-written rules with no model —
beat v1 and is in the default output.

Preferences captured from a live swarm are fingerprinted against the scenario they were
produced for. If the scenario has moved, they are refused rather than silently scored,
because a stale preference set produces a plausible table full of wrong numbers, which is
worse than no table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bench.baselines import (
    allocate_by_preference,
    b0_random,
    b1_first_come,
    b2_rules,
    b3_greedy_upper_bound,
    rule_preferences,
)
from bench.metrics import Panel, score, table
from kernel.clock import FIXED
from kernel.effect import hash_payload
from swarm.canonical import bind, collapse, project_passenger
from swarm.scenario import build_scenario


def scenario_fingerprint(passengers: list[dict]) -> str:
    """Identifies the exact population a preference set was produced for.

    Cheap insurance against the failure this project is most prone to: an artefact
    recorded against one world being scored against another and nobody noticing, because
    the numbers still look reasonable.
    """
    return hash_payload(
        [
            [p["id"], p["scheduled_departure"], p["tier"], p["party_size"]]
            for p in passengers
        ]
    )[:16]


def load_preferences(path: Path, passengers: list[dict]) -> tuple[dict | None, str]:
    if not path.exists():
        return None, f"{path} not found"
    payload = json.loads(path.read_text())
    prefs = payload.get("preferences", {})
    stamped = payload.get("scenario_fingerprint")
    current = scenario_fingerprint(passengers)
    if stamped is None:
        return None, (
            f"{path} predates fingerprinting and cannot be matched to this scenario "
            "— regenerate with scripts/prove_swarm.py"
        )
    if stamped != current:
        return None, (
            f"{path} was recorded against scenario {stamped}, this is {current} "
            "— refusing to score stale preferences"
        )
    missing = [p["id"] for p in passengers if p["id"] not in prefs]
    if missing:
        return None, f"{path} covers {len(prefs)} of {len(passengers)} passengers"
    return prefs, "ok"


def main(count: int, preferences_path: str | None) -> int:
    scenario = build_scenario(passengers=count)
    passengers = [asdict(p) for p in scenario.passengers]
    flights = [asdict(f) for f in scenario.flights]
    cohorts = collapse(passengers, bind(project_passenger, FIXED))

    print(f"\n  {count:,} travellers · {sum(p['party_size'] for p in passengers):,} souls · "
          f"{sum(f['seats_free'] for f in flights):,} seats · {len(cohorts)} cohorts")
    print(f"  scenario fingerprint {scenario_fingerprint(passengers)}\n")

    panels: list[Panel] = []
    rules = {p["id"]: rule_preferences(p) for p in passengers}

    panels.append(score(strategy="B0  random", passengers=passengers, flights=flights,
                        assignments=b0_random(passengers, flights)))
    panels.append(score(strategy="B1  first-come", passengers=passengers, flights=flights,
                        assignments=b1_first_come(passengers, flights)))
    panels.append(score(strategy="B2  rules, zero LLM", passengers=passengers, flights=flights,
                        assignments=b2_rules(passengers, flights)))
    panels.append(score(strategy="B3  greedy upper bound", passengers=passengers, flights=flights,
                        assignments=b3_greedy_upper_bound(
                            passengers, flights, preferences=rules)))

    note = None
    if preferences_path:
        prefs, why = load_preferences(Path(preferences_path), passengers)
        if prefs is None:
            note = why
        else:
            panels.append(score(
                strategy="B4  Chorus (LLM)", passengers=passengers, flights=flights,
                assignments=allocate_by_preference(passengers, flights, prefs),
                model_calls=len(cohorts),
            ))

    print(table(panels))

    b1 = next(p for p in panels if p.strategy.startswith("B1"))
    print(f"\n  Seat supply is the binding constraint: every arm that fills the aircraft seats")
    print(f"  the same souls. What changes is WHICH travellers move, so tier-blind is printed")
    print(f"  beside tier-weighted and the trade-off is visible rather than buried.\n")

    for panel in panels:
        if panel.strategy.startswith("B1"):
            continue
        dw = panel.satisfaction_tier_weighted / b1.satisfaction_tier_weighted - 1
        db = panel.satisfaction_tier_blind / b1.satisfaction_tier_blind - 1
        verdict = ("redistributes toward weighted tiers"
                   if dw > 0 and db <= 0 else
                   "better on both" if dw > 0 and db > 0 else "worse")
        print(f"  {panel.strategy:<26} tier-weighted {dw:+7.1%}   tier-blind {db:+7.1%}   {verdict}")

    if note:
        print(f"\n  B4 not scored: {note}")
    print()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=8000)
    ap.add_argument("--preferences", default="data/preferences.json")
    a = ap.parse_args()
    raise SystemExit(main(a.agents, a.preferences))
