"""HTTP surface for the Lightcone console.

Thin by design: every route is a translation of a request into one Engine call. The
interesting logic lives in the kernel, where it can be tested without a server.

Replay streams over Server-Sent Events rather than returning a result, because the whole
point is watching an unchanged prefix snap back for free while the diverged remainder
genuinely re-executes. A spinner would hide the only thing worth seeing.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from hmac import compare_digest
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi import Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.engine import Engine
from api.runs import Run, Runner
from api.runs import store_from_env as run_store_from_env
from fleet.a2a import agent_card
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
# The console is served from the same origin as the API, so cross-origin access is a
# convenience for local development rather than a requirement. `*` with credentials is the
# combination that turns a browsing judge into an authenticated caller of someone else's
# mutation endpoints, so the allowlist is explicit and extra origins are opt-in.
_ORIGINS = [o for o in os.environ.get("CHORUS_ORIGINS", "").split(",") if o] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type", "authorization"],
)

engine = Engine(SNAPSHOT)



# -- authorisation ------------------------------------------------------------
#
# Reads stay public and mutations do not. That split is deliberate: a judge, a reader or a
# recruiter should be able to open the console and watch twenty thousand agents collapse
# without being handed a credential, while forking a timeline, merging one into production,
# adopting a policy or spending money on a swarm should not be available to anyone who
# finds the URL.
#
# The token comes from Secret Manager via the deploy, never from a literal. When none is
# configured the mutation endpoints are refused outright rather than left open — an
# unset secret is the single most common way a control like this ends up doing nothing.

_MUTATION_TOKEN = os.environ.get("CHORUS_WRITE_TOKEN", "")


def require_write(authorization: str = Header(default="")) -> None:
    """Gate for anything that mutates state or spends money."""
    if not _MUTATION_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "No write token is configured, so mutation endpoints are closed. "
                "Set CHORUS_WRITE_TOKEN to enable them."
            ),
        )
    supplied = authorization.removeprefix("Bearer ").strip()
    # Constant time: a short-circuiting comparison leaks the token one byte at a time.
    if not supplied or not compare_digest(supplied, _MUTATION_TOKEN):
        raise HTTPException(status_code=401, detail="write access requires a bearer token")



# The demo endpoint is the exception, and the reasoning is worth stating. Closing
# /api/swarm would protect the budget by removing the product: the one thing a visitor
# should be able to do is watch the collapse happen. So it stays open with a ceiling low
# enough that abuse is bounded, and the full range needs a token.
#
# The limiter is per instance, not global. With several Cloud Run instances the effective
# rate is the limit times the instance count, which is a real weakness and is written down
# rather than left for someone to discover. A global limit belongs in Cloud Armor.

PUBLIC_AGENT_CEILING = 300
_RATE_WINDOW_S = 60.0
_RATE_MAX = 6
_recent: dict[str, list[float]] = defaultdict(list)


def _rate_limited(caller: str) -> bool:
    now = time.time()
    hits = [t for t in _recent[caller] if now - t < _RATE_WINDOW_S]
    _recent[caller] = hits
    if len(hits) >= _RATE_MAX:
        return True
    hits.append(now)
    return False


def demo_or_write(
    request: Request, authorization: str = Header(default="")
) -> bool:
    """Allow a small public run; require a token for anything larger.

    Returns whether the caller is authorised for the full range, so the endpoint can cap
    the population rather than refuse the request outright.
    """
    supplied = authorization.removeprefix("Bearer ").strip()
    if _MUTATION_TOKEN and supplied and compare_digest(supplied, _MUTATION_TOKEN):
        return True
    caller = request.client.host if request.client else "unknown"
    if _rate_limited(caller):
        raise HTTPException(
            status_code=429,
            detail=f"more than {_RATE_MAX} runs a minute; use a token for sustained use",
        )
    return False


# -- request models -----------------------------------------------------------

# Every bound below is a real limit rather than a formality. `agents` multiplies directly
# into model spend, `concurrency` into rate-limit rejections, and an unbounded `population`
# in a search request is an unbounded bill someone else pays.
class ForkRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    at_seq: int = Field(..., ge=0, le=10_000_000)
    perturbation: dict[str, Any] | None = None


class PolicyEdit(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)


class ReplayRequest(BaseModel):
    dispute_ids: list[str] | None = Field(default=None, max_length=500)
    limit: int = Field(10, ge=1, le=500)


class MergeRequest(BaseModel):
    into: str = PRIMARY
    force: bool = False


class SearchRequest(BaseModel):
    dispute_ids: list[str] = Field(default_factory=list, max_length=500)
    clause_id: str = Field("POL-REFUND-CEILING", max_length=120)
    generations: int = Field(2, ge=1, le=10)
    population: int = Field(3, ge=1, le=12)
    concurrency: int = Field(3, ge=1, le=16)


class SwarmRequest(BaseModel):
    agents: int = Field(2_000, ge=1, le=50_000)
    concurrency: int = Field(6, ge=1, le=64)


class AdoptRequest(BaseModel):
    clause_id: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1, max_length=20_000)


# -- meta ---------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus enough state to prove the process really loaded a timeline."""
    return {
        "status": "ok",
        "branches": len(engine.branches()),
        "primary_effects": len(engine.store.timeline(PRIMARY)),
        "snapshot": SNAPSHOT,
        # Which store the process is really serving from — "firestore" when the durable
        # backend is live, otherwise the snapshot it fell back to and why.
        "backend": getattr(engine, "backend", "unknown"),
        "deployment": os.environ.get("K_SERVICE", "local"),
        "region": os.environ.get("LIGHTCONE_REGION", "local"),
    }


