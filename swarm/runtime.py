"""Running the swarm.

Every agent is invoked independently. Nothing here groups them, dedupes them, or is even
aware that other agents exist — each passenger agent runs its own ADK invocation with its
own context. The saving is discovered by the kernel: because a model call is addressed by
`H(kind, role, causal parents, request)` and the request carries only the canonical
projection, the second agent in a cohort computes an address that is already in the store
and never reaches the model.

That distinction matters. Grouping by projection in application code would produce the
same number of API calls and prove nothing — it would just be a `GROUP BY`. Letting
genuinely independent agents collide in a content-addressed store means the sharing is
*derived* rather than assumed, holds for structure nobody anticipated, and stays correct
when an agent's situation is subtly different in a way a hand-written grouping would miss.

Rounds exist so that agents reasoning about the same world state share a causal anchor.
Without one, each agent would sit at a different causal position, every address would
differ, and nothing would ever collide.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from kernel.branch import PRIMARY
from kernel.effect import Determinism, Effect, EffectKind, hash_payload
from kernel.interposer import LightconePlugin, Mode
from kernel.store import EffectStore
from swarm.canonical import Projection

MODEL = "gemini-3.5-flash"
APP_NAME = "chorus-irrops"

PASSENGER_INSTRUCTION = """You represent one traveller stranded by a hub closure. You are \
given only your situation, never your identity — you are reasoning about what someone in \
this position should want, not about who you are.

State your rebooking preferences as JSON with exactly these keys:
  max_wait_hours       integer, the longest delay you would accept before compensation
  accept_downgrade     boolean, whether a worse cabin is acceptable to depart sooner
  accept_split_party   boolean, whether your party may travel separately
  accept_nearby_airport boolean, whether an alternate arrival airport is acceptable
  needs_hotel          boolean, whether an overnight stay requires accommodation
  urgency_score        integer 0-100, how strongly you need to be prioritised

Be realistic about the trade-off: a passenger who refuses every compromise gets a worse \
outcome when seats are scarce. Return only JSON."""

CREW_INSTRUCTION = """You represent one crew member during an irregular-operations event. \
You are given only your duty situation, never your identity.

State your availability as JSON with exactly these keys:
  can_operate          boolean, whether you may legally operate another sector
  max_sector_hours     number, the longest sector you could legally take
  requires_rest        boolean, whether you must rest before operating
  willing_to_reposition boolean, whether you would deadhead to another base
  availability_score   integer 0-100, how useful you are to this recovery

