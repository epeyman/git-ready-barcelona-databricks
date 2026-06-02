"""Shared helpers across vendor adapters — semantics live in the OSI model,
not in any one engine. Adapters import from here for validation, time-grain
resolution, and dual-shape OSI extraction so the same OSI dict yields
equivalent intent on every backend.

Dual-shape readers: all OSI-extraction helpers accept BOTH the
spec-compliant shape (per `core-spec/osi-schema.json`) and the legacy
prototype shape (originally produced by the pre-spec exporter).
"""
from __future__ import annotations

import json
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
    """Resolve a dimension name to its SQL expression. Falls back to the
    first expression if no dialect-specific entry exists."""
    for f in sm["datasets"][0]["fields"]:
        if f["name"] == name:
            return get_expression_sql(f.get("expression"), dialect=dialect, fallback=name)
    raise KeyError(f"Unknown dimension '{name}'")


def metric_expression(sm: dict[str, Any], name: str, *, dialect: str | None = None) -> str:
    """Resolve a metric name to its SQL expression."""
    for m in sm.get("metrics") or []:
        if m["name"] == name:
            return get_expression_sql(m.get("expression"), dialect=dialect, fallback=name)
    raise KeyError(f"Unknown metric '{name}'")


def get_expression_sql(
    expression: Any,
    *,
    dialect: str | None = None,
    fallback: str = "",
) -> str:
    """Pull SQL out of an OSI `expression` block. Accepts both shapes.

    - Spec: `{"dialects": [{"dialect": "DATABRICKS", "expression": "<sql>"}]}`
    - Legacy: `[{"dialect": "Databricks", "sql": "<sql>"}]`

    Dialect match is case-insensitive. Falls back to the first entry if no
    dialect-specific match; falls back to the `fallback` string if empty.
    """
    if not expression:
        return fallback

    def _read_entry(e: dict[str, Any]) -> str | None:
        return e.get("expression") or e.get("sql")

    target = (dialect or "").lower()

    # Spec-compliant: {"dialects": [...]}
    if isinstance(expression, dict) and "dialects" in expression:
        entries = expression.get("dialects") or []
        if target:
            for e in entries:
                if (e.get("dialect") or "").lower() == target:
                    return _read_entry(e) or fallback
        if entries:
            return _read_entry(entries[0]) or fallback
        return fallback

    # Legacy: list of {dialect, sql}
    if isinstance(expression, list):
        if target:
            for e in expression:
                if (e.get("dialect") or "").lower() == target:
                    return _read_entry(e) or fallback
        if expression:
            return _read_entry(expression[0]) or fallback

    return fallback


def get_custom_extension(custom_extensions: Any, vendor: str) -> dict[str, Any]:
    """Pull a vendor's extension payload out, returning a plain dict.

    Accepts both shapes:
    - Spec: `[{"vendor_name": "DATABRICKS", "data": "<JSON-string>"}]`
    - Legacy: `{"databricks": {...}}` (vendor-keyed map)

    Vendor match is case-insensitive. Returns `{}` if nothing matches.
    """
    if not custom_extensions:
        return {}
    target = vendor.lower()

    if isinstance(custom_extensions, list):
        for ext in custom_extensions:
            if (ext.get("vendor_name") or "").lower() == target:
                data = ext.get("data")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        return {"_raw": data}
                if isinstance(data, dict):
                    return data
                return {}
        return {}

    if isinstance(custom_extensions, dict):
        for k, v in custom_extensions.items():
            if k.lower() == target:
                return v or {}
        return {}

    return {}


def list_extension_vendors(custom_extensions: Any) -> list[str]:
    """List vendor names present in either shape, lowercased."""
    if not custom_extensions:
        return []
    if isinstance(custom_extensions, list):
        return [
            (ext.get("vendor_name") or "").lower()
            for ext in custom_extensions
            if ext.get("vendor_name")
        ]
    if isinstance(custom_extensions, dict):
        return [k.lower() for k in custom_extensions.keys()]
    return []


def get_ai_context(obj: dict[str, Any]) -> dict[str, Any]:
    """Return AIContext as a dict regardless of which JSON-schema form was used.

    Per the OSI JSON schema, AIContext is `oneOf: [string, object]`. The string
    form maps to `{"instructions": <string>}` here so downstream consumers can
    use one shape uniformly.
    """
    ctx = obj.get("ai_context")
    if isinstance(ctx, str):
        return {"instructions": ctx}
    return ctx or {}


_FILTER_COLUMN_ALIASES = ("column", "dimension", "field", "name", "key")
_FILTER_VALUE_ALIASES = ("value", "val", "values")


def _filter_column(f: dict[str, Any]) -> Any:
    """Pull the column name out of a filter dict, accepting common aliases."""
    for k in _FILTER_COLUMN_ALIASES:
        if k in f and f[k] is not None:
            return f[k]
    return None


def _filter_value(f: dict[str, Any]) -> Any:
    for k in _FILTER_VALUE_ALIASES:
        if k in f:
            return f[k]
    raise KeyError(f"filter has no value field; expected one of {_FILTER_VALUE_ALIASES}: {f!r}")


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
        col = _filter_column(f)
        if col not in valid_dims:
            raise ValueError(f"Unknown filter column '{col}'. Valid: {sorted(valid_dims)}")


def render_filter(f: dict[str, Any]) -> str:
    """Render a SQL WHERE clause from {column, op, value}. Shared across SQL adapters.

    `column` can also be given as `dimension`, `field`, `name`, or `key`;
    `value` accepts `val` / `values`. Lists become an IN(...) clause.
    """
    col = _filter_column(f)
    op = (f.get("op") or f.get("operator") or "=").strip()
    val = _filter_value(f)

    def _lit(v: Any) -> str:
        return f"'{v}'" if isinstance(v, str) else str(v)

    if isinstance(val, (list, tuple)):
        rendered = "(" + ", ".join(_lit(v) for v in val) + ")"
        if op == "=":
            op = "IN"
        return f"{col} {op} {rendered}"
    return f"{col} {op} {_lit(val)}"
