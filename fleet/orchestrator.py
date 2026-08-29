"""Running the fleet on a branch.

Assembles the four pieces that must agree with each other or nothing works: the effect
store (what happened), the Shadow World (what the world looked like), the branch (which
timeline), and the interposer (record or replay). Wiring them in one place means a caller
cannot accidentally record onto one branch while reading state from another.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from fleet.agents import build_fleet
from fleet.tools import FleetContext
from kernel.branch import PRIMARY
from kernel.interposer import LightconePlugin, Mode
from kernel.store import EffectStore
from world.shadow import ShadowWorld

APP_NAME = "lightcone-revops"
OPERATOR = "fleet-operator"

# Every agent transfer swaps the system instruction and the tool set, which changes the
# request prefix and re-sends the whole prompt uncached. In a fleet that delegates on
# every case that is most of the bill, so each agent gets its own cache. The TTL comfortably
# outlives one dispute; `min_tokens` skips caching prompts too small to be worth it.
CONTEXT_CACHE = ContextCacheConfig(cache_intervals=10, ttl_seconds=1800, min_tokens=2048)


@dataclass
class RunResult:
    """What one pass of the fleet over a set of disputes produced."""

    branch_id: str
    mode: str
    disputes: list[str]
    effects: int
    reports: list[dict[str, Any]] = field(default_factory=list)
    wall_s: float = 0.0
    errors: list[dict[str, str]] = field(default_factory=list)

    def totals(self) -> dict[str, Any]:
        def total(key: str) -> float:
            return sum(r.get(key, 0) for r in self.reports)

        return {
            "branch": self.branch_id,
            "mode": self.mode,
            "disputes": len(self.disputes),
            "effects": self.effects,
            "boundary_crossings": int(total("boundary_crossings")),
            "replay_hits": int(total("replay_hits")),
            "executed": int(total("executed")),
            "quarantined": int(total("quarantined")),
            "tokens_in": int(total("tokens_in")),
            "tokens_out": int(total("tokens_out")),
            "cost_usd": round(total("cost_usd"), 6),
            "cost_avoided_usd": round(total("cost_avoided_usd"), 6),
            "wall_s": round(self.wall_s, 1),
            "errors": len(self.errors),
        }


class FleetRunner:
    """Drives the dispute fleet over a branch, recording or replaying."""

    def __init__(
        self,
        *,
        store: EffectStore,
        world: ShadowWorld,
        branch_id: str = PRIMARY,
        mode: Mode = Mode.RECORD,
        state_seq_floor: int = 0,
    ) -> None:
        self.store = store
        self.world = world
        self.branch_id = branch_id
        self.mode = mode
        self.ctx = FleetContext(world=world, branch_id=branch_id)
        self.ctx.sync_seq(state_seq_floor)
        self.fleet, self.registry = build_fleet(self.ctx)

    def _fingerprint(self, collections: tuple[str, ...]) -> str:
        return self.world.fingerprint(branch_id=self.branch_id, collections=collections)

    async def run_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Process one dispute end to end, recording every boundary crossing.

        A fresh plugin per dispute because disputes are genuinely independent units of
        work: giving each its own causal frontier keeps unrelated cases from appearing
        as each other's ancestors, which would make every lightcone far too wide.
        Dependencies that really are shared — the policy corpus, customer records —
        travel through the read-set fingerprint instead, where they belong.
        """
        plugin = LightconePlugin(
            store=self.store,
            branch_id=self.branch_id,
            mode=self.mode,
            registry=self.registry,
            state_fingerprint=self._fingerprint,
        )
        sessions = InMemorySessionService()
        runner = Runner(
            app=App(
                name=APP_NAME,
                root_agent=self.fleet,
                plugins=[plugin],
                context_cache_config=CONTEXT_CACHE,
            ),
            session_service=sessions,
        )
        session = await sessions.create_session(app_name=APP_NAME, user_id=OPERATOR)
        async for _ in runner.run_async(
            user_id=OPERATOR,
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=f"Resolve dispute {dispute_id}.")],
            ),
        ):
            pass
        plugin.flush()
        report = plugin.report()
        report["dispute_id"] = dispute_id
        return report

    async def run_batch(
        self,
        dispute_ids: list[str],
        *,
        on_progress: Callable[[int, int, dict[str, Any]], None] | None = None,
        stop_on_error: bool = False,
    ) -> RunResult:
        started = time.perf_counter()
        result = RunResult(branch_id=self.branch_id, mode=self.mode.value,
                           disputes=list(dispute_ids), effects=0)
        for index, dispute_id in enumerate(dispute_ids, start=1):
            try:
                report = await self.run_dispute(dispute_id)
                result.reports.append(report)
                if on_progress:
                    on_progress(index, len(dispute_ids), report)
            except Exception as exc:  # noqa: BLE001 - one bad case must not void the run
                result.errors.append({"dispute_id": dispute_id,
                                      "error": f"{type(exc).__name__}: {exc}"})
                if stop_on_error:
                    raise
        result.effects = len(self.store.own_effects(self.branch_id))
        result.wall_s = time.perf_counter() - started
        return result
