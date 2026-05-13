"""Producer journey — auto-generate OSI + ODCS contracts from a UC table.

The portal's `/publish` page walks a data producer through three steps:
  1. enter the source table FQN, domain, and owner
  2. review the inferred OSI / ODCS YAML (synonyms, descriptions, metrics)
  3. publish — commits both files to a GitHub contracts repo and writes
     the model into the local model store so the catalog sees it instantly.
"""
from osi_bridge.producer.service import infer, publish

__all__ = ["infer", "publish"]
