"""Inspect a Unity Catalog table to retrieve its column list and types.

Used by the producer journey as the first step: turn an FQN the producer
typed into a structured list of `{name, type, comment, nullable}` rows
that the modeler can feed to Gemini.

Real path runs `DESCRIBE TABLE EXTENDED <fqn> AS JSON` against the SQL
warehouse identified by the standard DATABRICKS_* env vars. The dry-run
path returns a synthetic schema so the producer UI is demo-able without
a live workspace.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any


def describe_table(fqn: str, *, dry_run: bool = False) -> list[dict[str, Any]]:
    """Return the column list for a UC table FQN.

    Falls back to synthetic columns when `dry_run=True` or the required
    Databricks env vars are missing.
    """
    if dry_run or not (os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_HTTP_PATH") and os.environ.get("DATABRICKS_TOKEN")):
        return _synthetic_schema(fqn)

    from databricks import sql as dbsql

    host = os.environ["DATABRICKS_HOST"].replace("https://", "")
    http_path = os.environ["DATABRICKS_HTTP_PATH"]
    token = os.environ["DATABRICKS_TOKEN"]
    with dbsql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
        with c.cursor() as cur:
            cur.execute(f"DESCRIBE TABLE EXTENDED {fqn} AS JSON")
            rows = cur.fetchall()

    payload = json.loads(rows[0][0])
    cols = payload.get("columns") or payload.get("Columns") or []
    return [
        {
            "name": col.get("name") or col.get("Name"),
            "type": (col.get("type") or col.get("Type") or {}).get("name")
                     if isinstance(col.get("type") or col.get("Type"), dict)
                     else (col.get("type") or col.get("Type") or "string"),
            "nullable": col.get("nullable", True),
            "comment": col.get("comment") or col.get("Comment") or "",
        }
        for col in cols
    ]


def _synthetic_schema(fqn: str) -> list[dict[str, Any]]:
    """Heuristic synthetic schema seeded off the FQN's last segment.

    Common retail/loyalty shape so the demo produces a plausible OSI for
    table names like 'main.sales.transactions' or 'demo.loyalty.events'.
    """
    base = fqn.split(".")[-1]
    is_transactions = re.search(r"(transaction|order|sale|basket|tx)", base, re.IGNORECASE)
    is_events = re.search(r"(event|log|audit)", base, re.IGNORECASE)
    common: list[dict[str, Any]] = [
        {"name": f"{base.rstrip('s')}_id", "type": "string", "nullable": False,
         "comment": f"Primary key for {base}"},
        {"name": "created_at", "type": "timestamp", "nullable": False,
         "comment": "Record creation timestamp"},
        {"name": "country", "type": "string", "nullable": True,
         "comment": "Country code (DE, FR, ES, …)"},
        {"name": "store_id", "type": "string", "nullable": True,
         "comment": "Store identifier"},
    ]
    if is_transactions:
        common += [
            {"name": "amount", "type": "decimal(12,2)", "nullable": False,
             "comment": "Transaction amount"},
            {"name": "currency", "type": "string", "nullable": False, "comment": "ISO currency"},
            {"name": "customer_id", "type": "string", "nullable": True, "comment": "Customer identifier"},
            {"name": "payment_method", "type": "string", "nullable": True,
             "comment": "Payment method (cash, card, lidlpay)"},
        ]
    elif is_events:
        common += [
            {"name": "event_type", "type": "string", "nullable": False,
             "comment": "Type of event"},
            {"name": "actor_id", "type": "string", "nullable": True,
             "comment": "Actor that produced the event"},
        ]
    else:
        common += [
            {"name": "value", "type": "double", "nullable": True, "comment": "Generic numeric value"},
            {"name": "category", "type": "string", "nullable": True, "comment": "Generic category"},
        ]
    return common
