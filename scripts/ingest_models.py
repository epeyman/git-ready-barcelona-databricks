"""Ingest OSI and ODCS YAML files (and optional Confluence pages) into the
OSI Bridge model store.

This is the bridge between the "YAML on disk" world the engineers author in
and the "YAML in DB" runtime the bridge serves. Run it once per
contract-publish event; in production the Schwarz team is expected to wrap
this in a GitHub Action so every merge into the contracts repo upserts the
matching row in Lakebase.

Usage examples:

    # Local dev — SQLite store seeded from the repo's sample files
    python scripts/ingest_models.py \\
        --store sqlite --sqlite-path osi_bridge.db \\
        --osi-dir examples/models \\
        --odcs-dir examples/odcs

    # Lakebase / Postgres — same files, real store
    OSI_BRIDGE_PG_DSN=postgresql://... \\
    python scripts/ingest_models.py \\
        --store lakebase \\
        --osi-dir examples/models \\
        --odcs-dir examples/odcs

    # With Confluence enrichment
    CONFLUENCE_BASE_URL=https://schwarz.atlassian.net \\
    CONFLUENCE_TOKEN=... \\
    python scripts/ingest_models.py \\
        --store sqlite --sqlite-path osi_bridge.db \\
        --osi-dir examples/models \\
        --confluence-map orders=1234567
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from osi_bridge.parsers.osi import load_osi_yaml
from osi_bridge.parsers.odcs import load_odcs_yaml, odcs_to_osi, merge_metrics_from_osi
from osi_bridge.parsers.confluence import fetch_confluence_page, merge_confluence_into_osi


def _open_store(args: argparse.Namespace):
    if args.store == "sqlite":
        from osi_bridge.store.sqlite import SqliteModelStore

        return SqliteModelStore(args.sqlite_path)
    if args.store == "lakebase":
        from osi_bridge.store.lakebase import LakebaseModelStore

        return LakebaseModelStore(args.pg_dsn)
    raise ValueError(f"Unsupported --store {args.store}")


def _index_dir(path: Path, suffix: str) -> dict[str, Path]:
    """Return {stem: file} for every `*<suffix>` in `path`."""
    out: dict[str, Path] = {}
    if not path.exists():
        return out
    for f in sorted(path.glob(f"*{suffix}")):
        stem = f.name.removesuffix(suffix)
        out[stem] = f
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", choices=["sqlite", "lakebase"], default="sqlite")
    ap.add_argument("--sqlite-path", default=os.environ.get("OSI_BRIDGE_SQLITE", "osi_bridge.db"))
    ap.add_argument("--pg-dsn", default=os.environ.get("OSI_BRIDGE_PG_DSN"))
    ap.add_argument("--osi-dir", default="examples/models", help="Directory of *.osi.yaml files")
    ap.add_argument("--odcs-dir", default="examples/odcs", help="Directory of *.odcs.yaml files (optional)")
    ap.add_argument(
        "--confluence-map",
        action="append",
        default=[],
        help="Repeatable. Format: <model_name>=<confluence_page_id>. Enriches the OSI ai_context with the page body.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse everything and print the resulting OSI dicts without writing to the store.",
    )
    args = ap.parse_args()

    osi_dir = Path(args.osi_dir)
    odcs_dir = Path(args.odcs_dir) if args.odcs_dir else None

    osi_files = _index_dir(osi_dir, ".osi.yaml")
    odcs_files = _index_dir(odcs_dir, ".odcs.yaml") if odcs_dir else {}

    confluence_map: dict[str, str] = {}
    for entry in args.confluence_map:
        if "=" not in entry:
            print(f"WARN: --confluence-map entry {entry!r} not in name=page_id form, skipping", file=sys.stderr)
            continue
        k, v = entry.split("=", 1)
        confluence_map[k.strip()] = v.strip()

    if not osi_files and not odcs_files:
        print(f"ERROR: no OSI or ODCS files found under {osi_dir} / {odcs_dir}", file=sys.stderr)
        return 2

    store = None if args.dry_run else _open_store(args)

    processed: list[dict[str, Any]] = []
    keys = sorted(set(osi_files) | set(odcs_files))
    for key in keys:
        osi_path = osi_files.get(key)
        odcs_path = odcs_files.get(key)

        osi_doc: dict[str, Any] | None = None
        odcs_doc: dict[str, Any] | None = None

        if osi_path:
            osi_doc = load_osi_yaml(osi_path)
        if odcs_path:
            odcs_doc = load_odcs_yaml(odcs_path)

        # Merge strategy:
        #   - If we have both, ODCS is the contract-of-record for fields and
        #     governance; OSI contributes the metrics.
        #   - If we have only OSI, use it as-is.
        #   - If we have only ODCS, ingest with empty metrics — the agent can
        #     still discover the model and prompt for a Metric View.
        if odcs_doc and osi_doc:
            projected = odcs_to_osi(odcs_doc)
            merged = merge_metrics_from_osi(projected, osi_doc)
        elif odcs_doc:
            merged = odcs_to_osi(odcs_doc)
        else:
            assert osi_doc is not None
            merged = osi_doc

        name = merged["semantic_model"][0]["name"]
        confluence_url: str | None = None
        confluence_key = key if key in confluence_map else (name if name in confluence_map else None)
        if confluence_key:
            page = fetch_confluence_page(confluence_map[confluence_key])
            merge_confluence_into_osi(merged, page)
            confluence_url = page.get("url")

        processed.append({
            "name": name,
            "from_osi": osi_path is not None,
            "from_odcs": odcs_path is not None,
            "confluence": confluence_url,
        })

        if store is not None:
            version = store.save_model(
                name,
                merged,
                odcs=odcs_doc,
                confluence_url=confluence_url,
            )
            print(f"  saved {name:30s} v{version:<3} osi={bool(osi_path)} odcs={bool(odcs_path)} confluence={bool(confluence_url)}")
        else:
            print(f"  [dry-run] would save {name:30s} osi={bool(osi_path)} odcs={bool(odcs_path)} confluence={bool(confluence_url)}")

    print(f"\nProcessed {len(processed)} model(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
