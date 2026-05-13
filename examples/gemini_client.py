"""Databricks-hosted Gemini ↔ OSI Bridge (MCP).

Uses the OpenAI-compatible Databricks Model Serving endpoint
(`/serving-endpoints/<model>/invocations` via the OpenAI SDK) and runs a
manual MCP tool-calling loop because the Databricks endpoint does not
implement Google's native MCP auto-tool-calling.

Usage:
    python examples/gemini_client.py "What was revenue by priority last year?"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client
from openai import OpenAI

load_dotenv(override=True)


def mcp_tool_to_openai(tool) -> dict:
    """Convert an MCP tool descriptor to OpenAI function-tool schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }


def mcp_result_text(result) -> str:
    """Extract text content from an MCP CallToolResult."""
    parts = []
    for c in (result.content or []):
        if hasattr(c, "text") and c.text:
            parts.append(c.text)
        elif isinstance(c, dict) and c.get("text"):
            parts.append(c["text"])
    return "\n".join(parts) or json.dumps({"isError": result.isError})


async def ask(question: str) -> None:
    bridge_url = os.environ.get("OSI_BRIDGE_URL", "http://localhost:8000/sse")
    model = os.environ.get("GEMINI_MODEL", "databricks-gemini-2-5-flash")
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]

    client = OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")

    async with sse_client(bridge_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [mcp_tool_to_openai(t) for t in tools_resp.tools]
            print(f"[client] {len(tools)} MCP tools available: {[t['function']['name'] for t in tools]}")

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a data analyst. The OSI Bridge serves several "
                        "semantic models — call list_models first to see them, "
                        "then list_metrics (optionally filtered by model) to find "
                        "the right metric, list_dimensions(model=...) for slicing "
                        "options, and finally query_metric(model=..., metric=...) "
                        "to fetch numbers. After receiving query results, "
                        "summarise them in plain English with concrete numbers."
                    ),
                },
                {"role": "user", "content": question},
            ]

            for step in range(8):  # safety bound
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                )
                msg = resp.choices[0].message
                # Echo assistant turn
                assistant_turn = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    assistant_turn["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                messages.append(assistant_turn)

                if not msg.tool_calls:
                    print("\n=== Gemini answer ===")
                    print(msg.content)
                    return

                # Execute each tool call via MCP and append results
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    print(f"[client] → {name}({json.dumps(args)[:120]})")
                    result = await session.call_tool(name, args)
                    text = mcp_result_text(result)
                    print(f"[client] ← {text[:200]}{'…' if len(text)>200 else ''}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": text,
                    })

            print("[client] hit step bound without final answer", file=sys.stderr)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "What was total revenue by order priority?"
    asyncio.run(ask(q))
