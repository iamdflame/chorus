"""A gate anyone can write. What matters is that a denial is an effect.

Content-addressed, replayable and diffable — which is what turns "what would this fleet
have done if it had been allowed?" from a thought experiment into a branch and a diff.
"""

from __future__ import annotations

import asyncio

import pytest

from gateway.policy import (
    Decision,
    Gateway,
    Request,
    allowlist,
    argument_cap,
    default_gateway,
    denied_result,
    no_irreversible_off_primary,
)
from kernel.branch import PRIMARY
from kernel.effect import Determinism, EffectKind


def req(agent="refund_agent", tool="issue_refund", args=None, branch=PRIMARY,
        det=Determinism.EXTERNAL_IRREVERSIBLE) -> Request:
    return Request(agent=agent, tool=tool, args=args or {}, branch_id=branch,
                   determinism=det)


class TestRules:
    def test_a_tool_the_card_does_not_declare_is_refused(self) -> None:
        """The agent card stops being documentation and becomes the enforcement surface."""
        gateway = Gateway().rule("cards", allowlist({"refund_agent": {"issue_refund"}}))
        assert gateway.check(req(tool="issue_refund")).allowed
        assert not gateway.check(req(tool="send_email")).allowed

    def test_an_agent_with_no_card_is_refused_rather_than_waved_through(self) -> None:
        """Failing open on an unknown agent is how allowlists become decoration."""
        gateway = Gateway().rule("cards", allowlist({"known": {"t"}}))
        assert not gateway.check(req(agent="ghost", tool="t")).allowed

    def test_a_cap_bounds_what_an_injection_could_ask_for(self) -> None:
        gateway = Gateway().rule("cap", argument_cap("issue_refund", "amount_usd", 5_000))
        assert gateway.check(req(args={"amount_usd": 4_999})).allowed
        assert not gateway.check(req(args={"amount_usd": 5_001})).allowed

    def test_a_non_numeric_amount_is_refused_not_coerced(self) -> None:
        gateway = Gateway().rule("cap", argument_cap("issue_refund", "amount_usd", 5_000))
        assert not gateway.check(req(args={"amount_usd": "all of it"})).allowed

    def test_a_cap_ignores_tools_it_does_not_govern(self) -> None:
        gateway = Gateway().rule("cap", argument_cap("issue_refund", "amount_usd", 1))
        assert gateway.check(req(tool="get_dispute", args={"amount_usd": 99})).allowed

    def test_forced_irreversible_off_primary_is_refused(self) -> None:
        gateway = Gateway().rule("irrev", no_irreversible_off_primary)
        assert gateway.check(req(branch="what-if", args={"force": True})).allowed is False
        assert gateway.check(req(branch=PRIMARY, args={"force": True})).allowed

    def test_first_denial_wins_and_names_its_rule(self) -> None:
        gateway = default_gateway({"refund_agent": {"issue_refund"}})
        decision = gateway.check(req(args={"amount_usd": 9_999}))
        assert not decision.allowed and decision.rule == "refund-cap"

    def test_every_denial_carries_a_reason(self) -> None:
        """A denial without one is unactionable: an operator cannot tell a working
        control from a misconfiguration."""
        gateway = default_gateway({"refund_agent": {"issue_refund"}})
        for bad in (req(tool="send_email"), req(args={"amount_usd": 1e9})):
            decision = gateway.check(bad)
            assert not decision.allowed and decision.reason


class TestRefusalIsHonest:
    def test_the_agent_is_told_it_was_refused(self) -> None:
        """Not handed a fabricated success. An agent that believes it succeeded learns
        the wrong lesson, and the transcript misleads whoever reads it later."""
        result = denied_result(Decision(False, "over the cap", "refund-cap"), "issue_refund")
        assert result["status"] == "denied"
        assert result["_gateway_denied"] is True
        assert "over the cap" in result["error"]


class TestDenialsAreEffects:
    def _run(self, gateway):
        from tests.instruments import ToolCallingFleet

        return ToolCallingFleet(gateway=gateway)

    def test_a_denied_call_is_recorded_with_its_own_kind(self) -> None:
        """Written through to the store on close, so it survives whether or not the run
        reaches a flush — a refusal that only exists if the process exits cleanly is not
        an audit record."""
        from kernel.interposer import LightconePlugin
        from kernel.store import InMemoryEffectStore

        store = InMemoryEffectStore()
        plugin = LightconePlugin(
            store=store, branch_id=PRIMARY,
            gateway=default_gateway({"refund_agent": {"issue_refund"}}),
        )

        class Tool:
            name = "send_email"

        class Ctx:
            agent_name = "refund_agent"

        result = asyncio.run(plugin.before_tool_callback(
            tool=Tool(), tool_args={}, tool_context=Ctx()
        ))
        assert result is not None and result["_gateway_denied"]
        plugin.flush()
        recorded = store.own_effects(PRIMARY)
        assert [e.kind for e in recorded] == [EffectKind.GATEWAY_DENIED]
        assert recorded[0].request["rule"] == "agent-card-allowlist"

    def test_a_denial_is_addressed_so_it_replays(self) -> None:
        """The property that makes it more than a log line: the same refusal at the same
        causal position addresses identically, so a replay reproduces it."""
        from kernel.interposer import LightconePlugin
        from kernel.store import InMemoryEffectStore

        class Tool:
            name = "send_email"

        class Ctx:
            agent_name = "refund_agent"

        addresses = []
        for _ in range(2):
            store = InMemoryEffectStore()
            plugin = LightconePlugin(
                store=store, branch_id=PRIMARY,
                gateway=default_gateway({"refund_agent": {"issue_refund"}}),
            )
            asyncio.run(plugin.before_tool_callback(
                tool=Tool(), tool_args={"to": "x@y.z"}, tool_context=Ctx()
            ))
            plugin.flush()
            addresses.append(store.own_effects(PRIMARY)[0].id)
        assert addresses[0] == addresses[1]

    def test_a_permitted_call_records_no_denial(self) -> None:
        from kernel.interposer import LightconePlugin
        from kernel.store import InMemoryEffectStore

        plugin = LightconePlugin(
            store=InMemoryEffectStore(), branch_id=PRIMARY,
            gateway=default_gateway({"refund_agent": {"issue_refund"}}),
        )

        class Tool:
            name = "issue_refund"

        class Ctx:
            agent_name = "refund_agent"

        result = asyncio.run(plugin.before_tool_callback(
            tool=Tool(), tool_args={"amount_usd": 10}, tool_context=Ctx()
        ))
        assert result is None  # falls through to the real tool
        assert all(e.kind is not EffectKind.GATEWAY_DENIED for e in plugin.flush())

    def test_no_gateway_permits_everything_and_records_nothing(self) -> None:
        """Stated rather than implied — a gateway that silently defaults to open would
        be worse than none at all."""
        from kernel.interposer import LightconePlugin
        from kernel.store import InMemoryEffectStore

        plugin = LightconePlugin(store=InMemoryEffectStore(), branch_id=PRIMARY)

        class Tool:
            name = "anything_at_all"

        class Ctx:
            agent_name = "unregistered"

        result = asyncio.run(plugin.before_tool_callback(
            tool=Tool(), tool_args={}, tool_context=Ctx()
        ))
        assert result is None


class TestReport:
    def test_the_report_counts_both_sides(self) -> None:
        gateway = default_gateway({"a": {"ok"}})
        gateway.check(req(agent="a", tool="ok"))
        gateway.check(req(agent="a", tool="nope"))
        report = gateway.report()
        assert report["permitted"] == 1 and report["denied"] == 1
        assert report["denials"][0]["tool"] == "nope"
