## =============================================================================
## te_platform/agent/mcp_bridge.py — the agent's MCP client
## =============================================================================
## GUIDE STEP   8.4 (step 1-2 and 4 of the loop)
## PURPOSE      Everything the agent needs from the MCP server, in one class:
##              - connect to the mcp service over Streamable HTTP, sending the
##                agent's own API key (the "service" principal);
##              - list the tools, keep only those the session state allows,
##                and convert them to provider-neutral ToolDefs;
##              - translate tool names between our ids and provider-safe names;
##              - call a tool and return a small, uniform outcome dict.
## USED BY      agent/loop.py (one McpBridge per turn), agent/chat_api.py (opens
##              it), agent/spec_api.py (validates specs through spec.validate.v1).
## DEPENDS ON   mcp (official SDK, >= 2.3: mcp.Client, streamable_http_client),
##              httpx2 (the HTTP library the MCP SDK is built on: its client
##              only accepts an httpx2 client, which is how we add our
##              headers), config.py,
##              providers/base.py (ToolDef).
## WHY          Architecture D8: the agent is an ordinary MCP client, so it is
##              subject to exactly the same pipeline rules (preconditions,
##              quotas, audit) as any external agent. Name mapping lives here
##              because it is a property of the MCP <-> provider boundary.
## ACTIVATE     Uncomment after the MCP server runs over HTTP (guide 4.1-4.2).
##              Test the name mapping round trip (test_platform_agent.py); the
##              loop tests (guide 8.4) use this class against the real MCP
##              server, started over HTTP inside the test.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the names McpBridge,
## to_provider_name and from_provider_name exactly: loop.py, app.py and the
## tests import them. The MCP server must already run over HTTP (4.1-4.2).
##
## Guide 8.4 (loop steps 1-2 and 4)
## [ ] 1. Imports at the top: json, re, AsyncExitStack, Any and Self, httpx2,
##        `Client` from mcp, TextContent from mcp.types,
##        streamable_http_client from mcp.client.streamable_http, ToolDef
##        (providers/base.py) and get_settings.
## [ ] 2. `_PROVIDER_NAME`: a compiled regex for ^[a-zA-Z0-9_-]{1,64}$ (the
##        names the Anthropic API accepts).
## [ ] 3. `to_provider_name(tool_id: str) -> str`: ValueError if the id
##        already contains "__"; replace every "." with "__"; ValueError if
##        the result does not match _PROVIDER_NAME.
## [ ] 4. `from_provider_name(name: str) -> str`: replace "__" back with ".".
## [ ] 5. `class McpBridge`, `__init__(self, on_behalf_of, correlation_id,
##        url=None)`: url defaults to settings.agent_mcp_url; the key is
##        settings.agent_mcp_api_key's secret value, or "" when unset. Make
##        an httpx2.AsyncClient with timeout=120.0 and the three headers:
##          | headers={"Authorization": f"Bearer {key}",
##          |          "X-TE-On-Behalf-Of": on_behalf_of,
##          |          "X-Correlation-ID": correlation_id},
##        plus self._stack = AsyncExitStack() and self._client = None, and
##        a small `_connected()` that returns self._client or raises
##        RuntimeError outside `async with`.
## [ ] 6. `__aenter__`: transport = streamable_http_client(self._url,
##        http_client=self._http); enter Client(transport) on the stack,
##        keep it in self._client, return self. `__aexit__`: close the stack,
##        then the httpx2 client.
## [ ] 7. `async tool_defs(allowed_ids) -> list[ToolDef]`: list the server's
##        tools, keep only the allowed ones IN THE ORDER of allowed_ids (skip
##        ids the server does not serve), each as ToolDef(name=
##        to_provider_name(id), description, input_schema).
## [ ] 8. `async call(provider_name, arguments) -> dict[str, Any]`: map the
##        name back, call_tool, take structured_content as payload (fallback:
##        parse the TextContent items as JSON, or {"text": ...});
##        ok = not is_error and payload.get("ok", True); return
##        {"tool", "ok", "payload", "text"} where text is the JSON payload.
## [ ] 9. Check: activate test_tool_name_mapping_round_trip and
##        test_tool_id_with_double_underscore_is_rejected, then
##          | uv run pytest tests/platform_tests/test_platform_agent.py -q
##          | uv run mypy te_platform
##        The loop tests of guide 8.4 then exercise the bridge for real.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import json
import re
from contextlib import AsyncExitStack
from typing import Any, Self

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from te_platform.agent.providers.base import ToolDef
from te_platform.config import get_settings

