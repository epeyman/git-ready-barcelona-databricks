"""Translate an OSI metric request into Databricks SQL using MEASURE()."""
from __future__ import annotations

from typing import Any


def _time_column(sm: dict[str, Any]) -> str | None:
    """Return the first dimension flagged `dimension.is_time: true`, or None."""
    for f in sm["datasets"][0]["fields"]:
        if (f.get("dimension") or {}).get("is_time"):
            return f["name"]
    return None


def build_sql(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> str:
    sm = osi_model["semantic_model"][0]
    fqn = sm["custom_extensions"]["databricks"]["metric_view_fqn"]

    valid_metrics = {m["name"] for m in sm["metrics"]}
    valid_dims = {f["name"] for f in sm["datasets"][0]["fields"]}

    for m in metrics:
        if m not in valid_metrics:
            raise ValueError(f"Unknown metric '{m}'. Valid: {sorted(valid_metrics)}")
    for d in dimensions or []:
        if d not in valid_dims:
            raise ValueError(f"Unknown dimension '{d}'. Valid: {sorted(valid_dims)}")

    select_parts = [f"MEASURE({m}) AS {m}" for m in metrics]
    group_dims: list[str] = []

    if time_grain:
        time_col = _time_column(sm)
        if time_col is None:
            raise ValueError(
                f"time_grain='{time_grain}' requested but no dimension has "
                "`dimension.is_time: true` in this OSI model."
            )
        select_parts.append(f"DATE_TRUNC('{time_grain}', {time_col}) AS time_bucket")
        group_dims.append("time_bucket")

    for d in dimensions or []:
        select_parts.append(d)
        group_dims.append(d)

    sql = f"SELECT {', '.join(select_parts)}\nFROM {fqn}"

    where = []
    for f in filters or []:
        col, op, val = f["column"], f.get("op", "="), f["value"]
        if col not in valid_dims:
            raise ValueError(f"Unknown filter column '{col}'")
        rendered = f"'{val}'" if isinstance(val, str) else str(val)
        where.append(f"{col} {op} {rendered}")
    if where:
        sql += "\nWHERE " + " AND ".join(where)

    if group_dims:
        sql += "\nGROUP BY " + ", ".join(group_dims)
        sql += "\nORDER BY " + ", ".join(group_dims)

    sql += f"\nLIMIT {int(limit)}"
    return sql
