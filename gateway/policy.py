"""The agent gateway — every tool call passes a policy, and every denial is an effect.

Most agent systems enforce tool access with a prompt: the instruction lists what the agent
may use and everyone hopes it complies. That is not enforcement, it is etiquette. Where
this project can push the boundary into IAM it does (`infra/identity.sh`), but IAM cannot
express *this agent may not use this tool on this branch with these arguments*, and that is
the layer the gateway occupies.

The property worth having is not the gate — anyone can write an if-statement — it is what
happens to a denial afterwards. **A denial is recorded as an effect**, which means it is
content-addressed, replayable, and diffable across branches like everything else:

    it is auditable        a refusal has an address, a causal position and a reason,
                           rather than being a log line that may or may not exist
    it is replayable       replaying the run reproduces the refusal at the same point
                           without re-running the policy engine
    it is diffable         forking the timeline and relaxing the policy shows exactly
                           which refusals disappear and what the fleet then did

That last one is the novel bit. "What would this fleet have done if it had been allowed?"
becomes a branch and a diff rather than a thought experiment.

Denials are deliberately *not* silent to the agent, and not lies either. The agent is told
it was refused and why, which is the only version that leaves the transcript honest — an
agent handed a fabricated success learns the wrong lesson and an auditor reading the
transcript is misled about what the fleet believed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from kernel.branch import PRIMARY
from kernel.effect import Determinism

# A rule sees the request and returns a reason to deny, or None to permit.
Rule = Callable[["Request"], "str | None"]


@dataclass(frozen=True, slots=True)
class Request:
    """One attempted tool call, as the gateway sees it."""

    agent: str
    tool: str
    args: dict[str, Any]
    branch_id: str
    determinism: Determinism


@dataclass(frozen=True, slots=True)
class Decision:
    """Permit or deny, always with a reason.

    A denial without a reason is unactionable — the operator cannot tell a working control
    from a misconfiguration — so the reason is not optional.
    """

    allowed: bool
    reason: str = ""
    rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "rule": self.rule}


def denied_result(decision: Decision, tool: str) -> dict[str, Any]:
    """What the agent is handed when it is refused.

    An honest refusal rather than a fabricated success. The agent can reason about being
    denied — ask for help, take another route, stop — and the transcript records what
    actually happened. This is the opposite choice from the quarantine gate, and the
    difference is deliberate: quarantine hides a *branch* from the world while keeping the
    agent's reasoning identical to production, whereas a denial is a real policy event the
    agent is entitled to know about.
    """
    return {
        "status": "denied",
        "_gateway_denied": True,
        "_gateway_rule": decision.rule,
        "error": f"{tool} refused by policy: {decision.reason}",
    }


class Gateway:
    """Rules, evaluated in order, first denial wins."""

    def __init__(self) -> None:
        self._rules: list[tuple[str, Rule]] = []
        self.permitted = 0
        self.denied = 0
        self.denials: list[tuple[Request, Decision]] = []

    def rule(self, name: str, fn: Rule) -> Gateway:
        self._rules.append((name, fn))
        return self

    def check(self, request: Request) -> Decision:
        for name, fn in self._rules:
            reason = fn(request)
            if reason:
                decision = Decision(allowed=False, reason=reason, rule=name)
                self.denied += 1
                self.denials.append((request, decision))
                return decision
        self.permitted += 1
        return Decision(allowed=True)

    def report(self) -> dict[str, Any]:
        return {
            "permitted": self.permitted,
            "denied": self.denied,
            "rules": [name for name, _ in self._rules],
            "denials": [
                {"agent": r.agent, "tool": r.tool, "branch": r.branch_id,
                 **d.to_dict()}
                for r, d in self.denials
            ],
        }


# -- the default policy ------------------------------------------------------

def allowlist(per_agent: dict[str, set[str]]) -> Rule:
    """Each agent may call only the tools its card declares.

    Read from the registry rather than written twice: a tool an agent does not declare is
    a tool it cannot call, so the agent card stops being documentation and becomes the
    enforcement surface.
    """

    def check(request: Request) -> str | None:
        allowed = per_agent.get(request.agent)
        if allowed is None:
            return f"agent {request.agent!r} has no published card"
        if request.tool not in allowed:
            return f"{request.tool!r} is not declared by {request.agent!r}"
        return None

    return check


def no_irreversible_off_primary(request: Request) -> str | None:
    """Belt to the quarantine gate's braces.

    The interposer already stages irreversible actions off primary, and this refuses them
    outright. Two mechanisms for one hazard is not redundancy here: quarantine keeps the
    agent's reasoning identical to production, which is what a counterfactual needs, while
    this exists so a tool that is *never* acceptable off primary can say so and be denied
    rather than staged.
    """
    if (
        request.determinism is Determinism.EXTERNAL_IRREVERSIBLE
        and request.branch_id != PRIMARY
        and request.args.get("force") is True
    ):
        return "forced irreversible action attempted on a non-primary branch"
    return None


def argument_cap(tool: str, field: str, limit: float) -> Rule:
    """Refuse a value beyond a declared bound.

    A refund agent that can issue any amount is one prompt injection away from issuing
    every amount. The cap belongs in policy rather than in the instruction, because an
    instruction is a suggestion to a model and this is not.
    """

    def check(request: Request) -> str | None:
        if request.tool != tool:
            return None
        try:
            value = float(request.args.get(field, 0))
        except (TypeError, ValueError):
            return f"{field} is not a number"
        if value > limit:
            return f"{field}={value:g} exceeds the policy limit of {limit:g}"
        return None

    return check


def default_gateway(per_agent: dict[str, set[str]] | None = None) -> Gateway:
    gateway = Gateway()
    if per_agent:
        gateway.rule("agent-card-allowlist", allowlist(per_agent))
    gateway.rule("no-forced-irreversible-off-primary", no_irreversible_off_primary)
    gateway.rule("refund-cap", argument_cap("issue_refund", "amount_usd", 5_000.0))
    return gateway