## --- Tool-name mapping -----------------------------------------------------------------
## Our tool ids contain dots ("verify.run.v1"), but the Anthropic API only
## accepts tool names matching ^[a-zA-Z0-9_-]{1,64}$. We replace each "." with
## "__" (two underscores). The mapping is reversible ("__" -> ".") as long as
## no tool id itself contains "__" — checked below, so a future id that breaks
## the rule fails loudly instead of being silently mis-mapped.
_PROVIDER_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def to_provider_name(tool_id: str) -> str:
    """Map our tool id ("verify.run.v1") to a provider-safe name ("verify__run__v1")."""
    if "__" in tool_id:
        raise ValueError(f"tool id {tool_id!r} must not contain '__' (reserved for the mapping)")
    name = tool_id.replace(".", "__")
    if not _PROVIDER_NAME.match(name):
        raise ValueError(f"tool id {tool_id!r} cannot be mapped to a valid provider name")
    return name


def from_provider_name(name: str) -> str:
    """Map a provider-side name back to our tool id (inverse of to_provider_name)."""
    return name.replace("__", ".")


## --- The bridge ---------------------------------------------------------------------------
class McpBridge:
    """The agent's connection to the MCP server, for one chat turn.

    Use as `async with McpBridge(...) as mcp: ...` so the connection is
    always closed, even when the turn is interrupted.
    """

    def __init__(self, on_behalf_of: str, correlation_id: str, url: str | None = None) -> None:
        s = get_settings()
        self._url = url or s.agent_mcp_url
        key = s.agent_mcp_api_key.get_secret_value() if s.agent_mcp_api_key else ""
        # The MCP SDK lets us pass our own HTTP client; that is how headers
        # are added to every request:
        # - Authorization: our SERVICE API key (proves "this is the agent");
        # - X-TE-On-Behalf-Of: the end user's principal id, so the MCP side
        #   applies that user's ownership checks and quotas. The MCP auth
        #   middleware (mcp_server/auth.py) accepts this header ONLY when
        #   the API key belongs to the service principal; from anyone else
        #   it answers 403, so it cannot be used to impersonate users.
        # - X-Correlation-ID: the id of this chat turn; the MCP server uses
        #   it for every tool call of the turn (and passes it on to jobs), so
        #   one turn can be followed through all logs (observability.py).
        self._http = httpx2.AsyncClient(
            headers={
                "Authorization": f"Bearer {key}",
                "X-TE-On-Behalf-Of": on_behalf_of,
                "X-Correlation-ID": correlation_id,
            },
            timeout=120.0,
        )
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    async def __aenter__(self) -> Self:
        transport = streamable_http_client(self._url, http_client=self._http)
        self._client = await self._stack.enter_async_context(Client(transport))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()
        await self._http.aclose()

    def _connected(self) -> Client:
        """Return the MCP client; it exists only inside `async with`."""
        if self._client is None:
            raise RuntimeError("use McpBridge inside `async with`")
        return self._client

    async def tool_defs(self, allowed_ids: list[str]) -> list[ToolDef]:
        """Return the tools offered to the model: only the allowed ones.

        They come in the ORDER of allowed_ids: a stable order keeps the
        provider's prompt cache valid.
        """
        listed = {t.name: t for t in (await self._connected().list_tools()).tools}
        defs: list[ToolDef] = []
        for tool_id in allowed_ids:
            t = listed.get(tool_id)
            if t is None:
                continue  # allowed by the policy but not served (yet): skip it
            defs.append(
                ToolDef(
                    name=to_provider_name(tool_id),
                    description=t.description or "",
                    input_schema=t.input_schema,
                )
            )
        return defs

    async def call(self, provider_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool; return {"tool": id, "ok": bool, "payload": dict, "text": str}.

        The MCP server returns a CallToolResult: `structured_content` (our
        ToolOutcome as JSON) plus `content` (text blocks) and `is_error`.
        `text` is what goes back to the model as the tool result: the full
        JSON outcome, including suggested_next or the ToolError with do_first,
        so the model can follow the policy or correct itself.
        """
        tool_id = from_provider_name(provider_name)
        result = await self._connected().call_tool(tool_id, arguments)
        payload: dict[str, Any] = result.structured_content or {}
        if not payload:
            # isinstance (not a type string) lets the type checker know that
            # only text items have a .text attribute.
            texts = [c.text for c in result.content if isinstance(c, TextContent)]
            try:
                payload = json.loads("".join(texts)) if texts else {}
            except json.JSONDecodeError:
                payload = {"text": "".join(texts)}
        ok = not result.is_error and payload.get("ok", True)
        return {
            "tool": tool_id,
            "ok": bool(ok),
            "payload": payload,
            "text": json.dumps(payload, ensure_ascii=False),
        }
