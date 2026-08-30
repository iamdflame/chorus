"""HTTP surface for the Lightcone console.

Thin by design: every route is a translation of a request into one Engine call. The
interesting logic lives in the kernel, where it can be tested without a server.

Replay streams over Server-Sent Events rather than returning a result, because the whole
point is watching an unchanged prefix snap back for free while the diverged remainder
genuinely re-executes. A spinner would hide the only thing worth seeing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.engine import Engine
from fleet.domain import COMMS, DISPUTES, LEDGER, POLICIES, TICKETS
from kernel.branch import PRIMARY
from kernel.interposer import Mode

SNAPSHOT = os.environ.get("LIGHTCONE_SNAPSHOT", "data/history.json")
CONSOLE_DIR = Path(__file__).parent.parent / "console" / "dist"

app = FastAPI(
    title="Lightcone",
    description="Version control for agent reality.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = Engine(SNAPSHOT)


# -- request models -----------------------------------------------------------

class ForkRequest(BaseModel):
    name: str = Field(..., description="Human name for the new timeline")
    at_seq: int = Field(..., description="Sequence position to fork from")
    perturbation: dict[str, Any] | None = None


class PolicyEdit(BaseModel):
    text: str


class ReplayRequest(BaseModel):
    dispute_ids: list[str] | None = None
    limit: int = 10


class MergeRequest(BaseModel):
    into: str = PRIMARY
    force: bool = False


class SearchRequest(BaseModel):
    dispute_ids: list[str] = Field(default_factory=list)
    clause_id: str = "POL-REFUND-CEILING"
    generations: int = 2
    population: int = 3
    concurrency: int = 3


class SwarmRequest(BaseModel):
    agents: int = 2000
    concurrency: int = 6


class AdoptRequest(BaseModel):
    clause_id: str
    text: str


# -- meta ---------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus enough state to prove the process really loaded a timeline."""
    return {
        "status": "ok",
        "branches": len(engine.branches()),
        "primary_effects": len(engine.store.timeline(PRIMARY)),
        "snapshot": SNAPSHOT,
        "deployment": os.environ.get("K_SERVICE", "local"),
        "region": os.environ.get("LIGHTCONE_REGION", "local"),
    }


# -- timelines ----------------------------------------------------------------

@app.get("/api/branches")
def list_branches() -> list[dict[str, Any]]:
    return engine.branches()


