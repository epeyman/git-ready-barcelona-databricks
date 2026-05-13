"""OSI Bridge MCP server.

Loads one or more OSI YAML models into a registry and exposes MCP tools
that an agent (Gemini, Claude, etc.) consumes:

  - list_models       — what semantic models are available
  - list_metrics      — metrics across one or all models
  - list_dimensions   — dimensions of a given model
  - query_metric      — execute a metric query against the backing engine

Backend: Databricks SQL warehouse, queried via databricks-sql-connector.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from databricks import sql
from dotenv import load_dotenv
from fastmcp import FastMCP

from osi_bridge.registry import Registry
from osi_bridge.translator import build_sql

load_dotenv(override=True)

mcp = FastMCP("osi-bridge")
_REGISTRY = Registry()


def _run_sql(sql_text: str) -> list[dict[str, Any]]:
    host = os.environ["DATABRICKS_HOST"].replace("https://", "")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
        with c.cursor() as cur:
            cur.execute(sql_text)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@mcp.tool()
def list_models() -> list[dict[str, Any]]:
    """List all OSI semantic models available to the bridge."""
    out = []
    for name, m in _REGISTRY.items():
        sm = m["semantic_model"][0]
        out.append({
            "name": name,
            "description": sm.get("description"),
            "source": (sm.get("datasets") or [{}])[0].get("source"),
            "metric_count": len(sm.get("metrics", [])),
            "dimension_count": sum(len(ds.get("fields", [])) for ds in sm.get("datasets", [])),
        })
    return out


@mcp.tool()
def list_metrics(model: str | None = None) -> list[dict[str, Any]]:
    """List metrics. If `model` is omitted, returns metrics across every model.

    Each row carries the `model` it belongs to so the agent can route a
    follow-up `query_metric` call.
    """
    target = [model] if model else _REGISTRY.names()
    out = []
    for name in target:
        sm = _REGISTRY.get(name)["semantic_model"][0]
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


@mcp.tool()
def list_dimensions(model: str, metric: str | None = None) -> list[dict[str, Any]]:
    """List dimensions of a model.

    `metric` is currently informational — Databricks Metric Views allow any
    dimension on any metric within the same view.
    """
    sm = _REGISTRY.get(model)["semantic_model"][0]
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


@mcp.tool()
def query_metric(
    model: str,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Query a metric in `model` with optional dimensions, filters, and time grain.

    Args:
        model: model name from list_models()
        metric: metric name from list_metrics(model=...)
        dimensions: dimension names from list_dimensions(model=...)
        filters: list of {column, op, value}
        time_grain: 'day' | 'week' | 'month' | 'quarter' | 'year'
        limit: row cap (default 1000)
    """
    osi = _REGISTRY.get(model)
    sql_text = build_sql(
        osi_model=osi,
        metrics=[metric],
        dimensions=dimensions or [],
        filters=filters or [],
        time_grain=time_grain,
        limit=limit,
    )
    rows = _run_sql(sql_text)
    return {"model": model, "sql": sql_text, "rows": rows, "row_count": len(rows)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--store",
        default=os.environ.get("OSI_BRIDGE_STORE", "file"),
        choices=["file", "sqlite", "lakebase"],
        help="Backing model store. 'file' scans --models-dir, 'sqlite' uses "
             "--sqlite-path, 'lakebase' uses $OSI_BRIDGE_PG_DSN.",
    )
    p.add_argument(
        "--osi-model",
        default=os.environ.get("OSI_MODEL_PATH"),
        help="Path to a single OSI YAML file (back-compat).",
    )
    p.add_argument(
        "--models-dir",
        default=os.environ.get("OSI_MODELS_DIR", "examples/models"),
        help="Directory of *.osi.yaml files (used by --store file).",
    )
    p.add_argument(
        "--sqlite-path",
        default=os.environ.get("OSI_BRIDGE_SQLITE", "osi_bridge.db"),
        help="SQLite file (used by --store sqlite).",
    )
    p.add_argument(
        "--pg-dsn",
        default=os.environ.get("OSI_BRIDGE_PG_DSN"),
        help="Postgres DSN (used by --store lakebase).",
    )
    p.add_argument("--transport", default="sse", choices=["sse", "stdio"])
    p.add_argument("--host", default=os.environ.get("OSI_BRIDGE_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("OSI_BRIDGE_PORT", 8000)))
    args = p.parse_args()

    if args.store == "file":
        source = args.osi_model or args.models_dir
        loaded = _REGISTRY.load_path(source)
        print(f"[OSI Bridge] Loaded {len(loaded)} model(s) from {source}: {loaded}")
    elif args.store == "sqlite":
        from osi_bridge.store.sqlite import SqliteModelStore

        store = SqliteModelStore(args.sqlite_path)
        _REGISTRY.attach(store)
        loaded = store.list_names()
        print(f"[OSI Bridge] Loaded {len(loaded)} model(s) from sqlite {args.sqlite_path}: {loaded}")
    elif args.store == "lakebase":
        from osi_bridge.store.lakebase import LakebaseModelStore

        store = LakebaseModelStore(args.pg_dsn)
        _REGISTRY.attach(store)
        loaded = store.list_names()
        print(f"[OSI Bridge] Loaded {len(loaded)} model(s) from Lakebase: {loaded}")
    else:  # argparse already restricts this; defensive
        raise ValueError(f"Unknown --store {args.store!r}")

    if args.transport == "sse":
        print(f"[OSI Bridge] MCP server listening on http://{args.host}:{args.port}/sse")
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
