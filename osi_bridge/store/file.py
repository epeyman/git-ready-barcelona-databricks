"""Filesystem-backed model store. Wraps the Phase 0 directory-scan behaviour
behind the new store interface so server.py can plug in any backend."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from osi_bridge.parsers.osi import load_osi_yaml


class FileModelStore:
    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"OSI model path does not exist: {p}")
        self._path = p
        self._cache: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        files = [self._path] if self._path.is_file() else sorted(self._path.glob("*.osi.yaml"))
        if not files:
            raise FileNotFoundError(f"No *.osi.yaml files in {self._path}")
        for f in files:
            data = load_osi_yaml(f)
            name = data["semantic_model"][0]["name"]
            if name in self._cache:
                raise ValueError(f"Duplicate model name '{name}' (from {f})")
            self._cache[name] = data

    def list_names(self) -> list[str]:
        return sorted(self._cache)

    def get(self, name: str) -> dict[str, Any]:
        if name not in self._cache:
            raise KeyError(f"Unknown model '{name}'. Available: {self.list_names()}")
        return self._cache[name]

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self._cache.items())
