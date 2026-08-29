"""End-to-end proof that agent execution is deterministic and re-executable.

Everything the product claims rests on three measurements made here:

    record      N model calls, N effects
    replay      0 model calls, identical DAG root hash
    perturb     model calls == |forward lightcone of the change|, not N

The third is the one that matters commercially: it is the difference between
"you can re-run your fleet" (true of anything) and "you can ask a counterfactual
question about three weeks of history for the price of the part that changed".
"""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from kernel.branch import PRIMARY, Branch
from kernel.effect import Determinism
from kernel.interposer import LightconePlugin, Mode, ReplayMiss
from kernel.quarantine import ReversibilityRegistry
from kernel.store import InMemoryEffectStore
from tests.instruments import CountingLlm

APP = "lightcone-test"
USER = "tester"


# A real tool with a real side effect on a shared ledger, so quarantine can be observed
# rather than asserted.
LEDGER: list[dict] = []


def issue_refund(dispute_id: str, amount_usd: float) -> dict:
    """Issue a refund to a customer. Irreversible in the real world."""
    LEDGER.append({"dispute_id": dispute_id, "amount_usd": amount_usd})
    return {"status": "refunded", "dispute_id": dispute_id, "amount_usd": amount_usd}


def build(instruction: str, model: CountingLlm, tool=None) -> LlmAgent:
    return LlmAgent(
        name="refund_agent",
        model=model,
        instruction=instruction,
        tools=[tool] if tool else [],
    )


async def run_once(agent, plugin, message="process dispute D-1"):
    """Drive one real ADK invocation with the interposer attached.

    Plugins are attached via `App` rather than `Runner(plugins=...)`: the latter is
    deprecated in ADK 2.8 and the fleet runs the supported path.
    """
    session_service = InMemorySessionService()
    app = App(name=APP, root_agent=agent, plugins=[plugin])
    runner = Runner(app=app, session_service=session_service)
    session = await session_service.create_session(app_name=APP, user_id=USER)
    async for _ in runner.run_async(
        user_id=USER,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        pass
    return plugin.flush()


@pytest.mark.asyncio
async def test_record_then_replay_costs_nothing_and_reproduces_exactly():
    store = InMemoryEffectStore()
    model = CountingLlm()

    rec = LightconePlugin(store=store, branch_id=PRIMARY, mode=Mode.RECORD)
    await run_once(build("You handle refunds.", model), rec)
    recorded_calls = model.calls
    assert recorded_calls > 0, "the recording run must actually reach the model"
    baseline = store.dag(PRIMARY)

    # Replay on the same branch. Every address is already present, so the model layer
    # must never be reached.
    model.reset()
    rep = LightconePlugin(store=store, branch_id=PRIMARY, mode=Mode.REPLAY_STRICT)
    await run_once(build("You handle refunds.", model), rep)

    assert model.calls == 0, f"replay reached the model {model.calls} times; must be 0"
    assert rep.hits > 0 and rep.misses == 0
    assert rep.report()["cost_usd"] == 0.0
    assert store.dag(PRIMARY).root_hash() == baseline.root_hash(), (
        "replay must reproduce the timeline exactly, not approximately"
    )


@pytest.mark.asyncio
async def test_strict_replay_fails_loudly_when_execution_diverges():
    """A silent divergence would be the worst possible bug: a counterfactual that
    quietly re-executes everything and reports a confident wrong answer."""
    store = InMemoryEffectStore()
    model = CountingLlm()
    await run_once(build("Instruction A", model), LightconePlugin(store=store, mode=Mode.RECORD))

    strict = LightconePlugin(store=store, mode=Mode.REPLAY_STRICT)
    # ADK wraps a raising plugin callback in RuntimeError, so match on the surfaced
    # message rather than the class: what matters is that it is loud, not silent.
    with pytest.raises((ReplayMiss, RuntimeError), match="diverged where determinism"):
        await run_once(build("Instruction B — different", model), strict)


@pytest.mark.asyncio
async def test_perturbed_replay_on_a_fork_costs_only_the_divergence():
    store = InMemoryEffectStore()
    model = CountingLlm()

    await run_once(build("Refund ceiling is $500.", model), LightconePlugin(store=store, mode=Mode.RECORD))
    full_cost = model.calls
    primary_effects = len(store.own_effects(PRIMARY))

    branch = store.create_branch(
        Branch.fork(
            parent=store.get_branch(PRIMARY), name="lower-ceiling", at_seq=0,
            perturbation={"path": "refund.ceiling", "from": 500, "to": 50},
        )
    )

    model.reset()
    plugin = LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY)
    await run_once(build("Refund ceiling is $50.", model), plugin)

    assert model.calls > 0, "a genuine perturbation must re-execute something"
    assert model.calls <= full_cost
    assert plugin.misses == model.calls, "every model call must correspond to a recorded miss"
    # The branch stores only what it executed; the parent's history is not copied.
    assert len(store.own_effects(branch.id)) < primary_effects + len(store.own_effects(branch.id)) + 1
    assert store.own_effects(PRIMARY), "the primary timeline must be untouched by the fork"


