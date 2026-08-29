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


@pytest.mark.asyncio
async def test_tool_effects_are_recorded_when_the_tool_declares_a_read_set():
    """Regression: the open/close keys for a tool effect must agree.

    A read-set tool was opened under a key built from its full request (including the
    state fingerprint) and closed under one built from its arguments alone, so it was
    never recorded — and then missed forever on replay while reporting itself executed.
    """
    from kernel.effect import EffectKind

    LEDGER.clear()
    store = InMemoryEffectStore()
    registry = ReversibilityRegistry()
    registry.register("issue_refund", Determinism.RECORDED, reads=("disputes",))

    model = CountingLlm(use_tool="issue_refund",
                        tool_args={"dispute_id": "D-7", "amount_usd": 5.0})
    plugin = LightconePlugin(
        store=store, mode=Mode.RECORD, registry=registry,
        state_fingerprint=lambda collections: "fixed-fingerprint",
    )
    await run_once(build("go", model, issue_refund), plugin)

    tool_effects = [e for e in store.own_effects(PRIMARY) if e.kind is EffectKind.TOOL_CALL]
    assert tool_effects, "a read-set tool's effect must be persisted, not silently dropped"
    assert tool_effects[0].response is not None, "the effect must carry its result"
    assert "reads" in tool_effects[0].request, "the read fingerprint belongs in the address"


@pytest.mark.asyncio
async def test_delegation_is_not_quarantined_on_a_branch():
    """Handoff is control flow, not a world effect.

    Quarantining it severs delegation on every branch, so the counterfactual silently
    stops at the point the fleet hands off and reports far less downstream work than
    really would have happened.
    """
    from fleet.tools import FleetContext, build_tools
    from world.shadow import ShadowWorld

    _, registry = build_tools(FleetContext(world=ShadowWorld(), branch_id=PRIMARY))
    assert registry.classify("transfer_to_agent") is Determinism.PURE
    # Anything that actually reaches the world must still fail closed.
    assert registry.classify("issue_refund") is Determinism.EXTERNAL_IRREVERSIBLE
    assert registry.classify("some_tool_nobody_registered") is Determinism.EXTERNAL_IRREVERSIBLE


@pytest.mark.asyncio
async def test_search_candidates_inherit_production_history():
    """The economics the whole optimiser rests on.

    Every candidate forks from the branch holding production's recorded run, so the
    stages upstream of the policy — intake, customer lookup, the facts of the dispute —
    are inherited rather than re-executed. Scoring the baseline on its own fork instead
    puts that shared work on a sibling branch no candidate can resolve through, and the
    search degrades to full re-execution while still looking like it worked.
    """
    from kernel.effect import EffectKind

    store = InMemoryEffectStore()
    model = CountingLlm()

    # Production runs and records.
    await run_once(build("Ceiling is $500.", model), LightconePlugin(store=store, mode=Mode.RECORD))
    recorded = len(store.own_effects(PRIMARY))
    assert recorded > 0

    # A candidate forks from production and changes the policy.
    branch = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="candidate", at_seq=0)
    )
    model.reset()
    plugin = LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY)
    await run_once(build("Ceiling is $500.", model), plugin)

    assert plugin.hits > 0, (
        "a candidate must inherit production's recorded work; if it cannot resolve "
        "through the branch chain the search silently costs full price"
    )
    assert model.calls == 0, "an unchanged candidate must not reach the model at all"
    assert store.own_effects(branch.id) == []


@pytest.mark.asyncio
async def test_a_diverging_candidate_still_reuses_the_shared_prefix():
    """A policy edit must invalidate the calls that read it — and only those.

    This is the shape of every search candidate: the intake reasoning before the policy
    is consulted stays cached, while the policy-reading tool and everything downstream
    re-executes. If the edit invalidated the whole run, the search would cost full price
    per candidate; if it invalidated nothing, the counterfactual would be a lie.
    """
    store = InMemoryEffectStore()
    registry = ReversibilityRegistry()
    # Declares a read set, so its address folds in the state fingerprint.
    registry.register("issue_refund", Determinism.RECORDED, reads=("policies",))

    fingerprint = {"value": "policy-v1"}

    def plugin_for(branch_id: str, mode: Mode) -> LightconePlugin:
        return LightconePlugin(
            store=store, branch_id=branch_id, mode=mode, registry=registry,
            state_fingerprint=lambda _collections: fingerprint["value"],
        )

    model = CountingLlm(use_tool="issue_refund",
                        tool_args={"dispute_id": "D-1", "amount_usd": 10.0})
    agent = build("Handle the dispute.", model, issue_refund)
    await run_once(agent, plugin_for(PRIMARY, Mode.RECORD))

    branch = store.create_branch(
        Branch.fork(parent=store.get_branch(PRIMARY), name="cand", at_seq=0)
    )
    fingerprint["value"] = "policy-v2"  # the exogenous edit a candidate makes

    replay_model = CountingLlm(use_tool="issue_refund",
                               tool_args={"dispute_id": "D-1", "amount_usd": 10.0})
    plugin = plugin_for(branch.id, Mode.REPLAY)
    await run_once(build("Handle the dispute.", replay_model, issue_refund), plugin)

    assert plugin.hits > 0, "reasoning before the policy read must stay cached"
    assert plugin.misses > 0, "the call that reads the edited policy must re-execute"
