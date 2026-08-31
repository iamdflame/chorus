"""The engine behind the API — one place that owns the live timeline.

Holds the effect store, the Shadow World and the branch registry together, because they
are only meaningful as a set: a timeline without the state it produced cannot answer a
counterfactual, and state without its timeline cannot explain itself.

Every operation the console performs is a method here, so the HTTP layer stays a thin
translation of requests into kernel calls.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncIterator

from fleet.domain import COMMS, DISPUTES, LEDGER, POLICIES, TICKETS, build_seed, load_into_world
from fleet.orchestrator import FleetRunner
from kernel.branch import PRIMARY, Branch
from kernel.dag import CausalDAG
from kernel.effect import Effect
from kernel.interposer import Mode
from kernel.snapshot import load, save
from kernel.store import InMemoryEffectStore
from world.shadow import ShadowWorld


class Engine:
    """Owns the live timeline and every operation over it."""

    def __init__(self, snapshot: str | Path | None = None) -> None:
        # Which store is actually serving, reported by /health so the claim is checkable
        # from the one surface a reader has without cloning the repo.
        self.backend = "memory"

        if snapshot and Path(snapshot).exists():
            self.store, self.world = load(snapshot)
            self.state_floor = self._infer_state_floor()
            self.backend = f"snapshot:{Path(snapshot).name}"

            # Firestore is the durable store, and saying so while serving from a JSON file
            # would be the softest claim in the project. When a project is configured the
            # timeline is promoted into Firestore on boot and served from there; the
            # snapshot becomes the seed rather than the source.
            #
            # Failure here is not fatal on purpose. A demo that will not start because a
            # database is unreachable is worse than one that starts on the reference
            # backend and says which it is — and it says which either way.
            project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            if project and os.environ.get("CHORUS_STORE", "firestore") == "firestore":
                try:
                    from kernel.firestore_store import FirestoreEffectStore

                    remote = FirestoreEffectStore(
                        project=project,
                        root=os.environ.get("CHORUS_STORE_ROOT", "lightcone"),
                    )
                    for branch in self.store.list_branches():
                        if remote.get_branch(branch.id) is None:
                            remote.create_branch(branch)
                    existing = {e.id for e in remote.own_effects(PRIMARY)}
                    fresh = [
                        e for e in self.store.timeline(PRIMARY) if e.id not in existing
                    ]
                    if fresh:
                        remote.put_many(fresh)
                        remote.append_manifest(PRIMARY, [e.id for e in fresh])
                    self.store = remote
                    self.backend = "firestore"
                except Exception as exc:  # noqa: BLE001 - degraded, and it says so
                    self.backend = f"snapshot:{Path(snapshot).name} (firestore: "
                    self.backend += f"{type(exc).__name__})"
        else:
            self.store = InMemoryEffectStore()
            self.world = ShadowWorld(
                branches={b.id: b for b in InMemoryEffectStore().list_branches()}
            )
            seed = build_seed()
            self.state_floor = load_into_world(self.world, seed, branch_id=PRIMARY)
        self._sync_branches()
        self._lock = asyncio.Lock()

    def _infer_state_floor(self) -> int:
        highest = 0
        for history in self.world._versions.values():
            for version in history:
                highest = max(highest, version.seq)
        return highest

    def _sync_branches(self) -> None:
        """Keep the world's branch registry identical to the store's.

        They are separate objects but describe the same tree; if they drift, a branch can
        read state it should not see.
        """
        for branch in self.store.list_branches():
            self.world.register_branch(branch)

    # -- reads -----------------------------------------------------------------

    def branches(self) -> list[dict[str, Any]]:
        out = []
        for branch in self.store.list_branches():
            timeline = self.store.timeline(branch.id)
            out.append(
                {
                    **branch.to_dict(),
                    "effects": len(timeline),
                    "own_effects": len(self.store.own_effects(branch.id)),
                    "is_primary": branch.is_primary,
                }
            )
        return out

    def dag(self, branch_id: str) -> CausalDAG:
        return self.store.dag(branch_id)

    def graph(self, branch_id: str, *, limit: int | None = None) -> dict[str, Any]:
        """The causal graph shaped for rendering.

        `inherited` marks effects resolved from an ancestor rather than executed here —
        the console dims those, so the eye reads reused work and new work apart at a
        glance without needing a legend.
        """
        timeline = self.store.timeline(branch_id)
        if limit:
            timeline = timeline[:limit]
        present = {e.id for e in timeline}
        nodes = [
            {
                "id": e.id,
                "seq": e.seq,
                "agent": e.agent,
                "kind": e.kind.value,
                "determinism": e.determinism.value,
                "inherited": e.branch_id != branch_id,
                "quarantined": e.quarantined,
                "cost_usd": e.cost_usd,
                "tokens": e.tokens_in + e.tokens_out,
                "wall_ms": round(e.wall_ms, 1),
                "label": self._label(e),
            }
            for e in timeline
        ]
        edges = [
            {"source": parent, "target": e.id}
            for e in timeline
            for parent in e.causal_parents
            if parent in present
        ]
        agents: list[str] = []
        for node in nodes:
            if node["agent"] not in agents:
                agents.append(node["agent"])
        return {
            "branch": self.store.get_branch(branch_id).to_dict(),
            "nodes": nodes,
            "edges": edges,
            "agents": agents,
            "stats": CausalDAG(timeline).stats(),
        }

    @staticmethod
    def _label(effect: Effect) -> str:
        if effect.kind.value == "tool_call":
            return effect.request.get("tool", "tool")
        if effect.kind.value == "delegation":
            return f"-> {effect.request.get('to', '?')}"
        if effect.kind.value == "model_call":
            return "reason"
        return effect.kind.value.replace("_", " ")

    def effect(self, branch_id: str, effect_id: str) -> dict[str, Any] | None:
        found = self.store.lookup(branch_id, effect_id)
        if found is None:
            return None
        payload = found.to_dict()
        payload["staged_action"] = (
            ((found.response or {}).get("result") or {}).get("_lightcone_action")
            if found.quarantined
            else None
        )
        return payload

    def lightcone(self, branch_id: str, effect_id: str) -> dict[str, Any]:
        """Forward and backward cones for one effect — blast radius and provenance."""
        dag = self.store.dag(branch_id)
        forward = dag.forward_lightcone(effect_id, include_roots=False)
        backward = dag.backward_lightcone(effect_id, include_leaves=False)
        affected = [dag.get(e) for e in forward if dag.get(e)]
        return {
            "root": effect_id,
            "forward": sorted(forward),
            "backward": sorted(backward),
            "forward_count": len(forward),
            "backward_count": len(backward),
            "agents_touched": sorted({e.agent for e in affected}),
            "irreversible_downstream": [
                {"id": e.id, "agent": e.agent,
                 "action": ((e.response or {}).get("result") or {}).get("_lightcone_action")
                 or e.request.get("tool")}
                for e in affected
                if e.determinism.value == "external_irreversible"
            ],
            "cost_downstream_usd": round(sum(e.cost_usd for e in affected), 6),
        }

    def world_view(
        self, branch_id: str, collection: str, at_seq: int | None = None
    ) -> dict[str, Any]:
        return self.world.scan(branch_id=branch_id, collection=collection, at_seq=at_seq)

    # -- the money question ----------------------------------------------------

    def diff(self, left: str, right: str) -> dict[str, Any]:
        """Compare two timelines causally and financially.

        The causal half says what the agents did differently. The financial half says
        what it cost, which is the half that settles an argument.
        """
        causal = self.store.dag(left).diff(self.store.dag(right))
        state = self.world.diff(left=left, right=right)

        def money(branch: str) -> dict[str, Any]:
            ledger = self.world.scan(branch_id=branch, collection=LEDGER)
            refunds = [e for e in ledger.values() if e.get("type") == "refund"]
            return {
                "refund_count": len(refunds),
                "refund_total_usd": round(sum(e.get("amount_usd", 0) for e in refunds), 2),
                "emails_sent": len(self.world.scan(branch_id=branch, collection=COMMS)),
                "tickets_open": len(self.world.scan(branch_id=branch, collection=TICKETS)),
            }

        left_money, right_money = money(left), money(right)
        staged = [
            {"id": e.id, "agent": e.agent,
             "action": ((e.response or {}).get("result") or {}).get("_lightcone_action")}
            for e in self.store.timeline(right)
            if e.quarantined
        ]
        return {
            "left": left,
            "right": right,
            "causal": causal.summary(),
            "changed_effects": sorted(causal.changed),
            "state_changes": state,
            "money": {
                "left": left_money,
                "right": right_money,
                "delta_refund_usd": round(
                    right_money["refund_total_usd"] - left_money["refund_total_usd"], 2
                ),
                "delta_refund_count": right_money["refund_count"] - left_money["refund_count"],
            },
            "staged_actions": staged,
            "staged_count": len(staged),
        }

    # -- writes ----------------------------------------------------------------

    def fork(
        self, *, parent_id: str, name: str, at_seq: int,
        perturbation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parent = self.store.get_branch(parent_id)
        if parent is None:
            raise KeyError(f"unknown branch {parent_id}")
        branch = self.store.create_branch(
            Branch.fork(parent=parent, name=name, at_seq=at_seq, perturbation=perturbation)
        )
        self.world.register_branch(branch)
        return branch.to_dict()

    def edit_policy(self, *, branch_id: str, clause_id: str, text: str) -> dict[str, Any]:
        """Rewrite a policy clause on a branch.

        Writes to the branch's overlay, so production's policy is untouched. Because
        `search_policy` declares the policy corpus as its read set, this single write is
        what makes every decision that consulted the corpus re-execute on replay.
        """
        clause = self.world.read(branch_id=branch_id, collection=POLICIES, key=clause_id)
        if clause is None:
            raise KeyError(f"unknown clause {clause_id}")
        self.state_floor += 1
        updated = {**clause, "text": text, "version": clause.get("version", 1) + 1}
        self.world.write(
            branch_id=branch_id, collection=POLICIES, key=clause_id,
            value=updated, seq=self.state_floor,
        )
        return {"clause": updated, "branch_id": branch_id}

    def merge(self, *, branch_id: str, into: str = PRIMARY, force: bool = False) -> dict[str, Any]:
        self.state_floor += 1
        return self.world.merge(
            branch_id=branch_id, into=into, seq=self.state_floor, force=force
        )

    # -- replay ----------------------------------------------------------------

    async def replay(
        self, *, branch_id: str, dispute_ids: list[str], mode: Mode = Mode.REPLAY
    ) -> AsyncIterator[dict[str, Any]]:
        """Re-execute the fleet on a branch, yielding progress as it goes.

        Streams because the interesting part is watching an unchanged prefix snap back
        for free while the diverged remainder genuinely re-runs — a progress bar would
        hide exactly the thing worth seeing.
        """
        async with self._lock:
            runner = FleetRunner(
                store=self.store, world=self.world, branch_id=branch_id,
                mode=mode, state_seq_floor=self.state_floor,
            )
            yield {"event": "start", "branch": branch_id,
                   "disputes": len(dispute_ids), "mode": mode.value}
            totals = {"hits": 0, "executed": 0, "cost": 0.0, "avoided": 0.0, "quarantined": 0}
            for index, dispute_id in enumerate(dispute_ids, start=1):
                try:
                    report = await runner.run_dispute(dispute_id)
                except Exception as exc:  # noqa: BLE001 - report and continue
                    yield {"event": "error", "dispute_id": dispute_id,
                           "error": f"{type(exc).__name__}: {exc}", "index": index}
                    continue
                totals["hits"] += report["replay_hits"]
                totals["executed"] += report["executed"]
                totals["cost"] += report["cost_usd"]
                totals["avoided"] += report["cost_avoided_usd"]
                totals["quarantined"] += report["quarantined"]
                yield {
                    "event": "dispute",
                    "index": index,
                    "total": len(dispute_ids),
                    "dispute_id": dispute_id,
                    "replay_hits": report["replay_hits"],
                    "executed": report["executed"],
                    "cost_usd": round(report["cost_usd"], 6),
                    "cost_avoided_usd": round(report["cost_avoided_usd"], 6),
                    "quarantined": report["quarantined"],
                    "running": {
                        "hits": totals["hits"],
                        "executed": totals["executed"],
                        "cost_usd": round(totals["cost"], 6),
                        "cost_avoided_usd": round(totals["avoided"], 6),
                        "quarantined": totals["quarantined"],
                    },
                }
            self.state_floor = max(self.state_floor, runner.ctx._counter)
            yield {"event": "done", "branch": branch_id,
                   "root_hash": self.store.dag(branch_id).root_hash(), "totals": totals}

    async def search_policy(
        self,
        *,
        dispute_ids: list[str],
        clause_id: str = "POL-REFUND-CEILING",
        generations: int = 2,
        population: int = 3,
        concurrency: int = 3,
    ) -> AsyncIterator[dict[str, Any]]:
        """Search policy space against recorded history, streaming every event.

        Held under the same lock as replay: both mutate the branch tree, and two searches
        interleaving would attribute one another's effects to the wrong timeline.
        """
        from optimizer.search import PolicySearch

        async with self._lock:
            search = PolicySearch(
                store=self.store, world=self.world, dispute_ids=dispute_ids,
                epoch=self.state_floor, clause_id=clause_id, concurrency=concurrency,
            )
            async for event in search.run(
                generations=generations, population=population, survivors=2
            ):
                yield event
            self._sync_branches()

    def adopt(self, *, clause_id: str, text: str) -> dict[str, Any]:
        """Promote a discovered policy into production.

        The end of the loop the product exists to close: the fleet does not merely
        report that a better policy exists, it installs the one it proved.
        """
        clause = self.world.read(branch_id=PRIMARY, collection=POLICIES, key=clause_id)
        if clause is None:
            raise KeyError(f"unknown clause {clause_id}")
        self.state_floor += 1
        updated = {**clause, "text": text, "version": clause.get("version", 1) + 1,
                   "adopted_from_search": True}
        self.world.write(
            branch_id=PRIMARY, collection=POLICIES, key=clause_id,
            value=updated, seq=self.state_floor,
        )
        return {"adopted": True, "clause": updated}

    async def run_swarm(
        self, *, agents: int = 2000, concurrency: int = 6
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the swarm, streaming one event per cohort as it resolves.

        Distinguishes a cohort that reached the model from one served by the store,
        because that difference is the entire claim and the console draws them apart.
        """
        from dataclasses import asdict

        from kernel.clock import FIXED
        from swarm.canonical import bind, collapse, project_passenger
        from swarm.runtime import Swarm
        from swarm.scenario import build_scenario

        async with self._lock:
            scenario = build_scenario(passengers=agents)
            passengers = [asdict(p) for p in scenario.passengers]
            cohorts = collapse(passengers, bind(project_passenger, FIXED))
            summary = scenario.summary()

            yield {
                "event": "swarm_start",
                "agents": len(passengers),
                "cohorts": [
                    {"key": key, "size": len(members),
                     "label": key.split("|", 1)[1] if "|" in key else key}
                    for key, members in sorted(
                        cohorts.items(), key=lambda kv: len(kv[1]), reverse=True
                    )
                ],
                "scenario": summary,
            }

            context = (
                f"Hub closed by severe weather. {summary['souls_on_board']:,} travellers "
                f"need to move. {summary['seats_available']:,} seats exist on the next "
                f"departures. Seats are scarce."
            )
            swarm = Swarm(store=self.store, branch_id=PRIMARY,
                          mode=Mode.REPLAY, concurrency=concurrency)
            resolved: set[str] = set()

            queue: asyncio.Queue = asyncio.Queue()

            def progress(
                done: int, total: int, metrics, cohort: str, thought: bool,
                answer: dict[str, Any] | None = None,
            ) -> None:
                # One event per agent would flood the stream; cohorts are emitted the
                # first time they resolve, and aggregate counters ride along every 25.
                first_time = cohort not in resolved
                if first_time:
                    resolved.add(cohort)
                if first_time or done % 25 == 0 or done == total:
                    queue.put_nowait({
                        "event": "progress", "done": done, "total": total,
                        "cohort": cohort, "thought": thought, "first": first_time,
                        # Only on the first resolution: the console shows one thought per
                        # cohort, and repeating it on every hit would be pure stream noise.
                        "preference": answer if first_time else None,
                        **metrics.to_dict(),
                    })

            task = asyncio.create_task(
                swarm.run(entities=passengers, projector=bind(project_passenger, FIXED),
                          role="passenger", context=context,
                          round_id=f"irrops-{agents}", on_progress=progress)
            )
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.4)
                except asyncio.TimeoutError:
                    continue
                yield event

            preferences, metrics = await task
            yield {"event": "swarm_done", "metrics": metrics.to_dict(),
                   "preferences": len(preferences)}

    def snapshot(self, path: str | Path) -> dict[str, Any]:
        save(path, store=self.store, world=self.world)
        from kernel.snapshot import describe

        return describe(path)
