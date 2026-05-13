"""Dremio access provisioning via REST.

Posts a grant against the dataset path identified by
`custom_extensions.dremio.table`. The Dremio API for catalog-level grants
is `POST /api/v3/catalog/by-path/{path}/privileges`; the body lists the
principal (user or role) and the privilege ('SELECT').

Requires DREMIO_BASE_URL and DREMIO_TOKEN. Missing creds → status='skipped'.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from osi_bridge.provisioning._common import GrantResult, engine_fqn


ENGINE_NAME = "dremio"


def _creds() -> tuple[str, str] | None:
    base = os.environ.get("DREMIO_BASE_URL")
    token = os.environ.get("DREMIO_TOKEN")
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
    path = engine_fqn(osi_model, ENGINE_NAME)
    if not path:
        return GrantResult(ENGINE_NAME, "skipped", "OSI has no custom_extensions.dremio block")

    creds = _creds()
    body = {
        "principal": {"type": "USER", "name": requester},
        "privileges": ["SELECT"],
    }
    target = f"/api/v3/catalog/by-path/{urllib.parse.quote(path, safe='')}/privileges"

    if dry_run or creds is None:
        return GrantResult(
            ENGINE_NAME,
            "dry-run" if dry_run else "skipped",
            f"Would POST {target} body={json.dumps(body)}",
        )

    base, token = creds
    req = urllib.request.Request(
        f"{base}{target}",
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return GrantResult(
                ENGINE_NAME, "granted",
                f"Dremio responded {resp.status} for {target}",
            )
    except Exception as e:
        return GrantResult(ENGINE_NAME, "failed", f"{type(e).__name__}: {e}")
