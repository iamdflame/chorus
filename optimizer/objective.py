"""Scoring a timeline in the units the business argues in.

An optimiser is only as good as what it maximises, and "the agents seemed better" is not
a number. Every candidate policy is scored against the *same* recorded history, so the
comparison is like-for-like: identical disputes, identical customers, identical facts —
only the policy differs.

The objective is deliberately multi-term and signed in dollars. A single-term objective
("minimise refunds") is trivially gamed by a policy that escalates everything to a human,
which is not an improvement, it is a cost transfer. Escalation therefore carries a real
handling cost, and wrongly refusing a legitimate dispute carries a churn cost, so the
optimum is an actual trade-off rather than a corner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fleet.domain import COMMS, DISPUTES, LEDGER, TICKETS

# Loaded costs, in USD. These are the assumptions the whole search rests on, so they are
# stated in one place where they can be argued with rather than buried in a formula.
HUMAN_REVIEW_COST = 18.00      # analyst time to work one escalated ticket
CHURN_COST_MULTIPLE = 2.4      # lost lifetime value when a valid dispute is refused
CONTACT_COST = 0.35            # cost of one outbound customer notification


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one timeline actually did, in money."""

    branch_id: str
    label: str
    refunds_issued: int
    refunds_usd: float
    escalations: int
    notifications: int
    disputes_resolved: int
    wrongful_refunds_usd: float
    missed_valid_usd: float
    compute_usd: float
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def escalation_cost(self) -> float:
        return self.escalations * HUMAN_REVIEW_COST

    @property
    def contact_cost(self) -> float:
        return self.notifications * CONTACT_COST

    @property
    def total_cost_usd(self) -> float:
        """Everything this policy cost the business on this history.

        Refunds that were owed are not a cost — paying a valid dispute is the correct
        outcome. Only wrongful payouts, human handling, churn from wrong refusals, and
        compute count against a policy.
        """
        return round(
            self.wrongful_refunds_usd
            + self.escalation_cost
            + self.missed_valid_usd
            + self.contact_cost
            + self.compute_usd,
            2,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "label": self.label,
            "refunds_issued": self.refunds_issued,
            "refunds_usd": round(self.refunds_usd, 2),
            "escalations": self.escalations,
            "notifications": self.notifications,
            "disputes_resolved": self.disputes_resolved,
            "wrongful_refunds_usd": round(self.wrongful_refunds_usd, 2),
            "missed_valid_usd": round(self.missed_valid_usd, 2),
            "escalation_cost_usd": round(self.escalation_cost, 2),
            "contact_cost_usd": round(self.contact_cost, 2),
            "compute_usd": round(self.compute_usd, 6),
            "total_cost_usd": self.total_cost_usd,
        }


def is_wrongful(dispute: dict[str, Any], customer: dict[str, Any]) -> bool:
    """Ground truth for whether a refund should not have been paid.

    Derived from the seeded facts, not from what any agent decided — otherwise the
    optimiser would be scoring itself against its own opinion. A refund is wrongful when
    the claim shows the fraud signature the policy corpus exists to catch: a repeat
    disputer on a non-duplicate claim.
    """
    return (
        customer.get("prior_disputes", 0) >= 3
        and dispute.get("reason") != "duplicate_charge"
    )


def is_valid_claim(dispute: dict[str, Any], customer: dict[str, Any]) -> bool:
    """A dispute that genuinely deserved payment."""
    return not is_wrongful(dispute, customer)


def score(
    *,
    world,
    branch_id: str,
    label: str,
    dispute_ids: list[str],
    compute_usd: float,
    quarantined_actions: list[dict[str, Any]] | None = None,
) -> Outcome:
    """Score one timeline against the disputes it was asked to handle.

    Reads the branch's own view of the world, so a counterfactual is measured on the
    state it actually produced. Irreversible actions that were quarantined still count:
    the agent chose them, and the point of a counterfactual is what the fleet *would*
    have done, not what the sandbox permitted.
    """
    from fleet.domain import CUSTOMERS

    ledger = world.scan(branch_id=branch_id, collection=LEDGER)
    tickets = world.scan(branch_id=branch_id, collection=TICKETS)
    comms = world.scan(branch_id=branch_id, collection=COMMS)
    disputes = world.scan(branch_id=branch_id, collection=DISPUTES)
    customers = world.scan(branch_id=branch_id, collection=CUSTOMERS)

    staged = quarantined_actions or []
    staged_refunds = [a for a in staged if "refund" in (a.get("action") or "")]
    staged_escalations = [a for a in staged if "escalate" in (a.get("action") or "")]
    staged_emails = [a for a in staged if "email" in (a.get("action") or "")]

    refunds = [e for e in ledger.values() if e.get("type") == "refund"]
    refunds_usd = sum(e.get("amount_usd", 0.0) for e in refunds)

    wrongful = 0.0
    for entry in refunds:
        dispute = disputes.get(entry.get("dispute_id", ""), {})
        customer = customers.get(dispute.get("customer_id", ""), {})
        if dispute and customer and is_wrongful(dispute, customer):
            wrongful += entry.get("amount_usd", 0.0)

    # A valid claim that was escalated rather than paid is a churn risk, not a saving.
    missed = 0.0
    escalated_ids = {t.get("dispute_id") for t in tickets.values()}
    escalated_ids |= {
        a.get("action", "").split()[1] for a in staged_escalations
        if len(a.get("action", "").split()) > 1
    }
    for dispute_id in escalated_ids:
        dispute = disputes.get(dispute_id or "", {})
        customer = customers.get(dispute.get("customer_id", ""), {})
        if dispute and customer and is_valid_claim(dispute, customer):
            missed += dispute.get("amount_usd", 0.0) * (CHURN_COST_MULTIPLE - 1.0)

    resolved = sum(
        1 for did in dispute_ids
        if disputes.get(did, {}).get("status") in ("resolved", "escalated", "rejected")
    )

    return Outcome(
        branch_id=branch_id,
        label=label,
        refunds_issued=len(refunds) + len(staged_refunds),
        refunds_usd=refunds_usd,
        escalations=len(tickets) + len(staged_escalations),
        notifications=len(comms) + len(staged_emails),
        disputes_resolved=resolved,
        wrongful_refunds_usd=wrongful,
        missed_valid_usd=missed,
        compute_usd=compute_usd,
        detail={"staged": len(staged)},
    )
