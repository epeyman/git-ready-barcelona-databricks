"""Shared helpers across vendor adapters — semantics live in the OSI model,
not in any one engine. Adapters import from here for validation and time-grain
resolution so the same OSI dict yields equivalent intent on every backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RenderedQuery:
    """One translator's rendered output. The dispatcher returns this so the
    portal can show *which* engine was used and *what* was sent to it."""

    engine: str
    kind: str  # 'sql' | 'rest'
    payload: Any  # str for SQL, dict for REST
    fqn: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def time_column(sm: dict[str, Any]) -> str | None:
    """Return the first dimension flagged `dimension.is_time: true`, or None."""
    for f in sm["datasets"][0]["fields"]:
        if (f.get("dimension") or {}).get("is_time"):
            return f["name"]
    return None


def dim_expression(sm: dict[str, Any], name: str, *, dialect: str | None = None) -> str:
    """Resolve a dimension name to its `expression[].sql`. Falls back to the
    first expression if no dialect-specific entry exists."""
    for f in sm["datasets"][0]["fields"]:
        if f["name"] == name:
            return _pick_sql(f.get("expression") or [], dialect, fallback=name)
    raise KeyError(f"Unknown dimension '{name}'")


def metric_expression(sm: dict[str, Any], name: str, *, dialect: str | None = None) -> str:
    """Resolve a metric name to its `expression[].sql`."""
    for m in sm.get("metrics") or []:
        if m["name"] == name:
            return _pick_sql(m.get("expression") or [], dialect, fallback=name)
    raise KeyError(f"Unknown metric '{name}'")


def _pick_sql(exprs: list[dict[str, Any]], dialect: str | None, fallback: str) -> str:
    if dialect:
        for e in exprs:
            if (e.get("dialect") or "").lower() == dialect.lower():
                return e["sql"]
    if exprs:
        return exprs[0]["sql"]
    return fallback


def validate(
    sm: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None,
    filters: list[dict[str, Any]] | None,
) -> None:
    valid_metrics = {m["name"] for m in sm["metrics"]}
    valid_dims = {f["name"] for f in sm["datasets"][0]["fields"]}
    for m in metrics:
        if m not in valid_metrics:
            raise ValueError(f"Unknown metric '{m}'. Valid: {sorted(valid_metrics)}")
    for d in dimensions or []:
        if d not in valid_dims:
            raise ValueError(f"Unknown dimension '{d}'. Valid: {sorted(valid_dims)}")
    for f in filters or []:
        col = f.get("column")
        if col not in valid_dims:
            raise ValueError(f"Unknown filter column '{col}'. Valid: {sorted(valid_dims)}")


def render_filter(f: dict[str, Any]) -> str:
    """Render a SQL WHERE clause from {column, op, value}. Shared across SQL adapters."""
    col, op, val = f["column"], f.get("op", "="), f["value"]
    rendered = f"'{val}'" if isinstance(val, str) else str(val)
    return f"{col} {op} {rendered}"
