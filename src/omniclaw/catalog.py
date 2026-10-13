"""Tool discovery: intent routing, BM25 ranking, schema cleanup and per-request tool injection.

The model never explores blindly. Before the LLM loop starts, the catalog works out which
connected apps a message is about and injects the best matching tools, with full parameter
schemas, as real function-calling tools. If that is not enough, the model calls ``find_tools``
once and the matches become callable on the next step.
"""

import asyncio
import logging
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from omniclaw.tools import Tool, ToolContext

log = logging.getLogger(__name__)

CONNECTED_TTL_SECONDS = 300
MAX_ROUTED_TOOLKITS = 3
MAX_SEARCH_TOOLKITS = 6
MAX_SCHEMA_PROPERTIES = 30
MAX_SCHEMA_DEPTH = 4
MAX_DESCRIPTION_CHARS = 240
_BM25_K1 = 1.5
_BM25_B = 0.75

# Words that point to an app. Matching is on whole lowercase words.
TOOLKIT_HINTS: dict[str, frozenset[str]] = {
    "github": frozenset(
        {
            "github",
            "repo",
            "repos",
            "repository",
            "repositories",
            "commit",
            "commits",
            "branch",
            "branches",
            "pull",
            "pr",
            "prs",
            "issue",
            "issues",
            "gist",
        }
    ),
    "gmail": frozenset({"gmail", "email", "emails", "mail", "inbox", "unread", "draft", "drafts"}),
    "googlecalendar": frozenset(
        {"calendar", "meeting", "meetings", "event", "events", "agenda", "appointment"}
    ),
    "slack": frozenset({"slack", "channel", "channels", "dm", "dms"}),
    "linkedin": frozenset({"linkedin"}),
    "instagram": frozenset({"instagram", "insta"}),
    "notion": frozenset({"notion"}),
    "googledrive": frozenset({"drive", "gdrive"}),
    "googlesheets": frozenset({"spreadsheet", "spreadsheets", "sheet", "sheets"}),
    "twitter": frozenset({"twitter", "tweet", "tweets"}),
    "discord": frozenset({"discord"}),
    "trello": frozenset({"trello"}),
    "jira": frozenset({"jira"}),
    "linear": frozenset({"linear"}),
    "asana": frozenset({"asana"}),
}

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "for",
        "and",
        "or",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "my",
        "me",
        "i",
        "you",
        "your",
        "our",
        "please",
        "can",
        "could",
        "would",
        "do",
        "does",
        "is",
        "are",
        "was",
        "were",
        "be",
        "it",
        "this",
        "that",
        "these",
        "those",
        "all",
        "any",
        "some",
        "top",
        "most",
        "about",
        "what",
        "which",
        "show",
        "give",
        "tell",
        "then",
        "also",
        "just",
        "now",
    }
)
_SYNONYMS = {
    "repo": "repository",
    "repos": "repository",
    "mail": "email",
    "mails": "email",
    "msg": "message",
    "msgs": "message",
    "dm": "message",
    "dms": "message",
    "pr": "pull",
    "prs": "pull",
    "meeting": "event",
    "meetings": "event",
    "appointment": "event",
    "appointments": "event",
    "recent": "update",
    "recently": "update",
    "latest": "update",
    "newest": "update",
}

# Tool-name verbs. Used to demote write tools when the user's words show no write intent.
_WRITE_WORDS = frozenset(
    {
        "send",
        "create",
        "add",
        "delete",
        "remove",
        "post",
        "reply",
        "forward",
        "merge",
        "close",
        "schedule",
        "edit",
        "rename",
        "comment",
        "assign",
        "invite",
        "cancel",
        "write",
        "modify",
        "change",
        "update",
        "set",
        "upload",
        "publish",
        "move",
        "archive",
        "fork",
        "star",
    }
)
_READ_WORDS = frozenset(
    {
        "list",
        "get",
        "fetch",
        "search",
        "find",
        "read",
        "retrieve",
        "view",
        "lookup",
        "count",
        "check",
        "query",
    }
)
_WRITE_PENALTY = 0.3
_READ_BONUS = 1.25