Duty limits are law, not preference: if you are timed out, you cannot operate. Return \
only JSON."""


@dataclass
class SwarmMetrics:
    """What the run actually cost, measured rather than estimated."""

    agents_invoked: int = 0
    model_calls: int = 0
    cache_hits: int = 0
    distinct_thoughts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    cost_avoided_usd: float = 0.0
    wall_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def collapse(self) -> float:
        return self.agents_invoked / max(self.distinct_thoughts, 1)

    @property
    def naive_cost_usd(self) -> float:
        """What the same swarm would have cost with one model call per agent."""
        if not self.model_calls:
            return 0.0
        return round((self.cost_usd / self.model_calls) * self.agents_invoked, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents_invoked": self.agents_invoked,
            "model_calls": self.model_calls,
            "cache_hits": self.cache_hits,
            "distinct_thoughts": self.distinct_thoughts,
            "collapse": round(self.collapse, 1),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "cost_avoided_usd": round(self.cost_avoided_usd, 6),
            "naive_cost_usd": self.naive_cost_usd,
            "wall_s": round(self.wall_s, 1),
            "errors": len(self.errors),
        }


def build_agent(role: str) -> LlmAgent:
    """One agent definition per ROLE, not per entity.

    The name is part of every address, so naming agents individually would make each one's
    reasoning unique and defeat sharing entirely. Individuality lives in the entity data
    and in the allocation that follows — never in the reasoning step.
    """
    return LlmAgent(
        name=f"{role}_agent",
        model=MODEL,
        instruction=PASSENGER_INSTRUCTION if role == "passenger" else CREW_INSTRUCTION,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )


class Swarm:
    """Invokes one agent per entity against a shared content-addressed store."""

    def __init__(
        self,
        *,
        store: EffectStore,
        branch_id: str = PRIMARY,
        mode: Mode = Mode.REPLAY,
        concurrency: int = 4,
    ) -> None:
        self.store = store
        self.branch_id = branch_id
        self.mode = mode
        self.gate = asyncio.Semaphore(concurrency)
        self.agents = {role: build_agent(role) for role in ("passenger", "crew")}
        self._sessions = InMemorySessionService()

    def round_anchor(self, round_id: str, context: dict[str, Any]) -> str:
        """A causal anchor shared by every agent reasoning in this round.

        Recorded as a real effect so the swarm's reasoning is rooted in the world state it
        saw, and so two rounds facing different scarcity cannot silently share answers.
        """
        effect = Effect.create(
            branch_id=self.branch_id, seq=0, agent="swarm",
            kind=EffectKind.AGENT_ENTER, determinism=Determinism.PURE,
            causal_parents=(), request={"round": round_id, "context": context},
            response={"anchored": True},
        )
        if self.store.lookup(self.branch_id, effect.id) is None:
            self.store.put(effect.with_seq(self.store.next_seq(self.branch_id)))
        return effect.id

    async def _invoke(
        self, role: str, projection: Projection, context: str, anchor: str
    ) -> tuple[dict[str, Any] | None, LightconePlugin]:
        plugin = LightconePlugin(
            store=self.store, branch_id=self.branch_id, mode=self.mode,
            seed_parents=(anchor,),
        )
        runner = Runner(
            app=App(name=APP_NAME, root_agent=self.agents[role], plugins=[plugin]),
            session_service=self._sessions,
        )
        session = await self._sessions.create_session(app_name=APP_NAME, user_id="swarm")
        text = f"{context}\n\n{projection.to_prompt()}"
        answer: dict[str, Any] | None = None
        async for event in runner.run_async(
            user_id="swarm", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        try:
                            answer = json.loads(part.text)
                        except json.JSONDecodeError:
                            pass
        plugin.flush()
        return answer, plugin

    async def run(
        self,
        *,
        entities: list[dict[str, Any]],
        projector: Callable[[dict[str, Any]], Projection],
        role: str,
        context: str,
        round_id: str,
        on_progress: Callable[[int, int, SwarmMetrics, str, bool, dict[str, Any] | None], None] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], SwarmMetrics]:
        """Invoke every entity's agent. Sharing is discovered, never assumed."""
        started = time.perf_counter()
        metrics = SwarmMetrics()
        anchor = self.round_anchor(round_id, {"role": role, "context": hash_payload(context)})
        preferences: dict[str, dict[str, Any]] = {}
        seen_addresses: set[str] = set()

        async def one(entity: dict[str, Any]) -> None:
            async with self.gate:
                projection = projector(entity)
                try:
                    answer, plugin = await self._invoke(role, projection, context, anchor)
                except Exception as exc:  # noqa: BLE001 - one agent must not end the swarm
                    metrics.errors.append(f"{entity.get('id')}: {type(exc).__name__}: {exc}")
                    return
                if answer is not None:
                    preferences[entity["id"]] = answer
                metrics.agents_invoked += 1
                metrics.model_calls += plugin.misses
                metrics.cache_hits += plugin.hits
                report = plugin.report()
                metrics.tokens_in += report["tokens_in"]
                metrics.tokens_out += report["tokens_out"]
                metrics.cost_usd += report["cost_usd"]
                metrics.cost_avoided_usd += report["cost_avoided_usd"]
                seen_addresses.update(plugin.diverged)
                metrics.distinct_thoughts = len(seen_addresses)
                if on_progress:
                    # `thought` distinguishes a cohort that reached the model from one
                    # served by the store; the console draws those two states apart, and
                    # the difference between them is the entire claim.
                    on_progress(
                        metrics.agents_invoked, len(entities), metrics,
                        projection.key(), plugin.misses > 0, answer,
                    )

        # Sequential batches rather than one giant gather: 8,000 coroutines all holding
        # ADK sessions at once exhausts memory long before the semaphore matters.
        batch = 200
        for start in range(0, len(entities), batch):
            await asyncio.gather(*(one(e) for e in entities[start:start + batch]))

        metrics.wall_s = time.perf_counter() - started
        return preferences, metrics
