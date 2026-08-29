"""Firestore-backed effect storage — the production timeline.

Satisfies the same `EffectStore` protocol as `InMemoryEffectStore`, which is the point:
the kernel never learns that Google Cloud exists, the determinism proof runs offline in
CI against the reference implementation, and this backend is validated by behaving
identically to it.

Layout mirrors the access pattern rather than the data model:

    branches/{branch}                     branch record and sequence counter
    branches/{branch}/effects/{address}   one document per effect, keyed by address
    branches/{branch}/manifest/{chunk}    ordered visit manifest, chunked

Keying effects by their content address means `lookup` — the hottest operation, called
before every model and tool call — is a direct document get rather than a query. Chain
resolution costs one get per ancestor, and a process-local cache makes a repeated replay
free after the first pass, which matters because an address is immutable: once read, it
can never be stale.

`request`, `response` and `meta` are stored as JSON strings rather than maps. Firestore
cannot represent nested arrays, and an LLM response is full of them; serialising avoids a
whole class of silent shape corruption at the cost of not querying inside payloads, which
nothing does.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from google.cloud import firestore

from kernel.branch import PRIMARY, Branch
from kernel.dag import CausalDAG
from kernel.effect import Effect

# Firestore caps a document at 1 MiB. Addresses are 32 characters, so 5,000 per chunk
# leaves a wide margin while keeping the number of manifest reads small.
MANIFEST_CHUNK = 5000
_JSON_FIELDS = ("request", "response", "meta")


def _to_document(effect: Effect) -> dict[str, Any]:
    raw = effect.to_dict()
    for field in _JSON_FIELDS:
        raw[field] = json.dumps(raw[field], separators=(",", ":"), default=repr)
    return raw


def _from_document(raw: dict[str, Any]) -> Effect:
    decoded = dict(raw)
    for field in _JSON_FIELDS:
        value = decoded.get(field)
        decoded[field] = json.loads(value) if isinstance(value, str) else value
    return Effect.from_dict(decoded)


class FirestoreEffectStore:
    """Durable, branch-aware effect storage."""

    def __init__(
        self,
        *,
        client: firestore.Client | None = None,
        project: str | None = None,
        root: str = "lightcone",
    ) -> None:
        self._db = client or firestore.Client(project=project)
        self._root = root
        # Addresses are immutable, so a hit can never go stale and needs no invalidation.
        self._cache: dict[str, Effect] = {}
        self._branch_cache: dict[str, Branch] = {}
        self._ensure_primary()

    # -- paths -----------------------------------------------------------------

    def _branch_ref(self, branch_id: str):
        return self._db.collection(self._root).document(branch_id)

    def _effects_ref(self, branch_id: str):
        return self._branch_ref(branch_id).collection("effects")

    def _manifest_ref(self, branch_id: str):
        return self._branch_ref(branch_id).collection("manifest")

    # -- branches --------------------------------------------------------------

    def _ensure_primary(self) -> None:
        ref = self._branch_ref(PRIMARY)
        if not ref.get().exists:
            ref.set({**Branch.primary().to_dict(), "seq": 0})

    def create_branch(self, branch: Branch) -> Branch:
        ref = self._branch_ref(branch.id)
        if ref.get().exists:
            raise ValueError(f"branch already exists: {branch.id}")
        if branch.parent_id and not self._branch_ref(branch.parent_id).get().exists:
            raise ValueError(f"unknown parent branch: {branch.parent_id}")
        ref.set({**branch.to_dict(), "seq": branch.fork_at_seq or 0})
        self._branch_cache[branch.id] = branch
        return branch

    def get_branch(self, branch_id: str) -> Branch | None:
        cached = self._branch_cache.get(branch_id)
        if cached is not None:
            return cached
        snapshot = self._branch_ref(branch_id).get()
        if not snapshot.exists:
            return None
        branch = Branch.from_dict(snapshot.to_dict())
        self._branch_cache[branch_id] = branch
        return branch

    def list_branches(self) -> list[Branch]:
        found = [
            Branch.from_dict(doc.to_dict())
            for doc in self._db.collection(self._root).stream()
        ]
        for branch in found:
            self._branch_cache[branch.id] = branch
        return sorted(found, key=lambda b: b.created_at)

    def _chain(self, branch_id: str) -> list[Branch]:
        chain: list[Branch] = []
        seen: set[str] = set()
        current = self.get_branch(branch_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = self.get_branch(current.parent_id) if current.parent_id else None
        return chain

    # -- writes ----------------------------------------------------------------

    def put(self, effect: Effect) -> None:
        self._effects_ref(effect.branch_id).document(effect.id).set(_to_document(effect))
        self._cache[f"{effect.branch_id}:{effect.id}"] = effect

    def put_many(self, effects: Iterable[Effect]) -> None:
        """Batch writes — a recorded dispute is dozens of effects and one round trip
        each would dominate the wall time of every run."""
        batch = self._db.batch()
        pending = 0
        for effect in effects:
            batch.set(self._effects_ref(effect.branch_id).document(effect.id),
                      _to_document(effect))
            self._cache[f"{effect.branch_id}:{effect.id}"] = effect
            pending += 1
            if pending == 450:  # Firestore caps a batch at 500 operations.
                batch.commit()
                batch = self._db.batch()
                pending = 0
        if pending:
            batch.commit()

    def next_seq(self, branch_id: str) -> int:
        ref = self._branch_ref(branch_id)

        @firestore.transactional
        def bump(transaction: firestore.Transaction) -> int:
            snapshot = ref.get(transaction=transaction)
            current = (snapshot.to_dict() or {}).get("seq", 0)
            transaction.update(ref, {"seq": current + 1})
            return current + 1

        return bump(self._db.transaction())

    def append_manifest(self, branch_id: str, addresses: list[str]) -> None:
        if not addresses:
            return
        existing = self._manifest_ref(branch_id).stream()
        chunks = sorted(
            ((int(d.id), d.to_dict().get("addresses", [])) for d in existing),
            key=lambda pair: pair[0],
        )
        index = chunks[-1][0] if chunks else 0
        tail = list(chunks[-1][1]) if chunks else []
        for address in addresses:
            if len(tail) >= MANIFEST_CHUNK:
                self._manifest_ref(branch_id).document(str(index)).set({"addresses": tail})
                index += 1
                tail = []
            tail.append(address)
        self._manifest_ref(branch_id).document(str(index)).set({"addresses": tail})

    def manifest(self, branch_id: str) -> list[str]:
        chunks = sorted(
            ((int(d.id), d.to_dict().get("addresses", []))
             for d in self._manifest_ref(branch_id).stream()),
            key=lambda pair: pair[0],
        )
        return [address for _, addresses in chunks for address in addresses]

    # -- reads -----------------------------------------------------------------

    def lookup(self, branch_id: str, address: str) -> Effect | None:
        for branch in self._chain(branch_id):
            key = f"{branch.id}:{address}"
            if key in self._cache:
                return self._cache[key]
            snapshot = self._effects_ref(branch.id).document(address).get()
            if snapshot.exists:
                effect = _from_document(snapshot.to_dict())
                self._cache[key] = effect
                return effect
        return None

    def own_effects(self, branch_id: str) -> list[Effect]:
        found = [_from_document(d.to_dict()) for d in self._effects_ref(branch_id).stream()]
        return sorted(found, key=lambda e: (e.seq, e.id))

    def timeline(self, branch_id: str) -> list[Effect]:
        branch = self.get_branch(branch_id)
        if branch is None:
            return []
        out: list[Effect] = []
        seen: set[str] = set()

        if branch.parent_id and branch.fork_at_seq is not None:
            for effect in self.timeline(branch.parent_id):
                if effect.seq <= branch.fork_at_seq and effect.id not in seen:
                    seen.add(effect.id)
                    out.append(effect)

        visited = self.manifest(branch_id)
        if visited:
            for address in visited:
                if address in seen:
                    continue
                resolved = self.lookup(branch_id, address)
                if resolved is not None:
                    seen.add(address)
                    out.append(resolved)
        else:
            for effect in self.own_effects(branch_id):
                if effect.id not in seen:
                    seen.add(effect.id)
                    out.append(effect)
        return out

    def dag(self, branch_id: str) -> CausalDAG:
        return CausalDAG(self.timeline(branch_id))

    # -- maintenance -----------------------------------------------------------

    def purge(self) -> int:
        """Delete everything under the root. Used by tests against a scratch root."""
        removed = 0
        for branch_doc in self._db.collection(self._root).stream():
            for sub in ("effects", "manifest"):
                for doc in branch_doc.reference.collection(sub).stream():
                    doc.reference.delete()
                    removed += 1
            branch_doc.reference.delete()
            removed += 1
        self._cache.clear()
        self._branch_cache.clear()
        return removed