def _stem(word: str) -> str:
    for suffix, replacement in (
        ("ies", "y"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
        ("e", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: len(word) - len(suffix)] + replacement
    return word


def tokenize(text: str) -> list[str]:
    """Lowercase, drop filler words, map synonyms and apply a crude stemmer."""
    tokens: list[str] = []
    for raw in _WORD.findall(text.lower()):
        if raw.isdigit() or raw in _STOP:
            continue
        tokens.append(_stem(_SYNONYMS.get(raw, raw)))
    return tokens


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


@dataclass(frozen=True)
class Entry:
    tool: Tool
    toolkit: str
    tokens: tuple[str, ...]


def make_entry(tool: Tool, toolkit: str) -> Entry:
    name_tokens = tokenize(tool.name)
    # The name counts double: it is the strongest signal of what a tool does.
    tokens = (*name_tokens, *name_tokens, *tokenize(tool.description), *tokenize(toolkit))
    return Entry(tool, toolkit, tokens)


def rank(query: str, entries: list[Entry], k: int) -> list[Entry]:
    """BM25 ranking. Any query word can match, so 'list repos' finds 'repositories'.

    Write tools are demoted unless the raw query contains a write verb. Raw words are checked
    (not stemmed tokens) because 'recently' is mapped to 'update' for matching purposes.
    """
    terms = set(tokenize(query))
    if not terms or not entries:
        return []
    wants_write = bool(set(_WORD.findall(query.lower())) & _WRITE_WORDS)
    total = len(entries)
    average = (sum(len(entry.tokens) for entry in entries) / total) or 1.0
    doc_freq: Counter[str] = Counter()
    for entry in entries:
        doc_freq.update(set(entry.tokens) & terms)

    scored: list[tuple[float, Entry]] = []
    for entry in entries:
        counts = Counter(entry.tokens)
        length = len(entry.tokens)
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            norm = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / average)
            score += idf * tf * (_BM25_K1 + 1) / norm
        if score > 0:
            if not wants_write:
                words = set(re.split(r"[^a-z0-9]+", entry.tool.name.lower()))
                if words & _WRITE_WORDS:
                    score *= _WRITE_PENALTY
                elif words & _READ_WORDS:
                    score *= _READ_BONUS
            scored.append((score, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:k]]


_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def clean_schema(schema: Any, depth: int = 0) -> dict[str, Any]:
    """Reduce a JSON schema to the subset every LLM provider accepts."""
    if not isinstance(schema, dict) or depth > MAX_SCHEMA_DEPTH:
        return {"type": "string"}

    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            usable = [o for o in options if isinstance(o, dict) and o.get("type") != "null"]
            if usable:
                merged = dict(usable[0])
                if schema.get("description"):
                    merged.setdefault("description", schema["description"])
                return clean_schema(merged, depth)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((t for t in kind if t != "null"), "string")
    if kind not in _SCHEMA_TYPES:
        kind = "object" if isinstance(schema.get("properties"), dict) else "string"

    cleaned: dict[str, Any] = {"type": kind}
    description = schema.get("description")
    if isinstance(description, str) and description:
        cleaned["description"] = description[:MAX_DESCRIPTION_CHARS]

    if kind == "object":
        raw_props = schema.get("properties")
        props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
        raw_required = schema.get("required")
        required = [r for r in raw_required if r in props] if isinstance(raw_required, list) else []
        names = required + [name for name in props if name not in required]
        cleaned["properties"] = {
            name: clean_schema(props[name], depth + 1) for name in names[:MAX_SCHEMA_PROPERTIES]
        }
        kept = [name for name in required if name in cleaned["properties"]]
        if kept:
            cleaned["required"] = kept
    elif kind == "array":
        cleaned["items"] = clean_schema(schema.get("items"), depth + 1)
    elif kind == "string":
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            cleaned["enum"] = [str(value) for value in enum][:50]
    return cleaned


def clean_parameters(schema: Any) -> dict[str, Any]:
    """Top-level tool parameters must always be an object schema."""
    cleaned = clean_schema(schema)
    if cleaned.get("type") != "object":
        return {"type": "object", "properties": {}}
    return cleaned


def detect_toolkits(text: str, connected: list[str]) -> list[str]:
    """Which apps does this message talk about? Keyword hints plus literal toolkit names."""
    words = set(_WORD.findall(text.lower()))
    found = [toolkit for toolkit, hints in TOOLKIT_HINTS.items() if words & hints]
    for toolkit in connected:
        if toolkit not in found and _norm(toolkit) in words:
            found.append(toolkit)
    return found


class ToolProvider(Protocol):
    """A source of tools (Composio, Nango, ...)."""

    name: str

    async def toolkits(self) -> list[str]:
        """Connected toolkits. An empty list means 'unknown', not 'none'."""
        ...

    async def load(self, toolkit: str) -> list[Tool]:
        """All tools of a toolkit, or an empty list when the toolkit is unsupported."""
        ...


@dataclass
class Route:
    connected: list[str] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)


