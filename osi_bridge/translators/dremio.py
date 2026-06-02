"""Dremio adapter — inlines metric and dimension expressions into Dremio SQL
and executes via the Dremio v3 REST `sql` endpoint.

Dremio does not have a `MEASURE()` primitive. The adapter walks the OSI
`metrics[].expression[].sql` and `datasets[0].fields[].expression[].sql`
entries, preferring `dialect: Dremio` when present and falling back to the
first available expression otherwise.

REST flow: POST /api/v3/sql with `{"sql": "..."}` returns a job id, then poll
/api/v3/job/{id}/results until the job completes. The adapter implements both
the build and the (optional) execute. Execute requires DREMIO_BASE_URL and
DREMIO_TOKEN env vars; if either is missing it returns the rendered query
with `metadata.executable=False` so the portal can still demo the contract.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from osi_bridge.translators._common import (
    RenderedQuery,
    dim_expression,
    get_custom_extension,
    metric_expression,
    render_filter,
    time_column,
    validate,
)


ENGINE_NAME = "dremio"


def build_query(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> RenderedQuery:
    sm = osi_model["semantic_model"][0]
    ext = get_custom_extension(sm.get("custom_extensions"), "dremio")
    table = ext.get("table") or ext.get("dataset")
    if not table:
        raise ValueError(
            "OSI model has no custom_extensions[vendor_name=dremio].table — set it to the Dremio "
            "dataset path (e.g. prod.sales.orders) before pointing the dispatcher here."
        )

    validate(sm, metrics, dimensions, filters)

    select_parts: list[str] = []
    for m in metrics:
        expr = metric_expression(sm, m, dialect="Dremio")
        select_parts.append(f"{expr} AS {m}")

    group_dims: list[str] = []
    if time_grain:
        tcol = time_column(sm)
        if tcol is None:
            raise ValueError(
                f"time_grain={time_grain!r} requested but no dimension has "
                "`dimension.is_time: true` in this OSI model."
            )
        tcol_expr = dim_expression(sm, tcol, dialect="Dremio")
        select_parts.append(f"DATE_TRUNC('{time_grain}', {tcol_expr}) AS time_bucket")
        group_dims.append("time_bucket")
    for d in dimensions or []:
        dexpr = dim_expression(sm, d, dialect="Dremio")
        select_parts.append(f"{dexpr} AS {d}")
        group_dims.append(d)

    sql_text = f"SELECT {', '.join(select_parts)}\nFROM {table}"
    if filters:
        sql_text += "\nWHERE " + " AND ".join(render_filter(f) for f in filters)
    if group_dims:
        sql_text += "\nGROUP BY " + ", ".join(group_dims)
        sql_text += "\nORDER BY " + ", ".join(group_dims)
    sql_text += f"\nLIMIT {int(limit)}"

    return RenderedQuery(
        engine=ENGINE_NAME,
        kind="sql",
        payload=sql_text,
        fqn=table,
        metadata={"executable": _has_creds()},
    )


def _has_creds() -> bool:
    return bool(os.environ.get("DREMIO_BASE_URL") and os.environ.get("DREMIO_TOKEN"))


def execute(rendered: RenderedQuery) -> list[dict[str, Any]]:
    if rendered.kind != "sql":
        raise ValueError(f"Dremio adapter only executes SQL, got kind={rendered.kind}")
    if not _has_creds():
        raise RuntimeError(
            "Dremio execute requires DREMIO_BASE_URL and DREMIO_TOKEN env vars. "
            f"Rendered SQL was: {rendered.payload}"
        )
    base = os.environ["DREMIO_BASE_URL"].rstrip("/")
    token = os.environ["DREMIO_TOKEN"]

    def _req(path: str, *, method: str = "GET", body: Any = None) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{base}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    job = _req("/api/v3/sql", method="POST", body={"sql": rendered.payload})
    job_id = job["id"]

    # Poll up to ~30s for the job to complete
    for _ in range(30):
        status = _req(f"/api/v3/job/{urllib.parse.quote(job_id)}")
        state = status.get("jobState")
        if state == "COMPLETED":
            break
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Dremio job {job_id} {state}: {status.get('errorMessage', '')}")
        time.sleep(1)
    else:
        raise TimeoutError(f"Dremio job {job_id} did not complete within 30s")

    results = _req(f"/api/v3/job/{urllib.parse.quote(job_id)}/results")
    cols = [c["name"] for c in results.get("schema", [])]
    return [dict(zip(cols, row)) for row in results.get("rows", [])]
