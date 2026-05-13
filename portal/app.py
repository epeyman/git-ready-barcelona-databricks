"""FastAPI entry point for the GIT READY portal.

Loads the registry from a backing model store (file, sqlite, or lakebase —
controlled by env vars) at startup, then exposes a small JSON API consumed
by the single-page preact/htm frontend in ./static/.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from osi_bridge import tools
from osi_bridge.registry import Registry
from osi_bridge.search import ai_fallback, search_metrics

from portal import chat as chat_handler
from portal.schemas import (
    AccessRequest,
    AccessRequestResponse,
    ChatRequest,
    ChatResponse,
    DimensionSummary,
    FallbackRequest,
    FallbackResponse,
    MetricSummary,
    ModelSummary,
    SearchHit,
    SearchResponse,
)

load_dotenv(override=True)

STATIC_DIR = Path(__file__).parent / "static"
REGISTRY = Registry()
# In-memory request log — Phase 4 will replace with persisted rows + real
# provisioning across Databricks, Strategy, and Dremio.
_ACCESS_LOG: list[AccessRequestResponse] = []


def _init_registry() -> None:
    store_kind = os.environ.get("PORTAL_STORE", os.environ.get("OSI_BRIDGE_STORE", "file"))
    if store_kind == "file":
        path = os.environ.get("OSI_MODELS_DIR", "examples/models")
        REGISTRY.load_path(path)
    elif store_kind == "sqlite":
        from osi_bridge.store.sqlite import SqliteModelStore

        db = os.environ.get("OSI_BRIDGE_SQLITE", "osi_bridge.db")
        REGISTRY.attach(SqliteModelStore(db))
    elif store_kind == "lakebase":
        from osi_bridge.store.lakebase import LakebaseModelStore

        REGISTRY.attach(LakebaseModelStore(os.environ.get("OSI_BRIDGE_PG_DSN")))
    else:
        raise RuntimeError(f"Unknown PORTAL_STORE {store_kind!r}")
    print(f"[Portal] Registry loaded from {store_kind}: {REGISTRY.names()}")


app = FastAPI(title="GIT READY data portal", version="0.2.0")
_init_registry()


@app.get("/api/models", response_model=list[ModelSummary])
def get_models() -> list[ModelSummary]:
    return [ModelSummary(**m) for m in tools.list_models(REGISTRY)]


@app.get("/api/models/{name}")
def get_model(name: str) -> dict[str, Any]:
    try:
        osi = REGISTRY.get(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    sm = osi["semantic_model"][0]
    return {
        "name": name,
        "description": sm.get("description"),
        "source": (sm.get("datasets") or [{}])[0].get("source"),
        "ai_context": sm.get("ai_context", {}),
        "metrics": tools.list_metrics(REGISTRY, name),
        "dimensions": [DimensionSummary(**d).model_dump() for d in tools.list_dimensions(REGISTRY, name)],
        "fqn": (sm.get("custom_extensions") or {}).get("databricks", {}).get("metric_view_fqn"),
        "odcs": (sm.get("custom_extensions") or {}).get("odcs", {}),
        "confluence": (sm.get("custom_extensions") or {}).get("confluence", {}),
    }


@app.get("/api/metrics", response_model=list[MetricSummary])
def get_metrics(model: str | None = None) -> list[MetricSummary]:
    return [MetricSummary(**m) for m in tools.list_metrics(REGISTRY, model)]


@app.get("/api/search", response_model=SearchResponse)
def get_search(q: str, limit: int = 20) -> SearchResponse:
    hits = [SearchHit(**h) for h in search_metrics(REGISTRY, q, limit=limit)]
    return SearchResponse(query=q, hits=hits)


@app.post("/api/search/fallback", response_model=FallbackResponse)
def post_fallback(req: FallbackRequest) -> FallbackResponse:
    try:
        result = ai_fallback(REGISTRY, req.query)
    except Exception as e:
        # Fallback degrades gracefully — surface the error to the UI as rationale.
        return FallbackResponse(
            query=req.query,
            rationale=f"AI fallback unavailable ({type(e).__name__}: {e}).",
        )
    return FallbackResponse(
        query=req.query,
        suggested_models=result.get("suggested_models", []) or [],
        rationale=result.get("rationale", "") or "",
        owner_contacts=result.get("owner_contacts", []) or [],
        request_action=result.get("request_action", "") or "",
    )


@app.post("/api/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest) -> ChatResponse:
    try:
        return chat_handler.chat(REGISTRY, req.question, max_steps=req.max_steps)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/access-requests", response_model=AccessRequestResponse)
def post_access_request(req: AccessRequest) -> AccessRequestResponse:
    if req.model not in REGISTRY.names():
        raise HTTPException(status_code=404, detail=f"Unknown model '{req.model}'")
    entry = AccessRequestResponse(
        id=str(uuid.uuid4()),
        model=req.model,
        requester=req.requester,
        status="pending",
        note=(
            "Phase 4 will provision access across Databricks, Dremio, and "
            "Strategy via REST APIs. Logged in-memory for now."
        ),
    )
    _ACCESS_LOG.append(entry)
    print(f"[Portal] access-request {entry.id} for {req.model} by {req.requester} @ {datetime.utcnow().isoformat()}Z")
    return entry


@app.get("/api/access-requests", response_model=list[AccessRequestResponse])
def list_access_requests() -> list[AccessRequestResponse]:
    return list(_ACCESS_LOG)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "models": REGISTRY.names()}


# ----- Static SPA -----

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(404)
async def spa_fallback(request, exc):  # type: ignore[no-untyped-def]
    # API 404s pass through; everything else falls back to the SPA so the
    # client-side router can take it.
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": exc.detail})
    return FileResponse(STATIC_DIR / "index.html")
