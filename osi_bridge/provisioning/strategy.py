"""Strategy Mosaic access provisioning via REST.

Mosaic security is project- and object-scoped ACL. The simplest portable
path is `PUT /api/v1/projects/{id}/permissions/users/{email}` with a body
like `{"role": "consumer"}`. Schwarz's real Mosaic deployment may use a
different endpoint shape; the env var STRATEGY_PERMISSION_ROLE lets the
SA pick the role name without code changes.

Requires STRATEGY_BASE_URL and STRATEGY_TOKEN. Missing creds → 'skipped'.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from osi_bridge.provisioning._common import GrantResult, engine_fqn


ENGINE_NAME = "strategy"


def _creds() -> tuple[str, str] | None:
    base = os.environ.get("STRATEGY_BASE_URL")
    token = os.environ.get("STRATEGY_TOKEN")
    if base and token:
        return base.rstrip("/"), token
    return None


def grant(
    osi_model: dict[str, Any],
    requester: str,
    justification: str = "",
    *,
    dry_run: bool = False,
) -> GrantResult:
    project_id = engine_fqn(osi_model, ENGINE_NAME)
    if not project_id:
        return GrantResult(ENGINE_NAME, "skipped", "OSI has no custom_extensions.strategy block")

    creds = _creds()
    role = os.environ.get("STRATEGY_PERMISSION_ROLE", "consumer")
    body = {"role": role}
    target = (
        f"/api/v1/projects/{urllib.parse.quote(str(project_id), safe='')}"
        f"/permissions/users/{urllib.parse.quote(requester, safe='')}"
    )

    if dry_run or creds is None:
        return GrantResult(
            ENGINE_NAME,
            "dry-run" if dry_run else "skipped",
            f"Would PUT {target} body={json.dumps(body)}",
        )

    base, token = creds
    req = urllib.request.Request(
        f"{base}{target}",
        method="PUT",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return GrantResult(
                ENGINE_NAME, "granted",
                f"Strategy responded {resp.status} for {target}",
            )
    except Exception as e:
        return GrantResult(ENGINE_NAME, "failed", f"{type(e).__name__}: {e}")
