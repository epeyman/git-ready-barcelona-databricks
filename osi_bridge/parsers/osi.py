"""OSI v1.0 YAML loader and minimal validator.

We do not pull in a full JSON Schema validator yet — the OSI standard is
still moving, and the only fields the bridge actually relies on are the ones
checked here. Anything else round-trips untouched so consumers can carry
custom_extensions, AI hints, etc. without the bridge stripping them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_TOP_KEYS = ("version", "semantic_model")
REQUIRED_SEMANTIC_KEYS = ("name", "datasets")


def load_osi_yaml(path: str | Path) -> dict[str, Any]:
    """Load and validate a single OSI YAML file. Returns the OSI dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    validate_osi(data, source=str(path))
    return data


def validate_osi(data: dict[str, Any], source: str = "<inline>") -> None:
    """Raise ValueError if `data` does not look like a usable OSI v1.0 model."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: OSI document must be a mapping, got {type(data).__name__}")
    for k in REQUIRED_TOP_KEYS:
        if k not in data:
            raise ValueError(f"{source}: missing required top-level key '{k}'")
    sms = data["semantic_model"]
    if not isinstance(sms, list) or not sms:
        raise ValueError(f"{source}: 'semantic_model' must be a non-empty list")
    sm = sms[0]
    for k in REQUIRED_SEMANTIC_KEYS:
        if k not in sm:
            raise ValueError(f"{source}: semantic_model[0] missing required key '{k}'")
    if not isinstance(sm["datasets"], list) or not sm["datasets"]:
        raise ValueError(f"{source}: semantic_model[0].datasets must be a non-empty list")
    if "fields" not in sm["datasets"][0]:
        raise ValueError(f"{source}: semantic_model[0].datasets[0] missing 'fields'")
