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


def nango_needs_approval(args: dict[str, Any]) -> bool:
    return str(args.get("method", "GET")).upper() != "GET"


def build_connector_tools(settings: Settings, http: httpx.AsyncClient) -> list[Tool]:
    tools: list[Tool] = []

    composio_key = settings.composio_api_key.get_secret_value()
    if composio_key:
        base = settings.composio_base_url.rstrip("/")
        headers = {"x-api-key": composio_key}

        async def composio_list_tools(args: dict[str, Any], ctx: ToolContext) -> Any:
            response = await http.get(
                f"{base}/api/v3/tools",
                headers=headers,
                params={"toolkit_slug": args["toolkit"], "limit": 25},
            )
            response.raise_for_status()
            items = response.json().get("items", [])
            return [
                {"slug": item.get("slug"), "description": (item.get("description") or "")[:200]}
                for item in items
            ]

        async def composio_execute(args: dict[str, Any], ctx: ToolContext) -> Any:
            response = await http.post(
                f"{base}/api/v3/tools/execute/{args['tool_slug']}",
                headers=headers,
                json={"user_id": settings.composio_user_id, "arguments": args.get("arguments", {})},
            )
            response.raise_for_status()
            return response.json()

        tools.append(
            Tool(
                name="composio_list_tools",
                description=(
                    "List available Composio tool slugs for a toolkit "
                    "(for example gmail, googlecalendar, linkedin, instagram)."
                ),
                parameters={
                    "type": "object",
                    "properties": {"toolkit": {"type": "string"}},
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
            )
        )

    return tools
