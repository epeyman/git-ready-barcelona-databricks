"""Producer-journey orchestrator.

Two operations:

  - `infer(fqn, domain, owner, description, dry_run)` — describe a UC table
    and run the AI / heuristic modeler. Returns the proposed OSI and ODCS
    dicts, plus the YAML strings the producer's UI shows for review.

  - `publish(osi, odcs, dry_run, store)` — render OSI/ODCS YAML, commit
    them to the configured GitHub contracts repo (or dry-run), and write
    the model into the local store so the portal can serve it right away.
"""
from __future__ import annotations

import os
from typing import Any

import yaml

from osi_bridge.producer import dataset_modeler, schema_inspector
from osi_bridge.producer.git_publisher import publish as git_publish


def infer(
    fqn: str,
    *,
    domain: str,
    owner: str,
    description: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    columns = schema_inspector.describe_table(fqn, dry_run=dry_run)
    if not columns:
        raise ValueError(f"No columns found for {fqn}")
    enriched = dataset_modeler.infer(
        fqn, columns, domain=domain, owner=owner, description=description, dry_run=dry_run
    )
    return {
        "fqn": fqn,
        "columns": columns,
        "osi": enriched["osi"],
        "odcs": enriched["odcs"],
        "osi_yaml": yaml.safe_dump(enriched["osi"], sort_keys=False),
        "odcs_yaml": yaml.safe_dump(enriched["odcs"], sort_keys=False),
        "ai_used": enriched["ai_used"],
        "metrics_summary": enriched["metrics_summary"],
    }


def publish(
    osi: dict[str, Any],
    odcs: dict[str, Any],
    *,
    dry_run: bool = False,
    store: Any | None = None,
    contracts_subdir: str | None = None,
) -> dict[str, Any]:
    """Commit OSI + ODCS YAML to GitHub and persist the model to `store`.

    `contracts_subdir` overrides the repo path prefix; the defaults are
    `examples/models/` and `examples/odcs/` so the bridge's own repo can
    accept producer-journey commits during the demo.
    """
    name = osi["semantic_model"][0]["name"]
    short = name[:-3] if name.endswith("_mv") else name

    osi_subdir = (contracts_subdir or os.environ.get("GITHUB_OSI_SUBDIR", "examples/models")).strip("/")
    odcs_subdir = (contracts_subdir or os.environ.get("GITHUB_ODCS_SUBDIR", "examples/odcs")).strip("/")

    files = {
        f"{osi_subdir}/{short}.osi.yaml": yaml.safe_dump(osi, sort_keys=False),
        f"{odcs_subdir}/{short}.odcs.yaml": yaml.safe_dump(odcs, sort_keys=False),
    }
    git_result = git_publish(
        files,
        commit_message=f"osi-bridge: publish {name} via producer journey",
        dry_run=dry_run,
    )

    persisted = False
    if store is not None and hasattr(store, "save_model"):
        store.save_model(name, osi, odcs=odcs)
        persisted = True

    return {
        "model": name,
        "git": git_result,
        "persisted_to_store": persisted,
    }
