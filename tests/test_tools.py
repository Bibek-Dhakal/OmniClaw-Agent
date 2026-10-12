import asyncio

from omniclaw.approvals import ApprovalBroker
from omniclaw.tools import Tool, ToolContext, ToolRegistry


async def _log(*_args):
    return None


def _setup(handler, needs_approval):
    broker = ApprovalBroker(2)
    registry = ToolRegistry(broker, _log, approval_required=True)
    registry.register(
        Tool("act", "act", {"type": "object", "properties": {}}, handler, needs_approval)
    )
    asked = asyncio.Event()

    async def notify(_text):
        asked.set()

    return broker, registry, ToolContext("test", "1", notify), asked


async def test_rejected_action_is_not_executed():
    calls = []

    async def handler(args, ctx):
        calls.append(args)
        return {"ok": True}

    broker, registry, ctx, asked = _setup(handler, lambda _a: True)
    task = asyncio.create_task(registry.call("act", {}, ctx))
    await asked.wait()
    assert broker.resolve(ctx.key, "no") == "Rejected."
    result = await task

    assert "rejected" in result.lower()
    assert calls == []


async def test_approved_action_runs():
    async def handler(args, ctx):
        return {"ok": True}

    broker, registry, ctx, asked = _setup(handler, lambda _a: True)
    task = asyncio.create_task(registry.call("act", {}, ctx))
    await asked.wait()
    assert broker.resolve(ctx.key, "YES") == "Approved."

    assert '"ok": true' in await task


async def test_unknown_message_while_pending_is_held():
    async def handler(args, ctx):
        return {}

    broker, registry, ctx, asked = _setup(handler, lambda _a: True)
    task = asyncio.create_task(registry.call("act", {}, ctx))
    await asked.wait()
    assert "YES or NO" in broker.resolve(ctx.key, "what time is it?")
    broker.resolve(ctx.key, "no")
    await task


async def test_handler_errors_are_contained():
    async def handler(args, ctx):
        raise ValueError("boom")

    _, registry, ctx, _ = _setup(handler, lambda _a: False)
    result = await registry.call("act", {}, ctx)
    assert "ValueError" in result and "boom" in result


async def test_unknown_tool():
    _, registry, ctx, _ = _setup(lambda a, c: None, lambda _a: False)
    assert "Unknown tool" in await registry.call("missing", {}, ctx)
