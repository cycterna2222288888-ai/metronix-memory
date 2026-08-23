# LangGraph

Wire Metronix Memory into a LangGraph agent as explicit tool nodes (via MCP), or as a
plain RAG chat step (via `/v1`).

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples generally use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored. **Exception, verified by actually running this guide's
> example:** every `metronix_memory_*` tool (`metronix_memory_search`,
> `metronix_memory_store`, and friends) requires an authenticated *principal* and
> rejects the shared key outright with `AUTH_REQUIRED` — see Setup step 2 and
> Troubleshooting below.

## Prerequisites

- Metronix Memory running and accessible (`curl http://localhost:8000/health` returns OK)
- Python 3.10+ (`langgraph` requirement; the repo itself targets 3.12+)
- `pip install langgraph langchain-mcp-adapters` — official packages, not community forks.
  Verified current as of this guide: `langgraph>=1.2`, `langchain-mcp-adapters>=0.3`.
  **Install these in a separate environment from the Metronix backend itself** —
  `langchain-mcp-adapters` 0.3.2 pins an older MCP SDK than Metronix requires
  (it downgrades `mcp` from the `>=2.0,<3` this repo needs down to `1.x`), which breaks
  Metronix's own `metronix.mcp.server` import if the two end up in the same venv. This
  is a client library; it has no reason to share a virtualenv with the server.
- A **personal API key** for the memory tools — see Setup step 2. The shared
  `METRONIX_MCP_API_KEY` does *not* work here (see the callout above);
  `METRONIX_OPENAI_COMPAT_KEY` for `/v1`

## When to use MCP vs `/v1`

Both work with LangGraph. Pick based on what the graph needs to *do* with memory, not
just talk about it:

- **`/v1` (OpenAI-compatible)** — use when a graph node just needs a grounded chat
  response and doesn't need to reason about individual memory calls. Point a
  `ChatOpenAI`-style node at Metronix's `/v1` endpoint; retrieval happens server-side,
  invisibly to the graph.
- **MCP (via `langchain-mcp-adapters`)** — use when the graph itself needs to decide
  *when* to retrieve or store — e.g. a `retrieve → reason → store` loop with conditional
  edges, where `metronix_memory_search` and `metronix_memory_store` are explicit tool
  nodes the graph can branch on. This is the shape most "agent with durable memory"
  graphs want, and it's what the example below builds.

Default recommendation: start with MCP if the graph's job centers on memory. Reach for
`/v1` only if Metronix is one RAG-chat step among other unrelated tools.

## Setup

1. Get the backend running (see the [main README](../../README.md)) and confirm
   `curl http://localhost:8000/health` returns `{"status":"ok"}`.
2. Get a **personal API key** — the credential the memory tools actually accept.
   Locally (`AUTH_ENABLED=false`), any request is trusted as admin, so this works
   with no login step:
   ```bash
   curl -X POST http://localhost:8000/api/v1/users \
     -H "Content-Type: application/json" \
     -d '{"email":"langgraph-agent@example.com","password":"<a-strong-password>","role":"admin"}'
   # -> {"...", "api_key": "mtk_..."}  <- this is METRONIX_MCP_TOKEN below
   ```
   Hosted (`AUTH_ENABLED=true`): use a user JWT instead (log in via `/api/v1/auth/login`),
   or have an admin issue a personal key via `POST /api/v1/users/{user_id}/api-keys`.
3. Install the two packages (in their own environment — see Prerequisites):
   ```bash
   pip install langgraph langchain-mcp-adapters
   ```
4. Connect with `MultiServerMCPClient` and load Metronix's tools:
   ```python
   from langchain_mcp_adapters.client import MultiServerMCPClient

   client = MultiServerMCPClient(
       {
           "metronix": {
               "transport": "http",  # streamable-http; matches Metronix's /mcp endpoint
               "url": "http://localhost:8000/mcp",
               "headers": {
                   "Authorization": f"Bearer {METRONIX_MCP_TOKEN}",
                   "X-Agent-Id": "langgraph-quickstart-agent",  # keep this stable per agent
               },
           }
       }
   )
   tools = await client.get_tools()
   ```
   `headers` only applies to `http`/`sse` transports (not `stdio`) — both
   `Authorization` and the required `X-Agent-Id` pass through cleanly here since
   Metronix's MCP endpoint is `streamable-http`.
5. Bind the loaded tools into a `StateGraph` — see
   [`examples/langgraph_memory_example.py`](../../examples/langgraph_memory_example.py)
   for a full retrieve → reason → store graph using `metronix_memory_search` and
   `metronix_memory_store` as tool nodes with a stable `agent_id` and
   `workspace_id="MTRNIX"`.
6. One more adapter quirk worth knowing before you write a tool node:
   `langchain-mcp-adapters` tool calls resolve to the *raw* MCP content block list
   (`[{"type": "text", "text": "<json-encoded string>"}]`), not a parsed dict — decode
   `result[0]["text"]` with `json.loads` yourself. The example wraps this in a
   `_parse_tool_result()` helper; without it, `.get("id")` / `.get("results")` silently
   no-op instead of raising, which is easy to misread as "zero results" rather than a
   parsing bug.

## Verify

After setup, confirm the connection works:

1. Send a GET request to `http://localhost:8000/health` and confirm a 200 OK response.
2. Run `python examples/langgraph_memory_example.py` — it should print a stored memory
   ID from `metronix_memory_store` and then a matching result from
   `metronix_memory_search` in the same run.
3. Alternatively, call `client.get_tools()` directly and confirm
   `metronix_status`/`metronix_memory_search`/`metronix_memory_store` all appear in the
   returned tool list.

## Troubleshooting

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).

**Authentication errors on `/mcp`:** In local mode (`AUTH_ENABLED=false`), confirm the
`Authorization: Bearer <key>` header matches `METRONIX_MCP_API_KEY` in `.env`. In hosted
mode (`AUTH_ENABLED=true`), the shared key is ignored — pass a user JWT instead. Either
way, confirm `X-Agent-Id` is included in every request.

**`AUTH_REQUIRED: unauthorized agent memory access` calling `metronix_memory_search` /
`metronix_memory_store` (but `metronix_status` works fine with the same key):** you're
using the shared `METRONIX_MCP_API_KEY`. It authenticates the MCP *transport* but never
binds a request principal, and every `metronix_memory_*` tool requires one
(`require_agent_access` in `mcp/tools/_agent_access.py`) — tools without an ownership
concept, like `metronix_status`, don't have this check, which is why they keep working
and the memory tools don't. Swap in a personal API key (Setup step 2) or a JWT.

**Tools not appearing / empty list from `client.get_tools()`:** Double-check `transport`
is `"http"` (or `"streamable_http"`) and not `"stdio"` — `headers` (and therefore auth)
is silently dropped on `stdio`, which usually shows up as an auth error further down
rather than a config error here.

**`asyncio` errors calling `client.get_tools()` from a sync script:** `MultiServerMCPClient`
is async-only; run it inside `asyncio.run(...)` or an existing event loop, as the example
does.

## Recommendation

Building a memory-centric agent graph — one where retrieve/store decisions are part of
the graph's own logic? Start with MCP via `langchain-mcp-adapters`.
Using LangGraph mainly to orchestrate a chat flow where Metronix is just the RAG
backend? Start with `/v1` and add MCP later only if you need explicit tool-level control.
