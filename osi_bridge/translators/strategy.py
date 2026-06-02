"""Strategy Mosaic adapter — renders a Mosaic REST `report` payload.

Strategy (formerly MicroStrategy) exposes metrics through Mosaic as named
report objects. Unlike Databricks or Dremio, this adapter does not emit SQL:
it produces a JSON body the Mosaic REST API consumes directly and Mosaic
plans the SQL on its side.

The mapping from OSI to Mosaic is deliberately simple for the hackathon:
metric and dimension names go through as-is on the assumption that the OSI
metric/dimension names match the Mosaic metric/attribute object names. Phase
3 of the customer's real integration will likely add a per-name override
table under `custom_extensions.strategy.metric_id_map`.

Execute requires STRATEGY_BASE_URL and STRATEGY_TOKEN; missing creds returns
the rendered body with `metadata.executable=False`.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from osi_bridge.translators._common import (
    RenderedQuery,
    get_custom_extension,
    time_column,
    validate,
)


ENGINE_NAME = "strategy"


def build_query(
    osi_model: dict[str, Any],
    metrics: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    time_grain: str | None = None,
    limit: int = 1000,
) -> RenderedQuery:
    sm = osi_model["semantic_model"][0]
    ext = get_custom_extension(sm.get("custom_extensions"), "strategy")
    metric_set_id = ext.get("metric_set_id") or ext.get("project_id")
    if not metric_set_id:
        raise ValueError(
            "OSI model has no custom_extensions[vendor_name=strategy].metric_set_id — set it to "
            "the Mosaic metric set / project identifier before routing to Strategy."
        )

    validate(sm, metrics, dimensions, filters)

    id_map = ext.get("metric_id_map") or {}
    attr_map = ext.get("attribute_id_map") or {}

    dims_out: list[dict[str, Any]] = []
    if time_grain:
        tcol = time_column(sm)
        if tcol is None:
            raise ValueError(
                f"time_grain={time_grain!r} requested but no dimension has "
                "`dimension.is_time: true` in this OSI model."
            )
        dims_out.append(
            {"id": attr_map.get(tcol, tcol), "name": tcol, "time_grain": time_grain}
        )
    for d in dimensions or []:
        dims_out.append({"id": attr_map.get(d, d), "name": d})

    body = {
        "metric_set_id": metric_set_id,
        "metrics": [{"id": id_map.get(m, m), "name": m} for m in metrics],
        "dimensions": dims_out,
        "filters": list(filters or []),
        "limit": int(limit),
    }

    return RenderedQuery(
        engine=ENGINE_NAME,
        kind="rest",
        payload=body,
        fqn=str(metric_set_id),
        metadata={"executable": _has_creds()},
    )


def _has_creds() -> bool:
    return bool(os.environ.get("STRATEGY_BASE_URL") and os.environ.get("STRATEGY_TOKEN"))


def execute(rendered: RenderedQuery) -> list[dict[str, Any]]:
    if rendered.kind != "rest":
        raise ValueError(f"Strategy adapter only executes REST, got kind={rendered.kind}")
    if not _has_creds():
        raise RuntimeError(
            "Strategy execute requires STRATEGY_BASE_URL and STRATEGY_TOKEN env vars. "
            f"Rendered body was: {json.dumps(rendered.payload)[:300]}…"
        )
    base = os.environ["STRATEGY_BASE_URL"].rstrip("/")
    token = os.environ["STRATEGY_TOKEN"]

    req = urllib.request.Request(
        f"{base}/api/v1/cubes/{urllib.request.quote(rendered.fqn)}/report",
        method="POST",
        data=json.dumps(rendered.payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())

    cols = [c["name"] for c in result.get("columns", [])]
    return [dict(zip(cols, row)) for row in result.get("rows", [])]
