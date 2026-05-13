"""Databricks Unity Catalog access provisioning.

Runs a `GRANT SELECT ON <fqn> TO `<principal>`` via the Databricks SQL
warehouse. UC's GRANT is idempotent — re-running on an already-granted
principal succeeds without complaint.

Requires DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN. If any is
missing the provider returns status='skipped' so the demo can still proceed
on the engines that *are* configured.
"""
from __future__ import annotations

import os
from typing import Any

from osi_bridge.provisioning._common import GrantResult, engine_fqn


ENGINE_NAME = "databricks"


def _creds() -> tuple[str, str, str] | None:
    host = os.environ.get("DATABRICKS_HOST")
    http_path = os.environ.get("DATABRICKS_HTTP_PATH")
    token = os.environ.get("DATABRICKS_TOKEN")
    if host and http_path and token:
        return host.replace("https://", ""), http_path, token
    return None


def grant(
    osi_model: dict[str, Any],
    requester: str,
    justification: str = "",
    *,
    dry_run: bool = False,
) -> GrantResult:
    fqn = engine_fqn(osi_model, ENGINE_NAME)
    if not fqn:
        return GrantResult(ENGINE_NAME, "skipped", "OSI has no custom_extensions.databricks block")

    creds = _creds()
    sql_text = f"GRANT SELECT ON TABLE {fqn} TO `{requester}`"

    if dry_run or creds is None:
        return GrantResult(
            ENGINE_NAME,
            "dry-run" if dry_run else "skipped",
            f"Would run: {sql_text}" if dry_run else
            f"Databricks credentials not set; would run: {sql_text}",
        )

    try:
        from databricks import sql as dbsql
    except ImportError as e:
        return GrantResult(ENGINE_NAME, "failed", f"databricks-sql-connector not installed: {e}")

    host, http_path, token = creds
    try:
        with dbsql.connect(server_hostname=host, http_path=http_path, access_token=token) as c:
            with c.cursor() as cur:
                cur.execute(sql_text)
        return GrantResult(ENGINE_NAME, "granted", f"Executed: {sql_text}")
    except Exception as e:  # surface UC error to the audit log
        return GrantResult(ENGINE_NAME, "failed", f"{type(e).__name__}: {e}")
