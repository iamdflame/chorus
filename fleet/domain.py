"""The financial-operations domain the fleet works in.

Chosen because it makes the abstract concrete in the only units that settle an argument:
dollars. A counterfactual that reports "17 fewer effects" is a curiosity. One that reports
"$18,240 of refunds that should never have been issued" is a decision.

The seed generator produces a genuine three-week operating history — disputes arriving on
a realistic diurnal curve, customers with real tiers and histories, a policy corpus the
agents actually retrieve from. Nothing here is a fixture the demo reads back: the fleet
runs against this data, and every number the console shows is derived from effects the
agents really produced.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Collections in the Shadow World.
DISPUTES = "disputes"
CUSTOMERS = "customers"
LEDGER = "ledger"
POLICIES = "policies"
COMMS = "communications"
TICKETS = "tickets"

TIERS = ("standard", "standard", "standard", "plus", "plus", "enterprise")
REASONS = (
    "duplicate_charge",
    "item_not_received",
    "item_not_as_described",
    "unauthorised_transaction",
    "subscription_not_cancelled",
    "quality_complaint",
)
COUNTRIES = ("US", "US", "US", "GB", "DE", "FR", "CA", "NG", "IN", "BR")
EU_COUNTRIES = frozenset({"DE", "FR", "IE", "NL", "ES", "IT"})


@dataclass(slots=True)
class Customer:
    id: str
    name: str
    email: str
    tier: str
    country: str
    lifetime_value_usd: float
    prior_disputes: int

    @property
    def is_eu(self) -> bool:
        return self.country in EU_COUNTRIES


@dataclass(slots=True)
class Dispute:
    id: str
    customer_id: str
    order_id: str
    amount_usd: float
    reason: str
    opened_at: str
    status: str = "open"
    resolution: str | None = None
    handled_by: str | None = None


@dataclass(slots=True)
class PolicyClause:
    """One retrievable rule.

    Split into clauses rather than held as one document because the agents retrieve them
    by similarity, and because a counterfactual that edits a single clause should perturb
    only the decisions that actually read it.
    """

    id: str
    title: str
    text: str
    version: int = 1
    tags: list[str] = field(default_factory=list)


# The live policy corpus. `AUTO_APPROVE_CEILING` is the clause the demo perturbs: it is
# the single line that decides whether a dispute is settled automatically or escalated,
# so a change to it has a large, well-defined, and entirely computable blast radius.
POLICY_CORPUS: list[PolicyClause] = [
    PolicyClause(
        id="POL-REFUND-CEILING",
        title="Automatic refund ceiling",
        text=(
            "Disputes with a claimed amount at or below USD 500.00 may be auto-approved "
            "for full refund without human review, provided the customer has fewer than "
            "three prior disputes. Amounts above the ceiling must be escalated."
        ),
        tags=["refund", "ceiling", "auto-approve"],
    ),
    PolicyClause(
        id="POL-DUPLICATE",
        title="Duplicate charges",
        text=(
            "A verified duplicate charge is always refunded in full regardless of amount. "
            "Duplicate charges do not count toward the customer's prior dispute total."
        ),
        tags=["refund", "duplicate"],
    ),
    PolicyClause(
        id="POL-REPEAT",
        title="Repeat disputers",
        text=(
            "Customers with three or more prior disputes in a rolling ninety day window "
            "must be escalated to a human reviewer irrespective of amount."
        ),
        tags=["fraud", "escalation"],
    ),
    PolicyClause(
        id="POL-EU-DATA",
        title="EU data handling",
        text=(
            "Personal data belonging to customers resident in the European Union may not "
            "be transmitted to systems outside the EU processing region. Agents handling "
            "EU customers must redact identifiers before any outbound communication."
        ),
        tags=["compliance", "gdpr", "pii"],
    ),
    PolicyClause(
        id="POL-ENTERPRISE",
        title="Enterprise accounts",
        text=(
            "Enterprise tier disputes are never auto-approved. They route to the named "
            "account manager with a summary and a recommended action."
        ),
        tags=["enterprise", "escalation"],
    ),
    PolicyClause(
        id="POL-COMMS",
        title="Customer communication",
        text=(
            "Every resolved dispute requires exactly one outbound notification to the "
            "customer stating the outcome and the amount. Never send more than one "
            "notification for the same dispute."
        ),
        tags=["comms", "notification"],
    ),
]

FIRST_NAMES = ("Amara", "Tobias", "Wen", "Priya", "Lucas", "Ines", "Kwame", "Sofia",
               "Yusuf", "Maja", "Diego", "Nneka", "Anders", "Leila", "Hiroshi", "Rosa")
LAST_NAMES = ("Okafor", "Lindqvist", "Zhang", "Raman", "Moreau", "Costa", "Mensah",
              "Rossi", "Demir", "Kowalski", "Alvarez", "Eze", "Berg", "Haddad")


def build_customers(rng: random.Random, count: int) -> list[Customer]:
    customers: list[Customer] = []
    for i in range(count):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        tier = rng.choice(TIERS)
        customers.append(
            Customer(
                id=f"CUST-{4000 + i}",
                name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}@example.com",
                tier=tier,
                country=rng.choice(COUNTRIES),
                lifetime_value_usd=round(
                    rng.uniform(120, 900) * {"standard": 1, "plus": 4, "enterprise": 22}[tier], 2
                ),
                # Deliberately skewed: most customers have never disputed, a few are
                # repeat disputers. The repeat-disputer clause only bites on the tail,
                # which is what makes the policy interaction interesting.
                prior_disputes=rng.choices([0, 0, 0, 1, 1, 2, 3, 4], k=1)[0],
            )
        )
    return customers


def build_disputes(
    rng: random.Random, customers: list[Customer], count: int, days: int
) -> list[Dispute]:
    """Disputes arriving over `days`, with a realistic amount distribution.

    Amounts are log-normal-ish rather than uniform: most disputes are small, a thin tail
    is large. That shape is what makes the refund ceiling a meaningful decision boundary
    instead of an arbitrary one.
    """
    start = datetime.now(timezone.utc) - timedelta(days=days)
    disputes: list[Dispute] = []
    for i in range(count):
        customer = rng.choice(customers)
        reason = rng.choice(REASONS)
        magnitude = rng.choices([1, 1, 1, 1, 2, 2, 3], k=1)[0]
        amount = round(rng.uniform(15, 180) * (3.4 ** (magnitude - 1)), 2)
        opened = start + timedelta(
            days=rng.uniform(0, days),
            hours=rng.triangular(6, 22, 14),  # business-hours weighted
        )
        disputes.append(
            Dispute(
                id=f"D-{4400 + i}",
                customer_id=customer.id,
                order_id=f"ORD-{88000 + rng.randrange(1, 9000)}",
                amount_usd=amount,
                reason=reason,
                opened_at=opened.isoformat(timespec="seconds"),
            )
        )
    disputes.sort(key=lambda d: d.opened_at)
    return disputes


@dataclass(slots=True)
class Seed:
    customers: list[Customer]
    disputes: list[Dispute]
    policies: list[PolicyClause]

    def summary(self) -> dict[str, Any]:
        amounts = [d.amount_usd for d in self.disputes]
        return {
            "customers": len(self.customers),
            "disputes": len(self.disputes),
            "policy_clauses": len(self.policies),
            "total_at_stake_usd": round(sum(amounts), 2),
            "median_dispute_usd": round(sorted(amounts)[len(amounts) // 2], 2) if amounts else 0,
            "over_ceiling": sum(1 for a in amounts if a > 500),
            "eu_customers": sum(1 for c in self.customers if c.is_eu),
        }


def build_seed(*, customers: int = 60, disputes: int = 120, days: int = 21, seed: int = 8891) -> Seed:
    """Deterministic three-week operating history.

    Fixed seed so the demo, the tests and the recorded timeline all describe the same
    world — a counterfactual is only meaningful against a history that does not move.
    """
    rng = random.Random(seed)
    people = build_customers(rng, customers)
    return Seed(
        customers=people,
        disputes=build_disputes(rng, people, disputes, days),
        policies=list(POLICY_CORPUS),
    )


def load_into_world(world, seed_data: Seed, *, branch_id: str, start_seq: int = 0) -> int:
    """Write the seed into the Shadow World as versioned state. Returns the next seq."""
    seq = start_seq
    for customer in seed_data.customers:
        seq += 1
        world.write(branch_id=branch_id, collection=CUSTOMERS, key=customer.id,
                    value=asdict(customer), seq=seq)
    for clause in seed_data.policies:
        seq += 1
        world.write(branch_id=branch_id, collection=POLICIES, key=clause.id,
                    value=asdict(clause), seq=seq)
    for dispute in seed_data.disputes:
        seq += 1
        world.write(branch_id=branch_id, collection=DISPUTES, key=dispute.id,
                    value=asdict(dispute), seq=seq)
    return seq
