"""Databricks Metric View → OSI v1.0 YAML.

In the current Databricks Metric View YAML schema, columns/measures support
only `name`, `expr`, `window`. Richer annotations (synonyms, display names,
descriptions) live in a companion file (`agent_metadata.yaml`) that this
exporter merges at write time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from databricks import sql

METADATA_DIR = Path(__file__).parent / "metadata"


def _default_metadata_for(fqn: str) -> Path | None:
    """Look up `osi_bridge/metadata/<view_name>.yaml` based on the FQN's last part."""
    view = fqn.split(".")[-1]
    # Strip a trailing `_mv` so metric_view `orders_mv` maps to `orders.yaml`.
    stem = view[:-3] if view.endswith("_mv") else view
    candidates = [METADATA_DIR / f"{view}.yaml", METADATA_DIR / f"{stem}.yaml"]
    for c in candidates:
        if c.exists():
            return c
    return None


def fetch_metric_view_yaml(fqn: str) -> dict[str, Any]:
    host = os.environ["DATABRICKS_HOST"].replace("https://", "").rstrip("/")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]

    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DESCRIBE TABLE EXTENDED {fqn} AS JSON")
            rows = cur.fetchall()

    payload = json.loads(rows[0][0])
    view_text = payload.get("view_text") or payload.get("View Text")
    if not view_text:
        raise RuntimeError(f"No view_text in DESCRIBE result for {fqn}")
    return yaml.safe_load(view_text)


def db_to_osi(mv: dict[str, Any], fqn: str, agent_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    name = fqn.split(".")[-1]
    am = agent_meta or {"dimensions": {}, "metrics": {}}

    def dim_block(d: dict[str, Any]) -> dict[str, Any]:
        meta = am.get("dimensions", {}).get(d["name"], {})
        return {
            "name": d["name"],
            "description": meta.get("description", d["name"]),
            "expression": [{"dialect": "Databricks", "sql": d["expr"]}],
            "dimension": {"is_time": meta.get("is_time", False)},
            "ai_context": {
                "synonyms": meta.get("synonyms", []),
                "display_name": meta.get("display_name", d["name"]),
            },
        }

    def metric_block(m: dict[str, Any]) -> dict[str, Any]:
        meta = am.get("metrics", {}).get(m["name"], {})
        return {
            "name": m["name"],
            "description": meta.get("description", m["name"]),
            "expression": [{"dialect": "Databricks", "sql": m["expr"]}],
            "ai_context": {
                "synonyms": meta.get("synonyms", []),
                "display_name": meta.get("display_name", m["name"]),
            },
        }

    description = am.get("description") or mv.get("comment") or f"Semantic model for {name}"
    instructions = am.get("ai_instructions") or (
        f"Semantic model exported from Databricks Metric View {fqn}. "
        "Use the metrics defined here for any quantitative question against this dataset."
    )
    return {
        "version": "1.0",
        "semantic_model": [{
            "name": name,
            "description": description,
            "ai_context": {"instructions": instructions},
            "datasets": [{
                "name": name,
                "source": mv["source"],
                "fields": [dim_block(d) for d in mv.get("dimensions", [])],
            }],
            "metrics": [metric_block(m) for m in mv.get("measures", [])],
            "custom_extensions": {
                "databricks": {
                    "metric_view_fqn": fqn,
                    "query_pattern": (
                        "SELECT MEASURE(<metric>), <dims> FROM <fqn> "
                        "WHERE <filters> GROUP BY <dims>"
                    ),
                }
            },
        }],
    }


def export(fqn: str, output_path: str, metadata_path: str | None = None) -> None:
    mv = fetch_metric_view_yaml(fqn)
    am = None
    meta_file = Path(metadata_path) if metadata_path else _default_metadata_for(fqn)
    if meta_file and meta_file.exists():
        with open(meta_file) as f:
            am = yaml.safe_load(f)
        print(f"Using metadata from {meta_file}")
    else:
        print("No companion metadata file found — exporting without synonyms/display names.")
    osi = db_to_osi(mv, fqn, am)
    with open(output_path, "w") as f:
        yaml.safe_dump(osi, f, sort_keys=False)
    print(f"Exported {fqn} → {output_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--fqn", required=True, help="catalog.schema.metric_view")
    p.add_argument("--out", default="examples/model.osi.yaml")
    p.add_argument("--metadata", default=None, help="optional agent_metadata.yaml path")
    args = p.parse_args()
    export(args.fqn, args.out, args.metadata)
