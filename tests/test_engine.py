import json
from types import SimpleNamespace

from omniclaw import engine as engine_module
from omniclaw.approvals import ApprovalBroker
from omniclaw.config import EngineProfile
from omniclaw.engine import STEP_LIMIT_REPLY, AgentEngine
from omniclaw.tools import Tool, ToolContext, ToolRegistry


def _response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _call(call_id, name, args):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


async def _log(*_args):
    return None


async def _notify(_text):
    return None


def _engine(max_steps=3):
    async def echo(args, ctx):
        return {"got": args["x"]}

    registry = ToolRegistry(ApprovalBroker(1), _log, approval_required=True)
    registry.register(Tool("echo", "echo", {"type": "object", "properties": {}}, echo))
    return AgentEngine(EngineProfile("m", None, None), registry, max_steps)


async def test_engine_runs_tool_then_answers(monkeypatch):
    responses = iter(
        [_response(tool_calls=[_call("1", "echo", {"x": 1})]), _response(content="done")]
    )

    async def fake_acompletion(**_kwargs):
        return next(responses)

    monkeypatch.setattr(engine_module, "acompletion", fake_acompletion)
    messages = [{"role": "user", "content": "hi"}]
    reply = await _engine().run(messages, ToolContext("test", "1", _notify))

    assert reply == "done"
    assert messages[-1]["role"] == "tool"
    assert '"got": 1' in messages[-1]["content"]


async def test_engine_stops_at_step_limit(monkeypatch):
    async def always_tool(**_kwargs):
        return _response(tool_calls=[_call("1", "echo", {"x": 1})])

    monkeypatch.setattr(engine_module, "acompletion", always_tool)
    reply = await _engine(max_steps=2).run([], ToolContext("test", "1", _notify))
    assert reply == STEP_LIMIT_REPLY
