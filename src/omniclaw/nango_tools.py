"""Curated Nango tools.

Nango is an authenticated API proxy and has no tool catalog of its own, so the tools the agent
can use through Nango are defined here. Each tool maps its arguments onto one proxied REST call
and trims the response so the model sees only useful fields.
"""

import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

import httpx

from omniclaw.catalog import clean_parameters
from omniclaw.config import Settings
from omniclaw.tools import Tool, ToolContext

log = logging.getLogger(__name__)

CONNECTION_TTL_SECONDS = 300

# Router-facing toolkit name -> Nango provider id. Edit if your integration ids differ.
PROVIDERS = {
    "github": "github",
    "gmail": "google-mail",
    "googlecalendar": "google-calendar",
    "slack": "slack",
}


@dataclass(frozen=True)
class NangoSpec:
    name: str
    toolkit: str
    description: str
    method: str
    path: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...] = ()
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()
    query_defaults: dict[str, Any] = field(default_factory=dict)
    fields: tuple[str, ...] = ()
    list_key: str = "items"
    prepare: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    build_body: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    shape: Callable[[Any], Any] | None = None


def _pick(item: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(item, dict):
        return item
    return {key: item[key] for key in keys if key in item}


def _slim(data: Any, keys: tuple[str, ...], list_key: str) -> Any:
    """Keep only the listed fields so results stay small enough for the model."""
    if not keys:
        return data
    if isinstance(data, list):
        return [_pick(item, keys) for item in data]
    if isinstance(data, dict) and isinstance(data.get(list_key), list):
        slim = {k: v for k, v in data.items() if k in ("total_count", "nextPageToken")}
        slim[list_key] = [_pick(item, keys) for item in data[list_key]]
        return slim
    return _pick(data, keys)


def _gmail_body(args: dict[str, Any]) -> dict[str, Any]:
    message = EmailMessage()
    message["To"] = str(args["to"])
    message["Subject"] = str(args["subject"])
    message.set_content(str(args["body"]))
    return {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}


def _gmail_summary(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    payload = data.get("payload") or {}
    headers = {
        str(h.get("name", "")).lower(): h.get("value", "")
        for h in payload.get("headers", [])
        if isinstance(h, dict)
    }
    return {
        "id": data.get("id"),
        "thread_id": data.get("threadId"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "subject": headers.get("subject"),
        "date": headers.get("date"),
        "snippet": data.get("snippet"),
        "labels": data.get("labelIds"),
    }


def _events_prepare(args: dict[str, Any]) -> dict[str, Any]:
    # Without timeMin Google lists events from the beginning of time, oldest first.
    return {"timeMin": datetime.now(UTC).isoformat(timespec="seconds"), **args}


def _event_body(args: dict[str, Any]) -> dict[str, Any]:
    zone = args.get("time_zone")

    def moment(value: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"dateTime": str(value)}
        if zone:
            result["timeZone"] = str(zone)
        return result

    body: dict[str, Any] = {
        "summary": args["summary"],
        "start": moment(args["start"]),
        "end": moment(args["end"]),
    }
    for key in ("description", "location"):
        if args.get(key):
            body[key] = args[key]
    if args.get("attendees"):
        emails = [e.strip() for e in str(args["attendees"]).split(",") if e.strip()]
        body["attendees"] = [{"email": email} for email in emails]
    return body


REPO_FIELDS = (
    "name",
    "full_name",
    "description",
    "private",
    "language",
    "stargazers_count",
    "updated_at",
    "pushed_at",
    "html_url",
)

SPECS: tuple[NangoSpec, ...] = (
    # GitHub
    NangoSpec(
        name="github_list_my_repos",
        toolkit="github",
        description=(
            "List repositories of the authenticated GitHub user. Newest activity comes first by "
            "default, so 'most recently updated repos' only needs per_page."
        ),
        method="GET",
        path="/user/repos",
        properties={
            "per_page": {"type": "integer", "description": "How many repositories (1-100)."},
            "sort": {
                "type": "string",
                "enum": ["created", "updated", "pushed", "full_name"],
                "description": "Sort field (default updated).",
            },
            "direction": {
                "type": "string",
                "enum": ["asc", "desc"],
                "description": "Sort direction (default desc, newest first).",
            },
            "visibility": {
                "type": "string",
                "enum": ["all", "public", "private"],
                "description": "Filter by visibility.",
            },
        },
        query_params=("per_page", "sort", "direction", "visibility"),
        query_defaults={"sort": "updated", "direction": "desc", "per_page": 10},
        fields=REPO_FIELDS,
    ),
    NangoSpec(
        name="github_search_repos",
        toolkit="github",
        description="Search public GitHub repositories with GitHub search syntax.",
        method="GET",
        path="/search/repositories",
        properties={
            "q": {
                "type": "string",
                "description": "Search query, for example 'user:octocat language:python'.",
            },
            "sort": {"type": "string", "enum": ["stars", "forks", "updated"]},
            "order": {"type": "string", "enum": ["asc", "desc"]},
            "per_page": {"type": "integer", "description": "How many results (1-100)."},
        },
        required=("q",),
        query_params=("q", "sort", "order", "per_page"),
        query_defaults={"per_page": 10},
        fields=REPO_FIELDS,
    ),
    NangoSpec(
        name="github_get_repo",
        toolkit="github",
        description="Get details of one GitHub repository.",
        method="GET",
        path="/repos/{owner}/{repo}",
        properties={
            "owner": {"type": "string", "description": "Repository owner (user or org)."},
            "repo": {"type": "string", "description": "Repository name."},
        },
        required=("owner", "repo"),
        path_params=("owner", "repo"),
        fields=(*REPO_FIELDS, "default_branch", "open_issues_count", "forks_count", "created_at"),
    ),
    NangoSpec(
        name="github_list_issues",
        toolkit="github",
        description="List issues of a GitHub repository. Pull requests also appear in this list.",
        method="GET",
        path="/repos/{owner}/{repo}/issues",
        properties={
            "owner": {"type": "string", "description": "Repository owner."},
            "repo": {"type": "string", "description": "Repository name."},
            "state": {"type": "string", "enum": ["open", "closed", "all"]},
            "labels": {"type": "string", "description": "Comma-separated label names."},
            "sort": {"type": "string", "enum": ["created", "updated", "comments"]},
            "direction": {"type": "string", "enum": ["asc", "desc"]},
            "per_page": {"type": "integer", "description": "How many issues (1-100)."},
        },
        required=("owner", "repo"),
        path_params=("owner", "repo"),
        query_params=("state", "labels", "sort", "direction", "per_page"),
        query_defaults={"per_page": 10},
        fields=("number", "title", "state", "html_url", "created_at", "updated_at", "comments"),
    ),
    NangoSpec(
        name="github_create_issue",
        toolkit="github",
        description="Create an issue in a GitHub repository.",
        method="POST",
        path="/repos/{owner}/{repo}/issues",
        properties={
            "owner": {"type": "string", "description": "Repository owner."},
            "repo": {"type": "string", "description": "Repository name."},
            "title": {"type": "string", "description": "Issue title."},
            "body": {"type": "string", "description": "Issue description in Markdown."},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        required=("owner", "repo", "title"),
        path_params=("owner", "repo"),
        body_params=("title", "body", "labels"),
        fields=("number", "title", "html_url"),
    ),
    NangoSpec(
        name="github_list_pull_requests",
        toolkit="github",
        description="List pull requests of a GitHub repository.",
        method="GET",
        path="/repos/{owner}/{repo}/pulls",
        properties={
            "owner": {"type": "string", "description": "Repository owner."},
            "repo": {"type": "string", "description": "Repository name."},
            "state": {"type": "string", "enum": ["open", "closed", "all"]},
            "sort": {"type": "string", "enum": ["created", "updated", "popularity"]},
            "direction": {"type": "string", "enum": ["asc", "desc"]},
            "per_page": {"type": "integer", "description": "How many pull requests (1-100)."},
        },
        required=("owner", "repo"),
        path_params=("owner", "repo"),
        query_params=("state", "sort", "direction", "per_page"),
        query_defaults={"per_page": 10},
        fields=("number", "title", "state", "draft", "html_url", "created_at", "updated_at"),
    ),
    # Gmail
    NangoSpec(
        name="gmail_list_messages",
        toolkit="gmail",
        description=(
            "List Gmail messages matching a Gmail search query. Returns message ids only; call "
            "gmail_get_message for each id to read sender, subject and snippet."
        ),
        method="GET",
        path="/gmail/v1/users/me/messages",
        properties={
            "q": {
                "type": "string",
                "description": "Gmail search, for example 'is:unread newer_than:2d from:alice'.",
            },
            "maxResults": {"type": "integer", "description": "How many messages (1-50)."},
        },
        query_params=("q", "maxResults"),
        query_defaults={"maxResults": 10},
    ),
    NangoSpec(
        name="gmail_get_message",
        toolkit="gmail",
        description="Read one Gmail message by id: sender, recipients, subject, date and snippet.",
        method="GET",
        path="/gmail/v1/users/me/messages/{id}",
        properties={
            "id": {"type": "string", "description": "Message id from gmail_list_messages."}
        },
        required=("id",),
        path_params=("id",),
        query_defaults={"format": "metadata"},
        shape=_gmail_summary,
    ),
    NangoSpec(
        name="gmail_send_message",
        toolkit="gmail",
        description="Send a plain-text email from the owner's Gmail account.",
        method="POST",
        path="/gmail/v1/users/me/messages/send",
        properties={
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Email subject."},
            "body": {"type": "string", "description": "Plain-text email body."},
        },
        required=("to", "subject", "body"),
        build_body=_gmail_body,
        fields=("id", "threadId"),
    ),
    # Google Calendar
    NangoSpec(
        name="calendar_list_events",
        toolkit="googlecalendar",
        description=(
            "List upcoming events on the primary Google Calendar, soonest first. Starts from now "
            "unless timeMin is given."
        ),
        method="GET",
        path="/calendar/v3/calendars/primary/events",
        properties={
            "timeMin": {
                "type": "string",
                "description": "RFC3339 start, for example 2026-10-13T00:00:00Z.",
            },
            "timeMax": {"type": "string", "description": "RFC3339 end."},
            "maxResults": {"type": "integer", "description": "How many events (1-50)."},
            "q": {"type": "string", "description": "Free-text filter."},
        },
        query_params=("timeMin", "timeMax", "maxResults", "q"),
        query_defaults={"singleEvents": "true", "orderBy": "startTime", "maxResults": 10},
        fields=("id", "summary", "start", "end", "location", "htmlLink", "status"),
        prepare=_events_prepare,
    ),
    NangoSpec(
        name="calendar_create_event",
        toolkit="googlecalendar",
        description="Create an event on the primary Google Calendar.",
        method="POST",
        path="/calendar/v3/calendars/primary/events",
        properties={
            "summary": {"type": "string", "description": "Event title."},
            "start": {
                "type": "string",
                "description": "RFC3339 start time. Include an offset or also pass time_zone.",
            },
            "end": {"type": "string", "description": "RFC3339 end time."},
            "time_zone": {
                "type": "string",
                "description": "IANA zone, for example Asia/Kathmandu.",
            },
            "description": {"type": "string"},
            "location": {"type": "string"},
            "attendees": {"type": "string", "description": "Comma-separated email addresses."},
        },
        required=("summary", "start", "end"),
        build_body=_event_body,
        fields=("id", "summary", "htmlLink", "start", "end"),
    ),
    # Slack
    NangoSpec(
        name="slack_list_channels",
        toolkit="slack",
        description="List Slack channels (id, name, privacy). Use it to find a channel id.",
        method="GET",
        path="/conversations.list",
        properties={
            "limit": {"type": "integer", "description": "How many channels (1-200)."},
            "types": {
                "type": "string",
                "description": "Comma-separated: public_channel, private_channel, im, mpim.",
            },
        },
        query_params=("limit", "types"),
        query_defaults={
            "limit": 50,
            "types": "public_channel,private_channel",
            "exclude_archived": "true",
        },
        fields=("id", "name", "is_private", "is_member", "num_members"),
        list_key="channels",
    ),
    NangoSpec(
        name="slack_channel_history",
        toolkit="slack",
        description="Read the latest messages of a Slack channel by channel id.",
        method="GET",
        path="/conversations.history",
        properties={
            "channel": {"type": "string", "description": "Channel id such as C0123456789."},
            "limit": {"type": "integer", "description": "How many messages (1-100)."},
        },
        required=("channel",),
        query_params=("channel", "limit"),
        query_defaults={"limit": 10},
        fields=("ts", "user", "text", "thread_ts", "reply_count"),
        list_key="messages",
    ),
    NangoSpec(
        name="slack_post_message",
        toolkit="slack",
        description="Post a message to a Slack channel by channel id.",
        method="POST",
        path="/chat.postMessage",
        properties={
            "channel": {"type": "string", "description": "Channel id such as C0123456789."},
            "text": {"type": "string", "description": "Message text."},
        },
        required=("channel", "text"),
        body_params=("channel", "text"),
        fields=("channel", "ts"),
    ),
)


def _describe(spec: NangoSpec, args: dict[str, Any]) -> str:
    lines = [f"Run {spec.name}"]
    lines.extend(f"- {key}: {str(value)[:300]}" for key, value in args.items())
    return "\n".join(lines)


class NangoProvider:
    name = "nango"

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._base = settings.nango_base_url.rstrip("/")
        self._key = settings.nango_secret_key.get_secret_value()
        self._cache: tuple[float, list[dict[str, str]]] | None = None

    async def _connections(self) -> list[dict[str, str]]:
        now = time.monotonic()
        if self._cache is not None and now - self._cache[0] < CONNECTION_TTL_SECONDS:
            return self._cache[1]
        response = await self._http.get(
            f"{self._base}/connection", headers={"Authorization": f"Bearer {self._key}"}
        )
        response.raise_for_status()
        connections: list[dict[str, str]] = []
        for item in response.json().get("connections", []):
            connection_id = item.get("connection_id")
            config_key = item.get("provider_config_key")
            if connection_id and config_key:
                connections.append(
                    {
                        "connection_id": str(connection_id),
                        "provider_config_key": str(config_key),
                        "provider": str(item.get("provider") or config_key),
                    }
                )
        self._cache = (now, connections)
        return connections

    async def _connection(self, toolkit: str) -> dict[str, str] | None:
        provider_id = PROVIDERS[toolkit]
        try:
            connections = await self._connections()
        except Exception:
            log.warning("Could not list Nango connections", exc_info=True)
            if self._s.nango_connection_id:
                return {
                    "connection_id": self._s.nango_connection_id,
                    "provider_config_key": provider_id,
                    "provider": provider_id,
                }
            return None
        matches = [
            c for c in connections if provider_id in (c["provider"], c["provider_config_key"])
        ]
        for connection in matches:
            if connection["connection_id"] == self._s.nango_connection_id:
                return connection
        return matches[0] if matches else None

    async def toolkits(self) -> list[str]:
        try:
            connections = await self._connections()
        except Exception:
            log.warning("Could not list Nango connections", exc_info=True)
            return []
        return [
            toolkit
            for toolkit, provider_id in PROVIDERS.items()
            if any(provider_id in (c["provider"], c["provider_config_key"]) for c in connections)
        ]

    async def load(self, toolkit: str) -> list[Tool]:
        return [self._tool(spec) for spec in SPECS if spec.toolkit == toolkit]

    def _tool(self, spec: NangoSpec) -> Tool:
        async def handler(args: dict[str, Any], ctx: ToolContext) -> Any:
            return await self._call(spec, args)

        writes = spec.method != "GET"
        return Tool(
            name=spec.name,
            description=spec.description,
            parameters=clean_parameters(
                {
                    "type": "object",
                    "properties": spec.properties,
                    "required": list(spec.required),
                }
            ),
            handler=handler,
            needs_approval=lambda _args: writes,
            describe=lambda args: _describe(spec, args),
        )

    async def _call(self, spec: NangoSpec, args: dict[str, Any]) -> Any:
        connection = await self._connection(spec.toolkit)
        if connection is None:
            return {"error": f"No Nango connection found for {PROVIDERS[spec.toolkit]}."}

        args = {key: value for key, value in args.items() if value is not None}
        if spec.prepare is not None:
            args = spec.prepare(args)
        missing = [key for key in spec.required if key not in args]
        if missing:
            return {"error": f"Missing required arguments: {', '.join(missing)}"}

        path = spec.path.format(**{key: quote(str(args[key]), safe="") for key in spec.path_params})
        params = {**spec.query_defaults, **{k: args[k] for k in spec.query_params if k in args}}
        body: dict[str, Any] | None = None
        if spec.build_body is not None:
            body = spec.build_body(args)
        elif spec.body_params:
            body = {key: args[key] for key in spec.body_params if key in args}

        response = await self._http.request(
            spec.method,
            f"{self._base}/proxy/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Connection-Id": connection["connection_id"],
                "Provider-Config-Key": connection["provider_config_key"],
            },
            params=params or None,
            json=body,
        )
        if not response.is_success:
            return {"status": response.status_code, "body": response.text[:2000]}
        try:
            data = response.json()
        except ValueError:
            return {"status": response.status_code, "body": response.text[:2000]}
        if isinstance(data, dict) and data.get("ok") is False:
            return {"error": data.get("error", "request failed")}
        if spec.shape is not None:
            return spec.shape(data)
        return _slim(data, spec.fields, spec.list_key)
