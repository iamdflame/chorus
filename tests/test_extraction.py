"""Tests for the stage that makes the model load-bearing.

Two things need guarding here. The corpus must not describe itself — a message containing
the bucket vocabulary turns extraction into string matching and the whole comparison
becomes worthless. And the control must stay competent, because a strawman baseline is
how a project convinces itself of something untrue.
"""

from __future__ import annotations

import pytest

from extract import keyword
from extract.situation import CONSTRAINTS, PARTY, TIERS, URGENCY, Extracted, parse
from intake.corpus import corpus_stats, jargon_leaks, load_corpus
from swarm.canonical import Projection


# -- corpus integrity ---------------------------------------------------------

@pytest.fixture(scope="module")
def corpus():
    messages = load_corpus()
    if not messages:
        pytest.skip("no corpus; run scripts/build_corpus.py")
    return messages


def test_the_corpus_does_not_describe_itself(corpus):
    """If messages contain category words, extraction is string matching."""
    leaking = [m.id for m in corpus if jargon_leaks(m.text)]
    assert not leaking, f"{len(leaking)} messages contain bucket vocabulary: {leaking[:5]}"


def test_the_corpus_is_genuinely_varied(corpus):
    stats = corpus_stats(corpus)
    assert stats["distinct_texts"] == stats["messages"], "duplicate messages in the corpus"
    assert stats["languages"] >= 5, "too few languages to claim unbounded input"
    assert stats["registers"] >= 6


def test_every_message_carries_exact_ground_truth(corpus):
    """Known by construction: the message was written from the situation."""
    for message in corpus[:200]:
        assert set(message.truth) >= {"tier", "urgency", "party", "constraints"}
        assert message.truth["tier"] in TIERS
        assert message.truth["urgency"] in URGENCY
        assert message.truth["party"] in PARTY
        assert message.truth["constraints"] in CONSTRAINTS


def test_the_corpus_covers_a_wide_slice_of_the_lattice(corpus):
    cells = {
        "|".join(m.truth[f] for f in ("tier", "urgency", "party", "constraints"))
        for m in corpus
    }
    assert len(cells) >= 100, (
        f"only {len(cells)} situation cells represented; a corpus concentrated in a few "
        "cells cannot test extraction across the lattice"
    )


# -- the control --------------------------------------------------------------

@pytest.mark.parametrize("text,field,expected", [
    ("my mother is 84 and needs a wheelchair", "constraints", "assisted"),
    ("no checked bags at all, just hand luggage", "constraints", "unencumbered"),
    ("our suitcases are in the hold", "constraints", "checked_bags"),
    ("there are six of us", "party", "group"),
    ("travelling on my own", "party", "solo"),
    ("my wife and I", "party", "pair"),
    ("no rush, whenever suits", "urgency", "flexible"),
    ("I need to be there within the next few hours", "urgency", "critical"),
])
def test_the_control_handles_what_a_competent_regex_should(text, field, expected):
    """A strawman control proves nothing, so these are the cases it must not fail."""
    got = keyword.extract("t", text).projection.to_dict()
    assert got[field] == expected, f"control failed on {text!r}: {field}={got[field]}"


def test_the_control_handles_negation():
    assert keyword.extract("t", "we have no checked bags").projection.constraints == "unencumbered"


def test_the_control_reads_more_than_one_language():
    spanish = keyword.extract("t", "necesito una silla de ruedas para mi madre")
    assert spanish.projection.constraints == "assisted", (
        "the control defaults on non-English input, which would make the comparison unfair"
    )


def test_the_control_does_not_fabricate_confidence():
    """It has no calibrated notion of confidence; inventing one would flatter it."""
    got = keyword.extract("t", "anything")
    assert set(got.confidence.values()) == {0.5}
    assert got.evidence == {}


# -- extraction plumbing ------------------------------------------------------

def test_out_of_range_values_are_coerced_not_trusted():
    got = parse("m", {"tier": "diamond", "urgency": "eventually",
                      "party": "17", "constraints": "levitating"})
    assert got.projection.tier in TIERS
    assert got.projection.urgency in URGENCY
    assert got.projection.party in PARTY
    assert got.projection.constraints in CONSTRAINTS


def test_confidence_is_clamped():
    got = parse("m", {"tier": "gold", "urgency": "urgent", "party": "solo",
                      "constraints": "unencumbered",
                      "confidence": {"tier": 4.2, "urgency": -1, "party": None}})
    assert all(0.0 <= v <= 1.0 for v in got.confidence.values())


def test_evidence_spans_are_checked_against_the_message():
    """A cited span that is not in the message is a fabrication, and an audit trail built
    on fabrications is worse than none."""
    got = Extracted(
        message_id="m",
        projection=Projection(role="passenger", tier="basic", urgency="urgent",
                              party="solo", constraints="assisted"),
        evidence={"constraints": "needs a wheelchair", "tier": "I am platinum"},
    )
    checked = got.evidence_is_quoted("my father needs a wheelchair at the gate")
    assert checked["constraints"] is True
    assert checked["tier"] is False