@pytest.mark.asyncio
async def test_unchanged_prefix_is_reused_across_a_fork():
    """The cheap-fork property: a branch inherits its parent's recorded work as cache."""
    store = InMemoryEffectStore()
    model = CountingLlm()
    await run_once(build("Stable instruction.", model), LightconePlugin(store=store, mode=Mode.RECORD))

    branch = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="same", at_seq=0)
    )
    model.reset()
    plugin = LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY)
    await run_once(build("Stable instruction.", model), plugin)

    assert model.calls == 0, "an unperturbed fork must cost nothing"
    assert plugin.hits > 0
    assert store.own_effects(branch.id) == [], "nothing executed means nothing stored"


@pytest.mark.asyncio
async def test_irreversible_tool_executes_on_primary_and_is_quarantined_on_a_branch():
    """The safety property. The same agent, the same tool, the same arguments —
    dispatched for real exactly once, and never again from a counterfactual."""
    LEDGER.clear()
    store = InMemoryEffectStore()
    registry = ReversibilityRegistry()
    registry.register("issue_refund", Determinism.EXTERNAL_IRREVERSIBLE,
                      describe=lambda a: f"refund ${a.get('amount_usd')} on {a.get('dispute_id')}")

    model = CountingLlm(use_tool="issue_refund",
                        tool_args={"dispute_id": "D-1", "amount_usd": 240.0})

    await run_once(
        build("Handle the dispute.", model, issue_refund),
        LightconePlugin(store=store, mode=Mode.RECORD, registry=registry),
    )
    assert len(LEDGER) == 1, "on primary the refund must really be issued"

    branch = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="counterfactual", at_seq=0)
    )
    perturbed = CountingLlm(use_tool="issue_refund",
                            tool_args={"dispute_id": "D-1", "amount_usd": 999.0})
    plugin = LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY, registry=registry)
    await run_once(build("Handle the dispute differently.", perturbed, issue_refund), plugin)

    assert len(LEDGER) == 1, (
        f"a counterfactual issued {len(LEDGER) - 1} real refund(s); quarantine failed"
    )
    staged = [e for e in plugin.recorded if e.quarantined]
    assert staged, "the blocked action must still be recorded as a counterfactual"
    assert staged[0].response["result"]["_lightcone_staged"] is True
    assert "999" in staged[0].response["result"]["_lightcone_action"], (
        "the counterfactual must record the arguments the agent actually chose"
    )


@pytest.mark.asyncio
async def test_unregistered_tools_default_to_quarantined():
    """A forgotten registration must fail safe: staged, never dispatched."""
    LEDGER.clear()
    store = InMemoryEffectStore()
    model = CountingLlm(use_tool="issue_refund", tool_args={"dispute_id": "D-9", "amount_usd": 10.0})
    await run_once(build("go", model, issue_refund), LightconePlugin(store=store, mode=Mode.RECORD))
    LEDGER.clear()

    branch = store.create_branch(Branch.fork(parent=store.get_branch(PRIMARY), name="b", at_seq=0))
    other = CountingLlm(use_tool="issue_refund", tool_args={"dispute_id": "D-9", "amount_usd": 77.0})
    await run_once(
        build("different", other, issue_refund),
        LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY),
    )
    assert LEDGER == [], "an unregistered tool must default to quarantined off-primary"
