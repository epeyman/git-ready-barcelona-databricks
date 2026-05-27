"""Workspace-wide Metric View discovery.

The portal's sync feature uses this to enumerate every Metric View the SQL
warehouse can see, then hands each FQN to `osi_bridge.exporter` for OSI
translation.

The discovery query uses `system.information_schema.tables`, which spans
every catalog in the metastore. Metric Views surface there with
`table_type = 'METRIC_VIEW'`. Older runtimes that don't carry the
METRIC_VIEW table_type fall through the secondary path: list views and
let the exporter raise on non-MVs (the caller treats those as failures).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from databricks import sql


@dataclass(frozen=True)
class MetricViewRef:
    catalog: str
    schema: str
    name: str

    @property
    def fqn(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.name}"


def _connect():
    host = os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    return sql.connect(server_hostname=host, http_path=http_path, access_token=token)


def list_metric_views(
    *,
    catalogs: Iterable[str] | None = None,
    schemas: Iterable[str] | None = None,
) -> list[MetricViewRef]:
    """Return every Metric View the warehouse can see, optionally filtered.

    `catalogs` / `schemas` are inclusive whitelists. Passing neither scans
    the whole metastore via `system.information_schema.tables`.
    """
    where = ["table_type = 'METRIC_VIEW'"]
    if catalogs:
        joined = ", ".join(f"'{c}'" for c in catalogs)
        where.append(f"table_catalog IN ({joined})")
    if schemas:
        joined = ", ".join(f"'{s}'" for s in schemas)
        where.append(f"table_schema IN ({joined})")

    query = (
        "SELECT table_catalog, table_schema, table_name "
        "FROM system.information_schema.tables "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY table_catalog, table_schema, table_name"
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    return [MetricViewRef(catalog=r[0], schema=r[1], name=r[2]) for r in rows]
