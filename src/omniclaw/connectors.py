"""Connector layer: Composio (hosted tool catalog) and Nango (curated tools, see nango_tools.py)."""

import logging
import re
from typing import Any

import httpx

from omniclaw.catalog import ToolProvider, clean_parameters
from omniclaw.config import Settings
from omniclaw.nango_tools import NangoProvider
from omniclaw.tools import Tool, ToolContext

log = logging.getLogger(__name__)

COMPOSIO_PAGE_SIZE = 100
COMPOSIO_MAX_PAGES = 12

_READ_VERBS = frozenset(
    {
        "FETCH",
        "LIST",
        "GET",
        "SEARCH",
        "FIND",
        "READ",
        "RETRIEVE",
        "VIEW",
        "LOOKUP",
        "COUNT",
        "CHECK",
        "QUERY",
    }
)
_WRITE_VERBS = frozenset(
    {
        "SEND",
        "CREATE",
        "DELETE",
        "UPDATE",
        "POST",
        "ADD",
        "REMOVE",
        "REPLY",
        "FORWARD",
        "PATCH",
        "MODIFY",
        "MOVE",
        "INSERT",
        "EDIT",
        "TRASH",
        "ARCHIVE",
        "STAR",
        "UNSTAR",
        "MERGE",
        "CLOSE",
        "REOPEN",
        "ASSIGN",
        "LIKE",
        "FOLLOW",
        "UNFOLLOW",
        "COMMENT",
        "SET",
        "UPLOAD",
        "PUBLISH",
        "SCHEDULE",
        "INVITE",
        "ACCEPT",
        "DECLINE",
        "SUBMIT",
        "CONNECT",
        "DISCONNECT",
        "INITIATE",
        "FORK",
        "REVOKE",
        "CANCEL",
        "EXECUTE",
        "RUN",
        "TRIGGER",
        "SUBSCRIBE",
        "UNSUBSCRIBE",
        "APPEND",
        "WRITE",
        "SWIPE",
        "PIN",
        "UNPIN",
        "REACT",
        "REPLACE",
        "RENAME",
        "COPY",
        "SHARE",
        "TRANSFER",
        "LOCK",
        "UNLOCK",
        "ENABLE",
        "DISABLE",
    }
)


def composio_needs_approval(args: dict[str, Any]) -> bool:
    """Only clearly read-only slugs skip approval. Any write verb always needs the owner."""
    tokens = set(re.split(r"[^A-Z0-9]+", str(args.get("tool_slug", "")).upper()))
    if tokens & _WRITE_VERBS:
        return True
    return not (tokens & _READ_VERBS)


def composio_describe(args: dict[str, Any]) -> str:
    """Make the approval prompt for Composio human-readable instead of raw JSON."""
    slug = args.get("tool_slug", "Unknown Action")
    arguments = args.get("arguments") or {}
    lines = [f"Run {slug}"]
    lines.extend(f"- {key}: {str(value)[:300]}" for key, value in arguments.items())
    return "\n".join(lines)


def nango_needs_approval(args: dict[str, Any]) -> bool:
    return str(args.get("method", "GET")).upper() != "GET"


def nango_describe(args: dict[str, Any]) -> str:
    """Make the approval prompt for Nango human-readable instead of raw JSON."""
    method = args.get("method", "GET")
    path = args.get("path", "")
    return f"Make a {method} request to {path}"


class ComposioProvider:
    """Composio tools. Each tool carries its real input schema so the model gets arguments right."""

    name = "composio"

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._base = settings.composio_base_url.rstrip("/")
        self._headers = {"x-api-key": settings.composio_api_key.get_secret_value()}

    async def toolkits(self) -> list[str]:
        """Toolkits with an active connected account. Empty means unknown."""
        try:
            response = await self._http.get(
                f"{self._base}/api/v3/connected_accounts",
                headers=self._headers,
                params={"user_ids": self._s.composio_user_id, "statuses": "ACTIVE", "limit": 100},
            )
        except httpx.HTTPError:
            log.warning("Composio connected accounts request failed", exc_info=True)
            return []
        if not response.is_success:
            log.warning("Composio connected accounts HTTP %s", response.status_code)
            return []
        names: list[str] = []
        for item in response.json().get("items", []):
            slug = str((item.get("toolkit") or {}).get("slug") or "").lower()
            if slug and slug not in names:
                names.append(slug)
        return names

    async def load(self, toolkit: str) -> list[Tool]:
        found: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        for page in range(1, COMPOSIO_MAX_PAGES + 1):
            params: dict[str, Any] = {
                "toolkit_slug": toolkit,
                "limit": COMPOSIO_PAGE_SIZE,
                "page": page,
            }
            if cursor:
                params["cursor"] = cursor
            response = await self._http.get(
                f"{self._base}/api/v3/tools", headers=self._headers, params=params
            )
            if not response.is_success:
                if found:
                    break
                raise RuntimeError(
                    f"Composio tools HTTP {response.status_code}: {response.text[:300]}"
                )
            data = response.json()
            batch = [item for item in data.get("items", []) if item.get("slug")]
            new = [item for item in batch if item["slug"] not in found]
            for item in new:
                found[item["slug"]] = item
            cursor = data.get("next_cursor")
            total_pages = data.get("total_pages") or 0
            more = bool(cursor) or page < total_pages
            if not total_pages and not cursor:
                more = len(batch) >= COMPOSIO_PAGE_SIZE
            if not new or not more:
                break
        return [self._tool(item) for item in found.values()]

    async def execute(self, slug: str, arguments: dict[str, Any]) -> Any:
        response = await self._http.post(
            f"{self._base}/api/v3/tools/execute/{slug}",
            headers=self._headers,
            json={"user_id": self._s.composio_user_id, "arguments": arguments},
        )
        if not response.is_success:
            return {"error": f"HTTP {response.status_code}", "body": response.text[:2000]}
        return response.json()

    def _tool(self, item: dict[str, Any]) -> Tool:
        slug = str(item["slug"])
        description = str(item.get("description") or item.get("name") or slug)[:400]

        async def handler(args: dict[str, Any], ctx: ToolContext) -> Any:
            return await self.execute(slug, args)

        return Tool(
            name=slug[:64],
            description=description,
            parameters=clean_parameters(item.get("input_parameters") or item.get("parameters")),
            handler=handler,
            needs_approval=lambda _args: composio_needs_approval({"tool_slug": slug}),
            describe=lambda args: composio_describe({"tool_slug": slug, "arguments": args}),
        )


def build_providers(settings: Settings, http: httpx.AsyncClient) -> list[ToolProvider]:
    """Providers follow whatever is configured in the environment."""
    providers: list[ToolProvider] = []
    if settings.composio_api_key.get_secret_value():
        providers.append(ComposioProvider(settings, http))
    if settings.nango_secret_key.get_secret_value():
        providers.append(NangoProvider(settings, http))
    return providers


def build_connector_tools(settings: Settings, http: httpx.AsyncClient) -> list[Tool]:
    """Static escape-hatch tools. Discoverable tools come from build_providers."""
    tools: list[Tool] = []

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
                description=(
                    "Last-resort generic call to a third-party REST API through the Nango proxy. "
                    "Prefer the dedicated tools; use this only when none of them fits."
                ),
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
