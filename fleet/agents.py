"""The fleet — six agents that resolve customer disputes.

Structure is a deliberate mix, not an accident of convenience:

    triage -> policy -> resolver -> comms          fixed pipeline, sequential in data
                          |
                          +-> refund_specialist    real delegation, chosen at runtime
                          +-> escalation_specialist

The pipeline stages are sequential because each genuinely reads the previous one's
output, and encoding that as structure makes the causal graph honest. The resolver is a
delegating agent because the choice between paying a customer and escalating to a human
is exactly the judgement that should be made by a model at runtime — and because it puts
a real `transfer_to_agent` edge in the DAG, which is what a fleet-level lightcone is for.

`thinking_level` is set per agent rather than left at the default. Gemini 3.5 Flash
defaults to `medium`, and spending the same reasoning budget on "read this record" as on
"decide whether to move money" is the kind of undifferentiated cost that makes agent
fleets expensive for no benefit.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types

from fleet.tools import FleetContext, build_tools
from kernel.quarantine import ReversibilityRegistry

MODEL = "gemini-3.5-flash"


def _config(level: str) -> types.GenerateContentConfig:
    """Generation settings for one agent.

    Temperature is pinned low across the fleet. Financial decisions should not vary run
    to run for reasons unrelated to the facts, and lower variance also means a replayed
    timeline stays comparable to the one recorded beside it.
    """
    return types.GenerateContentConfig(
        temperature=0.1,
        thinking_config=types.ThinkingConfig(thinking_level=level),
    )


def build_fleet(ctx: FleetContext) -> tuple[SequentialAgent, ReversibilityRegistry]:
    """Construct the fleet bound to one branch of the world."""
    tools, registry = build_tools(ctx)
    by_name = {t.__name__: t for t in tools}

    triage = LlmAgent(
        name="triage",
        model=MODEL,
        generate_content_config=_config("low"),
        tools=[by_name["get_dispute"], by_name["get_customer"]],
        instruction=(
            "You are the intake stage of a disputes team. You will be given a dispute id.\n"
            "1. Call get_dispute to load it.\n"
            "2. Call get_customer for the customer on that dispute.\n"
            "Then output exactly these five lines and nothing else:\n"
            "DISPUTE: <id>\nAMOUNT: <amount in USD>\nREASON: <reason>\n"
            "CUSTOMER: <customer id> tier=<tier> country=<country> prior_disputes=<n>\n"
            "FACTS: <one sentence of anything unusual, or 'none'>"
        ),
    )

    policy = LlmAgent(
        name="policy",
        model=MODEL,
        # The one decision in the fleet that moves money gets the largest budget.
        generate_content_config=_config("high"),
        tools=[by_name["search_policy"]],
        instruction=(
            "You are the policy stage. Above you is a triage summary of a dispute.\n"
            "1. Call search_policy with a query describing the decision, including the "
            "amount, the reason, the customer tier and the prior dispute count.\n"
            "2. Apply the retrieved clauses literally. Quote the clause ids you relied on. "
            "Where two clauses conflict, the more restrictive one wins.\n"
            "Then output exactly these four lines and nothing else:\n"
            "DECISION: APPROVE_REFUND or ESCALATE\nAMOUNT: <amount in USD to refund, or 0>\n"
            "CLAUSES: <comma separated clause ids you relied on>\n"
            "REASON: <one sentence citing the controlling clause>"
        ),
    )

    refund_specialist = LlmAgent(
        name="refund_specialist",
        model=MODEL,
        generate_content_config=_config("low"),
        tools=[by_name["issue_refund"], by_name["record_ledger_entry"],
               by_name["set_dispute_status"]],
        # Terminal stage: without this it can hand control back and loop.
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        instruction=(
            "You execute approved refunds. Using the decision above:\n"
            "1. Call issue_refund with the dispute id and the approved amount.\n"
            "2. Call record_ledger_entry with entry_type 'refund' and the same amount.\n"
            "3. Call set_dispute_status with status 'resolved' and a one sentence resolution.\n"
            "Then output one line: REFUNDED <dispute id> <amount>."
        ),
    )

    escalation_specialist = LlmAgent(
        name="escalation_specialist",
        model=MODEL,
        generate_content_config=_config("low"),
        tools=[by_name["escalate_to_human"], by_name["set_dispute_status"]],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        instruction=(
            "You route disputes that need human judgement. Using the decision above:\n"
            "1. Call escalate_to_human with the dispute id and the controlling reason.\n"
            "2. Call set_dispute_status with status 'escalated' and a one sentence resolution.\n"
            "Then output one line: ESCALATED <dispute id>."
        ),
    )

    resolver = LlmAgent(
        name="resolver",
        model=MODEL,
        generate_content_config=_config("low"),
        sub_agents=[refund_specialist, escalation_specialist],
        instruction=(
            "You route a decided dispute to the right specialist. Read the DECISION line "
            "above.\n"
            "If it is APPROVE_REFUND, transfer to refund_specialist.\n"
            "If it is ESCALATE, transfer to escalation_specialist.\n"
            "Transfer immediately. Do not restate the decision and do not act yourself."
        ),
    )

    comms = LlmAgent(
        name="comms",
        model=MODEL,
        generate_content_config=_config("low"),
        tools=[by_name["send_customer_email"]],
        instruction=(
            "You notify the customer of the outcome, exactly once.\n"
            "Call send_customer_email with the customer id from the triage summary, a "
            "subject naming the dispute, and a short body stating the outcome and, if a "
            "refund was issued, the amount.\n"
            "If the customer's country is in the EU, do not include their name, email "
            "address or order id in the body -- refer only to the dispute id.\n"
            "Then output one line: NOTIFIED <customer id>."
        ),
    )

    fleet = SequentialAgent(
        name="revops_fleet",
        sub_agents=[triage, policy, resolver, comms],
    )
    return fleet, registry
