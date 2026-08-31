"""LightconePlugin — total interposition on the agent/world boundary.

This is the only file in the kernel that knows ADK exists, and it is the mechanism the
whole system rests on. ADK's plugin protocol registers on the `Runner`, applies to every
agent in the fleet, takes precedence over per-agent callbacks, and — critically — lets a
callback return a value that *short-circuits* the real call:

    before_model_callback -> Optional[LlmResponse]   returning one skips the model
    before_tool_callback  -> Optional[dict]          returning one skips the tool

Those two signatures are the entire basis for deterministic replay. Every boundary the
agent crosses is addressed by `(kind, agent, causal parents, request)`; the plugin looks
that address up before executing, and returns the recorded response on a hit. No
monkey-patching, no forked framework, no swapped tools — the agent under replay is byte
for byte the agent that ran in production.

Three modes:

    RECORD         never look up; execute and record everything (production)
    REPLAY         look up; execute on miss and record (counterfactual re-execution)
    REPLAY_STRICT  look up; raise on miss (used to *prove* determinism in CI)

Cost follows directly: an unperturbed replay is all hits and spends nothing, while a
perturbed replay spends only on the forward lightcone of whatever was changed.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from kernel.branch import PRIMARY
from kernel.effect import Determinism, Effect, EffectKind, canonical_json, hash_payload
from kernel.errors import ReplayError
from kernel.quarantine import ReversibilityRegistry, staged_result
from kernel.singleflight import SingleFlight
from kernel.store import EffectStore

# Gemini 3.5 Flash list price, USD per million tokens. Recorded per effect so that a
# counterfactual diff can be denominated in money rather than token counts.
PRICE_IN_PER_M = 1.35
PRICE_OUT_PER_M = 8.10

# Minimum length of produced text before it is trusted as a data-flow fingerprint.
# Short strings ("OK", "done") recur by coincidence and would manufacture false causal
# edges, which is worse than a missing one: a wrong lightcone silently over-reports
# blast radius.
MIN_PRODUCER_TEXT = 16


class Mode(str, Enum):
    """How the interposer treats the effect store.

    The names are about *provenance*, not about speed, and the distinction has bitten
    this project once already, so it is spelled out:

    RECORD
        Never consult the store. Every call executes and is recorded. This is what you
        want when producing a clean recording to replay against later — and it is the
        wrong mode for a swarm, because collapse *is* the store lookup. Two scripts were
        written with it and paid full price for answers the store already held.
    REPLAY
        Consult the store; execute and record on a miss. This is the mode that makes a
        swarm cheap, and it is what every collapse number in this repository is measured
        under.
    REPLAY_STRICT
        Consult the store; a miss is an error. Determinism proofs use this, because a
        miss there means execution diverged where it was asserted not to.
    """

    RECORD = "record"
    REPLAY = "replay"
    REPLAY_STRICT = "replay_strict"


class ReplayMiss(ReplayError):
    """Raised in REPLAY_STRICT when an address is absent from the store.

    In strict mode a miss means execution diverged where it was asserted not to — a
    determinism bug — so it fails loudly instead of silently spending tokens.
    """


def canonical_llm_request(req: LlmRequest) -> dict[str, Any]:
    """Reduce an LlmRequest to exactly the fields that determine the model's output.

    Everything volatile is excluded, because anything included here that varies between
    runs would change the address and turn every replay into a cache miss. `tools_dict`
    holds live BaseTool objects, so only the declared tool names are hashed; the schemas
    reaching the model are already carried in `config`.
    """
    contents: list[dict[str, Any]] = []
    for content in req.contents or []:
        contents.append(content.model_dump(mode="json", exclude_none=True))

    config: dict[str, Any] = {}
    if req.config is not None:
        raw = req.config.model_dump(mode="json", exclude_none=True)
        # Retain only semantically load-bearing generation settings.
        for key in (
            "system_instruction",
            "temperature",
            "top_p",
            "top_k",
            "max_output_tokens",
            "response_mime_type",
            "response_schema",
            "thinking_config",
            "tools",
        ):
            if key in raw:
                config[key] = raw[key]

    return {
        "model": req.model,
        "contents": contents,
        "config": config,
        "tools": sorted(req.tools_dict.keys()) if req.tools_dict else [],
    }


def _tool_key(agent: str, tool_name: str, tool_args: dict[str, Any]) -> str:
    """Key linking a tool effect opened in `before_tool` to its close in `after_tool`.

    Deliberately built from only the three things both callbacks see. The address cannot
    be used here because `after_tool_callback` never receives it, and rebuilding it there
    from the request would mean reconstructing the read-set fingerprint identically — a
    silent drop the moment the two constructions disagree, which is exactly the bug this
    replaced.
    """
    return f"tool:{agent}:{tool_name}:{hash_payload(tool_args)}"


def _model_key(agent: str, address: str) -> str:
    """Key a pending model effect by its address, not by the agent alone.

    `f"model:{agent}"` collides the moment one agent has two model calls in flight, and
    the loser's effect is silently dropped -- it is opened, never closed, and never
    recorded. Addresses are unique by construction, so they cannot collide.
    """
    return f"model:{agent}:{address}"


class LightconePlugin(BasePlugin):
    """Records or replays every model call, tool call and delegation on a branch."""

    def __init__(
        self,
        *,
        store: EffectStore,
        branch_id: str = PRIMARY,
        mode: Mode = Mode.RECORD,
        gateway: Any | None = None,
        registry: ReversibilityRegistry | None = None,
        name: str = "lightcone",
        seed_parents: tuple[str, ...] = (),
        state_fingerprint: Callable[[tuple[str, ...]], str] | None = None,
        single_flight: SingleFlight | None = None,
    ) -> None:
        super().__init__(name=name)
        self.store = store
        self.branch_id = branch_id
        self.mode = mode
        self.registry = registry or ReversibilityRegistry()
        # Supplied by the world so a state-reading tool is addressed by what it reads as
        # well as by its arguments. Without it, a counterfactual that edits data the
        # agents consult would replay straight past the edit.
        self._state_fingerprint = state_fingerprint
        # Shared across every plugin instance in a swarm: the point is to coalesce
        # agents running in *different* invocations, so a per-plugin instance would
        # coalesce nothing.
        self._single_flight = single_flight

        # Causal bookkeeping. None of this may leak into an address: invocation ids are
        # fresh on every run, so including one would make every replay miss.
        self._agent_stack: list[str] = []
        self._last_by_agent: dict[str, str] = {}
        self._seed_parents: tuple[str, ...] = tuple(seed_parents)
        self._last_global: str | None = None
        # (produced text, address) in production order — the data-flow index. Scoped to
        # a run, so it stays small enough to scan on every crossing.
        self._producers: list[tuple[str, str]] = []

        # Effects opened in a before_* hook and closed in the matching after_* hook.
        self._pending: dict[str, tuple[Effect, float]] = {}

        # Ordered addresses visited this run. Written to the branch as a manifest so a
        # forked timeline can be materialised without copying its parent's effects.
        self.visited: list[str] = []
        # Effects this run actually executed (as opposed to served from the store).
        self.recorded: list[Effect] = []
        # Addresses already persisted by write-through, so flush does not rewrite them.
        self._written: set[str] = set()
        # Policy gate for tool calls. None means no gateway is configured and every call
        # is permitted — stated rather than implied, because a gateway that silently
        # defaults to open is worse than none at all.
        self.gateway = gateway
        self.diverged: list[str] = []
        # Every model-call address this plugin resolved, whether it paid for the answer
        # or was handed one. Distillation needs the address regardless of who paid: a row
        # served from the store is exactly the row whose provenance must name the call
        # that originally produced it.
        self.served_model: list[str] = []
        self.hits = 0
        self.misses = 0
        # Calls suppressed because an identical question was already in flight.
        # Distinct from a hit: a hit is work already recorded, a coalesce is work
        # that was about to be duplicated.
        self.coalesced = 0

    # -- causal position -------------------------------------------------------

    @staticmethod
    def _text_of(content: dict[str, Any]) -> str:
        """A comparable text projection of a content block.

        Covers both channels an effect's output can travel on: plain text (how ADK
        relays one agent's answer to the next) and structured function responses (how a
        tool's result reaches the model). Omitting the second would drop every
        tool-mediated dependency from the graph.
        """
        chunks: list[str] = []
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("text"):
                chunks.append(part["text"])
            if part.get("function_response") is not None:
                chunks.append(canonical_json(part["function_response"]).decode("utf-8"))
        return "\n".join(chunks)

    def _register_producer(self, address: str, content: dict[str, Any] | None) -> None:
        """Index an effect's output so later requests that quote it become its children.

        Called on the replay path as well as the execute path. If it were only called
        after real execution, a replayed run would lose its data-flow edges and the two
        timelines would not be comparable.
        """
        if not content:
            return
        text = self._text_of(content)
        if len(text) >= MIN_PRODUCER_TEXT:
            self._producers.append((text, address))

    def _data_parents(self, contents: list[dict[str, Any]]) -> list[str]:
        """Effects whose output this request actually reads.

        ADK does not pass an upstream agent's output through verbatim — it re-roles and
        wraps it in a quoted transcript block — so identity on the whole content block
        never matches. Containment of the produced text does, and it is the honest
        signal: if this request contains that output, this effect depends on it.

        Reading dependencies rather than inferring them from the call tree is what makes
        the lightcone correct. Sibling stages of a SequentialAgent share a parent in the
        call tree but are strictly sequential in data, and only the data answer supports
        the question the product exists to answer.
        """
        haystack = "\n".join(self._text_of(c) for c in contents)
        if not haystack:
            return []
        found: list[str] = []
        for text, address in self._producers:
            if text in haystack and address not in found:
                found.append(address)
        return found

    def _parents_for(self, agent: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Causal parents for the next effect issued by `agent`.

        Program order within the agent, plus every effect whose output this request
        reads. The fallback to the run frontier keeps the graph connected when no data
        edge is detectable (the first crossing of a run, or a request carrying no
        recoverable text), so an effect is never orphaned.
        """
        parents: list[str] = []
        own = self._last_by_agent.get(agent)
        if own:
            parents.append(own)
        for candidate in extra:
            if candidate not in parents:
                parents.append(candidate)
        if not parents:
            if self._last_global:
                parents.append(self._last_global)
            elif self._seed_parents:
                parents.extend(self._seed_parents)
        return tuple(parents)

    def _advance(self, agent: str, address: str) -> None:
        self._last_by_agent[agent] = address
        self._last_global = address
        self.visited.append(address)

    # -- record / replay core --------------------------------------------------

    def _resolve(self, address: str) -> Effect | None:
        """Consult the store, honouring the current mode."""
        if self.mode is Mode.RECORD:
            return None
        found = self.store.lookup(self.branch_id, address)
        if found is None and self.mode is Mode.REPLAY_STRICT:
            raise ReplayMiss(
                f"no recorded effect at address {address[:12]} on branch "
                f"{self.branch_id}; execution diverged where determinism was asserted"
            )
        return found

    def _open(
        self,
        *,
        agent: str,
        kind: EffectKind,
        determinism: Determinism,
        request: dict[str, Any],
        extra_parents: tuple[str, ...] = (),
    ) -> tuple[Effect, Effect | None]:
        """Compute an address, look it up, and return (opened effect, cached hit)."""
        parents = self._parents_for(agent, extra_parents)
        effect = Effect.create(
            branch_id=self.branch_id,
            seq=0,  # assigned at flush; never part of the address
            agent=agent,
            kind=kind,
            determinism=determinism,
            causal_parents=parents,
            request=request,
        )
        return effect, self._resolve(effect.id)

    def _close(self, effect: Effect, response: dict[str, Any] | None, **kw: Any) -> None:
        closed = effect.with_response(response, **kw)
        self.recorded.append(closed)
        # Written through immediately rather than only at flush.
        #
        # There is otherwise a window between a leader resolving its single-flight promise
        # and its invocation ending: the in-flight entry is gone, the store does not yet
        # hold the answer, and an agent arriving in that gap misses both and pays for a
        # question already answered. It is small, it is real, and it is exactly the kind of
        # duplicate that quietly erodes a collapse ratio under load — measured here as one
        # extra call in 120 agents before this line existed.
        if not closed.replayed:
            self.store.put(closed.with_seq(self.store.next_seq(self.branch_id)))
            self._written.add(closed.id)

    def _record_pure(
        self,
        *,
        agent: str,
        kind: EffectKind,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> str:
        """Record a deterministic structural effect, reusing the stored copy on a hit.

        Agent entry and delegation cost nothing to recompute, but they still have to be
        cache-resolved: if a replay wrote fresh copies of them, an unperturbed fork would
        accumulate storage and the DAG root hash would drift. They are deliberately kept
        out of `hits`/`misses`, which measure paid crossings.
        """
        effect, cached = self._open(
            agent=agent,
            kind=kind,
            determinism=Determinism.PURE,
            request=request,
        )
        if cached is not None:
            self.recorded.append(cached.with_response(cached.response, replayed=True))
        else:
            self._close(effect, response)
        self._advance(agent, effect.id)
        return effect.id

    # -- model boundary --------------------------------------------------------

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        agent = callback_context.agent_name
        request = canonical_llm_request(llm_request)
        effect, cached = self._open(
            agent=agent,
            kind=EffectKind.MODEL_CALL,
            determinism=Determinism.RECORDED,
            request=request,
            extra_parents=tuple(self._data_parents(request["contents"])),
        )
        self._advance(agent, effect.id)
        self.served_model.append(effect.id)

        if cached is not None and cached.response:
            # Replay hit: the model is never called.
            self.hits += 1
            self.recorded.append(cached.with_response(cached.response, replayed=True))
            recorded_response = cached.response["llm_response"]
            self._register_producer(effect.id, recorded_response.get("content"))
            return LlmResponse.model_validate(recorded_response)

        if self._single_flight is not None:
            waiting = self._single_flight.begin(effect.id)
            if waiting is not None:
                # Someone is already asking this exact question. Wait for their answer
                # rather than paying for the same one. Without this the collapse degrades
                # precisely as concurrency rises -- the one thing you would raise to make
                # a swarm fast.
                shared = await waiting
                if shared is not None:
                    self.coalesced += 1
                    self.recorded.append(effect.with_response(shared, replayed=True))
                    self._register_producer(
                        effect.id, shared["llm_response"].get("content")
                    )
                    return LlmResponse.model_validate(shared["llm_response"])

        self.misses += 1
        self.diverged.append(effect.id)
        self._pending[_model_key(agent, effect.id)] = (effect, time.perf_counter())
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        agent = callback_context.agent_name
        entry = self._take_pending_model(agent)
        if entry is None:
            # No pending open: before_model_callback served this from the store.
            return None
        effect, started = entry

        content = (
            llm_response.content.model_dump(mode="json", exclude_none=True)
            if llm_response.content
            else None
        )
        self._register_producer(effect.id, content)

        usage = llm_response.usage_metadata
        tokens_in = getattr(usage, "prompt_token_count", 0) or 0
        tokens_out = getattr(usage, "candidates_token_count", 0) or 0
        payload = {"llm_response": llm_response.model_dump(mode="json", exclude_none=True)}
        self._close(
            effect,
            payload,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=(tokens_in * PRICE_IN_PER_M + tokens_out * PRICE_OUT_PER_M) / 1e6,
            wall_ms=(time.perf_counter() - started) * 1000.0,
        )
        if self._single_flight is not None:
            self._single_flight.resolve(effect.id, payload)
        return None

    def _take_pending_model(self, agent: str) -> tuple[Effect, float] | None:
        """The pending model effect for this agent.

        ADK hands `after_model_callback` no address, so the entry is found by prefix.
        Only one call per agent is outstanding within a single invocation; the address in
        the key is what keeps *different* invocations from colliding.
        """
        prefix = f"model:{agent}:"
        for key in list(self._pending):
            if key.startswith(prefix):
                return self._pending.pop(key)
        return None

    # -- tool boundary ---------------------------------------------------------

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        agent = tool_context.agent_name
        determinism = self.registry.classify(tool.name)
        request: dict[str, Any] = {"tool": tool.name, "args": tool_args}
        reads = self.registry.reads_of(tool.name)
        if reads and self._state_fingerprint is not None:
            request["reads"] = {"collections": list(reads),
                                "state": self._state_fingerprint(reads)}
        if self.gateway is not None:
            from gateway.policy import Request as GatewayRequest, denied_result

            decision = self.gateway.check(GatewayRequest(
                agent=agent, tool=tool.name, args=tool_args,
                branch_id=self.branch_id, determinism=determinism,
            ))
            if not decision.allowed:
                # The refusal is an effect. It has an address, a causal position and a
                # reason, so replaying reproduces it at the same point and forking with a
                # relaxed policy shows exactly which refusals disappear.
                refusal, _ = self._open(
                    agent=agent,
                    kind=EffectKind.GATEWAY_DENIED,
                    determinism=Determinism.PURE,
                    request={"tool": tool.name, "args": tool_args,
                             "rule": decision.rule},
                )
                self._advance(agent, refusal.id)
                result = denied_result(decision, tool.name)
                self._close(refusal, {"result": result})
                return result

        effect, cached = self._open(
            agent=agent,
            kind=EffectKind.TOOL_CALL,
            determinism=determinism,
            request=request,
        )
        self._advance(agent, effect.id)

        if cached is not None and cached.response:
            self.hits += 1
            self.recorded.append(cached.with_response(cached.response, replayed=True))
            self._register_producer(
                effect.id,
                {"parts": [{"function_response": {"response": cached.response["result"]}}]},
            )
            return cached.response["result"]

        self.misses += 1
        self.diverged.append(effect.id)

        # The quarantine gate. An irreversible action off the primary branch is never
        # dispatched; it is recorded as a counterfactual and the agent is handed a
        # well-formed success so its subsequent reasoning is unchanged.
        if (
            determinism is Determinism.EXTERNAL_IRREVERSIBLE
            and self.branch_id != PRIMARY
        ):
            result = staged_result(self.registry, tool.name, tool_args)
            self._close(effect, {"result": result}, quarantined=True)
            return result

        self._pending[_tool_key(agent, tool.name, tool_args)] = (effect, time.perf_counter())
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        agent = tool_context.agent_name
        entry = self._pending.pop(_tool_key(agent, tool.name, tool_args), None)
        if entry is None:
            return None
        effect, started = entry
        self._register_producer(
            effect.id, {"parts": [{"function_response": {"response": result}}]}
        )
        self._close(
            effect,
            {"result": result},
            wall_ms=(time.perf_counter() - started) * 1000.0,
            meta={
                "compensator": self.registry.compensate(tool.name, tool_args, result) or {},
            },
        )
        return None

    # -- agent boundary --------------------------------------------------------

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> None:
        # Push before addressing so `_parents_for` sees the caller directly beneath this
        # agent on the stack and records delegation as a real causal edge.
        self._agent_stack.append(agent.name)
        self._record_pure(
            agent=agent.name,
            kind=EffectKind.AGENT_ENTER,
            request={"agent": agent.name},
            response={"entered": True},
        )
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> None:
        if self._agent_stack and self._agent_stack[-1] == agent.name:
            self._agent_stack.pop()
        return None

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> None:
        """Capture explicit delegation as a causal edge.

        ADK signals a handoff via `actions.transfer_to_agent`. Recording it makes the
        edge between two agents' work explicit in the DAG instead of leaving it implied
        by ordering.
        """
        target = getattr(event.actions, "transfer_to_agent", None) if event.actions else None
        if not target:
            return None
        source = event.author or (self._agent_stack[-1] if self._agent_stack else "root")
        address = self._record_pure(
            agent=source,
            kind=EffectKind.DELEGATION,
            request={"from": source, "to": target},
            response={"transferred": True},
        )
        # Seed the callee so its first effect descends from the handoff rather than
        # appearing as an unrelated root in the graph.
        self._last_by_agent[target] = address
        return None

    # -- persistence -----------------------------------------------------------

    def flush(self) -> list[Effect]:
        """Assign sequence numbers and persist this run's effects and visit manifest.

        Only executed effects are written; replay hits are resolved through the branch
        chain, which is what keeps a fork cheap. The manifest records the order of every
        address visited so a branch timeline can be materialised without copying its
        parent's history.
        """
        stamped = [
            effect.with_seq(self.store.next_seq(self.branch_id))
            for effect in self.recorded
            if not effect.replayed and effect.id not in self._written
        ]
        self.store.put_many(stamped)
        self.store.append_manifest(self.branch_id, self.visited)
        return stamped

    def report(self) -> dict[str, Any]:
        """Measurements for this run.

        `cost_usd` is what this run actually spent; `cost_avoided_usd` is what the same
        work cost when it was first recorded and did not cost again. The gap between
        them is the product.
        """
        executed = [e for e in self.recorded if not e.replayed]
        reused = [e for e in self.recorded if e.replayed]
        total = self.hits + self.misses
        return {
            "mode": self.mode.value,
            "branch": self.branch_id,
            "boundary_crossings": total,
            "replay_hits": self.hits,
            "coalesced": self.coalesced,
            "executed": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "diverged": len(self.diverged),
            "effects_written": len(executed),
            "effects_reused": len(reused),
            "tokens_in": sum(e.tokens_in for e in executed),
            "tokens_out": sum(e.tokens_out for e in executed),
            "cost_usd": round(sum(e.cost_usd for e in executed), 6),
            "cost_avoided_usd": round(sum(e.cost_usd for e in reused), 6),
            "quarantined": sum(1 for e in self.recorded if e.quarantined),
        }
