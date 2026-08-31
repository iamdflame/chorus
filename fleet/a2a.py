"""An A2A agent card, mapped from the registry this project already keeps.

The Agent2Agent specification asks a service to publish, at a well-known path, what its
agents are and what they can do, so another system can discover and call them without a
private integration. Almost none of that is new work here: `fleet/registry.py` already
emits a card per agent with a content-derived version, the model behind it, its tools and
its data policy. This is a field mapping over data we hold, not a second source of truth.

Two things this card carries that most do not, both because the kernel needed them first:

    reversibility   every skill declares whether it can be undone, and whether it has a
                    compensator. A caller can therefore tell, before invoking anything,
                    which operations are safe to retry and which are one-way. Most agent
                    cards describe capability without describing consequence.
    version         derived from the agent's own definition — instruction, model,
                    generation config, tool allowlist — so editing a prompt moves the
                    version without anyone remembering to bump it. A pinned version is a
                    real guarantee rather than a promise to be careful.

The coverage gaps are published too. A capability with no agent behind it escalates to a
human instead of being routed to whichever agent looked closest, and saying so in the card
is more useful to a caller than a silent absence.
"""

from __future__ import annotations

from typing import Any

from fleet.registry import build_registry

# Skills are named per (agent, tool). An A2A caller addresses a skill, not an internal
# function, so the id is the pair rather than the bare tool name — two agents may hold the
# same tool under different policies.
def _skill(agent: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    reversibility = tool.get("reversibility", "unknown")
    return {
        "id": f"{agent['id']}.{tool['name']}",
        "name": tool["name"].replace("_", " "),
        "description": (
            f"{tool['name']} — {reversibility.replace('_', ' ')}"
            + (", compensator available" if tool.get("has_compensator") else "")
        ),
        "tags": sorted({agent["role"], reversibility, *tool.get("reads", [])}),
        "inputModes": ["text/plain", "application/json"],
        "outputModes": ["application/json"],
        # Beyond the A2A core, and deliberately: a caller should know whether an operation
        # can be undone before it invokes it, not after.
        "x-chorus": {
            "reversibility": reversibility,
            "reversible": reversibility in ("pure", "recorded", "external_reversible"),
            "hasCompensator": bool(tool.get("has_compensator")),
            "reads": tool.get("reads", []),
        },
    }


def agent_card(base_url: str) -> dict[str, Any]:
    """The card served at /.well-known/agent-card.json."""
    registry = build_registry()
    agents = registry.get("agents", [])

    skills: list[dict[str, Any]] = []
    for agent in agents:
        for tool in agent.get("tools", []):
            skills.append(_skill(agent, tool))
        if not agent.get("tools"):
            # An agent whose whole job is reasoning still has a skill: its role. Omitting
            # it would make the passenger and crew agents invisible to discovery, which is
            # exactly backwards — they are the ones that carry the product.
            skills.append({
                "id": f"{agent['id']}.reason",
                "name": f"{agent['role']} reasoning",
                "description": agent.get("summary", ""),
                "tags": [agent["role"], "reasoning", "collapsible"],
                "inputModes": ["text/plain"],
                "outputModes": ["application/json"],
                "x-chorus": {
                    "reversibility": "recorded",
                    "reversible": True,
                    "hasCompensator": False,
                    "collapses": True,
                },
            })

    return {
        "protocolVersion": "0.3.0",
        "name": "Chorus",
        "description": (
            "One agent per entity, priced by the diversity of their situations rather "
            "than their population. Identical reasoning is computed once and shared, and "
            "how much of it was needed at all is measured continuously."
        ),
        "url": f"{base_url.rstrip('/')}/api",
        "preferredTransport": "JSONRPC",
        "version": registry.get("version", "0.1.0"),
        "provider": {
            "organization": "Chorus",
            "url": base_url.rstrip("/"),
        },
        "documentationUrl": f"{base_url.rstrip('/')}/architecture",
        "capabilities": {
            "streaming": True,          # /api/swarm streams over SSE
            "pushNotifications": False,
            "stateTransitionHistory": True,  # every effect is content-addressed and kept
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": skills,
        # Beyond the spec, and the part a caller actually needs to trust the rest.
        "x-chorus": {
            "agents": [
                {
                    "id": a["id"],
                    "role": a["role"],
                    "version": a["version"],
                    "model": a.get("model"),
                    "status": a.get("status"),
                    # An agent with an empty policy is not an agent with nothing to
                    # hide — it is one that has declared nothing, and emitting empty
                    # arrays would let a caller read the second as the first. The
                    # projection agents carry a structural guarantee; the fleet agents
                    # operate on real customer records under IAM and say so.
                    **(
                        {
                            "sees": a["data_policy"]["sees"],
                            "neverSees": a["data_policy"]["never_sees"],
                            "dataPolicy": "structural",
                        }
                        if a.get("data_policy", {}).get("sees")
                        else {
                            "dataPolicy": "undeclared",
                            "dataPolicyNote": (
                                "Operates on customer records through tools, under IAM "
                                "rather than under a projection. No field-level guarantee "
                                "is claimed for this agent."
                            ),
                        }
                    ),
                }
                for a in agents
            ],
            "versioning": (
                "Agent versions are derived from the agent's own definition, so editing "
                "an instruction moves the version without anyone bumping it by hand."
            ),
            "coverageGaps": (
                "A declared capability with no published agent escalates to a human "
                "rather than being routed to whichever agent looked closest."
            ),
            "reversibilityClasses": registry.get("reversibility_classes", {}),
        },
    }
