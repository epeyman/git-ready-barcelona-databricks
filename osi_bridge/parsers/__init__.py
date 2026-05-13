"""Parsers that turn external contract formats into the canonical OSI dict.

The OSI dict shape (the one `osi_bridge.translator.build_sql` and the MCP tools
consume) is the lingua franca inside the bridge. Each parser converts its
input format — OSI YAML, ODCS v3 YAML, Confluence page text — to that shape
or augments an existing OSI dict in place.
"""
from osi_bridge.parsers.osi import load_osi_yaml, validate_osi
from osi_bridge.parsers.odcs import load_odcs_yaml, odcs_to_osi
from osi_bridge.parsers.confluence import fetch_confluence_page, merge_confluence_into_osi

__all__ = [
    "load_osi_yaml",
    "validate_osi",
    "load_odcs_yaml",
    "odcs_to_osi",
    "fetch_confluence_page",
    "merge_confluence_into_osi",
]
