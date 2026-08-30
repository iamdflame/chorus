"""The evidence rig must not be able to flatter the product.

Two properties matter more than any individual number here:

    the scorer cannot see which arm produced a plan
    a preference set recorded against one world cannot be scored against another

The second is the failure this project is most prone to — an artefact outliving the world
it describes, producing a plausible table full of wrong numbers.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from bench.baselines import b0_random, b1_first_come, b2_rules, rule_preferences
from bench.metrics import gini, percentile, score
from bench.run import load_preferences, scenario_fingerprint
from swarm.scenario import build_scenario


@pytest.fixture(scope="module")
def world():
    scenario = build_scenario(passengers=1200)
    return ([asdict(p) for p in scenario.passengers],
            [asdict(f) for f in scenario.flights])


def test_gini_bounds():
    assert gini([5, 5, 5, 5]) == 0.0
    assert gini([0, 0, 0, 20]) > 0.7
    assert gini([]) == 0.0


def test_percentile_is_monotonic():
    values = [float(i) for i in range(1, 101)]
    assert percentile(values, 0.5) <= percentile(values, 0.95) <= percentile(values, 1.0)


def test_random_is_a_floor_the_others_clear(world):
    passengers, flights = world
    def sat(fn):
        return score(strategy="x", passengers=passengers, flights=flights,
                     assignments=fn(passengers, flights)).satisfaction_tier_blind
    assert sat(b1_first_come) > sat(b0_random), (
        "first-come did not beat random; the metric is satisfied by noise"
    )


def test_the_scorer_cannot_see_the_strategy(world):
    """Identical assignments must score identically regardless of the label."""
    passengers, flights = world
    assignments = b1_first_come(passengers, flights)
    a = score(strategy="B1", passengers=passengers, flights=flights, assignments=assignments)
    b = score(strategy="totally different name", passengers=passengers, flights=flights,
              assignments=assignments)
    assert a.satisfaction_tier_weighted == b.satisfaction_tier_weighted
    assert a.gini_wait == b.gini_wait


def test_tier_blind_and_tier_weighted_can_disagree(world):
    """The panel exists to surface redistribution. If the two metrics always agreed it
    would be measuring one thing twice."""
    passengers, flights = world
    rules = score(strategy="B2", passengers=passengers, flights=flights,
                  assignments=b2_rules(passengers, flights))
    fcfs = score(strategy="B1", passengers=passengers, flights=flights,
                 assignments=b1_first_come(passengers, flights))
    weighted = rules.satisfaction_tier_weighted - fcfs.satisfaction_tier_weighted
    blind = rules.satisfaction_tier_blind - fcfs.satisfaction_tier_blind
    assert weighted > 0 > blind, (
        "expected the rule arm to win on tier-weighted and lose on tier-blind; "
        "if it no longer does, the redistribution warning in bench/run.py is stale"
    )


def test_stale_preferences_are_refused(tmp_path, world):
    """A preference set from another world must never be scored silently."""
    passengers, _ = world
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({
        "scenario_fingerprint": "definitely-not-this-world",
        "preferences": {p["id"]: {} for p in passengers},
    }))
    prefs, why = load_preferences(path, passengers)
    assert prefs is None and "refusing to score stale" in why


def test_unstamped_preferences_are_refused(tmp_path, world):
    passengers, _ = world
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"preferences": {p["id"]: {} for p in passengers}}))
    prefs, why = load_preferences(path, passengers)
    assert prefs is None and "predates fingerprinting" in why


def test_matching_preferences_are_accepted(tmp_path, world):
    passengers, _ = world
    path = tmp_path / "good.json"
    path.write_text(json.dumps({
        "scenario_fingerprint": scenario_fingerprint(passengers),
        "preferences": {p["id"]: rule_preferences(p) for p in passengers},
    }))
    prefs, why = load_preferences(path, passengers)
    assert prefs is not None and why == "ok"


def test_fingerprint_moves_with_the_world(world):
    passengers, _ = world
    other = [asdict(p) for p in build_scenario(passengers=1200, seed=4242).passengers]
    assert scenario_fingerprint(passengers) != scenario_fingerprint(other)
