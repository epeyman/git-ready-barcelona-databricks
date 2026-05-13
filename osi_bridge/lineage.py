"""Lineage view for an OSI model.

Combines two signals:

  - Engine-side lineage from `system.access.table_lineage` (Databricks UC).
    Returns the immediate upstream and downstream FQNs of the model's
    source table, deduped and ordered by most-recent event.
  - Contract-side version history from the model store's `history()` —
    every ingestion in `osi_model_versions` is one revision.

If the warehouse is unreachable or DATABRICKS_* env vars are missing, the
upstream/downstream lists fall back to a small synthetic projection so the
demo still renders something meaningful.
"""
from __future__ import annotations

import os
from typing import Any


_LINEAGE_SQL = """
SELECT
    source_table_full_name,
    target_table_full_name,
    MAX(event_time) AS last_seen
FROM system.access.table_lineage
WHERE source_table_full_name = '{fqn}' OR target_table_full_name = '{fqn}'
GROUP BY source_table_full_name, target_table_full_name
ORDER BY last_seen DESC
LIMIT 100
"""


def get_lineage(store: Any, model_name: str, *, max_rows: int = 25) -> dict[str, Any]:
    osi = store.get(model_name)
    sm = osi["semantic_model"][0]
    source_fqn = (sm.get("datasets") or [{}])[0].get("source") or ""
    fqn = (sm.get("custom_extensions") or {}).get("databricks", {}).get("metric_view_fqn") or source_fqn

    upstream, downstream, mode = _lineage_rows(fqn, max_rows=max_rows)
    versions: list[dict[str, Any]] = []
    if hasattr(store, "history"):
        try:
            versions = store.history(model_name)
        except Exception:
            versions = []

    return {
        "model": model_name,
        "fqn": fqn,
        "source": source_fqn,
        "mode": mode,  # 'live' | 'synthetic'
        "upstream": upstream,
        "downstream": downstream,
        "versions": versions,
    }


def _lineage_rows(fqn: str, *, max_rows: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if not (os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_HTTP_PATH") and os.environ.get("DATABRICKS_TOKEN")):
        return _synthetic(fqn) + ("synthetic",)

    try:
        from databricks import sql as dbsql

        host = os.environ["DATABRICKS_HOST"].replace("https://", "")
        http_path = os.environ["DATABRICKS_HTTP_PATH"]
        token = os.environ["DATABRICKS_TOKEN"]
        with dbsql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
            with c.cursor() as cur:
                cur.execute(_LINEAGE_SQL.format(fqn=fqn))
                rows = cur.fetchall()
    except Exception:
        return _synthetic(fqn) + ("synthetic",)

    upstream: list[dict[str, Any]] = []
    downstream: list[dict[str, Any]] = []
    seen_up: set[str] = set()
    seen_down: set[str] = set()
    for src, tgt, last in rows:
        if tgt == fqn and src and src not in seen_up:
            seen_up.add(src)
            upstream.append({"fqn": src, "last_seen": last.isoformat() if last else None})
        elif src == fqn and tgt and tgt not in seen_down:
            seen_down.add(tgt)
            downstream.append({"fqn": tgt, "last_seen": last.isoformat() if last else None})
        if len(upstream) >= max_rows and len(downstream) >= max_rows:
            break

    return upstream[:max_rows], downstream[:max_rows], "live"


def _synthetic(fqn: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plausible-but-fake lineage for offline demos.

    For a Metric View we conjure one upstream raw table (replacing `_mv`),
    and a couple of plausible downstream consumers (a dashboard table and
    a serving table). The labels make it obvious to a reviewer that this
    is the demo path, not real UC lineage.
    """
    if not fqn:
        return [], []
    base = fqn.split(".")[-1]
    if base.endswith("_mv"):
        upstream = [{"fqn": fqn.replace("_mv", "_raw"), "last_seen": None, "_synthetic": True}]
    else:
        upstream = [{"fqn": f"{fqn}_raw", "last_seen": None, "_synthetic": True}]
    downstream = [
        {"fqn": f"reporting.dash.{base}_kpis", "last_seen": None, "_synthetic": True},
        {"fqn": f"serving.api.{base}", "last_seen": None, "_synthetic": True},
    ]
    return upstream, downstream
