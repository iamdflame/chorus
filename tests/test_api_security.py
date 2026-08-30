"""Every one of these was an audit finding, and each has a failure mode that looks fine.

An open CORS wildcard, an unbounded integer and a missing token all behave perfectly until
somebody tries. These pin the behaviour so a later refactor cannot quietly reopen them.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.main import (
    PUBLIC_AGENT_CEILING,
    ForkRequest,
    PolicyEdit,
    SearchRequest,
    SwarmRequest,
    _ORIGINS,
    require_write,
)


class TestInputCaps:
    def test_agents_is_bounded_above(self) -> None:
        """`agents` multiplies straight into model spend."""
        with pytest.raises(ValidationError):
            SwarmRequest(agents=10_000_000)

    def test_agents_is_bounded_below(self) -> None:
        with pytest.raises(ValidationError):
            SwarmRequest(agents=0)

    def test_concurrency_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            SwarmRequest(agents=10, concurrency=10_000)

    def test_a_reasonable_request_is_accepted(self) -> None:
        assert SwarmRequest(agents=2_000, concurrency=6).agents == 2_000

    def test_search_population_is_bounded(self) -> None:
        """An unbounded population is an unbounded bill somebody else pays."""
        with pytest.raises(ValidationError):
            SearchRequest(population=10_000)

    def test_free_text_is_length_capped(self) -> None:
        with pytest.raises(ValidationError):
            PolicyEdit(text="x" * 100_000)

    def test_a_fork_needs_a_name(self) -> None:
        with pytest.raises(ValidationError):
            ForkRequest(name="", at_seq=1)

    def test_a_fork_cannot_target_a_negative_position(self) -> None:
        with pytest.raises(ValidationError):
            ForkRequest(name="what-if", at_seq=-5)


class TestCors:
    def test_the_wildcard_is_gone(self) -> None:
        """`*` with credentials turns a browsing judge into an authenticated caller of
        someone else's mutation endpoints."""
        assert "*" not in _ORIGINS


class TestWriteGuard:
    def test_an_unset_token_closes_mutations_rather_than_opening_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset secret is the most common way a control like this ends up doing
        nothing at all."""
        import api.main as main

        monkeypatch.setattr(main, "_MUTATION_TOKEN", "")
        with pytest.raises(HTTPException) as raised:
            main.require_write(authorization="Bearer anything")
        assert raised.value.status_code == 503

    def test_a_wrong_token_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.main as main

        monkeypatch.setattr(main, "_MUTATION_TOKEN", "correct-horse")
        with pytest.raises(HTTPException) as raised:
            main.require_write(authorization="Bearer wrong")
        assert raised.value.status_code == 401

    def test_a_missing_header_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.main as main

        monkeypatch.setattr(main, "_MUTATION_TOKEN", "correct-horse")
        with pytest.raises(HTTPException):
            main.require_write(authorization="")

    def test_the_right_token_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.main as main

        monkeypatch.setattr(main, "_MUTATION_TOKEN", "correct-horse")
        assert main.require_write(authorization="Bearer correct-horse") is None


class TestDemoCeiling:
    def test_the_public_ceiling_is_small_enough_to_be_survivable(self) -> None:
        """Closing the demo would protect the budget by removing the product, so it is
        bounded instead — but the bound has to actually bound something."""
        assert 0 < PUBLIC_AGENT_CEILING <= 1_000

    def test_rate_limiting_bites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import api.main as main

        monkeypatch.setattr(main, "_recent", main.defaultdict(list))
        for _ in range(main._RATE_MAX):
            assert main._rate_limited("1.2.3.4") is False
        assert main._rate_limited("1.2.3.4") is True

    def test_one_caller_cannot_exhaust_another(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.main as main

        monkeypatch.setattr(main, "_recent", main.defaultdict(list))
        for _ in range(main._RATE_MAX + 2):
            main._rate_limited("1.2.3.4")
        assert main._rate_limited("5.6.7.8") is False


class TestProductionImage:
    def test_playwright_is_not_a_production_dependency(self) -> None:
        """A browser engine and its dependency tree have no business in the image that
        serves the API."""
        from pathlib import Path

        assert "playwright" not in Path("requirements.txt").read_text()
        assert "playwright" in Path("requirements-dev.txt").read_text()
