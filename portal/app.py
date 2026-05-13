"""FastAPI entry point for the GIT READY portal.

Loads the registry from a backing model store (file, sqlite, or lakebase —
controlled by env vars) at startup, then exposes a small JSON API consumed
by the single-page preact/htm frontend in ./static/. Access-requests are
persisted to a SQLite or Lakebase store when available; the file-backed
flow keeps an in-memory log so the demo path stays self-contained.
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

from osi_bridge import tools, translators
from osi_bridge.lineage import get_lineage
from osi_bridge.producer import infer as producer_infer
from osi_bridge.producer import publish as producer_publish
from osi_bridge.provisioning import grant_all, rollup_status
from osi_bridge.registry import Registry
from osi_bridge.search import ai_fallback, search_metrics

from portal import chat as chat_handler
from portal.schemas import (
    AccessRequest,
    AccessRequestListEntry,
    AccessRequestResponse,
    ApprovalAction,
    ChatRequest,
    ChatResponse,
    DimensionSummary,
    FallbackRequest,
    FallbackResponse,
    GrantEntry,
    InferRequest,
    InferResponse,
    LineageResponse,
    MetricSummary,
    ModelSummary,
    PublishFileResult,
    PublishRequest,
    PublishResponse,
    SearchHit,
    SearchResponse,
)

load_dotenv(override=True)

STATIC_DIR = Path(__file__).parent / "static"
REGISTRY = Registry()
_STORE: Any = None  # SqliteModelStore | LakebaseModelStore | None
_INMEM_REQUESTS: list[dict[str, Any]] = []  # used only when _STORE is None


def _init_registry() -> None:
    global _STORE
    store_kind = os.environ.get("PORTAL_STORE", os.environ.get("OSI_BRIDGE_STORE", "file"))
    if store_kind == "file":
        path = os.environ.get("OSI_MODELS_DIR", "examples/models")
        REGISTRY.load_path(path)
    elif store_kind == "sqlite":
        from osi_bridge.store.sqlite import SqliteModelStore

        db = os.environ.get("OSI_BRIDGE_SQLITE", "osi_bridge.db")
        store = SqliteModelStore(db)
        REGISTRY.attach(store)
        _STORE = store
    elif store_kind == "lakebase":
        from osi_bridge.store.lakebase import LakebaseModelStore

        store = LakebaseModelStore(os.environ.get("OSI_BRIDGE_PG_DSN"))
        REGISTRY.attach(store)
        _STORE = store
    else:
        raise RuntimeError(f"Unknown PORTAL_STORE {store_kind!r}")
    print(f"[Portal] Registry loaded from {store_kind}: {REGISTRY.names()}")
    if _STORE is None:
        print("[Portal] file-backed store has no access-request persistence; using in-memory log.")


app = FastAPI(title="GIT READY data portal", version="0.4.0")
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
    engines = translators.available_engines(osi) or ["databricks"]
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
        "engines": engines,
        "default_engine": engines[0],
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


def _model_owner(osi: dict[str, Any]) -> str | None:
    return ((osi["semantic_model"][0].get("custom_extensions") or {}).get("odcs") or {}).get("owner")


def _persist_request(
    request_id: str, req: AccessRequest, status: str, grants: list[dict[str, Any]]
) -> None:
    if _STORE is not None:
        _STORE.save_access_request(request_id, req.model, req.requester, req.business_justification)
        _STORE.update_access_status(request_id, status)
        if grants:
            _STORE.record_grants(request_id, grants)
    else:
        _INMEM_REQUESTS.append({
            "id": request_id,
            "model": req.model,
            "requester": req.requester,
            "justification": req.business_justification,
            "status": status,
            "grants": grants,
            "created_at": datetime.utcnow().isoformat() + "Z",
        })


@app.post("/api/access-requests", response_model=AccessRequestResponse)
def post_access_request(req: AccessRequest) -> AccessRequestResponse:
    try:
        osi = REGISTRY.get(req.model)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    request_id = str(uuid.uuid4())
    owner = _model_owner(osi)
    requires_approval = owner is not None and not req.auto_approve

    if requires_approval:
        status = "pending_approval"
        grants: list[dict[str, Any]] = []
        note = f"Pending approval by {owner}."
    else:
        results = grant_all(osi, req.requester, req.business_justification, dry_run=req.dry_run)
        grants = [r.as_dict() for r in results]
        status = rollup_status(results)
        note = "; ".join(f"{g['engine']}: {g['status']}" for g in grants)

    _persist_request(request_id, req, status, grants)
    print(
        f"[Portal] access-request {request_id} {req.model} by {req.requester} "
        f"→ {status}: {note}"
    )
    return AccessRequestResponse(
        id=request_id,
        model=req.model,
        requester=req.requester,
        status=status,
        note=note,
        grants=[GrantEntry(**g) for g in grants],
    )


@app.post("/api/access-requests/{request_id}/approve", response_model=AccessRequestResponse)
def approve_access_request(request_id: str, action: ApprovalAction) -> AccessRequestResponse:
    if _STORE is None:
        entry = next((r for r in _INMEM_REQUESTS if r["id"] == request_id), None)
    else:
        entry = _STORE.get_access_request(request_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown request '{request_id}'")
    if entry["status"] != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Request is {entry['status']}, not pending_approval.")

    try:
        osi = REGISTRY.get(entry["model"])
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    results = grant_all(osi, entry["requester"], entry.get("justification", ""), dry_run=False)
    grants = [r.as_dict() for r in results]
    # Stamp the approver into the audit log via a synthetic "approval" row.
    grants.insert(0, {"engine": "approval", "status": "granted", "detail": f"Approved by {action.approver}: {action.reason or 'no reason given'}"})
    status = rollup_status(results)

    if _STORE is not None:
        _STORE.record_grants(request_id, grants)
        _STORE.update_access_status(request_id, status)
    else:
        entry["status"] = status
        entry["grants"] = (entry.get("grants") or []) + grants

    note = "; ".join(f"{g['engine']}: {g['status']}" for g in grants)
    print(f"[Portal] approve {request_id} by {action.approver} → {status}: {note}")
    return AccessRequestResponse(
        id=request_id,
        model=entry["model"],
        requester=entry["requester"],
        status=status,
        note=note,
        grants=[GrantEntry(**g) for g in grants],
    )


@app.post("/api/access-requests/{request_id}/reject", response_model=AccessRequestResponse)
def reject_access_request(request_id: str, action: ApprovalAction) -> AccessRequestResponse:
    if _STORE is None:
        entry = next((r for r in _INMEM_REQUESTS if r["id"] == request_id), None)
    else:
        entry = _STORE.get_access_request(request_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown request '{request_id}'")
    if entry["status"] != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Request is {entry['status']}, not pending_approval.")

    rejection_row = {
        "engine": "approval",
        "status": "rejected",
        "detail": f"Rejected by {action.approver}: {action.reason or 'no reason given'}",
    }
    if _STORE is not None:
        _STORE.record_grants(request_id, [rejection_row])
        _STORE.update_access_status(request_id, "rejected")
    else:
        entry["status"] = "rejected"
        entry["grants"] = (entry.get("grants") or []) + [rejection_row]

    return AccessRequestResponse(
        id=request_id,
        model=entry["model"],
        requester=entry["requester"],
        status="rejected",
        note=rejection_row["detail"],
        grants=[GrantEntry(**rejection_row)],
    )


@app.get("/api/access-requests", response_model=list[AccessRequestListEntry])
def list_access_requests(
    owner: str | None = None, status: str | None = None
) -> list[AccessRequestListEntry]:
    if _STORE is not None:
        return [
            AccessRequestListEntry(**r)
            for r in _STORE.list_access_requests(owner=owner, status=status)
        ]
    # In-memory fallback: filter by owner via the registry, by status directly.
    rows = list(reversed(_INMEM_REQUESTS))
    if status:
        rows = [r for r in rows if r["status"] == status]
    if owner:
        rows = [r for r in rows if _model_owner(REGISTRY.get(r["model"])) == owner]
    return [
        AccessRequestListEntry(
            id=r["id"], model=r["model"], requester=r["requester"],
            status=r["status"], created_at=r["created_at"],
        )
        for r in rows
    ]


@app.get("/api/access-requests/{request_id}", response_model=AccessRequestResponse)
def get_access_request(request_id: str) -> AccessRequestResponse:
    if _STORE is not None:
        entry = _STORE.get_access_request(request_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Unknown request '{request_id}'")
        return AccessRequestResponse(
            id=entry["id"],
            model=entry["model"],
            requester=entry["requester"],
            status=entry["status"],
            note="; ".join(f"{g['engine']}: {g['status']}" for g in entry["grants"]),
            grants=[GrantEntry(**g) for g in entry["grants"]],
        )
    for r in _INMEM_REQUESTS:
        if r["id"] == request_id:
            return AccessRequestResponse(
                id=r["id"],
                model=r["model"],
                requester=r["requester"],
                status=r["status"],
                note="; ".join(f"{g['engine']}: {g['status']}" for g in r["grants"]),
                grants=[GrantEntry(**g) for g in r["grants"]],
            )
    raise HTTPException(status_code=404, detail=f"Unknown request '{request_id}'")


@app.get("/api/models/{name}/lineage", response_model=LineageResponse)
def get_model_lineage(name: str) -> LineageResponse:
    try:
        store_target = _STORE if _STORE is not None else _file_store_facade()
        return LineageResponse(**get_lineage(store_target, name))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _file_store_facade() -> Any:
    """When the portal is in file-store mode the registry-attached object IS
    the store; lineage just needs a `.get(name)` and an optional `.history`.
    """
    return REGISTRY._store  # noqa: SLF001  intentional access for facade


@app.post("/api/producer/infer", response_model=InferResponse)
def post_producer_infer(req: InferRequest) -> InferResponse:
    try:
        result = producer_infer(
            req.fqn,
            domain=req.domain,
            owner=req.owner,
            description=req.description,
            dry_run=req.dry_run,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
    return InferResponse(**result)


@app.post("/api/producer/publish", response_model=PublishResponse)
def post_producer_publish(req: PublishRequest) -> PublishResponse:
    try:
        result = producer_publish(req.osi, req.odcs, dry_run=req.dry_run, store=_STORE)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
    git_result = result["git"]
    return PublishResponse(
        model=result["model"],
        mode=git_result["mode"],
        files=[PublishFileResult(**f) for f in git_result["files"]],
        persisted_to_store=result["persisted_to_store"],
        commit_message=git_result.get("commit_message", ""),
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    import os as _os
    return {
        "status": "ok",
        "models": REGISTRY.names(),
        "persistent_access_log": _STORE is not None,
        "git_publishing_configured": bool(_os.environ.get("GITHUB_TOKEN") and _os.environ.get("GITHUB_CONTRACTS_REPO")),
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(404)
async def spa_fallback(request, exc):  # type: ignore[no-untyped-def]
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": exc.detail})
    return FileResponse(STATIC_DIR / "index.html")
