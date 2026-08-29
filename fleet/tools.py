"""The fleet's tools, and their honest classification.

Every tool here is bound to a branch. It reads and writes the Shadow World rather than a
global database, which is what lets a counterfactual mutate "production" without touching
it. The agent is unaware of any of this: it calls `issue_refund` and gets a refund result,
on production and on a fork alike.

Each tool is registered with its reversibility class, and reversible ones must supply a
compensator — a function that produces the action undoing them. Declaring something
reversible without being able to say how to reverse it is an untested claim, so the
registry rejects it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from fleet.domain import COMMS, CUSTOMERS, DISPUTES, LEDGER, POLICIES, TICKETS
from kernel.effect import Determinism
from kernel.quarantine import ReversibilityRegistry
from world.shadow import ShadowWorld


@dataclass
class FleetContext:
    """Everything a tool needs to act on one branch at one moment."""

    world: ShadowWorld
    branch_id: str
    _counter: int = 0

    def seq(self) -> int:
        self._counter += 1
        return self._counter

    def sync_seq(self, floor: int) -> None:
        """Keep state versions ordered above the history already loaded."""
        self._counter = max(self._counter, floor)


# -- retrieval ----------------------------------------------------------------

_EMBED_MODEL = "gemini-embedding-001"
_embed_cache: dict[str, list[float]] = {}


def _embed(text: str) -> list[float]:
    """Embed text via the Gemini API, cached per process.

    Cached because the policy corpus is embedded on every retrieval otherwise, and an
    embedding call is a network round trip with a price attached. The cache is keyed by
    exact text, so a policy edit correctly produces a new vector.
    """
    if text in _embed_cache:
        return _embed_cache[text]
    from google import genai

    client = genai.Client()
    result = client.models.embed_content(model=_EMBED_MODEL, contents=text)
    vector = list(result.embeddings[0].values)
    _embed_cache[text] = vector
    return vector


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# -- tool factory -------------------------------------------------------------

def build_tools(ctx: FleetContext) -> tuple[list[Callable[..., dict]], ReversibilityRegistry]:
    """Construct branch-bound tools and the registry describing what they do.

    Returned together deliberately: a tool that reaches the world without a registered
    reversibility class is a tool that can escape quarantine, so they are never
    constructed apart.
    """

    def _read(collection: str, key: str) -> dict[str, Any] | None:
        return ctx.world.read(branch_id=ctx.branch_id, collection=collection, key=key)

    def _write(collection: str, key: str, value: Any) -> None:
        ctx.world.write(
            branch_id=ctx.branch_id, collection=collection, key=key,
            value=value, seq=ctx.seq(),
        )

    # -- reads -----------------------------------------------------------------

    def get_dispute(dispute_id: str) -> dict:
        """Look up a customer dispute by its id.

        Args:
            dispute_id: The dispute identifier, for example D-4471.
        """
        found = _read(DISPUTES, dispute_id)
        if not found:
            return {"status": "not_found", "dispute_id": dispute_id}
        return {"status": "ok", "dispute": found}

    def get_customer(customer_id: str) -> dict:
        """Look up a customer record, including tier and prior dispute count.

        Args:
            customer_id: The customer identifier, for example CUST-4003.
        """
        found = _read(CUSTOMERS, customer_id)
        if not found:
            return {"status": "not_found", "customer_id": customer_id}
        return {"status": "ok", "customer": found}

    def search_policy(query: str) -> dict:
        """Retrieve the policy clauses most relevant to a question.

        Args:
            query: A natural language description of the decision being made.
        """
        clauses = ctx.world.scan(branch_id=ctx.branch_id, collection=POLICIES)
        if not clauses:
            return {"status": "ok", "clauses": []}
        query_vector = _embed(query)
        scored = []
        for clause in clauses.values():
            text = f"{clause['title']}. {clause['text']}"
            scored.append((_cosine(query_vector, _embed(text)), clause))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return {
            "status": "ok",
            "clauses": [
                {"id": c["id"], "title": c["title"], "text": c["text"],
                 "relevance": round(score, 4)}
                for score, c in scored[:3]
            ],
        }

    # -- world mutations -------------------------------------------------------

    def set_dispute_status(dispute_id: str, status: str, resolution: str) -> dict:
        """Update a dispute's status and record how it was resolved.

        Args:
            dispute_id: The dispute identifier.
            status: One of open, resolved, escalated, rejected.
            resolution: One sentence explaining the outcome.
        """
        dispute = _read(DISPUTES, dispute_id)
        if not dispute:
            return {"status": "not_found", "dispute_id": dispute_id}
        previous = dispute.get("status")
        updated = {**dispute, "status": status, "resolution": resolution}
        _write(DISPUTES, dispute_id, updated)
        # The prior value travels in the result so the compensator can restore it.
        return {"status": "ok", "dispute_id": dispute_id,
                "new_status": status, "previous_status": previous}

    def record_ledger_entry(dispute_id: str, entry_type: str, amount_usd: float) -> dict:
        """Write a financial entry to the ledger.

        Args:
            dispute_id: The dispute this entry relates to.
            entry_type: One of refund, reversal, fee, adjustment.
            amount_usd: The signed amount in US dollars.
        """
        entry_id = f"LED-{dispute_id}-{ctx.seq()}"
        entry = {
            "id": entry_id, "dispute_id": dispute_id, "type": entry_type,
            "amount_usd": round(amount_usd, 2),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write(LEDGER, entry_id, entry)
        return {"status": "ok", "entry_id": entry_id, "entry": entry}

    # -- irreversible ----------------------------------------------------------

    def issue_refund(dispute_id: str, amount_usd: float) -> dict:
        """Send money back to the customer. This moves real funds.

        Args:
            dispute_id: The dispute being refunded.
            amount_usd: The amount to refund in US dollars.
        """
        dispute = _read(DISPUTES, dispute_id)
        if not dispute:
            return {"status": "not_found", "dispute_id": dispute_id}
        payout_id = f"PAY-{dispute_id}-{ctx.seq()}"
        _write(LEDGER, payout_id, {
            "id": payout_id, "dispute_id": dispute_id, "type": "refund",
            "amount_usd": round(amount_usd, 2),
            "customer_id": dispute.get("customer_id"),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return {"status": "refunded", "payout_id": payout_id,
                "dispute_id": dispute_id, "amount_usd": round(amount_usd, 2)}

    def send_customer_email(customer_id: str, subject: str, body: str) -> dict:
        """Send an email to a customer. This cannot be unsent.

        Args:
            customer_id: The recipient's customer id.
            subject: The email subject line.
            body: The email body.
        """
        customer = _read(CUSTOMERS, customer_id)
        if not customer:
            return {"status": "not_found", "customer_id": customer_id}
        message_id = f"MSG-{customer_id}-{ctx.seq()}"
        _write(COMMS, message_id, {
            "id": message_id, "customer_id": customer_id,
            "to": customer.get("email"), "subject": subject, "body": body,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return {"status": "sent", "message_id": message_id, "to": customer.get("email")}

    def escalate_to_human(dispute_id: str, reason: str) -> dict:
        """Raise a dispute to a human reviewer, creating a ticket in their queue.

        Args:
            dispute_id: The dispute to escalate.
            reason: Why this needs human judgement.
        """
        ticket_id = f"TKT-{dispute_id}-{ctx.seq()}"
        _write(TICKETS, ticket_id, {
            "id": ticket_id, "dispute_id": dispute_id, "reason": reason,
            "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": "queued",
        })
        return {"status": "escalated", "ticket_id": ticket_id, "dispute_id": dispute_id}

    # -- registry --------------------------------------------------------------

    registry = ReversibilityRegistry()

    # ADK's built-in handoff. It is control flow, not a world effect, so it must be
    # declared — the registry's fail-safe default would otherwise quarantine it off
    # primary, severing delegation on every branch and silently truncating the
    # counterfactual at the point the fleet hands off. Worth noting that the default
    # caught it rather than letting it through: an unclassified tool fails visible.
    registry.register("transfer_to_agent", Determinism.PURE)

    # Read sets are what make a counterfactual propagate. `search_policy` consults the
    # policy corpus, so editing a clause must invalidate it; `get_dispute` does not, so a
    # policy edit must leave it cached.
    registry.register("get_dispute", Determinism.RECORDED, reads=(DISPUTES,))
    registry.register("get_customer", Determinism.RECORDED, reads=(CUSTOMERS,))
    registry.register("search_policy", Determinism.RECORDED, reads=(POLICIES,))

    registry.register(
        "set_dispute_status",
        Determinism.EXTERNAL_REVERSIBLE,
        compensator=lambda args, result: (
            {"tool": "set_dispute_status",
             "args": {"dispute_id": args["dispute_id"],
                      "status": result.get("previous_status") or "open",
                      "resolution": "reverted by compensation"}}
            if result.get("status") == "ok" else None
        ),
    )
    registry.register(
        "record_ledger_entry",
        Determinism.EXTERNAL_REVERSIBLE,
        compensator=lambda args, result: (
            {"tool": "record_ledger_entry",
             "args": {"dispute_id": args["dispute_id"], "entry_type": "reversal",
                      "amount_usd": -float(args.get("amount_usd", 0))}}
            if result.get("status") == "ok" else None
        ),
    )

    # No compensator exists for any of these. Money that has left, a mail that has been
    # delivered and a ticket a person has already seen are not undone by writing another
    # row, so they are quarantined off-primary rather than pretended away.
    registry.register(
        "issue_refund", Determinism.EXTERNAL_IRREVERSIBLE,
        describe=lambda a: f"refund ${float(a.get('amount_usd', 0)):,.2f} on {a.get('dispute_id')}",
    )
    registry.register(
        "send_customer_email", Determinism.EXTERNAL_IRREVERSIBLE,
        describe=lambda a: f"email {a.get('customer_id')}: {str(a.get('subject'))[:60]}",
    )
    registry.register(
        "escalate_to_human", Determinism.EXTERNAL_IRREVERSIBLE,
        describe=lambda a: f"escalate {a.get('dispute_id')}: {str(a.get('reason'))[:60]}",
    )

    tools = [get_dispute, get_customer, search_policy, set_dispute_status,
             record_ledger_entry, issue_refund, send_customer_email, escalate_to_human]
    return tools, registry