@app.post("/api/branches/{branch_id}/fork")
def fork(branch_id: str, request: ForkRequest) -> dict[str, Any]:
    try:
        return engine.fork(
            parent_id=branch_id, name=request.name,
            at_seq=request.at_seq, perturbation=request.perturbation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/branches/{branch_id}/graph")
def graph(branch_id: str, limit: int | None = Query(default=None)) -> dict[str, Any]:
    if engine.store.get_branch(branch_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown branch {branch_id}")
    return engine.graph(branch_id, limit=limit)


@app.get("/api/branches/{branch_id}/effects/{effect_id}")
def effect(branch_id: str, effect_id: str) -> dict[str, Any]:
    found = engine.effect(branch_id, effect_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such effect on this branch")
    return found


@app.get("/api/branches/{branch_id}/effects/{effect_id}/lightcone")
def lightcone(branch_id: str, effect_id: str) -> dict[str, Any]:
    """Blast radius and provenance for one decision."""
    if engine.store.lookup(branch_id, effect_id) is None:
        raise HTTPException(status_code=404, detail="no such effect on this branch")
    return engine.lightcone(branch_id, effect_id)


@app.get("/api/branches/{left}/diff/{right}")
def diff(left: str, right: str) -> dict[str, Any]:
    for branch in (left, right):
        if engine.store.get_branch(branch) is None:
            raise HTTPException(status_code=404, detail=f"unknown branch {branch}")
    return engine.diff(left, right)


# -- world --------------------------------------------------------------------

@app.get("/api/branches/{branch_id}/world/{collection}")
def world(branch_id: str, collection: str, at_seq: int | None = None) -> dict[str, Any]:
    if collection not in (DISPUTES, LEDGER, COMMS, TICKETS, POLICIES, "customers"):
        raise HTTPException(status_code=400, detail=f"unknown collection {collection}")
    return engine.world_view(branch_id, collection, at_seq)


@app.patch("/api/branches/{branch_id}/policies/{clause_id}")
def edit_policy(branch_id: str, clause_id: str, edit: PolicyEdit) -> dict[str, Any]:
    """Rewrite one policy clause on a branch — the perturbation the demo turns on."""
    if engine.store.get_branch(branch_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown branch {branch_id}")
    if branch_id == PRIMARY:
        raise HTTPException(
            status_code=409,
            detail="refusing to edit policy on production; fork a timeline first",
        )
    try:
        return engine.edit_policy(branch_id=branch_id, clause_id=clause_id, text=edit.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/branches/{branch_id}/merge")
def merge(branch_id: str, request: MergeRequest) -> dict[str, Any]:
    if engine.store.get_branch(branch_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown branch {branch_id}")
    result = engine.merge(branch_id=branch_id, into=request.into, force=request.force)
    if not result["merged"]:
        # 409 rather than 200-with-a-flag: a refused merge is a failed request, and the
        # client should not have to read the body to discover production is unchanged.
        raise HTTPException(status_code=409, detail=result)
    return result


# -- replay -------------------------------------------------------------------

@app.post("/api/branches/{branch_id}/replay")
async def replay(branch_id: str, request: ReplayRequest) -> StreamingResponse:
    if engine.store.get_branch(branch_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown branch {branch_id}")

    dispute_ids = request.dispute_ids
    if not dispute_ids:
        resolved = [
            d["id"]
            for d in engine.world_view(branch_id, DISPUTES).values()
            if d.get("status") != "open"
        ]
        dispute_ids = resolved[: request.limit]

    async def stream():
        async for event in engine.replay(
            branch_id=branch_id, dispute_ids=dispute_ids, mode=Mode.REPLAY
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- policy search ------------------------------------------------------------

@app.post("/api/search")
async def search(request: SearchRequest) -> StreamingResponse:
    """Search policy space against recorded history.

    Streams because the search is the demo: candidates fork, replay, and settle onto a
    cost frontier one at a time, and a final JSON blob would throw away the only part
    worth watching.
    """
    dispute_ids = request.dispute_ids or [
        d["id"]
        for d in engine.world_view(PRIMARY, DISPUTES).values()
        if d.get("status") != "open"
    ][:6]
    if not dispute_ids:
        raise HTTPException(
            status_code=409,
            detail="no recorded disputes to search against; record a history first",
        )

    async def stream():
        async for event in engine.search_policy(
            dispute_ids=dispute_ids,
            clause_id=request.clause_id,
            generations=request.generations,
            population=request.population,
            concurrency=request.concurrency,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/policies/adopt")
def adopt(request: AdoptRequest) -> dict[str, Any]:
    """Install a policy the search proved better into production."""
    try:
        return engine.adopt(clause_id=request.clause_id, text=request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# -- swarm --------------------------------------------------------------------

@app.get("/api/swarm/cohorts")
def swarm_cohorts(agents: int = 20000) -> dict[str, Any]:
    """The cohort layout for a population, without running anything.

    Pure bucketing, no model calls, no cost — so the console can render the field at rest
    before a single agent has been woken.
    """
    from dataclasses import asdict

    from swarm.canonical import collapse, project_passenger
    from swarm.scenario import build_scenario

    scenario = build_scenario(passengers=agents)
    passengers = [asdict(p) for p in scenario.passengers]
    grouped = collapse(passengers, project_passenger)
    return {
        "agents": len(passengers),
        "scenario": scenario.summary(),
        "cohorts": [
            {"key": key, "size": len(members),
             "label": key.split("|", 1)[1] if "|" in key else key}
            for key, members in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)
        ],
    }


@app.post("/api/swarm")
async def swarm(request: SwarmRequest) -> StreamingResponse:
    """Run the swarm, streaming progress.

    A recorded swarm replays from the store with no model calls at all, so re-running
    one is instant and free — which is what makes twenty thousand agents watchable in a
    demo rather than a twenty-minute wait.
    """
    async def stream():
        async for event in engine.run_swarm(
            agents=request.agents, concurrency=request.concurrency
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- console ------------------------------------------------------------------

if CONSOLE_DIR.exists():
    # Hashed asset files are served directly and cached hard; they are immutable by
    # construction, so a year is safe and a rebuild busts it via the filename.
    app.mount(
        "/assets",
        StaticFiles(directory=str(CONSOLE_DIR / "assets")),
        name="assets",
    )

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Serve the console shell for any non-API path.

        The front end routes on the client, so /mechanism and /evidence have no file
        behind them. A plain StaticFiles mount 404s on those, which breaks every deep
        link, every refresh and every link anyone shares — the routes work only if you
        arrive at / first and click. Real files are still served when they exist.
        """
        candidate = (CONSOLE_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(CONSOLE_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(CONSOLE_DIR / "index.html")
