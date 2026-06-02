"""Vendor adapter dispatcher.

The bridge ships three adapters today: `databricks`, `dremio`, `strategy`.
Each implements:
  - ENGINE_NAME       — short string used in OSI custom_extensions
  - build_query(...)  — produces a RenderedQuery (SQL string or REST body)
  - execute(rendered) — runs it and returns rows

A model's available engines are discovered from OSI `custom_extensions`. The
default engine is the first one present in this priority order:
`databricks`, `dremio`, `strategy`. The caller may pass `engine=...` to
override.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

from osi_bridge.translators._common import RenderedQuery, list_extension_vendors


_ENGINE_PRIORITY = ("databricks", "dremio", "strategy")
_MODULES = {name: f"osi_bridge.translators.{name}" for name in _ENGINE_PRIORITY}


def _load(engine: str):
    if engine not in _MODULES:
        raise ValueError(f"Unknown engine '{engine}'. Available: {list(_MODULES)}")
    return import_module(_MODULES[engine])


def available_engines(osi_model: dict[str, Any]) -> list[str]:
    """Return engines for which a `custom_extensions` entry is present in the
    OSI, ordered by the bridge's priority. Accepts both the spec-compliant
    array shape (`[{vendor_name, data}]`) and the legacy map shape."""
    vendors = set(list_extension_vendors(
        osi_model["semantic_model"][0].get("custom_extensions")
    ))
    return [e for e in _ENGINE_PRIORITY if e in vendors]


def pick_engine(osi_model: dict[str, Any], hint: str | None = None) -> str:
    """Choose an engine to route a query to.

    If `hint` is given and the OSI has a matching custom_extensions block,
    honour it. Otherwise return the first available engine. If nothing is
    available, fall back to `databricks` to preserve Phase 0 behaviour.
    """
    available = available_engines(osi_model)
    if hint:
        if hint not in _MODULES:
            raise ValueError(f"Unknown engine hint '{hint}'. Available: {list(_MODULES)}")
        if hint not in available:
            raise ValueError(
                f"Engine '{hint}' has no custom_extensions block in this OSI model. "
                f"Available: {available}"
            )
        return hint
    return available[0] if available else "databricks"


def build_query(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
    *,
    engine: str | None = None,
) -> RenderedQuery:
    chosen = pick_engine(osi_model, engine)
    adapter = _load(chosen)
    return adapter.build_query(osi_model, metrics, dimensions, filters, time_grain, limit)


def execute(rendered: RenderedQuery) -> list[dict[str, Any]]:
    return _load(rendered.engine).execute(rendered)


def build_and_execute(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
    *,
    engine: str | None = None,
) -> tuple[RenderedQuery, list[dict[str, Any]]]:
    rendered = build_query(
        osi_model, metrics, dimensions, filters, time_grain, limit, engine=engine
    )
    rows = execute(rendered)
    return rendered, rows


__all__ = [
    "RenderedQuery",
    "available_engines",
    "pick_engine",
    "build_query",
    "execute",
    "build_and_execute",
]
