"""Databricks Metric View → OSI YAML (spec-compliant).

Produces OSI documents that validate against `core-spec/osi-schema.json`
from github.com/open-semantic-interchange/OSI:

- `version: "0.2.0.dev0"` (current OSI dev spec).
- Expressions nested as `expression.dialects[*].{dialect, expression}`
  with `dialect: DATABRICKS` (uppercase enum value).
- `custom_extensions` as an array of `{vendor_name, data}` where `data`
  is a JSON-encoded string carrying Databricks-specific fields that OSI
  core doesn't model yet (joins, filter, window measures, materialization,
  the source view FQN, the native MV YAML version).
- `ai_context` in its object form with `instructions` (model level) and
  `synonyms` (field/metric level) — these are the two AIContext sub-keys
  that have a defined home in the OSI JSON schema.
- No `display_name`, no dataset-level `filter`, no mixed-case dialect
  strings — those were prototype-era liberties.

Companion `osi_bridge/metadata/<view>.yaml` files merge in synonyms,
descriptions, and the `is_time` flag at export time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from databricks import sql

METADATA_DIR = Path(__file__).parent / "metadata"

OSI_VERSION = "0.2.0.dev0"
DATABRICKS_DIALECT = "DATABRICKS"


def _default_metadata_for(fqn: str) -> Path | None:
    """Look up `osi_bridge/metadata/<view_name>.yaml` based on the FQN's last part."""
    view = fqn.split(".")[-1]
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


def _expr(sql_text: str) -> dict[str, Any]:
    """Wrap a single Databricks SQL expression in the OSI expression shape."""
    return {"dialects": [{"dialect": DATABRICKS_DIALECT, "expression": sql_text}]}


def _ai_context(synonyms: list[str] | None, instructions: str | None = None) -> dict[str, Any] | None:
    """Build an AIContext object. Returns None if there's nothing to carry."""
    body: dict[str, Any] = {}
    if instructions:
        body["instructions"] = instructions
    if synonyms:
        body["synonyms"] = list(synonyms)
    return body or None


def db_to_osi(mv: dict[str, Any], fqn: str, agent_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate a parsed Databricks Metric View YAML into a spec-compliant OSI document."""
    name = fqn.split(".")[-1]
    am = agent_meta or {"dimensions": {}, "metrics": {}}

    def dim_block(d: dict[str, Any]) -> dict[str, Any]:
        meta = am.get("dimensions", {}).get(d["name"], {})
        out: dict[str, Any] = {
            "name": d["name"],
            "expression": _expr(d["expr"]),
            "description": meta.get("description") or d["name"],
            "dimension": {"is_time": bool(meta.get("is_time", False))},
        }
        ctx = _ai_context(meta.get("synonyms"))
        if ctx:
            out["ai_context"] = ctx
        return out

    def metric_block(m: dict[str, Any]) -> dict[str, Any]:
        meta = am.get("metrics", {}).get(m["name"], {})
        out: dict[str, Any] = {
            "name": m["name"],
            "expression": _expr(m["expr"]),
            "description": meta.get("description") or m["name"],
        }
        ctx = _ai_context(meta.get("synonyms"))
        if ctx:
            out["ai_context"] = ctx
        # Window measures aren't first-class in OSI core — carry as DATABRICKS extension.
        if m.get("window"):
            out["custom_extensions"] = [
                {
                    "vendor_name": DATABRICKS_DIALECT,
                    "data": json.dumps({"window": m["window"]}, separators=(",", ":")),
                }
            ]
        return out

    description = am.get("description") or mv.get("comment") or f"Semantic model for {name}"
    instructions = am.get("ai_instructions") or (
        f"Semantic model exported from Databricks Metric View {fqn}. "
        "Use the metrics defined here for any quantitative question against this dataset."
    )

    # Databricks-specific top-level config (filter, joins, materialization, mv FQN)
    # goes into a single custom_extensions entry, JSON-encoded.
    db_payload: dict[str, Any] = {
        "metric_view_fqn": fqn,
        "version": mv.get("version", "1.1"),
        "query_pattern": (
            "SELECT MEASURE(<metric>), <dims> FROM <fqn> WHERE <filters> GROUP BY <dims>"
        ),
    }
    for key in ("filter", "joins", "materialization"):
        if mv.get(key) is not None:
            db_payload[key] = mv[key]

    sm: dict[str, Any] = {
        "name": name,
        "description": description,
        "ai_context": {"instructions": instructions},
        "datasets": [
            {
                "name": name,
                "source": mv["source"],
                "fields": [dim_block(d) for d in mv.get("dimensions", [])],
            }
        ],
        "metrics": [metric_block(m) for m in mv.get("measures", [])],
        "custom_extensions": [
            {
                "vendor_name": DATABRICKS_DIALECT,
                "data": json.dumps(db_payload, separators=(",", ":")),
            }
        ],
    }

    return {
        "version": OSI_VERSION,
        "semantic_model": [sm],
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
