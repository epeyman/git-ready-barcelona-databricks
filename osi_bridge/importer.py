"""OSI YAML → Databricks Unity Catalog Metric View.

Inverse of `osi_bridge.exporter.db_to_osi`.

Accepts both shapes:

- **Spec-compliant** (validates against `core-spec/osi-schema.json`):
  `expression.dialects[*].{dialect, expression}` with uppercase
  `dialect: DATABRICKS`; `custom_extensions` as an array of
  `{vendor_name, data}` where `data` is a JSON-encoded string carrying
  Databricks-specific fields (filter, joins, materialization, window,
  mv version, mv FQN).

- **Legacy prototype shape** (the original `examples/models/*.osi.yaml`
  files): flat `expression: [{dialect: "Databricks", sql: ...}]` array,
  vendor-keyed `custom_extensions.{databricks: {...}}` map, dataset-level
  `filter`, mixed-case dialect. Read for backwards compatibility; not
  emitted by the current exporter.

Databricks-only fields that survive: `filter` (top-level), `joins`,
`materialization`, per-measure `window`, and the `version` field of
the native MV YAML.
"""
from __future__ import annotations

import json
import os
from typing import Any

import yaml
from databricks import sql

DATABRICKS_VENDOR_NAMES = {"databricks", "DATABRICKS"}


# ---------------------------------------------------------------------------
# Extraction helpers — read both spec-compliant and legacy shapes
# ---------------------------------------------------------------------------


def _extract_databricks_sql(expression: Any, field_name: str) -> str:
    """Pull the Databricks-dialect SQL out of an OSI `expression` block.

    Accepts both shapes:
    - Spec: `expression = {"dialects": [{"dialect": "DATABRICKS", "expression": "..."}]}`
    - Legacy: `expression = [{"dialect": "Databricks", "sql": "..."}]`

    Falls back to the first entry if no Databricks dialect is present.
    """
    if expression is None:
        raise ValueError(f"No SQL expression on '{field_name}'")

    # Spec-compliant shape: {"dialects": [...]}
    if isinstance(expression, dict) and "dialects" in expression:
        dialects = expression["dialects"] or []
        for e in dialects:
            if (e.get("dialect") or "").upper() == "DATABRICKS":
                return e["expression"]
        if dialects:
            return dialects[0]["expression"]
        raise ValueError(f"No SQL expression on '{field_name}'")

    # Legacy shape: flat list of {dialect, sql}
    if isinstance(expression, list):
        for e in expression:
            if (e.get("dialect") or "").lower() == "databricks":
                return e.get("sql") or e.get("expression")
        if expression:
            first = expression[0]
            return first.get("sql") or first.get("expression")
        raise ValueError(f"No SQL expression on '{field_name}'")

    raise ValueError(f"Unrecognized expression shape on '{field_name}': {type(expression).__name__}")


def _extract_databricks_extension(custom_extensions: Any) -> dict[str, Any]:
    """Pull Databricks-specific config out of an OSI custom_extensions block.

    Accepts both shapes:
    - Spec: `custom_extensions = [{"vendor_name": "DATABRICKS", "data": "<JSON>"}]`
    - Legacy: `custom_extensions = {"databricks": {...}}`

    Returns the parsed payload as a plain dict (empty if no Databricks entry).
    """
    if not custom_extensions:
        return {}

    # Spec-compliant shape: array of {vendor_name, data}
    if isinstance(custom_extensions, list):
        for ext in custom_extensions:
            if (ext.get("vendor_name") or "").upper() in {n.upper() for n in DATABRICKS_VENDOR_NAMES}:
                data = ext.get("data")
                if isinstance(data, str):
                    try:
                        return json.loads(data)
                    except json.JSONDecodeError:
                        return {"raw": data}
                if isinstance(data, dict):
                    return data
        return {}

    # Legacy shape: vendor-keyed map
    if isinstance(custom_extensions, dict):
        for vendor in DATABRICKS_VENDOR_NAMES:
            if vendor in custom_extensions:
                return custom_extensions[vendor] or {}
        return {}

    return {}


# ---------------------------------------------------------------------------
# OSI → Databricks Metric View YAML
# ---------------------------------------------------------------------------


def osi_to_mv_yaml(osi: dict[str, Any]) -> str:
    """Render an OSI document as a Databricks Metric View YAML string.

    Round-trips Databricks-only fields (filter, joins, materialization,
    per-measure window) that were stashed by the exporter in
    `custom_extensions` under `vendor_name: DATABRICKS`.
    """
    sm = osi["semantic_model"][0]
    datasets = sm.get("datasets") or []
    if not datasets:
        raise ValueError("OSI model has no datasets")
    ds = datasets[0]

    dimensions = [
        {"name": f["name"], "expr": _extract_databricks_sql(f.get("expression"), f["name"])}
        for f in (ds.get("fields") or [])
    ]

    measures: list[dict[str, Any]] = []
    for m in sm.get("metrics") or []:
        block: dict[str, Any] = {
            "name": m["name"],
            "expr": _extract_databricks_sql(m.get("expression"), m["name"]),
        }
        # Per-measure window comes from this metric's own custom_extensions.
        db_ext = _extract_databricks_extension(m.get("custom_extensions"))
        if db_ext.get("window"):
            block["window"] = db_ext["window"]
        measures.append(block)

    # Top-level Databricks-specific config: filter / joins / materialization /
    # mv version, sitting under semantic_model[0].custom_extensions or (legacy)
    # under datasets[0].filter (and similar liberties).
    db_payload = _extract_databricks_extension(sm.get("custom_extensions"))

    mv: dict[str, Any] = {
        "version": db_payload.get("version") or 1.1,
        "source": ds["source"],
    }

    # Legacy fallback — older OSI files put `filter` directly on the dataset.
    legacy_filter = ds.get("filter") or db_payload.get("filter")
    if legacy_filter:
        mv["filter"] = legacy_filter

    if db_payload.get("joins"):
        mv["joins"] = db_payload["joins"]

    mv["dimensions"] = dimensions
    mv["measures"] = measures

    if db_payload.get("materialization"):
        mv["materialization"] = db_payload["materialization"]

    return yaml.safe_dump(mv, sort_keys=False)


# ---------------------------------------------------------------------------
# DDL execution
# ---------------------------------------------------------------------------


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

    `target_name` defaults to the OSI `semantic_model[0].name` so a
    round-trip export+import lands on the same name. The full FQN is
    `<target_catalog>.<target_schema>.<target_name>`.
    """
    name = target_name or osi["semantic_model"][0]["name"]
    target_fqn = f"{target_catalog}.{target_schema}.{name}"
    mv_yaml = osi_to_mv_yaml(osi)
    description = osi["semantic_model"][0].get("description")
    create_metric_view(target_fqn, mv_yaml, comment=description, or_replace=or_replace)
    return {"target_fqn": target_fqn, "mv_yaml": mv_yaml}
