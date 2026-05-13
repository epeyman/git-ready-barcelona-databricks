"""Turn a raw column list into a canonical OSI dict + matching ODCS dict.

Used by the producer journey's second step. Calls Databricks-hosted Gemini
with the column list and asks for synonyms, display names, descriptions,
and suggested metric definitions. The dry-run path falls back to
deterministic heuristics so the producer UI demo runs offline.
"""
from __future__ import annotations

import json
import os
from typing import Any


NUMERIC_TYPES = (
    "int", "bigint", "smallint", "tinyint",
    "double", "float", "decimal", "numeric",
)
TIME_TYPES = ("date", "timestamp", "timestamp_ntz")


def infer(
    fqn: str,
    columns: list[dict[str, Any]],
    *,
    domain: str,
    owner: str,
    description: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Return `{osi, odcs, metrics_summary, ai_used}`.

    On `dry_run=True` (or when Gemini credentials are absent), the
    enrichment is heuristic — every numeric column gains a SUM/AVG metric,
    every column gets a sentence-cased display name and one or two
    synonyms derived from the column name.
    """
    use_ai = not dry_run and bool(os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"))
    enriched = _ai_enrich(fqn, columns, domain, owner) if use_ai else _heuristic_enrich(columns)
    osi = _build_osi(fqn, domain, owner, description, enriched)
    odcs = _build_odcs(fqn, domain, owner, description, enriched)
    return {
        "osi": osi,
        "odcs": odcs,
        "ai_used": use_ai,
        "metrics_summary": [m["name"] for m in osi["semantic_model"][0]["metrics"]],
    }


# ---------- Heuristic path (offline) ----------


def _heuristic_enrich(columns: list[dict[str, Any]]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for col in columns:
        name = col["name"]
        ctype = (col.get("type") or "string").lower()
        is_time = any(t in ctype for t in TIME_TYPES) or name.endswith("_at") or name.endswith("_date")
        fields.append({
            "name": name,
            "display_name": _to_display(name),
            "description": col.get("comment") or f"{_to_display(name)} column",
            "synonyms": _synonyms_for(name),
            "is_time": is_time,
            "sql_expression": name,
        })
        if any(t in ctype for t in NUMERIC_TYPES) and not name.endswith("_id"):
            metrics.append({
                "name": f"total_{name}",
                "display_name": f"Total {_to_display(name)}",
                "description": f"Sum of {name} across rows",
                "synonyms": [f"total {name}", _to_display(name).lower()],
                "expression": f"SUM({name})",
            })
            metrics.append({
                "name": f"avg_{name}",
                "display_name": f"Average {_to_display(name)}",
                "description": f"Mean of {name} across rows",
                "synonyms": [f"average {name}", "mean"],
                "expression": f"AVG({name})",
            })
    # Always include a row count
    metrics.insert(0, {
        "name": "row_count",
        "display_name": "Row Count",
        "description": "Number of rows",
        "synonyms": ["count", "rows", "volume"],
        "expression": "COUNT(*)",
    })
    return {"fields": fields, "metrics": metrics}


def _to_display(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace("_", " ").split())


def _synonyms_for(name: str) -> list[str]:
    base = name.replace("_", " ")
    out = [base]
    if name.endswith("_id"):
        out.append(name[:-3].replace("_", " ") + " identifier")
    elif name.endswith("_at"):
        out.append(name[:-3].replace("_", " ") + " time")
    elif name.endswith("_date"):
        out.append("date")
    return out


# ---------- AI path ----------


_SYSTEM = (
    "You are the OSI Bridge contract-generator. Given a UC table FQN and its "
    "column list, produce a JSON object with two keys: `fields` and `metrics`. "
    "Each field has name, display_name, description (1 sentence), synonyms "
    "(2-4 plain-language alternatives), is_time (bool), sql_expression (the "
    "column reference; use CAST(... AS DATE) for derived date dimensions). "
    "Each metric has name (snake_case), display_name, description, synonyms, "
    "and expression (a SQL aggregate using ONLY the columns provided). Always "
    "include a row_count metric. Do not invent columns that are not in the "
    "input list. Return only the JSON object, no prose."
)


def _ai_enrich(
    fqn: str, columns: list[dict[str, Any]], domain: str, owner: str
) -> dict[str, Any]:
    from openai import OpenAI

    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    model = os.environ.get("GEMINI_MODEL", "databricks-gemini-2-5-flash")
    client = OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")

    cols_summary = "\n".join(f"- {c['name']}: {c.get('type', 'string')} — {c.get('comment', '')}" for c in columns)
    user = f"FQN: {fqn}\nDomain: {domain}\nOwner: {owner}\n\nColumns:\n{cols_summary}"

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _heuristic_enrich(columns)
    # Coerce any missing fields back to safe defaults
    fields = parsed.get("fields") or []
    metrics = parsed.get("metrics") or []
    valid_cols = {c["name"] for c in columns}
    fields = [f for f in fields if f.get("name") in valid_cols]
    return {"fields": fields, "metrics": metrics}


# ---------- OSI / ODCS assembly ----------


def _build_osi(fqn: str, domain: str, owner: str, description: str, enriched: dict[str, Any]) -> dict[str, Any]:
    short = fqn.split(".")[-1]
    name = f"{short}_mv"
    return {
        "version": "1.0",
        "semantic_model": [{
            "name": name,
            "description": description or f"Auto-generated semantic model for {fqn}.",
            "ai_context": {
                "instructions": (
                    f"Auto-generated by the OSI Bridge producer journey from {fqn}. "
                    "Review synonyms and metric definitions before publishing."
                )
            },
            "datasets": [{
                "name": name,
                "source": fqn,
                "fields": [
                    {
                        "name": f["name"],
                        "description": f.get("description") or f["name"],
                        "expression": [{"dialect": "Databricks", "sql": f.get("sql_expression") or f["name"]}],
                        "dimension": {"is_time": bool(f.get("is_time"))},
                        "ai_context": {
                            "synonyms": list(f.get("synonyms") or []),
                            "display_name": f.get("display_name") or f["name"],
                        },
                    }
                    for f in enriched["fields"]
                ],
            }],
            "metrics": [
                {
                    "name": m["name"],
                    "description": m.get("description") or m["name"],
                    "expression": [{"dialect": "Databricks", "sql": m.get("expression") or "COUNT(*)"}],
                    "ai_context": {
                        "synonyms": list(m.get("synonyms") or []),
                        "display_name": m.get("display_name") or m["name"],
                    },
                }
                for m in enriched["metrics"]
            ],
            "custom_extensions": {
                "databricks": {
                    "metric_view_fqn": _build_mv_fqn(fqn, name),
                    "query_pattern": (
                        "SELECT MEASURE(<metric>), <dims> FROM <fqn> "
                        "WHERE <filters> GROUP BY <dims>"
                    ),
                },
                "odcs": {
                    "id": f"{short}-v1",
                    "version": "1.0.0",
                    "domain": domain,
                    "data_product": short,
                    "owner": owner,
                },
            },
        }],
    }


def _build_mv_fqn(source_fqn: str, mv_name: str) -> str:
    parts = source_fqn.split(".")
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}.{mv_name}"
    return f"main.osi_demo.{mv_name}"


def _build_odcs(fqn: str, domain: str, owner: str, description: str, enriched: dict[str, Any]) -> dict[str, Any]:
    short = fqn.split(".")[-1]
    parts = fqn.split(".")
    catalog = parts[0] if len(parts) >= 1 else "main"
    schema = parts[1] if len(parts) >= 2 else "default"
    return {
        "apiVersion": "v3.0.0",
        "kind": "DataContract",
        "id": f"{short}-v1",
        "status": "active",
        "name": short.replace("_", " ").title(),
        "version": "1.0.0",
        "domain": domain,
        "dataProduct": short,
        "description": {
            "purpose": description or f"Auto-generated contract for {fqn}.",
            "usage": "Auto-generated by the OSI Bridge producer journey; review before publishing.",
        },
        "servers": [{
            "server": "production",
            "type": "databricks",
            "catalog": catalog,
            "schema": schema,
            "path": parts[-1],
        }],
        "schema": [{
            "name": short,
            "physicalName": f"{short}_mv",
            "description": description or f"Schema for {fqn}.",
            "properties": [
                {
                    "name": f["name"],
                    "logicalType": _logical_type(f),
                    "physicalType": "STRING",
                    "description": f.get("description") or f["name"],
                    "customProperties": [
                        {"property": "display_name", "value": f.get("display_name") or f["name"]},
                        {"property": "ai_synonyms", "value": list(f.get("synonyms") or [])},
                        {"property": "sql_expression", "value": f.get("sql_expression") or f["name"]},
                        {"property": "is_time", "value": bool(f.get("is_time"))},
                    ],
                }
                for f in enriched["fields"]
            ],
        }],
        "team": [{"role": "owner", "username": owner}],
        "support": [],
    }


def _logical_type(field: dict[str, Any]) -> str:
    if field.get("is_time"):
        return "date"
    return "string"
