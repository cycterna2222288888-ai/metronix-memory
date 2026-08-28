#!/usr/bin/env python3
"""
LangGraph example: retrieve -> reason -> store over Metronix Memory via MCP.

Demonstrates the pattern from docs/integrations/langgraph.md: a small
StateGraph where metronix_memory_search and metronix_memory_store are loaded
as LangChain tools (via langchain-mcp-adapters) and called as explicit graph
nodes, using a stable agent_id and workspace scoping throughout.

Note: this is an MCP *client* example. Install its dependencies in a
separate environment from the Metronix backend itself -- langchain-mcp-adapters
0.3.2 pins an older MCP SDK (mcp<2) than Metronix's own server requires
(mcp>=2.0,<3), so installing both in one venv downgrades `mcp` and breaks
Metronix's own `metronix.mcp.server` import. See Troubleshooting in the guide.

Prerequisites:
    pip install langgraph langchain-mcp-adapters

    Get a PERSONAL API key, not METRONIX_MCP_API_KEY -- the shared key
    authenticates the MCP transport but never binds a principal, and every
    metronix_memory_* tool requires one (see Troubleshooting in the guide):
        curl -X POST http://localhost:8000/api/v1/users \\
          -H "Content-Type: application/json" \\
          -d '{"email":"langgraph-agent@example.com",
               "password":"<a-strong-password>","role":"admin"}'
        # -> {"...", "api_key": "mtk_..."}
    export METRONIX_MCP_TOKEN=mtk_...

Usage:
    python examples/langgraph_memory_example.py "Q3 deployment window"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, TypedDict

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph

METRONIX_URL = os.environ.get("METRONIX_URL", "http://localhost:8000")
METRONIX_MCP_TOKEN = os.environ.get("METRONIX_MCP_TOKEN", "")
AGENT_ID = "langgraph-demo-agent"  # stable id, reused across retrieve and store calls
WORKSPACE_ID = "MTRNIX"


def _parse_tool_result(raw: Any) -> dict[str, Any]:
    """Unwrap an MCP tool call result into the plain dict Metronix returned.

    langchain-mcp-adapters resolves a tool call to the raw MCP content block
    list (``[{"type": "text", "text": "<json-encoded string>"}]``), not a
    parsed dict -- decode the first text block ourselves. Skipping this and
    calling ``.get(...)`` directly on the raw result silently no-ops instead
    of raising, which is easy to misread as "zero results" or "no id".
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
        return json.loads(raw[0]["text"])
    raise TypeError(f"Unexpected MCP tool result shape: {raw!r}")


class MemoryLoopState(TypedDict):
    """Graph state threaded through retrieve -> reason -> store -> verify."""

    query: str
    search_results: list[dict[str, Any]]
    should_store: bool
    stored_id: str | None
    post_store_results: list[dict[str, Any]]


def _build_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "metronix": {
                "transport": "http",  # streamable-http; matches Metronix's /mcp endpoint
                "url": f"{METRONIX_URL}/mcp",
                "headers": {
                    "Authorization": f"Bearer {METRONIX_MCP_TOKEN}",
                    "X-Agent-Id": AGENT_ID,
                },
            }
        }
    )


async def build_graph():
    """Load Metronix's MCP tools and wire them into a retrieve/reason/store graph."""
    client = _build_client()
    tools = await client.get_tools()
    tools_by_name = {tool.name: tool for tool in tools}
    search_tool = tools_by_name["metronix_memory_search"]
    store_tool = tools_by_name["metronix_memory_store"]

    def make_retrieve_node(output_key: str, label: str):
        """Build a search-and-record node. ``retrieve`` (before store) and
        ``verify`` (after store) share this same search call and just write
        the results into different state fields, so the final summary can
        show both counts from a single run instead of the second call
        silently overwriting the first.
        """

        async def _node(state: MemoryLoopState) -> dict[str, Any]:
            raw = await search_tool.ainvoke(
                {
                    "query": state["query"],
                    "agent_id": AGENT_ID,
                    "workspace_id": WORKSPACE_ID,
                    "top_k": 5,
                }
            )
            parsed = _parse_tool_result(raw)
            results = parsed.get("results", [])
            print(f"[{label}] {len(results)} memory record(s) for: {state['query']!r}")
            return {output_key: results}

        return _node

    retrieve = make_retrieve_node("search_results", "retrieve")
    verify = make_retrieve_node("post_store_results", "verify")

    async def reason(state: MemoryLoopState) -> dict[str, Any]:
        # A real agent would put an LLM call here to decide whether the
        # retrieved records already cover the query. Kept as a deterministic
        # rule (store only when nothing was found) so this example is
        # runnable end-to-end without an extra model dependency.
        should_store = len(state["search_results"]) == 0
        print(f"[reason] should_store={should_store}")
        return {"should_store": should_store}

    async def store(state: MemoryLoopState) -> dict[str, Any]:
        raw = await store_tool.ainvoke(
            {
                "content": f"LangGraph demo fact: {state['query']}",
                "agent_id": AGENT_ID,
                "workspace_id": WORKSPACE_ID,
                "kind": "fact",
            }
        )
        parsed = _parse_tool_result(raw)
        stored_id = parsed.get("id")
        print(f"[store] stored memory id={stored_id}")
        return {"stored_id": stored_id}

    def route_after_reason(state: MemoryLoopState) -> str:
        return "store" if state["should_store"] else END

    graph = StateGraph(MemoryLoopState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("reason", reason)
    graph.add_node("store", store)
    graph.add_node("verify", verify)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "reason")
    graph.add_conditional_edges("reason", route_after_reason, {"store": "store", END: END})
    graph.add_edge("store", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


async def main() -> None:
    if not METRONIX_MCP_TOKEN:
        print("Set METRONIX_MCP_TOKEN to a PERSONAL api key -- see the module")
        print("docstring for how to mint one. METRONIX_MCP_API_KEY (the shared")
        print("key) will not work here: memory tools reject it with AUTH_REQUIRED.")
        sys.exit(1)

    query = sys.argv[1] if len(sys.argv) > 1 else "Q3 deployment window for the LangGraph demo"
    app = await build_graph()
    result = await app.ainvoke(
        {
            "query": query,
            "search_results": [],
            "should_store": False,
            "stored_id": None,
            "post_store_results": [],
        }
    )

    print("\n--- final state ---")
    print(f"query:              {result['query']}")
    print(f"found before store: {len(result['search_results'])} record(s)")
    print(f"stored_id:          {result['stored_id']}")
    if result["stored_id"] is not None:
        print(f"found after store:  {len(result['post_store_results'])} record(s)")


if __name__ == "__main__":
    asyncio.run(main())
