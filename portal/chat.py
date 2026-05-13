"""In-process Gemini chat handler.

Reimplements the manual MCP tool-calling loop from `examples/gemini_client.py`
but routes the tool calls to local Python functions in `osi_bridge.tools`
rather than over SSE/MCP. The portal serves a single chat endpoint; the
underlying OSI Bridge MCP server can still be running for external agents
that need MCP over the wire.

The trace returned to the caller mirrors what an MCP-aware client would have
recorded, so the UI can show "agent called list_models → list_metrics → …"
exactly as it would over the real protocol.
"""
from __future__ import annotations

import json
import os
from typing import Any

from osi_bridge import tools
from osi_bridge.registry import Registry

from portal.schemas import ChatResponse, ToolCall


SYSTEM_PROMPT = (
    "You are the Schwarz GIT READY data portal's analytics agent. The portal "
    "exposes a registry of OSI semantic models. Always call `list_models` "
    "first to discover what is available, then `list_metrics` (optionally "
    "filtered by `model`) to find the right metric, then `list_dimensions` "
    "for slicing options, and finally `query_metric` to fetch numbers from "
    "the backing Databricks engine. After receiving results, answer in plain "
    "English with concrete numbers. Cite the model name so the user can find "
    "the contract owner."
)


def _tool_specs() -> list[dict[str, Any]]:
    """OpenAI-shape tool descriptors mirroring the four MCP tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_models",
                "description": "List all OSI semantic models available to the bridge.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_metrics",
                "description": "List metrics, optionally filtered to one model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Optional model name from list_models"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_dimensions",
                "description": "List dimensions of one OSI model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "metric": {"type": "string"},
                    },
                    "required": ["model"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_metric",
                "description": "Query a metric in `model` with optional dimensions, filters, and time grain. Returns SQL and rows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "metric": {"type": "string"},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "filters": {"type": "array", "items": {"type": "object"}},
                        "time_grain": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
                        "limit": {"type": "integer"},
                    },
                    "required": ["model", "metric"],
                },
            },
        },
    ]


def _dispatch(registry: Registry, name: str, args: dict[str, Any]) -> Any:
    if name == "list_models":
        return tools.list_models(registry)
    if name == "list_metrics":
        return tools.list_metrics(registry, args.get("model"))
    if name == "list_dimensions":
        return tools.list_dimensions(registry, args["model"], args.get("metric"))
    if name == "query_metric":
        return tools.query_metric(
            registry,
            model=args["model"],
            metric=args["metric"],
            dimensions=args.get("dimensions"),
            filters=args.get("filters"),
            time_grain=args.get("time_grain"),
            limit=args.get("limit", 1000),
        )
    raise ValueError(f"Unknown tool '{name}'")


def chat(registry: Registry, question: str, *, max_steps: int = 8) -> ChatResponse:
    """Run a Gemini MCP-style tool loop in-process and return the final answer."""
    from openai import OpenAI  # lazy import keeps unit tests independent of openai

    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    model = os.environ.get("GEMINI_MODEL", "databricks-gemini-2-5-flash")
    client = OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")
    tool_specs = _tool_specs()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    trace: list[ToolCall] = []

    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_specs,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        assistant_turn: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if not msg.tool_calls:
            return ChatResponse(answer=msg.content or "", trace=trace)

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = _dispatch(registry, name, args)
                preview = json.dumps(result, default=str)[:600]
            except Exception as e:  # surface tool failures to the model
                result = {"error": str(e)}
                preview = json.dumps(result)[:600]
            trace.append(ToolCall(step=step, name=name, arguments=args, result_preview=preview))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return ChatResponse(answer="(no answer — step budget exceeded)", trace=trace)
