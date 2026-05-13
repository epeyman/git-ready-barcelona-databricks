"""Registry of OSI semantic models.

A registry holds a `{model_name: osi_dict}` map served to the MCP tools.
Phase 0 loaded these from a directory of YAML files; Phase 1 makes the
backing store pluggable so the bridge can read from a Lakebase / Postgres
table instead. The MCP server interacts with a single `Registry` instance
and never knows where the models came from.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ModelStore(Protocol):
    def list_names(self) -> list[str]: ...
    def get(self, name: str) -> dict[str, Any]: ...
    def items(self) -> list[tuple[str, dict[str, Any]]]: ...


class Registry:
    def __init__(self, store: ModelStore | None = None) -> None:
        self._store: ModelStore | None = store

    def __len__(self) -> int:
        return len(self.names())

    def __contains__(self, name: str) -> bool:
        return name in self.names()

    def attach(self, store: ModelStore) -> None:
        """Attach (or replace) the backing store."""
        self._store = store

    def names(self) -> list[str]:
        return self._store.list_names() if self._store else []

    def get(self, name: str) -> dict[str, Any]:
        if self._store is None:
            raise RuntimeError("Registry has no store attached.")
        return self._store.get(name)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        return self._store.items() if self._store else []

    # ----- Convenience constructors for the two common backends -----

    @classmethod
    def from_path(cls, path: str | Path) -> "Registry":
        """Load every `*.osi.yaml` under `path` (or just `path` if it is a file)."""
        from osi_bridge.store.file import FileModelStore

        return cls(FileModelStore(path))

    @classmethod
    def from_sqlite(cls, db_path: str | Path) -> "Registry":
        from osi_bridge.store.sqlite import SqliteModelStore

        return cls(SqliteModelStore(db_path))

    @classmethod
    def from_lakebase(cls, dsn: str | None = None) -> "Registry":
        from osi_bridge.store.lakebase import LakebaseModelStore

        return cls(LakebaseModelStore(dsn))

    # ----- Phase-0 back-compat shim -----

    def load_path(self, path: str | Path) -> list[str]:
        """Phase-0 API. Attaches a FileModelStore and returns loaded names."""
        from osi_bridge.store.file import FileModelStore

        store = FileModelStore(path)
        self._store = store
        return store.list_names()
