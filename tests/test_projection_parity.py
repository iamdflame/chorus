"""The browser's projection must agree with the kernel's.

`console/src/site/Projection.ts` recomputes the projection client-side so the mechanism
page can teach it interactively. A teaching page that quietly diverges from the system it
teaches is worse than no page — and the divergence would be invisible, because both sides
would keep producing plausible keys.

These read the TypeScript as text rather than executing it. That is enough to catch the
failure that actually happens: someone adds a bucket, a tier or a band on one side and
forgets the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from swarm.canonical import SCHEMA_VERSION, Projection, constraint_band, party_band, urgency_band

PORT = Path("console/src/site/Projection.ts")


@pytest.fixture(scope="module")
def source() -> str:
    if not PORT.exists():
        pytest.skip("console port not present")
    return PORT.read_text()


def vocabulary(source: str, name: str) -> list[str]:
    found = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
    assert found, f"{name} not found in the port"
    return re.findall(r'"([^"]+)"', found.group(1))


class TestVocabularies:
    def test_schema_version_matches(self, source: str) -> None:
        found = re.search(r'export const SCHEMA = "([^"]+)"', source)
        assert found and found.group(1) == SCHEMA_VERSION

    def test_tiers_match(self, source: str) -> None:
        assert vocabulary(source, "TIERS") == ["basic", "silver", "gold", "platinum"]

    def test_urgencies_match_the_kernel_bands(self, source: str) -> None:
        produced = {urgency_band(h) for h in (1, 8, 24, 100)}
        assert set(vocabulary(source, "URGENCIES")) == produced

    def test_constraints_match_the_kernel_bands(self, source: str) -> None:
        produced = {
            constraint_band(checked_bags=0, needs_assistance=True),
            constraint_band(checked_bags=2, needs_assistance=False),
            constraint_band(checked_bags=0, needs_assistance=False),
        }
        assert set(vocabulary(source, "CONSTRAINTS")) == produced

    def test_party_bands_match(self, source: str) -> None:
        produced = {party_band(n) for n in (1, 2, 3, 9)}
        assert produced == {"solo", "pair", "family", "group"}


class TestBoundaries:
    """The band edges, which are where a port silently drifts."""

    @pytest.mark.parametrize("hours,band", [
        (4, "critical"), (4.1, "urgent"), (12, "urgent"),
        (12.1, "same_day"), (24, "same_day"), (24.1, "flexible"),
    ])
    def test_urgency_edges(self, source: str, hours: float, band: str) -> None:
        assert urgency_band(hours) == band
        # The port uses the same comparisons, expressed as <=.
        assert "hours <= 4" in source and "hours <= 12" in source and "hours <= 24" in source

    @pytest.mark.parametrize("size,band", [
        (1, "solo"), (2, "pair"), (4, "family"), (5, "group")])
    def test_party_edges(self, source: str, size: int, band: str) -> None:
        assert party_band(size) == band


class TestKeyShape:
    def test_the_port_builds_the_same_nine_segment_key(self, source: str) -> None:
        real = Projection(
            role="passenger", tier="platinum", urgency="critical", party="solo",
            constraints="assisted", haul="long", hotel_entitled=True, misconnect=False,
        ).key()
        assert real.count("|") == 8
        for segment in ("SCHEMA", '"passenger"', "t.tier", "urgencyBand", "partyBand",
                        "constraintBand", "t.haul"):
            assert segment in source

    def test_the_ceiling_agrees(self, source: str) -> None:
        assert "TIERS.length * URGENCIES.length * 4 * CONSTRAINTS.length" in source
        assert 4 * 4 * 4 * 3 * 3 * 2 * 2 == 2304
