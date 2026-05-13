"""OSI Bridge MCP server.

Wraps the plain-Python tool functions from `osi_bridge.tools` in FastMCP
decorators so any MCP-capable agent (Gemini, Claude, etc.) can consume them
over SSE. The portal (`portal.app`) imports the same functions directly,
skipping the network hop.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from osi_bridge import tools as _tools
from osi_bridge.registry import Registry

load_dotenv(override=True)

mcp = FastMCP("osi-bridge")
_REGISTRY = Registry()


@mcp.tool()
def list_models() -> list[dict[str, Any]]:
    """List all OSI semantic models available to the bridge."""
    return _tools.list_models(_REGISTRY)


@mcp.tool()
def list_metrics(model: str | None = None) -> list[dict[str, Any]]:
    """List metrics. If `model` is omitted, returns metrics across every model.

    Each row carries the `model` it belongs to so the agent can route a
    follow-up `query_metric` call.
    """
    return _tools.list_metrics(_REGISTRY, model)


@mcp.tool()
def list_dimensions(model: str, metric: str | None = None) -> list[dict[str, Any]]:
    """List dimensions of a model.

    `metric` is currently informational — Databricks Metric Views allow any
    dimension on any metric within the same view.
    """
    return _tools.list_dimensions(_REGISTRY, model, metric)


@mcp.tool()
def query_metric(
    model: str,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Query a metric in `model` with optional dimensions, filters, and time grain."""
    return _tools.query_metric(_REGISTRY, model, metric, dimensions, filters, time_grain, limit)


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