# -- timelines ----------------------------------------------------------------

@app.get("/api/branches")
def list_branches() -> list[dict[str, Any]]:
    return engine.branches()


@app.post("/api/branches/{branch_id}/fork", dependencies=[Depends(require_write)])
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


@app.post("/api/branches/{branch_id}/merge", dependencies=[Depends(require_write)])
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

@app.post("/api/branches/{branch_id}/replay", dependencies=[Depends(require_write)])
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

@app.post("/api/search", dependencies=[Depends(require_write)])
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


@app.post("/api/policies/adopt", dependencies=[Depends(require_write)])
def adopt(request: AdoptRequest) -> dict[str, Any]:
    """Install a policy the search proved better into production."""
    try:
        return engine.adopt(clause_id=request.clause_id, text=request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# -- registry -----------------------------------------------------------------

@app.get("/.well-known/agent-card.json", include_in_schema=False)
def a2a_agent_card(request: Request) -> dict[str, Any]:
    """The A2A discovery document, at the path the specification names.

    Mapped from the registry rather than maintained beside it: a second hand-written copy
    of what the agents are would drift from the first, and the drift would be invisible
    because both files would keep looking plausible.

    The base URL is taken from the request so the card is correct behind Cloud Run's
    hostname without anyone configuring it — a card that advertises localhost is worse
    than no card.
    """
    base = str(request.base_url).rstrip("/")
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return agent_card(base)


@app.get("/api/registry")
def registry() -> dict[str, Any]:
    """The agent registry: what is published, at what version, allowed to touch what.

    An enterprise cannot approve what it cannot enumerate. Versions are content-derived,
    so editing a prompt moves the version on its own, and each card states the fields its
    agent is permitted to see — which `tests/test_registry.py` checks is actually true of
    the projection rather than merely written down.
    """
    from fleet.registry import build_registry

    return build_registry()


# -- swarm --------------------------------------------------------------------

@lru_cache(maxsize=8)
def _cohort_layout(agents: int) -> str:
    """The cohort layout for a population, as a JSON string.

    Deterministic: the scenario is generated from a fixed seed, so this is the same answer
    every time and has no business being computed twice. Cached as a string rather than a
    dict so callers cannot mutate the cached value.
    """
    from dataclasses import asdict

    from kernel.clock import FIXED
    from swarm.canonical import bind, collapse, project_passenger
    from swarm.scenario import build_scenario

    scenario = build_scenario(passengers=agents)
    passengers = [asdict(p) for p in scenario.passengers]
    grouped = collapse(passengers, bind(project_passenger, FIXED))
    return json.dumps({
        "agents": len(passengers),
        "scenario": scenario.summary(),
        "cohorts": [
            {"key": key, "size": len(members),
             "label": key.split("|", 1)[1] if "|" in key else key}
            for key, members in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)
        ],
    })


