"""Snapshotting a timeline to disk.

A recorded history is expensive to produce — it is real model calls against real data —
so it must outlive the process that made it. This serialises the effect store, the branch
registry and the Shadow World into one JSON document that can be reloaded instantly.

Firestore is the production backend (see `kernel/firestore_store.py`); this exists so the
API can boot with three weeks of history already loaded, and so a recorded run can be
committed to the repository as reproducible evidence rather than a claim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kernel.branch import Branch
from kernel.effect import Effect
from kernel.store import InMemoryEffectStore
from world.shadow import TOMBSTONE, ShadowWorld, Version

SCHEMA_VERSION = 1
_TOMBSTONE_MARKER = {"__lightcone_tombstone__": True}


def _encode(value: Any) -> Any:
    return _TOMBSTONE_MARKER if value is TOMBSTONE else value


def _decode(value: Any) -> Any:
    return TOMBSTONE if value == _TOMBSTONE_MARKER else value


def save(path: str | Path, *, store: InMemoryEffectStore, world: ShadowWorld) -> Path:
    """Write store and world to a single JSON document."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    branches = [b.to_dict() for b in store.list_branches()]
    document = {
        "schema": SCHEMA_VERSION,
        "branches": branches,
        "effects": {
            b["id"]: [e.to_dict() for e in store.own_effects(b["id"])] for b in branches
        },
        "manifests": {b["id"]: store.manifest(b["id"]) for b in branches},
        "world": [
            {
                "collection": v.collection,
                "key": v.key,
                "value": _encode(v.value),
                "seq": v.seq,
                "branch_id": v.branch_id,
                "effect_id": v.effect_id,
                "wall_ts": v.wall_ts,
            }
            for history in world._versions.values()
            for v in history
        ],
    }
    target.write_text(json.dumps(document, separators=(",", ":")))
    return target


def load(path: str | Path) -> tuple[InMemoryEffectStore, ShadowWorld]:
    """Reconstruct store and world from a snapshot."""
    document = json.loads(Path(path).read_text())
    if document.get("schema") != SCHEMA_VERSION:
        raise ValueError(
            f"snapshot schema {document.get('schema')} != expected {SCHEMA_VERSION}"
        )

    store = InMemoryEffectStore()
    for raw in document["branches"]:
        branch = Branch.from_dict(raw)
        if store.get_branch(branch.id) is None:
            store.create_branch(branch)

    for branch_id, effects in document["effects"].items():
        store.put_many(Effect.from_dict(e) for e in effects)
    for branch_id, addresses in document["manifests"].items():
        store.append_manifest(branch_id, addresses)

    world = ShadowWorld(branches={b.id: b for b in store.list_branches()})
    for raw in document["world"]:
        world._versions.setdefault((raw["collection"], raw["key"]), []).append(
            Version(
                collection=raw["collection"],
                key=raw["key"],
                value=_decode(raw["value"]),
                seq=raw["seq"],
                branch_id=raw["branch_id"],
                effect_id=raw.get("effect_id"),
                wall_ts=raw.get("wall_ts", 0.0),
            )
        )
    for history in world._versions.values():
        history.sort(key=lambda v: (v.seq, v.branch_id))
    return store, world


def describe(path: str | Path) -> dict[str, Any]:
    """Summarise a snapshot without fully materialising it."""
    document = json.loads(Path(path).read_text())
    return {
        "schema": document.get("schema"),
        "branches": len(document.get("branches", [])),
        "effects": sum(len(v) for v in document.get("effects", {}).values()),
        "world_versions": len(document.get("world", [])),
        "size_kb": round(Path(path).stat().st_size / 1024, 1),
    }
