"""MongoDB-backed model store.

Same ModelStore protocol as `FileModelStore` / `SqliteModelStore`, so the
portal can `REGISTRY.attach(MongoModelStore(...))` without touching the
rest of the registry surface.

The default constructor uses `mongomock` so the demo runs entirely in
memory — useful for the hackathon. Pass `client=MongoClient(uri)` to point
at a real Mongo instance; the rest of the class is identical because
mongomock mirrors pymongo's API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoModelStore:
    """Read/write store for OSI models, optionally with version history."""

    def __init__(
        self,
        *,
        client: Any = None,
        database: str = "osi_bridge",
        collection: str = "osi_models",
        versions_collection: str = "osi_model_versions",
    ) -> None:
        if client is None:
            import mongomock

            client = mongomock.MongoClient()
        self._client = client
        self._db = client[database]
        self._models = self._db[collection]
        self._versions = self._db[versions_collection]
        # Unique index on model name so upserts are deterministic.
        self._models.create_index("name", unique=True)
        self._versions.create_index([("name", 1), ("version", 1)], unique=True)

    # ---------- ModelStore protocol ----------

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
        now = _utcnow()

        existing = self._models.find_one({"name": name})
        created_at = existing["created_at"] if existing else now

        self._models.update_one(
            {"name": name},
            {
                "$set": {
                    "name": name,
                    "description": description,
                    "source": source,
                    "osi_payload": osi,
                    "odcs_payload": odcs,
                    "confluence_url": confluence_url,
                    "updated_at": now,
                    "created_at": created_at,
                }
            },
            upsert=True,
        )

        last = self._versions.find_one(
            {"name": name}, sort=[("version", -1)]
        )
        next_version = (last["version"] + 1) if last else 1
        self._versions.insert_one(
            {
                "name": name,
                "version": next_version,
                "osi_payload": osi,
                "odcs_payload": odcs,
                "created_at": now,
            }
        )
        return next_version

    def list_names(self) -> list[str]:
        return sorted(d["name"] for d in self._models.find({}, {"name": 1}))

    def get(self, name: str) -> dict[str, Any]:
        doc = self._models.find_one({"name": name})
        if doc is None:
            raise KeyError(f"Unknown model '{name}'. Available: {self.list_names()}")
        return doc["osi_payload"]

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(
            (d["name"], d["osi_payload"]) for d in self._models.find()
        )

    def history(self, name: str) -> list[dict[str, Any]]:
        return [
            {"version": d["version"], "created_at": d["created_at"]}
            for d in self._versions.find({"name": name}).sort("version", 1)
        ]

    def delete(self, name: str) -> bool:
        result = self._models.delete_one({"name": name})
        self._versions.delete_many({"name": name})
        return result.deleted_count > 0

    # ---------- Convenience for the sync flow ----------

    def summary(self) -> list[dict[str, Any]]:
        """Lightweight projection used by the Admin page to render a table."""
        return [
            {
                "name": d["name"],
                "source": d.get("source"),
                "description": d.get("description"),
                "updated_at": d.get("updated_at"),
            }
            for d in self._models.find({}, {"osi_payload": 0, "odcs_payload": 0}).sort("name", 1)
        ]
