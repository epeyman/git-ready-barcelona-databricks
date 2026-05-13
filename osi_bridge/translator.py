"""Phase-0 import path. The translator was split into per-vendor adapters in
Phase 3 (`osi_bridge.translators.{databricks,dremio,strategy}`). This module
re-exports the Databricks `build_sql` so notebooks and exporters that imported
`osi_bridge.translator.build_sql` keep working.
"""
from osi_bridge.translators.databricks import build_sql  # noqa: F401

__all__ = ["build_sql"]
