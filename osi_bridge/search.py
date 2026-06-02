"""Search across OSI metrics and an AI fallback for empty result sets.

The hackathon's Top-Down Discovery journey wants a business user to type a
KPI name and either land on the exact metric or be guided to the nearest
domain owner. This module supplies both halves:

  - `search_metrics()` scores every metric in the registry against the user's
    query string. Cheap, deterministic, runs on every keystroke.

  - `ai_fallback()` calls Databricks-hosted Gemini with a short OSI catalog
    summary and asks for adjacent models and owners when the search comes up
    empty. Used by the portal on `0 results`.

Neither function does any persistence. The portal layer decides what to do
with the answers.
"""
from __future__ import annotations

import json
import os
from typing import Any

from osi_bridge.registry import Registry
from osi_bridge.translators._common import get_ai_context, get_custom_extension


def _score_metric(metric: dict[str, Any], model: str, q: str) -> float:
    """Heuristic relevance score for one metric vs. a lowercased query string.

    Tuning intent: exact matches on the canonical name win; partial matches on
    the display name come next; synonyms and descriptions are softer signals.
    The model name itself contributes a small boost so cross-model unions stay
    reasonable when the user types the dataset (`taxi`, `lidlplus`).
    """
    if not q:
        return 0.0
    score = 0.0
    ai = get_ai_context(metric)
    name = (metric.get("name") or "").lower()
    display = (ai.get("display_name") or "").lower()
    description = (metric.get("description") or "").lower()
    synonyms = [s.lower() for s in (ai.get("synonyms") or [])]
    model_lc = model.lower()

    if q == name:
        score += 10.0
    elif q in name:
        score += 6.0
    if q == display:
        score += 8.0
    elif q in display:
        score += 4.0
    for syn in synonyms:
        if q == syn:
            score += 5.0
        elif q in syn or syn in q:
            score += 2.5
    if q in description:
        score += 1.5
    if q in model_lc:
        score += 0.75
    return score


def search_metrics(registry: Registry, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Rank every metric in `registry` against `query` and return the top hits.

    Returned rows are portal-friendly: enough metadata to render a card
    (model, display name, synonyms, description) plus the raw score for
    debugging.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    hits: list[tuple[float, dict[str, Any]]] = []
    for model_name, osi in registry.items():
        sm = osi["semantic_model"][0]
        for m in sm.get("metrics", []):
            score = _score_metric(m, model_name, q)
            if score <= 0:
                continue
            ai = get_ai_context(m)
            hits.append((
                score,
                {
                    "model": model_name,
                    "name": m["name"],
                    "display_name": ai.get("display_name"),
                    "description": m.get("description"),
                    "synonyms": ai.get("synonyms", []),
                    "score": round(score, 2),
                },
            ))
    hits.sort(key=lambda t: -t[0])
    return [h for _, h in hits[:limit]]


def _catalog_summary(registry: Registry) -> str:
    """Compact catalog dump used as Gemini context when searching is empty."""
    lines: list[str] = []
    for name, osi in registry.items():
        sm = osi["semantic_model"][0]
        odcs = get_custom_extension(sm.get("custom_extensions"), "odcs")
        owner = odcs.get("owner") or "unknown"
        domain = odcs.get("domain") or "unknown"
        metric_names = [m["name"] for m in sm.get("metrics", [])]
        dim_names = [f["name"] for f in sm["datasets"][0]["fields"]]
        lines.append(
            f"- model: {name}\n"
            f"    description: {sm.get('description', '')}\n"
            f"    domain: {domain}\n"
            f"    owner: {owner}\n"
            f"    metrics: {metric_names}\n"
            f"    dimensions: {dim_names}"
        )
    return "\n".join(lines)


def ai_fallback(
    registry: Registry,
    query: str,
    *,
    model_name: str | None = None,
    host: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Ask Gemini for the closest models and owners when search returns nothing.

    Returns `{"query", "suggested_models", "rationale", "owner_contacts",
    "request_action"}`. Owner contacts come from the OSI custom_extensions.odcs
    block so we never invent an email.
    """
    from openai import OpenAI  # lazy import — module is optional in tests

    host = host or os.environ["DATABRICKS_HOST"].rstrip("/")
    token = token or os.environ["DATABRICKS_TOKEN"]
    gemini = model_name or os.environ.get("GEMINI_MODEL", "databricks-gemini-2-5-flash")

    client = OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")
    summary = _catalog_summary(registry)

    system = (
        "You are the Schwarz Git Ready Barcelona Hackathon data portal's discovery assistant. "
        "A business user searched for a metric that does not exist in the OSI "
        "catalog. From the catalog summary, suggest one or more models whose "
        "data could plausibly answer the question, name the model owner from "
        "the catalog (never invent emails), and propose one concrete next action. "
        "Respond as compact JSON with keys "
        "`suggested_models` (list of model names), `rationale` (string), "
        "`owner_contacts` (list of email strings copied verbatim from the catalog), "
        "`request_action` (one-sentence next step). No prose outside the JSON."
    )
    user = f"User search: {query!r}\n\nOSI catalog:\n{summary}"
    resp = client.chat.completions.create(
        model=gemini,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"suggested_models": [], "rationale": raw, "owner_contacts": [], "request_action": ""}
    parsed["query"] = query
    return parsed
