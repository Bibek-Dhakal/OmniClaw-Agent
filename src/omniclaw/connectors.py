"""Connector tools: Composio (tool execution) and Nango (authenticated API proxy)."""

import re
from typing import Any

import httpx

from omniclaw.config import Settings
from omniclaw.tools import Tool, ToolContext

_READ_ONLY = re.compile(r"FETCH|LIST|GET|SEARCH|FIND|READ", re.IGNORECASE)


def composio_needs_approval(args: dict[str, Any]) -> bool:
    """Anything that is not clearly a read needs owner approval."""
    return not _READ_ONLY.search(str(args.get("tool_slug", "")))


def composio_describe(args: dict[str, Any]) -> str:
    """Make the approval prompt for Composio human-readable instead of raw JSON."""
    slug = args.get("tool_slug", "Unknown Action")
    kwargs = args.get("arguments", {})
    return f"Use '{slug}'\nDetails: {kwargs}"


def nango_needs_approval(args: dict[str, Any]) -> bool:
    return str(args.get("method", "GET")).upper() != "GET"


def nango_describe(args: dict[str, Any]) -> str:
    """Make the approval prompt for Nango human-readable instead of raw JSON."""
    method = args.get("method", "GET")
    path = args.get("path", "")
    return f"Make a {method} request to {path}"


def build_connector_tools(settings: Settings, http: httpx.AsyncClient) -> list[Tool]:
    tools: list[Tool] = []

    composio_key = settings.composio_api_key.get_secret_value()
    if composio_key:
        base = settings.composio_base_url.rstrip("/")
        headers = {"x-api-key": composio_key}

        async def composio_list_tools(args: dict[str, Any], ctx: ToolContext) -> Any:
            items = []
            page = 1

            # Paginate through the Composio API to ensure we get ALL tools for massive APIs like GitHub
            while True:
                response = await http.get(
                    f"{base}/api/v3/tools",
                    headers=headers,
                    params={"toolkit_slug": args["toolkit"], "limit": 100, "page": page},
                )
                if not response.is_success:
                    if not items:
                        return {
                            "error": f"HTTP {response.status_code}",
                            "body": response.text[:2000],
                        }
                    break

                page_items = response.json().get("items", [])
                if not page_items:
                    break

                items.extend(page_items)
                if len(page_items) < 100:
                    break

                page += 1
                if page > 20:  # Safety limit to prevent infinite loops (2000 tools max)
                    break

            # Smart Multi-Word Fuzzy Search
            # Splits "list repos" into ["list", "repos"] and ensures ALL words are present
            raw_query = args.get("query", "").lower()
            query_words = [w.strip() for w in raw_query.split() if w.strip()]

            results = []
            for item in items:
                slug = (item.get("slug") or "").lower()
                desc = (item.get("description") or "").lower()
                search_text = f"{slug} {desc}"

                # If agent provided a search query, ensure ALL words are in the text
                if query_words and not all(word in search_text for word in query_words):
                    continue

                results.append(
                    {"slug": item.get("slug"), "description": (item.get("description") or "")[:200]}
                )

            if not results:
                return {
                    "error": f"No tools found matching '{raw_query}'. Try broader keywords like 'list', 'get', or 'create'."
                }

            # Return max 50 to keep the LLM context clean
            return results[:50]

        async def composio_execute(args: dict[str, Any], ctx: ToolContext) -> Any:
            response = await http.post(
                f"{base}/api/v3/tools/execute/{args['tool_slug']}",
                headers=headers,
                json={"user_id": settings.composio_user_id, "arguments": args.get("arguments", {})},
            )
            if not response.is_success:
                return {"error": f"HTTP {response.status_code}", "body": response.text[:2000]}
            return response.json()

        tools.append(
            Tool(
                name="composio_list_tools",
                description=(
                    "List available Composio tool slugs for a toolkit "
                    "(for example gmail, googlecalendar, linkedin, instagram). "
                    "Use the 'query' parameter to search for specific actions. Use broad keywords like 'list repositories'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "toolkit": {"type": "string"},
                        "query": {
                            "type": "string",
                            "description": "Optional search terms. Uses fuzzy matching (e.g., 'list repositories' finds tools containing both words).",
                        },
                    },
                    "required": ["toolkit"],
                },
                handler=composio_list_tools,
            )
        )
        tools.append(
            Tool(
                name="composio_execute",
                description=(
                    "Execute a Composio tool by slug with JSON arguments. "
                    "Use composio_list_tools first if you do not know the slug."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "tool_slug": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool_slug"],
                },
                handler=composio_execute,
                needs_approval=composio_needs_approval,
                describe=composio_describe,
            )
        )

    nango_key = settings.nango_secret_key.get_secret_value()
    if nango_key:
        nango_base = settings.nango_base_url.rstrip("/")

        async def nango_request(args: dict[str, Any], ctx: ToolContext) -> Any:
            connection_id = args.get("connection_id") or settings.nango_connection_id
            response = await http.request(
                str(args.get("method", "GET")).upper(),
                f"{nango_base}/proxy/{str(args['path']).lstrip('/')}",
                headers={
                    "Authorization": f"Bearer {nango_key}",
                    "Connection-Id": connection_id,
                    "Provider-Config-Key": args["provider_config_key"],
                },
                params=args.get("params"),
                json=args.get("body"),
            )
            return {"status": response.status_code, "body": response.text[:6000]}

        tools.append(
            Tool(
                name="nango_request",
                description="Call a third-party REST API through the Nango authenticated proxy.",
                parameters={
                    "type": "object",
                    "properties": {
                        "provider_config_key": {"type": "string"},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        },
                        "path": {"type": "string"},
                        "params": {"type": "object"},
                        "body": {"type": "object"},
                        "connection_id": {"type": "string"},
                    },
                    "required": ["provider_config_key", "path"],
                },
                handler=nango_request,
                needs_approval=nango_needs_approval,
                describe=nango_describe,
            )
        )

    return tools
