"""Confluence page → OSI ai_context.instructions enrichment.

Customer keeps business-rule documentation (definitions of revenue, what
counts as an active customer, how returns are netted, …) in Confluence. The
hackathon brief calls this out as one of the inputs we should ingest. We
fetch the page via the Confluence REST v2 API, strip the HTML to plain text,
and merge it into the OSI semantic_model.ai_context.instructions so the
agent has the business glossary at hand without leaving MCP.

The fetcher is deliberately thin — no auth dance, no link-rewriting — so it
works against both Schwarz's Confluence Cloud and Server / Data Center
instances. The ingestion script calls this once per model and persists the
combined OSI dict in the store.
"""
from __future__ import annotations

import os
import re
from typing import Any

import urllib.parse
import urllib.request


CONFLUENCE_BASE_URL_ENV = "CONFLUENCE_BASE_URL"
CONFLUENCE_TOKEN_ENV = "CONFLUENCE_TOKEN"
CONFLUENCE_EMAIL_ENV = "CONFLUENCE_EMAIL"  # Cloud Basic auth (email + API token)


def fetch_confluence_page(
    page_id: str,
    *,
    base_url: str | None = None,
    token: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Fetch a Confluence page by ID. Returns `{title, body_text, body_html, url}`.

    Authentication strategy:
      - Confluence Cloud: pass `email` + an API token in `token`. Basic auth.
      - Confluence Server / Data Center: pass `token` only. Bearer auth.
      - Anything env-overridden: CONFLUENCE_BASE_URL, CONFLUENCE_TOKEN, CONFLUENCE_EMAIL.
    """
    base = base_url or os.environ.get(CONFLUENCE_BASE_URL_ENV)
    tok = token or os.environ.get(CONFLUENCE_TOKEN_ENV)
    em = email or os.environ.get(CONFLUENCE_EMAIL_ENV)
    if not base:
        raise RuntimeError(
            f"Confluence base URL not set. Provide base_url=... or set ${CONFLUENCE_BASE_URL_ENV}."
        )
    if not tok:
        raise RuntimeError(
            f"Confluence credentials not set. Provide token=... or set ${CONFLUENCE_TOKEN_ENV}."
        )

    url = f"{base.rstrip('/')}/wiki/api/v2/pages/{urllib.parse.quote(page_id)}?body-format=storage"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if em:
        import base64

        creds = base64.b64encode(f"{em}:{tok}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    else:
        req.add_header("Authorization", f"Bearer {tok}")

    import json
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    body_html = (payload.get("body") or {}).get("storage", {}).get("value", "")
    return {
        "title": payload.get("title", ""),
        "body_html": body_html,
        "body_text": _html_to_text(body_html),
        "url": (payload.get("_links") or {}).get("webui")
        or f"{base.rstrip('/')}/wiki/spaces/{payload.get('spaceId', '')}/pages/{page_id}",
    }


def merge_confluence_into_osi(osi: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    """Append the Confluence page text to semantic_model[0].ai_context.instructions.

    Mutates `osi` in place and returns it. Also records the page URL under
    custom_extensions.confluence for traceability.
    """
    sm = osi["semantic_model"][0]
    ai_ctx = sm.setdefault("ai_context", {})
    existing = ai_ctx.get("instructions", "")
    addition = (
        f"\n\nBusiness rules from Confluence page '{page.get('title', '')}':\n"
        f"{page.get('body_text', '').strip()}"
    )
    ai_ctx["instructions"] = (existing or "").rstrip() + addition

    ext = sm.setdefault("custom_extensions", {})
    ext["confluence"] = {
        "url": page.get("url"),
        "title": page.get("title"),
    }
    return osi


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace. Not a full parser — good enough
    for instruction text that the LLM will read."""
    no_tags = _TAG_RE.sub(" ", html or "")
    return _WS_RE.sub(" ", no_tags).strip()
