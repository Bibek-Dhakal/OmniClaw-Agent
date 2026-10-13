from omniclaw.approvals import ApprovalBroker
from omniclaw.catalog import (
    ToolCatalog,
    clean_parameters,
    detect_toolkits,
    make_entry,
    rank,
    tokenize,
)
from omniclaw.config import Settings
from omniclaw.connectors import composio_needs_approval
from omniclaw.nango_tools import NangoProvider
from omniclaw.tools import Tool, ToolContext, ToolRegistry


async def _notify(_text):
    return None


async def _log(*_args):
    return None


def _tool(name, description):
    async def handler(args, ctx):
        return {}

    return Tool(name, description, {"type": "object", "properties": {}}, handler)


class FakeProvider:
    name = "fake"

    def __init__(self, tools, connected):
        self._tools = tools
        self._connected = connected

    async def toolkits(self):
        return self._connected

    async def load(self, toolkit):
        return self._tools.get(toolkit, [])


def test_tokenize_maps_synonyms_and_stems():
    tokens = tokenize("List my most recently updated repos")
    assert "repository" in tokens
    assert "updat" in tokens
    assert "my" not in tokens


def test_rank_prefers_matching_tool():
    entries = [
        make_entry(
            _tool("github_list_my_repos", "List repositories of the user, sorted by updated"),
            "github",
        ),
        make_entry(_tool("github_create_issue", "Create an issue in a repository"), "github"),
        make_entry(_tool("gmail_send_message", "Send an email"), "gmail"),
    ]
    best = rank("list my most recently updated repos", entries, 2)
    assert best[0].tool.name == "github_list_my_repos"
    assert all(entry.tool.name != "gmail_send_message" for entry in best)


def test_clean_parameters_simplifies_schema():
    schema = {
        "type": "object",
        "title": "Args",
        "additionalProperties": False,
        "properties": {
            "a": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "d"},
            "b": {"type": ["string", "null"], "default": "x"},
        },
        "required": ["a", "missing"],
    }
    cleaned = clean_parameters(schema)
    assert cleaned["properties"]["a"]["type"] == "integer"
    assert cleaned["properties"]["b"]["type"] == "string"
    assert cleaned["required"] == ["a"]
    assert "title" not in cleaned
    assert "additionalProperties" not in cleaned


def test_clean_parameters_always_returns_object():
    assert clean_parameters(None) == {"type": "object", "properties": {}}


def test_detect_toolkits():
    assert detect_toolkits("list top 3 recently updated repos", ["github", "gmail"]) == ["github"]
    assert detect_toolkits("email my notes and add it to the calendar", []) == [
        "gmail",
        "googlecalendar",
    ]
    assert detect_toolkits("just chat", []) == []


def test_composio_write_verbs_need_approval():
    assert composio_needs_approval({"tool_slug": "GITHUB_CREATE_AN_ISSUE"})
    assert not composio_needs_approval(
        {"tool_slug": "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER"}
    )
    assert not composio_needs_approval({"tool_slug": "GMAIL_FETCH_EMAILS"})
    assert composio_needs_approval({"tool_slug": "SOMETHING_UNKNOWN"})


async def test_route_injects_ranked_tools():
    provider = FakeProvider(
        {
            "github": [
                _tool("github_list_my_repos", "List repositories sorted by updated"),
                _tool("github_create_issue", "Create an issue"),
            ]
        },
        ["github"],
    )
    catalog = ToolCatalog([provider], ttl_seconds=60, top_k=1)
    ctx = ToolContext("test", "1", _notify)
    route = await catalog.route("list my most recently updated repos", ctx)

    assert route.connected == ["github"]
    assert list(ctx.dynamic) == ["github_list_my_repos"]


async def test_route_skips_chat_only_messages():
    provider = FakeProvider({"github": [_tool("github_list_my_repos", "List repos")]}, ["github"])
    catalog = ToolCatalog([provider])
    ctx = ToolContext("test", "1", _notify)
    await catalog.route("hi, tell me a joke", ctx)
    assert ctx.dynamic == {}


async def test_find_tools_loads_matches_for_next_step():
    provider = FakeProvider(
        {
            "gmail": [_tool("gmail_send_message", "Send an email message")],
            "github": [_tool("github_list_my_repos", "List repositories")],
        },
        ["gmail", "github"],
    )
    catalog = ToolCatalog([provider])
    ctx = ToolContext("test", "1", _notify)
    result = await catalog.search("send an email", None, ctx)

    assert result["loaded"][0]["name"] == "gmail_send_message"
    assert "gmail_send_message" in ctx.dynamic


async def test_registry_exposes_and_calls_dynamic_tools():
    async def handler(args, ctx):
        return {"ok": args["x"]}

    registry = ToolRegistry(ApprovalBroker(1), _log, approval_required=True)
    ctx = ToolContext("test", "1", _notify)
    ctx.dynamic["dyn"] = Tool("dyn", "d", {"type": "object", "properties": {}}, handler)

    assert [spec["function"]["name"] for spec in registry.specs(ctx)] == ["dyn"]
    assert registry.specs() == []
    assert '"ok": 2' in await registry.call("dyn", {"x": 2}, ctx)


async def test_nango_catalog_exposes_curated_tools():
    settings = Settings(_env_file=None, nango_secret_key="key")
    provider = NangoProvider(settings, None)
    tools = await provider.load("github")

    assert "github_list_my_repos" in {tool.name for tool in tools}
    assert all(tool.parameters["type"] == "object" for tool in tools)
    assert await provider.load("unknown") == []


def test_rank_demotes_write_tools_for_read_queries():
    entries = [
        make_entry(_tool("GITHUB_UPDATE_A_REPOSITORY", "Update a repository"), "github"),
        make_entry(
            _tool(
                "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
                "List repositories for the authenticated user",
            ),
            "github",
        ),
    ]
    best = rank("list my most recently updated repos", entries, 2)
    assert best[0].tool.name == "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER"


def test_rank_keeps_write_tools_for_write_queries():
    entries = [
        make_entry(_tool("github_create_issue", "Create an issue"), "github"),
        make_entry(_tool("github_list_issues", "List issues"), "github"),
    ]
    assert rank("create an issue", entries, 1)[0].tool.name == "github_create_issue"
