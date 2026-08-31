"""Structured logs, because an empty Cloud Logging stream reads as an unmonitored system.

The reasoning path is covered by the causal DAG. This covers the operational path — the
container that will not start, the permission denial, the quota error that outlived its
retries — none of which are effects, because none of them are the fleet reasoning.
"""

from __future__ import annotations

import json

import pytest

from obs import logging as obslog


def emitted(capsys) -> list[dict]:
    out = capsys.readouterr().out.strip().splitlines()
    return [json.loads(line) for line in out if line.startswith("{")]


class TestShape:
    def test_every_line_is_one_json_object(self, capsys) -> None:
        """Cloud Run ingests stdout as structured entries only if each line parses."""
        obslog.info("boot", backend="firestore")
        obslog.error("nope", reason="PermissionDenied")
        lines = emitted(capsys)
        assert len(lines) == 2
        assert all(isinstance(x, dict) for x in lines)

    def test_severity_is_the_field_cloud_logging_reads(self, capsys) -> None:
        obslog.warn("degraded")
        assert emitted(capsys)[0]["severity"] == "WARNING"

    def test_context_is_structured_not_formatted_into_the_message(self, capsys) -> None:
        """A message that has been string-formatted is a message you cannot query."""
        obslog.info("run finished", run_id="abc", agents=20_000)
        line = emitted(capsys)[0]
        assert line["message"] == "run finished"
        assert line["run_id"] == "abc" and line["agents"] == 20_000


class TestTraceCorrelation:
    def test_a_trace_id_is_fully_qualified(self, capsys, monkeypatch) -> None:
        """Cloud Logging wants the resource name, not a bare hex id, or the log and the
        span never point at each other."""
        monkeypatch.setattr(obslog, "_PROJECT", "demo-project")
        obslog.error("boom", trace_id="a1b2c3")
        line = emitted(capsys)[0]
        assert line["logging.googleapis.com/trace"] == "projects/demo-project/traces/a1b2c3"

    def test_no_project_omits_the_field_rather_than_emitting_a_broken_one(
        self, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(obslog, "_PROJECT", "")
        obslog.error("boom", trace_id="a1b2c3")
        assert "logging.googleapis.com/trace" not in emitted(capsys)[0]


class TestRobustness:
    def test_an_unserialisable_field_does_not_lose_the_line(self, capsys) -> None:
        """The line that vanishes because one field held an odd object is the line you
        needed."""
        class Odd:
            def __repr__(self) -> str:
                return "<odd>"

        obslog.info("weird", thing=Odd())
        line = emitted(capsys)[0]
        assert line["message"] == "weird"

    def test_logging_never_raises(self, capsys) -> None:
        """A logger that can fail is a liability, not an aid."""
        class Hostile:
            def __repr__(self) -> str:
                raise RuntimeError("no repr for you")

        obslog.info("hostile", thing=Hostile())  # must not propagate
        assert emitted(capsys)[0]["message"] == "hostile"


class TestOperationalEvents:
    def test_named_events_carry_their_name_as_a_field(self, capsys) -> None:
        """So a dashboard can count them without parsing prose."""
        obslog.event("run.finished", run_id="abc", cost_usd=1.94)
        line = emitted(capsys)[0]
        assert line["event"] == "run.finished"
        assert line["severity"] == "NOTICE"
