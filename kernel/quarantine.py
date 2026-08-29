"""Reversibility classification and the quarantine gate.

Replay is only half the problem. Re-running an agent's reasoning is free; re-running its
*side effects* is not — a replayed run must not send the customer a second email or issue
the refund again.

Most systems answer this by running counterfactuals against a mock. That is a bad answer:
the moment you swap the tools, you are no longer replaying the system you are trying to
reason about, and the result proves nothing about production.

Lightcone answers it by classifying every tool by what it does to the world, and gating
only the subset that genuinely cannot be undone:

    PURE / RECORDED        replayed from the record, never re-executed
    EXTERNAL_REVERSIBLE    re-executed against the branch's shadow state, compensator kept
    EXTERNAL_IRREVERSIBLE  quarantined off-primary: never executed, recorded as counterfactual

Quarantine is the honest engineering position. An email cannot be unsent, so the system
refuses to pretend otherwise: on a branch it records exactly what *would* have been sent,
with the same arguments the agent actually chose, and shows it as a staged action. Nothing
about the agent changes — it receives a well-formed success result and continues reasoning
— but the blast radius stops at the process boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kernel.effect import Determinism

# A compensator turns a completed effect into the action that undoes it.
# Returns None when the effect needs no compensation.
Compensator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class ToolClass:
    """How one tool behaves with respect to the world."""

    name: str
    determinism: Determinism
    compensator: Compensator | None = None
    # Shown in the console when an action is staged rather than executed.
    describe: Callable[[dict[str, Any]], str] | None = None
    # World collections this tool reads. Folded into the tool's address so that a change
    # to the data it consults invalidates it, and a change elsewhere does not.
    reads: tuple[str, ...] = ()


class ReversibilityRegistry:
    """Maps tool names to their world-effect classification.

    The default is deliberately the *safest* class, not the most convenient one: an
    unregistered tool is treated as irreversible and is quarantined off-primary. A
    forgotten registration therefore causes a visibly staged action, never an
    unintended real-world side effect.
    """

    def __init__(self, default: Determinism = Determinism.EXTERNAL_IRREVERSIBLE) -> None:
        self._tools: dict[str, ToolClass] = {}
        self._default = default

    def register(
        self,
        name: str,
        determinism: Determinism,
        *,
        compensator: Compensator | None = None,
        describe: Callable[[dict[str, Any]], str] | None = None,
        reads: tuple[str, ...] = (),
    ) -> None:
        if determinism is Determinism.EXTERNAL_REVERSIBLE and compensator is None:
            raise ValueError(
                f"tool {name!r} is declared reversible but supplies no compensator; "
                "reversibility without a compensator is just an untested claim"
            )
        self._tools[name] = ToolClass(
            name=name, determinism=determinism, compensator=compensator,
            describe=describe, reads=tuple(reads),
        )

    def classify(self, name: str) -> Determinism:
        entry = self._tools.get(name)
        return entry.determinism if entry else self._default

    def get(self, name: str) -> ToolClass | None:
        return self._tools.get(name)

    def compensate(
        self, name: str, args: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Build the action that would undo a completed effect, if one exists."""
        entry = self._tools.get(name)
        if entry is None or entry.compensator is None:
            return None
        return entry.compensator(args, result)

    def describe(self, name: str, args: dict[str, Any]) -> str:
        entry = self._tools.get(name)
        if entry and entry.describe:
            return entry.describe(args)
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(args.items()))
        return f"{name}({rendered})"

    def reads_of(self, name: str) -> tuple[str, ...]:
        entry = self._tools.get(name)
        return entry.reads if entry else ()

    def registered(self) -> dict[str, Determinism]:
        return {name: tc.determinism for name, tc in sorted(self._tools.items())}


def staged_result(registry: ReversibilityRegistry, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The synthetic result handed to an agent whose irreversible action was quarantined.

    Shaped to look like a normal success so the agent's reasoning is unaffected — the
    counterfactual is only useful if the agent behaves exactly as it would have in
    production — while remaining unambiguously identifiable downstream via
    `_lightcone_staged`.
    """
    return {
        "status": "ok",
        "_lightcone_staged": True,
        "_lightcone_action": registry.describe(name, args),
        "detail": (
            "Action accepted. Executed against branch state; not dispatched to external "
            "systems because this timeline is not production."
        ),
    }
