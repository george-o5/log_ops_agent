"""
src/agent.py
------------
Handles all AI logic: tool definitions, prompt construction,
and calls to Anthropic (Claude) via MCP.
"""

import os
from typing import Any
import anthropic
from src.splunk_client import SplunkClient

# ── Clients ────────────────────────────────────────────────────────────────────
_anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
_splunk = SplunkClient()

# ── Tool Definitions (MCP-style) ───────────────────────────────────────────────
TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_splunk_search",
        "description": "Execute a Splunk SPL search query and return results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The SPL search query to run."},
                "earliest": {"type": "string", "description": "Earliest time (e.g. '-1h', '-24h')."},
                "latest": {"type": "string", "description": "Latest time, default 'now'."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_alerts",
        "description": "Fetch recent Splunk alerts / triggered alert actions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of alerts to return (default 10)."},
            },
        },
    },
]

SYSTEM_PROMPT = """You are Splunk Agentic Ops — an expert AI assistant embedded inside a Splunk Cloud environment.
You can run real SPL searches, retrieve alerts, and surface insights to help operations teams respond faster.
Always explain what you are doing before calling a tool. Keep answers concise and actionable."""


def _dispatch_tool(name: str, inputs: dict[str, Any]) -> str:
    """Route a tool call to the correct SplunkClient method."""
    if name == "run_splunk_search":
        return _splunk.run_search(
            query=inputs["query"],
            earliest=inputs.get("earliest", "-1h"),
            latest=inputs.get("latest", "now"),
        )
    if name == "get_alerts":
        return _splunk.get_alerts(limit=inputs.get("limit", 10))
    return f"[Tool '{name}' not implemented]"


def run_agent(
    user_message: str,
    history: list[dict],
    model: str = "claude-3-5-sonnet-20241022",
    max_tokens: int = 1024,
) -> str:
    """
    Core agentic loop.
    Sends message -> handles tool calls -> returns final text response.
    """
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m["role"] in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": user_message})

    while True:
        response = _anthropic.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "[No response generated]"

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _dispatch_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            return "[Unexpected stop reason from model]"
