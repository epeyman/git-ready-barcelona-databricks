"""Databricks adapter — emits SQL using `MEASURE()` against a Unity Catalog
Metric View and executes it via databricks-sql-connector.

The MEASURE() pattern means the metric definition is owned by the Metric View
on the engine side, not duplicated in the OSI. The adapter only needs the
Metric View's FQN and the dimension/filter names.
"""
from __future__ import annotations

import os
from typing import Any

from databricks import sql

from osi_bridge.translators._common import RenderedQuery, render_filter, time_column, validate


ENGINE_NAME = "databricks"


def build_query(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> RenderedQuery:
    sm = osi_model["semantic_model"][0]
    ext = (sm.get("custom_extensions") or {}).get("databricks") or {}
    fqn = ext.get("metric_view_fqn")
    if not fqn:
        raise ValueError("OSI model has no custom_extensions.databricks.metric_view_fqn")

    validate(sm, metrics, dimensions, filters)

    select_parts = [f"MEASURE({m}) AS {m}" for m in metrics]
    group_dims: list[str] = []

    if time_grain:
        tcol = time_column(sm)
        if tcol is None:
            raise ValueError(
                f"time_grain={time_grain!r} requested but no dimension has "
                "`dimension.is_time: true` in this OSI model."
            )
        select_parts.append(f"DATE_TRUNC('{time_grain}', {tcol}) AS time_bucket")
        group_dims.append("time_bucket")

    for d in dimensions or []:
        select_parts.append(d)
        group_dims.append(d)

    sql_text = f"SELECT {', '.join(select_parts)}\nFROM {fqn}"
    if filters:
        sql_text += "\nWHERE " + " AND ".join(render_filter(f) for f in filters)
    if group_dims:
        sql_text += "\nGROUP BY " + ", ".join(group_dims)
        sql_text += "\nORDER BY " + ", ".join(group_dims)
    sql_text += f"\nLIMIT {int(limit)}"

    return RenderedQuery(engine=ENGINE_NAME, kind="sql", payload=sql_text, fqn=fqn)


# Phase-0 back-compat shim used by exporter/notebooks/tests that import
# `osi_bridge.translator.build_sql`.
def build_sql(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> str:
    return build_query(osi_model, metrics, dimensions, filters, time_grain, limit).payload


def execute(rendered: RenderedQuery) -> list[dict[str, Any]]:
    if rendered.kind != "sql":
        raise ValueError(f"Databricks adapter only executes SQL, got kind={rendered.kind}")
    host = os.environ["DATABRICKS_HOST"].replace("https://", "")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
        with c.cursor() as cur:
            cur.execute(rendered.payload)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
