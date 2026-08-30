"""Routing decides who gets a shared thought and who gets a full-price one.

It escalated 26 travellers in 30 by reading confidence over fields whose extracted value
is thrown away. These pin the corrected behaviour so it cannot silently return.
"""

from __future__ import annotations

from extract.situation import Extracted
from swarm.canonical import Projection
from swarm.pipeline import (
    ESCALATION_THRESHOLD,
    MESSAGE_SOURCED,
    RECORD_SOURCED,
    PipelineReport,
    message_address,
    plan,
    route,
    situations,
)


def made(**confidence: float) -> Extracted:
    return Extracted(
        message_id="MSG-1",
        projection=Projection(
            role="passenger", tier="basic", urgency="flexible",
            party="solo", constraints="unencumbered",
        ),
        confidence=confidence,
    )


class TestSources:
    def test_the_two_halves_do_not_overlap(self) -> None:
        assert not set(MESSAGE_SOURCED) & set(RECORD_SOURCED)

    def test_every_routed_field_is_one_the_model_is_asked_for(self) -> None:
        """Routing on a field the extractor never reports would read 0.0 and escalate
        every traveller — the failure this file exists to prevent."""
        reported = made(urgency=0.9, party=0.9, constraints=0.9, tier=0.5)
        for field in MESSAGE_SOURCED:
            assert field in reported.confidence


class TestRoute:
    def test_confident_traveller_collapses(self) -> None:
        assert route(made(urgency=0.9, party=0.9, constraints=0.9, tier=0.5)) == "collapse"

    def test_doubt_about_a_record_sourced_field_does_not_escalate(self) -> None:
        """The regression. Tier confidence of 0.5 is the model's "I don't know" about a
        value the booking record holds as fact, so it must not cost a full-price call."""
        confident = made(urgency=0.95, party=0.95, constraints=0.95, tier=0.05)
        assert route(confident) == "collapse"

    def test_doubt_about_a_message_sourced_field_does_escalate(self) -> None:
        """The rule must still bite where it matters: an unsure bucket may be wrong."""
        unsure = made(urgency=0.2, party=0.95, constraints=0.95, tier=0.99)
        assert route(unsure) == "escalate"

    def test_threshold_is_exclusive_at_the_boundary(self) -> None:
        at = made(urgency=ESCALATION_THRESHOLD, party=1.0, constraints=1.0)
        below = made(urgency=ESCALATION_THRESHOLD - 0.01, party=1.0, constraints=1.0)
        assert route(at) == "collapse"
        assert route(below) == "escalate"

    def test_a_failed_extraction_never_collapses(self) -> None:
        broken = Extracted(
            message_id="MSG-2",
            projection=Projection(
                role="passenger", tier="basic", urgency="flexible",
                party="solo", constraints="unencumbered",
            ),
            confidence={"urgency": 1.0, "party": 1.0, "constraints": 1.0},
            error="TimeoutError",
        )
        assert route(broken) == "escalate"

    def test_a_question_outranks_confidence(self) -> None:
        asking = made(urgency=1.0, party=1.0, constraints=1.0)
        asking = Extracted(**{**asking.__dict__, "clarifying_question": "Which airport?"})
        assert route(asking) == "ask"

    def test_no_confidence_at_all_escalates(self) -> None:
        """Absence of evidence is not confidence. An empty dict must not read as 1.0."""
        assert route(made()) == "escalate"


class TestPlan:
    def test_every_traveller_lands_in_exactly_one_bucket(self) -> None:
        people = [
            made(urgency=0.9, party=0.9, constraints=0.9),
            made(urgency=0.1, party=0.9, constraints=0.9),
            made(),
        ]
        buckets = plan(people)
        assert sum(len(v) for v in buckets.values()) == len(people)


class TestAddressing:
    def test_the_same_sentence_is_one_extraction(self) -> None:
        assert message_address("Can I get out tonight?") == message_address(
            "  can i get OUT tonight?  "
        )

    def test_different_sentences_are_not(self) -> None:
        assert message_address("I need to leave tonight") != message_address(
            "I need to leave tomorrow"
        )


class TestReport:
    def test_blended_is_never_flattered_by_the_collapsible_stage(self) -> None:
        """The headline must be the blend. If extraction dominates, the blend is small
        even when the collapsible stage looks spectacular — that is the point."""
        report = PipelineReport(entities=20_000)
        report.extraction.calls = 2_000
        report.elicitation.calls = 200
        assert report.elicitation_collapse == 100.0
        assert report.blended_collapse < 20.0

    def test_a_pipeline_that_saves_nothing_reports_no_gain(self) -> None:
        report = PipelineReport(entities=100)
        report.extraction.calls = 100
        report.elicitation.calls = 100
        assert report.blended_collapse == 1.0
