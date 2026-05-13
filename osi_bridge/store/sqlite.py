"""SQLite-backed model store — for local dev and CI.

The schema is a near-direct port of osi_bridge/store/schema.sql: same tables,
JSON instead of JSONB, no TIMESTAMPTZ. The CRUD surface is identical to
LakebaseModelStore so server.py and the ingestion CLI can switch backends by
config alone.

Used by tests and by anyone who wants to demo the YAML-in-database story
without standing up a Postgres / Lakebase first.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS osi_models (
    name           TEXT PRIMARY KEY,
    description    TEXT,
    source         TEXT,
    osi_payload    TEXT NOT NULL,
    odcs_payload   TEXT,
    confluence_url TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS osi_model_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL REFERENCES osi_models(name) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    osi_payload  TEXT NOT NULL,
    odcs_payload TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS osi_models_source_idx ON osi_models (source);

CREATE TABLE IF NOT EXISTS osi_access_requests (
    id            TEXT PRIMARY KEY,
    model         TEXT NOT NULL,
    requester     TEXT NOT NULL,
    justification TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS osi_access_grants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL REFERENCES osi_access_requests(id) ON DELETE CASCADE,
    engine      TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS osi_access_requests_model_idx ON osi_access_requests (model);
CREATE INDEX IF NOT EXISTS osi_access_grants_request_idx ON osi_access_grants (request_id);
"""


class SqliteModelStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path)
        c.execute("PRAGMA foreign_keys = ON")
        return c

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
        osi_json = json.dumps(osi)
        odcs_json = json.dumps(odcs) if odcs else None
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO osi_models (name, description, source, osi_payload, odcs_payload, confluence_url)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description    = excluded.description,
                    source         = excluded.source,
                    osi_payload    = excluded.osi_payload,
                    odcs_payload   = excluded.odcs_payload,
                    confluence_url = excluded.confluence_url,
                    updated_at     = datetime('now')
                """,
                (name, description, source, osi_json, odcs_json, confluence_url),
            )
            row = c.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM osi_model_versions WHERE name = ?",
                (name,),
            ).fetchone()
            next_version = row[0]
            c.execute(
                """
                INSERT INTO osi_model_versions (name, version, osi_payload, odcs_payload)
                VALUES (?, ?, ?, ?)
                """,
                (name, next_version, osi_json, odcs_json),
            )
        return next_version

    def list_names(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT name FROM osi_models ORDER BY name").fetchall()
        return [r[0] for r in rows]

    def get(self, name: str) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute(
                "SELECT osi_payload FROM osi_models WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown model '{name}'. Available: {self.list_names()}")
        return json.loads(row[0])

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT name, osi_payload FROM osi_models ORDER BY name"
            ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def history(self, name: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT version, created_at
                FROM osi_model_versions
                WHERE name = ?
                ORDER BY version
                """,
                (name,),
            ).fetchall()
        return [{"version": r[0], "created_at": r[1]} for r in rows]

    # ---------- Access-request log ----------

    def save_access_request(
        self,
        request_id: str,
        model: str,
        requester: str,
        justification: str = "",
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO osi_access_requests (id, model, requester, justification, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (request_id, model, requester, justification),
            )

    def record_grants(self, request_id: str, grants: list[dict[str, Any]]) -> None:
        with self._conn() as c:
            for g in grants:
                c.execute(
                    """
                    INSERT INTO osi_access_grants (request_id, engine, status, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (request_id, g["engine"], g["status"], g.get("detail", "")),
                )

    def update_access_status(self, request_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute(
                """
                UPDATE osi_access_requests
                SET status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, request_id),
            )

    def get_access_request(self, request_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute(
                """
                SELECT id, model, requester, justification, status, created_at, updated_at
                FROM osi_access_requests
                WHERE id = ?
                """,
                (request_id,),
            ).fetchone()
            if r is None:
                return None
            grants = c.execute(
                """
                SELECT engine, status, detail, created_at
                FROM osi_access_grants
                WHERE request_id = ?
                ORDER BY id
                """,
                (request_id,),
            ).fetchall()
        return {
            "id": r[0],
            "model": r[1],
            "requester": r[2],
            "justification": r[3],
            "status": r[4],
            "created_at": r[5],
            "updated_at": r[6],
            "grants": [
                {"engine": g[0], "status": g[1], "detail": g[2], "created_at": g[3]}
                for g in grants
            ],
        }

    def list_access_requests(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT id, model, requester, status, created_at
                FROM osi_access_requests
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "model": r[1],
                "requester": r[2],
                "status": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]
