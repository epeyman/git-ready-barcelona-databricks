"""Provisioning orchestrator.

Given an OSI model and a requester, calls every engine the model declares
in its `custom_extensions` blocks and returns one GrantResult per engine.
Status semantics:

  - granted  — the engine ran the grant successfully
  - failed   — the engine rejected the call (HTTP error, UC denial, …)
  - skipped  — the engine has no credentials in this process / no extension
  - dry-run  — caller passed dry_run=True

The orchestrator does not raise on per-engine failure; the audit row carries
the verdict and the portal can render mixed-status outcomes correctly.

`grant_all` rolls up the per-engine statuses into a single request status:
  - all granted             → 'granted'
  - any granted, none failed → 'partial'   (some engines skipped, others granted)
  - all skipped              → 'pending'   (no engine actually ran)
  - any failed               → 'failed'
"""
from __future__ import annotations

from typing import Any

from osi_bridge import translators
from osi_bridge.provisioning import databricks, dremio, strategy
from osi_bridge.provisioning._common import GrantResult


_PROVIDERS = {
    databricks.ENGINE_NAME: databricks,
    dremio.ENGINE_NAME: dremio,
    strategy.ENGINE_NAME: strategy,
}


def grant_all(
    osi_model: dict[str, Any],
    requester: str,
    justification: str = "",
    *,
    dry_run: bool = False,
) -> list[GrantResult]:
    """Run every engine declared on the OSI model. Returns one result each."""
    engines = translators.available_engines(osi_model) or ["databricks"]
    results: list[GrantResult] = []
    for eng in engines:
        provider = _PROVIDERS.get(eng)
        if provider is None:
            results.append(GrantResult(eng, "skipped", "no provider registered"))
            continue
        results.append(provider.grant(osi_model, requester, justification, dry_run=dry_run))
    return results


def rollup_status(results: list[GrantResult]) -> str:
    statuses = {r.status for r in results}
    if "failed" in statuses:
        return "failed"
    if "granted" in statuses and statuses <= {"granted", "skipped", "dry-run"}:
        return "granted" if statuses <= {"granted"} else "partial"
    if statuses == {"dry-run"}:
        return "dry-run"
    return "pending"