# Warmed off the critical path so a cold container does not make its first visitor sit
# through the generation. Started here rather than beside the engine because the function
# has to exist first — module bodies run top to bottom.
threading.Thread(target=_cohort_layout, args=(20000,), daemon=True).start()


@app.get("/api/necessity")
def necessity() -> dict[str, Any]:
    """The Necessity Ledger: is the model earning its cost?

    Served from the last recorded run rather than computed on request. The number is the
    product of a measurement that costs real money — deriving a policy, serving traffic
    from it, then re-asking the model against its own cache — and recomputing it on every
    page load would be both slow and a different number each time, which is the opposite
    of what a ledger is for.

    Absent data returns `available: false` rather than zeros. A necessity of 0% from a run
    that never happened is the most reassuring number this endpoint could serve and the
    least true.
    """
    path = Path(os.environ.get("CHORUS_NECESSITY", "data/necessity.json"))
    if not path.exists():
        return {"available": False,
                "reason": "no run recorded; scripts/necessity.py writes this"}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"unreadable: {type(exc).__name__}"}
    return {"available": True, **payload}


@app.get("/api/policy")
def policy_table(limit: int = 60, q: str = "") -> dict[str, Any]:
    """The distilled policy, row by row, each with the provenance that derived it.

    Served from the last recorded distillation. Rows are the product of real model calls,
    so recomputing them on request would be both slow and a different table each time —
    which is the opposite of what a policy version is for.
    """
    path = Path(os.environ.get("CHORUS_POLICY", "data/policy.json"))
    if not path.exists():
        return {"available": False, "reason": "no policy distilled; scripts/necessity.py writes this"}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"unreadable: {type(exc).__name__}"}

    rows = payload.get("rows", [])
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r["key"].lower()]
    # Most-served first: the rows that carry the most traffic are the ones worth auditing.
    rows = sorted(rows, key=lambda r: -r.get("provenance", {}).get("served", 0))
    return {
        "available": True,
        "version": payload.get("version"),
        "ceiling": payload.get("ceiling"),
        "populated": payload.get("populated"),
        "matched": len(rows),
        "rows": rows[: max(1, min(limit, 400))],
    }


