"""OSI v1.0 YAML → Databricks Unity Catalog Metric View.

Inverse of `osi_bridge.exporter.db_to_osi`: given an OSI semantic model,
emit the Databricks Metric View YAML (version 0.1) and CREATE OR REPLACE
VIEW … WITH METRICS … AS $$<yaml>$$ against the SQL warehouse.

OSI carries strictly more metadata than the MV (synonyms, display names,
descriptions live in `ai_context`). Those fields aren't part of the MV
YAML schema and so are dropped on import — they remain in the OSI
contract / Mongo catalog as the source of truth.
"""
from __future__ import annotations

import os
from typing import Any

import yaml
from databricks import sql


def osi_to_mv_yaml(osi: dict[str, Any]) -> str:
    """Render an OSI dict as a Databricks Metric View YAML string."""
    sm = osi["semantic_model"][0]
    datasets = sm.get("datasets") or []
    if not datasets:
        raise ValueError("OSI model has no datasets")
    ds = datasets[0]

    def _sql(expression: list[dict[str, Any]] | None, field_name: str) -> str:
        expression = expression or []
        # Prefer Databricks dialect; fall back to the first.
        for e in expression:
            if (e.get("dialect") or "").lower() == "databricks":
                return e["sql"]
        if expression:
            return expression[0]["sql"]
        raise ValueError(f"No SQL expression on '{field_name}'")

    dimensions = [
        {"name": f["name"], "expr": _sql(f.get("expression"), f["name"])}
        for f in (ds.get("fields") or [])
    ]
    measures = [
        {"name": m["name"], "expr": _sql(m.get("expression"), m["name"])}
        for m in (sm.get("metrics") or [])
    ]

    mv: dict[str, Any] = {
        "version": 0.1,
        "source": ds["source"],
        "dimensions": dimensions,
        "measures": measures,
    }
    return yaml.safe_dump(mv, sort_keys=False)


def _connect():
    host = os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    return sql.connect(server_hostname=host, http_path=http_path, access_token=token)


def create_metric_view(
    target_fqn: str,
    mv_yaml: str,
    *,
    comment: str | None = None,
    or_replace: bool = True,
) -> None:
    """Run CREATE [OR REPLACE] VIEW <fqn> WITH METRICS LANGUAGE YAML on the warehouse."""
    if "$$" in mv_yaml:
        raise ValueError("MV YAML contains '$$' which would break the dollar-quoted body")
    keyword = "CREATE OR REPLACE VIEW" if or_replace else "CREATE VIEW"
    comment_clause = f"  COMMENT '{comment.replace(chr(39), chr(39)*2)}'\n" if comment else ""
    ddl = (
        f"{keyword} {target_fqn}\n"
        "  WITH METRICS\n"
        "  LANGUAGE YAML\n"
        f"{comment_clause}"
        f"AS $$\n{mv_yaml}\n$$"
    )
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


def import_osi(
    osi: dict[str, Any],
    *,
    target_catalog: str,
    target_schema: str,
    target_name: str | None = None,
    or_replace: bool = True,
) -> dict[str, Any]:
    """End-to-end: OSI dict → Databricks Metric View in UC.

    `target_name` defaults to the OSI semantic_model[0].name so a round-trip
    export+import lands on the same name. The full FQN is
    `<target_catalog>.<target_schema>.<target_name>`.
    """
    name = target_name or osi["semantic_model"][0]["name"]
    target_fqn = f"{target_catalog}.{target_schema}.{name}"
    mv_yaml = osi_to_mv_yaml(osi)
    description = osi["semantic_model"][0].get("description")
    create_metric_view(target_fqn, mv_yaml, comment=description, or_replace=or_replace)
    return {"target_fqn": target_fqn, "mv_yaml": mv_yaml}
