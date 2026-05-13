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

from databricks import sql

from osi_bridge.registry import Registry
from osi_bridge.translator import build_sql


def run_sql(sql_text: str) -> list[dict[str, Any]]:
    """Execute SQL against the Databricks warehouse identified by env vars."""
    host = os.environ["DATABRICKS_HOST"].replace("https://", "")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
        with c.cursor() as cur:
            cur.execute(sql_text)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_models(registry: Registry) -> list[dict[str, Any]]:
    """All OSI semantic models available to the bridge."""
    out = []
    for name, m in registry.items():
        sm = m["semantic_model"][0]
        out.append({
            "name": name,
            "description": sm.get("description"),
            "source": (sm.get("datasets") or [{}])[0].get("source"),
            "metric_count": len(sm.get("metrics", [])),
            "dimension_count": sum(len(ds.get("fields", [])) for ds in sm.get("datasets", [])),
            "owner": (sm.get("custom_extensions") or {}).get("odcs", {}).get("owner"),
            "domain": (sm.get("custom_extensions") or {}).get("odcs", {}).get("domain"),
        })
    return out


def list_metrics(registry: Registry, model: str | None = None) -> list[dict[str, Any]]:
    """Metrics across all models, or one. Each row is labelled with `model`."""
    target = [model] if model else registry.names()
    out = []
    for name in target:
        sm = registry.get(name)["semantic_model"][0]
        for m in sm.get("metrics", []):
            ai = m.get("ai_context", {}) or {}
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
    return [
        {
            "name": f["name"],
            "display_name": (f.get("ai_context") or {}).get("display_name"),
            "is_time": (f.get("dimension") or {}).get("is_time", False),
            "synonyms": (f.get("ai_context") or {}).get("synonyms", []),
            "description": f.get("description"),
        }
        for f in fields
    ]


def query_metric(
    registry: Registry,
    model: str,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Translate an OSI metric request to SQL and run it. Returns SQL + rows."""
    osi = registry.get(model)
    sql_text = build_sql(
        osi_model=osi,
        metrics=[metric],
        dimensions=dimensions or [],
        filters=filters or [],
        time_grain=time_grain,
        limit=limit,
    )
    rows = run_sql(sql_text)
    return {"model": model, "sql": sql_text, "rows": rows, "row_count": len(rows)}
