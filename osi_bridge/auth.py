"""On-demand OAuth refresh for the Databricks bearer token.

The portal and bridge read `os.environ["DATABRICKS_TOKEN"]` directly in
many places (`exporter`, `importer`, `discovery`, `translators.databricks`,
`portal.chat`). Rather than thread a token object through every call, this
module exposes `get_token()`, which:

- Returns a personal access token (`dapi…`) untouched — PATs don't expire.
- Decodes a Bearer JWT's `exp` claim and mints a fresh OAuth token via
  the Databricks SDK when there's < 5 minutes left.
- Writes the refreshed token back to `os.environ["DATABRICKS_TOKEN"]`
  so existing readers see the new value without changes.

Thread-safe via a single module-level lock; safe to call from any
FastAPI handler.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time

_LOCK = threading.Lock()
_CACHED_TOKEN: str | None = None
_CACHED_EXP: float = 0.0  # epoch seconds; 0 means "never expires" (PAT)
_REFRESH_SAFETY_WINDOW = 300  # refresh when < 5 min left


def _decode_jwt_exp(token: str) -> float | None:
    """Pull `exp` out of a JWT's payload without verifying the signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def _is_pat(token: str) -> bool:
    return token.startswith("dapi")


def _mint_fresh_token() -> tuple[str, float]:
    """Mint a fresh OAuth bearer by calling `databricks auth token`.

    Goes through the CLI rather than the SDK Config chain because the SDK
    prefers a `DATABRICKS_TOKEN` env var (treats it as an external PAT) over
    OAuth refresh — exactly what we want to bypass when refreshing.
    The CLI reads `~/.databricks/token-cache.json` directly.
    """
    import subprocess

    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    result = subprocess.run(
        ["databricks", "auth", "token", "--host", host],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"databricks auth token failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    token = payload["access_token"]
    exp = _decode_jwt_exp(token) or (time.time() + 3600)
    return token, exp


def _bootstrap_from_env() -> None:
    """Initial cache fill from DATABRICKS_TOKEN env var."""
    global _CACHED_TOKEN, _CACHED_EXP
    env_token = os.environ.get("DATABRICKS_TOKEN", "")
    if not env_token:
        _CACHED_TOKEN, _CACHED_EXP = _mint_fresh_token()
        os.environ["DATABRICKS_TOKEN"] = _CACHED_TOKEN
        return
    _CACHED_TOKEN = env_token
    if _is_pat(env_token):
        _CACHED_EXP = 0.0
    else:
        _CACHED_EXP = _decode_jwt_exp(env_token) or 0.0


def get_token() -> str:
    """Return a valid Databricks bearer. Refreshes silently if near expiry."""
    global _CACHED_TOKEN, _CACHED_EXP

    with _LOCK:
        if _CACHED_TOKEN is None:
            _bootstrap_from_env()

        # PATs never expire here.
        if _CACHED_EXP == 0.0:
            return _CACHED_TOKEN  # type: ignore[return-value]

        if _CACHED_EXP - time.time() < _REFRESH_SAFETY_WINDOW:
            try:
                _CACHED_TOKEN, _CACHED_EXP = _mint_fresh_token()
                os.environ["DATABRICKS_TOKEN"] = _CACHED_TOKEN
            except Exception:
                # Fall through with the cached (probably-stale) token —
                # callers will see the real Databricks 401 instead of a
                # mint failure mid-request.
                pass
        return _CACHED_TOKEN  # type: ignore[return-value]


def reset_cache() -> None:
    """Drop the cached token (for tests)."""
    global _CACHED_TOKEN, _CACHED_EXP
    with _LOCK:
        _CACHED_TOKEN = None
        _CACHED_EXP = 0.0
