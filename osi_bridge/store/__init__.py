"""Model stores backing the bridge's registry.

A model store persists OSI dicts (plus optional ODCS payloads and Confluence
metadata) so the bridge can load them at startup without scanning the
filesystem. Two backends ship today:

  - `FileModelStore`     — reads `*.osi.yaml` from a directory (Phase 0 behaviour).
  - `LakebaseModelStore` — Postgres-backed; works against Databricks Lakebase
                           or any vanilla Postgres.

A `SqliteModelStore` is also provided for local development so a
psycopg / Postgres dependency is not required to demo the persistence story.

All three implement the same minimal interface used by `osi_bridge.registry`:

    list_names() -> list[str]
    get(name)    -> dict        # the OSI dict
    items()      -> list[(name, osi_dict)]
"""
from osi_bridge.store.file import FileModelStore
from osi_bridge.store.sqlite import SqliteModelStore

try:
    from osi_bridge.store.lakebase import LakebaseModelStore  # noqa: F401
except ImportError:  # psycopg not installed — Lakebase is optional
    LakebaseModelStore = None  # type: ignore[assignment]


__all__ = ["FileModelStore", "SqliteModelStore", "LakebaseModelStore"]
