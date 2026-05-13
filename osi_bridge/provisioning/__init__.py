"""Access-provisioning across the bridge's vendor engines.

Each engine provider exposes `grant(osi_model, requester, justification, *, dry_run)`.
`service.grant_all(...)` orchestrates the engines declared on a model and
`service.rollup_status(...)` collapses the per-engine verdicts into a single
status the portal can render on a request row.
"""
from osi_bridge.provisioning._common import GrantResult
from osi_bridge.provisioning.service import grant_all, rollup_status

__all__ = ["GrantResult", "grant_all", "rollup_status"]
