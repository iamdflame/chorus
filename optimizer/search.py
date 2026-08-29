"""Policy search over recorded history.

The idea the rest of the system exists to serve: given three weeks of what your agent
fleet actually did, search the space of policies it *could* have followed, and find the
one that would have produced the best outcome — measured on the real disputes, with the
real tools, against the real data.

Every candidate is a forked timeline. Forking is O(1), the unchanged prefix of each run
replays from the store for nothing, and — the part nobody else can do — every
irreversible action the candidate chooses is quarantined rather than dispatched. That
last property is what makes searching against *production history* possible at all.
Re-running a fleet ten thousand times is not expensive so much as catastrophic: it would
send ten thousand real emails and issue ten thousand real refunds. Staging them turns an
impossible experiment into an ordinary one.

The mutation operator is Gemini itself. Given the current population and their measured
outcomes in dollars, it proposes the next generation of policy text — so the search is
guided by a model reading its own scoreboard rather than by random perturbation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fleet.domain import POLICIES
from fleet.orchestrator import FleetRunner
from kernel.branch import PRIMARY, Branch
from kernel.interposer import Mode
from optimizer.objective import Outcome, score

PROPOSER_MODEL = "gemini-3.5-flash"


@dataclass
class Candidate:
    """One policy under evaluation."""

    id: str
    clause_id: str
    text: str
    generation: int
    rationale: str = ""
    parent_id: str | None = None
    branch_id: str | None = None
    outcome: Outcome | None = None
    error: str | None = None

    @property
    def cost(self) -> float:
        return self.outcome.total_cost_usd if self.outcome else float("inf")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clause_id": self.clause_id,
            "text": self.text,
            "generation": self.generation,
            "rationale": self.rationale,
            "parent_id": self.parent_id,
            "branch_id": self.branch_id,
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "error": self.error,
        }


@dataclass
class SearchState:
    population: list[Candidate] = field(default_factory=list)
    baseline: Outcome | None = None
    generation: int = 0
    evaluations: int = 0
    compute_usd: float = 0.0
    replay_hits: int = 0
    executed: int = 0

    def best(self) -> Candidate | None:
        scored = [c for c in self.population if c.outcome is not None]
        return min(scored, key=lambda c: c.cost) if scored else None


class PolicySearch:
    """Evolutionary search over policy text, evaluated on recorded history."""

    def __init__(
        self,
        *,
        store,
        world,
        dispute_ids: list[str],
        epoch: int,
        clause_id: str = "POL-REFUND-CEILING",
        base_branch: str = PRIMARY,
        concurrency: int = 3,
    ) -> None:
        self.store = store
        self.world = world
        self.dispute_ids = dispute_ids
        self.epoch = epoch
        self.clause_id = clause_id
        self.base_branch = base_branch
        # Bounded because every candidate is real model traffic; the limit is the API's
        # rate ceiling, not the machine's.
        self.gate = asyncio.Semaphore(concurrency)
        self.state = SearchState()

    # -- shared history --------------------------------------------------------

    async def ensure_history(self) -> dict[str, Any]:
        """Record production's own run on the base branch, if it has not run yet.

        This is what every candidate inherits. The stages upstream of the policy — intake,
        customer lookup, the facts of the dispute — are identical no matter what the policy
        says, so recording them once on the base branch means each candidate pays only for
        the part its change actually touches. Evaluating the baseline on a fork instead
        puts that shared work on a sibling branch no candidate can resolve through, and
        the search silently degrades to full re-execution every single time.
        """
        existing = len(self.store.own_effects(self.base_branch))
        if existing:
            return {"recorded": False, "effects": existing, "cost_usd": 0.0}
        runner = FleetRunner(
            store=self.store, world=self.world, branch_id=self.base_branch,
            mode=Mode.RECORD, state_seq_floor=self.epoch,
        )
        result = await runner.run_batch(self.dispute_ids)
        totals = result.totals()
        self.state.compute_usd += totals["cost_usd"]
        return {
            "recorded": True,
            "effects": len(self.store.own_effects(self.base_branch)),
            "cost_usd": totals["cost_usd"],
            "errors": totals["errors"],
        }

    def score_base(self, compute_usd: float) -> Outcome:
        """Score production itself — no fork, because this timeline really happened."""
        return score(
            world=self.world, branch_id=self.base_branch, label="production",
            dispute_ids=self.dispute_ids, compute_usd=compute_usd,
            quarantined_actions=[],
        )

    # -- evaluation ------------------------------------------------------------

    async def evaluate(self, candidate: Candidate) -> Candidate:
        """Fork, rewrite the clause, replay the same disputes, score the result.

        The fork is taken at the same epoch every time, so every candidate faces an
        identical world: the same disputes, the same customers, the same facts. Only the
        policy differs, which is the only way the comparison means anything.
        """
        async with self.gate:
            branch = self.store.create_branch(
                Branch.fork(
                    parent=self.store.get_branch(self.base_branch),
                    name=f"cand-{candidate.id}",
                    at_seq=self.epoch,
                    perturbation={"clause": candidate.clause_id, "generation": candidate.generation},
                )
            )
            self.world.register_branch(branch)
            candidate.branch_id = branch.id

            clause = self.world.read(
                branch_id=branch.id, collection=POLICIES, key=candidate.clause_id
            )
            if clause is None:
                candidate.error = f"unknown clause {candidate.clause_id}"
                return candidate
            # Written at epoch+1 so the read-set fingerprint sees it: exogenous change,
            # which must invalidate every decision that consulted the corpus.
            self.world.write(
                branch_id=branch.id, collection=POLICIES, key=candidate.clause_id,
                value={**clause, "text": candidate.text,
                       "version": clause.get("version", 1) + 1},
                seq=self.epoch + 1,
            )

            runner = FleetRunner(
                store=self.store, world=self.world, branch_id=branch.id,
                mode=Mode.REPLAY, state_seq_floor=self.epoch + 1,
            )
            try:
                result = await runner.run_batch(self.dispute_ids)
            except Exception as exc:  # noqa: BLE001 - a bad candidate must not end the search
                candidate.error = f"{type(exc).__name__}: {exc}"
                return candidate

            totals = result.totals()
            staged = [
                {"action": ((e.response or {}).get("result") or {}).get("_lightcone_action")}
                for e in self.store.timeline(branch.id)
                if e.quarantined
            ]
            candidate.outcome = score(
                world=self.world, branch_id=branch.id, label=candidate.id,
                dispute_ids=self.dispute_ids, compute_usd=totals["cost_usd"],
                quarantined_actions=staged,
            )
            self.state.evaluations += 1
            self.state.compute_usd += totals["cost_usd"]
            self.state.replay_hits += totals["replay_hits"]
            self.state.executed += totals["executed"]
            if result.errors:
                candidate.error = result.errors[0]["error"]
            return candidate

    # -- mutation --------------------------------------------------------------

    async def propose(self, count: int, parents: list[Candidate]) -> list[Candidate]:
        """Ask Gemini for the next generation, showing it the scoreboard.

        The proposer sees each parent's policy text and what it actually cost on real
        history, so it is optimising against measured consequences rather than guessing
        at plausible-sounding rules.
        """
        from google import genai

        baseline = self.state.baseline
        scoreboard = [
            {
                "policy": p.text,
                "total_cost_usd": p.outcome.total_cost_usd,
                "wrongful_refunds_usd": round(p.outcome.wrongful_refunds_usd, 2),
                "escalations": p.outcome.escalations,
                "missed_valid_usd": round(p.outcome.missed_valid_usd, 2),
            }
            for p in parents if p.outcome
        ]

        prompt = (
            "You are optimising one clause of a customer-dispute refund policy for an "
            "autonomous agent fleet. Each candidate below was executed against the SAME "
            "real historical disputes, and the costs are measured, not estimated.\n\n"
            f"Baseline (current production policy) cost: "
            f"${baseline.total_cost_usd if baseline else 'unknown'}\n\n"
            f"Results so far:\n{json.dumps(scoreboard, indent=2)}\n\n"
            "Cost model: a wrongful refund costs its full amount; each human escalation "
            f"costs $18.00; wrongly refusing a valid dispute costs 1.4x its amount in "
            "churn. So a policy that escalates everything is NOT an improvement.\n\n"
            f"Propose {count} NEW variants of this clause that you predict will lower "
            "total cost. Vary the mechanism, not just the number: thresholds, conditions "
            "on prior disputes, conditions on the claim reason, tier carve-outs, or "
            "combinations. Each must be a complete, self-contained clause an agent can "
            "apply literally.\n\n"
            'Return ONLY JSON: {"variants":[{"text":"...","rationale":"one sentence"}]}'
        )

        client = genai.Client()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=PROPOSER_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.9},
        )
        try:
            payload = json.loads(response.text)
            variants = payload.get("variants", [])[:count]
        except (json.JSONDecodeError, AttributeError):
            variants = []

        return [
            Candidate(
                id=f"g{self.state.generation}-{uuid.uuid4().hex[:6]}",
                clause_id=self.clause_id,
                text=v["text"],
                rationale=v.get("rationale", ""),
                generation=self.state.generation,
                parent_id=parents[0].id if parents else None,
            )
            for v in variants
            if isinstance(v, dict) and v.get("text")
        ]

    # -- the loop --------------------------------------------------------------

    async def run(
        self, *, generations: int = 3, population: int = 4, survivors: int = 2
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the search, streaming every event as it happens."""
        baseline_clause = self.world.read(
            branch_id=self.base_branch, collection=POLICIES, key=self.clause_id
        )
        yield {
            "event": "search_start",
            "clause": self.clause_id,
            "baseline_text": (baseline_clause or {}).get("text", ""),
            "disputes": len(self.dispute_ids),
            "generations": generations,
            "population": population,
        }

        # Production's own run, recorded on the base branch. Every candidate inherits it.
        history = await self.ensure_history()
        yield {"event": "history", **history}

        baseline = Candidate(id="production", clause_id=self.clause_id,
                             text=(baseline_clause or {}).get("text", ""), generation=0)
        baseline.branch_id = self.base_branch
        baseline.outcome = self.score_base(history.get("cost_usd", 0.0))
        self.state.baseline = baseline.outcome
        yield {"event": "baseline", "candidate": baseline.to_dict()}

        elite: list[Candidate] = [baseline]
        for generation in range(1, generations + 1):
            self.state.generation = generation
            proposals = await self.propose(population, elite)
            if not proposals:
                yield {"event": "generation_empty", "generation": generation}
                continue
            yield {
                "event": "generation_start",
                "generation": generation,
                "candidates": [{"id": c.id, "rationale": c.rationale} for c in proposals],
            }

            # Evaluated concurrently — the whole point of an O(1) fork is that timelines
            # are independent and can be explored in parallel.
            evaluated = await asyncio.gather(*(self.evaluate(c) for c in proposals))
            for candidate in evaluated:
                self.state.population.append(candidate)
                yield {
                    "event": "evaluated",
                    "candidate": candidate.to_dict(),
                    "baseline_cost": self.state.baseline.total_cost_usd if self.state.baseline else None,
                    "running": {
                        "evaluations": self.state.evaluations,
                        "compute_usd": round(self.state.compute_usd, 4),
                        "replay_hits": self.state.replay_hits,
                        "executed": self.state.executed,
                    },
                }

            scored = [c for c in evaluated + elite if c.outcome and not c.error]
            elite = sorted(scored, key=lambda c: c.cost)[:survivors]
            best = elite[0] if elite else None
            yield {
                "event": "generation_done",
                "generation": generation,
                "best": best.to_dict() if best else None,
                "improvement_usd": (
                    round(self.state.baseline.total_cost_usd - best.cost, 2)
                    if best and self.state.baseline else 0.0
                ),
            }

        winner = self.state.best()
        yield {
            "event": "search_done",
            "winner": winner.to_dict() if winner else None,
            "baseline": self.state.baseline.to_dict() if self.state.baseline else None,
            "improvement_usd": (
                round(self.state.baseline.total_cost_usd - winner.cost, 2)
                if winner and self.state.baseline else 0.0
            ),
            "evaluations": self.state.evaluations,
            "compute_usd": round(self.state.compute_usd, 4),
            "replay_hits": self.state.replay_hits,
            "executed": self.state.executed,
        }