class ToolCatalog:
    def __init__(
        self, providers: list[ToolProvider], ttl_seconds: int = 3600, top_k: int = 8
    ) -> None:
        self._providers = providers
        self._ttl = ttl_seconds
        self._top_k = top_k
        self._tool_cache: dict[tuple[str, str], tuple[float, list[Entry]]] = {}
        self._connected: tuple[float, list[str]] | None = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._providers)

    async def connected(self) -> list[str]:
        now = time.monotonic()
        if self._connected is not None and now - self._connected[0] < CONNECTED_TTL_SECONDS:
            return self._connected[1]
        names: list[str] = []
        for provider in self._providers:
            try:
                for name in await provider.toolkits():
                    if name not in names:
                        names.append(name)
            except Exception:
                log.warning("Could not list connected apps for %s", provider.name, exc_info=True)
        self._connected = (now, names)
        return names

    async def _entries(self, toolkit: str) -> list[Entry]:
        entries: list[Entry] = []
        for provider in self._providers:
            key = (provider.name, toolkit)
            async with self._lock:
                cached = self._tool_cache.get(key)
                if cached is None or time.monotonic() - cached[0] > self._ttl:
                    try:
                        tools = await provider.load(toolkit)
                    except Exception:
                        log.warning(
                            "Could not load %s tools from %s", toolkit, provider.name, exc_info=True
                        )
                        continue
                    cached = (time.monotonic(), [make_entry(tool, toolkit) for tool in tools])
                    self._tool_cache[key] = cached
            entries.extend(cached[1])
        return entries

    @staticmethod
    def _inject(ctx: ToolContext, entries: list[Entry]) -> list[str]:
        names: list[str] = []
        for entry in entries:
            ctx.dynamic.setdefault(entry.tool.name, entry.tool)
            names.append(entry.tool.name)
        return names

    async def route(self, text: str, ctx: ToolContext, previous: str = "") -> Route:
        """Load the best tools for this message before the LLM loop starts. Never raises."""
        if not self._providers:
            return Route()
        connected = await self.connected()
        loaded: list[str] = []
        try:
            toolkits = detect_toolkits(text, connected)
            query = text
            if not toolkits and previous:
                # Short follow-ups ("and the last 5?") inherit the app from the previous message.
                toolkits = detect_toolkits(previous, connected)
                query = f"{previous} {text}"
            if connected:
                toolkits = [toolkit for toolkit in toolkits if toolkit in connected]
            for toolkit in toolkits[:MAX_ROUTED_TOOLKITS]:
                entries = await self._entries(toolkit)
                picked = rank(query, entries, self._top_k)
                if not picked and 0 < len(entries) <= self._top_k:
                    picked = entries
                loaded.extend(self._inject(ctx, picked))
        except Exception:
            log.warning("Tool routing failed", exc_info=True)
        log.info("Routed %s -> %s", ctx.key, loaded or "no tools")
        return Route(connected, loaded)

    async def search(self, query: str, toolkit: str | None, ctx: ToolContext) -> dict[str, Any]:
        """Backs the find_tools tool: rank, inject, and report what was loaded."""
        connected = await self.connected()
        if toolkit:
            wanted = _norm(str(toolkit))
            scope = [
                next((c for c in connected if _norm(c) == wanted), str(toolkit).strip().lower())
            ]
        else:
            scope = [
                t for t in detect_toolkits(query, connected) if not connected or t in connected
            ]
            scope = scope or connected[:MAX_SEARCH_TOOLKITS]
        if not scope:
            return {
                "error": "Connected apps are unknown. Pass the toolkit argument, "
                "for example github, gmail, googlecalendar or slack."
            }
        entries: list[Entry] = []
        for name in scope[:MAX_SEARCH_TOOLKITS]:
            entries.extend(await self._entries(name))
        picked = rank(query, entries, self._top_k)
        if not picked:
            return {
                "error": f"No tools matched '{query}'. Try different keywords.",
                "searched": scope,
            }
        self._inject(ctx, picked)
        return {
            "loaded": [
                {"name": entry.tool.name, "description": entry.tool.description[:160]}
                for entry in picked
            ],
            "note": "These tools are now available. Call the right one directly by name.",
        }

    def find_tools_tool(self) -> Tool:
        async def handler(args: dict[str, Any], ctx: ToolContext) -> Any:
            toolkit = args.get("toolkit")
            return await self.search(str(args.get("query", "")), toolkit or None, ctx)

        return Tool(
            name="find_tools",
            description=(
                "Find tools for a goal when none of the loaded tools fits. Describe the goal in "
                "plain words, for example 'list my most recently updated repositories'. Matching "
                "tools are loaded with their full schemas and can be called directly on the next "
                "step. Call it at most once or twice per request."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you want to do."},
                    "toolkit": {
                        "type": "string",
                        "description": "Optional app, for example github, gmail, googlecalendar.",
                    },
                },
                "required": ["query"],
            },
            handler=handler,
        )
