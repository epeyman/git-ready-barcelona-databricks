"""Bridge tool implementations as plain Python.

These are the same functions exposed over MCP by `osi_bridge.server` and
called in-process by the portal (`portal.app`) without going through SSE.
Keeping them in a separate module means:

  - The MCP server is a thin `@mcp.tool()` decorator wrapper.
  - The portal can call `list_models()` etc. directly with zero networking.
  - Unit tests do not have to stand up FastMCP.

Every function takes the `Registry` it operates on as the first argument so
this module owns no global state.
"""
from __future__ import annotations

import os
from typing import Any

from osi_bridge import translators
from osi_bridge.registry import Registry
from osi_bridge.translators._common import RenderedQuery, get_ai_context, get_custom_extension


def _odcs_ext(sm: dict[str, Any]) -> dict[str, Any]:
    """ODCS data-contract block from custom_extensions (dual-shape)."""
    return get_custom_extension(sm.get("custom_extensions"), "odcs")


def run_sql(sql_text: str) -> list[dict[str, Any]]:
    """Phase-0 escape hatch — execute raw SQL against the Databricks warehouse.

    Kept for ad-hoc tooling; the canonical query path is now
    `osi_bridge.translators.build_and_execute`, which routes per the OSI
    model's `custom_extensions`.
    """
    from osi_bridge.translators.databricks import execute as _execute

    return _execute(RenderedQuery(engine="databricks", kind="sql", payload=sql_text))


def list_models(registry: Registry) -> list[dict[str, Any]]:
    """All OSI semantic models available to the bridge."""
    out = []
    for name, m in registry.items():
        sm = m["semantic_model"][0]
        engines = translators.available_engines(m) or ["databricks"]
        out.append({
            "name": name,
            "description": sm.get("description"),
            "source": (sm.get("datasets") or [{}])[0].get("source"),
            "metric_count": len(sm.get("metrics", [])),
            "dimension_count": sum(len(ds.get("fields", [])) for ds in sm.get("datasets", [])),
            "owner": _odcs_ext(sm).get("owner"),
            "domain": _odcs_ext(sm).get("domain"),
            "engines": engines,
            "default_engine": engines[0],
        })
    return out


def list_metrics(registry: Registry, model: str | None = None) -> list[dict[str, Any]]:
    """Metrics across all models, or one. Each row is labelled with `model`."""
    target = [model] if model else registry.names()
    out = []
    for name in target:
        sm = registry.get(name)["semantic_model"][0]
        for m in sm.get("metrics", []):
            ai = get_ai_context(m)
            out.append({
                "model": name,
                "name": m["name"],
                "display_name": ai.get("display_name"),
                "description": m.get("description"),
                "synonyms": ai.get("synonyms", []),
            })
    return out


def list_dimensions(
    registry: Registry, model: str, metric: str | None = None
) -> list[dict[str, Any]]:
    """Dimensions of one model. `metric` is informational only."""
    sm = registry.get(model)["semantic_model"][0]
    fields = sm["datasets"][0]["fields"]
    rows = []
    for f in fields:
        ai = get_ai_context(f)
        rows.append({
            "name": f["name"],
            "display_name": ai.get("display_name"),
            "is_time": (f.get("dimension") or {}).get("is_time", False),
            "synonyms": ai.get("synonyms", []),
            "description": f.get("description"),
        })
    return rows


def query_metric(
    registry: Registry,
    model: str,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
    *,
    engine: str | None = None,
) -> dict[str, Any]:
    """Translate an OSI metric request and run it on the selected engine.

    The engine is picked from the OSI model's `custom_extensions` blocks —
    `databricks` first, then `dremio`, then `strategy`. Pass `engine=...` to
    force one. The response always carries the engine that ran, the rendered
    query (SQL string or REST body), and `executable` metadata so the portal
    can tell the user whether the query was actually run or just rendered.
    """
    osi = registry.get(model)
    rendered = translators.build_query(
        osi_model=osi,
        metrics=[metric],
        dimensions=dimensions or [],
        filters=filters or [],
        time_grain=time_grain,
        limit=limit,
        engine=engine,
    )
    executable = rendered.metadata.get("executable", True)
    response: dict[str, Any] = {
        "model": model,
        "engine": rendered.engine,
        "kind": rendered.kind,
        "fqn": rendered.fqn,
        rendered.kind: rendered.payload,  # 'sql' or 'rest' key on the response
        "executable": executable,
    }
    if not executable:
        response["rows"] = []
        response["row_count"] = 0
        response["note"] = (
            f"Adapter '{rendered.engine}' has no credentials configured "
            "(set the engine's env vars). Returning the rendered query only."
        )
        return response

    rows = translators.execute(rendered)
    response["rows"] = rows
    response["row_count"] = len(rows)
    return response
