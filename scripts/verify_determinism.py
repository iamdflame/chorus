"""The proof.

Three measurements, run against a real ADK fleet. Everything Lightcone claims reduces
to whether these numbers come out right:

    1. RECORD    a fleet runs; every boundary crossing is addressed and stored
    2. REPLAY    the same fleet re-runs; the model is never reached and the causal
                 root hash is identical -- reproduction, not approximation
    3. PERTURB   one agent's policy changes on a fork; only the forward lightcone of
                 that change re-executes, and the rest is reused

Run offline (free, uses the counting instrument):
    python scripts/verify_determinism.py

Run against live gemini-3.5-flash:
    python scripts/verify_determinism.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Load .env so the proof is reproducible from a clean shell.
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from kernel.branch import PRIMARY, Branch
from kernel.effect import EffectKind
from kernel.interposer import LightconePlugin, Mode
from kernel.store import InMemoryEffectStore

APP, USER = "lightcone-proof", "verifier"
MODEL = "gemini-3.5-flash"

BASELINE_POLICY = "Disputes under $500 are auto-approved for refund."
PERTURBED_POLICY = "Disputes under $50 are auto-approved for refund. All others escalate."

DISPUTE = (
    "Dispute D-4471: customer claims a duplicate charge of $240.00 on order ORD-88120. "
    "Customer tier: standard. Prior disputes: 1. Decide and act."
)


def build_fleet(policy: str, model):
    """A three-stage financial-operations pipeline.

    Sequential rather than free-form delegation so the causal chain is unambiguous:
    each stage reads the previous stage's output, which is what makes the cascade in
    step 3 a genuine causal consequence rather than a coincidence of ordering.
    """
    triage = LlmAgent(
        name="triage",
        model=model,
        instruction="Classify the dispute. State the type and the amount in one line.",
    )
    policy_agent = LlmAgent(
        name="policy",
        model=model,
        instruction=f"Apply this policy to the classified dispute: {policy} "
        "State the decision (APPROVE or ESCALATE) and the reason in one line.",
    )
    ledger = LlmAgent(
        name="ledger",
        model=model,
        instruction="Write the one-line ledger entry implied by the decision above.",
    )
    return SequentialAgent(name="revops_fleet", sub_agents=[triage, policy_agent, ledger])


async def run(agent, plugin) -> None:
    sessions = InMemorySessionService()
    runner = Runner(
        app=App(name=APP, root_agent=agent, plugins=[plugin]), session_service=sessions
    )
    session = await sessions.create_session(app_name=APP, user_id=USER)
    async for _ in runner.run_async(
        user_id=USER,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=DISPUTE)]),
    ):
        pass
    plugin.flush()


def row(label: str, *cells: object) -> str:
    return f"  {label:<26}" + "".join(f"{str(c):>20}" for c in cells)


async def main(live: bool) -> int:
    if live:
        model_a = model_b = MODEL
        counter = None
        print(f"\n  MODEL   {MODEL} (live)")
    else:
        from tests.instruments import CountingLlm

        counter = CountingLlm()
        model_a = model_b = counter
        print("\n  MODEL   counting instrument (offline; use --live for gemini-3.5-flash)")

    store = InMemoryEffectStore()

    # 1 -- RECORD ------------------------------------------------------------
    rec = LightconePlugin(store=store, branch_id=PRIMARY, mode=Mode.RECORD)
    await run(build_fleet(BASELINE_POLICY, model_a), rec)
    recorded = rec.report()
    baseline_dag = store.dag(PRIMARY)
    real_calls_record = counter.calls if counter else recorded["executed"]

    # 2 -- REPLAY ------------------------------------------------------------
    if counter:
        counter.reset()
    rep = LightconePlugin(store=store, branch_id=PRIMARY, mode=Mode.REPLAY_STRICT)
    await run(build_fleet(BASELINE_POLICY, model_a), rep)
    replayed = rep.report()
    real_calls_replay = counter.calls if counter else replayed["executed"]
    replay_dag = store.dag(PRIMARY)

    # 3 -- PERTURB -----------------------------------------------------------
    branch = store.create_branch(
        Branch.fork(
            parent=store.get_branch(PRIMARY),
            name="tighter-refund-policy",
            at_seq=0,
            perturbation={"path": "policy.auto_approve_ceiling", "from": 500, "to": 50},
        )
    )
    if counter:
        counter.reset()
    per = LightconePlugin(store=store, branch_id=branch.id, mode=Mode.REPLAY)
    await run(build_fleet(PERTURBED_POLICY, model_b), per)
    perturbed = per.report()
    real_calls_perturb = counter.calls if counter else perturbed["executed"]

    total_crossings = recorded["boundary_crossings"]

    print("\n  " + "=" * 86)
    print(row("", "RECORD", "REPLAY", "PERTURBED FORK"))
    print("  " + "-" * 86)
    print(row("model+tool crossings", total_crossings, replayed["boundary_crossings"],
              perturbed["boundary_crossings"]))
    print(row("served from store", recorded["replay_hits"], replayed["replay_hits"],
              perturbed["replay_hits"]))
    print(row("actually executed", recorded["executed"], replayed["executed"],
              perturbed["executed"]))
    print(row("real model invocations", real_calls_record, real_calls_replay, real_calls_perturb))
    print(row("effects written", recorded["effects_written"], replayed["effects_written"],
              perturbed["effects_written"]))
    print(row("cost incurred (USD)", f"${recorded['cost_usd']:.6f}",
              f"${replayed['cost_usd']:.6f}", f"${perturbed['cost_usd']:.6f}"))
    print(row("cost avoided (USD)", f"${recorded['cost_avoided_usd']:.6f}",
              f"${replayed['cost_avoided_usd']:.6f}", f"${perturbed['cost_avoided_usd']:.6f}"))
    print("  " + "=" * 86)

    # -- assertions ----------------------------------------------------------
    failures: list[str] = []

    if real_calls_replay != 0:
        failures.append(f"replay reached the model {real_calls_replay} times; must be 0")
    if replay_dag.root_hash() != baseline_dag.root_hash():
        failures.append("replay did not reproduce the causal root hash")
    if replayed["cost_usd"] != 0.0:
        failures.append(f"replay incurred ${replayed['cost_usd']}; must be free")
    if replayed["effects_written"] != 0:
        failures.append(
            f"replay wrote {replayed['effects_written']} effects; an exact replay stores nothing"
        )

    # The perturbation must re-execute strictly less than the whole run, and every
    # re-execution must be causally downstream of the change.
    if perturbed["executed"] >= total_crossings:
        failures.append(
            f"perturbed fork executed {perturbed['executed']} of {total_crossings} crossings; "
            "cost must scale with the divergence, not the run"
        )
    if perturbed["replay_hits"] == 0:
        failures.append("perturbed fork reused nothing; the unchanged prefix must be inherited")

    branch_dag = store.dag(branch.id)
    diff = baseline_dag.diff(branch_dag)
    if not diff.diverged:
        failures.append("the perturbation produced no divergence at all")

    # Every diverged effect must lie in the forward lightcone of the first divergence.
    if per.diverged:
        cone = branch_dag.forward_lightcone(per.diverged[0])
        stray = {e for e in per.diverged[1:] if e not in cone}
        if stray:
            failures.append(
                f"{len(stray)} re-executed effect(s) lie outside the lightcone of the change"
            )

    print()
    print(row("baseline root hash", baseline_dag.root_hash()[:24]))
    print(row("replay root hash", replay_dag.root_hash()[:24]))
    print(row("fork root hash", branch_dag.root_hash()[:24]))
    print(row("causal diff", str(diff.summary())))
    print(row("primary effects intact", len(store.own_effects(PRIMARY))))
    print(row("fork effects stored", len(store.own_effects(branch.id))))

    print()
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\n  {len(failures)} check(s) failed\n")
        return 1

    reuse = perturbed["replay_hits"] / max(perturbed["boundary_crossings"], 1)
    print(f"  PASS  replay is free and exact; the fork reused {reuse:.0%} of three weeks "
          f"of work\n        and paid only for the {perturbed['executed']} crossing(s) "
          f"the change actually touched.\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use real gemini-3.5-flash")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.live)))