@app.get("/api/policy/{cell}")
def policy_cell(cell: str) -> dict[str, Any]:
    """One cell, deep-linkable. Every number elsewhere should be able to reach here.

    Provenance you can get to in one click is what separates an audited system from a
    dashboard: the effect that derived this answer, the model that produced it, when, how
    many entities it has served, and whether drift has since invalidated it.
    """
    path = Path(os.environ.get("CHORUS_POLICY", "data/policy.json"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="no policy distilled")
    payload = json.loads(path.read_text())
    for row in payload.get("rows", []):
        if row["key"] == cell:
            return {"available": True, "version": payload.get("version"), **row}
    raise HTTPException(status_code=404, detail=f"no policy cell {cell!r}")


@app.get("/api/swarm/cohorts")
def swarm_cohorts(agents: int = 20000) -> Response:
    """The population at rest: pure bucketing, no model calls, no cost.

    The console draws the field from this before anything is woken, so it sits directly in
    front of first paint — several seconds of blank canvas here is the first thing anyone
    sees of the product.
    """
    return Response(content=_cohort_layout(agents), media_type="application/json")


# -- background runs ----------------------------------------------------------
#
# The synchronous /api/swarm stays, because a small demo run should be watchable in one
# request. Anything larger belongs here: a fifty-minute sweep that costs real money should
# not die with a dropped connection, and the effect DAG is already the checkpoint that
# makes resuming free.

_runs = run_store_from_env()
_runner = Runner(_runs)


async def _execute(run: Run, emit) -> None:
    """Perform one queued sweep, mirroring progress onto the run record."""
    async for event in engine.run_swarm(agents=run.agents, concurrency=run.concurrency):
        emit(event)
        # The engine emits "progress" carrying the metrics dict inline, and "swarm_done"
        # carrying it nested. Reading the wrong field names is silent: the run completes,
        # reports 0/12, and nothing errors — which is exactly what the first version did.
        kind = event.get("event")
        if kind == "progress":
            run.progress = event.get("done", run.progress)
            run.model_calls = event.get("model_calls", run.model_calls)
            run.cache_hits = event.get("cache_hits", run.cache_hits)
            run.cost_usd = event.get("cost_usd", run.cost_usd)
            run.failed = event.get("failed", run.failed)
            # Firestore on every agent would be twenty thousand writes; the record is
            # mirrored on a cadence, and always on the terminal states.
            if run.progress % 250 == 0:
                _runs.put(run)
        elif kind == "swarm_done":
            metrics = event.get("metrics", {})
            run.progress = metrics.get("agents_invoked", run.progress)
            run.model_calls = metrics.get("model_calls", run.model_calls)
            run.cache_hits = metrics.get("cache_hits", run.cache_hits)
            run.cost_usd = metrics.get("cost_usd", run.cost_usd)
            run.distinct_thoughts = metrics.get("distinct_thoughts", 0)
            run.failed = metrics.get("failed", 0)


@app.on_event("startup")
async def _start_runner() -> None:
    _runner.start(_execute)


@app.post("/api/runs", status_code=202)
def enqueue_run(
    request: SwarmRequest, privileged: bool = Depends(demo_or_write)
) -> dict[str, Any]:
    """Queue a sweep and return immediately. The work outlives the request."""
    agents = request.agents
    if not privileged and agents > PUBLIC_AGENT_CEILING:
        agents = PUBLIC_AGENT_CEILING
    run = _runner.enqueue(agents, request.concurrency)
    return {
        "run_id": run.id,
        "state": run.state,
        "agents": run.agents,
        "durable": run.durable,
        "stream": f"/api/runs/{run.id}/stream",
        "capped": agents != request.agents,
    }


@app.get("/api/runs")
def list_runs(limit: int = 20) -> dict[str, Any]:
    return {"runs": [r.to_dict() for r in _runs.recent(limit)]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
    return run.to_dict()


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    """Everything so far, then the live tail.

    A client connecting at agent 12,000 is shown the run from its beginning rather than a
    run that appears to start there — the emitted events are replayed first.
    """
    if _runs.get(run_id) is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")

    async def stream():
        sent = 0
        while True:
            events = _runner.events(run_id)
            for event in events[sent:]:
                yield f"data: {json.dumps(event)}\n\n"
            sent = len(events)
            run = _runs.get(run_id)
            if run and run.state in ("done", "failed", "cancelled"):
                yield f"data: {json.dumps({'event': 'closed', **run.to_dict()})}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/swarm")
async def swarm(
    request: SwarmRequest,
    privileged: bool = Depends(demo_or_write),
) -> StreamingResponse:
    """Run the swarm, streaming progress.

    A recorded swarm replays from the store with no model calls at all, so re-running
    one is instant and free — which is what makes twenty thousand agents watchable in a
    demo rather than a twenty-minute wait.

    An unauthenticated caller is capped rather than refused. The cap is silent in the
    response body but reported in the stream's opening frame, so a visitor sees what they
    actually ran instead of wondering why the number changed.
    """
    agents = request.agents
    capped = not privileged and agents > PUBLIC_AGENT_CEILING
    if capped:
        agents = PUBLIC_AGENT_CEILING

    async def stream():
        if capped:
            yield (
                "data: "
                + json.dumps({
                    "event": "capped",
                    "requested": request.agents,
                    "running": agents,
                    "reason": "public demo ceiling; a write token lifts it",
                })
                + "\n\n"
            )
        async for event in engine.run_swarm(
            agents=agents, concurrency=request.concurrency
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
