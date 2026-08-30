"""Where profiles live, and how they survive weeks of asynchronous operation.

Three backends behind one contract, for the same reason the effect store has three: the
kernel must never import Google Cloud, or the proofs could not run offline in CI against
the same code path production uses.

    InMemoryProfileStore   tests and local development
    FirestoreProfileStore  durable, and what the deployment uses
    MemoryBankProfileStore Vertex AI Agent Engine Memory Bank

The Vertex backend is deliberately the thinnest of the three, and that is a design position
rather than laziness. Memory Bank stores conversational memories and retrieves them by
similarity, which is the right tool when the thing being remembered is unstructured. Here
the thing being remembered is four booleans that must be auditable, expire on a schedule,
and feed a bucketing function — so the typed profile is authoritative, and Memory Bank
holds the conversational record it was derived from. Storing the booleans as prose and
retrieving them by embedding would make a regulator-facing decision depend on a nearest
neighbour search, which is not a trade anyone should take.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from kernel.clock import Clock
from memory.profile import Profile


@runtime_checkable
class ProfileStore(Protocol):
    def get(self, passenger_id: str) -> Profile | None: ...
    def put(self, profile: Profile) -> None: ...
    def many(self, passenger_ids: list[str]) -> dict[str, Profile]: ...


class InMemoryProfileStore:
    """Reference implementation. The other backends are validated against its behaviour."""

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def get(self, passenger_id: str) -> Profile | None:
        return self._profiles.get(passenger_id)

    def put(self, profile: Profile) -> None:
        self._profiles[profile.passenger_id] = profile

    def many(self, passenger_ids: list[str]) -> dict[str, Profile]:
        return {
            pid: self._profiles[pid] for pid in passenger_ids if pid in self._profiles
        }

    def __len__(self) -> int:
        return len(self._profiles)


class FirestoreProfileStore:
    """Durable profiles, one document per traveller.

    Reads are batched because the alternative is one round trip per passenger, and a
    twenty-thousand-agent round would then spend more wall time fetching memory than
    reasoning — which would be a memory system that costs more than the thing it saves.
    """

    def __init__(self, client: Any, collection: str = "profiles") -> None:
        self._db = client
        self._collection = collection

    def get(self, passenger_id: str) -> Profile | None:
        doc = self._db.collection(self._collection).document(passenger_id).get()
        if not doc.exists:
            return None
        return Profile.from_dict(doc.to_dict())

    def put(self, profile: Profile) -> None:
        self._db.collection(self._collection).document(
            profile.passenger_id
        ).set(profile.to_dict())

    def many(self, passenger_ids: list[str]) -> dict[str, Profile]:
        out: dict[str, Profile] = {}
        collection = self._db.collection(self._collection)
        # Firestore caps a batched get at 300 references.
        for start in range(0, len(passenger_ids), 300):
            refs = [collection.document(p) for p in passenger_ids[start:start + 300]]
            for doc in self._db.get_all(refs):
                if doc.exists:
                    payload = doc.to_dict()
                    out[payload["passenger_id"]] = Profile.from_dict(payload)
        return out


class MemoryBankProfileStore:
    """Vertex AI Agent Engine Memory Bank, holding the record a profile was derived from.

    The typed profile remains authoritative for bucketing. What Memory Bank adds is the
    conversational history behind it: *why* this traveller is marked as needing assistance,
    in their own words, retrievable weeks later by an operator who has to justify a
    decision to the person it affected.

    Requires an Agent Engine instance. Absent one, this raises at construction rather than
    silently degrading to a no-op store — a memory service that forgets everything while
    reporting success is worse than no memory service.
    """

    def __init__(self, service: Any, fallback: ProfileStore, app_name: str = "chorus") -> None:
        if service is None:
            raise ValueError(
                "MemoryBankProfileStore needs a VertexAiMemoryBankService; refusing to "
                "construct a memory service that would silently forget everything"
            )
        self._service = service
        self._fallback = fallback
        self._app_name = app_name

    def get(self, passenger_id: str) -> Profile | None:
        return self._fallback.get(passenger_id)

    def put(self, profile: Profile) -> None:
        self._fallback.put(profile)

    def many(self, passenger_ids: list[str]) -> dict[str, Profile]:
        return self._fallback.many(passenger_ids)

    async def remember(self, passenger_id: str, said: str, *, clock: Clock) -> None:
        """File what a traveller actually said, alongside the typed fact derived from it."""
        await self._service.add_memory(
            app_name=self._app_name,
            user_id=passenger_id,
            content=said,
            custom_metadata={"observed_at": clock.now().isoformat()},
        )

    async def recall(self, passenger_id: str, query: str) -> list[str]:
        """The traveller's own words behind a remembered constraint."""
        found = await self._service.search_memory(
            app_name=self._app_name, user_id=passenger_id, query=query
        )
        return [m.content for m in getattr(found, "memories", [])]


def learn(profile: Profile, record: dict[str, Any], *, clock: Clock) -> Profile:
    """Update a profile from one disruption.

    Only records what the airline observed this time. It never clears a constraint on
    absence — see `memory.profile.apply` for why forgetting on silence is the dangerous
    direction.
    """
    profile.disruptions_seen += 1
    if record.get("needs_assistance"):
        profile.observe("needs_assistance", True, clock=clock, source="booking")
    if record.get("has_hotel_entitlement"):
        profile.observe("hotel_entitled", True, clock=clock, source="booking")
    return profile
