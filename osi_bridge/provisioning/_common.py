"""Shared types and helpers for engine-specific provisioning providers.

Every provider implements:

    grant(osi_model, requester, justification, *, dry_run=False) -> GrantResult

The service in `osi_bridge.provisioning.service` iterates the engines
declared on the OSI model and aggregates one GrantResult per provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GrantResult:
    """One provider's verdict for one access request."""

    engine: str
    status: str  # 'granted' | 'skipped' | 'failed' | 'dry-run'
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"engine": self.engine, "status": self.status, "detail": self.detail}


def engine_fqn(osi_model: dict[str, Any], engine: str) -> str | None:
    """Look up the engine-specific identifier from custom_extensions.

    Databricks → metric_view_fqn, Dremio → table, Strategy → metric_set_id.
    Returns None if the engine block is missing. Accepts both the
    spec-compliant array-of-objects shape and the legacy vendor-keyed map.
    """
    from osi_bridge.translators._common import get_custom_extension

    ext = get_custom_extension(
        osi_model["semantic_model"][0].get("custom_extensions"), engine
    )
    if engine == "databricks":
        return ext.get("metric_view_fqn")
    if engine == "dremio":
        return ext.get("table") or ext.get("dataset")
    if engine == "strategy":
        return ext.get("metric_set_id") or ext.get("project_id")
    return None
