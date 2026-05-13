"""Databricks Lakebase / Postgres-backed model store.

Lakebase is Databricks-managed Postgres. The schema (see schema.sql) is
identical to vanilla Postgres, so this adapter works against any PG instance
the user points it at — Lakebase, RDS, a local docker container, anything.
Lakebase-specific connection minting is gated behind an optional helper
(`mint_lakebase_dsn`) so users who already have a DSN can skip it.

Dependencies:
  - psycopg[binary] >= 3.1 (optional — only required for this adapter)
  - databricks-sdk    (only required if you use mint_lakebase_dsn)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import tuple_row
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "psycopg is required for the Lakebase store. Install with "
        "`pip install 'psycopg[binary]>=3.1'`."
    ) from e


SCHEMA_FILE = Path(__file__).parent / "schema.sql"


class LakebaseModelStore:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or os.environ.get("OSI_BRIDGE_PG_DSN") or os.environ.get("PG_DSN")
        if not self._dsn:
            raise RuntimeError(
                "Lakebase store requires a Postgres DSN. Pass dsn=... or set "
                "$OSI_BRIDGE_PG_DSN (e.g. postgresql://user:pwd@host:5432/db)."
            )
        self._ensure_schema()

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, autocommit=True)

    def _ensure_schema(self) -> None:
        ddl = SCHEMA_FILE.read_text()
        with self._conn() as c:
            with c.cursor() as cur:
                cur.execute(ddl)

    def save_model(
        self,
        name: str,
        osi: dict[str, Any],
        *,
        odcs: dict[str, Any] | None = None,
        confluence_url: str | None = None,
    ) -> int:
        sm = osi["semantic_model"][0]
        description = sm.get("description")
        source = (sm.get("datasets") or [{}])[0].get("source")
        with self._conn() as c, c.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                """
                INSERT INTO osi_models (name, description, source, osi_payload, odcs_payload, confluence_url)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description    = EXCLUDED.description,
                    source         = EXCLUDED.source,
                    osi_payload    = EXCLUDED.osi_payload,
                    odcs_payload   = EXCLUDED.odcs_payload,
                    confluence_url = EXCLUDED.confluence_url,
                    updated_at     = now()
                """,
                (name, description, source, json.dumps(osi),
                 json.dumps(odcs) if odcs else None, confluence_url),
            )
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM osi_model_versions WHERE name = %s",
                (name,),
            )
            next_version = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO osi_model_versions (name, version, osi_payload, odcs_payload)
                VALUES (%s, %s, %s::jsonb, %s::jsonb)
                """,
                (name, next_version, json.dumps(osi),
                 json.dumps(odcs) if odcs else None),
            )
        return next_version

    def list_names(self) -> list[str]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT name FROM osi_models ORDER BY name")
            return [r[0] for r in cur.fetchall()]

    def get(self, name: str) -> dict[str, Any]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT osi_payload FROM osi_models WHERE name = %s", (name,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown model '{name}'. Available: {self.list_names()}")
        payload = row[0]
        return payload if isinstance(payload, dict) else json.loads(payload)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT name, osi_payload FROM osi_models ORDER BY name")
            rows = cur.fetchall()
        out: list[tuple[str, dict[str, Any]]] = []
        for name, payload in rows:
            out.append((name, payload if isinstance(payload, dict) else json.loads(payload)))
        return out

    def history(self, name: str) -> list[dict[str, Any]]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                """
                SELECT version, created_at
                FROM osi_model_versions
                WHERE name = %s
                ORDER BY version
                """,
                (name,),
            )
            return [{"version": r[0], "created_at": r[1].isoformat()} for r in cur.fetchall()]

    # ---------- Access-request log ----------

    def save_access_request(
        self,
        request_id: str,
        model: str,
        requester: str,
        justification: str = "",
    ) -> None:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO osi_access_requests (id, model, requester, justification, status)
                VALUES (%s, %s, %s, %s, 'pending')
                """,
                (request_id, model, requester, justification),
            )

    def record_grants(self, request_id: str, grants: list[dict[str, Any]]) -> None:
        with self._conn() as c, c.cursor() as cur:
            for g in grants:
                cur.execute(
                    """
                    INSERT INTO osi_access_grants (request_id, engine, status, detail)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (request_id, g["engine"], g["status"], g.get("detail", "")),
                )

    def update_access_status(self, request_id: str, status: str) -> None:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                """
                UPDATE osi_access_requests
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, request_id),
            )

    def get_access_request(self, request_id: str) -> dict[str, Any] | None:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                """
                SELECT id, model, requester, justification, status, created_at, updated_at
                FROM osi_access_requests
                WHERE id = %s
                """,
                (request_id,),
            )
            r = cur.fetchone()
            if r is None:
                return None
            cur.execute(
                """
                SELECT engine, status, detail, created_at
                FROM osi_access_grants
                WHERE request_id = %s
                ORDER BY id
                """,
                (request_id,),
            )
            grants = cur.fetchall()
        return {
            "id": r[0],
            "model": r[1],
            "requester": r[2],
            "justification": r[3],
            "status": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
            "updated_at": r[6].isoformat() if r[6] else None,
            "grants": [
                {
                    "engine": g[0],
                    "status": g[1],
                    "detail": g[2],
                    "created_at": g[3].isoformat() if g[3] else None,
                }
                for g in grants
            ],
        }

    def list_access_requests(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                """
                SELECT id, model, requester, status, created_at
                FROM osi_access_requests
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [
                {
                    "id": r[0],
                    "model": r[1],
                    "requester": r[2],
                    "status": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in cur.fetchall()
            ]


def mint_lakebase_dsn(
    *,
    instance_name: str,
    database: str = "databricks_postgres",
    workspace_host: str | None = None,
    workspace_token: str | None = None,
) -> str:
    """Mint a short-lived Lakebase Postgres DSN using the workspace OAuth token.

    Lakebase instances expose a public Postgres endpoint and accept the
    workspace OAuth token as the Postgres password. This helper looks up the
    instance host via the Databricks SDK and returns a ready-to-use DSN.

    Falls back to env vars: DATABRICKS_HOST, DATABRICKS_TOKEN.
    """
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as e:
        raise ImportError(
            "databricks-sdk is required for mint_lakebase_dsn. Install with "
            "`pip install databricks-sdk`."
        ) from e

    host = workspace_host or os.environ.get("DATABRICKS_HOST")
    token = workspace_token or os.environ.get("DATABRICKS_TOKEN")
    if not host or not token:
        raise RuntimeError(
            "DATABRICKS_HOST and DATABRICKS_TOKEN must be set (or passed in) "
            "to mint a Lakebase DSN."
        )
    w = WorkspaceClient(host=host, token=token)
    inst = w.database.get_database_instance(name=instance_name)
    pg_host = inst.read_write_dns
    user = w.current_user.me().user_name
    # Lakebase accepts the workspace OAuth token as the Postgres password;
    # the username is the Databricks user email.
    return f"postgresql://{user}:{token}@{pg_host}:5432/{database}?sslmode=require"
